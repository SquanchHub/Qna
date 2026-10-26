"""RAG requests (design-rag.md §6). Responses are built by the serialize_*
helpers in services/rag/catalog.py, like qa_service's, because their shape
depends on the course's profiles."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

PROFILE_NAME = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_BAD_REF = re.compile(r"[\s:~^?*\[\\]|\.\.|@\{")
MAX_URL = 2048


def utc_z(value: datetime | None) -> str | None:
    """Stored naive UTC as ISO 8601 with a Z (design §6)."""
    if value is None:
        return None
    return value.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def check_http_url(url: str) -> str:
    """http(s) with a host, at most 2048 characters; raises ValueError."""
    url = url.strip()
    if len(url) > MAX_URL:
        raise ValueError(f"URL is longer than {MAX_URL} characters")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("must be an http or https URL")
    return url


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, pattern=PROFILE_NAME)


class ResourceRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["syllabus", "schedule", "repository"]
    title: str = Field(min_length=1, max_length=255)
    url: str
    git_ref: str | None = Field(default=None, max_length=255)
    subpath: str | None = Field(default=None, max_length=1024)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title is empty")
        return value

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return check_http_url(value)

    @field_validator("git_ref")
    @classmethod
    def _git_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _SHA.match(value):
            raise ValueError(
                "git_ref must be a branch or tag name; git clone --branch can't take a SHA"
            )
        if (
            not value
            or value.startswith(("-", "/"))
            or value.endswith(("/", ".", ".lock"))
            or _BAD_REF.search(value)
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("git_ref is not a valid branch or tag name")
        return value

    @field_validator("subpath")
    @classmethod
    def _subpath(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\\" in value or "\x00" in value or value.startswith("/"):
            raise ValueError("subpath must be a relative path inside the repository")
        parts = [p for p in value.split("/") if p not in ("", ".")]
        if ".." in parts:
            raise ValueError("subpath may not contain '..'")
        if not parts:
            raise ValueError("subpath is empty; omit it for the whole repository")
        return "/".join(parts)

    @model_validator(mode="after")
    def _repository_only(self) -> ResourceRegister:
        if self.resource_type == "repository":
            if urlsplit(self.url).scheme != "https":
                raise ValueError("repository URLs must use https")
        elif self.git_ref is not None or self.subpath is not None:
            raise ValueError("git_ref and subpath apply only to repositories")
        return self


class ResourceSync(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Omit for every profile; an empty list is an error (design §6)
    profile_ids: list[int] | None = Field(default=None, min_length=1)

    @field_validator("profile_ids")
    @classmethod
    def _dedupe(cls, value: list[int] | None) -> list[int] | None:
        return None if value is None else list(dict.fromkeys(value))


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompareRequest(BaseModel):
    """The harness's five fields, all required (design §4.4.5)."""

    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    ingestion_profile: str = Field(min_length=1, max_length=64)
    similarity_threshold: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    system_prompt: str = Field(min_length=1, max_length=8000)
    generation_model: str = Field(min_length=1, max_length=100)
