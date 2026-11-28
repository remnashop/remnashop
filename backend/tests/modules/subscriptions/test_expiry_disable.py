from datetime import timedelta
from decimal import Decimal
from typing import Any, Final, Optional
from uuid import uuid4

import httpx
import pytest
from remnapy import RemnawaveSDK
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.db.models import EventOutboxEntry
from app.core.db.uow import UnitOfWork
from app.core.enums import Currency, Locale, PlanType, PurchaseType, Role, SubscriptionStatus
from app.core.error_codes import ErrorCode
from app.core.exceptions import ValidationError
from app.core.ports import EventPublisher
from app.core.utils.time import datetime_now, truncate_to_ms
from app.modules.plans.dto import (
    CreatePlanDto,
    PlanDto,
    SetPlanDurationDto,
    SetPlanDurationsDto,
    UpdatePlanDto,
)
from app.modules.plans.repository import PlanRepository
from app.modules.pricing.repository import PricingRepository
from app.modules.settings import GraceSettingsDto, SettingsRepository
from app.modules.settings.dto import UpdateGraceSettingsDto
from app.modules.subscriptions.api.schemas import OwnSubscriptionResponse
from app.modules.subscriptions.credit_segment_repository import CreditSegmentRepository
from app.modules.subscriptions.dto import (
    PurchaseSubscriptionDto,
    SetSubscriptionEnabledDto,
    SubscriptionDto,
)
from app.modules.subscriptions.expiry_disable import (
    CLAIM_STALE_AFTER,
    disable_due,
    handled,
    warning_due,
)
from app.modules.subscriptions.idempotency_repository import PurchaseIdempotencyRepository
from app.modules.subscriptions.lifecycle import SubscriptionLifecycleService
from app.modules.subscriptions.panel import restore_expiry_switch_off
from app.modules.subscriptions.repository import SubscriptionRepository
from app.modules.subscriptions.usecases import (
    DisableExpiredSubscriptionUseCase,
    PurchaseSubscriptionUseCase,
    RestoreDuePanelConfigsUseCase,
    SetSubscriptionEnabledUseCase,
    SweepExpiryDisableUseCase,
    WarnOfExpiryDisableUseCase,
)
from app.modules.users.dto import UserDto
from app.modules.users.repository import UserRepository
from tests.fakes.recurring import make_recurring_lifecycle
from tests.fakes.remnawave import FakeUserStore, _user_payload
from tests.modules.subscriptions.factories import (
    create_subscription,
    make_eligibility,
    make_plan_snapshot,
    snapshot_from_plan,
)

OWNER: Final[UserDto] = UserDto(login="owner", name="owner", role=Role.OWNER, language=Locale.EN)
_SETTINGS: Final[GraceSettingsDto] = GraceSettingsDto(
    expiry_disable_enabled=True, expiry_disable_after_days=7, expiry_disable_warn_days=2
)


def _row(**overrides: Any) -> SubscriptionDto:
    now = datetime_now()
    fields: dict[str, Any] = {
        "id": 1,
        "user_id": 1,
        "remnawave_user_id": 1,
        "status": SubscriptionStatus.EXPIRED,
        "traffic_limit": 100,
        "device_limit": 3,
        "effective_traffic_limit": 100,
        "effective_device_limit": 3,
        "expire_at": now - timedelta(days=8),
        "url": "https://example.com/sub/1",
        "plan_snapshot": make_plan_snapshot(),
    }
    return SubscriptionDto(**(fields | overrides))


def test_disable_counts_from_the_grace_end() -> None:
    now = datetime_now()
    expired = _row(expire_at=now - timedelta(days=10), grace_ended_at=now - timedelta(days=6))

    assert not disable_due(expired, _SETTINGS, now)
    assert disable_due(expired, _SETTINGS, now + timedelta(days=1))


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": SubscriptionStatus.ACTIVE},
        {"status": SubscriptionStatus.DISABLED},
        {"grace_until": datetime_now() + timedelta(days=1)},
        {"expire_at": datetime_now() - timedelta(days=6)},
    ],
)
def test_disable_is_not_due(overrides: dict[str, Any]) -> None:
    assert not disable_due(_row(**overrides), _SETTINGS, datetime_now())


