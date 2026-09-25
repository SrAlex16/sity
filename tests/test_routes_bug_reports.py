"""Integration tests for POST /bug-report and GET/DELETE /bug-reports* endpoints.

Properties verified:
1.  POST /bug-report as Guest → 201, report saved with role="guest", user_id=None.
2.  POST /bug-report as regular user → 201, report saved with role="user".
3.  POST /bug-report as admin → 201, report saved with role="admin".
4.  POST /bug-report with invalid severity → 422.
5.  POST /bug-report with empty observations → 422.
6.  POST /bug-report with image attachment → saved to disk, URL in detail response.
7.  GET /bug-reports as Guest → 403.
8.  GET /bug-reports as regular user → 403.
9.  GET /bug-reports as Admin → 200 with list (contains submitted report).
10. GET /bug-reports/{id} as Admin → 200 with full detail including observations.
11. GET /bug-reports/{id} for non-existent id → 404.
12. GET /bug-reports/{id}/download as Admin → JSON attachment with correct filename.
13. has_attachments=False when no attachments submitted.
14. has_attachments=True when attachment was submitted.
15. DELETE /bug-reports/{id} as Guest → 403.
16. DELETE /bug-reports/{id} as User → 403.
17. DELETE /bug-reports/{id} as Admin → 200, report gone (404).
18. DELETE /bug-reports/{id} with attachment → file removed from disk.
19. DELETE /bug-reports/{id} for non-existent → 404.
20. DELETE /bug-reports with empty ids → 422.
21. DELETE /bug-reports as Admin (multiple ids) → 200, deleted=N, all gone.
22. DELETE /bug-reports as Guest → 403.
23. DELETE /bug-reports ignores non-existent ids in list.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import make_admin_token, make_user_token

# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def admin_client():
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("sity_session", token)
        yield c


@pytest.fixture()
def user_client():
    token = make_user_token()
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("sity_session", token)
        yield c


# ── helpers ───────────────────────────────────────────────────────────────────

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _submit(client: TestClient, **overrides) -> dict:
    body = {
        "observations": "El botón no funciona.",
        "severity": "media",
        **overrides,
    }
    resp = client.post("/bug-report", json=body)
    return resp


# ── tests ─────────────────────────────────────────────────────────────────────

class TestSubmitBugReport:

    def test_guest_submit_201(self, client: TestClient):
        resp = _submit(client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["id"], int)

    def test_guest_report_stored_correctly(self, client: TestClient, admin_client: TestClient):
        resp = _submit(client, observations="Test guest observations", severity="alta")
        report_id = resp.json()["id"]

        detail = admin_client.get(f"/bug-reports/{report_id}").json()
        assert detail["role"] == "guest"
        assert detail["user_id"] is None
        assert detail["observations"] == "Test guest observations"
        assert detail["severity"] == "alta"

    def test_user_submit_201(self, user_client: TestClient, admin_client: TestClient):
        resp = _submit(user_client, observations="User report test", severity="baja")
        assert resp.status_code == 201
        report_id = resp.json()["id"]

        detail = admin_client.get(f"/bug-reports/{report_id}").json()
        assert detail["role"] == "user"
        assert detail["user_id"] is not None

    def test_admin_submit_201(self, admin_client: TestClient):
        resp = _submit(admin_client, observations="Admin report test", severity="crítica")
        assert resp.status_code == 201
        detail = admin_client.get(f"/bug-reports/{resp.json()['id']}").json()
        assert detail["role"] == "admin"

    def test_invalid_severity_422(self, client: TestClient):
        resp = _submit(client, severity="urgente")
        assert resp.status_code == 422

    def test_empty_observations_422(self, client: TestClient):
        resp = _submit(client, observations="   ")
        assert resp.status_code == 422

    def test_git_commit_populated(self, client: TestClient, admin_client: TestClient):
        resp = _submit(client)
        report_id = resp.json()["id"]
        detail = admin_client.get(f"/bug-reports/{report_id}").json()
        assert detail["git_commit"] is not None
        assert detail["git_commit"] != ""

    def test_user_agent_captured(self, client: TestClient, admin_client: TestClient):
        resp = client.post(
            "/bug-report",
            json={"observations": "UA test", "severity": "baja"},
            headers={"User-Agent": "TestBrowser/1.0"},
        )
        assert resp.status_code == 201
        detail = admin_client.get(f"/bug-reports/{resp.json()['id']}").json()
        assert "TestBrowser" in (detail["user_agent"] or "")

    def test_no_attachments_flag_false(self, client: TestClient, admin_client: TestClient):
        resp = _submit(client)
        report_id = resp.json()["id"]
        listing = admin_client.get("/bug-reports").json()
        item = next((r for r in listing["reports"] if r["id"] == report_id), None)
        assert item is not None
        assert item["has_attachments"] is False

    def test_with_image_attachment(
        self, client: TestClient, admin_client: TestClient, tmp_path: Path
    ):
        resp = client.post("/bug-report", json={
            "observations": "Screenshot attached",
            "severity": "alta",
            "attachments": [{"data": _TINY_PNG_B64, "media_type": "image/png"}],
        })
        assert resp.status_code == 201
        report_id = resp.json()["id"]

        listing = admin_client.get("/bug-reports").json()
        item = next(r for r in listing["reports"] if r["id"] == report_id)
        assert item["has_attachments"] is True

        detail = admin_client.get(f"/bug-reports/{report_id}").json()
        assert len(detail["attachments"]) == 1
        att = detail["attachments"][0]
        assert att["url"].startswith("/uploads/bug-reports/")
        assert att["mime_type"] == "image/png"


class TestAdminListAndDetail:

    def test_guest_cannot_list(self, client: TestClient):
        resp = client.get("/bug-reports")
        assert resp.status_code == 403

    def test_user_cannot_list(self, user_client: TestClient):
        resp = user_client.get("/bug-reports")
        assert resp.status_code == 403

    def test_admin_list_200(self, admin_client: TestClient):
        resp = admin_client.get("/bug-reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["reports"], list)
        assert isinstance(data["total"], int)

    def test_list_contains_submitted_report(self, client: TestClient, admin_client: TestClient):
        _submit(client, observations="List visibility test")
        resp = admin_client.get("/bug-reports")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_detail_404_for_missing(self, admin_client: TestClient):
        resp = admin_client.get("/bug-reports/999999")
        assert resp.status_code == 404

    def test_detail_full_fields(self, client: TestClient, admin_client: TestClient):
        _submit(client, observations="Full detail check", severity="crítica")
        listing = admin_client.get("/bug-reports").json()
        report_id = listing["reports"][0]["id"]

        detail = admin_client.get(f"/bug-reports/{report_id}").json()
        for field in ("id", "created_at", "severity", "role", "observations",
                      "session_id", "user_agent", "git_commit", "attachments"):
            assert field in detail, f"Missing field: {field}"

    def test_guest_cannot_see_detail(self, client: TestClient, admin_client: TestClient):
        _submit(client)
        listing = admin_client.get("/bug-reports").json()
        report_id = listing["reports"][0]["id"]
        resp = client.get(f"/bug-reports/{report_id}")
        assert resp.status_code == 403

    def test_user_cannot_see_detail(self, user_client: TestClient, admin_client: TestClient):
        _submit(user_client)
        listing = admin_client.get("/bug-reports").json()
        report_id = listing["reports"][0]["id"]
        resp = user_client.get(f"/bug-reports/{report_id}")
        assert resp.status_code == 403


class TestDownload:

    def test_download_returns_json_attachment(self, client: TestClient, admin_client: TestClient):
        _submit(client, observations="Download test")
        listing = admin_client.get("/bug-reports").json()
        report_id = listing["reports"][0]["id"]

        resp = admin_client.get(f"/bug-reports/{report_id}/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        cd = resp.headers.get("content-disposition", "")
        assert f"bug-report-{report_id}.json" in cd

        payload = resp.json()
        assert payload["id"] == report_id
        assert "observations" in payload
        assert "exported_at" in payload

    def test_download_404_for_missing(self, admin_client: TestClient):
        resp = admin_client.get("/bug-reports/999998/download")
        assert resp.status_code == 404

    def test_guest_cannot_download(self, client: TestClient, admin_client: TestClient):
        _submit(client)
        listing = admin_client.get("/bug-reports").json()
        report_id = listing["reports"][0]["id"]
        resp = client.get(f"/bug-reports/{report_id}/download")
        assert resp.status_code == 403


class TestDeleteBugReport:

    def test_guest_cannot_delete(self, client: TestClient, admin_client: TestClient):
        report_id = _submit(client).json()["id"]
        resp = client.delete(f"/bug-reports/{report_id}")
        assert resp.status_code == 403

    def test_user_cannot_delete(self, user_client: TestClient, admin_client: TestClient):
        report_id = _submit(user_client).json()["id"]
        resp = user_client.delete(f"/bug-reports/{report_id}")
        assert resp.status_code == 403

    def test_admin_delete_200_and_gone(self, admin_client: TestClient):
        report_id = _submit(admin_client).json()["id"]
        del_resp = admin_client.delete(f"/bug-reports/{report_id}")
        assert del_resp.status_code == 200
        assert del_resp.json() == {"ok": True, "deleted": 1}
        assert admin_client.get(f"/bug-reports/{report_id}").status_code == 404

    def test_delete_removes_attachment_from_disk(
        self, client: TestClient, admin_client: TestClient
    ):
        resp = client.post("/bug-report", json={
            "observations": "Attachment delete test",
            "severity": "baja",
            "attachments": [{"data": _TINY_PNG_B64, "media_type": "image/png"}],
        })
        assert resp.status_code == 201
        report_id = resp.json()["id"]

        detail = admin_client.get(f"/bug-reports/{report_id}").json()
        filename = detail["attachments"][0]["url"].split("/")[-1]
        att_path = Path(__file__).resolve().parents[1] / "uploads" / "bug-reports" / filename
        assert att_path.exists()

        admin_client.delete(f"/bug-reports/{report_id}")
        assert not att_path.exists()

    def test_delete_404_for_missing(self, admin_client: TestClient):
        resp = admin_client.delete("/bug-reports/999997")
        assert resp.status_code == 404

    def test_bulk_delete_empty_ids_422(self, admin_client: TestClient):
        resp = admin_client.request("DELETE", "/bug-reports", json={"ids": []})
        assert resp.status_code == 422

    def test_bulk_delete_admin_200(self, admin_client: TestClient):
        id1 = _submit(admin_client).json()["id"]
        id2 = _submit(admin_client).json()["id"]

        del_resp = admin_client.request("DELETE", "/bug-reports", json={"ids": [id1, id2]})
        assert del_resp.status_code == 200
        data = del_resp.json()
        assert data["ok"] is True
        assert data["deleted"] == 2

        assert admin_client.get(f"/bug-reports/{id1}").status_code == 404
        assert admin_client.get(f"/bug-reports/{id2}").status_code == 404

    def test_bulk_delete_guest_403(self, client: TestClient, admin_client: TestClient):
        report_id = _submit(client).json()["id"]
        resp = client.request("DELETE", "/bug-reports", json={"ids": [report_id]})
        assert resp.status_code == 403

    def test_bulk_delete_ignores_missing_ids(self, admin_client: TestClient):
        report_id = _submit(admin_client).json()["id"]
        del_resp = admin_client.request("DELETE", "/bug-reports", json={"ids": [report_id, 999996]})
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] == 1
