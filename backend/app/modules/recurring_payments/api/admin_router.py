from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.api.dependencies.admin import require_admin
from app.api.errors import error_responses
from app.core.actor import Actor
from app.core.constants import DEFAULT_PAGE_SIZE, INT32_MAX, MAX_PAGE_SIZE, SEARCH_MAX_LENGTH
from app.core.utils.http import resolve_client_ip
from app.modules.recurring_payments.api.schemas import (
    RecurringAdminActionRequest,
    RecurringConsentResponse,
    RecurringPaymentAdminItemResponse,
    RecurringPaymentPageResponse,
    RecurringPaymentSummaryResponse,
)
from app.modules.recurring_payments.dto import ListRecurringPaymentsDto, RecurringAdminActionDto
from app.modules.recurring_payments.policy import RecurringState
from app.modules.recurring_payments.usecases import (
    CheckRecurringPaymentUseCase,
    CloseRecurringPaymentUseCase,
    GetRecurringConsentUseCase,
    GetRecurringPaymentSummaryUseCase,
    ListRecurringPaymentsUseCase,
    RetryRecurringPaymentUseCase,
)

router = APIRouter(prefix="/transactions/recurring", tags=["recurring-payments"])


@router.get("", response_model=RecurringPaymentPageResponse)
@inject
async def list_recurring_payments(
    use_case: FromDishka[ListRecurringPaymentsUseCase],
    actor: Actor = Depends(require_admin),
    state: Optional[RecurringState] = None,
    search: Optional[str] = Query(None, max_length=SEARCH_MAX_LENGTH),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> RecurringPaymentPageResponse:
    items, total = await use_case(
        actor, ListRecurringPaymentsDto(state=state, search=search, page=page, page_size=page_size)
    )
    return RecurringPaymentPageResponse(
        items=[
            RecurringPaymentAdminItemResponse.model_validate(item, from_attributes=True)
            for item in items
        ],
        total=total,
    )


@router.get("/summary", response_model=RecurringPaymentSummaryResponse)
@inject
async def get_recurring_payment_summary(
    use_case: FromDishka[GetRecurringPaymentSummaryUseCase],
    actor: Actor = Depends(require_admin),
) -> RecurringPaymentSummaryResponse:
    return RecurringPaymentSummaryResponse.model_validate(
        await use_case(actor), from_attributes=True
    )


@router.get(
    "/{subscription_id:int}/consent",
    response_model=RecurringConsentResponse,
    responses=error_responses(404),
)
@inject
async def get_recurring_consent(
    use_case: FromDishka[GetRecurringConsentUseCase],
    subscription_id: int = Path(ge=1, le=INT32_MAX),
    actor: Actor = Depends(require_admin),
) -> RecurringConsentResponse:
    consent = await use_case(actor, subscription_id)
    return RecurringConsentResponse.model_validate(consent, from_attributes=True)


def _action(
    subscription_id: int, data: RecurringAdminActionRequest, request: Request
) -> RecurringAdminActionDto:
    return RecurringAdminActionDto(
        subscription_id=subscription_id,
        expected_pending_transaction_id=data.expected_pending_transaction_id,
        client_ip=resolve_client_ip(request),
    )


@router.post(
    "/{subscription_id:int}/actions/check",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(404, 409, 502),
)
@inject
async def check_recurring_payment(
    data: RecurringAdminActionRequest,
    request: Request,
    use_case: FromDishka[CheckRecurringPaymentUseCase],
    subscription_id: int = Path(ge=1, le=INT32_MAX),
    actor: Actor = Depends(require_admin),
) -> Response:
    await use_case(actor, _action(subscription_id, data, request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{subscription_id:int}/actions/close",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(404, 409),
)
@inject
async def close_recurring_payment(
    data: RecurringAdminActionRequest,
    request: Request,
    use_case: FromDishka[CloseRecurringPaymentUseCase],
    subscription_id: int = Path(ge=1, le=INT32_MAX),
    actor: Actor = Depends(require_admin),
) -> Response:
    await use_case(actor, _action(subscription_id, data, request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{subscription_id:int}/actions/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 404, 409),
)
@inject
async def retry_recurring_payment(
    data: RecurringAdminActionRequest,
    request: Request,
    use_case: FromDishka[RetryRecurringPaymentUseCase],
    subscription_id: int = Path(ge=1, le=INT32_MAX),
    actor: Actor = Depends(require_admin),
) -> Response:
    await use_case(actor, _action(subscription_id, data, request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
