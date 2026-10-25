# backend/app

The FastAPI application package. This README rolls up the subdirectory READMEs.
Read those for detail:
[models](models/README.md), [schemas](schemas/README.md),
[services](services/README.md), [routers](routers/README.md),
[common](common/README.md).

## Layering

```
HTTP request (nginx /api/* → backend:8000)
  → routers/      thin endpoints: auth via Depends, validate via schemas, call a service, commit
  → common/       auth/course-scope dependencies, error model, logging, rate limiting, capped uploads
  → services/     business logic on an AsyncSession (flush, never commit)
  → models/       SQLAlchemy ORM → MySQL 8 (schema owned by Alembic migrations/)
```

## Top-level modules

- **`main.py`**: builds the `FastAPI` app.
  - Configures structlog.
  - Registers the slowapi limiter, CORS and the exception handlers.
  - Mounts the routers `health`, `auth`, `admin` and `qa` under `/api`.
  - The lifespan hook connects Redis and runs `services.bootstrap.bootstrap_admin()`.
  - The OpenAPI docs are at `/api/docs`, in development only.
- **`config.py`**: pydantic-settings `Settings`, read from the environment or `.env`. It holds:
  - `APP_ENV`, `DATABASE_URL`, `REDIS_URL`;
  - the JWT keys;
  - the OAuth2 proxy secret;
  - CORS origins and the frontend URL;
  - the bootstrap admin credentials and `GRADER_PASSWORD_HASH`.

  New settings (service URLs, the GitLab token) go here and are read from the environment.
- **`database.py`**: the async SQLAlchemy engine (asyncmy), `AsyncSessionLocal` and `Base`.
  - `get_db()` yields one session per request, commits on success and rolls back on exceptions.
- **`redis_client.py`**: a lazy global `redis.asyncio` client. Today the app only connects to Redis at startup. It's available for caching or job state.
- **`migrations/`**: Alembic. `versions/001_initial_schema.py` creates every current table.

## Cross-cutting rules (true everywhere in this package)

- **Course scoping**:
  - Every `/api/courses/{course_id}/...` route depends on `require_course_member` or `require_course_staff`.
  - Non-members get a 404.
  - A global ADMIN acts as STAFF in every course.
  - `X-App-Surface: student` clamps the effective role to STUDENT.
- **The thread model**:
  - A `Question` (OPEN or CLOSED) owns `Post`s.
  - Each post is an ANSWER or a FOLLOWUP and snapshots its `author_role` (STUDENT or STAFF).
  - Staff accept at most one ANSWER per question through `PATCH .../posts/{pid}/accept`, and close or reopen threads explicitly.
  - Closed threads reject new posts with 409.
- **Errors**: services raise `QnaError` subclasses, which become `{"error", "message"}` JSON with the matching HTTP status.

## Where the RAG feature hooks in (summary)

| Concern | Hook point |
|---|---|
| Trigger an AI answer | After `POST /courses/{cid}/questions` commits (`routers/qa.py:create_question`) |
| Represent the AI author | `Post.author_role` enum, the non-null `Post.author_user_id`, and `PostResponse`/`serialize_post`. All three need extending. |
| Accept an AI answer | No change: `qa_service.set_post_accepted` already ignores who wrote the post |
| Historical Q&A source | `Question.status == "CLOSED"` and `Post.is_accepted` rows |
| Staff-only RAG endpoints | A new router using `require_course_staff` |
| New config and secrets | `config.py` `Settings`, read from the environment |
