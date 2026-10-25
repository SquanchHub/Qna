"""RAG ingestion state (design-rag.md §5). Chunks live only in ChromaDB."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

RESOURCE_TYPES = ("syllabus", "schedule", "repository", "historical_qa")
SOURCE_KINDS = ("url", "upload", "internal")
STATE_STATUSES = ("QUEUED", "RUNNING", "READY", "FAILED")
JOB_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")
JOB_SCOPES = ("resource", "profile")

# course_resources.singleton_key of the one historical-Q&A resource per course
HISTORICAL_QA_KEY = "historical_qa"


class IngestionProfile(Base):
    """A named chunking + embedding configuration with its own Chroma collection."""

    __tablename__ = "ingestion_profiles"
    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_profile_course_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    preset: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    query_instruction: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chunking: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Display only; availability checks use Chroma count()
    chunk_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    states: Mapped[list[ResourceProfileState]] = relationship(
        "ResourceProfileState", back_populates="profile", passive_deletes=True
    )

    @property
    def collection_name(self) -> str:
        return f"c{self.course_id}_p{self.id}"


class CourseResource(Base):
    """A syllabus, schedule, repository or the course's historical Q&A."""

    __tablename__ = "course_resources"
    __table_args__ = (
        # MySQL allows many NULLs, so only the historical-Q&A row is unique
        UniqueConstraint(
            "course_id", "singleton_key", name="uq_resource_course_singleton"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(
        Enum(*RESOURCE_TYPES, name="resource_type"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(
        Enum(*SOURCE_KINDS, name="resource_source_kind"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    git_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subpath: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    citation_base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    upload_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    singleton_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    states: Mapped[list[ResourceProfileState]] = relationship(
        "ResourceProfileState", back_populates="resource", passive_deletes=True
    )


class ResourceProfileState(Base):
    """How far one resource has been ingested into one profile."""

    __tablename__ = "resource_profile_states"

    resource_id: Mapped[int] = mapped_column(
        ForeignKey("course_resources.id", ondelete="CASCADE"), primary_key=True
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        Enum(*STATE_STATUSES, name="resource_state_status"), nullable=False
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    last_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    resource: Mapped[CourseResource] = relationship(
        "CourseResource", back_populates="states"
    )
    profile: Mapped[IngestionProfile] = relationship(
        "IngestionProfile", back_populates="states"
    )


class IngestionJob(Base):
    """One sync run: every resource of a profile, or one resource."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_jobs_course_created", "course_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_profiles.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(
        Enum(*JOB_SCOPES, name="job_scope"), nullable=False
    )
    # Set exactly when scope == "resource"
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_resources.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum(*JOB_STATUSES, name="job_status"), nullable=False
    )
    chunks_added: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_updated: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_deleted: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
