# Development Status

## CHECKPOINT C: Autonomous Cycle Command: COMPLETE — OFFLINE VALIDATED

Implemented `run_autonomous_cycle.py` command-line interface for running the complete autonomous job application cycle with explicit controls:
- `--max-applications N`: Limit on real applications (default: 1)
- `--dry-run`: Discovery and analysis only, no Apply clicks or application records
- `--max-jobs N`: Cap on jobs inspected per run (default: unlimited)

The command calls existing services in sequence: DiscoveryService → MatchEngine → AIQueueService → ApplicationRunner. It excludes S&P job `300926927428`, skips external jobs, re-classifies native/external before click, requires post-click Applied evidence, and stops on AUTH/SECURITY/limits/errors. Output includes per-job decision table and summary. No input() prompts. Exit code 0 on normal completion, non-zero on stops.

Test coverage: 12 focused tests in `backend/tests/test_autonomous_cycle.py` covering eligible native jobs, external jobs, unpaid jobs, excluded jobs, max-applications limit, and dry-run flag. All tests use isolated temporary SQLite database. No live Naukri activity, Gemini calls, or Apply clicks in tests.

Examples:
```powershell
# Dry-run (discovery and analysis only)
python run_autonomous_cycle.py --dry-run --max-jobs 10

# First live run with 1 application
python run_autonomous_cycle.py --max-applications 1 --max-jobs 10
```

Note: This command builds and tests offline only. Do not run it live yourself; no Apply clicks, no Gemini calls, no weakening of filters/limits/duplicate rules/safety gate. Never apply to EXTERNAL jobs.

## Checkpoint B2: Salary Gate Without Description: COMPLETE — OFFLINE VALIDATED

The full-suite failure from Checkpoint B was traced to a real code defect
introduced with the Checkpoint A3 salary test: `MatchEngine.evaluate_job()`
nested structured salary and employment-type gates under `if job.description`.
An explicitly unpaid job with no description therefore bypassed the salary gate
and incorrectly reached the AI path. The gates now evaluate independently of
description text, so disclosed unpaid and below-minimum salary records remain
deterministically rejected, and employment-type restrictions are not weakened.

Historical worktree validation found the test absent at `0468ff5` and
`5f8d0bd`, then failing at its introduction in `e0994fe` and still failing at
`40635cb`. The focused regression now passes. Full backend suite: **645 passed,
0 failed** (three third-party deprecation warnings). No live Naukri, Gemini,
Apply/Submit, external-application, or production-database action occurred.

## Checkpoint B: Apply Button Scoping: COMPLETE — OFFLINE VALIDATED

`NaukriAdapter` now resolves Naukri's duplicated `apply-button` controls through
`#job_header button#apply-button` first. A visible global `button#apply-button`
is selected only when the header control is absent; the adapter logs whether the
header or fallback was used. Native classification and the click path share this
resolver, so neither can hit Playwright strict-mode ambiguity or click the sticky
header while a job-header control exists. No control returns `AMBIGUOUS` during
classification and `NEEDS_ATTENTION` if a previously classified page no longer
has a scoped clickable control.

Already-applied evidence is evaluated in `#job_header` first. Existing visible
form/banner evidence outside the header remains valid after a click. The fixture
is minimal synthetic HTML only; it contains no logged-in session data, profile
details, names, photo URLs, or notification counts.

Offline validation:

- Focused adapter suite: 103 passed.
- Full backend suite: 644 passed, 1 failed, 645 total. The unrelated failure is
  `backend/tests/test_checkpoint_a3_salary.py::TestEndToEndSalary::test_unpaid_skip`,
  in `MatchEngine.evaluate_job` after its salary branch is skipped for an empty
  description and a `MagicMock` is passed to Pydantic. Checkpoint B changes only
  the Naukri adapter and its tests.

No browser session, Naukri action, Apply/Submit click, Gemini call, external
application action, or production-database write occurred. The required backup
is `data/naukri_agent.db.bak-before-checkpoint-b` and is intentionally untracked.

## Phase 10 Application-Type Reliability Fix: COMPLETE — LIVE READ-ONLY VALIDATED

Implemented a bounded reliability fix for state/timing-dependent Naukri application classification:

- Existing visible external-first behavior is preserved.
- Existing visible native selectors remain authoritative.
- An inconclusive state receives one bounded 500 ms settling observation.
- No reloads or indefinite polling are used.
- Persistent absence of both evidence types returns `AMBIGUOUS`.
- `ApplicationRunner` maps `AMBIGUOUS` to `NEEDS_ATTENTION` before creating an application record.

Offline validation:

- Focused classification tests: 14 passed.
- Full Naukri adapter suite: 96 passed.

Live read-only validation:

- Quadrasystems.net (`240926500723`): initial `AMBIGUOUS`, settled `AMBIGUOUS`, final `AMBIGUOUS`; selector nodes existed but were not visible, and no external indicator was visible.
- Omozing (`150526504514`): initial `AMBIGUOUS`, settled `AMBIGUOUS`; no visible native or external evidence.
- Cisco (`120826500949`): initial `EXTERNAL`, settled `EXTERNAL`; visible `Apply on company site`.
- No CAPTCHA, security challenge, login challenge, or access block appeared.
- No Apply/Submit action, Gemini call, application runner invocation, or database write occurred.

Database remained unchanged at 10 applications, 0 APPLIED, and 0 SUBMITTED. Automated successful application count remains **0**. Real submission and confirmation validation remain outstanding.

## Phase 10 Live Native Application Test: BLOCKED — NO SAFE ELIGIBLE NATIVE CANDIDATE

**Observed on 2026-10-01:** The existing persistent Playwright session opened authenticated Naukri successfully. No CAPTCHA, security challenge, login wall, or access block was observed. The local backend readiness endpoint returned `ready`. The confirmed profile, configured preferences, compatible application schema, and unused hourly/daily limits were verified.

A single bounded discovery pass inspected five `Data Analyst` results read-only:

- RR Groups: `EXTERNAL`; duplicate/application history blocked it.
- Digital Glyde: `EXTERNAL`; duplicate/application history blocked it.
- Foundation Ai: `EXTERNAL`; duplicate/application history blocked it.
- Ivy Knowledge Services: `EXTERNAL`; employment type failed.
- Thyrocare: `NAUKRI_NATIVE` on two checks; duplicate/application history blocked it.

No Apply or Submit action occurred. No Gemini request was made because no candidate passed the deterministic eligibility boundary. The application runner was not invoked. Database verification after the attempt showed 10 application records, 0 APPLIED/SUBMITTED records, and no changed confirmation evidence. Automated successful application count remains **0**.

**Remaining Phase 10 work:** Repeat the controlled checkpoint only when a fresh candidate passes duplicate protection, native classification, all hard filters, Gemini recommendation, final safety gate, and confirmation requirements. Do not retry the candidates rejected in this checkpoint without the repository-required manual reset.

## Phase 10 Database Schema Migration: COMPLETE

**Status:** Local SQLite database migrated and verified. All code changes implemented, tested, and deployed to local database.

**Implementation:**
- Root cause: `confirmation_evidence` column in ORM model but missing from `initialize_database()` function
- Solution: Idempotent ALTER TABLE with column existence checks (extends Phase 9B-4 pattern)
- Files changed: `backend/database/database.py`, `backend/api/routes/health.py`
- New test file: `backend/tests/test_schema_migration.py` (7 tests, all passing)

**Migration Execution:**
- Timing: Automatic during FastAPI lifespan initialization (before request handling)
- Idempotency: Safe to run multiple times; existing columns are skipped
- Data preservation: All existing application records preserved
- SQL compatibility: Works on both SQLite and PostgreSQL

**Local Database Results:**
- Database: data/naukri_agent.db
- Backup created: data/naukri_agent.db.bak-before-migration (240K)
- Applications table: 10 records (unchanged)
- Record 10 status: APPLICATION_STARTED (unchanged)
- APPLIED/SUBMITTED: 0/0 (unchanged)
- New columns: confirmation_evidence (TEXT NULL), is_dry_run (BOOLEAN)
- ORM queries: Executing without OperationalError

**Testing:**
- Migration-focused tests: 7/7 passing
- Full backend suite: 557/557 passing
- Test coverage:
  - Old schema migration adds confirmation_evidence ✓
  - Migration preserves existing rows ✓
  - Migration is idempotent ✓
  - Readiness check detects schema compatibility ✓
  - Current schema requires no changes ✓
  - Database isolation (never uses production DB) ✓

**Startup Verification:**
- `initialize_database()` runs before request handling ✓
- Schema compatibility check integrated into `/readiness` endpoint ✓
- Readiness status: compatible ✓
- Standalone migration command: `python -m backend.database.database` ✓

**PostgreSQL/Neon Support:**
- SQL syntax validated for PostgreSQL compatibility ✓
- Standard SQL used (ALTER TABLE, ADD COLUMN, BOOLEAN, TEXT, DEFAULT, NULL) ✓
- Neon migration: NOT executed (manual step when deploying to Neon)
- Neon command provided in docs for future deployment

**Documentation Updated:**
- README.md: Added Phase 10 schema migration section
- docs/MASTER_PRD.md: Added detailed schema migration mechanism
- docs/ARCHITECTURE.md: Added Phase 10 schema migration pattern and validation
- docs/DEVELOPMENT_STATUS.md: This status section

**Remaining Tasks:**
- Neon migration: Will be executed separately when deploying to production Neon PostgreSQL
- No code or git changes remain; all implementation complete

---

## Phase 10 Application Boundary Fix: EVIDENCE-DRIVEN POST-CLICK DETECTION

Implemented evidence-driven post-click state detection with bounded waits. After the Apply click,
the adapter waits for explicit visible evidence:
- **Applied**: `#already-applied`, `.already-applied`, exact visible "Applied" text, or
  `Applied to "<title>"` banner
- **Form opened**: visible application container (dialog, drawer, modal, or form)
- **Neither within 8s timeout**: NEEDS_ATTENTION (no retry without manual reset)

