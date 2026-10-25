"""Profiles, resources and jobs behind the /rag routes (design-rag.md §4.5, §6).

Like the other services, these flush and never commit. The router commits,
because job creation and deletes must commit while JOB_CREATE_LOCK is held,
and a background job must only start after its row is committed. IDs are
always looked up together with the course, so another course's ID gives the
same 404 as a missing one.
"""

from __future__ import annotations

import asyncio
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import structlog
from fastapi import UploadFile, status
from sqlalchemy import select

from ...common.exceptions import NotFoundError, QnaError
from ...common.uploads import read_upload_capped
from ...config import settings
from ...models.course import Course
from ...models.rag import (
    CourseResource,
    IngestionJob,
    IngestionProfile,
    ResourceProfileState,
)
from ...schemas.rag import ProfileCreate, ResourceRegister, check_http_url, utc_z
from . import embeddings, store
from .archives import UnsafeArchive, read_zip, safe_filename
from .fetchers import (
    MAX_PDF_PAGES,
    FetchError,
    parse_gitlab_file_url,
    parse_repo_url,
    pdf_page_count,
)
from .ingest import set_state, utcnow
from .presets import PRESETS, get_preset, validate_chunking
from .ssrf import UrlNotAllowed, check_registration_host

logger = structlog.get_logger()

ACTIVE = ("QUEUED", "RUNNING")
MB = 1024 * 1024
UPLOAD_SUFFIXES = {
    "syllabus": (".html", ".htm"),
    "schedule": (".html", ".htm"),
    "repository": (".zip", ".md", ".pdf"),
}


def _error(code: str, message: str, status_code: int) -> QnaError:
    return QnaError(code, message, status_code)


def _validation(message: str) -> QnaError:
    return _error("VALIDATION_ERROR", message, status.HTTP_422_UNPROCESSABLE_ENTITY)


def _chroma_unavailable(exc: Exception, message: str) -> QnaError:
    logger.warning("rag_chroma_unavailable", error=type(exc).__name__)
    return _error("CHROMA_UNAVAILABLE", message, status.HTTP_503_SERVICE_UNAVAILABLE)


def _job_running(message: str) -> QnaError:
    return _error("JOB_RUNNING", message, status.HTTP_409_CONFLICT)


async def ensure_course(db, course_id: int) -> None:
    """ADMIN passes require_course_member for any id, so writes check the course."""
    if await db.get(Course, course_id) is None:
        raise NotFoundError(f"Course {course_id} not found")


# Serialization (design §6 shapes)


def serialize_profile(profile: IngestionProfile, active_job_id: int | None) -> dict:
    return {
        "id": profile.id,
        "course_id": profile.course_id,
        "name": profile.name,
        "preset": profile.preset,
        "embedding_model": profile.embedding_model,
        "query_instruction": profile.query_instruction or "",
        "chunking": profile.chunking,
        "chunk_count": profile.chunk_count,
        "collection_name": profile.collection_name,
        "active_job_id": active_job_id,
        "created_at": utc_z(profile.created_at),
    }


def serialize_job(job: IngestionJob, profile_name: str) -> dict:
    return {
        "id": job.id,
        "course_id": job.course_id,
        "profile_id": job.profile_id,
        "profile_name": profile_name,
        "scope": job.scope,
        "resource_id": job.resource_id,
        "status": job.status,
        "chunks_added": job.chunks_added,
        "chunks_updated": job.chunks_updated,
        "chunks_deleted": job.chunks_deleted,
        "error": job.error,
        "created_at": utc_z(job.created_at),
        "started_at": utc_z(job.started_at),
        "finished_at": utc_z(job.finished_at),
    }


def _serialize_state(profile: IngestionProfile, state) -> dict:
    if state is None:
        return {
            "profile_id": profile.id,
            "profile_name": profile.name,
            "status": "NEVER",
            "chunk_count": 0,
            "last_commit_sha": None,
            "last_synced_at": None,
            "error": None,
        }
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "status": state.status,
        "chunk_count": state.chunk_count,
        "last_commit_sha": state.last_commit_sha,
        "last_synced_at": utc_z(state.last_synced_at),
        "error": state.error,
    }


def serialize_resource(resource: CourseResource, profiles, states: dict) -> dict:
    return {
        "id": resource.id,
        "course_id": resource.course_id,
        "resource_type": resource.resource_type,
        "source_kind": resource.source_kind,
        "title": resource.title,
        "url": resource.url,
        "git_ref": resource.git_ref,
        "subpath": resource.subpath,
        "citation_base_url": resource.citation_base_url,
        "original_filename": resource.original_filename,
        "created_at": utc_z(resource.created_at),
        "states": [
            _serialize_state(p, states.get((resource.id, p.id))) for p in profiles
        ],
    }


