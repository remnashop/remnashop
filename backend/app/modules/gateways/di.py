from dishka import Provider, Scope, provide, provide_all

from app.modules.gateways.repository import GatewayRepository
from app.modules.gateways.usecases import (
    ListGatewaysUseCase,
    ReorderGatewaysUseCase,
    SetGatewayActiveUseCase,
    UpdateGatewayChannelsUseCase,
    UpdateGatewayPresentationUseCase,
    UpdateGatewaySettingsUseCase,
)


class GatewaysProvider(Provider):
    scope = Scope.REQUEST

    gateway_repository = provide(GatewayRepository)
    use_cases = provide_all(
        ListGatewaysUseCase,
        UpdateGatewayPresentationUseCase,
        UpdateGatewaySettingsUseCase,
        SetGatewayActiveUseCase,
        UpdateGatewayChannelsUseCase,
        ReorderGatewaysUseCase,
    )


def get_gateways_providers() -> list[Provider]:
    return [GatewaysProvider()]
