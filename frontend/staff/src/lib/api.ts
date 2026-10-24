const BASE = '/api';

// Declares this app's surface on every request — see the matching comment
// in frontend/student/src/lib/api.ts. "staff" does not grant anything by
// itself; the backend still resolves the caller's real course role first
// and only ever clamps toward STUDENT, never the reverse.
const APP_SURFACE = 'staff';

/** A non-2xx response. `code` is the backend's `error` field, when present. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ErrorBody {
  error?: string;
  message?: string;
  // VALIDATION_ERROR carries pydantic's errors() list instead of `message`.
  detail?: { msg?: string }[];
}

async function toApiError(res: Response): Promise<ApiError> {
  // Non-JSON bodies (e.g. nginx's HTML 413 page) fall through to the status line.
  const err = (await res.json().catch(() => ({}))) as ErrorBody;
  const message =
    err.message ??
    err.detail?.[0]?.msg ??
    (res.status === 413 ? 'File is too large' : `HTTP ${res.status}`);
  return new ApiError(message, res.status, err.error ?? null);
}

async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('token');
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'X-App-Surface': APP_SURFACE,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...((opts.headers as Record<string, string>) ?? {}),
    },
  });
  if (!res.ok) throw await toApiError(res);
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : ({} as T);
}

function jsonFetch<T>(path: string, method: string, body?: unknown) {
  return apiFetch<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export const api = {
  get: <T>(path: string) => jsonFetch<T>(path, 'GET'),
  post: <T>(path: string, body?: unknown) => jsonFetch<T>(path, 'POST', body),
  put: <T>(path: string, body?: unknown) => jsonFetch<T>(path, 'PUT', body),
  patch: <T>(path: string, body?: unknown) => jsonFetch<T>(path, 'PATCH', body),
  delete: <T>(path: string) => jsonFetch<T>(path, 'DELETE'),
  // No Content-Type: the browser sets multipart/form-data with its boundary.
  upload: <T>(path: string, form: FormData) => apiFetch<T>(path, { method: 'POST', body: form }),
};

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}