Question detection now strictly scopes to visible application containers and rejects:
- Hidden, disabled, readonly fields
- Zero-sized elements
- Hidden-type inputs
- Header/search input patterns

Experience computation uses `compute_profile_experience_years()` consistently in safety gate
and runner, computing actual elapsed years from `start_date`/`end_date` (not entry count).
The +2 year tolerance is preserved and reported in reasons.

Native/external classification moved BEFORE creating APPLICATION_STARTED. Re-classification
happens immediately before the click; mismatch aborts to external without creating a record.

No-repeat enforcement: jobs with EXTERNAL_APPLICATION or NEEDS_ATTENTION status require
explicit manual reset before automatic retry.

All changes validated with isolated temporary SQLite unit tests only. No live Naukri activity,
no Apply/Submit clicks, no Gemini calls. Production DB untouched. Successful application count: 0.

Implemented and regression-tested the focused application-boundary changes:
explicit Applied-state detection and evidence persistence, visible application
container question scoping, hidden-input rejection, computed profile experience
in the runner and final safety gate, pre-record native/external classification with
immediate reclassification, and no-repeat behavior for unresolved attempts. The
existing two-year experience tolerance remains unchanged. Tests use isolated
temporary SQLite only. No live Naukri activity, Gemini call, Apply/Submit click, or
database write occurred in this checkpoint; automated successful application count
remains 0.

## Roadmap Reconciliation

`docs/MASTER_PRD.md` is the authoritative product roadmap. Its next formal product phase after the current Phase 9B checkpoint work is **Phase 9 — Notifications**, followed by Phase 10 testing/security/Windows packaging and Phase 11 integration/production hardening. The README phase list now follows that numbering. The custom Phase 9B-3 native application-boundary validation remains unresolved and is not marked complete; Phase 9B-4 safety hardening remains implemented and committed. Cloud deployment preparation remains supporting infrastructure rather than a separately numbered product phase.

## Phase 9B-4 — Application Dry-Run and Lifecycle Safety: IMPLEMENTED OFFLINE

The dry-run boundary is hardened to stop before native Apply, external Apply, question answering, submission, and confirmation. Dry-run application records now include an explicit `is_dry_run` marker and remain eligible for future real attempts because duplicate protection still blocks only APPLIED and SUBMITTED. Lifecycle data includes PRE_APPLY and FORM_OPENED distinctions; the adapter does not claim FORM_OPENED from a click alone and reports NEEDS_ATTENTION when the form is unverified. Focused offline tests passed (118 tests across application, duplicate-protection, and adapter suites). No browser, Naukri, Gemini, ApplicationRunner live run, Apply click, or database manual write occurred. Native Apply semantics remain UNKNOWN and Phase 9B-3 is incomplete.

## Phase 9 — Notifications: IMPLEMENTED OFFLINE

Implemented the isolated notification service, persisted history model, SMTP configuration boundary, required event helpers, scheduler evening summary, `GET /api/notifications`, and minimal dashboard visibility. Focused tests cover event dispatch, missing configuration, delivery failure isolation, summary timing, and duplicate prevention. Real SMTP delivery remains unverified; Phase 9 is not marked production-complete.

## Gemini V1 Model Switch: IMPLEMENTED, LIVE NATIVE RECHECK PENDING

The V1 Gemini default changed from `gemini-2.5-flash` to verified non-preview model `gemini-flash-lite-latest` after repeated `429 RESOURCE_EXHAUSTED` responses. An isolated runtime request successfully parsed the existing structured `JobAnalysis` schema. `gemini-3.1-flash-lite-preview` also succeeded during viability testing but was not selected for V1. The model remains configurable through `NAUKRI_AGENT_GEMINI_MODEL`; retry logic, prompts, schema, provider abstraction, Naukri behavior, and application safety are unchanged. Phase 9B-3 remains incomplete until a fresh Gemini APPLY decision reaches the real native application form boundary.

## Phase 9B-3 Production JD Extraction Fix: IMPLEMENTED, LIVE RECHECK PENDING

Updated only `NaukriAdapter.fetch_job_description()` to use visible rendered DOM selectors in this order:

1. `[class*="dang-inner-html"]`
2. `section[class*="job-desc-container"]`

The existing security check remains in place. The first visible matching element is used, its text is stripped, and an empty string is returned when neither current selector is available. Focused tests cover the live hashed inner class pattern, container fallback, precedence, hidden inner element fallback, and no matching selectors. No Gemini call, Apply click, ApplicationRunner invocation, or submission occurred. Phase 9B-3 remains incomplete pending a live native APPLY boundary run.

## Phase 9B-3 Live JD Extraction Diagnostic: BLOCKER IDENTIFIED

Read-only visible-browser diagnostics inspected two persisted native jobs without invoking Gemini, ApplicationRunner, `start_application()`, or any Apply control:

- First American: HTTP 200, page title `Data Analyst - Bengaluru - First American - 1 to 3 years of experience`, visible body length 7,264.
- ReactZ Consulting: HTTP 200, page title `Software Engineer Fresher - Bengaluru - Reactz Consulting - 0 to 1 years of experience`, visible body length 4,486.

Both pages contained visible job-description text, but the current selectors `.job-desc` and exact `.styles_JDC__` matched zero elements. Observed rendered structures included `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`. No iframe was present. The likely production defect is selector matching against hashed class names with runtime suffixes. No production selector was changed. Gemini is intentionally deferred because quota is exhausted. No application was submitted; Phase 9B-3 remains incomplete.

## Phase 9B-3 Diagnostic JD Fetch: IMPLEMENTED, LIVE RECHECK PENDING

`diagnose_live_dry_run.py` now calls the existing `NaukriAdapter.fetch_job_description()` for selected real jobs, assigns the result to `Job.description`, commits it, and uses that value in the Gemini context. It inspects bounded candidates before choosing, excludes external jobs from native validation, reuses persisted analyses, stops on quota exhaustion, reports description status/length, and emits ASCII-safe output. Focused offline regression tests cover fetching, selection, and avoiding unnecessary refetches. No live Naukri search or Gemini request was run in this checkpoint, no application was submitted, and Phase 9B-3 remains incomplete.

## Test Database Isolation Checkpoint: COMPLETE

## Phase 9B-3 Native Application Detection Fix: IMPLEMENTED, LIVE RECHECK PENDING

Live candidate inspection found a real Naukri-native First American Data Analyst page:

- URL: `https://www.naukri.com/job-listings-data-analyst-first-american-bengaluru-1-to-3-years-230926038405`
- Stable control: `button#apply-button` / `button.apply-button`
- Visible text: `Apply`
- External control: absent
- Security check: passed

The adapter previously missed the current native selectors and returned `EXTERNAL`. Implemented the targeted fix in `backend/services/naukri/adapter.py`:

- `detect_application_type()` checks rendered external indicators first.
- Native detection recognizes `#apply-button`, `button.apply-button`, existing selectors, and visible exact-text `Apply` buttons.
- `start_application()` recognizes the same stable current native selectors.
- Hashed CSS classes are not used.

Focused regression coverage verifies both native selectors, visible exact-text `Apply`, external application text, no-control fallback, and native start-button compatibility. Focused result: 84 adapter tests passed. Full backend result: 519 tests passed with 3 dependency deprecation warnings. The full live native dry-run remains pending. No application was submitted and no live run was performed in this implementation checkpoint.

## Test Database Isolation Checkpoint: COMPLETE

Fixed a serious test-environment persistence defect. The shared fixture previously imported the application's production `engine` and executed `Base.metadata.drop_all()` against `data/naukri_agent.db`, allowing tests to delete runtime profile and resume data.

Implemented:
- Added a session-scoped temporary file-backed SQLite test engine.
- Redirected application and directly imported service session factories to the isolated test engine during tests.
- Limited `drop_all()` and `create_all()` in the shared fixture to the disposable test engine.
- Added regression tests proving the test engine path differs from production and test schema resets preserve production row counts.

Verification:
- Production database: `C:\Users\ajays\Desktop\Naukri Agent\data\naukri_agent.db`
- Test database: disposable temporary SQLite file under the system temp directory
- Focused isolation regression tests: 3 passed
- Full backend suite: 512 passed
- Production database remained present with its existing profile/resume rows after the full suite.

No application behavior, profile business logic, Naukri automation, Gemini, scheduler, worker coordination, or matching logic was changed.

## Phase 9B-3 False-Positive Fix Checkpoint: IMPLEMENTED, LIVE RECHECK PENDING

During a real visible-browser dry-run, the selected RR Groups job page was a normal HTTP 200 Naukri page with no actual CAPTCHA. The security gate nevertheless blocked it because raw HTML included Naukri's internal `"showCaptcha":false` value. The defect was isolated to `_check_security()` treating raw HTML text as visible security content.

Implemented fix in `backend/services/naukri/adapter.py`:
- Inspect rendered `page.inner_text("body")` instead of raw `page.content()`.
- Remove bare `captcha` as a standalone trigger.
- Preserve visible human-verification, security-challenge, reCAPTCHA/hCAPTCHA, login, and blocked-access indicators.

Regression coverage in `backend/tests/test_naukri_adapter.py` verifies:
- Raw `"showCaptcha":false` does not block a normal page.
- Bare visible `captcha` does not block.
- Visible reCAPTCHA, hCAPTCHA, and security-verification indicators still block.
- A normal Naukri job page is allowed.

**Recorded test results:** 77 Naukri adapter tests passed; 509 full backend tests passed. No application was submitted. Phase 9B-3 live validation remains incomplete until another real visible-browser Naukri dry-run confirms the corrected behavior.

## Phase 9B-2C Profile Duplicate ERROR Recovery: COMPLETE

Fixed a live-validation blocker in the resume/profile upload pipeline.

**Root cause:** `ProfileService.upload_resume()` duplicate path returned the existing profile unconditionally, regardless of its status. A profile in `ERROR` state (empty data, `confirmed=false`) was returned as-is, making it impossible to recover by re-uploading the same PDF.

