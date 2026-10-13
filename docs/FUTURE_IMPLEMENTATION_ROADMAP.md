# Naukri Agent — Future Implementation Roadmap

> Planning document only. Nothing in this roadmap changes current runtime behavior,
> authorizes automation, or represents future work as implemented.

**Updated:** 2026-10-13 (documentation pass after E5-R20; HEAD = `c2868d0`).
This file is the stand-in for the requested `docs/FUTURE_IMPLEMENTATION.md`,
which does not exist in this repository.

## 1. Roadmap principles

1. Implement one checkpoint at a time and validate it before beginning the next.
2. Never combine unrelated future features in one checkpoint.
3. Live automation must always have explicit, testable safety boundaries.
4. Deterministic Python rules remain authoritative; Gemini provides bounded reasoning
   and evaluation support, never final authority.
5. Candidate facts must come from the structured candidate profile or an explicit,
   approved user answer. The agent must never fabricate candidate information.
6. Unknown or consequential questions require user involvement.
7. Future work remains Naukri-only unless the PRD explicitly changes that scope.
8. CAPTCHA and security controls must never be bypassed, and external applications
   must never be submitted.
9. No uncontrolled background execution is permitted.
10. Runs are bounded by eligibility, not by counters: E5-R10 removed hourly/daily
    application quotas and `max_applications` is display-only, so a run processes all
    eligible matching jobs until the eligible queue is exhausted (this replaces the
    earlier formulation "`max_applications` means successful native applications").
11. Jobs discovered, jobs filtered, AI evaluations, applications, and attention
    items remain separate metrics.

## 2. Current baseline (verified 2026-10-13)

The project provides a local-first architecture with a FastAPI backend,
React/TypeScript/Tailwind dashboard, and SQLite/SQLAlchemy persistence. Implemented
capabilities include Naukri discovery (multi-location, live-verified pagination,
freshness-first, targeted search groups — E5-R8/R19), deterministic hard filtering
with a shared irrelevant-role gate (E5-R17), interest-tier prioritization with hard
role exclusions (E5-R10/R10B), native-first application-mode ranking (E5-R9), bounded
Gemini evaluation (advisory only), legacy and conversational native application with
bounded steps (E5-R7/R14/R20), pointer-honest clicks and ambiguous-submission
reconciliation (E5-R20), duplicate protection, protected-job invariants
(81/87/114/120), a DB-backed single-run lock with dashboard Stop (E5-R15), a
login-aware application gate with `LOGIN_REQUIRED` (E5-R16), read-only Naukri history
reconciliation (E5-R16/R20), and dashboard drill-downs.

**E4 (first dashboard-controlled live cycle) is complete.** Run #52 (2026-10-09)
exercised Dashboard → AutonomousCycle → Naukri end-to-end with `max_applications = 1`,
returning to `IDLE` with `lock_held = false`. The E4-R2 Windows requirement stands as
recorded: live runs must use non-reload Uvicorn (Playwright subprocess compatibility).
The application-submission objective that Run #52 left unresolved was subsequently
met by later checkpoints (D5/D7 single and multi native applications; E5-R7 surgical
live validation of job 114).

