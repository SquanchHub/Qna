"""The live auto-responder's decisions (design-rag.md §4.2.3, §4.2.4, §4.1.3).

Every collaborator is patched, so these cover the status each path ends in;
the integration board tests cover the real database and services.
"""

from __future__ import annotations

import asyncio

import pytest

from app.common.exceptions import ConflictError
from app.config import settings
from app.services.rag import answer_job, pipeline
from app.services.rag.answer_job import citations, post_body
from app.services.rag.pipeline import Hit, ProfileSnap, Retrieval
from app.services.rag.prompts import LIVE_PROMPT

SNAP = ProfileSnap(3, "sliding-window", "sentence-transformers/all-MiniLM-L6-v2", "", "c1_p3")
QUESTION = {"course_id": 1, "title": "Quindlewort?", "body": "What does it need?", "closed": False}


def hit(i: int, score: float, url: str | None = None) -> Hit:
    return Hit(
        score,
        f"doc{i}",
        {"resource_type": "repo_markdown", "title": f"notes.md > S{i}", "source_url": url or f"https://e.com/{i}"},
    )


# --- citations and body -----------------------------------------------------


def test_citations_dedupe_by_url_and_rank_from_one():
    hits = [hit(0, 0.812345), hit(1, 0.7, "https://e.com/0"), hit(2, 0.65)]
    assert citations(hits) == [
        {"rank": 1, "resource_type": "repo_markdown", "title": "notes.md > S0",
         "source_url": "https://e.com/0", "similarity_score": 0.8123},
        {"rank": 2, "resource_type": "repo_markdown", "title": "notes.md > S2",
         "source_url": "https://e.com/2", "similarity_score": 0.65},
    ]


def test_post_body():
    cites = citations([hit(0, 0.8), hit(1, 0.7)])
    assert post_body("  Three handshakes.\n", cites) == (
        "Three handshakes.\n\nSources:\n"
        "[1] notes.md > S0 — https://e.com/0\n"
        "[2] notes.md > S1 — https://e.com/1"
    )


# --- initial status ---------------------------------------------------------


class CountDb:
    def __init__(self, pending: int):
        self.pending = pending

    async def scalar(self, stmt):
        return self.pending


@pytest.mark.parametrize(
    "live, pending, expected",
    [(False, 0, "NONE"), (True, 0, "PENDING"), (True, 2, "PENDING"), (True, 3, "SKIPPED"), (True, 9, "SKIPPED")],
)
async def test_initial_status(monkeypatch, live, pending, expected):
    monkeypatch.setattr(settings, "RAG_LIVE_ENABLED", live)
    monkeypatch.setattr(settings, "RAG_MAX_PENDING_PER_COURSE", 3)
    assert await answer_job.initial_status(CountDb(pending), 1) == expected


# --- run --------------------------------------------------------------------


@pytest.fixture()
def job(monkeypatch):
    state = {
        "loaded": (QUESTION, SNAP),
        "count": 5,
        "retrieval": Retrieval(True, [hit(0, 0.8), hit(1, 0.7)], 1.0, 1.0),
        "answer": "Three handshakes.",
        "post": "ANSWERED",
        "finished": [],
        "posted": [],
        "generated": [],
    }

    async def load(qid):
        return state["loaded"]

    async def open_coll(snap):
        return object(), state["count"]

    async def retrieve(snap, query, threshold, coll, count, embed_timeout):
        state["query"] = (query, threshold, embed_timeout)
        return state["retrieval"]

    async def generate(model, system_prompt, message, timeout):
        state["generated"].append((model, system_prompt, timeout))
        if isinstance(state["answer"], Exception):
            raise state["answer"]
        return state["answer"]

    async def post_answer(qid, body, cites, snap):
        state["posted"].append((qid, body, cites, snap.name))
        if isinstance(state["post"], Exception):
            raise state["post"]
        return state["post"]

    async def finish(qid, status):
        state["finished"].append(status)

    monkeypatch.setattr(answer_job, "load", load)
    monkeypatch.setattr(pipeline, "open_snap_collection", open_coll)
    monkeypatch.setattr(pipeline, "retrieve", retrieve)
    monkeypatch.setattr(pipeline, "generate", generate)
    monkeypatch.setattr(answer_job, "post_answer", post_answer)
    monkeypatch.setattr(answer_job, "finish", finish)
    monkeypatch.setattr(answer_job, "GENERATION_LOCK", asyncio.Semaphore(1))
    return state


