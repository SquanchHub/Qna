# frontend/staff

The Staff app is a React 18 + TypeScript + Vite + Tailwind 3 single-page app
for course staff. Staff use it to answer questions, mark answers verified,
close and reopen threads, and manage categories.

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
| `lib/api.ts` | Sends `X-App-Surface: staff`. This grants nothing by itself: the backend resolves the real course role, and this value just doesn't clamp it. A user without STAFF access in the course gets 403 on staff routes. |
| `App.tsx` | The header reads "Course Q&A — Staff" and has `NavLink`s to Questions and **Categories**. It has an extra `/categories` route. |
| `pages/CategoriesPage.tsx` | Staff-only page that lists, creates and deletes categories for the selected course (`/courses/{id}/categories`). |
| `pages/QuestionDetailPage.tsx` | The post form defaults to **ANSWER**. Every ANSWER post has a **Mark verified / Verified** toggle that calls `PATCH .../posts/{pid}/accept {is_accepted}`. A **Close thread / Reopen** button calls `POST .../close` or `.../reopen`. While a request is in flight, `busy` disables the buttons. |
| `pages/AskQuestionPage.tsx` | When the course has no categories yet, it points staff to the Categories page. |
| `pages/LoginPage.tsx` | The heading says "Staff Login". The login flow is the same. |

## Routes

`/login`, `/questions`, `/questions/new`, `/questions/:questionId`, and
`/categories`. All routes except `/login` sit behind `RequireAuth`.

## Behavior worth knowing

- **Accepting answers:** the accept toggle is shown for **every** `ANSWER` post, whatever its author. An AI-authored ANSWER post would get the same "Mark verified" button with no new code path. This is the existing acceptance mechanism that T5 must reuse.
- **Role badges:** these use the same `STAFF ? 'Course Staff' : 'Student'` badge logic as the Student app, so a new author role needs a badge here too.
- **What's missing for RAG:** the app has no resource or ingestion UI yet. T4's staff resource management (register a URL, upload fallback, re-sync, profiles) will be added here as new pages and routes.
- **Theming:** the colors are raw palette utilities, with no token layer and no light theme (T8).