def test_disable_is_off_with_the_rule() -> None:
    off = _SETTINGS.model_copy(update={"expiry_disable_enabled": False})

    assert not disable_due(_row(), off, datetime_now())


def test_warning_window() -> None:
    now = datetime_now()

    assert warning_due(_row(expire_at=now - timedelta(days=6)), _SETTINGS, now)
    # too early: more than two days before the switch-off
    assert not warning_due(_row(expire_at=now - timedelta(days=4)), _SETTINGS, now)
    # the switch-off date has passed: switched off without one
    assert not warning_due(_row(expire_at=now - timedelta(days=8)), _SETTINGS, now)
    no_warning = _SETTINGS.model_copy(update={"expiry_disable_warn_days": 0})
    assert not warning_due(_row(expire_at=now - timedelta(days=6)), no_warning, now)


def test_warning_goes_once_per_expiry() -> None:
    now = datetime_now()
    expire_at = now - timedelta(days=6)

    assert not warning_due(
        _row(expire_at=expire_at, expiry_disable_warned_at=now - timedelta(hours=1)),
        _SETTINGS,
        now,
    )
    # warned of an earlier expiry, renewed and lapsed again since
    assert warning_due(
        _row(expire_at=expire_at, expiry_disable_warned_at=expire_at - timedelta(days=40)),
        _SETTINGS,
        now,
    )


def test_customer_sees_an_expiry_switch_off_as_expired() -> None:
    switched_off = _row(status=SubscriptionStatus.DISABLED, expiry_disabled_at=datetime_now())
    by_admin = _row(status=SubscriptionStatus.DISABLED)

    assert switched_off.disabled_by_expiry
    assert switched_off.customer_status is SubscriptionStatus.EXPIRED
    assert not by_admin.disabled_by_expiry
    assert by_admin.customer_status is SubscriptionStatus.DISABLED
    response = OwnSubscriptionResponse.from_dto(switched_off, secret="s", locale=Locale.EN)
    assert response.status is SubscriptionStatus.EXPIRED


class _Rule:
    def __init__(
        self,
        session: AsyncSession,
        sdk: RemnawaveSDK,
        uow: UnitOfWork,
        publisher: EventPublisher,
    ) -> None:
        subscriptions = SubscriptionRepository(session)
        settings = SettingsRepository(session)
        self.lifecycle = SubscriptionLifecycleService(
            subscriptions, CreditSegmentRepository(session)
        )
        self.disable = DisableExpiredSubscriptionUseCase(
            subscriptions, settings, self.lifecycle, sdk, uow, publisher
        )
        self.warn = WarnOfExpiryDisableUseCase(
            subscriptions, settings, UserRepository(session), uow, publisher
        )
        self.sweep = SweepExpiryDisableUseCase(
            subscriptions, settings, uow, self.warn, self.disable
        )
        self.purchase = PurchaseSubscriptionUseCase(
            subscriptions,
            make_eligibility(session),
            sdk,
            uow,
            publisher,
            self.lifecycle,
            PricingRepository(session),
            PurchaseIdempotencyRepository(session),
            UserRepository(session),
            AppConfig.get(),
            settings,
            recurring_closer=make_recurring_lifecycle(session),
        )
        self.set_enabled = SetSubscriptionEnabledUseCase(
            subscriptions,
            UserRepository(session),
            settings,
            sdk,
            self.lifecycle,
            publisher,
            uow,
        )


@pytest.fixture
def rule(
    session: AsyncSession,
    remnawave_sdk: RemnawaveSDK,
    uow: UnitOfWork,
    event_publisher: EventPublisher,
) -> _Rule:
    return _Rule(session, remnawave_sdk, uow, event_publisher)


