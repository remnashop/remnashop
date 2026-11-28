from loguru import logger

from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.error_codes import ErrorCode
from app.core.exceptions import ConflictError
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.modules.recurring_payments.admin_guard import RecurringAdminGuard, require_pending
from app.modules.recurring_payments.dto import RecurringAction, RecurringAdminActionDto
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import ConsentChannel, RecurringReason


class CloseRecurringPaymentUseCase(UseCase[RecurringAdminActionDto, None]):
    required_permission = Permission.TRANSACTIONS_RECURRING_CLOSE

    def __init__(
        self, guard: RecurringAdminGuard, recurring_lifecycle: RecurringLifecycle, uow: UnitOfWork
    ) -> None:
        self._guard = guard
        self._lifecycle = recurring_lifecycle
        self._uow = uow

    async def _execute(self, actor: Actor, data: RecurringAdminActionDto) -> None:
        async with self._uow:
            locked = await self._guard.lock(actor, data)
            if not await self._lifecycle.retire_pending(
                data.subscription_id, require_pending(locked), force_unknown=True, notify=False
            ):
                raise ConflictError(
                    "The payment can no longer be closed",
                    code=ErrorCode.RECURRING_PAYMENT_STATE_CHANGED,
                )
            await self._lifecycle.revoke_consent(
                data.subscription_id,
                channel=ConsentChannel.ADMIN,
                event_id=f"admin:{actor.id}",
                ip_address=data.client_ip,
            )
            await self._lifecycle.disable(data.subscription_id, RecurringReason.ADMIN_CLOSED)
            await self._guard.record(actor, data, locked, RecurringAction.CLOSE)
        logger.info(f"{actor.log} Closed the pending recurring payment '{data.subscription_id}'")
