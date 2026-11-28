from typing import Protocol, Union

from app.core.enums import Locale
from app.modules.recurring_payments.dto import RecurringTermsTextDto


class RecurringTermsTexts(Protocol):
    async def render(
        self, locale: Locale, args: dict[str, Union[str, int]]
    ) -> RecurringTermsTextDto: ...