async def _switch_on(settings_repository: SettingsRepository, warn_days: int = 2) -> None:
    await settings_repository.update_grace_settings(
        UpdateGraceSettingsDto(
            expiry_disable_enabled=True,
            expiry_disable_after_days=7,
            expiry_disable_warn_days=warn_days,
            fields_set=frozenset(
                {"expiry_disable_enabled", "expiry_disable_after_days", "expiry_disable_warn_days"}
            ),
        )
    )


async def _plan(plan_repository: PlanRepository) -> PlanDto:
    plan = await plan_repository.create(
        CreatePlanDto(
            public_code=f"exp{uuid4().hex[:6]}",
            name=f"exp{uuid4().hex[:6]}",
            type=PlanType.BOTH,
            traffic_limit=100,
            device_limit=3,
        )
    )
    await plan_repository.set_durations(
        SetPlanDurationsDto(
            plan_id=plan.id,
            durations=[SetPlanDurationDto(days=30, order_index=0, base_price=Decimal("500.00"))],
        )
    )
    return await plan_repository.update(UpdatePlanDto(plan_id=plan.id, is_active=True))


async def _expired(
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    store: FakeUserStore,
    panel_id: int,
    *,
    days_ago: float,
    plan: Optional[PlanDto] = None,
) -> SubscriptionDto:
    expire_at = truncate_to_ms(datetime_now() - timedelta(days=days_ago))
    subscription = await create_subscription(
        subscription_repository,
        user_repository,
        telegram_id=panel_id,
        remnawave_user_id=panel_id,
        status=SubscriptionStatus.EXPIRED,
        expire_at=expire_at,
        **({"plan_id": plan.id} if plan is not None else {}),
    )
    payload = _user_payload(user_id=panel_id, username=f"rs_{panel_id}", expire_at=expire_at)
    payload["status"] = "EXPIRED"
    store[panel_id] = payload
    return subscription


async def _events(session: AsyncSession, subscription_id: int, event_type: str) -> int:
    result = await session.scalars(
        select(EventOutboxEntry.id).where(
            EventOutboxEntry.payload["subscription_id"].as_integer() == subscription_id,
            EventOutboxEntry.event_type == event_type,
        )
    )
    return len(result.all())


async def test_sweep_switches_off_a_subscription_expired_past_the_days(
    rule: _Rule,
    session: AsyncSession,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository)
    due = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_001, days_ago=8
    )
    early = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_002, days_ago=3
    )

    await rule.sweep.system()

    switched_off = await subscription_repository.get_by_id(due.id)
    assert switched_off.status is SubscriptionStatus.DISABLED
    assert switched_off.disabled_by_expiry
    assert remnawave_store[96_001]["status"] == "DISABLED"
    assert remnawave_store[96_001]["droppedConnections"] == 1
    assert await _events(session, due.id, "SubscriptionExpiryDisabledEvent") == 1
    assert (await subscription_repository.get_by_id(early.id)).status is SubscriptionStatus.EXPIRED
    assert remnawave_store[96_002]["status"] == "EXPIRED"

    # a repeat run finds nothing left to do
    await rule.sweep.system()
    assert remnawave_store[96_001]["droppedConnections"] == 1


async def test_sweep_does_nothing_with_the_rule_off(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    remnawave_store: FakeUserStore,
) -> None:
    due = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_011, days_ago=30
    )

    await rule.sweep.system()

    assert (await subscription_repository.get_by_id(due.id)).status is SubscriptionStatus.EXPIRED
    assert remnawave_store[96_011]["status"] == "EXPIRED"


async def test_sweep_warns_once_ahead_of_the_switch_off(
    rule: _Rule,
    session: AsyncSession,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository)
    soon = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_021, days_ago=6
    )

    await rule.sweep.system()
    await rule.sweep.system()

    assert await _events(session, soon.id, "SubscriptionExpiryDisableWarningEvent") == 1
    still = await subscription_repository.get_by_id(soon.id)
    assert still.status is SubscriptionStatus.EXPIRED
    assert still.expiry_disable_warned_at is not None


async def test_sweep_sends_no_warning_without_warn_days(
    rule: _Rule,
    session: AsyncSession,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository, warn_days=0)
    soon = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_031, days_ago=6
    )

    await rule.sweep.system()

    assert await _events(session, soon.id, "SubscriptionExpiryDisableWarningEvent") == 0


