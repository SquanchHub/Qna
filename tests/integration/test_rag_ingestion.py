"""
Ingestion integration tests for the RAG feature, run against the live stack:
presets and profiles, resources on the upload and URL paths, jobs, re-sync,
profile coexistence, and which threads count as historical Q&A.

Spec: docs/design-rag.md §6 (API reference), §4.1 (citation URLs), §4.4.1
(presets), §4.5 (ingestion, jobs, re-sync). Case IDs are from
docs/test-plan-rag.md §4.2–§4.4. Each test skips, naming the milestone,
until the backend serves the routes it needs.
"""

from __future__ import annotations

import io
import re
import time
import uuid
import zipfile
from datetime import datetime

import httpx
import pytest

from .conftest import (
    CRUD_TIMEOUT,
    EVAL_SAMPLE_DATA,
    GTE,
    MINILM,
    QUINDLEWORT_QUESTION,
    RAG_FIXTURES,
    chroma_counts,
    compare_body,
    fresh_profile,
    get_profile,
    get_resource,
    list_resources,
    login_as_netid,
    new_course,
    rag_compare,
    rag_setting,
    rag_url,
    resource_state,
    start_sync,
    sync_and_wait,
    unique_name,
    upload_raw,
    upload_resource,
    wait_for_ai_status,
    wait_for_job,
)

