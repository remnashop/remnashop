from decimal import Decimal
from hashlib import sha256
from typing import Final, Optional

from app.core.enums import Currency, Locale, PurchaseType
from app.modules.recurring_payments.dto import RecurringTerms
from app.modules.recurring_payments.policy import (
    METHOD_RETENTION_DAYS,
    PENDING_TIMEOUT_HOURS,
    RETRY_OFFSETS_HOURS,
    RecurringPolicy,
)
from app.modules.recurring_payments.ports import RecurringTermsTexts

TERMS_VERSION: Final[str] = "1"


async def build_recurring_terms(
    *,
    texts: RecurringTermsTexts,
    policy: RecurringPolicy,
    user_id: int,
    plan_id: int,
    target_subscription_id: Optional[int],
    purchase_type: PurchaseType,
    initial_amount: Decimal,
    amount_limit: Decimal,
    currency: Currency,
    duration_days: int,
    locale: Locale,
) -> RecurringTerms:
    amount = Decimal(format(amount_limit.normalize(), "f"))
    initial = Decimal(format(initial_amount.normalize(), "f"))
    # a one-day plan must not be charged again right after its purchase
    lead_minutes = min(policy.lead_minutes, duration_days * 24 * 60 // 2)
    rendered = await texts.render(
        locale,
        {
            "initial": str(initial),
            "amount": str(amount),
            "currency": currency.value,
            "currency_symbol": currency.symbol,
            "days": duration_days,
            "lead_minutes": lead_minutes,
            "retry_hours": ", ".join(str(hour) for hour in RETRY_OFFSETS_HOURS),
            "retry_minutes": policy.retry_minutes,
            "overdue_hours": policy.max_overdue_hours,
            "retention_days": METHOD_RETENTION_DAYS,
        },
    )
    terms = RecurringTerms(
        version=TERMS_VERSION,
        terms_id="",
        user_id=user_id,
        plan_id=plan_id,
        target_subscription_id=target_subscription_id,
        purchase_type=purchase_type,
        initial_amount=initial,
        amount_limit=amount,
        currency=currency,
        duration_days=duration_days,
        lead_minutes=lead_minutes,
        retry_minutes=policy.retry_minutes,
        max_overdue_hours=policy.max_overdue_hours,
        retry_offsets_hours=RETRY_OFFSETS_HOURS,
        pending_timeout_hours=PENDING_TIMEOUT_HOURS,
        locale=locale,
        summary=rendered.summary,
        text=rendered.text,
    )
    # the fingerprint binds the displayed text to this customer, selection and policy
    return terms.model_copy(
        update={"terms_id": sha256(terms.model_dump_json().encode()).hexdigest()}
    )
