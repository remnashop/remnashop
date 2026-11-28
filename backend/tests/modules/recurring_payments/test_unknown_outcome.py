import json
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.db.models import (
    Subscription,
    Transaction,
)
from app.core.enums import (
    PaymentGatewayType,
    PurchaseChannel,
    TransactionStatus,
)
from app.core.exceptions import ValidationError
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.dto import (
    SetRecurringPaymentDto,
)
from app.modules.transactions.dto import (
    HandleWebhookDto,
    WebhookRequest,
)
from app.modules.transactions.usecases import (
    HandlePaymentWebhookUseCase,
)
from tests.fakes.events import RecordingEventPublisher
from tests.fakes.recurring import fulfil, make_recurring_lifecycle
from tests.modules.recurring_payments.harness import (
    lose_recurring_payment,
    manual_renewal,
    tick_again,
)


async def test_unknown_payment_leaves_the_active_queue(
    case, transaction_repository, session, uow
) -> None:
    order_id = await lose_recurring_payment(case, session, uow)
    await tick_again(case, uow)
    mandate = await case.repository.get(case.subscription.id)
    order = await transaction_repository.get_by_id(order_id)
    assert mandate.pending_transaction_id is None
    assert mandate.submitted_at is not None
    assert not mandate.enabled
    assert mandate.last_error == "payment_status_unknown"
    assert order.status is TransactionStatus.FAILED
    future = datetime_now() + timedelta(days=2)
    assert case.subscription.id not in await case.repository.list_due(
        future, due_before=future, limit=100
    )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1


async def test_manual_payment_restores_renewals_after_an_unknown_payment(
    case, transaction_repository, session, uow
) -> None:
    old_id = await lose_recurring_payment(case, session, uow)
    await tick_again(case, uow)
    manual = await manual_renewal(case, transaction_repository, session, uow)
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.source_transaction_id == manual.id
    assert mandate.pending_transaction_id is None
    assert mandate.enabled and mandate.last_error is None
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(minutes=30))
        )
    await tick_again(case, uow)
    fresh = await case.repository.get(case.subscription.id)
    assert fresh.pending_transaction_id != old_id
    assert (
        await transaction_repository.get_by_id(fresh.pending_transaction_id)
    ).status is TransactionStatus.PAID
    assert len(case.provider.posts) == 2
    assert len(case.provider.keys) == 2
    assert json.loads(case.provider.posts[-1].content)["payment_method_id"] == "fresh-method"


async def test_manual_payment_releases_an_aged_unknown_pending_order(
    case, transaction_repository, session, uow
) -> None:
    await lose_recurring_payment(case, session, uow)
    async with uow:
        await case.lifecycle.disable(case.subscription.id, "payment_status_unknown")
    await manual_renewal(case, transaction_repository, session, uow)
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.pending_transaction_id is None
    assert mandate.enabled and mandate.last_error is None


async def test_unknown_retirement_rolls_back_the_order_and_mandate_together(
    case, transaction_repository, session, uow
) -> None:
    old_id = await lose_recurring_payment(case, session, uow)
    with pytest.raises(RuntimeError, match="rollback"):
        async with uow:
            retired = await case.lifecycle.retire_pending(case.subscription.id, old_id)
            assert retired
            raise RuntimeError("rollback")
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.enabled and mandate.pending_transaction_id == old_id
    assert (await transaction_repository.get_by_id(old_id)).status is TransactionStatus.PENDING


async def test_a_paid_order_is_not_retired_while_waiting_for_fulfillment(
    case, transaction_repository, session, uow
) -> None:
    old_id = await lose_recurring_payment(case, session, uow)
    async with uow:
        await transaction_repository.mark_status(old_id, TransactionStatus.PAID)
    await tick_again(case, uow)
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.enabled and mandate.pending_transaction_id == old_id
    assert (await transaction_repository.get_by_id(old_id)).status is TransactionStatus.PAID


async def test_manual_reenrollment_keeps_a_known_in_flight_payment(
    case, transaction_repository, session, uow
) -> None:
    case.provider.status = "pending"
    await case.worker.system()
    old = await case.repository.get(case.subscription.id)
    await manual_renewal(case, transaction_repository, session, uow)
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.pending_transaction_id == old.pending_transaction_id
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1


