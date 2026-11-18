from datetime import timedelta

from loguru import logger

from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.usecase import UseCase
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.policy import METHOD_RETENTION_DAYS
from app.modules.recurring_payments.repository import RecurringPaymentRepository


class WipeStalePaymentMethodsUseCase(UseCase[None, None]):
    required_permission = None

    def __init__(self, recurring_repository: RecurringPaymentRepository, uow: UnitOfWork) -> None:
        self._recurring = recurring_repository
        self._uow = uow

    async def _execute(self, actor: Actor, data: None) -> None:
        async with self._uow:
            wiped = await self._recurring.wipe_stale_methods(
                datetime_now() - timedelta(days=METHOD_RETENTION_DAYS)
            )
        if wiped:
            logger.info(f"Wiped {wiped} saved payment method(s) withdrawn long ago")
