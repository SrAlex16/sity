from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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
