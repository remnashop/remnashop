from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import delete, update

from app.core.db.models import RecurringConsent, RecurringPayment, User
from app.core.enums import (
    PurchaseChannel,
)
from app.core.exceptions import ValidationError
from app.core.utils.time import datetime_now
from app.modules.account_merge.repository import AccountMergeRepository
from app.modules.recurring_payments.dto import (
    SetRecurringPaymentDto,
)
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.usecases.wipe_stale_payment_methods import (
    WipeStalePaymentMethodsUseCase,
)
from app.modules.users.dto import CreateUserDto
from tests.modules.recurring_payments.harness import (
    manual_renewal,
    set_recurring_timings,
)


async def test_a_mandate_without_explicit_consent_is_not_charged(case, session, uow):
    async with uow:
        await session.execute(
            update(RecurringPayment)
            .where(RecurringPayment.subscription_id == case.subscription.id)
            .values(consent_id=None, enabled=True)
        )
    await case.worker.system()
    state = await case.get_state(case.user, case.subscription.id)
    assert not case.provider.posts
    assert not state.enabled and not state.available
    assert state.last_error == "consent_required"


async def test_reenabling_requires_fresh_confirmation_of_current_terms(case):
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    with pytest.raises(ValidationError):
        await case.set_state(
            case.user,
            SetRecurringPaymentDto(
                subscription_id=case.subscription.id, enabled=True, channel=PurchaseChannel.CABINET
            ),
        )
    assert not (await case.get_state(case.user, case.subscription.id)).enabled


async def test_withdrawal_is_recorded_once_and_reenrollment_has_its_own_record(case, session):
    before = await case.repository.get(case.subscription.id)
    off = SetRecurringPaymentDto(
        subscription_id=case.subscription.id,
        enabled=False,
        channel=PurchaseChannel.BOT,
        event_id="disable-click",
    )
    await case.set_state(case.user, off)
    revoked = await session.get(RecurringConsent, before.consent_id, populate_existing=True)
    assert revoked.revoked_at is not None
    revoked_at = revoked.revoked_at
    assert revoked.revoked_channel == PurchaseChannel.BOT.value
    assert revoked.revoked_event_id == "disable-click"
    await case.set_state(case.user, off)
    await session.refresh(revoked)
    assert revoked.revoked_at == revoked_at
    state = await case.get_state(case.user, case.subscription.id)
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id,
            enabled=True,
            terms_id=state.terms.terms_id,
            channel=PurchaseChannel.BOT,
            event_id="new-consent",
        ),
    )
    after = await case.repository.get(case.subscription.id)
    assert after.enabled and after.consent_id != before.consent_id
    fresh = await session.get(RecurringConsent, after.consent_id)
    assert fresh.event_id == "new-consent" and fresh.revoked_at is None
    assert fresh.terms == state.terms.model_dump(mode="json")


async def test_a_manual_payment_without_consent_does_not_restore_withdrawn_authorization(
    case,
    transaction_repository,
    session,
    uow,
):
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id, enabled=False, channel=PurchaseChannel.CABINET
        ),
    )
    await manual_renewal(case, transaction_repository, session, uow, consent=False)
    state = await case.get_state(case.user, case.subscription.id)
    assert not state.enabled and state.customer_disabled
    assert (await case.repository.get(case.subscription.id)).consent_id is None


async def test_a_new_policy_preserves_existing_consent(case):
    await set_recurring_timings(case, lead_minutes=60)
    await case.worker.system()
    state = await case.get_state(case.user, case.subscription.id)
    assert state.enabled and state.last_error is None
    assert len(case.provider.posts) == 1


async def test_account_merge_preserves_authorized_owner_and_immutable_consent(
    case,
    user_repository,
    session,
    uow,
):
    original = await case.repository.get(case.subscription.id)
    async with uow:
        target = await user_repository.create(CreateUserDto(name="merged customer"))
        await AccountMergeRepository(session).reassign(case.user.id, target.id, {})
    await case.worker.system()
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.enabled and mandate.last_error is None
    assert len(case.provider.posts) == 1
    consent = await session.get(RecurringConsent, original.consent_id, populate_existing=True)
    assert consent.owner_user_id == target.id
    assert consent.user_id == case.user.id
    assert consent.terms["user_id"] == case.user.id


async def test_purging_merged_author_retains_current_owners_recurring_authorization(
    case, session, uow, user_repository, subscription_repository, transaction_repository
) -> None:
    original = await case.repository.get(case.subscription.id)
    consent = await session.get(RecurringConsent, original.consent_id)
    original_terms = deepcopy(consent.terms)
    original_telegram_id = consent.telegram_id
    original_accepted_at = consent.accepted_at

    async with uow:
        target = await user_repository.create(CreateUserDto(name="merged recurring owner"))
        await AccountMergeRepository(session).reassign(case.user.id, target.id, {})
        await session.execute(delete(User).where(User.id == case.user.id))

    await session.refresh(consent)
    assert await user_repository.find_by_id(case.user.id) is None
    assert consent.user_id is None
    assert consent.owner_user_id == target.id
    assert consent.terms == original_terms
    assert consent.terms["user_id"] == case.user.id
    assert consent.telegram_id == original_telegram_id
    assert consent.accepted_at == original_accepted_at
    assert consent.revoked_at is None
    assert (await case.repository.consent_terms(consent.id)).user_id == target.id

    mandate = await case.repository.get(case.subscription.id)
    assert mandate.enabled and mandate.consent_id == consent.id
    assert mandate.payment_method_id == original.payment_method_id
    assert (await subscription_repository.get_by_id(case.subscription.id)).user_id == target.id
    assert (await transaction_repository.get_by_id(case.source.id)).user_id == target.id

    await case.worker.system()
    assert len(case.provider.posts) == 1
    mandate = await case.repository.get(case.subscription.id)
    assert mandate.enabled and mandate.last_error is None
    order = await transaction_repository.get_by_id(mandate.pending_transaction_id)
    assert order.user_id == target.id
    assert order.recurring_consent_id == consent.id


async def _withdrawn(case, session, uow, *, days: int, pending: bool = False) -> None:  # type: ignore[no-untyped-def]
    async with uow:
        row = await session.get(RecurringPayment, case.subscription.id)
        row.customer_disabled = True
        row.enabled = False
        row.disabled_at = datetime_now() - timedelta(days=days)
        if pending:
            row.pending_transaction_id = case.source.id
        await session.flush()


async def test_wipe_after_30_days_only(case, session, uow) -> None:
    repository = RecurringPaymentRepository(session)
    use_case = WipeStalePaymentMethodsUseCase(repository, uow)
    await _withdrawn(case, session, uow, days=29)
    await use_case.system()
    assert (await repository.get(case.subscription.id)).payment_method_id is not None
    await _withdrawn(case, session, uow, days=31, pending=True)
    await use_case.system()
    assert (await repository.get(case.subscription.id)).payment_method_id is not None
    await _withdrawn(case, session, uow, days=31)
    async with uow:
        row = await session.get(RecurringPayment, case.subscription.id)
        row.pending_transaction_id = None
    await use_case.system()
    assert (await repository.get(case.subscription.id)).payment_method_id is None
