from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.usecase import UseCase
from app.modules.transactions.dto import MarkOrderFulfilledDto
from app.modules.transactions.ports import RecurringOrderHooks
from app.modules.transactions.repository import TransactionRepository


class MarkOrderFulfilledUseCase(UseCase[MarkOrderFulfilledDto, None]):
    """Links a paid order to the subscription its purchase delivered, right after
    delivery: a refund's rollback needs that link, and the reconcile sweep would
    only set it some 25 minutes later."""

    required_permission = None

    def __init__(
        self,
        transaction_repository: TransactionRepository,
        uow: UnitOfWork,
        recurring_hooks: RecurringOrderHooks,
    ) -> None:
        self._transaction_repository = transaction_repository
        self._uow = uow
        self._recurring_hooks = recurring_hooks

    async def _execute(self, actor: Actor, data: MarkOrderFulfilledDto) -> None:
        async with self._uow:
            marked = await self._transaction_repository.mark_fulfilled_by_key(
                data.payment_key, data.subscription_id
            )
            if marked is not None:
                await self._recurring_hooks.on_fulfilled(marked, data.subscription_id)