def _renewal(
    target: SubscriptionDto, plan: PlanDto, *, refuse_disabled_target: bool = True
) -> PurchaseSubscriptionDto:
    return PurchaseSubscriptionDto(
        user_id=target.user_id,
        plan_snapshot=snapshot_from_plan(plan, price_paid=Decimal("299.00"), duration_days=30),
        duration_days=30,
        price_paid=Decimal("299.00"),
        currency=Currency.RUB,
        purchase_type=PurchaseType.RENEW,
        target_subscription_id=target.id,
        idempotency_key=uuid4().hex,
        refuse_disabled_target=refuse_disabled_target,
    )


async def test_renewal_turns_an_expiry_switch_off_back_on(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    plan_repository: PlanRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository)
    plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_041, days_ago=8, plan=plan
    )
    await rule.sweep.system()
    switched_off = await subscription_repository.get_by_id(target.id)
    buyer = await user_repository.find_by_id(target.user_id)
    assert buyer is not None

    renewed = await rule.purchase(buyer, _renewal(switched_off, plan))

    assert renewed.status is SubscriptionStatus.ACTIVE
    assert renewed.expiry_disabled_at is None
    assert renewed.expire_at > datetime_now()
    assert remnawave_store[96_041]["status"] == "ACTIVE"


async def test_plan_change_turns_an_expiry_switch_off_back_on(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    plan_repository: PlanRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository)
    plan = await _plan(plan_repository)
    new_plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_045, days_ago=8, plan=plan
    )
    await rule.sweep.system()
    buyer = await user_repository.find_by_id(target.user_id)
    assert buyer is not None

    changed = await rule.purchase(
        buyer,
        PurchaseSubscriptionDto(
            user_id=target.user_id,
            plan_snapshot=snapshot_from_plan(
                new_plan, price_paid=Decimal("299.00"), duration_days=30
            ),
            duration_days=30,
            price_paid=Decimal("299.00"),
            currency=Currency.RUB,
            purchase_type=PurchaseType.CHANGE,
            target_subscription_id=target.id,
            idempotency_key=uuid4().hex,
        ),
    )

    assert changed.status is SubscriptionStatus.ACTIVE
    assert changed.expiry_disabled_at is None
    assert remnawave_store[96_045]["status"] == "ACTIVE"


async def test_renewal_still_refuses_a_subscription_an_admin_switched_off(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    plan_repository: PlanRepository,
    remnawave_store: FakeUserStore,
) -> None:
    plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_051, days_ago=1, plan=plan
    )
    disabled = await rule.set_enabled(
        OWNER, SetSubscriptionEnabledDto(subscription_id=target.id, enabled=False)
    )
    buyer = await user_repository.find_by_id(target.user_id)
    assert buyer is not None

    with pytest.raises(ValidationError) as error:
        await rule.purchase(buyer, _renewal(disabled, plan))

    assert error.value.code is ErrorCode.SUBSCRIPTION_DISABLED


async def test_an_admins_switch_clears_the_expiry_mark(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    plan_repository: PlanRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository)
    plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_061, days_ago=8, plan=plan
    )
    await rule.sweep.system()

    # an admin's switch-off on top: a renewal must not undo it
    await rule.set_enabled(
        OWNER, SetSubscriptionEnabledDto(subscription_id=target.id, enabled=False)
    )

    kept = await subscription_repository.get_by_id(target.id)
    assert kept.status is SubscriptionStatus.DISABLED
    assert not kept.disabled_by_expiry


async def test_switched_off_subscription_is_not_listed_as_active(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_071, days_ago=8
    )
    await rule.sweep.system()

    assert await subscription_repository.get_active_by_user(target.user_id) == []