GITLAB_PROJECT = rag_setting(
    "RAG_TEST_GITLAB_PROJECT",
    "https://git.doit.wisc.edu/cdis/cs/courses/aicoding/fa26/student-repos/p3/qna-74",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Each page of fixtures/rag/slides.pdf has its own term (make_fixtures.py)
PDF_PAGE_TERMS = ("Brambleflux", "Zorvatic", "Plimquist")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _is_utc_z(ts: str | None) -> bool:
    """design §6: timestamps are UTC ISO 8601 ending in Z."""
    if not ts or not ts.endswith("Z"):
        return False
    datetime.fromisoformat(ts[:-1] + "+00:00")
    return True


def _jobs(base_url, course_id, token, **params) -> httpx.Response:
    return httpx.get(f"{rag_url(base_url, course_id)}/jobs", params=params, headers=_headers(token),
                     timeout=CRUD_TIMEOUT)


def _chunks_for(base_url, course_id, token, profile_name, question) -> list[dict]:
    """Top-K chunks at threshold 0.0, so provenance tests don't depend on the
    calibrated threshold (design §4.4.3 returns only above-threshold chunks)."""
    r = rag_compare(base_url, course_id, token,
                    compare_body(question, ingestion_profile=profile_name, similarity_threshold=0.0))
    assert r.status_code == 200, r.text
    return r.json()["retrieved_chunks"]


def _synced_course(base_url, admin_token, make_profile, files, preset="sliding-window", name=None):
    """A fresh course with one profile and the given (path, resource_type, base)
    uploads synced to READY. Returns (course_id, profile, {filename: resource})."""
    cid = new_course(base_url, admin_token, "RAG Ingest")
    profile = make_profile(cid, admin_token, preset, name or unique_name("ingest"))
    resources = {}
    for path, rtype, base in files:
        resources[path.name] = upload_resource(base_url, cid, admin_token, path, rtype, base)
    sync_and_wait(base_url, cid, admin_token, profile_id=profile["id"])
    return cid, get_profile(base_url, cid, admin_token, profile["id"]), resources


def _upload_eval_corpus(base_url, course_id, token) -> list[dict]:
    """All of eval/sample_data, one upload per file: enough content that a
    profile sync over it takes seconds, used to hold a job open (plan §6 item 5)."""
    out = [
        upload_resource(base_url, course_id, token, EVAL_SAMPLE_DATA / "web" / "syllabus.html", "syllabus"),
        upload_resource(base_url, course_id, token, EVAL_SAMPLE_DATA / "web" / "schedule.html", "schedule"),
    ]
    for path in sorted((EVAL_SAMPLE_DATA / "repo").rglob("*")):
        if path.suffix in (".md", ".pdf"):
            out.append(upload_resource(base_url, course_id, token, path, "repository"))
    return out


def _while_job_active(base_url, course_id, token, make_profile, rag_health, start_target, action, attempts=3):
    """Run `action(target_job)` while a target job is QUEUED or RUNNING.

    MiniLM can finish the tiny corpus in under a second, so the target job is
    queued behind a slower blocker job on INGESTION_LOCK (design §4.5.7): the
    blocker syncs all of eval/sample_data, with gte if Infinity serves it. If
    the target is already done before the action, the setup is retried (up to
    `attempts` times). If it was done by the time the action returned, the
    result says nothing, so the test skips rather than assert (plan §6 item 5).
    """
    if not any(r["source_kind"] == "upload" and r["original_filename"] == "schedule.html"
               for r in list_resources(base_url, course_id, token)):
        _upload_eval_corpus(base_url, course_id, token)
    blocker_preset = "embedding-alt" if GTE in rag_health["infinity"]["models"] else "sliding-window"
    blocker = make_profile(course_id, token, blocker_preset, unique_name("blocker"))
    for _ in range(attempts):
        r = start_sync(base_url, course_id, token, profile_id=blocker["id"])
        assert r.status_code == 202, r.text
        blocker_job = r.json()
        target_job = start_target()
        active = httpx.get(f"{rag_url(base_url, course_id)}/jobs/{target_job['id']}", headers=_headers(token),
                           timeout=CRUD_TIMEOUT).json()["status"] in ("QUEUED", "RUNNING")
        if active:
            result = action(target_job)
            still = httpx.get(f"{rag_url(base_url, course_id)}/jobs/{target_job['id']}", headers=_headers(token),
                              timeout=CRUD_TIMEOUT).json()["status"] in ("QUEUED", "RUNNING")
        wait_for_job(base_url, course_id, token, blocker_job["id"], timeout=900)
        wait_for_job(base_url, course_id, token, target_job["id"], timeout=900)
        if active:
            if still:
                return result
            pytest.skip("inconclusive: the target job finished before the action's response; cannot prove 409")
    pytest.skip(f"could not hold a job QUEUED/RUNNING in {attempts} attempts")


# ---------------------------------------------------------------------------
# Profiles (plan §4.2)
# ---------------------------------------------------------------------------


@pytest.mark.rag_m4
class TestProfiles:
    def test_p1_presets(self, base_url, course_id, staff_token):
        r = httpx.get(f"{rag_url(base_url, course_id)}/presets", headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 200, r.text
        presets = {p["preset"]: p for p in r.json()}
        assert {"sliding-window", "type-tailored", "embedding-alt"} <= presets.keys()
        for p in presets.values():
            assert {"embedding_model", "query_instruction", "chunking"} <= p.keys()
            # §4.4.1 chunking shape
            assert p["chunking"]["token_unit"] == "minilm-wordpiece"
            assert {"method", "chunk_size", "chunk_overlap"} <= p["chunking"]["default"].keys()
        assert presets["sliding-window"]["embedding_model"] == MINILM
        assert presets["type-tailored"]["embedding_model"] == MINILM
        assert presets["embedding-alt"]["embedding_model"] == GTE
        assert presets["embedding-alt"]["query_instruction"].startswith("Instruct: ")

    def test_p2_create_from_preset(self, base_url, course_id, staff_token, make_profile):
        p = make_profile(course_id, staff_token, "sliding-window")
        assert p["name"] == "sliding-window"  # name defaults to the preset
        assert p["preset"] == "sliding-window"
        assert p["course_id"] == course_id
        assert p["embedding_model"] == MINILM
        assert p["chunk_count"] == 0
        assert p["collection_name"] == f"c{course_id}_p{p['id']}"
        assert p["active_job_id"] is None
        assert _is_utc_z(p["created_at"])

    def test_p3_named_copy_coexists(self, base_url, course_id, staff_token, make_profile):
        a = make_profile(course_id, staff_token, "sliding-window")
        b = make_profile(course_id, staff_token, "sliding-window", "sw-copy")
        assert b["name"] == "sw-copy"
        assert a["collection_name"] != b["collection_name"]

    def test_p4_duplicate_name_is_409(self, base_url, course_id, staff_token, make_profile):
        make_profile(course_id, staff_token, "sliding-window", "dupe-name")
        r = httpx.post(f"{rag_url(base_url, course_id)}/profiles", json={"preset": "type-tailored", "name": "dupe-name"},
                       headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "DUPLICATE_PROFILE"

    def test_p5_same_name_in_another_course(self, base_url, course_id, staff_token, admin_token, make_profile):
        """UNIQUE(course_id, name): names are per course (design §5)."""
        make_profile(course_id, staff_token, "sliding-window", "shared-name")
        other = new_course(base_url, admin_token)
        assert make_profile(other, admin_token, "sliding-window", "shared-name")["name"] == "shared-name"

    def test_p6_unknown_preset_is_422(self, base_url, course_id, staff_token):
        r = httpx.post(f"{rag_url(base_url, course_id)}/profiles", json={"preset": "nope"},
                       headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "UNKNOWN_PRESET"

    @pytest.mark.parametrize(
        "body",
        [
            {"preset": "sliding-window", "name": "A"},
            {"preset": "sliding-window", "name": "-x-"},
            {"preset": "sliding-window", "name": "a" * 65},
            {"preset": "sliding-window", "name": "has space"},
            {"preset": "sliding-window", "name": "ok-name", "chunk_size": 100},  # extra="forbid"
        ],
        ids=["one-char", "leading-dash", "65-chars", "space", "extra-field"],
    )
    def test_p7_invalid_name_or_extra_field_is_422(self, base_url, course_id, staff_token, body):
        """Name pattern ^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$ (design §5)."""
        r = httpx.post(f"{rag_url(base_url, course_id)}/profiles", json=body, headers=_headers(staff_token),
                       timeout=CRUD_TIMEOUT)
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "VALIDATION_ERROR"

    def test_p8_preset_with_unserved_model_is_422(self, base_url, course_id, staff_token, rag_health):
        """Conditional: only meaningful when Infinity lacks some preset's model
        (for example gte dropped on a low-RAM laptop, design §4.3.1)."""
        r = httpx.get(f"{rag_url(base_url, course_id)}/presets", headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
        served = set(rag_health["infinity"]["models"])
        unserved = [p["preset"] for p in r.json() if p["embedding_model"] not in served]
        if not unserved:
            pytest.skip("every preset's embedding model is served by Infinity")
        r = httpx.post(f"{rag_url(base_url, course_id)}/profiles", json={"preset": unserved[0]},
                       headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "EMBEDDING_MODEL_NOT_SERVED"

    def test_p9_list_and_no_update_route(self, base_url, course_id, staff_token, make_profile):
        """Profiles are immutable: no PATCH or PUT (design §4.4.1, §6)."""
        a = make_profile(course_id, staff_token, "sliding-window")
        b = make_profile(course_id, staff_token, "sliding-window", "sw-copy")
        r = httpx.get(f"{rag_url(base_url, course_id)}/profiles", headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 200, r.text
        assert {a["id"], b["id"]} <= {p["id"] for p in r.json()}
        for method in ("PATCH", "PUT"):
            r = httpx.request(method, f"{rag_url(base_url, course_id)}/profiles/{a['id']}", json={"name": "renamed"},
                              headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
            assert r.status_code == 405, r.text

    def test_p10_delete(self, base_url, course_id, staff_token):
        profile = fresh_profile(base_url, course_id, staff_token, "sliding-window")
        r = httpx.delete(f"{rag_url(base_url, course_id)}/profiles/{profile['id']}", headers=_headers(staff_token),
                         timeout=CRUD_TIMEOUT)
        assert r.status_code == 204, r.text
        r = httpx.get(f"{rag_url(base_url, course_id)}/profiles", headers=_headers(staff_token), timeout=CRUD_TIMEOUT)
        assert profile["id"] not in {p["id"] for p in r.json()}

    @pytest.mark.rag_m5
    def test_p10_compare_on_deleted_profile_is_404(self, base_url, admin_token, make_profile):
        cid, profile, _ = _synced_course(base_url, admin_token, make_profile, [(RAG_FIXTURES / "notes.md", "repository", None)])
        r = httpx.delete(f"{rag_url(base_url, cid)}/profiles/{profile['id']}", headers=_headers(admin_token),
                         timeout=CRUD_TIMEOUT)
        assert r.status_code == 204, r.text
        r = rag_compare(base_url, cid, admin_token, compare_body(QUINDLEWORT_QUESTION, ingestion_profile=profile["name"]))
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "PROFILE_NOT_FOUND"

    @pytest.mark.db_access
    def test_p10_delete_drops_the_chroma_collection(self, base_url, admin_token, make_profile):
        """Profile delete drops the collection, then the row (design §4.5.6)."""
        cid, profile, _ = _synced_course(base_url, admin_token, make_profile, [(RAG_FIXTURES / "notes.md", "repository", None)])
        assert chroma_counts()[profile["collection_name"]] == profile["chunk_count"] > 0
        r = httpx.delete(f"{rag_url(base_url, cid)}/profiles/{profile['id']}", headers=_headers(admin_token),
                         timeout=CRUD_TIMEOUT)
        assert r.status_code == 204, r.text
        assert profile["collection_name"] not in chroma_counts()

    def test_p11_delete_missing_is_404(self, base_url, course_id, staff_token):
        r = httpx.delete(f"{rag_url(base_url, course_id)}/profiles/2000000000", headers=_headers(staff_token),
                         timeout=CRUD_TIMEOUT)
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "PROFILE_NOT_FOUND"

    def test_p12_delete_with_active_job_is_409(self, base_url, admin_token, make_profile, rag_health):
        cid = new_course(base_url, admin_token, "RAG Busy")
        target = make_profile(cid, admin_token, "sliding-window", unique_name("target"))

        def start():
            r = start_sync(base_url, cid, admin_token, profile_id=target["id"])
            assert r.status_code == 202, r.text
            return r.json()

        r = _while_job_active(
            base_url, cid, admin_token, make_profile, rag_health, start,
            lambda job: httpx.delete(f"{rag_url(base_url, cid)}/profiles/{target['id']}",
                                     headers=_headers(admin_token), timeout=CRUD_TIMEOUT),
        )
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "JOB_RUNNING"


# ---------------------------------------------------------------------------
# Resources (plan §4.3)
# ---------------------------------------------------------------------------


@pytest.mark.rag_m4
class TestResources:
    def test_r1_course_has_exactly_one_historical_qa_resource(self, base_url, course_id, staff_token):
        """Created by POST /admin/courses; GET routes never create rows (design §4.5.1)."""
        first = list_resources(base_url, course_id, staff_token)
        second = list_resources(base_url, course_id, staff_token)
        hqa = [r for r in first if r["resource_type"] == "historical_qa"]
        assert len(hqa) == 1, first
        assert hqa[0]["source_kind"] == "internal"
        assert [r["id"] for r in second] == [r["id"] for r in first]

    def test_r2_historical_qa_cannot_be_deleted(self, base_url, course_id, staff_token):
        hqa = next(r for r in list_resources(base_url, course_id, staff_token) if r["resource_type"] == "historical_qa")
        r = httpx.delete(f"{rag_url(base_url, course_id)}/resources/{hqa['id']}", headers=_headers(staff_token),
                         timeout=CRUD_TIMEOUT)
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "PROTECTED_RESOURCE"

    def test_r3_upload_is_unsynced_in_every_profile(self, base_url, course_id, staff_token, make_profile):
        """states lists every course profile; one without a state row is NEVER (§6)."""
        p1 = make_profile(course_id, staff_token, "sliding-window", unique_name("r3a"))
        p2 = make_profile(course_id, staff_token, "type-tailored", unique_name("r3b"))
        res = upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        assert res["resource_type"] == "repository"
        assert res["source_kind"] == "upload"
        assert res["original_filename"] == "notes.md"
        assert _is_utc_z(res["created_at"])
        states = {s["profile_id"]: s for s in res["states"]}
        assert states.keys() == {p1["id"], p2["id"]}
        for s in states.values():
            assert s["status"] == "NEVER"
            assert s["chunk_count"] == 0

    def test_r15_delete_resource_refreshes_counts(self, base_url, admin_token, make_profile):
        """Resource delete removes its chunks from every profile collection and
        refreshes each chunk_count (design §4.5.6)."""
        cid, profile, res = _synced_course(base_url, admin_token, make_profile, [
            (RAG_FIXTURES / "notes.md", "repository", None),
            (RAG_FIXTURES / "slides.pdf", "repository", None),
        ])
        notes = get_resource(base_url, cid, admin_token, res["notes.md"]["id"])
        notes_count = resource_state(notes, profile["id"])["chunk_count"]
        assert 0 < notes_count < profile["chunk_count"]

        r = httpx.delete(f"{rag_url(base_url, cid)}/resources/{res['slides.pdf']['id']}",
                         headers=_headers(admin_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 204, r.text
        assert res["slides.pdf"]["id"] not in {r["id"] for r in list_resources(base_url, cid, admin_token)}
        assert get_profile(base_url, cid, admin_token, profile["id"])["chunk_count"] == notes_count

    @pytest.mark.rag_m5
    def test_r15_deleted_resource_is_no_longer_retrieved(self, base_url, admin_token, make_profile):
        cid, profile, res = _synced_course(base_url, admin_token, make_profile, [
            (RAG_FIXTURES / "notes.md", "repository", None),
            (RAG_FIXTURES / "slides.pdf", "repository", None),
        ])
        question = "What invalidates a Zorvatic cache?"
        assert any("Zorvatic" in c["text"] for c in _chunks_for(base_url, cid, admin_token, profile["name"], question))
        r = httpx.delete(f"{rag_url(base_url, cid)}/resources/{res['slides.pdf']['id']}",
                         headers=_headers(admin_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 204, r.text
        chunks = _chunks_for(base_url, cid, admin_token, profile["name"], question)
        assert not any("Zorvatic" in c["text"] for c in chunks)
        assert all(c["resource_type"] != "repo_pdf" for c in chunks)

    @pytest.mark.db_access
    def test_r15_delete_resource_drops_chroma_chunks(self, base_url, admin_token, make_profile):
        cid, profile, res = _synced_course(base_url, admin_token, make_profile, [
            (RAG_FIXTURES / "notes.md", "repository", None),
            (RAG_FIXTURES / "slides.pdf", "repository", None),
        ])
        before = chroma_counts()[profile["collection_name"]]
        slides = get_resource(base_url, cid, admin_token, res["slides.pdf"]["id"])
        slides_count = resource_state(slides, profile["id"])["chunk_count"]
        r = httpx.delete(f"{rag_url(base_url, cid)}/resources/{slides['id']}", headers=_headers(admin_token),
                         timeout=CRUD_TIMEOUT)
        assert r.status_code == 204, r.text
        assert chroma_counts()[profile["collection_name"]] == before - slides_count

    def test_r16_delete_resource_with_active_job_is_409(self, base_url, admin_token, make_profile, rag_health):
        cid = new_course(base_url, admin_token, "RAG Busy")
        target = make_profile(cid, admin_token, "sliding-window", unique_name("target"))
        res = upload_resource(base_url, cid, admin_token, RAG_FIXTURES / "notes.md", "repository")

        def start():
            r = start_sync(base_url, cid, admin_token, resource_id=res["id"], profile_ids=[target["id"]])
            assert r.status_code == 202, r.text
            return r.json()["jobs"][0]

        r = _while_job_active(
            base_url, cid, admin_token, make_profile, rag_health, start,
            lambda job: httpx.delete(f"{rag_url(base_url, cid)}/resources/{res['id']}",
                                     headers=_headers(admin_token), timeout=CRUD_TIMEOUT),
        )
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "JOB_RUNNING"


# ---------------------------------------------------------------------------
# Upload path (plan §4.3, design §4.1.1 "Upload path", §4.5.3)
# ---------------------------------------------------------------------------


def _zip_bytes(entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def _symlink_zip() -> bytes:
    info = zipfile.ZipInfo("top/link.md")
    info.create_system = 3  # unix, so external_attr carries the mode
    info.external_attr = 0o120777 << 16  # S_IFLNK
    return _zip_bytes([("top/real.md", b"## Real\n\ntext\n"), (info, b"/etc/passwd")])


class TestUploadPath:
    @pytest.mark.rag_m5
    def test_r4_markdown_upload_cites_file_and_lines(self, base_url, rag_course, admin_token):
        """Without citation_base_url the citation is upload://<rid>/<path><suffix>
        (design §4.1.1). The design inserts ?plain=1 only for a GitLab /-/blob/
        base, so it is optional here; the plan's R4 shape assumed it."""
        notes = rag_course.resources["notes.md"]
        state = resource_state(get_resource(base_url, rag_course.id, admin_token, notes["id"]), rag_course.profile["id"])
        assert state["status"] == "READY"
        assert state["chunk_count"] > 0
        chunks = _chunks_for(base_url, rag_course.id, admin_token, rag_course.profile["name"], QUINDLEWORT_QUESTION)
        hit = next(c for c in chunks if "Quindlewort" in c["text"])
        assert hit["resource_type"] == "repo_markdown"
        assert re.fullmatch(rf"upload://{notes['id']}/notes\.md(\?plain=1)?#L\d+(-\d+)?", hit["source_url"]), hit

    @pytest.mark.rag_m5
    def test_r5_citation_base_url_is_used(self, base_url, admin_token, make_profile):
        """For a single file the base is that file's URL; a GitLab /-/blob/ base
        gets ?plain=1 before #L (design §4.1.1)."""
        base = f"https://git.doit.wisc.edu/x/y/-/blob/{'a' * 40}/dir/notes.md"
        cid, profile, _ = _synced_course(base_url, admin_token, make_profile,
                                         [(RAG_FIXTURES / "notes.md", "repository", base)])
        hit = next(c for c in _chunks_for(base_url, cid, admin_token, profile["name"], QUINDLEWORT_QUESTION)
                   if "Quindlewort" in c["text"])
        assert hit["source_url"].startswith(base)
        assert "/notes.md?plain=1#L" in hit["source_url"]

    @pytest.mark.rag_m5
    def test_r6_zip_upload(self, base_url, admin_token, make_profile):
        """Only .md/.pdf are extracted and a single shared top-level directory is
        stripped (design §4.5.3); PDF citations carry the 1-based start page."""
        cid, profile, res = _synced_course(base_url, admin_token, make_profile,
                                           [(RAG_FIXTURES / "repo.zip", "repository", None)])
        rid = res["repo.zip"]["id"]

        md = next(c for c in _chunks_for(base_url, cid, admin_token, profile["name"], QUINDLEWORT_QUESTION)
                  if "Quindlewort" in c["text"])
        assert md["resource_type"] == "repo_markdown"
        assert md["source_url"].startswith(f"upload://{rid}/notes.md")

        pdf = next(c for c in _chunks_for(base_url, cid, admin_token, profile["name"], "What invalidates a Zorvatic cache?")
                   if "Zorvatic" in c["text"])
        assert pdf["resource_type"] == "repo_pdf"
        assert pdf["source_url"].startswith(f"upload://{rid}/docs/slides.pdf#page=")
        assert "/top/" not in pdf["source_url"]
        # Every page ends with its own term, and fixture pages are shorter than
        # one window, so a chunk's start page is the first page whose term it holds
        expected = next(i for i, term in enumerate(PDF_PAGE_TERMS, start=1) if term in pdf["text"])
        assert pdf["source_url"].endswith(f"#page={expected}"), pdf

        for c in _chunks_for(base_url, cid, admin_token, profile["name"], "What is the Gribbletoast rule?"):
            assert "Gribbletoast" not in c["text"]

    @pytest.mark.rag_m5
    def test_r7_html_upload_strips_markup_noise(self, base_url, rag_course, admin_token):
        """nav, .sr-only and script are removed before chunking (design §4.5.4);
        web chunks cite a text fragment (§4.1.1)."""
        rid = rag_course.resources["syllabus.html"]["id"]
        chunks = _chunks_for(base_url, rag_course.id, admin_token, rag_course.profile["name"],
                             "How many days late can work be under the Fenwickery late policy?")
        hit = next(c for c in chunks if "Fenwickery" in c["text"])
        assert hit["resource_type"] == "syllabus"
        assert hit["source_url"].startswith(f"upload://{rid}/syllabus.html")
        assert "#:~:text=" in hit["source_url"]
        for noise in ("Navwhistle", "Srlurk", "Scriptmoo"):
            assert noise not in hit["text"]

    @pytest.mark.rag_m4
    @pytest.mark.parametrize(
        "content",
        [
            _zip_bytes([("top/ok.md", b"## ok\n"), ("../evil.md", b"## evil\n")]),
            _zip_bytes([("/abs/evil.md", b"## evil\n")]),
            _symlink_zip(),
        ],
        ids=["zip-slip", "absolute-path", "symlink"],
    )
    def test_r8_unsafe_archive_is_422(self, base_url, course_id, staff_token, content):
        r = upload_raw(base_url, course_id, staff_token, "repo.zip", content, "repository")
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "UNSAFE_ARCHIVE"

    @pytest.mark.rag_m4
    @pytest.mark.parametrize("filename", ["tool.exe", "notes.txt"])
    def test_r9_unsupported_single_file_is_422(self, base_url, course_id, staff_token, filename):
        r = upload_raw(base_url, course_id, staff_token, filename, b"MZ not really a binary\n", "repository")
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "UNSUPPORTED_FILE"

    @pytest.mark.rag_m4
    def test_r10_oversized_upload_is_413(self, base_url, course_id, staff_token):
        cap_mb = int(rag_setting("MAX_UPLOAD_MB", "20"))
        content = b"## Big\n\n" + b"a" * ((cap_mb + 1) * 1024 * 1024)
        r = upload_raw(base_url, course_id, staff_token, "big.md", content, "repository")
        assert r.status_code == 413, r.text
        assert r.json()["error"] == "PAYLOAD_TOO_LARGE"
        assert all(x["original_filename"] != "big.md" for x in list_resources(base_url, course_id, staff_token))


# ---------------------------------------------------------------------------
# URL path (plan §4.3, design §4.5.2)
# ---------------------------------------------------------------------------


def _register(base_url, course_id, token, body) -> httpx.Response:
    return httpx.post(f"{rag_url(base_url, course_id)}/resources", json=body, headers=_headers(token),
                      timeout=CRUD_TIMEOUT)


class TestUrlPath:
    @pytest.mark.rag_m4
    @pytest.mark.parametrize(
        "body",
        [
            {"resource_type": "syllabus", "title": "s", "url": "ftp://example.com/syllabus.html"},
            {"resource_type": "syllabus", "title": "s", "url": "https://example.com/s.html", "git_ref": "main"},
            {"resource_type": "repository", "title": "r", "url": f"{GITLAB_PROJECT}", "subpath": "../x"},
            {"resource_type": "repository", "title": "r", "url": f"{GITLAB_PROJECT}", "git_ref": "a" * 40},
        ],
        ids=["ftp-scheme", "git-ref-on-syllabus", "dotdot-subpath", "sha-git-ref"],
    )
    def test_r11_invalid_registration_is_422(self, base_url, course_id, staff_token, body):
        """SHAs are rejected because `git clone --branch` cannot take them (§4.5.1)."""
        r = _register(base_url, course_id, staff_token, body)
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "VALIDATION_ERROR"

    @pytest.mark.rag_m4
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data",
            "http://ollama:11434/",
            "http://mysql:3306/",
        ],
    )
    def test_r12_ssrf_targets_are_refused(self, base_url, course_id, staff_token, url):
        """Without the guard, staff could make the backend reach internal
        services or cloud metadata (design §4.6)."""
        r = _register(base_url, course_id, staff_token, {"resource_type": "syllabus", "title": "s", "url": url})
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "URL_NOT_ALLOWED"

    @pytest.mark.rag_m5
    @pytest.mark.gitlab
    def test_r13_gitlab_repository(self, base_url, admin_token, make_profile):
        """The primary path: a shallow clone of our own repo, limited by subpath,
        cited with SHA permalinks (design §4.1.1, §4.5.2)."""
        cid = new_course(base_url, admin_token, "RAG GitLab")
        profile = make_profile(cid, admin_token, "sliding-window", unique_name("gitlab"))
        r = _register(base_url, cid, admin_token, {"resource_type": "repository", "title": "Sample repo",
                                                   "url": GITLAB_PROJECT, "git_ref": "main",
                                                   "subpath": "eval/sample_data/repo"})
        assert r.status_code == 201, r.text
        res = r.json()
        [job] = sync_and_wait(base_url, cid, admin_token, resource_id=res["id"], timeout=300)
        state = resource_state(get_resource(base_url, cid, admin_token, res["id"]), profile["id"])
        assert state["status"] == "READY"
        sha = state["last_commit_sha"]
        assert SHA_RE.match(sha), sha

        chunks = _chunks_for(base_url, cid, admin_token, profile["name"],
                             "What is broken in the Project 1 starter code that students have to fix?")
        assert chunks
        for c in chunks:
            assert "eval/sample_data/repo/" in c["source_url"]
            if c["resource_type"] == "repo_markdown":
                assert f"/-/blob/{sha}/" in c["source_url"]

        token = rag_setting("GITLAB_TOKEN", "")
        exposed = r.text + str(job) + str(get_resource(base_url, cid, admin_token, res["id"])) + str(chunks)
        if token:
            assert token not in exposed
        assert "glpat-" not in exposed
        assert "oauth2:" not in exposed

    @pytest.mark.rag_m5
    @pytest.mark.gitlab
    def test_r14_gitlab_file_url(self, base_url, admin_token, make_profile):
        """The harness scores a hit by substring of the repo-relative path (design §3.1)."""
        cid = new_course(base_url, admin_token, "RAG GitLab")
        profile = make_profile(cid, admin_token, "sliding-window", unique_name("gitlab"))
        r = _register(base_url, cid, admin_token, {
            "resource_type": "syllabus", "title": "Syllabus",
            "url": f"{GITLAB_PROJECT}/-/blob/main/eval/sample_data/web/syllabus.html",
        })
        assert r.status_code == 201, r.text
        sync_and_wait(base_url, cid, admin_token, resource_id=r.json()["id"])
        chunks = _chunks_for(base_url, cid, admin_token, profile["name"],
                             "How many slip days does each student get, and what do they cover?")
        assert chunks
        for c in chunks:
            assert c["resource_type"] == "syllabus"
            assert "eval/sample_data/web/syllabus.html" in c["source_url"]


# ---------------------------------------------------------------------------
# Historical Q&A (plan §4.3 H1–H3, design §4.5.4)
# ---------------------------------------------------------------------------


def _ask(base_url, course_id, token, category_id, term) -> int:
    r = httpx.post(
        f"{base_url}/api/courses/{course_id}/questions",
        json={"title": f"How does the {term} step work?", "body": f"I am stuck on the {term} step.",
              "category_ids": [category_id]},
        headers=_headers(token),
        timeout=CRUD_TIMEOUT,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _answer(base_url, course_id, token, qid, body) -> int:
    r = httpx.post(f"{base_url}/api/courses/{course_id}/questions/{qid}/posts", json={"kind": "ANSWER", "body": body},
                   headers=_headers(token), timeout=CRUD_TIMEOUT)
    assert r.status_code == 201, r.text
    return r.json()["posts"][-1]["id"]


def _accept(base_url, course_id, token, qid, post_id) -> None:
    r = httpx.patch(f"{base_url}/api/courses/{course_id}/questions/{qid}/posts/{post_id}/accept",
                    json={"is_accepted": True}, headers=_headers(token), timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text


def _close(base_url, course_id, token, qid) -> None:
    r = httpx.post(f"{base_url}/api/courses/{course_id}/questions/{qid}/close", headers=_headers(token),
                   timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text


def _thread_qids(chunks: list[dict], course_id: int) -> set[int]:
    """Question ids cited by historical_qa chunks, checking the §4.1.1 URL shape."""
    frontend = rag_setting("FRONTEND_URL", "http://localhost:8080").rstrip("/")
    out = set()
    for c in chunks:
        if c["resource_type"] != "historical_qa":
            continue
        m = re.fullmatch(rf"{re.escape(frontend)}/student/questions/(\d+)\?course={course_id}", c["source_url"])
        assert m, c["source_url"]
        out.add(int(m.group(1)))
    return out


@pytest.mark.rag_m5
class TestHistoricalQA:
    def _hqa(self, base_url, course_id, token) -> dict:
        return next(r for r in list_resources(base_url, course_id, token) if r["resource_type"] == "historical_qa")

    def test_h1_only_resolved_threads_are_ingested(
        self, base_url, course_id, staff_token, student_token, category_id, make_profile
    ):
        """A thread qualifies if it has an accepted non-AI ANSWER, or is CLOSED
        with a STAFF ANSWER (design §4.5.4)."""
        terms = {k: f"{k}{uuid.uuid4().hex[:6]}" for k in ("Wobblequark", "Thistlegrain", "Marrowsplice",
                                                             "Quillfeather", "Saltmarsh")}
        a, b, c, d, e = terms.values()
        qa = _ask(base_url, course_id, student_token, category_id, a)  # (a) accepted student answer
        _accept(base_url, course_id, staff_token, qa,
                _answer(base_url, course_id, student_token, qa, f"Run the {a} script twice."))
        qb = _ask(base_url, course_id, student_token, category_id, b)  # (b) closed, staff answer, not accepted
        _answer(base_url, course_id, staff_token, qb, f"The {b} step needs a fresh token.")
        _close(base_url, course_id, staff_token, qb)
        qc = _ask(base_url, course_id, student_token, category_id, c)  # (c) closed, only a student answer
        _answer(base_url, course_id, student_token, qc, f"Maybe {c} is optional?")
        _close(base_url, course_id, staff_token, qc)
        _ask(base_url, course_id, student_token, category_id, d)  # (d) open, unanswered
        qe = _ask(base_url, course_id, student_token, category_id, e)  # (e) open, unaccepted student answer
        _answer(base_url, course_id, student_token, qe, f"I think {e} just works.")

        # Not the default profile name, so the live board never answers here
        profile = make_profile(course_id, staff_token, "sliding-window", unique_name("hqa"))
        hqa = self._hqa(base_url, course_id, staff_token)
        sync_and_wait(base_url, course_id, staff_token, resource_id=hqa["id"], profile_ids=[profile["id"]])
        state = resource_state(get_resource(base_url, course_id, staff_token, hqa["id"]), profile["id"])
        assert state["status"] == "READY"
        assert state["chunk_count"] == 2  # one unsplit pair per qualifying thread

        cited = set()
        for term in terms.values():
            cited |= _thread_qids(_chunks_for(base_url, course_id, staff_token, profile["name"],
                                              f"How does the {term} step work?"), course_id)
        assert cited == {qa, qb}

    @pytest.mark.live_board
    def test_h2_accepted_ai_answer_is_excluded(self, base_url, admin_token, rag_health, make_profile):
        """Accepted AI posts would duplicate chunks we already hold (design §4.5.4)."""
        cid = new_course(base_url, admin_token, "RAG HQA")
        staff = login_as_netid(base_url, admin_token, cid, "STAFF")
        student = login_as_netid(base_url, admin_token, cid, "STUDENT")
        category = httpx.post(f"{base_url}/api/courses/{cid}/categories", json={"name": "General", "description": ""},
                              headers=_headers(staff), timeout=CRUD_TIMEOUT).json()["id"]
        profile = make_profile(cid, staff, "sliding-window", rag_health["defaults"]["profile"])
        upload_resource(base_url, cid, staff, RAG_FIXTURES / "notes.md", "repository")
        sync_and_wait(base_url, cid, staff, profile_id=profile["id"])

        r = httpx.post(f"{base_url}/api/courses/{cid}/questions",
                       json={"title": QUINDLEWORT_QUESTION, "body": "Asking for the lab.", "category_ids": [category]},
                       headers=_headers(student), timeout=CRUD_TIMEOUT)
        assert r.status_code == 201, r.text
        ai_qid = r.json()["id"]
        detail = wait_for_ai_status(base_url, cid, staff, ai_qid)
        assert detail["ai_status"] == "ANSWERED", detail
        ai_post = next(p for p in detail["posts"] if p["author_role"] == "AI")
        _accept(base_url, cid, staff, ai_qid, ai_post["id"])

        control = _ask(base_url, cid, student, category, "Hollyburr")
        _accept(base_url, cid, staff, control, _answer(base_url, cid, staff, control, "Hollyburr needs a restart."))

        hqa = self._hqa(base_url, cid, staff)
        sync_and_wait(base_url, cid, staff, resource_id=hqa["id"], profile_ids=[profile["id"]])
        assert resource_state(get_resource(base_url, cid, staff, hqa["id"]), profile["id"])["chunk_count"] == 1
        cited = _thread_qids(_chunks_for(base_url, cid, staff, profile["name"], QUINDLEWORT_QUESTION), cid)
        assert ai_qid not in cited
        assert control in cited

    def test_h3_historical_qa_does_not_auto_sync(
        self, base_url, course_id, staff_token, student_token, category_id, make_profile
    ):
        """Only staff-triggered syncs change it, so eval collections don't drift (§4.5.6)."""
        q1 = _ask(base_url, course_id, student_token, category_id, "Fernwhistle")
        _accept(base_url, course_id, staff_token, q1, _answer(base_url, course_id, staff_token, q1, "Restart it."))
        profile = make_profile(course_id, staff_token, "sliding-window", unique_name("hqa"))
        hqa = self._hqa(base_url, course_id, staff_token)
        sync_and_wait(base_url, course_id, staff_token, resource_id=hqa["id"], profile_ids=[profile["id"]])
        jobs_before = _jobs(base_url, course_id, staff_token).json()

        q2 = _ask(base_url, course_id, student_token, category_id, "Gorsepetal")
        _accept(base_url, course_id, staff_token, q2, _answer(base_url, course_id, staff_token, q2, "Reinstall it."))
        time.sleep(5)
        state = resource_state(get_resource(base_url, course_id, staff_token, hqa["id"]), profile["id"])
        assert state["chunk_count"] == 1
        assert get_profile(base_url, course_id, staff_token, profile["id"])["chunk_count"] == 1
        assert _jobs(base_url, course_id, staff_token).json() == jobs_before

        sync_and_wait(base_url, course_id, staff_token, resource_id=hqa["id"], profile_ids=[profile["id"]])
        state = resource_state(get_resource(base_url, course_id, staff_token, hqa["id"]), profile["id"])
        assert state["chunk_count"] == 2


# ---------------------------------------------------------------------------
# Jobs (plan §4.4 J1–J10, design §4.5.5, §6)
# ---------------------------------------------------------------------------


@pytest.mark.rag_m4
class TestJobs:
    def test_j1_profile_sync(self, base_url, course_id, staff_token, make_profile):
        profile = make_profile(course_id, staff_token, "sliding-window", unique_name("j1"))
        upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        r = start_sync(base_url, course_id, staff_token, profile_id=profile["id"])
        assert r.status_code == 202, r.text
        job = r.json()
        assert job["scope"] == "profile"
        assert job["resource_id"] is None
        assert job["profile_id"] == profile["id"]
        assert job["status"] in ("QUEUED", "RUNNING")

        active = get_profile(base_url, course_id, staff_token, profile["id"])["active_job_id"]
        if active is None:  # only allowed if the job already finished
            assert wait_for_job(base_url, course_id, staff_token, job["id"], timeout=0)["status"] in ("SUCCEEDED", "FAILED")
        else:
            assert active == job["id"]

        done = wait_for_job(base_url, course_id, staff_token, job["id"])
        assert done["status"] == "SUCCEEDED", done["error"]
        assert _is_utc_z(done["started_at"]) and _is_utc_z(done["finished_at"])
        assert done["chunks_added"] > 0
        assert get_profile(base_url, course_id, staff_token, profile["id"])["active_job_id"] is None

    def test_j2_resource_sync_targets_every_profile(self, base_url, course_id, staff_token, make_profile):
        p1 = make_profile(course_id, staff_token, "sliding-window", unique_name("j2a"))
        p2 = make_profile(course_id, staff_token, "type-tailored", unique_name("j2b"))
        res = upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        r = start_sync(base_url, course_id, staff_token, resource_id=res["id"])
        assert r.status_code == 202, r.text
        jobs = r.json()["jobs"]
        assert sorted(j["profile_id"] for j in jobs) == sorted([p1["id"], p2["id"]])
        for j in jobs:
            assert j["scope"] == "resource"
            assert j["resource_id"] == res["id"]
            assert wait_for_job(base_url, course_id, staff_token, j["id"])["status"] == "SUCCEEDED"

    def test_j3_profile_ids_limits_the_sync(self, base_url, course_id, staff_token, make_profile):
        p1 = make_profile(course_id, staff_token, "sliding-window", unique_name("j3a"))
        p2 = make_profile(course_id, staff_token, "sliding-window", unique_name("j3b"))
        res = upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        jobs = sync_and_wait(base_url, course_id, staff_token, resource_id=res["id"], profile_ids=[p1["id"]])
        assert [j["profile_id"] for j in jobs] == [p1["id"]]
        states = {s["profile_id"]: s for s in get_resource(base_url, course_id, staff_token, res["id"])["states"]}
        assert states[p1["id"]]["status"] == "READY"
        assert states[p2["id"]]["status"] == "NEVER"

    def test_j4_empty_profile_ids_is_422(self, base_url, course_id, staff_token, make_profile):
        """Omit the field for "all"; an empty list is an error (design §6)."""
        make_profile(course_id, staff_token, "sliding-window", unique_name("j4"))
        res = upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        r = start_sync(base_url, course_id, staff_token, resource_id=res["id"], profile_ids=[])
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "VALIDATION_ERROR"

    def test_j5_other_courses_profile_id_is_404(self, base_url, course_id, staff_token, admin_token, make_profile):
        make_profile(course_id, staff_token, "sliding-window", unique_name("j5"))
        foreign = make_profile(new_course(base_url, admin_token), admin_token, "sliding-window", unique_name("j5b"))
        res = upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        r = start_sync(base_url, course_id, staff_token, resource_id=res["id"], profile_ids=[foreign["id"]])
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "PROFILE_NOT_FOUND"
        assert _jobs(base_url, course_id, staff_token).json() == []

    def test_j6_resource_sync_without_profiles_is_409(self, base_url, course_id, staff_token):
        res = upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        r = start_sync(base_url, course_id, staff_token, resource_id=res["id"])
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "NO_PROFILES"

    def test_j7_second_sync_while_active_is_409(self, base_url, admin_token, make_profile, rag_health):
        """At most one QUEUED/RUNNING job per profile (design §4.5.5)."""
        cid = new_course(base_url, admin_token, "RAG Busy")
        target = make_profile(cid, admin_token, "sliding-window", unique_name("target"))

        def start():
            r = start_sync(base_url, cid, admin_token, profile_id=target["id"])
            assert r.status_code == 202, r.text
            return r.json()

        r = _while_job_active(base_url, cid, admin_token, make_profile, rag_health, start,
                              lambda job: start_sync(base_url, cid, admin_token, profile_id=target["id"]))
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "JOB_RUNNING"

    def test_j8_multi_profile_sync_is_all_or_nothing(self, base_url, admin_token, make_profile, rag_health):
        """If any target profile is busy, no job is created for any (design §6)."""
        cid = new_course(base_url, admin_token, "RAG Busy")
        p1 = make_profile(cid, admin_token, "sliding-window", unique_name("p1"))
        p2 = make_profile(cid, admin_token, "sliding-window", unique_name("p2"))
        res = upload_resource(base_url, cid, admin_token, RAG_FIXTURES / "notes.md", "repository")

        def start():
            r = start_sync(base_url, cid, admin_token, profile_id=p1["id"])
            assert r.status_code == 202, r.text
            return r.json()

        def action(job):
            r = start_sync(base_url, cid, admin_token, resource_id=res["id"], profile_ids=[p1["id"], p2["id"]])
            p2_jobs = [j for j in _jobs(base_url, cid, admin_token, limit=100).json() if j["profile_id"] == p2["id"]]
            return r, p2_jobs

        r, p2_jobs = _while_job_active(base_url, cid, admin_token, make_profile, rag_health, start, action)
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "JOB_RUNNING"
        assert p2_jobs == []

    def test_j9_job_listing(self, base_url, course_id, staff_token, make_profile):
        profile = make_profile(course_id, staff_token, "sliding-window", unique_name("j9"))
        upload_resource(base_url, course_id, staff_token, RAG_FIXTURES / "notes.md", "repository")
        first = sync_and_wait(base_url, course_id, staff_token, profile_id=profile["id"])[0]
        second = sync_and_wait(base_url, course_id, staff_token, profile_id=profile["id"])[0]

        r = _jobs(base_url, course_id, staff_token)
        assert r.status_code == 200, r.text
        assert [j["id"] for j in r.json()][:2] == [second["id"], first["id"]]  # newest first
        assert len(_jobs(base_url, course_id, staff_token, limit=1).json()) == 1
        for bad in (0, 101):
            r = _jobs(base_url, course_id, staff_token, limit=bad)
            assert r.status_code == 422, r.text
            assert r.json()["error"] == "VALIDATION_ERROR"
        succeeded = _jobs(base_url, course_id, staff_token, status="SUCCEEDED").json()
        assert {first["id"], second["id"]} <= {j["id"] for j in succeeded}
        assert all(j["status"] == "SUCCEEDED" for j in succeeded)
        assert _jobs(base_url, course_id, staff_token, status="FAILED").json() == []

    def test_j10_missing_and_foreign_job_are_404(self, base_url, course_id, staff_token, rag_course):
        for jid in (2_000_000_000, rag_course.job["id"]):
            r = httpx.get(f"{rag_url(base_url, course_id)}/jobs/{jid}", headers=_headers(staff_token),
                          timeout=CRUD_TIMEOUT)
            assert r.status_code == 404, r.text
            assert r.json()["error"] == "JOB_NOT_FOUND"


# ---------------------------------------------------------------------------
# Re-sync (plan §4.4 S1–S4, design §4.5.6)
# ---------------------------------------------------------------------------


class TestResync:
    @pytest.mark.rag_m4
    def test_s1_unchanged_resync_rewrites_nothing(self, base_url, admin_token, make_profile):
        """Chunk IDs are content hashes, so an unchanged source keeps every chunk
        and only refreshes metadata (design §4.1.2, §4.5.6)."""
        cid, profile, res = _synced_course(base_url, admin_token, make_profile,
                                           [(RAG_FIXTURES / "notes.md", "repository", None)])
        rid = res["notes.md"]["id"]
        before = resource_state(get_resource(base_url, cid, admin_token, rid), profile["id"])["chunk_count"]
        assert before > 0

        [job] = sync_and_wait(base_url, cid, admin_token, resource_id=rid, profile_ids=[profile["id"]])
        assert (job["chunks_added"], job["chunks_deleted"], job["chunks_updated"]) == (0, 0, before)
        after = get_resource(base_url, cid, admin_token, rid)  # same id: no delete and re-add
        assert resource_state(after, profile["id"])["chunk_count"] == before
        assert get_profile(base_url, cid, admin_token, profile["id"])["chunk_count"] == before

    @pytest.mark.rag_m4
    def test_s2_resync_updates_last_synced_at(self, base_url, admin_token, make_profile):
        cid, profile, res = _synced_course(base_url, admin_token, make_profile,
                                           [(RAG_FIXTURES / "notes.md", "repository", None)])
        rid = res["notes.md"]["id"]
        first = resource_state(get_resource(base_url, cid, admin_token, rid), profile["id"])
        time.sleep(1.1)  # timestamps may have one-second resolution
        sync_and_wait(base_url, cid, admin_token, resource_id=rid, profile_ids=[profile["id"]])
        second = resource_state(get_resource(base_url, cid, admin_token, rid), profile["id"])
        assert second["status"] == "READY"
        assert _is_utc_z(second["last_synced_at"])
        assert second["last_synced_at"] > first["last_synced_at"]

    def _failing_sync(self, base_url, admin_token, make_profile):
        """Upload A (READY) plus URL resource B that passes registration but can't
        be fetched. A GitLab file URL with a bogus path fails with or without a
        token, and also without egress (plan §6 item 4)."""
        cid, profile, res = _synced_course(base_url, admin_token, make_profile,
                                           [(RAG_FIXTURES / "notes.md", "repository", None)])
        a = res["notes.md"]
        a_count = resource_state(get_resource(base_url, cid, admin_token, a["id"]), profile["id"])["chunk_count"]
        r = _register(base_url, cid, admin_token, {
            "resource_type": "syllabus", "title": "Missing",
            "url": f"{GITLAB_PROJECT}/-/blob/main/does-not-exist-{uuid.uuid4().hex[:8]}.html",
        })
        assert r.status_code == 201, r.text
        b = r.json()
        [job] = sync_and_wait(base_url, cid, admin_token, profile_id=profile["id"], expect=None)
        return cid, profile, a, a_count, b, job

    @pytest.mark.rag_m4
    def test_s3_failed_fetch_deletes_nothing(self, base_url, admin_token, make_profile):
        """Weak form: a fetch failure marks B FAILED and leaves A's chunks alone.
        The strong form (a source that succeeds, then fails) needs stubbed
        fetchers and belongs in unit tests (plan §6 item 3)."""
        cid, profile, a, a_count, b, job = self._failing_sync(base_url, admin_token, make_profile)
        assert job["status"] == "FAILED"
        b_state = resource_state(get_resource(base_url, cid, admin_token, b["id"]), profile["id"])
        assert b_state["status"] == "FAILED"
        assert b_state["error"]
        a_state = resource_state(get_resource(base_url, cid, admin_token, a["id"]), profile["id"])
        assert a_state["status"] == "READY"
        assert a_state["chunk_count"] == a_count
        assert get_profile(base_url, cid, admin_token, profile["id"])["chunk_count"] >= a_count

    @pytest.mark.rag_m5
    def test_s3_failed_fetch_keeps_old_chunks_retrievable(self, base_url, admin_token, make_profile):
        cid, profile, *_ = self._failing_sync(base_url, admin_token, make_profile)
        chunks = _chunks_for(base_url, cid, admin_token, profile["name"], QUINDLEWORT_QUESTION)
        assert any("Quindlewort" in c["text"] for c in chunks)

    @pytest.mark.rag_m5
    @pytest.mark.gitlab
    def test_s4_gitlab_resync_is_a_no_op(self, base_url, admin_token, make_profile):
        cid = new_course(base_url, admin_token, "RAG GitLab")
        profile = make_profile(cid, admin_token, "sliding-window", unique_name("gitlab"))
        r = _register(base_url, cid, admin_token, {"resource_type": "repository", "title": "Sample repo",
                                                   "url": GITLAB_PROJECT, "git_ref": "main",
                                                   "subpath": "eval/sample_data/repo"})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        sync_and_wait(base_url, cid, admin_token, resource_id=rid, timeout=300)
        sha = resource_state(get_resource(base_url, cid, admin_token, rid), profile["id"])["last_commit_sha"]
        [job] = sync_and_wait(base_url, cid, admin_token, resource_id=rid, timeout=300)
        assert job["chunks_added"] == 0
        assert job["chunks_deleted"] == 0
        assert resource_state(get_resource(base_url, cid, admin_token, rid), profile["id"])["last_commit_sha"] == sha


# ---------------------------------------------------------------------------
# Coexisting profiles (plan §4.4 C1–C3, design §4.4.1, §4.5.6 "Coexistence")
# ---------------------------------------------------------------------------


_CORPUS = [
    (RAG_FIXTURES / "notes.md", "repository", None),
    (RAG_FIXTURES / "slides.pdf", "repository", None),
    (RAG_FIXTURES / "syllabus.html", "syllabus", None),
]


def _two_profile_course(base_url, admin_token, make_profile, presets):
    cid = new_course(base_url, admin_token, "RAG Coexist")
    profiles = [make_profile(cid, admin_token, preset, unique_name(preset[:8].strip("-"))) for preset in presets]
    for path, rtype, base in _CORPUS:
        upload_resource(base_url, cid, admin_token, path, rtype, base)
    for p in profiles:
        sync_and_wait(base_url, cid, admin_token, profile_id=p["id"], timeout=900)
    return cid, [get_profile(base_url, cid, admin_token, p["id"]) for p in profiles]


class TestCoexistence:
    @pytest.mark.rag_m4
    def test_c1_profiles_have_separate_collections(self, base_url, admin_token, make_profile):
        """Each profile writes only its own collection and state rows (§4.5.6)."""
        cid, (sw, tt) = _two_profile_course(base_url, admin_token, make_profile, ["sliding-window", "type-tailored"])
        assert sw["collection_name"] != tt["collection_name"]
        assert sw["chunk_count"] > 0 and tt["chunk_count"] > 0
        # slides.pdf: sliding-window streams pages into 200-token windows,
        # type-tailored windows each page alone (make_fixtures.py)
        assert sw["chunk_count"] != tt["chunk_count"]

        def tt_view():
            states = [resource_state(r, tt["id"]) for r in list_resources(base_url, cid, admin_token)
                      if r["resource_type"] != "historical_qa"]
            return get_profile(base_url, cid, admin_token, tt["id"])["chunk_count"], states

        before = tt_view()
        time.sleep(1.1)
        sync_and_wait(base_url, cid, admin_token, profile_id=sw["id"])
        assert tt_view() == before

    @pytest.mark.rag_m5
    def test_c2_deleting_one_profile_leaves_the_other_answering(self, base_url, admin_token, make_profile, rag_health):
        cid, (sw, tt) = _two_profile_course(base_url, admin_token, make_profile, ["sliding-window", "type-tailored"])
        r = httpx.delete(f"{rag_url(base_url, cid)}/profiles/{tt['id']}", headers=_headers(admin_token),
                         timeout=CRUD_TIMEOUT)
        assert r.status_code == 204, r.text
        r = rag_compare(base_url, cid, admin_token, compare_body(
            QUINDLEWORT_QUESTION, ingestion_profile=sw["name"],
            similarity_threshold=rag_health["defaults"]["threshold"]))
        assert r.status_code == 200, r.text
        assert r.json()["matched"] is True

    @pytest.mark.rag_m4
    def test_c3_sliding_window_profiles_chunk_identically(self, base_url, admin_token, make_profile, rag_health):
        """All-sliding-window profiles share the chunk-token unit, so only the
        embedding differs (design §4.4.1 "Byte-identical chunks")."""
        if GTE not in rag_health["infinity"]["models"]:
            pytest.skip(f"{GTE} is not served by Infinity (embedding-alt unavailable)")
        _, (sw, alt) = _two_profile_course(base_url, admin_token, make_profile, ["sliding-window", "embedding-alt"])
        assert sw["chunk_count"] == alt["chunk_count"] > 0
