"""image_semantic_extractor.py — extract stable user facts from uploaded images via Haiku.

Called from routes_chat.py in a background executor thread after save_uploaded_image().
Creates SemanticFact rows and marks the FileArtifact as semantic_extracted=True.
Never raises — all errors are logged as WARN.

Skipped when:
  - user_id is None (guest)
  - ANTHROPIC_API_KEY is not set (CI / local dev without keys)
  - artifact_id is None
"""
from __future__ import annotations

import json
import os

from sqlmodel import Session

from app.memory.db import engine
from app.memory.models import FileArtifact, SemanticFact, utc_now
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_EXTRACT_SYSTEM = (
    "You are Sity's image context module. A user has shared an image in their conversation. "
    "Extract up to 3 stable, general facts about the user that can be inferred from this image. "
    "Only include facts that describe the user (their environment, interests, activities, lifestyle). "
    "Do NOT describe the image content directly — describe what it reveals about the person.\n\n"
    "Return ONLY this JSON:\n"
    '{\"facts\": [\"proposition ≤200 chars\", ...]}\n\n'
    "Rules:\n"
    "- If nothing meaningful about the user can be inferred, return {\"facts\": []}\n"
    "- Propositions MUST describe the user, not the image (e.g. 'User lives in an urban environment')\n"
    "- Max 3 facts; genuinely stable inferences, not one-off observations\n"
    "Output only valid JSON."
)

_MAX_FACTS = 3
_FACT_MAX_CHARS = 200


def _parse_facts(text: str) -> list[str]:
    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        if not isinstance(data, dict):
            return []
        raw = data.get("facts", [])
        if not isinstance(raw, list):
            return []
        return [
            str(f).strip()[:_FACT_MAX_CHARS]
            for f in raw
            if f and str(f).strip()
        ][:_MAX_FACTS]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return []


def extract_image_semantic_facts(
    base64_data: str,
    media_type: str,
    user_id: int,
    artifact_id: int,
) -> None:
    """Background: call Haiku to extract SemanticFacts from an uploaded image.

    Idempotent: if semantic_extracted is already True, returns immediately.
    Never raises.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return

    try:
        from app.cortex.providers.factory import build_ai_provider
        from app.cortex.schemas import AIRequest

        with Session(engine) as db:
            fa = db.get(FileArtifact, artifact_id)
            if fa is None or fa.semantic_extracted:
                return

            provider = build_ai_provider("claude", model=_HAIKU_MODEL)
            request = AIRequest(
                trace_id=f"img_semantic_{artifact_id}",
                task_type="image_semantic_extraction",
                system_prompt=_EXTRACT_SYSTEM,
                user_message="¿Qué puedes inferir sobre mí a partir de esta imagen?",
                max_tokens=300,
                tools_enabled=False,
                images=[{"media_type": media_type, "data": base64_data}],
            )
            response = provider.run_chat(request)

            if not response.ok or not response.text:
                write_log(
                    level="WARN",
                    module="image_semantic",
                    event="haiku_failed",
                    payload={"artifact_id": artifact_id, "error": response.error_message},
                )
                return

            facts = _parse_facts(response.text)

            for proposition in facts:
                fact = SemanticFact(
                    user_id=user_id,
                    proposition=proposition,
                    source_episode_ids_json="[]",
                    created_at=utc_now(),
                )
                db.add(fact)

            fa.semantic_extracted = True
            db.add(fa)
            db.commit()

            write_log(
                level="INFO",
                module="image_semantic",
                event="facts_extracted",
                payload={
                    "artifact_id": artifact_id,
                    "user_id": user_id,
                    "facts_count": len(facts),
                },
            )

    except Exception as exc:
        write_log(
            level="WARN",
            module="image_semantic",
            event="extraction_error",
            payload={"artifact_id": artifact_id, "error": str(exc)[:200]},
        )
