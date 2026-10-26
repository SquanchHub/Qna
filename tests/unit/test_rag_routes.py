"""RAG request schemas and route wiring that the integration tests can't pin
down (design-rag.md §6): validators, timestamps, presets' `served`, and the
lock that makes "one active job per profile" hold under concurrent requests."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.common.dependencies import require_course_staff
from app.database import get_db
from app.schemas.rag import ProfileCreate, ResourceRegister, ResourceSync, utc_z
from app.services.rag import catalog, embeddings

REPO = "https://git.doit.wisc.edu/ns/qna-74"


def test_utc_z():
    assert utc_z(datetime(2026, 10, 25, 18, 3, 11, 999)) == "2026-10-25T18:03:11Z"
    assert utc_z(None) is None


@pytest.mark.parametrize("name", ["A", "-x-", "a" * 65, "has space", "ab", "x-"])
def test_bad_profile_names(name):
    with pytest.raises(ValidationError):
        ProfileCreate(preset="sliding-window", name=name)


def test_profile_name_ok_and_extra_forbidden():
    assert ProfileCreate(preset="sliding-window", name="sw-copy").name == "sw-copy"
    assert ProfileCreate(preset="sliding-window", name="a" * 64).name
    with pytest.raises(ValidationError):
        ProfileCreate(preset="sliding-window", chunk_size=100)


@pytest.mark.parametrize(
    "body",
    [
        {"resource_type": "syllabus", "title": "s", "url": "ftp://example.com/s.html"},
        {"resource_type": "syllabus", "title": "s", "url": "https:///s.html"},
        {
            "resource_type": "syllabus",
            "title": "s",
            "url": "https://e.com/" + "a" * 2048,
        },
        {"resource_type": "syllabus", "title": " ", "url": "https://e.com/s.html"},
        {
            "resource_type": "syllabus",
            "title": "s",
            "url": "https://e.com/s",
            "git_ref": "main",
        },
        {
            "resource_type": "schedule",
            "title": "s",
            "url": "https://e.com/s",
            "subpath": "x",
        },
        {"resource_type": "historical_qa", "title": "s", "url": "https://e.com/s"},
        {"resource_type": "repository", "title": "r", "url": "http://e.com/r"},
        {"resource_type": "repository", "title": "r", "url": REPO, "git_ref": "a" * 40},
        {
            "resource_type": "repository",
            "title": "r",
            "url": REPO,
            "git_ref": "-upload-pack=x",
        },
        {"resource_type": "repository", "title": "r", "url": REPO, "git_ref": "a b"},
        {"resource_type": "repository", "title": "r", "url": REPO, "git_ref": "a..b"},
        {"resource_type": "repository", "title": "r", "url": REPO, "subpath": "../x"},
        {"resource_type": "repository", "title": "r", "url": REPO, "subpath": "/etc"},
        {"resource_type": "repository", "title": "r", "url": REPO, "subpath": "a\\b"},
        {"resource_type": "repository", "title": "r", "url": REPO, "subpath": "a\x00b"},
        {"resource_type": "repository", "title": "r", "url": REPO, "subpath": "/"},
        {"resource_type": "repository", "title": "r", "url": REPO, "extra": 1},
    ],
)
def test_invalid_registrations(body):
    with pytest.raises(ValidationError):
        ResourceRegister(**body)


def test_valid_registration_normalises_subpath():
    body = ResourceRegister(
        resource_type="repository",
        title=" Sample ",
        url=REPO,
        git_ref="release/1.0",
        subpath="eval/./sample_data/repo/",
    )
    assert (body.title, body.subpath) == ("Sample", "eval/sample_data/repo")


def test_profile_ids_empty_is_error_and_duplicates_collapse():
    with pytest.raises(ValidationError):
        ResourceSync(profile_ids=[])
    assert ResourceSync(profile_ids=[3, 4, 3]).profile_ids == [3, 4]
    assert ResourceSync().profile_ids is None


async def test_presets_report_served(monkeypatch):
    async def served():
        return {"sentence-transformers/all-MiniLM-L6-v2"}

    monkeypatch.setattr(embeddings, "served_models", served)
    presets = {p["preset"]: p for p in await catalog.list_presets()}
    assert presets["sliding-window"]["served"] is True
    assert presets["embedding-alt"]["served"] is False
    assert (
        presets["type-tailored"]["chunking"]["per_type"]["syllabus"]["method"]
        == "semantic"
    )


async def test_presets_with_infinity_down_are_unserved(monkeypatch):
    async def down():
        return None

    monkeypatch.setattr(embeddings, "served_models", down)
    assert not any(p["served"] for p in await catalog.list_presets())


async def test_concurrent_syncs_check_and_insert_under_one_lock(monkeypatch):
    """Two simultaneous POST /sync for one profile: exactly one 202, one 409."""
    from app.common.exceptions import QnaError
    from app.main import app
    from app.routers import rag as rag_router

    created: list[int] = []

    async def create_job(db, course_id, profile_id, user_id):
        busy = bool(created)
        await asyncio.sleep(0.05)  # a check-then-insert race window
        if busy:
            raise QnaError("JOB_RUNNING", "busy", 409)
        created.append(1)
        return {"id": len(created)}

    db = MagicMock()

    async def commit():
        return None

    db.commit = commit

    async def override_db():
        yield db

    monkeypatch.setattr(catalog, "create_profile_job", create_job)
    monkeypatch.setattr(rag_router, "schedule_job", lambda job_id: None)
    app.dependency_overrides[require_course_staff] = lambda: MagicMock()
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            a, b = await asyncio.gather(
                ac.post("/api/courses/1/rag/profiles/2/sync", json={}),
                ac.post("/api/courses/1/rag/profiles/2/sync", json={}),
            )
    finally:
        app.dependency_overrides.clear()
    assert sorted([a.status_code, b.status_code]) == [202, 409]


async def test_busy_check_starts_a_fresh_transaction_under_the_lock(monkeypatch):
    """Auth already read on the request's session; under REPEATABLE READ the
    check would miss a job committed while this request waited for the lock."""
    from app.main import app
    from app.routers import rag as rag_router

    events: list[str] = []

    async def create_job(db, course_id, profile_id, user_id):
        assert rag_router.JOB_CREATE_LOCK.locked()
        events.append("check")
        return {"id": 1}

    db = MagicMock()

    async def commit():
        events.append("commit")

    db.commit = commit

    async def override_db():
        yield db

    monkeypatch.setattr(catalog, "create_profile_job", create_job)
    monkeypatch.setattr(rag_router, "schedule_job", lambda job_id: None)
    app.dependency_overrides[require_course_staff] = lambda: MagicMock()
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.post("/api/courses/1/rag/profiles/2/sync", json={})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 202
    assert events == ["commit", "check", "commit"]


async def test_upload_refuses_a_pdf_over_the_page_cap(monkeypatch):
    import io

    from fastapi import UploadFile

    from app.common.exceptions import QnaError

    async def pages(data):
        return 501

    monkeypatch.setattr(catalog, "pdf_page_count", pages)
    file = UploadFile(file=io.BytesIO(b"%PDF-1.4"), filename="slides.pdf")
    with pytest.raises(QnaError) as err:
        await catalog.upload_resource(
            MagicMock(), 1, 1, "repository", "Slides", None, file
        )
    assert err.value.code == "UNSUPPORTED_FILE" and "500 pages" in err.value.message


# --- POST /rag/compare request (design §4.4.5) ------------------------------

COMPARE = {
    "question": "What does Quindlewort require?",
    "ingestion_profile": "sliding-window",
    "similarity_threshold": 0.5,
    "system_prompt": "Only use the tagged context.",
    "generation_model": "qwen2.5:1.5b",
}


@pytest.mark.parametrize(
    "change",
    [
        *[{"drop": k} for k in COMPARE],
        {"set": {"top_k": 3}},
        {"set": {"similarity_threshold": 1.5}},
        {"set": {"similarity_threshold": -0.1}},
        {"set": {"similarity_threshold": float("nan")}},
        {"set": {"question": ""}},
        {"set": {"question": "  \n\t "}},
        {"set": {"question": "q" * 4001}},
        {"set": {"system_prompt": ""}},
        {"set": {"system_prompt": "p" * 8001}},
        {"set": {"ingestion_profile": ""}},
        {"set": {"ingestion_profile": "a" * 65}},
        {"set": {"generation_model": ""}},
        {"set": {"generation_model": "m" * 101}},
    ],
)
def test_compare_request_rejects(change):
    from app.schemas.rag import CompareRequest

    body = dict(COMPARE)
    if "drop" in change:
        del body[change["drop"]]
    else:
        body.update(change["set"])
    with pytest.raises(ValidationError):
        CompareRequest(**body)


@pytest.mark.parametrize(
    "change",
    [
        {"similarity_threshold": 0.0},
        {"similarity_threshold": 1.0},
        {"similarity_threshold": 1},
        {"question": "q" * 4000},
        {"question": "  padded  " + "q" * 3990},
    ],
)
def test_compare_request_accepts_edges(change):
    from app.schemas.rag import CompareRequest

    req = CompareRequest(**{**COMPARE, **change})
    assert req.question == req.question.strip()
    assert 0.0 <= req.similarity_threshold <= 1.0


async def test_compare_route_returns_the_pipeline_result(monkeypatch):
    from app.main import app
    from app.routers import rag as rag_router

    seen = {}

    async def compare(db, course_id, req):
        seen["args"] = (course_id, req.ingestion_profile)
        return {"matched": False, "retrieved_chunks": [], "answer": None,
                "metrics": {"embedding_time_ms": 1, "retrieval_time_ms": 1,
                            "generation_time_ms": 0, "cpu_percent": 0.0}}

    async def override_db():
        yield MagicMock()

    monkeypatch.setattr(rag_router.pipeline, "compare", compare)
    app.dependency_overrides[require_course_staff] = lambda: MagicMock()
    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post("/api/courses/7/rag/compare", json=COMPARE)
            bad = await ac.post("/api/courses/7/rag/compare", json={})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200 and r.json()["matched"] is False
    assert seen["args"] == (7, "sliding-window")
    assert bad.status_code == 422 and bad.json()["error"] == "VALIDATION_ERROR"
