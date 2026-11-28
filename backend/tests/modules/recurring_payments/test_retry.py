import json
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.core.db.models import (
    RecurringPayment,
    Subscription,
    Transaction,
)
from app.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseChannel,
    PurchaseType,
    TransactionStatus,
)
from app.core.utils.time import datetime_now
from app.modules.recurring_payments.dto import (
    SetRecurringPaymentDto,
)
from app.modules.transactions.dto import (
    CreateTransactionDto,
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
    notice_types,
    set_recurring_timings,
    tick_again,
)


async def _age_retry(case, session, uow, retry_count):
    offsets = (1, 3, 6, 12, 24, 36, 48, 72)
    first = datetime_now() - timedelta(hours=offsets[retry_count - 1], minutes=1)
    expiry = first + timedelta(days=1)
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(
                first_failure_at=first,
                bank_retry_at=first + timedelta(hours=offsets[retry_count - 1]),
                retry_count=retry_count,
                cycle_expire_at=expiry,
                next_attempt_at=datetime_now() - timedelta(seconds=1),
            )
        )
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=expiry)
        )
    return first


async def _manual_stars_renewal(case, transaction_repository, session, uow):
    values = {
        field.name: getattr(case.source, field.name) for field in fields(CreateTransactionDto)
    }
    values.update(
        idempotency_key="manual-stars-" + str(case.source.id),
        gateway_type=PaymentGatewayType.TELEGRAM_STARS,
        currency=Currency.XTR,
        purchase_type=PurchaseType.RENEW,
        target_subscription_id=case.subscription.id,
        recurring_consent_id=None,
        final_price=Decimal("100"),
        plan_snapshot=replace(
            case.source.plan_snapshot, currency=Currency.XTR, price_paid=Decimal("100")
        ),
    )
    async with uow:
        order = await transaction_repository.create(CreateTransactionDto(**values))
        await transaction_repository.mark_status(order.id, TransactionStatus.PAID)
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(days=30))
        )
        await fulfil(transaction_repository.session, order.id, case.subscription.id)
    return order


@pytest.mark.parametrize("reject_code", [401, 403])
async def test_merchant_credentials_failure_keeps_authorization_and_bank_retry_budget(
    case,
    reject_code,
    uow,
):
    case.provider.reject = True
    case.provider.reject_code = reject_code
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.enabled and not mandate.customer_disabled
    assert mandate.pending_transaction_id is None
    assert mandate.first_failure_at is None and mandate.retry_count == 0
    assert mandate.last_error == "merchant_unavailable"
    assert mandate.next_attempt_at > datetime_now()
    assert len(case.provider.posts) == 1
    first_key = case.provider.posts[0].headers["Idempotence-Key"]
    case.provider.reject = False
    await tick_again(case, uow)
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and after.first_failure_at is None and after.retry_count == 0
    assert len(case.provider.posts) == 2
    assert case.provider.posts[1].headers["Idempotence-Key"] != first_key


async def test_request_configuration_error_never_consumes_bank_retries(case, uow):
    case.provider.reject = True
    await case.worker.system()
    initial = await case.repository.get(case.subscription.id)
    assert initial.enabled and initial.retry_count == 0
    assert initial.pending_transaction_id is None and initial.first_failure_at is None
    assert initial.last_error == "provider_request_rejected"
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1


async def test_bank_decline_schedules_a_retry_without_switching_off_the_customer_preference(
    case,
    uow,
):
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "insufficient_funds"
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.enabled and mandate.pending_transaction_id is None
    assert mandate.first_failure_at is not None and mandate.retry_count == 1
    assert mandate.next_attempt_at == mandate.first_failure_at + timedelta(hours=1)
    assert mandate.last_error == "insufficient_funds"
    await tick_again(case, uow)
    # the next slot is an hour away: no repost, and nothing was provisioned
    assert len(case.provider.posts) == 1 and not case.dispatch.messages