**Fix — `backend/services/profile/resume_service.py`:**
- Added `read_stored(directory, filename) -> bytes` method to read back a previously stored PDF file.

**Fix — `backend/services/profile/profile_service.py`:**
- Duplicate path now checks `ProfileStatus` of the existing profile.
- `CONFIRMED` and `REVIEW_REQUIRED` duplicates: reused as before (no extraction).
- `ERROR` duplicate: re-reads stored PDF via `ResumeService.read_stored()`, re-runs PDF text extraction + Gemini extraction pipeline, updates the existing profile record in-place.
- On successful recovery: profile transitions `ERROR → REVIEW_REQUIRED`, `confirmed` remains `false`.
- On failed recovery: profile remains `ERROR`.
- No new resume or profile records are created.

**Regression tests — `backend/tests/test_profile.py` (+6 tests):**
- `test_duplicate_confirmed_profile_reused_without_extraction`
- `test_duplicate_review_required_profile_reused_without_extraction`
- `test_duplicate_error_profile_triggers_extraction_retry`
- `test_duplicate_error_recovery_transitions_to_review_required`
- `test_duplicate_error_recovery_failed_extraction_remains_error`
- `test_duplicate_error_recovery_no_new_records_created`

**Test results:** 503 backend tests passing (previously 497, +6). No regressions.

**No live Naukri activity in this checkpoint.** Phase 9B-2B live dry-run re-execution pending (requires confirmed profile).

---

## Phase 9B-2B Defect Fix: COMPLETE

Two runtime defects discovered during live dry-run attempts were fixed:

**Defect 1 — prompt_version NOT NULL persistence:**
- `AIQueueService.process_item()` in `backend/services/gemini/queue.py` hardcoded `prompt_version="v1"` — a disconnected literal not tied to the prompt versioning architecture.
- Fix: import `JOB_ANALYSIS_PROMPT_V1` from `backend/services/gemini/prompts.py` and use it when creating `JobAnalysisModel`.
- 6 regression tests added in `backend/tests/test_job_analysis_persistence.py`.

**Defect 2 — Experience year computation:**
- `MatchEngine.evaluate_job()` computed `user_exp_years = len(profile.data.get("experience", []))` — counting experience list entries as a proxy for years.
- For the actual user profile (1 ANZ entry, start: July 2026, end: Present), this returned 1 year when the actual elapsed time is ~0 years.
- Fix: added `compute_profile_experience_years()` to `backend/services/matching/normalizer.py` which parses `start_date`/`end_date` fields and computes actual elapsed years. Falls back to entry count when dates are unparseable.
- 8 regression tests added in `backend/tests/test_matching_rules.py`.

**Hard-filter architecture preserved:** Jobs rejected by experience hard filter never reach Gemini. The 0–1 year RR Groups job correctly passes the hard filter (0-year minimum is reachable by a fresher) and Gemini's advisory SKIP is also correct.

**Test results:** 497 backend tests passing (previously 483, +14). No regressions.

**No live Naukri activity in this checkpoint.** Phase 9B-2B live dry-run re-execution pending.

---

## Phase 9A: COMPLETE - Scheduler Automation Loop

Implemented complete Phase 9A scheduler automation loop connecting all existing components into one automatic local execution flow:

- **Gap C1 Fixed**: Scheduler automatically processes AI queue after discovery completes.
- **Gap C2 Fixed**: Scheduler invokes ApplicationRunner for jobs with completed AI analysis.
- **Gap C3 Fixed**: Deterministic hard filters integrated into runtime discovery/matching path.

Implementation details:

- Added `_apply_hard_filters_and_enqueue()` method that evaluates each discovered job through MatchEngine hard filters before queueing for AI analysis. Jobs failing hard filters are blocked from entering the application path.
- Added `_process_ai_queue_items()` method that processes eligible jobs through Gemini analysis, respecting quota exhaustion (stops processing without applying), retry policies, and stale item recovery.
- Added `_invoke_application_runner()` method that passes jobs with completed AI analysis to ApplicationRunner for execution, ensuring final safety gates always run.
- Updated main `_run_discovery_task()` to orchestrate full Phase 9A cycle: Discovery → Hard Filters → AI Queue → ApplicationRunner, with failure isolation so single job failures don't kill entire cycle.
- Updated scheduler routes to provide manual cycle execution endpoint `/scheduler/run-cycle`.
- Scheduler now logs cycle statistics: discovered, hard_filtered, queued, ai_processed, ai_blocked, application_candidates, applied, skipped, needs_attention, failed.

Safety preservation:

- Hard filters remain deterministic and authoritative (Gemini is advisory only).
- ApplicationRunner remains the sole executor of applications.
- Final safety gate in ApplicationService continues to run before every application submission.
- Application limits checked before and during execution.
- Duplicate protection enforced at multiple stages.
- AI quota exhaustion stops processing gracefully without applying jobs.
- Failure isolation: errors in individual jobs don't cascade; processing continues safely.

Testing:

- 5 new Phase 9A integration tests verify cycle orchestration, hard filter enforcement, AI queue processing, ApplicationRunner invocation, and failure isolation.
- All 480 backend tests pass (previously 475, +5 Phase 9A tests).
- Frontend builds successfully.
- No regression: all existing services, safety gates, and limitations remain unchanged and authoritative.

Known limitations: Real Naukri browser submission validation deferred to Phase 9B. Cloud workers, browser execution, and infrastructure changes deferred to Phase 8.5C and later.

---

## Phase 8.5B: COMPLETE - Distributed Work Coordination

Implemented distributed worker work coordination to safely queue and claim AI analysis work among multiple workers:

- Extended AIQueueItem model with three coordination fields: `claimed_by` (worker_id ownership), `last_heartbeat_at` (stale detection), `available_at` (backoff/release timing).
- Implemented WorkCoordinationService with atomic work claiming, ownership verification, heartbeat tracking, stale detection, and safe recovery.
- PostgreSQL claiming uses atomic SELECT...FOR UPDATE SKIP LOCKED to prevent race conditions.
- SQLite uses transaction-safe fallback (without row-level locking) with clear documentation of semantic differences.
- Heartbeat prevents stale detection and requires ownership verification.
- Stale detection identifies work items without heartbeat for 30+ minutes.
- Stale recovery preserves existing safety: if max_attempts exceeded, escalates to NEEDS_ATTENTION (human review required) rather than blindly retrying.
- Release, complete, and fail operations verify ownership and are terminal/idempotent where appropriate.
- Worker load tracking (claimed_count, processing_count).
- Deterministic claiming: priority descending, then created_at ascending.
- Comprehensive test suite: 49 focused tests covering claiming, ownership, heartbeat, stale detection, recovery, release/complete/fail, worker load, priority ordering, database compatibility, edge cases, and safety preservation.
- All 49 tests pass; 475 total backend tests pass (previously 426, +49 coordination tests).
- No regression: existing AI queue, application runner, safety gates, duplicate detection, and application limits remain unchanged and authoritative.
- Frontend unchanged.
- Safety preserved: stale recovery with exhausted attempts does not bypass duplicate protection or safety gates; uncertain outcomes require human review.

Known limitations: Cloud browser execution, browser session migration, cloud browser providers (Browserless, Browserbase), persistent cloud sessions, remote browser execution, Kubernetes, Redis, Celery, RabbitMQ, Kafka, multi-region infrastructure are all deferred to Phase 8.5C and later.

---


Implemented persistent worker identity layer to support future cloud browser coordination without modifying current execution:

- Added Worker SQLAlchemy model with identity (worker_id, unique), type, status, runtime_environment, and lifecycle timestamps (created_at, updated_at, started_at, stopped_at).
- Defined WorkerType enum: LOCAL_WINDOWS (current), CLOUD_BROWSER (future identity-only, not execution).
- Defined WorkerStatus enum: STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR (separate from AgentState).
- Implemented WorkerRegisterRequest and WorkerStatusResponse Pydantic schemas.
- Implemented WorkerListResponse with worker list, total_count, and active_count.
- Implemented WorkerService with four core operations: register_worker (safely repeatable by type+environment), get_worker (by ID), list_workers (all with active count), update_worker_status (with lifecycle tracking).
- Added three minimal API endpoints: GET /api/worker/status (list), POST /api/worker/register (register new or return existing), GET /api/worker/{worker_id} (get by ID).
- Registration is idempotent: same worker_type + runtime_environment returns the same worker_id.
- No sensitive data stored: Worker model contains identity and status only, never stores passwords, cookies, sessions, API keys, or Naukri credentials.
- Comprehensive test suite: type validation, status validation, registration, repeat registration, retrieval, status updates, persistence, listing, active count calculation, API endpoints, unknown worker handling.
- 12 focused tests all pass; 426 total backend tests pass; no regression.
- Frontend build passes with no changes.
- Current Windows/Naukri execution path unchanged; scheduler, Playwright, NaukriAdapter, ApplicationRunner all untouched.

Known limitations: Task claiming, heartbeat, stale-worker detection, PostgreSQL row locking, browser lifecycle refactoring, and cloud browser execution are all deferred to Phase 8.5B-D. Worker registration does not yet trigger any background services or lifecycle hooks.

---

## Phase 8.4.1: COMPLETE - Responsive Mobile Naukri-Inspired UX

Implemented a fully responsive mobile-first frontend experience inspired by Naukri's mobile UX patterns:

- Added mobile header (56px fixed, sticky) with hamburger menu, brand, and notifications bell.
- Converted desktop sidebar to a mobile drawer that slides in from the left with semi-transparent backdrop.
- Implemented bottom navigation bar (56px fixed, sticky) with 5 primary destinations: Home (Overview), Activity, Jobs (disabled), Applications (disabled), and More (secondary routes).
- Added comprehensive responsive CSS for mobile breakpoints (320px, 360px, 375px, 390px, 414px, 480px, 768px, 1024px, 1280px, 1440px+).
- Ensured all touch targets are minimum ~44x44px for accessibility.
- Preserved desktop layout and functionality; sidebar remains visible on desktop (>768px), topbar remains visible, mobile header/bottom nav hidden.
- Responsive grid layouts: metrics 4-col → 2-col → 1-col; analytics 3-col → 2-col → 1-col; forms 2-col → 1-col.
- Mobile-optimized form fields, upload zones, buttons, and cards with proper padding/spacing at each breakpoint.
- No backend changes, no API contract changes, no Gemini/scheduler/automation changes.
- Jobs and Applications routes remain disabled because those pages do not yet exist.
- Mobile UX is inspired by Naukri's information hierarchy and mobile interaction patterns, using Naukri Agent's own branding and design system.

Known limitations: Responsive behavior has been CSS-verified and logically tested, but browser-based device simulation testing at actual viewport sizes was not performed. Mobile UX patterns are Naukri-inspired (not copied); all UI assets and code are original Naukri Agent.

---

## Phase 8.4: COMPLETE - Vercel Frontend to Hosted FastAPI Preparation

Prepared the existing Vite dashboard for Vercel hosting and hosted API connectivity without deploying either service:

- Centralized all frontend API requests in `frontend/src/services/api.ts` using public `VITE_API_BASE_URL` configuration.
- Development retains `http://127.0.0.1:8000` as an omitted-variable fallback. Production requires a configured API URL and never silently uses localhost.
- Normalized configured origins and `/api` suffixes, added a 15-second request timeout, and mapped network, HTTP, timeout, and malformed-response errors to safe user-facing messages.
- Replaced direct/relative frontend `fetch` calls in agent control, analytics, preferences, and AI status with the shared client.
- Updated the existing root `vercel.json` to install/build `frontend/` and publish `frontend/dist`.
- Verified no rewrite is needed because the dashboard uses hash links and in-page state rather than browser-path routes.
- Preserved backend Phase 8.3 CORS; a deployed Vercel origin must be supplied through `NAUKRI_AGENT_FRONTEND_ORIGINS`.

Known limitations: Vercel and the hosted backend have not been deployed; no production URL, managed database, remote browser worker, or cloud automation was added.

---

## Phase 8.3: COMPLETE - Hosted FastAPI Deployment Preparation

Implemented deployment preparation for the existing FastAPI API without deploying any infrastructure:

- Added `Procfile` and a minimal `render.yaml` with root dependency installation, Uvicorn startup, platform-provided `PORT`, and secret-free environment placeholders.
- Preserved `python run.py` for local Windows development; hosted services run `backend.main:app` on `0.0.0.0`.
- Production readiness now requires PostgreSQL, Gemini configuration, and explicit non-wildcard frontend origins using the existing `NAUKRI_AGENT_` prefix.
- Liveness (`/api/health`) is independent of database and Gemini. Readiness (`/api/readiness`) reports safe database/configuration/storage/AI/runtime status without raw exception text.
- Production CORS supports one or more configured origins and leaves credentialed browser requests disabled.
- Hardened `SafeJsonFormatter` with centralized recursive sanitization for message text, extras, nested containers, credential URLs, auth/cookie/session data, and exceptions.
- Confirmed the existing frontend `VITE_API_BASE_URL` configuration remains separate from backend environment configuration.

Known limitations: no hosting provider deployment, managed PostgreSQL provisioning, frontend deployment, object storage, remote browser worker, or cloud automation was implemented.

---

## Phase 8.1: COMPLETE - Production Backend Preparation (Checkpoint 8.1)

Implemented Phase 8.1 - Production Backend Preparation to make the FastAPI backend production-hosting ready without actual deployment:

**Production Configuration Enhancements:**
- Enhanced configuration with environment separation (LOCAL_WINDOWS/CLOUD)
- Added production detection properties (is_production, is_local_windows, is_cloud)
- Added CORS origins parsing from comma-separated string for multiple frontend origins
- Updated .env.example with comprehensive production-ready configuration placeholders
- Added runtime_environment configuration field for environment-specific behavior

**CORS Configuration Improvements:**
- Production-safe CORS configuration with configurable origins
- Development mode allows localhost origins for convenience
- Production mode uses only configured origins from FRONTEND_ORIGINS
- Added support for multiple origins via comma-separated list
- Enhanced CORS methods and headers for full API support

**Health and Readiness Endpoints:**
- Added separate readiness endpoint (/api/readiness) from liveness endpoint (/api/health)
- Liveness check: simple API process status
- Readiness check: detailed component status (database, configuration, storage, AI provider, runtime environment)
- Readiness endpoint validates database connectivity, configuration validity, storage availability
- Production mode requires API key for configuration validation
- Added ReadinessResponse schema for structured component status reporting

**Error Handling Enhancements:**
- Added catch-all exception handler to prevent sensitive information exposure
- Generic exception handler returns safe error messages without stack traces
- Enhanced error responses for production safety
- Logs errors without exposing sensitive details to clients

**Logging Production Readiness:**
- Added SafeJsonFormatter for production-safe logging
- Automatic redaction of sensitive information (api_key, password, token, secret, credential, auth)
- Production mode uses SafeJsonFormatter by default
- Development mode uses standard JsonFormatter for debugging
- Enhanced logging configuration to respect environment settings

**Database Configuration Verification:**
- Verified database configuration supports both SQLite and PostgreSQL
- SQLite directory creation works for both relative and absolute paths
- PostgreSQL URL configuration is fully supported via DATABASE_URL
- No SQLite-only assumptions that would prevent hosted operation
- Database initialization works correctly in both modes

**Storage Configuration Verification:**
- Verified StorageService abstraction for hosted readiness
- Application code uses StorageService for file operations
- No direct Windows-specific absolute path dependencies
- Local filesystem storage preserved for LOCAL_WINDOWS
- Abstraction ready for future object storage integration

**Browser/API Separation Verification:**
- Verified browser automation is not auto-started by API startup
- Playwright browser only starts when explicitly called via DiscoveryService
- API process initialization does not launch Chromium
- Clear separation between API process and browser worker
- Safe for future cloud architecture with separate browser worker

**Frontend API Configuration:**
- Enhanced frontend API configuration for environment-based backend URL
- Added VITE_API_BASE_URL environment variable support
- Development: http://127.0.0.1:8000/api (default)
- Production: https://<hosted-api>/api (configurable via environment)
- Added frontend/.env.example with API configuration placeholder
- No hardcoded localhost in production frontend code

**Security Improvements:**
- Enhanced CORS configuration prevents wildcard origins in production
- Error responses don't expose stack traces or internal details
- Logging redacts sensitive information automatically
- Configuration properties don't expose API keys or secrets
- API responses never return credentials or sensitive configuration

**Production Configuration Tests:**
- Added comprehensive test suite (backend/tests/test_production_config.py)
- Tests for environment separation (LOCAL_WINDOWS/CLOUD)
- Tests for CORS configuration and origins parsing
- Tests for health and readiness endpoints
- Tests for error handling and security
- Tests for database configuration (SQLite/PostgreSQL)
- Tests for storage configuration
- Tests for browser/API separation
- Tests for Gemini configuration
- Tests for environment variable configuration
- Total: 401 tests passing (32 new production configuration tests)

**Files Changed:**
- backend/core/config.py: Enhanced with production configuration properties
- backend/main.py: Enhanced CORS, logging, error handling
- backend/core/logging.py: Added SafeJsonFormatter for production
- backend/api/routes/health.py: Added readiness endpoint
- backend/schemas/health.py: Added ReadinessResponse schema
- .env.example: Comprehensive production configuration
- frontend/src/services/api.ts: Environment-based API URL
- frontend/.env.example: Frontend environment configuration
- backend/tests/test_production_config.py: New comprehensive test suite
- backend/tests/test_health.py: Enhanced with readiness tests

**Key Design Decisions:**
- Environment separation via runtime_environment (local_windows/cloud)
- Production-safe CORS with configurable origins
- Separate liveness and readiness endpoints for container orchestration
- Production logging with automatic sensitive information redaction
- No actual cloud deployment in this checkpoint
- All V1 functionality remains local Windows only
- Future cloud deployment will use CLOUD mode with object storage and PostgreSQL

**Known Limitations:**
- Cloud execution NOT implemented (future phase)
- Remote browser automation NOT implemented (future phase)
- Object storage (S3/Azure/GCS) NOT implemented (future phase)
- PostgreSQL production database NOT deployed (future phase)
- Cloud infrastructure NOT deployed (future phase)
- All V1 functionality remains local Windows only

**Next Phase:**
- Phase 8.2 - COMPLETE: PostgreSQL + Production Persistence (Checkpoint 8.2)

---

## Phase 8.2: COMPLETE - PostgreSQL + Production Persistence (Checkpoint 8.2)

Implemented Phase 8.2 - Production Database Support alongside the existing SQLite backend:

**PostgreSQL Driver Integration:**
- Configured PostgreSQL connectivity using the `psycopg` v3 driver.
- Added connection pooling metrics suitable for scaling (e.g. `pool_size`, `max_overflow`).
- Rewrote dialect URLs handling transparently replacing basic `postgresql://` inputs to `postgresql+psycopg://` at runtime.

**Backward Compatibility:**
- Maintained fully functional SQLite configuration with memory and file support for local V1 instances.
- All testing functions default natively against SQLite without requiring production teardowns.
- Storage directory constraints automatically managed based on database environments.

**Persistence:**
- Confirmed StorageService compatibility with absolute path routing avoiding storage conflicts.
- Local environments default safely preserving past file histories.

**Files Changed:**
- backend/requirements.txt: Appended `psycopg[binary]`.
- backend/database/database.py: Added PostgreSQL dialect interception and configurations.
- backend/tests/test_database_engines.py: Extensive test suite proving isolated dialect and queue pool attributes handling.

**Next Phase:**
- Cloud Execution (Docker/Hosting setup) - TBD

---

