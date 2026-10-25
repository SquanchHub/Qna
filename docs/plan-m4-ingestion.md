# M4 plan: fetchers, ingestion jobs, re-sync, profile and resource APIs

Schedule row 10-28 (vzhou2, T4, T7). Design: `docs/design-rag.md` §4.5 (ingestion), §4.6 (security), §5 (tables), §6 (API). Branch `feature/rag-ingestion`, stacked on `feature/rag-chunking` (MR !19), which is stacked on `feature/rag-data-model` (MR !18). The MR targets `main`.

Done when the M4-marked cases in `tests/integration/test_rag_ingestion.py` and `test_rag_access.py` pass against the local stack, and the new unit tests pass. Cases marked `rag_m5`, `gitlab` or `live_board` skip until M5 or until a token is configured. M5 cases skip because `/compare` is missing; that is intended.

## 1. Files

| File | Contents |
|---|---|
| `services/rag/locks.py` | `INGESTION_LOCK = asyncio.Semaphore(1)`; `JOB_CREATE_LOCK = asyncio.Lock()`, held around "check for an active job, insert jobs, commit" so two requests cannot both pass the check. M5 adds `GENERATION_LOCK`. |
| `services/rag/ssrf.py` | `resolve_public(host, port)`, `is_public(ip)`, `guarded_get(url, ...)` |
| `services/rag/archives.py` | `read_zip(data) -> list[(path, bytes)]`, `safe_filename(name)` |
| `services/rag/fetchers.py` | `Document`, `Fetched`, `fetch(resource)` dispatch: upload, web page, GitLab file, git clone; `parse_gitlab_file_url`, `parse_repo_url`, `git_env`, `scrub` |
| `services/rag/embeddings.py` | `embed(model, texts)` (Infinity `POST /embeddings`), `served_models()` |
| `services/rag/store.py` | Chroma: `open_client()`, `collection(client, profile)`, `resource_ids(coll, rid)`, `drop_collection`, `delete_resource_chunks` |
| `services/rag/ingest.py` | `build_chunks(...)`, `sync_resource(...)`, `run_job(job_id)` |
| `services/rag/profiles.py` | `list_profiles`, `create_profile`, `delete_profile`, `active_jobs` |
| `services/rag/resources.py` (extended) | `register_resource`, `upload_resource`, `delete_resource`, `list_resources` |
| `services/rag/jobs.py` | `create_profile_job`, `create_resource_jobs`, `list_jobs`, `get_job` |
| `schemas/rag.py` | Request and response models |
| `routers/rag.py` (extended) | The course routes in §6; health gains `limits` |
| `tests/unit/test_ssrf.py`, `test_archives.py`, `test_fetchers.py`, `test_ingest.py`, `test_rag_routes.py` | §7 |
| `services/README.md`, `routers/README.md`, `schemas/README.md` | One section each for the new modules |

## 2. API layer

### 2.1 Auth and errors

- Every course route depends on `require_course_staff`. FastAPI runs dependencies before it validates the body, so a denied request gets 401/404/403 and never reaches a write (A1–A8).
- Errors are `QnaError(code, message, status)`. App codes: `PROFILE_NOT_FOUND`, `RESOURCE_NOT_FOUND`, `JOB_NOT_FOUND` (404); `DUPLICATE_PROFILE`, `JOB_RUNNING`, `PROTECTED_RESOURCE`, `NO_PROFILES` (409); `UNKNOWN_PRESET`, `EMBEDDING_MODEL_NOT_SERVED`, `URL_NOT_ALLOWED`, `UNSUPPORTED_FILE`, `UNSAFE_ARCHIVE` (422); `PAYLOAD_TOO_LARGE` (413, the existing class). Checks that pydantic cannot express (a multipart field, or a rule across fields) raise `QnaError("VALIDATION_ERROR", ..., 422)`, with the same `{error, message}` shape.
- IDs are looked up by `(id, course_id)`, so another course's ID is the same 404 as a missing one.
- There are no PATCH or PUT routes. Starlette answers 405 for a path that matches with another method: `DELETE /profiles/{pid}` exists, so PATCH/PUT give 405 (P9).

### 2.2 Schemas (`schemas/rag.py`)

- Requests are `extra="forbid"`.
  - `ProfileCreate {preset: str, name: str | None}`. `name` matches `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` and defaults to `preset`.
  - `ResourceRegister {resource_type: Literal["syllabus", "schedule", "repository"], title (1–255 chars, stripped), url (≤ 2048 chars), git_ref?, subpath?}`. A model validator rejects:
    - a scheme other than http/https, or a URL with no host;
    - for a repository, any scheme but https;
    - `git_ref` or `subpath` on a non-repository resource;
    - a `git_ref` that is 40 hex characters, or that is empty, starts with `-`, or contains whitespace, `..` or `:`;
    - a `subpath` that is absolute, contains a `..` segment or a backslash, or is empty after stripping `/`. `subpath` is stored normalised, without leading or trailing `/`.
  - `ResourceSync {profile_ids: list[int] | None}` with `min_length=1` when given.
