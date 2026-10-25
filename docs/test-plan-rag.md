# RAG Integration Test Plan

Status: implemented in `tests/integration/test_rag_*.py` (every case skips, naming its milestone, until that milestone is deployed). Owner: varikooty (`tests/integration/test_rag_*.py`, per `docs/schedule.md` and design §9). Spec under test: `docs/design-rag.md` (§6 API reference, plus §4.2, §4.4.5, §4.5 and §10 that §6 depends on). If this plan and the design disagree, the design wins; fix this plan.

---

## 1. Patterns the existing suite establishes (new tests must follow them)

Read from `tests/integration/conftest.py`, `test_qa_flow.py`, `test_security.py`, `pytest.ini` and `requirements.txt`.

### 1.1 How tests reach the stack

- **Live stack only, over HTTP.** Tests call the real backend with plain synchronous `httpx.get/post/patch(...)`. There is no `TestClient`, no app import and no DB fixture. `asyncio_mode = auto` is set, but no test is async; RAG tests stay synchronous too.
- **Base URL** comes from `--base-url` (default `http://localhost:8000`) via the session `base_url` fixture. Every URL is built as `f"{base_url}/api/..."`. Never hard-code a host.
- **Stack lifecycle.** The session `docker_stack` fixture checks `GET /api/health`. If the stack is already up it is reused and left running. If not, it runs `docker compose up -d --build`, waits up to 120 s, and runs `docker compose down` at teardown. RAG tests reach it through `admin_token` and `course_id`, so they need no extra dependency. **The 120 s wait is too short for a cold RAG stack** (the Infinity `start_period` is 900 s and model pulls run on first boot). RAG tests therefore wait on `/api/rag/health` themselves (§3.2), and the plan's run instructions say to start the stack yourself first.

### 1.2 How identities, courses and categories are made

| Thing | Mechanism | Scope |
|---|---|---|
| Admin | `admin_token`: `POST /api/auth/login {username, password}`, credentials from `.env` (`ADMIN_USERNAME`/`ADMIN_PASSWORD`), falling back to the environment, then `admin`/`change_me_admin` | session |
| Course | `course_id`: `POST /api/admin/courses {name: "Test Course <hex8>", semester: "Test"}` as admin, expecting 201 | **per test** |
| Student / staff | `login_as_netid(base_url, admin_token, course_id, role)`: dev netid login with a fresh `test-<role>-<hex8>` netid, then `POST /api/auth/exchange-temp`, then a `GET /api/admin/users` lookup, then `POST /api/admin/users/{id}/course-access {course_id, role}` (204) | the `student_token` and `staff_token` fixtures are per test, bound to `course_id` |
| Outsider (non-member) | Done inline in the test: netid login plus exchange-temp with **no** course-access grant (`TestAccessControl` in `test_qa_flow.py`) | per test |
| Category | `category_id`: staff `POST /courses/{cid}/categories`. Every question needs `category_ids` | per test |
| Second course | Inline admin `POST /api/admin/courses` (`TestCrossResourceIDOR`) | per test |

`login_as_netid` is a plain function, not a fixture, so session-scoped RAG fixtures can call it for their own course.

### 1.3 Conventions

- **Auth header.** Each test file defines its own local helper, `_headers(token)` in `test_qa_flow.py` and `admin_headers(token)` in `test_security.py`, rather than importing from conftest. RAG files do the same.
- **Surface clamp.** `X-App-Surface: student` is added to the headers to check that staff or admin is clamped to STUDENT. `X-App-Surface: staff` must never grant STAFF.
- **Status codes.** A non-member gets **404, not 403**, so a course's existence never leaks. A wrong role gets 403. No token gets 401. A missing ID and an ID belonging to another course return the **same 404**.
- **Assertions.** `assert r.status_code == N, r.text` (the body goes in the message), then assertions on the JSON. Errors have the shape `{"error": CODE, "message": ...}`, so RAG tests assert the `error` code as well as the status.
- **Grouping.** Tests are grouped in `class Test<Behavior>:`. The module docstring says what the file is for. Docstrings on tests explain *why* something must hold.
- **Isolation.** A fresh course per test, never deleted (there is no course DELETE). Unique names come from `uuid4().hex[:8]`. Tests never depend on order or on seeded data.
- **Timeouts.** conftest passes `timeout=10.0`. Most tests use the httpx default (5 s), and the upload test passes 15 s. RAG calls need explicit, larger timeouts (§3.4).
- **File placement.** `test_security.py` holds "should never be possible" tests (escalation, cross-tenant leaks, bypasses). `test_qa_flow.py` holds feature behavior. Both are **unchanged and must stay green** (R8). RAG tests go in new `test_rag_*.py` files.
- **Dependencies.** `requirements.txt` lists only pytest, pytest-asyncio, httpx and python-dotenv. The dry-run test adds `pymysql` (design §8). A Chroma check can use plain httpx against Chroma's REST API, so it does not need `chromadb-client` in the test env.

