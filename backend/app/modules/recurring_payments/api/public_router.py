from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Request

from app.api.dependencies.public import AuthContext, get_auth_context, get_current_user
from app.api.errors import error_responses
from app.core.enums import PurchaseChannel
from app.core.utils.http import resolve_client_ip
from app.modules.recurring_payments.api.schemas import (
    CheckoutRecurringTermsRequest,
    CheckoutRecurringTermsResponse,
    RecurringPaymentStateResponse,
    SetRecurringPaymentRequest,
)
from app.modules.recurring_payments.dto import SetRecurringPaymentDto
from app.modules.recurring_payments.usecases import (
    GetCheckoutRecurringTermsUseCase,
    GetOwnRecurringPaymentUseCase,
    SetOwnRecurringPaymentUseCase,
)
from app.modules.transactions import CreateCheckoutDto
from app.modules.users import UserDto

router = APIRouter(tags=["recurring-payments"])


@router.get(
    "/subscriptions/me/{subscription_id:int}/auto-renew",
    response_model=RecurringPaymentStateResponse,
    responses=error_responses(400, 404),
)
@inject
async def get_own_recurring_payment(
    subscription_id: int,
    use_case: FromDishka[GetOwnRecurringPaymentUseCase],
    actor: UserDto = Depends(get_current_user),
) -> RecurringPaymentStateResponse:
    state = await use_case(actor, subscription_id)
    return RecurringPaymentStateResponse.model_validate(state, from_attributes=True)


@router.put(
    "/subscriptions/me/{subscription_id:int}/auto-renew",
    response_model=RecurringPaymentStateResponse,
    responses=error_responses(400, 404),
)
@inject
async def set_own_recurring_payment(
    subscription_id: int,
    payload: SetRecurringPaymentRequest,
    request: Request,
    use_case: FromDishka[SetOwnRecurringPaymentUseCase],
    actor: UserDto = Depends(get_current_user),
) -> RecurringPaymentStateResponse:
    state = await use_case(
        actor,
        SetRecurringPaymentDto(
            subscription_id=subscription_id,
            enabled=payload.enabled,
            terms_id=payload.terms_id,
            channel=PurchaseChannel.CABINET,
            client_ip=resolve_client_ip(request),
        ),
    )
    return RecurringPaymentStateResponse.model_validate(state, from_attributes=True)


@router.post(
    "/checkout/recurring-terms",
    response_model=CheckoutRecurringTermsResponse,
    responses=error_responses(400, 404),
)
@inject
async def checkout_recurring_terms(
    payload: CheckoutRecurringTermsRequest,
    use_case: FromDishka[GetCheckoutRecurringTermsUseCase],
    actor: UserDto = Depends(get_current_user),
    auth: AuthContext = Depends(get_auth_context),
) -> CheckoutRecurringTermsResponse:
    result = await use_case(
        actor,
        CreateCheckoutDto(
            plan_id=payload.plan_id,
            duration_days=payload.duration_days,
            currency=payload.currency,
            purchase_type=payload.purchase_type,
            channel=PurchaseChannel.CABINET,
            gateway_type=payload.gateway_type,
            in_telegram=auth.telegram_mini_app,
            target_subscription_id=payload.target_subscription_id,
            plan_code=payload.plan_code,
            legal_locale=payload.legal_locale,
        ),
    )
    return CheckoutRecurringTermsResponse.model_validate(result, from_attributes=True)