**E5 status: substantial but not finished.** Checkpoints E5-R1 through E5-R20 are
implemented and documented in `docs/DEVELOPMENT_STATUS.md`. Offline suite:
**1092 passed / 0 failed** at `c2868d0` (verified 2026-10-12). Live-verified since
E5-R7: single-job surgical apply (job 114, row 82) and history-confirmed application
(job 462, row 148 via reconciliation after attempt #147).

**Known limitations / open items:**

- **Multi-job application execution is UNVERIFIED.** No single run has completed
  multiple native applications since E5-R7. This is the top roadmap priority.
- 13 `NEEDS_ATTENTION` application rows remain for human review (incl. #146 job 105
  and #147 job 462 — remote status uncertain; #148 is the history-confirmed
  companion row of 462). No bulk resolution mechanism exists by design.
- Data anomaly: discovery run 74 (2026-10-11) still shows `status=RUNNING` with
  `completed_at=NULL` while later runs completed — a stale control row, not an
  active run.
- E5-R18 exists only as an operational record (discovery run 78, no code, no
  commit); E5-R11 has no recorded evidence anywhere (assumed unused sequence number).

## 3. E5 remainder — Multi-Application Dashboard Cycle (priority order)

E5's original purpose (Section 4 below) is partially delivered: the dashboard can
initiate, monitor and stop cycles, and the safety gates hold — but end-to-end
multi-job execution has not been demonstrated since the E5-R7 code changes. Remaining
work, in priority order:

1. **Multi-job application execution.** Verify one dashboard-initiated run that
   discovers → hard-filters → evaluates → attempts → truthfully verifies **at least
   two** native applications in a single cycle. Acceptance criteria are recorded in
   `docs/MASTER_PRD.md` ("Multi-job acceptance criteria", as of E5-R20). Status:
   NOT MET.
2. **Historical application reconciliation.** Implemented (E5-R16 endpoint, E5-R20
   attempt-level reconciliation; live read-only run reconciled 117 → 145 rows
   additively). Remaining: make it a routine, documented workflow (when to trigger,
   how results surface in the dashboard) — no new mechanism required.
3. **Dashboard stop/cancel.** Delivered (E5-R15: DB-backed lock, idempotent Stop,
   `CANCELLED` reporting, `CANCELLING` UI state). Remaining: live multi-job run to
   observe Stop under sustained load.
4. **Needs-attention causes and resolution.** Partially delivered: E5-R20 reconciles
   ambiguous submissions against Naukri history before `NEEDS_ATTENTION`, and
   confirmed jobs are excluded from the attention queue. Remaining: triage the 13
   open rows (per-row cause: occluded click, screening question, uncertain remote
   status) and document a human resolution path — one row at a time, never bulk
   status wipes.
5. **Login and native-only discovery state.** Partially delivered: `LOGIN_REQUIRED`
   terminates a cycle cleanly (E5-R16, test-verified) and `application_mode`
   prioritizes native-only candidates (E5-R9). Remaining: a full live cycle started
   deliberately in a logged-out state, and login-recovery guidance in the dashboard.

Guardrails for any E5-remainder work: no new quota system, no relaxation of
duplicate/protected-job/evidence rules, no external submissions, no CAPTCHA
interaction, and no claim of multi-job success without a verified run.

## 4. E5 (original brief, retained for record)

### Purpose

Validate that a dashboard-initiated run can continue through multiple eligible jobs
instead of stopping after its first successful application.

### Desired behavior

The user can configure `max_applications` as 1, 2, 3, 5, 10, and other values within
a safe server-side maximum. A run should discover jobs, hard filter them, evaluate
candidates, apply only to eligible native jobs, verify each result, continue to the
next eligible job, and stop when the successful native-application count reaches the
configured limit.

`max_applications` is the maximum number of successful native applications. It is
not a limit on discovered jobs, inspected jobs, Gemini evaluations, or candidates.

> **Superseded by E5-R10 (2026-10-11):** application quotas and the `max_applications`
> budget slice were removed; runs now process all eligible matching jobs until the
> eligible queue is exhausted, and `max_applications` is display-only. The original
> text is retained above for history (see also PRD §29 status note).

The existing D6/D7 work demonstrated multi-application behavior. E5 should expose
and validate that existing capability through the Dashboard while preserving all
application, duplicate, and evidence safety gates.

## 5. E6 — Candidate Profile & Question Answer Engine

### Purpose

Replace the current questionnaire boundary with a safe candidate-answer system.

```text
Resume / Profile JSON
        |
Structured Candidate Profile
        |
Question Answer Engine
        |
  1. Known profile fact
  2. Previously approved answer
  3. Deterministic answer derived from profile
  4. Unknown -> ask user
```

Candidate Profile JSON becomes the authoritative source for factual application
answers. Examples include graduation year, degree, specialization, college,
education, experience, skills, certifications, languages, projects, configured
availability, configured location, and other explicitly stored candidate facts.

Gemini must not repeatedly infer facts that are already structured profile data.

## 6. Question categories

### Category A — Automatically answerable profile facts

These answers are directly supported by Candidate Profile and should be retrieved
deterministically, without Gemini.

| Question | Authoritative source |
| --- | --- |
| What is your graduation year? | `profile.education.graduation_year` |
| What is your branch? | `profile.education.specialization` |
| What is your highest qualification? | `profile.education.degree` |

### Category B — Previously approved candidate answers

These are answers the user explicitly gave and approved for reuse. For example, an
approved answer to "Are you willing to relocate?" may be reused for a truly
equivalent question such as "Would you be willing to move to another city?" The
first answer must always be user-approved.

### Category C — Unknown, subjective, or consequential questions

Examples include motivation statements, salary expectations, bonds, legal/work
authorization declarations, night-shift acceptance, facts absent from the profile,
and other subjective or consequential questions. They must never be fabricated by
Gemini. They create `NEEDS_ATTENTION` and request user input. A user-approved answer
may later be stored for safe reuse.

## 7. E7 — Persistent Candidate Answer Memory

### Purpose

Persist approved user answers to recurring application questions. The conceptual name
is **Candidate Answer Memory**, not "AI Memory."

### Proposed future table

`application_question_answers` may include:

- `id`
- `original_question`
- `normalized_question`
- `answer`
- `answer_type`
- `source`
- `approval_status`
- `created_at`
- `updated_at`
- `superseded_at`
- `version`

Possible answer types: `profile_fact`, `user_preference`, `user_approved`,
`deterministic_generated`, and `unknown`.

Possible sources: `candidate_profile`, `user_approved`, and `system_generated`.

This is a proposal only; E7 must introduce and validate the schema separately.

## 8. Answer versioning

Candidate Answer Memory must support changes without ambiguity. If a candidate's
answer to relocation willingness changes from "Yes" to "No," the prior answer becomes
superseded and the new answer is the sole active/current answer. Historical versions
remain available for audit but must not compete as active answers.

## 9. Question normalization and semantic matching

Future work must distinguish exact matching from semantic-equivalent matching. A
potential normalized representation for relocation questions is
`relocation_willingness`, but equivalence must never be assumed blindly. Questions
with materially different implications remain separate. Gemini may assist with
semantic interpretation only inside a safety boundary for consequential questions.

## 10. Source-of-truth hierarchy

```text
Candidate Profile JSON
        |
Deterministic candidate facts
        |
Approved Candidate Answer Memory
        |
User-provided answer
        |
Gemini interpretation where appropriate
        |
Never fabricate
```

Gemini must not override authoritative candidate data.

## 11. Question answer flow

```text
Naukri question
      |
Extract question
      |
Normalize / classify
      |
Profile fact? ---------------- yes --> deterministic answer
      |
      no
      |
Approved answer memory? ------ yes --> reuse approved answer
      |
      no
      |
Safely derivable from profile? - yes --> deterministic answer
      |
      no
      |
Unknown / consequential
      |
NEEDS_ATTENTION -> ask user -> optional explicit approval to remember
      |
Store Candidate Answer Memory -> reuse only for future equivalent questions
```

## Sequencing guardrail

E4 is complete (Run #52, 2026-10-09). E5 is in progress — see Section 3 for the
priority-ordered remainder, led by verified multi-job application execution. E6 and
E7 are future implementation checkpoints; neither is authorized by this roadmap.
Each requires its own design review, implementation, automated tests, and explicit
safety validation. Live automation steps (any run that applies to jobs) always
require explicit human approval regardless of roadmap position.
