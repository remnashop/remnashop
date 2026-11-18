from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.db.models import EventOutboxEntry
from app.core.db.uow import UnitOfWork
from app.core.enums import Currency, Locale
from app.core.event_bus import EventBus
from app.core.events import EventCategory
from app.core.outbox_event_publisher import OutboxEventPublisher
from app.modules.customer_notifications.render_args import customer_render_args
from app.modules.customer_notifications.routing import CustomerChannel, channels_for
from app.modules.customer_notifications.subscribers import register_subscribers
from app.modules.notifications.render import NotificationRenderer
from app.modules.recurring_payments.events import (
    RecurringPaymentExhaustedEvent,
    RecurringPaymentFailedEvent,
    RecurringPaymentPausedEvent,
    RecurringPaymentUpcomingEvent,
)
from tests.fakes.dispatch import RecordingDispatch
from tests.fakes.events import stored_event
from tests.seeded_translations import seeded_fluent_source

_EVENTS = [
    RecurringPaymentUpcomingEvent(
        user_id=5,
        subscription_id=7,
        amount="500",
        currency=Currency.RUB,
        scheduled_at="2026-11-15T12:00:00+00:00",
    ),
    RecurringPaymentFailedEvent(
        user_id=5,
        subscription_id=7,
        order_id=8,
        amount="500",
        currency=Currency.RUB,
        reason="insufficient_funds",
        next_attempt_at="2026-11-15T13:00:00+00:00",
        attempt=1,
    ),
    RecurringPaymentPausedEvent(user_id=5, subscription_id=7, reason="merchant_unavailable"),
    RecurringPaymentExhaustedEvent(user_id=5, subscription_id=7, reason="retries_exhausted"),
]


async def test_repository_notice_is_committed_with_its_state_and_rolls_back_together(session, uow):
    with pytest.raises(RuntimeError):
        async with uow:
            await OutboxEventPublisher(UnitOfWork(session), RecordingDispatch()).publish(
                RecurringPaymentPausedEvent(
                    user_id=5, subscription_id=7, reason="provider_unavailable"
                ),
            )
            assert (
                await session.scalar(
                    select(EventOutboxEntry).where(
                        EventOutboxEntry.event_type == "RecurringPaymentPausedEvent"
                    )
                )
                is not None
            )
            raise RuntimeError("rollback")
    assert (
        await session.scalar(
            select(EventOutboxEntry).where(
                EventOutboxEntry.event_type == "RecurringPaymentPausedEvent"
            )
        )
        is None
    )


@pytest.mark.parametrize("event", _EVENTS)
@pytest.mark.parametrize("locale", [Locale.RU, Locale.EN])
async def test_recurring_events_reach_customer_channels_and_have_complete_templates(event, locale):
    bus = EventBus()
    register_subscribers(bus)
    with patch(
        "app.modules.customer_notifications.tasks.notify_customer_task.kiq", new_callable=AsyncMock
    ) as dispatched:
        await bus.dispatch_stored(stored_event(event))
    dispatched.assert_awaited_once()
    fields = dispatched.await_args.kwargs
    assert fields["user_id"] == 5 and fields["subscription_id"] == 7
    assert channels_for(event.event_type, telegram_id=1, email="customer@example.com") == [
        CustomerChannel.TELEGRAM,
        CustomerChannel.EMAIL,
    ]
    renderer = NotificationRenderer({locale: seeded_fluent_source(locale)}, default_locale=locale)
    title, body = renderer.render(
        locale, "Customer" + event.event_type, customer_render_args(fields["args"], locale)
    )
    assert title and body and "{" not in body
    assert event.category is EventCategory.PAYMENT
    if isinstance(event, RecurringPaymentUpcomingEvent):
        assert "15.11.2026 12:00 UTC" in body
    if isinstance(event, RecurringPaymentFailedEvent):
        assert "15.11.2026 13:00 UTC" in body