## Frontend Codebase Structure Verification - COMPLETE

Verified frontend codebase structure and dependencies for production readiness:

**Current Frontend Stack:**
- React 19.1.0 with TypeScript 5.8.3
- Vite 6.3.5 for build tooling
- Tailwind CSS 4.1.4 for styling
- Lucide React 0.468.0 for icons
- @vitejs/plugin-react 4.4.1 for React support

**Frontend Component Structure:**
- App.tsx: Main application shell with navigation
- AnalyticsDashboard.tsx: Analytics metrics and decision breakdown
- AgentControl.tsx: Agent lifecycle controls
- AIStatus.tsx: AI usage tracking
- BackendState.tsx: Backend connection state handling
- EmptyState.tsx: Reusable empty state component
- ErrorState.tsx: Reusable error state component
- LoadingState.tsx: Reusable loading state component
- JobPreferences.tsx: Job search preferences management
- ProfileWorkspace.tsx: Resume and profile management

**Frontend Build Status:**
- TypeScript compilation: PASSED
- Vite production build: PASSED (267.10 kB JS, 28.43 kB CSS)
- Build time: 17.59s
- No build errors or warnings

**Code Quality:**
- Type-safe components with TypeScript
- Proper error handling and loading states
- Reusable state components
- Modern React patterns
- Clean component architecture

**Dependencies:**
- All dependencies are up-to-date and stable
- No deprecated packages
- Production-ready versions (all published >7 days ago)
- Minimal dependency footprint

**Next Steps:**
- Frontend is production-ready for current feature set
- Components follow modern React best practices
- Build pipeline is stable and performant
- Codebase is well-structured for future enhancements

---

## Frontend UX/UI Redesign Checkpoint - COMPLETE

Implemented comprehensive frontend UX/UI redesign to transform the dashboard from a development prototype to a polished, modern SaaS product:

**User Experience Improvements:**
- Removed all development-phase terminology from user-facing UI (Phase 1-7 labels, "foundation phase", etc.)
- Replaced technical error messages with user-friendly alternatives
- Created reusable state components (LoadingState, EmptyState, ErrorState, BackendState)
- Implemented graceful backend connection state handling
- Added profile completion indicator with visual progress tracking
- Improved preferences page with clear sections and descriptions
- Enhanced analytics dashboard with compact, readable charts

**Visual Design Overhaul:**
- Modern SaaS dashboard layout with improved sidebar navigation
- Enhanced top bar with page titles, descriptions, and status indicators
- Consistent visual language using Naukri-inspired color palette
- Improved typography hierarchy and spacing
- Rounded corners, subtle shadows, and smooth transitions
- Hover states and active navigation indicators
- Better card design with visual hierarchy

**Navigation Structure:**
- Overview: Main command center with agent status and controls
- Activity: Timeline of agent actions and events
- Jobs: Job discovery interface (placeholder for future)
- Applications: Application tracking dashboard (placeholder for future)
- Analytics: Performance metrics and decision analytics
- Profile: Resume and profile management
- Preferences: Job search criteria and automation settings

**Accessibility Enhancements:**
- Skip-to-content link for keyboard navigation
- Proper ARIA labels on interactive elements
- Visible focus states on all interactive elements
- Semantic HTML structure
- Sufficient color contrast
- Keyboard-friendly navigation

**Responsive Design:**
- Desktop: Full sidebar with all navigation items
- Tablet: Collapsed sidebar with icons only
- Mobile: Off-canvas sidebar layout
- Card layouts reflow appropriately
- Optimized for various screen sizes

**Technical Improvements:**
- Enhanced CSS with modern design tokens
- Improved button hierarchy and states
- Better form field styling with focus states
- Consistent spacing system (4px, 8px, 16px, 24px, 32px)
- Performance optimizations with minimal dependencies
- Type-safe components with TypeScript

**Files Changed:**
- frontend/src/app/App.tsx: Redesigned app shell with navigation
- frontend/src/styles.css: Complete visual language overhaul
- frontend/src/components/LoadingState.tsx: New reusable loading component
- frontend/src/components/EmptyState.tsx: New reusable empty state component
- frontend/src/components/ErrorState.tsx: New reusable error state component
- frontend/src/components/BackendState.tsx: New backend connection state component
- frontend/src/components/ProfileWorkspace.tsx: Enhanced with completion indicator
- frontend/src/components/JobPreferences.tsx: Improved with clear sections
- frontend/src/components/AnalyticsDashboard.tsx: Enhanced error handling

**Testing:**
- Frontend build: PASSED (TypeScript compilation successful)
- Frontend typecheck: PASSED
- Backend pytest: PASSED (369 tests, no regression)
- No backend functionality modified (frontend-only changes)

**Design Principles Applied:**
- Professional SaaS aesthetic
- User-centric language
- Accessibility-first approach
- Responsive design
- Graceful degradation
- Performance optimization

**Next Steps:**
- Implement Jobs page with proper discovery interface
- Implement Applications page with tracking dashboard
- Implement Activity timeline with real agent data
- Add more sophisticated data visualizations
- Implement user onboarding flow

---

## Phase 7: COMPLETE - Agent Intelligence, Decision Quality & Application Analytics (Checkpoint 4)

Implemented Phase 7 Checkpoint 4:

- Created decision quality model in backend/schemas/decision.py:
  - DecisionPriority enum: HARD_REJECT, SKIP, LOW_PRIORITY, NORMAL_PRIORITY, HIGH_PRIORITY, NEEDS_ATTENTION
  - DecisionReasonCode enum: 20+ structured reason codes for explainable decisions
  - DecisionQuality schema: comprehensive decision assessment with signals
  - DecisionSignal schema: individual signal contribution to decision
  - JobPriorityRequest/Response: bulk job prioritization
  - DecisionHistoryRequest/Response: decision history tracking
- Created feedback schemas in backend/schemas/feedback.py:
  - FeedbackType enum: RELEVANT, NOT_RELEVANT, APPLIED, SKIPPED, INCORRECT_MATCH, etc.
  - FeedbackCreate/Response: feedback submission and retrieval
  - FeedbackSummary: feedback aggregation metrics
- Created feedback models in backend/models/feedback.py:
  - JobFeedback: stores explicit user feedback for learning
  - DecisionQualityRecord: stores decision quality assessments for analytics
- Implemented DecisionQualityService in backend/services/decision/quality.py:
  - evaluate_job_decision(): comprehensive decision evaluation with explainable reasoning
  - Hard filter checks remain authoritative (profile, location, experience, salary, employment, title scope, duplicate)
  - AI analysis integration (advisory only, never overrides hard rules)
  - Signal calculation: role relevance, skill relevance, experience compatibility, location match, salary suitability, job quality, freshness, duplicate probability, suspicious probability
  - Historical feedback integration: feedback adjustment (-1 to 1)
  - Decision score calculation (0-100) using weighted signal combination
  - Priority determination based on score and special cases
  - Explainable decision generation with reason codes
  - save_decision_record(): persistence to DecisionQualityRecord for analytics
- Implemented JobPrioritizationService in backend/services/decision/prioritization.py:
  - prioritize_jobs(): bulk job prioritization with sorting
  - get_eligible_jobs_for_application(): filter to eligible jobs only
  - get_prioritized_eligible_jobs(): prioritized eligible jobs with limit
  - Deterministic and reproducible prioritization
  - Hard-filtered jobs never become higher priority
- Implemented FeedbackService in backend/services/learning/service.py:
  - submit_feedback(): submit user feedback for jobs
  - get_feedback_for_job(): retrieve feedback for specific job
  - get_feedback_summary(): aggregate feedback metrics
  - delete_feedback(): remove feedback records
  - Feedback influences ranking only (cannot override hard rules)
- Implemented AnalyticsService in backend/services/analytics/service.py:
  - get_analytics_summary(): comprehensive analytics summary
  - get_skip_reasons(): top skip reasons with counts
  - get_decision_breakdown(): decision priority distribution
  - get_applications_by_day(): daily application counts
  - get_applications_by_job_profile(): application breakdown by title
  - get_primary_reason_codes(): top decision reason codes
  - get_feedback_summary(): feedback metrics
  - get_recent_decision_activity(): latest decision records
  - All analytics use existing data without creating fake historical data
- Added decision API routes in backend/api/routes/decision.py:
  - POST /api/decision/evaluate/{job_id}: evaluate decision quality for specific job
  - POST /api/decision/prioritize: prioritize list of jobs
  - GET /api/decision/history/{job_id}: get decision history for job
- Added feedback API routes in backend/api/routes/feedback.py:
  - POST /api/feedback/submit: submit user feedback
  - GET /api/feedback/job/{job_id}: get feedback for job
  - GET /api/feedback/summary: get feedback summary
  - DELETE /api/feedback/{feedback_id}: delete feedback
- Added analytics API routes in backend/api/routes/analytics.py:
  - GET /api/analytics/summary: comprehensive analytics summary
  - GET /api/analytics/skip-reasons: top skip reasons
  - GET /api/analytics/decision-breakdown: decision priority distribution
  - GET /api/analytics/applications-by-day: daily application counts
  - GET /api/analytics/applications-by-profile: application breakdown by title
  - GET /api/analytics/primary-reasons: top decision reason codes
  - GET /api/analytics/feedback-summary: feedback metrics
  - GET /api/analytics/recent-decisions: recent decision activity
- Added AnalyticsDashboard component in frontend/src/components/AnalyticsDashboard.tsx:
  - Summary metrics: jobs discovered, applications submitted, success rate, AI usage
  - Decision breakdown: priority distribution with visual bars
  - Top skip reasons: aggregated skip reason analysis
  - Real-time data fetching with error handling
  - Naukri-inspired design with color-coded metrics
- Enhanced App.tsx to include AnalyticsDashboard in overview section
- Added analytics styles in frontend/src/styles.css:
  - Analytics card grid layout
  - Color-coded metric icons (success, warning, attention, info, neutral)
  - Decision breakdown bars with percentages
  - Skip reasons list styling
  - Responsive design for mobile
