from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum, auto
from typing import Any, Callable, Final, Mapping, Optional, Protocol, TypeVar

from app.core.enums import UpperStrEnum
from app.modules.gateways import RECURRING_TIMINGS

SAFE_REPOST_WINDOW: Final[timedelta] = timedelta(hours=23)
RETRY_OFFSETS_HOURS: Final[tuple[int, ...]] = (1, 3, 6, 12, 24, 36, 48, 72)
POLICY_RECHECK_DELAY: Final[timedelta] = timedelta(hours=1)
# the scheduler's bounded batches and its queue claim
DEBIT_BATCH_SIZE: Final[int] = 1000
POLL_BATCH_SIZE: Final[int] = 1000
QUEUE_LEASE: Final[timedelta] = timedelta(minutes=60)
PENDING_TIMEOUT_HOURS: Final[int] = 24
# how long a saved method outlives the customer's withdrawal; stated in the terms
METHOD_RETENTION_DAYS: Final[int] = 30


@dataclass(frozen=True, kw_only=True)
class RecurringPolicy:
    lead_minutes: int
    retry_minutes: int
    max_overdue_hours: int
    notice_lead_minutes: int


def recurring_policy(settings: Mapping[str, Any]) -> RecurringPolicy:
    def value(key: str) -> int:
        default, low, high = RECURRING_TIMINGS[key]
        raw = settings.get(key)
        try:
            number = int(str(raw).strip()) if raw not in (None, "") else default
        except ValueError:
            number = default
        return min(max(number, low), high)

    return RecurringPolicy(
        lead_minutes=value("recurring_lead_minutes"),
        retry_minutes=value("recurring_retry_minutes"),
        max_overdue_hours=value("recurring_max_overdue_hours"),
        notice_lead_minutes=value("recurring_notice_lead_minutes"),
    )


class RetryKind(StrEnum):
    NONE = "none"
    TECHNICAL = "technical"
    BANK = "bank"
    POLL = "poll"


@dataclass(frozen=True)
class ReasonPolicy:
    retry: RetryKind
    customer_notice: bool = True
    admin_notice: bool = True
    terminal: bool = False
    attention: bool = True
    block_enable: bool = True

    @property
    def allows_debit(self) -> bool:
        return self.retry in {RetryKind.TECHNICAL, RetryKind.BANK}


class RecurringReason(StrEnum):
    CUSTOMER_DISABLED = "customer_disabled"
    ADMIN_CLOSED = "admin_closed"
    BANK_DECLINED = "bank_declined"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    ISSUER_UNAVAILABLE = "issuer_unavailable"
    PAYMENT_METHOD_UNAVAILABLE = "payment_method_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MERCHANT_UNAVAILABLE = "merchant_unavailable"
    PROVIDER_CONFIGURATION_ERROR = "provider_configuration_error"
    # YooKassa refused the request itself (HTTP 400/404): the shop or the card, we can't tell
    PROVIDER_REQUEST_REJECTED = "provider_request_rejected"
    PROVIDER_REJECTED = "provider_rejected"
    PERMISSION_REVOKED = "permission_revoked"
    PAYMENT_METHOD_RESTRICTED = "payment_method_restricted"
    CARD_EXPIRED = "card_expired"
    FRAUD_SUSPECTED = "fraud_suspected"
    PRICE_CHANGED = "price_changed"
    SUBSCRIPTION_CHANGED = "subscription_changed"
    SHOP_CHANGED = "shop_changed"
    CONSENT_REQUIRED = "consent_required"
    PLAN_UNAVAILABLE = "plan_unavailable"
    CUSTOMER_EMAIL_REQUIRED = "customer_email_required"
    GATEWAY_DISABLED = "gateway_disabled"
    SUBSCRIPTION_UNAVAILABLE = "subscription_unavailable"
    PAYMENT_STATUS_UNKNOWN = "payment_status_unknown"
    PENDING_TIMEOUT = "pending_timeout"
    RETRIES_EXHAUSTED = "retries_exhausted"
    PAYMENT_METHOD_NOT_SAVED = "payment_method_not_saved"
    RENEWAL_WINDOW_EXPIRED = "renewal_window_expired"
    REFUNDED = "refunded"

    @property
    def policy(self) -> ReasonPolicy:
        return _REASON_POLICIES[self]


