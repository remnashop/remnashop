import datetime
from datetime import timedelta, timezone
from typing import AsyncIterator

import httpx
import pytest
from dishka import AsyncContainer
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.constants import API_V1
from app.core.db.models import User
from app.core.db.uow import UnitOfWork
from app.core.enums import Locale, PurchaseChannel, Role, SessionAudience, TransactionStatus
from app.core.security import create_access_token, hash_password, hash_refresh_token
from app.modules.auth.dto import CreateSessionDto
from app.modules.auth.repository import SessionRepository
from app.modules.recurring_payments.dto import SetRecurringPaymentDto
from app.modules.users.dto import CreateUserDto
from app.modules.users.repository import UserRepository
from tests.fakes.container import make_test_container


@pytest.fixture
async def test_container(session: AsyncSession, config: AppConfig) -> AsyncIterator[AsyncContainer]:
    container = make_test_container(session, config)
    yield container
    await container.close()


@pytest.fixture
async def client(
    test_container: AsyncContainer, api_app: FastAPI
) -> AsyncIterator[httpx.AsyncClient]:
    api_app.state.dishka_container = test_container
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


async def staff_headers(
    user_repository: UserRepository,
    session_repository: SessionRepository,
    uow: UnitOfWork,
    config: AppConfig,
    role: Role,
) -> dict[str, str]:
    login = f"transactions{role.name.lower()}"
    async with uow:
        staff = await user_repository.create(
            CreateUserDto(
                login=login,
                password_hash=await hash_password("x", config.crypt_key.get_secret_value()),
                name=login,
                role=role,
                language=Locale.EN,
            )
        )
        await uow.commit()
    session = await session_repository.create(
        CreateSessionDto(
            user_id=staff.id,
            refresh_token_hash=hash_refresh_token(f"test-refresh-token-{login}"),
            ip_address="127.0.0.1",
            user_agent=None,
            expires_at=datetime.datetime.now(timezone.utc) + timedelta(days=30),
            audience=SessionAudience.DASHBOARD,
        )
    )
    token = create_access_token(staff.id, session.id, config.jwt_secret.get_secret_value())
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_auth_headers(user_repository, session_repository, uow, config) -> dict[str, str]:
    return await staff_headers(user_repository, session_repository, uow, config, Role.ADMIN)


@pytest.fixture
async def owner_auth_headers(user_repository, session_repository, uow, config) -> dict[str, str]:
    return await staff_headers(user_repository, session_repository, uow, config, Role.OWNER)


async def test_recurring_dashboard_is_available_to_an_owner(client, owner_auth_headers):
    response = await client.get(f"{API_V1}/transactions/recurring", headers=owner_auth_headers)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    summary = await client.get(
        f"{API_V1}/transactions/recurring/summary", headers=owner_auth_headers
    )
    assert summary.status_code == 200
    assert summary.json()["total"] == 0 and summary.json()["revenue"] == "0"


async def test_recurring_dashboard_requires_recurring_permission(
    client,
    admin_auth_headers,
    user_repository,
    session,
    uow,
):
    admin = await user_repository.find_by_login("transactionsadmin")
    async with uow:
        row = await session.get(User, admin.id)
        row.permission_revokes = ["TRANSACTIONS_RECURRING_VIEW"]
        await session.flush()
    response = await client.get(f"{API_V1}/transactions/recurring", headers=admin_auth_headers)
    assert response.status_code == 403


async def test_recurring_dashboard_rejects_unknown_state(client, owner_auth_headers):
    response = await client.get(
        f"{API_V1}/transactions/recurring?state=secret", headers=owner_auth_headers
    )
    assert response.status_code == 422


async def test_recurring_permission_does_not_require_other_transaction_permissions(
    client,
    admin_auth_headers,
    user_repository,
    session,
    uow,
):
    admin = await user_repository.find_by_login("transactionsadmin")
    async with uow:
        row = await session.get(User, admin.id)
        row.permission_revokes = ["TRANSACTIONS_VIEW", "TRANSACTIONS_SUMMARY_VIEW"]
        await session.flush()
    response = await client.get(f"{API_V1}/transactions/recurring", headers=admin_auth_headers)
    assert response.status_code == 200
    assert (
        await client.get(f"{API_V1}/transactions", headers=admin_auth_headers)
    ).status_code == 403
    assert (
        await client.get(f"{API_V1}/transactions/summary", headers=admin_auth_headers)
    ).status_code == 403