async def test_late_success_of_retired_order_cannot_clear_the_new_cycle(
    case,
    transaction_repository,
    gateway_repository,
    user_repository,
    session,
    uow,
) -> None:
    old_id = await lose_recurring_payment(case, session, uow)
    old = await transaction_repository.get_by_id(old_id)
    provider_id = case.provider.keys[old.idempotency_key]
    await tick_again(case, uow)
    manual = await manual_renewal(case, transaction_repository, session, uow)
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(minutes=30))
        )
    case.provider.status = "pending"
    await tick_again(case, uow)
    active = await case.repository.get(case.subscription.id)
    assert active.pending_transaction_id != old_id
    handler = HandlePaymentWebhookUseCase(
        transaction_repository,
        gateway_repository,
        case.worker._poller._factory,
        user_repository,
        RecordingEventPublisher(),
        uow,
        case.dispatch,
        make_recurring_lifecycle(transaction_repository.session),
    )
    case.provider.status = "succeeded"
    notification = HandleWebhookDto(
        gateway_type=PaymentGatewayType.YOOKASSA,
        request=WebhookRequest(
            body=json.dumps(
                {
                    "event": "payment.succeeded",
                    "object": {"id": provider_id, "metadata": {"order_ref": old.idempotency_key}},
                }
            ).encode(),
            headers={},
            client_ip="185.71.76.1",
        ),
    )
    await handler.system(notification)
    await handler.system(notification)
    assert (await transaction_repository.get_by_id(old_id)).status is TransactionStatus.PAID
    assert len(case.dispatch.messages) == 1
    async with uow:
        await fulfil(transaction_repository.session, old_id, case.subscription.id)
    after = await case.repository.get(case.subscription.id)
    assert after.pending_transaction_id == active.pending_transaction_id
    assert after.source_transaction_id == manual.id
    assert after.enabled


async def test_toggling_preference_cannot_erase_an_unknown_payment(
    case,
    transaction_repository,
    session,
    uow,
) -> None:
    await lose_recurring_payment(case, session, uow)
    await tick_again(case, uow)
    disabled = await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    assert disabled.last_error == "customer_disabled"
    assert disabled.customer_disabled and not disabled.available
    with pytest.raises(ValidationError):
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=True, channel=PurchaseChannel.CABINET
            ),
        )
    await manual_renewal(case, transaction_repository, session, uow)
    state = await case.get_state(case.user, case.subscription.id)
    assert not state.customer_disabled and state.enabled and state.available


@pytest.mark.usefixtures("production_session_mode")
async def test_unknown_payment_still_allows_withdrawal_and_late_success_cannot_reenable(
    case, session, uow, transaction_repository
):
    case.provider.lose_response = True
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    async with uow:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == mandate.pending_transaction_id)
            .values(created_at=datetime_now() - timedelta(hours=24))
        )
    await tick_again(case, uow)
    parked = await case.get_state(case.user, case.subscription.id)
    assert not parked.enabled and parked.can_disable and parked.accepted_terms
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    async with uow:
        await transaction_repository.mark_status(
            mandate.pending_transaction_id, TransactionStatus.PAID
        )
        await fulfil(
            transaction_repository.session, mandate.pending_transaction_id, case.subscription.id
        )
    after = await case.repository.get(case.subscription.id)
    assert after.customer_disabled and not after.enabled
    assert after.last_error == "customer_disabled"


@pytest.mark.usefixtures("production_session_mode")
async def test_poll_of_already_paid_order_does_not_touch_revenue_timestamp_or_redispatch(
    case, transaction_repository, uow
):
    await case.worker.system()
    current = await case.repository.get(case.subscription.id)
    paid = await transaction_repository.get_by_id(current.pending_transaction_id)
    count = len(case.dispatch.messages)
    async with uow:
        gateway = await case.worker._poller.gateway()
    await case.worker._poller.poll(case.subscription.id, paid, gateway)
    after = await transaction_repository.get_by_id(paid.id)
    assert after.updated_at == paid.updated_at
    assert len(case.dispatch.messages) == count


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize("consent", [False, True])
async def test_manual_renewal_before_unknown_retirement_keeps_the_future_cycle_available(
    case, session, uow, transaction_repository, consent
):
    case.provider.lose_response = True
    await case.worker.system()
    before = await case.repository.get(case.subscription.id)
    await manual_renewal(case, transaction_repository, session, uow, consent=consent)
    async with uow:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == before.pending_transaction_id)
            .values(created_at=datetime_now() - timedelta(hours=24))
        )
    await tick_again(case, uow)
    after = await case.repository.get(case.subscription.id)
    assert after.pending_transaction_id is None and after.submitted_at is None
    assert after.enabled and after.last_error is None
    state = await case.get_state(case.user, case.subscription.id)
    assert state.enabled and state.available and not state.paused
    await case.worker.system(case.subscription.id)
    assert len(case.provider.posts) == 1
    assert (
        await transaction_repository.get_by_id(before.pending_transaction_id)
    ).status is TransactionStatus.FAILED
