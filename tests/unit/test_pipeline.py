"""Retrieval, generation and the compare endpoint's logic (design-rag.md §4.4.3–§4.4.5).

Upstream services are patched at pipeline's module attributes; the HTTP
shape of the Ollama call is checked on an httpx.MockTransport.
"""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.common.exceptions import QnaError
from app.config import settings
from app.schemas.rag import CompareRequest
from app.services.rag import embeddings, locks, pipeline
from app.services.rag.pipeline import Hit, ProfileSnap, model_available

SNAP = ProfileSnap(
    id=3,
    name="sliding-window",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    query_instruction="",
    collection_name="c1_p3",
)
BACKEND = Path(__file__).resolve().parents[2] / "backend"


def meta(i: int, **extra) -> dict:
    return {
        "resource_type": "repo_markdown",
        "source_url": f"https://e.com/{i}",
        "title": f"T{i}",
        "rel_path": "a.md",
        "line_start": 1,
        "line_end": 2,
        **extra,
    }


class FakeCollection:
    def __init__(self, distances: list[float]):
        self.distances = distances
        self.queries: list[dict] = []

    async def query(self, **kwargs):
        self.queries.append(kwargs)
        n = kwargs["n_results"]
        d = self.distances[:n]
        return {
            "ids": [[f"id{i}" for i in range(len(d))]],
            "documents": [[f"doc{i}" for i in range(len(d))]],
            "metadatas": [[meta(i) for i in range(len(d))]],
            "distances": [d],
        }

    async def count(self):
        return len(self.distances)


@pytest.fixture()
def embedded(monkeypatch):
    calls = []

    async def fake_embed(model, texts, timeout=None):
        calls.append((model, texts, timeout))
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(embeddings, "embed", fake_embed)
    return calls


# --- retrieve -------------------------------------------------------------


async def test_similarity_is_one_minus_distance_sorted(embedded):
    coll = FakeCollection([0.4, 0.1, 0.3])
    r = await pipeline.retrieve(SNAP, "q", 0.0, coll, 3, embed_timeout=5)
    assert [round(h.score, 6) for h in r.hits] == [0.9, 0.7, 0.6]
    assert r.matched is True
    assert isinstance(r.embedding_ms, float) and isinstance(r.retrieval_ms, float)


async def test_threshold_compares_the_raw_score(embedded):
    # 0.50004 and 0.50002 both display as 0.5; only the raw one decides
    coll = FakeCollection([1 - 0.50004, 1 - 0.50002])
    r = await pipeline.retrieve(SNAP, "q", 0.50003, coll, 2, embed_timeout=5)
    assert len(r.hits) == 1 and r.hits[0].score == pytest.approx(0.50004)
    r = await pipeline.retrieve(SNAP, "q", 0.9, coll, 2, embed_timeout=5)
    assert r.matched is False and r.hits == []


async def test_query_instruction_and_n_results(embedded, monkeypatch):
    monkeypatch.setattr(settings, "RAG_TOP_K", 4)
    snap = ProfileSnap(**{**SNAP.__dict__, "query_instruction": "Query: "})
    coll = FakeCollection([0.1, 0.2])
    await pipeline.retrieve(snap, "When?", 0.0, coll, 2, embed_timeout=7)
    assert embedded == [(snap.embedding_model, ["Query: When?"], 7)]
    assert coll.queries[0]["n_results"] == 2
    assert set(coll.queries[0]["include"]) == {"documents", "metadatas", "distances"}

    coll = FakeCollection([0.1] * 10)
    await pipeline.retrieve(SNAP, "q", 0.0, coll, 10, embed_timeout=7)
    assert coll.queries[0]["n_results"] == 4


async def test_embed_errors_map_to_upstream_codes(monkeypatch):
    async def slow(*a, **k):
        raise asyncio.TimeoutError

    async def down(*a, **k):
        raise httpx.ConnectError("refused")

    for fake, status, code in ((slow, 504, "UPSTREAM_TIMEOUT"), (down, 503, "UPSTREAM_UNAVAILABLE")):
        monkeypatch.setattr(embeddings, "embed", fake)
        with pytest.raises(QnaError) as e:
            await pipeline.retrieve(SNAP, "q", 0.0, FakeCollection([0.1]), 1, embed_timeout=1)
        assert (e.value.status_code, e.value.code) == (status, code)


# --- models and generation -----------------------------------------------


