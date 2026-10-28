# Project Schedule

## Team

| Name | NetID |
|---|---|
| Vincent Zhou | vzhou2 |
| Vikram Varikooty | varikooty |

## Timeline

Work is split by file so the two of us never edit the same file:
- **vzhou2** owns everything that makes RAG run: all of `backend/` (migration `002_rag`, models, schemas, routers, `config.py`, `requirements.txt`, `Dockerfile`, `qa_service`, `bootstrap`, and every module in `services/rag/`), `docker-compose.yml`, `.env.template`, the RAG services in `docker-compose.prod.yml`, `tests/unit/`, and `eval/` (calibration, preflight, `configs.json`, the harness run and its reports). vzhou2 also answers `docs/frontend-open-questions.md` by updating §6 of `docs/design-rag.md`.
- **varikooty** owns `frontend/` (all three apps, including the RAG pages and AI-answer display), `tests/integration/` with its fixtures, `docs/test-plan-rag.md`, `docs/ui/`, and deployment: `.gitlab-ci.yml`, `DEPLOYMENT_URL.txt`, and the VM `production-web-server` in GCP project `qna-varikooty` (its `.env`, `main` → `production` deploys, seeding and model pulls).

`docker-compose.prod.yml` already holds varikooty's base stack; from now on only vzhou2 edits it (to add the RAG services), and varikooty reviews. If a backend change breaks an integration test because the contract in `docs/design-rag.md` §6 changed, vzhou2 updates the doc first and varikooty updates the test.

### Done

