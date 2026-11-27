import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any, Final, Optional

import httpx
import pytest

from app.core.enums import TransactionStatus
from app.core.exceptions import PaymentGatewayError
from app.modules.transactions.gateways.base import PaymentHttpClient, WebhookSignal
from app.modules.transactions.gateways.coinspay import CoinsPayGateway
from tests.modules.transactions.gateways.support import (
    NO_HTTP,
    ORDER_REF,
    PAYMENT_TEXT,
    RETURN_URL,
    WEBHOOK_URL,
    HttpRecorder,
    json_response,
    make_order,
    webhook,
)

_SECRET: Final[str] = "whsec_test"
_SETTINGS: Final[dict[str, str]] = {"api_key": "cpk_live_key", "webhook_secret": _SECRET}
_TEST_SETTINGS: Final[dict[str, str]] = {"api_key": "cpk_test_key", "webhook_secret": _SECRET}
_SIGNAL: Final[WebhookSignal] = WebhookSignal(
    reference=ORDER_REF, claims_paid=True, provider_payment_id="inv_1"
)


def _gateway(
    http: PaymentHttpClient = NO_HTTP, settings: Optional[dict[str, str]] = None
) -> CoinsPayGateway:
    return CoinsPayGateway(
        settings=settings or _SETTINGS, webhook_url=WEBHOOK_URL, return_url=RETURN_URL, http=http
    )


def _invoice(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "inv_1",
        "test": False,
        "status": "paid",
        "currency": "RUB",
        "amount": "500",
        "amount_paid": "500",
        "reference": ORDER_REF,
        "pay_url": "https://coinspay.app/pay/abc",
        **overrides,
    }


def _event(event_type: str = "invoice.paid", **invoice: Any) -> bytes:
    data = {"invoice": _invoice(**invoice)}
    return json.dumps({"id": "evt_1", "type": event_type, "test": False, "data": data}).encode()


def _signature(body: bytes, *, at: Optional[int] = None, secret: str = _SECRET) -> str:
    timestamp = int(time.time()) if at is None else at
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


def _signed(body: bytes) -> dict[str, str]:
    return {"X-CPay-Signature": _signature(body)}


async def test_create_sends_order_terms_and_returns_payment_page() -> None:
    http = HttpRecorder(json_response({"invoice": _invoice(status="open")}, 201))
    intent = await _gateway(http.client).create_payment(make_order(), PAYMENT_TEXT)
    assert intent.confirmation_url == "https://coinspay.app/pay/abc"
    assert intent.provider_payment_id == "inv_1"
    assert http.last.method == "POST"
    assert http.last.url == "https://coinspay.app/api/v1/invoices"
    assert http.last.headers["authorization"] == "Bearer cpk_live_key"
    assert http.last.headers["idempotency-key"] == ORDER_REF
    assert "Remnashop" in http.last.headers["user-agent"]
    body = http.last_json()
    assert body["currency"] == "RUB"
    assert body["amount"] == "500.00"
    assert body["reference"] == ORDER_REF
    assert body["title"] == PAYMENT_TEXT.title
    assert body["description"] == PAYMENT_TEXT.localized_description
    assert body["return_url"] == RETURN_URL
    assert 15 <= body["lifetime_minutes"] <= 43200


@pytest.mark.parametrize(
    "overrides",
    [
        {"reference": "another-order"},
        {"amount": "499.99"},
        {"currency": "USD"},
        {"pay_url": "http://unsafe"},
        {"pay_url": None},
        {"id": None},
    ],
)
async def test_create_rejects_conflicting_invoice(overrides: dict[str, Any]) -> None:
    http = HttpRecorder(json_response({"invoice": _invoice(status="open", **overrides)}, 201))
    with pytest.raises(PaymentGatewayError):
        await _gateway(http.client).create_payment(make_order(), PAYMENT_TEXT)


async def test_create_fails_on_missing_invoice() -> None:
    http = HttpRecorder(json_response({"error": {"code": "VALIDATION_ERROR"}}))
    with pytest.raises(PaymentGatewayError):
        await _gateway(http.client).create_payment(make_order(), PAYMENT_TEXT)


async def test_test_key_refuses_customer_orders_without_a_call() -> None:
    with pytest.raises(PaymentGatewayError):
        await _gateway(settings=_TEST_SETTINGS).create_payment(make_order(), PAYMENT_TEXT)


async def test_test_key_serves_dashboard_test_payment() -> None:
    http = HttpRecorder(json_response({"invoice": _invoice(status="open", test=True)}, 201))
    gateway = _gateway(http.client, _TEST_SETTINGS)
    intent = await gateway.create_payment(make_order(is_test=True), PAYMENT_TEXT)
    assert intent.provider_payment_id == "inv_1"


async def test_paid_webhook_is_signed_and_parsed() -> None:
    body = _event()
    signal = await _gateway().parse_webhook(webhook(body, _signed(body)))
    assert signal == WebhookSignal(
        reference=ORDER_REF, claims_paid=True, provider_payment_id="inv_1"
    )


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "garbage",
        "t=1,v1=" + "0" * 64,
        "v1=" + "0" * 64,
        "t=1700000000",
        "t=abc,v1=" + "0" * 64,
        "t=" + "9" * 20 + ",v1=" + "0" * 64,
    ],
)
async def test_bad_signature_header_refused(header: Optional[str]) -> None:
    headers = {} if header is None else {"X-CPay-Signature": header}
    with pytest.raises(PaymentGatewayError):
        await _gateway().parse_webhook(webhook(_event(), headers))


