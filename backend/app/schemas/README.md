# backend/app/schemas

Pydantic v2 request and response models for the HTTP API. Routers use them to
validate request bodies and to set `response_model`.

## Conventions

- **Request models** set `ConfigDict(extra="forbid")`, so unknown fields are a 422, not silently ignored.
  - Length limits are declared with `Field(...)`.
  - Enum-like strings are validated with a regex `pattern`, for example `^(ANSWER|FOLLOWUP)$` and `^(STUDENT|STAFF)$`.
- **Response models** that map straight from ORM rows use `from_attributes=True`.
  - Nested Q&A responses (`QuestionSummary`, `QuestionDetail`, `PostResponse`) are built as plain dicts by the `serialize_*` helpers in `services/qa_service.py` and then validated against these models.
- Validation errors are rendered as `{"error": "VALIDATION_ERROR", "detail": [...]}` by `common/exceptions.py`.

## Files

### `auth.py`

- `LoginRequest` takes either `username`+`password` or `netid`.
  - `netid` login is a dev-only fallback.
  - A `model_validator` rejects requests that have neither.
- `TokenResponse`, `TempTokenResponse` and `RefreshResponse` are bearer-token envelopes.

### `admin.py`

Used only by `routers/admin.py`.

- **Courses:** `CourseCreate`, `CourseUpdate`, `CourseResponse`.
- **Roster:**
  - `RosterEntryResponse`, `RosterEntryPatch`.
  - `RosterRowIn` and `RosterImportPayload`, for JSON rows from the column-mapping wizard.
  - `RosterUploadResult`, with imported, updated and deactivated counts plus errors.
- **Staff CSV:** `StaffUploadResult`.
- **Users:**
  - `UserCreate` and `UserUpdate`. Usernames are lowercased by a validator. Passwords are 8–72 characters, the bcrypt limit.
  - `UserResponse`.
  - `UserWithAccessResponse`, which adds `course_access: list[dict]`.
- **Access:** `CourseAccessGrant` (`course_id`, `role`).

### `qa.py`

Used by `routers/qa.py`.

- **Categories:** `CategoryCreate`, `CategoryUpdate`, `CategoryResponse`.
- **Questions:**
  - `QuestionCreate`: title, body and `category_ids`, with at least one category id.
  - `QuestionSummary`, used in the list view. It adds `post_count` and `has_accepted_answer`.
  - `QuestionDetail`: the full thread, with `posts`.
- **Posts:**
  - `PostCreate`: `kind` and `body`. The author role is **not** client-supplied. The server derives it.
  - `PostResponse`: `author_role` and `kind` are typed as plain `str`, not enums.
  - `PostAcceptPatch` (`is_accepted`).
- **`AuthorSummary`:** `{id, display_name}`, embedded in questions and posts.
- **`MyCourseResponse`:** used by the course picker (`GET /courses/mine`).

### `rag.py`

- Requests are all `extra="forbid"`:
  - `ProfileCreate`: `preset`, plus an optional `name` matching the profile-name pattern.
  - `ResourceRegister`: validates the http(s) URL, rejects repository-only fields on other resource types, and rejects SHA, option-like and malformed `git_ref` values and `..`, absolute or backslash `subpath` values. It also normalises `subpath`.
  - `ResourceSync`: `profile_ids` must have at least one entry when given, and duplicates are dropped.
  - `EmptyBody`.
- Responses are dicts built by `services/rag/catalog.py`. Their shape depends on the course's profiles: every resource lists a state per profile.
- `utc_z` formats every RAG timestamp as `…Z`.

## Things to know before extending

- `PostResponse` has no field that could carry citations or an "AI-generated" marker. Clients only see what is listed here, so new post metadata needs new fields in this file and in `qa_service.serialize_post`.
- New feature areas (for example RAG resources or `/rag/compare`) should get their own module here rather than growing `qa.py`.
