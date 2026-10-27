# Project 3: QnA

**Score: 68.0 / 90.0**

Graded: 2026-10-27 10:39 UTC

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

No shortfalls count because B2 is reported as a minor shortfall by only one of the three audits, while the other two audits mark it met. All other criteria have no reported shortfalls, so the work has zero counted minor or major shortfalls.

**Where to look:**

- `merges.txt:1` — This supports the presence of a branch-based workflow with substantive work merged into main.
  > `Merge branch 'fix/staff-live-api' into 'main'`

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
| every merge into main was approved by a teammate or staff | ✓ passed | 21 merged MR(s) checked |
| member varikooty: review duty -0 (max -2) | — skipped | no missed reviews |
| member vzhou2: review duty -0 (max -2) | — skipped | no missed reviews |

---

## ✓ R3 — 4.0 / 4.0

2/2 tests passed

| Test | Status | Message |
|------|--------|---------|
| logging verified before code work (T0) | ✓ passed | R3 is scored for each member separately; this report shows the highest member score. |
| session logs on at least 50% of the days with code commits | ✓ passed |  |
| member varikooty: R3 4/4 | — skipped | first session log 2026-10-23, first code commit 2026-10-23 (log within 24 hours after it); you committed code on 4 da... |
| member vzhou2: R3 4/4 | — skipped | first session log 2026-10-19, first code commit 2026-10-19 (log within 24 hours after it); you committed code on 3 da... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

## ✓ R4 — 8.0 / 8.0

All three audits report every criterion P1–P3 and D1–D5 as MET and explicitly identify no shortfalls. Therefore, no shortfalls count under the consensus rule, warranting L8.

**Where to look:**

- `report:19` — All three audits cite this evidence for P2, so the design-process ordering requirement is met.
  > `Design doc committed before implementation: yes`
- `design document:24` — The audits consistently cite this as evidence that the document is self-contained and sufficiently guides implementation for D5.
  > `authoritative spec for T4–T7`

---

## ✓ R5 — 12.0 / 12.0

No shortfall meets the required two-audit consensus rule. Grader 1 reported a minor G5 issue, but graders 2 and 3 both marked G5 MET with citations; therefore no shortfalls are counted and the result is L12.

**Where to look:**

- `backend/app/services/rag/chunking.py:567` — Grader 2 cites the type-specific Q&A chunking path as evidence that G5 is met.
  > `chunk_qa`
- `backend/app/services/rag/chunking.py:567` — Grader 3 likewise cites the Q&A chunker and states that pairs remain together unless oversized, so the lone contrary report does not establish consensus.
  > `chunk_qa`

---

## ✓ R6 — 11.0 / 11.0

All three audits report every criterion as MET and explicitly identify no shortfalls. Therefore, no shortfall is supported by the required two-audit consensus, so the work receives the highest level.

**Where to look:**

- `grader 1 audit` — The audit identifies no counted shortfalls.
  > `SHORTFALLS: none`
- `grader 2 audit` — The second independent audit also identifies no shortfalls.
  > `SHORTFALLS: none`

---

## ✓ R7 — 0.0 / 12.0

All three audits agree that C3 is a MINOR shortfall because the OFAT configuration file is missing, and two audits agree that C5 is MINOR for missing individual write-ups. All three agree that C4 is MAJOR because the committed evaluation report and reproduction results are absent; additionally, the released cap applies because neither the configuration matrix nor a committed comparison report is present.

**Where to look:**

- `rag_rerun_report.txt:8` — This supports the counted C3 shortfall and the released cap.
  > `FATAL: eval/configs.json not committed`
  - *Fix:* Commit eval/configs.json containing the baseline and five one-factor-at-a-time configurations.
- `eval/report.md:1` — The required committed evaluation report is absent, supporting the C4 MAJOR shortfall.
  > `[no files matched pattern 'eval/report.md']`
  - *Fix:* Add and commit eval/report.md with the fresh deployed-app comparison results and required Sections 3–4.
