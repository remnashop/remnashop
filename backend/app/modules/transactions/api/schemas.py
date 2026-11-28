from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.constants import RECURRING_TERMS_ID_PATTERN
from app.core.dto import ResponseModel
from app.core.enums import (
    Currency,
    DiscountSource,
    FulfillmentHold,
    Locale,
    PaymentGatewayType,
    PurchaseChannel,
    PurchaseType,
    TransactionStatus,
)
from app.core.utils.validators import known_locale
from app.modules.subscriptions import PlanSnapshot, PlanSnapshotResponse
from app.modules.transactions.dto import TransactionDto


class CreateCheckoutRequest(BaseModel):
    plan_id: int
    duration_days: int = Field(ge=0)
    currency: Currency
    purchase_type: PurchaseType
    # omitted: only for an order that costs nothing, recorded without a gateway
    gateway_type: Optional[PaymentGatewayType] = None
    target_subscription_id: Optional[int] = None
    customer_email: Optional[EmailStr] = None
    plan_code: Optional[str] = Field(default=None, max_length=64)
    legal_locale: Optional[Locale] = None
    expected_price: Optional[Decimal] = None
    replaces_order_id: Optional[int] = None
    recurring_consent: bool = False
    recurring_terms_id: Optional[str] = Field(default=None, pattern=RECURRING_TERMS_ID_PATTERN)

    _legal_locale = field_validator("legal_locale", mode="before")(known_locale)


class CheckoutResponse(ResponseModel):
    order_id: int
    confirmation_url: Optional[str] = None


class QuoteCheckoutRequest(BaseModel):
    plan_id: int
    duration_days: int = Field(ge=0)
    currency: Currency
    plan_code: Optional[str] = Field(default=None, max_length=64)
    renew_subscription_id: Optional[int] = None
    # a CHANGE: the subscription being changed, whose payment an unlimited one credits
    change_subscription_id: Optional[int] = None


class CheckoutQuoteResponse(ResponseModel):
    base_price: Decimal
    change_credit: Decimal
    change_credit_days: int
    plan_discount_percent: int
    discount_percent: int
    discount_source: DiscountSource
    final_price: Decimal
    currency: Currency


class TransactionUserResponse(ResponseModel):
    name: str
    username: Optional[str]
    telegram_id: Optional[int]
    email: Optional[str]


class TransactionResponse(ResponseModel):
    id: int
    user_id: int
    user: Optional[TransactionUserResponse]
    # None once the plan is deleted; plan_snapshot always records what was ordered
    plan_id: Optional[int]
    plan_snapshot: PlanSnapshotResponse
    # a CHANGE order's plan before it; None on other orders and on ones older than the field
    previous_plan_snapshot: Optional[PlanSnapshotResponse]
    duration_days: int
    currency: Currency
    purchase_type: PurchaseType
    channel: PurchaseChannel
    target_subscription_id: Optional[int]
    gateway_type: Optional[PaymentGatewayType]  # None: a free order
    external_payment_id: Optional[str]
    status: TransactionStatus
    base_price: Decimal
    discount_percent: int
    discount_source: DiscountSource
    plan_discount_percent: int
    # admin only: the customer never learns of a markup
    markup_percent: int
    final_price: Decimal
    change_credit: Decimal
    customer_email: Optional[str]
    idempotency_key: str
    is_test: bool
    # set: paid, left to an admin to issue or refund
    fulfillment_hold: Optional[FulfillmentHold]
    expires_at: datetime
    # the subscription the order provisioned, once reconciliation has seen it
    fulfilled_subscription_id: Optional[int]
    # always a stored row here
    created_at: datetime
    updated_at: datetime

    @field_validator("plan_snapshot", "previous_plan_snapshot", mode="before")
    @classmethod
    def _snapshot_as_json(cls, value: Any) -> Any:
        return value.to_json() if isinstance(value, PlanSnapshot) else value


