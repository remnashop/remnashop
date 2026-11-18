from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from app.core.enums import Currency, PaymentGatewayType, TransactionStatus
from app.core.events import SystemEvent
from app.modules.recurring_payments.dto import (
    ConsentFacts,
    PaidOrderFacts,
    RecurringPaymentDto,
    RecurringTerms,
)
from app.modules.recurring_payments.events import (
    RecurringPaymentExhaustedEvent,
    RecurringPaymentFailedEvent,
    RecurringPaymentPausedEvent,
    RecurringPaymentUpcomingEvent,
)
from app.modules.recurring_payments.policy import ConsentChannel, RecurringReason


@dataclass(kw_only=True)
class MandateEffects:
    notices: list[SystemEvent] = field(default_factory=list)
    # (consent id, revoked_channel)
    revoked_consents: list[tuple[int, ConsentChannel]] = field(default_factory=list)
    attached_consent_id: Optional[int] = None

    def notice(self, event: Optional[SystemEvent]) -> None:
        if event is not None:
            self.notices.append(event)


def reset_cycle(mandate: RecurringPaymentDto, now: datetime) -> None:
    mandate.bank_retry_at = None
    mandate.first_failure_at = None
    mandate.retry_count = 0
    mandate.cycle_expire_at = None
    mandate.pending_since = None
    mandate.submitted_at = None
    mandate.last_error = RecurringReason.CUSTOMER_DISABLED if mandate.customer_disabled else None
    mandate.leased_until = None
    mandate.next_attempt_at = now


def pause_notice(
    mandate: RecurringPaymentDto,
    reason: RecurringReason,
    user_id: Optional[int],
    until: Optional[datetime] = None,
) -> Optional[RecurringPaymentPausedEvent]:
    if user_id is None or mandate.customer_disabled or mandate.last_error == reason:
        return None
    return RecurringPaymentPausedEvent(
        user_id=user_id,
        subscription_id=mandate.subscription_id,
        reason=reason,
        order_id=mandate.pending_transaction_id,
        next_attempt_at=until.isoformat() if until is not None else None,
    )


def apply_defer(
    mandate: RecurringPaymentDto,
    until: datetime,
    error: Optional[RecurringReason],
    user_id: Optional[int],
) -> MandateEffects:
    effects = MandateEffects()
    if mandate.customer_disabled:
        mandate.last_error = RecurringReason.CUSTOMER_DISABLED
    elif error is not None:
        effects.notice(pause_notice(mandate, error, user_id, until))
        mandate.last_error = error
    mandate.next_attempt_at = until
    mandate.leased_until = None
    return effects


def apply_disable(
    mandate: RecurringPaymentDto, reason: RecurringReason, user_id: Optional[int], now: datetime
) -> MandateEffects:
    effects = MandateEffects()
    effects.notice(pause_notice(mandate, reason, user_id))
    mandate.enabled = False
    mandate.leased_until = None
    if not mandate.customer_disabled:
        mandate.disabled_at = now
        mandate.last_error = reason
    return effects


def apply_clear_error(mandate: RecurringPaymentDto) -> None:
    mandate.last_error = RecurringReason.CUSTOMER_DISABLED if mandate.customer_disabled else None
    mandate.leased_until = None


def apply_resume(mandate: RecurringPaymentDto, now: datetime) -> bool:
    if (
        mandate.customer_disabled
        or mandate.pending_transaction_id is not None
        or mandate.submitted_at is not None
    ):
        return False
    mandate.enabled = True
    mandate.disabled_at = None
    mandate.last_error = None
    mandate.next_attempt_at = now
    mandate.leased_until = None
    return True


def apply_set_pending(
    mandate: RecurringPaymentDto, transaction_id: int, expire_at: datetime, now: datetime
) -> None:
    mandate.pending_transaction_id = transaction_id
    mandate.leased_until = None
    mandate.submitted_at = None
    mandate.pending_since = now
    mandate.cycle_expire_at = expire_at