@pytest.mark.parametrize("retry_count", range(1, 9))
async def test_each_bank_retry_uses_the_persisted_first_failure_anchor(
    case,
    session,
    uow,
    retry_count,
):
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "insufficient_funds"
    await case.worker.system()
    first_key = case.provider.posts[0].headers["Idempotence-Key"]
    first = await _age_retry(case, session, uow, retry_count)
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    assert len(case.provider.posts) == 2
    assert case.provider.posts[1].headers["Idempotence-Key"] != first_key
    assert mandate.first_failure_at == first
    assert mandate.retry_count == retry_count + 1
    assert mandate.enabled and mandate.pending_transaction_id is None
    offsets = (1, 3, 6, 12, 24, 36, 48, 72)
    if retry_count < len(offsets):
        assert mandate.next_attempt_at == first + timedelta(hours=offsets[retry_count])
    else:
        assert mandate.last_error == "retries_exhausted"
        future = datetime_now() + timedelta(days=7)
        assert case.subscription.id not in await case.repository.list_due(
            future, due_before=future, limit=100
        )


async def test_a_cancellation_webhook_before_cron_still_schedules_a_bank_retry(
    case,
    transaction_repository,
    gateway_repository,
    user_repository,
    uow,
):
    case.provider.status = "pending"
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    order = await transaction_repository.get_by_id(mandate.pending_transaction_id)
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "insufficient_funds"
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
    await handler.system(
        HandleWebhookDto(
            gateway_type=PaymentGatewayType.YOOKASSA,
            request=WebhookRequest(
                body=json.dumps(
                    {
                        "event": "payment.canceled",
                        "object": {
                            "id": order.external_payment_id,
                            "metadata": {"order_ref": order.idempotency_key},
                        },
                    }
                ).encode(),
                headers={},
                client_ip="185.71.76.1",
            ),
        )
    )
    assert (await transaction_repository.get_by_id(order.id)).status is TransactionStatus.CANCELED
    await tick_again(case, uow)
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and after.pending_transaction_id is None
    assert after.retry_count == 1 and after.first_failure_at is not None
    assert after.next_attempt_at == after.first_failure_at + timedelta(hours=1)


async def test_a_payment_pending_past_the_timeout_is_closed_as_unknown(
    case,
    session,
    uow,
    transaction_repository,
):
    case.provider.status = "pending"
    await case.worker.system()
    initial = await case.repository.get(case.subscription.id)
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(pending_since=datetime_now() - timedelta(hours=25))
        )
    await tick_again(case, uow)
    closed = await case.repository.get(case.subscription.id)
    # the manual checkout is no longer held back by a payment nobody can resolve
    assert closed.pending_transaction_id is None
    assert not closed.enabled and closed.last_error == "payment_status_unknown"
    order = await transaction_repository.get_by_id(initial.pending_transaction_id)
    assert order.status is TransactionStatus.FAILED
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1


async def test_a_stale_cancellation_cannot_clear_the_next_pending_attempt(
    case,
    transaction_repository,
    session,
    uow,
):
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "insufficient_funds"
    await case.worker.system()
    reference = json.loads(case.provider.posts[0].content)["metadata"]["order_ref"]
    first_id = await session.scalar(
        select(Transaction.id).where(Transaction.idempotency_key == reference)
    )
    old = await transaction_repository.get_by_id(first_id)
    await _age_retry(case, session, uow, 1)
    case.provider.status = "pending"
    await case.worker.system()
    current = await case.repository.get(case.subscription.id)
    assert current.pending_transaction_id is not None and current.pending_transaction_id != old.id
    case.provider.status = "canceled"
    gateway = await case.worker._poller.gateway()
    await case.worker._poller.poll(case.subscription.id, old, gateway)
    after = await case.repository.get(case.subscription.id)
    assert after.pending_transaction_id == current.pending_transaction_id
    assert after.retry_count == current.retry_count
    assert after.first_failure_at == current.first_failure_at
    assert after.enabled


