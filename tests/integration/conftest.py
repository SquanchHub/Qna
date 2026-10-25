"""
Session-level fixtures for the QnA integration test suite.

Stack lifecycle
---------------
The `docker_stack` fixture detects whether the stack is already running
(by calling /api/health). If it is, nothing is started or stopped — the
dev stack is used as-is. If it is not, `docker compose up -d --build` is
run from the repo root and `docker compose down` is called on teardown.

Test isolation
--------------
Every test gets a freshly-created course (via the `course_id` fixture), so
category-name collisions and question lists don't leak between tests.
Courses have no DELETE endpoint, so they're left as inert records — same
convention as the rest of this course's projects.
"""
from __future__ import annotations

import logging
import os
import pathlib
import subprocess
import time
import uuid
from dataclasses import dataclass, field

import httpx
import pytest

logger = logging.getLogger(__name__)

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# pytest options
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )


@pytest.fixture(scope="session")
def base_url(request) -> str:
    return request.config.getoption("--base-url").rstrip("/")


# ---------------------------------------------------------------------------
# Docker stack lifecycle
# ---------------------------------------------------------------------------


def _is_healthy(url: str) -> bool:
    try:
        r = httpx.get(f"{url}/api/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _wait_healthy(url: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_healthy(url):
            return
        time.sleep(2)
    raise RuntimeError(
        f"Stack at {url} did not become healthy within {timeout}s. "
        "Check `docker compose logs backend`."
    )


@pytest.fixture(scope="session")
def docker_stack(base_url: str):
    already_running = _is_healthy(base_url)

    if not already_running:
        logger.info("Stack not detected — running docker compose up --build")
        subprocess.run(["docker", "compose", "up", "-d", "--build"], check=True, cwd=_REPO_ROOT)
        logger.info("Waiting for stack to become healthy…")
        _wait_healthy(base_url)
        logger.info("Stack is healthy")

    yield

    if not already_running:
        logger.info("Tearing down stack started by this session")
        subprocess.run(["docker", "compose", "down"], check=True, cwd=_REPO_ROOT)


# ---------------------------------------------------------------------------
# Admin token (session-scoped — one login for the whole session)
# ---------------------------------------------------------------------------


def _read_env() -> dict[str, str]:
    """Parse the repo-root .env (KEY=VALUE lines, # comments). Missing file → {}."""
    env_path = _REPO_ROOT / ".env"
    env_vars: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()
    return env_vars


@pytest.fixture(scope="session")
def admin_token(docker_stack, base_url: str) -> str:
    """Log in as the bootstrap admin. Credentials come from .env / environment."""
    return _admin_login(base_url)


def _admin_login(base_url: str) -> str:
    env_vars = _read_env()

    username = env_vars.get("ADMIN_USERNAME") or os.environ.get("ADMIN_USERNAME", "admin")
    password = env_vars.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD", "change_me_admin")

    r = httpx.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10.0,
    )
    assert r.status_code == 200, (
        f"Admin login failed ({r.status_code}): {r.text}\n"
        f"Set ADMIN_USERNAME / ADMIN_PASSWORD in .env or environment."
    )
    token = r.json().get("access_token")
    assert token, "Login response missing access_token"
    return token


def admin_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Dev-only netid login helper — mints a distinct STUDENT or STAFF identity
# and grants it course access, using the same dev fallback the frontend uses.
# ---------------------------------------------------------------------------


def login_as_netid(base_url: str, admin_token: str, course_id: int, role: str) -> str:
    netid = f"test-{role.lower()}-{uuid.uuid4().hex[:8]}"

    r = httpx.post(f"{base_url}/api/auth/login", json={"netid": netid}, timeout=10.0)
    assert r.status_code == 200, f"netid login failed: {r.text}"
    temp_token = r.json()["temp_token"]

    r = httpx.post(
        f"{base_url}/api/auth/exchange-temp",
        headers={"Authorization": f"Bearer {temp_token}"},
        timeout=10.0,
    )
    assert r.status_code == 200, f"exchange-temp failed: {r.text}"
    access_token = r.json()["access_token"]

    r = httpx.get(f"{base_url}/api/admin/users", headers=admin_headers(admin_token), timeout=10.0)
    assert r.status_code == 200
    user = next(u for u in r.json() if u["netid"] == netid)

    r = httpx.post(
        f"{base_url}/api/admin/users/{user['id']}/course-access",
        json={"course_id": course_id, "role": role},
        headers=admin_headers(admin_token),
        timeout=10.0,
    )
    assert r.status_code == 204, f"grant course-access failed: {r.text}"

    return access_token