async def test_a_renewal_during_the_switch_off_turns_the_panel_back_on(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    uow: UnitOfWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_081, days_ago=8
    )
    disable_user = remnawave_sdk.users.disable_user

    async def renewed_meanwhile(user_id: int) -> Any:
        response = await disable_user(user_id)
        async with uow:
            await rule.lifecycle.renew(
                target.id,
                datetime_now() + timedelta(days=30),
                paid=Decimal("0"),
                currency=Currency.RUB,
                previous_expire_at=target.expire_at,
                starts_at=datetime_now(),
                payment_key=None,
            )
        return response

    monkeypatch.setattr(remnawave_sdk.users, "disable_user", renewed_meanwhile)

    await rule.disable.system(target.id)

    current = await subscription_repository.get_by_id(target.id)
    assert current.status is SubscriptionStatus.ACTIVE
    assert current.expiry_disabled_at is None
    # the fake panel enables against its own past expiry
    assert remnawave_store[96_081]["status"] != "DISABLED"


async def test_disable_skips_a_panel_user_that_is_gone(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_store: FakeUserStore,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_091, days_ago=8
    )
    del remnawave_store[96_091]

    await rule.disable.system(target.id)

    kept = await subscription_repository.get_by_id(target.id)
    assert kept.status is SubscriptionStatus.EXPIRED
    # done with this expiry: it no longer holds a place in every run's batch
    assert handled(kept, datetime_now() + CLAIM_STALE_AFTER)
    assert kept.expiry_disabled_at is None
    assert (
        await subscription_repository.list_expiry_disable_due(
            datetime_now(), datetime_now() + CLAIM_STALE_AFTER, 100
        )
        == []
    )


async def test_a_failed_panel_call_leaves_the_subscription_for_the_next_run(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_101, days_ago=8
    )

    async def unreachable(user_id: int) -> Any:
        raise httpx.ConnectError("panel down")

    monkeypatch.setattr(remnawave_sdk.users, "disable_user", unreachable)

    with pytest.raises(httpx.ConnectError):
        await rule.disable.system(target.id)

    # the claim stays: no other run takes it until it goes stale, then it's tried again
    claimed = await subscription_repository.get_by_id(target.id)
    assert claimed.expiry_disable_handled_at is not None
    assert not disable_due(claimed, _SETTINGS, datetime_now())
    assert disable_due(claimed, _SETTINGS, datetime_now() + CLAIM_STALE_AFTER)
    assert (
        await subscription_repository.list_expiry_disable_due(
            datetime_now(), datetime_now() - CLAIM_STALE_AFTER, 100
        )
        == []
    )
    due = await subscription_repository.list_expiry_disable_due(
        datetime_now(), datetime_now() + CLAIM_STALE_AFTER, 100
    )
    assert [s.id for s in due] == [target.id]


async def test_the_panels_echo_landing_first_still_marks_the_switch_off_as_the_rules(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    uow: UnitOfWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_111, days_ago=8
    )
    disable_user = remnawave_sdk.users.disable_user

    async def echoed(user_id: int) -> Any:
        response = await disable_user(user_id)
        # the webhook worker syncs the panel's user.disabled before the sweep's own commit
        async with uow:
            await rule.lifecycle.sync_status(target.id, SubscriptionStatus.DISABLED)
        return response

    monkeypatch.setattr(remnawave_sdk.users, "disable_user", echoed)

    await rule.disable.system(target.id)

    assert (await subscription_repository.get_by_id(target.id)).disabled_by_expiry


async def test_the_panel_reporting_it_live_clears_the_mark(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_store: FakeUserStore,
    uow: UnitOfWork,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_121, days_ago=8
    )
    await rule.sweep.system()

    # an admin turned it on and extended it in the panel, then switched it off there
    async with uow:
        await rule.lifecycle.sync_status(target.id, SubscriptionStatus.ACTIVE)
        await rule.lifecycle.sync_status(target.id, SubscriptionStatus.DISABLED)

    assert not (await subscription_repository.get_by_id(target.id)).disabled_by_expiry


