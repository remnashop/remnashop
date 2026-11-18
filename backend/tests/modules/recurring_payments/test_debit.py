import asyncio
import json
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text, update

import app.modules.recurring_payments.debit as worker_module
import app.modules.recurring_payments.repository as recurring_repository_module
from app.core.db.models import (
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
from app.modules.plans.dto import (
    SetPlanDurationDto,
    SetPlanDurationsDto,
)
from app.modules.recurring_payments.dto import (
    SetRecurringPaymentDto,
)
from app.modules.recurring_payments.policy import (
    RecurringReason,
    recurring_policy,
)
from app.modules.recurring_payments.terms import build_recurring_terms
from app.modules.settings.dto import UpdateShopSettingsDto
from app.modules.subscriptions.tasks import purchase_subscription_task
from app.modules.subscriptions.usecases import FulfillPurchaseUseCase
from app.modules.transactions.dto import (
    CreateTransactionDto,
    HandleWebhookDto,
    MarkOrderFulfilledDto,
    WebhookRequest,
)
from app.modules.transactions.usecases import (
    HandlePaymentWebhookUseCase,
    MarkOrderFulfilledUseCase,
)
from tests.fakes.events import RecordingEventPublisher
from tests.fakes.recurring import ShippedRecurringTermsTexts, make_recurring_lifecycle
from tests.fakes.remnawave import _user_payload
from tests.modules.recurring_payments.harness import (
    notice_types,
    tick_again,
)
from tests.modules.transactions.test_repository import _order_dto


async def test_due_subscription_is_charged_once_and_dispatched_as_a_renewal(
    case, transaction_repository, uow
) -> None:
    await case.worker.system()
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1
    assert len(case.dispatch.messages) == 1
    mandate = await case.repository.get(case.subscription.id)
    order = await transaction_repository.get_by_id(mandate.pending_transaction_id)
    assert order.status is TransactionStatus.PAID
    assert order.is_recurring
    assert order.final_price == Decimal("500")
    assert order.discount_source is DiscountSource.NONE
    assert order.target_subscription_id == case.subscription.id
    assert case.dispatch.messages[0]["purchase_type"] == "RENEW"
    assert json.loads(case.provider.posts[0].content)["payment_method_id"] == "method-token"


async def test_an_expired_idempotency_key_is_never_sent_again(case, session, uow) -> None:
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
    state = await case.get_state(case.user, case.subscription.id)
    assert not state.enabled
    assert state.last_error == "payment_status_unknown"
    assert len(case.provider.posts) == 1


async def test_disabling_shop_stops_new_requests_but_confirms_in_flight_payment(
    case, gateway_repository, uow
) -> None:
    case.provider.status = "pending"
    await case.worker.system()
    async with uow:
        await gateway_repository.update_settings(
            PaymentGatewayType.YOOKASSA, {"payment_mode": "single"}
        )
    case.provider.status = "succeeded"
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1
    assert len(case.dispatch.messages) == 1


@pytest.mark.parametrize("setting", ["payment_mode", "is_active"])
async def test_disabled_gateway_never_starts_a_charge(
    case, gateway_repository, uow, setting
) -> None:
    async with uow:
        if setting == "is_active":
            await gateway_repository.set_active(PaymentGatewayType.YOOKASSA, False)
        else:
            await gateway_repository.update_settings(
                PaymentGatewayType.YOOKASSA, {setting: "single"}
            )
    await case.worker.system()
    assert not case.provider.posts


async def test_a_price_above_the_agreed_limit_stops_auto_renew(case, plan_repository, uow) -> None:
    async with uow:
        await plan_repository.set_durations(
            SetPlanDurationsDto(
                plan_id=case.source.plan_id,
                durations=[SetPlanDurationDto(days=30, order_index=0, base_price=Decimal("600"))],
            )
        )
    await case.worker.system()
    assert not case.provider.posts
    assert (await case.get_state(case.user, case.subscription.id)).last_error == "price_changed"


@pytest.mark.parametrize("status", [SubscriptionStatus.DELETED, SubscriptionStatus.DISABLED])
async def test_deleted_or_disabled_subscriptions_are_not_charged(
    case, session, uow, status
) -> None:
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(status=status)
        )
    await case.worker.system()
    assert not case.provider.posts


async def test_blocked_customer_is_not_charged(case, user_repository, uow) -> None:
    async with uow:
        await user_repository.set_blocked(case.user.id, True)
    await case.worker.system()
    assert not case.provider.posts