_BANK = ReasonPolicy(RetryKind.BANK, admin_notice=False, attention=False, block_enable=False)
_TECHNICAL = ReasonPolicy(RetryKind.TECHNICAL, customer_notice=False)
_TERMINAL = ReasonPolicy(RetryKind.NONE, terminal=True)
# the customer's own card or bank ended it: the customer acts, not the shop
_CARD_ENDED = ReasonPolicy(RetryKind.NONE, admin_notice=False, terminal=True)
_REASON_POLICIES: Final[dict[RecurringReason, ReasonPolicy]] = {
    RecurringReason.CUSTOMER_DISABLED: ReasonPolicy(
        RetryKind.NONE,
        customer_notice=False,
        admin_notice=False,
        attention=False,
        block_enable=False,
    ),
    RecurringReason.ADMIN_CLOSED: ReasonPolicy(RetryKind.NONE, terminal=True, block_enable=False),
    RecurringReason.BANK_DECLINED: _BANK,
    RecurringReason.INSUFFICIENT_FUNDS: _BANK,
    RecurringReason.ISSUER_UNAVAILABLE: _BANK,
    RecurringReason.PAYMENT_METHOD_UNAVAILABLE: _BANK,
    RecurringReason.PROVIDER_REJECTED: _BANK,
    RecurringReason.PROVIDER_UNAVAILABLE: _TECHNICAL,
    RecurringReason.MERCHANT_UNAVAILABLE: _TECHNICAL,
    RecurringReason.PROVIDER_CONFIGURATION_ERROR: ReasonPolicy(
        RetryKind.NONE, customer_notice=False, terminal=True
    ),
    # both sides hear of it: the customer can pay by hand, an admin can fix and retry
    RecurringReason.PROVIDER_REQUEST_REJECTED: ReasonPolicy(RetryKind.NONE, terminal=True),
    RecurringReason.PERMISSION_REVOKED: _CARD_ENDED,
    RecurringReason.PAYMENT_METHOD_RESTRICTED: _CARD_ENDED,
    RecurringReason.CARD_EXPIRED: _CARD_ENDED,
    RecurringReason.FRAUD_SUSPECTED: _CARD_ENDED,
    RecurringReason.PRICE_CHANGED: ReasonPolicy(RetryKind.TECHNICAL),
    RecurringReason.SUBSCRIPTION_CHANGED: _TERMINAL,
    RecurringReason.SHOP_CHANGED: _TECHNICAL,
    RecurringReason.CONSENT_REQUIRED: _TERMINAL,
    RecurringReason.PLAN_UNAVAILABLE: _TECHNICAL,
    RecurringReason.CUSTOMER_EMAIL_REQUIRED: _TECHNICAL,
    RecurringReason.GATEWAY_DISABLED: _TECHNICAL,
    RecurringReason.SUBSCRIPTION_UNAVAILABLE: ReasonPolicy(
        RetryKind.NONE, customer_notice=False, terminal=True
    ),
    RecurringReason.PAYMENT_STATUS_UNKNOWN: _TERMINAL,
    RecurringReason.PENDING_TIMEOUT: ReasonPolicy(RetryKind.POLL),
    RecurringReason.RETRIES_EXHAUSTED: _CARD_ENDED,
    RecurringReason.PAYMENT_METHOD_NOT_SAVED: _TERMINAL,
    RecurringReason.RENEWAL_WINDOW_EXPIRED: _TERMINAL,
    RecurringReason.REFUNDED: ReasonPolicy(RetryKind.NONE, customer_notice=False, terminal=True),
}


