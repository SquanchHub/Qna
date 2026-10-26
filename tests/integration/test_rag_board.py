"""
Integration tests for the live auto-responder and staff acceptance of AI
answers, run against the live stack with RAG_LIVE_ENABLED=true.

Spec: docs/design-rag.md §4.2.3 (ai_status), §4.2.4 (answer job), §4.2.5
(acceptance and triage), §4.1.3 (citations on the AI post). Case IDs are
from docs/test-plan-rag.md §4.6–§4.7. Board tests skip, naming M5, until the
answer job exists, and skip when live answering is off; the one live-off
case runs only when it is off.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import pytest

from .conftest import (
    AI_DISPLAY_NAME,
    CRUD_TIMEOUT,
    OFF_TOPIC_QUESTION,
    QUINDLEWORT_QUESTION,
    RAG_FIXTURES,
    delete_profile_when_idle,
    fresh_profile,
    login_as_netid,
    new_course,
    rag_setting,
    require_rag,
    sync_and_wait,
    upload_resource,
    wait_for_ai_status,
)

TERMINAL = {"ANSWERED", "NO_MATCH", "DECLINED", "SKIPPED", "FAILED"}
CITATION_KEYS = {"rank", "resource_type", "title", "source_url", "similarity_score"}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class BoardCourse:
    id: int
    staff_token: str
    student_token: str
    category_id: int


def _make_board_course(base_url, admin_token, profile_name=None, sync=True) -> tuple[BoardCourse, dict | None]:
    """A course with staff, student and a category; optionally a profile named
    profile_name (RAG_DEFAULT_PROFILE for the board) with notes.md synced."""
    cid = new_course(base_url, admin_token, "RAG Board")
    staff = login_as_netid(base_url, admin_token, cid, "STAFF")
    student = login_as_netid(base_url, admin_token, cid, "STUDENT")
    r = httpx.post(f"{base_url}/api/courses/{cid}/categories", json={"name": "General", "description": ""},
                   headers=_headers(staff), timeout=CRUD_TIMEOUT)
    assert r.status_code == 201, r.text
    course = BoardCourse(cid, staff, student, r.json()["id"])
    profile = None
    if profile_name is not None:
        profile = fresh_profile(base_url, cid, staff, "sliding-window", profile_name)
        if sync:
            upload_resource(base_url, cid, staff, RAG_FIXTURES / "notes.md", "repository")
            sync_and_wait(base_url, cid, staff, profile_id=profile["id"])
    return course, profile


@pytest.fixture(scope="module")
def board_course(request, rag_capabilities, base_url, admin_token):
    """Gates itself too, for when the stack was down at the conftest hook's check."""
    require_rag(rag_capabilities, "m5")
    health = request.getfixturevalue("rag_health")
    if not health["live_enabled"]:
        pytest.skip("live_board: RAG_LIVE_ENABLED is false on the backend (/api/rag/health)")
    course, profile = _make_board_course(base_url, admin_token, health["defaults"]["profile"])
    yield course
    delete_profile_when_idle(base_url, course.id, admin_token, profile["id"])