async def test_plaintext_tokens_are_not_stored_or_returned(case, session) -> None:
    stored = await session.scalar(
        text("SELECT payment_method_id FROM recurring_payments WHERE subscription_id = :id"),
        {"id": case.subscription.id},
    )
    state = await case.get_state(case.user, case.subscription.id)
    assert stored != "method-token"
    assert "method-token" not in repr(state)
    assert "method-token" not in repr(await case.repository.get(case.subscription.id))


async def test_changing_shop_never_uses_a_method_from_another_merchant(
    case, gateway_repository, uow
) -> None:
    async with uow:
        await gateway_repository.update_settings(
            PaymentGatewayType.YOOKASSA, {"shop_id": "different"}
        )
    await case.worker.system()
    assert not case.provider.posts


async def test_recurring_payment_runs_the_real_subscription_fulfillment_once(
    case,
    remnawave_store,
    purchase_subscription_use_case,
    user_repository,
    transaction_repository,
    subscription_repository,
    uow,
) -> None:
    remnawave_store[case.subscription.remnawave_user_id] = _user_payload(
        user_id=case.subscription.remnawave_user_id,
        username="recurring-buyer",
        expire_at=case.subscription.expire_at,
        active_internal_squads=[str(squad) for squad in case.source.plan_snapshot.internal_squads],
    )
    await case.worker.system()
    task = purchase_subscription_task.original_func.__dishka_orig_func__
    fulfill = FulfillPurchaseUseCase(
        user_repository, purchase_subscription_use_case, transaction_repository, uow
    )
    await task(**case.dispatch.messages[0], use_case=fulfill)
    first = await subscription_repository.get_by_id(case.subscription.id)
    await task(**case.dispatch.messages[0], use_case=fulfill)
    second = await subscription_repository.get_by_id(case.subscription.id)
    assert first.expire_at > case.subscription.expire_at + timedelta(days=29)
    assert second.expire_at == first.expire_at
    await MarkOrderFulfilledUseCase(
        transaction_repository, uow, make_recurring_lifecycle(transaction_repository.session)
    ).system(
        MarkOrderFulfilledDto(
            payment_key=case.dispatch.messages[0]["idempotency_key"], subscription_id=first.id
        )
    )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1


async def test_retry_preserves_receipt_after_a_gateway_settings_change(
    case, gateway_repository, uow
) -> None:
    async with uow:
        await gateway_repository.update_settings(PaymentGatewayType.YOOKASSA, {"vat_code": "1"})
    case.provider.lose_response = True
    await case.worker.system()
    async with uow:
        await gateway_repository.update_settings(PaymentGatewayType.YOOKASSA, {"vat_code": "2"})
    await tick_again(case, uow)
    assert len(case.provider.posts) == 2
    assert case.provider.posts[0].content == case.provider.posts[1].content
    assert json.loads(case.provider.posts[1].content)["receipt"]["items"][0]["vat_code"] == 1


async def test_a_rejected_retry_cannot_establish_that_the_original_was_not_paid(
    case, transaction_repository, uow
) -> None:
    case.provider.lose_response = True
    await case.worker.system()
    pending = await case.repository.get(case.subscription.id)
    case.provider.reject = True
    await tick_again(case, uow)
    mandate = await case.repository.get(case.subscription.id)
    order = await transaction_repository.get_by_id(pending.pending_transaction_id)
    assert order.status is TransactionStatus.PENDING
    assert mandate.pending_transaction_id == order.id
    assert mandate.last_error == "merchant_unavailable"
    assert mandate.enabled
    assert len(case.provider.keys) == 1


@pytest.mark.parametrize("original_email", [None, "previous-buyer@example.com"])
async def test_recurring_receipt_uses_current_shop_payment_email(
    case,
    settings_repository,
    gateway_repository,
    transaction_repository,
    session,
    uow,
    original_email,
) -> None:
    async with uow:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == case.source.id)
            .values(customer_email=original_email)
        )
        await settings_repository.update_shop_settings(
            UpdateShopSettingsDto(
                payment_email="shop@example.com", fields_set=frozenset({"payment_email"})
            )
        )
        await gateway_repository.update_settings(PaymentGatewayType.YOOKASSA, {"vat_code": "1"})
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    order = await transaction_repository.get_by_id(mandate.pending_transaction_id)
    assert order.customer_email == "shop@example.com"
    body = json.loads(case.provider.posts[0].content)
    assert body["receipt"]["customer"]["email"] == "shop@example.com"


