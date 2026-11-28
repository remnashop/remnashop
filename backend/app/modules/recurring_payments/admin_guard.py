from dataclasses import dataclass
from typing import Optional

from app.core.actor import Actor
from app.core.error_codes import ErrorCode
from app.core.exceptions import ConflictError
from app.core.ports import EventPublisher
from app.modules.recurring_payments.dto import (
    RecurringAction,
    RecurringAdminActionDto,
    RecurringPaymentDto,
)
from app.modules.recurring_payments.events import RecurringPaymentManagedEvent
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.subscriptions import (
    SubscriptionDto,
    SubscriptionRepository,
    get_manageable_subscription,
)
from app.modules.transactions import TransactionRepository
from app.modules.users import UserDto, UserRepository


@dataclass(frozen=True, kw_only=True)
class LockedMandate:
    subscription: SubscriptionDto
    customer: UserDto
    # as the admin saw it; `mandate` is the same row read again under its lock
    before: RecurringPaymentDto
    mandate: RecurringPaymentDto


class RecurringAdminGuard:
    def __init__(
        self,
        recurring_repository: RecurringPaymentRepository,
        transaction_repository: TransactionRepository,
        subscription_repository: SubscriptionRepository,
        user_repository: UserRepository,
        event_publisher: EventPublisher,
    ) -> None:
        self._recurring = recurring_repository
        self._transactions = transaction_repository
        self._subscriptions = subscription_repository
        self._users = user_repository
        self._events = event_publisher

    async def lock(self, actor: Actor, data: RecurringAdminActionDto) -> LockedMandate:
        # refuses unless the pending payment is still the one the admin acted on
        subscription = await get_manageable_subscription(
            self._subscriptions, self._users, actor, data.subscription_id
        )
        customer = await self._users.find_by_id(subscription.user_id)
        before = await self._recurring.get(data.subscription_id)
        if before is None or customer is None:
            raise ConflictError(
                "No recurring payment is available", code=ErrorCode.RECURRING_NOT_AVAILABLE
            )
        _assert_unchanged(before.pending_transaction_id, data.expected_pending_transaction_id)
        # lock order everywhere: order, then mandate
        if before.pending_transaction_id is not None:
            await self._transactions.get_by_id_for_update(before.pending_transaction_id)
        mandate = await self._recurring.get(data.subscription_id, for_update=True)
        if mandate is None:
            raise ConflictError(
                "No recurring payment is available", code=ErrorCode.RECURRING_NOT_AVAILABLE
            )
        _assert_unchanged(mandate.pending_transaction_id, before.pending_transaction_id)
        return LockedMandate(
            subscription=subscription, customer=customer, before=before, mandate=mandate
        )

    async def record(
        self,
        actor: Actor,
        data: RecurringAdminActionDto,
        locked: LockedMandate,
        action: RecurringAction,
    ) -> None:
        await self._events.publish(
            RecurringPaymentManagedEvent(
                actor=actor,
                target=locked.customer,
                subscription_id=data.subscription_id,
                action=action,
                order_id=locked.before.pending_transaction_id,
                previous_reason=locked.before.last_error,
                ip_address=data.client_ip,
            )
        )


def require_pending(locked: LockedMandate) -> int:
    if locked.mandate.pending_transaction_id is None:
        raise ConflictError(
            "There is no pending payment", code=ErrorCode.RECURRING_PAYMENT_STATE_CHANGED
        )
    return locked.mandate.pending_transaction_id


def _assert_unchanged(current: Optional[int], expected: Optional[int]) -> None:
    if current != expected:
        raise ConflictError(
            "The recurring payment changed", code=ErrorCode.RECURRING_PAYMENT_STATE_CHANGED
        )
