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
_TITLE_RE = re.compile(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_DDG_URL_RE = re.compile(r"uddg=([^&]+)")


def _clean(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


def _decode_ddg_url(raw: str) -> str:
    m = _DDG_URL_RE.search(raw)
    return unquote(m.group(1)) if m else raw


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

        titles = _TITLE_RE.findall(html)
        snippets = _SNIPPET_RE.findall(html)

        results: list[str] = []
        for i, raw_snippet in enumerate(snippets[:5]):
            snippet = _clean(raw_snippet)
            if not snippet:
                continue
            title = _clean(titles[i][1]) if i < len(titles) else ""
            url = _decode_ddg_url(titles[i][0]) if i < len(titles) else ""
            entry = f"{len(results) + 1}. {title}\n   {snippet}"
            if url:
                entry += f"\n   {url}"
            results.append(entry)

        if not results:
            text = "No se encontraron resultados para esa búsqueda."
            return ToolExecutionResult(
                tool_name=ctx.tool_name,
                ok=True,
                message="web_search ok: 0 resultados",
                updated_parameters=[],
                raw_result={"success": True, "query": query, "text": text},
            )

        text = f"Resultados de búsqueda para '{query}':\n\n" + "\n\n".join(results)
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
