from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.enums import TransactionStatus
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.admin_repository import RecurringPaymentAdminRepository
from app.modules.recurring_payments.dto import (
    ListRecurringPaymentsDto,
    RecurringPaymentAdminItemDto,
    RecurringPaymentAdminRowDto,
)
from app.modules.recurring_payments.policy import RetryKind, admin_may_retry
from app.modules.users import detail_roles


class ListRecurringPaymentsUseCase(
    UseCase[ListRecurringPaymentsDto, tuple[list[RecurringPaymentAdminItemDto], int]]
):
    required_permission = Permission.TRANSACTIONS_RECURRING_VIEW

    def __init__(self, repository: RecurringPaymentAdminRepository, uow: UnitOfWork) -> None:
        self._repository = repository
        self._uow = uow

    async def _execute(
        self, actor: Actor, data: ListRecurringPaymentsDto
    ) -> tuple[list[RecurringPaymentAdminItemDto], int]:
        async with self._uow:
            rows, total = await self._repository.list_page(
                data, roles=detail_roles(actor), now=datetime_now()
            )
        return [_to_item(row) for row in rows], total


def _to_item(row: RecurringPaymentAdminRowDto) -> RecurringPaymentAdminItemDto:
    pending = row.pending_transaction_id is not None
    reason = row.last_error
    stopped = not pending and (
        row.customer_disabled or (reason is not None and reason.policy.retry is RetryKind.NONE)
    )
    return RecurringPaymentAdminItemDto(
        subscription_id=row.subscription_id,
        user_id=row.user_id,
        user_name=row.user_name,
        plan_name=row.plan_name,
        enabled=row.enabled,
        customer_disabled=row.customer_disabled,
        state=row.state,
        last_error=reason,
        # a stopped mandate has no next attempt, whatever the column still holds
        next_attempt_at=None if stopped else row.next_attempt_at,
        submitted_at=row.submitted_at,
        pending_transaction_id=row.pending_transaction_id,
        external_payment_id=row.external_payment_id,
        can_check=row.external_payment_id is not None,
        can_close=row.pending_status is TransactionStatus.PENDING,
        can_retry=admin_may_retry(
            last_error=reason,
            customer_disabled=row.customer_disabled,
            pending=pending,
            submitted=row.submitted_at is not None,
            has_method=row.has_saved_method,
            authorized=row.authorized,
            overdue=row.overdue,
        ),
        retry_count=row.retry_count,
        first_failure_at=row.first_failure_at,
        amount_limit=row.amount_limit,
        currency=row.currency,
        duration_days=row.duration_days,
        has_saved_method=row.has_saved_method,
        expire_at=row.expire_at,
    )