class TransactionPageResponse(ResponseModel):
    items: list[TransactionResponse]
    total: int


class TransactionSummaryResponse(ResponseModel):
    report_currency: Currency
    total_count: int
    pending_count: int
    paid_count: int
    conversion_rate: Decimal
    revenue: Decimal
    average_check: Optional[Decimal]
    average_discount: Optional[Decimal]
    discount_amount: Decimal
    refunded_amount: Decimal


class TransactionGatewayListResponse(ResponseModel):
    items: list[PaymentGatewayType]
    total: int


class UnratedAnchorCountResponse(ResponseModel):
    currency: Currency
    count: int


class UnratedAnchorCountListResponse(ResponseModel):
    items: list[UnratedAnchorCountResponse]
    total: int


class CreateTestPaymentRequest(BaseModel):
    gateway_type: PaymentGatewayType
    channel: PurchaseChannel = PurchaseChannel.BOT


class TestPaymentResponse(ResponseModel):
    order_id: int
    confirmation_url: Optional[str]


class TestPaymentStatusResponse(ResponseModel):
    status: TransactionStatus


class PaymentWaitlistCountResponse(ResponseModel):
    total: int


class RollbackPreviewResponse(ResponseModel):
    available: bool
    blocked_reason: Optional[str]
    old_term_expired: bool


class RefundPreviewResponse(ResponseModel):
    refundable: bool
    reason: Optional[str]
    rollback: Optional[RollbackPreviewResponse]


class RefundTransactionRequest(BaseModel):
    rollback_subscription: bool


class PaymentCheckResponse(ResponseModel):
    transaction: TransactionResponse
    paid: bool


class RefundTransactionResponse(ResponseModel):
    transaction: TransactionResponse
    rollback_failed: bool


class OwnTransactionResponse(ResponseModel):
    id: int
    status: TransactionStatus
    final_price: Decimal
    # what the discounts were taken off, and which: the cabinet shows the saving
    base_price: Decimal
    change_credit: Decimal
    plan_discount_percent: int
    discount_percent: int
    discount_source: DiscountSource
    currency: Currency
    purchase_type: PurchaseType
    gateway_type: Optional[PaymentGatewayType]  # None: a free order
    plan_name: str
    plan_icon_emoji_id: Optional[str]
    plan_icon_emoji_fallback: Optional[str]
    duration_days: int
    created_at: Optional[datetime]
    # what a failed payment's "try again" reopens: the plan, and the subscription
    # a renewal or change was for
    plan_id: int
    target_subscription_id: Optional[int]

    @classmethod
    def from_dto(cls, order: TransactionDto, locale: Locale) -> "OwnTransactionResponse":
        return cls(
            id=order.id,
            status=order.status,
            final_price=order.final_price,
            base_price=order.base_price,
            change_credit=order.change_credit,
            plan_discount_percent=order.plan_discount_percent,
            discount_percent=order.discount_percent,
            discount_source=order.discount_source,
            currency=order.currency,
            purchase_type=order.purchase_type,
            gateway_type=order.gateway_type,
            plan_name=order.plan_snapshot.display_name(locale),
            plan_icon_emoji_id=order.plan_snapshot.icon_emoji_id,
            plan_icon_emoji_fallback=order.plan_snapshot.icon_emoji_fallback,
            duration_days=order.duration_days,
            created_at=order.created_at,
            plan_id=order.plan_snapshot.plan_id,
            target_subscription_id=order.target_subscription_id,
        )


class OwnTransactionListResponse(ResponseModel):
    items: list[OwnTransactionResponse]
    total: int
    page: int
    page_size: int


class PaymentMethodResponse(ResponseModel):
    gateway_type: PaymentGatewayType
    currency: Currency
    name: str
    requires_email: bool
    asks_email: bool
    recurring_available: bool = False
    recurring_required: bool = False


class PaymentMethodListResponse(ResponseModel):
    items: list[PaymentMethodResponse]
    total: int
