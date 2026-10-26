# Frontend open questions for the RAG API

**Status: all six answered on 2026-10-25 in `docs/design-rag.md` §6, under "Answers to docs/frontend-open-questions.md".** The `TODO(design §6)` markers in `frontend/` can now be resolved against those answers. Items 3 (`limits` in health) and 6 (`served` on presets) land with M4.

The staff Resources and Profiles pages were built against `docs/design-rag.md` §6 before the backend routes existed. These are the points where the spec doesn't pin down what the frontend needs. Each one has a conservative default in the code, marked `TODO(design §6): confirm with backend`. Once a question is answered, please update §6 and the frontend will follow.

## 1. Error bodies

§6 says errors are `{"error", "message"}`, but the existing `RequestValidationError` handler (`backend/app/common/exceptions.py`) returns `{"error": "VALIDATION_ERROR", "detail": [...]}` with no `message`.

- Will the RAG-specific 422s (bad URL or scheme, repo-only fields on other types, `..` in `subpath`, SHA `git_ref`, empty `profile_ids`) come back as `QnaError`s with a `message`, or as pydantic `detail` lists?
- nginx enforces `client_max_body_size 50m`. An upload over that gets nginx's HTML 413 page, not a JSON `PAYLOAD_TOO_LARGE`. Is that acceptable, or should the nginx limit sit above `MAX_ZIP_MB` so the backend always answers?

**Frontend default:** show `message`, else the first `detail[].msg`, else "File is too large" for a 413, else `HTTP <status>`. The `error` code is kept on `ApiError.code`.

## 2. `citation_base_url` (upload path)

§4.1.1 says the base is "joined with the in-zip path" for a zip, with `?plain=1` inserted for a GitLab `/-/blob/` base.

- For a single `.md` or `.pdf` upload, is the file name appended to the base, or is the base the full file URL?
- Does the base need a trailing `/`, or does the backend add one?
- Is the field valid for `.html` syllabus/schedule uploads, and if so, is it the page URL that text fragments attach to?
- Is it validated (scheme, SSRF), and with which error code?

**Frontend default:** help text only, no client-side validation.

## 3. Upload types and size limits

- §4.5.1 gives `.html` for syllabus/schedule and `.zip`, `.md` or `.pdf` for repository. Does the server reject a mismatched type and extension (for example a `.zip` as `syllabus`) with `UNSUPPORTED_FILE`? Is `.htm` accepted?
- `MAX_UPLOAD_MB` and `MAX_ZIP_MB` are env settings the frontend can't read. Could they be exposed, for example in `GET /api/rag/health` or a small config endpoint?

**Frontend default:** the file picker's `accept` follows §4.5.1. Client-side size checks hard-code the §4.3.2 initial values (20 MB, 50 MB for `.zip`), and the server's 413 is authoritative.

## 4. `GET /rag/jobs?status=`

- Does `status` take one value or a comma-separated list (for example `QUEUED,RUNNING`)?
- What does `limit` default to when omitted?

**Frontend default:** never sends `status`. It always sends `limit=20` and filters on the client.

## 5. Profile and preset field types

- The §6 Profile example shows `"chunking": {}`, but the text says it has the §4.4.1 shape. Is the full config always returned?
- `query_instruction` is `""` in the example but a plain `TEXT` column in §5. Is it `""` or `null` when a preset has none?
- `GET /api/rag/health` lists only key names. Confirm that `models` is a `string[]`, whether `chroma.server_version` is `null` when Chroma is down, and the types under `defaults`.

**Frontend default:** `chunking: ChunkingConfig`, with the summary guarded against `{}`; `query_instruction: string | null`; health types as assumed in `lib/ragTypes.ts`.

## 6. Presets and model availability

`GET /rag/presets` returns `{preset, embedding_model, query_instruction, chunking}`, with no display label, description, or indication of whether the embedding model is served by Infinity. An unserved model, such as the optional `bge-small`, only fails on create with `422 EMBEDDING_MODEL_NOT_SERVED`.

- Could presets include a `served: boolean` field (or only list served models), so the UI can disable those that would fail?

**Frontend default:** list every preset and show the 422 message on create.
