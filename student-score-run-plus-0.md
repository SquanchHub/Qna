# Project 3: QnA

**Score: 81.0 / 90.0**

Graded: 2026-10-28 17:36 UTC

---

## ✓ R0 — 0.0 / 3.0

0/5 tests passed

| Test | Status | Message |
|------|--------|---------|
| docs/schedule.md was on main by the schedule deadline | ✗ failed | docs/schedule.md first reached main on 2026-10-20T19:43:08-05:00, after the deadline (2026-10-16T23:59:00-05:00) |
| Team section lists every team member's NetID | ✗ failed | not assessed: docs/schedule.md first reached main on 2026-10-20T19:43:08-05:00, after the deadline (2026-10-16T23:59:... |
| Timeline table has Milestone, Tasks, Owner and Target date columns, and every row has a team-member owner and a YYYY-MM-DD date | ✗ failed | not assessed: docs/schedule.md first reached main on 2026-10-20T19:43:08-05:00, after the deadline (2026-10-16T23:59:... |
| Timeline covers every required task and gives every member at least one row | ✗ failed | not assessed: docs/schedule.md first reached main on 2026-10-20T19:43:08-05:00, after the deadline (2026-10-16T23:59:... |
| Check-ins section lists at least 2 dated check-ins | ✗ failed | not assessed: docs/schedule.md first reached main on 2026-10-20T19:43:08-05:00, after the deadline (2026-10-16T23:59:... |

---

## ✓ R1 — 5.0 / 5.0

No shortfalls are reported by at least two audits, so no criterion is counted against the work. All assessable workflow criteria B1–B6 were marked MET by the audits; B7 was marked NOT ASSESSABLE, which does not constitute a shortfall under the stated rule.

**Where to look:**

- `merges.txt:6` — The cited merge history supports the assessable branch-based workflow criteria.
  > `"feature/rag-ingestion"`
- `authors.txt:1` — The author summary supports the finding of consistent team identities for B6.
  > `Vikram Varikooty <varikooty@wisc.edu>`

---

## ✓ R2 — 4.0 / 4.0

6/6 tests passed

| Test | Status | Message |
|------|--------|---------|
| frontend/student/tsconfig.json type-checking strictness unchanged | ✓ passed |  |
| frontend/staff/tsconfig.json type-checking strictness unchanged | ✓ passed |  |
| frontend/admin/tsconfig.json type-checking strictness unchanged | ✓ passed |  |
| starter lint/scan jobs still present in .gitlab-ci.yml | ✓ passed |  |
| main history is merge-based (no direct pushes of work) | ✓ passed |  |
| every merge into main was approved by a teammate or staff | ✓ passed | 27 merged MR(s) checked |
| member varikooty: review duty -0 (max -2) | — skipped | no missed reviews |
| member vzhou2: review duty -0 (max -2) | — skipped | no missed reviews |

---

## ✓ R3 — 4.0 / 4.0

2/2 tests passed

| Test | Status | Message |
|------|--------|---------|
| logging verified before code work (T0) | ✓ passed | R3 is scored for each member separately; this report shows the highest member score. |
| session logs on at least 50% of the days with code commits | ✓ passed |  |
| member varikooty: R3 4/4 | — skipped | first session log 2026-10-23, first code commit 2026-10-23 (log within 24 hours after it); you committed code on 5 da... |
| member vzhou2: R3 4/4 | — skipped | first session log 2026-10-19, first code commit 2026-10-19 (log within 24 hours after it); you committed code on 5 da... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

## ✓ R4 — 8.0 / 8.0

All three audits agree that P1–P3 and D1–D5 are met, and none reports a cited shortfall. Therefore, no shortfalls count under the two-audit consensus rule, warranting L8.

**Where to look:**

- `design_evidence.txt:12` — All audits cite this as evidence that P1 is met.
  > `ALL ASSIGNED READMES PRESENT: yes`
- `design_evidence.txt:19` — All audits cite this as evidence that P2 is met.
  > `Design doc committed before implementation: yes`
- `design_evidence.txt:14` — All audits cite the substantive revision as evidence that P3 is met.
  > `REVISED after initial commit`

---

## ✓ R5 — 11.0 / 12.0

G5 is the only counted shortfall: graders 1 and 3 independently classify oversized historical Q&A pairs being split as MINOR, with citations. Grader 2 reports no shortfalls, so the consensus count is one MINOR and no MAJOR shortfalls, matching L11; the G3 cap does not apply.

**Where to look:**

- `backend/app/services/rag/chunking.py` — Graders 1 and 3 cite this behavior as evidence that oversized Q&A pairs may be split, contrary to the unsplit Q&A requirement.
  > `if count_tokens(text) <= QA_MAX_TOKENS ... else ... _window_spans(...)`
  - *Fix:* Change chunk_qa() so each question-answer pair remains a single chunk, or explicitly revise the requirement if oversized-pair splitting is intended.

---

## ✓ R6 — 11.0 / 11.0

No shortfall is reported by at least two audits with citations. Grader 1 reports one Q4 minor, but graders 2 and 3 report no shortfalls, so the Q4 issue does not count under the consensus rule.

**Where to look:**

- `grader 2` — This audit identifies no shortfalls across Q1–Q5.
  > `SHORTFALLS: none`
- `grader 3` — This independent audit also identifies no shortfalls.
  > `SHORTFALLS: none`

---

## ✓ R7 — 7.0 / 12.0

All three audits agree on one MAJOR shortfall: C4, because the required committed evaluation artifacts and reproduction comparison are missing. No other shortfalls were reported by at least two audits, and eval/configs.json is present, so the L0 condition does not apply.

**Where to look:**

- `rag_rerun_report.txt:24` — The required committed JSON evaluation report is absent, preventing reproduction of the committed results.
  > `COMMITTED eval/report.json MISSING — required deliverable absent`
  - *Fix:* Commit eval/report.json containing the completed evaluation results and use it for a fresh comparison against the deployed application.
- `eval/report.md:1` — The required committed Markdown evaluation report is also missing.
  > `[no files matched pattern 'eval/report.md']`
  - *Fix:* Add and commit eval/report.md summarizing the evaluation and fresh-versus-committed comparison.

---

## ✓ R8 — 8.0 / 8.0

All three audits agree that I1 through I6 are met, so no shortfalls count under the consensus rule. The reported unit and integration runs passed, and the integrity checks found no deleted starter tests; therefore the score is L8.

**Where to look:**

- `pytest_output.txt:73` — Confirms the unit test suite passed.
  > `UNIT VERDICT: PASSED`
- `test_integrity.txt:4` — Confirms there is no integrity shortfall from deleting starter tests.
  > `no starter test files deleted`

---

## ✓ R9 — 8.0 / 8.0

No shortfall is reported by at least two audits as a counted deficiency. The audits unanimously conclude “SHORTFALLS: none”; the K2 and K4 partial findings are explicitly characterized as evidence gaps rather than established failures.

**Where to look:**

- `theme_report.txt:5` — Supports the unanimously reported K1 result that raw palette utilities were eliminated.
  > `student: starter 93 -> now 0`
- `theme_report.txt:46` — This is an evidence gap for K2, not a confirmed shortfall according to all three audits.
  > `admin: none matched by filename — check the design doc / diff for where these landed`
- `ui_samples.txt:3` — Supports the unanimously reported screenshot-manifest coverage for K6.
  > `Screenshots committed under docs/ui: 32`

---

## ✓ R10 — 5.0 / 5.0

7/7 tests passed

| Test | Status | Message |
|------|--------|---------|
| deployed application reachable (http://34.121.90.110) | ✓ passed |  |
| course grader account can sign in to the deployed application | ✓ passed |  |
| automated deploy stage present in .gitlab-ci.yml | ✓ passed | new stage(s)/job beyond the starter's lint/test/secret-detection: {'build', 'deploy'} |
| production branch exists | ✓ passed |  |
| production history is merge-only from main (no direct pushes) | ✓ passed |  |
| deploy job gated to the production branch | ✓ passed |  |
| no committed credential material | ✓ passed |  |

---

## ✓ R11 — 6.0 / 6.0

All three audits agree that varikooty and vzhou2 have no shortfalls across W1–W5, so the strongest member's counted shortfalls are zero. Therefore, the work matches L6, which requires no counted shortfalls.

**Where to look:**

- `docs/varikooty.md:64` — The document candidly reports the incomplete evaluation rather than claiming unsupported findings; all audits still marked W4 MET.
  > `I have no measured results`
- `docs/vzhou2.md:58` — The document accurately acknowledges the missing evaluation evidence; all audits marked W4 MET and identified no shortfall.
  > `no completed harness evidence`

---

## ✓ R12 — 4.0 / 4.0

1/1 test passed

| Test | Status | Message |
|------|--------|---------|
| contribution share (team of 2, floor 30%) | ✓ passed | R12 is scored for each member separately; this report shows the highest member score. |
| member varikooty: R12 4/4 | — skipped | at or above the floor: lines 7254 (34%), files 151 (55%), commits 60, counted on main at the graded commit; share flo... |
| member vzhou2: R12 4/4 | — skipped | at or above the floor: lines 14022 (66%), files 123 (45%), commits 52, counted on main at the graded commit; share fl... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

