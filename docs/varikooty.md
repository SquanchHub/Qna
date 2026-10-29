# Vikram Varikooty (varikooty): Project 3 Write-up

My teammate was Vincent Zhou (vzhou2). In short: vzhou2 ran the T3 design sessions and built most of the backend RAG pipeline (M2–M5). I built the staff-facing RAG UI, the T8 theming for all three apps, the RAG integration test plan and tests, the GCP deployment (prod compose, CI deploy stage, RAG services on the VM), and the T6 evaluation config.

## Repository and Codebase Organization

The repository is a Docker Compose stack with one Python backend and three React front ends:

- **`backend/app/`** is the FastAPI app. `routers/` holds the HTTP layer (`qa.py` for questions and posts, `admin.py`, `auth.py`, `health.py`, and our new `rag.py`). `services/` holds the business logic the routers call; all RAG code is in `services/rag/`. `models/` holds the SQLAlchemy tables (`qa.py` has `Question` and `Post`; `rag.py` has resources, ingestion profiles and jobs), `schemas/` the Pydantic request and response shapes, and `common/` the shared auth dependencies and the `QnaError` exception handling. Migrations live in `migrations/versions/`. `002_rag.py` is ours: it adds the RAG tables, the `AI` author role and the question `ai_status` column.
- **`frontend/student`, `frontend/staff`, `frontend/admin`** are three separate Vite apps, one per role. Since T8 they share one color-token file, `frontend/shared/tokens.css`.
- **`nginx/`** routes `/api` to the backend and `/student`, `/staff`, `/admin` to the apps. **`tests/integration/`** is the pytest suite that runs against the live stack. **`eval/`** holds the T6 harness, ground truth, sample data and our `configs.json`. **`docs/`** holds the design doc, the milestone plans and the write-ups.
- The RAG services are three more Compose containers: **Ollama** (generation), **Infinity** (embeddings) and **ChromaDB** (vector store). The backend is the only thing that talks to them. In production none of them publish a port.

**How a question becomes a cited AI answer.** A student posts a question through the student app. `routers/qa.py` calls the QA service, which commits the `Question` row. If the live board is enabled (`RAG_LIVE_ENABLED`) and the course doesn't already have too many pending answers, it sets `ai_status = PENDING` and starts `services/rag/answer_job.run` as a background task, so the student's request returns right away. The job takes a plain snapshot of the question and the course's default ingestion profile. `pipeline.retrieve` embeds the title and body through Infinity using that profile's embedding model, queries the profile's Chroma collection, and keeps only chunks whose similarity is at or above `RAG_DEFAULT_THRESHOLD`. If no chunk survives, the status becomes `NO_MATCH` and nothing is posted. Otherwise, while holding the generation lock, the job builds a prompt with the chunks in tags plus the guardrail system prompt and calls Ollama. If the answer is a decline (`decline.py`), the status becomes `DECLINED`. If not, `create_ai_answer` inserts a `Post` with `author_role = AI`, authored by the system AI user. Its citations come from each chunk's stored metadata: source URL plus a line range for markdown, a page for PDFs, or a text fragment for web pages. The answer is an ordinary post in the thread, so staff accept it the same way as any human answer, and the student and staff apps render it with an AI badge, a sources list and a disclaimer.

The content that retrieval searches gets there separately. Staff register or upload resources (syllabus, schedule, repository, historical Q&A) on the staff **Resources** page, and an ingestion job fetches, chunks and embeds them under each **ingestion profile**. The profile fixes the chunker and the embedding model, so changing either means re-ingesting rather than flipping a setting.

**Directory READMEs.** vzhou2 generated and verified the T3 READMEs for the `backend/app/*` directories and the three frontend apps. My contribution was keeping the frontend ones true as the code changed. I added the Resources and Profiles pages to [`frontend/staff/README.md`](../frontend/staff/README.md), documented token theming there, and added the "Theming" section to [`frontend/README.md`](../frontend/README.md). I also used these READMEs constantly as context. My first logged session ([2026-10-23_17-50-04](../ai_log/2026-10-23_17-50-04_27855118.md)) was asking Claude to explain how the staff app calls the API and handles auth, starting from that README. What I learned from editing them is that a README is only useful as AI context while it's accurate. A stale route table or file list sends the next session in the wrong direction, so I treated updating the README as part of the same change as the code.

## Design Process (Elephant/Goldfish)

vzhou2 ran the T3 Elephant and Goldfish sessions, and I didn't run either one. The Elephant session produced the first version of [`docs/design-rag.md`](design-rag.md) (commit `85eca8d`, 2026-10-19). A fresh Goldfish session that saw only the document critiqued it, and the same day `c647565` revised it. §13 of the design doc records every Goldfish finding and what changed. The big ones were:

