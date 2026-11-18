from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.db.models import RecurringConsent, RecurringPayment, Subscription, Transaction
from app.core.enums import (
    Currency,
    Locale,
    PlanType,
    PurchaseChannel,
    PurchaseType,
    TransactionStatus,
)
from app.core.utils.time import datetime_now
from app.modules.plans.dto import (
    CreatePlanDto,
    SetPlanDurationDto,
    SetPlanDurationsDto,
    UpdatePlanDto,
    UpdatePlanSquadsDto,
)
from app.modules.recurring_payments.dto import (
    SetRecurringPaymentDto,
)
from app.modules.recurring_payments.policy import recurring_policy
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.terms import build_recurring_terms
from app.modules.subscriptions.dto import (
    ChangeSubscriptionPlanDto,
    PurchaseSubscriptionDto,
)
from app.modules.subscriptions.usecases.change_subscription_plan import (
    ChangeSubscriptionPlanUseCase,
)
from tests.fakes.recurring import ShippedRecurringTermsTexts, fulfil
from tests.fakes.remnawave import _user_payload
from tests.modules.recurring_payments.harness import (
    new_subscription,
    notice_types,
    paid_order_with_consent,
    tick_again,
)
from tests.modules.transactions.test_handle_payment_webhook import (
    _order,
    _refunded,
    _report,
    _ReportingGateway,
    purchase_dispatch,
)
from tests.modules.transactions.test_usecases import _seed_subscription


async def test_fulfillment_moves_the_cycle_and_preserves_customer_opt_out(
    case, transaction_repository, session, uow
) -> None:
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(days=30))
        )
        await fulfil(
            transaction_repository.session, mandate.pending_transaction_id, case.subscription.id
        )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1
    state = await case.get_state(case.user, case.subscription.id)
    assert not state.enabled and state.customer_disabled


async def test_delayed_manual_fulfillment_cannot_reenable_a_canceled_subscription(
    case, session, transaction_repository, uow
) -> None:
    async with uow:
        await session.execute(
            update(Transaction).where(Transaction.id == case.source.id).values(fulfilled_at=None)
        )
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(source_transaction_id=None)
        )
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    async with uow:
        await fulfil(transaction_repository.session, case.source.id, case.subscription.id)
    state = await case.get_state(case.user, case.subscription.id)
    assert not state.enabled and state.customer_disabled
    await case.worker.system()
    assert not case.provider.posts


async def test_new_cycle_waits_for_fulfillment_and_current_subscription_expiry(
    case, transaction_repository, session, uow
) -> None:
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(days=30))
        )
        await fulfil(
            transaction_repository.session, mandate.pending_transaction_id, case.subscription.id
        )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 1
    async with uow:
        await session.execute(
            update(Subscription)
            .where(Subscription.id == case.subscription.id)
            .values(expire_at=datetime_now() + timedelta(minutes=30))
        )
    await tick_again(case, uow)
    assert len(case.provider.posts) == 2
    assert len(case.provider.keys) == 2
    assert (
        await session.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.is_recurring.is_(True))
        )
        == 2
    )


