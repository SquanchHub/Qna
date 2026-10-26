"""Course resource helpers shared by bootstrap and the admin router."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.rag import HISTORICAL_QA_KEY, CourseResource

HISTORICAL_QA_TITLE = "Historical Q&A"


async def ensure_qa_resource(db: AsyncSession, course_id: int) -> bool:
    """Add the course's one historical-Q&A resource if it is missing (design
    §4.5.1). Flushes, never commits; returns True if a row was added.
    UNIQUE(course_id, singleton_key) rejects a concurrent duplicate."""
    existing = await db.execute(
        select(CourseResource.id).where(
            CourseResource.course_id == course_id,
            CourseResource.singleton_key == HISTORICAL_QA_KEY,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False
    db.add(
        CourseResource(
            course_id=course_id,
            resource_type="historical_qa",
            source_kind="internal",
            title=HISTORICAL_QA_TITLE,
            singleton_key=HISTORICAL_QA_KEY,
        )
    )
    await db.flush()
    return True
