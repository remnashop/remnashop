from typing import Union

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.db.uow import UnitOfWork
from app.core.enums import Locale
from app.core.outbox_event_publisher import OutboxEventPublisher
from app.modules.notifications import NotificationRenderer
from app.modules.recurring_payments.checkout import RecurringCheckoutConsent
from app.modules.recurring_payments.dto import RecurringTermsTextDto
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.transactions.repository import TransactionRepository
from tests.fakes.dispatch import RecordingDispatch


def make_recurring_lifecycle(session: AsyncSession) -> RecurringLifecycle:
    return RecurringLifecycle(
        RecurringPaymentRepository(session),
        TransactionRepository(session),
        OutboxEventPublisher(UnitOfWork(session), RecordingDispatch()),
    )


async def fulfil(session: AsyncSession, order_id: int, subscription_id: int) -> None:
    """mark_fulfilled plus the mandate update its usecases run after it"""
    marked = await TransactionRepository(session).mark_fulfilled(order_id, subscription_id)
    if marked is not None:
        await make_recurring_lifecycle(session).on_fulfilled(marked, subscription_id)


class ShippedRecurringTermsTexts:
    """RecurringTermsTexts over the shipped notifications.ftl files."""

    async def render(
        self, locale: Locale, args: dict[str, Union[str, int]]
    ) -> RecurringTermsTextDto:
        renderer = NotificationRenderer(
            {
                shipped: (
                    AppConfig.get().translations_dir / shipped.value / "notifications.ftl"
                ).read_text(encoding="utf-8")
                for shipped in (Locale.RU, Locale.EN)
            },
            default_locale=Locale.EN,
        )
        return RecurringTermsTextDto(
            summary=renderer.render_message(locale, "recurring-terms-summary", args).strip(),
            text=renderer.render_message(locale, "recurring-terms-text", args).strip(),
        )


def make_recurring_checkout(session: AsyncSession) -> RecurringCheckoutConsent:
    return RecurringCheckoutConsent(
        RecurringPaymentRepository(session),
        make_recurring_lifecycle(session),
        ShippedRecurringTermsTexts(),
    )
