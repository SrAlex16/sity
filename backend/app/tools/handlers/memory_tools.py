from __future__ import annotations

from app.memory.recall import MemoryFragment, MemoryRecallResult, MemoryRecallRunner
from app.memory.search import MessageContext
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

_ROLE_LABEL = {"user": "Usuario", "sity": "Sity"}


def _fmt_ts(dt) -> str:
    if dt is None:
        return ""
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)


def _fmt_ctx(label: str, ctx: MessageContext) -> str:
    who = _ROLE_LABEL.get(ctx.role, ctx.role)
    ts = _fmt_ts(ctx.created_at)
    return f"  [{label}] {who} ({ts}): {ctx.text}"


def _fmt_fragment(i: int, f: MemoryFragment) -> str:
    mid = f"msg #{f.message_id}" if f.message_id is not None else "msg"
    ts = _fmt_ts(f.timestamp)
    who = _ROLE_LABEL.get(f.role, f.role)

    lines = [f"Fragmento {i} [{mid}, {ts}]:"]
    if f.prev:
        lines.append(_fmt_ctx("anterior", f.prev))
    lines.append(f"  [coincidencia] {who}: {f.text}")
    if f.next:
        lines.append(_fmt_ctx("siguiente", f.next))
    return "\n".join(lines)


def _fmt_recall_result(r: MemoryRecallResult) -> str:
    queries_str = ", ".join(f'"{q}"' for q in r.queries_tried)
    lines = [
        "Memoria recuperada:",
        f"status: {r.status}",
        f"confidence: {r.result_confidence:.2f}",
        f"queries: [{queries_str}]",
        "",
    ]

    if r.fragments:
        lines.append("Evidencia:")
        for i, f in enumerate(r.fragments, 1):
            lines.append(_fmt_fragment(i, f))
            lines.append("")
    else:
        lines.append("Evidencia:")
        lines.append("Sin resultados.")
        lines.append("")

    lines.append(f"Resumen: {r.evidence_summary}")
    if r.windows_read:
        anchors = ", ".join(f"#{a}" for a in r.anchor_message_ids)
        lines.append(f"(Ventanas de contexto leídas: {r.windows_read}, anclas: {anchors})")
    if r.truncated:
        lines.append("(Resultados truncados al límite máximo.)")

    return "\n".join(lines)


@tool_handler("search_conversation_history")
def handle_search_conversation_history(ctx: ToolContext) -> ToolExecutionResult:
    query = str(ctx.tool_input.get("query", "")).strip()
    trace_id = ctx.trace_id

    if not query:
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=False,
            message="query vacío",
            updated_parameters=[],
            raw_result={"success": False, "text": "No he encontrado nada en el historial sobre eso."},
        )

    result = MemoryRecallRunner().recall(query=query, trace_id=trace_id)
    text = _fmt_recall_result(result)

    return ToolExecutionResult(
        tool_name=ctx.tool_name,
        ok=True,
        message=f"status={result.status}, {len(result.fragments)} fragmento(s).",
        updated_parameters=[],
        raw_result={
            "success": True,
            "query": query,
            "status": result.status,
            "confidence": result.result_confidence,
            "count": len(result.fragments),
            "text": text,
        },
    )
