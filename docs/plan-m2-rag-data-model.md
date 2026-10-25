# M2 plan: migration `002_rag`, RAG models, AI system user and serializers

Status: implemented and verified 2026-10-25 (results at the end).

Schedule row (vzhou2, 2026-10-27): migration `002_rag`, RAG models, system user, Q&A resource bootstrap, serializers, and answers to the frontend open questions in §6. Spec: `docs/design-rag.md` §4.2, §4.5.1 (historical Q&A resource), §5, §6 ("Changed shapes"), §9 M2 ("serializer and decline unit tests"; done when the upgrade is clean and existing tests are green). Branch `feature/rag-data-model` from `main`, which already has M1.

## Scope

**In:**
- Migration `002_rag`.
- `models/rag.py` (four tables), plus the `models/qa.py` columns.
- In `bootstrap`: the AI system user, one historical-Q&A resource per course, and the restart sweep.
- The Q&A resource created on `POST /api/admin/courses`.
- 409 `SYSTEM_ACCOUNT` guards.
- `ai_status`, `citations` and `ai_model` in the serializers.
- `services/rag/decline.py`.
- A `message` on `VALIDATION_ERROR`.
- Answers to `docs/frontend-open-questions.md`, written into §6.

**Out:**
- `/rag` profile, resource and job routes and `schemas/rag.py` (M4).
- `create_ai_answer` and the answer job (M5).
- Until M5, `create_question` always sets `ai_status = NONE`, because there is no responder yet and so no attempt. That matches §4.2.3 ("No attempt") and makes `test_b1` pass. M5 adds the `PENDING`/`SKIPPED` branch.

## Migration `backend/app/migrations/versions/002_rag.py` (hand-written, `down_revision = "001"`)

**Upgrade:**
1. `op.alter_column("posts", "author_role", type_=Enum("STUDENT","STAFF","AI"), existing_type=Enum("STUDENT","STAFF"), existing_nullable=False)`.
2. Add `posts.citations JSON NULL`, `posts.ai_model VARCHAR(100) NULL` and `posts.ai_profile VARCHAR(64) NULL`.
3. Add `questions.ai_status ENUM(NONE,PENDING,ANSWERED,NO_MATCH,DECLINED,SKIPPED,FAILED) NOT NULL server_default 'NONE'`. Existing rows become `NONE`.
4. Create the tables in FK order:
   - `ingestion_profiles`, with UNIQUE(`course_id`,`name`). `chunking` is JSON NOT NULL; `query_instruction` is TEXT NOT NULL, and is empty when unused, set by the application, because MySQL TEXT can't take a server default.
   - `course_resources`, with UNIQUE(`course_id`,`singleton_key`).
   - `resource_profile_states`, with PK(`resource_id`,`profile_id`), both FKs CASCADE.
   - `ingestion_jobs`, with `resource_id` NULL FK CASCADE and INDEX(`course_id`,`created_at`).
   - Every `created_by_user_id` is a NULL FK to `users.id` with ON DELETE SET NULL, so deleting a user never fails.

**Downgrade:**
1. `DELETE FROM posts WHERE author_role='AI'`.
2. Drop the four tables in reverse order, then the columns.
3. Restore the two-value enum.

**Verified locally:** `upgrade head`, then `downgrade 001`, then `upgrade head` on the dev database, with a row count check on posts and questions.

The name-pattern constraint `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` is enforced in the M4 request schema, not by a DB CHECK.

## Models

`models/rag.py` defines:
- `IngestionProfile` (`collection_name` property `c{course_id}_p{id}`)
- `CourseResource`
- `ResourceProfileState`
- `IngestionJob`

Column types match the migration. Relationships are minimal: resource and profile to states, with `passive_deletes=True` so the DB cascades do the work.

`models/qa.py` changes:
- `Post.author_role` gains `AI`.
- `Post` gains `citations: list[dict] | None` (JSON), `ai_model` and `ai_profile`.
- `Question` gains `ai_status`, default `NONE`.

The new models are exported from `models/__init__.py` so Alembic's `env.py` metadata sees them.

## Bootstrap (`services/bootstrap.py`)

It runs after the admin and grader steps, in the same retry loop. On a database still at 001, a missing table raises `ProgrammingError`, which the existing loop treats as "waiting for schema". In prod, `alembic upgrade head` runs first anyway.

- **`_ensure_ai_user(db)`** (all three steps run inside `bootstrap_rag()`, one session and one commit):
  - Selects by `username = "qna-ai-assistant"`. If it's missing, inserts `display_name "QnA Assistant (AI)"`, `role USER`, and NULL `password_hash`, `netid` and `email`.
  - Caches the id in a module variable, exposed through `ai_user_id()` for M5.
  - Two backends starting at once are covered by the username UNIQUE constraint: it catches `IntegrityError` and re-selects.
