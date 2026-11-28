from typing import Protocol


class ProcessRecurringPaymentDispatch(Protocol):
    async def kiq(self, *, subscription_id: int) -> object: ...
