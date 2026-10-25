"""
Access-control integration tests for the RAG API, run against the live stack.

Like test_security.py, every test here exists because something should never
be possible: a student or outsider reaching staff-only RAG routes, the
X-App-Surface header granting STAFF, an ID from another course resolving, or
the AI system account being edited, logged into or impersonated.

Spec: docs/design-rag.md §6 (conventions and route table), §4.2 (system
user), §4.4.5 (compare auth). Case IDs (A1–A15) are from
docs/test-plan-rag.md §4.1. Every test except A15 skips, naming the
milestone, until the backend serves the route it needs.
"""

from __future__ import annotations

import httpx
import pytest

from .conftest import (
    AI_USERNAME,
    CRUD_TIMEOUT,
    OFF_TOPIC_QUESTION,
    RAG_FIXTURES,
    RagCourse,
    compare_body,
    fresh_profile,
    list_resources,
    new_course,
    rag_compare,
    rag_setting,
    rag_url,
    sync_and_wait,
    unique_name,
    upload_resource,
)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# Every route in design §6, as (method, path template, body). Path IDs come from
# rag_course so an authorized request would get past the ID lookup; the
# historical-Q&A resource is used for {rid} because DELETE on it is 409
# PROTECTED_RESOURCE even if an auth bug let the request through (§4.5.1).
# Compare is M5; everything else is M4.
_UPLOAD = {"files": {"file": ("notes.md", b"## Heading\n\nText.\n", "text/markdown")},
           "data": {"resource_type": "repository", "title": "notes"}}
_COMPARE = {"json": compare_body(OFF_TOPIC_QUESTION)}
ROUTES = [
    pytest.param("GET", "/profiles", None, id="list-profiles", marks=pytest.mark.rag_m4),
    pytest.param("POST", "/profiles", {"json": {"preset": "sliding-window", "name": "access-probe"}},
                 id="create-profile", marks=pytest.mark.rag_m4),
    pytest.param("DELETE", "/profiles/{pid}", None, id="delete-profile", marks=pytest.mark.rag_m4),
    pytest.param("POST", "/profiles/{pid}/sync", {"json": {}}, id="sync-profile", marks=pytest.mark.rag_m4),
    pytest.param("GET", "/presets", None, id="presets", marks=pytest.mark.rag_m4),
    pytest.param("GET", "/resources", None, id="list-resources", marks=pytest.mark.rag_m4),
    pytest.param("POST", "/resources",
                 {"json": {"resource_type": "syllabus", "title": "s", "url": "https://example.com/syllabus.html"}},
                 id="register-resource", marks=pytest.mark.rag_m4),
    pytest.param("POST", "/resources/upload", _UPLOAD, id="upload-resource", marks=pytest.mark.rag_m4),
    pytest.param("DELETE", "/resources/{rid}", None, id="delete-resource", marks=pytest.mark.rag_m4),
    pytest.param("POST", "/resources/{rid}/sync", {"json": {}}, id="sync-resource", marks=pytest.mark.rag_m4),
    pytest.param("GET", "/jobs", None, id="list-jobs", marks=pytest.mark.rag_m4),
    pytest.param("GET", "/jobs/{jid}", None, id="get-job", marks=pytest.mark.rag_m4),
    pytest.param("POST", "/compare", _COMPARE, id="compare", marks=pytest.mark.rag_m5),
]
# A7: the routes STAFF/ADMIN may call without side effects
READ_ROUTES = [p for p in ROUTES if p.values[0] == "GET" or p.id == "compare"]


def _call(base_url: str, course: RagCourse, method: str, template: str, body, headers: dict) -> httpx.Response:
    path = template.format(pid=course.profile["id"], rid=course.historical_qa["id"], jid=course.job["id"])
    kwargs = dict(body or {})
    timeout = 180.0 if template == "/compare" else 30.0
    return httpx.request(method, f"{rag_url(base_url, course.id)}{path}", headers=headers, timeout=timeout, **kwargs)


