from datetime import timedelta
from typing import Optional

from loguru import logger

from app.core.db.uow import UnitOfWork
from app.core.enums import PaymentGatewayType, TransactionStatus
from app.core.exceptions import PaymentGatewayError
from app.core.utils.time import datetime_now
from app.modules.gateways import GatewayRepository
from app.modules.recurring_payments.dto import RecurringPaymentDto, RecurringTerms
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import (
    PENDING_TIMEOUT_HOURS,
    RecurringReason,
)
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.subscriptions import PurchaseSubscriptionDispatch
from app.modules.transactions import (
    PaymentGatewayFactory,
    TransactionDto,
    TransactionRepository,
    WebhookSignal,
    YooKassaGateway,
    settle_verified_payment,
)


def pending_expired(
    mandate: RecurringPaymentDto, order: TransactionDto, terms: Optional[RecurringTerms]
) -> bool:
    started = mandate.pending_since or order.created_at
    hours = terms.pending_timeout_hours if terms else PENDING_TIMEOUT_HOURS
    return started is not None and datetime_now() >= started + timedelta(hours=hours)


class RecurringPoller:
    def __init__(
        self,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        transaction_repository: TransactionRepository,
        gateway_repository: GatewayRepository,
        gateway_factory: PaymentGatewayFactory,
        purchase_dispatch: PurchaseSubscriptionDispatch,
        uow: UnitOfWork,
    ) -> None:
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._transactions = transaction_repository
        self._gateways = gateway_repository
        self._factory = gateway_factory
        self._dispatch = purchase_dispatch
        self._uow = uow

    async def gateway(self) -> YooKassaGateway:
        settings = await self._gateways.get_raw_settings(PaymentGatewayType.YOOKASSA)
        gateway = self._factory.build(PaymentGatewayType.YOOKASSA, settings)
        if not isinstance(gateway, YooKassaGateway):
            raise PaymentGatewayError("Unexpected YooKassa gateway implementation")
        return gateway

    async def poll(
        self, subscription_id: int, order: TransactionDto, gateway: YooKassaGateway
    ) -> None:
        payment = await gateway.fetch_payment(
            order, WebhookSignal(reference=order.idempotency_key, claims_paid=True)
        )
        if (
            payment.reference != order.idempotency_key
            or payment.amount != order.final_price
            or payment.currency != order.currency.value
            or payment.provider_payment_id != order.external_payment_id
        ):
            raise PaymentGatewayError("YooKassa returned a payment for a different order")
        if gateway.payment_matches(order, payment):
            moved = await settle_verified_payment(
                order, payment, self._transactions, self._uow, self._dispatch
            )
            if moved:
                logger.info(f"Recurring order '{order.id}' confirmed by YooKassa")
        elif payment.status is TransactionStatus.CANCELED:
            async with self._uow:
                await self._transactions.mark_status_if(
                    order.id,
                    TransactionStatus.CANCELED,
                    current=frozenset({TransactionStatus.PENDING, TransactionStatus.FAILED}),
                )
                await self._lifecycle.on_canceled(order.id, payment.cancellation_reason)
        else:
            async with self._uow:
                mandate = await self._recurring.get(subscription_id)
                terms = await self._recurring.consent_terms(mandate.consent_id) if mandate else None
                if (
                    mandate
                    and mandate.pending_transaction_id == order.id
                    and pending_expired(mandate, order, terms)
                ):
                    await self._lifecycle.pause(subscription_id, RecurringReason.PENDING_TIMEOUT)
