# ADR-0001: Backend as Single Authority for Actions / Backend como Autoridad Única

[English](#english) · [Español](#español)

**Status:** Accepted  
**Date:** 2026-05

---

## English

## Context

Sity has access to external services (Google, Spotify, Home Assistant, filesystem, git) and system-level capabilities. The language model can be prompted, manipulated via injected content, or hallucinate tool calls. Without a clear authority boundary, the model could take actions the user didn't intend.

Early development showed the model would occasionally describe actions it had "taken" without actually executing them, or claim capabilities it didn't have.

## Decision

The backend is the **single source of truth for all actions**. The model proposes; the backend validates and executes. No action reaches the outside world without passing through backend authorization.

Specifically:
- Tools are defined in the backend, not in the model's imagination
- The model cannot invoke a tool that hasn't been registered and scoped to its role
- Destructive or irreversible actions require a two-step confirmation (propose → confirm with exact phrase)
- Unknown tool invocations produce a generic error message, not execution

## Rationale

- **Prevents capability fabrication**: if a tool doesn't exist in the backend, it cannot be executed regardless of what the model claims
- **Role enforcement**: toolsets are assembled per session role before the prompt is constructed
- **Auditability**: all tool calls go through `tool_executor.py` which logs every invocation
- **User control**: for destructive actions, the user sees the proposed plan before any real-world effect

## Consequences

- Slightly more backend complexity (three authorization layers)
- Model-proposed tools that don't exist produce a recoverable error rather than silent failure
- The cognitive pipeline can propose actions through Decision, but they still flow through the executor

## References

- `backend/app/chat/tool_executor.py`
- Security overview: [security/overview.md](../security/overview.md)
- Response integrity: `backend/app/chat/response_integrity.py` (commit `dc4e7a4`)

---

## Español

## Contexto

Sity tiene acceso a servicios externos y capacidades de nivel de sistema. Sin un límite claro de autoridad, el modelo podría tomar acciones que el usuario no pretendía. En el desarrollo temprano, el modelo ocasionalmente describía acciones que había "tomado" sin ejecutarlas realmente.

## Decisión

El backend es la **fuente de verdad única para todas las acciones**. El modelo propone; el backend valida y ejecuta. Ninguna acción llega al mundo exterior sin pasar por la autorización del backend.

## Justificación

- Previene fabricación de capacidades
- Aplica roles de forma determinista
- Auditabilidad completa
- Las acciones destructivas requieren confirmación explícita del usuario

## Consecuencias

Ligera complejidad adicional en el backend (tres capas de autorización). Los tools propuestos por el modelo que no existen producen un error recuperable.