def test_model_available():
    pulled = {"qwen2.5:1.5b", "llama3.2:latest"}
    assert model_available("qwen2.5:1.5b", pulled)
    assert model_available("llama3.2", pulled)
    assert not model_available("qwen2.5", pulled)  # never another tag
    assert not model_available("nonexistent:1b", pulled)


_REAL_CLIENT = httpx.AsyncClient


def _ollama(monkeypatch, handler):
    real = _REAL_CLIENT

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline.httpx, "AsyncClient", client)


async def test_generate_request_shape(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": " Hi. "}})

    _ollama(monkeypatch, handler)
    out = await pipeline.generate("qwen2.5:1.5b", "SYS", "USER", timeout=5)
    assert out == " Hi. "
    assert seen["url"] == f"{settings.OLLAMA_URL}/api/chat"
    body = seen["body"]
    assert body["model"] == "qwen2.5:1.5b" and body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 300}
    assert "keep_alive" not in body


@pytest.mark.parametrize(
    "response, status, code",
    [
        (httpx.Response(500, text="boom"), 503, "UPSTREAM_UNAVAILABLE"),
        (httpx.Response(404, json={"error": "model not found"}), 422, "MODEL_NOT_AVAILABLE"),
    ],
)
async def test_generate_errors(monkeypatch, response, status, code):
    _ollama(monkeypatch, lambda request: response)
    with pytest.raises(QnaError) as e:
        await pipeline.generate("m", "s", "u", timeout=5)
    assert (e.value.status_code, e.value.code) == (status, code)


async def test_generate_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    _ollama(monkeypatch, handler)
    with pytest.raises(QnaError) as e:
        await pipeline.generate("m", "s", "u", timeout=5)
    assert (e.value.status_code, e.value.code) == (504, "UPSTREAM_TIMEOUT")


async def test_pulled_models(monkeypatch):
    _ollama(monkeypatch, lambda r: httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]}))
    assert await pipeline.pulled_models() == {"qwen2.5:1.5b"}
    _ollama(monkeypatch, lambda r: httpx.Response(502))
    with pytest.raises(QnaError) as e:
        await pipeline.pulled_models()
    assert e.value.code == "UPSTREAM_UNAVAILABLE"


# --- compare ----------------------------------------------------------------


class FakeDb:
    def __init__(self, log):
        self.log = log

    async def rollback(self):
        self.log.append("rollback")


def request(**overrides) -> CompareRequest:
    body = {
        "question": "What does Quindlewort require?",
        "ingestion_profile": "sliding-window",
        "similarity_threshold": 0.5,
        "system_prompt": "SYS",
        "generation_model": "qwen2.5:1.5b",
    }
    body.update(overrides)
    return CompareRequest(**body)


@pytest.fixture()
def world(monkeypatch):
    """Every collaborator of compare(), healthy by default; tests break one."""
    log: list = []
    state = {
        "snap": SNAP,
        "coll": FakeCollection([0.2, 0.3]),
        "count": 2,
        "pulled": {"qwen2.5:1.5b"},
        "served": {SNAP.embedding_model},
        "hits": [Hit(0.81234, "doc0", meta(0)), Hit(0.7, "doc1", meta(1))],
        "answer": "Three handshakes.",
    }

    async def load_snap(db, course_id, name):
        log.append("load")
        return state["snap"] if name == SNAP.name else None

    async def open_coll(snap):
        log.append("open")
        return state["coll"], state["count"]

    async def pulled():
        log.append("tags")
        if isinstance(state["pulled"], Exception):
            raise state["pulled"]
        return state["pulled"]

    async def served():
        log.append("served")
        return state["served"]

    async def retrieve(snap, query, threshold, coll, count, embed_timeout):
        log.append(("retrieve", threshold, embed_timeout))
        if isinstance(state["hits"], Exception):
            raise state["hits"]
        hits = [h for h in state["hits"] if h.score >= threshold]
        return pipeline.Retrieval(bool(hits), hits, 12.4, 3.6)

    async def generate(model, system_prompt, message, timeout):
        log.append(("generate", model, system_prompt, timeout))
        if isinstance(state["answer"], Exception):
            raise state["answer"]
        await asyncio.sleep(0.002)
        return state["answer"]

    monkeypatch.setattr(pipeline, "load_snap", load_snap)
    monkeypatch.setattr(pipeline, "open_snap_collection", open_coll)
    monkeypatch.setattr(pipeline, "pulled_models", pulled)
    monkeypatch.setattr(pipeline.embeddings, "served_models", served)
    monkeypatch.setattr(pipeline, "retrieve", retrieve)
    monkeypatch.setattr(pipeline, "generate", generate)
    monkeypatch.setattr(pipeline, "GENERATION_LOCK", asyncio.Semaphore(1))
    state["log"] = log
    state["db"] = FakeDb(log)
    return state