- the timeout budget could exceed the harness's limit, which led to holding the generation lock only around Ollama, plus `RAG_LIVE_ENABLED` to turn the live board off during eval runs
- re-sync could delete good chunks after a failed fetch, so a failed fetch or a zero-chunk result now deletes nothing
- compare configs could name models or profiles that weren't ready, which led to a preflight check
- a suggestion to drop gte-Qwen2, which was rejected because T6 requires it

Reading that log taught me what the Elephant missed. Mostly it was failure paths and concurrency (races, partial failures, timeouts), not the happy path.

My part of T3 was **implementing against the document as the spec**. I built the staff Resources and Profiles pages from §6 (the API reference) before the backend routes existed. Wherever §6 didn't pin something down, I didn't guess silently. I put a conservative default in the code, marked it `TODO(design §6): confirm with backend`, and logged the question in [`docs/frontend-open-questions.md`](frontend-open-questions.md) (commit `04204f6`). There were six mismatches:

- error bodies: `{"error", "message"}` in §6 versus the existing validation handler's `detail` list, and nginx's HTML 413 for oversized uploads
- how `citation_base_url` joins with file names
- whether upload size limits are exposed to the frontend
- the `status` filter format on `/rag/jobs`
- profile and preset field types
- whether presets say if their embedding model is actually served

vzhou2 answered all six in §6 on 2026-10-25 (`87622ab`). When the real backend landed, I matched the frontend to the live API on `fix/staff-live-api`: `ragTypes.ts` updated to the real shapes, and upload limits and accepted types read from the backend instead of hard-coded.

The process did change how I implemented. Because the doc was the contract, I could build the frontend in parallel with a backend that didn't exist yet. The open-questions file turned "the spec is vague here" into a list someone could answer, instead of hidden assumptions in my code. The rule "fix the doc first, then the code" also kept the frontend and backend from drifting. When the answers came back I mostly had to change types, not rethink the pages.

## RAG Configuration Findings

**What I set up.** I wrote [`eval/configs.json`](../eval/configs.json), following design doc §11.3, and [`eval/ingest_sample_data.py`](../eval/ingest_sample_data.py). The ingest script uploads `eval/sample_data/` through the staff API under every ingestion profile, with citation base URLs pointing at the GitLab blob path so the harness's source check can match chunks. The **baseline** is:

