# frontend/staff

The Staff app is a React 18 + TypeScript + Vite + Tailwind 3 single-page app
for course staff. Staff use it to answer questions, mark answers verified,
close and reopen threads, manage categories, and manage the RAG auto-responder's
course resources and ingestion profiles.

| Mode | Where it's served |
|---|---|
| Development | `npm run dev:staff` on port **5174** (`/api` proxied to `localhost:8000`) |
| Production | nginx at `/staff/` |

The code started as a copy of `frontend/student/`, and the structure is the
same: `main.tsx`, `App.tsx`, `lib/{api,CourseContext,types,utils}`,
`components/ui/*` and `pages/*`. The rest of this README covers only what
differs from the Student app.

## Differences from the Student app

| Area | Staff app |
|---|---|
| `lib/api.ts` | Sends `X-App-Surface: staff`. This grants nothing by itself: the backend resolves the real course role, and this value just doesn't clamp it. A user without STAFF access in the course gets 403 on staff routes. Also has `upload<T>(path, FormData)` (no `Content-Type`, so the browser sets the multipart boundary) and throws `ApiError` carrying the backend's `error` code and HTTP status. |
| `lib/ragTypes.ts` | Types and paths for the `/rag` routes, mirroring `docs/design-rag.md` §6 field for field. Update the design doc first, then this file. Unconfirmed spots are marked `TODO(design §6)`; see `docs/frontend-open-questions.md`. |
| `App.tsx` | The header reads "Course Q&A — Staff" and has `NavLink`s to Questions, **Categories**, **Resources** and **Profiles**. It has extra `/categories`, `/resources` and `/profiles` routes. |
| `pages/CategoriesPage.tsx` | Staff-only page that lists, creates and deletes categories for the selected course (`/courses/{id}/categories`). |
| `pages/ResourcesPage.tsx` | Lists course resources with one status chip per profile (status, chunk count; hover for last sync, commit and error). **Register URL** (`git_ref`/`subpath` for repositories), **Upload** (file or zip, optional citation base URL), **Re-sync** with profile checkboxes, and **Delete** (hidden for historical Q&A). A new resource isn't synced automatically: an inline **Sync now** appears instead. The jobs panel polls `/rag/jobs` every 3 s while a job is active. |
| `pages/ProfilesPage.tsx` | Lists ingestion profiles (model, chunk count, chunking summary), **Create from preset**, **Sync all**, **Delete**, and a service health panel (`GET /api/rag/health`). |
| `pages/QuestionDetailPage.tsx` | The post form defaults to **ANSWER**. Every ANSWER post has a **Mark verified / Verified** toggle that calls `PATCH .../posts/{pid}/accept {is_accepted}`. A **Close thread / Reopen** button calls `POST .../close` or `.../reopen`. While a request is in flight, `busy` disables the buttons. |
| `pages/AskQuestionPage.tsx` | When the course has no categories yet, it points staff to the Categories page. |
| `pages/LoginPage.tsx` | The heading says "Staff Login". The login flow is the same. |

## Routes

`/login`, `/questions`, `/questions/new`, `/questions/:questionId`,
`/categories`, `/resources` and `/profiles`. All routes except `/login` sit behind `RequireAuth`.

## Behavior worth knowing

- **Accepting answers:** the accept toggle is shown for **every** `ANSWER` post, whatever its author. An AI-authored ANSWER post would get the same "Mark verified" button with no new code path. This is the existing acceptance mechanism that T5 must reuse.
- **Role badges:** these use the same `STAFF ? 'Course Staff' : 'Student'` badge logic as the Student app, so a new author role needs a badge here too.
- **RAG resource UI:** the Resources and Profiles pages implement T4's staff resource management. They were written against the design doc before the backend routes existed.
- **Theming:** the colors are raw palette utilities, with no token layer and no light theme (T8). Status and health colors on the RAG pages come only from the `Badge` variants (`success`, `info`, `danger`, `outline`), so the T8 token switch only has to touch those.