async def test_retry_preserves_payment_email_after_shop_settings_change(
    case,
    settings_repository,
    gateway_repository,
    uow,
) -> None:
    async with uow:
        await settings_repository.update_shop_settings(
            UpdateShopSettingsDto(
                payment_email="first-shop@example.com", fields_set=frozenset({"payment_email"})
            )
        )
        await gateway_repository.update_settings(PaymentGatewayType.YOOKASSA, {"vat_code": "1"})
    case.provider.lose_response = True
    await case.worker.system()
    async with uow:
        await settings_repository.update_shop_settings(
            UpdateShopSettingsDto(
                payment_email="second-shop@example.com", fields_set=frozenset({"payment_email"})
            )
        )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 2
    assert case.provider.posts[0].content == case.provider.posts[1].content
    assert (
        json.loads(case.provider.posts[1].content)["receipt"]["customer"]["email"]
        == "first-shop@example.com"
    )


async def test_an_ambiguous_request_is_not_retried_beyond_the_agreed_overdue_window(
    case,
    session,
    uow,
):
    case.provider.lose_response = True
    await case.worker.system()
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(
                expire_at=datetime_now()
                - timedelta(hours=recurring_policy({}).max_overdue_hours + 1)
            )
        )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1
    mandate = await case.repository.get(case.subscription.id)
    assert not mandate.enabled and mandate.last_error == "renewal_window_expired"


async def test_auto_charge_waits_for_pending_manual_order(
    case, transaction_repository, uow
) -> None:
    async with uow:
        await transaction_repository.create(
            replace(
                _order_dto(
                    user_id=case.user.id,
                    plan_id=case.source.plan_id,
                    idempotency_key="manual-open",
                ),
                purchase_type=PurchaseType.RENEW,
                target_subscription_id=case.subscription.id,
            )
        )
    await case.worker.system()
    assert not case.provider.posts
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.pending_transaction_id is None
    assert mandate.next_attempt_at > datetime_now()


@pytest.mark.usefixtures("production_session_mode")
async def test_one_day_plan_does_not_charge_again_at_purchase(case, session, uow, plan_repository):
    snapshot = replace(case.source.plan_snapshot, duration_days=1)
    expiry = datetime_now() + timedelta(days=1)
    async with uow:
        await plan_repository.set_durations(
            SetPlanDurationsDto(
                plan_id=snapshot.plan_id,
                durations=[SetPlanDurationDto(days=1, order_index=0, base_price=Decimal("500"))],
            )
        )
        terms = await build_recurring_terms(
            texts=ShippedRecurringTermsTexts(),
            policy=recurring_policy({}),
            user_id=case.user.id,
            plan_id=snapshot.plan_id,
            target_subscription_id=case.subscription.id,
            purchase_type=PurchaseType.RENEW,
            initial_amount=Decimal("500"),
            amount_limit=Decimal("500"),
            currency=Currency.RUB,
            duration_days=1,
            locale=case.user.language,
        )
        consent_id = await case.repository.record_consent(
            terms, channel=PurchaseChannel.BOT, telegram_id=case.user.telegram_id
        )
        await session.execute(
            update(Transaction)
            .where(Transaction.id == case.source.id)
            .values(duration_days=1, plan_snapshot=snapshot.to_json())
        )
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=expiry, plan_snapshot=snapshot.to_json())
        )
        await case.lifecycle.set_enabled(case.subscription.id, True, consent_id=consent_id)
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    assert terms.lead_minutes == 720
    assert "720" in terms.text
    assert not case.provider.posts
    assert mandate.next_attempt_at == expiry - timedelta(hours=12)
    state = await case.get_state(case.user, case.subscription.id)
    assert state.next_payment_at == mandate.next_attempt_at


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize("customer", [True, False])
async def test_unsent_reserved_payment_is_canceled_without_unknown_outcome(
    case, customer, gateway_repository, transaction_repository, session, uow
):
    await case.worker.reservation.reserve(await case.repository.get(case.subscription.id))
    reserved = await case.repository.get(case.subscription.id)
    if customer:
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
            ),
        )
    else:
        async with uow:
            await gateway_repository.update_settings(
                PaymentGatewayType.YOOKASSA, {"payment_mode": "single"}
            )
    await case.worker.debit.charge_or_poll(case.subscription.id)
    current = await case.repository.get(case.subscription.id)
    assert current.pending_transaction_id is None and current.submitted_at is None
    assert (
        await transaction_repository.get_by_id(reserved.pending_transaction_id)
    ).status is TransactionStatus.CANCELED
    assert not case.provider.posts
    assert not await notice_types(session)
    assert current.last_error != "payment_status_unknown"