def apply_upcoming(
    mandate: RecurringPaymentDto, expire_at: datetime, terms: RecurringTerms, scheduled_at: datetime
) -> MandateEffects:
    effects = MandateEffects()
    if mandate.upcoming_notified_for == expire_at:
        return effects
    mandate.upcoming_notified_for = expire_at
    mandate.leased_until = None
    effects.notice(
        RecurringPaymentUpcomingEvent(
            user_id=terms.user_id,
            subscription_id=mandate.subscription_id,
            amount=str(terms.amount_limit),
            currency=terms.currency,
            scheduled_at=scheduled_at.isoformat(),
        )
    )
    return effects


def apply_customer_toggle(
    mandate: RecurringPaymentDto,
    *,
    enabled: bool,
    consent_id: Optional[int],
    disabled_at: Optional[datetime],
    subscription_expire_at: datetime,
    now: datetime,
) -> None:
    unknown = mandate.submitted_at is not None and mandate.pending_transaction_id is None
    authorized = enabled and consent_id is not None and not unknown
    mandate.consent_id = consent_id
    mandate.customer_disabled = not enabled
    mandate.enabled = authorized
    mandate.disabled_at = None if enabled else disabled_at or now
    mandate.last_error = (
        RecurringReason.CUSTOMER_DISABLED
        if not enabled
        else RecurringReason.PAYMENT_STATUS_UNKNOWN
        if unknown
        else None
    )
    mandate.leased_until = None
    mandate.next_attempt_at = now
    # the bank-retry ladder belongs to the billing cycle: re-enabling within it must not
    # buy an immediate extra attempt on a card the bank just declined
    if authorized and mandate.cycle_expire_at != subscription_expire_at:
        mandate.bank_retry_at = None
        mandate.first_failure_at = None
        mandate.retry_count = 0


def next_retry_at(
    mandate: RecurringPaymentDto,
    terms: Optional[RecurringTerms],
    subscription_expire_at: Optional[datetime],
    now: datetime,
) -> Optional[datetime]:
    if terms is None or mandate.first_failure_at is None:
        return None
    offsets = terms.retry_offsets_hours
    if mandate.retry_count < 0 or mandate.retry_count >= len(offsets):
        return None
    # missed slots are skipped after an outage; never catch up by hammering the bank
    first = mandate.first_failure_at
    next_at = next(
        (first + timedelta(hours=hour) for hour in offsets if first + timedelta(hours=hour) > now),
        None,
    )
    if next_at is None:
        return None
    if subscription_expire_at is not None and next_at > subscription_expire_at + timedelta(
        hours=terms.max_overdue_hours
    ):
        return None
    return next_at


def reject_method(
    mandate: RecurringPaymentDto, reason: RecurringReason, now: datetime, effects: MandateEffects
) -> None:
    mandate.enabled = False
    if not mandate.customer_disabled:
        mandate.disabled_at = now
    mandate.payment_method_id = None
    if reason == RecurringReason.PERMISSION_REVOKED and mandate.consent_id is not None:
        effects.revoked_consents.append((mandate.consent_id, ConsentChannel.PROVIDER))


def _failure_while_closed(
    mandate: RecurringPaymentDto,
    reason: RecurringReason,
    permanent: bool,
    now: datetime,
    effects: MandateEffects,
) -> bool:
    if mandate.enabled and not mandate.customer_disabled:
        return False
    if permanent:
        reject_method(mandate, reason, now, effects)
    if mandate.customer_disabled:
        mandate.last_error = RecurringReason.CUSTOMER_DISABLED
    mandate.leased_until = None
    return True