- Responses are plain dicts built by `serialize_profile`, `serialize_resource` and `serialize_job`, matching the existing `qa_service` style and the field lists in design §6. `utc_z(dt)` gives `dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"`, or `None`. MySQL `DATETIME` is naive and the server runs in UTC, so every timestamp the app writes is `datetime.now(UTC).replace(tzinfo=None)`.

### 2.3 Routes

| Route | Behaviour |
|---|---|
| `GET /presets` | `[{preset, embedding_model, query_instruction, chunking, served}]`. `served` comes from one `served_models()` call; if Infinity is down it is `False` everywhere. |
| `GET /profiles` | Ordered by id. `active_job_id` is the profile's newest QUEUED/RUNNING job, found with one query for the whole course. |
| `POST /profiles` | Steps: an unknown preset is 422 `UNKNOWN_PRESET`; the preset's model must be in `served_models()`, else 422 `EMBEDDING_MODEL_NOT_SERVED` (an unreachable Infinity counts as not served, and the message says so); a name already in the course is 409 `DUPLICATE_PROFILE`. It then inserts and flushes; an `IntegrityError` from a concurrent duplicate also maps to 409. `validate_chunking` runs as a guard and should never fail for a built-in preset. Returns 201. No Chroma call: the collection is created at the first sync. |
| `DELETE /profiles/{pid}` | 404, then 409 `JOB_RUNNING` if the profile has an active job. Drops the Chroma collection (a missing collection is ignored), then deletes the row (states and jobs cascade). Returns 204. A Chroma failure is 503 `CHROMA_UNAVAILABLE`, and the row is kept, so a retry can finish the job. |
| `POST /profiles/{pid}/sync` | 404, then under `JOB_CREATE_LOCK`: 409 if there is an active job; otherwise insert the job as QUEUED with scope `profile`, upsert a QUEUED state for every course resource, commit, schedule `run_job`, and return 202 `Job`. |
| `GET /resources` | Ordered by id, historical Q&A included. `states` has one entry per course profile, in profile id order, with `profile_name`; a profile with no state row shows `{status: "NEVER", chunk_count: 0, last_commit_sha: null, last_synced_at: null, error: null}`. |
| `POST /resources` | Schema validation (422 `VALIDATION_ERROR`), then the SSRF check on the host (§3.1, 422 `URL_NOT_ALLOWED`). Inserts `source_kind: url`; 201. |
| `POST /resources/upload` | §3.4. |
| `DELETE /resources/{rid}` | Order of checks: 404; 409 `PROTECTED_RESOURCE` for historical Q&A; 409 `JOB_RUNNING` if an active job has `resource_id = rid`, or has scope `profile` in this course. It then deletes `where resource_id = rid` from every course profile's collection, sets each profile's `chunk_count` from `count()`, deletes the upload directory, deletes the row, and returns 204. A Chroma failure is 503 with the row kept. |
| `POST /resources/{rid}/sync` | 404 `RESOURCE_NOT_FOUND`. With `profile_ids`, every id must be a course profile, else 404 `PROFILE_NOT_FOUND`; without it, every course profile, and none is 409 `NO_PROFILES`. Under `JOB_CREATE_LOCK`, if any target has an active job it is 409 and nothing is created. Otherwise one QUEUED job per profile with scope `resource`, a QUEUED state for each (rid, pid), commit, schedule each `run_job`, and 202 `{jobs}`. |
| `GET /jobs` | `status: Literal[QUEUED, RUNNING, SUCCEEDED, FAILED] \| None`, `limit: int = Query(20, ge=1, le=100)`, ordered `created_at DESC, id DESC`. |
| `GET /jobs/{jid}` | 404 `JOB_NOT_FOUND` |
| `GET /api/rag/health` | Adds `limits: {max_upload_mb, max_zip_mb}` (design §6, answer 3) |

**Scheduling.** The router commits explicitly before `asyncio.create_task(run_job(job_id))`, because `get_db` commits only after the handler returns, and the task must see the row. Task references are kept in a module-level set until they finish, so they are not garbage-collected. The jobs then queue FIFO on `INGESTION_LOCK`.

## 3. Fetchers

`Document(rel_path: str, data: bytes, kind: "md" | "pdf" | "html", charset: str | None = None)`. `Fetched(documents, ctx: CitationContext, commit_sha: str | None)`. Any fetch failure raises `FetchError(message)`, and its message is already scrubbed (§3.3).

