"""
Response guard.

Guards model-generated final text before it is sent to the user.
Does not execute actions and does not validate tool payloads.
Only blocks unsafe or misleading final text patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_VALID_ACTION_ID_RE = re.compile(r"\bact_[a-fA-F0-9]{8}\b")

_PSEUDO_TOOL_CALL_RE = re.compile(
    r"<function_calls>|<invoke\s+name=|</function_calls>|</invoke>",
    re.IGNORECASE,
)

_INVALID_CONFIRMATION_RE = re.compile(
    r"confirmo\s+ejecutar\s+(?!act_[a-fA-F0-9]{8}\b)[`'\"]?([a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)

_BLOCKED_TEXT = (
    "He bloqueado una respuesta inválida: el modelo intentó crear una "
    "confirmación que no existe en el sistema. No se ha creado ninguna "
    "acción pendiente. Repite la petición o hazlo manualmente con Git."
)


@dataclass(frozen=True)
class ResponseGuardResult:
    allowed: bool
    text: str
    reason: str | None = None


class ResponseGuard:
    def validate_final_text(self, text: str) -> ResponseGuardResult:
        if not text:
            return ResponseGuardResult(allowed=True, text=text)

        if "confirmo ejecutar" in text.lower() and not _VALID_ACTION_ID_RE.search(text):
            return ResponseGuardResult(allowed=False, text=_BLOCKED_TEXT, reason="invalid_model_generated_confirmation")

        if _INVALID_CONFIRMATION_RE.search(text):
            return ResponseGuardResult(allowed=False, text=_BLOCKED_TEXT, reason="invalid_model_generated_confirmation")

        if _PSEUDO_TOOL_CALL_RE.search(text):
            return ResponseGuardResult(
                allowed=False,
                text=(
                    "He bloqueado una respuesta inválida: el modelo intentó mostrar una llamada "
                    "a herramienta como texto en vez de ejecutarla realmente. No se ha ejecutado "
                    "ninguna acción. Repite la petición de forma directa o usa la herramienta "
                    "correcta mediante el flujo normal."
                ),
                reason="pseudo_tool_call_in_final_text",
            )

        return ResponseGuardResult(allowed=True, text=text)
