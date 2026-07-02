from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from elevenlabs import save as elevenlabs_save

from app.memory.db import get_session
from app.memory.models import Episode, NewsItem


@dataclass
class ContentActionResult:
    ok: bool
    text: str


def execute_content_action(payload: dict[str, Any]) -> ContentActionResult:
    action = payload.get("action")
    if action == "select_news":
        return _execute_select_news(payload)
    if action == "generate_script":
        return _execute_generate_script(payload)
    if action == "generate_tts":
        return _execute_generate_tts(payload)
    return ContentActionResult(ok=False, text=f"Acción desconocida: {action}")


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)


def _execute_select_news(payload: dict[str, Any]) -> ContentActionResult:
    from sqlmodel import select as sql_select

    session = next(get_session())
    news_ids = payload.get("news_ids", [])
    status = payload.get("status", "selected")
    updated = 0
    for nid in news_ids:
        item = session.exec(sql_select(NewsItem).where(NewsItem.id == nid)).first()
        if item:
            item.status = status
            updated += 1
    session.commit()
    return ContentActionResult(ok=True, text=f"{updated} noticia(s) marcadas como '{status}'.")


def _execute_generate_script(payload: dict[str, Any]) -> ContentActionResult:
    import anthropic
    from docx import Document
    from docx.shared import Pt  # noqa: F401
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from sqlmodel import select as sql_select

    full_prompt = payload.get("full_prompt", "")
    news_ids = payload.get("news_ids", [])
    output_dir = Path(payload.get("output_dir", "work/canal/guiones"))

    session = next(get_session())
    date_str = datetime.now().strftime("%Y-%m-%d")
    episode = Episode(status="draft")
    session.add(episode)
    session.flush()
    ep_id = episode.id
    ep_label = f"EP{ep_id:03d}"
    docx_path = output_dir / f"{ep_label}-{date_str}.docx"

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": full_prompt}],
    )
    first_block = response.content[0]
    script_text: str = first_block.text if hasattr(first_block, "text") else ""  # type: ignore[union-attr]

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()

    title_para = doc.add_heading(f"GUION — Sity Canal · {ep_label}", 0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    doc.add_paragraph()

    for line in script_text.split("\n"):
        if line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.strip():
            p = doc.add_paragraph(line)
            if "[NOTA PRODUCCIÓN:" in line:
                for run in p.runs:
                    run.italic = True
        else:
            doc.add_paragraph()

    doc.save(str(docx_path))

    episode.script_path = str(docx_path)
    episode.status = "script_ready"

    for nid in news_ids:
        item = session.exec(sql_select(NewsItem).where(NewsItem.id == nid)).first()
        if item:
            item.status = "used"
            item.episode_id = ep_id
    session.commit()

    return ContentActionResult(
        ok=True,
        text=(
            f"Guion generado: {ep_label}\n"
            f"Archivo: {docx_path}\n"
            f"{len(news_ids)} noticia(s) vinculadas al episodio.\n"
            f"Abre el archivo para revisarlo antes de continuar."
        ),
    )


def _execute_generate_tts(payload: dict[str, Any]) -> ContentActionResult:
    from elevenlabs.client import ElevenLabs
    from elevenlabs.types import VoiceSettings
    from docx import Document
    from sqlmodel import select as sql_select

    episode_id = payload.get("episode_id")
    script_path = Path(payload.get("script_path", ""))
    audio_path = Path(payload.get("audio_path", ""))

    if not script_path.exists():
        return ContentActionResult(ok=False, text=f"No se encontró el guion en {script_path}")

    doc = Document(str(script_path))
    narrable_lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if text.startswith("[NOTA PRODUCCIÓN") or text.startswith("*[NOTA"):
            continue
        if text.startswith("GUION") or text.startswith("Generado:"):
            continue
        if para.style and para.style.name.startswith("Heading"):
            continue
        narrable_lines.append(text)

    full_text = "\n".join(narrable_lines)
    if not full_text.strip():
        return ContentActionResult(ok=False, text="El guion no tiene texto narrable extraíble.")

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "")
    if not api_key or not voice_id:
        return ContentActionResult(ok=False, text="Faltan ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID en .env")

    try:
        client = ElevenLabs(api_key=api_key)
        audio = client.text_to_speech.convert(
            voice_id=voice_id,
            text=full_text,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
        )
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        elevenlabs_save(audio, str(audio_path))
    except Exception as e:
        return ContentActionResult(ok=False, text=f"Error llamando a ElevenLabs: {e}")

    session = next(get_session())
    episode = session.exec(sql_select(Episode).where(Episode.id == episode_id)).first()
    if episode:
        episode.audio_path = str(audio_path)
        episode.status = "audio_ready"
        session.add(episode)
        session.commit()

    size_mb = audio_path.stat().st_size / (1024 * 1024)
    return ContentActionResult(
        ok=True,
        text=(
            f"Audio generado: {audio_path}\n"
            f"Tamaño: {size_mb:.1f} MB\n"
            f"Episodio actualizado a status='audio_ready'.\n"
            f"Escucha el archivo antes de continuar."
        ),
    )
