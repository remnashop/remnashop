from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from loguru import logger

from app.core.db.uow import UnitOfWork
from app.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    SubscriptionStatus,
    TransactionStatus,
)
from app.core.exceptions import AppError
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.checks import RecurringDebitChecks
from app.modules.recurring_payments.dto import RecurringPaymentDto, RecurringTerms
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import SAFE_REPOST_WINDOW, RecurringReason
from app.modules.recurring_payments.poller import RecurringPoller
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.settings import SettingsRepository
from app.modules.subscriptions import PlanSnapshot, SubscriptionDto, SubscriptionRepository
from app.modules.transactions import (
    CheckoutPricer,
    CreateTransactionDto,
    TransactionDto,
    TransactionRepository,
    YooKassaGateway,
)
from app.modules.users import UserRepository


class RecurringReservation:
    # creates this cycle's order once the renewal is due and still authorized; sends nothing

    def __init__(
        self,
        checks: RecurringDebitChecks,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        recurring_poller: RecurringPoller,
        transaction_repository: TransactionRepository,
        subscription_repository: SubscriptionRepository,
        user_repository: UserRepository,
        settings_repository: SettingsRepository,
        pricer: CheckoutPricer,
        uow: UnitOfWork,
    ) -> None:
        self._checks = checks
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._poller = recurring_poller
        self._transactions = transaction_repository
        self._subscriptions = subscription_repository
        self._users = user_repository
        self._settings = settings_repository
        self._pricer = pricer
        self._uow = uow

    async def reserve(self, mandate: RecurringPaymentDto) -> None:
        if not await self._reservation_available(mandate):
            return
        async with self._uow:
            if not mandate.enabled or not await self._checks.enabled():
                await self._checks.defer(mandate.subscription_id, RecurringReason.GATEWAY_DISABLED)
                return
            if await self._transactions.has_open_manual_order(
                mandate.subscription_id, datetime_now()
            ):
                await self._checks.defer(mandate.subscription_id)
                return
            source = (
                await self._transactions.get_by_id(mandate.source_transaction_id)
                if mandate.source_transaction_id is not None
                else None
            )
            subscription = await self._subscriptions.get_by_id(mandate.subscription_id)
            user = await self._users.find_by_id(subscription.user_id)
        if (
            source is None
            or source.status is not TransactionStatus.PAID
            or user is None
            or user.deleted_at is not None
            or user.is_blocked
        ):
            async with self._uow:
                await self._lifecycle.disable(
                    mandate.subscription_id, RecurringReason.SUBSCRIPTION_UNAVAILABLE
                )
            return
        try:
            async with self._uow:
                plan, user = await self._pricer.load_purchasable_plan(
                    user.id, source.plan_snapshot.plan_id, None, subscription.id
                )
            user = await self._pricer.drop_dead_promocode_discounts(user)
            # A one-shot discount is reserved by interactive checkouts, never by a timer.
            quote = await self._pricer.quote(
                plan,
                source.duration_days,
                Currency.RUB,
                user.model_copy(update={"purchase_discount": 0}),
            )
        except AppError:
            async with self._uow:
                await self._lifecycle.pause(
                    mandate.subscription_id, RecurringReason.PLAN_UNAVAILABLE
                )
            return

        async with self._uow:
            current = await self._recurring.get(subscription.id, for_update=True)
            terms = await self._reservation_terms(current, source, subscription.id)
            if terms is None or current is None:
                return
            shop = await self._settings.get_shop_settings()
            customer_email = shop.payment_email or user.email or source.customer_email
            gateway = await self._reservation_gateway(current, customer_email)
            if gateway is None:
                return
            vat_code = gateway.settings.vat_code
            subscription = await self._subscriptions.get_by_id_for_update(subscription.id)
            now = datetime_now()
            new_snapshot = PlanSnapshot.from_plan(
                plan,
                price_paid=quote.final_price,
                currency=Currency.RUB,
                duration_days=source.duration_days,
            )
            if not await self._valid_renewal(
                source, subscription, new_snapshot, quote.final_price, terms
            ):
                return
            if not await self._cycle_due(current, subscription.expire_at, terms):
                return
            order = await self._transactions.create(
                CreateTransactionDto(
                    user_id=user.id,
                    plan_id=plan.id,
                    plan_snapshot=new_snapshot,
                    duration_days=source.duration_days,
                    currency=Currency.RUB,
                    purchase_type=PurchaseType.RENEW,
                    channel=source.channel,
                    target_subscription_id=subscription.id,
                    gateway_type=PaymentGatewayType.YOOKASSA,
                    base_price=quote.base_price,
                    discount_percent=quote.discount_percent,
                    discount_source=quote.discount_source,
                    plan_discount_percent=quote.plan_discount_percent,
                    markup_percent=quote.markup_percent,
                    final_price=quote.final_price,
                    anchor_base_price=quote.anchor_base_price,
                    anchor_final_price=quote.anchor_final_price,
                    discount_promocode_id=quote.discount_promocode_id,
                    customer_email=customer_email,
                    idempotency_key=uuid4().hex,
                    expires_at=now + SAFE_REPOST_WINDOW,
                    # charged in the shop that holds the card
                    gateway_account=current.shop_id,
                    recurring_consent_id=current.consent_id,
                    is_recurring=True,
                    yookassa_receipt_vat_code=int(vat_code) if vat_code is not None else None,
                )
            )
            await self._lifecycle.set_pending(
                subscription.id, order.id, expire_at=subscription.expire_at
            )
        logger.info(f"Reserved recurring order '{order.id}' for subscription '{subscription.id}'")

    async def _reservation_available(self, mandate: RecurringPaymentDto) -> bool:
        async with self._uow:
            subscription = await self._subscriptions.get_by_id(mandate.subscription_id)
            terms = await self._recurring.consent_terms(mandate.consent_id)
            if subscription.status in {SubscriptionStatus.DELETED, SubscriptionStatus.DISABLED}:
                await self._lifecycle.close_for_plan_change(subscription.id)
                return False
            if terms and subscription.expire_at < datetime_now() - timedelta(
                hours=terms.max_overdue_hours
            ):
                await self._lifecycle.disable(
                    subscription.id, RecurringReason.RENEWAL_WINDOW_EXPIRED
                )
                return False
            return True

    async def _reservation_gateway(
        self, mandate: RecurringPaymentDto, customer_email: Optional[str]
    ) -> Optional[YooKassaGateway]:
        gateway = await self._poller.gateway()
        if not gateway.takes_payments_into(mandate.shop_id) or not mandate.payment_method_id:
            await self._lifecycle.pause(mandate.subscription_id, RecurringReason.SHOP_CHANGED)
            return None
        if gateway.settings.vat_code is not None and not customer_email:
            await self._lifecycle.pause(
                mandate.subscription_id, RecurringReason.CUSTOMER_EMAIL_REQUIRED
            )
            return None
        return gateway

    async def _reservation_terms(
        self, mandate: Optional[RecurringPaymentDto], source: TransactionDto, subscription_id: int
    ) -> Optional[RecurringTerms]:
        if mandate is None or not mandate.enabled or mandate.pending_transaction_id is not None:
            return None
        reason = mandate.last_error
        if reason and not reason.policy.allows_debit:
            return None
        if mandate.source_transaction_id != source.id or not await self._checks.enabled():
            await self._checks.defer(subscription_id)
            return None
        if not await self._checks.has_consent(mandate, source, source.base_price):
            return None
        return await self._recurring.consent_terms(mandate.consent_id)

    async def _valid_renewal(
        self,
        source: TransactionDto,
        subscription: SubscriptionDto,
        new_snapshot: PlanSnapshot,
        price: Decimal,
        terms: RecurringTerms,
    ) -> bool:
        now = datetime_now()
        if subscription.expire_at < now - timedelta(hours=terms.max_overdue_hours):
            await self._lifecycle.disable(subscription.id, RecurringReason.RENEWAL_WINDOW_EXPIRED)
            return False
        if (
            subscription.status
            not in {
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.EXPIRED,
                SubscriptionStatus.LIMITED,
            }
            or subscription.is_trial
            or subscription.plan_snapshot.plan_id != source.plan_id
            or source.plan_snapshot.terms_differ(subscription.plan_snapshot)
            or subscription.plan_snapshot.terms_differ(new_snapshot)
        ):
            await self._lifecycle.close_for_plan_change(subscription.id)
            return False
        if price <= 0 or price > source.base_price:
            await self._lifecycle.pause(subscription.id, RecurringReason.PRICE_CHANGED)
            return False
        return True

    async def _cycle_due(
        self, mandate: RecurringPaymentDto, expire_at: datetime, terms: RecurringTerms
    ) -> bool:
        now = datetime_now()
        scheduled = expire_at - timedelta(minutes=terms.lead_minutes)
        if now < scheduled:
            notice_lead = (await self._checks.policy()).notice_lead_minutes
            if now >= expire_at - timedelta(minutes=notice_lead):
                await self._lifecycle.notify_upcoming(
                    mandate.subscription_id, expire_at, terms, scheduled
                )
            await self._lifecycle.defer(mandate.subscription_id, scheduled)
            return False
        if mandate.first_failure_at is not None:
            deadlines = [
                value
                for value in (mandate.bank_retry_at, mandate.next_attempt_at)
                if value is not None
            ]
            deadline = max(deadlines) if deadlines else None
            if deadline is not None and now < deadline:
                await self._lifecycle.defer(mandate.subscription_id, deadline)
                return False
        await self._lifecycle.notify_upcoming(mandate.subscription_id, expire_at, terms, scheduled)
        return True