async def run(world, **overrides):
    return await pipeline.compare(world["db"], 1, request(**overrides))


async def expect_error(world, status, code, **overrides):
    with pytest.raises(QnaError) as e:
        await run(world, **overrides)
    assert (e.value.status_code, e.value.code) == (status, code)


async def test_matched_response_is_the_fixed_contract(world):
    out = await run(world)
    assert set(out) == {"matched", "retrieved_chunks", "answer", "metrics"}
    assert out["matched"] is True
    assert out["answer"] == "Three handshakes."
    assert out["retrieved_chunks"][0] == {
        "resource_type": "repo_markdown",
        "source_url": "https://e.com/0",
        "similarity_score": 0.8123,
        "text": "doc0",
    }
    m = out["metrics"]
    assert set(m) == {"embedding_time_ms", "retrieval_time_ms", "generation_time_ms", "cpu_percent"}
    assert (m["embedding_time_ms"], m["retrieval_time_ms"]) == (12, 4)
    assert isinstance(m["generation_time_ms"], int) and m["generation_time_ms"] >= 1
    assert isinstance(m["cpu_percent"], float) and 0.0 <= m["cpu_percent"] <= 100.0
    assert ("generate", "qwen2.5:1.5b", "SYS", settings.RAG_COMPARE_GENERATION_TIMEOUT_S) in world["log"]
    assert ("retrieve", 0.5, settings.RAG_COMPARE_EMBED_TIMEOUT_S) in world["log"]


async def test_rollback_comes_before_any_upstream_call(world):
    await run(world)
    log = world["log"]
    assert log[:2] == ["load", "rollback"]


async def test_no_match_never_generates(world):
    out = await run(world, similarity_threshold=0.95)
    assert out["matched"] is False
    assert out["retrieved_chunks"] == [] and out["answer"] is None
    assert out["metrics"]["generation_time_ms"] == 0
    assert not any(isinstance(e, tuple) and e[0] == "generate" for e in world["log"])


async def test_unknown_profile(world):
    await expect_error(world, 404, "PROFILE_NOT_FOUND", ingestion_profile="nope")


@pytest.mark.parametrize("coll", [None, FakeCollection([])])
async def test_empty_or_unsynced_profile(world, coll):
    world["coll"], world["count"] = coll, 0
    await expect_error(world, 409, "PROFILE_EMPTY")


async def test_model_checked_before_retrieval(world):
    await expect_error(world, 422, "MODEL_NOT_AVAILABLE", generation_model="nonexistent:1b")
    assert not any(isinstance(e, tuple) and e[0] == "retrieve" for e in world["log"])


async def test_ollama_down_at_tag_check(world):
    world["pulled"] = QnaError("UPSTREAM_UNAVAILABLE", "down", 503)
    await expect_error(world, 503, "UPSTREAM_UNAVAILABLE")


async def test_embedding_model_no_longer_served(world):
    world["served"] = {"BAAI/bge-small-en-v1.5"}
    await expect_error(world, 409, "EMBEDDING_MODEL_UNAVAILABLE")


async def test_infinity_unreachable(world):
    world["served"] = None
    await expect_error(world, 503, "UPSTREAM_UNAVAILABLE")


async def test_upstream_errors_propagate(world):
    world["hits"] = QnaError("UPSTREAM_TIMEOUT", "slow", 504)
    await expect_error(world, 504, "UPSTREAM_TIMEOUT")


async def test_generation_busy(world, monkeypatch):
    monkeypatch.setattr(settings, "RAG_COMPARE_LOCK_WAIT_S", 0.05)
    await pipeline.GENERATION_LOCK.acquire()
    try:
        await expect_error(world, 503, "GENERATION_BUSY")
    finally:
        pipeline.GENERATION_LOCK.release()
    # The lock is free again and usable
    assert (await run(world))["matched"] is True


async def test_lock_is_released_when_generation_fails(world):
    world["answer"] = QnaError("UPSTREAM_TIMEOUT", "slow", 504)
    await expect_error(world, 504, "UPSTREAM_TIMEOUT")
    assert not pipeline.GENERATION_LOCK.locked()


