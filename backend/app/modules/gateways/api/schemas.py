from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.dto import ResponseModel
from app.core.enums import PaymentGatewayType


class GatewayResponse(ResponseModel):
    type: PaymentGatewayType
    order_index: int
    is_active: bool
    is_configured: bool
    flags: dict[str, bool]
    values: dict[str, str]
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


class GatewayFieldConditionResponse(ResponseModel):
    field: str
    value: str


class GatewayFieldSpecResponse(ResponseModel):
    key: str
    kind: Literal["text", "secret", "number", "boolean", "url", "choice"]
    options: list[str]
    required: bool
    group: Optional[str]
    requires_all_channels: bool
    required_unless: Optional[str]
    hidden_when: Optional[GatewayFieldConditionResponse]


class GatewayCatalogEntryResponse(ResponseModel):
    type: PaymentGatewayType
    webhook_url: Optional[str]
    fields: list[GatewayFieldSpecResponse]


class GatewayCatalogResponse(ResponseModel):
    items: list[GatewayCatalogEntryResponse]
    total: int


class GatewayListResponse(ResponseModel):
    items: list[GatewayResponse]
    total: int