@pytest.mark.parametrize("action", ["check", "close", "retry"])
async def test_recurring_management_has_a_separate_permission(
    client, admin_auth_headers, user_repository, session, uow, action
):
    admin = await user_repository.find_by_login("transactionsadmin")
    async with uow:
        row = await session.get(User, admin.id)
        row.permission_revokes = [f"TRANSACTIONS_RECURRING_{action.upper()}"]
        await session.flush()
    response = await client.post(
        f"{API_V1}/transactions/recurring/1/actions/{action}",
        headers=admin_auth_headers,
        json={"expected_pending_transaction_id": None},
    )
    assert response.status_code == 403


async def test_recurring_management_rejects_unknown_action(client, owner_auth_headers):
    response = await client.post(
        f"{API_V1}/transactions/recurring/1/actions/charge",
        headers=owner_auth_headers,
        json={"expected_pending_transaction_id": None},
    )
    assert response.status_code in {404, 405}


async def test_recurring_close_uses_the_pending_order_confirmed_by_the_operator(
    client, owner_auth_headers, case, transaction_repository
):
    case.provider.status = "pending"
    await case.worker.system()
    before = await case.repository.get(case.subscription.id)
    path = f"{API_V1}/transactions/recurring/{case.subscription.id}/actions/close"
    stale = await client.post(
        path,
        headers=owner_auth_headers,
        json={"expected_pending_transaction_id": before.pending_transaction_id + 1},
    )
    assert stale.status_code == 409
    assert (
        await transaction_repository.get_by_id(before.pending_transaction_id)
    ).status is TransactionStatus.PENDING
    assert (await case.repository.get(case.subscription.id)).enabled
    closed = await client.post(
        path,
        headers=owner_auth_headers,
        json={"expected_pending_transaction_id": before.pending_transaction_id},
    )
    assert closed.status_code == 204
    after = await case.repository.get(case.subscription.id)
    assert (
        not after.enabled
        and after.last_error == "admin_closed"
        and after.pending_transaction_id is None
    )
    assert await case.repository.consent_terms(before.consent_id) is None
    assert len(case.provider.posts) == 1


async def test_the_consent_route_shows_what_the_customer_accepted_even_after_withdrawal(
    client, owner_auth_headers, case, session, uow
):
    path = f"{API_V1}/transactions/recurring/{case.subscription.id}/consent"
    accepted = await client.get(path, headers=owner_auth_headers)
    assert accepted.status_code == 200
    assert accepted.json()["channel"] == "BOT" and accepted.json()["revoked_at"] is None
    assert accepted.json()["terms"]["text"]
    await case.set_state(
        case.user,
        SetRecurringPaymentDto(
            subscription_id=case.subscription.id,
            enabled=False,
            channel=PurchaseChannel.CABINET,
        ),
    )
    withdrawn = await client.get(path, headers=owner_auth_headers)
    assert withdrawn.json()["revoked_at"] is not None
    assert withdrawn.json()["terms"]["text"] == accepted.json()["terms"]["text"]


async def test_the_consent_route_answers_404_without_any_consent(client, owner_auth_headers):
    response = await client.get(
        f"{API_V1}/transactions/recurring/999999/consent", headers=owner_auth_headers
    )
    assert response.status_code == 404


async def test_the_consent_of_a_hidden_staff_member_answers_404(
    client, admin_auth_headers, case, session, uow
):
    async with uow:
        await session.execute(update(User).where(User.id == case.user.id).values(role=Role.ADMIN))
    response = await client.get(
        f"{API_V1}/transactions/recurring/{case.subscription.id}/consent",
        headers=admin_auth_headers,
    )
    assert response.status_code == 404
