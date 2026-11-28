from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel

from app.core.constants import DEFAULT_PAGE_SIZE
from app.core.enums import (
    Currency,
    Locale,
    PaymentGatewayType,
    PurchaseChannel,
    PurchaseType,
    TransactionStatus,
)
from app.modules.recurring_payments.policy import ConsentChannel, RecurringReason, RecurringState


# stored as the consent's JSONB snapshot: the exact amounts, timings and text shown
class RecurringTerms(BaseModel):
    version: str
    terms_id: str
    user_id: int
    plan_id: int
    target_subscription_id: Optional[int]
    purchase_type: PurchaseType
    initial_amount: Decimal
    amount_limit: Decimal
    currency: Currency
    duration_days: int
    lead_minutes: int
    retry_minutes: int
    retry_offsets_hours: tuple[int, ...]
    pending_timeout_hours: int
    max_overdue_hours: int
    locale: Locale
    summary: str
    text: str

    def covers(
        self,
        *,
        user_id: int,
        plan_id: int,
        amount: Decimal,
        duration_days: int,
        currency: Currency,
    ) -> bool:
        return (
            self.user_id == user_id
            and self.plan_id == plan_id
            and self.currency is currency
            and self.duration_days == duration_days
            and 0 < amount <= self.amount_limit
        )


# mutable: transitions edit a copy, the repository writes the changed fields
@dataclass(kw_only=True)
class RecurringPaymentDto:
    subscription_id: int
    source_transaction_id: Optional[int]
    payment_method_id: Optional[str] = field(repr=False)
    shop_id: str
    enabled: bool
    customer_disabled: bool
    last_error: Optional[RecurringReason]
    pending_transaction_id: Optional[int]
    submitted_at: Optional[datetime] = None
    disabled_at: Optional[datetime] = None
    consent_id: Optional[int] = None
    first_failure_at: Optional[datetime] = None
    retry_count: int = 0
    cycle_expire_at: Optional[datetime] = None
    pending_since: Optional[datetime] = None
    upcoming_notified_for: Optional[datetime] = None
    next_attempt_at: Optional[datetime] = None
    leased_until: Optional[datetime] = None
    bank_retry_at: Optional[datetime] = None


@dataclass(frozen=True, kw_only=True)
class ConsentFacts:
    id: int
    owner_user_id: int
    revoked: bool
    accepted_at: datetime


@dataclass(frozen=True, kw_only=True)
class PaidOrderFacts:
    id: int
    user_id: int
    status: TransactionStatus
    gateway_type: Optional[PaymentGatewayType]
    is_test: bool
    is_recurring: bool
    recurring_consent_id: Optional[int]
    saved_payment_method_id: Optional[str] = field(repr=False)
    payment_method_shop_id: Optional[str]
    final_price: Decimal
    currency: Currency


@dataclass(frozen=True, kw_only=True)
class RecurringTermsTextDto:
    summary: str
    text: str


@dataclass(frozen=True, kw_only=True)
class CheckoutRecurringTermsDto:
    # None where the method or the plan offers no auto-renewal
    terms: Optional[RecurringTerms]


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentStateDto:
    subscription_id: int
    enabled: bool
    available: bool
    terms: Optional[RecurringTerms] = None
    accepted_terms: Optional[RecurringTerms] = None
    customer_disabled: bool = False
    can_disable: bool = False
    paused: bool = False
    retrying: bool = False
    payment_pending: bool = False
    # a charge request was sent and its outcome is not known yet
    payment_in_flight: bool = False
    next_retry_at: Optional[datetime] = None
    amount_limit: Optional[Decimal] = None
    currency: Optional[Currency] = None
    duration_days: Optional[int] = None
    next_payment_at: Optional[datetime] = None
    last_error: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class SetRecurringPaymentDto:
    subscription_id: int
    enabled: bool
    channel: PurchaseChannel
    terms_id: Optional[str] = None
    event_id: Optional[str] = None
    client_ip: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class ProcessRecurringPaymentDto:
    subscription_id: int


@dataclass(frozen=True, kw_only=True)
class ListRecurringPaymentsDto:
    state: Optional[RecurringState] = None
    search: Optional[str] = None
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentAdminRowDto:
    # one mandate as stored, for the admin list to decide what it may offer
    subscription_id: int
    user_id: int
    user_name: Optional[str]
    plan_name: str
    enabled: bool
    customer_disabled: bool
    state: RecurringState
    last_error: Optional[RecurringReason]
    next_attempt_at: Optional[datetime]
    submitted_at: Optional[datetime]
    pending_transaction_id: Optional[int]
    pending_status: Optional[TransactionStatus]
    external_payment_id: Optional[str]
    has_saved_method: bool
    # a consent is attached and not withdrawn
    authorized: bool
    # past the window the consent allows charges in
    overdue: bool
    retry_count: int
    first_failure_at: Optional[datetime]
    amount_limit: Optional[Decimal]
    currency: Optional[Currency]
    duration_days: Optional[int]
    expire_at: datetime


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentAdminItemDto:
    subscription_id: int
    user_id: int
    user_name: Optional[str]
    plan_name: str
    enabled: bool
    customer_disabled: bool
    state: RecurringState
    last_error: Optional[str]
    next_attempt_at: Optional[datetime]
    submitted_at: Optional[datetime]
    pending_transaction_id: Optional[int]
    external_payment_id: Optional[str]
    can_check: bool
    can_close: bool
    can_retry: bool
    retry_count: int
    first_failure_at: Optional[datetime]
    amount_limit: Optional[Decimal]
    currency: Optional[Currency]
    duration_days: Optional[int]
    has_saved_method: bool
    expire_at: datetime


@dataclass(frozen=True, kw_only=True)
class RecurringConsentDto:
    # the latest consent of the mandate, withdrawn or not, with the exact terms shown
    terms: RecurringTerms
    channel: PurchaseChannel
    accepted_at: datetime
    revoked_at: Optional[datetime]
    revoked_channel: Optional[ConsentChannel]


@dataclass(frozen=True, kw_only=True)
class RecurringPaymentSummaryDto:
    total: int
    enabled: int
    disabled: int
    pending: int
    retrying: int
    attention: int
    paid_renewals: int
    failed_renewals: int
    revenue: Decimal
    currency: Currency


class RecurringAction(StrEnum):
    CHECK = "check"
    CLOSE = "close"
    RETRY = "retry"


@dataclass(frozen=True, kw_only=True)
class RecurringAdminActionDto:
    subscription_id: int
    client_ip: str
    # the pending order the admin saw; a different one means the state moved under them
    expected_pending_transaction_id: Optional[int] = None
