from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Final, Literal, Optional, cast, get_args, get_origin

from pydantic import SecretStr
from pydantic.fields import FieldInfo

from app.core.enums import Currency, PaymentGatewayType
from app.core.error_codes import ErrorCode
from app.core.exceptions import ValidationError
from app.modules.gateways.gateway_settings import (
    GATEWAY_SETTINGS,
    HIDDEN_WHEN_KEY,
    RECURRING_TIMINGS,
    NumericStr,
)

_CURRENCY_FIELD_KEY: Final[str] = "currency"
# Stars settle only through the Telegram Stars gateway, which has no currency field
_GATEWAY_CURRENCIES: Final[tuple[Currency, ...]] = (Currency.USD, Currency.RUB)
# Webhook source-IP check for providers that don't sign their notifications
VERIFY_IP_FIELD_KEY: Final[str] = "verify_ip"
REQUIRE_PAID_PURCHASE_FIELD_KEY: Final[str] = "require_paid_purchase"
_BOOLEAN_VALUES: Final[frozenset[str]] = frozenset({"true", "false"})


class GatewayFieldKind(StrEnum):
    TEXT = auto()
    SECRET = auto()
    NUMBER = auto()
    BOOLEAN = auto()
    CHOICE = auto()


@dataclass(frozen=True, kw_only=True)
class GatewayFieldSpec:
    key: str
    kind: GatewayFieldKind
    required: bool = True
    default: str = ""
    options: tuple[str, ...] = ()
    # (other field key, value): the dashboard hides this field while that one holds the value
    hidden_when: Optional[tuple[str, str]] = None


_KIND_BY_TYPE: Final[dict[object, GatewayFieldKind]] = {
    str: GatewayFieldKind.TEXT,
    SecretStr: GatewayFieldKind.SECRET,
    NumericStr: GatewayFieldKind.NUMBER,
    bool: GatewayFieldKind.BOOLEAN,
}


def _field_spec(key: str, field: FieldInfo) -> GatewayFieldSpec:
    extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
    condition = cast(Optional[list[str]], extra.get(HIDDEN_WHEN_KEY))
    hidden_when = (condition[0], condition[1]) if condition else None
    if get_origin(field.annotation) is Literal:
        return GatewayFieldSpec(
            key=key,
            kind=GatewayFieldKind.CHOICE,
            required=field.is_required(),
            default=str(field.default),
            options=get_args(field.annotation),
            hidden_when=hidden_when,
        )
    declared = [arg for arg in get_args(field.annotation) if arg is not type(None)]
    kind = _KIND_BY_TYPE[declared[0] if declared else field.annotation]
    default = str(field.default).lower() if kind is GatewayFieldKind.BOOLEAN else ""
    return GatewayFieldSpec(
        key=key, kind=kind, required=field.is_required(), default=default, hidden_when=hidden_when
    )


GATEWAY_FIELD_CATALOG: Final[dict[PaymentGatewayType, tuple[GatewayFieldSpec, ...]]] = {
    gateway_type: tuple(_field_spec(key, field) for key, field in model.model_fields.items())
    for gateway_type, model in GATEWAY_SETTINGS.items()
}


def is_gateway_configured(gateway_type: PaymentGatewayType, values: dict[str, str]) -> bool:
    return all(
        values.get(field_spec.key, "").strip() != ""
        for field_spec in GATEWAY_FIELD_CATALOG[gateway_type]
        if field_spec.required
    )


def gateway_flags(gateway_type: PaymentGatewayType, values: dict[str, str]) -> dict[str, bool]:
    # unlike every other field these aren't secrets, so the dashboard reads
    # them back and renders switches
    flags = {
        field_spec.key: (values.get(field_spec.key) or field_spec.default) == "true"
        for field_spec in GATEWAY_FIELD_CATALOG[gateway_type]
        if field_spec.kind is GatewayFieldKind.BOOLEAN
    }
    return flags


_READABLE_KINDS: Final[frozenset[GatewayFieldKind]] = frozenset(
    {GatewayFieldKind.TEXT, GatewayFieldKind.NUMBER, GatewayFieldKind.CHOICE}
)


def gateway_values(gateway_type: PaymentGatewayType, values: dict[str, str]) -> dict[str, str]:
    # every stored setting but the secrets, so the dashboard shows what is in effect
    readable: dict[str, str] = {}
    for field_spec in GATEWAY_FIELD_CATALOG[gateway_type]:
        if field_spec.kind not in _READABLE_KINDS:
            continue
        value = values.get(field_spec.key) or field_spec.default
        if value:
            readable[field_spec.key] = value
    return readable


def validate_gateway_field_keys(gateway_type: PaymentGatewayType, values: dict[str, str]) -> None:
    valid_keys = {field_spec.key for field_spec in GATEWAY_FIELD_CATALOG[gateway_type]}
    unknown = set(values) - valid_keys
    if unknown:
        raise ValidationError(
            f"Unknown settings field(s) for {gateway_type.value}: {', '.join(sorted(unknown))}",
            code=ErrorCode.GATEWAY_FIELD_UNKNOWN,
        )


def validate_gateway_field_values(gateway_type: PaymentGatewayType, values: dict[str, str]) -> None:
    raw_currency = values.get(_CURRENCY_FIELD_KEY, "").strip()
    if raw_currency:
        if raw_currency.upper() not in _GATEWAY_CURRENCIES:
            allowed = ", ".join(currency.value for currency in _GATEWAY_CURRENCIES)
            raise ValidationError(
                f"Invalid currency '{raw_currency}' for {gateway_type.value}; "
                f"must be one of {allowed}",
                code=ErrorCode.GATEWAY_CURRENCY_INVALID,
            )

    for field_spec in GATEWAY_FIELD_CATALOG[gateway_type]:
        _validate_field_value(gateway_type, field_spec, values.get(field_spec.key))


def _validate_field_value(
    gateway_type: PaymentGatewayType, field_spec: GatewayFieldSpec, raw_value: Optional[str]
) -> None:
    if field_spec.kind is GatewayFieldKind.CHOICE:
        if raw_value is not None and raw_value not in field_spec.options:
            raise ValidationError(
                f"Invalid choice for '{field_spec.key}'",
                code=ErrorCode.GATEWAY_FIELD_INVALID_CHOICE,
            )
        return
    if field_spec.kind is GatewayFieldKind.BOOLEAN:
        if raw_value is not None and raw_value not in _BOOLEAN_VALUES:
            raise ValidationError(
                f"Field '{field_spec.key}' for {gateway_type.value} must be 'true' or 'false'",
                code=ErrorCode.GATEWAY_FIELD_NOT_BOOLEAN,
            )
        return
    if field_spec.kind is not GatewayFieldKind.NUMBER or not raw_value or not raw_value.strip():
        return
    try:
        number = int(raw_value)
    except ValueError:
        raise ValidationError(
            f"Field '{field_spec.key}' for {gateway_type.value} must be a number, "
            f"got '{raw_value}'",
            code=ErrorCode.GATEWAY_FIELD_NOT_NUMBER,
        ) from None
    bounds = RECURRING_TIMINGS.get(field_spec.key)
    if bounds is not None and not bounds[1] <= number <= bounds[2]:
        raise ValidationError(
            f"Field '{field_spec.key}' must be between {bounds[1]} and {bounds[2]}",
            code=ErrorCode.GATEWAY_FIELD_OUT_OF_RANGE,
        )
