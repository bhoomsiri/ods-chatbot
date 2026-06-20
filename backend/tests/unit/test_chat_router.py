from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api.routers.chat import get_answer_usecase
from app.domain.entities import ERROR_MESSAGE, QUOTA_MESSAGE
from app.domain.errors import QuotaExceededError
from app.main import create_app


class _QuotaUsecase:
    async def execute(self, *args: object, **kwargs: object) -> AsyncIterator[object]:
        for _ in ():  # no-op; makes this an async generator
            yield _
        raise QuotaExceededError("429 You exceeded your current quota")


class _BoomUsecase:
    async def execute(self, *args: object, **kwargs: object) -> AsyncIterator[object]:
        for _ in ():
            yield _
        raise RuntimeError("internal kaboom with secrets")


def test_quota_error_yields_friendly_message() -> None:
    app = create_app()
    app.dependency_overrides[get_answer_usecase] = lambda: _QuotaUsecase()
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "งดน้ำกี่ชั่วโมง"})
    assert r.status_code == 200
    assert QUOTA_MESSAGE in r.text
    assert '"type": "token"' in r.text  # friendly reply, not a raw error


def test_generic_error_is_sanitized() -> None:
    app = create_app()
    app.dependency_overrides[get_answer_usecase] = lambda: _BoomUsecase()
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "งดน้ำกี่ชั่วโมง"})
    assert r.status_code == 200
    assert ERROR_MESSAGE in r.text
    assert "kaboom" not in r.text  # internal details must not leak