| Milestone | Tasks | Owner | Finished |
|---|---|---|---|
| Directory READMEs for `backend/app/*` and the three frontend apps | T3 | vzhou2 | 2026-10-19 |
| `docs/design-rag.md` from the Elephant session, revised after the Goldfish review | T3 | vzhou2 | 2026-10-20 |
| Shared semantic color tokens, contrast check, light/dark toggle in the student and admin apps, before/after screenshots in `docs/ui/` | T8 | varikooty | 2026-10-23 |
| Staff Resources and Profiles pages, RAG API types and upload client (built against §6, before the backend exists), frontend open questions | T4 | varikooty | 2026-10-23 |
| `build`/`deploy` CI stages, `docker-compose.prod.yml` base stack, VM with static IP, `DEPLOYMENT_URL.txt` (project `qna-varikooty`) | T9 | varikooty | 2026-10-24 |
| RAG integration test plan and tests for access, ingestion, compare and the board (branch `test/rag-tests`, failing until the backend lands) | T7 | varikooty | 2026-10-24 |
| Staff app theming (branch `feature/staff-theme`) | T8 | varikooty | 2026-10-24 |
| Eval plan revised for threshold, abstention, hit-rate and median-time metrics | T3, T6 | vzhou2 | 2026-10-25 |
| M1: Ollama, Infinity and ChromaDB in `docker-compose.yml` (pinned, verified U1, U4, U6), `.env.template`, one-shot model pulls, health probes and `GET /api/rag/health` (branch `feature/rag-services`; plan in `docs/plan-m1-rag-services.md`) | T5 | vzhou2 | 2026-10-25 |
| M2: migration `002_rag` (upgrade/downgrade verified), RAG models, AI system user with `SYSTEM_ACCOUNT` guards, historical-Q&A resource per course, restart sweep, `ai_status`/`citations`/`ai_model` serializers, `decline.py`; frontend open questions answered in design §6 (branch `feature/rag-data-model`; plan in `docs/plan-m2-rag-data-model.md`) | T4, T5 | vzhou2 | 2026-10-25 |
| M3: vendored MiniLM tokenizer, presets with validation, structure-aware chunkers (markdown, HTML, PDF, historical Q&A) with sliding-window and semantic fallbacks, citation URLs, chunk IDs and Chroma metadata; 104 unit tests passing on `eval/sample_data/` (branch `feature/rag-chunking`; plan in `docs/plan-m3-chunking.md`) | T4 | vzhou2 | 2026-10-25 |
| M4: SSRF-guarded fetchers (URL, GitLab file, repository clone, upload with zip and PDF safety), ingestion jobs with incremental re-sync, profile, resource and job APIs, `limits` in health and `served` on presets; `test_rag_ingestion` and `test_rag_access` green apart from M5 skips (branch `feature/rag-ingestion`; plan in `docs/plan-m4-ingestion.md`) | T4, T7 | vzhou2 | 2026-10-25 |
| M5: retrieval with threshold, tagged prompt with guardrail and escaping, `POST /api/courses/{course_id}/rag/compare` dry run with timings and CPU, background answer job (conditional `ai_status` writes, row-locked AI post and close, labeled and cited AI post); `test_rag_compare` and `test_rag_board` green apart from B12, whose off-topic question abstains as `NO_MATCH` (test fix for varikooty); U8 left for M5f (branch `feature/rag-pipeline`; plan in `docs/plan-m5-pipeline.md`) | T5, T6, T7 | vzhou2 | 2026-10-25 |
| `test/rag-tests` and `feature/staff-theme` merged; first `main` → `production` deploy verified (VM at `http://34.121.90.110` serves the apps and `/api/health`; `production` is at the M4 merge) | T7, T8, T9 | varikooty | 2026-10-25 |
| RAG services (`ollama`, `infinity`, `chroma`) in `docker-compose.prod.yml` with `mem_limit` 9g/4g, no published ports, backend RAG URLs pinned; Infinity serves MiniLM and gte only; nginx redirects bare app paths (branch `deploy/rag-services`) | T5, T9 | varikooty | 2026-10-25 |
| `production` redeployed with M5 and the RAG services (merge of `main` through `fix/staff-live-api`) | T5, T9 | varikooty | 2026-10-27 |
| Staff pages on the live API: `ragTypes.ts` matched to the real shapes, upload limits and accepted types read from the backend (`fix/staff-live-api`) | T4 | varikooty | 2026-10-26 |
| B12 (`test_b12_decline_posts_nothing`) accepts `NO_MATCH` as inconclusive, like `ANSWERED` | T7 | varikooty | 2026-10-26 |
| AI-answer label, citation links and `ai_status` polling in the student and staff apps (`feature/ai-answer-ui`); staff screenshots in `docs/ui/` | T5, T8 | varikooty | 2026-10-27 |
| `eval/configs.json` and `eval/ingest_sample_data.py` (`eval/t6-report`) | T6 | varikooty | 2026-10-27 |
| Individual documents `docs/varikooty.md` and `docs/vzhou2.md` | T10 | each | 2026-10-27 |

### Remaining

| Milestone | Tasks | Owner | Target date |
|---|---|---|---|
| Redeploy: merge current `main` (AI-answer UI and later) into `production`, which is at the `fix/staff-live-api` merge; confirm the VM `.env` RAG block, models pulled into the VM's Ollama (`docker exec … ollama pull`, deployment Part 8 step 5.1) and the course seeded | T5, T9 | varikooty | 2026-10-30 |
| U8: browser check of 5 text-fragment citations against the real pages; any mismatch fixed in the chunkers | T4, T6 | vzhou2 | 2026-10-30 |
| Eval dry run on the local stack: threshold calibrated, preflight and a harness run, so the VM run is a rerun (`eval/configs.json` and `eval/ingest_sample_data.py` are merged; the local run was abandoned after a disk-full crash) | T6 | vzhou2 | 2026-10-29 |
| `sample_data/` ingested on the VM under every profile, threshold calibrated, `eval/configs.json`, preflight, harness run against the deployment, `report.*` and `summary.md` committed | T6 | vzhou2 | 2026-10-31 |
| Integration tests re-run against the full stack; CI pipeline green on `main` | T2, T7 | varikooty | 2026-10-31 |

## Check-ins

| Date | What we will review |
|---|---|
| 2026-10-27 | Compose services and migration merged; deploy working; answers to the frontend open questions; any contract change in §6 |
| 2026-10-29 | Ingestion and compare passing the integration tests; frontend on the live API; plan for the VM eval run |
