from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.constants import INT32_MAX, RECURRING_TERMS_ID_PATTERN
from app.core.enums import Currency, Locale, PaymentGatewayType, PurchaseChannel, PurchaseType
from app.core.utils.validators import known_locale
from app.modules.recurring_payments.policy import RecurringState


class CheckoutRecurringTermsRequest(BaseModel):
    plan_id: int
    duration_days: int = Field(ge=0)
    currency: Currency
    purchase_type: PurchaseType
    gateway_type: PaymentGatewayType
    target_subscription_id: Optional[int] = None
    plan_code: Optional[str] = Field(default=None, max_length=64)
    legal_locale: Optional[Locale] = None

    _legal_locale = field_validator("legal_locale", mode="before")(known_locale)


class SetRecurringPaymentRequest(BaseModel):
    enabled: bool
    terms_id: Optional[str] = Field(default=None, pattern=RECURRING_TERMS_ID_PATTERN)


class RecurringAdminActionRequest(BaseModel):
    expected_pending_transaction_id: Optional[int] = Field(default=None, ge=1, le=INT32_MAX)


class RecurringTermsResponse(BaseModel):
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


class CheckoutRecurringTermsResponse(BaseModel):
    # null where the method or the plan offers no auto-renewal
    terms: Optional[RecurringTermsResponse]


class RecurringPaymentStateResponse(BaseModel):
    subscription_id: int
    terms: Optional[RecurringTermsResponse] = None
    accepted_terms: Optional[RecurringTermsResponse] = None
    enabled: bool
    available: bool
    customer_disabled: bool
    can_disable: bool
    paused: bool
    retrying: bool
    payment_pending: bool
    payment_in_flight: bool
    next_retry_at: Optional[datetime] = None
    amount_limit: Optional[Decimal] = None
    currency: Optional[Currency] = None
    duration_days: Optional[int] = None
    next_payment_at: Optional[datetime] = None
    last_error: Optional[str] = None


class RecurringPaymentAdminItemResponse(BaseModel):
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


class RecurringConsentResponse(BaseModel):
    terms: RecurringTermsResponse
    channel: PurchaseChannel
    accepted_at: datetime
    revoked_at: Optional[datetime]
    revoked_channel: Optional[str]


class RecurringPaymentPageResponse(BaseModel):
    items: list[RecurringPaymentAdminItemResponse]
    total: int


class RecurringPaymentSummaryResponse(BaseModel):
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