class TestRouteAccessMatrix:
    """design §6 conventions: 401 no token, 404 non-member, 403 student role or
    student surface. The surface header only ever clamps toward STUDENT."""

    @pytest.mark.parametrize("method,template,body", ROUTES)
    def test_a1_no_token_is_401(self, base_url, rag_course, method, template, body):
        r = _call(base_url, rag_course, method, template, body, {})
        assert r.status_code == 401, r.text
        assert r.json()["error"] == "UNAUTHORIZED"

    @pytest.mark.parametrize("method,template,body", ROUTES)
    def test_a2_course_student_is_403(self, base_url, rag_course, rag_course_student_token, method, template, body):
        r = _call(base_url, rag_course, method, template, body, _headers(rag_course_student_token))
        assert r.status_code == 403, r.text
        assert r.json()["error"] == "FORBIDDEN"

    @pytest.mark.parametrize("method,template,body", ROUTES)
    def test_a3_staff_on_student_surface_is_403(
        self, base_url, rag_course, rag_course_staff_token, method, template, body
    ):
        headers = {**_headers(rag_course_staff_token), "X-App-Surface": "student"}
        r = _call(base_url, rag_course, method, template, body, headers)
        assert r.status_code == 403, r.text
        assert r.json()["error"] == "FORBIDDEN"

    @pytest.mark.parametrize("method,template,body", ROUTES)
    def test_a4_admin_on_student_surface_is_403(self, base_url, rag_course, admin_token, method, template, body):
        headers = {**_headers(admin_token), "X-App-Surface": "student"}
        r = _call(base_url, rag_course, method, template, body, headers)
        assert r.status_code == 403, r.text
        assert r.json()["error"] == "FORBIDDEN"

    @pytest.mark.parametrize("method,template,body", ROUTES)
    def test_a5_student_claiming_staff_surface_is_403(
        self, base_url, rag_course, rag_course_student_token, method, template, body
    ):
        """The header can only clamp toward STUDENT, never grant STAFF."""
        headers = {**_headers(rag_course_student_token), "X-App-Surface": "staff"}
        r = _call(base_url, rag_course, method, template, body, headers)
        assert r.status_code == 403, r.text
        assert r.json()["error"] == "FORBIDDEN"

    @pytest.mark.parametrize("method,template,body", ROUTES)
    def test_a6_outsider_is_404(self, base_url, rag_course, outsider_token, method, template, body):
        """A non-member gets 404, not 403, so the course's existence never leaks."""
        r = _call(base_url, rag_course, method, template, body, _headers(outsider_token))
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "NOT_FOUND"

    @pytest.mark.parametrize("method,template,body", READ_ROUTES)
    @pytest.mark.parametrize("who", ["staff", "admin"])
    def test_a7_staff_and_admin_without_surface_succeed(
        self, base_url, rag_course, rag_course_staff_token, admin_token, who, method, template, body
    ):
        """The harness logs in as admin with no surface header (design §2), so
        that must be STAFF on every read route and compare."""
        token = rag_course_staff_token if who == "staff" else admin_token
        r = _call(base_url, rag_course, method, template, body, _headers(token))
        assert 200 <= r.status_code < 300, r.text


@pytest.mark.rag_m4
class TestDeniedRequestsHaveNoSideEffects:
    def test_a8_student_403s_change_nothing(self, base_url, rag_course, rag_course_student_token, admin_token):
        """A 403 must be decided before any write; a check that runs after the
        insert would still leave a profile, resource or job behind."""
        base = rag_url(base_url, rag_course.id)

        def snapshot():
            out = {}
            for path in ("/profiles", "/resources", "/jobs"):
                r = httpx.get(f"{base}{path}", headers=_headers(admin_token), timeout=CRUD_TIMEOUT)
                assert r.status_code == 200, r.text
                out[path] = r.json()
            return out

        before = snapshot()
        student = _headers(rag_course_student_token)
        notes_rid = rag_course.resources["notes.md"]["id"]
        attempts = [
            httpx.post(f"{base}/profiles", json={"preset": "sliding-window", "name": unique_name("student")},
                       headers=student, timeout=CRUD_TIMEOUT),
            httpx.post(f"{base}/resources/upload", headers=student, timeout=30.0, **_UPLOAD),
            httpx.post(f"{base}/profiles/{rag_course.profile['id']}/sync", json={}, headers=student,
                       timeout=CRUD_TIMEOUT),
            httpx.post(f"{base}/resources/{notes_rid}/sync", json={}, headers=student, timeout=CRUD_TIMEOUT),
            httpx.delete(f"{base}/resources/{notes_rid}", headers=student, timeout=CRUD_TIMEOUT),
        ]
        for r in attempts:
            assert r.status_code == 403, f"{r.request.method} {r.request.url}: {r.status_code} {r.text}"
        assert snapshot() == before