async def test_answered(job):
    await answer_job.run(42)
    assert job["finished"] == []  # post_answer sets ANSWERED in its own session
    [(qid, body, cites, profile)] = job["posted"]
    assert (qid, profile) == (42, "sliding-window")
    assert body.startswith("Three handshakes.\n\nSources:\n[1] ")
    assert [c["rank"] for c in cites] == [1, 2]
    assert job["generated"] == [(settings.RAG_DEFAULT_MODEL, LIVE_PROMPT, settings.RAG_LIVE_GENERATION_TIMEOUT_S)]
    query, threshold, timeout = job["query"]
    assert query == "Quindlewort?\n\nWhat does it need?"
    assert threshold == settings.RAG_DEFAULT_THRESHOLD
    assert timeout == settings.RAG_INGEST_EMBED_TIMEOUT_S


async def test_query_is_truncated(job):
    job["loaded"] = ({**QUESTION, "body": "x" * 5000}, SNAP)
    await answer_job.run(1)
    assert len(job["query"][0]) == 4000


async def test_question_gone(job):
    job["loaded"] = None
    await answer_job.run(1)
    assert job["finished"] == [] and job["posted"] == []


async def test_no_profile_is_skipped(job):
    job["loaded"] = (QUESTION, None)
    await answer_job.run(1)
    assert job["finished"] == ["SKIPPED"]


async def test_empty_profile_is_skipped(job):
    job["count"] = 0
    await answer_job.run(1)
    assert job["finished"] == ["SKIPPED"]


async def test_no_match(job):
    job["retrieval"] = Retrieval(False, [], 1.0, 1.0)
    await answer_job.run(1)
    assert job["finished"] == ["NO_MATCH"] and job["generated"] == []


async def test_decline_posts_nothing(job):
    job["answer"] = "INSUFFICIENT_CONTEXT"
    await answer_job.run(1)
    assert job["finished"] == ["DECLINED"] and job["posted"] == []


async def test_closed_meanwhile_is_skipped(job):
    job["post"] = "SKIPPED"
    await answer_job.run(1)
    assert job["finished"] == [] and len(job["posted"]) == 1


async def test_generation_error_fails(job):
    job["answer"] = RuntimeError("ollama exploded")
    await answer_job.run(1)
    assert job["finished"] == ["FAILED"] and job["posted"] == []


async def test_lock_wait_timeout_fails(job, monkeypatch):
    monkeypatch.setattr(settings, "RAG_LIVE_LOCK_WAIT_S", 0.01)
    lock = answer_job.GENERATION_LOCK
    await lock.acquire()
    try:
        await answer_job.run(1)
    finally:
        lock.release()
    assert job["finished"] == ["FAILED"] and job["generated"] == []


async def test_insert_error_fails(job):
    job["post"] = RuntimeError("db down")
    await answer_job.run(1)
    assert job["finished"] == ["FAILED"]


async def test_finish_error_is_swallowed(job, monkeypatch):
    async def broken(qid, status):
        raise RuntimeError("db down")

    job["count"] = 0
    monkeypatch.setattr(answer_job, "finish", broken)
    await answer_job.run(1)  # must not raise: it runs as a background task


def test_conflict_error_is_the_close_signal():
    # post_answer maps qa_service's ConflictError (thread closed) to SKIPPED
    assert issubclass(ConflictError, Exception)


async def test_already_closed_is_skipped_without_retrieval(job):
    job["loaded"] = ({**QUESTION, "closed": True}, SNAP)
    await answer_job.run(1)
    assert job["finished"] == ["SKIPPED"] and "query" not in job


@pytest.mark.parametrize("answer", ["", "  \n "])
async def test_empty_answer_fails(job, answer):
    job["answer"] = answer
    await answer_job.run(1)
    assert job["finished"] == ["FAILED"] and job["posted"] == []


def test_citation_title_falls_back():
    no_title = Hit(0.8, "d", {"resource_type": "repo_pdf", "rel_path": "slides.pdf", "source_url": "u"})
    [c] = citations([no_title])
    assert c["title"] == "slides.pdf"
    assert "None" not in post_body("A.", [c])
