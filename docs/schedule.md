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

### Remaining

| Milestone | Tasks | Owner | Target date |
|---|---|---|---|
| Merge `test/rag-tests` and `feature/staff-theme`; first `main` → `production` deploy verified (Part 8; the VM currently does not respond) | T7, T8, T9 | varikooty | 2026-10-26 |
| Tokenizer, type-tailored chunkers and citation helpers, with unit tests passing on `eval/sample_data/` | T4 | vzhou2 | 2026-10-27 |
| Fetchers, ingestion jobs, re-sync, profile and resource APIs; `test_rag_ingestion` and `test_rag_access` green | T4, T7 | vzhou2 | 2026-10-28 |
| Staff pages switched from mock JSON to the live API, open-question TODOs resolved | T4 | varikooty | 2026-10-28 |
| RAG pipeline, `POST /api/courses/{course_id}/rag/compare` dry run, background answer job (retrieval, threshold, tagged prompt with guardrail, labeled and cited AI post); `test_rag_compare` and `test_rag_board` green | T5, T6, T7 | vzhou2 | 2026-10-29 |
| AI-answer label, citation links and status polling in the student and staff apps; staff screenshots in `docs/ui/` | T5, T8 | varikooty | 2026-10-29 |
| RAG services added to `docker-compose.prod.yml` with `mem_limit`; redeploy with the RAG stack; models pulled and course seeded on the VM | T5, T9 | vzhou2 (compose), varikooty (deploy, VM) | 2026-10-30 |
| `sample_data/` ingested on the VM under every profile, threshold calibrated, `eval/configs.json`, preflight, harness run against the deployment, `report.*` and `summary.md` committed | T6 | vzhou2 | 2026-10-31 |
| Integration tests re-run against the full stack; CI pipeline green on `main` | T2, T7 | varikooty | 2026-10-31 |
| Individual documents `docs/vzhou2.md` and `docs/varikooty.md` | T10 | each | 2026-11-01 |

## Check-ins

| Date | What we will review |
|---|---|
| 2026-10-27 | Compose services and migration merged; deploy working; answers to the frontend open questions; any contract change in §6 |
| 2026-10-29 | Ingestion and compare passing the integration tests; frontend on the live API; plan for the VM eval run |
