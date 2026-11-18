from typing import Optional, Protocol

from app.core.enums import Locale, PurchaseChannel
from app.modules.plans import PlanDto
from app.modules.transactions.dto import (
    CreateCheckoutDto,
    PaymentTextDto,
    PriceQuote,
    TransactionDto,
)
from app.modules.users import UserDto


class PromocodeLiveness(Protocol):
    async def is_live(self, promocode_id: int) -> bool: ...


class PaymentsRestoredNotifier(Protocol):
    # queues the "payments are back" notice for each user, as a notification of that outbox event
    async def notify(self, user_ids: list[int], outbox_id: int) -> None: ...


class PaymentTexts(Protocol):
    # what the provider shows the customer for the order
    async def describe(self, order: TransactionDto, locale: Locale) -> PaymentTextDto: ...


class RecurringCheckout(Protocol):
    # auto-renewal as a manual checkout sees it; every call runs in the checkout's transaction
    async def hold(self, user_id: int, data: CreateCheckoutDto) -> None: ...

    async def record_consent(
        self,
        actor: UserDto,
        data: CreateCheckoutDto,
        plan: PlanDto,
        quote: PriceQuote,
        gateway_settings: dict[str, str],
    ) -> Optional[int]: ...

    async def revoke_consent(self, consent_id: Optional[int], channel: PurchaseChannel) -> None: ...


class RecurringOrderHooks(Protocol):
    # called under the order's row lock, in the transaction that moved its status
    async def on_canceled(self, order_id: int, provider_reason: Optional[str]) -> None: ...

    async def on_refunded(self, order: TransactionDto) -> None: ...

    async def on_fulfilled(self, order: TransactionDto, subscription_id: int) -> None: ...