async def test_refunding_the_source_stops_future_charges(case, transaction_repository, uow) -> None:
    async with uow:
        await transaction_repository.mark_status(case.source.id, TransactionStatus.REFUNDED)
    await case.worker.system()
    assert not case.provider.posts


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize("withdraw_after_consent", [False, True])
async def test_plan_change_preserves_the_actual_withdrawal_time(
    case,
    transaction_repository,
    subscription_repository,
    session,
    uow,
    withdraw_after_consent,
    plan_repository,
):
    if not withdraw_after_consent:
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
            ),
        )
    async with uow:
        plan = await plan_repository.create(
            CreatePlanDto(
                name="Consent change",
                public_code="consent-change",
                type=PlanType.BOTH,
                traffic_limit=100,
                device_limit=3,
            )
        )
    snapshot = replace(case.source.plan_snapshot, plan_id=plan.id)
    order = await paid_order_with_consent(
        case, transaction_repository, uow, purchase_type=PurchaseType.CHANGE, plan=snapshot
    )
    if withdraw_after_consent:
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
            ),
        )
    old = await case.repository.get(case.subscription.id)
    new = await new_subscription(case, subscription_repository, uow, snapshot)
    async with uow:
        await case.lifecycle.close_for_plan_change(case.subscription.id)
        await fulfil(transaction_repository.session, order.id, new.id)
    changed = await case.repository.get(new.id)
    assert changed.enabled is not withdraw_after_consent
    assert changed.customer_disabled is withdraw_after_consent
    if withdraw_after_consent:
        assert changed.disabled_at == old.disabled_at
    else:
        assert changed.payment_method_id == "new-method"
        assert changed.consent_id == order.recurring_consent_id


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize(
    ("consent", "saved", "disabled"),
    [
        (False, False, False),
        (False, False, True),
        (True, False, False),
        (True, True, False),
        (True, True, True),
    ],
)
async def test_manual_renewal_mandate_decision_table(
    case, transaction_repository, session, uow, consent, saved, disabled
):
    if disabled:
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
            ),
        )
    before = await case.repository.get(case.subscription.id)
    order = await paid_order_with_consent(
        case, transaction_repository, uow, consent=consent, saved=saved
    )
    async with uow:
        await fulfil(transaction_repository.session, order.id, case.subscription.id)
    after = await case.repository.get(case.subscription.id)
    if consent and saved:
        assert after.enabled and after.payment_method_id == "new-method"
        assert after.consent_id == order.recurring_consent_id
    else:
        assert after.enabled == before.enabled
        assert after.payment_method_id == before.payment_method_id
        assert after.consent_id == before.consent_id
        assert after.customer_disabled == before.customer_disabled
    if consent and saved and before.consent_id:
        assert (await session.get(RecurringConsent, before.consent_id)).revoked_at is not None


@pytest.mark.usefixtures("production_session_mode")
@pytest.mark.parametrize("admin", [False, True])
async def test_real_plan_change_closes_old_mandate_before_order_fulfillment(
    case,
    admin,
    plan_repository,
    purchase_subscription_use_case,
    subscription_repository,
    user_repository,
    event_publisher,
    remnawave_store,
    uow,
    session,
):
    remnawave_store[case.subscription.remnawave_user_id] = _user_payload(
        user_id=case.subscription.remnawave_user_id,
        username="recurring-change",
        expire_at=case.subscription.expire_at,
    )
    async with uow:
        plan = await plan_repository.create(
            CreatePlanDto(
                name="Changed plan",
                public_code="changed-plan",
                type=PlanType.BOTH,
                traffic_limit=100,
                device_limit=3,
            )
        )
        plan = await plan_repository.set_durations(
            SetPlanDurationsDto(
                plan_id=plan.id,
                durations=[SetPlanDurationDto(days=30, order_index=0, base_price=Decimal("500"))],
            )
        )
        await plan_repository.update_squads(
            UpdatePlanSquadsDto(plan_id=plan.id, internal_squads=[uuid4()], external_squad=None)
        )
        plan = await plan_repository.update(UpdatePlanDto(plan_id=plan.id, is_active=True))
    if admin:
        changed = await ChangeSubscriptionPlanUseCase(
            subscription_repository,
            user_repository,
            plan_repository,
            purchase_subscription_use_case,
            event_publisher,
            uow,
        ).system(
            ChangeSubscriptionPlanDto(
                subscription_id=case.subscription.id, plan_id=plan.id, duration_days=30
            )
        )
    else:
        changed = await purchase_subscription_use_case.system(
            PurchaseSubscriptionDto(
                user_id=case.user.id,
                plan_snapshot=replace(case.source.plan_snapshot, plan_id=plan.id),
                duration_days=30,
                price_paid=Decimal("500"),
                base_price=Decimal("500"),
                currency=Currency.RUB,
                purchase_type=PurchaseType.CHANGE,
                target_subscription_id=case.subscription.id,
            )
        )
    old = await case.repository.get(case.subscription.id)
    assert not old.enabled
    assert (await session.get(RecurringConsent, old.consent_id)).revoked_at is not None
    assert await case.repository.get(changed.id) is None
    before = len(case.provider.posts)
    await case.worker.system(case.subscription.id)
    assert len(case.provider.posts) == before


