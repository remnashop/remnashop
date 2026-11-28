from dishka.integrations.taskiq import FromDishka, inject

from app.core.broker import broker
from app.modules.recurring_payments.dto import ProcessRecurringPaymentDto
from app.modules.recurring_payments.usecases import (
    EnqueueRecurringPaymentsUseCase,
    ProcessRecurringPaymentUseCase,
    WipeStalePaymentMethodsUseCase,
)


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
@inject(patch_module=True)
async def process_recurring_payments_task(
    use_case: FromDishka[EnqueueRecurringPaymentsUseCase],
) -> None:
    await use_case.system()


@broker.task(retry_on_error=True, max_retries=3)
@inject(patch_module=True)
async def process_one_recurring_payment_task(
    subscription_id: int,
    use_case: FromDishka[ProcessRecurringPaymentUseCase],
) -> None:
    await use_case.system(ProcessRecurringPaymentDto(subscription_id=subscription_id))


@broker.task(schedule=[{"cron": "30 4 * * *"}])
@inject(patch_module=True)
async def wipe_stale_payment_methods_task(
    use_case: FromDishka[WipeStalePaymentMethodsUseCase],
) -> None:
    await use_case.system()