async def test_the_rule_leaves_alone_what_an_admin_turned_back_on(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_store: FakeUserStore,
    uow: UnitOfWork,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_131, days_ago=8
    )
    await rule.sweep.system()

    await rule.set_enabled(
        OWNER, SetSubscriptionEnabledDto(subscription_id=target.id, enabled=True)
    )
    # the panel turns it on as ACTIVE, and its own cron expires it again later
    assert (await subscription_repository.get_by_id(target.id)).status is SubscriptionStatus.ACTIVE
    remnawave_store[96_131]["status"] = "EXPIRED"
    async with uow:
        await rule.lifecycle.sync_status(target.id, SubscriptionStatus.EXPIRED)
    await rule.sweep.system()

    assert (await subscription_repository.get_by_id(target.id)).status is SubscriptionStatus.EXPIRED
    assert remnawave_store[96_131]["status"] == "EXPIRED"

    # then switched off in the panel by an admin: theirs, not the rule's, so no renewal undoes it
    async with uow:
        await rule.lifecycle.sync_status(target.id, SubscriptionStatus.DISABLED)
    assert not (await subscription_repository.get_by_id(target.id)).disabled_by_expiry


async def test_a_change_paid_as_the_rule_switches_off_still_comes_out_on(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    plan_repository: PlanRepository,
    remnawave_store: FakeUserStore,
) -> None:
    plan = await _plan(plan_repository)
    new_plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_141, days_ago=8, plan=plan
    )
    # the sweep's panel call landed; its row update hasn't yet
    remnawave_store[96_141]["status"] = "DISABLED"
    buyer = await user_repository.find_by_id(target.user_id)
    assert buyer is not None

    changed = await rule.purchase(
        buyer,
        PurchaseSubscriptionDto(
            user_id=target.user_id,
            plan_snapshot=snapshot_from_plan(
                new_plan, price_paid=Decimal("299.00"), duration_days=30
            ),
            duration_days=30,
            price_paid=Decimal("299.00"),
            currency=Currency.RUB,
            purchase_type=PurchaseType.CHANGE,
            target_subscription_id=target.id,
            idempotency_key=uuid4().hex,
        ),
    )

    assert changed.status is SubscriptionStatus.ACTIVE
    assert remnawave_store[96_141]["status"] == "ACTIVE"


async def test_a_renewal_that_fails_on_the_panel_switches_it_back_off(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    plan_repository: PlanRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_151, days_ago=8, plan=plan
    )
    await rule.sweep.system()
    switched_off = await subscription_repository.get_by_id(target.id)
    buyer = await user_repository.find_by_id(target.user_id)
    assert buyer is not None

    async def refused(request: Any) -> Any:
        raise RuntimeError("panel refused the expiry")

    monkeypatch.setattr(remnawave_sdk.users, "update_user", refused)

    with pytest.raises(RuntimeError):
        await rule.purchase(buyer, _renewal(switched_off, plan))

    assert remnawave_store[96_151]["status"] == "DISABLED"
    assert (await subscription_repository.get_by_id(target.id)).disabled_by_expiry


async def test_a_change_paid_as_the_rule_switches_it_off_mid_way_comes_out_on(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    plan_repository: PlanRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    plan = await _plan(plan_repository)
    new_plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_161, days_ago=8, plan=plan
    )
    update_user = remnawave_sdk.users.update_user
    swept = False

    async def swept_after_the_push(request: Any) -> Any:
        nonlocal swept
        response = await update_user(request)
        if not swept:
            swept = True
            await rule.disable.system(target.id)
        return response

    monkeypatch.setattr(remnawave_sdk.users, "update_user", swept_after_the_push)
    buyer = await user_repository.find_by_id(target.user_id)
    assert buyer is not None

    changed = await rule.purchase(
        buyer,
        PurchaseSubscriptionDto(
            user_id=target.user_id,
            plan_snapshot=snapshot_from_plan(
                new_plan, price_paid=Decimal("299.00"), duration_days=30
            ),
            duration_days=30,
            price_paid=Decimal("299.00"),
            currency=Currency.RUB,
            purchase_type=PurchaseType.CHANGE,
            target_subscription_id=target.id,
            idempotency_key=uuid4().hex,
        ),
    )

    assert swept
    assert changed.status is SubscriptionStatus.ACTIVE
    assert remnawave_store[96_161]["status"] == "ACTIVE"


