"""The live auto-responder (design-rag.md §4.2.3, §4.2.4, §4.1.3).

create_question sets the initial ai_status and, for PENDING, schedules run().
run() moves PENDING to exactly one terminal status and never raises. Each
database step is a short session of its own; no session is open while
Infinity, Chroma or Ollama work.
"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import func, select, update

from ...common.exceptions import ConflictError
from ...config import settings
from ...database import AsyncSessionLocal
from ...models.qa import Question
from ...models.rag import IngestionProfile
from .. import bootstrap, qa_service
from . import pipeline
from .decline import is_decline
from .locks import GENERATION_LOCK, acquire
from .pipeline import ProfileSnap
from .prompts import LIVE_PROMPT, user_message

logger = structlog.get_logger()

MAX_QUERY_CHARS = 4000


async def initial_status(db, course_id: int) -> str:
    """NONE when live answering is off; SKIPPED once the course has
    RAG_MAX_PENDING_PER_COURSE PENDING questions; else PENDING. Two creates at
    the same moment can both pass, so the cap is a soft guard."""
    if not settings.RAG_LIVE_ENABLED:
        return "NONE"
    pending = await db.scalar(
        select(func.count())
        .select_from(Question)
        .where(Question.course_id == course_id, Question.ai_status == "PENDING")
    )
    return "SKIPPED" if pending >= settings.RAG_MAX_PENDING_PER_COURSE else "PENDING"


_TASKS: set[asyncio.Task] = set()


def schedule(question_id: int) -> None:
    """Start run() in the background; call only after the question commits.
    The set holds a reference so the task isn't garbage-collected."""
    task = asyncio.create_task(run(question_id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def citations(hits) -> list[dict]:
    """Above-threshold hits deduplicated by source_url, ranked from 1 (§4.1.3).
    Attached by code from chunk metadata, never written by the model."""
    out, seen = [], set()
    for hit in hits:
        url = hit.metadata.get("source_url")
        if url in seen:
            continue
        seen.add(url)
        title = (
            hit.metadata.get("title") or hit.metadata.get("rel_path") or url or "Source"
        )
        out.append(
            {
                "rank": len(out) + 1,
                "resource_type": hit.metadata.get("resource_type"),
                "title": title,
                "source_url": url,
                "similarity_score": round(hit.score, 4),
            }
        )
    return out


def post_body(answer: str, cites: list[dict]) -> str:
    """The answer, then a Sources block, so citations show wherever bodies
    render as plain text."""
    lines = [f"[{c['rank']}] {c['title']} — {c['source_url']}" for c in cites]
    return answer.strip() + "\n\nSources:\n" + "\n".join(lines)


async def load(question_id: int):
    """(question fields, ProfileSnap or None), or None if the question is gone."""
    async with AsyncSessionLocal() as db:
        question = await db.get(Question, question_id)
        if question is None:
            return None
        fields = {
            "course_id": question.course_id,
            "title": question.title,
            "body": question.body,
            "closed": question.status == "CLOSED",
        }
        result = await db.execute(
            select(IngestionProfile).where(
                IngestionProfile.course_id == question.course_id,
                IngestionProfile.name == settings.RAG_DEFAULT_PROFILE,
            )
        )
        profile = result.scalar_one_or_none()
        return fields, ProfileSnap.of(profile) if profile is not None else None


def _only_pending(question_id: int, status: str):
    # Terminal values never change, even if the restart sweep got there first
    return (
        update(Question)
        .where(Question.id == question_id, Question.ai_status == "PENDING")
        .values(ai_status=status)
    )


async def finish(question_id: int, status: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(_only_pending(question_id, status))
        await db.commit()
    logger.info("rag_answer_finished", question_id=question_id, ai_status=status)


async def post_answer(question_id: int, body: str, cites: list[dict], snap) -> str:
    """Insert the AI post and set ANSWERED in one transaction; SKIPPED if the
    thread closed meanwhile."""
    async with AsyncSessionLocal() as db:
        try:
            # Locks the question row first, so the status check below is current
            await qa_service.create_ai_answer(
                db,
                question_id,
                author_user_id=bootstrap.ai_user_id(),
                body=body,
                citations=cites,
                ai_model=settings.RAG_DEFAULT_MODEL,
                ai_profile=snap.name,
            )
            status = "ANSWERED"
        except ConflictError:
            await db.rollback()
            status = "SKIPPED"
        updated = await db.execute(_only_pending(question_id, status))
        if updated.rowcount == 0:
            # No longer PENDING (a restart sweep marked it FAILED): post nothing
            await db.rollback()
            logger.warning("rag_answer_not_pending", question_id=question_id)
            return "FAILED"
        await db.commit()
    logger.info("rag_answer_finished", question_id=question_id, ai_status=status)
    return status


async def run(question_id: int) -> None:
    try:
        await _run(question_id)
    except Exception as exc:  # noqa: BLE001 - a background task must not die silently
        logger.error("rag_answer_failed", question_id=question_id, exc_info=exc)
        try:
            await finish(question_id, "FAILED")
        except Exception as inner:  # noqa: BLE001
            logger.error(
                "rag_answer_fail_mark_failed", question_id=question_id, exc_info=inner
            )


async def _run(question_id: int) -> None:
    loaded = await load(question_id)
    if loaded is None:
        return
    question, snap = loaded
    if snap is None or question["closed"]:
        # Closed before we started: don't hold the generation lock for nothing
        return await finish(question_id, "SKIPPED")
    coll, count = await pipeline.open_snap_collection(snap)
    if count == 0:
        return await finish(question_id, "SKIPPED")

    query = (question["title"] + "\n\n" + question["body"])[:MAX_QUERY_CHARS]
    # Nobody waits on this, and Infinity may be busy with an ingestion batch
    r = await pipeline.retrieve(
        snap,
        query,
        settings.RAG_DEFAULT_THRESHOLD,
        coll,
        count,
        settings.RAG_INGEST_EMBED_TIMEOUT_S,
    )
    if not r.matched:
        return await finish(question_id, "NO_MATCH")

    acquired = False
    try:
        async with acquire(GENERATION_LOCK, settings.RAG_LIVE_LOCK_WAIT_S):
            acquired = True
            answer = await pipeline.generate(
                settings.RAG_DEFAULT_MODEL,
                LIVE_PROMPT,
                user_message(r.hits, query),
                settings.RAG_LIVE_GENERATION_TIMEOUT_S,
            )
    except TimeoutError:
        if acquired:
            raise
        logger.warning("rag_answer_lock_timeout", question_id=question_id)
        return await finish(question_id, "FAILED")
    if not answer.strip():
        logger.warning("rag_answer_empty", question_id=question_id)
        return await finish(question_id, "FAILED")
    if is_decline(answer):
        return await finish(question_id, "DECLINED")

    cites = citations(r.hits)
    await post_answer(question_id, post_body(answer, cites), cites, snap)
