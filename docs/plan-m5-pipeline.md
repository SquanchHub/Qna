# M5 plan: pipeline, compare, answer job, prompts, locks, metrics

Schedule row 10-29 (vzhou2, T5, T6, T7). Design: `docs/design-rag.md` §4.1.3 (citations on the AI post), §4.2.3–§4.2.5 (`ai_status`, answer job, acceptance), §4.4.3–§4.4.6 (retrieval, prompt, compare, board defaults), §4.5.7 (locks). Branch `feature/rag-pipeline`, from `main` after M4 (MR merged as `14f7700`). The MR targets `main`.

Done when every `rag_m5` case in `tests/integration/test_rag_compare.py`, `test_rag_board.py`, `test_rag_access.py` and `test_rag_ingestion.py` passes against the local stack (`live_board` with `RAG_LIVE_ENABLED=true`, then `live_off` with it false), the existing suites stay green, and the new unit tests pass. Cases that need gte, `qwen2.5:3b`, a GitLab token or `RAG_EVAL_CORPUS=1` may skip.

## 1. Files

| File | Contents |
|---|---|
| `services/rag/prompts.py` | `BASELINE_GUARDRAIL` (T6 verbatim), `LIVE_SUFFIX`, `LIVE_PROMPT`, `escape(text)`, `user_message(hits, question)` |
| `services/rag/metrics.py` | `cpu_snapshot()`, `cpu_percent(windows)` over `psutil.cpu_times()` |
| `services/rag/pipeline.py` | `ProfileSnap`, `Hit`, `Retrieval`; `retrieve`, `generate`, `pulled_models`, `model_available`, `compare`. **Never imports `qa_service`** |
| `services/rag/answer_job.py` | `initial_status(db, course_id)`, `schedule(question_id)`, `run(question_id)`, `citations(hits)`, `post_body(answer, citations)` |
| `services/rag/locks.py` | adds `GENERATION_LOCK = asyncio.Semaphore(1)` and `acquire(lock, timeout)` |
| `services/rag/embeddings.py` | `embed(..., timeout=None)`: the query path passes its own timeout |
| `services/qa_service.py` | `create_question(..., ai_status="NONE")`; new `create_ai_answer` |
| `routers/qa.py` | `create_question` sets the initial `ai_status` and schedules the job after the commit |
| `routers/rag.py` | `POST /courses/{course_id}/rag/compare` |
| `schemas/rag.py` | `CompareRequest` |
| `common/exceptions.py` | `UnprocessableError` (422), `ServiceUnavailableError` (503), `GatewayTimeoutError` (504), each taking a code |
| `requirements.txt` | `psutil==7.1.3` |
| `tests/unit/test_prompts.py`, `test_metrics.py`, `test_pipeline.py`, `test_answer_job.py`; `test_rag_routes.py` (extended) | §6 |
| `services/README.md`, `routers/README.md`, `schemas/README.md` | One section each for the new modules |

## 2. Retrieval (`pipeline.retrieve`)

```
ProfileSnap(id, name, embedding_model, query_instruction, collection_name)   # plain, no ORM
Hit(score: float (raw), document: str, metadata: dict)
Retrieval(matched, hits, embedding_ms, retrieval_ms)

retrieve(snap, query, threshold, coll, count, embed_timeout):
  t0; [qvec] = embeddings.embed(snap.embedding_model, [snap.query_instruction + query], timeout=embed_timeout)
  t1; res = coll.query(query_embeddings=[qvec], n_results=min(RAG_TOP_K, count),
                       include=["documents", "metadatas", "distances"])   # under CHROMA_TIMEOUT_S
  hits = [Hit(1 - d, doc, meta) ...], sorted by score descending; keep score >= threshold (raw)
```

