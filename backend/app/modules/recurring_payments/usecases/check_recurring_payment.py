from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.error_codes import ErrorCode
from app.core.exceptions import ConflictError
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.modules.recurring_payments.admin_guard import RecurringAdminGuard, require_pending
from app.modules.recurring_payments.dto import RecurringAction, RecurringAdminActionDto
from app.modules.recurring_payments.poller import RecurringPoller
from app.modules.transactions import TransactionRepository


class CheckRecurringPaymentUseCase(UseCase[RecurringAdminActionDto, None]):
    required_permission = Permission.TRANSACTIONS_RECURRING_CHECK

    def __init__(
        self,
        guard: RecurringAdminGuard,
        transaction_repository: TransactionRepository,
        recurring_poller: RecurringPoller,
        uow: UnitOfWork,
    ) -> None:
        self._guard = guard
        self._transactions = transaction_repository
        self._poller = recurring_poller
        self._uow = uow

    async def _execute(self, actor: Actor, data: RecurringAdminActionDto) -> None:
        async with self._uow:
            locked = await self._guard.lock(actor, data)
            order = await self._transactions.get_by_id(require_pending(locked))
            gateway = await self._poller.gateway()
            if (
                order.external_payment_id is None
                or locked.mandate.shop_id != gateway.settings.shop_id
            ):
                raise ConflictError(
                    "No payment can be checked with the current shop",
                    code=ErrorCode.RECURRING_PAYMENT_STATE_CHANGED,
                )
            await self._guard.record(actor, data, locked, RecurringAction.CHECK)
        # the provider is asked with no transaction open
        await self._poller.poll(data.subscription_id, order, gateway)
