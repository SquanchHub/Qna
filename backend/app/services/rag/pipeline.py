"""Retrieval, generation and the compare dry run (design-rag.md §4.4.3–§4.4.5).

Shared by POST /rag/compare and the live answer job. This module must never
import qa_service: compare is a dry run that only reads the profile row and
queries Chroma, and the import boundary is unit-tested. Upstream failures
become 503 UPSTREAM_UNAVAILABLE or 504 UPSTREAM_TIMEOUT.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter

import httpx
import structlog
from chromadb.errors import NotFoundError
from fastapi import status
from sqlalchemy import select

from ...common.exceptions import (
    GatewayTimeoutError,
    QnaError,
    ServiceUnavailableError,
    UnprocessableError,
)
from ...config import settings
from ...models.rag import IngestionProfile
from ...schemas.rag import CompareRequest
from . import embeddings, store
from .locks import GENERATION_LOCK, acquire
from .metrics import cpu_percent, cpu_snapshot
from .prompts import user_message

logger = structlog.get_logger()

# Each Chroma step (open + count, then query); the design budgets about 1 s
# for the query. With the other bounds, compare's worst case stays under the
# harness's 180 s: 5 + 5 (tags) + 3 (Infinity /models) + 15 + 5 + 30 + 100 = 163.
CHROMA_TIMEOUT_S = 5.0
TAGS_TIMEOUT_S = 5.0
# A backstop over the whole request, in case the sum above is ever wrong
COMPARE_DEADLINE_S = 170.0
# Fixed before calibration and the committed run (§4.4.4)
GENERATION_OPTIONS = {
    "temperature": 0,
    "seed": 42,
    "num_ctx": 4096,
    "num_predict": 300,
}


@dataclass(frozen=True)
class ProfileSnap:
    """What retrieval needs from a profile, as plain values: no ORM object
    outlives its session."""

    id: int
    name: str
    embedding_model: str
    query_instruction: str
    collection_name: str

    @classmethod
    def of(cls, profile: IngestionProfile) -> ProfileSnap:
        return cls(
            profile.id,
            profile.name,
            profile.embedding_model,
            profile.query_instruction or "",
            profile.collection_name,
        )


@dataclass(frozen=True)
class Hit:
    score: float  # raw 1 - cosine distance; rounded only for display
    document: str
    metadata: dict


@dataclass(frozen=True)
class Retrieval:
    matched: bool
    hits: list[Hit]  # above the threshold, highest first
    embedding_ms: float
    retrieval_ms: float


async def _upstream(service: str, coro, timeout: float | None = None):
    """Await an upstream call, mapping its failures to 503/504 app errors."""
    try:
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout)
    except QnaError:
        raise
    except (TimeoutError, httpx.TimeoutException) as exc:
        logger.warning("rag_upstream_timeout", service=service)
        raise GatewayTimeoutError("UPSTREAM_TIMEOUT", f"{service} timed out") from exc
    except Exception as exc:  # noqa: BLE001 - refused, 5xx, bad payload
        logger.warning("rag_upstream_failed", service=service, error=type(exc).__name__)
        raise ServiceUnavailableError(
            "UPSTREAM_UNAVAILABLE", f"{service} is unavailable ({type(exc).__name__})"
        ) from exc


async def load_snap(db, course_id: int, name: str) -> ProfileSnap | None:
    result = await db.execute(
        select(IngestionProfile).where(
            IngestionProfile.course_id == course_id, IngestionProfile.name == name
        )
    )
    profile = result.scalar_one_or_none()
    return ProfileSnap.of(profile) if profile is not None else None


async def open_snap_collection(snap: ProfileSnap):
    """(collection, count), or (None, 0) for a profile that was never synced."""

    async def call():
        client = await store.open_client()
        try:
            coll = await client.get_collection(
                name=snap.collection_name, embedding_function=None
            )
        except NotFoundError:
            # Only "no such collection" means empty; anything else is a 503
            return None, 0
        return coll, await coll.count()

    return await _upstream("Chroma", call(), CHROMA_TIMEOUT_S)


async def retrieve(
    snap: ProfileSnap,
    query: str,
    threshold: float,
    coll,
    count: int,
    embed_timeout: float,
) -> Retrieval:
    t0 = perf_counter()
    vectors = await _upstream(
        "Infinity",
        embeddings.embed(
            snap.embedding_model,
            [snap.query_instruction + query],
            timeout=embed_timeout,
        ),
    )
    t1 = perf_counter()

    async def query() -> list[Hit]:
        # Parsed inside the guard, so a malformed reply is a 503, not a 500
        res = await coll.query(
            query_embeddings=[vectors[0]],
            n_results=max(1, min(settings.RAG_TOP_K, count)),
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(1.0 - distance, document or "", metadata or {})
            for document, metadata, distance in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]

    hits = await _upstream("Chroma", query(), CHROMA_TIMEOUT_S)
    t2 = perf_counter()
    hits.sort(key=lambda h: h.score, reverse=True)
    kept = [h for h in hits if h.score >= threshold]
    return Retrieval(bool(kept), kept, (t1 - t0) * 1000, (t2 - t1) * 1000)


def model_available(name: str, pulled: set[str]) -> bool:
    """An untagged name means `:latest`, never another tag (§4.4.5 step 3)."""
    return name in pulled or (":" not in name and f"{name}:latest" in pulled)


async def pulled_models() -> set[str]:
    async def call():
        async with httpx.AsyncClient(timeout=TAGS_TIMEOUT_S) as http:
            r = await http.get(f"{settings.OLLAMA_URL}/api/tags")
        r.raise_for_status()
        return {m["name"] for m in r.json()["models"]}

    return await _upstream("Ollama", call(), TAGS_TIMEOUT_S)


def _not_pulled(model: str) -> UnprocessableError:
    return UnprocessableError(
        "MODEL_NOT_AVAILABLE", f"Model {model!r} is not pulled into Ollama"
    )


async def generate(model: str, system_prompt: str, message: str, timeout: float) -> str:
    """One non-streaming Ollama chat call. Callers hold GENERATION_LOCK."""

    async def call():
        async with httpx.AsyncClient(timeout=timeout) as http:
            r = await http.post(
                f"{settings.OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "stream": False,
                    "options": GENERATION_OPTIONS,
                },
            )
        if r.status_code == status.HTTP_404_NOT_FOUND:
            raise _not_pulled(model)  # removed after the tag check
        r.raise_for_status()
        return r.json()["message"]["content"]

    return await _upstream("Ollama", call(), timeout)


def _chunk(hit: Hit) -> dict:
    return {
        "resource_type": hit.metadata.get("resource_type"),
        "source_url": hit.metadata.get("source_url"),
        "similarity_score": round(hit.score, 4),
        "text": hit.document,
    }


async def compare(db, course_id: int, req: CompareRequest) -> dict:
    """The fixed compare contract (§4.4.5). Writes nothing anywhere."""
    try:
        async with asyncio.timeout(COMPARE_DEADLINE_S):
            return await _compare(db, course_id, req)
    except TimeoutError as exc:
        raise GatewayTimeoutError(
            "UPSTREAM_TIMEOUT", "Compare exceeded its time budget"
        ) from exc


async def _compare(db, course_id: int, req: CompareRequest) -> dict:
    snap = await load_snap(db, course_id, req.ingestion_profile)
    await db.rollback()  # the rest never touches MySQL; release the connection
    if snap is None:
        raise QnaError(
            "PROFILE_NOT_FOUND",
            f"No profile named {req.ingestion_profile!r} in this course",
            status.HTTP_404_NOT_FOUND,
        )
    coll, count = await open_snap_collection(snap)
    if count == 0:
        raise QnaError(
            "PROFILE_EMPTY",
            f"Profile {snap.name!r} has no chunks; sync it first",
            status.HTTP_409_CONFLICT,
        )
    # Before retrieval, so an off-topic question still can't get a fallback
    if not model_available(req.generation_model, await pulled_models()):
        raise _not_pulled(req.generation_model)
    served = await embeddings.served_models()
    if served is None:
        raise ServiceUnavailableError("UPSTREAM_UNAVAILABLE", "Infinity is unreachable")
    if snap.embedding_model not in served:
        raise QnaError(
            "EMBEDDING_MODEL_UNAVAILABLE",
            f"Infinity no longer serves {snap.embedding_model!r}",
            status.HTTP_409_CONFLICT,
        )

    a = cpu_snapshot()
    r = await retrieve(
        snap,
        req.question,
        req.similarity_threshold,
        coll,
        count,
        settings.RAG_COMPARE_EMBED_TIMEOUT_S,
    )
    windows = [(a, cpu_snapshot())]
    answer, generation_ms = None, 0
    if r.matched:
        message = user_message(r.hits, req.question)
        acquired = False
        try:
            async with acquire(GENERATION_LOCK, settings.RAG_COMPARE_LOCK_WAIT_S):
                acquired = True
                c, t = cpu_snapshot(), perf_counter()
                answer = await generate(
                    req.generation_model,
                    req.system_prompt,
                    message,
                    settings.RAG_COMPARE_GENERATION_TIMEOUT_S,
                )
                generation_ms = max(1, round((perf_counter() - t) * 1000))
                windows.append((c, cpu_snapshot()))
        except TimeoutError as exc:
            if acquired:
                raise
            raise ServiceUnavailableError(
                "GENERATION_BUSY", "Another generation is running; retry shortly"
            ) from exc

    return {
        "matched": r.matched,
        "retrieved_chunks": [_chunk(h) for h in r.hits],
        "answer": answer,
        "metrics": {
            "embedding_time_ms": round(r.embedding_ms),
            "retrieval_time_ms": round(r.retrieval_ms),
            "generation_time_ms": generation_ms,
            "cpu_percent": cpu_percent(windows),
        },
    }
