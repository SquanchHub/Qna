"""Sync and re-sync against a fake Chroma collection (design-rag.md §4.5.5, §4.5.6).

The integration tests can only show the weak form of "a failed fetch deletes
nothing"; here a source that succeeds and then fails shows the strong form.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.rag import ingest
from app.services.rag.citations import CitationContext
from app.services.rag.fetchers import Document, Fetched, FetchError
from app.services.rag.ingest import QaThread, sync_resource
from app.services.rag.presets import get_preset

PROFILE = SimpleNamespace(
    id=4,
    course_id=3,
    name="sw",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    chunking=get_preset("sliding-window")["chunking"],
)
RESOURCE = SimpleNamespace(
    id=7,
    course_id=3,
    resource_type="repository",
    source_kind="upload",
    citation_base_url=None,
)
QA_RESOURCE = SimpleNamespace(
    id=8, course_id=3, resource_type="historical_qa", source_kind="internal"
)


class FakeCollection:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.fail_upsert_after = None  # fail the n-th upsert call (0-based)
        self.fail_delete = False
        self.upserts = 0
        self.batch_sizes: list[int] = []

    async def get(self, where=None, include=None):
        return {
            "ids": [
                i
                for i, row in self.rows.items()
                if all(row["metadata"].get(k) == v for k, v in (where or {}).items())
            ]
        }

    async def upsert(self, ids, embeddings, documents, metadatas):
        if (
            self.fail_upsert_after is not None
            and self.upserts >= self.fail_upsert_after
        ):
            raise RuntimeError("chroma write failed")
        self.upserts += 1
        self.batch_sizes.append(len(ids))
        for i, e, d, m in zip(ids, embeddings, documents, metadatas):
            self.rows[i] = {"embedding": e, "document": d, "metadata": m}

    async def update(self, ids, metadatas):
        for i, m in zip(ids, metadatas):
            self.rows[i]["metadata"] = m

    async def delete(self, ids=None, where=None):
        if self.fail_delete:
            raise RuntimeError("chroma delete failed")
        for i in ids or []:
            self.rows.pop(i, None)

    async def count(self):
        return len(self.rows)


async def fake_embed(texts):
    return [[float(len(t)), 1.0] for t in texts]


def _md(n_sections: int, edit: str = "") -> bytes:
    return "\n\n".join(
        f"## Section {i}\n\nBody of section {i} with words{edit if i == 0 else ''}."
        for i in range(n_sections)
    ).encode()


def _fetcher(data: bytes):
    async def fetch(resource):
        return Fetched(
            [Document("notes.md", data, "md")],
            CitationContext(kind="upload", resource_id=resource.id),
            None,
        )

    return fetch


async def _sync(coll, fetcher, job_id=1, resource=RESOURCE, **kw):
    return await sync_resource(
        resource, PROFILE, job_id, coll, embed=fake_embed, fetcher=fetcher, **kw
    )


async def test_first_sync_adds_every_chunk_in_batches_of_eight():
    coll = FakeCollection()
    out = await _sync(coll, _fetcher(_md(20)))
    assert out.status == "READY"
    assert (out.added, out.kept, out.deleted) == (20, 0, 0)
    assert out.chunk_count == 20 == await coll.count()
    assert coll.batch_sizes == [8, 8, 4]
    meta = next(iter(coll.rows.values()))["metadata"]
    assert meta["resource_id"] == 7 and meta["profile_id"] == 4
    assert meta["ingest_job_id"] == 1
    assert meta["source_url"].startswith("upload://7/notes.md#L")


async def test_unchanged_resync_keeps_everything_and_refreshes_metadata():
    coll = FakeCollection()
    await _sync(coll, _fetcher(_md(5)), job_id=1)
    out = await _sync(coll, _fetcher(_md(5)), job_id=2)
    assert (out.added, out.kept, out.deleted) == (0, 5, 0)
    assert all(r["metadata"]["ingest_job_id"] == 2 for r in coll.rows.values())


async def test_edit_adds_changed_and_deletes_stale():
    coll = FakeCollection()
    await _sync(coll, _fetcher(_md(5)))
    before = set(coll.rows)
    out = await _sync(coll, _fetcher(_md(4, edit=" changed")))
    assert (out.added, out.kept, out.deleted) == (1, 3, 2)
    assert len(coll.rows) == 4 and len(before & set(coll.rows)) == 3


async def test_fetch_failure_after_success_leaves_old_set():
    coll = FakeCollection()
    await _sync(coll, _fetcher(_md(5)))
    snapshot = {k: dict(v) for k, v in coll.rows.items()}

    async def failing(resource):
        raise FetchError("HTTP 500 from example.test")

    out = await _sync(coll, failing)
    assert out.status == "FAILED" and "HTTP 500" in out.error
    assert coll.rows == snapshot


async def test_embed_failure_on_second_batch_rolls_back_the_first():
    coll = FakeCollection()
    await _sync(coll, _fetcher(_md(3)))
    old = set(coll.rows)
    calls = 0

    async def flaky(texts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("infinity down")
        return await fake_embed(texts)

    out = await sync_resource(
        RESOURCE, PROFILE, 2, coll, embed=flaky, fetcher=_fetcher(_md(20, edit=" v2"))
    )
    assert out.status == "FAILED" and out.error
    assert set(coll.rows) == old


async def test_failed_stale_delete_keeps_new_and_old_ids():
    coll = FakeCollection()
    await _sync(coll, _fetcher(_md(3)))
    coll.fail_delete = True
    out = await _sync(coll, _fetcher(_md(2, edit=" new")))
    assert out.status == "FAILED"
    # The newly written chunk is rolled back best-effort (delete also fails here),
    # and the old chunks remain retrievable
    assert {r["metadata"]["resource_id"] for r in coll.rows.values()} == {7}


async def test_zero_chunks_is_failed_and_deletes_nothing():
    coll = FakeCollection()
    await _sync(coll, _fetcher(_md(3)))
    out = await _sync(coll, _fetcher(b"   \n\n"))
    assert out.status == "FAILED" and "no chunks" in out.error
    assert len(coll.rows) == 3


async def test_unexpected_chunker_error_is_failed():
    async def bad(resource):
        return Fetched(
            [Document("x.pdf", b"not a pdf", "pdf")],
            CitationContext(kind="upload", resource_id=7),
            None,
        )

    out = await _sync(FakeCollection(), bad)
    assert out.status == "FAILED" and out.error


async def test_other_resources_chunks_are_untouched():
    coll = FakeCollection()
    coll.rows["other"] = {
        "embedding": [1],
        "document": "x",
        "metadata": {"resource_id": 99},
    }
    await _sync(coll, _fetcher(_md(2)))
    await _sync(coll, _fetcher(_md(1, edit=" z")))
    assert "other" in coll.rows


async def test_chroma_update_and_delete_use_max_batch():
    coll = FakeCollection()
    await _sync(coll, _fetcher(_md(5)))
    seen = []
    original = coll.update

    async def spy(ids, metadatas):
        seen.append(len(ids))
        await original(ids, metadatas)

    coll.update = spy
    await _sync(coll, _fetcher(_md(5)), max_batch=2)
    assert seen == [2, 2, 1]


# Historical Q&A


def _loader(threads):
    async def load(course_id):
        assert course_id == 3
        return threads

    return load


async def test_historical_qa_with_no_threads_is_ready_and_clears_stale():
    coll = FakeCollection()
    threads = [QaThread(11, "How?", "Body", "Answer")]
    out = await _sync(coll, None, resource=QA_RESOURCE, qa_loader=_loader(threads))
    assert out.status == "READY" and out.chunk_count == 1
    meta = next(iter(coll.rows.values()))["metadata"]
    assert meta["question_id"] == 11
    assert meta["source_url"].endswith("/student/questions/11?course=3")

    out = await _sync(coll, None, resource=QA_RESOURCE, qa_loader=_loader([]))
    assert out.status == "READY" and out.chunk_count == 0 and out.deleted == 1
    assert coll.rows == {}


# run_job: one bad resource does not stop the others


@pytest.fixture
def job_steps(monkeypatch):
    """Replace run_job's short DB sessions with an in-memory record."""
    record = SimpleNamespace(states={}, finished=None, failed=None, started=False)
    job = SimpleNamespace(
        id=1, course_id=3, profile_id=4, scope="profile", resource_id=None
    )

    async def start(job_id):
        record.started = True
        return job

    async def resource_ids(j):
        return [7, 70, 700]

    async def begin(j, rid):
        return SimpleNamespace(**{**vars(RESOURCE), "id": rid}), PROFILE

    async def finish_resource(j, rid, outcome):
        record.states[rid] = outcome

    async def finish(j, failures, total, count):
        record.finished = (failures, total, count)

    async def fail(job_id, error):
        record.failed = error

    async def open_collection(profile):
        return FakeCollection(), 100

    for name, fn in {
        "_start_job": start,
        "_resource_ids": resource_ids,
        "_begin_resource": begin,
        "_finish_resource": finish_resource,
        "_finish_job": finish,
        "_fail_job": fail,
        "_open_collection": open_collection,
    }.items():
        monkeypatch.setattr(ingest, name, fn)
    return record


