# Plan: fixes for the run-plus-0 grade report

Source: `student-score-run-plus-0.md` on the `grading` branch (graded 2026-10-28 17:36 UTC), **81.0 / 90.0**. Three items lost points:

| Item | Score | Cause | Fixable? |
|---|---|---|---|
| R0 Team schedule | 0 / 3 | `docs/schedule.md` first reached `main` on 2026-10-20, after the schedule deadline | **No.** The rubric grades the version on `main` at the deadline and says later updates never change the score. |
| R5 Ingestion (G5) | 11 / 12 | `chunk_qa` windows a historical Q&A pair over 222 tokens; T4 says never split pairs | Yes (+1) |
| R7 RAG comparison (C4) | 7 / 12 | `eval/report.json` and `eval/report.md` are not committed, so the re-run had nothing to compare against | Yes (up to +5) |

**Timing.** run-plus-0 is the on-deadline run, so these fixes only count if we submit late with slip days, and the run that grades a late submission tests the deployment again. Check that we have slip days left and agree with varikooty before starting. If we don't use them, the only remaining channel is T11: R0 is a genuine miss (the template was published 2026-10-07 and our first push was 2026-10-19), so there is nothing to dispute there.

Order: R5 first, because it changes ingestion, and R7's run must use the final ingested content.

---

## Fix 1 — R5 G5: never split a historical Q&A pair

**Why the cap existed.** Goldfish finding M8 (design §13) added the 222-token cap for two reasons: MiniLM only sees 256 tokens, and four chunks of at most 252 tokens kept the prompt inside `num_ctx 4096` (§4.4.4). A pair can be up to about 20,000 characters (255-character title, 10,000-character body, 10,000-character answer), so removing the cap needs a guard in both places.

**Changes (test first):**

1. `tests/unit/test_chunking.py:470`: replace the "over the cap is windowed with title prefixes" test with "an oversized pair (`QA_MAX_TOKENS + 1` and a ~5,000-token pair) returns exactly one chunk whose text is the whole pair". Keep the at-cap test at :462.
2. `backend/app/services/rag/chunking.py` `chunk_qa`: always return one `Chunk("historical_qa", title, "", text, question_id=…)`; drop the windowing branch and the `chunking` argument's use (keep the signature so `ingest.py:147` is unchanged, or drop the argument there too).
3. **Embedding input.** Verify how Infinity 0.0.77 handles input over MiniLM's 256 tokens (U1 only tested short text): embed a ~2,000-token string locally.
   - If it truncates silently: no code change; the embedding covers the question and the start of the answer, which is what retrieval should match on. Note it in §4.5.4.
   - If it errors: truncate only the text sent to Infinity in `embeddings.py` to the model's limit, with a unit test. The stored chunk stays whole.
   - gte-Qwen2 accepts 32k tokens, so the `embedding-alt` profile embeds the whole pair either way.
