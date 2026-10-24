# frontend/student

The Student app is a React 18 + TypeScript + Vite + Tailwind 3 single-page app
for asking questions and taking part in threads.

| Mode | Where it's served | API |
|---|---|---|
| Development | `npm run dev:student` on port **5173**, with Vite proxying `/api` to `localhost:8000` | proxied |
| Production | nginx at `/student/` (Vite `base` is `/student/` when `mode === 'production'`) | same origin |

## Structure

```
src/
  main.tsx              React root
  index.css             imports ../../shared/tokens.css, Tailwind layers, token body colors, focus-visible ring
  App.tsx               Router, RequireAuth guard, Layout (header + course picker + logout)
  lib/
    api.ts              fetch wrapper: /api base, Bearer token from localStorage,
                        always sends `X-App-Surface: student`
    CourseContext.tsx   loads GET /courses/mine; current course id persisted in localStorage
    types.ts            TS mirrors of backend schemas (Category, QuestionSummary, Post, QuestionDetail, MyCourse)
    utils.ts            cn() = clsx + tailwind-merge
  components/ui/        badge (incl. `ai` variant), button, card, input, textarea — token classes only
  components/ThemeToggle.tsx  light/dark toggle (header and login page); state in lib/theme.ts
  pages/
    LoginPage.tsx           username/password, or dev netid login → temp token → /auth/exchange-temp
    QuestionsPage.tsx       list with category/status/keyword filters
    AskQuestionPage.tsx     title, body, required category picks → POST /courses/{id}/questions
    QuestionDetailPage.tsx  thread view; post form (defaults to FOLLOWUP); read-only accepted marker
```

## Routes

| Route | Page | Notes |
|---|---|---|
| `/login` | LoginPage | The only route that doesn't need a login |
| `/questions` | QuestionsPage | Behind `RequireAuth`, which checks that `localStorage.token` exists |
| `/questions/new` | AskQuestionPage | |
| `/questions/:questionId` | QuestionDetailPage | |
| `*` | | Redirects to `/questions` |

## Behavior worth knowing

- **The surface header:** `X-App-Surface: student` clamps the effective role to STUDENT on the backend, even for staff or admin accounts. Anything posted from this app is recorded with `author_role = STUDENT`.
- **Auth storage:** the access token is kept in `localStorage.token`. There is no refresh logic. An expired token makes requests fail until the user logs in again.
- **Rendering posts:** in `QuestionDetailPage`, each post shows the author name and a role badge. The badge logic is `author_role === 'STAFF' ? 'Course Staff' : 'Student'`, so any new role such as an AI author would be **mislabeled as "Student"** until this logic changes. Accepted posts get an emerald border and the label "Verified by staff". Post bodies are shown as plain text (`whitespace-pre-wrap`), with no markdown or link rendering.
- **Freshness:** the thread is fetched once when the page opens and after the user posts. There is no polling. A background AI answer only appears after a reload or a refetch.
- **Theming:** components use the semantic token classes from `tailwind.config.ts` (`bg-surface-raised`, `text-muted`, `bg-accent`, …), backed by `frontend/shared/tokens.css`. First visit follows the OS theme; the toggle persists the choice in `localStorage.theme`. See `frontend/README.md` → Theming.
