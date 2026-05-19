from __future__ import annotations

from typing import Any

from app.trace.logger import write_log


FALLBACK_REACTIONS: dict[str, str] = {
    "audio_recording_cancelled": "Cancelado. He parado la grabación de audio.",
    "camera_capture_cancelled": "Cancelado. No he sacado la foto.",
    "audio_recording_finished": "Listo. He grabado el audio.",
    "camera_capture_finished": "Listo. He sacado la foto.",
}


def fallback_micro_reaction(event_type: str) -> str:
    return FALLBACK_REACTIONS.get(event_type, "Hecho.")


def build_micro_reaction_prompt(
    *,
    event_type: str,
    event_description: str,
    personality: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    personality = personality or {}

    style_context = {
        k: personality.get(k)
        for k in (
            "sarcasm_level",
            "rudeness_level",
            "warmth_level",
            "honesty_level",
            "dry_humor_level",
            "melancholy_level",
            "verbosity_level",
            "helpfulness_level",
        )
    }

    system = (
        "Eres Sity. Responde a un evento pequeño del sistema con una sola frase breve. "
        "No uses herramientas. No expliques el sistema. No inventes acciones. "
        "No lo trates como error si el usuario canceló algo voluntariamente. "
        "Mantén tu personalidad según estos parámetros, pero no exageres. "
        "Máximo una frase."
    )

    user = (
        f"Evento: {event_type}\n"
        f"Descripción: {event_description}\n"
        f"Parámetros de personalidad: {style_context}\n\n"
        "Responde con una frase natural y breve."
    )

    messages: list[dict[str, str]] = [{"role": "user", "content": user}]
    return system, messages


def generate_micro_reaction(
    *,
    ai_client: Any,
    event_type: str,
    event_description: str,
    personality: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> str:
    system, messages = build_micro_reaction_prompt(
        event_type=event_type,
        event_description=event_description,
        personality=personality,
    )

    try:
        result = ai_client.generate_micro_reaction(
            messages=messages,
            system=system,
            max_tokens=50,
        )

        text = result.get("text", "").strip()
        input_tokens = result.get("input_tokens", 0)
        output_tokens = result.get("output_tokens", 0)

        write_log(
            level="INFO",
            module="micro_reactions",
            event="micro_reaction_generated",
            trace_id=trace_id or "none",
            payload={
                "event_type": event_type,
                "micro_reaction_tokens_input": input_tokens,
                "micro_reaction_tokens_output": output_tokens,
                "fallback": False,
            },
        )

        if not text:
            return fallback_micro_reaction(event_type)

        if len(text) > 220:
            text = text[:217].rstrip() + "..."

        return text

    except Exception as exc:
        write_log(
            level="WARN",
            module="micro_reactions",
            event="micro_reaction_fallback",
            trace_id=trace_id or "none",
            payload={"event_type": event_type, "error": str(exc), "fallback": True},
        )
        return fallback_micro_reaction(event_type)
