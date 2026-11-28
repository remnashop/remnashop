from datetime import datetime
from typing import Optional, Protocol

from app.core.enums import FulfillmentHold


class ReferrerLookup(Protocol):
    async def has_referrer(self, user_id: int) -> bool: ...


class OrderFailer(Protocol):
    async def fail_unpaid_free_order(self, idempotency_key: str) -> None:
        """Fails a paid free order left unissued and hands its one-shot discount back."""
        ...


class PaidOrderHold(Protocol):
    async def hold_paid_order(self, idempotency_key: str, hold: FulfillmentHold) -> bool:
        """Leaves a paid order to an admin; False when no paid order has the key."""
        ...


class OpenOrderCounter(Protocol):
    # NEW orders that can still become a subscription: unexpired PENDING or PAID-unlinked
    async def count_open_new_orders(
        self, user_id: int, now: datetime, *, exclude_key: Optional[str] = None
    ) -> int: ...


class RecurringPaymentCloser(Protocol):
    async def close_for_plan_change(self, subscription_id: int) -> None: ...
