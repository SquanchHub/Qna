# M1 plan: RAG Compose services and `GET /api/rag/health`

Status: implemented and verified 2026-10-25 (results at the end).

Schedule row (vzhou2, 2026-10-26): Ollama, Infinity and ChromaDB in `docker-compose.yml`, `.env.template`, model pulls, service clients and `GET /api/rag/health`. Spec: `docs/design-rag.md` §4.3, §6 (health row), §9 M1, §12 U1, U4 and U6. Branch `feature/rag-services` from `main`.

## Scope

In: the dev Compose services, all §4.3.2 settings, the `git` package in the Dockerfile, pinned dependencies, read-only service clients, and the health route with its access rule.
Out: `docker-compose.prod.yml` (10-30 row), the migration and models (M2), and any embedding, chunking or Chroma collection code (M3 onward).

## Pinned versions (chosen 2026-10-25, each at least two weeks old)

| Component | Pin | Notes |
|---|---|---|
| Ollama | `ollama/ollama:0.35.1` | amd64 and arm64 |
| Infinity | `michaelf34/infinity:0.0.77-cpu` | Released 2025-08-22; 0.0.78-cpu (2026-10-19) is too new. amd64 only, so `platform: linux/amd64` (emulated under Rosetta on Apple silicon, native on the e2 VM). Fallback if emulation fails locally: check Infinity on the VM and record it as a deviation. |
| Chroma server | `chromadb/chroma:1.5.9` | Persist path `/data` (from `/config.yaml`); no curl, wget or python, but has bash |
| Chroma client | `chromadb-client==1.5.9` | Thin HTTP client, no server deps |

## Compose (`docker-compose.yml`)

