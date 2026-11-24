from app.core.actor import Actor
from app.core.db.uow import UnitOfWork
from app.core.ports import EventPublisher
from app.core.security.permissions import Permission
from app.core.usecase import UseCase
from app.modules.gateways.dto import PaymentGatewayDto, UpdateGatewayPresentationDto
from app.modules.gateways.events import GatewayChangedEvent
from app.modules.gateways.repository import GatewayRepository


class UpdateGatewayPresentationUseCase(UseCase[UpdateGatewayPresentationDto, PaymentGatewayDto]):
    required_permission = Permission.GATEWAYS_UPDATE

    def __init__(
        self,
        gateway_repository: GatewayRepository,
        event_publisher: EventPublisher,
        uow: UnitOfWork,
    ) -> None:
        self._gateway_repository = gateway_repository
        self._event_publisher = event_publisher
        self._uow = uow

    async def _execute(self, actor: Actor, data: UpdateGatewayPresentationDto) -> PaymentGatewayDto:
        async with self._uow:
            gateway = await self._gateway_repository.set_presentation(data.type, data.presentation)
            await self._event_publisher.publish(
                GatewayChangedEvent(
                    actor=actor,
                    action="settings",
                    gateway_type=data.type,
                    changed_fields=["presentation"],
                    ip_address=data.client_ip,
                )
            )
        return gateway
