import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.enums import Locale, PaymentGatewayType
from app.core.exceptions import PermissionDeniedError
from app.modules.gateways.api.schemas import UpdateGatewayPresentationRequest
from app.modules.gateways.dto import UpdateGatewayPresentationDto
from app.modules.gateways.presentation import GatewayText, gateway_text
from app.modules.gateways.usecases import UpdateGatewayPresentationUseCase
from tests.fakes.events import RecordingEventPublisher
from tests.modules.gateways.test_usecases import OWNER, REGULAR_USER


def test_text_validation_and_legacy_fallback():
    data = UpdateGatewayPresentationRequest.model_validate(
        {"presentation": {"ru": {"name": "  Карта\nили СБП ", "description": " <b>Оплата</b> "}}}
    )
    assert data.presentation[Locale.RU].name == "Карта или СБП"
    assert data.presentation[Locale.RU].description == "<b>Оплата</b>"
    assert gateway_text({}, Locale.RU) == GatewayText()
    assert gateway_text({Locale.EN: GatewayText(name="Crypto")}, Locale.RU).name == "Crypto"
    for value in ({"ru": {"name": "x" * 65}}, {"ru": {"description": "x" * 161}}, {"UNKNOWN": {}}):
        with pytest.raises(ValidationError):
            UpdateGatewayPresentationRequest(presentation=value)


async def test_presentation_is_persisted_audited_and_reset_without_changing_payment_settings(
    gateway_repository, uow
):
    kind = PaymentGatewayType.YOOKASSA
    async with uow:
        await gateway_repository.update_settings(kind, {"shop_id": "42", "api_key": "test-only"})
        before = await gateway_repository.set_active(kind, True)
    publisher = RecordingEventPublisher()
    update = UpdateGatewayPresentationUseCase(gateway_repository, publisher, uow)
    result = await update(
        OWNER,
        UpdateGatewayPresentationDto(
            type=kind,
            presentation={Locale.RU: GatewayText(name="Карта или СБП", description="Через ЮKassa")},
            client_ip="127.0.0.1",
        ),
    )
    assert result.is_active == before.is_active
    assert result.telegram_enabled == before.telegram_enabled
    assert result.cabinet_enabled == before.cabinet_enabled
    async with uow:
        gateway_repository.session.expire_all()
        stored = await gateway_repository.get_by_type(kind)
        assert stored.presentation == result.presentation
        assert await gateway_repository.get_raw_settings(kind) == {
            "shop_id": "42",
            "api_key": "test-only",
        }
    event = publisher.events[0]
    assert event.changed_fields == ["presentation"]
    assert event.ip_address == "127.0.0.1"
    assert "test-only" not in repr(event)
    reset = await update(
        OWNER, UpdateGatewayPresentationDto(type=kind, presentation={}, client_ip=None)
    )
    assert reset.presentation == {}
    assert reset.is_active


async def test_presentation_permission_and_unconfigured_gateway(gateway_repository, uow):
    update = UpdateGatewayPresentationUseCase(gateway_repository, RecordingEventPublisher(), uow)
    data = UpdateGatewayPresentationDto(
        type=PaymentGatewayType.PAY_2328,
        presentation={Locale.EN: GatewayText(name="Crypto")},
        client_ip=None,
    )
    with pytest.raises(PermissionDeniedError):
        await update(REGULAR_USER, data)
    result = await update(OWNER, data)
    assert result.presentation[Locale.EN].name == "Crypto"
    assert not result.is_active
    assert not result.is_configured


def test_all_gateway_suggestions_have_both_locales_and_fit_fields():
    root = Path(__file__).resolve().parents[4]
    expected = {kind.value for kind in PaymentGatewayType}
    for locale in ("ru", "en"):
        path = root / "frontend/src/shared/i18n/locales" / f"{locale}.json"
        suggestions = json.loads(path.read_text(encoding="utf-8"))["settings"]["gateways"][
            "suggestions"
        ]
        assert set(suggestions) == expected
        for text in suggestions.values():
            assert text["name"] and text["description"]
            UpdateGatewayPresentationRequest(presentation={locale: text})