# Lookups


async def _profiles(db, course_id: int) -> list[IngestionProfile]:
    result = await db.execute(
        select(IngestionProfile)
        .where(IngestionProfile.course_id == course_id)
        .order_by(IngestionProfile.id)
    )
    return list(result.scalars())


async def get_profile(db, course_id: int, profile_id: int) -> IngestionProfile:
    profile = await db.get(IngestionProfile, profile_id)
    if profile is None or profile.course_id != course_id:
        raise _error(
            "PROFILE_NOT_FOUND", "Profile not found", status.HTTP_404_NOT_FOUND
        )
    return profile


async def get_resource(db, course_id: int, resource_id: int) -> CourseResource:
    resource = await db.get(CourseResource, resource_id)
    if resource is None or resource.course_id != course_id:
        raise _error(
            "RESOURCE_NOT_FOUND", "Resource not found", status.HTTP_404_NOT_FOUND
        )
    return resource


async def active_jobs(db, course_id: int) -> list[IngestionJob]:
    result = await db.execute(
        select(IngestionJob).where(
            IngestionJob.course_id == course_id, IngestionJob.status.in_(ACTIVE)
        )
    )
    return list(result.scalars())


async def _active_by_profile(db, course_id: int) -> dict[int, int]:
    """profile_id → its newest active job id."""
    out: dict[int, int] = {}
    for job in await active_jobs(db, course_id):
        out[job.profile_id] = max(job.id, out.get(job.profile_id, 0))
    return out


# Presets and profiles


async def list_presets() -> list[dict]:
    served = await embeddings.served_models() or set()
    return [
        {**get_preset(name), "served": PRESETS[name]["embedding_model"] in served}
        for name in PRESETS
    ]


async def list_profiles(db, course_id: int) -> list[dict]:
    active = await _active_by_profile(db, course_id)
    return [
        serialize_profile(p, active.get(p.id)) for p in await _profiles(db, course_id)
    ]


