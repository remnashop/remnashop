from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.core.db.models import (
    EventOutboxEntry,
    RecurringConsent,
    RecurringPayment,
    User,
)
from app.core.enums import (
    Currency,
    PurchaseChannel,
    Role,
    TransactionStatus,
)
from app.core.exceptions import ValidationError
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.admin_guard import RecurringAdminGuard
from app.modules.recurring_payments.admin_repository import RecurringPaymentAdminRepository
from app.modules.recurring_payments.dto import (
    ListRecurringPaymentsDto,
    RecurringAction,
    RecurringAdminActionDto,
    SetRecurringPaymentDto,
)
from app.modules.recurring_payments.policy import (
    RecurringState,
    classify,
)
from app.modules.recurring_payments.usecases.check_recurring_payment import (
    CheckRecurringPaymentUseCase,
)
from app.modules.recurring_payments.usecases.close_recurring_payment import (
    CloseRecurringPaymentUseCase,
)
from app.modules.recurring_payments.usecases.list_recurring_payments import (
    ListRecurringPaymentsUseCase,
)
from app.modules.recurring_payments.usecases.retry_recurring_payment import (
    RetryRecurringPaymentUseCase,
)
from app.modules.users.dto import CreateUserDto
from app.modules.users.listing import ALLOWED_ROLES, STAFF_ROLES
from tests.fakes.recurring import fulfil
from tests.modules.recurring_payments.harness import (
    recurring_order,
)


@pytest.fixture
async def manager(
    case, transaction_repository, subscription_repository, user_repository, event_publisher, uow
):
    async with uow:
        operator = await user_repository.create(
            CreateUserDto(name="Recurring operator", role=Role.OWNER)
        )
    guard = RecurringAdminGuard(
        case.repository,
        transaction_repository,
        subscription_repository,
        user_repository,
        event_publisher,
    )
    actions = {
        RecurringAction.CHECK: CheckRecurringPaymentUseCase(
            guard, transaction_repository, case.worker._poller, uow
        ),
        RecurringAction.CLOSE: CloseRecurringPaymentUseCase(guard, case.lifecycle, uow),
        RecurringAction.RETRY: RetryRecurringPaymentUseCase(
            guard, case.repository, case.lifecycle, uow
        ),
    }
    return actions, operator


async def _audit(session):
    return list(
        await session.scalars(
            select(EventOutboxEntry).where(
                EventOutboxEntry.event_type == "RecurringPaymentManagedEvent"
            )
        )
    )


@pytest.mark.usefixtures("production_session_mode")
async def test_operator_checks_a_timed_out_payment_without_starting_a_new_charge(
    case, manager, session, uow, transaction_repository
):
    action, operator = manager
    case.provider.status = "pending"
    await case.worker.system()
    before = await case.repository.get(case.subscription.id)
    async with uow:
        await case.lifecycle.pause(case.subscription.id, "pending_timeout")
    case.provider.status = "succeeded"
    await action[RecurringAction.CHECK](
        operator,
        RecurringAdminActionDto(
            subscription_id=case.subscription.id,
            expected_pending_transaction_id=before.pending_transaction_id,
            client_ip="127.0.0.1",
        ),
    )
    paid = await transaction_repository.get_by_id(before.pending_transaction_id)
    assert paid.status is TransactionStatus.PAID
    assert len(case.provider.posts) == 1 and len(case.dispatch.messages) == 1
    entries = await _audit(session)
    assert len(entries) == 1 and entries[0].actor_id == operator.id
    assert entries[0].payload["action"] == "check" and entries[0].ip_address == "127.0.0.1"


