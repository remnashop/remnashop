from datetime import timedelta

from loguru import logger

from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.error_codes import ErrorCode
from app.core.exceptions import ValidationError
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.admin_guard import LockedMandate, RecurringAdminGuard
from app.modules.recurring_payments.dto import RecurringAction, RecurringAdminActionDto
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import admin_may_retry
from app.modules.recurring_payments.repository import RecurringPaymentRepository


class RetryRecurringPaymentUseCase(UseCase[RecurringAdminActionDto, None]):
    required_permission = Permission.TRANSACTIONS_RECURRING_RETRY

    def __init__(
        self,
        guard: RecurringAdminGuard,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        uow: UnitOfWork,
    ) -> None:
        self._guard = guard
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._uow = uow

    async def _execute(self, actor: Actor, data: RecurringAdminActionDto) -> None:
        async with self._uow:
            locked = await self._guard.lock(actor, data)
            await self._assert_retryable(locked)
            await self._lifecycle.resume(data.subscription_id)
            await self._guard.record(actor, data, locked, RecurringAction.RETRY)
        logger.info(f"{actor.log} Retried the recurring payment '{data.subscription_id}'")

    async def _assert_retryable(self, locked: LockedMandate) -> None:
        mandate = locked.mandate
        terms = await self._recurring.consent_terms(mandate.consent_id)
        overdue = terms is not None and locked.subscription.expire_at < datetime_now() - timedelta(
            hours=terms.max_overdue_hours
        )
        if not admin_may_retry(
            last_error=mandate.last_error,
            customer_disabled=mandate.customer_disabled,
            pending=mandate.pending_transaction_id is not None,
            submitted=mandate.submitted_at is not None,
            has_method=bool(mandate.payment_method_id),
            authorized=terms is not None,
            overdue=overdue,
        ):
            raise ValidationError(
                "Renewal cannot be retried under the current consent",
                code=ErrorCode.RECURRING_RETRY_NOT_ALLOWED,
            )
