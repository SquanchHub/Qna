# backend/app/services

Business logic, kept separate from HTTP. Service functions take an
`AsyncSession` and plain arguments and return ORM objects or result schemas.
They raise `common.exceptions` errors for domain failures.

Services **flush** and never commit. The router, or the `get_db` dependency in
`database.py`, commits at the end of the request. The exception is
`bootstrap.py`, which runs at startup and manages its own sessions.

## Files

### `auth_service.py`

- **Passwords:** bcrypt via passlib (`hash_password`, `verify_password`), 12 rounds.
- **JWTs:** RS256, signed with base64-encoded PEM keys from `JWT_PRIVATE_KEY` and `JWT_PUBLIC_KEY`. If the keys are missing, ephemeral keys are generated and a warning is logged.
  - **Access token:** 2 hours. Carries `sub`, `role` and `token_type: access`.
  - **Refresh token:** 7 days. Sent as an httpOnly cookie scoped to `/api/auth`.
  - **Temp token:** 15 minutes. Used for the OAuth2 and dev-netid exchange.
  - `decode_token` raises `JWTError`.
- **`get_or_create_user_by_netid`:** used by SSO and dev login. It updates `last_login`, then calls `_sync_roster_course_access`, which grants STUDENT access for every course where the netid is on the active roster and the user has no grant yet. It never revokes.
- **`authenticate_local`:** username/password login for admin and local accounts.

### `bootstrap.py`

Runs in the FastAPI lifespan, from `main.py`.

- **First admin:** creates it from `ADMIN_USERNAME`/`ADMIN_PASSWORD` if no non-grader ADMIN exists.
- **Grader:** keeps an ADMIN user named `grader` in sync with `GRADER_PASSWORD_HASH`, which is base64 of a bcrypt hash. This runs on every startup.
- **RAG state** (`bootstrap_rag`): runs in one transaction, so a database still at migration 001 gets none of it.
  - Creates the AI system user. If a real account already holds that name (one with a password, netid, email or admin role), it is not adopted. An `ai_user_name_taken` error is logged, the board runs without an AI author (`ai_user_id()` raises), and an admin can rename that account, since the 409 guard applies only to the true system account.
  - Assumes one backend process, which both compose stacks run.
  - Adds a missing historical-Q&A resource to each course.
  - Sweeps work the previous process was killed in: `PENDING` questions, and `QUEUED`/`RUNNING` jobs and states, become `FAILED` ("interrupted by restart").
  - `ai_user_id()` returns the cached id for the answer job.
- **Waiting for the schema:** retries every 5 seconds until `alembic upgrade head` has created it, including MySQL's "unknown column/table" errors when migrations lag the code. Because the RAG step always runs, startup now always waits for the schema, even with no admin or grader configured.

### `qa_service.py`: the thread model

**Serialization**
- `serialize_post`, `serialize_question_summary` and `serialize_question_detail` turn ORM objects into the dicts behind `schemas/qa.py`.
- `display_name()` falls back through display_name, then username, then netid, then "Unknown".

**Loading**
- `_question_load_options()` eager-loads author, closed_by, categories, and posts with their authors and accepters.
- `_get_question` re-fetches with `populate_existing=True`. Without it, a second load in the same request would return the stale cached `posts` collection.
- Every mutating function ends by re-fetching the question and returning it, so routers can return the full updated thread.

**Categories**
- Course-scoped CRUD.
- Duplicate names return 409.

**Questions**
- `list_questions` takes optional category, status and `q` filters. `q` is a SQL `LIKE` over title and body.
- `create_question` validates that every `category_ids` entry belongs to the course, then links them.
- **There is currently no hook after a question is created.** This is where an automatic AI answer would be triggered.

**Posts**
- `create_post(..., author_role, data)` rejects posts on CLOSED questions with 409. The router supplies `author_role` from the effective course role.

**Accept**
- `set_post_accepted` works only for `ANSWER` posts (409 otherwise).
- Accepting one post un-accepts any other in the question, so there is at most one accepted post.
- It records `accepted_by_user_id` and `accepted_at`.
- It doesn't check the author, so it works the same for any author, including an AI post.