@pytest.mark.usefixtures("production_session_mode")
async def test_operator_close_revokes_consent_but_preserves_a_late_paid_fulfillment(
    case, manager, session, uow, transaction_repository
):
    action, operator = manager
    case.provider.status = "pending"
    await case.worker.system()
    before = await case.repository.get(case.subscription.id)
    await action[RecurringAction.CLOSE](
        operator,
        RecurringAdminActionDto(
            subscription_id=case.subscription.id,
            expected_pending_transaction_id=before.pending_transaction_id,
            client_ip="127.0.0.1",
        ),
    )
    closed = await case.repository.get(case.subscription.id)
    assert not closed.enabled and closed.last_error == "admin_closed"
    assert closed.pending_transaction_id is None and closed.submitted_at is not None
    assert (await session.get(RecurringConsent, before.consent_id)).revoked_at is not None
    order = await transaction_repository.get_by_id(before.pending_transaction_id)
    assert order.status is TransactionStatus.FAILED
    case.provider.status = "succeeded"
    async with uow:
        gateway = await case.worker._poller.gateway()
    await case.worker._poller.poll(case.subscription.id, order, gateway)
    assert (await transaction_repository.get_by_id(order.id)).status is TransactionStatus.PAID
    async with uow:
        await fulfil(transaction_repository.session, order.id, case.subscription.id)
    state = await case.get_state(case.user, case.subscription.id)
    assert not state.enabled and not state.can_disable and state.available
    assert (await case.repository.get(case.subscription.id)).submitted_at is None
    assert len(case.provider.posts) == 1 and len(await _audit(session)) == 1


@pytest.mark.usefixtures("production_session_mode")
async def test_operator_retry_requeues_a_corrected_shop_error_without_touching_consent(
    case, manager, session
):
    action, operator = manager
    case.provider.reject = True
    await case.worker.system()
    before = await case.repository.get(case.subscription.id)
    assert before.last_error == "provider_request_rejected"
    await action[RecurringAction.RETRY](
        operator,
        RecurringAdminActionDto(
            subscription_id=case.subscription.id,
            client_ip="127.0.0.1",
        ),
    )
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and after.last_error is None and after.consent_id == before.consent_id
    assert len(case.provider.posts) == 1
    case.provider.reject = False
    await case.worker.system()
    assert len(case.provider.posts) == 2 and len(await _audit(session)) == 1


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize(
    "reason", ["retries_exhausted", "payment_status_unknown", "permission_revoked"]
)
async def test_operator_retry_cannot_bypass_terminal_payment_limits(
    case, manager, reason, session, uow
):
    action, operator = manager
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(last_error=reason, retry_count=9)
        )
    with pytest.raises(ValidationError):
        await action[RecurringAction.RETRY](
            operator,
            RecurringAdminActionDto(
                subscription_id=case.subscription.id,
                client_ip="127.0.0.1",
            ),
        )
    assert not case.provider.posts and not await _audit(session)


@pytest.mark.usefixtures("production_session_mode")
async def test_operator_retry_cannot_override_customer_withdrawal(case, manager, session):
    action, operator = manager
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    with pytest.raises(ValidationError):
        await action[RecurringAction.RETRY](
            operator,
            RecurringAdminActionDto(
                subscription_id=case.subscription.id,
                client_ip="127.0.0.1",
            ),
        )
    assert (await case.repository.get(case.subscription.id)).customer_disabled
    assert not case.provider.posts and not await _audit(session)


@pytest.mark.usefixtures("production_session_mode")
async def test_late_verified_cancellation_resolves_operator_closed_payment_without_reenabling(
    case, manager, session, uow, transaction_repository
):
    action, operator = manager
    case.provider.status = "pending"
    await case.worker.system()
    before = await case.repository.get(case.subscription.id)
    await action[RecurringAction.CLOSE](
        operator,
        RecurringAdminActionDto(
            subscription_id=case.subscription.id,
            expected_pending_transaction_id=before.pending_transaction_id,
            client_ip="127.0.0.1",
        ),
    )
    case.provider.status = "canceled"
    order = await transaction_repository.get_by_id(before.pending_transaction_id)
    async with uow:
        gateway = await case.worker._poller.gateway()
    await case.worker._poller.poll(case.subscription.id, order, gateway)
    after = await case.repository.get(case.subscription.id)
    assert after.submitted_at is None and not after.enabled
    assert after.last_error == "admin_closed"
    assert (await transaction_repository.get_by_id(order.id)).status is TransactionStatus.CANCELED
    assert not (await case.get_state(case.user, case.subscription.id)).can_disable
    assert len(case.provider.posts) == 1


