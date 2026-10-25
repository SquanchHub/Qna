"""
Unit tests for GET /api/rag/health and its access rule (design §6).

Ollama, Infinity and Chroma are replaced by an httpx.MockTransport and the
database by a fake session, so no Docker stack is required.

Run with:
    cd tests/unit && pytest test_rag_health.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.common.dependencies import get_current_user, require_rag_viewer
from app.common.exceptions import ForbiddenError
from app.config import settings
from app.services.rag import clients

OLLAMA = "http://ollama:11434"
INFINITY = "http://infinity:7997"
CHROMA = "http://chroma:8000"


def service_handler(down: frozenset[str] = frozenset()):
    """A MockTransport handler answering like the three services; any in `down` refuse connections."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for name, base in (("ollama", OLLAMA), ("infinity", INFINITY), ("chroma", CHROMA)):
            if url.startswith(base) and name in down:
                raise httpx.ConnectError("refused", request=request)
        if url == f"{OLLAMA}/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}, {"name": "qwen2.5:3b"}]})
        if url == f"{INFINITY}/health":
            return httpx.Response(200, json={"unix": 1.0})
        if url == f"{INFINITY}/models":
            return httpx.Response(
                200, json={"data": [{"id": "sentence-transformers/all-MiniLM-L6-v2"}, {"id": "BAAI/bge-small-en-v1.5"}]}
            )
        if url == f"{CHROMA}/api/v2/heartbeat":
            return httpx.Response(200, json={"nanosecond heartbeat": 1})
        if url == f"{CHROMA}/api/v2/version":
            return httpx.Response(200, json="1.0.0")
        return httpx.Response(404)

    return handler


@pytest_asyncio.fixture
async def health_client():
    """Yields a function that GETs /api/rag/health with the given services down."""
    from app.main import app
    from app.routers.rag import get_rag_http

    down: set[str] = set()

    async def override_http():
        async with httpx.AsyncClient(transport=httpx.MockTransport(service_handler(frozenset(down)))) as c:
            yield c

    app.dependency_overrides[get_rag_http] = override_http
    app.dependency_overrides[require_rag_viewer] = lambda: MagicMock()

    async def get(*services_down: str) -> httpx.Response:
        down.clear()
        down.update(services_down)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            return await ac.get("/api/rag/health")

    yield get
    app.dependency_overrides.clear()


# -- Response shape -----------------------------------------------------------


async def test_all_services_up(health_client):
    r = await health_client()
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "ollama", "infinity", "chroma", "gitlab_token_configured", "live_enabled", "defaults", "limits"
    }
    assert body["limits"] == {"max_upload_mb": settings.MAX_UPLOAD_MB, "max_zip_mb": settings.MAX_ZIP_MB}
    assert body["ollama"] == {"ok": True, "models": ["qwen2.5:1.5b", "qwen2.5:3b"]}
    assert body["infinity"] == {
        "ok": True,
        "models": ["sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"],
    }
    assert body["chroma"]["ok"] is True
    assert body["chroma"]["server_version"] == "1.0.0"
    assert isinstance(body["chroma"]["client_version"], str)
    assert isinstance(body["gitlab_token_configured"], bool)
    assert isinstance(body["live_enabled"], bool)
    assert body["defaults"] == {
        "profile": settings.RAG_DEFAULT_PROFILE,
        "threshold": settings.RAG_DEFAULT_THRESHOLD,
        "model": settings.RAG_DEFAULT_MODEL,
    }


@pytest.mark.parametrize("service", ["ollama", "infinity", "chroma"])
async def test_one_service_down_is_reported_not_raised(health_client, service):
    r = await health_client(service)
    assert r.status_code == 200
    body = r.json()
    assert body[service]["ok"] is False
    for other in {"ollama", "infinity", "chroma"} - {service}:
        assert body[other]["ok"] is True
    if service == "chroma":
        assert body["chroma"]["server_version"] is None
        assert isinstance(body["chroma"]["client_version"], str)
    else:
        assert body[service]["models"] == []


async def test_all_services_down_is_still_200(health_client):
    r = await health_client("ollama", "infinity", "chroma")
    assert r.status_code == 200
    assert not any(r.json()[s]["ok"] for s in ("ollama", "infinity", "chroma"))


async def test_gitlab_token_is_reported_only_as_a_flag(health_client, monkeypatch):
    monkeypatch.setattr(settings, "GITLAB_TOKEN", "glpat-secret-value")
    r = await health_client()
    assert r.json()["gitlab_token_configured"] is True
    assert "glpat-secret-value" not in r.text


async def test_unexpected_payload_counts_as_down():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await clients.ollama_health(c) == {"ok": False, "models": []}


async def test_slow_service_times_out(monkeypatch):
    import asyncio

    monkeypatch.setattr(clients, "HEALTH_TIMEOUT_S", 0.05)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"models": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await clients.ollama_health(c) == {"ok": False, "models": []}


# -- Access: ADMIN, or STAFF in some course; never the student surface --------


def db_with_staff_grant(found: bool):
    result = MagicMock()
    result.scalar_one_or_none.return_value = 1 if found else None
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def user(role: str):
    u = MagicMock()
    u.id = "u1"
    u.role = role
    return u


async def test_admin_may_view():
    db = db_with_staff_grant(False)
    assert (await require_rag_viewer(user("ADMIN"), db, None)).role == "ADMIN"
    db.execute.assert_not_called()


async def test_staff_in_some_course_may_view():
    db = db_with_staff_grant(True)
    assert (await require_rag_viewer(user("USER"), db, "staff")).role == "USER"
    # The grant lookup must filter on STAFF, or any student would pass
    query = str(db.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "role = 'STAFF'" in query and "user_id = 'u1'" in query


async def test_student_only_user_is_forbidden():
    with pytest.raises(ForbiddenError):
        await require_rag_viewer(user("USER"), db_with_staff_grant(False), "staff")


async def test_student_surface_is_forbidden_even_for_admin():
    with pytest.raises(ForbiddenError):
        await require_rag_viewer(user("ADMIN"), db_with_staff_grant(True), "student")


async def test_no_token_is_401_before_any_role_check():
    from app.main import app

    app.dependency_overrides.pop(get_current_user, None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/rag/health")
    assert r.status_code == 401
    assert r.json()["error"] == "UNAUTHORIZED"