- chunking: the `sliding-window` profile (one fixed-size window for every type's oversized content)
- embedding: `all-MiniLM-L6-v2`
- similarity threshold: the team default, `0.50`
- system prompt: the T5 guardrail, verbatim
- generation: `qwen2.5:1.5b`

The comparisons each change exactly one field. Here is each one, what it tests, and what I expected going in:

1. **Chunking: `type-tailored-chunking`** (profile `type-tailored`). This tests whether picking a fallback chunker per resource type beats one naive window everywhere. It uses semantic chunking for syllabus and schedule prose, a 150/30 window that resets at sub-headings for markdown, and a page-reset window for PDFs. **Expected:** a small retrieval gain on syllabus/schedule questions, because a semantic chunk keeps one policy together instead of cutting it mid-paragraph. Little change elsewhere, since structure-aware splitting by header is already in the baseline.
2. **Embedding model: `gte-qwen2-last-token`** (profile `embedding-alt`, `gte-Qwen2-1.5B-instruct` with last-token pooling). This tests a ~1.5B-parameter decoder-based embedder against the ~22M-parameter MiniLM. **Expected:** better ranking of the right source, but a very large cost in ingestion time and RAM on a CPU-only machine. Its scores are on a different scale, so a 0.50 threshold tuned for MiniLM could make it look better or worse than it really is. That confound is why §11.2 planned a threshold-free hit@K check per profile.
3. **Similarity threshold: `threshold-conservative` (0.65) and `threshold-permissive` (0.35)**, baseline ± 0.15 on the baseline profile. **Expected:** conservative leaves more in-scope questions unanswered (false abstentions) but stays correct on the out-of-scope question. Permissive answers more questions but lets weak chunks through, so some answers are padded or wrong, and it risks answering the question that should get "no match".
4. **System prompt: `resist-injection` and `cite-every-claim`**, each the guardrail plus one sentence. `resist-injection` tells the model that text inside the tagged context is data and never instructions. `cite-every-claim` requires every sentence to trace to a specific passage. **Expected:** no change to retrieval, by construction. `cite-every-claim` should give shorter, more literal answers and more declines from a 1.5B model. `resist-injection` should barely matter on our sample data, which contains no injected instructions.
5. **Generation model: `qwen2.5-3b-size`** (`qwen2.5:3b`). This isolates model size within one family. **Expected:** identical retrieval, more coherent answers that better combine several chunks, and roughly double the generation time on the 4-vCPU VM.

Going in, my guess was that the generation-model change would improve answer quality most and threshold choice would matter most for retrieval. The design doc's point was to check that: a generator can't answer from a passage that retrieval never returned.

**What happened.** My own run never finished: my laptop's disk filled and WSL crashed mid-run ([session log](../ai_log/2026-10-27_14-19-48_cc8f323b.md)). vzhou2 later ran the unmodified harness against the deployed VM with my `configs.json` (course 1 on the VM) and committed [`eval/report.md`](../eval/report.md) and [`eval/report.json`](../eval/report.json). That run was after the on-deadline grading run. Two planned comparisons from §11.3, `bge-small-cls` and `live-board-prompt`, aren't in `configs.json`: the bge profile was optional, and I cut the matrix to what we could actually ingest. The threshold of 0.50 is the team default, not a calibrated value.

**What the report shows**, against my predictions above. Hit rate is out of 13, but q12 and q13 can't score as hits, so 11 is the ceiling. Every run got the out-of-scope q14 right.

- **Chunking:** type-tailored got 10 hits against the baseline's 9. Under our rule a one-question difference is a tie, so my "small gain" prediction holds only in the weakest sense. It fixed q05 but answered q10 wrongly.
- **Embedding model:** gte-Qwen2 got 11 hits (85%), the only change that beats the baseline under our rule. The cost was even larger than I expected: median wall-clock 49.8 s per question against 7.5 s, about 37 minutes to ingest against 11 s, and the VM's compare embedding timeout had to go from 15 s to 120 s. Better retrieval didn't fix the 1.5B model's answers: it still got q04's date and q05's service count wrong.
- **Threshold:** 0.65 abstained on 12 of 13 in-scope questions (0 hits), so the conservative side was far more costly than I predicted. 0.35 gained one question (a tie) but answered q03 "Yes, AI is allowed during exams", the kind of wrong answer I expected from letting weak chunks through.
- **System prompt:** as predicted, retrieval was identical and `resist-injection` changed little on data with no injections. `cite-every-claim` made answers more literal and sometimes terser, but didn't produce more declines.
- **Generation model:** as predicted, retrieval was identical and generation was about twice as slow (median 17.2 s against 7.5 s, worst case 65 s). It gave the most complete answers (q01, q03, q07) and, on q06, said the context didn't cover the question instead of guessing.

So my guess going in was half right. The 3B model improved answer quality most, but the embedding model, not the threshold, gave the only real retrieval gain.

**Limitation.** This sweep is one-factor-at-a-time: each comparison moves one axis from the baseline and holds the other four fixed. That isolates each axis's effect but says nothing about interactions. For example, it can't show whether gte retrieval plus the 3B model would fix q04 and q05 together, or whether the 3B model needs a different threshold. A full factorial over five axes was out of scope. With 13 questions, one question is 8 percentage points, and the threshold was never calibrated, so the baseline's hit rate isn't the best this pipeline can reach.

## AI Tools Used

The only AI tool I used was **Claude Code**, in the terminal. Every session is logged automatically in `ai_log/`. These are the ones that mattered, grouped by task:

- **Learning the codebase.** [2026-10-23_17-50-04](../ai_log/2026-10-23_17-50-04_27855118.md): I asked how the staff app calls the API and handles auth, and where a new page would go, with no edits allowed. That gave me a quick, accurate map that I checked against `lib/api.ts` and `App.tsx`.
- **Staff Resources/Profiles UI (T4 frontend).** [2026-10-23_18-44-16](../ai_log/2026-10-23_18-44-16_957484ed.md), [18-52-37](../ai_log/2026-10-23_18-52-37_957484ed.md): I had Claude plan the pages from design §6 before coding, then implement and commit them as six atomic commits after a `tsc --noEmit` check. It was good at turning §6 into types and components. It was also the one that surfaced the spec gaps I put in `frontend-open-questions.md`, though I decided which defaults to use.
- **T8 theming.** [2026-10-23_19-16-46](../ai_log/2026-10-23_19-16-46_a67710e5.md), [19-25-28](../ai_log/2026-10-23_19-25-28_a67710e5.md), [2026-10-24_11-51-05](../ai_log/2026-10-24_11-51-05_3c31ed92.md): token plan, then student/admin migration, then staff. I asked for a WCAG contrast script (`scripts/check_contrast.py`) so the contrast claims would be reproducible, and for a raw-palette grep to prove no hard-coded colors were left. The grep was more trustworthy than reading the diff by eye.
- **Screenshots.** [2026-10-23_19-41-20](../ai_log/2026-10-23_19-41-20_68f250f7.md), [22-32-35](../ai_log/2026-10-23_22-32-35_40debb13.md), [2026-10-26_18-33-11](../ai_log/2026-10-26_18-33-11_c249af14.md): Claude wrote `scripts/screenshots.mjs` with Playwright and captured before/after shots. This is where it fell short. It needed system libraries that only I could install with sudo, and it ran into another project's containers holding the same ports ([22-25-07](../ai_log/2026-10-23_22-25-07_40debb13.md)), which I had to decide how to handle.
- **Integration tests (T7).** [2026-10-24_11-20-41](../ai_log/2026-10-24_11-20-41_09f137fe.md): I had Claude read `tests/integration/` and design §6 and write `docs/test-plan-rag.md` before any test code. Then [2026-10-24_21-35-18](../ai_log/2026-10-24_21-35-18_e5436627.md) on `test/rag-tests` wrote the access-control, ingestion, compare and auto-responder tests. Later I changed the decline test to treat `NO_MATCH` as inconclusive ([2026-10-26_16-39-02](../ai_log/2026-10-26_16-39-02_ef8c1436.md)). Writing the plan first helped, because the tests followed the spec instead of whatever the code happened to do.
- **Deployment (T9).** [2026-10-24_16-58-14](../ai_log/2026-10-24_16-58-14_89291c8d.md), [19-49-24](../ai_log/2026-10-24_19-49-24_e5436627.md): CI deploy job variables and the production compose file. Then [2026-10-25_23-20-55](../ai_log/2026-10-25_23-20-55_3a0db312.md): adding Ollama, Infinity and Chroma to prod compose and the nginx bare-path redirects. I had Claude list the VM `.env` lines with names only for secrets, and I set the secrets myself.
- **Live API fixes and AI-answer UI.** [2026-10-26_13-59-52](../ai_log/2026-10-26_13-59-52_bba5f355.md) (`fix/staff-live-api`) and [2026-10-26_15-35-51](../ai_log/2026-10-26_15-35-51_5d984a63.md), [16-07-14](../ai_log/2026-10-26_16-07-14_5d984a63.md) (`feature/ai-answer-ui`: AI badge, sources, disclaimer and `ai_status` polling).
- **T6 evaluation.** [2026-10-27_13-24-28](../ai_log/2026-10-27_13-24-28_cc8f323b.md), [13-37-22](../ai_log/2026-10-27_13-37-22_cc8f323b.md), [14-19-48](../ai_log/2026-10-27_14-19-48_cc8f323b.md): building `configs.json` and the ingest script, attempting the local run, and abandoning it after the disk-full crash.

**Where it helped:** reading a large codebase and spec quickly, writing typed boilerplate that follows a spec, splitting work into atomic commits, and writing verification scripts (contrast checks, grep checks, test plans) that made my claims checkable. **Where it fell short:** anything involving my machine's environment (sudo, port conflicts, disk space, a 1.5B embedding model on a laptop). Also, when I told it to work autonomously on a deadline, it made choices I then had to review afterward. It also can't produce results that don't exist: once the eval run failed, the honest thing was to write the expectations down as expectations.

## Best Practices Learned

- **Design before code pays off most for parallel work.** A written contract (design §6) let me build the frontend before the backend existed. An open-questions file is a cheap way to turn spec ambiguity into answerable questions instead of silent assumptions.
- **In RAG, retrieval and generation fail differently, so evaluate them separately.** Hit rate and no-match accuracy measure retrieval. Reading answers side by side measures generation. Prompt and generation-model changes can't change retrieval at all, which is a useful sanity check on any results.
- **One-factor-at-a-time comparisons are honest only if you say what they can't show** (interactions), and only if the winning rule is fixed before the run.
- **Local model serving is an infrastructure problem.** Model sizes, RAM, disk and cold-start load times decide what you can actually evaluate. I lost the T6 run to a full disk, and the lesson is to run long evaluations on the machine they're graded on (the VM), not a laptop, and to start them well before the deadline.
- **Make AI output verifiable.** I trusted Claude's work most when it came with a check I could rerun: `tsc --noEmit`, the contrast script, the raw-palette grep, integration tests. I treated a summary without a check as a starting point, not a result.
- **Keep READMEs and design docs in sync with the code.** They're the context every later AI session starts from, so a stale doc keeps costing time.
