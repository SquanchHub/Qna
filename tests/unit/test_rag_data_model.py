"""
Unit tests for the M2 RAG data model: serializers, the AI system account,
the historical-Q&A resource and the validation-error message.

No Docker stack required: the database is a fake session.

Run with:
    cd tests/unit && pytest test_rag_data_model.py -v
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.common.dependencies import require_admin
from app.common.exceptions import validation_message
from app.database import get_db
from app.models.qa import Post, Question
from app.models.rag import CourseResource, IngestionProfile
from app.models.user import AI_USERNAME, User
from app.schemas.admin import UserCreate, UserUpdate
from app.schemas.qa import PostResponse, QuestionDetail, QuestionSummary
from app.services import bootstrap, qa_service
from app.services.rag.resources import ensure_qa_resource

NOW = datetime(2026, 10, 25, 12, 0, 0)
CITATIONS = [
    {
        "rank": 1,
        "resource_type": "syllabus",
        "title": "Syllabus > Late Policy",
        "source_url": "https://git.doit.wisc.edu/x/-/blob/abc/syllabus.html#:~:text=slip",
        "similarity_score": 0.7123,
    }
]


def make_user(username: str, display_name: str | None = None) -> User:
    return User(id=f"id-{username}", username=username, display_name=display_name, role="USER")


def make_post(author: User, role: str, **extra) -> Post:
    post = Post(
        id=1,
        question_id=10,
        author_user_id=author.id,
        author_role=role,
        kind="ANSWER",
        body="Three slip days.",
        is_accepted=False,
        created_at=NOW,
        **extra,
    )
    post.author = author
    post.accepted_by = None
    return post


def make_question(posts: list[Post], ai_status: str = "NONE") -> Question:
    question = Question(
        id=10,
        course_id=1,
        author_user_id="id-student",
        title="Slip days?",
        body="How many?",
        status="OPEN",
        ai_status=ai_status,
        created_at=NOW,
        updated_at=NOW,
    )
    question.author = make_user("student")
    question.category_links = []
    question.posts = posts
    question.closed_by = None
    return question


# -- Serializers (design §6 "Changed shapes") ---------------------------------


def test_ai_post_serializes_role_citations_and_model():
    ai = make_user(AI_USERNAME, "QnA Assistant (AI)")
    data = qa_service.serialize_post(
        make_post(ai, "AI", citations=CITATIONS, ai_model="qwen2.5:1.5b", ai_profile="sliding-window")
    )
    parsed = PostResponse(**data)
    assert parsed.author_role == "AI"
    assert parsed.author.display_name == "QnA Assistant (AI)"
    assert parsed.citations == CITATIONS
    assert parsed.ai_model == "qwen2.5:1.5b"
    assert "ai_profile" not in PostResponse.model_fields


def test_human_post_has_null_citations_and_model():
    data = qa_service.serialize_post(make_post(make_user("ta"), "STAFF"))
    assert data["citations"] is None and data["ai_model"] is None
    PostResponse(**data)


@pytest.mark.parametrize("status", ["NONE", "PENDING", "ANSWERED", "NO_MATCH", "DECLINED", "SKIPPED", "FAILED"])
def test_summary_and_detail_carry_ai_status(status):
    question = make_question([], ai_status=status)
    assert QuestionSummary(**qa_service.serialize_question_summary(question)).ai_status == status
    assert QuestionDetail(**qa_service.serialize_question_detail(question)).ai_status == status


def test_new_question_defaults_to_none_before_flush():
    """The Python-side default matters: async can't lazy-load a server default."""
    assert Question.__table__.c.ai_status.default.arg == "NONE"
    assert Question.__table__.c.ai_status.server_default.arg == "NONE"


def test_collection_name_is_derived_from_course_and_profile():
    assert IngestionProfile(id=3, course_id=1).collection_name == "c1_p3"


# -- The reserved username ----------------------------------------------------


def test_admin_cannot_create_or_rename_to_the_ai_username():
    with pytest.raises(ValueError, match="reserved"):
        UserCreate(username="QnA-AI-Assistant", display_name="x", password="password123")
    with pytest.raises(ValueError, match="reserved"):
        UserUpdate(username=AI_USERNAME)
    assert UserCreate(username="qna-ai-helper", display_name="x", password="password123")


# -- SYSTEM_ACCOUNT guards ----------------------------------------------------


