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
- **Waiting for the schema:** retries every 5 seconds until `alembic upgrade head` has created it.

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

## Things to know before extending

- Historical Q&A ingestion can query `Question` and `Post` directly. "Accepted" is `Post.is_accepted`; "closed" is `Question.status == "CLOSED"`.
- Long-running work (model calls, cloning a repository) shouldn't hold a request open on the shared session. Because services flush and never commit, an AI post created after the question's commit needs its own session, for example a background task using `AsyncSessionLocal`.
