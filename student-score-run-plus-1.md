# Project 3: QnA

**Score: 86.0 / 90.0**

Graded: 2026-10-29 13:05 UTC

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

All three audits report SHORTFALLS: none, so no criterion has a counted shortfall under the consensus rule. The audits consistently find the branch-based workflow and commit practices met; B7 is not assessable but is not a shortfall.

**Where to look:**

- `gitlog.txt:59` — Evidence of independent feature work merged into main, supporting the absence of a B1 or B3 shortfall.
  > `Merge branch 'feature/rag-pipeline' into 'main'`
- `authors.txt:1` — Consistent team-member identity, supporting the absence of a B6 shortfall.
  > `vzhou2 <vzhou2@wisc.edu>`

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
| every merge into main was approved by a teammate or staff | ✓ passed | 28 merged MR(s) checked |
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
| member vzhou2: R3 4/4 | — skipped | first session log 2026-10-19, first code commit 2026-10-19 (log within 24 hours after it); you committed code on 6 da... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

## ✓ R4 — 8.0 / 8.0

No shortfalls were reported by any of the three audits, so no criterion has a counted MAJOR or MINOR deficiency. The evidence indicates that the design document preceded implementation and covered all required design areas.

**Where to look:**

- `design_evidence.txt:19` — All three audits cite this as evidence that P2 is met.
  > `Design doc committed before implementation: yes`

---

## ✓ R5 — 12.0 / 12.0

All three audits report no shortfalls, so there are zero counted MAJOR or MINOR deficiencies. The work provides all required resource types and a shallow, runtime-configured repository ingestion path, supporting the highest level.

**Where to look:**

- `backend/app/models/rag.py` — All required resource categories are implemented.
  > `all four resource types, including `syllabus`, `schedule`, `repository`, and `historical_qa``
- `backend/app/services/rag/fetchers.py:374` — Repository ingestion uses the required shallow clone options.
  > `["clone", "--depth", "1", "--single-branch", "--no-tags"]`

---

## ✓ R6 — 11.0 / 11.0

All three audits report that every criterion is MET and explicitly identify no shortfalls. Therefore, no counted MINOR or MAJOR shortfalls remain under the consensus rule, matching L11.

**Where to look:**

- `grader 1 audit` — The audit reports no shortfalls across Q1–Q5.
  > `SHORTFALLS: none`
- `grader 2 audit` — The second independent audit also reports no shortfalls.
  > `SHORTFALLS: none`
- `grader 3 audit` — The third independent audit likewise reports no shortfalls.
  > `SHORTFALLS: none`

---

## ✓ R7 — 12.0 / 12.0

All three audits agree that C1–C5 are met and report no counted shortfalls. The evidence also confirms OFAT compliance and an unmodified evaluation harness, so no cap applies.

**Where to look:**

- `rag_rerun_report.txt:7` — Confirms the required one-factor-at-a-time evaluation structure.
  > `OFAT check: every comparison changes exactly one field from baseline — OK`
- `rag_rerun_report.txt:3` — Confirms the harness-integrity requirement was satisfied.
  > `compare_harness.py: unmodified — OK`

---

## ✓ R8 — 8.0 / 8.0

All three independent audits report every criterion I1–I6 as MET and identify no counted shortfalls. The full suite passed, and the integrity report shows no starter test files were deleted, so the evidence supports L8.

**Where to look:**

- `pytest_output.txt:225` — The complete live-stack test suite passed with no failures.
  > `SUITE VERDICT: PASSED — 233 passed, 0 failed`
- `test_integrity.txt:4` — No starter test files were deleted.
  > `none`

---

## ✓ R9 — 7.0 / 8.0

Two MINOR shortfalls are supported by at least two audits: incomplete evidence of admin coverage for the new T4–T6 surfaces (K2), and lack of evidence for visible focus states (K4). No audit identifies a MAJOR shortfall, so the count corresponds to L7.

**Where to look:**

- `theme_report.txt:46` — Two audits identify this as an evidence gap for admin’s new T4–T6 themed surfaces.
  > `admin: none matched by filename — check the design doc / diff for where these landed`
  - *Fix:* Document or add screenshots showing the admin T4–T6 surfaces in both light and dark themes.
- `grader 1` — All three audits report K4 as only partly met because focus-state visibility is not established.
  > `the supplied screenshots and report do not establish that focus states are visibly present`
  - *Fix:* Add screenshots or interaction evidence showing visible keyboard focus states for interactive controls in both themes.

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

## ✓ R11 — 6.0 / 6.0

No shortfall is reported by at least two audits for any criterion. All three audits independently state that both members meet W1–W5, so the strongest member's work has zero counted MAJOR or MINOR shortfalls and qualifies for L6.

**Where to look:**

- `grader 1` — The audit reports no criterion-level shortfalls.
  > `SHORTFALLS: none`
- `grader 3` — The audit confirms that both members satisfy every audited criterion.
  > `The strongest work is effectively tied: both satisfy all five criteria.`

---

## ✓ R12 — 4.0 / 4.0

1/1 test passed

| Test | Status | Message |
|------|--------|---------|
| contribution share (team of 2, floor 30%) | ✓ passed | R12 is scored for each member separately; this report shows the highest member score. |
| member varikooty: R12 4/4 | — skipped | at or above the floor: lines 7254 (27%), files 151 (52%), commits 61, counted on main at the graded commit; share flo... |
| member vzhou2: R12 4/4 | — skipped | at or above the floor: lines 19196 (73%), files 138 (48%), commits 57, counted on main at the graded commit; share fl... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

