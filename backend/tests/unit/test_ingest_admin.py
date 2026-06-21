"""Ingest admin lock: when ODS_ADMIN_KEY is set, /api/ingest needs the header."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routers.ingest import get_ingest_usecase
from app.core.settings import get_settings
from app.domain.entities import IngestReport
from app.main import create_app


class _StubIngest:
    def execute(
        self, content: bytes, filename: str, *, category: str | None = None
    ) -> IngestReport:
        return IngestReport(filename=filename, chunks=1)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ODS_ADMIN_KEY", "secret123")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_ingest_usecase] = lambda: _StubIngest()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _file() -> dict[str, tuple[str, bytes, str]]:
    return {"files": ("a.txt", b"hello", "text/plain")}


def test_ingest_rejects_without_admin_key(client: TestClient) -> None:
    r = client.post("/api/ingest", files=_file())
    assert r.status_code == 403


def test_ingest_rejects_wrong_admin_key(client: TestClient) -> None:
    r = client.post("/api/ingest", files=_file(), headers={"X-Admin-Key": "nope"})
    assert r.status_code == 403


def test_ingest_allows_correct_admin_key(client: TestClient) -> None:
    r = client.post("/api/ingest", files=_file(), headers={"X-Admin-Key": "secret123"})
    assert r.status_code == 200
    assert r.json()[0]["status"] == "success"