- `count` comes from the caller's `coll.count()`, which both callers already need for `PROFILE_EMPTY`/`SKIPPED`. Capping `n_results` at `count` avoids asking Chroma for more results than the collection holds.
- `CHROMA_TIMEOUT_S = 10`, a module constant, covers each `count()` and `query()` call. The design budgets about 1 s for the query; 10 s is the bound that keeps the total under 180 s.
- `open_snap_collection(snap)` returns `(coll, count)`, or `(None, 0)` when the collection does not exist yet (a profile that was never synced). `store.existing_collection` already does the lookup.
- Embedding errors map as in §4: `asyncio.TimeoutError` and `httpx.TimeoutException` are 504 `UPSTREAM_TIMEOUT`; a connect error or a non-2xx status (including Infinity's warm-up 503) is 503 `UPSTREAM_UNAVAILABLE`.

## 3. Generation (`pipeline.generate`) and prompts

- `POST {OLLAMA_URL}/api/chat` with `{"model", "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user_message}], "stream": false, "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 300}}`. No `keep_alive` (env only, §4.4.4). The result is `message.content`. Timeout via both `httpx` and `asyncio.wait_for`.
- An Ollama 404 at chat time (the model was removed after the check) is 422 `MODEL_NOT_AVAILABLE`; any other non-2xx is 503.
- `pulled_models()`: `GET /api/tags` → the set of `models[].name`. `model_available(name, pulled)`: `name in pulled`, or for a name without `:`, `name + ":latest" in pulled` (x8).
- **User message** (§4.4.4), tag = `resource_type`:

  | Tag | Attributes |
  |---|---|
  | `syllabus`, `schedule` | `source`, `section` = title |
  | `repo_markdown` | `source`, `file` = `rel_path`, `lines` = `a-b` |
  | `repo_pdf` | `source`, `file`, `page` = `page_start` |
  | `historical_qa` | `source`, `thread` = title |

  The body is the Chroma document (embedded text). `escape` maps `<` → `‹`, `>` → `›`, `"` → `'` in bodies and attribute values. **The question is escaped too**: a question containing `</context>` could otherwise close the block. This adds to the design (§4.4.4 names only context text and attributes) and is recorded in §8.
- `LIVE_PROMPT = BASELINE_GUARDRAIL + " " + LIVE_SUFFIX`, both verbatim from §1.1 and §4.4.6.

## 4. `POST /api/courses/{course_id}/rag/compare` (`pipeline.compare`)

`CompareRequest` (`extra="forbid"`): `question` (stripped, 1–4000), `ingestion_profile` (1–64), `similarity_threshold` (0.0–1.0, `allow_inf_nan=False`), `system_prompt` (1–8000), `generation_model` (1–100). Auth is `require_course_staff`.

Steps, in this order (§4.4.5):
1. Profile by `(course_id, name)`, else 404 `PROFILE_NOT_FOUND`. Copy it into a `ProfileSnap`.
2. `db.rollback()` releases the connection; nothing else touches MySQL.
3. Open the collection and `count()`; missing or 0 is 409 `PROFILE_EMPTY`.
4. `pulled_models()`; the model must pass `model_available`, else 422 `MODEL_NOT_AVAILABLE`. Checked before retrieval, so an off-topic question still gets the 422 (x7).
5. `embeddings.served_models()`; `None` (Infinity unreachable) is 503 `UPSTREAM_UNAVAILABLE`, and a model not in the set is 409 `EMBEDDING_MODEL_UNAVAILABLE`.
6. CPU snapshot A; `retrieve(..., embed_timeout=RAG_COMPARE_EMBED_TIMEOUT_S)`; snapshot B.
7. If matched: `acquire(GENERATION_LOCK, RAG_COMPARE_LOCK_WAIT_S)` else 503 `GENERATION_BUSY`; snapshot C; `generate(..., RAG_COMPARE_GENERATION_TIMEOUT_S)`, timing only this call; snapshot D; release. Otherwise `answer = None`, `generation_time_ms = 0`, and no C→D window.
8. Return exactly `{matched, retrieved_chunks: [{resource_type, source_url, similarity_score: round(score, 4), text}], answer, metrics: {embedding_time_ms, retrieval_time_ms, generation_time_ms, cpu_percent}}`. Times are `int(round(ms))`; a matched `generation_time_ms` is at least 1.

The order of checks is the design's (profile and emptiness, then model, then embedding model). Only the `rollback` moves, from step 5 to step 2, since steps 3–5 never read MySQL; this releases the connection earlier.

Errors are `QnaError` subclasses, so the existing handler gives `{error, message}`. A Chroma error that is neither a timeout nor a missing collection is 503 `UPSTREAM_UNAVAILABLE`.

**Metrics** (`metrics.py`). `cpu_snapshot()` is `psutil.cpu_times()`. For each window, `Δtotal` = the sum of all fields' deltas and `Δbusy = Δtotal − Δidle − Δiowait` (`iowait` is 0 where psutil has no such field, as on macOS). `cpu_percent([(A, B), (C, D)]) = round(100 × ΣΔbusy / ΣΔtotal, 1)`, clamped to 0–100, and 0.0 when `ΣΔtotal` is 0 (a window shorter than one clock tick).

## 5. Live board (`answer_job.py`)

### 5.1 Trigger (`routers/qa.py` `create_question`)

```
status = await answer_job.initial_status(db, course_id)   # NONE if live off; SKIPPED if PENDING >= cap; else PENDING
question = await qa_service.create_question(db, course_id, member.user, body, ai_status=status)
await db.commit()
if status == "PENDING": answer_job.schedule(question.id)
return serialize_question_detail(question)
```

- `initial_status` counts the course's PENDING questions. Two simultaneous creates can both pass, going one over the cap; the cap is a soft guard and this is accepted.
- `schedule` uses `asyncio.create_task` with a module-level task set, like `ingest.schedule_job`, instead of `BackgroundTasks`. The job then runs outside the request's lifecycle, and both kinds of background work follow one pattern. Recorded as a deviation in §8.
- Follow-ups and answers never trigger the job (B14).

### 5.2 `run(question_id)` (never raises)

```
try:
  snap = load(question_id)        # one short session: {course_id, title, body} and ProfileSnap for RAG_DEFAULT_PROFILE, or None
  if question gone: return
  if no profile: finish(SKIPPED)
  coll, count = open_snap_collection(snap); if count == 0: finish(SKIPPED)
  query = (title + "\n\n" + body)[:4000]
  r = retrieve(snap, query, RAG_DEFAULT_THRESHOLD, coll, count, embed_timeout=RAG_INGEST_EMBED_TIMEOUT_S)
  if not r.matched: finish(NO_MATCH)
  acquire GENERATION_LOCK within RAG_LIVE_LOCK_WAIT_S, else finish(FAILED)
    answer = generate(RAG_DEFAULT_MODEL, LIVE_PROMPT, user_message(r.hits, query), RAG_LIVE_GENERATION_TIMEOUT_S)
  if is_decline(answer): finish(DECLINED)
  cites = citations(r.hits); body = post_body(answer, cites)
  session: create_ai_answer(...); ANSWERED (conditional, below); commit
           ConflictError (closed meanwhile) → SKIPPED; commit
except Exception: log; finish(FAILED)
```

- **Live embed timeout.** There is no `RAG_LIVE_EMBED_TIMEOUT_S`; the live job uses `RAG_INGEST_EMBED_TIMEOUT_S` (120 s), since it may queue behind an ingestion batch in Infinity and nobody waits on it.
- **`finish(qid, status)`** is `UPDATE questions SET ai_status = :s WHERE id = :qid AND ai_status = 'PENDING'`, in its own session. Terminal values therefore never change (B10), even if the restart sweep or a second job got there first. The ANSWERED update in the insert session uses the same condition.
- **`citations(hits)`**: hits in rank order, deduplicated by `source_url` (first wins), numbered from 1: `{rank, resource_type, title, source_url, similarity_score: round(score, 4)}`. Hits are already above the threshold and at most `RAG_TOP_K`.
- **`post_body`**: `answer.strip() + "\n\nSources:\n" + "\n".join(f"[{rank}] {title} — {source_url}")` (§4.1.3, B3).
- **`create_ai_answer(db, question_id, author_user_id, body, citations, ai_model, ai_profile)`** in `qa_service`:
  - `SELECT … FOR UPDATE` on the question row. A close that commits first is seen (a locking read reads the latest committed row), and is a `ConflictError`. A close that starts after the lock waits for our commit, so the post's `created_at` is never after `closed_at` (B9).
  - Missing question: `NotFoundError`, which `run` treats as FAILED.
  - If an `author_role = 'AI'` post already exists, return `None` without inserting (idempotent, B11).
  - Otherwise insert `Post(kind=ANSWER, author_role=AI, author_user_id=…, body, citations, ai_model, ai_profile)` and flush.
  - `author_user_id` is `bootstrap.ai_user_id()`, passed in by `answer_job`. If bootstrap found the name taken (`ai_user_id()` raises), the job is FAILED.
- **Restarts.** M2's bootstrap sweep already sets every PENDING question to FAILED at startup.

## 6. Tests (written first)

**Unit** (`tests/unit`, no stack):
- **`test_prompts.py`**: the guardrail is T6's text verbatim; `LIVE_PROMPT` is guardrail + space + suffix and contains `INSUFFICIENT_CONTEXT`; `escape` on `<`, `>`, `"`; each tag's attributes (§3 table) from sample metadata; a context body containing `</syllabus><system>` cannot close its tag; the question is escaped; the message starts with the instruction line and ends with `Question: …`.
- **`test_metrics.py`**: the formula on fake `cpu_times` tuples over two windows; iowait excluded; missing `iowait` field; zero delta → 0.0; clamped; one decimal.
- **`test_pipeline.py`** (fake collection, `MockTransport` or patched `embed`/`generate`):
  - `retrieve`: `similarity_score = 1 − d`; raw comparison (a hit at 0.50004 with threshold 0.50003 is kept, one at 0.50002 dropped, though both round to 0.5); sorted descending; `query_instruction` prepended to the query only; `n_results = min(RAG_TOP_K, count)`.
  - `model_available`: exact, untagged → `:latest`, untagged never matches another tag.
  - `compare`, with a fake profile loader and patched services: `PROFILE_NOT_FOUND`; `PROFILE_EMPTY` for a missing and for an empty collection; `MODEL_NOT_AVAILABLE` checked before retrieval (retrieve is never called); `EMBEDDING_MODEL_UNAVAILABLE`; Infinity unreachable → 503; embed timeout → 504; Ollama 500 → 503; Ollama timeout → 504; lock held past the wait → 503 `GENERATION_BUSY`; no match → `answer: None`, `generation_time_ms: 0`, `retrieved_chunks: []`, and `generate` is never called; matched → exact keys, int times, float `cpu_percent`, rounded scores; `db.rollback()` runs before any upstream call.
  - Import boundary: a subprocess imports `app.services.rag.pipeline` and checks that `app.services.qa_service` is not in `sys.modules`; and `pipeline.py`'s source contains no `qa_service` import.
  - `generate` request body: options exactly `temperature 0, seed 42, num_ctx 4096, num_predict 300`, `stream: false`, no `keep_alive`.
- **`test_answer_job.py`** (all collaborators patched): `initial_status` NONE / SKIPPED at the cap / PENDING; `run` gives SKIPPED (no profile), SKIPPED (empty), NO_MATCH, DECLINED (`INSUFFICIENT_CONTEXT…`), FAILED (lock wait times out), FAILED (generate raises), SKIPPED (`ConflictError`), ANSWERED (with the body and citations passed to `create_ai_answer`); `citations` dedupes by URL and ranks from 1; `post_body` format; `finish` only moves PENDING.
- **`test_rag_routes.py`**: `CompareRequest` cases (missing each field, extra field, threshold 1.5, −0.1, NaN, empty and whitespace question, 4001 chars, prompt 8001, profile 65; and 0.0, 1.0 and 4000 chars accepted, with the question stripped).

**Integration** (`tests/integration`, `--base-url http://localhost:8002`): `test_rag_compare.py`, `test_rag_board.py`, the `rag_m5` cases of `test_rag_access.py` and `test_rag_ingestion.py`, with `RAG_LIVE_ENABLED=true`; then the `live_off` case with the backend restarted with it false. Plus the full existing suites for regressions.

## 7. Verification

1. Unit: `cd tests/unit && ../../.venv/bin/pytest -q -p no:logging`.
2. `ruff check backend/ scripts/`; `ruff format --check backend/ scripts/`.
3. Rebuild the backend (`docker compose -p qna74 -f docker-compose.yml -f <port-override> up -d --build backend`); `/api/rag/health` shows `qwen2.5:1.5b` and MiniLM.
4. Integration as in §6.
5. Manual: ask one board question in the browser-free way (curl), read the AI post body and citations; record a sample compare response and its timings.

## 8. Deviations from the design, and risks

- **Question escaped** in the user message (§3), adding to §4.4.4.
- **`rollback` earlier** in compare (§4).
- **`n_results = min(RAG_TOP_K, count)`** (§2), and every status write is conditional on PENDING (§5.2).
- **`create_ai_answer` takes `author_user_id`**, so `qa_service` doesn't import `bootstrap`.
- **The Chroma document is the display text** (`chunk.text`, `ingest.py`), not the embedded text that design §4.1.2 names. It has been so since M4, so prompt bodies and compare's `text` carry no heading prefix; the prompt's `section`/`file` attributes carry it instead. Recorded in the design.
- **`asyncio.create_task`** instead of `BackgroundTasks` (§5.1).
- **Live embed timeout** reuses `RAG_INGEST_EMBED_TIMEOUT_S` (§5.2).
- **Soft PENDING cap** under concurrent creates (§5.1).
- **CHROMA_TIMEOUT_S** is a constant, not env.
- **Risk:** CPU-only Ollama in Docker on the dev laptop is slower than the VM, so x13's 150 s budget and the 150 s live wait may be tight locally. A failure there is reported as measured, not hidden; U7 is measured on the VM at M6.
- **U8** (browser check of 5 text-fragment citations) needs the M5f frontend's links; it is left for M5f/M6 and noted in the schedule.

## 9. Goldfish plan review (fresh subagent) and how each finding was handled

No blockers. The reviewer traced every assertion in the compare, board, access and ingestion M5 cases and found the plan would pass them. It also confirmed that `asyncio.wait_for(sem.acquire(), t)` is safe on Python 3.12 and that MySQL `FOR UPDATE` reads the latest committed row under REPEATABLE READ. Its note about "another session implementing in this checkout" was this session's own uncommitted test-first work. Each item below overrides the earlier sections where they differ.

| # | Finding | Resolution |
|---|---|---|
| 1 | Major: the worst case could pass 180 s. `open_client` and `get_collection` were unbounded, and each Chroma call had 10 s. | One 5 s bound covers client creation, lookup and `count()`; another covers the query. The tag check is 5 s. Worst case: 5 + 5 + 3 + 15 + 5 + 30 + 100 = 163 s. The whole compare also runs under `asyncio.timeout(170)`, which gives 504. A unit test checks the sum. |
| 2 | Major: a failed `/api/tags` must be 503, not 422. | `pulled_models` raises (it doesn't reuse the never-raising health probe); unit test. |
| 3 | Major: `store.existing_collection` turns any `ValueError` into "no collection", so it would become `PROFILE_EMPTY`/`SKIPPED`; other `httpx` errors, bad JSON and the client-creation `ValueError` were unmapped. | The pipeline looks the collection up itself and treats only `chromadb.errors.NotFoundError` as empty (x6 confirms this is what 1.5.9 raises). `_upstream` maps timeouts to 504 and every other exception to 503. Unit tests cover `ReadError`, `RemoteProtocolError`, `KeyError` and `ValueError`. |
| 4 | Minor: ANSWERED wasn't atomic with the insert. | The conditional UPDATE runs in the insert's transaction; if it matches no row, the transaction rolls back and nothing is posted. An existing AI post still gives ANSWERED. |
| 5 | Minor: B9's ordering argument relied on second-precision timestamps. | `close_question` now takes the row lock before reading, so a close that starts during an AI insert waits, then reads and sets `closed_at` after the post's commit. `created_at` (MySQL `NOW()`) and `closed_at` (Python UTC) agree because MySQL runs in UTC (U10). |
| 6 | Minor: an already-closed question still went through retrieval and generation. | `load` reports `closed`, and `run` finishes SKIPPED before retrieval; unit test. |
| 7 | Minor: an empty answer would be posted. | Empty or whitespace-only is FAILED; unit test. |
| 8 | Minor: missing unit tests. | Added: upstream mapping, the collection lookup, the compare deadline and its budget, the closed and empty paths. `create_ai_answer`'s lock and idempotency are covered by B9 and B11 against MySQL; a fake session would not show row locking. |
| 9 | Minor: `run` could raise if `finish` failed in the `except`. | Already handled: the inner `finish` is wrapped and logged; unit test. |
| 10 | Nit: §4's sentence on order contradicted itself. | Rewritten. |
| 11 | Nit: undisclosed deviations. | Added to §8, including the display-text document. |
| 12 | Nit: keep `cpu_percent` and scores floats. | `cpu_percent` returns `round(float, 1)` or `0.0`; scores are `1.0 − distance`. x1 checks both types. |
| 13 | Nit: lock with a plain select. | `create_ai_answer` locks `select(Question)` with no relationship loads. |
| — | Could cut the source-text import check. | Kept, but as an AST check of import statements (the docstring mentions `qa_service`); the subprocess check is the main one. |

## 10. Goldfish diff review (fresh subagent) and how each finding was handled

No blockers. The reviewer traced x1–x14, D1–D3, B1–B14 and K1–K9 and the harness's limits. It confirmed that the 170 s deadline wrapping the lock is safe (cancellation is a `CancelledError`, which nothing catches, and the lock is released in `finally`), that `close_question` and `create_ai_answer` cannot deadlock (both take the question's X lock first), and that `generation_time_ms` excludes the lock wait.

| # | Finding | Resolution |
|---|---|---|
| 1 | Major: after `close_question`'s lock, `_get_question` and the CLOSED check still read the REPEATABLE READ snapshot the auth dependency opened. Two simultaneous closes both succeeded, and the response could miss an AI post committed during the wait. | The locking select returns `status`, and the CLOSED check uses it. The close route commits before calling the service (as `job_lock` does), so the reads after the lock see current data; `expire_on_commit=False` keeps `member.user` usable. The design's B9 note is now accurate. |
| 2 | Minor: parsing Chroma's reply ran outside the error guard, so a malformed reply was a 500. | Parsing moved inside the guarded coroutine; unit test. |
| 3 | Minor: escaping alters code snippets in bodies; the tag name wasn't sanitised. | Tag names must match `[a-z_]+`, else `context`; unit test. Body escaping is **kept**: design §4.4.4 specifies it for text and attributes, and changing it would change the evaluated prompts. |
| 4 | Minor: a chunk without a title gave `[1] None — url`. | Title falls back to `rel_path`, then the URL; unit test. |
| 5 | Minor: `embed(timeout=0)` silently became 120 s. | `if timeout is None`. |
| — | Nits: import order, line length, a missing docstring, and an unguarded "only the lock raises" comment. | Fixed; the live job uses the same `acquired` flag as compare. |

## 11. Results (2026-10-25)

- **Unit:** 431 passed; `ruff check` and `ruff format --check` clean.
- **Integration, live on** (`localhost:8002`, after the diff-review fixes): 233 passed, 2 failed, 6 skipped. The skips are `eval_corpus`, `live_off`, three GitLab tests without a token, and gte not served by this Infinity.
  - **J2** (`test_j2_resource_sync_targets_every_profile`) got `404 Course 447 not found` creating its first profile, a course the fixture had just created. It passed in run 1 and passes alone, and no test deletes courses. It is treated as a flake of the shared dev stack, not an M5 regression.
  - **B12** (`test_b12_decline_posts_nothing`) ended `NO_MATCH`, not `DECLINED`: its off-topic question scored below the 0.50 threshold, so retrieval abstained before generation. The backend is correct. The test treats only `ANSWERED` as inconclusive and should accept `NO_MATCH` the same way. This is reported to varikooty, who owns `tests/integration`.
- **Integration, live off** (`RAG_LIVE_ENABLED=false`): `test_rag_board.py -m live_off` 1 passed.
- **Deferred:** U8 (§8) to M5f/M6.
