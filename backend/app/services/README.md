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

Pure functions with no I/O. M4's ingestion jobs call them (design-rag.md §4.1, §4.4.1, §4.5.4).
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

## Things to know before extending

- Historical Q&A ingestion can query `Question` and `Post` directly. "Accepted" is `Post.is_accepted`; "closed" is `Question.status == "CLOSED"`.
- Long-running work (model calls, cloning a repository) shouldn't hold a request open on the shared session. Because services flush and never commit, an AI post created after the question's commit needs its own session, for example a background task using `AsyncSessionLocal`.
