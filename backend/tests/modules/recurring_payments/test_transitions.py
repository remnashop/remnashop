from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.core.enums import Currency, PaymentGatewayType, TransactionStatus
from app.modules.recurring_payments.dto import (
    ConsentFacts,
    PaidOrderFacts,
    RecurringPaymentDto,
    RecurringTerms,
)
from app.modules.recurring_payments.events import (
    RecurringPaymentFailedEvent,
)
from app.modules.recurring_payments.policy import ConsentChannel, RecurringReason
from app.modules.recurring_payments.transitions import (
    adopt_paid_order,
    apply_customer_toggle,
    apply_failed_order,
)

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


EXPIRE = NOW + timedelta(hours=2)


def _mandate(**overrides: Any) -> RecurringPaymentDto:
    base = RecurringPaymentDto(
        subscription_id=7,
        source_transaction_id=5,
        payment_method_id="pm-old",
        shop_id="shop",
        enabled=True,
        customer_disabled=False,
        last_error=None,
        pending_transaction_id=None,
        consent_id=1,
        next_attempt_at=NOW,
    )
    return replace(base, **overrides)


def _order(**overrides: Any) -> PaidOrderFacts:
    base = PaidOrderFacts(
        id=10,
        user_id=3,
        status=TransactionStatus.PAID,
        gateway_type=PaymentGatewayType.YOOKASSA,
        is_test=False,
        is_recurring=False,
        recurring_consent_id=None,
        saved_payment_method_id=None,
        payment_method_shop_id=None,
        final_price=Decimal("100"),
        currency=Currency.RUB,
    )
    return replace(base, **overrides)


def _terms() -> RecurringTerms:
    return RecurringTerms(
        version="1",
        terms_id="t",
        user_id=3,
        plan_id=1,
        target_subscription_id=7,
        purchase_type="RENEW",
        initial_amount=Decimal("100"),
        amount_limit=Decimal("100"),
        currency=Currency.RUB,
        duration_days=30,
        lead_minutes=60,
        retry_minutes=5,
        retry_offsets_hours=(1, 3, 6, 12, 24, 36, 48, 72),
        pending_timeout_hours=24,
        max_overdue_hours=96,
        locale="ru",
        summary="s",
        text="t",
    )


def test_manual_renewal_keeps_enabled_mandate() -> None:
    mandate = _mandate(
        first_failure_at=NOW, retry_count=2, last_error=RecurringReason.INSUFFICIENT_FUNDS
    )
    effects = adopt_paid_order(
        mandate,
        _order(gateway_type=PaymentGatewayType.TELEGRAM_STARS, currency=Currency.XTR),
        consent=None,
        current_consent_active=True,
        now=NOW,
    )
    assert mandate.enabled is True
    assert mandate.payment_method_id == "pm-old"
    assert mandate.first_failure_at is None and mandate.retry_count == 0
    assert mandate.last_error is None
    assert effects.notices == [] and effects.revoked_consents == []


def test_paid_with_unsaved_method_keeps_working_mandate() -> None:
    mandate = _mandate()
    consent = ConsentFacts(id=2, owner_user_id=3, revoked=False, accepted_at=NOW)
    effects = adopt_paid_order(
        mandate,
        _order(recurring_consent_id=2, saved_payment_method_id=None),
        consent=consent,
        current_consent_active=True,
        now=NOW,
    )
    assert mandate.payment_method_id == "pm-old"
    assert mandate.consent_id == 1 and mandate.enabled is True
    assert effects.revoked_consents == [(2, ConsentChannel.UNUSED)]


