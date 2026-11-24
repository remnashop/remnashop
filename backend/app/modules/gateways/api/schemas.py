from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.enums import Locale, PaymentGatewayType
from app.modules.gateways.presentation import (
    GATEWAY_DESCRIPTION_MAX_LENGTH,
    GATEWAY_NAME_MAX_LENGTH,
)


class GatewayTextResponse(BaseModel):
    name: str
    description: str


class GatewayTextRequest(BaseModel):
    name: str = Field(default="", max_length=GATEWAY_NAME_MAX_LENGTH)
    description: str = Field(default="", max_length=GATEWAY_DESCRIPTION_MAX_LENGTH)

    @field_validator("name", "description")
    @classmethod
    def single_line(cls, value: str) -> str:
        return " ".join(value.split())


class UpdateGatewayPresentationRequest(BaseModel):
    presentation: dict[Locale, GatewayTextRequest]


class GatewayResponse(BaseModel):
    presentation: dict[Locale, GatewayTextResponse] = Field(default_factory=dict)
    type: PaymentGatewayType
    order_index: int
    is_active: bool
    is_configured: bool
    flags: dict[str, bool]
    splits_channels: bool
    telegram_enabled: bool
    cabinet_enabled: bool


class UpdateGatewaySettingsRequest(BaseModel):
    values: dict[str, str] = Field(min_length=1)


class UpdateGatewayRequest(BaseModel):
    telegram_enabled: Optional[bool] = None
    cabinet_enabled: Optional[bool] = None


class ReorderGatewaysRequest(BaseModel):
    types: list[PaymentGatewayType]


class GatewayFieldSpecResponse(BaseModel):
    key: str
    kind: Literal["text", "secret", "number", "boolean", "url"]
    required: bool
    group: Optional[str]
    requires_all_channels: bool
    required_unless: Optional[str]


class GatewayCatalogEntryResponse(BaseModel):
    type: PaymentGatewayType
    webhook_url: Optional[str]
    fields: list[GatewayFieldSpecResponse]


class GatewayCatalogResponse(BaseModel):
    items: list[GatewayCatalogEntryResponse]
    total: int


class GatewayListResponse(BaseModel):
    items: list[GatewayResponse]
    total: int