4. **Prompt budget.** In the prompt builder (`prompts.py` / `pipeline.py`), clip a `historical_qa` chunk's text **in the prompt only** to 252 MiniLM tokens, ending with `…`, so §4.4.4's arithmetic still holds. The stored chunk, its citation and the thread link are unchanged. Unit test: an oversized pair produces a prompt within the budget, and short pairs are passed through byte-identical (so answers on normal threads don't move).
   - Rejected: raising `num_ctx` to 8192 or more. It costs RAM and CPU time on the VM for every call, to serve a rare case.
5. `docs/design-rag.md`: update §4.5.4 (pairs are never split), §4.4.4 (prompt-side clip), and add a §15 revision note that cites the R5 finding. Update `backend/app/services/README.md` for `chunk_qa`.
6. Run unit tests, `ruff check`, `ruff format --check`, and `tests/integration` against the local stack (ingestion tests re-sync historical Q&A).

**Effect on existing data.** Only pairs over 222 tokens change chunk IDs. After deploy, re-sync the historical-Q&A resource under every profile on the VM (re-sync adds the whole-pair chunk and deletes the old windows). Checked locally (2026-10-28): the 13 qualifying seeded pairs are at most 171 tokens, so none changes and the q12/q13 eval content is unaffected; the re-sync is a precaution.

Owner: vzhou2 (backend). MR into `main`, reviewed by varikooty.

---

## Fix 2 — R7 C4: commit a report produced against the deployment

The rubric: `eval/report.json` and `eval/report.md` are committed and reproduce cleanly against our running application, and each write-up's claims match the report. Everything else in R7 (contract, configurability, one-factor comparisons) was already met.

**Prerequisites on the VM** (varikooty owns the VM and its `.env`; vzhou2 drives the eval):

1. Merge Fix 1 into `main`, then `main` → `production` (production is at `4a9aff1`, the `fix/staff-live-api` merge, so it also picks up the AI-answer UI). Wait for the deploy job; check `/api/health` and `/api/rag/health` (Ollama, Infinity with MiniLM and gte, Chroma all up).
2. Pull both generation models in the VM's Ollama: `qwen2.5:1.5b`, `qwen2.5:3b`.
3. Course `642` ("AI-Assisted Software Development", from `eval/configs.json`): confirm it still exists on the VM with its seeded threads. If the VM was re-seeded, update `course_id`.
4. Set `RAG_LIVE_ENABLED=false` in the VM `.env` and restart the backend, so live-board jobs can't hold the generation lock during the run (design §11.1).
5. Ingest: `COURSE_ID=642 HARNESS_BASE_URL=http://34.121.90.110 HARNESS_ADMIN_PASSWORD='…' python eval/ingest_sample_data.py`. It creates `sliding-window`, `type-tailored` and `embedding-alt`, uploads the sample data and syncs each profile. gte ingestion on 4 CPUs is slow (U7), so start this early. Then re-sync the historical-Q&A resource under each profile (Fix 1).
6. Manual preflight (we never built `eval/preflight.py`): every profile READY with `chunk_count > 0` and no active job, both models in `/api/rag/health`, `live_enabled` false. One compare call per profile returns `source_url`s containing `eval/sample_data/`.

**Threshold.** Keep `0.50`. `calibrate.py` was never built, and building it now adds risk for little gain. The write-ups already say 0.50 is the team default, not a calibrated value. Optional, only if time allows: run one baseline compare per question at threshold 0.0, read the scores, and pick T by the §11.2 rule by hand. If T changes, update `configs.json`, the ± 0.15 comparisons and `RAG_DEFAULT_THRESHOLD` before the committed run, never after.

**The run.**

7. From a laptop: `HARNESS_BASE_URL=http://34.121.90.110 HARNESS_ADMIN_PASSWORD='…' python eval/compare_harness.py`. 14 questions × 8 runs = 112 calls; expect roughly 15–120 minutes. No warm-up first (§11.3: graders start cold). Unmodified harness.
8. Commit `eval/report.json` and `eval/report.md` exactly as written. Don't edit them.
9. **Freeze the course**: no re-syncs or new accepted threads in course 642 after the committed run. The grading re-run compares against it.
10. Leave the VM running with this state through the grading run. Turn `RAG_LIVE_ENABLED` back on only if it doesn't affect the re-run; the grader calls only `/rag/compare`, but keeping it off is the safer choice until grading is done.

**Write-ups (R7 criterion 5, and to keep R11 at 6/6).** Rewrite "RAG Configuration Findings" in `docs/vzhou2.md` and `docs/varikooty.md` from the committed report:
- hit rate and no-match accuracy per run, judged with the §11.3 rule fixed in advance (higher hit rate and no-match accuracy not lower; a one-question difference is a tie);
- answer quality from reading the side-by-side answers, naming the single change with the biggest gain and its cost in generation time and CPU from the report;
- whether it matched the predictions already in the docs;
- the existing caveats (one-factor-at-a-time, threshold not calibrated or tuned on the same 14 questions).
Every number must come from `report.md`; nothing claimed that the report doesn't show.

Owner: vzhou2 (run, report, both docs' numbers), varikooty (VM steps 1–4, review of the doc changes). MR into `main`, then `main` → `production` so the deployed code and the report match.

---

## Done when

- Unit and integration tests pass with Fix 1; design §4.4.4/§4.5.4 updated.
- `production` contains Fix 1; the VM has all three profiles READY and both models pulled.
- `eval/report.json` and `eval/report.md` from the VM are on `main`, and both write-ups match them.
- The VM is up and course 642 frozen for the grading run.