- **`ollama`:** env `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=10m`; volume `ollama_models:/root/.ollama`; port `11434:11434`; healthcheck `ollama list` every 5 s (the image's `OLLAMA_HOST=0.0.0.0:11434` makes the CLI reach the server).
- **`ollama-pull`:** same image, `entrypoint: ["/bin/sh", "-c"]` (the image's entrypoint is `/bin/ollama`), running `set -e; for m in $$OLLAMA_PULL_MODELS; do ollama pull $$m; done`. `environment:` sets `OLLAMA_HOST=http://ollama:11434` and `OLLAMA_PULL_MODELS=${OLLAMA_PULL_MODELS:-qwen2.5:1.5b qwen2.5:3b}`; `restart: "no"`; `depends_on: ollama: service_healthy`. A failed pull exits non-zero. The models persist in the `ollama` volume, so later runs are no-ops.
- **`infinity`:** `command: ["v2"]`; explicit `environment:` (never `env_file`, so MySQL and GitLab secrets stay out of the model containers): `INFINITY_MODEL_ID` and `INFINITY_BATCH_SIZE` interpolated from `.env` with design defaults, `INFINITY_ENGINE=torch`, `INFINITY_DEVICE=cpu`, `INFINITY_PORT=7997`; volume `infinity_cache:/app/.cache` (the image sets `HF_HOME=/app/.cache/huggingface`); port `7997:7997`; healthcheck runs `python` urllib against `/health`, with `start_period: 900s`. `INFINITY_BATCH_SIZE` needs one entry per model.
- **`chroma`:** volume `chroma_data:/data`; port `8001:8000` (matches `CHROMA_URL` in the integration conftest); healthcheck in bash: `exec 3<>/dev/tcp/localhost/8000`, send `GET /api/v2/heartbeat`, and grep the status line for 200 (tested on 1.5.9).
- **`backend`:** adds `depends_on` the three services (`service_started`, so a slow Infinity never blocks the API) and the volume `uploads_data:/data/uploads`.
- New volumes: `ollama_models`, `infinity_cache`, `chroma_data`, `uploads_data`. There is no top-level `name:`. The project name comes from `COMPOSE_PROJECT_NAME` in `.env`, or the directory name when it is unset. The existing local volume is `qna74_mysql_data`, and the design's `qna-74` would start on an empty database, so this MR corrects §4.3.1 and §4.3.2. The template leaves the name commented out, because on the VM (`/srv/app`) the project is `app` (diff review).

## Settings (`config.py`, `.env.template`)

All §4.3.2 variables are added with their design defaults, so later milestones only read them. Only `chromadb-client==1.5.9` is added to `requirements.txt`, and `httpx` moves from the test section to runtime. `beautifulsoup4`, `lxml`, `pypdf`, `psutil` and `tokenizers` wait for the milestones that use them. The template documents `COMPOSE_PROJECT_NAME`, `INFINITY_MODEL_ID`/`INFINITY_BATCH_SIZE` (all three models, with a comment that low-RAM laptops can drop gte), `OLLAMA_PULL_MODELS`, and `GITLAB_TOKEN` (empty, a runtime secret). `RAG_DEFAULT_THRESHOLD` stays `0.50` until calibration.

On this laptop, Docker has 3.8 GB, so the local `.env` (not committed) uses MiniLM and bge only.

## Clients (`backend/app/services/rag/clients.py`)

There are three small async functions. Each takes an `httpx.AsyncClient` argument, so tests can pass one built on `httpx.MockTransport`. The route opens one client per request with a `async with`, and each probe is wrapped in `asyncio.wait_for(..., 3)` so that two sequential calls can't exceed the tests' 10 s timeout. A module-level client would bind to the first event loop. Each function returns a plain dict and never raises:

- `ollama_health()`: `GET {OLLAMA_URL}/api/tags` gives `{"ok": True, "models": [m["name"]...]}`.
- `infinity_health()`: `GET {INFINITY_URL}/health`, then `GET /models` gives `{"ok", "models": [d["id"]...]}`.
- `chroma_health()`: `GET http://{CHROMA_HOST}:{CHROMA_PORT}/api/v2/heartbeat` and `/api/v2/version` give `{"ok", "server_version", "client_version"}`. `client_version` comes from `importlib.metadata.version("chromadb-client")`, or `"unknown"` if the package isn't installed. **`/api/v2/version` returns the API version (`"1.0.0"` on 1.5.9), not the release**, so no equality check is possible. The skew guard is the two literal pins (image tag and requirement), and the design's `chroma_version_mismatch` log is dropped with that reason recorded in §4.3.3.
- When a service is down, it returns `{"ok": false, "models": []}` (Ollama and Infinity) or `{"ok": false, "server_version": null, "client_version": "<str>"}` (Chroma). It logs `rag_health_probe_failed` with the service and the exception class only.

A real `chromadb` client object is deferred to M3, because health needs only HTTP.

## Route (`backend/app/routers/rag.py`, mounted under `/api`)

`GET /rag/health` uses `asyncio.gather` over the three probes and returns:

```json
{"ollama": {"ok": true, "models": ["qwen2.5:1.5b"]},
 "infinity": {"ok": true, "models": ["sentence-transformers/all-MiniLM-L6-v2"]},
 "chroma": {"ok": true, "server_version": "1.0.0", "client_version": "1.5.9"},
 "gitlab_token_configured": false, "live_enabled": true,
 "defaults": {"profile": "sliding-window", "threshold": 0.5, "model": "qwen2.5:1.5b"}}
```

It always returns 200 to an authorized caller. Access goes through a new `require_rag_viewer` dependency in `common/dependencies.py`: 401 without a valid token; 403 `FORBIDDEN` if `X-App-Surface: student`; 403 unless the user is ADMIN or has at least one `UserCourseAccess` with role STAFF.

## Tests first (`tests/unit/test_rag_health.py`)

- Every service up: shape and types match §6, and a configured `GITLAB_TOKEN` shows only as `gitlab_token_configured: true`, never its value.
- One service down (its probe raises `httpx.ConnectError`): that service reports `ok: false`, the others report `ok: true`, and the route still returns 200.
- Unexpected payloads and slow services count as down (3 s bound per probe).
- `require_rag_viewer`: ADMIN passes; STAFF somewhere passes; STUDENT-only gets 403; the student surface gets 403 even for ADMIN.

These use `httpx.MockTransport` and a fake DB session, so no stack is needed. They run from the local venv in `tests/unit` (`pythonpath = ../../backend`), which needs `chromadb-client` installed, or the `"unknown"` fallback covers it.

The integration tests already written (`test_rag_access.py` a11/a12) start running once the route exists. They must pass against the local stack.

## Docs

- `design-rag.md`: fill in the pinned versions in §4.3.1; correct `COMPOSE_PROJECT_NAME` to `qna74`; record the Chroma version finding; mark U1, U4 and U6 as verified; move U2 (gte pooling) and U3 (gte RAM) to M6, because gte doesn't fit in this laptop's 3.8 GB Docker VM; give the health field types in §6. That answers the `ragTypes.ts:131` TODO, a frontend file, so varikooty removes it (flagged in the MR).
- The `routers/` and `services/` READMEs.
- `schedule.md`: move the row to Done.

## Verification

1. `ruff check` and `ruff format --check` on `backend/`; unit tests are green.
2. `docker compose up -d --build`: `ollama-pull` exits 0; `/api/rag/health` reports all three `ok` with models listed; `docker stats` stays under the Docker memory limit.
3. The integration tests `test_rag_access.py -k health` and `test_qa_flow.py` are green (no regressions).
4. U1: `POST /embeddings {model, input}` returns `data[].embedding` of dimension 384 for MiniLM and bge.
5. U4: create a probe collection with curl, run `docker compose restart chroma`, check it still exists, then delete it.
6. U6: `/api/tags` names equal `qwen2.5:1.5b` and `qwen2.5:3b`.

## Goldfish review (2026-10-25)

A fresh-context review found 12 issues; all were adopted above. Majors: Chroma's version endpoint reports the API version (verified: `"1.0.0"`), the design's project name `qna-74` would orphan `qna74_mysql_data`, Infinity is amd64-only on an arm64 laptop with 3.8 GB, the Chroma image has no curl (bash `/dev/tcp` healthcheck instead), a module-level httpx client breaks per-test event loops, and the U1/U2/U3 checks were missing. Minors: down-service field values, `ollama-pull` `set -e` and a default for the model list, explicit `environment:` instead of `env_file` for model containers, a real U4 persistence probe, no scope-creep requirements, and how unit tests run.

## Results (2026-10-25, MacBook arm64, Docker 3.8 GB, gte dropped locally)

- 42 unit tests pass, including the 13 new ones in `tests/unit/test_rag_health.py`; `ruff check` and `ruff format --check` are clean.
- `docker compose up -d --build`: Infinity was healthy after about 90 s under emulation, and `ollama-pull` exited 0.
- `/api/rag/health` reports all three services `ok`, with `qwen2.5:1.5b` and `qwen2.5:3b`, MiniLM and bge, and Chroma `server_version "1.0.0"` and `client_version "1.5.9"`. No token gives 401 `UNAUTHORIZED`; the student surface gives 403 `FORBIDDEN`.
- U1, U4 and U6 are verified, and the results are recorded in design §12. U2 and U3 move to M6 on the VM.
- Integration: 24 passed (including `test_rag_access.py` a11 and a12, `test_qa_flow.py` and `test_security.py`); 217 skipped, each gated on M2 or later.
- Idle memory is about 1.8 GB (Infinity 1.2 GB, MySQL 0.4 GB).
- The existing volume `qna74_mysql_data` was reused.
