from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.modules.recurring_payments.admin_repository import RecurringPaymentAdminRepository
from app.modules.recurring_payments.dto import RecurringPaymentSummaryDto


class GetRecurringPaymentSummaryUseCase(UseCase[None, RecurringPaymentSummaryDto]):
    required_permission = Permission.TRANSACTIONS_RECURRING_SUMMARY_VIEW

    def __init__(self, repository: RecurringPaymentAdminRepository, uow: UnitOfWork) -> None:
        self._repository = repository
        self._uow = uow

    async def _execute(self, actor: Actor, data: None) -> RecurringPaymentSummaryDto:
        async with self._uow:
            return await self._repository.summary()
