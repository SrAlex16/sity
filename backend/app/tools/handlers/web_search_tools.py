"""Tool handler para búsqueda web via DuckDuckGo HTML."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path
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

# ------------------------------------------------------------------
# SQLite cache
# ------------------------------------------------------------------
CACHE_DB = Path(__file__).parent.parent.parent.parent / "data" / "search_cache.db"
TTL_SHORT = 3_600     # 1 hora  — contenido dinámico
TTL_LONG  = 86_400    # 24 horas — contenido estable
MAX_CACHE_ENTRIES = 500


def _init_cache() -> None:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                query_hash TEXT PRIMARY KEY,
                query      TEXT NOT NULL,
                result     TEXT NOT NULL,
                cached_at  INTEGER NOT NULL,
                ttl        INTEGER NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cached_at ON search_cache(cached_at)"
        )


_init_cache()


def _cache_get(query_hash: str) -> str | None:
    try:
        with sqlite3.connect(CACHE_DB) as conn:
            row = conn.execute(
                "SELECT result, cached_at, ttl FROM search_cache WHERE query_hash = ?",
                (query_hash,),
            ).fetchone()
        if row is None:
            return None
        result, cached_at, ttl = row
        if time.time() - cached_at > ttl:
            return None
        return result
    except Exception:
        return None


def _cache_set(query_hash: str, query: str, result: str, ttl: int) -> None:
    try:
        with sqlite3.connect(CACHE_DB) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_cache
                    (query_hash, query, result, cached_at, ttl)
                VALUES (?, ?, ?, ?, ?)
                """,
                (query_hash, query, result, int(time.time()), ttl),
            )
            count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
            if count > MAX_CACHE_ENTRIES:
                conn.execute(
                    """
                    DELETE FROM search_cache WHERE query_hash IN (
                        SELECT query_hash FROM search_cache
                        ORDER BY cached_at ASC LIMIT ?
                    )
                    """,
                    (count - MAX_CACHE_ENTRIES,),
                )
    except Exception:
        pass  # el caché es opcional, nunca rompe la búsqueda


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text)
    text = re.sub(r"&[a-z]+;", lambda m: _ENTITY_MAP.get(m.group(0), m.group(0)), text)
    return text.strip()


# ------------------------------------------------------------------
# Handler
# ------------------------------------------------------------------
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

    is_dynamic: bool = bool(ctx.tool_input.get("is_dynamic", False))
    ttl = TTL_SHORT if is_dynamic else TTL_LONG
    query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]

    cached = _cache_get(query_hash)
    if cached is not None:
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=True,
            message="web_search cache hit",
            updated_parameters=[],
            raw_result={"success": True, "query": query, "text": cached},
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

        _cache_set(query_hash, query, text, ttl)

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