@pytest.fixture()
def other_course(base_url, admin_token):
    """Course B for the cross-course cases: a profile with a unique name, an
    uploaded resource, and the job that synced it."""
    cid = new_course(base_url, admin_token, "Other RAG Course")
    profile = fresh_profile(base_url, cid, admin_token, "sliding-window", unique_name("b-only"))
    resource = upload_resource(base_url, cid, admin_token, RAG_FIXTURES / "notes.md")
    [job] = sync_and_wait(base_url, cid, admin_token, profile_id=profile["id"])
    yield {"id": cid, "profile": profile, "resource": resource, "job": job}
    httpx.delete(f"{rag_url(base_url, cid)}/profiles/{profile['id']}", headers=_headers(admin_token),
                 timeout=CRUD_TIMEOUT)


class TestCrossCourseIDs:
    """design §6: an ID from another course returns the same 404 as a missing one."""

    @pytest.mark.rag_m4
    def test_a9_other_courses_ids_are_not_found(self, base_url, course_id, staff_token, admin_token, other_course):
        base = rag_url(base_url, course_id)
        h = _headers(staff_token)
        pid, rid, jid = other_course["profile"]["id"], other_course["resource"]["id"], other_course["job"]["id"]
        missing = 2_000_000_000
        cases = [
            ("PROFILE_NOT_FOUND", lambda i: httpx.delete(f"{base}/profiles/{i}", headers=h, timeout=CRUD_TIMEOUT)),
            ("PROFILE_NOT_FOUND",
             lambda i: httpx.post(f"{base}/profiles/{i}/sync", json={}, headers=h, timeout=CRUD_TIMEOUT)),
            ("RESOURCE_NOT_FOUND", lambda i: httpx.delete(f"{base}/resources/{i}", headers=h, timeout=CRUD_TIMEOUT)),
            ("RESOURCE_NOT_FOUND",
             lambda i: httpx.post(f"{base}/resources/{i}/sync", json={}, headers=h, timeout=CRUD_TIMEOUT)),
            ("JOB_NOT_FOUND", lambda i: httpx.get(f"{base}/jobs/{i}", headers=h, timeout=CRUD_TIMEOUT)),
        ]
        for (code, call), foreign_id in zip(cases, [pid, pid, rid, rid, jid]):
            foreign, absent = call(foreign_id), call(missing)
            assert foreign.status_code == 404, f"{foreign.request.url}: {foreign.text}"
            assert foreign.json()["error"] == code
            # Same status and code as a missing ID, so B's IDs can't be probed for
            assert (absent.status_code, absent.json()["error"]) == (404, code)

        # B's objects are untouched
        bh = _headers(admin_token)
        b = rag_url(base_url, other_course["id"])
        assert any(p["id"] == pid for p in httpx.get(f"{b}/profiles", headers=bh, timeout=CRUD_TIMEOUT).json())
        assert any(r["id"] == rid for r in list_resources(base_url, other_course["id"], admin_token))
        assert httpx.get(f"{b}/jobs/{jid}", headers=bh, timeout=CRUD_TIMEOUT).status_code == 200

    @pytest.mark.rag_m5
    def test_a10_compare_cannot_name_another_courses_profile(
        self, base_url, course_id, staff_token, other_course
    ):
        """Profiles are looked up by (course_id, name) (design §4.4.5 step 2)."""
        r = rag_compare(base_url, course_id, staff_token,
                        compare_body(OFF_TOPIC_QUESTION, ingestion_profile=other_course["profile"]["name"]))
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "PROFILE_NOT_FOUND"


