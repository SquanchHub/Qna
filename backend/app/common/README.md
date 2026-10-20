# backend/app/common

Cross-cutting helpers that every router uses: authentication and authorization
dependencies, the error model, logging, rate limiting and safe uploads. Nothing
here holds business logic.

## Files

### `dependencies.py`: auth and course-scoped access (FastAPI `Depends`)

- **`_token_from_request`** reads the JWT from `Authorization: Bearer` first, then falls back to an `access_token` cookie.
- **`get_current_user`** decodes the RS256 JWT via `auth_service.decode_token`.
  - Accepts token types `access` or `temp`.
  - Loads the `User`.
  - Raises `UnauthorizedError` (401) on any failure.
- **`require_admin`** requires the global `User.role == "ADMIN"` and returns 403 otherwise.
- **`get_refresh_token`** reads the `refresh_token` cookie.
- **`CourseMember`** is a small holder for `(user, course_role)`.
- **`require_course_member(course_id, ...)`** is the course-scope check, used by every `/courses/{course_id}/...` route.
  1. A global ADMIN gets the natural role `STAFF` in every course.
  2. Anyone else must have a `UserCourseAccess` row for that course. If they don't, the response is **404 "Course not found"**, not 403, so course existence isn't leaked.
  3. The `X-App-Surface` header can only *clamp* the role. A value of `student` forces the effective role to `STUDENT`; any other value leaves the natural role. The Student app always sends `student`, so staff and admins acting there are treated as students.
- **`require_course_staff`** builds on `require_course_member` and requires the effective role `STAFF` (403 otherwise).

### `exceptions.py`: the error model

- **`QnaError(code, message, status_code)`** is the base class.
- **Subclasses:**
  - `NotFoundError` (404)
  - `ForbiddenError` (403)
  - `UnauthorizedError` (401)
  - `ConflictError` (409)
  - `PayloadTooLargeError` (413)
- **`register_exception_handlers(app)`** maps errors to JSON responses:
  - `QnaError` → `{"error": code, "message": ...}`
  - validation errors → 422 `{"error": "VALIDATION_ERROR", "detail": [...]}`, passed through `jsonable_encoder` so `ValueError` contexts serialize
  - any other exception → 500 `INTERNAL_ERROR`
- The frontends display `message`.

### `logging.py`

`configure_logging()` sets up structlog:

- a console renderer in development and JSON in other environments;
- DEBUG in development and INFO in other environments;
- `uvicorn.access` quieted outside development.

Modules call `structlog.get_logger()` and log event names with keyword arguments, for example `logger.info("post_created", post_id=...)`.

### `rate_limit.py`

A slowapi `Limiter`.

- **Key:** the client IP in production. In development the key is a random UUID per request, so limits never fire locally, because all Docker traffic shares one IP.
- **Where limits apply:** routes opt in with a decorator, for example `@limiter.limit("5/15minutes")` on login.

### `uploads.py`

`read_upload_capped(file, max_bytes=2 MB)` reads an `UploadFile` in 64 KB chunks and raises `PayloadTooLargeError` past the cap.

- **Why chunked:** Starlette doesn't cap request bodies, and `Content-Length` can't be trusted.
- **Current users:** roster and staff CSV uploads.
- **Note for RAG:** PDF and zip uploads need a larger, explicit `max_bytes`. nginx already allows bodies up to 50 MB.

## Things to know before extending

- New staff-only endpoints under a course should depend on `require_course_staff`. That gives course scoping, the 404-for-non-members behavior and the admin bypass for free.
- `require_course_staff` is the "existing staff auth" that `/rag/compare` must reuse.
