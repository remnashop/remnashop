from datetime import datetime, tzinfo
from typing import Final, Optional, Union

from app.core.constants import DATE_FORMAT, DATETIME_FORMAT, GB_TO_BYTES, MB_TO_BYTES
from app.core.enums import Locale
from app.core.utils.money import format_money
from app.modules.subscriptions import (
    SubscriptionChangedEvent,
    SubscriptionGraceStartedEvent,
    SubscriptionGrantedEvent,
    SubscriptionTrafficThresholdEvent,
)

_MB_PER_GB: Final[int] = GB_TO_BYTES // MB_TO_BYTES
# the text names the plan the subscription now has
NAMES_PLAN: Final[frozenset[str]] = frozenset(
    {SubscriptionGrantedEvent.__name__, SubscriptionChangedEvent.__name__}
)


# args that arrive as ISO moments and are shown as the shop's date, or date and time
_DATE_ARGS: Final[dict[str, str]] = {
    "grace_until": DATE_FORMAT,
    "disable_date": DATE_FORMAT,
    "reset_date": DATE_FORMAT,
    "scheduled_at": DATETIME_FORMAT,
    "next_attempt_at": DATETIME_FORMAT,
}


def shop_dates(args: dict[str, Union[str, int]], zone: tzinfo) -> dict[str, Union[str, int]]:
    """Date args as the shop's day; a value already written as a date (a task queued
    before this was) or "none" stays as it is."""
    dated = dict(args)
    for name, date_format in _DATE_ARGS.items():
        value = args.get(name)
        if not isinstance(value, str):
            continue
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            continue
        dated[name] = moment.astimezone(zone).strftime(date_format)
    return dated


def customer_render_args(
    args: dict[str, Union[str, int]], locale: Locale, event_type: Optional[str] = None
) -> dict[str, Union[str, int]]:
    """What the templates print but the feed does not store: it is rendered per reader."""
    rendered = dict(args)
    hours = args.get("hours")
    if isinstance(hours, int):
        # a plain number, so the plural selectors still match
        rendered["span_unit"], rendered["span"] = (
            ("day", hours // 24) if hours >= 24 else ("hour", hours)
        )
    minutes = args.get("minutes")
    if isinstance(minutes, int):
        rendered["span_unit"], rendered["span"] = "minute", minutes
    if event_type in NAMES_PLAN:
        # a feed row stored before the plan name was has none
        rendered["has_plan_name"] = "yes" if args.get("plan_name") else "no"
    if event_type == SubscriptionTrafficThresholdEvent.__name__:
        # a feed row stored before these were has none: no percent or date, still offers renewing
        rendered.setdefault("percent", 0)
        rendered.setdefault("reset_date", "none")
        rendered.setdefault("can_renew", "yes")
    if event_type == SubscriptionGraceStartedEvent.__name__:
        mb = args.get("traffic_limit_mb")
        if not isinstance(mb, int) or mb <= 0:
            rendered["traffic_unit"] = "none"
        # strings, so Fluent does not group the digits
        elif mb % _MB_PER_GB == 0:
            rendered["traffic_unit"], rendered["traffic_value"] = "gb", str(mb // _MB_PER_GB)
        else:
            rendered["traffic_unit"], rendered["traffic_value"] = "mb", str(mb)
    if "amount" in args and "currency" in args:
        rendered["money"] = format_money(str(args["amount"]), str(args["currency"]), locale)
    return rendered