@pytest.fixture()
def course_id(docker_stack, base_url: str, admin_token: str) -> int:
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(
        f"{base_url}/api/admin/courses",
        json={"name": f"Test Course {tag}", "semester": "Test"},
        headers=admin_headers(admin_token),
        timeout=10.0,
    )
    assert r.status_code == 201, f"Create course failed: {r.text}"
    return r.json()["id"]


@pytest.fixture()
def student_token(base_url: str, admin_token: str, course_id: int) -> str:
    return login_as_netid(base_url, admin_token, course_id, "STUDENT")


@pytest.fixture()
def staff_token(base_url: str, admin_token: str, course_id: int) -> str:
    return login_as_netid(base_url, admin_token, course_id, "STAFF")


@pytest.fixture()
def category_id(base_url: str, course_id: int, staff_token: str) -> int:
    """A default category for tests that need one to post a question but
    aren't themselves testing category behavior (every question requires
    at least one category — see QuestionCreate.category_ids)."""
    r = httpx.post(
        f"{base_url}/api/courses/{course_id}/categories",
        json={"name": "General", "description": "Default test category"},
        headers={"Authorization": f"Bearer {staff_token}"},
        timeout=10.0,
    )
    assert r.status_code == 201, f"Create category failed: {r.text}"
    return r.json()["id"]


# ---------------------------------------------------------------------------
# RAG infrastructure (docs/test-plan-rag.md §3; spec docs/design-rag.md §6)
#
# Everything below is additive: the fixtures above are unchanged, and only
# tests carrying a rag_* / gitlab / live_* / db_access / eval_corpus marker
# (registered in pytest.ini) ever touch it.
# ---------------------------------------------------------------------------

RAG_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "rag"
EVAL_SAMPLE_DATA = _REPO_ROOT / "eval" / "sample_data"

# Timeouts and budgets, test-plan §3.4
CRUD_TIMEOUT = 10.0
UPLOAD_TIMEOUT = 30.0
COMPARE_TIMEOUT = 180.0  # the harness's per-call limit (design §3 item 4)
COMPARE_BUDGET_S = 150  # design §4.4.5 timeout budget
INGEST_TIMEOUT = 120
LIVE_ANSWER_TIMEOUT = 150  # design §10 "within 150 s"
RAG_HEALTH_WAIT_S = 15 * 60  # cold start pulls models; Infinity start_period is 900 s

MINILM = "sentence-transformers/all-MiniLM-L6-v2"
GTE = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"
AI_USERNAME = "qna-ai-assistant"
AI_DISPLAY_NAME = "QnA Assistant (AI)"
# T6's baseline guardrail, verbatim (design §1.1)
BASELINE_GUARDRAIL = (
    "Only use the information provided in the tagged context to answer questions. "
    "If the context does not contain enough information to answer, say so rather "
    "than guessing."
)
BASELINE_MODEL = "qwen2.5:1.5b"
# Matches only fixtures/rag/notes.md; the off-topic question matches nothing (§3.3)
QUINDLEWORT_QUESTION = "What does the Quindlewort protocol require before a packet is accepted?"
OFF_TOPIC_QUESTION = "What's the best pizza topping?"

CHROMA_URL = "http://localhost:8001"  # dev host port for chroma (design §4.3.1)
DB_HOST, DB_PORT = "localhost", 3306
DB_TABLES = (
    "questions",
    "posts",
    "ingestion_jobs",
    "course_resources",
    "resource_profile_states",
    "ingestion_profiles",
)


def rag_setting(name: str, default: str) -> str:
    """A backend setting as the local stack sees it: .env, then environment, then
    the design §4.3.2 default. Against a remote --base-url only the default applies."""
    return _read_env().get(name) or os.environ.get(name) or default


def rag_url(base_url: str, course_id: int) -> str:
    return f"{base_url}/api/courses/{course_id}/rag"


