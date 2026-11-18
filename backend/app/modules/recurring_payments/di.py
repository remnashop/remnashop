from typing import cast

from dishka import Provider, Scope, alias, provide, provide_all

from app.modules.recurring_payments.admin_guard import RecurringAdminGuard
from app.modules.recurring_payments.admin_repository import RecurringPaymentAdminRepository
from app.modules.recurring_payments.checkout import RecurringCheckoutConsent
from app.modules.recurring_payments.checks import RecurringDebitChecks
from app.modules.recurring_payments.debit import RecurringDebit
from app.modules.recurring_payments.dispatch import ProcessRecurringPaymentDispatch
from app.modules.recurring_payments.lifecycle import RecurringLifecycle
from app.modules.recurring_payments.poller import RecurringPoller
from app.modules.recurring_payments.repository import RecurringPaymentRepository
from app.modules.recurring_payments.reservation import RecurringReservation
from app.modules.recurring_payments.tasks import process_one_recurring_payment_task
from app.modules.recurring_payments.usecases import (
    CheckRecurringPaymentUseCase,
    CloseRecurringPaymentUseCase,
    EnqueueRecurringPaymentsUseCase,
    GetCheckoutRecurringTermsUseCase,
    GetOwnRecurringPaymentUseCase,
    GetRecurringConsentUseCase,
    GetRecurringPaymentSummaryUseCase,
    ListRecurringPaymentsUseCase,
    ProcessRecurringPaymentUseCase,
    RetryRecurringPaymentUseCase,
    SetOwnRecurringPaymentUseCase,
    WipeStalePaymentMethodsUseCase,
)
from app.modules.subscriptions import RecurringPaymentCloser
from app.modules.transactions import RecurringCheckout, RecurringOrderHooks


class RecurringPaymentsProvider(Provider):
    scope = Scope.REQUEST

    recurring_payment_repository = provide(RecurringPaymentRepository)
    recurring_payment_admin_repository = provide(RecurringPaymentAdminRepository)
    recurring_lifecycle = provide(RecurringLifecycle)
    recurring_poller = provide(RecurringPoller)
    recurring_debit_checks = provide(RecurringDebitChecks)
    recurring_reservation = provide(RecurringReservation)
    recurring_debit = provide(RecurringDebit)
    recurring_admin_guard = provide(RecurringAdminGuard)
    recurring_checkout_consent = provide(RecurringCheckoutConsent)
    recurring_checkout = alias(source=RecurringCheckoutConsent, provides=RecurringCheckout)
    recurring_order_hooks = alias(source=RecurringLifecycle, provides=RecurringOrderHooks)
    recurring_payment_closer = alias(source=RecurringLifecycle, provides=RecurringPaymentCloser)
    use_cases = provide_all(
        CheckRecurringPaymentUseCase,
        EnqueueRecurringPaymentsUseCase,
        GetCheckoutRecurringTermsUseCase,
        GetOwnRecurringPaymentUseCase,
        GetRecurringConsentUseCase,
        GetRecurringPaymentSummaryUseCase,
        ListRecurringPaymentsUseCase,
        CloseRecurringPaymentUseCase,
        RetryRecurringPaymentUseCase,
        ProcessRecurringPaymentUseCase,
        SetOwnRecurringPaymentUseCase,
        WipeStalePaymentMethodsUseCase,
    )

    @provide(scope=Scope.APP)
    def process_recurring_payment_dispatch(self) -> ProcessRecurringPaymentDispatch:
        return cast(ProcessRecurringPaymentDispatch, process_one_recurring_payment_task)


def get_recurring_payments_providers() -> list[Provider]:
    return [RecurringPaymentsProvider()]
