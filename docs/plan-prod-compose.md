# Plan: RAG services in `docker-compose.prod.yml`

Schedule row "RAG services added to `docker-compose.prod.yml` with `mem_limit`" (T5, T9; vzhou2 owns the compose part). Design: `docs/design-rag.md` §4.3.1 (services), §4.3.3 (memory on the e2-standard-4: 4 vCPU, 16 GB).

## 1. Changes

- **`ollama`, `ollama-pull`, `infinity`, `chroma`** are copied from `docker-compose.yml`. The image, command, entrypoint, platform, health check and `depends_on` are identical, and a unit test keeps them that way.
- **No published ports.** Only nginx's 80 is reachable from outside. The backend reaches the RAG services over `qna_network` by service name, as in dev (`.env.template` defaults).
- **`mem_limit`:** 9 GB for `infinity` (gte-Qwen2 fp32 ≈ 6.2 GB plus activations; MiniLM and bge ≈ 0.3 GB) and 4 GB for `ollama` (one model loaded: 1.5 GB for 1.5b, 2.5 GB for 3b). That leaves 3 GB of the 16 for MySQL, Redis, Chroma, the backend and nginx (≈ 2 GB) and the host. A model server that outgrows its own limit is killed and restarted alone; the limits don't prevent a host-level OOM (the VM has no swap), so the runbook still applies (gte ingestion only with `RAG_LIVE_ENABLED=false`, no ingestion during harness runs).
- **Restart policies:** `unless-stopped` on the three servers. `ollama-pull` keeps `restart: "no"`, so each deploy's `docker compose up -d` runs it once and only pulls missing models.
- **No `env_file` on model containers**, so MySQL and GitLab secrets stay out of them.
- **Backend:**
  - `depends_on` the three servers with `service_started` (a cold Infinity takes up to 15 minutes; `GET /api/rag/health` reports state meanwhile);
  - mounts `uploads_data:/data/uploads`;
  - the new volumes are `ollama_models`, `infinity_cache`, `chroma_data` and `uploads_data`.
- **Unchanged:** nginx already allows 300 s and 50 MB per `/api/` request; the backend image already has `git`; the CI deploy job already runs `docker compose pull && docker compose up -d --remove-orphans`.

## 2. Tests (written first)

`tests/unit/test_prod_compose.py` parses both compose files and checks:

- dev/prod parity of the RAG services (image, command, entrypoint, platform, environment, volumes, health check, `depends_on`);
- no `env_file` on the RAG services;
- only nginx publishes ports;
- the two limits, and that every `mem_limit` in the file sums to 14 GB or less;
- restart policies;
- the backend's `depends_on` and uploads volume;
- declared volumes.

All 13 tests failed before the change. After the Goldfish review, the parity check covers environment and volumes, and `gib()` parses every compose byte form (a new test).

## 3. Results (2026-10-25)

- **Unit:** `test_prod_compose.py` 14 passed; the full unit suite on this branch 344 passed.
- **Compose:** `docker compose -f docker-compose.prod.yml config -q` is clean.
- **Local boot of the prod file** (project `qnaprod`, images built locally as `local/qna/{backend,nginx}:test`), with a scratchpad override that:
  - moves nginx to 8090;
  - drops gte, which doesn't fit the laptop's 3.9 GB Docker VM;
  - pulls only `qwen2.5:1.5b`;
  - sets `APP_ENV=development` for the integration run, because prod's login limit (5 per 15 minutes) stops the suite.
- **Health and frontend:** `GET /api/rag/health` through nginx reported Ollama, Infinity and Chroma `ok`, and `/student/` served 200.
- **`ollama-pull`:** the first run failed on a transient DNS error resolving the model CDN; a re-run succeeded. On the VM, re-run it with `docker compose up ollama-pull` if a deploy hits the same error.
- **Integration** (`test_rag_ingestion.py`, `test_rag_access.py` against `localhost:8090`): 139 passed, 2 failed, 24 skipped. P10 and R15 read Chroma on the dev host port 8001, which prod deliberately doesn't publish. They pass against the dev stack.
- **Observed:** nginx caches the backend's IP at startup, so recreating *only* the backend gives 502s until nginx restarts. A deploy recreates both, because both images change tag every commit. This matters only for a manual `docker compose up -d backend` on the VM.

## 4. Goldfish review (fresh subagent)

No blockers or majors; "safe to merge".

| Severity | Finding | Resolution |
|---|---|---|
| Minor | A failed `ollama-pull` doesn't fail the deploy: `up -d` doesn't wait for it, so CI goes green with models missing. | Needs `docker compose wait ollama-pull` after `up -d` in `.gitlab-ci.yml`, which varikooty owns; passed on (§5). |
| Minor | "An OOM kills one model server, not the backend" overclaims: only per-container overruns are contained, and the VM has no swap. | Comment and §1 reworded. |
| Minor | The sum check only re-added the two pinned limits; parity skipped `environment` and `volumes`. | Parity covers both; the sum is over every `mem_limit`. |
| Nit | `gib()` broke on ints and `9gb`. | Handles all compose forms; tested. |
| Nit | Memory figures disagreed. | One figure: 3 GB left, ≈ 2 GB used by the rest. |
| Nit | The VM `.env` must keep gte in `INFINITY_MODEL_ID`. | Runbook item in §5. |

## 5. For the VM (varikooty)

- **CI:** add `docker compose wait ollama-pull` after `docker compose up -d --remove-orphans` in `deploy_full_stack`, so a failed model pull fails the deploy.

- **`.env`:** the VM's `.env` needs the RAG block from `.env.template`:
  - `RAG_*`, `OLLAMA_URL`, `INFINITY_URL`, `CHROMA_HOST` and `CHROMA_PORT`;
  - `OLLAMA_PULL_MODELS`, `INFINITY_MODEL_ID` and `INFINITY_BATCH_SIZE`, with gte kept (`Alibaba-NLP/gte-Qwen2-1.5B-instruct`, batch 4): without it, the `embedding-alt` profile can't be created;
  - `GITLAB_TOKEN` if repository resources are used.
- **First deploy:** the first start downloads about 7 GB into `infinity_cache`. The backend serves meanwhile and `GET /api/rag/health` shows Infinity not yet `ok`.
- **Disk:** the 50 GB boot disk holds images plus models (≈ 7 GB of embeddings, ≈ 3 GB of Ollama models).
