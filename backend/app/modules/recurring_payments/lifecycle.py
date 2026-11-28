from dataclasses import replace
from datetime import datetime
from typing import Final, Optional

from loguru import logger

from app.core.enums import TransactionStatus
from app.core.ports import EventPublisher
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.dto import PaidOrderFacts, RecurringPaymentDto, RecurringTerms
from app.modules.recurring_payments.policy import (
    POLICY_RECHECK_DELAY,
    SAFE_REPOST_WINDOW,
    ConsentChannel,
    RecurringReason,
    provider_cancellation_reason,
)
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.transitions import (
    MandateEffects,
    adopt_paid_order,
    apply_cancel_unsent,
    apply_clear_error,
    apply_customer_toggle,
    apply_defer,
    apply_disable,
    apply_failed_order,
    apply_late_cancel_while_inactive,
    apply_recurring_fulfilled,
    apply_release_pending,
    apply_resume,
    apply_retire,
    apply_set_pending,
    apply_upcoming,
)
from app.modules.transactions import TransactionDto, TransactionRepository

_UNRESOLVED: Final[frozenset[TransactionStatus]] = frozenset(
    {TransactionStatus.PENDING, TransactionStatus.FAILED, TransactionStatus.CANCELED}
)
_FAILED: Final[frozenset[TransactionStatus]] = frozenset(
    {TransactionStatus.FAILED, TransactionStatus.CANCELED}
)


