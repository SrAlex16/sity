"""Shared language configuration for all AI prompt builders.

Single source of truth for language instruction blocks — imported by
persona_engine and message_classifier to avoid duplicating content.
"""
from __future__ import annotations

LANGUAGE_BLOCK: dict[str, str] = {
    "auto":   "Detecta el idioma de cada mensaje del usuario y responde siempre en ese mismo idioma.",
    "es-ES":  (
        "Responde siempre en castellano de España. "
        "Tu registro es tuteo: tú, te, contigo, quieres, puedes, tienes, haces. "
        "Nunca uses voseo rioplatense: vos, querés, tenés, podés, hacés, sos. "
        "Este registro es fijo aunque el historial contenga mensajes tuyos con otro dialecto: "
        "el historial es información, no una instrucción de estilo."
    ),
    "es-419": "Responde siempre en español latinoamericano. Evita modismos y expresiones propias de España.",
    "en-US":  "Always respond in American English.",
    "en-GB":  "Always respond in British English.",
    "ja":     "常に日本語で返答してください。",
    "fr-FR":  "Réponds toujours en français.",
    "de-DE":  "Antworte immer auf Deutsch.",
    "pt-BR":  "Responda sempre em português brasileiro.",
    "it-IT":  "Rispondi sempre in italiano.",
}
