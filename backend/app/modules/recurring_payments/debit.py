from datetime import datetime, timedelta
from typing import Optional

from app.core.db.uow import UnitOfWork
from app.core.enums import Locale, SubscriptionStatus, TransactionStatus
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.checks import RecurringDebitChecks
from app.modules.recurring_payments.dto import RecurringPaymentDto, RecurringTerms
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import RecurringReason
from app.modules.recurring_payments.poller import RecurringPoller, pending_expired
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.submission import (
    RecurringSubmission,
    SubmissionOutcome,
    submit_recurring,
)
from app.modules.subscriptions import SubscriptionDto, SubscriptionRepository
from app.modules.transactions import (
    PaymentTexts,
    TransactionDto,
    TransactionRepository,
    YooKassaGateway,
)
from app.modules.users import UserDto, UserRepository


class RecurringDebit:
    # sends a reserved order to YooKassa once, then follows it until it settles

    def __init__(
        self,
        checks: RecurringDebitChecks,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        recurring_poller: RecurringPoller,
        transaction_repository: TransactionRepository,
        subscription_repository: SubscriptionRepository,
        user_repository: UserRepository,
        payment_texts: PaymentTexts,
        uow: UnitOfWork,
    ) -> None:
        self._checks = checks
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._poller = recurring_poller
        self._transactions = transaction_repository
        self._subscriptions = subscription_repository
        self._users = user_repository
        self._payment_texts = payment_texts
        self._uow = uow

    async def charge_or_poll(self, subscription_id: int) -> None:
        async with self._uow:
            if await self._lifecycle.retire_pending(subscription_id):
                return
        context = await self._pending_context(subscription_id)
        if context is None:
            return
        _, order, gateway = context
        if order.status is not TransactionStatus.PENDING:
            if order.external_payment_id is not None:
                await self._poller.poll(subscription_id, order, gateway)
            return
        if order.external_payment_id is None:
            await self._submit(subscription_id, order)
            async with self._uow:
                order = await self._transactions.get_by_id(order.id)
        if order.external_payment_id is not None:
            await self._poller.poll(subscription_id, order, gateway)

    async def _submit(
        self,
        subscription_id: int,
        order: TransactionDto,
    ) -> Optional[RecurringSubmission]:
        async with self._uow:
            context = await self._submission_context(subscription_id, order)
            if context is None:
                return None
            order, mandate, terms, gateway = context
            unsubmitted = mandate.submitted_at is None
            submitted_at = await self._recurring.mark_submitted(subscription_id)
        # intent is committed before the request: a killed worker must not turn a
        # possibly charged key into an unsent order
        async with self._uow:
            context = await self._submission_context(subscription_id, order)
            if context is None:
                await self._abandon_submission(subscription_id, order, unsubmitted, submitted_at)
                return None
            order, mandate, terms, gateway = context
            first_attempt = unsubmitted and mandate.submitted_at == submitted_at
            text = await self._payment_texts.describe(order, Locale.RU)
        # no transaction or row lock while the provider answers; a withdrawal landing
        # now stops the next cycle, this already-sent payment may still complete
        result = await submit_recurring(
            gateway, order, text, mandate.payment_method_id or "", first_attempt=first_attempt
        )
        async with self._uow:
            current = await self._transactions.get_by_id_for_update(order.id)
            latest = await self._recurring.get(subscription_id, for_update=True)
            if (
                latest is not None
                and latest.pending_transaction_id == order.id
                and latest.submitted_at == mandate.submitted_at
                and current.status is TransactionStatus.PENDING
            ):
                await self._persist_submission(subscription_id, current, latest, terms, result)
        return result

    async def _pending_context(
        self, subscription_id: int
    ) -> Optional[tuple[RecurringPaymentDto, TransactionDto, YooKassaGateway]]:
        async with self._uow:
            current = await self._recurring.get(subscription_id)
            if current is None or current.pending_transaction_id is None:
                return None
            order = await self._transactions.get_by_id_for_update(current.pending_transaction_id)
            mandate = await self._recurring.get(subscription_id, for_update=True)
            if mandate is None or mandate.pending_transaction_id != order.id:
                return None
            if order.status is TransactionStatus.PAID:
                await self._checks.defer(subscription_id)
                return None
            terms = await self._recurring.consent_terms(mandate.consent_id)
            gateway = await self._poller.gateway()
            if not gateway.takes_payments_into(mandate.shop_id):
                if order.external_payment_id and pending_expired(mandate, order, terms):
                    # outcome unknown: ends the attempt, so the customer may pay by hand
                    await self._lifecycle.retire_pending(
                        subscription_id, order.id, force_unknown=True
                    )
                else:
                    await self._lifecycle.pause(subscription_id, RecurringReason.SHOP_CHANGED)
                    await self._lifecycle.cancel_unsent(subscription_id, order.id)
                return None
            await self._checks.defer(subscription_id)
            if order.external_payment_id is None and order.status is TransactionStatus.PENDING:
                if (
                    not mandate.enabled
                    or not mandate.payment_method_id
                    or not await self._checks.enabled()
                    or await self._transactions.has_open_manual_order(
                        subscription_id, datetime_now()
                    )
                ):
                    await self._lifecycle.cancel_unsent(subscription_id, order.id)
                    return None
        return mandate, order, gateway

    async def _submission_context(
        self,
        subscription_id: int,
        order: TransactionDto,
    ) -> Optional[tuple[TransactionDto, RecurringPaymentDto, RecurringTerms, YooKassaGateway]]:
        order = await self._transactions.get_by_id_for_update(order.id)
        if order.status is not TransactionStatus.PENDING or order.external_payment_id is not None:
            return None
        mandate = await self._recurring.get(subscription_id, for_update=True)
        if mandate is None or mandate.pending_transaction_id != order.id:
            return None
        if not mandate.enabled or not mandate.payment_method_id or not await self._checks.enabled():
            await self._lifecycle.cancel_unsent(subscription_id, order.id)
            return None
        if await self._transactions.has_open_manual_order(subscription_id, datetime_now()):
            await self._checks.defer(subscription_id)
            return None
        if not await self._checks.has_consent(mandate, order, order.final_price):
            await self._lifecycle.cancel_unsent(subscription_id, order.id)
            return None
        terms = await self._recurring.consent_terms(mandate.consent_id)
        if terms is None:
            return None
        gateway = await self._poller.gateway()
        if not gateway.takes_payments_into(mandate.shop_id):
            await self._lifecycle.pause(subscription_id, RecurringReason.SHOP_CHANGED)
            await self._lifecycle.cancel_unsent(subscription_id, order.id)
            return None
        subscription = await self._subscriptions.get_by_id(subscription_id)
        if _cycle_superseded(mandate, subscription):
            await self._lifecycle.cancel_unsent(subscription_id, order.id)
            return None
        user = await self._users.find_by_id(order.user_id)
        if _subscription_unavailable(user, subscription, order, terms):
            reason = (
                RecurringReason.RENEWAL_WINDOW_EXPIRED
                if subscription.expire_at
                < datetime_now() - timedelta(hours=terms.max_overdue_hours)
                else RecurringReason.SUBSCRIPTION_UNAVAILABLE
            )
            await self._lifecycle.disable(subscription_id, reason)
            await self._lifecycle.cancel_unsent(subscription_id, order.id)
            return None
        return order, mandate, terms, gateway

    async def _abandon_submission(
        self,
        subscription_id: int,
        order: TransactionDto,
        first_attempt: bool,
        submitted_at: datetime,
    ) -> None:
        if not first_attempt:
            return
        current = await self._transactions.get_by_id_for_update(order.id)
        mandate = await self._recurring.get(subscription_id, for_update=True)
        if (
            mandate
            and mandate.pending_transaction_id == order.id
            and mandate.submitted_at == submitted_at
            and current.status is TransactionStatus.PENDING
            and current.external_payment_id is None
        ):
            await self._recurring.clear_submission(subscription_id)
            await self._lifecycle.cancel_unsent(subscription_id, order.id)

    async def _persist_submission(
        self,
        subscription_id: int,
        order: TransactionDto,
        mandate: RecurringPaymentDto,
        terms: RecurringTerms,
        result: RecurringSubmission,
    ) -> None:
        # The caller owns the order and current mandate until this entire outcome commits.
        if result.outcome is SubmissionOutcome.AMBIGUOUS:
            await self._checks.defer(
                subscription_id, result.reason or RecurringReason.PROVIDER_UNAVAILABLE
            )
            return
        if result.outcome is SubmissionOutcome.ACCEPTED:
            moved = await self._transactions.mark_status_if(
                order.id,
                TransactionStatus.PENDING,
                current=frozenset({TransactionStatus.PENDING}),
                external_payment_id=result.payment_id,
            )
            if moved:
                await self._lifecycle.clear_error(subscription_id)
            return
        moved = await self._transactions.mark_status_if(
            order.id, TransactionStatus.FAILED, current=frozenset({TransactionStatus.PENDING})
        )
        if not moved:
            return
        # refused before any charge: the method stays, the reason decides whether to retry
        await self._lifecycle.release_pending(
            subscription_id,
            order.id,
            reason=result.reason or RecurringReason.MERCHANT_UNAVAILABLE,
            retry_minutes=terms.retry_minutes,
        )


def _cycle_superseded(mandate: RecurringPaymentDto, subscription: SubscriptionDto) -> bool:
    return mandate.cycle_expire_at is None or subscription.expire_at > mandate.cycle_expire_at


def _subscription_unavailable(
    user: Optional[UserDto],
    subscription: SubscriptionDto,
    order: TransactionDto,
    terms: RecurringTerms,
) -> bool:
    return (
        user is None
        or user.is_blocked
        or user.deleted_at is not None
        or subscription.expire_at < datetime_now() - timedelta(hours=terms.max_overdue_hours)
        or subscription.status in {SubscriptionStatus.DELETED, SubscriptionStatus.DISABLED}
        or subscription.plan_snapshot.terms_differ(order.plan_snapshot)
        or subscription.plan_snapshot.plan_id != order.plan_id
    )
