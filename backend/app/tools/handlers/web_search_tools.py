"""Tool handler para búsqueda web via DuckDuckGo."""
from __future__ import annotations

import re

import httpx

from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

_DDG_API_URL = "https://api.duckduckgo.com/"
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@tool_handler("web_search")
def handle_web_search(ctx: ToolContext) -> ToolExecutionResult:
    query = str(ctx.tool_input.get("query", "")).strip()
    if not query:
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=False,
            message="query vacío",
            updated_parameters=[],
            raw_result={"success": False, "text": "No se proporcionó ninguna consulta."},
        )

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                _DDG_API_URL,
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
                headers={"User-Agent": "Sity/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

            results: list[str] = []

            if data.get("AbstractText"):
                results.append(f"Resumen: {data['AbstractText']}")
                if data.get("AbstractURL"):
                    results.append(f"Fuente: {data['AbstractURL']}")

            for item in data.get("RelatedTopics", [])[:3]:
                if isinstance(item, dict) and item.get("Text"):
                    results.append(f"- {item['Text']}")

            if not results:
                resp2 = client.get(
                    _DDG_HTML_URL,
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                snippets = _SNIPPET_RE.findall(resp2.text)
                snippets = [_TAG_RE.sub("", s).strip() for s in snippets[:3]]
                results = snippets if snippets else ["No se encontraron resultados."]

        text = "\n".join(results)
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=True,
            message=f"web_search ok: {len(results)} resultado(s)",
            updated_parameters=[],
            raw_result={"success": True, "query": query, "text": text},
        )

    except Exception as e:
        msg = f"Error al buscar: {e}"
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=False,
            message=msg,
            updated_parameters=[],
            raw_result={"success": False, "text": msg},
        )
