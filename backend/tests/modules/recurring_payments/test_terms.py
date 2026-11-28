from decimal import Decimal
from typing import Union

from app.core.enums import Currency, Locale, PurchaseType
from app.modules.recurring_payments.dto import RecurringTermsTextDto
from app.modules.recurring_payments.policy import RecurringPolicy, recurring_policy
from app.modules.recurring_payments.terms import build_recurring_terms


class _EchoTexts:
    def __init__(self) -> None:
        self.calls: list[tuple[Locale, dict[str, Union[str, int]]]] = []

    async def render(
        self, locale: Locale, args: dict[str, Union[str, int]]
    ) -> RecurringTermsTextDto:
        self.calls.append((locale, args))
        return RecurringTermsTextDto(summary=f"summary:{args['amount']}", text=f"text:{args}")


async def _terms(texts: _EchoTexts, policy: RecurringPolicy):  # type: ignore[no-untyped-def]
    return await build_recurring_terms(
        texts=texts,
        policy=policy,
        user_id=3,
        plan_id=1,
        target_subscription_id=None,
        purchase_type=PurchaseType.NEW,
        initial_amount=Decimal("90"),
        amount_limit=Decimal("100"),
        currency=Currency.RUB,
        duration_days=30,
        locale=Locale.RU,
    )


async def test_terms_text_comes_from_translation_keys() -> None:
    texts = _EchoTexts()
    terms = await _terms(texts, recurring_policy({}))
    assert terms.summary == "summary:100"
    assert terms.text.startswith("text:")
    locale, args = texts.calls[0]
    assert locale is Locale.RU
    assert args["retention_days"] == 30 and args["lead_minutes"] == 1440


async def test_terms_snapshot_the_policy_they_were_shown_with() -> None:
    texts = _EchoTexts()
    policy = recurring_policy(
        {"recurring_retry_minutes": "15", "recurring_max_overdue_hours": "48"}
    )
    terms = await _terms(texts, policy)
    assert terms.retry_minutes == 15 and terms.max_overdue_hours == 48
    assert texts.calls[0][1]["retry_minutes"] == 15


async def test_terms_id_changes_with_the_text() -> None:
    first = await _terms(_EchoTexts(), recurring_policy({}))

    class _Edited(_EchoTexts):
        async def render(self, locale, args):  # type: ignore[no-untyped-def]
            return RecurringTermsTextDto(summary="edited", text="edited")

    second = await _terms(_Edited(), recurring_policy({}))
    assert first.terms_id != second.terms_id


def test_policy_reads_gateway_settings_and_falls_back_to_defaults() -> None:
    assert recurring_policy({"recurring_lead_minutes": "60"}).lead_minutes == 60
    defaults = recurring_policy({"recurring_lead_minutes": ""})
    assert defaults.lead_minutes == 1440 and defaults.retry_minutes == 5
    assert defaults.max_overdue_hours == 96 and defaults.notice_lead_minutes == 2880


def test_policy_clamps_a_stored_value_outside_its_bounds() -> None:
    assert recurring_policy({"recurring_lead_minutes": "5000"}).lead_minutes == 1440