def unique_name(prefix: str) -> str:
    """A profile name that satisfies design §5's pattern and never collides."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# -- Capability gating (test-plan §3.1) --------------------------------------

_MILESTONE_ORDER = ("m1", "m2", "m4", "m5")
_MILESTONES = {
    "m1": "M1 (Compose RAG services, GET /api/rag/health)",
    "m2": "M2 (migration 002, AI system user, ai_status)",
    "m4": "M4 (profile, resource and job APIs under /rag)",
    "m5": "M5 (pipeline, POST /rag/compare, answer job)",
}


def is_route_missing(r: httpx.Response) -> bool:
    """True when FastAPI itself answered because no route matched.

    FastAPI's unrouted 404 (or 405 for a known path with another method) is
    {"detail": "..."} with no "error" key. Every app error, including the
    course-membership 404 and RequestValidationError's 422, carries "error"
    (common/exceptions.py), so a deployed route can never look missing.
    """
    if r.status_code not in (404, 405):
        return False
    try:
        body = r.json()
    except ValueError:
        return False
    return isinstance(body, dict) and "detail" in body and "error" not in body


@dataclass
class RagCapabilities:
    available: dict[str, bool]
    evidence: dict[str, str]


def require_rag(caps: RagCapabilities, milestone: str) -> None:
    """Skip, naming the milestone, unless it and every earlier one is deployed.

    Skip rather than xfail (§3.1): once a milestone merges its tests must run,
    and CI treats a "not deployed" skip as a failure from M5 onward.
    """
    for m in _MILESTONE_ORDER[: _MILESTONE_ORDER.index(milestone) + 1]:
        if not caps.available[m]:
            needed = _MILESTONES[milestone]
            if m == milestone:
                pytest.skip(f"RAG {needed} not deployed: {caps.evidence[m]}")
            pytest.skip(f"needs RAG {needed}; {_MILESTONES[m]} not deployed: {caps.evidence[m]}")


def new_course(base_url: str, admin_token: str, label: str = "Test Course") -> int:
    r = httpx.post(
        f"{base_url}/api/admin/courses",
        json={"name": f"{label} {uuid.uuid4().hex[:8]}", "semester": "Test"},
        headers=admin_headers(admin_token),
        timeout=CRUD_TIMEOUT,
    )
    assert r.status_code == 201, f"Create course failed: {r.text}"
    return r.json()["id"]


def _probe_capabilities(base_url: str, admin_token: str) -> RagCapabilities:
    """Which RAG milestones the stack at base_url has deployed."""
    h = admin_headers(admin_token)
    available: dict[str, bool] = {}
    evidence: dict[str, str] = {}

    def route(m: str, label: str, r: httpx.Response) -> None:
        available[m] = not is_route_missing(r)
        evidence[m] = f"{label} returned FastAPI's {r.status_code} {r.text[:80]}"

    route("m1", "GET /api/rag/health", httpx.get(f"{base_url}/api/rag/health", headers=h, timeout=CRUD_TIMEOUT))

    # M2 adds no route; its observable marker is the AI system user (design §4.2)
    r = httpx.get(f"{base_url}/api/admin/users", headers=h, timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text
    available["m2"] = any(u.get("username") == AI_USERNAME for u in r.json())
    evidence["m2"] = f"no {AI_USERNAME!r} user in GET /api/admin/users"

    # Course routes need a real course, or require_course_staff's 404 would hide the route
    cid = new_course(base_url, admin_token, "RAG Probe")
    route("m4", "GET /rag/presets", httpx.get(f"{rag_url(base_url, cid)}/presets", headers=h, timeout=CRUD_TIMEOUT))
    # An empty body is a 422 once the route exists, and never runs a pipeline
    route("m5", "POST /rag/compare", httpx.post(f"{rag_url(base_url, cid)}/compare", json={}, headers=h, timeout=CRUD_TIMEOUT))

    logger.info("RAG capabilities: %s", available)
    return RagCapabilities(available, evidence)


_CAPABILITIES = pytest.StashKey[RagCapabilities]()


def _cached_capabilities(config, base_url: str, admin_token: str) -> RagCapabilities:
    if _CAPABILITIES not in config.stash:
        config.stash[_CAPABILITIES] = _probe_capabilities(base_url, admin_token)
    return config.stash[_CAPABILITIES]


@pytest.fixture(scope="session")
def rag_capabilities(request, docker_stack, base_url: str, admin_token: str) -> RagCapabilities:
    return _cached_capabilities(request.config, base_url, admin_token)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Skip rag_*-marked tests, naming the milestone, before any fixture is set up.

    This has to be a hook: pytest sets up a test's session- and module-scoped
    fixtures (rag_course, board_course, ...) before any function fixture, so
    an autouse fixture would run too late to give the test's own milestone.
    If the stack isn't up yet, docker_stack will start it and the RAG
    fixtures' own require_rag calls do the gating instead.
    """
    names = {m.name for m in item.iter_markers()}
    if "eval_corpus" in names and not os.environ.get("RAG_EVAL_CORPUS"):
        pytest.skip("eval_corpus: slow eval/sample_data smoke test; set RAG_EVAL_CORPUS=1 to run")
    milestones = [m for m in _MILESTONE_ORDER if f"rag_{m}" in names]
    if not milestones:
        return
    if _CAPABILITIES not in item.config.stash:
        base_url = item.config.getoption("--base-url").rstrip("/")
        if not _is_healthy(base_url):
            return
        item.config.stash[_CAPABILITIES] = _probe_capabilities(base_url, _admin_login(base_url))
    require_rag(item.config.stash[_CAPABILITIES], milestones[-1])


