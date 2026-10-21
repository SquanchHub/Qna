# frontend/admin

The Admin app is a React 18 + TypeScript + Vite + Tailwind 3 single-page app
for global administrators. Admins use it to manage courses, rosters, staff
lists, local user accounts and per-course access grants. It calls only
`/api/auth/*` and `/api/admin/*`. Every admin endpoint requires
`User.role == "ADMIN"`.

| Mode | Where it's served |
|---|---|
| Development | `npm run dev:admin` on port **5175** (`/api` proxied to `localhost:8000`) |
| Production | nginx at `/admin/` |

## Structure

```
src/
  main.tsx, index.css
  App.tsx              Router, RequireAdmin guard (token present), AdminLayout (left sidebar: Courses, Users, Logout)
  lib/
    api.ts             fetch wrapper (Bearer token from localStorage); no X-App-Surface header;
                       adds postForm() for multipart CSV uploads
    utils.ts           cn()
  components/ui/       badge, button, card, input, textarea
  pages/
    LoginPage.tsx        username/password only → localStorage.token
    CoursesPage.tsx      list/create/edit courses; "Roster" button per course
    RosterPage.tsx       per course: upload Canvas roster CSV, view/toggle roster entries,
                         upload staff CSV, list staff
    UsersPage.tsx        list users, create local (username/password) accounts
    UserDetailPage.tsx   one user: grant STUDENT/STAFF access to a course, revoke access
```

The Admin app has no `CourseContext` and no `types.ts`. Each page declares its
own local interfaces.

## Routes

| Route | Page |
|---|---|
| `/login` | LoginPage |
| `/courses` | CoursesPage |
| `/courses/:courseId/roster` | RosterPage |
| `/users` | UsersPage |
| `/users/:userId` | UserDetailPage |
| `*` | Redirects to `/courses` |

## Behavior worth knowing

- **The guard:** `RequireAdmin` only checks that a token exists. If a non-admin token reaches a page, the backend's 403 is what stops it.
- **Uploads:** roster and staff uploads go through `postForm`. It sends no `Content-Type`, so the browser sets the multipart boundary. The backend caps CSVs at 2 MB.
- **Scope of RAG changes:** the admin app isn't on the RAG path. It only needs T8 theming (tokens, light and dark themes, and the toggle).
