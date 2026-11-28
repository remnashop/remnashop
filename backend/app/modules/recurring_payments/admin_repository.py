from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.constants import INT32_MAX, ZERO_AMOUNT
from app.core.db.models import RecurringConsent, RecurringPayment, Subscription, Transaction, User
from app.core.db.user_search import user_search_filter
from app.core.enums import Currency, Role, TransactionStatus
from app.modules.recurring_payments.dto import (
    ListRecurringPaymentsDto,
    RecurringPaymentAdminRowDto,
    RecurringPaymentSummaryDto,
)
from app.modules.recurring_payments.policy import (
    RecurringState,
    stored_reason,
)
from app.modules.recurring_payments.queries import (
    recurring_state_expression,
    renewal_window_expired,
)


class RecurringPaymentAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self,
        data: ListRecurringPaymentsDto,
        *,
        roles: list[Role],
        now: datetime,
    ) -> tuple[list[RecurringPaymentAdminRowDto], int]:
        source = aliased(Transaction)
        pending = aliased(Transaction)
        state = recurring_state_expression()
        stmt = (
            select(
                RecurringPayment.subscription_id,
                Subscription.user_id,
                User.name.label("user_name"),
                func.coalesce(Subscription.plan_snapshot["name"].astext, "—").label("plan_name"),
                RecurringPayment.enabled,
                RecurringPayment.customer_disabled,
                state.label("state"),
                RecurringPayment.last_error,
                RecurringPayment.next_attempt_at,
                RecurringPayment.submitted_at,
                RecurringPayment.pending_transaction_id,
                pending.external_payment_id,
                pending.status.label("pending_status"),
                RecurringPayment.payment_method_id.is_not(None).label("has_saved_method"),
                and_(
                    RecurringPayment.consent_id.is_not(None), RecurringConsent.revoked_at.is_(None)
                ).label("authorized"),
                renewal_window_expired(now).label("overdue"),
                RecurringPayment.retry_count,
                RecurringPayment.first_failure_at,
                source.base_price.label("amount_limit"),
                source.currency,
                source.duration_days,
                Subscription.expire_at,
            )
            .join(Subscription, Subscription.id == RecurringPayment.subscription_id)
            .join(User, User.id == Subscription.user_id)
            .outerjoin(source, source.id == RecurringPayment.source_transaction_id)
            .outerjoin(pending, pending.id == RecurringPayment.pending_transaction_id)
            .outerjoin(RecurringConsent, RecurringConsent.id == RecurringPayment.consent_id)
            .where(User.role.in_(roles))
        )
        if data.state is not None:
            stmt = stmt.where(state == data.state)
        if data.search:
            stmt = stmt.where(_search_filter(data.search))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (
            await self.session.execute(
                stmt.order_by(
                    RecurringPayment.last_error.is_not(None).desc(),
                    RecurringPayment.next_attempt_at,
                    RecurringPayment.subscription_id,
                )
                .offset((data.page - 1) * data.page_size)
                .limit(data.page_size)
            )
        ).mappings()
        return [self._to_row_dto(dict(row)) for row in rows], total

    def _to_row_dto(self, values: dict[str, Any]) -> RecurringPaymentAdminRowDto:
        return RecurringPaymentAdminRowDto(
            **{
                **values,
                "state": RecurringState(values["state"]),
                "last_error": stored_reason(values["last_error"]),
                "has_saved_method": bool(values["has_saved_method"]),
                "authorized": bool(values["authorized"]),
                "overdue": bool(values["overdue"]),
            }
        )

    async def summary(self) -> RecurringPaymentSummaryDto:
        mandate = (
            (
                await self.session.execute(
                    select(
                        func.count().label("total"),
                        *(
                            func.count()
                            .filter(recurring_state_expression() == state.value)
                            .label(state.value)
                            for state in RecurringState
                        ),
                    ).select_from(RecurringPayment)
                )
            )
            .mappings()
            .one()
        )
        money = (
            (
                await self.session.execute(
                    select(
                        func.count()
                        .filter(Transaction.status == TransactionStatus.PAID)
                        .label("paid_renewals"),
                        func.count()
                        .filter(
                            Transaction.status.in_(
                                [TransactionStatus.FAILED, TransactionStatus.CANCELED]
                            )
                        )
                        .label("failed_renewals"),
                        func.sum(Transaction.final_price)
                        .filter(Transaction.status == TransactionStatus.PAID)
                        .label("revenue"),
                    ).where(
                        Transaction.is_recurring,
                        ~Transaction.is_test,
                        Transaction.currency == Currency.RUB,
                    )
                )
            )
            .mappings()
            .one()
        )
        return RecurringPaymentSummaryDto(
            **mandate,
            **{**money, "revenue": money["revenue"] or ZERO_AMOUNT},
            currency=Currency.RUB,
        )


def _search_filter(search: str) -> ColumnElement[bool]:
    # the list never shows a login, so it isn't searchable either
    by_user = user_search_filter(search, include_login=False)
    if search.isascii() and search.isdigit() and int(search) <= INT32_MAX:
        return or_(by_user, RecurringPayment.subscription_id == int(search))
    return by_user