- **The Q&A resource loop:**
  - For each course without a `singleton_key = 'historical_qa'` row, inserts `resource_type historical_qa`, `source_kind internal`, title `Historical Q&A` and `singleton_key 'historical_qa'`.
  - An `IntegrityError` from a concurrent insert is caught and the step re-runs.
  - The shared helper `rag_resources.ensure_qa_resource(db, course_id)` is in a new small module, `services/rag/resources.py`, so the admin router can reuse it.
- **`_sweep_interrupted(db)`:**
  - Sets every question with `ai_status = PENDING` to `FAILED`.
  - Sets `ingestion_jobs` with QUEUED/RUNNING to `FAILED`, with `error "interrupted by restart"` and `finished_at = now`.
  - Sets `resource_profile_states` with QUEUED/RUNNING to `FAILED` with the same error.
  - Logs the counts.

`bootstrap_admin()` currently returns early when neither admin nor grader is configured. The RAG steps must still run, so the early return moves to cover only those two steps.

## Admin router

- **`POST /admin/courses`:** after the flush, calls `ensure_qa_resource` in the same transaction.
- **`SYSTEM_ACCOUNT` guards:**
  - Covers `PUT /users/{id}`, `DELETE /users/{id}`, `POST /users/{id}/course-access` and `DELETE /users/{id}/course-access/{course_id}`.
  - The check runs **before** any 404 lookup of a course or access row, because a13 revokes access that doesn't exist and expects 409.
  - `SystemAccountError(ConflictError)` has code `SYSTEM_ACCOUNT`, defined in `common/exceptions.py`.
  - The check is by username, `user.username == AI_USERNAME`, through one helper, `_refuse_system_account(user)`.

## Serializers and schemas (`schemas/qa.py`, `qa_service.py`)

- **`PostResponse`:** `author_role` may be `"AI"`. Adds `citations: list[dict] | None` and `ai_model: str | None`.
- **`QuestionSummary` and `QuestionDetail`:** add `ai_status: str`.
- **Serializers:** read the new attributes.
- **Requests:** `PostCreate` stays `extra="forbid"`, so a client-supplied `author_role` is a 422 (a15).
- **Author display:** the AI author shows as `QnA Assistant (AI)` through `display_name`.

## `services/rag/decline.py`

`is_decline(answer: str) -> bool`, exactly as in §4.2.4, with no imports. The phrase tuple is exposed as `DECLINE_PHRASES`.

## Validation errors

The `RequestValidationError` handler adds `"message"`, which is the first error's `msg` prefixed by its field location (for example `profile_ids: List should have at least 1 item`; the `body` prefix is dropped). `detail` is kept. This answers open question 1, so the frontend always gets `message`.

## Answers to the frontend open questions (written into §6, the file then marks each answered)

1. **Errors:**
   - Every error has `error` and `message`. Pydantic 422s keep `detail` too.
   - RAG-specific 422s are `QnaError`s with their own codes.
   - An upload over nginx's 50 MB gets nginx's HTML 413, and that's accepted: the frontend's "File is too large" fallback covers it.
2. **`citation_base_url`:**
   - For a single `.md`, `.pdf` or `.html` file, the base **is** the file's or page's URL, used as-is plus the type suffix.
   - For a zip, the base is a directory URL, and the backend adds `/` if it's missing before joining the in-zip path.
   - Validated as an http(s) URL of at most 2048 characters, else 422 `VALIDATION_ERROR`. There's no SSRF check, because it is never fetched.
3. **Upload types:**
   - syllabus and schedule accept `.html` and `.htm`; repository accepts `.zip`, `.md` and `.pdf`.
   - A mismatch gets 422 `UNSUPPORTED_FILE`.
   - The limits are exposed as `GET /api/rag/health` → `limits: {max_upload_mb, max_zip_mb}` in M4 (moved by the Goldfish review).
4. **Jobs:** `status` takes one value (`QUEUED`, `RUNNING`, `SUCCEEDED` or `FAILED`), and `limit` defaults to 20.
5. **Profile fields:** `chunking` is always the full §4.4.1 object, and `query_instruction` is always a string (`""` when unused), never null. The health types are already in §6 since M1.
6. **Presets:** gain `served: bool`, from Infinity `/models` at request time, in M4. The UI can disable unserved presets, and create still returns 422 `EMBEDDING_MODEL_NOT_SERVED`.

The `TODO(design §6)` markers in `frontend/` belong to varikooty and are flagged in the MR, not edited.

## Tests first

**Unit** (`tests/unit/test_rag_data_model.py`, no stack):
- Serializers: an AI post serializes `author_role "AI"`, `citations` and `ai_model`; a human post has `citations: null`; the summary and detail carry `ai_status`.
- `is_decline`: the prefix, each phrase under 400 characters, the same phrase over 400 characters is not a decline, and the case doesn't matter.
- The `SYSTEM_ACCOUNT` guard on all four routes through `ASGITransport` with a fake DB returning the AI user (409, with the code), and the revoke path refused before the access lookup.
- `create_course` calls `ensure_qa_resource`.
- `bootstrap.ensure_ai_user` is idempotent (an existing user means no insert).
- The validation handler includes `message`.
- `IngestionProfile.collection_name`.
- Health includes `limits`.

