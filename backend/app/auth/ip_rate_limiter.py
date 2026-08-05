"""Guest IP rate limiter — sliding-window, in-memory, thread-safe.

Only applies to Guest sessions on POST /chat/message.  Authenticated users
(User or Admin) are never checked.

IP extraction priority (behind Cloudflare Tunnel + Caddy):
  1. CF-Connecting-IP  — set by Cloudflare with the real visitor IP; most reliable
  2. X-Forwarded-For   — first value only (may have multiple if chained proxies)
  3. request.client.host — Caddy's loopback address; only used as last resort
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request


def get_real_client_ip(request: "Request") -> str:
    """Return the real client IP behind Cloudflare Tunnel + Caddy."""
    cf_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cf_ip:
        return cf_ip

    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip()

    host = getattr(request.client, "host", None)
    return host or "unknown"


class GuestIPRateLimiter:
    """Sliding-window rate limiter for Guest IPs.

    Stores timestamps per IP in memory.  Old entries are cleaned up lazily
    on every check so memory stays bounded without a background thread.
    """

    def __init__(self, limit_per_hour: int) -> None:
        self._limit = limit_per_hour
        self._window_secs = 3600.0
        self._store: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def is_allowed(self, ip: str) -> bool:
        """Return True if the IP is under the limit; False if it should be blocked."""
        if self._limit <= 0:
            return True

        now = time.monotonic()
        cutoff = now - self._window_secs

        with self._lock:
            timestamps = self._store.get(ip, [])
            # drop timestamps outside the rolling window
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= self._limit:
                self._store[ip] = timestamps
                return False

            timestamps.append(now)
            self._store[ip] = timestamps
            return True


_limiter: GuestIPRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_guest_ip_rate_limiter() -> GuestIPRateLimiter:
    """Return the process-wide singleton, initialised from config on first call."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                from app.settings.config_loader import load_default_config
                cfg = load_default_config()
                limit = int(cfg.get("auth", {}).get("guest_ip_rate_limit_per_hour", 30))
                _limiter = GuestIPRateLimiter(limit)
    return _limiter
