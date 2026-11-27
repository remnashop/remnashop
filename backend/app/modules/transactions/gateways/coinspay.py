from typing import Any, Final, Optional
from urllib.parse import quote

import httpx

from app.core.enums import Currency, TransactionStatus
from app.core.exceptions import PaymentGatewayError
from app.core.utils.time import datetime_now
from app.modules.gateways import CoinsPaySettings
from app.modules.transactions.dto import PaymentTextDto, TransactionDto, WebhookRequest
from app.modules.transactions.gateways.base import (
    NOT_PAID,
    PaymentGateway,
    PaymentIntent,
    ProviderPayment,
    WebhookSignal,
)
from app.modules.transactions.gateways.common import (
    PROVIDER_API_TIMEOUT_S,
    compact_json,
    hmac_hex,
    link_lifetime,
    parse_json,
    safe_equals,
    to_decimal,
)

_API_BASE: Final[str] = "https://coinspay.app/api/v1"
_TEST_KEY_PREFIX: Final[str] = "cpk_test_"
_SIGNATURE_HEADER: Final[str] = "x-cpay-signature"
_SIGNATURE_TOLERANCE_S: Final[int] = 300
_MAX_TIMESTAMP_DIGITS: Final[int] = 15
_MIN_LIFETIME_MIN: Final[int] = 15
_MAX_LIFETIME_MIN: Final[int] = 43200
_PAID_EVENT: Final[str] = "invoice.paid"
_CLOSED_EVENTS: Final[frozenset[str]] = frozenset({"invoice.expired", "invoice.cancelled"})
_CLOSED_STATUSES: Final[frozenset[str]] = frozenset({"expired", "cancelled"})


def _closed_status(invoice: dict[str, Any]) -> TransactionStatus:
    # whatever was paid has already gone out to the shop's own wallets
    paid = to_decimal(invoice.get("amount_paid"))
    return TransactionStatus.FAILED if paid is not None and paid > 0 else TransactionStatus.CANCELED


