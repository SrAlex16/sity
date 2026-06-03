from __future__ import annotations

from app.memory.search import search_conversation_history
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


def _fmt_fragment(label: str, role: str, text: str, ts) -> str:
    who = _ROLE_LABEL.get(role, role)
    return f"  [{label}] {who} ({_fmt_ts(ts)}): {text}"


@tool_handler("search_conversation_history")
def handle_search_conversation_history(ctx: ToolContext) -> ToolExecutionResult:
    query = str(ctx.tool_input.get("query", "")).strip()
    limit = int(ctx.tool_input.get("limit", 5))

    if not query:
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=False,
            message="query vacío",
            updated_parameters=[],
            raw_result={"success": False, "text": "No he encontrado nada en el historial sobre eso."},
        )

    results = search_conversation_history(query=query, limit=limit)

    if not results:
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=True,
            message="sin resultados",
            updated_parameters=[],
            raw_result={
                "success": True,
                "query": query,
                "count": 0,
                "text": "No he encontrado nada en el historial sobre eso.",
            },
        )

    fragments: list[str] = []
    for i, r in enumerate(results, 1):
        lines = [f"Fragmento {i}:"]
        if r.prev:
            lines.append(_fmt_fragment("anterior", r.prev.role, r.prev.text, r.prev.created_at))
        lines.append(_fmt_fragment("coincidencia", r.match.role, r.match.text, r.match.created_at))
        if r.next:
            lines.append(_fmt_fragment("siguiente", r.next.role, r.next.text, r.next.created_at))
        fragments.append("\n".join(lines))

    text = "\n\n".join(fragments)

    return ToolExecutionResult(
        tool_name=ctx.tool_name,
        ok=True,
        message=f"{len(results)} fragmento(s) encontrado(s).",
        updated_parameters=[],
        raw_result={
            "success": True,
            "query": query,
            "count": len(results),
            "text": text,
        },
    )
