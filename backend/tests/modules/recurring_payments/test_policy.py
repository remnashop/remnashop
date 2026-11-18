from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.utils.time import datetime_now
from app.modules.recurring_payments.policy import (
    RecurringReason,
    RecurringState,
    classify,
    provider_cancellation_reason,
    stored_reason,
)


@pytest.mark.parametrize("reason", list(RecurringReason))
def test_every_reason_has_an_explicit_notification_policy_and_both_translations(reason):
    assets = Path(__file__).parents[3] / "assets" / "translations"
    for locale in ("ru", "en"):
        assert f"[{reason.value}]" in (assets / locale / "notifications.ftl").read_text()
    assert isinstance(reason.policy.customer_notice, bool)


@pytest.mark.parametrize(
    ("enabled", "customer_disabled", "pending", "failed", "reason", "expected"),
    [
        (True, False, None, None, None, RecurringState.ENABLED),
        (True, False, 1, None, None, RecurringState.PENDING),
        (True, False, None, datetime_now(), "insufficient_funds", RecurringState.RETRYING),
        (False, False, None, None, "payment_status_unknown", RecurringState.ATTENTION),
        (True, False, 1, None, "pending_timeout", RecurringState.ATTENTION),
        (False, True, 1, None, "customer_disabled", RecurringState.DISABLED),
    ],
)
def test_mandate_state_follows_one_ordered_policy(
    enabled, customer_disabled, pending, failed, reason, expected
):
    mandate = SimpleNamespace(
        enabled=enabled,
        customer_disabled=customer_disabled,
        pending_transaction_id=pending,
        first_failure_at=failed,
        last_error=stored_reason(reason),
        submitted_at=None,
    )
    assert classify(mandate) is expected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("insufficient_funds", RecurringReason.INSUFFICIENT_FUNDS),
        ("permission_revoked", RecurringReason.PERMISSION_REVOKED),
        ("general_decline", RecurringReason.BANK_DECLINED),
        # our own stop reasons never come from a webhook
        ("admin_closed", RecurringReason.BANK_DECLINED),
        ("retries_exhausted", RecurringReason.BANK_DECLINED),
        (None, RecurringReason.BANK_DECLINED),
    ],
)
def test_a_provider_code_maps_only_to_bank_and_card_reasons(provider, expected):
    assert provider_cancellation_reason(provider) is expected


def test_an_unknown_stored_reason_stops_debits_and_reaches_an_admin():
    reason = stored_reason("renamed_in_a_later_version")
    assert reason is RecurringReason.PROVIDER_CONFIGURATION_ERROR
    assert not reason.policy.allows_debit and reason.policy.admin_notice