- Integrated new routes in backend/main.py:
  - decision_router: decision quality and prioritization endpoints
  - feedback_router: feedback submission and retrieval endpoints
  - analytics_router: analytics and reporting endpoints
- Updated models/__init__.py to export JobFeedback and DecisionQualityRecord
- Comprehensive test coverage (46 new tests):
  - Decision quality tests (10 tests): hard filters, AI integration, scoring, explanations
  - Prioritization tests (7 tests): sorting, eligibility, determinism, AI analysis
  - Feedback tests (11 tests): submission, retrieval, summary, influence on decisions
  - Analytics tests (18 tests): summary, skip reasons, decision breakdown, time periods
- Total: 369 tests passing

Decision Quality Architecture:
```text
DecisionQualityService (decision evaluation)
    ↓
Hard filters (authoritative Python rules)
    ↓
AI analysis (advisory only)
    ↓
Signal calculation (weighted combination)
    ↓
Decision score (0-100)
    ↓
Priority determination
    ↓
Explainable decision with reason codes
    ↓
DecisionQualityRecord persistence
```

Key Design Decisions:
- Hard filters remain authoritative (location, experience, salary, duplicate, etc.)
- Gemini recommendations are advisory only - never override hard rules
- Decision quality combines deterministic Python rules with AI analysis
- Priority levels: HARD_REJECT, SKIP, LOW_PRIORITY, NORMAL_PRIORITY, HIGH_PRIORITY, NEEDS_ATTENTION
- Structured reason codes for explainable decisions (20+ codes)
- Historical feedback influences ranking but cannot modify hard rules
- User-controlled preferences remain authoritative
- Analytics use existing data without creating fake historical data
- Prioritization is deterministic and reproducible
- All decisions persisted for analytics and learning

API Endpoints Added:
- POST /api/decision/evaluate/{job_id}
- POST /api/decision/prioritize
- GET /api/decision/history/{job_id}
- POST /api/feedback/submit
- GET /api/feedback/job/{job_id}
- GET /api/feedback/summary
- DELETE /api/feedback/{feedback_id}
- GET /api/analytics/summary
- GET /api/analytics/skip-reasons
- GET /api/analytics/decision-breakdown
- GET /api/analytics/applications-by-day
- GET /api/analytics/applications-by-profile
- GET /api/analytics/primary-reasons
- GET /api/analytics/feedback-summary
- GET /api/analytics/recent-decisions

Frontend Changes:
- AnalyticsDashboard component with comprehensive metrics
- Decision breakdown visualization with priority bars
- Top skip reasons display
- Naukri-inspired design with color-coded cards
- Real-time data fetching and error handling
- Responsive grid layout for metrics

Safety Behavior:
- Hard filters remain authoritative (location, experience, salary, duplicate, etc.)
- Gemini cannot override hard rules or trigger applications
- Feedback cannot modify hard filters or user preferences
- Prioritization never places hard-filtered jobs above eligible jobs
- Learning is ranking/prioritization only, not rule modification
- All decisions are explainable with structured reason codes

Known limitations:
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented
- Learning is minimal (ranking influence only, not automatic rule modification)
- External application submission NOT implemented
- Complex automated learning NOT implemented

Next Phase: Phase 8 - Production Readiness (TBD)

Implemented cloud readiness infrastructure to support future cloud deployment while maintaining local-first V1:

- Created RuntimeContext abstraction in backend/core/runtime.py:
  - RuntimeEnvironment enum: LOCAL_WINDOWS (V1 current), CLOUD_READY (future)
  - RuntimeContext class: Provides environment-specific information and behavior
  - Auto-detects current runtime (Windows vs others)
  - Properties for: browser automation support, Windows auto-start support, persistent browser session support
  - Methods for: database URL retrieval, storage path resolution, directory paths
  - Global singleton instance with get_runtime_context() and set_runtime_context()
- Created StorageService abstraction in backend/core/storage.py:
  - StorageService class: File storage operations with clean interface
  - Methods for: store_file, read_file, delete_file, file_exists, get_file_size
  - Methods for: list_files, create_directory, delete_directory
  - Path resolution with resolve_path()
  - Directory management: resume storage, data storage, log storage, browser user data
  - Atomic file operations with temporary files
  - Global singleton instance with get_storage_service()
- Enhanced configuration in backend/core/config.py:
  - Added environment variable prefix (NAUKRI_AGENT_) for all settings
  - Changed storage paths from Path fields to string fields with property resolution
  - Properties for absolute path resolution: resume_storage_path, data_path, log_path, browser_user_data_path
  - Added runtime_environment configuration field
  - Support for both relative and absolute paths
- Enhanced database configuration in backend/database/database.py:
  - Support for both SQLite and PostgreSQL databases
  - Flexible DATABASE_URL configuration
  - Improved SQLite directory creation for both relative and absolute paths
- Integrated abstractions into existing services:
  - NaukriAdapter now uses get_browser_user_data_dir() from settings
  - ResumeService now uses StorageService for file operations
  - All path resolution goes through storage abstraction
- Added comprehensive tests (40 new tests):
  - RuntimeContext tests (16 tests): environment detection, properties, path resolution
  - StorageService tests (24 tests): file operations, directory management, path resolution
- Total: 323 tests passing

Cloud Readiness Architecture:
```text
RuntimeContext (environment detection)
    ↓
StorageService (file operations abstraction)
    ↓
Settings (environment variable driven configuration)
    ↓
Database (SQLite/PostgreSQL flexibility)
```

Key Design Decisions:
- V1 continues to run in LOCAL_WINDOWS mode
- Future cloud deployment will use CLOUD_READY mode
- No changes to existing business logic or public APIs
- Abstractions allow future cloud integration without code changes
- Environment variables prefixed with NAUKRI_AGENT_ for consistency
- Path resolution supports both relative and absolute paths
- Storage abstraction enables future S3/Azure Blob/GCS integration
- Database abstraction enables future PostgreSQL migration
- Browser automation only supported in LOCAL_WINDOWS (V1 design)
- All existing functionality preserved

Files Changed:
- backend/core/runtime.py (new)
- backend/core/storage.py (new)
- backend/core/config.py (enhanced)
- backend/database/database.py (enhanced)
- backend/services/naukri/adapter.py (minor integration)
- backend/services/profile/resume_service.py (minor integration)
- backend/tests/test_runtime.py (new)
- backend/tests/test_storage.py (new)
- backend/tests/test_profile.py (test fixes for new config)

Known Limitations:
- Cloud execution NOT implemented (future phase)
- Remote browser automation NOT implemented (future phase)
- Object storage (S3/Azure/GCS) NOT implemented (future phase)
- PostgreSQL deployment NOT implemented (future phase)
- All V1 functionality remains local Windows only

---

## Phase 7: COMPLETE - Windows Startup & Local Agent Lifecycle (Checkpoint 3)

Implemented Phase 7 Checkpoint 3:

- Created AgentLifecycleService in backend/services/lifecycle/service.py:
  - get_lifecycle_status(): Comprehensive status including agent state, scheduler, AI queue, prerequisites
  - start(): Safe agent start with prerequisite validation
  - stop(): Safe agent stop with queue preservation
  - pause(): Pause agent with queue preservation
  - resume(): Resume agent with prerequisite validation
  - recover_on_startup(): Startup recovery with stale queue recovery and safe state restoration
  - _check_prerequisites(): Validates confirmed profile, job preferences, and API key
- Created WindowsAutoStartService in backend/services/windows/autostart.py:
  - is_enabled(): Check if Windows Task Scheduler auto-start is enabled
  - enable(): Enable auto-start via Task Scheduler (user-level, no admin required)
  - disable(): Disable auto-start by removing Task Scheduler task
  - get_status(): Get auto-start status and platform support
- Added lifecycle schemas in backend/schemas/lifecycle.py:
  - LifecycleStatusResponse: Full lifecycle status
  - LifecycleActionResponse: Start/stop/pause/resume results
  - RecoveryStatsResponse: Startup recovery statistics
  - RecoveryResponse: Recovery operation result
- Added auto-start schemas in backend/schemas/autostart.py:
  - AutoStartStatusResponse: Auto-start status
  - AutoStartEnableRequest: Enable auto-start request
  - AutoStartActionResponse: Enable/disable results
- Created lifecycle API routes in backend/api/routes/lifecycle.py:
  - GET /api/agent/status: Get agent lifecycle status
  - POST /api/agent/start: Start agent
  - POST /api/agent/stop: Stop agent
  - POST /api/agent/pause: Pause agent
  - POST /api/agent/resume: Resume agent
  - POST /api/agent/recovery: Trigger startup recovery (for testing)
- Created system API routes in backend/api/routes/system.py:
  - GET /api/system/autostart: Get auto-start status
  - POST /api/system/autostart/enable: Enable Windows auto-start
  - POST /api/system/autostart/disable: Disable Windows auto-start
- Integrated lifecycle services in backend/main.py:
  - Initialize AgentLifecycleService with state_manager and scheduler_service
  - Initialize WindowsAutoStartService
  - Perform startup recovery during FastAPI lifespan
  - Removed auto-start of scheduler on startup (safe default)
  - Agent resets to IDLE after restart (no automatic application submission)
- Extended AgentControl component in frontend/src/components/AgentControl.tsx:
  - Displays current agent state with color coding
  - Start/Stop/Pause/Resume buttons based on current state
  - Shows scheduler status and AI queue counts
  - Windows auto-start toggle (Windows only)
  - Prerequisites validation warnings
  - Real-time status polling (5-second interval)
- Added agent control styles in frontend/src/styles.css:
  - Control button styles (primary, secondary, danger)
  - Agent state color coding (idle, running, paused, stopped, error states)
  - Warning text for missing prerequisites
  - Toggle button for auto-start
  - Status meta display improvements
