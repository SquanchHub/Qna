"""Ingestion jobs: sync each resource into one profile's collection
(design-rag.md §4.5.5, §4.5.6).

``run_job`` runs as a background task after the creating request commits. It
holds INGESTION_LOCK for the whole job and uses a short session for each
write, never one held across a fetch or an embed. ``sync_resource`` is pure
apart from the collection and its injected fetcher and embedder, so the unit
tests drive it with fakes.
"""

from __future__ import annotations

import asyncio
import posixpath
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ...config import settings
from ...database import AsyncSessionLocal
from ...models.qa import Question
from ...models.rag import (
    CourseResource,
    IngestionJob,
    IngestionProfile,
    ResourceProfileState,
)
from . import embeddings, store
from .chunking import Chunk, chunk_html, chunk_markdown, chunk_pdf, chunk_qa, qa_answer
from .citations import CitationContext, assign_ids, chunk_metadata, source_url
from .fetchers import Fetched, FetchError, fetch, parse_pdf, scrub
from .locks import INGESTION_LOCK

logger = structlog.get_logger()

EMBED_BATCH = 8
DEFAULT_MAX_BATCH = 1000
_MAX_ERROR = 500
FAIL_RETRY_DELAYS_S = (1.0, 5.0, 30.0)

Embed = Callable[[list[str]], Awaitable[list[list[float]]]]


def utcnow() -> datetime:
    """Naive UTC, as stored in MySQL DATETIME columns."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class Prepared:
    id: str
    document: str
    embedded: str
    metadata: dict


@dataclass
class Outcome:
    status: str  # READY or FAILED
    chunk_count: int
    commit_sha: str | None
    error: str | None
    added: int = 0
    kept: int = 0
    deleted: int = 0


@dataclass
class QaThread:
    question_id: int
    title: str
    body: str
    answer: str


def _failed(error: str) -> Outcome:
    return Outcome("FAILED", 0, None, scrub(error)[:_MAX_ERROR])


# Chunks


def _prepare(
    groups: list[tuple[str | None, list[Chunk]]],
    resource,
    profile,
    ctx: CitationContext,
    commit_sha: str | None,
    job_id: int,
) -> list[Prepared]:
    out: list[Prepared] = []
    for rel_path, chunks in groups:
        for chunk, (chunk_id, digest) in zip(
            chunks, assign_ids(chunks, resource.id, rel_path)
        ):
            metadata = chunk_metadata(
                chunk,
                course_id=resource.course_id,
                profile_id=profile.id,
                resource_id=resource.id,
                chunk_index=len(out),
                source_url=source_url(chunk, ctx, rel_path),
                content_hash=digest,
                ingest_job_id=job_id,
                rel_path=rel_path,
                commit_sha=commit_sha,
            )
            out.append(Prepared(chunk_id, chunk.text, chunk.embedded_text, metadata))
    return out


def _html_input(data: bytes, charset: str | None) -> str | bytes:
    if not charset:
        return data  # BeautifulSoup detects it from the bytes and <meta>
    try:
        return data.decode(charset, "replace")
    except LookupError:
        return data


async def build_chunks(resource, profile, fetched: Fetched, job_id: int, embed: Embed):
    chunking = profile.chunking
    groups = []
    for doc in fetched.documents:
        label = posixpath.basename(doc.rel_path) if doc.rel_path else ""
        if doc.kind == "md":
            text = doc.data.decode("utf-8", "replace")
            chunks = chunk_markdown(text, label, chunking)
        elif doc.kind == "pdf":
            chunks = chunk_pdf(await parse_pdf(doc.data), label, chunking)
        else:
            html = _html_input(doc.data, doc.charset)
            chunks = await chunk_html(html, resource.resource_type, chunking, embed)
        groups.append((doc.rel_path, chunks))
    return _prepare(groups, resource, profile, fetched.ctx, fetched.commit_sha, job_id)


def qa_chunks(resource, profile, threads: list[QaThread], job_id: int):
    chunks = [
        chunk
        for t in threads
        for chunk in chunk_qa(
            t.question_id, t.title, t.body, t.answer, profile.chunking
        )
    ]
    ctx = CitationContext(
        kind="internal",
        resource_id=resource.id,
        course_id=resource.course_id,
        frontend_url=settings.FRONTEND_URL,
    )
    return _prepare([(None, chunks)], resource, profile, ctx, None, job_id)


async def load_qa_threads(course_id: int) -> list[QaThread]:
    """The course's qualifying threads (design §4.5.4), oldest first."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Question)
            .where(Question.course_id == course_id)
            .options(selectinload(Question.posts))
            .order_by(Question.id)
        )
        threads = []
        for question in result.scalars():
            answer = qa_answer(question, question.posts)
            if answer is not None:
                threads.append(
                    QaThread(question.id, question.title, question.body, answer.body)
                )
        return threads


