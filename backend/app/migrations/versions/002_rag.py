"""RAG: AI posts, ai_status, ingestion profiles, resources, states and jobs

Hand-written (design-rag.md §5): autogenerate misses MySQL ENUM changes.
The AI system user and the historical-Q&A resources come from bootstrap.

MySQL commits each DDL statement implicitly, so a failure partway through
leaves the version at 001 with some changes applied. Drop whatever this
upgrade already created (tables, then columns) before running it again.

Revision ID: 002
Revises: 001
Create Date: 2026-10-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AI_USERNAME = "qna-ai-assistant"

AI_STATUSES = (
    "NONE",
    "PENDING",
    "ANSWERED",
    "NO_MATCH",
    "DECLINED",
    "SKIPPED",
    "FAILED",
)


def _created_by() -> sa.Column:
    return sa.Column(
        "created_by_user_id",
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
    )


def _course_id() -> sa.Column:
    return sa.Column(
        "course_id",
        sa.Integer,
        sa.ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.alter_column(
        "posts",
        "author_role",
        type_=sa.Enum("STUDENT", "STAFF", "AI", name="post_author_role"),
        existing_type=sa.Enum("STUDENT", "STAFF", name="post_author_role"),
        existing_nullable=False,
    )
    op.add_column("posts", sa.Column("citations", sa.JSON, nullable=True))
    op.add_column("posts", sa.Column("ai_model", sa.String(100), nullable=True))
    op.add_column("posts", sa.Column("ai_profile", sa.String(64), nullable=True))
    op.add_column(
        "questions",
        sa.Column(
            "ai_status",
            sa.Enum(*AI_STATUSES, name="question_ai_status"),
            nullable=False,
            server_default="NONE",
        ),
    )

    op.create_table(
        "ingestion_profiles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        _course_id(),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("preset", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(255), nullable=False),
        # MySQL TEXT takes no server default; the app writes "" when unused
        sa.Column("query_instruction", sa.Text, nullable=False),
        sa.Column("chunking", sa.JSON, nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        _created_by(),
        _created_at(),
        sa.UniqueConstraint("course_id", "name", name="uq_profile_course_name"),
    )

    op.create_table(
        "course_resources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        _course_id(),
        sa.Column(
            "resource_type",
            sa.Enum(
                "syllabus",
                "schedule",
                "repository",
                "historical_qa",
                name="resource_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "source_kind",
            sa.Enum("url", "upload", "internal", name="resource_source_kind"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("git_ref", sa.String(255), nullable=True),
        sa.Column("subpath", sa.String(1024), nullable=True),
        sa.Column("citation_base_url", sa.String(2048), nullable=True),
        sa.Column("upload_path", sa.String(1024), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("singleton_key", sa.String(32), nullable=True),
        _created_by(),
        _created_at(),
        sa.UniqueConstraint(
            "course_id", "singleton_key", name="uq_resource_course_singleton"
        ),
    )

    op.create_table(
        "resource_profile_states",
        sa.Column(
            "resource_id",
            sa.Integer,
            sa.ForeignKey("course_resources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("ingestion_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED", "RUNNING", "READY", "FAILED", name="resource_state_status"
            ),
            nullable=False,
        ),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_commit_sha", sa.String(40), nullable=True),
        sa.Column("last_synced_at", sa.DateTime, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        _course_id(),
        sa.Column(
            "profile_id",
            sa.Integer,
            sa.ForeignKey("ingestion_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scope", sa.Enum("resource", "profile", name="job_scope"), nullable=False
        ),
        sa.Column(
            "resource_id",
            sa.Integer,
            sa.ForeignKey("course_resources.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", name="job_status"),
            nullable=False,
        ),
        sa.Column("chunks_added", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunks_updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunks_deleted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        _created_by(),
        _created_at(),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_jobs_course_created", "ingestion_jobs", ["course_id", "created_at"]
    )


def downgrade() -> None:
    # AI posts can't fit the two-value enum; the AI user then has no posts
    op.execute("DELETE FROM posts WHERE author_role = 'AI'")
    op.execute(
        sa.text("DELETE FROM users WHERE username = :name").bindparams(name=AI_USERNAME)
    )

    # Dropping the table drops ix_jobs_course_created, which MySQL won't drop
    # alone while the course_id foreign key relies on it
    op.drop_table("ingestion_jobs")
    op.drop_table("resource_profile_states")
    op.drop_table("course_resources")
    op.drop_table("ingestion_profiles")

    op.drop_column("questions", "ai_status")
    op.drop_column("posts", "ai_profile")
    op.drop_column("posts", "ai_model")
    op.drop_column("posts", "citations")
    op.alter_column(
        "posts",
        "author_role",
        type_=sa.Enum("STUDENT", "STAFF", name="post_author_role"),
        existing_type=sa.Enum("STUDENT", "STAFF", "AI", name="post_author_role"),
        existing_nullable=False,
    )
