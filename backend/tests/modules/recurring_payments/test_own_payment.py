from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import update

import app.modules.recurring_payments.usecases.get_own_recurring_payment as own_module
from app.core.db.models import RecurringConsent, RecurringPayment
from app.core.enums import (
    PaymentGatewayType,
    PurchaseChannel,
)
from app.core.exceptions import ValidationError
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.dto import (
    SetRecurringPaymentDto,
)
from app.modules.recurring_payments.usecases import (
    GetOwnRecurringPaymentUseCase,
)
from app.modules.users.dto import CreateUserDto
from tests.fakes.recurring import ShippedRecurringTermsTexts
from tests.modules.recurring_payments.harness import (
    notice_types,
    set_recurring_timings,
    tick_again,
)


async def test_customer_can_disable_and_enable_auto_renew(case, uow) -> None:
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    await case.worker.system()
    assert not case.provider.posts
    assert (await case.get_state(case.user, case.subscription.id)).customer_disabled
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id,
            enabled=True,
            terms_id=(await case.get_state(case.user, case.subscription.id)).terms.terms_id,
            channel=PurchaseChannel.CABINET,
        ),
    )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1


async def test_other_customers_cannot_read_or_disable_auto_renew(case, user_repository) -> None:
    other = await user_repository.create(CreateUserDto(name="other", telegram_id=931002))
    with pytest.raises(ValidationError):
        await case.get_state(other, case.subscription.id)
    with pytest.raises(ValidationError):
        await case.set_state(
            other,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
            ),
        )
    assert (await case.get_state(case.user, case.subscription.id)).enabled


async def test_customer_can_withdraw_after_the_shop_switched_auto_renewal_off(
    case, gateway_repository, session, uow
) -> None:
    async with uow:
        await gateway_repository.update_settings(
            PaymentGatewayType.YOOKASSA, {"payment_mode": "single"}
        )
    consent_id = (await case.repository.get(case.subscription.id)).consent_id
    state = await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    assert state.customer_disabled and not state.enabled
    assert (await session.get(RecurringConsent, consent_id)).revoked_at is not None


@pytest.mark.usefixtures("production_session_mode")
async def test_withdrawal_while_pending_survives_decline_and_can_be_reenabled(case, session, uow):
    case.provider.status = "pending"
    await case.worker.system()
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "insufficient_funds"
    await tick_again(case, uow)
    state = await case.get_state(case.user, case.subscription.id)
    assert state.customer_disabled and state.available and state.last_error == "customer_disabled"
    assert not await notice_types(session)
    enabled = await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id,
            enabled=True,
            terms_id=state.terms.terms_id,
            channel=PurchaseChannel.CABINET,
        ),
    )
    assert enabled.enabled
    assert len(case.provider.posts) == 1


async def test_customer_state_distinguishes_a_pause_from_withdrawing_consent(case, uow):
    async with uow:
        await case.lifecycle.pause(case.subscription.id, "price_changed")
    state = await case.get_state(case.user, case.subscription.id)
    assert state.enabled and state.paused and not state.available
    assert not state.retrying and state.next_payment_at is None
    assert not state.customer_disabled


async def test_customer_state_uses_the_actual_scheduled_retry(case, session, uow):
    scheduled = datetime_now() + timedelta(hours=3)
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(
                first_failure_at=datetime_now(),
                retry_count=1,
                last_error="insufficient_funds",
                next_attempt_at=scheduled,
            )
        )
    state = await case.get_state(case.user, case.subscription.id)
    assert state.enabled and state.available and state.retrying and not state.paused
    assert state.next_retry_at == state.next_payment_at == scheduled


async def test_customer_state_keeps_the_accepted_lead_time_after_configuration_changes(case):
    before = await case.get_state(case.user, case.subscription.id)
    await set_recurring_timings(case, lead_minutes=60)
    after = await case.get_state(case.user, case.subscription.id)
    assert after.next_payment_at == before.next_payment_at
    assert after.accepted_terms.lead_minutes != 60


@pytest.mark.parametrize(
    "reason", ["payment_status_unknown", "pending_timeout", "permission_revoked"]
)
async def test_customer_cannot_restart_an_unsafe_payment_from_the_card(case, session, uow, reason):
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(last_error=reason, enabled=True)
        )
    state = await case.get_state(case.user, case.subscription.id)
    assert state.enabled and state.paused and not state.available
    if reason == "pending_timeout" and state.payment_pending:
        assert state.next_retry_at is not None
    else:
        assert state.next_retry_at is None and state.next_payment_at is None
    with pytest.raises(ValidationError):
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=True, channel=PurchaseChannel.CABINET
            ),
        )


async def test_state_skips_the_lookup_in_a_shop_without_auto_renewal(uow, monkeypatch) -> None:
    monkeypatch.setattr(own_module, "get_owned_target", AsyncMock())
    recurring = MagicMock(get=AsyncMock(return_value=None), consent_terms=AsyncMock())
    transactions = MagicMock(get_by_id=AsyncMock())
    gateways = MagicMock(
        get_by_type=AsyncMock(return_value=MagicMock(flags={"recurring_enabled": False})),
        get_raw_settings=AsyncMock(),
    )
    use_case = GetOwnRecurringPaymentUseCase(
        recurring, transactions, MagicMock(), gateways, uow, ShippedRecurringTermsTexts()
    )
    state = await use_case.system(7)
    assert not state.enabled and not state.available and not state.can_disable
    gateways.get_raw_settings.assert_not_awaited()
    recurring.consent_terms.assert_not_awaited()
