from datetime import timedelta
from decimal import Decimal
from typing import Optional

from app.core.enums import PaymentGatewayType
from app.core.utils.time import datetime_now
from app.modules.gateways import GatewayRepository, yookassa_recurring_enabled
from app.modules.recurring_payments.dto import RecurringPaymentDto
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.policy import (
    POLICY_RECHECK_DELAY,
    RecurringPolicy,
    RecurringReason,
    recurring_policy,
)
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.settings import SettingsRepository
from app.modules.transactions import TransactionDto, YooKassaGateway


class RecurringDebitChecks:
    # what both the reservation and the submission re-check before money moves

    def __init__(
        self,
        recurring_repository: RecurringPaymentRepository,
        recurring_lifecycle: RecurringLifecycle,
        gateway_repository: GatewayRepository,
        settings_repository: SettingsRepository,
    ) -> None:
        self._recurring = recurring_repository
        self._lifecycle = recurring_lifecycle
        self._gateways = gateway_repository
        self._settings = settings_repository

    async def defer(self, subscription_id: int, error: Optional[RecurringReason] = None) -> None:
        mandate = await self._recurring.get(subscription_id)
        terms = await self._recurring.consent_terms(mandate.consent_id) if mandate else None
        minutes = terms.retry_minutes if terms else (await self.policy()).retry_minutes
        reason = error or (mandate.last_error if mandate else None)
        delay = (
            POLICY_RECHECK_DELAY
            if reason is RecurringReason.PENDING_TIMEOUT
            else timedelta(minutes=minutes)
        )
        await self._lifecycle.defer(subscription_id, datetime_now() + delay, error)

    async def will_renew(self, subscription_id: int) -> bool:
        """Whether the next charge would go out as things stand, so the customer hears
        "renew in advance" from nothing but a working mandate."""
        mandate = await self._recurring.get(subscription_id)
        if (
            mandate is None
            or not mandate.enabled
            or mandate.last_error is not None
            or not mandate.payment_method_id
            or not await self.enabled()
            or await self._recurring.consent_terms(mandate.consent_id) is None
        ):
            return False
        settings = await self._gateways.get_raw_settings(PaymentGatewayType.YOOKASSA)
        return YooKassaGateway.shop_takes_payments(settings, mandate.shop_id)

    async def policy(self) -> RecurringPolicy:
        return recurring_policy(await self._gateways.get_raw_settings(PaymentGatewayType.YOOKASSA))

    async def enabled(self) -> bool:
        gateway = await self._gateways.get_by_type(PaymentGatewayType.YOOKASSA)
        access = await self._settings.get_access_settings()
        return bool(
            access.payments_enabled
            and gateway.is_active
            and gateway.is_configured
            and yookassa_recurring_enabled(gateway.values)
        )

    async def has_consent(
        self, mandate: RecurringPaymentDto, order: TransactionDto, amount: Decimal
    ) -> bool:
        terms = await self._recurring.consent_terms(mandate.consent_id)
        if terms is None:
            await self._lifecycle.disable(mandate.subscription_id, RecurringReason.CONSENT_REQUIRED)
            return False
        authorized = bool(
            terms
            and terms.covers(
                user_id=order.user_id,
                plan_id=order.plan_snapshot.plan_id,
                amount=amount,
                duration_days=order.duration_days,
                currency=order.currency,
            )
        )
        if not authorized:
            await self._lifecycle.pause(mandate.subscription_id, RecurringReason.CONSENT_REQUIRED)
        return authorized
