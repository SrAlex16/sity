from __future__ import annotations

import feedparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from app.actions.confirmation_manager import ConfirmationManager
from app.memory.db import get_session
from app.memory.models import NewsItem
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_CONTENT_CONFIG_PATH = _PROJECT_ROOT / "config" / "content_sources.yaml"


def _load_canal_config() -> dict[str, Any]:
    if not _CONTENT_CONFIG_PATH.exists():
        return {}
    with _CONTENT_CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("canal", {}) if isinstance(data, dict) else {}


def _pending_action_existing(manager: ConfirmationManager, ctx: ToolContext, payload: dict, action_type: str) -> ToolExecutionResult | None:
    existing = manager.find_equivalent_pending_action(action_type=action_type, payload=payload)
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        result = {
            "success": True, "message": local_text,
            "action_id": existing.id,
            "confirmation_phrase": existing.confirmation_phrase,
            "summary": existing.summary,
            "already_existed": True,
            "local_final": True, "text": local_text, "local_model": "pending-action-manager",
        }
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=local_text,
            updated_parameters=[], raw_result=result,
        )
    return None


def _pending_action_new(manager: ConfirmationManager, ctx: ToolContext, payload: dict, action_type: str, summary: str) -> ToolExecutionResult:
    created = manager.create_pending_action(
        action_type=action_type,
        risk_level="safe_confirm",
        summary=summary,
        payload=payload,
        trace_id=ctx.trace_id,
    )
    local_text = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result = {
        "success": True, "message": local_text,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "local_final": True, "text": local_text, "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=local_text,
        updated_parameters=[], raw_result=result,
    )


@tool_handler("fetch_rss_news")
def handle_fetch_rss_news(ctx: ToolContext) -> ToolExecutionResult:
    cfg = _load_canal_config()
    feeds = cfg.get("rss_feeds", [])
    days_back = int(cfg.get("settings", {}).get("days_back", 7))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    from sqlmodel import col, select as sql_select

    session = next(get_session())
    added = 0
    skipped = 0
    summary_lines: list[str] = []

    for feed_cfg in feeds:
        name = feed_cfg["name"]
        url = feed_cfg["url"]
        cat = feed_cfg.get("category", "general")

        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            summary_lines.append(f"✗ {name}: error ({e})")
            continue

        feed_added = 0
        for entry in parsed.entries:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                t = entry.published_parsed
                published = datetime(t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=timezone.utc)
            if published and published < cutoff:
                continue

            entry_url = entry.get("link", "")
            if not entry_url:
                continue

            exists = session.exec(sql_select(NewsItem).where(NewsItem.url == entry_url)).first()
            if exists:
                skipped += 1
                continue

            summary_text = entry.get("summary", "")[:500]
            item = NewsItem(
                title=entry.get("title", "Sin título")[:300],
                source=name,
                url=entry_url,
                published_at=published.isoformat() if published else None,
                summary=summary_text,
                category=cat,
                status="pending",
            )
            session.add(item)
            feed_added += 1
            added += 1

        session.commit()
        summary_lines.append(f"✓ {name}: {feed_added} nueva(s)")

    pending = session.exec(
        sql_select(NewsItem).where(NewsItem.status == "pending").order_by(col(NewsItem.created_at).desc()).limit(20)
    ).all()

    news_list = "\n".join(
        f"[{i + 1}] {n.title} ({n.source}, {n.category}) — ID:{n.id}"
        for i, n in enumerate(pending)
    )

    output = (
        f"Ingesta completada: {added} nueva(s), {skipped} duplicada(s).\n"
        + "\n".join(summary_lines)
        + f"\n\nNoticias pendientes de selección ({len(pending)}):\n{news_list}"
    )

    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output, "added": added},
    )


@tool_handler("select_news")
def handle_select_news(ctx: ToolContext) -> ToolExecutionResult:
    news_ids = list(ctx.tool_input.get("news_ids", []))
    action = str(ctx.tool_input.get("action", "selected"))

    if not news_ids:
        msg = "Falta news_ids — lista de IDs de noticias a marcar."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    if action not in ("selected", "discarded"):
        msg = "action debe ser 'selected' o 'discarded'."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    payload: dict[str, Any] = {"action": "select_news", "news_ids": news_ids, "status": action}
    manager = ConfirmationManager(ctx.executor.session)

    existing_result = _pending_action_existing(manager, ctx, payload, action_type="content")
    if existing_result:
        return existing_result

    summary = f"Marcar {len(news_ids)} noticia(s) como '{action}': IDs {news_ids}"
    return _pending_action_new(manager, ctx, payload, action_type="content", summary=summary)


@tool_handler("generate_script")
def handle_generate_script(ctx: ToolContext) -> ToolExecutionResult:
    from sqlmodel import col, select as sql_select

    session = next(get_session())
    selected = session.exec(
        sql_select(NewsItem).where(NewsItem.status == "selected").order_by(col(NewsItem.published_at).desc())
    ).all()

    if not selected:
        msg = "No hay noticias seleccionadas. Usa fetch_rss_news y luego select_news primero."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    news_text = "\n\n".join(
        f"Noticia {i + 1}: {n.title}\n"
        f"Fuente: {n.source} ({n.category})\n"
        f"Resumen: {n.summary or 'Sin resumen disponible'}\n"
        f"URL: {n.url}"
        for i, n in enumerate(selected)
    )

    prompt_path = _PROJECT_ROOT / "config" / "prompts" / "script_prompt.txt"
    prompt_template = prompt_path.read_text(encoding="utf-8")
    full_prompt = prompt_template.replace("{news_items}", news_text)

    cfg = _load_canal_config()
    output_dir = Path(cfg.get("settings", {}).get("output", {}).get("guiones", "work/canal/guiones"))
    if not output_dir.is_absolute():
        output_dir = _PROJECT_ROOT / output_dir
    date_str = datetime.now().strftime("%Y-%m-%d")
    docx_path = output_dir / f"{date_str}.docx"

    payload: dict[str, Any] = {
        "action": "generate_script",
        "news_ids": [n.id for n in selected],
        "docx_path": str(docx_path),
        "full_prompt": full_prompt,
    }
    dedup_payload: dict[str, Any] = {
        "action": "generate_script",
        "news_ids": [n.id for n in selected],
    }
    manager = ConfirmationManager(ctx.executor.session)

    existing_result = _pending_action_existing(manager, ctx, dedup_payload, action_type="content")
    if existing_result:
        return existing_result

    summary = f"Generar guion con {len(selected)} noticia(s) → {docx_path.name}"
    local_text_extra = f"\nSe guardará en: {docx_path}"

    created = manager.create_pending_action(
        action_type="content",
        risk_level="safe_confirm",
        summary=summary,
        payload=payload,
        trace_id=ctx.trace_id,
    )
    local_text = (
        f"Acción pendiente creada: {created.summary}"
        f"{local_text_extra}\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result = {
        "success": True, "message": local_text,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "local_final": True, "text": local_text, "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=local_text,
        updated_parameters=[], raw_result=result,
    )