# codes YooKassa may put in cancellation_details.reason that we track by name
_PROVIDER_REASONS: Final[frozenset[RecurringReason]] = frozenset(
    reason
    for reason in RecurringReason
    if _REASON_POLICIES[reason] in (_BANK, _CARD_ENDED)
    and reason is not RecurringReason.RETRIES_EXHAUSTED
)


def provider_cancellation_reason(value: Optional[str]) -> RecurringReason:
    # any other provider code is a bank refusal; never one of our own stop reasons
    for reason in _PROVIDER_REASONS:
        if reason.value == value:
            return reason
    return RecurringReason.BANK_DECLINED


def stored_reason(value: Optional[str]) -> Optional[RecurringReason]:
    if value is None:
        return None
    try:
        return RecurringReason(value)
    except ValueError:
        # a code this version no longer knows stops debits and reaches an admin
        return RecurringReason.PROVIDER_CONFIGURATION_ERROR


class RecurringState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    PENDING = "pending"
    RETRYING = "retrying"
    ATTENTION = "attention"


_T = TypeVar("_T")


def classification_rules(
    *,
    enabled: _T,
    customer_disabled: _T,
    pending: _T,
    failed: _T,
    attention: _T,
    has_error: _T,
    combine: Callable[[_T, _T], _T],
) -> tuple[tuple[_T, RecurringState], ...]:
    # The same ordered rules drive SQL filters and the customer-facing state.
    return (
        (customer_disabled, RecurringState.DISABLED),
        (attention, RecurringState.ATTENTION),
        (pending, RecurringState.PENDING),
        (combine(enabled, failed), RecurringState.RETRYING),
        (has_error, RecurringState.ATTENTION),
        (enabled, RecurringState.ENABLED),
    )


class MandateState(Protocol):
    @property
    def enabled(self) -> bool: ...
    @property
    def customer_disabled(self) -> bool: ...
    @property
    def pending_transaction_id(self) -> Optional[int]: ...
    @property
    def first_failure_at(self) -> Optional[datetime]: ...
    @property
    def last_error(self) -> Optional[RecurringReason]: ...
    @property
    def submitted_at(self) -> Optional[datetime]: ...


def classify(mandate: MandateState) -> RecurringState:
    reason = mandate.last_error
    for matches, state in classification_rules(
        enabled=mandate.enabled,
        customer_disabled=mandate.customer_disabled,
        pending=mandate.pending_transaction_id is not None,
        failed=mandate.first_failure_at is not None,
        attention=(reason is not None and reason.policy.attention)
        or (mandate.submitted_at is not None and mandate.pending_transaction_id is None),
        has_error=reason is not None,
        combine=lambda first, second: first and second,
    ):
        if matches:
            return state
    return RecurringState.DISABLED


class ConsentChannel(UpperStrEnum):
    # where a consent was withdrawn: the customer's own channel or what withdrew it for them
    BOT = auto()
    CABINET = auto()
    ADMIN = auto()
    PLAN_CHANGE = auto()
    REFUND = auto()
    PROVIDER = auto()
    UNUSED = auto()
    REPLACED = auto()


def admin_may_retry(
    *,
    last_error: Optional[RecurringReason],
    customer_disabled: bool,
    pending: bool,
    submitted: bool,
    has_method: bool,
    authorized: bool,
    overdue: bool,
) -> bool:
    # a technical stop the shop fixed, under a live consent and inside its window; never a
    # bank refusal or the customer's own choice. The admin list and the retry share it.
    reason = last_error
    return bool(
        authorized
        and not overdue
        and reason is not None
        and (
            reason.policy.retry is RetryKind.TECHNICAL
            or reason
            in (
                RecurringReason.PROVIDER_CONFIGURATION_ERROR,
                RecurringReason.PROVIDER_REQUEST_REJECTED,
            )
        )
        and not customer_disabled
        and not pending
        and not submitted
        and has_method
    )