@pytest.fixture(autouse=True)
def _rag_env_gate(request):
    """Apply the environment markers, which need fixtures (rag_health may wait
    up to 15 minutes), once the milestone hook above has let the test through."""
    names = {m.name for m in request.node.iter_markers()}
    if "db_access" in names:
        require_db_access()
    if names & {"gitlab", "live_board", "live_off"}:
        health = request.getfixturevalue("rag_health")
        if "gitlab" in names and not health["gitlab_token_configured"]:
            pytest.skip("gitlab: GITLAB_TOKEN is not configured on the backend (/api/rag/health)")
        if "live_board" in names and not health["live_enabled"]:
            pytest.skip("live_board: RAG_LIVE_ENABLED is false on the backend (/api/rag/health)")
        if "live_off" in names and health["live_enabled"]:
            pytest.skip("live_off: RAG_LIVE_ENABLED is true on the backend (/api/rag/health)")


@pytest.fixture(scope="session")
def rag_health(rag_capabilities, base_url: str, admin_token: str) -> dict:
    """GET /api/rag/health, polled until Ollama, Infinity and Chroma are all ok.

    docker_stack only waits 120 s, far too short for a cold RAG stack (model
    pulls, gte download), so this waits up to 15 minutes and logs progress.
    """
    require_rag(rag_capabilities, "m1")
    deadline = time.time() + RAG_HEALTH_WAIT_S
    while True:
        r = httpx.get(f"{base_url}/api/rag/health", headers=admin_headers(admin_token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        down = [s for s in ("ollama", "infinity", "chroma") if not body[s]["ok"]]
        if not down:
            return body
        if time.time() > deadline:
            pytest.fail(f"RAG services still not ok after {RAG_HEALTH_WAIT_S}s: {down}. Body: {body}")
        logger.info("Waiting for RAG services (%s not ok yet)…", ", ".join(down))
        time.sleep(10)


# -- Direct DB and Chroma access (db_access marker; dev stack only) ----------


def _db_connect():
    import pymysql

    env = _read_env()
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user="app_user",
        password=env.get("MYSQL_PASSWORD") or os.environ.get("MYSQL_PASSWORD", ""),
        database="qna",
        connect_timeout=5,
        autocommit=True,
    )


def db_scalar(sql: str) -> int:
    conn = _db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()[0]
    finally:
        conn.close()


def db_counts() -> dict[str, int]:
    """Global COUNT(*) of every table a compare must never write (design §10)."""
    return {t: db_scalar(f"SELECT COUNT(*) FROM {t}") for t in DB_TABLES}


def _chroma_collections() -> list[tuple[str, str]]:
    """(name, count URL) per collection.

    The pinned Chroma version decides v1 vs v2 REST paths (design U4, plan
    §6 item 10). Until M1 pins it, try v2 and fall back to v1.
    """
    v2 = f"{CHROMA_URL}/api/v2/tenants/default_tenant/databases/default_database/collections"
    r = httpx.get(v2, params={"limit": 10000}, timeout=CRUD_TIMEOUT)
    if r.status_code == 200:
        return [(c["name"], f"{v2}/{c['id']}/count") for c in r.json()]
    v1 = f"{CHROMA_URL}/api/v1/collections"
    r = httpx.get(v1, timeout=CRUD_TIMEOUT)
    r.raise_for_status()
    return [(c["name"], f"{v1}/{c['id']}/count") for c in r.json()]


def chroma_counts() -> dict[str, int]:
    out = {}
    for name, count_url in _chroma_collections():
        r = httpx.get(count_url, timeout=CRUD_TIMEOUT)
        r.raise_for_status()
        out[name] = int(r.json())
    return out


def require_db_access() -> None:
    try:
        import pymysql  # noqa: F401
    except ImportError:
        pytest.skip("db_access: pymysql is not installed (pip install -r tests/integration/requirements.txt)")
    try:
        db_scalar("SELECT 1")
    except Exception as exc:
        pytest.skip(f"db_access: MySQL not reachable on {DB_HOST}:{DB_PORT} ({exc})")
    try:
        _chroma_collections()
    except Exception as exc:
        pytest.skip(f"db_access: Chroma not reachable on {CHROMA_URL} ({exc})")


# -- Request helpers (test-plan §3.2) -----------------------------------------


def fresh_profile(
    base_url: str, course_id: int, token: str, preset: str = "sliding-window", name: str | None = None
) -> dict:
    """POST /rag/profiles; returns the Profile. Prefer the make_profile fixture,
    which also deletes it (plan §3.5)."""
    body = {"preset": preset}
    if name is not None:
        body["name"] = name
    r = httpx.post(
        f"{rag_url(base_url, course_id)}/profiles", json=body, headers=admin_headers(token), timeout=CRUD_TIMEOUT
    )
    assert r.status_code == 201, r.text
    return r.json()


def get_profile(base_url: str, course_id: int, token: str, profile_id: int) -> dict:
    r = httpx.get(f"{rag_url(base_url, course_id)}/profiles", headers=admin_headers(token), timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text
    return next(p for p in r.json() if p["id"] == profile_id)


def list_resources(base_url: str, course_id: int, token: str) -> list[dict]:
    r = httpx.get(f"{rag_url(base_url, course_id)}/resources", headers=admin_headers(token), timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def get_resource(base_url: str, course_id: int, token: str, resource_id: int) -> dict:
    return next(r for r in list_resources(base_url, course_id, token) if r["id"] == resource_id)


def resource_state(resource: dict, profile_id: int) -> dict:
    return next(s for s in resource["states"] if s["profile_id"] == profile_id)


def upload_raw(
    base_url: str,
    course_id: int,
    token: str,
    filename: str,
    content: bytes,
    resource_type: str = "repository",
    citation_base_url: str | None = None,
    title: str | None = None,
) -> httpx.Response:
    """Multipart POST /rag/resources/upload, returning the raw response."""
    data = {"resource_type": resource_type, "title": title or filename}
    if citation_base_url is not None:
        data["citation_base_url"] = citation_base_url
    return httpx.post(
        f"{rag_url(base_url, course_id)}/resources/upload",
        data=data,
        files={"file": (filename, content, "application/octet-stream")},
        headers=admin_headers(token),
        timeout=UPLOAD_TIMEOUT,
    )


def upload_resource(
    base_url: str,
    course_id: int,
    token: str,
    path: pathlib.Path,
    resource_type: str = "repository",
    citation_base_url: str | None = None,
) -> dict:
    """Upload a file from disk; asserts 201 and returns the Resource."""
    r = upload_raw(base_url, course_id, token, path.name, path.read_bytes(), resource_type, citation_base_url)
    assert r.status_code == 201, r.text
    return r.json()


def wait_for_job(base_url: str, course_id: int, token: str, job_id: int, timeout: float = INGEST_TIMEOUT) -> dict:
    """Poll GET /rag/jobs/{jid} every second until SUCCEEDED or FAILED."""
    deadline = time.time() + timeout
    while True:
        r = httpx.get(f"{rag_url(base_url, course_id)}/jobs/{job_id}", headers=admin_headers(token), timeout=CRUD_TIMEOUT)
        assert r.status_code == 200, r.text
        job = r.json()
        if job["status"] in ("SUCCEEDED", "FAILED"):
            return job
        if time.time() > deadline:
            pytest.fail(f"Job {job_id} still {job['status']} after {timeout}s (error: {job['error']})")
        time.sleep(1)


def start_sync(
    base_url: str,
    course_id: int,
    token: str,
    *,
    profile_id: int | None = None,
    resource_id: int | None = None,
    profile_ids: list[int] | None = None,
) -> httpx.Response:
    """Profile sync (scope profile) or resource sync (scope resource), raw response."""
    if profile_id is not None:
        url, body = f"{rag_url(base_url, course_id)}/profiles/{profile_id}/sync", {}
    else:
        url = f"{rag_url(base_url, course_id)}/resources/{resource_id}/sync"
        body = {} if profile_ids is None else {"profile_ids": profile_ids}
    return httpx.post(url, json=body, headers=admin_headers(token), timeout=CRUD_TIMEOUT)


def sync_and_wait(
    base_url: str,
    course_id: int,
    token: str,
    *,
    profile_id: int | None = None,
    resource_id: int | None = None,
    profile_ids: list[int] | None = None,
    timeout: float = INGEST_TIMEOUT,
    expect: str | None = "SUCCEEDED",
) -> list[dict]:
    """Start a sync, wait for every job it created, and return the finished jobs."""
    r = start_sync(
        base_url, course_id, token, profile_id=profile_id, resource_id=resource_id, profile_ids=profile_ids
    )
    assert r.status_code == 202, r.text
    jobs = [r.json()] if profile_id is not None else r.json()["jobs"]
    finished = [wait_for_job(base_url, course_id, token, j["id"], timeout) for j in jobs]
    if expect is not None:
        for job in finished:
            assert job["status"] == expect, f"job {job['id']} ended {job['status']}: {job['error']}"
    return finished


def delete_profile_when_idle(base_url: str, course_id: int, token: str, profile_id: int, timeout: float = INGEST_TIMEOUT) -> None:
    """Teardown delete: retry through 409 JOB_RUNNING until the profile's job ends."""
    deadline = time.time() + timeout
    while True:
        r = httpx.delete(
            f"{rag_url(base_url, course_id)}/profiles/{profile_id}", headers=admin_headers(token), timeout=CRUD_TIMEOUT
        )
        if r.status_code in (204, 404):
            return
        if r.status_code == 409 and time.time() < deadline:
            time.sleep(2)
            continue
        logger.warning("Could not delete profile %s in course %s: %s %s", profile_id, course_id, r.status_code, r.text)
        return


def compare_body(
    question: str,
    ingestion_profile: str = "sliding-window",
    similarity_threshold: float | None = None,
    system_prompt: str = BASELINE_GUARDRAIL,
    generation_model: str = BASELINE_MODEL,
) -> dict:
    """The five-field compare request (design §4.4.5). Threshold defaults to the
    backend's RAG_DEFAULT_THRESHOLD; callers with rag_health pass defaults.threshold."""
    if similarity_threshold is None:
        similarity_threshold = float(rag_setting("RAG_DEFAULT_THRESHOLD", "0.50"))
    return {
        "question": question,
        "ingestion_profile": ingestion_profile,
        "similarity_threshold": similarity_threshold,
        "system_prompt": system_prompt,
        "generation_model": generation_model,
    }


def rag_compare(base_url: str, course_id: int, token: str, body: dict) -> httpx.Response:
    return httpx.post(
        f"{rag_url(base_url, course_id)}/compare", json=body, headers=admin_headers(token), timeout=COMPARE_TIMEOUT
    )


def wait_for_ai_status(
    base_url: str, course_id: int, token: str, question_id: int, timeout: float = LIVE_ANSWER_TIMEOUT
) -> dict:
    """Poll GET /questions/{qid} until ai_status leaves PENDING; returns the QuestionDetail."""
    deadline = time.time() + timeout
    while True:
        r = httpx.get(
            f"{base_url}/api/courses/{course_id}/questions/{question_id}",
            headers=admin_headers(token),
            timeout=CRUD_TIMEOUT,
        )
        assert r.status_code == 200, r.text
        question = r.json()
        if question["ai_status"] != "PENDING":
            return question
        if time.time() > deadline:
            pytest.fail(f"Question {question_id} still PENDING after {timeout}s")
        time.sleep(2)


@pytest.fixture()
def outsider_token(docker_stack, base_url: str) -> str:
    """A fresh netid with no course-access grant (TestAccessControl's inline pattern)."""
    r = httpx.post(f"{base_url}/api/auth/login", json={"netid": f"outsider-{uuid.uuid4().hex[:8]}"}, timeout=CRUD_TIMEOUT)
    assert r.status_code == 200, r.text
    r = httpx.post(
        f"{base_url}/api/auth/exchange-temp",
        headers={"Authorization": f"Bearer {r.json()['temp_token']}"},
        timeout=CRUD_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def make_profile(base_url: str):
    """Factory for profiles that are deleted at teardown (plan §3.5), which also
    keeps Chroma from accumulating c<cid>_p<pid> collections across runs."""
    created: list[tuple[int, str, int]] = []

    def _make(course_id: int, token: str, preset: str = "sliding-window", name: str | None = None) -> dict:
        profile = fresh_profile(base_url, course_id, token, preset, name)
        created.append((course_id, token, profile["id"]))
        return profile

    yield _make
    for course_id, token, profile_id in created:
        delete_profile_when_idle(base_url, course_id, token, profile_id)


# -- The shared, read-only RAG course (plan §3.2) ------------------------------


@dataclass
class RagCourse:
    id: int
    profile: dict  # the synced `sliding-window` profile, chunk_count refreshed
    resources: dict[str, dict] = field(default_factory=dict)  # by fixture file name
    historical_qa: dict = field(default_factory=dict)
    job: dict = field(default_factory=dict)  # the profile sync that made it READY


@pytest.fixture(scope="session")
def rag_course(request, rag_capabilities, base_url: str, admin_token: str):
    """One course with a `sliding-window` profile and the fixture corpus synced
    to READY. Read-only tests share it so the suite does not re-ingest per test."""
    require_rag(rag_capabilities, "m4")
    rag_health = request.getfixturevalue("rag_health")  # after the M4 check
    course_id = new_course(base_url, admin_token, "RAG Course")
    profile = fresh_profile(base_url, course_id, admin_token, "sliding-window")
    resources = {
        name: upload_resource(base_url, course_id, admin_token, RAG_FIXTURES / name, rtype)
        for name, rtype in (("notes.md", "repository"), ("slides.pdf", "repository"), ("syllabus.html", "syllabus"))
    }
    [job] = sync_and_wait(base_url, course_id, admin_token, profile_id=profile["id"])
    historical = next(
        r for r in list_resources(base_url, course_id, admin_token) if r["resource_type"] == "historical_qa"
    )
    course = RagCourse(
        id=course_id,
        profile=get_profile(base_url, course_id, admin_token, profile["id"]),
        resources=resources,
        historical_qa=historical,
        job=job,
    )

    if rag_capabilities.available["m5"]:
        # Pay the first Ollama model load here, not inside a timed test (plan §3.4)
        r = rag_compare(
            base_url,
            course_id,
            admin_token,
            compare_body(QUINDLEWORT_QUESTION, similarity_threshold=rag_health["defaults"]["threshold"]),
        )
        logger.info("RAG warm-up compare: %s", r.status_code)

    yield course
    delete_profile_when_idle(base_url, course_id, admin_token, profile["id"])


@pytest.fixture(scope="session")
def rag_course_staff_token(base_url: str, admin_token: str, rag_course: RagCourse) -> str:
    return login_as_netid(base_url, admin_token, rag_course.id, "STAFF")


@pytest.fixture(scope="session")
def rag_course_student_token(base_url: str, admin_token: str, rag_course: RagCourse) -> str:
    return login_as_netid(base_url, admin_token, rag_course.id, "STUDENT")