async def create_profile(db, course_id: int, user_id: str, body: ProfileCreate) -> dict:
    if body.preset not in PRESETS:
        raise _error(
            "UNKNOWN_PRESET",
            f"Unknown preset {body.preset!r}; choose one of {', '.join(PRESETS)}",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    await ensure_course(db, course_id)
    preset = get_preset(body.preset)
    model = preset["embedding_model"]
    served = await embeddings.served_models()
    if served is None or model not in served:
        reason = (
            "Infinity is unreachable"
            if served is None
            else "Infinity does not serve it"
        )
        raise _error(
            "EMBEDDING_MODEL_NOT_SERVED",
            f"Embedding model {model} is not available ({reason})",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    validate_chunking(preset["chunking"], model)
    name = body.name or body.preset
    taken = await db.execute(
        select(IngestionProfile.id).where(
            IngestionProfile.course_id == course_id, IngestionProfile.name == name
        )
    )
    if taken.scalar_one_or_none() is not None:
        raise _error(
            "DUPLICATE_PROFILE",
            f"A profile named {name!r} already exists in this course",
            status.HTTP_409_CONFLICT,
        )
    profile = IngestionProfile(
        course_id=course_id,
        name=name,
        preset=body.preset,
        embedding_model=model,
        query_instruction=preset["query_instruction"],
        chunking=preset["chunking"],
        chunk_count=0,
        created_by_user_id=user_id,
        created_at=utcnow(),
    )
    db.add(profile)
    await db.flush()
    return serialize_profile(profile, None)


async def delete_profile(db, course_id: int, profile_id: int) -> None:
    """Call under JOB_CREATE_LOCK. Drops the collection, then the row."""
    profile = await get_profile(db, course_id, profile_id)
    if any(j.profile_id == profile.id for j in await active_jobs(db, course_id)):
        raise _job_running("This profile has a queued or running job")
    try:
        client = await store.open_client()
        await store.drop_collection(client, profile.collection_name)
    except Exception as exc:  # noqa: BLE001 - any Chroma failure keeps the row
        raise _chroma_unavailable(
            exc, "The vector store is unreachable; nothing was deleted. Try again."
        ) from exc
    await db.delete(profile)
    await db.flush()


# Resources


async def list_resources(db, course_id: int) -> list[dict]:
    profiles = await _profiles(db, course_id)
    resources = (
        (
            await db.execute(
                select(CourseResource)
                .where(CourseResource.course_id == course_id)
                .order_by(CourseResource.id)
            )
        )
        .scalars()
        .all()
    )
    rows = await db.execute(
        select(ResourceProfileState).where(
            ResourceProfileState.resource_id.in_([r.id for r in resources] or [0])
        )
    )
    states = {(s.resource_id, s.profile_id): s for s in rows.scalars()}
    return [serialize_resource(r, profiles, states) for r in resources]


async def _resource_response(db, resource: CourseResource) -> dict:
    return serialize_resource(resource, await _profiles(db, resource.course_id), {})


async def register_resource(
    db, course_id: int, user_id: str, body: ResourceRegister
) -> dict:
    try:
        if body.resource_type == "repository":
            parse_repo_url(body.url)
        else:
            parse_gitlab_file_url(body.url)
    except ValueError as exc:
        raise _validation(f"url: {exc}") from exc
    try:
        await check_registration_host(urlsplit(body.url).hostname or "")
    except UrlNotAllowed as exc:
        raise _error(
            "URL_NOT_ALLOWED", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    await ensure_course(db, course_id)
    resource = CourseResource(
        course_id=course_id,
        resource_type=body.resource_type,
        source_kind="url",
        title=body.title,
        url=body.url,
        git_ref=body.git_ref,
        subpath=body.subpath,
        created_by_user_id=user_id,
        created_at=utcnow(),
    )
    db.add(resource)
    await db.flush()
    return await _resource_response(db, resource)


def upload_dir(course_id: int, resource_id: int) -> Path:
    return Path(settings.UPLOAD_DIR) / str(course_id) / str(resource_id)


def remove_upload_dir(course_id: int, resource_id: int) -> None:
    shutil.rmtree(upload_dir(course_id, resource_id), ignore_errors=True)


def _unsupported(message: str) -> QnaError:
    return _error("UNSUPPORTED_FILE", message, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def upload_resource(
    db,
    course_id: int,
    user_id: str,
    resource_type: str,
    title: str,
    citation_base_url: str | None,
    file: UploadFile,
) -> dict:
    """Checks everything before writing, so a 413 or 422 leaves nothing behind.
    On success the file is on disk and the row flushed; the router commits and
    calls remove_upload_dir if that commit fails."""
    if resource_type not in UPLOAD_SUFFIXES:
        raise _validation("resource_type: must be syllabus, schedule or repository")
    title = (title or "").strip()
    if not title or len(title) > 255:
        raise _validation("title: must be 1 to 255 characters")
    if citation_base_url:
        try:
            citation_base_url = check_http_url(citation_base_url)
        except ValueError as exc:
            raise _validation(f"citation_base_url: {exc}") from exc
    else:
        citation_base_url = None

    original = (file.filename or "").strip()
    name = safe_filename(original)
    suffix = Path(name).suffix.lower()
    allowed = UPLOAD_SUFFIXES[resource_type]
    if suffix not in allowed:
        raise _unsupported(
            f"A {resource_type} upload must be one of: {', '.join(allowed)}"
        )

    cap_mb = settings.MAX_ZIP_MB if suffix == ".zip" else settings.MAX_UPLOAD_MB
    data = await read_upload_capped(file, cap_mb * MB)
    if suffix == ".zip":
        try:
            members = await asyncio.to_thread(read_zip, data)
        except UnsafeArchive as exc:
            raise _error(
                "UNSAFE_ARCHIVE", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY
            ) from exc
        except zipfile.BadZipFile as exc:
            raise _unsupported("The file is not a valid zip archive") from exc
        if not members:
            raise _unsupported("The archive holds no .md or .pdf files")
    elif suffix == ".pdf":
        try:
            pages = await pdf_page_count(data)
        except FetchError as exc:
            raise _unsupported(str(exc)) from exc
        if pages > MAX_PDF_PAGES:
            raise _unsupported(f"PDF has more than {MAX_PDF_PAGES} pages")

    await ensure_course(db, course_id)
    resource = CourseResource(
        course_id=course_id,
        resource_type=resource_type,
        source_kind="upload",
        title=title,
        citation_base_url=citation_base_url,
        original_filename=original[:255] or name,
        created_by_user_id=user_id,
        created_at=utcnow(),
    )
    db.add(resource)
    await db.flush()
    target = upload_dir(course_id, resource.id) / name
    try:
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)
        resource.upload_path = str(target)
        await db.flush()
        return await _resource_response(db, resource)
    except BaseException:
        # get_db rolls the row back, so the files must go too
        remove_upload_dir(course_id, resource.id)
        raise


async def delete_resource(db, course_id: int, resource_id: int) -> None:
    """Call under JOB_CREATE_LOCK. Removes the resource's chunks from every
    profile collection and refreshes each count. The router removes the
    upload directory after the commit."""
    resource = await get_resource(db, course_id, resource_id)
    if resource.resource_type == "historical_qa":
        raise _error(
            "PROTECTED_RESOURCE",
            "The course's historical Q&A resource can't be deleted",
            status.HTTP_409_CONFLICT,
        )
    busy = [
        j
        for j in await active_jobs(db, course_id)
        if j.scope == "profile" or j.resource_id == resource.id
    ]
    if busy:
        raise _job_running("A queued or running job includes this resource")
    profiles = await _profiles(db, course_id)
    try:
        client = await store.open_client()
        counts = await store.delete_resource_chunks(client, profiles, resource.id)
    except Exception as exc:  # noqa: BLE001
        # Earlier collections may already be cleared; a retry is idempotent
        raise _chroma_unavailable(
            exc,
            "The vector store is unreachable; the resource was kept but its "
            "chunks may be partly deleted. Try again.",
        ) from exc
    for profile in profiles:
        profile.chunk_count = counts.get(profile.id, profile.chunk_count)
    await db.delete(resource)
    await db.flush()


# Jobs


def _new_job(course_id, profile_id, scope, resource_id, user_id) -> IngestionJob:
    return IngestionJob(
        course_id=course_id,
        profile_id=profile_id,
        scope=scope,
        resource_id=resource_id,
        status="QUEUED",
        chunks_added=0,
        chunks_updated=0,
        chunks_deleted=0,
        created_by_user_id=user_id,
        created_at=utcnow(),
    )


async def create_profile_job(db, course_id: int, profile_id: int, user_id: str) -> dict:
    """Call under JOB_CREATE_LOCK. A QUEUED job over every course resource."""
    profile = await get_profile(db, course_id, profile_id)
    if any(j.profile_id == profile.id for j in await active_jobs(db, course_id)):
        raise _job_running("This profile already has a queued or running job")
    job = _new_job(course_id, profile.id, "profile", None, user_id)
    db.add(job)
    rids = (
        await db.execute(
            select(CourseResource.id).where(CourseResource.course_id == course_id)
        )
    ).scalars()
    for rid in rids:
        await set_state(db, rid, profile.id, status="QUEUED", error=None)
    await db.flush()
    return serialize_job(job, profile.name)


async def create_resource_jobs(
    db, course_id: int, resource_id: int, profile_ids: list[int] | None, user_id: str
) -> list[dict]:
    """Call under JOB_CREATE_LOCK. One QUEUED job per target profile, all or
    nothing: if any target is busy, no job is created."""
    resource = await get_resource(db, course_id, resource_id)
    profiles = await _profiles(db, course_id)
    if profile_ids is None:
        targets = profiles
        if not targets:
            raise _error(
                "NO_PROFILES",
                "Create an ingestion profile before syncing",
                status.HTTP_409_CONFLICT,
            )
    else:
        by_id = {p.id: p for p in profiles}
        if any(pid not in by_id for pid in profile_ids):
            raise _error(
                "PROFILE_NOT_FOUND", "Profile not found", status.HTTP_404_NOT_FOUND
            )
        targets = [by_id[pid] for pid in profile_ids]
    busy = {j.profile_id for j in await active_jobs(db, course_id)}
    if busy & {p.id for p in targets}:
        raise _job_running("A target profile already has a queued or running job")
    jobs = []
    for profile in targets:
        job = _new_job(course_id, profile.id, "resource", resource.id, user_id)
        db.add(job)
        jobs.append((job, profile.name))
        await set_state(db, resource.id, profile.id, status="QUEUED", error=None)
    await db.flush()
    return [serialize_job(job, name) for job, name in jobs]


async def list_jobs(
    db, course_id: int, status_filter: str | None, limit: int
) -> list[dict]:
    query = (
        select(IngestionJob, IngestionProfile.name)
        .join(IngestionProfile, IngestionProfile.id == IngestionJob.profile_id)
        .where(IngestionJob.course_id == course_id)
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
        .limit(limit)
    )
    if status_filter:
        query = query.where(IngestionJob.status == status_filter)
    return [serialize_job(job, name) for job, name in (await db.execute(query)).all()]


async def get_job(db, course_id: int, job_id: int) -> dict:
    row = (
        await db.execute(
            select(IngestionJob, IngestionProfile.name)
            .join(IngestionProfile, IngestionProfile.id == IngestionJob.profile_id)
            .where(IngestionJob.id == job_id, IngestionJob.course_id == course_id)
        )
    ).first()
    if row is None:
        raise _error("JOB_NOT_FOUND", "Job not found", status.HTTP_404_NOT_FOUND)
    return serialize_job(*row)