async def test_signature_binds_body_secret_and_time() -> None:
    body = _event()
    tampered = _event(amount="1")
    stale = _signature(body, at=int(time.time()) - 301)
    for request in (
        webhook(tampered, _signed(body)),
        webhook(body, {"X-CPay-Signature": _signature(body, secret="whsec_other")}),
        webhook(body, {"X-CPay-Signature": stale}),
    ):
        with pytest.raises(PaymentGatewayError):
            await _gateway().parse_webhook(request)


async def test_signature_accepts_any_matching_v1() -> None:
    body = _event()
    header = _signature(body) + ",v1=" + "0" * 64
    assert await _gateway().parse_webhook(webhook(body, {"X-CPay-Signature": header}))


@pytest.mark.parametrize(
    "event_type", ["invoice.partially_paid", "payment.confirmed", "payout.failed", "webhook.test"]
)
async def test_other_events_are_acknowledged_without_a_signal(event_type: str) -> None:
    body = _event(event_type)
    assert await _gateway().parse_webhook(webhook(body, _signed(body))) is None


async def test_invoice_without_reference_is_not_ours() -> None:
    body = _event(reference=None)
    assert await _gateway().parse_webhook(webhook(body, _signed(body))) is None


async def test_invoice_event_without_invoice_refused() -> None:
    body = json.dumps({"type": "invoice.paid", "data": {}}).encode()
    with pytest.raises(PaymentGatewayError):
        await _gateway().parse_webhook(webhook(body, _signed(body)))


async def test_confirm_reads_invoice_from_api() -> None:
    http = HttpRecorder(json_response({"invoice": _invoice()}))
    payment = await _gateway(http.client).confirm(make_order(), _SIGNAL)
    assert payment is not None and payment.provider_payment_id == "inv_1"
    assert payment.amount == Decimal("500")
    assert http.last.method == "GET"
    assert http.last.url == "https://coinspay.app/api/v1/invoices/inv_1"
    assert http.last.headers["authorization"] == "Bearer cpk_live_key"


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "open"},
        {"status": "expired"},
        {"status": "cancelled"},
        {"amount": "499.99"},
        {"amount": None},
        {"amount": "NaN"},
        {"currency": "USD"},
        {"currency": None},
        {"reference": "another-order"},
        {"reference": None},
        {"id": "inv_2"},
        {"id": None},
        {"test": True},
        {"test": None},
    ],
)
async def test_confirm_refuses_unverified_payment(overrides: dict[str, Any]) -> None:
    http = HttpRecorder(json_response({"invoice": _invoice(**overrides)}))
    assert await _gateway(http.client).confirm(make_order(), _SIGNAL) is None


async def test_confirm_takes_test_invoice_for_dashboard_test_payment() -> None:
    http = HttpRecorder(json_response({"invoice": _invoice(test=True)}))
    order = make_order(is_test=True)
    assert await _gateway(http.client, _TEST_SETTINGS).confirm(order, _SIGNAL) is not None


async def test_confirm_refuses_signal_for_another_invoice() -> None:
    order = make_order(external_payment_id="inv_2")
    assert await _gateway().confirm(order, _SIGNAL) is None


def _route(listed: list[dict[str, Any]], invoice: dict[str, Any]) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/invoices":
            return httpx.Response(200, json={"invoices": listed})
        return httpx.Response(200, json={"invoice": invoice})

    return respond


async def test_check_without_payment_id_finds_invoice_by_reference() -> None:
    http = HttpRecorder(_route([{"id": "inv_1"}], _invoice()))
    assert await _gateway(http.client).check_payment(make_order()) is not None
    listing = http.requests[0]
    assert listing.url.path == "/api/v1/invoices"
    assert listing.url.params["reference"] == ORDER_REF
    assert http.last.url.path == "/api/v1/invoices/inv_1"


@pytest.mark.parametrize("listed", [[], [{"id": "inv_1"}, {"id": "inv_2"}], [{"id": None}]])
async def test_check_by_reference_needs_exactly_one_invoice(listed: list[dict[str, Any]]) -> None:
    http = HttpRecorder(_route(listed, _invoice()))
    assert await _gateway(http.client).check_payment(make_order()) is None
    assert len(http.requests) == 1


@pytest.mark.parametrize(
    ("event_type", "amount_paid", "reported"),
    [
        ("invoice.expired", "0", TransactionStatus.CANCELED),
        ("invoice.cancelled", "0", TransactionStatus.CANCELED),
        ("invoice.expired", "120.5", TransactionStatus.FAILED),
    ],
)
async def test_closed_invoice_rechecked(
    event_type: str, amount_paid: str, reported: TransactionStatus
) -> None:
    status = "cancelled" if event_type == "invoice.cancelled" else "expired"
    body = _event(event_type, status=status, amount_paid=amount_paid)
    http = HttpRecorder(
        json_response({"invoice": _invoice(status=status, amount_paid=amount_paid)})
    )
    gateway = _gateway(http.client)
    signal = await gateway.parse_webhook(webhook(body, _signed(body)))
    assert signal is not None and not signal.claims_paid and signal.reported_status == reported
    assert await gateway.confirm_reported(make_order(), signal) == signal
    paid_since = _gateway(HttpRecorder(json_response({"invoice": _invoice()})).client)
    assert await paid_since.confirm_reported(make_order(), signal) is None


async def test_provider_error_propagates() -> None:
    http = HttpRecorder(json_response({"error": {"code": "NOT_FOUND"}}, 404))
    with pytest.raises(httpx.HTTPStatusError):
        await _gateway(http.client).confirm(make_order(), _SIGNAL)
