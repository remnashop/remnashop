import json
from dataclasses import dataclass, fields, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

import httpx
from sqlalchemy import select, update

from app.core.db.models import (
    EventOutboxEntry,
    Subscription,
    Transaction,
)
from app.core.enums import (
    Currency,
    DiscountSource,
    PaymentGatewayType,
    PurchaseChannel,
    PurchaseType,
    SubscriptionStatus,
    TransactionStatus,
)
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.debit import RecurringDebit
from app.modules.recurring_payments.dto import (
    ProcessRecurringPaymentDto,
)
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import (
    recurring_policy,
)
from app.modules.recurring_payments.poller import RecurringPoller
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.reservation import RecurringReservation
from app.modules.recurring_payments.terms import build_recurring_terms
from app.modules.recurring_payments.usecases import (
    GetOwnRecurringPaymentUseCase,
    ProcessRecurringPaymentUseCase,
    SetOwnRecurringPaymentUseCase,
)
from app.modules.subscriptions.dto import (
    CreateSubscriptionDto,
)
from app.modules.transactions.dto import (
    CreateTransactionDto,
)
from tests.fakes.dispatch import RecordingDispatch
from tests.fakes.recurring import ShippedRecurringTermsTexts, fulfil


class FakeYooKassa:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.keys: dict[str, str] = {}
        self.references: dict[str, str] = {}
        self.status = "succeeded"
        self.lose_response = False
        self.reject = False
        self.reject_code = 400
        self.reject_body = {
            "type": "error",
            "code": "invalid_request",
            "parameter": "receipt.items",
        }
        self.cancellation_reason = "bank_declined"
        # awaited while a charge request is in flight, with the provider's payment id
        self.on_post: Optional[Callable[[str], Awaitable[None]]] = None

    def __call__(self, request: httpx.Request) -> Any:
        self.requests.append(request)
        if request.method == "POST":
            if self.reject:
                return httpx.Response(self.reject_code, json=self.reject_body)
            key = request.headers["Idempotence-Key"]
            payment_id = self.keys.setdefault(key, f"payment-{len(self.keys) + 1}")
            self.references[payment_id] = json.loads(request.content)["metadata"]["order_ref"]
            if self.lose_response:
                self.lose_response = False
                raise httpx.ReadTimeout("response lost", request=request)
            if self.on_post is not None:
                return after_hook(self.on_post, payment_id)
            return httpx.Response(200, json={"id": payment_id})
        payment_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={
                "id": payment_id,
                "status": self.status,
                "paid": self.status == "succeeded",
                "amount": {"value": "500.00", "currency": "RUB"},
                "metadata": {"order_ref": self.references[payment_id]},
                "payment_method": {"id": "method-token", "saved": True},
                "cancellation_details": {"reason": self.cancellation_reason},
            },
        )

    @property
    def posts(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]


async def set_recurring_timings(case: "RecurringCase", **values: int) -> None:
    """Changes the shop's YooKassa auto-renewal timings, as the dashboard does."""
    async with case.uow:
        await case.gateways.update_settings(
            PaymentGatewayType.YOOKASSA,
            {f"recurring_{key}": str(value) for key, value in values.items()},
        )


async def after_hook(hook: Callable[[str], Awaitable[None]], payment_id: str) -> httpx.Response:
    await hook(payment_id)
    return httpx.Response(200, json={"id": payment_id})


class Worker:
    """The scheduler's fan-out in one call: every due mandate, then each of them."""

    def __init__(
        self,
        use_case: ProcessRecurringPaymentUseCase,
        lifecycle: RecurringLifecycle,
        repository: RecurringPaymentRepository,
        uow: Any,
        gateways: Any,
    ) -> None:
        self.use_case = use_case
        self._lifecycle = lifecycle
        self._repository = repository
        self._uow = uow
        self._gateways = gateways

    async def system(self, subscription_id: Optional[int] = None) -> None:
        if subscription_id is None:
            now = datetime_now()
            async with self._uow:
                policy = recurring_policy(
                    await self._gateways.get_raw_settings(PaymentGatewayType.YOOKASSA)
                )
                await self._lifecycle.close_overdue(now, limit=1000)
                ids = await self._repository.list_due(
                    now,
                    due_before=now + timedelta(minutes=max(1440, policy.notice_lead_minutes)),
                    limit=1000,
                )
        else:
            ids = [subscription_id]
        for due in ids:
            await self.use_case.system(ProcessRecurringPaymentDto(subscription_id=due))

    @property
    def reservation(self) -> RecurringReservation:
        return self.use_case._reservation

    @property
    def debit(self) -> RecurringDebit:
        return self.use_case._debit

    @property
    def _poller(self) -> RecurringPoller:
        return self.use_case._debit._poller


@dataclass
class RecurringCase:
    worker: Worker
    repository: RecurringPaymentRepository
    lifecycle: RecurringLifecycle
    uow: Any
    gateways: Any
    get_state: GetOwnRecurringPaymentUseCase
    set_state: SetOwnRecurringPaymentUseCase
    user: Any
    subscription: Any
    source: Any
    provider: FakeYooKassa
    dispatch: RecordingDispatch


