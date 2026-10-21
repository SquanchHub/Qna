# backend/app/models

SQLAlchemy 2.0 ORM models (declarative `Mapped[...]` style) for the whole
database. Every model inherits `Base` from `backend/app/database.py`. The
schema they describe is created by the single Alembic migration
`backend/app/migrations/versions/001_initial_schema.py`. Changing a model
here without adding a new migration does **not** change the database.

`__init__.py` re-exports every model so that `from app.models import X`
works. Alembic's `env.py` also imports it to discover the metadata.

## Files

| File | Models | Table |
|---|---|---|
| `user.py` | `User` | `users` |
| `course.py` | `Course`, `CourseRoster`, `UserCourseAccess` | `courses`, `course_rosters`, `user_course_access` |
| `qa.py` | `Category`, `Question`, `QuestionCategory`, `Post` | `categories`, `questions`, `question_categories`, `posts` |

## Entity summary

- **User**
  - `id` is a UUID string (`String(36)`).
  - Global `role` is `ADMIN` or `USER`. This is account-wide. It is *not* the course role.
  - Identity comes from one of two places:
    - `netid` for SSO and dev-login users, who have no password.
    - `username` + `password_hash` (bcrypt) for local accounts: admin, grader and staff-created accounts.
  - All identity columns are nullable and unique.
- **Course**: `name` and `semester`.
  - Owns its roster, access grants, categories and questions.
  - Every one of those relationships uses `cascade="all, delete-orphan"`.
- **CourseRoster**: a bookkeeping row per `(course_id, netid)`, imported from a Canvas CSV.
  - It does **not** grant access by itself.
  - Access is granted lazily at login by `auth_service._sync_roster_course_access`, which turns active roster rows into STUDENT grants.
  - `is_active=False` means the netid was missing from the latest upload.
- **UserCourseAccess**: composite primary key `(user_id, course_id)`.
  - `role` is `STUDENT` or `STAFF`.
  - This is the table that course-scoped authorization reads (see `common/dependencies.py`).
  - Global ADMINs bypass it.
- **Category**: a staff-managed tag, unique per course by name.
- **QuestionCategory**: the many-to-many link between questions and categories.
  - The API requires every question to have at least one category.
- **Question**: the root of a thread.
  - `status` is `OPEN` or `CLOSED`, and only staff change it.
  - `closed_at` and `closed_by_user_id` record who closed it.
  - `posts` is ordered by `Post.created_at`.
  - There is an index on `(course_id, status)`.
- **Post**: one entry in a thread.
  - `kind`: `ANSWER` or `FOLLOWUP`. Only `ANSWER` posts can be accepted.
  - `author_role`: `STUDENT` or `STAFF`. This is a **snapshot** of the author's effective course role at posting time, so badges don't change if access changes later.
  - `is_accepted`, `accepted_by_user_id`, `accepted_at`: at most one accepted post per question. The service layer enforces this, not a DB constraint.
  - `author_user_id`: a non-null foreign key to `users`.

## Things to know before extending

- **`Post.author_user_id` is non-null.** Any automated author (for example an AI answer) must be either a real `users` row or a schema change that makes the column nullable.
- **`post_author_role` is a MySQL `ENUM`.** Adding a value (for example `AI`) needs an Alembic migration that alters the column. Every reader that branches on `author_role` must also be updated:
  - the frontend badge logic, which treats anything that isn't `STAFF` as "Student";
  - `schemas/qa.py`.
- There is no table for course resources, ingestion runs or chunk metadata yet. RAG work adds new models here.
- Timestamps use `server_default=func.now()` (naive DB time). Service code sets `closed_at` and `accepted_at` with `datetime.now(timezone.utc)`.
