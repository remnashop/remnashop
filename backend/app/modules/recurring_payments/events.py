from dataclasses import dataclass
from typing import ClassVar, Optional

from app.core.enums import Currency
from app.core.events import ActorTargetEvent, EventCategory, SystemEvent
from app.modules.recurring_payments.dto import RecurringAction
from app.modules.recurring_payments.policy import RecurringReason


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentUpcomingEvent(SystemEvent):
    category: ClassVar[EventCategory] = EventCategory.PAYMENT
    user_id: int
    subscription_id: int
    amount: str
    currency: Currency
    scheduled_at: str


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentFailedEvent(SystemEvent):
    category: ClassVar[EventCategory] = EventCategory.PAYMENT
    user_id: int
    subscription_id: int
    order_id: int
    amount: str
    currency: Currency
    reason: RecurringReason
    next_attempt_at: Optional[str] = None
    attempt: int = 0


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentPausedEvent(SystemEvent):
    category: ClassVar[EventCategory] = EventCategory.PAYMENT
    user_id: int
    subscription_id: int
    reason: RecurringReason
    order_id: Optional[int] = None
    next_attempt_at: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentExhaustedEvent(SystemEvent):
    category: ClassVar[EventCategory] = EventCategory.PAYMENT
    user_id: int
    subscription_id: int
    reason: RecurringReason
    order_id: Optional[int] = None


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentManagedEvent(ActorTargetEvent):
    category: ClassVar[EventCategory] = EventCategory.PAYMENT
    subscription_id: int
    action: RecurringAction
    order_id: Optional[int]
    previous_reason: Optional[str]
