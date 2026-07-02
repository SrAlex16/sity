from __future__ import annotations

import feedparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from app.actions.confirmation_manager import ConfirmationManager
from app.memory.db import get_session
from app.memory.models import Episode, NewsItem
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


@tool_handler("list_news")
def handle_list_news(ctx: ToolContext) -> ToolExecutionResult:
    from sqlmodel import col, select as sql_select

    status = str(ctx.tool_input.get("status", "pending"))
    limit = min(int(ctx.tool_input.get("limit", 30)), 100)

    session = next(get_session())
    items = session.exec(
        sql_select(NewsItem)
        .where(NewsItem.status == status)
        .order_by(col(NewsItem.created_at).desc())
        .limit(limit)
    ).all()

    if not items:
        msg = f"No hay noticias con status='{status}'."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    lines = [
        f"[{i + 1}] ID:{n.id} | {n.title} | {n.source} ({n.category})"
        for i, n in enumerate(items)
    ]
    output = f"{len(items)} noticia(s) con status='{status}':\n\n" + "\n".join(lines)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
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

    news_items_text = "\n\n".join(
        f"Noticia {i + 1}: {n.title}\n"
        f"Fuente: {n.source} ({n.category})\n"
        f"Resumen: {n.summary or 'Sin resumen disponible'}\n"
        f"URL: {n.url}"
        for i, n in enumerate(selected)
    )

    cfg = _load_canal_config()
    output_dir = Path(cfg.get("settings", {}).get("output", {}).get("guiones", "work/canal/guiones"))
    if not output_dir.is_absolute():
        output_dir = _PROJECT_ROOT / output_dir
    date_str = datetime.now().strftime("%Y-%m-%d")

    payload: dict[str, Any] = {
        "action": "generate_script",
        "news_ids": [n.id for n in selected],
        "output_dir": str(output_dir),
        "news_items_text": news_items_text,
    }
    dedup_payload: dict[str, Any] = {
        "action": "generate_script",
        "news_ids": [n.id for n in selected],
    }
    manager = ConfirmationManager(ctx.executor.session)

    existing_result = _pending_action_existing(manager, ctx, dedup_payload, action_type="content")
    if existing_result:
        return existing_result

    summary = f"Generar guion largo + shorts de EP nuevo con {len(selected)} noticia(s)"

    created = manager.create_pending_action(
        action_type="content",
        risk_level="safe_confirm",
        summary=summary,
        payload=payload,
        trace_id=ctx.trace_id,
    )
    local_text = (
        f"Acción pendiente creada: {created.summary}\n"
        f"Se generarán DOS archivos:\n"
        f"  • EP[N]-largo-{date_str}.docx\n"
        f"  • EP[N]-shorts-{date_str}.docx\n\n"
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


@tool_handler("list_episodes")
def handle_list_episodes(ctx: ToolContext) -> ToolExecutionResult:
    from sqlmodel import col, select as sql_select

    session = next(get_session())
    episodes = session.exec(
        sql_select(Episode).order_by(col(Episode.id).desc()).limit(20)
    ).all()

    if not episodes:
        msg = "No hay episodios todavía."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    lines = [
        f"EP{ep.id:03d} | {ep.title or '(sin título)'} | {ep.status} | {str(ep.created_at)[:10]}"
        for ep in episodes
    ]
    output = f"{len(episodes)} episodio(s):\n\n" + "\n".join(lines)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("generate_images")
def handle_generate_images(ctx: ToolContext) -> ToolExecutionResult:
    import re
    from sqlmodel import col, select as sql_select

    session = next(get_session())
    raw_episode_id = ctx.tool_input.get("episode_id")

    if raw_episode_id is not None:
        episode = session.exec(
            sql_select(Episode).where(Episode.id == int(raw_episode_id))
        ).first()
    else:
        episode = session.exec(
            sql_select(Episode)
            .where(col(Episode.status).in_(["audio_ready", "script_ready"]))
            .order_by(col(Episode.id).desc())
        ).first()

    if not episode:
        msg = "No hay episodios con guion o audio listo."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    ep_label = f"EP{episode.id:03d}"
    timestamps_dir = _PROJECT_ROOT / "work" / "canal" / "guiones" / "timestamps"
    transcript_path = timestamps_dir / f"{ep_label}.txt"
    assets_dir = _PROJECT_ROOT / "work" / "canal" / "assets" / ep_label

    if not transcript_path.exists():
        msg = (
            f"No se encontró la transcripción en {transcript_path}.\n"
            f"Guarda el archivo de timestamps en "
            f"work/canal/guiones/timestamps/{ep_label}.txt"
        )
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    transcript_text = transcript_path.read_text(encoding="utf-8")
    timestamps = re.findall(r'\(\d+:\d+\)', transcript_text)
    n_images = len(timestamps)

    if n_images == 0:
        msg = (
            "No se encontraron timestamps en la transcripción. "
            "Formato esperado: (0:00) texto..."
        )
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    payload: dict[str, Any] = {
        "action": "generate_images",
        "episode_id": episode.id,
        "transcript_path": str(transcript_path),
        "assets_dir": str(assets_dir),
    }
    dedup_payload: dict[str, Any] = {
        "action": "generate_images",
        "episode_id": episode.id,
    }
    manager = ConfirmationManager(ctx.executor.session)

    existing_result = _pending_action_existing(manager, ctx, dedup_payload, action_type="content")
    if existing_result:
        return existing_result

    summary = (
        f"Generar {n_images} imágenes cyberpunk para {ep_label} "
        f"→ work/canal/assets/{ep_label}/"
    )
    created = manager.create_pending_action(
        action_type="content",
        risk_level="safe_confirm",
        summary=summary,
        payload=payload,
        trace_id=ctx.trace_id,
    )
    local_text = (
        f"Acción pendiente creada: {created.summary}\n"
        f"Transcripción: {transcript_path}\n"
        f"Salida: {assets_dir}/\n"
        f"Esto consumirá créditos de Stability AI "
        f"(~${n_images * 0.065:.2f} estimado con SD3.5).\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result: dict[str, Any] = {
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


@tool_handler("generate_tts")
def handle_generate_tts(ctx: ToolContext) -> ToolExecutionResult:
    from sqlmodel import col, select as sql_select

    session = next(get_session())
    raw_episode_id = ctx.tool_input.get("episode_id")
    script_type = str(ctx.tool_input.get("script_type", "largo"))

    if raw_episode_id is not None:
        episode = session.exec(
            sql_select(Episode).where(Episode.id == int(raw_episode_id))
        ).first()
    else:
        episode = session.exec(
            sql_select(Episode)
            .where(Episode.status == "script_ready")
            .order_by(col(Episode.id).desc())
        ).first()

    if not episode:
        msg = ("No hay episodios con status='script_ready'. "
               "Genera primero el guion con generate_script.")
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    ep_label = f"EP{episode.id:03d}"

    if script_type == "shorts":
        chosen_script = episode.script_shorts_path
        audio_suffix = f"{ep_label}-shorts.mp3"
        type_label = "shorts"
    else:
        chosen_script = episode.script_path
        audio_suffix = f"{ep_label}.mp3"
        type_label = "largo"

    if not chosen_script:
        msg = f"{ep_label} no tiene ruta de guion '{type_label}' registrada."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    cfg = _load_canal_config()
    audio_dir = Path(cfg.get("settings", {}).get("output", {}).get("audio", "work/canal/audio"))
    if not audio_dir.is_absolute():
        audio_dir = _PROJECT_ROOT / audio_dir
    audio_path = audio_dir / audio_suffix

    payload: dict[str, Any] = {
        "action": "generate_tts",
        "episode_id": episode.id,
        "script_path": chosen_script,
        "audio_path": str(audio_path),
        "script_type": script_type,
    }
    dedup_payload: dict[str, Any] = {
        "action": "generate_tts",
        "episode_id": episode.id,
        "script_type": script_type,
    }
    manager = ConfirmationManager(ctx.executor.session)

    existing_result = _pending_action_existing(manager, ctx, dedup_payload, action_type="content")
    if existing_result:
        return existing_result

    summary = f"Generar audio TTS ({type_label}) de {ep_label} → {audio_path.name}"
    local_text_extra = (
        f"\nGuion: {chosen_script}"
        f"\nAudio de salida: {audio_path}"
        f"\nEsto consumirá créditos de ElevenLabs."
    )
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