- Fixed SchedulerService database session management:
  - AI queue service now initialized per-session to avoid session conflicts
  - process_ai_queue() takes db session parameter
  - _enqueue_discovered_jobs() takes db session parameter
  - Gemini provider lazy initialization in AIQueueService
- Comprehensive test coverage (38 new tests):
  - Lifecycle service tests (21 tests): status, prerequisites, start/stop/pause/resume, recovery
  - Auto-start service tests (16 tests): enable/disable/status, Windows/non-Windows behavior
  - Lifecycle integration tests (15 tests): complete flow, scheduler integration, recovery, safety
- Total: 239 tests passing

Lifecycle Architecture:
```text
AgentLifecycleService (orchestration)
    ↓
AgentStateManager (existing state management)
    ↓
SchedulerService (existing scheduler)
    ↓
AIQueueService (existing AI queue)
    ↓
WindowsAutoStartService (Task Scheduler integration)
```

Key Design Decisions:
- Lifecycle service extends AgentStateManager without duplicating state logic
- Startup recovery defaults to IDLE state (safe default, no auto-submission)
- Active states (RUNNING, SEARCHING, FILTERING, APPLYING) reset to IDLE on restart
- Problem states (AUTH_REQUIRED, SECURITY_REQUIRED) are preserved on restart
- Auto-start uses Windows Task Scheduler (user-level, no admin required)
- Auto-start is optional and user-controlled (not automatic during development)
- Agent checks prerequisites before start/resume operations
- Scheduler is NOT auto-started on application startup (safe default)
- Queue is preserved across stop/start operations
- AI queue stale items recovered on startup
- Windows auto-start only available on Windows platform
- Subprocess flags are platform-specific (CREATE_NO_WINDOW on Windows)

API Endpoints Added:
- GET /api/agent/status
- POST /api/agent/start
- POST /api/agent/stop
- POST /api/agent/pause
- POST /api/agent/resume
- POST /api/agent/recovery
- GET /api/system/autostart
- POST /api/system/autostart/enable
- POST /api/system/autostart/disable

Frontend Changes:
- AgentControl component with real-time status polling
- State-based button visibility (Start when IDLE/STOPPED, Pause/Stop when RUNNING, etc.)
- Prerequisites validation and warnings
- Windows auto-start toggle (platform-aware)
- Color-coded agent states
- Scheduler and AI queue status display

Safety Behavior:
- No automatic application submission after restart
- Agent resets to IDLE even if it was RUNNING before restart
- Prerequisites validated before start/resume
- Queue preserved across lifecycle operations
- Stale queue items recovered on startup
- Error states preserved for user attention
- Scheduler not auto-started with application

Known limitations:
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented
- Windows service NOT implemented (Task Scheduler used instead)
- Complex installer NOT implemented
- Multi-platform auto-start NOT implemented (Windows-only currently)

Next Phase: Phase 8 - Production Readiness (TBD)

---

## Phase 7: COMPLETE - AI Work Queue (Checkpoint 2B)

Implemented Phase 7 Checkpoint 2A:

- Created ApplicationLimitService in backend/services/applications/limits.py:
  - get_limits(): Retrieves current limits from JobPreference (max_hourly_applications, max_daily_applications)
  - update_limits(): Updates hourly/daily limits
  - get_hourly_usage(): Counts successful applications (APPLIED/SUBMITTED) in last hour
  - get_daily_usage(): Counts successful applications (APPLIED/SUBMITTED) in last 24 hours
  - check_limits(): Returns LimitCheckResult with allowed status and detailed usage info
  - get_limit_status(): Returns full status including usage, remaining capacity, and percentages
- Added limit schemas in backend/schemas/application.py:
  - ApplicationLimitsUpdate: For updating max_hourly_applications and max_daily_applications
  - ApplicationLimitsResponse: Full limit status with usage metrics
  - LimitCheckResponse: Result of limit check with reason and capacity info
- Integrated limit check into ApplicationRunner (backend/services/applications/runner.py):
  - Added ApplicationLimitService to runner initialization
  - Check limits BEFORE safety gate and BEFORE application submission
  - Skip application with clear reason when limits reached
  - Preserve all existing safety gate and duplicate protection logic
- Integrated limit check into SchedulerService (backend/services/scheduler/service.py):
  - Check limits BEFORE starting discovery
  - Skip discovery when hourly or daily limits reached
  - Log when limits block discovery
  - Allow scheduler to continue safely without errors
- Added limit API endpoints in backend/api/routes/application.py:
  - GET /api/applications/limits: Get current limits and usage status
  - PUT /api/applications/limits: Update hourly/daily limits
  - GET /api/applications/limits/check: Check if another application is allowed
- Added comprehensive tests (22 new tests):
  - ApplicationLimitService tests (19 tests): get_limits, update_limits, hourly/daily usage, limit checks, status
  - Limit enforcement tests (3 tests): only APPLIED/SUBMITTED counted, failed/external not counted
- Total: 201 tests passing

Limit Architecture:
```text
ApplicationLimitService (deterministic Python logic)
    ↓
Counts only APPLIED/SUBMITTED applications (not SKIPPED/NEEDS_ATTENTION/EXTERNAL)
    ↓
Hourly usage: applications with applied_at >= now - 1 hour
    ↓
Daily usage: applications with applied_at >= now - 24 hours
    ↓
Limit check: blocks if hourly_used >= max_hourly OR daily_used >= max_daily
    ↓
ApplicationRunner: checks limits BEFORE safety gate and BEFORE submission
    ↓
SchedulerService: checks limits BEFORE starting discovery
```

Key Design Decisions:
- Limits use existing JobPreference model (max_hourly_applications, max_daily_applications already existed)
- Only successful applications (APPLIED/SUBMITTED status) count toward limits
- Failed/skipped/external applications do NOT count toward limits
- Deterministic Python logic only - Gemini never decides limits
- Limit check happens BEFORE safety gate (hard filters still execute first)
- Limit check happens BEFORE application submission
- Scheduler skips discovery when limits reached (no wasted resources)
- Clear reasons provided when limits block applications
- Percentage calculations for UI display
- UTC timezone for all time calculations

API Endpoints Added:
- GET /api/applications/limits
- PUT /api/applications/limits
- GET /api/applications/limits/check

Integration Points:
- ApplicationRunner._process_single_job(): Check limits after duplicate check, before safety gate
- SchedulerService._run_discovery_task(): Check limits before starting discovery
- Existing JobPreference model already had limit fields (Phase 4)
- Existing Application status enum used for filtering (Phase 6)

Known limitations:
- AI queue NOT implemented yet (future checkpoint)
- Gemini changes NOT implemented yet (future checkpoint)
- Restart recovery NOT implemented yet (future checkpoint)
- Windows startup NOT implemented yet (future checkpoint)
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented

Next Checkpoint: Phase 7 - Checkpoint 2B (AI Queue)

---

## Phase 7: COMPLETE - Scheduler Core (Checkpoint 1)

Implemented Phase 7 Checkpoint 1:

- Added APScheduler dependency to requirements.txt (>=3.10,<4.0)
- Added scheduler configuration to Settings:
  - scheduler_enabled: bool (default True)
  - scheduler_interval_minutes: int (default 60, hourly)
  - scheduler_max_instances: int (default 1)
- Created SchedulerConfig model in backend/models/scheduler.py for persistence:
  - enabled, interval_minutes, max_instances
  - is_running, is_paused states
  - last_run_at, next_run_at timestamps
  - created_at, updated_at for tracking
- Created scheduler core in backend/core/scheduler.py:
  - JobScheduler class using APScheduler AsyncIOScheduler
  - Configurable interval with max_instances=1 to prevent overlapping runs
  - Support for start, stop, pause, resume operations
  - Status reporting (is_running, is_paused, interval, last_run, next_run)
  - Task callback system for integration with discovery service
  - UTC timezone support
- Created scheduler service in backend/services/scheduler/service.py:
  - SchedulerService class for orchestration and persistence
  - Initializes from database config or creates defaults
  - Integrates with existing DiscoveryService for scheduled runs
  - Loads/saves configuration to database
  - Respects agent state - skips discovery when agent is busy
  - Safe startup/shutdown with database session management
- Created scheduler Pydantic schemas in backend/schemas/scheduler.py:
  - SchedulerStatusResponse: current scheduler status
  - SchedulerConfigRequest: update enabled/interval
  - SchedulerConfigResponse: full configuration
  - SchedulerActionResponse: action results with status
- Created scheduler API routes in backend/api/routes/scheduler.py:
  - GET /api/scheduler/status: Get scheduler status
  - POST /api/scheduler/start: Start scheduler
  - POST /api/scheduler/stop: Stop scheduler
  - POST /api/scheduler/pause: Pause scheduler
  - POST /api/scheduler/resume: Resume scheduler
  - PUT /api/scheduler/config: Update configuration
- Integrated scheduler startup/shutdown in backend/main.py:
  - Initializes SchedulerService with shared state_manager and discovery_service
  - Loads config from database on startup
  - Auto-starts scheduler if enabled in settings
  - Graceful shutdown on application stop
- Added comprehensive tests in backend/tests/test_scheduler.py (33 tests):
  - JobScheduler tests: initialization, callback, start/stop, pause/resume, interval update, status, task execution
  - SchedulerService tests: initialization, config load/create, start/stop/pause/resume, interval update, enabled toggle, status, shutdown, discovery task execution
  - Tests cover: default configuration, custom interval, duplicate/overlapping run prevention, application shutdown cleanup

Scheduler Architecture:
```text
APScheduler (JobScheduler)
    ↓
SchedulerService (orchestration + persistence)
    ↓
DiscoveryService (existing Phase 5 service)
    ↓
AgentStateManager (existing state management)
```

Key Design Decisions:
- Scheduler is timing/orchestration only - business rules remain in DiscoveryService
- Uses APScheduler with max_instances=1 to prevent overlapping runs
- Persists configuration to database for recovery across restarts
- Respects agent state - skips discovery when agent is busy (RUNNING, SEARCHING, FILTERING, APPLYING)
- Integrates with existing services without duplicating logic
- UTC timezone for all timestamps
- Global service instance shared between main.py and API routes
- Safe shutdown during application lifecycle

