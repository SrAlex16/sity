"""Tool handler para búsqueda web via DuckDuckGo HTML."""
from __future__ import annotations

import re
from urllib.parse import unquote

import httpx

from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_DDG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
}
_SNIPPET_RE = re.compile(r'<a class="result__snippet" href="([^"]*)">(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_MAP = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'"}


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = re.sub(r"&[a-z]+;", lambda m: _ENTITY_MAP.get(m.group(0), m.group(0)), text)
    return text.strip()


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
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.post(
                _DDG_HTML_URL,
                data={"q": query, "kl": "es-es"},
                headers=_DDG_HEADERS,
            )
            resp.raise_for_status()
            html = resp.text

        matches = _SNIPPET_RE.findall(html)

        results: list[str] = []
        for url, snippet in matches:
            snippet_clean = _clean(snippet)
            if not snippet_clean or "y.js" in url:
                continue
            results.append(f"- {snippet_clean}\n  {url}")
            if len(results) >= 5:
                break

        if not results:
            text = "No se encontraron resultados."
        else:
            text = f"Resultados para '{query}':\n\n" + "\n\n".join(results)

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