---

## 2. Files

This follows design §8. Profiles and re-sync are ingestion concerns, and acceptance is a board concern:

| File | Covers |
|---|---|
| `test_rag_access.py` | 401/403/404 matrix for every `/rag` route and `/api/rag/health`, cross-course IDs, AI system-user guards |
| `test_rag_ingestion.py` | Presets, profiles, resources (upload and URL paths), jobs, re-sync, coexistence, historical Q&A selection |
| `test_rag_compare.py` | `/rag/compare` contract, errors, threshold behavior, **no-writes guarantee** |
| `test_rag_board.py` | Auto-responder (`ai_status` lifecycle, AI post shape, citations), staff acceptance of AI posts |
| `fixtures/rag/` | Small committed corpus (§3.3) |

---

## 3. Shared infrastructure (add to `conftest.py` without changing existing fixtures)

### 3.1 Capability gating

Each RAG module probes what the stack supports and **skips with a reason naming the milestone** instead of failing with confusing errors on a stack that predates it:

- **Route present?** FastAPI's unknown-route 404 body is `{"detail": "Not Found"}`. The app's own 404s are `{"error": ...}`. A helper `rag_routes_available(base_url, token)` calls `GET /courses/{cid}/rag/presets` and treats a `detail`-only 404 as "not deployed".
- **Markers** (register them in `pytest.ini`): `rag_m1` (health), `rag_m2` (schema, `ai_status`, system user), `rag_m4` (ingestion APIs), `rag_m5` (compare and board), `gitlab` (needs `GITLAB_TOKEN` on the backend, which is read from `/api/rag/health` → `gitlab_token_configured`), `live_board` (needs `live_enabled: true`), `db_access` (needs MySQL on `localhost:3306` and Chroma on `localhost:8001`).
- **Skip, not xfail.** Once a milestone merges, its tests must run and pass. CI treats a skip whose reason says "not deployed" as a failure from M5 onward. That way the gating cannot hide a regression after the routes exist.

### 3.2 New fixtures and helpers

| Name | Scope | Purpose |
|---|---|---|
| `rag_health` | session | `GET /api/rag/health` as admin, polled until `ollama.ok`, `infinity.ok` and `chroma.ok` (≤ 15 min, log progress). Exposes `live_enabled`, `defaults`, `ollama.models`, `infinity.models` for skip decisions |
| `rag_course` | **session** | One course with staff and student tokens, a `sliding-window` profile, and the fixture corpus uploaded and synced to READY. **Read-only** tests (compare contract, access matrix) use it so the suite does not re-ingest per test |
| `rag_course_staff_token`, `rag_course_student_token` | session | `login_as_netid` against `rag_course` |
| `fresh_profile(course_id, token, preset="sliding-window")` | helper | `POST /rag/profiles`, returns a Profile |
| `upload_resource(course_id, token, path, resource_type, citation_base_url=None)` | helper | multipart `POST /rag/resources/upload` |
| `wait_for_job(course_id, token, job_id, timeout)` | helper | polls `GET /rag/jobs/{jid}` every 1 s until `SUCCEEDED`/`FAILED`. Fails with the job's `error` on timeout |
| `sync_and_wait(...)` | helper | resource or profile sync, then `wait_for_job` on each returned job |
| `wait_for_ai_status(course_id, token, qid, timeout=150)` | helper | polls `GET /questions/{qid}` until `ai_status != "PENDING"` |
| `outsider_token` | function | the inline outsider pattern from `test_qa_flow.py`, made a fixture |
| `db_counts()` | helper | `pymysql` against `localhost:3306` (db `qna`, user `app_user`, password `MYSQL_PASSWORD` from `.env`). Returns `COUNT(*)` for `questions`, `posts`, `ingestion_jobs`, `course_resources`, `resource_profile_states`, `ingestion_profiles` |
| `chroma_counts()` | helper | Chroma REST on `localhost:8001`: list collections, then `count` for each. Returns `{name: n}` |

Refactor conftest's inline `.env` parser into `_read_env()` so `admin_token` and `db_counts` share it, without changing `admin_token`'s behavior.

### 3.3 Fixture corpus (`tests/integration/fixtures/rag/`)

Keep it small so MiniLM ingestion takes seconds, and make it **deterministic to match**:

