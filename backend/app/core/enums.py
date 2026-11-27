from enum import IntEnum, StrEnum, auto
from typing import Optional


class UpperStrEnum(StrEnum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list) -> str:
        return name


class PaymentGatewayType(UpperStrEnum):
    TELEGRAM_STARS = auto()
    YOOKASSA = auto()
    YOOMONEY = auto()
    VALUTIX = auto()
    CRYPTOMUS = auto()
    HELEKET = auto()
    CRYPTOPAY = auto()
    FREEKASSA = auto()
    MULENPAY = auto()
    PAYMASTER = auto()
    PLATEGA = auto()
    ROBOKASSA = auto()
    URLPAY = auto()
    WATA = auto()
    ROLLYPAY = auto()
    ANTILOPAY = auto()
    PAYPALYCH = auto()
    RIOPAY = auto()
    AURAPAY = auto()
    SEVERPAY = auto()
    LAVA = auto()
    CLOUDPAYMENTS = auto()
    PAYPEAR = auto()
    CISPAY = auto()
    PAY_2328 = auto()
    COINSPAY = auto()


class PaymentOutcome(UpperStrEnum):
    SUCCEEDED = auto()
    NOT_FULFILLED = auto()
    CANCELED = auto()


class PlanType(UpperStrEnum):
    TRAFFIC = auto()
    DEVICES = auto()
    BOTH = auto()
    UNLIMITED = auto()


# a fixed set so the clients translate it, no per-plan texts
class PlanBadge(UpperStrEnum):
    POPULAR = auto()
    BEST_VALUE = auto()


class PlanAvailability(UpperStrEnum):
    ALL = auto()
    NEW = auto()
    EXISTING = auto()
    INVITED = auto()
    ALLOWED = auto()
    LINK = auto()


class Currency(UpperStrEnum):
    USD = auto()
    XTR = auto()
    RUB = auto()

    @property
    def symbol(self) -> str:
        symbols = {
            self.USD: "$",
            self.XTR: "★",
            self.RUB: "₽",
        }
        return symbols.get(self, "?")


class RoundingMode(UpperStrEnum):
    INTEGER = auto()
    DECIMAL_2 = auto()


class DiscountSource(UpperStrEnum):
    NONE = auto()
    PERSONAL = auto()
    PURCHASE = auto()
    LOYALTY = auto()


class FulfillmentHold(UpperStrEnum):
    """Why a paid order waits for an admin to issue or refund it."""

    # paid after its cancel, its one-shot discount already spent again
    PURCHASE_DISCOUNT_SPENT = auto()
    # a renewal whose subscription moved to another plan while it was paid
    PLAN_CHANGED = auto()


class SubscriptionStatus(UpperStrEnum):
    ACTIVE = auto()
    LIMITED = auto()
    EXPIRED = auto()
    DISABLED = auto()
    DELETED = auto()


class AddOnType(UpperStrEnum):
    TRAFFIC = auto()
    DEVICES = auto()


class PromocodeRewardType(UpperStrEnum):
    DURATION = auto()
    TRAFFIC = auto()
    DEVICES = auto()
    SUBSCRIPTION = auto()
    PERSONAL_DISCOUNT = auto()
    PURCHASE_DISCOUNT = auto()


class PromocodeAvailability(UpperStrEnum):
    ALL = auto()
    NEW = auto()
    EXISTING = auto()
    INVITED = auto()
    ALLOWED = auto()


class CreditSegmentKind(UpperStrEnum):
    """Where a stretch of a subscription's term came from, for the plan change credit."""

    PURCHASE = auto()
    # what a plan change credited from the replaced subscription
    CARRIED = auto()
    # free days: referral bonus, an admin's grant
    BONUS = auto()
    # the term as it stood before segments existed
    LEGACY = auto()


class PurchaseType(UpperStrEnum):
    NEW = auto()
    RENEW = auto()
    CHANGE = auto()


class PurchaseChannel(UpperStrEnum):
    BOT = auto()
    CABINET = auto()


class LegalDocumentKind(UpperStrEnum):
    OFFER = auto()
    USER_AGREEMENT = auto()
    PRIVACY_POLICY = auto()


class LegalAcceptanceTrigger(UpperStrEnum):
    SIGN_UP = auto()
    PAYMENT = auto()


class ReferralRewardType(UpperStrEnum):
    EXTRA_DAYS = auto()
    POINTS = auto()


class ReferralAccrualStrategy(UpperStrEnum):
    FIRST_PAYMENT = auto()
    EVERY_PAYMENT = auto()


class ReferralRewardStrategy(UpperStrEnum):
    AMOUNT = auto()
    PERCENT = auto()


class RegistrationSource(UpperStrEnum):
    BOT = auto()
    CABINET_TELEGRAM = auto()
    CABINET_MINI_APP = auto()
    CABINET_BOT_LINK = auto()
    CABINET_EMAIL = auto()
    CABINET_GOOGLE = auto()
    CABINET_YANDEX = auto()


