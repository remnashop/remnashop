from datetime import timedelta

from loguru import logger

from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.enums import PaymentGatewayType
from app.core.usecase import UseCase
from app.core.utils.time import datetime_now
from app.modules.gateways import GatewayRepository
from app.modules.recurring_payments.dispatch import ProcessRecurringPaymentDispatch
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import (
    DEBIT_BATCH_SIZE,
    POLL_BATCH_SIZE,
    QUEUE_LEASE,
    recurring_policy,
)
from app.modules.recurring_payments.repository import RecurringPaymentRepository


class EnqueueRecurringPaymentsUseCase(UseCase[None, None]):
    required_permission = None

    def __init__(
        self,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        dispatch: ProcessRecurringPaymentDispatch,
        uow: UnitOfWork,
        gateway_repository: GatewayRepository,
    ) -> None:
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._dispatch = dispatch
        self._uow = uow
        self._gateways = gateway_repository

    async def _execute(self, actor: Actor, data: None) -> None:
        now = datetime_now()
        lease = now + QUEUE_LEASE
        async with self._uow:
            policy = recurring_policy(
                await self._gateways.get_raw_settings(PaymentGatewayType.YOOKASSA)
            )
            # wide enough for the earliest charge and its advance notice
            due_before = now + timedelta(minutes=max(1440, policy.notice_lead_minutes))
            await self._lifecycle.close_overdue(now, limit=DEBIT_BATCH_SIZE)
            debits = await self._recurring.list_due(
                now,
                due_before=due_before,
                limit=DEBIT_BATCH_SIZE,
                pending=False,
                claim_until=lease,
            )
            polls = await self._recurring.list_due(
                now,
                due_before=due_before,
                limit=POLL_BATCH_SIZE,
                pending=True,
                claim_until=lease,
            )
        # Commit the leases before publishing. Each task receives its own request-scoped session;
        # a broker failure leaves a bounded lease for the next scheduler tick to reclaim.
        for subscription_id in (*debits, *polls):
            try:
                await self._dispatch.kiq(subscription_id=subscription_id)
            except Exception as error:
                logger.error(
                    f"Could not enqueue recurring subscription '{subscription_id}': "
                    f"{type(error).__name__}"
                )
