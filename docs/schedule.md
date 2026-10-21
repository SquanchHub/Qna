# Project Schedule

## Team

| Name | NetID |
|---|---|
| Vincent Zhou | vzhou2 |
| Vikram Varikooty | varikooty |

## Timeline

Work is split by directory so the two of us rarely edit the same files: vzhou2 owns `backend/`, `docker-compose.yml` and the backend side of `eval/`; varikooty owns `frontend/`, `tests/integration/test_rag_*.py`, `.gitlab-ci.yml` and the deployment files. The design doc fixes the API shapes first, so the frontend can be built against them in parallel.

| Milestone | Tasks | Owner | Target date |
|---|---|---|---|
| Directory READMEs for `backend/app/*` and the three frontend apps written and verified | T3 | vzhou2 | 2026-10-19 |
| `docs/design-rag.md` drafted in the Elephant session, including the API endpoints the frontend will call | T3 | vzhou2 | 2026-10-19 |
| Goldfish test run and `docs/design-rag.md` revised | T3 | vzhou2 | 2026-10-20 |
| Ollama, Infinity and ChromaDB running in `docker-compose.yml` and reachable from the backend | T5 | vzhou2 | 2026-10-23 |
| Backend ingestion of syllabus, schedule, repositories and historical Q&A, with profiles, re-sync and citation metadata | T4 | vzhou2 | 2026-10-25 |
| Staff UI for registering resources by URL, the file-upload fallback, re-sync and ingestion profiles (`frontend/staff/`) | T4 | varikooty | 2026-10-25 |
| Semantic color tokens, light/dark themes and a persistent toggle in all three apps | T8 | varikooty | 2026-10-27 |
| Backend RAG pipeline: retrieval, threshold, tagged prompt with guardrail, and a labeled, cited AI post | T5 | vzhou2 | 2026-10-28 |
| AI-answer label and citation links shown in the student and staff apps | T5, T8 | varikooty | 2026-10-28 |
| `POST /api/courses/{course_id}/rag/compare` dry-run endpoint | T6 | vzhou2 | 2026-10-28 |
| GCP VM, protected `production` branch, deploy stage in `.gitlab-ci.yml`, `DEPLOYMENT_URL.txt` | T9 | varikooty | 2026-10-29 |
| Integration tests for ingestion, the pipeline and `/rag/compare`, including access-control cases | T7 | varikooty | 2026-10-30 |
| `eval/sample_data/` ingested under every profile, `eval/configs.json` written, harness run, report committed | T6 | both | 2026-10-31 |
| Theme screenshots in `docs/ui/` | T8 | varikooty | 2026-10-31 |
| Individual documents `docs/vzhou2.md` and `docs/varikooty.md` | T10 | both | 2026-11-01 |

## Check-ins

| Date | What we will review |
|---|---|
| 2026-10-23 | Design doc final; services running in Compose; agree on API shapes before the frontend work starts; move dates that have slipped |
| 2026-10-25 | Ingestion working end to end through the staff UI; what is left for the pipeline, compare endpoint, theming and deployment |