class AdLinkChannel(UpperStrEnum):
    BOT = auto()
    WEBCABINET = auto()


class AccessMode(UpperStrEnum):
    PUBLIC = auto()
    INVITED = auto()
    RESTRICTED = auto()


class CaptchaProvider(UpperStrEnum):
    TURNSTILE = auto()
    HCAPTCHA = auto()


class SmtpSecurity(UpperStrEnum):
    STARTTLS = auto()
    TLS = auto()
    NONE = auto()


class SessionAudience(UpperStrEnum):
    DASHBOARD = auto()
    CABINET = auto()


class TransactionStatus(UpperStrEnum):
    PENDING = auto()
    PAID = auto()
    FAILED = auto()
    CANCELED = auto()
    REFUNDED = auto()


class BroadcastStatus(UpperStrEnum):
    DRAFT = auto()
    SCHEDULED = auto()
    SENDING = auto()
    COMPLETED = auto()
    CANCELED = auto()
    FAILED = auto()


class BroadcastCategory(UpperStrEnum):
    SERVICE = auto()
    MARKETING = auto()


class BroadcastDelivery(UpperStrEnum):
    TELEGRAM = auto()
    EMAIL = auto()
    ALL = auto()


class BroadcastChannel(UpperStrEnum):
    TELEGRAM = auto()
    EMAIL = auto()


class BroadcastRecipientStatus(UpperStrEnum):
    PENDING = auto()
    SENT = auto()
    FAILED = auto()
    BLOCKED = auto()
    CANCELED = auto()
    RECALLED = auto()


class BroadcastMediaType(UpperStrEnum):
    PHOTO = auto()
    VIDEO = auto()
    ANIMATION = auto()
    DOCUMENT = auto()


class BackupKind(UpperStrEnum):
    DATABASE = auto()
    ASSETS = auto()


class BackupRunStatus(UpperStrEnum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELED = auto()


class OAuthProvider(UpperStrEnum):
    GITHUB = auto()
    TELEGRAM = auto()
    OIDC = auto()
    GOOGLE = auto()
    YANDEX = auto()

    @classmethod
    def _missing_(cls, value: object) -> Optional["OAuthProvider"]:
        # path params arrive lowercase ("github"), values are uppercase; only
        # this enum is lenient, the rest of UpperStrEnum stays strict
        return cls.__members__.get(value.upper()) if isinstance(value, str) else None


class Role(IntEnum):
    USER = auto()
    ADMIN = auto()
    OWNER = auto()
    SYSTEM = auto()

    def __str__(self) -> str:
        return self.name

    def includes(self, other: "Role") -> bool:
        return self >= other


class Locale(StrEnum):
    AR = auto()  # Arabic
    AZ = auto()  # Azerbaijani
    BE = auto()  # Belarusian
    BG = auto()  # Bulgarian
    CS = auto()  # Czech
    DA = auto()  # Danish
    DE = auto()  # German
    EL = auto()  # Greek
    EN = auto()  # English
    ES = auto()  # Spanish
    FA = auto()  # Persian
    FI = auto()  # Finnish
    FR = auto()  # French
    HE = auto()  # Hebrew
    HI = auto()  # Hindi
    HU = auto()  # Hungarian
    ID = auto()  # Indonesian
    IT = auto()  # Italian
    JA = auto()  # Japanese
    KK = auto()  # Kazakh
    KO = auto()  # Korean
    MS = auto()  # Malay
    NL = auto()  # Dutch
    NO = auto()  # Norwegian
    PL = auto()  # Polish
    PT = auto()  # Portuguese
    RO = auto()  # Romanian
    RU = auto()  # Russian
    SR = auto()  # Serbian
    SV = auto()  # Swedish
    TG = auto()  # Tajik
    TH = auto()  # Thai
    TR = auto()  # Turkish
    UK = auto()  # Ukrainian
    UZ = auto()  # Uzbek
    VI = auto()  # Vietnamese
    ZH = auto()  # Chinese


class LogLevel(UpperStrEnum):
    CRITICAL = auto()
    FATAL = auto()
    ERROR = auto()
    WARN = auto()
    WARNING = auto()
    INFO = auto()
    DEBUG = auto()
    NOTSET = auto()


class DialogWindowKind(StrEnum):
    SEED = auto()
    CUSTOM = auto()


class DialogFlow(StrEnum):
    MENU = auto()
    PURCHASE = auto()
    RENEWAL = auto()
    CHANGE = auto()
    SUBSCRIPTION = auto()
    PROMOCODE = auto()
    REFERRALS = auto()
    CUSTOM = auto()


class ButtonLinkType(StrEnum):
    ACTION = auto()
    NAVIGATE = auto()
    URL = auto()
    WEB_APP = auto()


class ButtonStyleKind(StrEnum):
    PRIMARY = auto()
    SUCCESS = auto()
    DANGER = auto()
