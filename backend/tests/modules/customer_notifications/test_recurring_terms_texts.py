from unittest.mock import AsyncMock, MagicMock

from app.core.config import AppConfig
from app.core.enums import Locale
from app.modules.customer_notifications.recurring_terms_texts import RecurringTermsTextRenderer
from app.modules.notifications import NotificationRenderer

_ARGS = {
    "initial": "90",
    "amount": "100",
    "currency": "RUB",
    "currency_symbol": "₽",
    "days": 30,
    "lead_minutes": 1440,
    "retry_hours": "1, 3",
    "retry_minutes": 5,
    "overdue_hours": 96,
    "retention_days": 30,
}


def _factory(fluent: dict[Locale, str]) -> MagicMock:
    renderer = NotificationRenderer(fluent, default_locale=Locale.EN)
    return MagicMock(build=AsyncMock(return_value=renderer))


async def test_terms_use_the_shops_edited_translation() -> None:
    edited = "recurring-terms-summary = short { $amount }\nrecurring-terms-text = full { $days }\n"
    texts = RecurringTermsTextRenderer(_factory({Locale.RU: edited}), AppConfig.get())
    rendered = await texts.render(Locale.RU, _ARGS)
    assert rendered.summary == "short 100" and rendered.text == "full 30"


async def test_terms_never_come_out_empty_when_the_keys_are_missing() -> None:
    texts = RecurringTermsTextRenderer(_factory({Locale.RU: "other = x\n"}), AppConfig.get())
    rendered = await texts.render(Locale.RU, _ARGS)
    assert "100 ₽" in rendered.summary
    assert "Условия автоматического продления" in rendered.text