**Integration** (live stack): `test_rag_access.py` a13, a14 and a15; `test_rag_board.py::test_b1`, with `RAG_LIVE_ENABLED=false` for one run; and the whole existing suite green. The M2 probe then marks M2 as deployed.

**Migration:** upgrade, downgrade and upgrade on the dev database; after the upgrade there is exactly one AI user and one Q&A resource per course.

## Docs

- §5: the `query_instruction` NOT NULL note and `created_by` ON DELETE SET NULL.
- §6: the answers to the open questions, plus `limits` in health.
- `frontend-open-questions.md`: each item marked answered, with a pointer to §6.
- The `models/`, `services/` and `migrations/` READMEs.
- `schedule.md`: move the row to Done.

## Goldfish review (2026-10-25), adopted

**Blocker:**
1. `limits` in health moves to M4, alongside the upload route, because `test_rag_health.py` pins the exact key set. §6 notes it as planned.

**Majors:**
2. Model columns get Python `default=` as well as `server_default` (`ai_status`, `query_instruction`, counts). Otherwise reading a freshly flushed row lazy-loads in async and raises MissingGreenlet.
3. `ensure_ai_user` refuses a pre-existing `qna-ai-assistant` row that has a password, netid, email or a non-USER role: it logs an error and does not adopt it. `UserCreate` and `UserUpdate` reserve the name.
4. All RAG bootstrap steps (AI user, Q&A resources, sweep) run in **one session and commit once**. On a 001 database the whole step fails, so the M2 probe can't see an AI user early. The downgrade also deletes the AI user, after its posts.
5. The retry loop treats `OperationalError` 1054/1146 as "waiting for schema" too. Startup now always waits for the database, even with no admin or grader configured; that is stated in the bootstrap README.

**Minors:**
- `SystemAccountError` calls `QnaError.__init__` directly.
- Revoke runs in order: get the user (404 if missing), then the AI check, then the access lookup.
- The session rolls back before re-selecting after an `IntegrityError`.
- `citations` is `list[dict] | None` everywhere.
- The "deleting a user never fails" wording is fixed; 001's post FKs still block that.
- MySQL DDL implicitly commits, so a half-applied 002 needs manual cleanup (noted in the migration docstring).
- The 001 downgrade's `DROP TYPE` lines are guarded to PostgreSQL only.
- The models are named in `env.py`.
- The enums are named (`question_ai_status`, and so on).
- `message` is built from `jsonable_encoder` output.
- Q2 states that `?plain=1` is inserted after the join.
- Q3 documents that the effective zip limit is slightly under 50 MB, because of nginx's 50 m and multipart overhead.
- Q5 updates §6's `chunking` example.
- Q6 notes `served` in §6 now.

## Results (2026-10-25)

- Unit: 86 tests pass, including 32 in `test_rag_data_model.py` and 12 in `test_decline.py`. `ruff check` and `ruff format --check` are clean.
- Migration on the dev database (70 courses, 48 questions, 34 posts):
  - `upgrade head` keeps every post and question, and all questions are `ai_status NONE`.
  - Bootstrap then made exactly one AI user and 70 Q&A resources.
  - `downgrade 001` removes the four tables, the columns and the AI user, and restores the two-value enum.
  - A second `upgrade head` is clean.
  - The first downgrade attempt failed because MySQL refuses to drop `ix_jobs_course_created` while the `course_id` FK needs it. The downgrade now drops only the table.
- Integration: 26 passed, now including a13, a14 and a15, and 215 skipped (M4 and later). `test_b1` passes with `RAG_LIVE_ENABLED=false`. The M2 capability probe now reports M2 as deployed.

## Diff review (2026-10-25), adopted

**Major:** an impostor `qna-ai-assistant` account crashed startup. Bootstrap now logs `ai_user_name_taken` instead, and the board stays up with no AI author. The 409 guard uses `is_system_account` (the name plus NULL password, netid and email, plus role USER), so an admin can rename the impostor.

**Minors:**
- `_schema_missing` is narrowed to MySQL errors 1054 and 1146, so a real SQL bug no longer loops with a migration hint.
- `bootstrap_rag` has tests for the single commit, the rollback-and-retry and giving up.
- The single-process assumption is documented.
- U10 is verified on dev: MySQL runs in UTC (`NOW()` = `UTC_TIMESTAMP()`), so naive-UTC `finished_at` matches the server-side `created_at`.
- `defer(Post.citations)` for the question list is noted for M5, when AI posts exist.
