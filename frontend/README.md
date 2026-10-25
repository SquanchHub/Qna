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
  - All three apps use the semantic token classes and have light and dark themes (see Theming below).

## Theming

- **Shared tokens:**
  - `shared/tokens.css` is the one place that defines the light and dark color values: `surface`, `text-primary`, `accent`, `danger`, `ai` and the rest.
  - It's the only file the apps share. Each app still has its own Tailwind color map, theme toggle and components.
- **How an app uses it:**
  - Each app's `src/index.css` starts with `@import '../../shared/tokens.css';`, placed before the `@tailwind` lines. Vite inlines the file at build time.
  - `tailwind.config.ts` maps every token to a class such as `bg-surface-raised`, `text-muted` or `bg-danger/10`.
  - Components use only these classes. Raw palette classes like `slate-*` are not allowed outside `tokens.css`.
- **Root-build requirement:**
  - The relative import only resolves when the build can see all of `frontend/`.
  - `npm run build` from the repo root and the repo-root Docker build (`docker build -f nginx/Dockerfile .`) both can.
  - Don't build an app in a context that contains only `frontend/<app>`, such as a per-app Dockerfile.
- **Choosing a theme:**
  - An inline script in each `index.html` sets `data-theme` on `<html>` before first paint. It uses `localStorage.theme` if set, or the OS `prefers-color-scheme` otherwise.
  - The toggle writes the same key.
- **Contrast:**
  - `python scripts/check_contrast.py` parses `tokens.css` and checks every text/background pair against WCAG AA in both themes. Body text must reach 4.5:1, and borders and focus rings 3:1.
  - Rerun it after changing any value.

## Where the RAG feature touches the frontend

- **Student and staff `QuestionDetailPage`:**
  - Render an AI-authored post with a clear AI label. The current badge falls back to "Student".
  - Make its citation links clickable.
  - Pick up an answer that arrives after the page loads.
- **Staff app:**
  - Add a resource-management page: register a URL or upload a file, re-sync, choose an ingestion profile.
  - The existing "Mark verified" toggle already works for any ANSWER post.
- **Shared types:** `types.ts` in student and staff mirrors `schemas/qa.py`. Any new `PostResponse` field must be added to both.