- `docs/schedule.md:46` — The two individual T6 write-ups are still listed as remaining, supporting the counted C5 shortfall.
  > `Individual documents docs/vzhou2.md and docs/varikooty.md \| T10 \| each`
  - *Fix:* Add the T6 sections to both docs/vzhou2.md and docs/varikooty.md and reconcile their claims with the committed report.
- `eval/report.json` — This supports the released L0 cap requiring a committed comparison report when configs.json is absent.
  > `The supplied material also contains no committed `report.json`.`
  - *Fix:* Commit eval/report.json containing the generated comparison results.

**Feedback:** The missing configuration and report artifacts trigger the released L0 cap; complete and commit both artifacts before resubmitting.

---

## ✓ R8 — 8.0 / 8.0

All three audits report no shortfalls, so no criterion is counted against the submission. The evidence shows extensive ingestion, answer-pipeline, and compare coverage, with the live suite completing successfully.

**Where to look:**

- `pytest_output.txt:226` — The full test suite passed without failures.
  > `SUITE VERDICT: PASSED — 234 passed, 0 failed`
- `pytest_output.txt:140` — The ingestion area includes substantive passing tests beyond basic endpoint checks.
  > `PASSED ... test_r4_markdown_upload_cites_file_and_lines`
- `pytest_output.txt:109` — The compare area includes a passing response-contract test.
  > `test_x1_matched_response_shape`

---

## ✓ R9 — 7.0 / 8.0

All three audits agree on one MINOR shortfall: the screenshot manifest lacks after-redesign staff coverage. No MAJOR shortfalls are reported, so the result is L7.

**Where to look:**

- `ui_samples.txt:8` — The manifest includes staff only in the before/unknown category and does not demonstrate after-theme staff views.
  > `includes `before/unknown/staff` but no `after/.../staff` entries`
  - *Fix:* Add committed after-redesign staff screenshots for both light and dark themes, and list both paths in `ui_samples.txt`.

**Feedback:** Complete the staff screenshot coverage so the manifest demonstrates before/after light/dark evidence for all three apps.

---

## ✓ R10 — 5.0 / 5.0

7/7 tests passed

| Test | Status | Message |
|------|--------|---------|
| deployed application reachable (http://34.121.90.110) | ✓ passed |  |
| course grader account can sign in to the deployed application | ✓ passed |  |
| automated deploy stage present in .gitlab-ci.yml | ✓ passed | new stage(s)/job beyond the starter's lint/test/secret-detection: {'deploy', 'build'} |
| production branch exists | ✓ passed |  |
| production history is merge-only from main (no direct pushes) | ✓ passed |  |
| deploy job gated to the production branch | ✓ passed |  |
| no committed credential material | ✓ passed |  |

---

## ✓ R11 — 0.0 / 6.0

For the strongest member, all three audits agree that the required individual document is missing, so the work this item assesses is essentially absent rather than merely incomplete. This satisfies the explicit lowest-level condition; both members have the same documented gap.

**Where to look:**

- `individual_docs_report.txt:6` — The required per-member document is absent, leaving its substantive sections and AI-usage account unauditable.
  > `varikooty: MISSING (`docs/varikooty.md` not found)`
  - *Fix:* Create and commit docs/varikooty.md containing every required section, a specific AI-usage account, and a direct session-log reference; repeat this for vzhou2 in docs/vzhou2.md.

**Feedback:** The weaker member has the same gap as the strongest member: neither required individual document is present. Add both documents and ensure each one independently documents the codebase, design findings, RAG comparison, and AI-session evidence.

---

## ✓ R12 — 4.0 / 4.0

1/1 test passed

| Test | Status | Message |
|------|--------|---------|
| contribution share (team of 2, floor 30%) | ✓ passed | R12 is scored for each member separately; this report shows the highest member score. |
| member varikooty: R12 4/4 | — skipped | at or above the floor: lines 6461 (32%), files 116 (49%), commits 46, counted on main at the graded commit; share flo... |
| member vzhou2: R12 4/4 | — skipped | at or above the floor: lines 13919 (68%), files 119 (51%), commits 48, counted on main at the graded commit; share fl... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