def _ask(base_url, course: BoardCourse, title: str, body: str = "Asking for the lab.", token: str | None = None) -> dict:
    r = httpx.post(
        f"{base_url}/api/courses/{course.id}/questions",
        json={"title": title, "body": body, "category_ids": [course.category_id]},
        headers=_headers(token or course.student_token),
        timeout=CRUD_TIMEOUT,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _detail(base_url, course: BoardCourse, qid: int, token: str | None = None) -> dict:
    r = httpx.get(f"{base_url}/api/courses/{course.id}/questions/{qid}",
                  headers=_headers(token or course.staff_token), timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _ai_posts(detail: dict) -> list[dict]:
    return [p for p in detail["posts"] if p["author_role"] == "AI"]


def _accept(base_url, course: BoardCourse, qid: int, post_id: int, accepted: bool = True, headers=None):
    return httpx.patch(
        f"{base_url}/api/courses/{course.id}/questions/{qid}/posts/{post_id}/accept",
        json={"is_accepted": accepted},
        headers=headers or _headers(course.staff_token),
        timeout=CRUD_TIMEOUT,
    )


def _summary(base_url, course: BoardCourse, qid: int) -> dict:
    r = httpx.get(f"{base_url}/api/courses/{course.id}/questions", headers=_headers(course.staff_token),
                  timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text
    return next(q for q in r.json() if q["id"] == qid)


def _answered(base_url, course: BoardCourse) -> tuple[dict, dict]:
    """Ask the Quindlewort question and wait for the AI answer. Returns the
    question detail and its single AI post."""
    q = _ask(base_url, course, QUINDLEWORT_QUESTION)
    detail = wait_for_ai_status(base_url, course.id, course.staff_token, q["id"])
    assert detail["ai_status"] == "ANSWERED", detail
    [post] = _ai_posts(detail)
    return detail, post


@pytest.fixture(scope="module")
def answered_question(base_url, board_course):
    """B2's question, shared read-only by B3–B5, B10, B11 and B14."""
    return _answered(base_url, board_course)


@pytest.fixture(scope="module")
def no_match_question(base_url, board_course):
    q = _ask(base_url, board_course, OFF_TOPIC_QUESTION)
    return wait_for_ai_status(base_url, board_course.id, board_course.staff_token, q["id"])


@pytest.fixture()
def ai_answered(base_url, board_course):
    """A fresh AI-answered question per test, for the K-series, which mutate it."""
    return _answered(base_url, board_course)


# ---------------------------------------------------------------------------
# Auto-responder (plan §4.6)
# ---------------------------------------------------------------------------


@pytest.mark.rag_m5
@pytest.mark.live_board
class TestAutoResponder:
    def test_b1_new_question_is_pending(self, base_url, board_course):
        """POST /questions returns ai_status (§6 "Changed shapes")."""
        q = _ask(base_url, board_course, QUINDLEWORT_QUESTION)
        assert q["ai_status"] == "PENDING"
        wait_for_ai_status(base_url, board_course.id, board_course.staff_token, q["id"])  # don't leave it queued

    def test_b2_matching_question_gets_one_ai_answer(self, answered_question):
        detail, post = answered_question
        assert len(_ai_posts(detail)) == 1
        assert post["kind"] == "ANSWER"
        assert post["is_accepted"] is False
        assert post["author"]["display_name"] == AI_DISPLAY_NAME

    def test_b3_ai_post_carries_code_attached_citations(self, answered_question, rag_health):
        """Citations come from chunk metadata, never from the model (§4.1.3)."""
        _, post = answered_question
        citations = post["citations"]
        assert isinstance(citations, list) and citations
        assert [c["rank"] for c in citations] == list(range(1, len(citations) + 1))
        for c in citations:
            assert set(c) == CITATION_KEYS
        urls = [c["source_url"] for c in citations]
        assert len(urls) == len(set(urls))
        assert post["ai_model"] == rag_health["defaults"]["model"]
        assert "\n\nSources:\n" in post["body"]
        for c in citations:
            assert f"[{c['rank']}] {c['title']} — {c['source_url']}" in post["body"]

    def test_b4_triage_still_sees_it_as_unaccepted(self, base_url, board_course, answered_question):
        """has_accepted_answer stays false until staff accept (§4.2.5)."""
        detail, _ = answered_question
        summary = _summary(base_url, board_course, detail["id"])
        assert summary["ai_status"] == "ANSWERED"
        assert summary["has_accepted_answer"] is False

    def test_b5_and_k7_student_sees_it_before_any_staff_action(self, base_url, board_course, answered_question):
        """No pre-approval gate: visible to students immediately (§1.1 T5, §4.2.5)."""
        detail, post = answered_question
        student_view = _detail(base_url, board_course, detail["id"], board_course.student_token)
        [seen] = _ai_posts(student_view)
        assert seen["id"] == post["id"]
        assert seen["citations"] == post["citations"]
        assert seen["is_accepted"] is False

    def test_b6_off_topic_is_no_match(self, no_match_question):
        assert no_match_question["ai_status"] == "NO_MATCH"
        assert no_match_question["posts"] == []

    def test_b7_course_without_default_profile_is_skipped(self, base_url, admin_token):
        course, _ = _make_board_course(base_url, admin_token)
        q = _ask(base_url, course, QUINDLEWORT_QUESTION)
        detail = wait_for_ai_status(base_url, course.id, course.staff_token, q["id"])
        assert detail["ai_status"] == "SKIPPED"
        assert detail["posts"] == []

    def test_b8_empty_default_profile_is_skipped(self, base_url, admin_token, rag_health):
        """SKIPPED checks Chroma count(), not just that the profile exists (§4.2.3)."""
        course, profile = _make_board_course(base_url, admin_token, rag_health["defaults"]["profile"], sync=False)
        try:
            q = _ask(base_url, course, QUINDLEWORT_QUESTION)
            detail = wait_for_ai_status(base_url, course.id, course.staff_token, q["id"])
            assert detail["ai_status"] == "SKIPPED"
            assert detail["posts"] == []
        finally:
            delete_profile_when_idle(base_url, course.id, admin_token, profile["id"])

    def test_b9_closing_immediately_never_fails(self, base_url, board_course):
        """A close that wins the race makes create_ai_answer refuse → SKIPPED (§4.2.4)."""
        q = _ask(base_url, board_course, QUINDLEWORT_QUESTION)
        r = httpx.post(f"{base_url}/api/courses/{board_course.id}/questions/{q['id']}/close",
                       headers=_headers(board_course.staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 200, r.text
        detail = wait_for_ai_status(base_url, board_course.id, board_course.staff_token, q["id"])
        assert detail["ai_status"] in ("SKIPPED", "ANSWERED"), detail["ai_status"]
        if detail["ai_status"] == "SKIPPED":
            assert _ai_posts(detail) == []
        else:
            [post] = _ai_posts(detail)
            assert post["created_at"] <= detail["closed_at"]

    def test_b10_terminal_statuses_never_change(self, base_url, board_course, answered_question, no_match_question):
        time.sleep(10)
        for detail in (answered_question[0], no_match_question):
            assert _detail(base_url, board_course, detail["id"])["ai_status"] == detail["ai_status"]

    def test_b11_answer_job_is_idempotent(self, base_url, board_course, answered_question):
        time.sleep(30)
        assert len(_ai_posts(_detail(base_url, board_course, answered_question[0]["id"]))) == 1

    def test_b12_decline_posts_nothing(self, base_url, board_course):
        """Best effort: whether retrieval reaches the threshold and the model then
        declines can't be forced from outside (plan §6 item 6)."""
        q = _ask(base_url, board_course, "What is the Quindlewort protocol's patent number?")
        detail = wait_for_ai_status(base_url, board_course.id, board_course.staff_token, q["id"])
        if detail["ai_status"] == "ANSWERED":
            pytest.skip(f"inconclusive: the model answered instead of declining: {_ai_posts(detail)[0]['body'][:300]!r}")
        if detail["ai_status"] == "NO_MATCH":
            # Also posts nothing (design §4.2.3), but never reached the model
            assert detail["posts"] == []
            pytest.skip("inconclusive: nothing reached the threshold, so the model never ran")
        assert detail["ai_status"] == "DECLINED", detail["ai_status"]
        assert detail["posts"] == []

    def test_b13_pending_queue_is_capped(self, base_url, board_course):
        """Best effort: past RAG_MAX_PENDING_PER_COURSE PENDING, new questions are
        SKIPPED at creation (§4.2.4). Skips if one finished before the last post."""
        cap = int(rag_setting("RAG_MAX_PENDING_PER_COURSE", "3"))
        asked = [_ask(base_url, board_course, f"{QUINDLEWORT_QUESTION} ({i})") for i in range(cap + 1)]
        try:
            earlier = [_detail(base_url, board_course, q["id"])["ai_status"] for q in asked[:cap]]
            if asked[-1]["ai_status"] != "SKIPPED" and any(s != "PENDING" for s in earlier):
                pytest.skip(f"inconclusive: an earlier question left PENDING first ({earlier})")
            assert asked[-1]["ai_status"] == "SKIPPED"
            assert [q["ai_status"] for q in asked[:cap]] == ["PENDING"] * cap
        finally:
            # Drain the queue so later tests' questions aren't capped
            for q in asked:
                wait_for_ai_status(base_url, board_course.id, board_course.staff_token, q["id"], timeout=600)

    def test_b14_followups_are_not_answered(self, base_url, board_course, answered_question):
        """Answering follow-ups is a non-goal (§1.1)."""
        qid = answered_question[0]["id"]
        r = httpx.post(f"{base_url}/api/courses/{board_course.id}/questions/{qid}/posts",
                       json={"kind": "FOLLOWUP", "body": "And what about the Quindlewort session key?"},
                       headers=_headers(board_course.student_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 201, r.text
        time.sleep(15)
        assert len(_ai_posts(_detail(base_url, board_course, qid))) == 1


@pytest.mark.live_off
@pytest.mark.rag_m2
def test_b1_new_question_is_none_when_live_is_off(base_url, course_id, student_token, category_id):
    """With RAG_LIVE_ENABLED=false nothing is attempted (§4.2.3), which is how
    harness runs keep the generation lock uncontended (§4.4.5)."""
    r = httpx.post(
        f"{base_url}/api/courses/{course_id}/questions",
        json={"title": QUINDLEWORT_QUESTION, "body": "Asking for the lab.", "category_ids": [category_id]},
        headers=_headers(student_token),
        timeout=CRUD_TIMEOUT,
    )
    assert r.status_code == 201, r.text
    assert r.json()["ai_status"] == "NONE"


# ---------------------------------------------------------------------------
# Staff acceptance (plan §4.7, design §4.2.5)
# ---------------------------------------------------------------------------


@pytest.mark.rag_m5
@pytest.mark.live_board
class TestAcceptAIAnswer:
    def test_k1_staff_accepts_ai_post(self, base_url, board_course, ai_answered):
        detail, post = ai_answered
        r = _accept(base_url, board_course, detail["id"], post["id"])
        assert r.status_code == 200, r.text
        [accepted] = _ai_posts(r.json())
        assert accepted["is_accepted"] is True
        assert accepted["accepted_by"] is not None
        assert accepted["author_role"] == "AI"
        assert accepted["citations"] == post["citations"]

    def test_k2_accepted_ai_answer_shows_in_the_list(self, base_url, board_course, ai_answered):
        detail, post = ai_answered
        assert _accept(base_url, board_course, detail["id"], post["id"]).status_code == 200
        summary = _summary(base_url, board_course, detail["id"])
        assert summary["has_accepted_answer"] is True
        assert summary["ai_status"] == "ANSWERED"

    def test_k3_student_cannot_accept(self, base_url, board_course, ai_answered):
        detail, post = ai_answered
        r = _accept(base_url, board_course, detail["id"], post["id"], headers=_headers(board_course.student_token))
        assert r.status_code == 403, r.text

    def test_k4_staff_on_student_surface_cannot_accept(self, base_url, board_course, ai_answered):
        detail, post = ai_answered
        headers = {**_headers(board_course.staff_token), "X-App-Surface": "student"}
        r = _accept(base_url, board_course, detail["id"], post["id"], headers=headers)
        assert r.status_code == 403, r.text

    def test_k5_unaccept(self, base_url, board_course, ai_answered):
        detail, post = ai_answered
        assert _accept(base_url, board_course, detail["id"], post["id"]).status_code == 200
        r = _accept(base_url, board_course, detail["id"], post["id"], accepted=False)
        assert r.status_code == 200, r.text
        assert _summary(base_url, board_course, detail["id"])["has_accepted_answer"] is False

    def test_k6_accept_through_another_questions_url_is_404(self, base_url, board_course, ai_answered):
        """Same IDOR rule as test_security.py's TestCrossResourceIDOR."""
        _, post = ai_answered
        other = _ask(base_url, board_course, "An unrelated question about lunch", token=board_course.staff_token)
        r = _accept(base_url, board_course, other["id"], post["id"])
        assert r.status_code == 404, r.text
        wait_for_ai_status(base_url, board_course.id, board_course.staff_token, other["id"])

    def test_k8_human_answer_alongside_ai(self, base_url, board_course, ai_answered):
        """Staff can still answer, and accept either; at most one post is
        accepted at a time (qa_service.set_post_accepted)."""
        detail, ai_post = ai_answered
        r = httpx.post(f"{base_url}/api/courses/{board_course.id}/questions/{detail['id']}/posts",
                       json={"kind": "ANSWER", "body": "Three handshakes: announce, confirm, lock."},
                       headers=_headers(board_course.staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 201, r.text
        human = r.json()["posts"][-1]
        assert human["author_role"] == "STAFF"

        r = _accept(base_url, board_course, detail["id"], human["id"])
        assert r.status_code == 200, r.text
        posts = {p["id"]: p for p in r.json()["posts"]}
        assert posts[human["id"]]["is_accepted"] is True
        assert posts[ai_post["id"]]["is_accepted"] is False

        r = _accept(base_url, board_course, detail["id"], ai_post["id"])
        assert r.status_code == 200, r.text
        posts = {p["id"]: p for p in r.json()["posts"]}
        assert posts[ai_post["id"]]["is_accepted"] is True
        assert posts[human["id"]]["is_accepted"] is False

    def test_k9_close_keeps_the_ai_post(self, base_url, board_course, ai_answered):
        detail, post = ai_answered
        r = httpx.post(f"{base_url}/api/courses/{board_course.id}/questions/{detail['id']}/close",
                       headers=_headers(board_course.staff_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CLOSED"
        assert [p["id"] for p in _ai_posts(r.json())] == [post["id"]]
