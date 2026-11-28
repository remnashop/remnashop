import html
import math
from contextvars import ContextVar
from datetime import datetime, tzinfo
from decimal import Decimal
from typing import Final, Optional

from fluent_compiler.bundle import FluentBundle
from fluentogram import FluentTranslator, TranslatorHub, TranslatorRunner

from app.core.config import AppConfig
from app.core.constants import DATE_FORMAT, DATETIME_FORMAT, TIMEZONE
from app.core.db.standalone import standalone_session
from app.core.enums import Locale
from app.core.utils.time import datetime_now, period_parts
from app.modules.subscriptions import is_unlimited_expiry
from app.modules.translations import TranslationRepository
from app.modules.users import UserDto
from app.telegram.dialogs.rendering import TrustedHtml

# Bot API date_time entity: d = short date, t = short time
_TG_DATETIME_FORMAT: Final[str] = "dt"
_TG_DATE_FORMAT: Final[str] = "d"
# set per update by ShopZoneMiddleware
_shop_zone: Final[ContextVar[tzinfo]] = ContextVar("shop_zone", default=TIMEZONE)


def build_translator_hub(
    active_locales: list[Locale], translations_by_locale: dict[Locale, str], default_locale: Locale
) -> TranslatorHub:
    translators = [
        FluentTranslator(
            locale=locale.value,
            # bidi marks around a placeable on its own line show up in Telegram
            # as an empty line, e.g. before a select's <blockquote>
            translator=FluentBundle.from_string(  # type: ignore[no-untyped-call]
                locale.value, text=translations_by_locale[locale], use_isolating=False
            ),
        )
        for locale in active_locales
    ]
    return TranslatorHub(
        locales_map={locale.value: locale.value for locale in active_locales},
        translators=translators,
        root_locale=default_locale.value,
    )


async def read_translator_hub(config: AppConfig) -> TranslatorHub:
    # runs before the dishka container exists
    async with standalone_session(config) as session:
        translation_repository = TranslationRepository(session)
        active_locales = await translation_repository.list_active_locales()
        translations_by_locale = await translation_repository.get_fluent_text_by_locale(
            active_locales
        )
        default_locale = await translation_repository.get_default_locale()
        return build_translator_hub(active_locales, translations_by_locale, default_locale)


def telegram_locale(hub: TranslatorHub, language_code: Optional[str]) -> Optional[Locale]:
    # "pt-br" -> "pt"; only a locale the bot actually serves counts
    code = (language_code or "").split("-")[0].lower()
    return Locale(code) if code in hub.translators_map else None


def get_translator(hub: TranslatorHub, user: UserDto) -> TranslatorRunner:
    return hub.get_translator_by_locale(user.language.value)


def use_shop_zone(zone: tzinfo) -> None:
    _shop_zone.set(zone)


# every date the bot shows a customer goes through these two, written as the shop's
def format_datetime(value: Optional[datetime]) -> str:
    return value.astimezone(_shop_zone.get()).strftime(DATETIME_FORMAT) if value else "—"


def format_date(value: Optional[datetime]) -> str:
    return value.astimezone(_shop_zone.get()).strftime(DATE_FORMAT) if value else "—"


def format_price(price: Decimal) -> str:
    return f"{price:.2f}".removesuffix(".00")


def format_expiry(runner: TranslatorRunner, value: datetime, *, with_time: bool = False) -> str:
    """A subscription's expiry; an unlimited one has none to show."""
    if is_unlimited_expiry(value):
        return runner.get("time-unit.no-expiry")
    return format_datetime(value) if with_time else format_date(value)


def unix_time(value: datetime) -> str:
    # a string, so Fluent doesn't group the digits
    return str(int(value.timestamp()))


def expiry_unix_time(value: datetime) -> str:
    """Empty for an unlimited subscription: it has no date to show."""
    return "" if is_unlimited_expiry(value) else unix_time(value)


def format_date_tag(value: datetime, *, with_time: bool = False) -> TrustedHtml:
    """The date as <tg-time>, shown in the reader's own time zone; the inner
    text is for clients that don't know the tag."""
    text = format_datetime(value) if with_time else format_date(value)
    tg_format = _TG_DATETIME_FORMAT if with_time else _TG_DATE_FORMAT
    return TrustedHtml(f'<tg-time unix="{unix_time(value)}" format="{tg_format}">{text}</tg-time>')


def format_expiry_tag(
    runner: TranslatorRunner, value: datetime, *, with_time: bool = False
) -> TrustedHtml:
    if is_unlimited_expiry(value):
        return TrustedHtml(html.escape(runner.get("time-unit.no-expiry")))
    return format_date_tag(value, with_time=with_time)


def format_period(runner: TranslatorRunner, days: int) -> str:
    unit, value = period_parts(days)
    if unit == "unlimited":
        return runner.get("time-unit.unlimited")
    return runner.get(f"time-unit.{unit}", value=value)


def format_wait(runner: TranslatorRunner, until: datetime) -> str:
    """How long until `until`: days and hours, or hours and minutes under a day."""
    minutes = max(1, math.ceil((until - datetime_now()).total_seconds() / 60))
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = (("day", days), ("hour", hours)) if days else (("hour", hours), ("minute", minutes))
    return " ".join(runner.get(f"time-unit.{unit}", value=value) for unit, value in parts if value)
