# frontend

Three independent React 18 + TypeScript + Vite + Tailwind 3 apps. They share
no code: each has its own `package.json`, `components/ui` and `lib/api.ts`.
The root `package.json` runs all three with `npm run dev`.

| App | Who uses it | Dev port | Production path | `X-App-Surface` | README |
|---|---|---|---|---|---|
| `student/` | Students asking and discussing | 5173 | `/student/` | `student` (clamps to STUDENT) | [student/README.md](student/README.md) |
| `staff/` | Course staff answering, verifying and closing | 5174 | `/staff/` | `staff` | [staff/README.md](staff/README.md) |
| `admin/` | Global admins: courses, rosters, users, access | 5175 | `/admin/` | none (uses `/api/admin/*` only) | [admin/README.md](admin/README.md) |

## Common to all three apps

- **Auth:**
  - Each app logs in through `POST /api/auth/login` and stores the access token in `localStorage.token`.
  - Route guards only check that the token exists, so the backend enforces the real authorization.
  - There is no token refresh.
- **API calls:** `lib/api.ts` wraps `fetch` with the `/api` base and a Bearer header. It throws an `Error` carrying the backend's `message` field.
- **Styling:**
  - Colors are hardcoded Tailwind palette classes (`slate-*`, `indigo-*`, `emerald-*`, `red-*`).
  - There's a dark body background in `index.css`.
  - There's no semantic token layer and no light theme. T8 replaces this in all three apps.

## Where the RAG feature touches the frontend

- **Student and staff `QuestionDetailPage`:**
  - Render an AI-authored post with a clear AI label. The current badge falls back to "Student".
  - Make its citation links clickable.
  - Pick up an answer that arrives after the page loads.
- **Staff app:**
  - Add a resource-management page: register a URL or upload a file, re-sync, choose an ingestion profile.
  - The existing "Mark verified" toggle already works for any ANSWER post.
- **Shared types:** `types.ts` in student and staff mirrors `schemas/qa.py`. Any new `PostResponse` field must be added to both.