### 3.1 SSRF guard (`ssrf.py`)

- `is_public(ip)`: false for private, loopback, link-local, multicast, reserved, unspecified and site-local addresses. It also unwraps IPv4-mapped IPv6 and NAT64 (`64:ff9b::/96`) and checks 6to4 and Teredo embedded IPv4, so `::ffff:127.0.0.1` is refused. It uses `ipaddress`'s `is_global` and also rejects `100.64.0.0/10` (CGNAT, which `is_global` already excludes).
- `resolve_public(host, port)`: one `getaddrinfo` in `asyncio.to_thread`. Every returned address must be public, otherwise `UrlNotAllowed`; the first one is used. A host that is an IP literal is checked directly.
- **At registration**: `localhost`, `*.localhost`, IP literals and resolved names are checked (R12: `ollama` and `mysql` resolve to Docker-network private addresses). If DNS fails, the registration is still accepted: the fetch-time guard is the authority, and a registration should not depend on the backend's DNS at that moment. The sync then fails with "host does not resolve".
- **`guarded_get(url, *, headers, max_bytes, timeout=30, max_redirects=5, allow_redirects=True)`**:
  - For each hop it parses the URL (http/https only) and calls `resolve_public`. It then requests `scheme://<ip>:<port>/path?query` with the header `Host: <host[:port]>` and `extensions={"sni_hostname": host}`, so TLS SNI and certificate checks use the real name while the TCP connection goes to the validated IP. That defeats DNS rebinding.
  - It streams the body and aborts past `max_bytes` (`FetchError("larger than N MB")`).
  - Redirects (301/302/303/307/308) are followed manually up to 5 hops, with each `Location` resolved against the current URL and re-validated. `allow_redirects=False` treats a 3xx as a failure. Token-bearing GitLab API calls use it, so `PRIVATE-TOKEN` is never forwarded.
  - It returns `(final_url, status, headers, body)`, and a non-2xx status is a `FetchError`.
  - It uses one `httpx.AsyncClient(follow_redirects=False, trust_env=False)`. `trust_env=False` means a proxy variable cannot reroute the request.

### 3.2 Per source kind

- **Upload.** Reads `upload_path`. `.md`/`.pdf`/`.html`/`.htm` give one Document, with `rel_path` = the stored safe file name. `.zip` goes through `read_zip`, and `rel_path` is the path inside the zip. The context is `CitationContext("upload", rid, base=citation_base_url, in_zip=is_zip)` and `commit_sha` is `None`. A missing file is a `FetchError`.
- **Web page** (syllabus or schedule, not on GitLab). `guarded_get(url, max_bytes=MAX_FETCH_MB)` gives one `html` Document, with the charset taken from the `Content-Type` header if present. When it is absent, BeautifulSoup detects the encoding from the bytes and the `<meta>`. The context is `CitationContext("web", rid, url=<registered url>)`, `rel_path` is `None`, and `commit_sha` is `None`.
- **GitLab file URL** (`host == GITLAB_HOST` and the path contains `/-/blob/` or `/-/raw/`).
  - `parse_gitlab_file_url` splits `/<project>/-/(blob|raw)/<ref>/<file>`. `<ref>` is the first segment after `blob/`, and the file path must not be empty and must not contain `..`.
  - It calls `GET https://<host>/api/v4/projects/<quote(project, safe="")>/repository/files/<quote(file, safe="")>?ref=<ref>`, adding `PRIVATE-TOKEN` only when a token is configured, with `allow_redirects=False`.
  - The JSON gives base64 `content` (≤ `MAX_FETCH_MB` decoded) and `last_commit_id`, which must be 40 hex characters.
  - The context is `CitationContext("gitlab", rid, web=https://<host>/<project>, sha=last_commit_id)`, `rel_path` is the file path, and `commit_sha` is `last_commit_id`.
  - A 404 becomes "file not found on GitLab"; S3 relies on this.