def apply_failed_order(
    mandate: RecurringPaymentDto,
    *,
    order_id: int,
    amount: Decimal,
    currency: Currency,
    reason: RecurringReason,
    permanent: bool,
    terms: Optional[RecurringTerms],
    subscription_expire_at: Optional[datetime],
    user_id: Optional[int],
    now: datetime,
) -> MandateEffects:
    effects = MandateEffects()
    mandate.pending_transaction_id = None
    mandate.pending_since = None
    mandate.submitted_at = None
    if _failure_while_closed(mandate, reason, permanent, now, effects):
        return effects
    if (
        subscription_expire_at is not None
        and mandate.cycle_expire_at is not None
        and subscription_expire_at > mandate.cycle_expire_at
    ):
        reset_cycle(mandate, now)
        return effects
    if not permanent:
        mandate.first_failure_at = mandate.first_failure_at or now
    next_at = None if permanent else next_retry_at(mandate, terms, subscription_expire_at, now)
    retry = bool(
        next_at is not None
        and not permanent
        and terms
        and mandate.enabled
        and not mandate.customer_disabled
    )
    mandate.retry_count += 0 if permanent else 1
    mandate.last_error = reason
    mandate.leased_until = None
    mandate.next_attempt_at = next_at if retry and next_at is not None else now
    mandate.bank_retry_at = next_at if retry else None
    if user_id is not None and retry and next_at is not None:
        effects.notice(
            RecurringPaymentFailedEvent(
                user_id=user_id,
                subscription_id=mandate.subscription_id,
                order_id=order_id,
                amount=str(amount),
                currency=currency,
                reason=reason,
                next_attempt_at=next_at.isoformat(),
                attempt=mandate.retry_count,
            )
        )
    if not retry:
        mandate.last_error = reason if permanent else RecurringReason.RETRIES_EXHAUSTED
        if permanent:
            reject_method(mandate, reason, now, effects)
        if user_id is not None:
            effects.notice(
                RecurringPaymentExhaustedEvent(
                    user_id=user_id,
                    subscription_id=mandate.subscription_id,
                    order_id=order_id,
                    reason=mandate.last_error,
                )
            )
    return effects


def apply_release_pending(
    mandate: RecurringPaymentDto,
    reason: Optional[RecurringReason],
    retry_minutes: int,
    user_id: Optional[int],
    now: datetime,
) -> MandateEffects:
    effects = MandateEffects()
    until = now + timedelta(minutes=retry_minutes)
    if reason is not None:
        # a reason that never retries promises no next check
        effects.notice(
            pause_notice(mandate, reason, user_id, until if reason.policy.allows_debit else None)
        )
    mandate.pending_transaction_id = None
    mandate.pending_since = None
    mandate.submitted_at = None
    mandate.last_error = RecurringReason.CUSTOMER_DISABLED if mandate.customer_disabled else reason
    mandate.leased_until = None
    mandate.next_attempt_at = until if reason else now
    if reason is None:
        reset_cycle(mandate, now)
    return effects


def apply_retire(
    mandate: RecurringPaymentDto,
    *,
    unknown: bool,
    reconnected: bool,
    force_unknown: bool,
    notify: bool,
    user_id: Optional[int],
    now: datetime,
) -> tuple[TransactionStatus, MandateEffects]:
    effects = MandateEffects()
    if unknown and not reconnected and notify:
        effects.notice(pause_notice(mandate, RecurringReason.PAYMENT_STATUS_UNKNOWN, user_id))
    mandate.pending_transaction_id = None
    mandate.pending_since = None
    mandate.leased_until = None
    mandate.next_attempt_at = now
    if mandate.customer_disabled:
        mandate.last_error = RecurringReason.CUSTOMER_DISABLED
    elif unknown and not reconnected:
        mandate.enabled = False
        mandate.disabled_at = now
        mandate.last_error = RecurringReason.PAYMENT_STATUS_UNKNOWN
    elif not unknown or (reconnected and not force_unknown):
        # a delivered manual renewal already paid this cycle; its future mandate
        # must not inherit a retired attempt's submission marker
        reset_cycle(mandate, now)
    return (TransactionStatus.FAILED if unknown else TransactionStatus.CANCELED), effects


def apply_cancel_unsent(mandate: RecurringPaymentDto) -> None:
    mandate.pending_transaction_id = None
    mandate.pending_since = None
    mandate.leased_until = None


def apply_late_cancel_while_inactive(
    mandate: RecurringPaymentDto, reason: RecurringReason, now: datetime
) -> MandateEffects:
    effects = MandateEffects()
    previous = mandate.last_error
    reset_cycle(mandate, now)
    if reason.policy.terminal:
        reject_method(mandate, reason, now, effects)
    if previous == RecurringReason.ADMIN_CLOSED and not mandate.customer_disabled:
        mandate.last_error = previous
    return effects