def test_plan_change_carries_previous_disabled_at() -> None:
    withdrawn_at = NOW - timedelta(days=3)
    mandate = _mandate(payment_method_id=None, consent_id=None, enabled=False)
    apply_customer_toggle(
        mandate,
        enabled=False,
        consent_id=None,
        disabled_at=withdrawn_at,
        subscription_expire_at=EXPIRE,
        now=NOW,
    )
    assert mandate.disabled_at == withdrawn_at
    consent = ConsentFacts(
        id=4, owner_user_id=3, revoked=False, accepted_at=NOW - timedelta(minutes=5)
    )
    adopt_paid_order(
        mandate,
        _order(
            id=11,
            recurring_consent_id=4,
            saved_payment_method_id="pm-new",
            payment_method_shop_id="shop",
        ),
        consent=consent,
        current_consent_active=False,
        now=NOW,
    )
    assert mandate.enabled is True and mandate.customer_disabled is False
    assert mandate.consent_id == 4 and mandate.payment_method_id == "pm-new"


def test_failure_after_customer_disable_keeps_customer_disabled_and_no_notice() -> None:
    mandate = _mandate(
        enabled=False,
        customer_disabled=True,
        last_error=RecurringReason.CUSTOMER_DISABLED,
        pending_transaction_id=10,
    )
    effects = apply_failed_order(
        mandate,
        order_id=10,
        amount=Decimal("100"),
        currency=Currency.RUB,
        reason=RecurringReason.BANK_DECLINED,
        permanent=False,
        terms=None,
        subscription_expire_at=EXPIRE,
        user_id=3,
        now=NOW,
    )
    assert mandate.last_error == RecurringReason.CUSTOMER_DISABLED
    assert mandate.pending_transaction_id is None
    assert effects.notices == []


def test_bank_decline_schedules_ladder_offsets() -> None:
    mandate = _mandate(pending_transaction_id=10, cycle_expire_at=EXPIRE)
    effects = apply_failed_order(
        mandate,
        order_id=10,
        amount=Decimal("100"),
        currency=Currency.RUB,
        reason=RecurringReason.INSUFFICIENT_FUNDS,
        permanent=False,
        terms=_terms(),
        subscription_expire_at=EXPIRE,
        user_id=3,
        now=NOW,
    )
    assert mandate.first_failure_at == NOW
    assert mandate.bank_retry_at == NOW + timedelta(hours=1)
    assert mandate.next_attempt_at == NOW + timedelta(hours=1)
    assert mandate.retry_count == 1
    assert [type(n) for n in effects.notices] == [RecurringPaymentFailedEvent]


def test_toggle_within_cycle_keeps_ladder() -> None:
    first = NOW - timedelta(hours=2)
    mandate = _mandate(
        enabled=False,
        customer_disabled=True,
        first_failure_at=first,
        retry_count=2,
        bank_retry_at=first + timedelta(hours=6),
        cycle_expire_at=EXPIRE,
    )
    apply_customer_toggle(
        mandate,
        enabled=True,
        consent_id=9,
        disabled_at=None,
        subscription_expire_at=EXPIRE,
        now=NOW,
    )
    assert mandate.enabled is True
    assert mandate.first_failure_at == first and mandate.retry_count == 2
    assert mandate.bank_retry_at == first + timedelta(hours=6)


def test_toggle_in_new_cycle_resets_ladder() -> None:
    first = NOW - timedelta(days=40)
    mandate = _mandate(
        enabled=False,
        customer_disabled=True,
        first_failure_at=first,
        retry_count=8,
        bank_retry_at=first + timedelta(hours=72),
        cycle_expire_at=EXPIRE - timedelta(days=30),
    )
    apply_customer_toggle(
        mandate,
        enabled=True,
        consent_id=9,
        disabled_at=None,
        subscription_expire_at=EXPIRE,
        now=NOW,
    )
    assert mandate.first_failure_at is None and mandate.retry_count == 0
    assert mandate.bank_retry_at is None


def test_customer_disable_sets_disabled_at_now() -> None:
    mandate = _mandate()
    apply_customer_toggle(
        mandate,
        enabled=False,
        consent_id=None,
        disabled_at=None,
        subscription_expire_at=EXPIRE,
        now=NOW,
    )
    assert mandate.enabled is False and mandate.customer_disabled is True
    assert mandate.disabled_at == NOW
    assert mandate.last_error == RecurringReason.CUSTOMER_DISABLED