- **Repository** (clone).
  - `parse_repo_url`: https only, path stripped of a trailing `/` and `.git`, no query or fragment, which gives `WEB`. `resolve_public(host, 443)` runs first; git does its own DNS lookup, so the rebinding defence is only for `guarded_get`. That gap is accepted and noted in §8.
  - It runs `git clone --depth 1 --single-branch --no-tags [--branch <git_ref>] -- <WEB>.git <tmp>` with `asyncio.create_subprocess_exec`, under a 120 s `wait_for`. On timeout the process is killed. The temporary directory comes from `tempfile.mkdtemp(dir=CLONE_TMP_DIR, prefix="qna-clone-")`.
  - `git_env(host)` builds the environment:
    - a minimal base: `PATH`, `HOME=<tmp parent>`, `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_ASKPASS=/bin/true`, `LC_ALL=C`;
    - `GIT_CONFIG_COUNT`/`KEY_i`/`VALUE_i` for `protocol.allow=never`, `protocol.https.allow=always`, `http.followRedirects=false`, `core.symlinks=false` and `core.hooksPath=/dev/null`;
    - only for `GITLAB_HOST` with a token, `http.extraHeader=Authorization: Basic base64("oauth2:" + token)`.
  - The token never appears in argv or a URL. The header is never written to `.git/config`, because env config is not persisted.
  - `git -C <tmp> rev-parse HEAD` gives the SHA, which must be 40 hex characters.
  - It walks `<tmp>/<subpath>` with `os.walk(followlinks=False)`, skipping `.git` and `node_modules` and anything that is a symlink. Every file's `realpath` must stay under `<tmp>`. `*.md` and `*.pdf` (case-insensitive) are kept, with limits of 2000 files and 200 MB total. A file over `MAX_ZIP_MB` is skipped with a warning.
  - `rel_path` is relative to the **repo root**, using POSIX separators. A missing subpath is "subpath not found in repository".
  - The context is `CitationContext("gitlab", rid, web=WEB, sha=HEAD)`. A non-GitLab host still gets GitLab-style URLs; that is a known limitation, since the design targets GitLab.
  - The temporary directory is always removed in `finally` with `shutil.rmtree(ignore_errors=True)`.
- **Historical Q&A.** In its own short session it loads the course's questions with their posts, ordered by question id. Each question goes through `qa_answer`, and each qualifying pair through `chunk_qa(qid, title, body, answer.body, chunking)`. The context is `CitationContext("internal", rid, course_id, frontend_url=FRONTEND_URL)`. It is handled in `ingest.py`, not in fetchers.

### 3.3 Token scrubbing

`scrub(text)` replaces the token, `base64("oauth2:"+token)` and `oauth2:<token>` with `***`. Every stored error and log message from the GitLab or git paths passes through it, including git stderr (truncated to 500 characters). Errors never include request headers.

### 3.4 Upload route and zip safety

- **Order of checks:**
  1. form fields: `resource_type` ∈ syllabus, schedule, repository; `title` is 1–255 characters; `citation_base_url`, if present, is http(s) and ≤ 2048 characters. A failure is `VALIDATION_ERROR`.
  2. the file extension for the resource type: syllabus and schedule take `.html`/`.htm`; repository takes `.zip`/`.md`/`.pdf`. A mismatch is `UNSUPPORTED_FILE`.
  3. `read_upload_capped` with `MAX_ZIP_MB` for a zip, else `MAX_UPLOAD_MB` (413).
  4. for a zip, `read_zip`: `BadZipFile` is `UNSUPPORTED_FILE`, a safety failure is `UNSAFE_ARCHIVE`, and an archive with no `.md`/`.pdf` is `UNSUPPORTED_FILE`.
  5. for a `.pdf`, a page-count check (§3.5).
  6. insert and flush to get the id, write to `UPLOAD_DIR/<cid>/<rid>/<safe_filename>`, and set `upload_path`.

  A write failure removes the directory and re-raises, and the request rolls back. Nothing is stored before step 6, so a 413 or 422 leaves no row behind (R10).
