# Project 3: QnA

**Score: 62.0 / 90.0**

Graded: 2026-10-26 14:58 UTC

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

## ✓ R1 — 4.0 / 5.0

The only counted shortfall is B6, MINOR: all three audits agree that one member appears under two author names while using the same email address, citing authors.txt lines 1–3. Thus there is one MINOR shortfall and no MAJOR shortfalls, matching L4.

**Where to look:**

- `authors.txt:1` — This identity differs from the same member's alternate author name cited on line 3, creating the agreed B6 inconsistency.
  > `vzhou2 <vzhou2@wisc.edu>`
  - *Fix:* Configure a consistent Git author name for this email address and rewrite or document the inconsistent historical identity if permitted.

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
| every merge into main was approved by a teammate or staff | ✓ passed | 20 merged MR(s) checked |
| member varikooty: review duty -0 (max -2) | — skipped | no missed reviews |
| member vzhou2: review duty -0 (max -2) | — skipped | no missed reviews |

---

## ✓ R3 — 4.0 / 4.0

2/2 tests passed

| Test | Status | Message |
|------|--------|---------|
| logging verified before code work (T0) | ✓ passed | R3 is scored for each member separately; this report shows the highest member score. |
| session logs on at least 50% of the days with code commits | ✓ passed |  |
| member varikooty: R3 4/4 | — skipped | first session log 2026-10-23, first code commit 2026-10-23 (log within 24 hours after it); you committed code on 2 da... |
| member vzhou2: R3 4/4 | — skipped | first session log 2026-10-19, first code commit 2026-10-19 (log within 24 hours after it); you committed code on 3 da... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

## ✓ R4 — 8.0 / 8.0

No shortfalls are reported by any of the three audits, so no counted MAJOR or MINOR shortfalls exist. All criteria P1–P3 and D1–D5 are marked MET with citations, and the P2 cap does not apply.

**Where to look:**

- `report:19` — All three audits agree that P2 is met; therefore the released-requirements cap is not triggered.
  > `Design doc committed before implementation: yes`
- `design document:118` — This is cited evidence that the design document addresses the citation data model required by D1.
  > `The full citation URL is computed at ingestion and stored as chunk metadata `source_url``

---

## ✓ R5 — 11.0 / 12.0

All three audits agree on exactly one counted shortfall: G4 is MINOR because re-sync is absent despite separate profile collections. No MAJOR shortfalls are reported, so the scoring rules select L11.

**Where to look:**

- `ingestion_evidence.txt:29` — All three audits cite this as the single agreed G4 MINOR shortfall.
  > `Re-sync mechanism: NOT FOUND`
  - *Fix:* Implement and document a re-sync endpoint or job that refreshes the relevant ingestion profile collection when a resource changes.

---

## ✓ R6 — 11.0 / 11.0

All three independent audits report every criterion as MET and explicitly identify no shortfalls. Therefore, no shortfall is supported by the required two-audit consensus, so the work receives the highest level.

**Where to look:**

- `grader 1` — The audit reports no counted shortfalls across any criterion.
  > `SHORTFALLS: none`
- `grader 2` — An independent audit likewise finds no shortfalls.
  > `SHORTFALLS: none`

---

## ✗ R7 — 0.0 / 12.0

⚠️ This item could not be graded.

```
evidence path not found: student/eval/report.md
```

---

## ✓ R8 — 3.0 / 8.0

I6 is a counted MAJOR shortfall because all three audits cite the same failing live-stack test and incomplete suite. This would ordinarily correspond to L5, but the released requirement caps any score when I6 counts at at most L4; since L4 is not an available level, L3 is the highest applicable level.

**Where to look:**

- `pytest_output.txt:220` — The live integration suite contains a failing test, so I6 is a major shortfall.
  > `test_b12_decline_posts_nothing`
  - *Fix:* Fix the decline-path behavior or its test fixture, then rerun the complete live Docker-stack suite.
- `pytest_output.txt:221` — The complete live-stack suite does not pass.
  > `1 failed, 234 passed, 6 skipped`
  - *Fix:* Investigate the failure and verify a clean full-suite result with zero failures.

**Feedback:** Resolve the failing decline-posts-nothing case and rerun the entire test suite against the live stack.

---

## ✓ R9 — 8.0 / 8.0

No shortfall is reported by at least two audits with a citation, so no shortfalls count under the consensus rule. The audits consistently support a complete tokenized theme implementation and functioning theme controls; the K6 missing-staff-screenshots issue appears in only one audit and is therefore ignored.

**Where to look:**

- `report:3` — Supports the consistently reported removal of raw palette utilities as part of the theme-system implementation.
  > `student: starter 93 -> now 0`
- `report:20` — Supports the reported presence of theme toggles across all applications.
  > `THEME TOGGLE: PRESENT (all 3 apps)`

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

## ✓ R11 — 0.0 / 6.0

All three audits agree that both members' required individual documents are missing, so the work being assessed is essentially absent rather than merely incomplete. This satisfies the lowest-level condition; the strongest member has no substantive auditable document, and the reported W1/W5 major shortfalls reinforce that conclusion.

**Where to look:**

- `individual_docs_report.txt:6` — The required individual document for varikooty is absent, leaving the assessed sections undocumented.
  > `varikooty: MISSING (docs/varikooty.md not found)`
  - *Fix:* Create and commit docs/varikooty.md with all required sections, including the codebase discussion, design reflection, RAG comparison, and AI-usage account.
- `individual_docs_report.txt:7` — The required individual document for vzhou2 is also absent; neither member provides a stronger compliant submission.
  > `vzhou2: MISSING (docs/vzhou2.md not found)`
  - *Fix:* Create and commit docs/vzhou2.md with all required sections and an explicit reference to the relevant AI session log.

**Feedback:** Both members have the same fundamental gap: their required individual documents are missing. Adding the repository-required documents with complete, specific evidence-based sections is necessary before the work can earn a higher level.

---

## ✓ R12 — 4.0 / 4.0

1/1 test passed

| Test | Status | Message |
|------|--------|---------|
| contribution share (team of 2, floor 30%) | ✓ passed | R11 is scored for each member separately; this report shows the highest member score. |
| member varikooty: R11 4/4 | — skipped | at or above the floor: lines 6281 (31%), files 110 (48%), commits 40, counted on main at the graded commit; share flo... |
| member vzhou2: R11 4/4 | — skipped | at or above the floor: lines 13919 (69%), files 119 (52%), commits 47, counted on main at the graded commit; share fl... |
| roster source | — skipped | enrolled team from automation ($SELECTED_TEAM_KEY): varikooty, vzhou2 |

---