- `notes.md`: three `##` sections, one containing a nonsense term found nowhere else (for example "the **Quindlewort protocol** requires three handshakes"), plus a fenced code block containing a `# not a heading` line. A question about the Quindlewort protocol must match; "best pizza topping?" must not.
- `slides.pdf`: 2–3 pages, each with a distinct nonsense term. Commit it, generated once by a script that is also committed.
- `repo.zip`: `top/notes.md` plus `top/docs/slides.pdf` (a shared top-level dir that must be stripped) and a `.txt` that must be ignored.
- `syllabus.html`: a tiny page with `<nav>`, `.sr-only` and `<script>` noise around one `<main>` section.
- **Generated at runtime, never committed:** a zip-slip archive (`../evil.md`), a zip with a symlink entry, a payload over `MAX_UPLOAD_MB`, and a `.exe`/`.txt` upload. Build them with `zipfile`/`io.BytesIO`.
- A few tests use `eval/sample_data/` directly where the real paths matter (ground-truth substring checks).

### 3.4 Timeouts and budgets

- Plain CRUD calls: `timeout=10`.
- Upload: `30`.
- Compare: `timeout=180` (the harness limit). A matched compare is asserted at ≤ 150 s (design budget).
- Ingest wait: 120 s for the fixture corpus on MiniLM.
- Live answer wait: 150 s (design §10).
- **First-call cost.** The first compare or live answer after a model switch pays the Ollama load. A session-scoped warm-up compare inside `rag_course` keeps that cost out of per-test assertions.

### 3.5 Leftovers

Courses still cannot be deleted. RAG adds Chroma collections `c<cid>_p<pid>` and upload files. Tests that create profiles **delete them at the end** (in a `try/finally` or a yield fixture). This also exercises `DELETE /rag/profiles` and keeps Chroma from growing across runs. Courses stay as inert rows, as before.

---

## 4. Test cases

IDs are stable so MRs can reference them. **Gate** is the earliest milestone whose code the test needs (§5).

### 4.1 Access control (`test_rag_access.py`)

The parametrized matrix covers every route in §6: `GET/POST /rag/profiles`, `DELETE /rag/profiles/{pid}`, `POST /rag/profiles/{pid}/sync`, `GET /rag/presets`, `GET/POST /rag/resources`, `POST /rag/resources/upload`, `DELETE /rag/resources/{rid}`, `POST /rag/resources/{rid}/sync`, `GET /rag/jobs`, `GET /rag/jobs/{jid}`, `POST /rag/compare`. Each case is `(method, path_template, valid_body)`, with IDs taken from `rag_course` so a request reaches the auth check and not a 404.

| ID | Case | Expect | Gate |
|---|---|---|---|
| A1 | No token, each route | 401 `UNAUTHORIZED` | M4 (compare: M5) |
| A2 | **STUDENT** of the course, each route | **403 `FORBIDDEN`** | M4/M5 |
| A3 | STAFF with `X-App-Surface: student`, each route | 403 | M4/M5 |
| A4 | ADMIN with `X-App-Surface: student`, each route | 403 | M4/M5 |
| A5 | STUDENT with `X-App-Surface: staff`, each route | 403 (the header never grants) | M4/M5 |
| A6 | Outsider (no course access), each route | 404 `NOT_FOUND` | M4/M5 |
| A7 | STAFF and ADMIN (no surface header, which is how the harness logs in) on the GET routes and compare | 2xx | M4/M5 |
| A8 | **A student's 403 causes no side effect.** Student `POST /rag/profiles`, `POST /rag/resources/upload`, `POST .../sync`, `DELETE /rag/resources/{rid}`, then staff re-lists them | Profile, resource and job lists unchanged | M4 |
| A9 | Cross-course IDs. Staff of course A uses course B's `pid`/`rid`/`jid` under A's URL on GET/DELETE/sync | 404 `PROFILE_NOT_FOUND` / `RESOURCE_NOT_FOUND` / `JOB_NOT_FOUND`, the same body as a missing ID. B's object still exists afterwards | M4 |
| A10 | Compare naming course B's profile by name, from course A | 404 `PROFILE_NOT_FOUND` | M5 |
| A11 | `GET /api/rag/health`: none → 401; a user who is only a student anywhere → 403; staff of some course → 200; admin → 200; staff with student surface → 403 | as stated | M1 |
| A12 | Health never leaks the token: the body has `gitlab_token_configured` (bool) and no key or value containing the token | — | M1 |
| A13 | AI system user. Find `username == "qna-ai-assistant"` in `GET /api/admin/users`. Then `PUT /admin/users/{id}`, `DELETE /admin/users/{id}`, `POST .../course-access`, `DELETE .../course-access/{cid}` | each 409 `SYSTEM_ACCOUNT`, and the user still exists | M2 |
| A14 | The AI user cannot log in: `POST /api/auth/login {username: "qna-ai-assistant", password: <anything>}` | not 200 | M2 |
| A15 | A client cannot forge an AI post: `POST .../posts {kind, body, author_role: "AI"}` as staff | 422 (`PostCreate` is `extra="forbid"`) | today |