- **`safe_filename`:** basename only. Characters outside `[A-Za-z0-9._-]` become `_`, the name is at most 100 characters, and the extension is kept. An empty or dot-only result becomes `upload<ext>`. `original_filename` stores the client's name, truncated to 255.
- **`read_zip(data)`:**
  - Reject (`UnsafeArchive`) any entry whose name is absolute (`/`, `\`, or a drive letter), contains a `..` segment or a backslash, is a symlink (`(external_attr >> 16) & 0o170000 == 0o120000`), or is encrypted.
  - Abort past 2000 entries, or past 200 MB of **actual** decompressed bytes (read in 64 KB pieces, counting).
  - Directories are skipped, and so is `__MACOSX/`. Only `.md`/`.pdf` are kept. A single top-level directory shared by **every** kept file is stripped.
  - Returns `[(path, bytes)]` sorted by path. It is called at upload, to validate, and again at sync, which reads the stored zip.

### 3.5 PDF limits

`parse_pdf(data)` runs `asyncio.wait_for(asyncio.to_thread(_pages), 60)`. `_pages` opens the `PdfReader`, raises `FetchError` if `len(reader.pages) > 500`, and returns the text of each page through `pdf_pages`' logic. A timeout is a `FetchError("PDF parse timed out")`, and the thread finishes in the background. At upload, a quick `len(reader.pages)` check (under the same 60 s bound) turns a corrupt PDF or one over 500 pages into 422 `UNSUPPORTED_FILE`.

## 4. Chunks per resource (`build_chunks`)

For each Document, by kind and resource type:
- `md` gives `chunk_markdown(data.decode("utf-8", "replace"), basename(rel_path), chunking)`;
- `pdf` gives `chunk_pdf(await parse_pdf(data), basename(rel_path), chunking)`;
- `html` gives `await chunk_html(data, resource_type, chunking, embed=partial(embed, model))`.

`html` takes bytes. If a charset was given, the bytes are decoded first with `errors="replace"`, and an unknown charset falls back to bytes. For an uploaded or GitLab HTML file, `rel_path` is the file path.

Chunks are grouped by `rel_path`, and `assign_ids(group, rid, rel_path)` runs once per group. Historical Q&A uses one group with `rel_path=None`. For each chunk:
- **id and hash:** from `assign_ids`;
- **document:** `chunk.text`;
- **embedded text:** `chunk.embedded_text`;
- **metadata:** `chunk_metadata(chunk, course_id, profile_id, resource_id, chunk_index, source_url, content_hash, ingest_job_id, rel_path, commit_sha)`, where `chunk_index` is the position across the whole resource.

## 5. Sync and jobs (`ingest.py`)

### 5.1 `sync_resource(resource, profile, job_id, coll, client_embed)`

The design §4.5.6 pseudocode, with these specifics:
- **Fetch and chunk.** Fetch and chunk run outside any DB session. A `FetchError`, or any exception while chunking, gives `FAILED` with the scrubbed message, and nothing in Chroma is touched.
- **Zero chunks.**
  - For a fetched source, zero chunks is `FAILED` ("no chunks"), and nothing is deleted.
  - **Historical Q&A** is the exception: MySQL is authoritative, so zero qualifying threads is `READY` with `chunk_count` 0, and stale chunks are deleted. Without this, a profile sync in a course with no answered threads would always fail (J1 and the shared `rag_course` sync expect `SUCCEEDED`), and a thread that was un-accepted would stay indexed.
- **Comparing with Chroma.** `existing = coll.get(where={"resource_id": rid}, include=[])["ids"]`, then:
  - `add`: new chunks not in `existing`, in chunk order;
  - `keep`: new chunks already in `existing`;
  - `stale`: ids in `existing` that are no longer new.
- **Writing.**
  - `add` goes in batches of 8: `embed(profile.embedding_model, texts)` under `RAG_INGEST_EMBED_TIMEOUT_S`, then `coll.upsert(ids, embeddings, documents, metadatas)`. `written` collects the ids.
  - `keep` is one `coll.update(ids=keep, metadatas=...)`.
  - `stale` is one `coll.delete(ids=stale)`.
  - Any exception deletes `written` (best effort) and gives `FAILED`.
  - Empty lists skip the call.
- **Result.** It returns `Outcome(status, chunk_count, commit_sha, error, added, kept, deleted)`. The caller writes the state row: `READY` sets `chunk_count`, `last_commit_sha`, `last_synced_at=now` and `error=None`. `FAILED` sets `error` and leaves `chunk_count` and `last_commit_sha` at their old values, because the old chunks are still there.
- **Embeddings.** Infinity returns `data[i].embedding` with `index`; they are sorted by index, and a count mismatch is an error. Documents are embedded without `query_instruction`, which applies only to queries (M5).

### 5.2 `run_job(job_id)`

```
async with INGESTION_LOCK:
  try:
    session: job = get(job_id) or return; job RUNNING, started_at = now; commit
    rids = [job.resource_id] if scope == resource else all course resource ids (by id)
    client = await open_client(); coll = await collection(client, profile)
    for rid in rids:
      session: resource, profile = get both or skip; state RUNNING (upsert); commit
      outcome = await sync_resource(...)
      session: write the state from outcome; job.chunks_* += ...; commit
    session: profile.chunk_count = await coll.count(); job SUCCEEDED or FAILED
             (error = "k of n resources failed"), finished_at = now; commit
  except Exception:
    log; session: job FAILED with "internal error: <type>", finished_at;
         its profile's QUEUED/RUNNING states (for scope resource, only that one) → FAILED; commit
```

- **Collection.** `get_or_create_collection(name, configuration={"hnsw": {"space": "cosine"}}, metadata={"embedding_model": ...}, embedding_function=None)`. `embedding_function=None` matters: the default would try to download ONNX MiniLM inside the backend.
- **Chroma down.** If Chroma is unreachable, that is caught by the outer `except`, and the job and states become FAILED.
- **Deletes during a run.** A profile or resource cannot be deleted while it has an active job (409), so the "skip if missing" check covers only course deletion (cascade). The job row may vanish at any step; every session step tolerates a missing row.
- **Restart.** Bootstrap already marks QUEUED and RUNNING jobs and states FAILED.

### 5.3 Profile and resource delete

These follow §2.3. `store.delete_resource_chunks(client, profiles, rid)` runs `coll.delete(where={"resource_id": rid})` on each profile's collection, skips a collection that does not exist, and returns the new counts.

## 6. Config, Docker and requirements

- `git` is already in `backend/Dockerfile`, and the dev compose already mounts `uploads_data:/data/uploads`. `CLONE_TMP_DIR=/tmp` is outside `/app`.
- No new Python requirements: `httpx`, `chromadb-client`, `pypdf` and `python-multipart` are present.
- `.env.template` documents nothing new; every M4 variable exists from M1.

## 7. Tests (written first)

**Unit tests** (`tests/unit`, no stack):
- **`test_ssrf.py`:**
  - `is_public` for 127.0.0.1, 10.0.0.1, 172.16.0.1, 192.168.1.1, 169.254.169.254, 100.64.0.1, 0.0.0.0, ::1, fe80::1, fc00::1, `::ffff:127.0.0.1`, 64:ff9b::7f00:1, 224.0.0.1 (all refused) and 93.184.216.34 and 2606:4700::1 (allowed);
  - `resolve_public` with `getaddrinfo` patched: a name that resolves to one private and one public address is refused;
  - `guarded_get` on a `MockTransport`:
    - it connects to the IP with the `Host` header and the `sni_hostname` extension;
    - a redirect to `http://127.0.0.1/` is refused;
    - 6 redirects is too many;
    - a body larger than `max_bytes` aborts;
    - `allow_redirects=False` turns a 302 into an error;
    - `ftp://` is refused.
- **`test_archives.py`:**
  - zip-slip (`../x.md`), an absolute path, `C:\x.md`, a backslash, a symlink and an encrypted flag (set in the header) are each `UnsafeArchive`;
  - the 200 MB limit (patched to 1 KB) is checked on actual bytes, with the entry's declared `file_size` set to a lie;
  - more than 2000 entries (patched to 3) fails;
  - the single shared top directory is stripped, and is not stripped when there are two top directories or a root-level file;
  - `.txt` is dropped and `__MACOSX` skipped;
  - `safe_filename` handles `../../etc/passwd.md`, `"my notes.md"`, `"...md"` and a 300-character name.
- **`test_fetchers.py`:**
  - `parse_gitlab_file_url` for blob and raw URLs, subgroups (`cdis/cs/courses/...`), an empty file and `..`;
  - `parse_repo_url` strips `.git` and `/`, and refuses http and a query string;
  - `git_env`: the header is present only for `GITLAB_HOST` with a token; the token is not in any argv; `protocol.allow=never`, `http.followRedirects=false` and `GIT_TERMINAL_PROMPT=0`;
  - `scrub` removes the token, its base64 and `oauth2:<token>`;
  - the GitLab file fetch, with `guarded_get` patched: the API URL is quoted (`%2F` in the project), the token is in `PRIVATE-TOKEN` and the SHA in the context, and a 404 is a `FetchError`;
  - a repository walk over a temporary tree (no git: the clone is patched to `cp -r`) with a symlink to a file outside, a symlinked directory, `node_modules`, `.git` and a subpath; `rel_path` is relative to the repo root;
  - a PDF over 500 pages (limit patched) fails.
- **`test_ingest.py`**, with a fake collection (an in-memory dict with `get`/`upsert`/`update`/`delete`/`count`) and a fake `embed`:
  - first sync adds everything;
  - an unchanged re-sync is `(0, n, 0)`, with `ingest_job_id` updated in metadata;
  - an edited file adds the changed chunks and deletes the stale ones;
  - a fetch failure after a successful sync leaves the old set intact (S3 strong form);
  - an embed failure on the second batch deletes the first batch and keeps the old set;
  - zero chunks is FAILED and deletes nothing;
  - historical Q&A with zero threads is READY with 0 and deletes the stale chunks;
  - batches have at most 8 chunks.
- **`test_rag_routes.py`** (ASGI client, `MockTransport` for Infinity, a fake session only where cheap): the `ResourceRegister` validator cases (R11 list plus `http` repository, whitespace in `git_ref`, `subpath` "/", a backslash); `ProfileCreate` name cases (P7); `utc_z`. The routes themselves are covered by the integration tests.

**Integration** (`tests/integration`, against `--base-url http://localhost:8002`): `-m "rag_m4 or rag_m2 or rag_m1"` on `test_rag_ingestion.py` and `test_rag_access.py`, plus the full existing suite (`test_qa_flow.py`, `test_security.py`) for regressions. With `db_access` (MySQL :3306, Chroma :8001) P10 and R15 check Chroma directly.

## 8. Risks and accepted gaps

- **Clone DNS rebinding.** git resolves the host itself after our check. A host could rebind between the two lookups; the window is small, and the clone is https with redirects off and only `GITLAB_HOST` gets a token. Accepted and documented.
- **Repeated work.** A sync re-downloads and re-chunks everything; only embedding is incremental. Fine at course scale.
- **Infinity down at profile create.** This is 422 `EMBEDDING_MODEL_NOT_SERVED`, with a message saying Infinity is unreachable.
- **`asyncio.create_task` jobs lost on restart.** The bootstrap sweep marks them FAILED (M2).

## 9. Verification

1. Unit tests: `cd tests/unit && ../../.venv/bin/pytest -q -p no:logging`.
2. `ruff check backend/ scripts/`; `ruff format --check backend/ scripts/` (ruff 0.15.21).
3. Rebuild the backend (`docker compose -p qna74 ... up -d --build backend` with the port 8002 override); `docker compose exec backend git --version`.
4. Integration tests: `tests/integration` with `--base-url http://localhost:8002`, RAG M1/M2/M4 cases, `test_qa_flow.py` and `test_security.py`.
5. Manual: register `https://example.com/` as a syllabus and sync it, to check the real IP-pinned TLS path with SNI. Without egress this is skipped, and the result is recorded.

## 10. Goldfish plan review (fresh subagent) and how each finding was handled

The reviewer found no blockers. The auth order, error codes, ordering, NEVER states, the 405, the name pattern, `profile_ids` and the Chroma 1.5.9 calls were checked against the tests and the client source. Each item below is now part of the plan and overrides the earlier sections where they differ.

| # | Finding | Resolution |
|---|---|---|
| 1 | Major: `created_at` is a server default. After a flush it is not loaded, so serializing it lazy-loads, which raises MissingGreenlet and gives a 500. | Every row this milestone inserts sets `created_at = utcnow()` in Python, consistent with §2.2. The historical-Q&A rows from bootstrap are read back by queries, which load the column. |
| 2 | Major: exceptions other than `FetchError` (DNS, `httpx`, timeouts, bad GitLab JSON or base64, `UrlNotAllowed`) escape `sync_resource`. That would hit the outer handler, skip the remaining resources, and leave `error` empty. S3 needs a FAILED state with an error. | `fetch()` turns every exception into a scrubbed `FetchError`, and `UrlNotAllowed` subclasses it. `run_job` catches exceptions per resource, marks that resource FAILED with an error, and continues. The outer handler also writes `error` on the states it sweeps. Unit tests cover DNS failure, ConnectError and timeout. |
| 3 | Major: DELETE of a profile or resource checks for an active job outside `JOB_CREATE_LOCK`, so it races with job creation. | Both DELETE routes hold `JOB_CREATE_LOCK` from the check through the Chroma delete and the commit. |
| 4 | Major: duplicate `profile_ids` would create two jobs for one profile. | The list is de-duplicated, keeping order. A unit test covers it. |
| 5 | IP-pinned TLS: httpcore pools connections by IP origin and ignores SNI; IPv6 literals need brackets; relative `Location` headers. | A new `AsyncClient` per hop. IPv6 addresses are bracketed. `Location` is resolved against the logical URL. Unit tests cover these. |
| 6 | Deviation: design §4.5.2 says "a ref with `/` is 422", but the plan takes the first segment as the ref. | Recorded as a deviation. A blob URL cannot say where the ref ends, so the first segment is the ref, and a branch containing `/` must be registered by tag or SHA. The `ref` query parameter is URL-quoted. |
| 7 | Repo URL userinfo, host normalisation, and no limit on clone disk use. | `parse_repo_url` rejects userinfo and lowercases the host after stripping a trailing `.`. A watchdog checks the clone directory's size every second and kills git past 500 MB (`CLONE_MAX_MB`, a constant). |
| 8 | An `IntegrityError` caused by a missing course (ADMIN on any id) maps to `DUPLICATE_PROFILE`. | Course routes check that the course exists (404 `NOT_FOUND`) before writing, and the duplicate check is an explicit query. |
| 9 | One `update` or `delete` call can exceed Chroma's maximum batch size. | `keep` and `stale` are sent in slices of `await client.get_max_batch_size()`. |
| 10 | If the stale delete fails after the `keep` update, the old set has already been relabelled. | Noted in §5.1. The ids and texts are intact; only the metadata (lines, SHA, job id) has been refreshed. The order stays add → keep → stale, as the design requires. |
| 11 | File-system deletes come before the commit, and an upload write is followed by a commit that may fail. | `DELETE /resources` commits, then removes the upload directory. The upload route commits explicitly and removes the written file if the commit fails. |
| 12 | Undisclosed deviations: historical Q&A with zero chunks is READY, and 503 `CHROMA_UNAVAILABLE`. | Both are recorded in an "As built (M4)" note in design §4.5.6 and §6, and `CHROMA_UNAVAILABLE` is added to the §2.1 list. |
| 13 | FastAPI parses the body before dependencies run; only body validation comes after them. | §2.1 is reworded below. The auth outcome is unchanged: no handler code runs before the auth check, so nothing is written. |
| 14 | §6 items are stale: git is already in the Dockerfile, and `CLONE_TMP_DIR` is already outside `/app`. | Confirmed; no Docker change is needed. |
| — | Missing tests | Added to §7: per-resource failure isolation in `run_job`; a state `error` set by the outer handler; two concurrent syncs giving one 202 and one 409; fetch error mapping; `scrub` on a git stderr message containing the base64 header; `limits` and `served`; duplicate `profile_ids`; a `git_ref` with a leading `-`; a NUL in `subpath`. |

§2.1, corrected: FastAPI reads and parses JSON and form bodies before it resolves dependencies, but it raises body validation errors only after dependencies run, and the handler runs last. A request that fails auth therefore never reaches handler code, though an unauthenticated multipart body is still spooled by Starlette first. nginx's 50 MB cap bounds that.

## 11. Results (2026-10-25)

**As built vs. plan.** Profile, resource and job operations are in a single `services/rag/catalog.py` instead of `profiles.py`/`jobs.py`; `resources.py` is unchanged. Everything else follows §1–§10.

| Check | Result |
|---|---|
| Unit tests (`tests/unit`) | 330 passed (320 before the diff-review fixes) |
| `ruff check` / `ruff format --check` (`backend/ scripts/`) | clean |
| Integration `test_rag_ingestion.py` + `test_rag_access.py` + regressions `test_qa_flow.py` + `test_security.py` (:8002, after the fixes, with `pymysql` installed so `db_access` P10 and R15 run) | 162 passed, 24 skipped: 23 are M5 (`/rag/compare` not deployed) and 1 is gte not served by Infinity (`embedding-alt`) |
| Concurrent syncs against real MySQL (8 at once, one profile) | one 202, seven 409 `JOB_RUNNING` |
| `gitlab`-marked cases | skipped (no `GITLAB_TOKEN` locally), so P8 "token not configured" runs |
| §9.5 manual IP-pinned TLS check | passed in the backend container: `guarded_get('https://example.com/')` → 200 (certificate verified against the SNI name while connecting to the pinned IP); `http://github.com/` → redirect followed to `https://github.com/`, 200 |

## 12. Goldfish diff review (fresh subagent) and how each finding was handled

The reviewer found the SSRF guard, token handling, git invocation, symlink handling and rollback order sound.

| # | Finding | Resolution |
|---|---|---|
| 1 | Major: the auth dependencies read on the request's session before `JOB_CREATE_LOCK`, so under MySQL's REPEATABLE READ the busy check could miss a job committed while the request waited. That allows two active jobs for one profile, or a DELETE racing a running job. | The router's `job_lock(db)` takes the lock and then commits, so the check runs in a fresh transaction. All four routes use it. A unit test asserts commit → check → commit, and the race check against MySQL above passes. |
| 2 | Major: a corrupt deflate stream (`zlib.error`) or an unsupported method (Deflate64, `NotImplementedError`) gave a 500 on upload. | `_read_member` re-raises these, plus `EOFError` and `OSError`, as `UnsafeArchive` (422). Unit tests cover both. |
| 3 | Minor: if `stale` spans more than one Chroma batch and a later delete fails, part of the old set is already gone. | Accepted and documented in design §4.5.6. It needs more than `get_max_batch_size()` stale chunks for one resource (thousands; far above course scale), and the next successful sync repairs it. |
| 4 | Minor: the resource-delete 503 said "nothing was deleted" when earlier collections may already be cleared. | The message now says the chunks may be partly deleted, and that retrying is safe because the delete is idempotent. |
| 5 | Minor: if MySQL is down when the job is marked FAILED, the job stays QUEUED and blocks its profile until restart. | `_mark_failed` retries after 1, 5 and 30 s. Unit test. |
| 6 | Minor: an error after the upload file was written but before the commit left an orphaned directory. | The write, flush and serialization are wrapped together; any exception removes the directory. |
| 7 | Nit: `::/96` (IPv4-compatible), `::ffff:0:0:0/96` (SIIT) and `fec0::/10` passed `is_public`. | They are refused outright. Unit tests. |
| 8 | Nit: an IPv6-literal URL sent `Host` without brackets, and SNI set to an IP. | `Host` is bracketed, and SNI is omitted for literals. Unit test. |
| 9 | Nit: the upload PDF page count was computed and discarded. | Over `MAX_PDF_PAGES` is 422 `UNSUPPORTED_FILE` at upload. PDFs inside a zip are still checked at sync. Unit test. |
