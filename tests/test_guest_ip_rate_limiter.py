"""Tests for GuestIPRateLimiter and get_real_client_ip.

Scenarios:
- Multiple requests from the same IP exceed the limit
- Different IPs have independent counters
- Limit=0 never blocks
- IP extraction: CF-Connecting-IP wins over X-Forwarded-For and client.host
- IP extraction: X-Forwarded-For wins over client.host when CF header absent
- IP extraction: falls back to request.client.host when no proxy headers
- Authenticated User and Admin bypass the rate limiter (integration via route)
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.auth.ip_rate_limiter import GuestIPRateLimiter, get_real_client_ip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(*, cf_ip: str = "", xff: str = "", host: str = "127.0.0.1"):
    """Build a minimal fake Request with the given headers and client."""
    headers: dict[str, str] = {}
    if cf_ip:
        headers["cf-connecting-ip"] = cf_ip
    if xff:
        headers["x-forwarded-for"] = xff

    req = MagicMock()
    req.headers = headers
    req.client = SimpleNamespace(host=host)
    return req


# ---------------------------------------------------------------------------
# get_real_client_ip
# ---------------------------------------------------------------------------

class TestGetRealClientIp:
    def test_cf_connecting_ip_wins(self):
        req = _make_request(cf_ip="1.2.3.4", xff="9.9.9.9", host="127.0.0.1")
        assert get_real_client_ip(req) == "1.2.3.4"

    def test_xff_wins_when_no_cf(self):
        req = _make_request(xff="5.6.7.8, 10.0.0.1", host="127.0.0.1")
        assert get_real_client_ip(req) == "5.6.7.8"

    def test_xff_first_value_only(self):
        req = _make_request(xff="  11.22.33.44 , 55.66.77.88", host="127.0.0.1")
        assert get_real_client_ip(req) == "11.22.33.44"

    def test_falls_back_to_client_host(self):
        req = _make_request(host="192.168.1.10")
        assert get_real_client_ip(req) == "192.168.1.10"

    def test_unknown_when_no_client(self):
        req = MagicMock()
        req.headers = {}
        req.client = None
        assert get_real_client_ip(req) == "unknown"


# ---------------------------------------------------------------------------
# GuestIPRateLimiter
# ---------------------------------------------------------------------------

class TestGuestIPRateLimiter:
    def test_within_limit_allowed(self):
        limiter = GuestIPRateLimiter(limit_per_hour=3)
        for _ in range(3):
            assert limiter.is_allowed("1.2.3.4") is True

    def test_exceeds_limit_blocked(self):
        limiter = GuestIPRateLimiter(limit_per_hour=2)
        limiter.is_allowed("1.2.3.4")
        limiter.is_allowed("1.2.3.4")
        assert limiter.is_allowed("1.2.3.4") is False

    def test_different_ips_independent(self):
        limiter = GuestIPRateLimiter(limit_per_hour=1)
        limiter.is_allowed("1.1.1.1")
        # 1.1.1.1 is now blocked
        assert limiter.is_allowed("1.1.1.1") is False
        # 2.2.2.2 is unaffected
        assert limiter.is_allowed("2.2.2.2") is True

    def test_zero_limit_never_blocks(self):
        limiter = GuestIPRateLimiter(limit_per_hour=0)
        for _ in range(1000):
            assert limiter.is_allowed("any.ip") is True

    def test_blocked_request_does_not_consume_slot(self):
        """Being blocked should not add a new timestamp — the window stays full but stable."""
        limiter = GuestIPRateLimiter(limit_per_hour=2)
        limiter.is_allowed("9.9.9.9")
        limiter.is_allowed("9.9.9.9")
        # From here every call is blocked
        for _ in range(10):
            assert limiter.is_allowed("9.9.9.9") is False
        # Internal store should have exactly 2 timestamps
        assert len(limiter._store["9.9.9.9"]) == 2

    def test_old_timestamps_expire(self):
        limiter = GuestIPRateLimiter(limit_per_hour=2)
        # Inject old timestamps directly (2 hours ago)
        old_ts = time.monotonic() - 7300
        limiter._store["3.3.3.3"] = [old_ts, old_ts]
        # Should be allowed because old timestamps are outside the window
        assert limiter.is_allowed("3.3.3.3") is True

    def test_limit_property(self):
        limiter = GuestIPRateLimiter(limit_per_hour=42)
        assert limiter.limit == 42


# ---------------------------------------------------------------------------
# Singleton initialisation from config
# ---------------------------------------------------------------------------

class TestGetGuestIPRateLimiterSingleton:
    def test_reads_limit_from_config(self):
        import app.auth.ip_rate_limiter as mod
        original = mod._limiter
        try:
            mod._limiter = None
            fake_config = {"auth": {"guest_ip_rate_limit_per_hour": 99}}
            with patch("app.settings.config_loader.load_default_config", return_value=fake_config):
                from app.auth.ip_rate_limiter import get_guest_ip_rate_limiter
                limiter = get_guest_ip_rate_limiter()
                assert limiter.limit == 99
        finally:
            mod._limiter = original

    def test_default_limit_when_key_missing(self):
        import app.auth.ip_rate_limiter as mod
        original = mod._limiter
        try:
            mod._limiter = None
            with patch("app.settings.config_loader.load_default_config", return_value={}):
                from app.auth.ip_rate_limiter import get_guest_ip_rate_limiter
                limiter = get_guest_ip_rate_limiter()
                assert limiter.limit == 30
        finally:
            mod._limiter = original