# Sync


def _slices(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def sync_resource(
    resource,
    profile,
    job_id: int,
    coll,
    *,
    embed: Embed,
    fetcher=fetch,
    qa_loader=load_qa_threads,
    max_batch: int = DEFAULT_MAX_BATCH,
) -> Outcome:
    """Bring one resource's chunks in `coll` up to date (design §4.5.6).

    A failed fetch, zero chunks, or a failed write leaves the previous chunk
    set in place. Historical Q&A is the exception to "zero chunks is FAILED":
    MySQL is authoritative, so no qualifying threads means no chunks.
    """
    is_qa = resource.resource_type == "historical_qa"
    commit_sha = None
    try:
        if is_qa:
            threads = await qa_loader(resource.course_id)
            new = qa_chunks(resource, profile, threads, job_id)
        else:
            fetched = await fetcher(resource)
            commit_sha = fetched.commit_sha
            new = await build_chunks(resource, profile, fetched, job_id, embed)
    except FetchError as exc:
        return _failed(str(exc))
    except Exception as exc:  # noqa: BLE001 - a bad document fails only its resource
        logger.warning("rag_chunking_failed", resource_id=resource.id, exc_info=exc)
        return _failed(f"could not chunk the source: {type(exc).__name__}: {exc}")
    if not new and not is_qa:
        return _failed("no chunks: the source has no indexable text")

    try:
        existing = set(
            (await coll.get(where={"resource_id": resource.id}, include=[]))["ids"]
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(f"could not read the collection: {type(exc).__name__}")
    new_ids = {p.id for p in new}
    add = [p for p in new if p.id not in existing]
    keep = [p for p in new if p.id in existing]
    stale = sorted(existing - new_ids)

    written: list[str] = []
    try:
        for batch in _slices(add, EMBED_BATCH):
            vectors = await embed([p.embedded for p in batch])
            await coll.upsert(
                ids=[p.id for p in batch],
                embeddings=vectors,
                documents=[p.document for p in batch],
                metadatas=[p.metadata for p in batch],
            )
            written += [p.id for p in batch]
        # Kept chunks are not re-embedded; only lines, SHA, URL and job id change
        for batch in _slices(keep, max_batch):
            await coll.update(
                ids=[p.id for p in batch], metadatas=[p.metadata for p in batch]
            )
        for batch in _slices(stale, max_batch):
            await coll.delete(ids=batch)
    except Exception as exc:  # noqa: BLE001 - roll back and keep the old set
        logger.warning("rag_sync_write_failed", resource_id=resource.id, exc_info=exc)
        try:
            for batch in _slices(written, max_batch):
                await coll.delete(ids=batch)
        except Exception:  # noqa: BLE001
            logger.warning("rag_sync_rollback_failed", resource_id=resource.id)
        return _failed(f"writing chunks failed: {type(exc).__name__}: {exc}")

    return Outcome("READY", len(new), commit_sha, None, len(add), len(keep), len(stale))


# Jobs: each step below is one short session


async def _start_job(job_id: int):
    async with AsyncSessionLocal() as db:
        job = await db.get(IngestionJob, job_id)
        if job is None or job.status != "QUEUED":
            return None
        job.status = "RUNNING"
        job.started_at = utcnow()
        await db.commit()
        return job


async def _resource_ids(job) -> list[int]:
    if job.scope == "resource":
        return [job.resource_id]
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CourseResource.id)
            .where(CourseResource.course_id == job.course_id)
            .order_by(CourseResource.id)
        )
        return list(result.scalars())


async def set_state(db, resource_id: int, profile_id: int, **fields) -> None:
    state = await db.get(ResourceProfileState, (resource_id, profile_id))
    if state is None:
        state = ResourceProfileState(
            resource_id=resource_id, profile_id=profile_id, chunk_count=0, **fields
        )
        db.add(state)
    else:
        for key, value in fields.items():
            setattr(state, key, value)


async def _begin_resource(job, resource_id: int):
    async with AsyncSessionLocal() as db:
        resource = await db.get(CourseResource, resource_id)
        profile = await db.get(IngestionProfile, job.profile_id)
        if resource is None or profile is None or resource.course_id != job.course_id:
            return None
        await set_state(db, resource_id, profile.id, status="RUNNING", error=None)
        await db.commit()
        return resource, profile


