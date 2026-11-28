import httpx
from loguru import logger

from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.usecase import UseCase
from app.modules.recurring_payments.checks import RecurringDebitChecks
from app.modules.recurring_payments.debit import RecurringDebit
from app.modules.recurring_payments.dto import ProcessRecurringPaymentDto
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import RecurringReason
from app.modules.recurring_payments.poller import pending_expired
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.reservation import RecurringReservation
from app.modules.transactions import TransactionRepository


class ProcessRecurringPaymentUseCase(UseCase[ProcessRecurringPaymentDto, None]):
    required_permission = None

    def __init__(
        self,
        checks: RecurringDebitChecks,
        reservation: RecurringReservation,
        debit: RecurringDebit,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        transaction_repository: TransactionRepository,
        uow: UnitOfWork,
    ) -> None:
        self._checks = checks
        self._reservation = reservation
        self._debit = debit
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._transactions = transaction_repository
        self._uow = uow

    async def _execute(self, actor: Actor, data: ProcessRecurringPaymentDto) -> None:
        await self._run_one(data.subscription_id)

    async def _run_one(self, subscription_id: int) -> None:
        try:
            await self._process(subscription_id)
        except Exception as error:
            await self._uow.rollback()
            kind = (
                f"HTTP {error.response.status_code}"
                if isinstance(error, httpx.HTTPStatusError)
                else type(error).__name__
            )
            logger.error(f"Recurring payment for subscription '{subscription_id}': {kind}")
            async with self._uow:
                mandate = await self._recurring.get(subscription_id)
                order = (
                    await self._transactions.get_by_id(mandate.pending_transaction_id)
                    if mandate and mandate.pending_transaction_id
                    else None
                )
                terms = await self._recurring.consent_terms(mandate.consent_id) if mandate else None
                if (
                    mandate
                    and order
                    and order.external_payment_id
                    and pending_expired(mandate, order, terms)
                ):
                    # outcome unknown: ends the attempt, so the customer may pay by hand
                    await self._lifecycle.retire_pending(
                        subscription_id, order.id, force_unknown=True
                    )
                else:
                    merchant = isinstance(
                        error, httpx.HTTPStatusError
                    ) and error.response.status_code in {401, 403}
                    await self._checks.defer(
                        subscription_id,
                        RecurringReason.MERCHANT_UNAVAILABLE
                        if merchant
                        else RecurringReason.PROVIDER_UNAVAILABLE,
                    )

    async def _process(self, subscription_id: int) -> None:
        async with self._uow:
            mandate = await self._recurring.get(subscription_id)
            if mandate is None:
                return
        if mandate.pending_transaction_id is None:
            reason = mandate.last_error
            if not mandate.enabled or (reason is not None and not reason.policy.allows_debit):
                return
            await self._reservation.reserve(mandate)
        await self._debit.charge_or_poll(subscription_id)