@pytest_asyncio.fixture
async def admin_api():
    """The FastAPI app as an admin, with db.get returning the AI user."""
    from app.main import app

    ai = make_user(AI_USERNAME, "QnA Assistant (AI)")
    db = MagicMock()
    db.get = AsyncMock(return_value=ai)
    db.execute = AsyncMock(side_effect=AssertionError("guard must run before any query"))
    db.delete = AsyncMock()

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: make_user("admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, ai, db
    app.dependency_overrides.clear()


async def test_every_admin_mutation_of_the_ai_user_is_409(admin_api):
    client, ai, db = admin_api
    users = f"/api/admin/users/{ai.id}"
    attempts = [
        await client.put(users, json={"display_name": "Not The AI"}),
        await client.delete(users),
        await client.post(f"{users}/course-access", json={"course_id": 1, "role": "STAFF"}),
        # No access row exists: the guard must answer before the 404 lookup
        await client.delete(f"{users}/course-access/1"),
    ]
    for r in attempts:
        assert r.status_code == 409, (r.request.method, r.request.url, r.text)
        assert r.json() == {"error": "SYSTEM_ACCOUNT", "message": "The AI assistant is a system account"}
    assert ai.display_name == "QnA Assistant (AI)"
    db.delete.assert_not_called()


async def test_revoke_for_a_missing_user_is_still_404(admin_api):
    client, _, db = admin_api
    db.get.return_value = None
    r = await client.delete("/api/admin/users/nobody/course-access/1")
    assert r.status_code == 404


# -- Historical-Q&A resource --------------------------------------------------


def fake_db(existing_id):
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_id
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    return db


async def test_qa_resource_is_added_once_per_course():
    db = fake_db(None)
    assert await ensure_qa_resource(db, 7) is True
    [added] = [call.args[0] for call in db.add.call_args_list]
    assert isinstance(added, CourseResource)
    assert (added.course_id, added.resource_type, added.source_kind, added.singleton_key) == (
        7,
        "historical_qa",
        "internal",
        "historical_qa",
    )

    db = fake_db(42)
    assert await ensure_qa_resource(db, 7) is False
    db.add.assert_not_called()


async def test_creating_a_course_adds_its_qa_resource(monkeypatch):
    from app.main import app
    from app.routers import admin

    calls = []

    async def record(db, course_id):
        calls.append(course_id)
        return True

    monkeypatch.setattr(admin, "ensure_qa_resource", record)
    db = MagicMock()

    async def flush():
        db.add.call_args.args[0].id = 99

    db.flush = AsyncMock(side_effect=flush)
    db.refresh = AsyncMock()
    db.commit = AsyncMock()

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: make_user("admin")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            db.refresh.side_effect = lambda c: setattr(c, "created_at", NOW)
            r = await ac.post("/api/admin/courses", json={"name": "CS 1", "semester": "Fall"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 201, r.text
    assert calls == [99]
    db.commit.assert_awaited()


# -- Bootstrap: AI system user ------------------------------------------------


def db_returning_user(user):
    result = MagicMock()
    result.scalars.return_value.first.return_value = user
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    return db


async def test_ai_user_is_created_with_no_way_to_log_in():
    db = db_returning_user(None)
    user_id = await bootstrap._ensure_ai_user(db)
    [created] = [call.args[0] for call in db.add.call_args_list]
    assert created.id == user_id
    assert created.username == AI_USERNAME
    assert created.display_name == "QnA Assistant (AI)"
    assert created.role == "USER"
    assert created.password_hash is None and created.netid is None and created.email is None


async def test_existing_ai_user_is_reused():
    existing = User(id="ai-1", username=AI_USERNAME, role="USER")
    db = db_returning_user(existing)
    assert await bootstrap._ensure_ai_user(db) == "ai-1"
    db.add.assert_not_called()


@pytest.mark.parametrize(
    "field,value", [("password_hash", "$2b$12$x"), ("netid", "jdoe"), ("email", "a@b.c"), ("role", "ADMIN")]
)
async def test_a_real_account_with_the_ai_username_is_not_adopted(field, value):
    """The board stays up without an AI author rather than letting a login act as the AI."""
    impostor = User(id="u-1", username=AI_USERNAME, role="USER")
    setattr(impostor, field, value)
    db = db_returning_user(impostor)
    assert await bootstrap._ensure_ai_user(db) is None
    db.add.assert_not_called()


async def test_admin_can_rename_an_impostor_account(admin_api):
    client, ai, db = admin_api
    ai.password_hash = "$2b$12$x"
    ai.created_at = NOW
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    r = await client.put(f"/api/admin/users/{ai.id}", json={"username": "old-ai-name"})
    assert r.status_code == 200, r.text
    assert ai.username == "old-ai-name"


# -- Bootstrap: one transaction, retried after a UNIQUE race ------------------


def session_factory(sessions):
    """An AsyncSessionLocal stand-in handing out `sessions` in order."""
    factory = MagicMock()
    contexts = []
    for s in sessions:
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=s)
        ctx.__aexit__ = AsyncMock(return_value=False)
        contexts.append(ctx)
    factory.side_effect = contexts
    return factory


def rag_session(commit_error=None):
    db = MagicMock()
    courses = MagicMock()
    courses.scalars.return_value.all.return_value = [1, 2]
    updated = MagicMock(rowcount=0)
    db.execute = AsyncMock(side_effect=lambda stmt, *a, **k: courses if "courses" in str(stmt) else updated)
    db.commit = AsyncMock(side_effect=commit_error)
    db.rollback = AsyncMock()
    return db


async def test_bootstrap_rag_commits_once_and_retries_a_unique_race(monkeypatch):
    from sqlalchemy.exc import IntegrityError

    first = rag_session(commit_error=IntegrityError("INSERT", {}, Exception(1062, "dup")))
    second = rag_session()
    monkeypatch.setattr(bootstrap, "AsyncSessionLocal", session_factory([first, second]))
    monkeypatch.setattr(bootstrap, "_ai_user_id", None)
    monkeypatch.setattr(bootstrap, "_ensure_ai_user", AsyncMock(return_value="ai-9"))
    added = []

    async def ensure(db, course_id):
        added.append((db, course_id))
        return True

    monkeypatch.setattr(bootstrap, "ensure_qa_resource", ensure)

    await bootstrap.bootstrap_rag()

    first.rollback.assert_awaited_once()
    second.commit.assert_awaited_once()
    second.rollback.assert_not_called()
    assert added == [(first, 1), (first, 2), (second, 1), (second, 2)]
    assert bootstrap.ai_user_id() == "ai-9"
    # The sweep ran in the committed session: three UPDATEs plus the course query
    assert second.execute.await_count == 4


async def test_bootstrap_rag_sets_no_ai_user_until_commit_succeeds(monkeypatch):
    from sqlalchemy.exc import IntegrityError

    race = IntegrityError("INSERT", {}, Exception(1062, "dup"))
    monkeypatch.setattr(
        bootstrap, "AsyncSessionLocal", session_factory([rag_session(race) for _ in range(3)])
    )
    monkeypatch.setattr(bootstrap, "_ai_user_id", None)
    monkeypatch.setattr(bootstrap, "_ensure_ai_user", AsyncMock(return_value="ai-9"))
    monkeypatch.setattr(bootstrap, "ensure_qa_resource", AsyncMock(return_value=False))
    with pytest.raises(RuntimeError, match="UNIQUE"):
        await bootstrap.bootstrap_rag()
    assert bootstrap._ai_user_id is None


def test_ai_user_id_before_bootstrap_raises(monkeypatch):
    monkeypatch.setattr(bootstrap, "_ai_user_id", None)
    with pytest.raises(RuntimeError):
        bootstrap.ai_user_id()


# -- Bootstrap: schema detection ----------------------------------------------


@pytest.mark.parametrize("code,missing", [(1054, True), (1146, True), (2003, False), (1064, False)])
def test_unknown_column_or_table_means_waiting_for_schema(code, missing):
    """Only "unknown column/table" waits; a real SQL bug (1064) must not loop silently."""
    from sqlalchemy.exc import OperationalError, ProgrammingError

    for cls in (OperationalError, ProgrammingError):
        assert bootstrap._schema_missing(cls("SELECT 1", {}, Exception(code, "msg"))) is missing


# -- Validation errors carry a message (frontend open question 1) ------------


def test_validation_message_names_the_field():
    errors = [{"loc": ["body", "profile_ids"], "msg": "List should have at least 1 item"}]
    assert validation_message(errors) == "profile_ids: List should have at least 1 item"
    assert validation_message([{"loc": ["body"], "msg": "Field required"}]) == "Field required"
    assert validation_message([]) == "Invalid request"


async def test_422_body_has_error_message_and_detail():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/auth/login", json={"username": 5})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "VALIDATION_ERROR"
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["detail"], list)
