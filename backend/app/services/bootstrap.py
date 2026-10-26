"""
On first startup, create the initial admin user if ADMIN_USERNAME and
ADMIN_PASSWORD are set and no ADMIN account exists yet.

This runs once inside the lifespan startup hook. After the first admin
exists the env vars are ignored — remove them from .env if you like,
or leave them (they simply become a no-op).

It also keeps the course grader account in step with GRADER_PASSWORD_HASH
(base64 of a bcrypt hash that course staff publish in .env.template): an
ADMIN user named "grader" whose password only staff know. Unlike the first
admin this is applied on every startup, so a corrected hash takes effect on
the next restart.

It then prepares the RAG state (design-rag.md §4.2, §4.5.1) in one
transaction, so a database still at migration 001 gets none of it:
- the AI system user that authors auto-generated answers;
- one historical-Q&A resource per course;
- a restart sweep: PENDING questions and QUEUED/RUNNING ingestion work were
  killed with the previous process (a dev --reload, a deploy), so they are
  marked FAILED rather than left waiting forever. This assumes one backend
  process (true for both compose stacks); a second live process would have
  its in-flight work marked FAILED.

On a fresh database the schema doesn't exist until `alembic upgrade head`
has been run, so this retries instead of crashing: startup blocks (with a
log line every few seconds) until migrations land, then completes on its
own. Because the RAG steps always run, startup always waits for the schema.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import AsyncSessionLocal
from ..models.course import Course
from ..models.qa import Question
from ..models.rag import IngestionJob, ResourceProfileState
from ..models.user import AI_DISPLAY_NAME, AI_USERNAME, User, is_system_account
from .auth_service import hash_password
from .rag.resources import ensure_qa_resource

logger = structlog.get_logger()

RETRY_SECONDS = 5
GRADER_USERNAME = "grader"
INTERRUPTED = "interrupted by restart"
# MySQL "unknown column" / "table doesn't exist": the schema is behind the code
SCHEMA_MISSING_CODES = (1054, 1146)

_ai_user_id: str | None = None


def ai_user_id() -> str:
    """The AI system user's id, set by bootstrap before the app serves requests."""
    if _ai_user_id is None:
        raise RuntimeError("bootstrap has not created the AI system user yet")
    return _ai_user_id


def grader_password_hash() -> str | None:
    """The bcrypt hash carried by GRADER_PASSWORD_HASH, or None if it is unset or
    is not base64 of a bcrypt hash (logged, never fatal)."""
    raw = settings.GRADER_PASSWORD_HASH.strip()
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        decoded = ""
    if not decoded.startswith("$2"):
        logger.warning(
            "grader_hash_invalid",
            hint="copy GRADER_PASSWORD_HASH from .env.template unchanged",
        )
        return None
    return decoded


def _schema_missing(exc: Exception) -> bool:
    args = getattr(getattr(exc, "orig", None), "args", None) or (None,)
    return args[0] in SCHEMA_MISSING_CODES


async def bootstrap_admin() -> None:
    create_admin = bool(settings.ADMIN_USERNAME and settings.ADMIN_PASSWORD)
    grader_hash = grader_password_hash()

    while True:
        try:
            if create_admin:
                await _create_admin_if_missing()
            if grader_hash is not None:
                await _ensure_grader(grader_hash)
            await bootstrap_rag()
            return
        except (ProgrammingError, OperationalError) as exc:
            if _schema_missing(exc):
                # Fresh database, or migrations behind the code
                logger.warning(
                    "admin_bootstrap_waiting_for_schema",
                    hint="run `docker compose run --rm backend alembic upgrade head` "
                    "to create the schema; startup will finish on its own",
                )
            else:
                logger.warning("admin_bootstrap_retrying", error=str(exc.orig))
        await asyncio.sleep(RETRY_SECONDS)


async def bootstrap_rag() -> None:
    """AI user, historical-Q&A resources and the restart sweep, committed once.

    A concurrent startup can win a UNIQUE race; that rolls back and reruns.
    """
    global _ai_user_id
    for attempt in range(3):
        async with AsyncSessionLocal() as db:
            try:
                user_id = await _ensure_ai_user(db)
                added = 0
                for course_id in (await db.execute(select(Course.id))).scalars().all():
                    added += await ensure_qa_resource(db, course_id)
                swept = await _sweep_interrupted(db)
                await db.commit()
            except IntegrityError:
                await db.rollback()
                logger.warning("rag_bootstrap_race_retrying", attempt=attempt + 1)
                continue
        _ai_user_id = user_id
        logger.info("rag_bootstrap_ready", qa_resources_added=added, **swept)
        return
    raise RuntimeError("RAG bootstrap kept losing UNIQUE races")


async def _ensure_ai_user(db: AsyncSession) -> str | None:
    result = await db.execute(select(User).where(User.username == AI_USERNAME))
    user = result.scalars().first()
    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            username=AI_USERNAME,
            display_name=AI_DISPLAY_NAME,
            password_hash=None,
            role="USER",
        )
        db.add(user)
        await db.flush()
        logger.info("ai_user_created", user_id=user.id)
        return user.id
    if not is_system_account(user):
        # A real account took the name before it was reserved. Adopting it
        # would let a login act as the AI, so the board runs without an AI
        # author (ai_user_id() raises) until an admin renames that account.
        logger.error(
            "ai_user_name_taken",
            user_id=user.id,
            hint=f"rename the account {AI_USERNAME!r} and restart the backend",
        )
        return None
    return user.id


async def _sweep_interrupted(db: AsyncSession) -> dict[str, int]:
    """Work the previous process was doing when it died can never finish."""
    questions = await db.execute(
        update(Question)
        .where(Question.ai_status == "PENDING")
        .values(ai_status="FAILED")
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    jobs = await db.execute(
        update(IngestionJob)
        .where(IngestionJob.status.in_(("QUEUED", "RUNNING")))
        .values(status="FAILED", error=INTERRUPTED, finished_at=now)
    )
    states = await db.execute(
        update(ResourceProfileState)
        .where(ResourceProfileState.status.in_(("QUEUED", "RUNNING")))
        .values(status="FAILED", error=INTERRUPTED)
    )
    return {
        "pending_questions_failed": questions.rowcount,
        "jobs_failed": jobs.rowcount,
        "states_failed": states.rowcount,
    }


async def _create_admin_if_missing() -> None:
    async with AsyncSessionLocal() as db:
        # The grader account doesn't count: it must never stand in for your own admin.
        result = await db.execute(
            select(User)
            .where(User.role == "ADMIN", User.username != GRADER_USERNAME)
            .limit(1)
        )
        if result.scalars().first() is not None:
            return  # admin already exists

        admin = User(
            id=str(uuid.uuid4()),
            username=settings.ADMIN_USERNAME.lower(),
            display_name="Admin",
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="ADMIN",
        )
        db.add(admin)
        await db.commit()
        logger.info("admin_bootstrapped", username=settings.ADMIN_USERNAME.lower())


async def _ensure_grader(password_hash: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.username == GRADER_USERNAME).limit(1)
        )
        grader = result.scalars().first()
        if grader is None:
            db.add(
                User(
                    id=str(uuid.uuid4()),
                    username=GRADER_USERNAME,
                    display_name="Course Grader",
                    password_hash=password_hash,
                    role="ADMIN",
                )
            )
        elif grader.password_hash == password_hash and grader.role == "ADMIN":
            return
        else:
            grader.password_hash = password_hash
            grader.role = "ADMIN"
        await db.commit()
        logger.info("grader_account_ready", username=GRADER_USERNAME)
