from typing import Final

from pydantic import BaseModel, ConfigDict

from app.core.enums import Locale

GATEWAY_NAME_MAX_LENGTH: Final[int] = 64
GATEWAY_DESCRIPTION_MAX_LENGTH: Final[int] = 160


class GatewayText(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str = ""
    description: str = ""


def gateway_text(presentation: dict[Locale, GatewayText], locale: Locale) -> GatewayText:
    return presentation.get(locale, presentation.get(Locale.EN, GatewayText()))