def _nonempty(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


# Docs: https://coinspay.app/docs
class CoinsPayGateway(PaymentGateway[CoinsPaySettings]):
    settings_model = CoinsPaySettings
    currency = Currency.USD

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key.get_secret_value()}",
            "User-Agent": "Remnashop (+https://github.com/remnashop/remnashop)",
        }

    @staticmethod
    def _field(response: httpx.Response, key: str) -> Any:
        response.raise_for_status()
        return parse_json(response.content, "CoinsPay").get(key)

    async def _get_invoice(self, invoice_id: str) -> dict[str, Any]:
        response = await self._http.get(
            f"{_API_BASE}/invoices/{quote(invoice_id, safe='')}",
            headers=self._headers(),
            timeout=PROVIDER_API_TIMEOUT_S,
        )
        invoice = self._field(response, "invoice")
        if not isinstance(invoice, dict):
            raise PaymentGatewayError("CoinsPay API response missing invoice")
        return invoice

    async def _find_invoice(
        self, order: TransactionDto, signal: WebhookSignal
    ) -> Optional[dict[str, Any]]:
        known = {ref for ref in (order.external_payment_id, signal.provider_payment_id) if ref}
        if len(known) > 1:
            return None
        if known:
            return await self._get_invoice(known.pop())
        response = await self._http.get(
            f"{_API_BASE}/invoices",
            params={"reference": order.idempotency_key, "limit": 2},
            headers=self._headers(),
            timeout=PROVIDER_API_TIMEOUT_S,
        )
        listed = self._field(response, "invoices")
        if not isinstance(listed, list) or len(listed) != 1 or not isinstance(listed[0], dict):
            return None
        invoice_id = _nonempty(listed[0].get("id"))
        return await self._get_invoice(invoice_id) if invoice_id else None

    async def create_payment(self, order: TransactionDto, text: PaymentTextDto) -> PaymentIntent:
        # a test invoice is paid with a button on its payment page, by anyone holding the link
        api_key = self.settings.api_key.get_secret_value()
        if api_key.startswith(_TEST_KEY_PREFIX) and not order.is_test:
            raise PaymentGatewayError("A CoinsPay test key takes only dashboard test payments")
        response = await self._http.post(
            f"{_API_BASE}/invoices",
            content=compact_json(
                {
                    "currency": order.currency.value,
                    "amount": f"{order.final_price:.2f}",
                    "reference": order.idempotency_key,
                    "title": text.title[:200],
                    "description": text.localized_description[:1000],
                    "return_url": self._return_url,
                    "lifetime_minutes": link_lifetime(
                        order, unit="minutes", minimum=_MIN_LIFETIME_MIN, maximum=_MAX_LIFETIME_MIN
                    ),
                }
            ),
            headers={
                **self._headers(),
                "Content-Type": "application/json",
                "Idempotency-Key": order.idempotency_key,
            },
        )
        invoice = self._field(response, "invoice")
        if not isinstance(invoice, dict):
            raise PaymentGatewayError("CoinsPay API response missing invoice")
        if (
            invoice.get("reference") != order.idempotency_key
            or to_decimal(invoice.get("amount")) != order.final_price
            or invoice.get("currency") != order.currency.value
        ):
            raise PaymentGatewayError("CoinsPay invoice does not match the order")
        invoice_id, pay_url = _nonempty(invoice.get("id")), _nonempty(invoice.get("pay_url"))
        if invoice_id is None or pay_url is None:
            raise PaymentGatewayError("CoinsPay response missing invoice id or payment URL")
        return PaymentIntent(confirmation_url=pay_url, provider_payment_id=invoice_id)

    def _signature_valid(self, request: WebhookRequest) -> bool:
        timestamp: Optional[str] = None
        signatures: list[str] = []
        for piece in request.headers.get(_SIGNATURE_HEADER, "").split(","):
            key, separator, value = piece.strip().partition("=")
            if not separator:
                return False
            if key == "t":
                timestamp = value
            elif key == "v1":
                signatures.append(value)
        if (
            timestamp is None
            or not signatures
            or not (timestamp.isascii() and timestamp.isdigit())
            or len(timestamp) > _MAX_TIMESTAMP_DIGITS
            or abs(datetime_now().timestamp() - int(timestamp)) > _SIGNATURE_TOLERANCE_S
        ):
            return False
        expected = hmac_hex(
            self.settings.webhook_secret.get_secret_value(),
            f"{timestamp}.".encode("ascii") + request.body,
        )
        return any(safe_equals(expected, signature) for signature in signatures)

    async def parse_webhook(self, request: WebhookRequest) -> Optional[WebhookSignal]:
        if not self._signature_valid(request):
            raise PaymentGatewayError("Invalid CoinsPay webhook signature")
        event = parse_json(request.body, "CoinsPay")
        event_type = event.get("type")
        if event_type != _PAID_EVENT and event_type not in _CLOSED_EVENTS:
            return None
        data = event.get("data")
        invoice = data.get("invoice") if isinstance(data, dict) else None
        if not isinstance(invoice, dict):
            raise PaymentGatewayError("CoinsPay webhook missing invoice")
        reference = _nonempty(invoice.get("reference"))
        # an invoice issued by hand in the CoinsPay dashboard has none
        if reference is None:
            return None
        invoice_id = _nonempty(invoice.get("id"))
        if invoice_id is None:
            raise PaymentGatewayError("CoinsPay webhook missing invoice id")
        return WebhookSignal(
            reference=reference,
            provider_payment_id=invoice_id,
            claims_paid=event_type == _PAID_EVENT,
            reported_status=None if event_type == _PAID_EVENT else _closed_status(invoice),
        )

    async def fetch_payment(self, order: TransactionDto, signal: WebhookSignal) -> ProviderPayment:
        invoice = await self._find_invoice(order, signal)
        if invoice is None:
            return NOT_PAID
        amount = to_decimal(invoice.get("amount"))
        currency = _nonempty(invoice.get("currency"))
        invoice_id = _nonempty(invoice.get("id"))
        test = invoice.get("test")
        return ProviderPayment(
            paid=invoice.get("status") == "paid"
            and amount is not None
            and currency is not None
            and invoice_id is not None
            and (not order.external_payment_id or invoice_id == order.external_payment_id)
            and (not signal.provider_payment_id or invoice_id == signal.provider_payment_id)
            and (test is False or (test is True and order.is_test)),
            amount=amount,
            currency=currency,
            reference=str(invoice.get("reference") or ""),
            provider_payment_id=invoice_id,
        )

    async def confirm_reported(
        self, order: TransactionDto, signal: WebhookSignal
    ) -> Optional[WebhookSignal]:
        invoice = await self._find_invoice(order, signal)
        if (
            invoice is None
            or invoice.get("reference") != order.idempotency_key
            or invoice.get("id") != signal.provider_payment_id
            or invoice.get("status") not in _CLOSED_STATUSES
            or _closed_status(invoice) != signal.reported_status
        ):
            return None
        return signal
