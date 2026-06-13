"""Telegram bot adapter for Sity.

Runs as a standalone process (not part of the FastAPI app):

    python -m app.messaging.telegram_adapter

Reads TELEGRAM_BOT_TOKEN from the environment (.env is loaded automatically
because the working directory is the backend folder with python-dotenv).
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.messaging.gateway import SityGateway
from app.messaging.models import TelegramConfig, is_rate_limited, load_telegram_config
from app.trace.logger import write_log

logging.basicConfig(level=logging.INFO)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "telegram.yaml"

_VALID_PRESETS = {"normal_use", "demo_session", "debug_test"}

_HELP_TEXT = (
    "Comandos disponibles:\n\n"
    "/start — Saludo inicial\n"
    "/help — Esta lista\n"
    "/preset <modo> — Cambia preset de captura de dataset\n"
    "  Modos: normal_use, demo_session, debug_test\n"
    "/defaults — Restaura personalidad a valores canónicos\n"
    "/status — Muestra preset activo y tokens usados hoy"
)

_RATE_LIMIT_MSG = "Demasiados mensajes en poco tiempo. Espera un momento."


# ---------------------------------------------------------------------------
# Pure async handlers — decoupled from Telegram types so they are testable
# ---------------------------------------------------------------------------

async def handle_start(
    *,
    cfg: TelegramConfig,
    chat_id: int,
    chat_type: str,
    reply: Callable,
) -> None:
    if chat_type != "private" or chat_id not in cfg.allowed_chat_ids:
        return
    await reply("Hola. Soy Sity. ¿En qué te ayudo?")


async def handle_help(
    *,
    cfg: TelegramConfig,
    chat_id: int,
    chat_type: str,
    reply: Callable,
) -> None:
    if chat_type != "private" or chat_id not in cfg.allowed_chat_ids:
        return
    await reply(_HELP_TEXT)


async def handle_preset(
    *,
    cfg: TelegramConfig,
    gateway: SityGateway,
    chat_id: int,
    chat_type: str,
    args: list[str],
    reply: Callable,
) -> None:
    if chat_type != "private" or chat_id not in cfg.allowed_chat_ids:
        return
    if not args or args[0] not in _VALID_PRESETS:
        await reply(f"Uso: /preset <modo>\nModos válidos: {', '.join(sorted(_VALID_PRESETS))}")
        return
    source = args[0]
    try:
        await gateway.set_preset(source)
        await reply(f"Preset cambiado a: {source}")
        write_log(
            level="AUDIT", module="telegram", event="preset_changed",
            payload={"chat_id": chat_id, "source": source},
        )
    except Exception as exc:
        await reply("Error al cambiar preset. Revisa el backend.")
        write_log(
            level="ERROR", module="telegram", event="preset_error",
            payload={"chat_id": chat_id, "error": str(exc)},
        )


async def handle_defaults(
    *,
    cfg: TelegramConfig,
    gateway: SityGateway,
    chat_id: int,
    chat_type: str,
    reply: Callable,
) -> None:
    if chat_type != "private" or chat_id not in cfg.allowed_chat_ids:
        return
    try:
        await gateway.reset_personality()
        await reply("Personalidad restaurada a valores canónicos.")
        write_log(
            level="AUDIT", module="telegram", event="personality_reset",
            payload={"chat_id": chat_id},
        )
    except Exception as exc:
        await reply("Error al restaurar personalidad.")
        write_log(
            level="ERROR", module="telegram", event="defaults_error",
            payload={"chat_id": chat_id, "error": str(exc)},
        )


async def handle_status(
    *,
    cfg: TelegramConfig,
    gateway: SityGateway,
    chat_id: int,
    chat_type: str,
    reply: Callable,
) -> None:
    if chat_type != "private" or chat_id not in cfg.allowed_chat_ids:
        return
    try:
        capture = await gateway.get_capture_status()
        tokens = await gateway.get_daily_tokens()
        preset = capture.get("dataset_source", "?")
        enabled = capture.get("enabled", False)
        state = "activo" if enabled else "inactivo"
        await reply(f"Preset: {preset} ({state})\nTokens hoy: {tokens:,}")
    except Exception as exc:
        await reply("Error obteniendo estado.")
        write_log(
            level="ERROR", module="telegram", event="status_error",
            payload={"chat_id": chat_id, "error": str(exc)},
        )


async def handle_chat_message(
    *,
    cfg: TelegramConfig,
    gateway: SityGateway,
    rate_buckets: dict[int, deque[float]],
    chat_id: int,
    chat_type: str,
    text: str,
    username: str,
    reply: Callable,
) -> None:
    if chat_type != "private" or chat_id not in cfg.allowed_chat_ids:
        return
    if is_rate_limited(rate_buckets, chat_id, cfg.rate_limit_per_minute):
        await reply(_RATE_LIMIT_MSG)
        return
    if cfg.log_incoming:
        write_log(
            level="AUDIT", module="telegram", event="incoming",
            payload={"chat_id": chat_id, "user": username, "text": text},
        )
    try:
        response = await gateway.send_message(text)
    except Exception as exc:
        await reply("Error al contactar el backend de Sity.")
        write_log(
            level="ERROR", module="telegram", event="backend_error",
            payload={"chat_id": chat_id, "error": str(exc)},
        )
        return
    reply_text = response.get("text") or "…"
    if cfg.log_outgoing:
        usage: dict[str, Any] = response.get("usage") or {}
        write_log(
            level="AUDIT", module="telegram", event="outgoing",
            payload={
                "chat_id": chat_id,
                "trace_id": response.get("trace_id"),
                "tokens": usage.get("total_tokens", 0),
            },
        )
    await reply(reply_text)


# ---------------------------------------------------------------------------
# Telegram Application factory
# ---------------------------------------------------------------------------

def _build_app(cfg: TelegramConfig, gateway: SityGateway, token: str) -> Application:
    rate_buckets: dict[int, deque[float]] = defaultdict(deque)

    async def _cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await handle_start(
            cfg=cfg, chat_id=update.message.chat_id,
            chat_type=update.message.chat.type, reply=update.message.reply_text,
        )

    async def _cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await handle_help(
            cfg=cfg, chat_id=update.message.chat_id,
            chat_type=update.message.chat.type, reply=update.message.reply_text,
        )

    async def _cmd_preset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await handle_preset(
            cfg=cfg, gateway=gateway,
            chat_id=update.message.chat_id, chat_type=update.message.chat.type,
            args=list(ctx.args or []), reply=update.message.reply_text,
        )

    async def _cmd_defaults(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await handle_defaults(
            cfg=cfg, gateway=gateway,
            chat_id=update.message.chat_id, chat_type=update.message.chat.type,
            reply=update.message.reply_text,
        )

    async def _cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        await handle_status(
            cfg=cfg, gateway=gateway,
            chat_id=update.message.chat_id, chat_type=update.message.chat.type,
            reply=update.message.reply_text,
        )

    async def _msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.message.text is None:
            return
        user = update.effective_user
        await handle_chat_message(
            cfg=cfg, gateway=gateway, rate_buckets=rate_buckets,
            chat_id=update.message.chat_id, chat_type=update.message.chat.type,
            text=update.message.text,
            username=(user.username if user else None) or str(update.message.chat_id),
            reply=update.message.reply_text,
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("preset", _cmd_preset))
    app.add_handler(CommandHandler("defaults", _cmd_defaults))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _msg))
    return app


def main() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")
    cfg = load_telegram_config(_CONFIG_PATH)
    if not cfg.enabled:
        write_log(
            level="INFO", module="telegram", event="disabled",
            payload={"reason": "enabled: false in config/telegram.yaml"},
        )
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")
    gateway = SityGateway()
    write_log(
        level="INFO", module="telegram", event="startup",
        payload={"allowed_chat_ids": cfg.allowed_chat_ids},
    )
    app = _build_app(cfg, gateway, token)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