### 4.2 Profiles (`test_rag_ingestion.py::TestProfiles`)

| ID | Case | Expect | Gate |
|---|---|---|---|
| P1 | `GET /rag/presets` | 200 list containing `sliding-window`, `type-tailored`, `embedding-alt`, each with `embedding_model`, `query_instruction`, `chunking` (§4.4.1 shape) | M4 |
| P2 | `POST {preset: "sliding-window"}` | 201. `name == preset`, the MiniLM model, `chunk_count == 0`, `collection_name == f"c{cid}_p{id}"`, `active_job_id is None`, `created_at` ends in `Z` | M4 |
| P3 | `POST {preset: "sliding-window", name: "sw-copy"}` | 201 with that name. The two profiles coexist | M4 |
| P4 | Same name again | 409 `DUPLICATE_PROFILE` | M4 |
| P5 | The same name in a **different** course | 201 (uniqueness is per course) | M4 |
| P6 | `POST {preset: "nope"}` | 422 `UNKNOWN_PRESET` | M4 |
| P7 | Invalid names (`"A"`, `"-x-"`, 65 chars, `"has space"`) and an extra field | 422 `VALIDATION_ERROR` | M4 |
| P8 | A preset whose model Infinity does not serve. **Conditional:** run only if `rag_health.infinity.models` lacks a preset's model (for example gte dropped on a low-RAM laptop) | 422 `EMBEDDING_MODEL_NOT_SERVED` | M4 |
| P9 | `GET /rag/profiles` lists P2 and P3. No PATCH/PUT route exists (`PATCH` → 405) | — | M4 |
| P10 | `DELETE` → 204, then `GET` omits it. Compare on its name → 404 `PROFILE_NOT_FOUND`. Its Chroma collection is gone (`db_access`) | — | M4 / M5 for compare |
| P11 | Delete a missing pid | 404 `PROFILE_NOT_FOUND` | M4 |
| P12 | Delete while that profile's job is QUEUED/RUNNING | 409 `JOB_RUNNING` (see §6.5 on timing) | M4 |

### 4.3 Resources and ingestion (`TestResources`, `TestUploadPath`, `TestUrlPath`, `TestHistoricalQA`)

