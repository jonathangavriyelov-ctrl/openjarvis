"""Phone bridge from Telegram or Slack to the chief of staff.

Telegram is the preferred channel. Slack is enabled because OpenJarvis
already has a Slack channel. An empty allow-list denies everyone, including
when a bot token is present. Tokens never appear in the status payload.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _split_ids(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split(",") if part.strip())


@dataclass(slots=True)
class PhoneGate:
    """Who is allowed to command the chief of staff from a phone."""

    telegram_chat_ids: tuple[str, ...] = ()
    slack_user_ids: tuple[str, ...] = ()

    def allows(self, channel: str, identity: str) -> bool:
        identity = (identity or "").strip()
        if channel == "telegram":
            allowed = self.telegram_chat_ids
        elif channel == "slack":
            allowed = self.slack_user_ids
        else:
            return False
        if not allowed or not identity:
            return False
        return identity in allowed

    def reply_for(
        self,
        office: Any,
        channel: str,
        identity: str,
        text: str,
    ) -> str | None:
        """Run a mission for an allowed chat and return a same-chat reply."""
        if not self.allows(channel, identity):
            return None
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        detail = office.run_mission(cleaned)
        summary = (detail.get("summary") or "").strip()
        if not summary:
            summary = "The chief of staff finished with nothing to report."
        return summary[:3500]


def resolve_phone_gate(
    telegram_chat_id: str = "",
    slack_user_id: str = "",
) -> PhoneGate:
    """Env allow-lists win over config values."""
    telegram = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not telegram:
        telegram = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not telegram:
        telegram = telegram_chat_id or ""
    slack = os.environ.get("SLACK_ALLOWED_USER_ID", "").strip() or (slack_user_id or "")
    return PhoneGate(
        telegram_chat_ids=_split_ids(telegram),
        slack_user_ids=_split_ids(slack),
    )


def describe_phone(
    gate: PhoneGate,
    *,
    telegram_token_set: bool,
    slack_token_set: bool,
    telegram_listening: bool,
    slack_listening: bool,
    notes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Status safe to show in the dashboard. No tokens and no chat ids."""
    notes = notes or {}
    return {
        "telegram": _one(
            "Telegram",
            token_set=telegram_token_set,
            restricted=bool(gate.telegram_chat_ids),
            listening=telegram_listening,
            note=notes.get("telegram") or "",
            missing_allow="chat id",
        ),
        "slack": _one(
            "Slack",
            token_set=slack_token_set,
            restricted=bool(gate.slack_user_ids),
            listening=slack_listening,
            note=notes.get("slack") or "",
            missing_allow="user id",
        ),
    }


def _one(
    name: str,
    *,
    token_set: bool,
    restricted: bool,
    listening: bool,
    note: str,
    missing_allow: str,
) -> dict[str, Any]:
    if note:
        detail = note
    elif listening:
        detail = f"{name} is on, and only your chat can use it."
    elif token_set and restricted:
        detail = f"{name} is configured for your chat."
    elif token_set:
        detail = f"{name} has a token, but no {missing_allow} is set, so it stays off."
    elif restricted:
        detail = f"Your {name} {missing_allow} is set. Add the bot token to turn it on."
    else:
        detail = f"{name} is not connected."
    return {
        "ready": bool(token_set and restricted),
        "restricted": restricted,
        "listening": listening,
        "detail": detail,
    }


def start_phone(
    office: Any,
    *,
    telegram_token: str = "",
    slack_bot_token: str = "",
    slack_app_token: str = "",
    telegram_factory: Any = None,
    slack_factory: Any = None,
) -> dict[str, Any]:
    """Listen only when a token and an allow-list are both set.

    A missing ``python-telegram-bot`` or ``slack-sdk`` install is logged and
    ignored so the desk still starts.
    """
    if getattr(office, "_phone_started", False):
        return office.phone_status()
    office._phone_started = True
    office._telegram_token = telegram_token or ""
    office._slack_token = slack_bot_token or ""
    office._slack_app_token = slack_app_token or ""
    _listen_telegram(office, telegram_factory)
    _listen_slack(office, slack_factory)
    return office.phone_status()


def _listen_telegram(office: Any, factory: Any) -> None:
    if not office._telegram_token or not office.phone.telegram_chat_ids:
        return
    channel_cls = factory
    if channel_cls is None:
        try:
            import telegram.ext  # noqa: F401

            from openjarvis.channels.telegram import TelegramChannel

            channel_cls = TelegramChannel
        except ImportError:
            office._phone_notes["telegram"] = (
                "python-telegram-bot is not installed, so Telegram stays off."
            )
            logger.info("Telegram phone bridge skipped: python-telegram-bot missing")
            return
    channel = channel_cls(
        office._telegram_token,
        allowed_chat_ids=",".join(office.phone.telegram_chat_ids),
        parse_mode="",
    )

    def handler(message: Any, bound: Any = channel) -> None:
        reply = office.phone.reply_for(
            office,
            "telegram",
            getattr(message, "conversation_id", ""),
            getattr(message, "content", ""),
        )
        if reply:
            bound.send(getattr(message, "conversation_id", ""), reply)

    channel.on_message(handler)
    channel.connect()
    office._phone_channels["telegram"] = channel
    office._phone_listening["telegram"] = True


def _listen_slack(office: Any, factory: Any) -> None:
    if not office._slack_token or not office.phone.slack_user_ids:
        return
    channel_cls = factory
    if channel_cls is None:
        try:
            import slack_sdk  # noqa: F401

            from openjarvis.channels.slack import SlackChannel

            channel_cls = SlackChannel
        except ImportError:
            office._phone_notes["slack"] = (
                "slack-sdk is not installed, so Slack stays off."
            )
            logger.info("Slack phone bridge skipped: slack-sdk missing")
            return
    channel = channel_cls(
        office._slack_token,
        app_token=office._slack_app_token,
    )

    def handler(message: Any, bound: Any = channel) -> None:
        reply = office.phone.reply_for(
            office,
            "slack",
            getattr(message, "sender", ""),
            getattr(message, "content", ""),
        )
        if reply:
            bound.send(getattr(message, "conversation_id", "") or "slack", reply)

    channel.on_message(handler)
    channel.connect()
    office._phone_channels["slack"] = channel
    office._phone_listening["slack"] = True