async def test_manual_stars_renewal_keeps_authorization_and_supersedes_an_unsent_attempt(
    case,
    transaction_repository,
    session,
    uow,
):
    original = await case.repository.get(case.subscription.id)
    await case.worker.reservation.reserve(original)
    reserved = await case.repository.get(case.subscription.id)
    assert reserved.pending_transaction_id is not None and reserved.submitted_at is None
    await _manual_stars_renewal(case, transaction_repository, session, uow)
    await tick_again(case, uow)
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and not after.customer_disabled
    assert after.source_transaction_id == original.source_transaction_id
    assert after.consent_id == original.consent_id
    assert after.payment_method_id == original.payment_method_id
    assert after.pending_transaction_id is None
    assert not case.provider.posts
    assert (
        await transaction_repository.get_by_id(reserved.pending_transaction_id)
    ).status is TransactionStatus.CANCELED


async def test_runtime_timing_changes_do_not_replace_the_accepted_charge_policy(
    case,
    session,
    uow,
    monkeypatch,
):
    original = await case.repository.get(case.subscription.id)
    accepted = await case.repository.consent_terms(original.consent_id)
    assert accepted.lead_minutes == 1440
    await set_recurring_timings(case, lead_minutes=60, retry_minutes=1, max_overdue_hours=1)
    expiry = datetime_now() + timedelta(hours=12)
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=expiry)
        )
    state = await case.get_state(case.user, case.subscription.id)
    assert state.enabled and state.available
    assert state.next_payment_at == expiry - timedelta(minutes=accepted.lead_minutes)
    await case.worker.system()
    assert len(case.provider.posts) == 1
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and after.last_error != "consent_required"


async def test_runtime_window_increase_does_not_widen_the_accepted_limit(
    case,
    session,
    uow,
    monkeypatch,
):
    original = await case.repository.get(case.subscription.id)
    accepted = await case.repository.consent_terms(original.consent_id)
    await set_recurring_timings(case, max_overdue_hours=168)
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() - timedelta(hours=accepted.max_overdue_hours + 1))
        )
    await case.worker.system()
    assert not case.provider.posts
    after = await case.repository.get(case.subscription.id)
    assert not after.enabled and after.last_error == "renewal_window_expired"


async def test_auth_failure_after_a_lost_create_keeps_the_original_key_and_attempt(
    case,
    transaction_repository,
    uow,
):
    case.provider.lose_response = True
    await case.worker.system()
    original = await case.repository.get(case.subscription.id)
    assert original.pending_transaction_id is not None
    lost = await transaction_repository.get_by_id(original.pending_transaction_id)
    assert lost.external_payment_id is None
    case.provider.reject = True
    case.provider.reject_code = 401
    await tick_again(case, uow)
    ambiguous = await case.repository.get(case.subscription.id)
    assert ambiguous.pending_transaction_id == original.pending_transaction_id
    assert ambiguous.enabled and ambiguous.first_failure_at is None and ambiguous.retry_count == 0
    assert len(case.provider.posts) == 2
    assert len({request.headers["Idempotence-Key"] for request in case.provider.posts}) == 1
    case.provider.reject = False
    await tick_again(case, uow)
    assert len(case.provider.posts) == 3
    assert len({request.headers["Idempotence-Key"] for request in case.provider.posts}) == 1
    assert len(case.provider.keys) == 1
    assert len(case.dispatch.messages) == 1


async def test_manual_stars_renewal_does_not_repost_an_ambiguous_old_attempt(
    case,
    transaction_repository,
    session,
    uow,
):
    case.provider.lose_response = True
    await case.worker.system()
    original = await case.repository.get(case.subscription.id)
    await _manual_stars_renewal(case, transaction_repository, session, uow)
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1
    async with uow:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == original.pending_transaction_id)
            .values(created_at=datetime_now() - timedelta(hours=24))
        )
    await tick_again(case, uow)
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and after.pending_transaction_id is None
    assert after.source_transaction_id == original.source_transaction_id
    assert after.consent_id == original.consent_id
    assert len(case.provider.posts) == 1


async def test_provider_side_withdrawal_cannot_be_retried_with_the_saved_method(
    case,
    session,
    uow,
):
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "permission_revoked"
    original = await case.repository.get(case.subscription.id)
    await case.worker.system()
    after = await case.repository.get(case.subscription.id)
    assert not after.enabled and after.payment_method_id is None
    assert after.pending_transaction_id is None
    assert after.last_error == "permission_revoked"
    assert await case.repository.consent_terms(original.consent_id) is None
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1