async def test_run_job_isolates_a_failing_resource(job_steps, monkeypatch):
    async def fake_sync(resource, profile, job_id, coll, **kw):
        if resource.id == 70:
            raise RuntimeError("boom")
        return ingest.Outcome("READY", 2, None, None, 2, 0, 0)

    monkeypatch.setattr(ingest, "sync_resource", fake_sync)
    await ingest.run_job(1)
    assert job_steps.states[7].status == "READY"
    assert job_steps.states[70].status == "FAILED" and job_steps.states[70].error
    assert job_steps.states[700].status == "READY"
    assert job_steps.finished[:2] == (1, 3)
    assert job_steps.failed is None


async def test_run_job_outer_failure_marks_job_failed(job_steps, monkeypatch):
    async def broken(profile):
        raise ConnectionError("chroma down")

    monkeypatch.setattr(ingest, "_open_collection", broken)
    await ingest.run_job(1)
    assert job_steps.failed and "ConnectionError" in job_steps.failed


async def test_failure_mark_is_retried_so_the_job_never_stays_queued(
    job_steps, monkeypatch
):
    async def broken(job_id):
        raise ConnectionError("mysql down")

    attempts = []

    async def flaky_fail(job_id, error):
        attempts.append(error)
        if len(attempts) < 3:
            raise ConnectionError("mysql still down")

    monkeypatch.setattr(ingest, "_start_job", broken)
    monkeypatch.setattr(ingest, "_fail_job", flaky_fail)
    monkeypatch.setattr(ingest, "FAIL_RETRY_DELAYS_S", (0, 0, 0))
    await ingest.run_job(1)
    assert len(attempts) == 3 and "ConnectionError" in attempts[0]