class RecurringLifecycle:
    # lock order everywhere: order, then mandate

    def __init__(
        self,
        repository: RecurringPaymentRepository,
        transaction_repository: TransactionRepository,
        event_publisher: EventPublisher,
    ) -> None:
        self._repository = repository
        self._transactions = transaction_repository
        self._event_publisher = event_publisher

    async def _owner(self, subscription_id: int) -> Optional[int]:
        facts = await self._repository.subscription_facts(subscription_id)
        return facts.user_id if facts else None

    async def _commit(
        self,
        before: RecurringPaymentDto,
        after: RecurringPaymentDto,
        effects: Optional[MandateEffects] = None,
    ) -> None:
        await self._repository.save(before, after)
        if effects is None:
            return
        for consent_id, channel in effects.revoked_consents:
            await self._repository.revoke_consent_id(consent_id, channel=channel)
        if effects.attached_consent_id is not None:
            await self._repository.attach_consent(
                effects.attached_consent_id, after.subscription_id
            )
        for notice in effects.notices:
            await self._event_publisher.publish(notice)

    async def _locked(self, subscription_id: int) -> Optional[RecurringPaymentDto]:
        return await self._repository.get(subscription_id, for_update=True)

    async def notify_upcoming(
        self,
        subscription_id: int,
        expire_at: datetime,
        terms: RecurringTerms,
        scheduled_at: datetime,
    ) -> None:
        before = await self._locked(subscription_id)
        if before is None:
            return
        after = replace(before)
        effects = apply_upcoming(after, expire_at, terms, scheduled_at)
        await self._commit(before, after, effects)

    async def set_enabled(
        self,
        subscription_id: int,
        enabled: bool,
        *,
        consent_id: Optional[int] = None,
        disabled_at: Optional[datetime] = None,
    ) -> None:
        now = datetime_now()
        await self._repository.insert_if_missing(subscription_id, now)
        before = await self._locked(subscription_id)
        facts = await self._repository.subscription_facts(subscription_id)
        if before is None or facts is None:
            return
        after = replace(before)
        apply_customer_toggle(
            after,
            enabled=enabled,
            consent_id=consent_id,
            disabled_at=disabled_at,
            subscription_expire_at=facts.expire_at,
            now=now,
        )
        await self._commit(before, after)

    async def revoke_consent(
        self,
        subscription_id: int,
        *,
        channel: ConsentChannel,
        event_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        # the mandate lock serializes a withdrawal with the worker's claim
        mandate = await self._locked(subscription_id)
        if mandate is None or mandate.consent_id is None:
            return
        await self._repository.revoke_consent_id(
            mandate.consent_id, channel=channel, event_id=event_id, ip_address=ip_address
        )

    async def defer(
        self, subscription_id: int, until: datetime, error: Optional[RecurringReason] = None
    ) -> None:
        before = await self._locked(subscription_id)
        if before is None:
            return
        after = replace(before)
        effects = apply_defer(after, until, error, await self._owner(subscription_id))
        await self._commit(before, after, effects)

    async def pause(
        self,
        subscription_id: int,
        reason: RecurringReason,
        *,
        until: Optional[datetime] = None,
    ) -> None:
        await self.defer(subscription_id, until or datetime_now() + POLICY_RECHECK_DELAY, reason)

    async def disable(self, subscription_id: int, reason: RecurringReason) -> None:
        before = await self._locked(subscription_id)
        if before is None:
            return
        after = replace(before)
        effects = apply_disable(after, reason, await self._owner(subscription_id), datetime_now())
        await self._commit(before, after, effects)

    async def resume(self, subscription_id: int) -> None:
        before = await self._locked(subscription_id)
        if before is None:
            return
        after = replace(before)
        if apply_resume(after, datetime_now()):
            await self._commit(before, after)

    async def clear_error(self, subscription_id: int) -> None:
        before = await self._locked(subscription_id)
        if before is None:
            return
        after = replace(before)
        apply_clear_error(after)
        await self._commit(before, after)

    async def close_for_plan_change(self, subscription_id: int) -> None:
        current = await self._repository.get(subscription_id)
        if current is None:
            return
        if current.pending_transaction_id is not None:
            await self._transactions.get_by_id_for_update(current.pending_transaction_id)
        mandate = await self._locked(subscription_id)
        if mandate is None:
            return
        await self._repository.revoke_consent_id(
            mandate.consent_id, channel=ConsentChannel.PLAN_CHANGE
        )
        await self.disable(subscription_id, RecurringReason.SUBSCRIPTION_CHANGED)

    async def on_refunded(self, order: TransactionDto) -> None:
        # a refund means the customer disputes paying; no further automatic charge
        subscription_id = order.fulfilled_subscription_id or order.target_subscription_id
        if subscription_id is None:
            return
        mandate = await self._locked(subscription_id)
        if mandate is None:
            return
        await self._repository.revoke_consent_id(mandate.consent_id, channel=ConsentChannel.REFUND)
        await self.disable(subscription_id, RecurringReason.REFUNDED)

    async def close_overdue(self, now: datetime, *, limit: int) -> None:
        for subscription_id in await self._repository.overdue_ids(now, limit=limit):
            current = await self._repository.get(subscription_id)
            reason = current.last_error if current else None
            await self.disable(
                subscription_id,
                reason
                if reason and reason.policy.terminal
                else RecurringReason.RENEWAL_WINDOW_EXPIRED,
            )

    async def set_pending(
        self, subscription_id: int, transaction_id: int, *, expire_at: datetime
    ) -> None:
        before = await self._locked(subscription_id)
        if before is None:
            return
        after = replace(before)
        apply_set_pending(after, transaction_id, expire_at, datetime_now())
        await self._commit(before, after)

    async def release_pending(
        self,
        subscription_id: int,
        transaction_id: int,
        *,
        reason: Optional[RecurringReason],
        retry_minutes: int = 5,
    ) -> None:
        order = await self._transactions.get_by_id_for_update(transaction_id)
        if order.status not in _FAILED:
            return
        before = await self._locked(subscription_id)
        if before is None or before.pending_transaction_id != transaction_id:
            return
        after = replace(before)
        effects = apply_release_pending(
            after, reason, retry_minutes, await self._owner(subscription_id), datetime_now()
        )
        await self._commit(before, after, effects)

    async def fail_pending(
        self,
        subscription_id: int,
        reason: RecurringReason,
        *,
        transaction_id: Optional[int] = None,
        permanent: bool = False,
    ) -> None:
        current = await self._repository.get(subscription_id)
        expected = transaction_id or (current.pending_transaction_id if current else None)
        if expected is None:
            return
        # fulfillment's lock order; an old response never detaches a new attempt
        order = await self._transactions.get_by_id_for_update(expected)
        if order.status not in _FAILED:
            return
        before = await self._locked(subscription_id)
        if before is None or before.pending_transaction_id != expected:
            return
        await self._fail(before, order, reason, permanent)

    async def _fail(
        self,
        before: RecurringPaymentDto,
        order: TransactionDto,
        reason: RecurringReason,
        permanent: bool,
        *,
        start: Optional[RecurringPaymentDto] = None,
    ) -> None:
        facts = await self._repository.subscription_facts(before.subscription_id)
        after = replace(start or before)
        effects = apply_failed_order(
            after,
            order_id=order.id,
            amount=order.final_price,
            currency=order.currency,
            reason=reason,
            permanent=permanent,
            terms=await self._repository.consent_terms((start or before).consent_id),
            subscription_expire_at=facts.expire_at if facts else None,
            user_id=facts.user_id if facts else None,
            now=datetime_now(),
        )
        await self._commit(before, after, effects)

    async def retire_pending(
        self,
        subscription_id: int,
        transaction_id: Optional[int] = None,
        *,
        force_unknown: bool = False,
        notify: bool = True,
    ) -> bool:
        if transaction_id is None:
            current = await self._repository.get(subscription_id)
            if current is None or current.pending_transaction_id is None:
                return False
            transaction_id = current.pending_transaction_id
        order = await self._transactions.get_by_id_for_update(transaction_id)
        if (
            not order.is_recurring
            or order.target_subscription_id != subscription_id
            or order.status not in _UNRESOLVED
            or (order.external_payment_id is not None and not force_unknown)
        ):
            return False
        before = await self._locked(subscription_id)
        if before is None or before.pending_transaction_id != transaction_id:
            return False
        now = datetime_now()
        if (
            not force_unknown
            and order.status is TransactionStatus.PENDING
            and order.created_at is not None
            and order.created_at > now - SAFE_REPOST_WINDOW
        ):
            return False
        unknown = before.submitted_at is not None or order.external_payment_id is not None
        reconnected = unknown and (
            order.created_at is None
            or await self._transactions.has_manual_renewal_since(
                subscription_id, since=order.created_at, plan_id=order.plan_id
            )
        )
        after = replace(before)
        status, effects = apply_retire(
            after,
            unknown=unknown,
            reconnected=reconnected,
            force_unknown=force_unknown,
            notify=notify,
            user_id=await self._owner(subscription_id),
            now=now,
        )
        await self._transactions.mark_status_if(order.id, status, current=frozenset({order.status}))
        await self._commit(before, after, effects)
        logger.warning(
            f"Retired recurring order '{transaction_id}'; provider outcome unknown: {unknown}"
        )
        return True

    async def cancel_unsent(self, subscription_id: int, transaction_id: int) -> bool:
        order = await self._transactions.get_by_id_for_update(transaction_id)
        before = await self._locked(subscription_id)
        if (
            before is None
            or before.pending_transaction_id != transaction_id
            or order.status is not TransactionStatus.PENDING
            or order.external_payment_id is not None
            or before.submitted_at is not None
        ):
            return False
        after = replace(before)
        apply_cancel_unsent(after)
        await self._transactions.mark_status_if(
            order.id, TransactionStatus.CANCELED, current=frozenset({TransactionStatus.PENDING})
        )
        await self._commit(before, after)
        return True

    async def on_canceled(self, order_id: int, provider_reason: Optional[str]) -> None:
        order = await self._transactions.get_by_id_for_update(order_id)
        if (
            not order.is_recurring
            or order.status is not TransactionStatus.CANCELED
            or order.target_subscription_id is None
        ):
            return
        subscription_id = order.target_subscription_id
        before = await self._locked(subscription_id)
        if before is None:
            return
        resolved = provider_cancellation_reason(provider_reason)
        if before.pending_transaction_id != order.id:
            if (
                before.pending_transaction_id is not None
                or before.submitted_at is None
                or await self._transactions.latest_recurring_order_id(subscription_id) != order.id
            ):
                return
            active = (
                not before.customer_disabled
                and before.consent_id == order.recurring_consent_id
                and before.payment_method_id is not None
                and await self._repository.consent_terms(before.consent_id) is not None
            )
            if not active:
                after = replace(before)
                effects = apply_late_cancel_while_inactive(after, resolved, datetime_now())
                await self._commit(before, after, effects)
                return
            # the lost attempt is adopted, then failed like a tracked one
            adopted = replace(before, pending_transaction_id=order.id, enabled=True)
            await self._fail(before, order, resolved, resolved.policy.terminal, start=adopted)
            return
        await self._fail(before, order, resolved, resolved.policy.terminal)

    async def on_fulfilled(self, order: TransactionDto, subscription_id: int) -> None:
        now = datetime_now()
        if order.is_recurring:
            await self._on_recurring_fulfilled(order, subscription_id, now)
            return
        await self.retire_pending(subscription_id)
        previous = (
            await self._repository.get(order.target_subscription_id)
            if order.target_subscription_id is not None
            and order.target_subscription_id != subscription_id
            else None
        )
        if previous is not None and previous.customer_disabled:
            await self.set_enabled(subscription_id, False, disabled_at=previous.disabled_at)
        if (
            order.recurring_consent_id is None
            and await self._repository.get(subscription_id) is None
        ):
            return
        await self._repository.insert_if_missing(subscription_id, now)
        before = await self._locked(subscription_id)
        if before is None or (before.source_transaction_id or 0) >= order.id:
            return
        after = replace(before)
        effects = adopt_paid_order(
            after,
            PaidOrderFacts(
                id=order.id,
                user_id=order.user_id,
                status=order.status,
                gateway_type=order.gateway_type,
                is_test=order.is_test,
                is_recurring=order.is_recurring,
                recurring_consent_id=order.recurring_consent_id,
                saved_payment_method_id=order.saved_payment_method_id,
                payment_method_shop_id=order.payment_method_shop_id,
                final_price=order.final_price,
                currency=order.currency,
            ),
            consent=await self._repository.consent_facts(order.recurring_consent_id),
            current_consent_active=await self._repository.consent_terms(before.consent_id)
            is not None,
            now=now,
        )
        await self._commit(before, after, effects)

    async def _on_recurring_fulfilled(
        self, order: TransactionDto, subscription_id: int, now: datetime
    ) -> None:
        before = await self._locked(subscription_id)
        if before is None:
            return
        after = replace(before)
        changed = apply_recurring_fulfilled(
            after,
            order_id=order.id,
            order_consent_id=order.recurring_consent_id,
            latest_is_order=await self._transactions.latest_recurring_order_id(subscription_id)
            == order.id,
            consent_active=await self._repository.consent_terms(before.consent_id) is not None,
            now=now,
        )
        if changed:
            await self._commit(before, after)
