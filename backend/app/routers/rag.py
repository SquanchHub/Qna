import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import CourseMember, require_course_staff, require_rag_viewer
from ..config import settings
from ..database import get_db
from ..models.user import User
from ..schemas.rag import (
    CompareRequest,
    EmptyBody,
    ProfileCreate,
    ResourceRegister,
    ResourceSync,
)
from ..services.rag import catalog, clients, pipeline
from ..services.rag.ingest import schedule_job
from ..services.rag.locks import JOB_CREATE_LOCK

router = APIRouter(tags=["rag"])

Staff = Annotated[CourseMember, Depends(require_course_staff)]
Db = Annotated[AsyncSession, Depends(get_db)]


async def get_rag_http() -> AsyncIterator[httpx.AsyncClient]:
    """One client per request, so it is never bound to another event loop."""
    async with httpx.AsyncClient(timeout=clients.HEALTH_TIMEOUT_S) as http:
        yield http


@router.get("/rag/health")
async def rag_health(
    _: Annotated[User, Depends(require_rag_viewer)],
    http: Annotated[httpx.AsyncClient, Depends(get_rag_http)],
) -> dict:
    """Service status for ADMIN or staff of any course; never 5xx (design §6)."""
    ollama, infinity, chroma = await asyncio.gather(
        clients.ollama_health(http),
        clients.infinity_health(http),
        clients.chroma_health(http),
    )
    return {
        "ollama": ollama,
        "infinity": infinity,
        "chroma": chroma,
        "gitlab_token_configured": bool(settings.GITLAB_TOKEN),
        "live_enabled": settings.RAG_LIVE_ENABLED,
        "defaults": {
            "profile": settings.RAG_DEFAULT_PROFILE,
            "threshold": settings.RAG_DEFAULT_THRESHOLD,
            "model": settings.RAG_DEFAULT_MODEL,
        },
        "limits": {
            "max_upload_mb": settings.MAX_UPLOAD_MB,
            "max_zip_mb": settings.MAX_ZIP_MB,
        },
    }


# Course routes (design §6). require_course_staff runs before any handler
# code, so a denied request never writes anything.
COURSE = "/courses/{course_id}/rag"


@asynccontextmanager
async def job_lock(db: AsyncSession) -> AsyncIterator[None]:
    """JOB_CREATE_LOCK, then a fresh transaction. The auth dependencies already
    read on this session, and under MySQL's REPEATABLE READ the busy check
    would otherwise miss jobs committed while this request waited."""
    async with JOB_CREATE_LOCK:
        await db.commit()
        yield


@router.get(f"{COURSE}/presets")
async def list_presets(course_id: int, _: Staff) -> list[dict]:
    return await catalog.list_presets()


@router.get(f"{COURSE}/profiles")
async def list_profiles(course_id: int, _: Staff, db: Db) -> list[dict]:
    return await catalog.list_profiles(db, course_id)


@router.post(f"{COURSE}/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(
    course_id: int, body: ProfileCreate, member: Staff, db: Db
) -> dict:
    return await catalog.create_profile(db, course_id, member.user.id, body)


@router.delete(
    f"{COURSE}/profiles/{{profile_id}}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_profile(course_id: int, profile_id: int, _: Staff, db: Db) -> Response:
    async with job_lock(db):
        await catalog.delete_profile(db, course_id, profile_id)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    f"{COURSE}/profiles/{{profile_id}}/sync", status_code=status.HTTP_202_ACCEPTED
)
async def sync_profile(
    course_id: int,
    profile_id: int,
    member: Staff,
    db: Db,
    _body: EmptyBody | None = None,
) -> dict:
    async with job_lock(db):
        job = await catalog.create_profile_job(
            db, course_id, profile_id, member.user.id
        )
        await db.commit()
    schedule_job(job["id"])
    return job


@router.get(f"{COURSE}/resources")
async def list_resources(course_id: int, _: Staff, db: Db) -> list[dict]:
    return await catalog.list_resources(db, course_id)


@router.post(f"{COURSE}/resources", status_code=status.HTTP_201_CREATED)
async def register_resource(
    course_id: int, body: ResourceRegister, member: Staff, db: Db
) -> dict:
    return await catalog.register_resource(db, course_id, member.user.id, body)


@router.post(f"{COURSE}/resources/upload", status_code=status.HTTP_201_CREATED)
async def upload_resource(
    course_id: int,
    member: Staff,
    db: Db,
    resource_type: Annotated[str, Form()],
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    citation_base_url: Annotated[str | None, Form()] = None,
) -> dict:
    resource = await catalog.upload_resource(
        db, course_id, member.user.id, resource_type, title, citation_base_url, file
    )
    try:
        await db.commit()
    except Exception:
        catalog.remove_upload_dir(course_id, resource["id"])
        raise
    return resource


@router.delete(
    f"{COURSE}/resources/{{resource_id}}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_resource(
    course_id: int, resource_id: int, _: Staff, db: Db
) -> Response:
    async with job_lock(db):
        await catalog.delete_resource(db, course_id, resource_id)
        await db.commit()
    # Files go only after the row is gone, so a failed commit keeps both
    catalog.remove_upload_dir(course_id, resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    f"{COURSE}/resources/{{resource_id}}/sync", status_code=status.HTTP_202_ACCEPTED
)
async def sync_resource(
    course_id: int,
    resource_id: int,
    member: Staff,
    db: Db,
    body: ResourceSync | None = None,
) -> dict:
    profile_ids = body.profile_ids if body else None
    async with job_lock(db):
        jobs = await catalog.create_resource_jobs(
            db, course_id, resource_id, profile_ids, member.user.id
        )
        await db.commit()
    for job in jobs:
        schedule_job(job["id"])
    return {"jobs": jobs}


@router.get(f"{COURSE}/jobs")
async def list_jobs(
    course_id: int,
    _: Staff,
    db: Db,
    status_filter: Annotated[
        Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict]:
    return await catalog.list_jobs(db, course_id, status_filter, limit)


@router.get(f"{COURSE}/jobs/{{job_id}}")
async def get_job(course_id: int, job_id: int, _: Staff, db: Db) -> dict:
    return await catalog.get_job(db, course_id, job_id)


@router.post(f"{COURSE}/compare")
async def compare(course_id: int, body: CompareRequest, _: Staff, db: Db) -> dict:
    """Dry run for eval/compare_harness.py: retrieval and generation with the
    request's settings, creating no Question or Post (design §4.4.5)."""
    return await pipeline.compare(db, course_id, body)