@pytest.mark.rag_m1
class TestRagHealthAccess:
    """GET /api/rag/health is global: ADMIN, or STAFF in some course (design §6)."""

    def _get(self, base_url, headers):
        return httpx.get(f"{base_url}/api/rag/health", headers=headers, timeout=CRUD_TIMEOUT)

    def test_a11_health_access(self, base_url, admin_token, student_token, staff_token):
        r = self._get(base_url, {})
        assert r.status_code == 401, r.text
        assert r.json()["error"] == "UNAUTHORIZED"

        # student_token is a fresh netid that is only a student, in one course
        r = self._get(base_url, _headers(student_token))
        assert r.status_code == 403, r.text
        assert r.json()["error"] == "FORBIDDEN"

        assert self._get(base_url, _headers(staff_token)).status_code == 200
        assert self._get(base_url, _headers(admin_token)).status_code == 200

        r = self._get(base_url, {**_headers(staff_token), "X-App-Surface": "student"})
        assert r.status_code == 403, r.text

    def test_a12_health_never_leaks_the_gitlab_token(self, base_url, admin_token):
        """The token is a runtime secret; health may only say whether it is set (§4.6)."""
        r = self._get(base_url, _headers(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["gitlab_token_configured"], bool)

        def keys(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k
                    yield from keys(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from keys(v)

        token_keys = [k for k in keys(body) if "token" in k.lower()]
        assert token_keys == ["gitlab_token_configured"], token_keys
        token = rag_setting("GITLAB_TOKEN", "")
        if token:
            assert token not in r.text
        assert "glpat-" not in r.text


@pytest.mark.rag_m2
class TestAISystemAccount:
    """design §4.2: one qna-ai-assistant user, which nobody can edit, delete,
    enrol, or log in as."""

    def _ai_user(self, base_url, admin_token) -> dict:
        r = httpx.get(f"{base_url}/api/admin/users", headers=_headers(admin_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 200, r.text
        matches = [u for u in r.json() if u["username"] == AI_USERNAME]
        assert len(matches) == 1, f"expected exactly one {AI_USERNAME} user, found {len(matches)}"
        return matches[0]

    def test_a13_admin_mutations_are_409_system_account(self, base_url, admin_token, course_id):
        user = self._ai_user(base_url, admin_token)
        h = _headers(admin_token)
        users = f"{base_url}/api/admin/users/{user['id']}"
        attempts = [
            httpx.put(users, json={"display_name": "Not The AI"}, headers=h, timeout=CRUD_TIMEOUT),
            httpx.delete(users, headers=h, timeout=CRUD_TIMEOUT),
            httpx.post(f"{users}/course-access", json={"course_id": course_id, "role": "STAFF"}, headers=h,
                       timeout=CRUD_TIMEOUT),
            httpx.delete(f"{users}/course-access/{course_id}", headers=h, timeout=CRUD_TIMEOUT),
        ]
        for r in attempts:
            assert r.status_code == 409, f"{r.request.method} {r.request.url}: {r.status_code} {r.text}"
            assert r.json()["error"] == "SYSTEM_ACCOUNT"

        after = self._ai_user(base_url, admin_token)
        assert after == user

    def test_a14_ai_user_cannot_log_in(self, base_url, docker_stack):
        """It has a NULL password hash, so authenticate_local must refuse it."""
        for password in ("", "change_me_admin", "x" * 12):
            r = httpx.post(f"{base_url}/api/auth/login", json={"username": AI_USERNAME, "password": password},
                           timeout=CRUD_TIMEOUT)
            assert r.status_code != 200, r.text
            assert "access_token" not in r.text


class TestForgedAIPosts:
    def test_a15_client_cannot_post_as_ai(self, base_url, course_id, staff_token, category_id):
        """author_role is set by the server. PostCreate is extra="forbid", so a
        client-supplied author_role is rejected, not silently ignored (§4.6)."""
        r = httpx.post(
            f"{base_url}/api/courses/{course_id}/questions",
            json={"title": "Q", "body": "B", "category_ids": [category_id]},
            headers=_headers(staff_token),
        )
        assert r.status_code == 201, r.text
        question_id = r.json()["id"]

        r = httpx.post(
            f"{base_url}/api/courses/{course_id}/questions/{question_id}/posts",
            json={"kind": "ANSWER", "body": "Trust me, I'm the AI.", "author_role": "AI"},
            headers=_headers(staff_token),
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"] == "VALIDATION_ERROR"

        r = httpx.get(f"{base_url}/api/courses/{course_id}/questions/{question_id}", headers=_headers(staff_token))
        assert r.json()["posts"] == []