async def test_acquire_times_out_and_leaves_lock_consistent():
    lock = asyncio.Semaphore(1)
    await lock.acquire()
    with pytest.raises(asyncio.TimeoutError):
        async with locks.acquire(lock, 0.01):
            pass
    lock.release()
    async with locks.acquire(lock, 0.01):
        assert lock.locked()
    assert not lock.locked()


# --- import boundary (design §4.4.5 "Dry run") ------------------------------


def test_pipeline_never_imports_qa_service():
    tree = ast.parse((BACKEND / "app/services/rag/pipeline.py").read_text())
    imported = [
        name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in [getattr(node, "module", None) or ""] + [a.name for a in node.names]
    ]
    assert not [n for n in imported if "qa_service" in n], imported
    code = (
        "import sys, app.services.rag.pipeline; "
        "print('app.services.qa_service' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"


# --- upstream error mapping -------------------------------------------------


@pytest.mark.parametrize(
    "exc, status, code",
    [
        (TimeoutError(), 504, "UPSTREAM_TIMEOUT"),
        (httpx.ReadTimeout("slow"), 504, "UPSTREAM_TIMEOUT"),
        (httpx.ReadError("reset"), 503, "UPSTREAM_UNAVAILABLE"),
        (httpx.RemoteProtocolError("bad"), 503, "UPSTREAM_UNAVAILABLE"),
        (KeyError("data"), 503, "UPSTREAM_UNAVAILABLE"),
        (ValueError("Could not connect to a Chroma server"), 503, "UPSTREAM_UNAVAILABLE"),
    ],
)
async def test_upstream_mapping(exc, status, code):
    async def fail():
        raise exc

    with pytest.raises(QnaError) as e:
        await pipeline._upstream("X", fail(), 1)
    assert (e.value.status_code, e.value.code) == (status, code)


async def test_upstream_bound_is_enforced():
    with pytest.raises(QnaError) as e:
        await pipeline._upstream("X", asyncio.sleep(1), 0.01)
    assert e.value.code == "UPSTREAM_TIMEOUT"


class FakeClient:
    def __init__(self, exc=None):
        self.exc = exc

    async def get_collection(self, name, embedding_function=None):
        if self.exc:
            raise self.exc
        return FakeCollection([0.1, 0.2, 0.3])


@pytest.mark.parametrize(
    "client_exc, expected",
    [(None, 3), ("notfound", 0), (ValueError("unrelated"), "503")],
)
async def test_open_snap_collection(monkeypatch, client_exc, expected):
    from chromadb.errors import NotFoundError

    exc = NotFoundError("missing") if client_exc == "notfound" else client_exc

    async def open_client():
        return FakeClient(exc)

    monkeypatch.setattr(pipeline.store, "open_client", open_client)
    if expected == "503":
        with pytest.raises(QnaError) as e:
            await pipeline.open_snap_collection(SNAP)
        assert e.value.code == "UPSTREAM_UNAVAILABLE"  # never PROFILE_EMPTY
    else:
        _, count = await pipeline.open_snap_collection(SNAP)
        assert count == expected


async def test_whole_compare_deadline(world, monkeypatch):
    monkeypatch.setattr(pipeline, "COMPARE_DEADLINE_S", 0.01)

    async def slow(*a, **k):
        await asyncio.sleep(1)

    monkeypatch.setattr(pipeline, "retrieve", slow)
    await expect_error(world, 504, "UPSTREAM_TIMEOUT")


def test_worst_case_fits_the_harness_timeout():
    worst = (
        pipeline.CHROMA_TIMEOUT_S * 2
        + pipeline.TAGS_TIMEOUT_S
        + 3.0  # Infinity /models probe (clients.HEALTH_TIMEOUT_S)
        + settings.RAG_COMPARE_EMBED_TIMEOUT_S
        + settings.RAG_COMPARE_LOCK_WAIT_S
        + settings.RAG_COMPARE_GENERATION_TIMEOUT_S
    )
    assert worst < pipeline.COMPARE_DEADLINE_S < 180


async def test_malformed_chroma_reply_is_503(embedded):
    class Broken(FakeCollection):
        async def query(self, **kwargs):
            return {"documents": None, "metadatas": None, "distances": None}

    with pytest.raises(QnaError) as e:
        await pipeline.retrieve(SNAP, "q", 0.0, Broken([0.1]), 1, embed_timeout=1)
    assert e.value.code == "UPSTREAM_UNAVAILABLE"
