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


# ---------------------------------------------------------------------------
# Auth rate limiter — login / register / forgot-password / reset-password
# ---------------------------------------------------------------------------


class AuthRateLimiter:
    """Sliding-window rate limiter for auth endpoints (15-minute window).

    IP counters track ALL attempts (success and failure).
    Email counter tracks only FAILED login attempts; reset on successful login.

    Limits (configurable in default_config.yaml auth section):
      login_ip_limit=20     — all login attempts per IP per 15 min
      login_email_limit=5   — failed login attempts per email per 15 min
      register_ip_limit=10  — register attempts per IP per 15 min
      forgot_ip_limit=5     — forgot-password requests per IP per 15 min
      reset_ip_limit=10     — reset-password attempts per IP per 15 min
    """

    def __init__(
        self,
        *,
        window_secs: float = 900.0,
        login_ip_limit: int = 20,
        login_email_limit: int = 5,
        register_ip_limit: int = 10,
        forgot_ip_limit: int = 5,
        reset_ip_limit: int = 10,
    ) -> None:
        self._window = window_secs
        self._login_ip_limit = login_ip_limit
        self._login_email_limit = login_email_limit
        self._register_ip_limit = register_ip_limit
        self._forgot_ip_limit = forgot_ip_limit
        self._reset_ip_limit = reset_ip_limit
        self._login_ip: dict[str, list[float]] = {}
        self._login_email: dict[str, list[float]] = {}
        self._register_ip: dict[str, list[float]] = {}
        self._forgot_ip: dict[str, list[float]] = {}
        self._reset_ip: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _check_and_record(
        self, store: dict[str, list[float]], key: str, limit: int
    ) -> tuple[bool, int]:
        """Append a timestamp and check the limit. Returns (allowed, retry_after_secs)."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            ts = [t for t in store.get(key, []) if t > cutoff]
            if len(ts) >= limit:
                retry_after = max(1, int(ts[0] + self._window - now) + 1)
                store[key] = ts
                return False, retry_after
            ts.append(now)
            store[key] = ts
            return True, 0

    def _check_only(
        self, store: dict[str, list[float]], key: str, limit: int
    ) -> tuple[bool, int]:
        """Check without appending. Returns (allowed, retry_after_secs)."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            ts = [t for t in store.get(key, []) if t > cutoff]
            store[key] = ts
            if len(ts) >= limit:
                retry_after = max(1, int(ts[0] + self._window - now) + 1)
                return False, retry_after
            return True, 0

    def _append(self, store: dict[str, list[float]], key: str) -> None:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            ts = [t for t in store.get(key, []) if t > cutoff]
            ts.append(now)
            store[key] = ts

    # ------------------------------------------------------------------
    # Login — IP (all attempts) + email (failures only)
    # ------------------------------------------------------------------

    def check_login_ip(self, ip: str) -> tuple[bool, int]:
        """Record attempt and check IP limit. Returns (allowed, retry_after_secs)."""
        return self._check_and_record(self._login_ip, ip, self._login_ip_limit)

    def check_login_email(self, email: str) -> tuple[bool, int]:
        """Check email failure counter without recording. Returns (allowed, retry_after_secs)."""
        return self._check_only(self._login_email, email.lower(), self._login_email_limit)

    def record_login_failure(self, email: str) -> None:
        """Increment failed-login counter for this email."""
        self._append(self._login_email, email.lower())

    def reset_login_email(self, email: str) -> None:
        """Clear the email failure counter after a successful login."""
        with self._lock:
            self._login_email.pop(email.lower(), None)

    # ------------------------------------------------------------------
    # Register, forgot-password, reset-password — IP only
    # ------------------------------------------------------------------

    def check_register_ip(self, ip: str) -> tuple[bool, int]:
        return self._check_and_record(self._register_ip, ip, self._register_ip_limit)

    def check_forgot_ip(self, ip: str) -> tuple[bool, int]:
        return self._check_and_record(self._forgot_ip, ip, self._forgot_ip_limit)

    def check_reset_ip(self, ip: str) -> tuple[bool, int]:
        return self._check_and_record(self._reset_ip, ip, self._reset_ip_limit)


_auth_rate_limiter: AuthRateLimiter | None = None
_auth_rate_limiter_lock = threading.Lock()


def get_auth_rate_limiter() -> AuthRateLimiter:
    """Return the process-wide singleton, initialised from config on first call."""
    global _auth_rate_limiter
    if _auth_rate_limiter is None:
        with _auth_rate_limiter_lock:
            if _auth_rate_limiter is None:
                from app.settings.config_loader import load_default_config
                cfg = load_default_config()
                auth_cfg = cfg.get("auth", {})
                _auth_rate_limiter = AuthRateLimiter(
                    login_ip_limit=int(auth_cfg.get("login_ip_limit", 20)),
                    login_email_limit=int(auth_cfg.get("login_email_limit", 5)),
                    register_ip_limit=int(auth_cfg.get("register_ip_limit", 10)),
                    forgot_ip_limit=int(auth_cfg.get("forgot_ip_limit", 5)),
                    reset_ip_limit=int(auth_cfg.get("reset_ip_limit", 10)),
                )
    return _auth_rate_limiter