async def _finish_resource(job, resource_id: int, outcome: Outcome) -> None:
    async with AsyncSessionLocal() as db:
        if await db.get(CourseResource, resource_id) is None:
            return
        if outcome.status == "READY":
            await set_state(
                db,
                resource_id,
                job.profile_id,
                status="READY",
                chunk_count=outcome.chunk_count,
                last_commit_sha=outcome.commit_sha,
                last_synced_at=utcnow(),
                error=None,
            )
        else:
            # The old chunks are still there, so the old count and SHA stand
            await set_state(
                db, resource_id, job.profile_id, status="FAILED", error=outcome.error
            )
        row = await db.get(IngestionJob, job.id)
        if row is not None:
            row.chunks_added += outcome.added
            row.chunks_updated += outcome.kept
            row.chunks_deleted += outcome.deleted
        await db.commit()


async def _finish_job(job, failures: int, total: int, count: int | None) -> None:
    async with AsyncSessionLocal() as db:
        profile = await db.get(IngestionProfile, job.profile_id)
        if profile is not None and count is not None:
            profile.chunk_count = count
        row = await db.get(IngestionJob, job.id)
        if row is not None:
            row.status = "FAILED" if failures else "SUCCEEDED"
            row.error = f"{failures} of {total} resources failed" if failures else None
            row.finished_at = utcnow()
        await db.commit()


async def _fail_job(job_id: int, error: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(IngestionJob, job_id)
        if job is None:
            return
        job.status = "FAILED"
        job.error = error
        job.finished_at = utcnow()
        states = update(ResourceProfileState).where(
            ResourceProfileState.profile_id == job.profile_id,
            ResourceProfileState.status.in_(("QUEUED", "RUNNING")),
        )
        if job.scope == "resource":
            states = states.where(ResourceProfileState.resource_id == job.resource_id)
        await db.execute(states.values(status="FAILED", error=error))
        await db.commit()


async def _open_collection(profile):
    client = await store.open_client()
    coll = await store.collection(client, profile)
    return coll, await client.get_max_batch_size()


_TASKS: set[asyncio.Task] = set()


def schedule_job(job_id: int) -> None:
    """Start run_job in the background; call only after the job row commits.
    The set holds a reference so the task isn't garbage-collected."""
    task = asyncio.create_task(run_job(job_id))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def run_job(job_id: int) -> None:
    """Run one QUEUED job to SUCCEEDED or FAILED. Never raises."""
    async with INGESTION_LOCK:
        try:
            await _run(job_id)
        except Exception as exc:  # noqa: BLE001 - a background task must not die silently
            logger.error("rag_job_failed", job_id=job_id, exc_info=exc)
            error = scrub(f"internal error: {type(exc).__name__}: {exc}")[:_MAX_ERROR]
            await _mark_failed(job_id, error)


async def _mark_failed(job_id: int, error: str) -> None:
    """Retry, since a job left QUEUED blocks its profile until a restart."""
    for delay in (*FAIL_RETRY_DELAYS_S, None):
        try:
            await _fail_job(job_id, error)
            return
        except Exception as inner:  # noqa: BLE001
            logger.error("rag_job_fail_mark_failed", job_id=job_id, exc_info=inner)
        if delay is not None:
            await asyncio.sleep(delay)


async def _run(job_id: int) -> None:
    job = await _start_job(job_id)
    if job is None:
        return
    rids = await _resource_ids(job)
    coll = None
    failures = total = 0
    for rid in rids:
        begun = await _begin_resource(job, rid)
        if begun is None:
            continue
        resource, profile = begun
        if coll is None:
            coll, max_batch = await _open_collection(profile)
        total += 1
        try:
            outcome = await sync_resource(
                resource,
                profile,
                job.id,
                coll,
                embed=partial(embeddings.embed, profile.embedding_model),
                max_batch=max_batch,
            )
        except Exception as exc:  # noqa: BLE001 - isolate one resource's failure
            logger.warning("rag_resource_sync_crashed", resource_id=rid, exc_info=exc)
            outcome = _failed(f"sync failed: {type(exc).__name__}: {exc}")
        if outcome.status != "READY":
            failures += 1
        await _finish_resource(job, rid, outcome)
    count = await coll.count() if coll is not None else None
    await _finish_job(job, failures, total, count)
