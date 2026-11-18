from datetime import timedelta
from decimal import Decimal

from app.core.db.uow import UnitOfWork
from app.core.enums import PaymentGatewayType, PurchaseType, SubscriptionStatus, TransactionStatus
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.modules.gateways import GatewayRepository, yookassa_recurring_enabled
from app.modules.recurring_payments.dto import RecurringPaymentStateDto
from app.modules.recurring_payments.policy import (
    RecurringState,
    RetryKind,
    classify,
    recurring_policy,
)
from app.modules.recurring_payments.ports import RecurringTermsTexts
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.terms import build_recurring_terms
from app.modules.subscriptions import SubscriptionRepository, get_owned_target
from app.modules.transactions import TransactionRepository
from app.modules.users import UserDto


class GetOwnRecurringPaymentUseCase(UseCase[int, RecurringPaymentStateDto, UserDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        recurring_repository: RecurringPaymentRepository,
        transaction_repository: TransactionRepository,
        subscription_repository: SubscriptionRepository,
        gateway_repository: GatewayRepository,
        uow: UnitOfWork,
        recurring_terms_texts: RecurringTermsTexts,
    ) -> None:
        self._recurring = recurring_repository
        self._transactions = transaction_repository
        self._subscriptions = subscription_repository
        self._gateways = gateway_repository
        self._uow = uow
        self._recurring_terms_texts = recurring_terms_texts

    async def _execute(self, actor: UserDto, data: int) -> RecurringPaymentStateDto:
        async with self._uow:
            subscription = await get_owned_target(self._subscriptions, data, actor.id)
            mandate = await self._recurring.get(data)
            gateway = await self._gateways.get_by_type(PaymentGatewayType.YOOKASSA)
            if mandate is None and not yookassa_recurring_enabled(gateway.values):
                # opened on every subscription card: a shop without auto-renewal stops here
                return RecurringPaymentStateDto(
                    subscription_id=data, enabled=False, available=False
                )
            settings = await self._gateways.get_raw_settings(PaymentGatewayType.YOOKASSA)
            source = (
                await self._transactions.get_by_id(mandate.source_transaction_id)
                if mandate and mandate.source_transaction_id is not None
                else None
            )
        reason = mandate.last_error if mandate else None
        available = bool(
            mandate
            and mandate.payment_method_id
            and source
            and gateway.is_active
            and gateway.is_configured
            and yookassa_recurring_enabled(gateway.values)
            and mandate.shop_id == settings.get("shop_id")
            and subscription.status not in {SubscriptionStatus.DELETED, SubscriptionStatus.DISABLED}
            and not subscription.is_trial
            and subscription.plan_snapshot.plan_id == source.plan_id
            and source.status is TransactionStatus.PAID
            and source.duration_days > 0
            and source.base_price > 0
            and not (reason and reason.policy.block_enable)
            and not (mandate.submitted_at and mandate.pending_transaction_id is None)
            and source.plan_snapshot.terms_differ(subscription.plan_snapshot) is False
        )
        async with self._uow:
            authorized = (
                await self._recurring.consent_terms(mandate.consent_id) if mandate else None
            )
        state = classify(mandate) if mandate else RecurringState.DISABLED
        enabled = bool(mandate and mandate.enabled)
        available = bool(available and (authorized or not enabled))
        paused = bool(
            mandate
            and not mandate.customer_disabled
            and (state is RecurringState.ATTENTION or (enabled and not available))
        )
        retrying = state is RecurringState.RETRYING and available
        payment_pending = bool(mandate and mandate.pending_transaction_id is not None)
        recheck = bool(
            reason
            and (
                reason.policy.retry is RetryKind.TECHNICAL
                or (reason.policy.retry is RetryKind.POLL and payment_pending)
            )
        )
        next_retry_at = (
            mandate.next_attempt_at
            if mandate
            and not mandate.customer_disabled
            and (retrying or payment_pending or recheck)
            else None
        )
        next_payment_at = next_retry_at if retrying and available else None
        if enabled and available and authorized and next_payment_at is None and not payment_pending:
            next_payment_at = subscription.expire_at - timedelta(minutes=authorized.lead_minutes)
        terms = (
            await build_recurring_terms(
                texts=self._recurring_terms_texts,
                policy=recurring_policy(settings),
                user_id=actor.id,
                plan_id=source.plan_snapshot.plan_id,
                target_subscription_id=data,
                purchase_type=PurchaseType.RENEW,
                initial_amount=Decimal(0),
                amount_limit=source.base_price,
                currency=source.currency,
                duration_days=source.duration_days,
                locale=actor.language,
            )
            if available and source
            else None
        )
        return RecurringPaymentStateDto(
            subscription_id=data,
            terms=terms,
            accepted_terms=authorized,
            enabled=enabled,
            can_disable=bool(mandate and not mandate.customer_disabled and authorized),
            available=available,
            customer_disabled=bool(mandate and mandate.customer_disabled),
            paused=paused,
            retrying=retrying,
            payment_pending=payment_pending,
            payment_in_flight=bool(
                payment_pending and mandate and mandate.submitted_at is not None
            ),
            next_retry_at=next_retry_at,
            amount_limit=source.base_price if source else None,
            currency=source.currency if source else None,
            duration_days=source.duration_days if source else None,
            next_payment_at=next_payment_at,
            last_error=mandate.last_error if mandate else None,
        )