| ID | Case | Expect | Gate |
|---|---|---|---|
| R1 | A new course already lists exactly one `historical_qa` resource (`source_kind: "internal"`). Listing twice creates no duplicate | — | M4 (created at M2/M4) |
| R2 | `DELETE` historical Q&A resource | 409 `PROTECTED_RESOURCE` | M4 |
| R3 | Upload `notes.md` as `repository` | 201, `states` shows each course profile as `NEVER`, `chunk_count: 0` | M4 |
| R4 | Sync R3 to the profile → READY. `chunk_count > 0`. Compare on the Quindlewort question returns a `repo_markdown` chunk whose `source_url` is `upload://<rid>/notes.md#L<a>-<b>`-shaped (design §4.1.1 inserts `?plain=1` only for a GitLab `/-/blob/` base, so it is optional here), or uses `citation_base_url` when it was given | — | M4 (compare: M5) |
| R5 | Upload `notes.md` with `citation_base_url = "https://git.doit.wisc.edu/x/y/-/blob/<sha>/dir/notes.md"` (for a single file the base is the file's URL; only a zip joins it with the in-zip path, design §4.1.1). The compare `source_url` starts with the base, includes `/notes.md?plain=1#L` | — | M5 |
| R6 | Upload `repo.zip` and sync. Compare chunks include `repo_markdown` and `repo_pdf`. The PDF `source_url` contains `#page=` with the right 1-based page. The top dir is stripped from the path. The `.txt` is not ingested (its nonsense term never matches) | — | M5 |
| R7 | Upload `syllabus.html` as `syllabus`. The matched chunk's `text` has no nav, sr-only or script text. `source_url` contains `#:~:text=` | — | M5 |
| R8 | Unsafe uploads: zip-slip, symlink entry | 422 `UNSAFE_ARCHIVE` | M4 |
| R9 | `.exe` or `.txt` as a single file | 422 `UNSUPPORTED_FILE` | M4 |
| R10 | Over `MAX_UPLOAD_MB` | 413 `PAYLOAD_TOO_LARGE` | M4 |
| R11 | Register URL validation: `ftp://…`, `git_ref` on a syllabus, `subpath: "../x"`, a 40-hex `git_ref` on a repository | 422 `VALIDATION_ERROR` | M4 |
| R12 | SSRF: `http://localhost/`, `http://10.0.0.1/`, `http://169.254.169.254/latest/meta-data`, `http://ollama:11434/`, `http://mysql:3306/` | 422 `URL_NOT_ALLOWED` | M4 |
| R13 | **GitLab** (`gitlab`): register repo `https://git.doit.wisc.edu/<ns>/qna-74`, `git_ref: main`, `subpath: eval/sample_data/repo`, then sync. READY. `last_commit_sha` is 40 hex. Compare `source_url`s contain `eval/sample_data/repo/` and `/-/blob/<sha>/`. No `source_url`, job error or resource field contains the token | — | M5 |
| R14 | **GitLab file URL** (`gitlab`): syllabus at `…/-/blob/main/eval/sample_data/web/syllabus.html` → READY. `source_url` contains `eval/sample_data/web/syllabus.html` (harness substring rule, design §3.1) | — | M5 |
| R15 | Delete a resource → 204. Its chunks are gone from every profile collection (compare no longer returns its term; `chroma_counts` drop). `chunk_count` refreshed | — | M4 (compare: M5) |
| R16 | Delete a resource while a job touching it is active | 409 `JOB_RUNNING` | M4 |
| H1 | Historical Q&A selection. Make threads in a fresh course: (a) student answer **accepted**; (b) **closed** with a STAFF answer, not accepted; (c) closed with only a student answer; (d) open and unanswered; (e) open with an unaccepted student answer. Give each a unique nonsense term. Sync historical Q&A, then compare at threshold 0.0 for each term | (a) and (b) retrieved as `historical_qa`, `source_url` = `<FRONTEND_URL>/student/questions/<qid>?course=<cid>`. (c), (d), (e) never appear | M5 |
| H2 | **Accepted AI post is excluded** (`live_board`): an AI-answered, staff-accepted thread (from B-series setup) is not in historical Q&A after sync | — | M5 + live |
| H3 | Historical Q&A does **not** auto-sync: accepting a new answer after a sync leaves the collection count unchanged until staff sync again | — | M5 |

### 4.4 Jobs and re-sync (`TestJobs`, `TestResync`, `TestCoexistence`)

| ID | Case | Expect | Gate |
|---|---|---|---|
| J1 | `POST /rag/profiles/{pid}/sync {}` | 202 Job, `scope: "profile"`, `resource_id: null`, status `QUEUED`/`RUNNING`. The profile shows `active_job_id`. Ends `SUCCEEDED`. `started_at`/`finished_at` are set and end in `Z` | M4 |
| J2 | `POST /rag/resources/{rid}/sync {}` with two profiles | 202 `{"jobs": [two jobs]}`, `scope: "resource"`, `resource_id == rid` | M4 |
| J3 | `{"profile_ids": [p1]}` | exactly one job, for p1. p2's state unchanged | M4 |
| J4 | `{"profile_ids": []}` | 422 `VALIDATION_ERROR` | M4 |
| J5 | `profile_ids` with another course's pid | 404 `PROFILE_NOT_FOUND`, no jobs created | M4 |
| J6 | Resource sync in a course with no profiles | 409 `NO_PROFILES` | M4 |
| J7 | Second profile sync while one is active | 409 `JOB_RUNNING` | M4 |
| J8 | **All-or-nothing:** p1 has an active job and resource sync targets [p1, p2] | 409 `JOB_RUNNING`. `GET /rag/jobs` shows no new job for p2 | M4 |
| J9 | `GET /rag/jobs` is newest first. `limit=1` returns 1. `limit=0` and `limit=101` → 422. `status=SUCCEEDED` filters | — | M4 |
| J10 | `GET /rag/jobs/{missing}` and another course's jid | 404 `JOB_NOT_FOUND` | M4 |
| S1 | **Unchanged re-sync** of an uploaded resource | job `chunks_added == 0`, `chunks_deleted == 0`, `chunks_updated == previous chunk_count`. Resource `chunk_count` and Chroma count are equal before and after. The resource keeps its id (no delete and re-add) | M4 |
| S2 | Re-sync updates `last_synced_at` (strictly later) and keeps the state READY | — | M4 |
| S3 | **Failed fetch deletes nothing** (weak form): profile with a READY uploaded resource A plus a URL resource B that cannot be fetched. Profile sync → job `FAILED`, B's state `FAILED` with `error`, A still READY, A's chunks still returned by compare, collection count ≥ A's count | — | M4 (see §6.3–6.4) |
| S4 | **GitLab re-sync** (`gitlab`): re-sync R13 → `chunks_added == 0`, the same `last_commit_sha` | — | M5 |
| C1 | **Coexistence:** profiles `sliding-window` and `type-tailored` in one course, both synced. Separate `collection_name`s, both counts > 0, chunk counts differ (different chunking). Re-syncing one leaves the other's count and `last_synced_at` unchanged | — | M4 |
| C2 | Delete one of C1's profiles. Compare on the other still returns `matched: true` for the Quindlewort question | — | M5 |
| C3 | Two `sliding-window`-chunked profiles with different embedding models (`embedding-alt`, only if gte is served) have **equal** `chunk_count` (design §4.4.1 "byte-identical") | — | M4, conditional |

### 4.5 Compare (`test_rag_compare.py`)

These tests use the session `rag_course`. The baseline body is `{question, ingestion_profile: "sliding-window", similarity_threshold: <defaults.threshold>, system_prompt: <T6 guardrail verbatim>, generation_model: "qwen2.5:1.5b"}`.

| ID | Case | Expect | Gate |
|---|---|---|---|
| X1 | Matched (Quindlewort question) | 200. Top-level keys are **exactly** `{matched, retrieved_chunks, answer, metrics}`. `matched is True`. Each chunk has exactly `{resource_type, source_url, similarity_score, text}` with types str/str/float/str. Scores are within [threshold, 1], sorted descending, with ≤ 4 decimals. `len ≤ RAG_TOP_K`. `answer` is a non-empty str with **no** `Sources:` block. `metrics` keys are exactly the four; the three `*_ms` are int ≥ 0, `generation_time_ms > 0`, `cpu_percent` is a float in [0, 100] | M5 |
| X2 | Off-topic ("What's the best pizza topping?") | `matched: false`, `retrieved_chunks: []`, `answer: null`, `generation_time_ms == 0` | M5 |
| X3 | Threshold flips: the same matched question at `0.99` | `matched: false`. At `0.0`, `len(retrieved_chunks) == RAG_TOP_K` (or the collection size if smaller) | M5 |
| X4 | Raw (unrounded) comparison: set the threshold to the top chunk's displayed score + 0.00004. The result is consistent with the raw score (allow either outcome only within rounding; assert no chunk is returned whose displayed score is < threshold − 0.00005) | — | M5 |
| X5 | Unknown profile name | 404 `PROFILE_NOT_FOUND` | M5 |
| X6 | Profile exists with 0 chunks | 409 `PROFILE_EMPTY` | M5 |
| X7 | `generation_model: "nonexistent:1b"` with a **matching** question, and again with the **off-topic** question | 422 `MODEL_NOT_AVAILABLE` both times (checked before retrieval) | M5 |
| X8 | Untagged model name (`"qwen2.5"` when only `qwen2.5:1.5b` is pulled) | 422, not a silent fallback. If `:latest` is pulled, then 200 | M5 |
| X9 | Validation: each of the five fields missing; an extra field (`"top_k": 3`); `similarity_threshold` 1.5 and −0.1; `question` empty or whitespace only; `question` 4001 chars; `system_prompt` 8001 chars; `ingestion_profile` 65 chars | 422 `VALIDATION_ERROR` each | M5 |
| X10 | Edge values accepted: threshold `0.0` and `1.0`, a 4000-char question | 200 | M5 |
| X11 | A different `system_prompt` changes nothing in retrieval: `retrieved_chunks` is identical to X1's (same URLs and scores) | — | M5 |
| X12 | The second pulled model (`qwen2.5:3b`, only if in `ollama.models`): same retrieval as X1, 200 within 180 s | — | M5 |
| X13 | Latency: a matched compare finishes in ≤ 150 s after warm-up | — | M5 |
| X14 | Compare on `eval/sample_data` (optional, slow, marker `eval_corpus`): the q01–q11 questions' top-K contains `expected_source` by substring. q14 → `matched: false`. Smoke only; the harness does the real scoring | — | M5 |

#### No-writes guarantee (`TestCompareIsDryRun`, `db_access`)

| ID | Case | Expect | Gate |
|---|---|---|---|
| D1 | Take `db_counts()` and `chroma_counts()`. Run **three** compares: one matched, one off-topic, one error (`MODEL_NOT_AVAILABLE`). Take the counts again | Every MySQL count (`questions`, `posts`, `ingestion_jobs`, `course_resources`, `resource_profile_states`, `ingestion_profiles`) and every Chroma collection count is **unchanged** | M5 |
| D2 | Scoped check, also usable against the VM without DB ports: list `rag_course`'s questions (as staff), profiles, resources and jobs before and after the same three calls | identical JSON (ignoring nothing) | M5 |
| D3 | Compare never triggers the auto-responder: after D1, no question in `rag_course` has `ai_status` other than its previous value | — | M5 |

**Flake guard for D1.** The counts are global, so any background writer breaks D1: live answer jobs from other tests, a running ingestion job, or a human using the dev stack. Before taking counts, D1 (a) waits until `SELECT COUNT(*) FROM questions WHERE ai_status='PENDING'` is 0 and no `ingestion_jobs` row is `QUEUED`/`RUNNING`, with a 180 s cap, then (b) takes the counts twice 2 s apart and requires them to be equal. If they are not equal, it **skips** with "stack not quiescent" rather than failing. The `posts` and `questions` counts must be inside the guarded window.

### 4.6 Auto-responder (`test_rag_board.py::TestAutoResponder`)

This setup uses a per-module course with the default profile (`RAG_DEFAULT_PROFILE`, normally `sliding-window`), the fixture corpus synced, and `live_board` (skip unless `rag_health.live_enabled`).

| ID | Case | Expect | Gate |
|---|---|---|---|
| B1 | `POST /questions` response includes `ai_status` | `PENDING` with live on. `NONE` with live off (this runs in a separate `live_off` marker case if CI ever runs with it off) | M2 (field), M5 |
| B2 | Matching question (Quindlewort) → `wait_for_ai_status` | `ANSWERED` within 150 s. Exactly **one** post with `author_role == "AI"`, `kind == "ANSWER"`, `is_accepted False`, author display name `"QnA Assistant (AI)"` | M5 |
| B3 | AI post shape | `citations` is a non-empty list, rank-ordered from 1, each `{rank, resource_type, title, source_url, similarity_score}`. `source_url`s are unique. `ai_model == defaults.model`. The body contains `"\n\nSources:\n"` and a `[1] <title> — <source_url>` line for each citation | M5 |
| B4 | `GET /questions` summary shows `ai_status: "ANSWERED"` and `has_accepted_answer: false` (triage still sees it) | — | M5 |
| B5 | A student sees the same AI post and citations (`GET /questions/{qid}` as student) | — | M5 |
| B6 | Off-topic question | `NO_MATCH`, zero posts | M5 |
| B7 | Course with **no** default profile (fresh `course_id`) | `SKIPPED`, zero posts (the existing `test_qa_flow` tests take this path too) | M5 |
| B8 | Default profile exists but is empty (0 chunks) | `SKIPPED` | M5 |
| B9 | Close race: post a matching question, then close it immediately | final status ∈ {`SKIPPED`, `ANSWERED`}, **never `FAILED`**. If `SKIPPED`, no AI post. If `ANSWERED`, the post was created before the close | M5 |
| B10 | Terminal statuses never change: re-read B2's and B6's questions after 10 s | unchanged | M5 |
| B11 | Idempotency: B2's question never gains a second AI post (re-read after a further 30 s) | — | M5 |
| B12 | `DECLINED` (best effort, may skip): a question that retrieves the corpus at threshold but asks for something absent ("What is the Quindlewort protocol's patent number?") | if `DECLINED`, zero posts. If `ANSWERED`, the test is inconclusive → `pytest.skip` with the answer logged (the model decides; it cannot be forced from outside) | M5 |
| B13 | Queue cap (best effort): post `RAG_MAX_PENDING_PER_COURSE + 1` matching questions back-to-back | the last returns `SKIPPED` at creation, **or** the test skips if an earlier one already left PENDING (timing-dependent) | M5 |
| B14 | Follow-ups are not answered: a FOLLOWUP on an answered thread gets no new AI post | — | M5 |

### 4.7 Staff acceptance of AI posts (`test_rag_board.py::TestAcceptAIAnswer`)

| ID | Case | Expect | Gate |
|---|---|---|---|
| K1 | Staff `PATCH .../posts/{ai_post_id}/accept {is_accepted: true}` | 200. The post has `is_accepted: true` and `accepted_by` = the staff member. `author_role` is still `"AI"` and `citations` is unchanged | M5 |
| K2 | After K1, the list shows `has_accepted_answer: true`. `ai_status` stays `ANSWERED` | — | M5 |
| K3 | A student cannot accept an AI post | 403 | M5 |
| K4 | Staff on student surface cannot accept | 403 | M5 |
| K5 | Un-accept (`is_accepted: false`) | 200, `has_accepted_answer: false` | M5 |
| K6 | Accept through another question's URL (IDOR, as in `test_security.py`) | 404 | M5 |
| K7 | No pre-approval gate: the AI post is visible to the student **before** any staff action (asserted in B5's timeline) | — | M5 |
| K8 | Staff can still post a human ANSWER on an AI-answered thread and accept both or either | 201 / 200 | M5 |
| K9 | The staff close flow works on an AI-answered thread. After close, the AI post remains | — | M5 |

---

## 5. What can run when

Today's branch has **no RAG backend**: no `routers/rag.py`, no `services/rag/`, no migration `002`, and no `ollama`/`infinity`/`chroma` Compose services (and no Chroma port 8001). So **every RAG test except A15 needs work that has not landed yet.**

| Milestone (design §9) | Unblocks | Test IDs |
|---|---|---|
| **Now** | Regression, the forged-role check, and the helpers that do not need RAG (`_read_env`, `db_counts` on MySQL 3306, `outsider_token`) | existing suite, A15. Helpers can be smoke-tested |
| **M1** Compose services, `/api/rag/health` | health, `rag_health` fixture, `chroma_counts` | A11, A12 |
| **M2** Migration, system user, `ai_status`, admin guards | system-user and schema-field checks | A13, A14, B1 (field only), R1 (if observable before M4; otherwise M4) |
| **M4** Profiles, resources, jobs, re-sync APIs | everything in ingestion that does not need compare to observe it | A1–A9 (non-compare routes), P1–P9, P11, P12, R1–R3, R8–R12, R15/R16 (counts), J1–J10, S1–S3, C1, C3 |
| **M5** Pipeline, compare, answer job | anything that observes chunks through compare, the board | A1–A7/A10 for compare, P10, R4–R7, R13, R14, H1, H3, S4, C2, X1–X14, D1–D3, B1–B14, K1–K9 |
| **M5 + `RAG_LIVE_ENABLED=true`** | live board | B1–B14, K1–K9, H2 |
| **`GITLAB_TOKEN` on the backend** | primary URL path against git.doit.wisc.edu | R13, R14, S4 |
| **DB/Chroma ports reachable** (dev only; prod publishes only nginx 80) | global no-writes check | D1 (D2/D3 run anywhere) |

Recommended order for writing the code: §3 infrastructure first (it can be written now and smoke-tested against MySQL), then `test_rag_access.py` and `test_rag_ingestion.py` against the §6 contract so they are ready, failing, when M4 lands (design §9: "tests first"), then compare and board for M5.

---

## 6. Open issues and risks

1. **Live-on vs live-off conflict.** The harness runbook needs `RAG_LIVE_ENABLED=false`, but the board tests need it `true`. One test run cannot cover both. Plan: CI and default dev runs use `true`, and the `live_board` tests skip when it is false, so running the suite during eval prep is safe. B1's `NONE` branch only runs when live is off.
2. **Live jobs from unrelated tests.** With live on, every question any test creates (including `test_qa_flow.py`) enqueues an answer job. These end `SKIPPED` quickly (no default profile in a fresh course), but they write `questions.ai_status` and could race D1. The §4.5 flake guard handles this. Keep the suite serial (no `pytest-xdist`).
3. **Strong "failed re-sync keeps the old set" (S3)** needs a source that succeeds and then fails. Upload re-syncs re-read a stored file and cannot be made to fail. The SSRF guard blocks any test-hosted local server. So the strong form belongs in unit tests (§10 already stubs fetchers). The integration test covers only the weak form. **Decision needed:** who adds the unit test (vzhou2 owns `ingestion.py`).
4. **S3's unfetchable URL.** It must pass registration-time SSRF validation and then fail at fetch. Options: a public URL that returns 404 (needs outbound network from the backend), or a GitLab file URL with a bogus path (fails deterministically with or without a token, but needs network). Pick one at M4. Skip if there is no egress.
5. **Hitting "job active" (P12, R16, J7, J8)** relies on a job still being QUEUED/RUNNING when the second request arrives. MiniLM on the tiny corpus may finish in under 1 s. Mitigation: make the active job a profile sync over `eval/sample_data` (PDF plus HTML), or queue two jobs on different profiles so the second waits on `INGESTION_LOCK`, which keeps it `QUEUED`. Retry the setup up to 3 times before skipping.
6. **B12 (DECLINED) and B13 (queue cap)** are model- and timing-dependent. They are best effort and skip rather than fail. `is_decline` itself is unit-tested.
7. **`GENERATION_BUSY` 503, `UPSTREAM_UNAVAILABLE` 503, `UPSTREAM_TIMEOUT` 504 and `EMBEDDING_MODEL_UNAVAILABLE` 409** cannot be produced without stopping services mid-test. They are left to unit tests with stubbed clients. Optionally add a manual `--destructive` marker case that runs `docker compose stop infinity` and asserts 503, never in CI.
8. **Cold-start time.** The first run after `docker compose up` waits for model pulls and the gte download. `rag_health` polls for up to 15 minutes with logging. Document "start the stack yourself, wait for `/api/rag/health`" in the test README.
9. **Against the VM (`--base-url http://<vm>`).** DB and Chroma ports are closed, so D1 skips and D2/D3 run. Uploading fixtures adds courses and collections to the deployment, so **never point the suite at the frozen eval course's deployment during the eval window** (design §11.1 step 6). Tests always create their own courses, which avoids touching the eval course, but they still use CPU and RAM on the VM.
10. **Chroma REST path.** `chroma_counts` depends on the pinned Chroma version's REST API (v1 vs v2 paths, U4). Confirm at M1 and hard-code it with a comment.
