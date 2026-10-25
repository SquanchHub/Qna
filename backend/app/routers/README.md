# backend/app/routers

FastAPI `APIRouter`s, the HTTP layer. Every router is mounted under `/api` in
`main.py`. nginx proxies `/api/` to the backend with a 300-second read timeout
and a 50 MB body limit.

Routers stay thin. Each one:
1. resolves auth with dependencies from `common/dependencies.py`;
2. validates the body with `schemas/`;
3. calls a function in `services/`;
4. commits;
5. returns a serialized response.

## Files

### `health.py`

`GET /api/health` returns `{"status": "ok"}`. There is no auth and no database access.

### `auth.py` (`/api/auth`)

| Method & path | Purpose |
|---|---|
| `POST /login` | Username and password login. Returns an `access_token` in the body and sets the `refresh_token` cookie. With `{netid}` and only in development, returns a `temp_token`. Rate-limited to 5 per 15 minutes. |
| `GET /oauth2-callback` | For the SSO reverse proxy. It trusts the `X-Auth-Request-User` and `X-Auth-Request-Email` headers only when `X-Proxy-Shared-Secret` matches `OAUTH2_PROXY_SHARED_SECRET`, compared in constant time, and fails closed otherwise. It returns an HTML page that redirects to the app's login with a temp token in the URL fragment. |
| `POST /exchange-temp` | Exchanges a temp token for an access token plus the refresh cookie. 10 per minute. |
| `POST /refresh` | Issues a new access token and refresh cookie from the refresh cookie. |
| `POST /logout` | Clears the refresh cookie. |

### `admin.py` (`/api/admin`, every route requires `require_admin`)

- **Courses:** `GET/POST /courses`, `GET/PUT /courses/{id}`.
- **Roster:**
  - `GET /courses/{id}/roster`
  - `POST /courses/{id}/roster`: Canvas CSV upload, capped at 2 MB.
  - `POST /courses/{id}/roster/import`: JSON rows.
  - `PATCH /courses/{id}/roster/{roster_id}`
- **Staff:**
  - `GET /courses/{id}/staff`
  - `POST /courses/{id}/staff`: CSV upload that grants STAFF access immediately.
- **Users:**
  - `GET/POST /users`
  - `GET /users/{id}`: includes the user's `course_access`.
  - `PUT /users/{id}`
  - `DELETE /users/{id}`: ADMIN accounts can't be deleted.
- **Access:**
  - `POST /users/{id}/course-access`: grants access, or changes the role if a grant already exists.
  - `DELETE /users/{id}/course-access/{course_id}`

### `qa.py`: the course Q&A board (no prefix; paths start with `/courses`)

| Method & path | Auth | Service call |
|---|---|---|
| `GET /courses/mine` | any user | Lists the user's courses with their role. ADMIN sees every course as STAFF. |
| `GET /courses/{cid}/categories` | member | `list_categories` |
| `POST /courses/{cid}/categories` | staff | `create_category` |
| `PATCH/DELETE /courses/{cid}/categories/{id}` | staff | `update_category` / `delete_category` |
| `GET /courses/{cid}/questions?category_id&status&q` | member | `list_questions`, which returns `QuestionSummary[]` |
| `POST /courses/{cid}/questions` | member | `create_question`, which returns `QuestionDetail` |
| `GET /courses/{cid}/questions/{qid}` | member | `get_question` |
| `POST /courses/{cid}/questions/{qid}/posts` | member | `create_post`, with `author_role = member.course_role` |
| `PATCH /courses/{cid}/questions/{qid}/posts/{pid}/accept` | staff | `set_post_accepted`. Body: `{is_accepted}` |
| `POST /courses/{cid}/questions/{qid}/close` | staff | `close_question` |
| `POST /courses/{cid}/questions/{qid}/reopen` | staff | `reopen_question` |

Here, "member" means `require_course_member` and "staff" means `require_course_staff`. Both clamp to STUDENT when the request carries `X-App-Surface: student`.

### `rag.py`: RAG routes (no prefix)

| Method & path | Auth | Calls |
|---|---|---|
| `GET /rag/health` | `require_rag_viewer` | `services/rag/clients.py` probes, run concurrently |

`GET /rag/health` reports `ok`, the served models and the Chroma versions for Ollama, Infinity and Chroma, plus `gitlab_token_configured`, `live_enabled` and the board defaults (design-rag.md §6). It never returns 5xx: a down service shows `ok: false`. Each request opens its own `httpx.AsyncClient` through the `get_rag_http` dependency, which tests override with a `MockTransport`. The course-scoped `/courses/{cid}/rag/*` routes arrive in later milestones.

## Things to know before extending

- **Where new course-scoped RAG routes go:** in a new router module (for example `rag.py`), mounted in `main.py`. The routes are:
  - resource registration;
  - re-sync;
  - ingestion profiles;
  - `POST /courses/{course_id}/rag/compare`.
- **Auth for staff routes:** staff-only routes depend on `require_course_staff`. That covers staff and global admin, which is what `/rag/compare` needs.
- **Hooking in the AI answer:** `create_question` is the natural trigger point. It commits and then returns the thread, so an AI answer generated in the background after that commit doesn't block the student's request.
- **File uploads:** the only uploads today are the admin CSV endpoints, which use `UploadFile` and `read_upload_capped`.