async def tick_again(case: RecurringCase, uow) -> None:
    async with uow:
        await case.lifecycle.defer(case.subscription.id, datetime_now() - timedelta(seconds=1))
    await case.worker.system()


async def lose_recurring_payment(case, session, uow):
    case.provider.lose_response = True
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    order_id = mandate.pending_transaction_id
    async with uow:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == order_id)
            .values(created_at=datetime_now() - timedelta(hours=24))
        )
    return order_id


async def manual_renewal(case, transaction_repository, session, uow, *, consent=True):
    values = {
        field.name: getattr(case.source, field.name) for field in fields(CreateTransactionDto)
    }
    values.update(
        idempotency_key=uuid4().hex,
        purchase_type=PurchaseType.RENEW,
        target_subscription_id=case.subscription.id,
        discount_percent=0,
        discount_source=DiscountSource.NONE,
        final_price=Decimal("500"),
        anchor_final_price=Decimal("500"),
        plan_snapshot=replace(case.source.plan_snapshot, price_paid=Decimal("500")),
    )
    async with uow:
        values["recurring_consent_id"] = (
            await case.repository.record_consent(
                await build_recurring_terms(
                    texts=ShippedRecurringTermsTexts(),
                    policy=recurring_policy({}),
                    user_id=case.user.id,
                    plan_id=case.source.plan_id,
                    target_subscription_id=case.subscription.id,
                    purchase_type=PurchaseType.RENEW,
                    initial_amount=Decimal("500"),
                    amount_limit=Decimal("500"),
                    currency=Currency.RUB,
                    duration_days=30,
                    locale=case.user.language,
                ),
                channel=PurchaseChannel.BOT,
                telegram_id=case.user.telegram_id,
                event_id="fresh-checkbox",
            )
            if consent
            else None
        )
        order = await transaction_repository.create(CreateTransactionDto(**values))
        await transaction_repository.mark_status(order.id, TransactionStatus.PAID)
        await transaction_repository.remember_payment_method(order.id, "fresh-method", "1000")
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(days=30))
        )
        await fulfil(transaction_repository.session, order.id, case.subscription.id)
    return await transaction_repository.get_by_id(order.id)


async def paid_order_with_consent(
    case,
    transaction_repository,
    uow,
    *,
    purchase_type=PurchaseType.RENEW,
    consent=True,
    saved=True,
    plan=None,
):
    snapshot = plan or case.source.plan_snapshot
    consent_id = None
    async with uow:
        if consent:
            consent_id = await case.repository.record_consent(
                await build_recurring_terms(
                    texts=ShippedRecurringTermsTexts(),
                    policy=recurring_policy({}),
                    user_id=case.user.id,
                    plan_id=snapshot.plan_id,
                    target_subscription_id=case.subscription.id,
                    purchase_type=purchase_type,
                    initial_amount=Decimal("500"),
                    amount_limit=Decimal("500"),
                    currency=Currency.RUB,
                    duration_days=30,
                    locale=case.user.language,
                ),
                channel=PurchaseChannel.BOT,
                telegram_id=case.user.telegram_id,
            )
        values = {
            field.name: getattr(case.source, field.name) for field in fields(CreateTransactionDto)
        }
        values.update(
            idempotency_key=uuid4().hex,
            purchase_type=purchase_type,
            target_subscription_id=case.subscription.id,
            plan_id=snapshot.plan_id,
            plan_snapshot=snapshot,
            recurring_consent_id=consent_id,
        )
        order = await transaction_repository.create(CreateTransactionDto(**values))
        await transaction_repository.mark_status(order.id, TransactionStatus.PAID)
        if saved:
            await transaction_repository.remember_payment_method(order.id, "new-method", "1000")
    return order


async def new_subscription(case, subscription_repository, uow, snapshot):
    async with uow:
        return await subscription_repository.create(
            CreateSubscriptionDto(
                user_id=case.user.id,
                remnawave_user_id=case.subscription.remnawave_user_id + 1,
                status=SubscriptionStatus.ACTIVE,
                traffic_limit=100,
                device_limit=3,
                expire_at=datetime_now() + timedelta(days=30),
                url="https://example.test/changed",
                plan_snapshot=snapshot,
            )
        )


async def notice_types(session):
    return list(
        await session.scalars(
            select(EventOutboxEntry.event_type)
            .where(
                EventOutboxEntry.event_type.in_(
                    [
                        "RecurringPaymentFailedEvent",
                        "RecurringPaymentPausedEvent",
                        "RecurringPaymentExhaustedEvent",
                    ]
                )
            )
            .order_by(EventOutboxEntry.id)
        )
    )


async def recurring_order(case, transaction_repository, uow, status):
    values = {
        field.name: getattr(case.source, field.name) for field in fields(CreateTransactionDto)
    }
    values.update(
        is_recurring=True, target_subscription_id=case.subscription.id, idempotency_key=uuid4().hex
    )
    async with uow:
        order = await transaction_repository.create(CreateTransactionDto(**values))
        await transaction_repository.mark_status(order.id, status)
    return order
