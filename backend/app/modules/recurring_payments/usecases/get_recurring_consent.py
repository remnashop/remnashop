from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.error_codes import ErrorCode
from app.core.exceptions import NotFoundError
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.modules.recurring_payments.dto import RecurringConsentDto
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.subscriptions import SubscriptionRepository
from app.modules.users import UserRepository, get_visible_target


class GetRecurringConsentUseCase(UseCase[int, RecurringConsentDto]):
    required_permission = Permission.TRANSACTIONS_RECURRING_CONSENT_VIEW

    def __init__(
        self,
        recurring_repository: RecurringPaymentRepository,
        subscription_repository: SubscriptionRepository,
        user_repository: UserRepository,
        uow: UnitOfWork,
    ) -> None:
        self._recurring = recurring_repository
        self._subscriptions = subscription_repository
        self._users = user_repository
        self._uow = uow

    async def _execute(self, actor: Actor, data: int) -> RecurringConsentDto:
        async with self._uow:
            subscription = await self._subscriptions.get_by_id(data)
            await get_visible_target(self._users, actor, subscription.user_id)
            consent = await self._recurring.latest_consent(data)
        if consent is None:
            raise NotFoundError(
                f"Subscription '{data}' has no auto-renewal consent",
                code=ErrorCode.RECURRING_NOT_AVAILABLE,
            )
        return consent
