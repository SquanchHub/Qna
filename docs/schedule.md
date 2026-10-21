# Project Schedule

## Team

| Name | NetID |
|---|---|
| Vincent Zhou | vzhou2 |
| Vikram Varikooty | varikooty |

## Timeline

Work is split by file so the two of us rarely edit the same files:
- **vzhou2** owns all of deployment (the VM, `docker-compose.prod.yml`, `.gitlab-ci.yml`, `DEPLOYMENT_URL.txt`). In `backend/` they own the models, migrations, schemas, routers, `qa_service`, `bootstrap` and the RAG ingestion and pipeline services, plus the backend side of `eval/`.
- **varikooty** owns `docker-compose.yml`, `.env.template`, the RAG service clients, tokenizer, chunkers and citation helpers (`backend/app/services/rag/{clients,tokens,chunking,citations}.py`) with their unit tests, `frontend/`, and `tests/integration/test_rag_*.py`.

varikooty starts on 2026-10-23 with the pieces that depend on nothing else (Compose services and chunking), so his code lands first. The design doc fixes the API shapes, so the frontend can be built against them in parallel.

| Milestone | Tasks | Owner | Target date |
|---|---|---|---|
| Directory READMEs for `backend/app/*` and the three frontend apps written and verified | T3 | vzhou2 | 2026-10-19 |
| `docs/design-rag.md` drafted in the Elephant session, including the API endpoints the frontend will call | T3 | vzhou2 | 2026-10-19 |
| Goldfish test run and `docs/design-rag.md` revised | T3 | vzhou2 | 2026-10-20 |
| `build` and `deploy` stages in `.gitlab-ci.yml` and `docker-compose.prod.yml` (deployment guide Parts 6–7) | T9 | vzhou2 | 2026-10-20 |
| GCP credit, VM with static IP and Docker, VM `.env`, Workload Identity Federation, and the `deploy_full_stack` project ID/number filled in (Parts 1, 2 and 5) | T9 | vzhou2 | 2026-10-22 |
| Ollama, Infinity and ChromaDB running in `docker-compose.yml`, model pulls, service clients and `GET /api/rag/health` | T5 | varikooty | 2026-10-24 |
| Tokenizer, type-tailored chunkers and citation helpers, with unit tests passing on `eval/sample_data/` | T4 | varikooty | 2026-10-25 |
| Migration `002_rag`, RAG models, system user, Q&A resource bootstrap and serializers | T4, T5 | vzhou2 | 2026-10-25 |
| First `main` → `production` deploy verified (Part 8), RAG services added to `docker-compose.prod.yml`, `DEPLOYMENT_URL.txt` | T9 | vzhou2 | 2026-10-26 |
| Fetchers, ingestion jobs, re-sync, and the profile and resource APIs | T4 | vzhou2 | 2026-10-27 |
| Staff UI for registering resources by URL, the file-upload fallback, re-sync and ingestion profiles (`frontend/staff/`) | T4 | varikooty | 2026-10-27 |
| Semantic color tokens, light/dark themes and a persistent toggle in all three apps | T8 | varikooty | 2026-10-28 |
| RAG pipeline, `POST /api/courses/{course_id}/rag/compare` dry run, background answer job: retrieval, threshold, tagged prompt with guardrail, and a labeled, cited AI post | T5, T6 | vzhou2 | 2026-10-29 |
| AI-answer label and citation links shown in the student and staff apps | T5, T8 | varikooty | 2026-10-29 |
| Integration tests for ingestion, the pipeline and `/rag/compare`, including access-control cases | T7 | varikooty | 2026-10-30 |
| Models pulled and `eval/sample_data/` ingested on the VM under every profile, `eval/configs.json` written, harness run against the deployment, report committed | T6 | both | 2026-10-31 |
| Theme screenshots in `docs/ui/` | T8 | varikooty | 2026-10-31 |
| Individual documents `docs/vzhou2.md` and `docs/varikooty.md` | T10 | both | 2026-11-01 |

## Check-ins

| Date | What we will review |
|---|---|
| 2026-10-23 | Design doc final; agree on API shapes and the file split above before varikooty starts coding; VM and pipeline credentials ready; move dates that have slipped |
| 2026-10-25 | Compose services, chunkers and the migration merged; VM ready for the first deploy; what is left for ingestion, the pipeline, the compare endpoint, theming and tests |
