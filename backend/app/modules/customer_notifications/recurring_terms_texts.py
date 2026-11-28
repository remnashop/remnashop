from typing import Final, Union

from app.core.config import AppConfig
from app.core.enums import Locale
from app.modules.notifications import NotificationRenderer, NotificationRendererFactory
from app.modules.recurring_payments import (
    RecurringTermsTextDto,
)

_SUMMARY_KEY: Final[str] = "recurring-terms-summary"
_TEXT_KEY: Final[str] = "recurring-terms-text"
_SHIPPED_LOCALES: Final[tuple[Locale, ...]] = (Locale.RU, Locale.EN)

_SHIPPED: Final[dict[str, NotificationRenderer]] = {}


class RecurringTermsTextRenderer:
    def __init__(self, renderer_factory: NotificationRendererFactory, config: AppConfig) -> None:
        self._renderer_factory = renderer_factory
        self._config = config

    async def render(
        self, locale: Locale, args: dict[str, Union[str, int]]
    ) -> RecurringTermsTextDto:
        renderer = await self._renderer_factory.build()
        rendered = self._render(renderer, locale, args)
        if rendered.summary and rendered.text:
            return rendered
        # a customer never consents to an empty text, even with the keys deleted
        return self._render(self._shipped(), locale, args)

    @staticmethod
    def _render(
        renderer: NotificationRenderer, locale: Locale, args: dict[str, Union[str, int]]
    ) -> RecurringTermsTextDto:
        return RecurringTermsTextDto(
            summary=renderer.render_message(locale, _SUMMARY_KEY, args).strip(),
            text=renderer.render_message(locale, _TEXT_KEY, args).strip(),
        )

    def _shipped(self) -> NotificationRenderer:
        if "all" not in _SHIPPED:
            texts = {
                locale: (
                    self._config.translations_dir / locale.value / "notifications.ftl"
                ).read_text(encoding="utf-8")
                for locale in _SHIPPED_LOCALES
            }
            _SHIPPED["all"] = NotificationRenderer(texts, default_locale=Locale.EN)
        return _SHIPPED["all"]