@pytest.mark.usefixtures("production_session_mode")
async def test_first_enrollment_without_saved_method_is_reported(
    case, transaction_repository, session, uow
):
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(
                source_transaction_id=None, consent_id=None, payment_method_id=None, enabled=False
            )
        )
    order = await paid_order_with_consent(
        case, transaction_repository, uow, consent=True, saved=False
    )
    async with uow:
        await fulfil(transaction_repository.session, order.id, case.subscription.id)
    current = await case.repository.get(case.subscription.id)
    assert not current.enabled and current.last_error == "payment_method_not_saved"
    assert current.consent_id == order.recurring_consent_id
    assert await notice_types(session) == ["RecurringPaymentPausedEvent"]


__all__ = ["purchase_dispatch"]


async def _mandate(session, uow, subscription_repository, order) -> tuple[int, int]:
    subscription_id = await _seed_subscription(
        subscription_repository,
        user_id=order.user_id,
        remnawave_user_id=830_000 + order.id,
        plan_id=order.plan_id,
    )
    terms = await build_recurring_terms(
        texts=ShippedRecurringTermsTexts(),
        policy=recurring_policy({}),
        user_id=order.user_id,
        plan_id=order.plan_id,
        target_subscription_id=subscription_id,
        purchase_type=PurchaseType.RENEW,
        initial_amount=Decimal("500"),
        amount_limit=Decimal("500"),
        currency=Currency.RUB,
        duration_days=30,
        locale=Locale.RU,
    )
    repository = RecurringPaymentRepository(session)
    async with uow:
        consent_id = await repository.record_consent(
            terms, channel=PurchaseChannel.BOT, telegram_id=None
        )
        await session.execute(
            update(Transaction)
            .where(Transaction.id == order.id)
            .values(target_subscription_id=subscription_id, is_recurring=True)
        )
        session.add(
            RecurringPayment(
                subscription_id=subscription_id,
                enabled=True,
                consent_id=consent_id,
                payment_method_id="pm-saved",
                source_transaction_id=order.id,
                next_attempt_at=datetime_now(),
            )
        )
    return subscription_id, consent_id


@pytest.mark.parametrize(
    "amount", [pytest.param("500.00", id="full"), pytest.param("100.00", id="partial")]
)
async def test_refund_of_a_renewal_disables_auto_renewal(
    amount,
    session,
    transaction_repository,
    subscription_repository,
    user_repository,
    uow,
    user_id,
    plan_id,
    gateway_repository,
    purchase_dispatch,
) -> None:  # type: ignore[no-untyped-def]
    order = await _order(
        transaction_repository, uow, user_id, plan_id, status=TransactionStatus.PAID
    )
    subscription_id, consent_id = await _mandate(session, uow, subscription_repository, order)
    await _report(
        _ReportingGateway(_refunded(amount, "RUB")),
        transaction_repository=transaction_repository,
        user_repository=user_repository,
        uow=uow,
        gateway_repository=gateway_repository,
        purchase_dispatch=purchase_dispatch,
    )
    repository = RecurringPaymentRepository(session)
    mandate = await repository.get(subscription_id)
    assert mandate is not None and not mandate.enabled
    assert mandate.last_error == "refunded"
    assert await repository.consent_terms(consent_id) is None
    assert subscription_id not in await repository.list_due(
        datetime_now(), due_before=datetime_now().replace(year=2100), limit=100
    )
