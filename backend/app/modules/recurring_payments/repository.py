from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.filters import in_ids
from app.core.db.models.recurring_consent import RecurringConsent
from app.core.db.models.recurring_payment import RecurringPayment
from app.core.db.models.subscription import Subscription
from app.core.enums import PurchaseChannel
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.dto import (
    ConsentFacts,
    RecurringConsentDto,
    RecurringPaymentDto,
    RecurringTerms,
)
from app.modules.recurring_payments.policy import ConsentChannel, stored_reason
from app.modules.recurring_payments.queries import due_for_work, renewal_window_expired


@dataclass(frozen=True, kw_only=True)
class SubscriptionFacts:
    user_id: int
    expire_at: datetime


class RecurringPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _to_dto(self, row: RecurringPayment) -> RecurringPaymentDto:
        return RecurringPaymentDto(
            subscription_id=row.subscription_id,
            source_transaction_id=row.source_transaction_id,
            payment_method_id=row.payment_method_id,
            shop_id=row.shop_id,
            enabled=row.enabled,
            customer_disabled=row.customer_disabled,
            last_error=stored_reason(row.last_error),
            pending_transaction_id=row.pending_transaction_id,
            submitted_at=row.submitted_at,
            disabled_at=row.disabled_at,
            consent_id=row.consent_id,
            first_failure_at=row.first_failure_at,
            retry_count=row.retry_count,
            cycle_expire_at=row.cycle_expire_at,
            pending_since=row.pending_since,
            upcoming_notified_for=row.upcoming_notified_for,
            next_attempt_at=row.next_attempt_at,
            leased_until=row.leased_until,
            bank_retry_at=row.bank_retry_at,
        )

    async def get(
        self, subscription_id: int, *, for_update: bool = False
    ) -> Optional[RecurringPaymentDto]:
        stmt = select(RecurringPayment).where(RecurringPayment.subscription_id == subscription_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = await self.session.scalar(stmt.execution_options(populate_existing=True))
        return self._to_dto(row) if row is not None else None

    async def save(self, before: RecurringPaymentDto, after: RecurringPaymentDto) -> None:
        old, new = asdict(before), asdict(after)
        changed: dict[str, Any] = {key: value for key, value in new.items() if old[key] != value}
        if not changed:
            return
        await self.session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == after.subscription_id)
            .values(**changed)
        )

    async def insert_if_missing(self, subscription_id: int, now: datetime) -> None:
        # serializes enrollment of two payments for the same subscription
        await self.session.execute(
            insert(RecurringPayment)
            .values(subscription_id=subscription_id, enabled=False, next_attempt_at=now)
            .on_conflict_do_nothing(index_elements=[RecurringPayment.subscription_id])
        )

    async def subscription_facts(self, subscription_id: int) -> Optional[SubscriptionFacts]:
        row = (
            await self.session.execute(
                select(Subscription.user_id, Subscription.expire_at).where(
                    Subscription.id == subscription_id
                )
            )
        ).first()
        return SubscriptionFacts(user_id=row.user_id, expire_at=row.expire_at) if row else None

    async def list_due(
        self,
        now: datetime,
        *,
        due_before: datetime,
        limit: int,
        pending: Optional[bool] = None,
        claim_until: Optional[datetime] = None,
    ) -> list[int]:
        statement = (
            select(RecurringPayment.subscription_id)
            .join(Subscription, Subscription.id == RecurringPayment.subscription_id)
            .outerjoin(RecurringConsent, RecurringConsent.id == RecurringPayment.consent_id)
            .where(due_for_work(now, due_before=due_before))
            .order_by(RecurringPayment.next_attempt_at, RecurringPayment.subscription_id)
            .limit(limit)
        )
        if pending is not None:
            statement = statement.where(
                RecurringPayment.pending_transaction_id.is_not(None)
                if pending
                else RecurringPayment.pending_transaction_id.is_(None)
            )
        if claim_until is not None:
            statement = statement.with_for_update(of=RecurringPayment, skip_locked=True)
        ids = list(await self.session.scalars(statement))
        if ids and claim_until is not None:
            await self.session.execute(
                update(RecurringPayment)
                .where(in_ids(RecurringPayment.subscription_id, ids))
                .values(leased_until=claim_until)
            )
        return ids

    async def overdue_ids(self, now: datetime, *, limit: int) -> list[int]:
        return list(
            await self.session.scalars(
                select(RecurringPayment.subscription_id)
                .join(Subscription, Subscription.id == RecurringPayment.subscription_id)
                .outerjoin(RecurringConsent, RecurringConsent.id == RecurringPayment.consent_id)
                .where(
                    RecurringPayment.enabled.is_(True),
                    RecurringPayment.pending_transaction_id.is_(None),
                    renewal_window_expired(now),
                )
                .order_by(Subscription.expire_at, RecurringPayment.subscription_id)
                .limit(limit)
                .with_for_update(of=RecurringPayment, skip_locked=True)
            )
        )

    async def record_consent(
        self,
        terms: RecurringTerms,
        *,
        channel: PurchaseChannel,
        telegram_id: Optional[int],
        event_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> int:
        consent = RecurringConsent(
            user_id=terms.user_id,
            owner_user_id=terms.user_id,
            subscription_id=terms.target_subscription_id,
            channel=channel.value,
            telegram_id=telegram_id,
            event_id=event_id,
            ip_address=ip_address,
            terms=terms.model_dump(mode="json"),
            accepted_at=datetime_now(),
        )
        self.session.add(consent)
        await self.session.flush()
        return consent.id

    async def consent_terms(self, consent_id: Optional[int]) -> Optional[RecurringTerms]:
        consent = (
            await self.session.get(RecurringConsent, consent_id, populate_existing=True)
            if consent_id is not None
            else None
        )
        if consent is None or consent.revoked_at is not None:
            return None
        try:
            return RecurringTerms.model_validate(consent.terms).model_copy(
                update={"user_id": consent.owner_user_id}
            )
        except ValueError:
            return None

    async def latest_consent(self, subscription_id: int) -> Optional[RecurringConsentDto]:
        consent = await self.session.scalar(
            select(RecurringConsent)
            .where(RecurringConsent.subscription_id == subscription_id)
            .order_by(RecurringConsent.accepted_at.desc(), RecurringConsent.id.desc())
            .limit(1)
        )
        if consent is None:
            return None
        return RecurringConsentDto(
            terms=RecurringTerms.model_validate(consent.terms),
            channel=PurchaseChannel(consent.channel),
            accepted_at=consent.accepted_at,
            revoked_at=consent.revoked_at,
            revoked_channel=(
                ConsentChannel(consent.revoked_channel) if consent.revoked_channel else None
            ),
        )

    async def consent_facts(self, consent_id: Optional[int]) -> Optional[ConsentFacts]:
        if consent_id is None:
            return None
        consent = await self.session.get(RecurringConsent, consent_id, populate_existing=True)
        if consent is None:
            return None
        return ConsentFacts(
            id=consent.id,
            owner_user_id=consent.owner_user_id,
            revoked=consent.revoked_at is not None,
            accepted_at=consent.accepted_at,
        )

    async def revoke_consent_id(
        self,
        consent_id: Optional[int],
        *,
        channel: ConsentChannel,
        event_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        if consent_id is None:
            return
        await self.session.execute(
            update(RecurringConsent)
            .where(RecurringConsent.id == consent_id, RecurringConsent.revoked_at.is_(None))
            .values(
                revoked_at=datetime_now(),
                revoked_channel=channel,
                revoked_event_id=event_id,
                revoked_ip_address=ip_address,
            )
        )

    async def attach_consent(self, consent_id: int, subscription_id: int) -> None:
        await self.session.execute(
            update(RecurringConsent)
            .where(RecurringConsent.id == consent_id)
            .values(subscription_id=subscription_id)
        )

    async def wipe_stale_methods(self, before: datetime) -> int:
        result = await self.session.execute(
            update(RecurringPayment)
            .where(
                RecurringPayment.customer_disabled.is_(True),
                RecurringPayment.disabled_at < before,
                RecurringPayment.pending_transaction_id.is_(None),
                RecurringPayment.payment_method_id.is_not(None),
            )
            .values(payment_method_id=None)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def mark_submitted(self, subscription_id: int) -> datetime:
        token = await self.session.scalar(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == subscription_id)
            .values(
                submitted_at=func.greatest(
                    datetime_now(), RecurringPayment.submitted_at + timedelta(microseconds=1)
                )
            )
            .returning(RecurringPayment.submitted_at)
        )
        if token is None:
            raise RuntimeError("Recurring mandate disappeared before submission")
        return token

    async def clear_submission(self, subscription_id: int) -> None:
        await self.session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == subscription_id)
            .values(submitted_at=None)
        )