API Endpoints Added:
- GET /api/scheduler/status
- POST /api/scheduler/start
- POST /api/scheduler/stop
- POST /api/scheduler/pause
- POST /api/scheduler/resume
- PUT /api/scheduler/config

Known limitations:
- Application limits NOT implemented yet (future checkpoint)
- AI queue NOT implemented yet (future checkpoint)
- Restart recovery NOT implemented yet (future checkpoint)
- Windows startup NOT implemented yet (future checkpoint)
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented

Next Checkpoint: Phase 7 - Checkpoint 2A (Application Limits)

---

## Phase 7: COMPLETE - Scheduler Core (Checkpoint 1)

---

## Phase 6: COMPLETE - Naukri Application Automation

Implemented Phase 6:

- Created Application and ApplicationAnswer models in `backend/models/application.py`
- Created Application schemas with status enums in `backend/schemas/application.py`
- Implemented ApplicationService with final Python safety gate in `backend/services/applications/service.py`
  - Safety gate validates: job existence, profile confirmation, duplicate protection, location, experience, salary, employment type, job title scope, AI suspicious flag, AI recommendation
  - Gemini output is advisory; Python rules are authoritative
  - External application recording (does NOT submit external applications)
  - Application failure/skip recording with reasons
- Extended NaukriAdapter with application submission methods in `backend/services/naukri/adapter.py`
  - `open_job_page()`: Opens job page with security checks
  - `detect_application_type()`: Detects NAUKRI_NATIVE vs EXTERNAL
  - `start_application()`: Clicks apply button
  - `detect_application_questions()`: Finds application questions
  - `answer_question()`: Answers questions from profile/AI
  - `submit_application()`: Submits form
  - `confirm_submission()`: Confirms success
  - `get_external_redirect_url()`: Gets external redirect URL
- Implemented ApplicationRunner in `backend/services/applications/runner.py`
  - Processes jobs sequentially with safety gate enforcement
  - Coordinates job → matching → AI analysis → safety gate → Naukri adapter → application → persistence
  - Handles external redirects, security failures, authentication failures
  - Answers questions from profile data first, then AI-generated answers
  - Continues after safe single-job failures, stops on security/critical conditions
- Created application API routes in `backend/api/routes/application.py`
  - POST /api/applications/start: Start application for a job
  - GET /api/applications/{id}: Get application by ID
  - PUT /api/applications/{id}: Update application
  - GET /api/applications/job/{job_id}: Get application by job
  - GET /api/applications/history: Get application history
  - POST /api/applications/run: Start application runner (background task)
  - POST /api/applications/stop: Request graceful stop
- Registered application router in `backend/main.py`
- Extended AgentStateManager to support APPLYING state transitions
- Created comprehensive tests (34 new tests):
  - Safety gate tests (9 tests): location, experience, salary, profile confirmation, suspicious job, AI needs attention, employment type, job title scope
  - Application flow tests (11 tests): create, get, update, external application, failure recording, skip recording, history
  - Duplicate protection tests (5 tests): no existing, applied, submitted, skipped, needs attention, external
  - Application runner tests (9 tests): single job, external application, critical browser failure, idle state requirement, no profile, no preferences
- Total: 101 tests passing

Application Pipeline:
```text
Discovered Job
    ↓
Phase 4 Hard Filters
    ↓
Gemini Job Analysis
    ↓
Python Final Safety Gate (authoritative)
    ↓
Application Started
    ↓
Naukri-native Application (via NaukriAdapter)
    ↓
Answer Questions (profile data first, then AI)
    ↓
Submit
    ↓
Record Result (APPLIED/SUBMITTED/EXTERNAL/NEEDS_ATTENTION)
```

Key Design Decisions:
- Gemini is advisory only; Python safety gate is authoritative
- External applications are NOT submitted, only recorded
- Questions answered from confirmed profile data first, then AI-generated
- Never invent user qualifications, experience, or salary
- Security challenges (CAPTCHA, human verification) halt the agent
- Duplicate protection prevents re-application
- Sequential job processing (no parallel submission)

Known limitations:
- Live Naukri validation still required for real CSS selectors, job application flow, question detection, submission confirmation, and complete real-site application submission
- Application question answering uses basic profile matching; complex question understanding may need refinement
- External redirect detection uses heuristics; may need adjustment for Naukri's actual implementation

Next Phase: Phase 7 - Scheduler & Cloud Execution

## Phase 5: COMPLETE - Naukri Job Discovery & Automation

Implemented Phase 5:

- Added Playwright dependency for browser automation
- Implemented NaukriAdapter with Chrome/Edge browser selection and graceful fallback
- Enhanced security detection (CAPTCHA, human verification, blocked access, login required)
- Implemented job extraction from Naukri search pages with page_number tracking
- Added posted_at extraction with basic parsing (today, yesterday, just now)
- Added employment_type extraction
- Implemented job description fetching from individual job pages
- Integrated DiscoveryService with NaukriAdapter for complete discovery pipeline
- Implemented deduplication by external_job_id, URL, and title+company
- Added timezone-aware timestamps (UTC) for all datetime fields
- Implemented pages_processed tracking in DiscoveryRun statistics
- Configured discovery state transitions (COMPLETED, AUTH_REQUIRED, SECURITY_REQUIRED, FAILED, STOPPED)
- Added comprehensive integration tests (67 total tests passing)
- Configured background task DB session handling for API routes

Discovery Pipeline:
```text
NaukriAdapter (Playwright)
    ↓
DiscoveryService
    ↓
normalization
    ↓
deduplication
    ↓
persistence (SQLite)
    ↓
DiscoveryRun statistics
    ↓
AgentState/DiscoveryRun lifecycle
```

Known limitations:
- Live Naukri validation still required for CSS selectors, real job extraction, pagination, posted date formats, browser channels, persistent authenticated session, real security/CAPTCHA detection, and complete real-site discovery flow
- Posted date parsing currently handles only "today", "yesterday", "just now" - more complex formats return None
- Automatic application submission is NOT implemented (Phase 6)
- Scheduler is NOT implemented (Phase 7)

Next Phase: Phase 6 - Naukri-native Application Automation

## Phase 4: COMPLETE - Job Matching & Rules Engine

Implemented Phase 4:

- Designed strict deterministic matching pipelines enforcing hard rules for Experience, Location, Salary, Employment Types, and scoping.
- Added string normalizer `backend/services/matching/normalizer.py` to interpret "LPA", "Bengaluru", and relative experience blocks accurately.
- Built central `MatchEngine` to evaluate candidate jobs directly against SQLite Job Preferences.
- Configured final AI delegation ensuring Gemini is strictly invoked only for Semantic/Skill Analysis *after* all deterministic filters explicitly pass.
- Integrated `JobPreferences` API routes, enabling settings overrides like App limits and Aggressiveness.
- Implemented `JobPreferences.tsx` locally mapping UI elements to backend matching filters cleanly.
- Unit tested all deterministic filters; integration pipeline successful, with all bounds enforcing no unauthorized bypassing.
- Next Phase: Phase 5 - Job Discovery & Automation (Playwright integrations).

## Phase 3: COMPLETE - Gemini AI Engine

Implemented Phase 3:

- Rebuilt the corrupted Windows frontend `node_modules` via clean NPM install, resolving the Vite 8 Rolldown binding error.
- Successfully built `AIStatus` tracking metrics in the frontend dashboard App.
- Upgraded the `GeminiProvider` utilizing the official `google-genai` SDK within `backend/services/gemini/provider.py`.
- Enforced strict AI output boundaries via `GenerateContentConfig` tied to Pydantic schemas.
- Provided structured models arrays in `backend/schemas/ai.py` (e.g. `JobAnalysis`, `ApplicationAnswer`).
- Constructed database entity mapping for `JobAnalysis` caching and `AIUsage` tracking.
- Secured AI invocation timeouts, request retries, and quota-aware exception monitoring.
- 16 passing backend unit tests confirming AI boundaries, models, and profile functionality.

Next phase: Phase 4 - Matching & Rules Engine.

## Phase 2: COMPLETE

Implemented Phase 2:

- Safe PDF upload validation, SHA-256 duplicate detection, controlled local storage, and PyMuPDF text extraction.
- Profile/Resume SQLAlchemy models, strict Pydantic profile contracts, review status, edits, and explicit confirmation persistence.
- Narrow source-grounded Gemini profile extraction boundary. It requires `GEMINI_API_KEY`; malformed or failed output leaves the uploaded resume in `ERROR`, never a fabricated profile.
- Profile API: `POST /api/profile/resume`, `GET /api/profile`, `PUT /api/profile`, and `POST /api/profile/confirm`.
- Frontend profile workspace with upload, status, editable core facts/skills, save, and confirm operations.
- Backend tests pass, including PDF extraction, invalid uploads, duplicate uploads, failed extraction preservation, edits, and confirmation.

Next phase: Phase 3 - Gemini AI Engine.

## Phase 1: COMPLETE

Completed:

- FastAPI health API, typed settings, CORS, structured logging, error taxonomy, and SQLite/SQLAlchemy foundation.
- Typed agent-state and controlled provider/platform adapter boundaries.
- Vite React/TypeScript/Tailwind dashboard shell with live backend health display.
- Python test foundation for health, configuration defaults, and state transitions.
- README, architecture documentation, and decision log.

Files created include `backend/`, `frontend/`, `requirements.txt`, `.env.example`, `.gitignore`, `run.py`, and the Phase 1 documentation files.

Database changes: the SQLite engine and metadata initialization are present; no product-domain tables are introduced yet.

Known limitations: no resume handling, Gemini API calls, job discovery, browser automation, scheduling, job rules, application actions, notifications, or packaging. The dashboard intentionally reports only foundation-level status.

Next phase: Phase 2 - Resume & User Profile.