async def test_admin_summary_counts_only_real_recurring_orders(
    case, session, uow, transaction_repository
):
    await recurring_order(case, transaction_repository, uow, TransactionStatus.PAID)
    await recurring_order(case, transaction_repository, uow, TransactionStatus.CANCELED)
    repository = RecurringPaymentAdminRepository(session)
    summary = await repository.summary()
    assert summary.total == 1 and summary.enabled == 1
    assert summary.paid_renewals == 1 and summary.failed_renewals == 1
    assert summary.revenue == Decimal("400") and summary.currency is Currency.RUB
    items, total = await repository.list_page(
        ListRecurringPaymentsDto(), roles=STAFF_ROLES, now=datetime_now()
    )
    assert total == 1 and items[0].subscription_id == case.subscription.id
    assert items[0].amount_limit == Decimal("500")
    assert "method-token" not in repr(items[0])
    assert not hasattr(items[0], "payment_method_id")


async def test_admin_sees_stopped_pending_payments_as_attention(
    case, session, uow, transaction_repository
):
    order = await recurring_order(case, transaction_repository, uow, TransactionStatus.PENDING)
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(enabled=False, pending_transaction_id=order.id, last_error="pending_timeout")
        )
    repository = RecurringPaymentAdminRepository(session)
    items, total = await repository.list_page(
        ListRecurringPaymentsDto(state="attention"), roles=STAFF_ROLES, now=datetime_now()
    )
    assert total == 1 and items[0].state == "attention"
    assert items[0].pending_transaction_id == order.id and items[0].next_attempt_at is not None
    summary = await repository.summary()
    assert summary.pending == 0 and summary.attention == 1


async def test_staff_rows_are_hidden_without_admins_manage(case, session, uow):
    async with uow:
        await session.execute(update(User).where(User.id == case.user.id).values(role=Role.ADMIN))
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(
                retry_count=2,
                first_failure_at=datetime_now() - timedelta(hours=3),
                last_error="insufficient_funds",
            )
        )
    repository = RecurringPaymentAdminRepository(session)
    items, total = await repository.list_page(
        ListRecurringPaymentsDto(state="retrying"), roles=STAFF_ROLES, now=datetime_now()
    )
    assert total == 1 and items[0].state == "retrying" and items[0].retry_count == 2
    for data in (
        ListRecurringPaymentsDto(state="retrying"),
        ListRecurringPaymentsDto(search=case.user.name),
        ListRecurringPaymentsDto(search=str(case.user.id)),
    ):
        assert await repository.list_page(data, roles=ALLOWED_ROLES, now=datetime_now()) == ([], 0)


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize(
    ("enabled", "customer_disabled", "pending", "failed", "reason"),
    [
        (True, False, False, False, None),
        (True, False, True, False, None),
        (True, False, False, True, "insufficient_funds"),
        (True, False, True, False, "pending_timeout"),
        (False, True, True, False, "customer_disabled"),
    ],
)
async def test_admin_filters_and_totals_use_the_same_state_as_customer_policy(
    case, session, uow, enabled, customer_disabled, pending, failed, reason
):
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(
                enabled=enabled,
                customer_disabled=customer_disabled,
                pending_transaction_id=case.source.id if pending else None,
                first_failure_at=datetime_now() if failed else None,
                last_error=reason,
            )
        )
    expected = classify(await case.repository.get(case.subscription.id))
    repository = RecurringPaymentAdminRepository(session)
    for state in RecurringState:
        rows, total = await repository.list_page(
            ListRecurringPaymentsDto(state=state), roles=STAFF_ROLES, now=datetime_now()
        )
        assert total == int(state is expected)
        assert all(row.state is expected for row in rows)
    totals = await repository.summary()
    assert sum(getattr(totals, state.value) for state in RecurringState) == totals.total == 1
    assert getattr(totals, expected.value) == 1


@pytest.mark.usefixtures("production_session_mode")
async def test_the_list_offers_retry_exactly_when_the_retry_is_allowed(case, manager, session, uow):
    action, operator = manager
    listing = ListRecurringPaymentsUseCase(RecurringPaymentAdminRepository(session), uow)
    case.provider.reject = True
    await case.worker.system()
    [item], _ = await listing(operator, ListRecurringPaymentsDto())
    assert item.can_retry and not item.can_check and not item.can_close
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    [withdrawn], _ = await listing(operator, ListRecurringPaymentsDto())
    assert not withdrawn.can_retry and withdrawn.next_attempt_at is None
    with pytest.raises(ValidationError):
        await action[RecurringAction.RETRY](
            operator,
            RecurringAdminActionDto(subscription_id=case.subscription.id, client_ip="127.0.0.1"),
        )