def apply_recurring_fulfilled(
    mandate: RecurringPaymentDto,
    *,
    order_id: int,
    order_consent_id: Optional[int],
    latest_is_order: bool,
    consent_active: bool,
    now: datetime,
) -> bool:
    if mandate.pending_transaction_id != order_id:
        if (
            mandate.pending_transaction_id is not None
            or mandate.submitted_at is None
            or not latest_is_order
        ):
            return False
        recovered = (
            not mandate.customer_disabled
            and mandate.consent_id == order_consent_id
            and mandate.payment_method_id is not None
            and consent_active
        )
        if recovered:
            mandate.enabled = True
            mandate.disabled_at = None
    mandate.pending_transaction_id = None
    reset_cycle(mandate, now)
    return True


def _preserve_manual_renewal(mandate: RecurringPaymentDto, now: datetime) -> None:
    mandate.leased_until = None
    mandate.bank_retry_at = None
    if mandate.source_transaction_id is None or mandate.consent_id is None:
        return
    mandate.first_failure_at = None
    mandate.retry_count = 0
    mandate.last_error = (
        RecurringReason.CUSTOMER_DISABLED
        if mandate.customer_disabled
        else RecurringReason.PAYMENT_STATUS_UNKNOWN
        if mandate.submitted_at and mandate.pending_transaction_id is None
        else None
    )
    mandate.next_attempt_at = now
    if mandate.pending_transaction_id is None:
        mandate.cycle_expire_at = None


def adopt_paid_order(
    mandate: RecurringPaymentDto,
    order: PaidOrderFacts,
    *,
    consent: Optional[ConsentFacts],
    current_consent_active: bool,
    now: datetime,
) -> MandateEffects:
    effects = MandateEffects()
    if order.gateway_type is not PaymentGatewayType.YOOKASSA or order.recurring_consent_id is None:
        _preserve_manual_renewal(mandate, now)
        return effects
    if order.status is not TransactionStatus.PAID or order.is_test:
        return effects
    if (
        not order.saved_payment_method_id
        and mandate.payment_method_id
        and not mandate.customer_disabled
        and current_consent_active
    ):
        # the provider kept no method for this payment; the working mandate stays
        _preserve_manual_renewal(mandate, now)
        if order.recurring_consent_id != mandate.consent_id:
            effects.revoked_consents.append((order.recurring_consent_id, ConsentChannel.UNUSED))
        return effects
    _adopt_consent(mandate, order, consent, now, effects)
    return effects


def _adopt_consent(
    mandate: RecurringPaymentDto,
    order: PaidOrderFacts,
    consent: Optional[ConsentFacts],
    now: datetime,
    effects: MandateEffects,
) -> None:
    valid = bool(consent and not consent.revoked and consent.owner_user_id == order.user_id)
    # a late paid order must not undo a withdrawal made after its confirmation
    opted_out = mandate.customer_disabled and not (
        valid
        and consent is not None
        and mandate.disabled_at is not None
        and consent.accepted_at > mandate.disabled_at
    )
    if not order.saved_payment_method_id and valid and not opted_out:
        effects.notice(
            pause_notice(mandate, RecurringReason.PAYMENT_METHOD_NOT_SAVED, order.user_id)
        )
    if mandate.consent_id is not None and mandate.consent_id != order.recurring_consent_id:
        effects.revoked_consents.append((mandate.consent_id, ConsentChannel.REPLACED))
    mandate.source_transaction_id = order.id
    mandate.payment_method_id = order.saved_payment_method_id
    mandate.shop_id = order.payment_method_shop_id or ""
    mandate.consent_id = consent.id if valid and consent is not None and not opted_out else None
    mandate.customer_disabled = opted_out
    if consent is not None and valid:
        effects.attached_consent_id = consent.id
    mandate.enabled = bool(mandate.payment_method_id) and valid and not opted_out
    if mandate.enabled:
        mandate.disabled_at = None
    mandate.last_error = (
        RecurringReason.CUSTOMER_DISABLED
        if opted_out
        else None
        if mandate.enabled
        else RecurringReason.CONSENT_REQUIRED
        if not valid
        else RecurringReason.PAYMENT_METHOD_NOT_SAVED
    )
    mandate.leased_until = None
    mandate.next_attempt_at = now
    mandate.bank_retry_at = None
    mandate.first_failure_at = None
    mandate.retry_count = 0
    if mandate.pending_transaction_id is None:
        mandate.cycle_expire_at = None
        mandate.submitted_at = None