async def test_a_late_decline_skips_retry_slots_that_have_already_passed(
    case,
    session,
    uow,
):
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "insufficient_funds"
    await case.worker.system()
    first = datetime_now() - timedelta(hours=7)
    expiry = first + timedelta(days=1)
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(
                first_failure_at=first,
                bank_retry_at=first + timedelta(hours=1),
                retry_count=1,
                cycle_expire_at=expiry,
                next_attempt_at=datetime_now() - timedelta(seconds=1),
            )
        )
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=expiry)
        )
    await case.worker.system()
    after = await case.repository.get(case.subscription.id)
    assert after.first_failure_at == first and after.retry_count == 2
    assert after.next_attempt_at == first + timedelta(hours=12)
    assert after.bank_retry_at == first + timedelta(hours=12)
    assert len(case.provider.posts) == 2
    # A task queued before the decline must respect the newly scheduled retry.
    await case.worker.system(case.subscription.id)
    assert len(case.provider.posts) == 2


async def test_late_verified_success_resumes_the_original_authorization_without_a_new_charge(
    case,
    transaction_repository,
    gateway_repository,
    user_repository,
    session,
    uow,
):
    old_id = await lose_recurring_payment(case, session, uow)
    order = await transaction_repository.get_by_id(old_id)
    payment_id = case.provider.keys[order.idempotency_key]
    grant_id = (await case.repository.get(case.subscription.id)).consent_id
    await tick_again(case, uow)
    blocked = await case.repository.get(case.subscription.id)
    assert not blocked.enabled and blocked.last_error == "payment_status_unknown"
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
    await handler.system(
        HandleWebhookDto(
            gateway_type=PaymentGatewayType.YOOKASSA,
            request=WebhookRequest(
                body=json.dumps(
                    {
                        "event": "payment.succeeded",
                        "object": {
                            "id": payment_id,
                            "metadata": {"order_ref": order.idempotency_key},
                        },
                    }
                ).encode(),
                headers={},
                client_ip="185.71.76.1",
            ),
        )
    )
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(days=30))
        )
        await fulfil(transaction_repository.session, old_id, case.subscription.id)
    restored = await case.repository.get(case.subscription.id)
    assert restored.enabled and restored.last_error is None
    assert restored.consent_id == grant_id and restored.pending_transaction_id is None
    assert len(case.provider.posts) == 1


@pytest.mark.parametrize("reserved", [False, True])
async def test_paid_manual_renewal_waiting_for_fulfillment_prevents_an_auto_debit(
    case,
    transaction_repository,
    session,
    uow,
    reserved,
):
    if reserved:
        await case.worker.reservation.reserve(await case.repository.get(case.subscription.id))
    values = {
        field.name: getattr(case.source, field.name) for field in fields(CreateTransactionDto)
    }
    values.update(
        idempotency_key="paid-manual-waiting-" + str(case.source.id),
        gateway_type=PaymentGatewayType.TELEGRAM_STARS,
        currency=Currency.XTR,
        purchase_type=PurchaseType.RENEW,
        target_subscription_id=case.subscription.id,
        recurring_consent_id=None,
    )
    async with uow:
        order = await transaction_repository.create(CreateTransactionDto(**values))
        await transaction_repository.mark_status(order.id, TransactionStatus.PAID)
    await case.worker.system()
    assert not case.provider.posts
    before = await case.repository.get(case.subscription.id)
    assert before.enabled and before.submitted_at is None
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(days=30))
        )
        await fulfil(transaction_repository.session, order.id, case.subscription.id)
    await case.worker.system()
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and after.pending_transaction_id is None
    assert not case.provider.posts