**Close / reopen**
- `close_question` and `reopen_question` are staff actions that set or clear `closed_at` and `closed_by_user_id`.
- Repeating the current state returns 409.

**Course lookup**
- `get_course` is a simple existence lookup.

### `roster_service.py`

- `process_roster_csv` parses a Canvas gradebook CSV:
  - It needs the `Student` ("Last, First") and `SIS Login ID` columns.
  - It skips the "Points Possible" row.
  - It upserts `CourseRoster` rows and deactivates netids missing from the upload.
  - It processes at most 1000 rows.
- `process_roster_rows` does the same for JSON rows from the admin column-mapping wizard.
- Problem rows are collected into `errors` and don't fail the whole upload.

### `staff_service.py`

- `process_staff_csv` reads a CSV with `netid`, `full_name` and `email` columns, up to 200 rows.
- For each row it creates the user if missing and grants or upgrades the user to **STAFF** immediately. It does not wait for the user to log in.

### `rag/resources.py`

`ensure_qa_resource(db, course_id)` adds the course's one historical-Q&A resource if it is missing. It flushes but never commits. It is used by bootstrap and by `POST /api/admin/courses`.

### `rag/decline.py`

`is_decline` and `matched_decline_phrase` (design-rag.md §4.2.4): the `INSUFFICIENT_CONTEXT` prefix, or a known phrase in an answer under 400 characters. The module has no imports, so `eval/summarize.py` can load it by path.

### `rag/clients.py`

Health probes for the RAG services, each bounded by `HEALTH_TIMEOUT_S` (3 s) and never raising:
- **Ollama:** `GET /api/tags` returns the pulled models.
- **Infinity:** `GET /health`, then `GET /models`, returns the served model ids.
- **Chroma:** `GET /api/v2/heartbeat`, then `/api/v2/version`. That endpoint returns the API version (`"1.0.0"`), not the server release, so it is reported but not compared with the `chromadb-client` version. The matching pins in `docker-compose.yml` and `requirements.txt` guard against skew instead.

### `rag/tokens.py`, `rag/presets.py`, `rag/chunking.py`, `rag/citations.py`