@pytest.mark.usefixtures("production_session_mode")
async def test_canceled_worker_keeps_durable_possible_submission(case, monkeypatch):
    await case.worker.reservation.reserve(await case.repository.get(case.subscription.id))
    _mandate, order, _ = await case.worker.debit._pending_context(case.subscription.id)
    monkeypatch.setattr(
        worker_module, "submit_recurring", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await case.worker.debit._submit(case.subscription.id, order)
    current = await case.repository.get(case.subscription.id)
    assert current.submitted_at is not None and current.pending_transaction_id == order.id


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize(
    "body",
    [
        {"type": "error", "code": "invalid_request", "parameter": "receipt.items"},
        {
            "type": "error",
            "code": "invalid_request",
            "parameter": "payment_method_id",
            "description": "Payment method not found",
        },
        {
            "type": "error",
            "code": "invalid_request",
            "parameter": "payment_method_id",
            "description": "Payment method is not available",
        },
        {"type": "error", "code": "invalid_request", "description": "Новая формулировка"},
    ],
)
async def test_http400_stops_the_debit_whatever_its_wording(case, session, body):
    case.provider.reject = True
    case.provider.reject_body = body
    await case.worker.system()
    current = await case.repository.get(case.subscription.id)
    assert current.last_error == "provider_request_rejected" and current.enabled
    # the method stays, so an admin can retry once the shop side is fixed
    assert current.payment_method_id is not None
    assert current.bank_retry_at is None and current.first_failure_at is None
    assert len(await notice_types(session)) == 1
    reason = RecurringReason.PROVIDER_REQUEST_REJECTED
    assert reason.policy.customer_notice and reason.policy.admin_notice
    assert not reason.policy.allows_debit


@pytest.mark.usefixtures("production_session_mode")
async def test_manual_checkout_cannot_cancel_a_reserved_recurring_debit(
    case, transaction_repository, uow
):
    case.provider.status = "pending"
    await case.worker.system()
    before = await case.repository.get(case.subscription.id)
    async with uow:
        result = await transaction_repository.cancel_own_pending(
            before.pending_transaction_id, case.user.id
        )
    assert result is None
    assert (
        await transaction_repository.get_by_id(before.pending_transaction_id)
    ).status is TransactionStatus.PENDING
    after = await case.repository.get(case.subscription.id)
    assert after.pending_transaction_id == before.pending_transaction_id and after.enabled
    assert await case.repository.consent_terms(after.consent_id) is not None


async def _prepare(case):
    mandate = await case.repository.get(case.subscription.id)
    await case.worker.reservation.reserve(mandate)
    context = await case.worker.debit._pending_context(case.subscription.id)
    assert context is not None
    return context


@pytest.mark.parametrize("code", [200, 400, 401, 403, 404])
async def test_submission_persists_the_outcome_before_releasing_authorization(
    case, transaction_repository, code
):
    _, order, _ = await _prepare(case)
    case.provider.reject = code != 200
    case.provider.reject_code = code

    result = await case.worker.debit._submit(
        case.subscription.id,
        order,
    )

    assert result is not None
    saved = await transaction_repository.get_by_id(order.id)
    current = await case.repository.get(case.subscription.id)
    if code == 200:
        assert saved.status is TransactionStatus.PENDING
        assert saved.external_payment_id == result.payment_id
        assert current.pending_transaction_id == order.id
    else:
        assert saved.status is TransactionStatus.FAILED
        assert saved.external_payment_id is None
        assert current.pending_transaction_id is None
    error = current.last_error
    case.provider.reject = False

    # The queued task may still carry the original, unsent order DTO and first flag.
    replay = await case.worker.debit._submit(
        case.subscription.id,
        order,
    )

    assert replay is None
    assert len(case.provider.posts) == 1
    after = await case.repository.get(case.subscription.id)
    assert after.pending_transaction_id == current.pending_transaction_id
    assert after.last_error == error


@pytest.mark.parametrize("code", [400, 401])
async def test_delayed_first_preparation_cannot_retire_a_later_ambiguous_submission(
    case, transaction_repository, code
):
    initial, order, _ = await _prepare(case)
    later = await case.worker.debit._pending_context(case.subscription.id)
    assert later is not None
    retry, retry_order, _ = later
    assert initial.submitted_at is None and retry.submitted_at is None
    case.provider.lose_response = True

    with pytest.raises(httpx.ReadTimeout):
        await case.worker.debit._submit(
            case.subscription.id,
            retry_order,
        )

    first_marker = (await case.repository.get(case.subscription.id)).submitted_at
    assert first_marker is not None
    # The newer request reached YooKassa, so even a definite refusal for the delayed
    # first preparation cannot establish that this idempotency key was never charged.
    case.provider.reject = True
    case.provider.reject_code = code
    result = await case.worker.debit._submit(
        case.subscription.id,
        order,
    )

    assert result is not None and result.outcome == "ambiguous"
    saved = await transaction_repository.get_by_id(order.id)
    current = await case.repository.get(case.subscription.id)
    assert saved.status is TransactionStatus.PENDING
    assert saved.external_payment_id is None
    assert current.pending_transaction_id == order.id
    assert current.submitted_at > first_marker
    assert current.enabled
    assert len(case.provider.posts) == 2
    assert len(case.provider.keys) == 1
    assert {request.headers["Idempotence-Key"] for request in case.provider.posts} == {
        order.idempotency_key
    }


async def test_submission_markers_advance_when_the_clock_is_frozen(case, monkeypatch):
    frozen = datetime_now()
    monkeypatch.setattr(recurring_repository_module, "datetime_now", lambda: frozen)
    _, order, _ = await _prepare(case)
    case.provider.lose_response = True
    with pytest.raises(httpx.ReadTimeout):
        await case.worker.debit._submit(case.subscription.id, order)
    assert (await case.repository.get(case.subscription.id)).submitted_at == frozen
    result = await case.worker.debit._submit(case.subscription.id, order)
    assert result is not None and result.outcome == "accepted"
    current = await case.repository.get(case.subscription.id)
    assert current.submitted_at == frozen + timedelta(microseconds=1)
    await case.worker.debit._pending_context(case.subscription.id)
    assert (await case.repository.get(case.subscription.id)).submitted_at == current.submitted_at
    assert len(case.provider.keys) == 1


@pytest.mark.parametrize("code", [400, 401])
async def test_stale_submission_cannot_change_a_replacement_attempt(
    case, transaction_repository, uow, code
):
    _, old_order, _ = await _prepare(case)
    case.provider.reject = True
    case.provider.reject_code = code
    await case.worker.debit._submit(
        case.subscription.id,
        old_order,
    )
    values = {field.name: getattr(old_order, field.name) for field in fields(CreateTransactionDto)}
    values["idempotency_key"] = uuid4().hex
    async with uow:
        replacement = await transaction_repository.create(CreateTransactionDto(**values))
        await case.lifecycle.set_pending(
            case.subscription.id,
            replacement.id,
            expire_at=case.subscription.expire_at,
        )
        await case.lifecycle.defer(
            case.subscription.id,
            datetime_now() + timedelta(minutes=5),
            "provider_unavailable",
        )
    case.provider.reject = False

    await case.worker.debit._submit(
        case.subscription.id,
        old_order,
    )

    current = await case.repository.get(case.subscription.id)
    assert current.pending_transaction_id == replacement.id
    assert current.last_error == "provider_unavailable"
    assert len(case.provider.posts) == 1


@pytest.mark.usefixtures("production_session_mode")
async def test_post_runs_without_open_transaction(case, session) -> None:
    observed: list[bool] = []

    async def hook(payment_id: str) -> None:
        observed.append(session.in_transaction())

    case.provider.on_post = hook
    await case.worker.system()
    assert observed == [False]


@pytest.mark.usefixtures("production_session_mode")
async def test_disable_during_post_stops_next_cycle(case, session, uow) -> None:
    states = []

    async def hook(payment_id: str) -> None:
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
            ),
        )
        states.append(await case.get_state(case.user, case.subscription.id))

    case.provider.on_post = hook
    await case.worker.system()
    case.provider.on_post = None
    assert states and states[0].payment_in_flight and not states[0].enabled
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.customer_disabled and not mandate.enabled


@pytest.mark.usefixtures("production_session_mode")
async def test_webhook_before_record_settles_once(
    case, session, uow, transaction_repository, gateway_repository, user_repository
) -> None:
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
    seen: list[int] = []

    async def hook(payment_id: str) -> None:
        mandate = await case.repository.get(case.subscription.id)
        order = await transaction_repository.get_by_id(mandate.pending_transaction_id)
        seen.append(order.id)
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

    case.provider.on_post = hook
    await case.worker.system()
    case.provider.on_post = None
    order = await transaction_repository.get_by_id(seen[0])
    assert order.status is TransactionStatus.PAID
    assert len(case.dispatch.messages) == 1
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1 and len(case.dispatch.messages) == 1