@pytest.mark.usefixtures("production_session_mode")
async def test_overdue_mandate_has_a_terminal_state_and_leaves_the_queue(case, session, uow):
    terms = await case.repository.consent_terms(
        (await case.repository.get(case.subscription.id)).consent_id
    )
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() - timedelta(hours=terms.max_overdue_hours + 1))
        )
    now = datetime_now()
    async with uow:
        await case.lifecycle.close_overdue(now, limit=100)
    assert case.subscription.id not in await case.repository.list_due(
        now, due_before=now + timedelta(days=2), limit=100
    )
    current = await case.repository.get(case.subscription.id)
    assert not current.enabled and current.last_error == "renewal_window_expired"
    notices = await notice_types(session)
    assert notices == ["RecurringPaymentPausedEvent"]
    async with uow:
        await case.lifecycle.close_overdue(now + timedelta(days=30), limit=100)
    assert case.subscription.id not in await case.repository.list_due(
        now + timedelta(days=30), due_before=now + timedelta(days=31), limit=100
    )
    assert await notice_types(session) == notices


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize("withdrawn", [False, True])
@pytest.mark.parametrize("reason", ["insufficient_funds", "permission_revoked"])
async def test_late_cancel_webhook_resolves_lost_create_response_without_new_debit(
    case,
    session,
    uow,
    transaction_repository,
    gateway_repository,
    user_repository,
    withdrawn,
    reason,
):
    case.provider.lose_response = True
    await case.worker.system()
    pending = await case.repository.get(case.subscription.id)
    order = await transaction_repository.get_by_id(pending.pending_transaction_id)
    assert order.external_payment_id is None and pending.submitted_at is not None
    async with uow:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == order.id)
            .values(created_at=datetime_now() - timedelta(hours=24))
        )
    await tick_again(case, uow)
    retired = await case.repository.get(case.subscription.id)
    assert retired.pending_transaction_id is None and not retired.enabled
    if withdrawn:
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
            ),
        )
    notices_before = await notice_types(session)
    payment_id = next(iter(case.provider.references))
    case.provider.status = "canceled"
    case.provider.cancellation_reason = reason
    handler = HandlePaymentWebhookUseCase(
        transaction_repository,
        gateway_repository,
        case.worker._poller._factory,
        user_repository,
        RecordingEventPublisher(),
        uow,
        case.dispatch,
        make_recurring_lifecycle(session),
    )
    callback = HandleWebhookDto(
        gateway_type=PaymentGatewayType.YOOKASSA,
        request=WebhookRequest(
            body=json.dumps(
                {
                    "event": "payment.canceled",
                    "object": {
                        "id": payment_id,
                        "metadata": {"order_ref": order.idempotency_key},
                    },
                }
            ).encode(),
            headers={},
            client_ip="185.71.76.1",
        ),
    )
    await handler.system(callback)
    await handler.system(callback)
    after = await case.repository.get(case.subscription.id)
    canceled = await transaction_repository.get_by_id(order.id)
    assert (
        canceled.status is TransactionStatus.CANCELED and canceled.external_payment_id == payment_id
    )
    assert after.submitted_at is None and after.pending_transaction_id is None
    assert len(case.provider.posts) == 1 and not case.dispatch.messages
    if withdrawn:
        assert (
            after.customer_disabled
            and not after.enabled
            and after.last_error == "customer_disabled"
        )
        assert await notice_types(session) == notices_before
    elif reason == "insufficient_funds":
        assert after.enabled and after.retry_count == 1 and after.last_error == reason
        assert await notice_types(session) == [*notices_before, "RecurringPaymentFailedEvent"]
    else:
        assert not after.enabled and after.payment_method_id is None and after.last_error == reason
    if reason == "permission_revoked":
        assert after.payment_method_id is None


@pytest.mark.usefixtures("production_session_mode")
async def test_overdue_terminal_failure_does_not_send_another_final_notice(case, session, uow):
    case.provider.status = "canceled"
    case.provider.cancellation_reason = "card_expired"
    await case.worker.system()
    before = await notice_types(session)
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() - timedelta(days=10))
        )
        await case.repository.list_due(datetime_now(), due_before=datetime_now(), limit=100)
    assert await notice_types(session) == before
    after = await case.repository.get(case.subscription.id)
    assert not after.enabled and after.last_error == "card_expired"


async def test_an_unknown_stored_reason_keeps_the_mandate_out_of_the_debit_queue(
    case, session, uow
):
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(last_error="renamed_in_a_later_version", next_attempt_at=datetime_now())
        )
    future = datetime_now() + timedelta(days=60)
    assert case.subscription.id not in await case.repository.list_due(
        datetime_now(), due_before=future, limit=100
    )