Pure functions with no I/O. The M4 ingestion jobs call them (design-rag.md §4.1, §4.4.1, §4.5.4).
- **`tokens`:** chunk tokens from the vendored MiniLM `assets/minilm_tokenizer.json`. The file ships with truncation and padding at 128; the loader turns both off.
- **`presets`:** the four presets and `validate_chunking(chunking, model)`.
- **`chunking`:**
  - `chunk_markdown`, `chunk_pdf` (with `pdf_pages`), `chunk_qa` (with `qa_answer`, which picks a thread's answer) and `chunk_html`.
  - `chunk_html` is async only because semantic profiles call `embed`; sliding-window profiles never embed.
  - Each returns `Chunk`s with display text sliced from the source and their line or page range.
- **`citations`:**
  - `source_url(chunk, CitationContext, rel_path)` builds the stored citation.
  - `assign_ids` gives chunk IDs. Call it once per (resource, rel_path) group.
  - `chunk_metadata` gives Chroma metadata, leaving out any `None` value.

### Ingestion (M4): `rag/locks.py`, `ssrf.py`, `archives.py`, `fetchers.py`, `embeddings.py`, `store.py`, `ingest.py`, `catalog.py`

Design-rag.md §4.5, §4.6 and §6.
- **`ssrf`:** `guarded_get` is the only way the backend fetches a staff-supplied URL.
  - It resolves each host once and refuses internal addresses, including IPv4 embedded in IPv6.
  - It then connects to that IP, with the original name sent as `Host` and as the TLS SNI.
  - It follows at most 5 redirects, re-checking each one, and opens a fresh connection per hop.
  - `check_registration_host` is the earlier check at registration. It accepts a host that does not resolve.
- **`archives`:** `read_zip` checks every entry before reading anything. It refuses absolute paths, `..`, backslashes, symlinks and encrypted entries, and it caps the archive at 2000 entries and 200 MB of bytes actually read. It keeps only `.md` and `.pdf` files and strips a single shared top-level directory.
- **`fetchers`:** `fetch(resource)` gives the documents plus a `CitationContext`, and every failure becomes a `FetchError` scrubbed of the GitLab token. The sources are:
  - uploads;
  - web pages;
  - GitLab files, through the files API, where the ref is the first path segment;
  - `git clone --depth 1`, with config only through `GIT_CONFIG_*`, a 120 s timeout, a 500 MB watchdog, and a process-group kill.
  - PDFs are parsed in a thread, with a 60 s limit and at most 500 pages.
- **`embeddings` / `store`:**
  - **`embeddings`:** Infinity `/embeddings` and `served_models()`.
  - **`store`:** one Chroma collection per profile (cosine), always with `embedding_function=None`.
- **`ingest`:**
  - **`sync_resource`:** the §4.5.6 add / keep / stale sync. Embedding goes in batches of 8, and a failed write is rolled back.
    - A source that fails or gives no chunks is marked FAILED and nothing is deleted.
    - The exception is historical Q&A: since MySQL is the source of truth, zero qualifying threads is READY with 0 chunks.
  - **`run_job`:** holds `INGESTION_LOCK` and uses one short session per step. A failing resource is isolated, so the remaining resources still sync.
  - **`schedule_job`:** starts a job after its row is committed.
- **`catalog`:**
  - The profile, resource and job operations for the router, plus their serializers.
  - Like the rest, it flushes but does not commit.
  - Writes call `ensure_course`, because ADMIN passes the course check for any id.

### Pipeline and live board (M5): `rag/prompts.py`, `metrics.py`, `pipeline.py`, `answer_job.py`

Design-rag.md §4.2.3–§4.2.5 and §4.4.3–§4.4.6.
- **`prompts`:** `BASELINE_GUARDRAIL` (T6's text, verbatim), `LIVE_PROMPT` (the guardrail plus the injection and `INSUFFICIENT_CONTEXT` instructions), and `user_message`, which wraps each chunk in a tag named for its `resource_type`. `<`, `>` and `"` are replaced in chunk text, attributes and the question, so nothing can forge or close a tag.
- **`metrics`:** `cpu_percent` is whole-host busy time from `psutil.cpu_times()` over the embed/query window and the generation window.
- **`pipeline`:** `retrieve` (Infinity, then Chroma; the raw `1 − distance` is compared with the threshold), `generate` (one Ollama chat call), and `compare`, the fixed contract behind `POST /rag/compare`.
  - Upstream failures become 503 `UPSTREAM_UNAVAILABLE`, timeouts 504 `UPSTREAM_TIMEOUT`. Every call is bounded, and the whole compare has a 170 s deadline, under the harness's 180 s.
  - It never imports `qa_service`; a unit test enforces this, because compare must stay a dry run.
- **`answer_job`:** `initial_status` decides NONE / PENDING / SKIPPED when a question is created, and `run` moves PENDING to exactly one terminal status.
  - Each database step is its own short session, and no session is open during a model call.
  - Every status change is `WHERE ai_status = 'PENDING'`, so terminal statuses never change.
  - The AI post and ANSWERED are written in one transaction, after `qa_service.create_ai_answer` locks the question row.
- **`locks.GENERATION_LOCK`** is held only around an Ollama call. Compare waits 30 s for it (else 503 `GENERATION_BUSY`), the live job 600 s (else FAILED).

## Things to know before extending

- Historical Q&A ingestion can query `Question` and `Post` directly. "Accepted" is `Post.is_accepted`; "closed" is `Question.status == "CLOSED"`.
- Long-running work (model calls, cloning a repository) shouldn't hold a request open on the shared session. Because services flush and never commit, background work (`answer_job`, `ingest.run_job`) opens its own `AsyncSessionLocal` sessions.
- `close_question` and `create_ai_answer` both take the question's row lock (`FOR UPDATE`) first. Keep it that way, or an AI post can land after the thread closes.