async def test_a_refunded_renewal_leaves_it_switched_off_and_still_the_rules(
    rule: _Rule,
    session: AsyncSession,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    uow: UnitOfWork,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_171, days_ago=8
    )
    await rule.sweep.system()
    switched_off = await subscription_repository.get_by_id(target.id)
    # turned on for the payment, and the panel's echo already synced
    await remnawave_sdk.users.enable_user(96_171)
    async with uow:
        await rule.lifecycle.sync_status(target.id, SubscriptionStatus.ACTIVE)

    await restore_expiry_switch_off(
        remnawave_sdk, subscription_repository, rule.lifecycle, uow, switched_off
    )

    assert remnawave_store[96_171]["status"] == "DISABLED"
    assert (await subscription_repository.get_by_id(target.id)).disabled_by_expiry


async def test_a_run_dying_after_the_panel_call_still_leaves_it_the_rules(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    uow: UnitOfWork,
    remnawave_store: FakeUserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_181, days_ago=8
    )

    async def dies(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("worker killed")

    monkeypatch.setattr(rule.lifecycle, "sync_status", dies)
    with pytest.raises(RuntimeError):
        await rule.disable.system(target.id)
    monkeypatch.undo()

    # the panel's echo of the switch-off syncs the row afterwards
    async with uow:
        await rule.lifecycle.sync_status(target.id, SubscriptionStatus.DISABLED)

    assert remnawave_store[96_181]["status"] == "DISABLED"
    assert (await subscription_repository.get_by_id(target.id)).disabled_by_expiry


async def test_an_admins_switch_off_during_the_run_stays_the_admins(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_191, days_ago=8
    )
    disable_user = remnawave_sdk.users.disable_user
    calls = 0

    async def admin_meanwhile(user_id: int) -> Any:
        nonlocal calls
        calls += 1
        response = await disable_user(user_id)
        if calls == 1:
            remnawave_store[96_191]["status"] = "EXPIRED"
            await rule.set_enabled(
                OWNER, SetSubscriptionEnabledDto(subscription_id=target.id, enabled=False)
            )
        return response

    monkeypatch.setattr(remnawave_sdk.users, "disable_user", admin_meanwhile)

    await rule.disable.system(target.id)

    kept = await subscription_repository.get_by_id(target.id)
    assert kept.status is SubscriptionStatus.DISABLED
    assert not kept.disabled_by_expiry


async def test_a_renewal_whose_turning_on_fails_still_lands_and_the_cron_turns_it_on(
    rule: _Rule,
    subscription_repository: SubscriptionRepository,
    user_repository: UserRepository,
    settings_repository: SettingsRepository,
    plan_repository: PlanRepository,
    remnawave_sdk: RemnawaveSDK,
    remnawave_store: FakeUserStore,
    uow: UnitOfWork,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _switch_on(settings_repository)
    plan = await _plan(plan_repository)
    target = await _expired(
        subscription_repository, user_repository, remnawave_store, 96_201, days_ago=8, plan=plan
    )
    await rule.sweep.system()
    switched_off = await subscription_repository.get_by_id(target.id)
    buyer = await user_repository.find_by_id(target.user_id)
    assert buyer is not None
    update_user = remnawave_sdk.users.update_user

    async def refuses_turning_on(request: Any) -> Any:
        if request.status is not None:
            raise RuntimeError("panel timed out")
        return await update_user(request)

    monkeypatch.setattr(remnawave_sdk.users, "update_user", refuses_turning_on)

    renewed = await rule.purchase(buyer, _renewal(switched_off, plan))

    assert renewed.status is SubscriptionStatus.ACTIVE
    assert remnawave_store[96_201]["status"] == "DISABLED"
    assert (await subscription_repository.get_by_id(target.id)).panel_restore_due_at is not None
    monkeypatch.undo()

    await RestoreDuePanelConfigsUseCase(
        subscription_repository, settings_repository, remnawave_sdk, uow
    ).system()

    assert remnawave_store[96_201]["status"] == "ACTIVE"
