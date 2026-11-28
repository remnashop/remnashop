from loguru import logger

from app.core.db.uow import UnitOfWork
from app.core.error_codes import ErrorCode
from app.core.exceptions import ValidationError
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.modules.recurring_payments.dto import RecurringPaymentStateDto, SetRecurringPaymentDto
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import ConsentChannel
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.usecases.get_own_recurring_payment import (
    GetOwnRecurringPaymentUseCase,
)
from app.modules.subscriptions import SubscriptionRepository, get_owned_target
from app.modules.users import UserDto


class SetOwnRecurringPaymentUseCase(
    UseCase[SetRecurringPaymentDto, RecurringPaymentStateDto, UserDto]
):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        subscription_repository: SubscriptionRepository,
        get_own_recurring_payment: GetOwnRecurringPaymentUseCase,
        uow: UnitOfWork,
    ) -> None:
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._subscriptions = subscription_repository
        self._get_state = get_own_recurring_payment
        self._uow = uow

    async def _execute(
        self, actor: UserDto, data: SetRecurringPaymentDto
    ) -> RecurringPaymentStateDto:
        state = await self._get_state(actor, data.subscription_id)
        if data.enabled and not state.available:
            raise ValidationError(
                "A saved YooKassa payment method is required; pay for the subscription first",
                code=ErrorCode.RECURRING_NOT_AVAILABLE,
            )
        if data.enabled and (state.terms is None or data.terms_id != state.terms.terms_id):
            raise ValidationError(
                "Explicit consent to the current renewal terms is required",
                code=ErrorCode.RECURRING_TERMS_CHANGED,
            )
        async with self._uow:
            await get_owned_target(self._subscriptions, data.subscription_id, actor.id)
            if await self._recurring.get(data.subscription_id, for_update=True) is None:
                # nothing to withdraw, and switching on needs a mandate: no row is created
                return state
            await self._lifecycle.revoke_consent(
                data.subscription_id,
                channel=ConsentChannel(data.channel.value),
                event_id=data.event_id,
                ip_address=data.client_ip,
            )
            consent_id = (
                await self._recurring.record_consent(
                    state.terms,
                    channel=data.channel,
                    telegram_id=actor.telegram_id,
                    event_id=data.event_id,
                    ip_address=data.client_ip,
                )
                if data.enabled and state.terms is not None
                else None
            )
            await self._lifecycle.set_enabled(
                data.subscription_id, data.enabled, consent_id=consent_id
            )
        logger.info(
            f"{actor.log} Set auto-renewal of subscription '{data.subscription_id}' "
            f"to {data.enabled}"
        )
        return await self._get_state(actor, data.subscription_id)
