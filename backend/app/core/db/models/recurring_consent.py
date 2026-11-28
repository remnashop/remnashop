from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import BaseSql
from app.core.db.timestamp import NOW_FUNC


class RecurringConsent(BaseSql):
    __tablename__ = "recurring_consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # the author; survives a merge and the merged account's deletion
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # moves with an account merge
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger())
    event_id: Mapped[Optional[str]] = mapped_column(String(128))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    # the exact text, amounts and timings shown; a hash can't reproduce them
    terms: Mapped[dict[str, Any]]
    accepted_at: Mapped[datetime] = mapped_column(server_default=NOW_FUNC)
    revoked_at: Mapped[Optional[datetime]]
    revoked_channel: Mapped[Optional[str]] = mapped_column(String(16))
    revoked_event_id: Mapped[Optional[str]] = mapped_column(String(128))
    revoked_ip_address: Mapped[Optional[str]] = mapped_column(String(45))
