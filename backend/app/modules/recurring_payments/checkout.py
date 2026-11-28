from typing import Optional

from app.core.enums import PaymentGatewayType, PurchaseChannel, PurchaseType
from app.core.error_codes import ErrorCode
from app.core.exceptions import ConflictError, ValidationError
from app.modules.gateways import yookassa_recurring_enabled, yookassa_recurring_required
from app.modules.plans import PlanDto
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import ConsentChannel, recurring_policy
from app.modules.recurring_payments.ports import RecurringTermsTexts
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.terms import build_recurring_terms
from app.modules.transactions import CreateCheckoutDto, PriceQuote
from app.modules.users import UserDto


class RecurringCheckoutConsent:
    def __init__(
        self,
        repository: RecurringPaymentRepository,
        lifecycle: RecurringLifecycle,
        texts: RecurringTermsTexts,
    ) -> None:
        self._repository = repository
        self._lifecycle = lifecycle
        self._texts = texts

    async def hold(self, user_id: int, data: CreateCheckoutDto) -> None:
        # one period, one payment: an unsent automatic attempt gives way, a sent one refuses;
        # the mandate stays locked until this order commits
        subscription_id = data.target_subscription_id
        if subscription_id is None or data.purchase_type is PurchaseType.NEW:
            return
        current = await self._repository.get(subscription_id)
        facts = await self._repository.subscription_facts(subscription_id)
        if current is None or facts is None or facts.user_id != user_id:
            return
        if current.pending_transaction_id is not None and current.submitted_at is None:
            await self._lifecycle.cancel_unsent(subscription_id, current.pending_transaction_id)
        mandate = await self._repository.get(subscription_id, for_update=True)
        if (
            mandate is not None
            and mandate.pending_transaction_id is not None
            and mandate.submitted_at is not None
        ):
            raise ConflictError(
                "An automatic renewal payment is already in progress",
                code=ErrorCode.RECURRING_PAYMENT_IN_PROGRESS,
            )

    async def record_consent(
        self,
        actor: UserDto,
        data: CreateCheckoutDto,
        plan: PlanDto,
        quote: PriceQuote,
        gateway_settings: dict[str, str],
    ) -> Optional[int]:
        yookassa = data.gateway_type is PaymentGatewayType.YOOKASSA
        if yookassa and yookassa_recurring_required(gateway_settings) and quote.final_price > 0:
            if not data.recurring_consent or plan.is_trial or data.duration_days <= 0:
                raise ValidationError(
                    "This payment method requires explicit consent to auto-renewal",
                    code=ErrorCode.RECURRING_CONSENT_REQUIRED,
                )
        if not data.recurring_consent:
            return None
        recurring_allowed = (
            yookassa
            and yookassa_recurring_enabled(gateway_settings)
            and not plan.is_trial
            and data.duration_days > 0
            and quote.final_price > 0
        )
        terms = await build_recurring_terms(
            texts=self._texts,
            policy=recurring_policy(gateway_settings),
            user_id=actor.id,
            plan_id=plan.id,
            target_subscription_id=data.target_subscription_id,
            purchase_type=data.purchase_type,
            initial_amount=quote.final_price,
            amount_limit=quote.base_price,
            currency=data.currency,
            duration_days=data.duration_days,
            locale=data.legal_locale or actor.language,
        )
        if not recurring_allowed or data.recurring_terms_id != terms.terms_id:
            raise ConflictError(
                "Auto-renewal terms changed; confirm them again",
                code=ErrorCode.RECURRING_TERMS_CHANGED,
            )
        return await self._repository.record_consent(
            terms,
            channel=data.channel,
            telegram_id=actor.telegram_id,
            event_id=data.consent_event_id,
            ip_address=data.client_ip,
        )

    async def revoke_consent(self, consent_id: Optional[int], channel: PurchaseChannel) -> None:
        await self._repository.revoke_consent_id(consent_id, channel=ConsentChannel(channel.value))
