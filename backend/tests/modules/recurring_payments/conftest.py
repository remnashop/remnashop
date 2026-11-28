from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.models import Transaction
from app.core.enums import (
    Currency,
    DiscountSource,
    PaymentGatewayType,
    PlanType,
    PurchaseChannel,
    PurchaseType,
    SubscriptionStatus,
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
from app.modules.plans.repository import PlanRepository
from app.modules.recurring_payments.checks import RecurringDebitChecks
from app.modules.recurring_payments.debit import RecurringDebit
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
from app.modules.subscriptions.dto import CreateSubscriptionDto, PlanSnapshot
from app.modules.transactions.checkout_pricing import CheckoutPricer
from app.modules.transactions.dto import (
    CreateTransactionDto,
)
from app.modules.transactions.gateways.base import PaymentHttpClient
from app.modules.transactions.gateways.factory import PaymentGatewayFactory
from app.modules.transactions.repository import TransactionRepository
from app.modules.transactions.waitlist_repository import WaitlistRepository
from app.modules.users.dto import CreateUserDto
from app.modules.users.repository import UserRepository
from tests.fakes.dispatch import RecordingDispatch
from tests.fakes.events import RecordingEventPublisher
from tests.fakes.payment_texts import FixedPaymentTexts
from tests.fakes.recurring import ShippedRecurringTermsTexts, fulfil, make_recurring_lifecycle
from tests.modules.recurring_payments.harness import (
    FakeYooKassa,
    RecurringCase,
    Worker,
)
from tests.modules.subscriptions.factories import make_change_credit_calculator, make_eligibility


@pytest.fixture
def transaction_repository(session: AsyncSession) -> TransactionRepository:
    return TransactionRepository(session)


@pytest.fixture
def waitlist_repository(session: AsyncSession) -> WaitlistRepository:
    return WaitlistRepository(session)


@pytest.fixture
async def user_id(user_repository: UserRepository) -> int:
    user = await user_repository.create(CreateUserDto(name="buyer", telegram_id=900_001))
    return user.id


@pytest.fixture
async def plan_id(plan_repository: PlanRepository) -> int:
    plan = await plan_repository.create(
        CreatePlanDto(
            public_code="transaction-test-plan",
            name="Payment Order Test Plan",
            type=PlanType.BOTH,
            traffic_limit=100,
            device_limit=3,
        )
    )
    return plan.id


@pytest.fixture
def production_session_mode(session):
    session.autoflush = False


@pytest.fixture
async def case(
    session,
    uow,
    user_repository,
    subscription_repository,
    plan_repository,
    transaction_repository,
    gateway_repository,
    settings_repository,
    pricing_repository,
    promocode_repository,
    config,
    remnawave_sdk,
):
    async with uow:
        user = await user_repository.create(
            CreateUserDto(name="recurring buyer", telegram_id=931001)
        )
        plan = await plan_repository.create(
            CreatePlanDto(
                name="Recurring plan",
                public_code="recurring-plan",
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
        snapshot = PlanSnapshot.from_plan(
            plan, price_paid=Decimal("400"), currency=Currency.RUB, duration_days=30
        )
        subscription = await subscription_repository.create(
            CreateSubscriptionDto(
                user_id=user.id,
                remnawave_user_id=931001,
                status=SubscriptionStatus.ACTIVE,
                traffic_limit=100,
                device_limit=3,
                expire_at=datetime_now() + timedelta(minutes=30),
                url="https://example.com/recurring",
                plan_snapshot=snapshot,
            )
        )
        await gateway_repository.update_settings(
            PaymentGatewayType.YOOKASSA,
            {
                "shop_id": "1000",
                "api_key": "test-key",
                "payment_mode": "both",
            },
        )
        await gateway_repository.set_active(PaymentGatewayType.YOOKASSA, True)
        consent_id = await RecurringPaymentRepository(session).record_consent(
            await build_recurring_terms(
                texts=ShippedRecurringTermsTexts(),
                policy=recurring_policy({}),
                user_id=user.id,
                plan_id=plan.id,
                target_subscription_id=None,
                purchase_type=PurchaseType.NEW,
                initial_amount=Decimal("400"),
                amount_limit=Decimal("500"),
                currency=Currency.RUB,
                duration_days=30,
                locale=user.language,
            ),
            channel=PurchaseChannel.BOT,
            telegram_id=user.telegram_id,
            event_id="initial-checkbox",
        )
        source = await transaction_repository.create(
            CreateTransactionDto(
                user_id=user.id,
                plan_id=plan.id,
                plan_snapshot=snapshot,
                duration_days=30,
                currency=Currency.RUB,
                purchase_type=PurchaseType.NEW,
                channel=PurchaseChannel.BOT,
                target_subscription_id=None,
                gateway_type=PaymentGatewayType.YOOKASSA,
                base_price=Decimal("500"),
                final_price=Decimal("400"),
                discount_percent=20,
                discount_source=DiscountSource.PURCHASE,
                anchor_base_price=Decimal("500"),
                anchor_final_price=Decimal("400"),
                customer_email="buyer@example.com",
                idempotency_key=uuid4().hex,
                expires_at=datetime_now(),
                recurring_consent_id=consent_id,
            )
        )
        await transaction_repository.mark_status(source.id, TransactionStatus.PAID)
        await transaction_repository.remember_payment_method(source.id, "method-token", "1000")
        await fulfil(transaction_repository.session, source.id, subscription.id)
        # The original purchase predates the renewal cycle, as it does in production.
        paid_at = datetime_now() - timedelta(days=30)
        await session.execute(
            update(Transaction)
            .where(Transaction.id == source.id)
            .values(created_at=paid_at, updated_at=paid_at, fulfilled_at=paid_at)
        )
    repository = RecurringPaymentRepository(session)
    lifecycle = make_recurring_lifecycle(transaction_repository.session)
    provider = FakeYooKassa()
    dispatch = RecordingDispatch()
    get_state = GetOwnRecurringPaymentUseCase(
        repository,
        transaction_repository,
        subscription_repository,
        gateway_repository,
        uow,
        ShippedRecurringTermsTexts(),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        poller = RecurringPoller(
            repository,
            lifecycle,
            transaction_repository,
            gateway_repository,
            PaymentGatewayFactory(config, PaymentHttpClient(http)),
            dispatch,
            user_repository,
            RecordingEventPublisher(),
            uow,
        )
        checks = RecurringDebitChecks(
            repository, lifecycle, gateway_repository, settings_repository
        )
        reservation = RecurringReservation(
            checks,
            repository,
            lifecycle,
            poller,
            transaction_repository,
            subscription_repository,
            user_repository,
            settings_repository,
            CheckoutPricer(
                plan_repository,
                user_repository,
                make_eligibility(session),
                pricing_repository,
                uow,
                promocode_repository,
                subscription_repository,
                settings_repository,
                make_change_credit_calculator(session, remnawave_sdk),
            ),
            uow,
        )
        debit = RecurringDebit(
            checks,
            repository,
            lifecycle,
            poller,
            transaction_repository,
            subscription_repository,
            user_repository,
            FixedPaymentTexts(),
            uow,
        )
        use_case = ProcessRecurringPaymentUseCase(
            checks, reservation, debit, repository, lifecycle, transaction_repository, uow
        )
        yield RecurringCase(
            Worker(use_case, lifecycle, repository, uow, gateway_repository),
            repository,
            lifecycle,
            uow,
            gateway_repository,
            get_state,
            SetOwnRecurringPaymentUseCase(
                repository, lifecycle, subscription_repository, get_state, uow
            ),
            user,
            subscription,
            source,
            provider,
            dispatch,
        )
