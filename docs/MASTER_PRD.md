# Naukri AI Job Application Agent

## E5-R5.2 - Truthful Application Outcomes and Bounded Error Recovery

**Status:** E5-R5.2 IMPLEMENTED, TESTED, AND VERIFIED (offline only; all tests mocked). No live validation.

**Contract changes:**

1. **`SUBMITTED_UNCONFIRMED` is a first-class outcome.** A submit click without positive `confirm_submission()` evidence persists the existing truthful `SUBMITTED` database status (history and `applied_at` semantics unchanged; no retry or resubmission) and reports `SUBMITTED_UNCONFIRMED` - never `APPLIED`. Runner and cycle results carry a dedicated `submitted_unconfirmed` count; the cycle budget (`applications_count`) and the "Applied" summary line count only confirmed `APPLIED`. `AutonomousCycleRunResponse.stats` is a free-form dict, so the new key is additive with no schema or breaking API change.
2. **Bounded runner-error tolerance.** The first isolated runner `ERROR` is recorded and the candidate loop continues; a second consecutive `ERROR` aborts with `stop_reason = "Two consecutive runner errors; aborting remaining candidates"` (exit code 3 / FAILED). Any valid non-ERROR outcome resets the counter; per-candidate exceptions neither increment nor reset it. `SECURITY_REQUIRED`, `AUTH_REQUIRED`, CRITICAL_ERROR state handling, `max_applications`, duplicate safeguards, safety gates, and hourly/daily limits remain authoritative. No infinite retries or restart loops.

**Unchanged:** confirmed `APPLIED` still requires positive visible evidence end to end (adapter evidence scan -> runner re-check with stored `confirmation_evidence` -> budget increment).

**Tests:** 10 new mocked tests (`test_autonomous_cycle_outcomes.py` x8, `test_application_runner.py` +2); `test_execution_error_stops_cycle_and_reports_failure` updated to the two-consecutive-error contract. Focused 130 passed; full backend suite **914 passed, 0 failed**.

**Live-only uncertainties:** remote success of an unconfirmed submission (SUBMITTED rows remain for manual review); live occurrence of an isolated session-start ERROR and runtime recovery for the next candidate.

---

## E5-R4.3 - Offline Chromium DOM Regression Tests (optional)

**Status:** E5-R4.3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live validation - no autonomous cycle, no browser against Naukri, no Apply click, no submit, no DB/retry/preference writes.

**Contract:** the apply-flow detection logic must be verifiable without touching Naukri. `backend/tests/test_naukri_adapter_offline_dom.py` (9 tests) runs the real adapter's read-only methods against real Chromium DOM semantics using `page.set_content()` of (a) the saved job-page snapshot `data/job_page_snapshot.html` and (b) a controlled synthetic page. Headless Chromium only, no persistent/login profile, all requests aborted at the context level (zero network egress), no live URL loaded, and no Apply control clicked (the popup-observer probe uses a neutral local button opening `about:blank`).

**Verified offline:** indicator scanning (native on the real page with no false-EXTERNAL log; external with attribution on the synthetic page), header Apply-button selection over the duplicate-ID ambiguity, external URL grounding (None on real page-chrome links; example CTA returned and facebook footer rejected), applied-state and container detection in both scan modes, evidence screenshot capture under `tmp_path`, security gate on a normal page, and both popup-observer outcomes (`new_tab_detected=yes|no`). A deliberate-violation run (3 injected regressions, out-of-repo throwaway file) confirmed the assertions fail when the behavior is broken (3 failed, exit 1).

**Optional by design:** skipped via `pytest.importorskip("playwright")` and a Chromium-launch skip with a clear reason; the normal backend suite does not depend on Chromium. Prerequisite: `playwright install chromium`.

**Results:** focused file 9 passed (19.51s); full backend suite **904 passed, 0 failed** (400.36s; baseline 895 + 9).

**Not verified offline (live-only):** whether Naukri's real Apply click opens a popup; server-side instant-apply persistence behind the D5 reload decision; real click/redirect timing; live security challenges; DOM drift vs the 2026-10-02 snapshot; auth/session-gated rendering. A live cycle requires separate explicit approval.

---

## E5-R4.2 - Run #59 Validation Instrumentation (prepared; backend restarted on approval)

**Status:** E5-R4.2 IMPLEMENTED, TESTED, AND SERVED. Backend restarted on 2026-10-10 10:48:32 with explicit approval; no live validation executed (no cycle, no browser, no Apply click).

**Observability contract for the next controlled run (read-only; no application behavior change):**

1. An `EXTERNAL` classification logs the matched `external_text_indicators` phrase and the page URL; the persisted `external_url` decision logs the CTA link's visible text and href when one matches, or the explicit fallback to `job.url` when none does; the runner logs `job_id` with the recorded URL.
2. Around the native Apply click the adapter logs the page URL before and after the click.
3. A popup/new tab opened by the click is observed with a bounded `wait_for_event("page", ...)` covering the post-click window, reload settle, and 5s grace, and reported as `new_tab_detected=yes|no`. Observation is read-only: no click, fill, navigation, or close on the observed page.
4. Every bounded-window iteration logs `post-click check #N at +X.XXs: applied=... container=...`, and the window logs its elapsed time and check count on close, so the 8-second bound is auditable per run.
5. Terminal `NEEDS_ATTENTION` exits log `terminal_state=NEEDS_ATTENTION` with a screenshot path; the PNG is written under `data/` (`data/apply_terminal_<label>_<stamp>.png`, already covered by the `data/*.png` ignore rule).

**Unchanged:** `APPLIED` still requires positive visible evidence; external applications are never clicked or submitted; security checks still run after the click and after the reload; safety gates, duplicate protection, `max_applications`, hourly/daily limits, preferences, and all application/retry-queue records are untouched.

**Runtime state:** the pre-restart backend (PID 18732 / child 22596, started 08:39:13 without `--reload`) predates the adapter edits (09:26:54) and did not serve E5-R4.1/E5-R4.2 code. On explicit approval it was stopped, port 8000 was confirmed free, and a new backend was started at 10:48:32 as PID 25760 with the same no-`--reload` command. Post-restart read-only verification: `/api/health` → `ok` / `IDLE`; `/api/readiness` → all components healthy; `/api/autonomous-cycle/status` → `IDLE` with no active run; scheduler not running (`backend/main.py:81` does not auto-start it); startup recovery completed with no errors; the log shows only dashboard status polling - no apply, discovery, or click activity.

**Test coverage:** 6 new instrumentation tests; adapter suite 143 passed; full backend suite **895 passed, 0 failed**.

---

## E5-R4.1 - Run #59 Post-Click Window & External Evidence Grounding


**Status:** E5-R4.1 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live cycle run - awaiting human review.

**Contract changes:**

1. **Bounded post-click window is observable.** After a native Apply click, `start_application()` polls header/banner Applied evidence and the visible application-container check inside the configured 8-second window (`post_apply_timeout_seconds`), and runs the page-wide element scan exactly once after the window, before the single bounded reload. The window overran in Run #59 because that page-wide scan ran first in every iteration (Apply click `03:12:49.075` to reload decision `03:13:02.379` = 13.3s for an 8s bound), starving the container check. `detect_applied_state(page, scan_whole_page=...)` exposes the split; the terminal `NEEDS_ATTENTION` log records `page.url`.
2. **External URLs are evidence, not page chrome.** An `EXTERNAL_APPLICATION` row's `external_url` is populated only from a non-Naukri link whose visible text matches the shared `external_text_indicators` vocabulary; otherwise `job.url` is recorded. Run #59's three external rows and 16 of the 19 older external rows carry one identical AmbitionBox promo URL and the last one a Naukri Facebook URL, because the old implementation returned the first non-Naukri anchor on the page. Classification now logs the matched indicator so an `EXTERNAL` outcome is attributable in the run log.

**Unchanged:** native/external classification precedence and external-first ordering; external jobs are never clicked or submitted; `APPLIED` is never recorded without confirmation evidence; final safety gates, duplicate protection, `max_applications`, hourly/daily application limits, and saved preferences; the `external_url`/`confirmation_evidence` exposure rules in dashboard schemas.

**Run #59 outcome (2026-10-10, `max_applications = 2`):** 79 discovered, 62 hard-filtered, 17 pre-analyzed, 5 candidates, 0 genuine native applications - 3 `EXTERNAL_APPLICATION` (jobs 55/57/86), 1 `NEEDS_ATTENTION` (job 87), 1 skipped. No application row, retry queue, preference, limit, or database record was modified by this checkpoint.

**Test coverage:** 9 new focused tests; adapter suite 137 passed; runner/flow/safety/cycle/AI 187 passed; full backend suite **889 passed, 0 failed**.

**Open item:** job 87's apply surface did not appear in the main page (no Applied badge after the reload, no visible container matching the existing selectors, no login/CAPTCHA text). No selector was guessed; the failure remains to be attributed by the next controlled run.

---

## E5-R3 — Freshness-First Discovery & Advisory-Only AI Recommendations

**Status:** E5-R3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live cycle run — awaiting human review.

**E5-R3 Summary:**

The final safety gate treated Gemini's subjective `NEEDS_ATTENTION` recommendation as if it were proof of fraud, rejecting jobs that matched the user's saved preferences and passed every deterministic rule. Separately, discovery counted every scanned card against its scan budget and the cycle ordered candidates by raw `discovered_at`, so duplicate-heavy search pages could consume the budget and leave fresh eligible jobs unprocessed. E5-R3 removes the subjective block and makes discovery and candidate selection freshness-first.

**Implementation:**

1. `backend/services/applications/service.py` — `run_final_safety_gate()` no longer blocks on the AI recommendation. Gemini remains advisory; the only AI-derived block is the explicit `job_analysis.suspicious` fraud flag. Every deterministic gate is unchanged and authoritative: confirmed profile, duplicate/`APPLIED` protection, location, fresher/experience, IT-scope, salary minimum, employment type, and title/search scope. Unused `AIRecommendation` import removed.
2. `backend/services/naukri/adapter.py` — `_parse_posted_date()` returns timezone-aware UTC datetimes for `today`/`just now`, `yesterday`, `N days/weeks ago`, `30+ days ago` (30 days), and absolute formats (`%d %b %Y`, `%d %B %Y`, `%d-%m-%Y`, `%Y-%m-%d`); unrecognised text returns `None` (never fabricated). Per-page results are emitted freshness-first (`_posted_sort_key`: known dates newest-first, unknown last). No Naukri URL/sort parameter or pagination change.
3. `backend/services/discovery/service.py` — the scan budget (`max_cards`) now counts **new distinct jobs**, not all scanned cards, so duplicates cannot starve fresh jobs. `_refresh_duplicate_job()` advances `last_seen` and adopts only a newer grounded `posted_at`.
4. `backend/services/autonomous_cycle/service.py` — freshness-first ordering via `posted_freshness_key()` / `job_freshness_key()`. `_apply_hard_filters_and_enqueue()` prioritizes the newest-posted eligible jobs (unknown last), then `discovered_at` and `match_score`, so the bounded Gemini budget targets the freshest candidates. `_run_applications()` processes newest-posted candidates first (nulls last).

**Constraints honored:** no saved-preference changes; no hard-filter, duplicate-protection, safety-check, or configured-limit bypass; unknown posting dates never invented; no live Naukri cycle, browser, Apply click, or Gemini call; no database writes; no commit/push.

**Test Coverage:**

- `backend/tests/test_application_safety_gate.py` — 20 PASS (subjective `NEEDS_ATTENTION`/`SKIP` allowed; suspicious still blocked; deterministic rules still authoritative)
- `backend/tests/test_naukri_adapter.py` — 128 PASS (expanded date parsing, freshness ordering, page advancement)
- `backend/tests/test_discovery.py` — 15 PASS (newer `posted_at` refresh, unknown-no-overwrite, duplicate starvation)
- `backend/tests/test_autonomous_cycle.py` — 104 + new `TestFreshnessFirstOrdering` (3 tests), all PASS
- Focused run of the four files: **270 passed**. Full backend suite: **875 passed, 2 failed** — both pre-existing and unrelated (`test_checkpoint_c2_policy.py::test_it_scope_is_deterministic` on unmodified `matching/engine.py`; `test_dashboard.py::TestDashboardSummaryEmpty::test_empty_discovery_has_zero_counts`, a test-ordering isolation case that passes alone). Zero regressions.

**Files Modified:**
- `backend/services/applications/service.py`
- `backend/services/naukri/adapter.py`
- `backend/services/discovery/service.py`
- `backend/services/autonomous_cycle/service.py`
- `backend/tests/test_application_safety_gate.py`
- `backend/tests/test_naukri_adapter.py`
- `backend/tests/test_discovery.py`
- `backend/tests/test_autonomous_cycle.py`

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

**Remaining limitations:** only the Naukri card date renderings above are parsed (anything else stays `None`); Gemini may still label a good job `NEEDS_ATTENTION` at the analysis stage (advisory only); no live endpoint validation was performed.

## E4-R10 — Targeted Role-Matching Improvement

**Status:** E4-R10 IMPLEMENTED, TESTED, AND VERIFIED

**E4-R10 Summary:**

E4-R10 improves deterministic role matching so clearly relevant entry-level software and data roles are not rejected merely because their titles use reasonable variations of existing target-role names. The goal is greater relevant-job coverage, not simply more candidates.

**Reconciliation (completed before implementation):**
- NO_MATCHING_FAMILY count discrepancy resolved: script listed 37 IDs, not 38. All 37 jobs exist in the database.
- UNWANTED_SPECIALIZATION count: all 15 jobs exist in the database. No discrepancy.
- E4-R9 report was partially incorrect: "Associate Software Engineer", "Associate Developer Trainee", and "Python Developer" roles already PASS role-matching under production code (they match "software engineer", "developer", and "python developer" keywords respectively).

**Verified role-matching failures (5 jobs):**
1. Job 55: "Software Development Trainee" - User preference: "Software Developer Trainee", but code required "software developer" (noun) not "software development" (gerund)
2. Job 62: "Data Science Intern/Fresher" - User has "Data Analyst Fresher" and "Data Engineer Fresher", but no "data science" keyword in ALLOWED_ROLE_FAMILIES
3. Job 64: "Power Bi Internship _ For Freshers" - User has "Junior Data Analyst", but no "power bi" keyword
4. Job 87: "Qa Engineer" - User has "QA Engineer Fresher", but no "qa" keyword in ALLOWED_ROLE_FAMILIES
5. Job 112: "ELK Engineer" - Not in user preferences, but is DevOps/monitoring-related (not addressed in this checkpoint)

**Implementation:**

Extended `ALLOWED_ROLE_FAMILIES` in `backend/services/matching/engine.py`:
- Added "data science" and "power bi" to data family
- Added "software development" to software family
- Added new "qa" family with "qa" and "quality assurance"
- Added new "sql" family with "sql developer" (standalone "sql" excluded to prevent SQL Server Administrator matches)

**Constraints honored:**
- Did NOT add "associate" as a standalone catch-all keyword
- Did NOT admit pure sales, HR, mechanical, manufacturing, or operations jobs
- Did NOT weaken IT-scope filter, experience cap, salary policy, or employment-type policy
- Did NOT remove "sales" from UNWANTED_SPECIALIZATIONS
- Did NOT lower salary threshold
- Did NOT change candidate profile facts or preferences
- Did NOT change AI recommendations or final application safety gate

**Test Coverage:**
- 10 new tests for role-matching improvements: software development trainee, data science roles, power bi roles, qa roles, sql roles
- 9 new regression tests: SQL Server Administrator exclusion, boundary cases (sales mention in tech role, hardware with software), pure sales, mechanical, manufacturing, HR, operations roles
- Total: 54 tests in test_matching_rules.py — all PASS
- All verified failing jobs now PASS role-matching:
  - Job 55 (Software Development Trainee): PASS
  - Job 62 (Data Science Intern/Fresher): PASS
  - Job 64 (Power Bi Internship): PASS
  - Job 87 (Qa Engineer): PASS
  - Job 112 (ELK Engineer): FAIL (not in user preferences, DevOps/monitoring-specific, requires separate decision)

**Files Modified:**
- `backend/services/matching/engine.py` (ALLOWED_ROLE_FAMILIES extended)
- `backend/tests/test_matching_rules.py` (18 new tests)

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

---

## E4 — Dashboard Live-Run Outcome (Run #52)

**Status: E4 LIVE CYCLE EXECUTED — runtime/dashboard validation PASSED; application-submission objective UNRESOLVED.**

This checkpoint documents the actual outcome of the E4 live cycle (Run #52) triggered through the Dashboard UI. It is documentation and Git only: no new autonomous cycle was executed, no source code was modified, and no database was modified during this checkpoint.

**Verified Run #52 result (triggered by Dashboard UI):**

- Trigger: Dashboard UI "Run Autonomous Cycle" button with `max_applications = 1`.
- Run ID: `52`.
- Discovery run ID: `52`.
- Terminal status: `COMPLETED`.
- Jobs discovered: `103`.
- Jobs processed from the current run: `81`.
- Candidates considered for application: `3`.
- New applications submitted during Run #52: `0`.
- Apply clicks during Run #52: `0`.
- Runtime returned to `IDLE`, with `lock_held = false`.

**Distinction between successful execution and zero applications:**

- The cycle executed end-to-end: discovery, filtering, candidate evaluation, and safe completion. The runtime returned to `IDLE` and released its lock. The Dashboard UI, control/status APIs, non-reload Uvicorn runtime, and `max_applications = 1` control all behaved as designed. Runtime/dashboard validation therefore PASSED.
- However, zero applications were submitted during Run #52. The three candidates considered did not reach a safe native Apply click. The application-submission objective remains UNRESOLVED and is recorded as an open issue for a separate investigation checkpoint.
- The three existing applications referenced in earlier reports (records #18, #24, #25) belong to earlier runs (D4/D5 and D7), NOT to Run #52. They are preserved and unaltered.

**Open issue (carried forward):** Why did Run #52 submit zero applications despite successful execution? Root cause has not been determined. Investigation is deferred to a separate checkpoint after this push. Do not claim the application objective was achieved.

**Historical E4 records preserved:** The two accidental curl-triggered E4 attempts on 2026-10-08 that failed before browser startup remain preserved and unaltered. Run #52 is the first E4 cycle to execute end-to-end through the Dashboard UI.

## E4-R2 — Windows Playwright Runtime Requirement (Documentation Only)

E4 live validation has **NOT** yet succeeded. This checkpoint documents the runtime/environment requirement discovered during E4 validation and resolves the E4 browser-startup blocker. It is documentation-only: no E4 execution occurred, no Dashboard Run was clicked, no `POST /api/autonomous-cycle/run` was called, no database was modified, no backend/frontend source code was modified, no Playwright configuration was changed, and no asyncio workaround was added.

**Verified fact (Windows 11, Python 3.14.2, FastAPI 0.141.1, Starlette 1.6.0, Playwright 1.63.0):**

- Uvicorn with `--reload` → spawned reload worker uses `WindowsSelectorEventLoop` → Playwright subprocess bootstrap raises `NotImplementedError` → autonomous cycle fails immediately during browser startup.
- Uvicorn without `--reload` → `ProactorEventLoop` → Playwright driver starts successfully → configured Chromium persistent context starts successfully → standalone smoke test PASS.

The Playwright installation itself was healthy and the Chromium installation is healthy — the blocker was the event loop selected by the reload worker, not the browser installation.

**Resolution:**

- No source-code workaround was required.
- `--reload` is incompatible with the Windows Playwright subprocess requirement in this environment.
- Live autonomous execution must use non-reload Uvicorn. The correct live runtime invocation is:

  ```powershell
  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```

  WITHOUT `--reload`.

**E4 status tracking:**

- E4 live cycle has since EXECUTED end-to-end in Run #52 (triggered by Dashboard UI, `max_applications=1`, terminal status `COMPLETED`, `lock_held=false`). See the **E4 — Dashboard Live-Run Outcome (Run #52)** section at the top of this document.
- Runtime/dashboard validation PASSED; the application-submission objective remains UNRESOLVED (zero applications in Run #52). Investigation is deferred to a separate checkpoint.
- Historical E4 FAILED runs (including the two accidental curl-triggered attempts on 2026-10-08 that failed before browser startup) remain preserved and unaltered.
- The non-reload Uvicorn runtime requirement documented above was the runtime fix that made Run #52 possible.

**Do not claim the E4 application objective was achieved.** Describe E4 as runtime/dashboard validation passed, with application submission still unresolved.

## E4-R — Autonomous Cycle Recovery & Execution-Safety Hardening

E4-R prepared the runtime state model and recovery paths that Run #52 later exercised successfully. The two accidental curl-triggered attempts on 2026-10-08 stopped before browser startup; no applications were created or submitted, no Apply click occurred, and no CAPTCHA/security event occurred. E4-R is a recovery/source-hardening checkpoint only and must not be treated as live validation. Runtime status represents only current activity (`IDLE`/`RUNNING`) and retains terminal outcomes as a distinct last-run history. Read-only diagnostics must never execute a cycle. Lock release and restart recovery require mocked/unit-level verification.

**Run #52 outcome:** The cycle started, acquired the lock (`active_state=RUNNING`), completed normally, and returned to `IDLE` with `lock_held=false`. The `COMPLETED` terminal status and zero-application outcome are recorded in `last_run`, distinct from the active state. See the **E4 — Dashboard Live-Run Outcome (Run #52)** section at the top of this document.

## CHECKPOINT E3: Safe Dashboard Autonomous-Cycle Control

**Status:** E3 IMPLEMENTED, TESTED, AND VERIFIED

**E3 Summary:**

E3 enables safe manual triggering of the autonomous job application cycle from the dashboard, reusing the existing `AutonomousCycleService` extracted from the CLI. The dashboard now provides explicit user confirmation, status polling, and completion statistics while preserving all safety boundaries.

**E3 Scope:**
- Safe manual autonomous-cycle trigger from dashboard with user confirmation
- POST `/api/autonomous-cycle/run` with `max_applications` parameter (1-10, default 1)
- Dashboard confirmation modal includes a selectable Maximum applications control (1-10), defaulting to 1
- GET `/api/autonomous-cycle/status` for real-time cycle status
- Process-level concurrency lock (threading.Lock) to prevent concurrent cycles
- Dashboard status polling at 4-second intervals while cycle is RUNNING
- Dashboard data refresh after cycle completion
- No new automation logic — reuses existing `AutonomousCycleService`
- Scheduler remains discovery-only (integration deferred)
- No live Naukri execution performed during implementation/testing
- D7 PASS result preserved
- E2 COMPLETE result preserved
- E1 COMPLETE result preserved

**New Backend Endpoints:**

| Endpoint | Method | Description |
|---|---|---|
| `POST /api/autonomous-cycle/run` | POST | Start autonomous cycle with max_applications limit |
| `GET /api/autonomous-cycle/status` | GET | Get current autonomous cycle status |

**Request/Response Schemas:**

- `AutonomousCycleStartRequest`: `max_applications` (1-10, default 1)
- `AutonomousCycleStartResponse`: `run_id`, `status`, `max_applications`, `message`
- `AutonomousCycleStatusResponse`: `status` (IDLE/RUNNING/COMPLETED/FAILED), `run_id`, `started_at`, `completed_at`, `max_applications`, `stats`

**Safety Guarantees:**
- Server-authoritative `max_applications` (client cannot control Gemini budget)
- Process-level concurrency lock prevents concurrent cycles
- HTTP 409 Conflict returned if cycle already running
- All safety boundaries preserved: D6.1, D6.2, C2, D4/D5, D7
- Gemini budget internally derived as `max_applications * 2`
- Frontend only calls control/status APIs — no direct Naukri or Gemini access

**Frontend Changes:**
- Autonomous Cycle status panel: shows IDLE/RUNNING/COMPLETED/FAILED state
- Run Autonomous Cycle button with explicit confirmation modal
- Confirmation modal explains: real Naukri applications, max_applications limit, safety rules, concurrency protection
- Confirmation modal includes a selectable Maximum applications dropdown (1-10) with default 1; the value is sent as `max_applications` to `POST /api/autonomous-cycle/run`
- Status polling at 4-second intervals while RUNNING
- Dashboard data refresh (summary, recent apps, needs attention) after COMPLETED/FAILED
- Completion stats display: applied, needs_attention, external applications
- HTTP 409 Conflict handling: shows "An autonomous cycle is already running" message
- No accidental one-click trigger — requires explicit user confirmation

**Test Coverage:**
- 92 tests in `backend/tests/test_autonomous_cycle.py` (E3 autonomous cycle logic tests)
- 11 tests in `backend/tests/test_autonomous_cycle_api.py` (E3 API endpoint tests)
- 30 tests in `backend/tests/test_dashboard.py` (E1/E2 dashboard tests)
- 181 total tests: autonomous_cycle + matching_rules + application_safety_gate + dashboard
- All 181 tests: PASS
- Frontend TypeScript compilation: PASS
- Frontend production build: PASS (23.76s, 280.60 kB JS bundle)
- No Gemini calls during tests. No live Naukri applications.

**Security Review:**
- `AutonomousCycleStartRequest` uses `extra="forbid"` — Pydantic strict mode
- No `gemini_budget` parameter in request schema — client cannot control Gemini budget
- `max_applications` validated (1-10) and server-authoritative
- No secrets exposed in any response: no GEMINI_API_KEY, no Naukri credentials, no cookies, no session tokens
- Process-level lock prevents concurrent cycles (V1 local-first)
- Frontend only calls POST/GET endpoints — no direct service access

**Files Added:**
- `backend/services/autonomous_cycle/service.py` — extracted `AutonomousCycle` class (E3)
- `backend/api/routes/autonomous_cycle.py` — autonomous cycle control endpoints (E3)
- `backend/schemas/autonomous_cycle.py` — request/response schemas (E3)
- `backend/tests/test_autonomous_cycle.py` — 92 autonomous cycle logic tests (E3)
- `backend/tests/test_autonomous_cycle_api.py` — 11 API endpoint tests (E3)

**Files Modified:**
- `backend/main.py` — registered autonomous_cycle router (E3)
- `backend/tests/conftest.py` — autonomous_cycle router registration for tests (E3)
- `run_autonomous_cycle.py` — refactored to use extracted `AutonomousCycle` (E3)
- `frontend/src/types/api.ts` — added autonomous cycle types (E3)
- `frontend/src/services/api.ts` — added autonomous cycle API client methods (E3)
- `frontend/src/app/App.tsx` — added autonomous cycle UI with confirmation, polling, completion stats (E3)

**Preserved Features:**
- D6.1 Gemini look-ahead budget (max_applications * 2)
- D6.2 Gemini candidate evaluation budget
- current-run queue isolation
- deterministic filtering
- candidate ordering (match_score desc, discovered_at desc)
- C2 fresher-only policy
- C2 IT-only policy
- max_applications hard cap
- duplicate protection
- external application boundary
- questionnaire boundary
- CAPTCHA/security boundary
- D4/D5 Apply/evidence behavior

**E3 Live Validation (Run #52, 2026-10-09):** The E3 control surface was exercised end-to-end through the Dashboard UI with `max_applications = 1`. The cycle started, acquired the lock, ran discovery/filtering/candidate evaluation, completed with status `COMPLETED`, and returned to `IDLE` with `lock_held = false`. This confirms the confirmation modal, selectable `max_applications` control, status polling, completion stats, and HTTP 409 concurrency protection all behave as designed in a live run. Zero applications were submitted in Run #52; the three pre-existing applications (records #18, #24, #25) belong to earlier runs (D4/D5 and D7) and were untouched. See the **E4 — Dashboard Live-Run Outcome (Run #52)** section at the top of this document.

---

## CHECKPOINT E2: Dashboard Operational Visibility & Safe Control Foundation

**Status:** E2 IMPLEMENTED, TESTED, AND VERIFIED

**E2 Summary:**

E2 builds on E1's real backend → frontend integration to make the dashboard an accurate operational view of the Naukri Agent. The dashboard now provides visibility into what the system last did, what happened during the latest discovery/autonomous run, application outcomes, jobs needing attention, and system health status.

**E2 Scope:**
- Read-only from the frontend's perspective. No automation triggered from the dashboard.
- No new Naukri automation behavior. No changes to Apply logic, Gemini budgets, or matching rules.
- No live Naukri application performed.
- D7 PASS result preserved.
- E1 COMPLETE result preserved.

**New Backend Endpoints:**

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/dashboard/summary` | GET | Discovery stats, application status counts, profile status (E1) |
| `GET /api/dashboard/recent-applications` | GET | Recent applications enriched with job title + company (E1) |
| `GET /api/dashboard/needs-attention` | GET | Applications requiring user review (E2) |

**Data Exposed (read-only, no secrets):**
- Latest completed discovery run: `run_id`, `status`, `started_at`, `completed_at`, `jobs_discovered`, `new_jobs`, `pages_processed`, `total_runs` (E1)
- Application counts (all-time): `total`, `applied`, `needs_attention`, `skipped`, `external_application`, `failed` (E1)
- Profile summary: `status`, `confirmed`, `original_filename` — no `resume_hash`, no profile data fields, no API keys (E1)
- Recent applications: `job_title`, `company`, `status`, `application_method`, `applied_at`, `skip_reason`, `needs_attention`, `is_dry_run` — no `confirmation_evidence`, no credentials (E1)
- Needs-attention items: `job_title`, `company`, `status`, `skip_reason`, `failure_reason`, `needs_attention` — no secrets, no browser data (E2)

**Data NOT Exposed:**
- `GEMINI_API_KEY` — never in any response
- Naukri credentials — never in any response
- Cookies, session tokens, browser data — never in any response
- `resume_hash`, `Profile.data` fields — excluded from dashboard schemas
- `confirmation_evidence` — internal applied-state evidence, excluded from recent-applications and needs-attention
- Database connection strings, environment variables, filesystem paths — never in any response

**Frontend Changes:**
- E1 metrics section: `Applied`, `Jobs discovered`, `Discovery runs`, `Needs attention` — all real values (E1)
- E1 profile panel: real `status` and `confirmed` from dashboard summary (E1)
- E1 activity feed (overview) and Activity page: real application records with job title/company (E1)
- E2 Latest Run section: shows latest discovery run status, ID, jobs discovered, new jobs, completion date (E2)
- E2 Needs Attention section: dedicated section for applications requiring user review with skip/failure reasons (E2)
- E2 Refresh button: manual refresh with loading state and visual feedback (E2)
- E2 improved System Health presentation: backend status, agent state from health endpoint (E2)
- Per-section loading/error/empty states — backend offline does not crash the dashboard (E1)
- Retry button re-fetches all dashboard data (E1)

**Test Coverage:**
- 30 tests in `backend/tests/test_dashboard.py` (21 E1 + 9 E2)
- E1 tests: empty DB, counts, job enrichment, limit capping, required fields, no-secrets check, read-only (405 on POST/PUT/DELETE)
- E2 tests: needs-attention filtering, limit capping, required fields, no-secrets check, read-only (405 on POST/PUT/DELETE)
- All 30 tests: PASS
- Key regression tests (41 tests across health, analytics, profile, database isolation): PASS
- Frontend TypeScript compilation: PASS
- Frontend production build: PASS (3.10s, 275.91 kB JS bundle)
- No Gemini calls during tests. No live Naukri applications.

**Security Review:**
- `DashboardSummary`, `RecentApplicationItem`, `NeedsAttentionItem` schemas use `extra="forbid"` — Pydantic strict mode prevents extra fields leaking
- `RecentApplicationItem` explicitly excludes `confirmation_evidence`, `external_url`, and all credential fields
- `NeedsAttentionItem` explicitly excludes `confirmation_evidence`, `external_url`, and all credential fields
- `ProfileSummary` explicitly excludes `resume_hash` and all `Profile.data` personal fields
- All dashboard endpoints are HTTP GET only — no mutations possible via these routes
- No environment variable values are read or serialised into responses

**Files Added:**
- `backend/api/routes/dashboard.py` — dashboard route implementations (E1, extended in E2)
- `backend/schemas/dashboard.py` — Pydantic schemas for dashboard responses (E1, extended in E2)
- `backend/tests/test_dashboard.py` — 30 endpoint tests (21 E1 + 9 E2)

**Files Modified:**
- `backend/main.py` — registered dashboard router (E1)
- `frontend/src/types/api.ts` — added dashboard types (E1), added needs-attention types (E2)
- `frontend/src/services/api.ts` — added dashboard client functions (E1), added needs-attention client function (E2)
- `frontend/src/app/App.tsx` — wired dashboard data into metrics, profile panel, activity feed (E1), added Latest Run section, Needs Attention section, Refresh button (E2)

---

## CHECKPOINT E1: Frontend/API Integration Foundation

**Status:** E1 IMPLEMENTED, TESTED, AND VERIFIED

**E1 Summary:**

Connected the existing React + TypeScript + Tailwind frontend dashboard to the already-proven FastAPI backend using real read-only API data. The dashboard no longer shows placeholder values such as "Not available" or "Not configured" — it reflects the actual backend state.

**E1 Scope:**
- Read-only from the frontend's perspective. No automation triggered from the dashboard.
- No new Naukri automation behavior. No changes to Apply logic, Gemini budgets, or matching rules.
- No live Naukri application performed.
- D7 PASS result preserved.

**New Backend Endpoints:**

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/dashboard/summary` | GET | Discovery stats, application status counts, profile status |
| `GET /api/dashboard/recent-applications` | GET | Recent applications enriched with job title + company |

**Data Exposed (read-only, no secrets):**
- Latest completed discovery run: `run_id`, `status`, `started_at`, `completed_at`, `jobs_discovered`, `new_jobs`, `pages_processed`, `total_runs`
- Application counts (all-time): `total`, `applied`, `needs_attention`, `skipped`, `external_application`, `failed`
- Profile summary: `status`, `confirmed`, `original_filename` — no `resume_hash`, no profile data fields, no API keys
- Recent applications: `job_title`, `company`, `status`, `application_method`, `applied_at`, `skip_reason`, `needs_attention`, `is_dry_run` — no `confirmation_evidence`, no credentials

**Data NOT Exposed:**
- `GEMINI_API_KEY` — never in any response
- Naukri credentials — never in any response
- Cookies, session tokens, browser data — never in any response
- `resume_hash`, `Profile.data` fields — excluded from dashboard schemas
- `confirmation_evidence` — internal applied-state evidence, excluded from recent-applications
- Database connection strings, environment variables, filesystem paths — never in any response

**Frontend Changes:**
- Replaced hardcoded metrics (`"Not available"`) with live values from `/api/dashboard/summary`
- Profile panel now uses real `status` and `confirmed` from dashboard summary
- Activity feed (overview) and Activity page now show real application records with job title/company
- Loading state (`…`), error state (`Unavailable` / error message), and empty state handled per section
- Backend-offline does not crash the dashboard — each section degrades independently
- Retry button re-fetches all dashboard data

**Test Coverage:**
- 21 new tests in `backend/tests/test_dashboard.py`
- Covers: empty DB, populated DB, counts, job-detail enrichment, limit capping, required fields, no-secrets check, read-only (405 on POST/PUT/DELETE)
- All 21 tests: PASS
- Key regression tests (95 tests across health, analytics, applications, profile, schema migration, database isolation): PASS
- Frontend TypeScript compilation: PASS
- Frontend production build: PASS (15.81s, 273.57 kB JS bundle)
- No Gemini calls during tests. No live Naukri applications.

**Security Review:**
- `DashboardSummary` schema uses `extra="forbid"` — Pydantic strict mode prevents extra fields leaking
- `RecentApplicationItem` explicitly excludes `confirmation_evidence`, `external_url`, and all credential fields
- `ProfileSummary` explicitly excludes `resume_hash` and all `Profile.data` personal fields
- All new endpoints are HTTP GET only
- No environment variable values are read or serialised into responses

**Files Added:**
- `backend/api/routes/dashboard.py` — dashboard route implementations
- `backend/schemas/dashboard.py` — Pydantic schemas for dashboard responses
- `backend/tests/test_dashboard.py` — 21 new endpoint tests

**Files Modified:**
- `backend/main.py` — registered dashboard router
- `frontend/src/types/api.ts` — added `DashboardSummary`, `ApplicationCounts`, `DashboardProfileSummary`, `RecentApplicationItem`, `RecentApplicationsResponse` types
- `frontend/src/services/api.ts` — added `getDashboardSummary()` and `getRecentApplications()` client functions
- `frontend/src/app/App.tsx` — wired dashboard data into metrics, profile panel, and activity feed

---

## CHECKPOINT D6.2: Bounded Gemini Candidate Evaluation

**Status:** D6.2 IMPLEMENTED AND TESTED

**D6.2 Summary:**

D6.1's Gemini budget was applied TOO LATE in the pipeline. The autonomous cycle was calling MatchEngine.evaluate_job() for every job that passed deterministic filters, and MatchEngine would invoke Gemini for each job before returning. Only AFTER those Gemini calls did the D6.1 enqueue budget get applied. This defeated the purpose of bounded Gemini usage.

**D6.2 Fix:**
- Moved the Gemini budget boundary BEFORE NEW MatchEngine semantic evaluation
- Added `evaluate_job_deterministic()` method to MatchEngine that runs only deterministic checks (no Gemini)
- Autonomous cycle now: deterministic filters → bounded candidate selection → Gemini evaluation for only bounded candidates
- Gemini budget formula: `max_applications * 2` (unchanged from D6.1)
- Application limit: `max_applications` (unchanged)
- Cached analyses do not consume NEW Gemini evaluation budget
- Deterministically rejected jobs never call Gemini

**D6.2 Implementation:**
- Added `MatchEngine.evaluate_job_deterministic()` method in `backend/services/matching/engine.py`
- Updated `run_autonomous_cycle.py` to use deterministic-only evaluation for candidate collection
- Applied Gemini budget (max_applications * 2) BEFORE enqueuing to AI queue
- Added 8 D6.2 regression tests to `test_autonomous_cycle.py`
- All existing D4/D5/D6.1 tests preserved and passing

**D6.2 Test Coverage:**
- 8 new D6.2 tests added
- Total: 98 tests passing in test_autonomous_cycle.py (90 autonomous_cycle + 8 D6.2)
- 0 failures

**Key D6.2 Tests:**
1. `test_deterministic_evaluation_passes_without_gemini` → deterministic evaluation works without Gemini
2. `test_deterministic_evaluation_fails_unpaid_job` → deterministic checks reject unpaid jobs
3. `test_gemini_budget_bounded_for_max_applications_2` → Gemini budget=4 for max_applications=2
4. `test_gemini_budget_for_max_applications_1` → Gemini budget=2 for max_applications=1
5. `test_gemini_budget_for_max_applications_3` → Gemini budget=6 for max_applications=3
6. `test_cached_analysis_not_counted_as_new_gemini` → cached analyses don't trigger new Gemini calls
7. `test_deterministic_rejects_no_gemini_call` → deterministically rejected jobs never call Gemini
8. `test_application_limit_separate_from_gemini_budget` → application limit separate from Gemini budget

**Gemini Safety:**
- NEW Gemini evaluations during autonomous cycle are now bounded BEFORE invocation
- For max_applications=1: NEW Gemini evaluations <= 2
- For max_applications=2: NEW Gemini evaluations <= 4
- For max_applications=3: NEW Gemini evaluations <= 6
- Deterministically rejected jobs never call Gemini
- Cached analyses do not cause NEW Gemini calls
- Application attempts remain hard-capped by max_applications
- Gemini remains advisory, Python rules remain final authority

**Note:** D7 live validation has NOT been performed as part of this checkpoint. D6.2 is a source implementation checkpoint only.

---

## CHECKPOINT D7: Multi-Application Live Validation

**Status:** D7 LIVE VALIDATION PASSED

**D7 Summary:**

D7 is a live validation checkpoint that verified the autonomous cycle can process multiple independent eligible Naukri candidates and apply to more than one job when safe candidates are available. The D6.2 Gemini boundary was validated in a real autonomous cycle with max_applications=2.

**D7 Live Validation (2026-10-07):**

Command: `python run_autonomous_cycle.py --max-applications 2`

Discovery:
- Discovery run #32
- Jobs discovered: 103
- Jobs hard filtered: 60
- Current-run candidates: 4 queued for AI (jobs 99, 86, 85, 59)

D6.2 Gemini Boundary Validation:
- Gemini budget: 4 (max_applications=2 × 2)
- NEW Gemini evaluations: 4 (exactly the budget)
- Candidates capped: 5 (jobs 58, 56, 51, 20, 19)
- Budget respected: YES

Current-Run Isolation:
- All 4 AI queue items from AUTONOMOUS_CYCLE source
- Pre-existing MANUAL/SCHEDULER queue items NOT consumed
- Current-run isolation: PASS

Gemini Results:
- Job 99 (Neorealm Solutions): SKIP - Python/Data Science vs C#/.NET mismatch
- Job 86 (Futureacad): NEEDS_ATTENTION - 3-month unpaid internship + 2-year bond
- Job 85 (Access Automation): SKIP - No LabVIEW experience
- Job 59 (Capgemini): SKIP - L1 support/voice process vs AI/DS background

Application Outcomes:
- Job 99 → EXTERNAL_APPLICATION (no external submission, Apply clicks: 0)
- Job 86 → SKIPPED (unpaid internship, Apply clicks: 0)
- Job 85 → APPLIED (native Naukri, 1 Apply click, application record #24, NAUKRI_NATIVE)
- Job 59 → APPLIED (native Naukri, 1 Apply click, application record #25, NAUKRI_NATIVE)

Final Results:
- APPLIED: 2
- NEEDS_ATTENTION: 1
- SKIPPED: 1
- EXTERNAL: 1
- FAILED: 0
- Apply clicks: 2 (exactly once per applied job)

Safety Verification:
- Duplicate protection: PASS (no reapplications)
- Current-run isolation: PASS (only current-run candidates processed)
- Pre-existing queue consumption: NONE
- CAPTCHA/security bypass: NONE
- Questionnaire/form bypass: NONE
- External application submission: NONE
- Fabricated answers: NONE
- max_applications hard cap: PASS (cycle stopped after 2 applications)

**D7 Verdict:** PASS — multiple applications validated

**Source Changes:** NONE (D7 is a validation checkpoint only)

**Database Backup:** data/naukri_agent.db.bak-before-d7-live (not committed)

---

## CHECKPOINT D6.1: Bounded Gemini Look-Ahead for Multi-Application Runs

**Status:** D6.1 IMPLEMENTED AND TESTED

**D6.1 Summary:**

D6 exposed a candidate-selection issue where `max_applications` was incorrectly used as both the Gemini candidate cap AND the actual application limit. This prevented the system from having backup candidates when initial candidates were rejected (EXTERNAL or NEEDS_ATTENTION).

**D6.1 Fix:**
- Separated Gemini candidate budget from actual application limit
- New formula: `max_gemini_candidates = max_applications * 2`
- This provides bounded look-ahead (backup candidates) while preventing uncontrolled Gemini usage
- Actual application attempts remain capped at `max_applications`

**D6.1 Implementation:**
- Modified `run_autonomous_cycle.py` enqueue logic to use `max_applications * 2` as Gemini budget
- Updated summary output to show both `max_applications` and `Gemini candidate budget`
- Added 11 D6.1 regression tests to `test_autonomous_cycle.py`
- All existing D4/D5 tests preserved and passing

**D6.1 Live Validation (2026-10-07):**
- Command: `python run_autonomous_cycle.py --max-applications 2`
- Result: 103 jobs discovered, 69 hard filtered, 11 pre-analyzed, 0 newly queued
- Cycle was safe: 0 Apply clicks, 0 new APPLIED
- No external applications submitted
- No questionnaires answered
- Application 18 (from D4/D5) correctly excluded
- Current-run isolation verified correct

**D6.1 Test Coverage:**
- 11 new D6.1 tests added
- Total: 261 tests passing (83 autonomous_cycle + 41 matching_rules + 119 naukri_adapter + 18 application_safety_gate)
- 0 failures

**Key D6.1 Tests:**
1. `test_d61_gemini_budget_max_applications_1` → Gemini budget=2
2. `test_d61_gemini_budget_max_applications_2` → Gemini budget=4
3. `test_d61_gemini_budget_max_applications_3` → Gemini budget=6
4. `test_d61_gemini_never_exceeds_bounded_budget` → 10 eligible, max_applications=2 → only 4 enqueued
5. `test_d61_actual_applications_never_exceed_max_applications` → application limit enforced separately
6. `test_d61_external_candidate_does_not_consume_slot` → EXTERNAL doesn't consume application slot
7. `test_d61_needs_attention_does_not_consume_slot` → NEEDS_ATTENTION doesn't consume application slot
8. `test_d61_rejected_candidate_allows_backup_evaluation` → backup candidates evaluated when earlier rejected
9. `test_d61_current_run_isolation_preserved` → current-run filtering still works
10. `test_d61_stale_queued_job_cannot_leak` → stale queue items don't leak into current run

**Current-Run Isolation Investigation:**
- D6 report discrepancy (104 vs 81 jobs) explained: discovery reports 104 total (1 new + 103 duplicates), but only 81 unique job IDs in current_run_job_ids
- Job 107 was legitimately in current_run_job_ids (last 20 IDs included it)
- No isolation bug found - system correctly isolates current runs

**Gemini Safety:**
- Gemini budget remains explicitly bounded (max_applications * 2)
- No uncontrolled AI processing
- No fallback to AI-free application
- Existing quota exhaustion behavior preserved

**Note:** D6.1's original implementation bounded the downstream AI queue, but MatchEngine could still invoke Gemini before that boundary. D6.2 fixes this by bounding NEW Gemini evaluations before invocation.

---

## CHECKPOINT D5: First Verified Native Naukri Application

**Status:** FIRST VERIFIED NATIVE NAUKRI APPLICATION: SUCCESS

**D5 Summary:**

The D4 apply click on NetM Corporate Solutions "Software Engineer / Developer" DID submit the application to Naukri. D5 investigation confirmed the Applied badge `<span id="already-applied">Applied</span>` is visible on the job page after reload. The D4 timeout expired before this badge appeared in-page.

**D5 Fix:** `start_application()` now performs one bounded page reload after the 8-second in-page window. If `detect_applied_state()` returns `(True, evidence)` on the reloaded page, the application is marked APPLIED. This is a read-only confirmation of Naukri's persistent server-side state — not a retry of the Apply click.

**D5 Evidence:**
- `detect_applied_state()` returns `(True, "Applied")` on Job 23 live page
- Apply button gone, `#already-applied` span visible
- Database: application 18 → APPLIED, applied_at, method=NAUKRI_NATIVE, confirmation_evidence=Applied
- **APPLIED count: 1**

**Test coverage:** 238 focused tests, 0 failures (14 new D5 tests added)

---

## CHECKPOINT D4: First Verified Native Naukri Application (Apply clicked — evidence confirmed by D5)

**Status:** D4 role: physical Apply click reached and executed

The physical Apply button was reached and clicked once for a real Naukri-native job. However, no post-click Applied evidence was detected by the existing selectors within the 8-second observation window. The application was correctly recorded as `NEEDS_ATTENTION` (not APPLIED). APPLIED count remains 0.

**D4 Live Run Summary:**
- Live discovery: 103–104 jobs found in current run
- 70 jobs rejected by hard filters (Java, .NET, PHP, unpaid, non-IT, sales, etc.)
- 11 pre-analyzed candidates from current run proceeded to application phase
- 7 detected as EXTERNAL by NaukriAdapter (no external submission)
- 1 blocked by safety gate: Gemini NEEDS_ATTENTION (Blue Yonder)
- 1 blocked by safety gate: EXTERNAL classification before run
- 1 candidate (NetM Corporate Solutions) reached and passed all gates as NAUKRI_NATIVE
- Apply button physically clicked ONCE
- Post-click evidence wait: 8 seconds — no Applied state detected
- Application 18: NEEDS_ATTENTION, method=NAUKRI_NATIVE, evidence=None
- APPLIED count: 0

**Boundary failed:** H — Post-click Applied evidence detection

**What held:**
- No CAPTCHA bypass
- No external application submitted
- No questionnaire automatically answered
- max_applications=1 respected
- No APPLIED status persisted without evidence
- All deterministic safety rules enforced

**Bug fixes applied:**
1. Pre-analyzed candidate bypass in `run_autonomous_cycle.py` (jobs with existing analyses no longer block the cycle)
2. Title scope check in final safety gate (`backend/services/applications/service.py`) replaced strict substring match with `title_matches_allowed_role()` function

**Test coverage:** 224 focused tests passing, 0 failures

---

## CHECKPOINT D1: Autonomous Discovery Tracking (2026-10-06)

Implemented current-run job ID tracking to prevent historical DB jobs from being processed when live discovery fails. The autonomous cycle now tracks the current DiscoveryRun and only processes jobs from that specific run, ensuring discovery failures don't silently fall back to stale database records.

**Current-Run Job ID Tracking:**
- Added `current_run_job_ids` column to `DiscoveryRun` model (comma-separated for SQLite compatibility)
- DiscoveryService tracks job IDs from current run in memory during discovery
- Both new jobs and existing jobs (duplicates) are added to current-run tracking
- On discovery completion, job IDs are persisted as comma-separated string
- Autonomous cycle parses current-run job IDs and filters jobs to only those in the current run
- Fallback to timestamp comparison if job IDs not available (shouldn't happen)
- Cycle stops with error if `current_run.jobs_discovered == 0`

**Direct Naukri Search Navigation:**
- Removed homepage navigation dependency - now navigates directly to search URL
- Simplified security check to single call after search navigation
- Removed bounded wait for homepage elements
- Reduced navigation time and potential failure points

**Role Targeting and Metadata Enrichment:**
- Added deterministic role/title targeting in MatchEngine before IT metadata gate
- Explicitly rejects unwanted specializations: Java, PHP, .NET, C#, C++, Power Platform, Platform Engineer, Salesforce, SAP, ServiceNow, embedded, firmware, hardware, electrical, mechanical, civil, sales, marketing, HR, operations
- Allowed role families: data (analyst, engineer), software (engineer, developer), devops, python developer
- Enhanced NaukriAdapter metadata extraction with JSON-LD parsing, "Other Details" section extraction, and fallback body text scanning
- Always fetches job details for IT metadata enrichment (industry/department/role_category) even when description is present

**Historical Job Exclusion:**
- Jobs not returned by current search are excluded from current-run tracking
- Autonomous cycle only processes jobs with IDs in `current_run_job_ids`
- Historical jobs remain in database but are not sent to Gemini or ApplicationRunner

**Live Read-Only Validation (2026-10-06):**
- Authenticated Naukri session opened successfully
- Direct search navigation reached real Naukri search-results page
- 105 job cards discovered across 11 pages
- 82 jobs tracked in current run (including existing duplicates)
- 21 historical jobs excluded from current run
- 105 existing jobs rediscovered (0 new jobs added - all were duplicates)
- Role targeting detected 12 jobs with unwanted specializations
- Experience filtering passed (all jobs appear entry-level/fresher)
- No CAPTCHA, security challenge, or login challenge appeared
- No Apply clicked, no Gemini called, no submission made
- Current-run tracking fix confirmed working

**Test Coverage:**
- Focused current-run tracking tests: 12 passed
- Full backend suite: 681 passed, 0 failures
- All discovery tests pass with current-run tracking

**Note:** Metadata enrichment for NEW jobs has not been live-validated because all jobs in the current discovery run were existing duplicates. Existing DB rows predate the metadata enrichment implementation. NEW-job metadata validation will be performed separately with fresh jobs.

## CHECKPOINT C: Autonomous Cycle Command (2026-10-02)

`run_autonomous_cycle.py` provides a command-line interface for running the complete autonomous job application cycle with explicit controls and safety guarantees.

**Command-Line Flags:**
- `--max-applications N`: Limit on real applications (default: 1)
- `--dry-run`: Discovery and analysis only, no Apply clicks or application records
- `--max-jobs N`: Cap on jobs inspected per run (default: unlimited)

**Orchestration Flow:**
The command calls existing services in sequence:
1. DiscoveryService.run_discovery() - discovers jobs from Naukri
2. MatchEngine.evaluate_job() - applies hard filters (salary, experience, employment type, location)
3. AIQueueService.enqueue_job() - enqueues eligible jobs for AI analysis
4. AIQueueService.process_item() - processes queue through Gemini
5. ApplicationRunner.run_applications() - applies to eligible native jobs with dry_run flag

**Safety Guarantees:**
- S&P job `300926927428` is always excluded
- External jobs are skipped (never applied to)
- Native/external re-classification happens immediately before Apply click
- Post-click Applied evidence is required before recording APPLIED
- Stops on SECURITY_REQUIRED, AUTH_REQUIRED, hourly/daily limits, or critical errors
- No input() prompts anywhere

**Output:**
- Per-job decision table with: company, title, native/external, filter results, Gemini result, gate result, outcome
- Final summary with counts
- Exit code 0 on normal completion, non-zero on AUTH/SECURITY/critical stop
- Normal completion includes reaching the configured `max_applications` limit: exit 0, status `COMPLETED`. AUTH/SECURITY stops return exit 2, other critical stops return exit 3, both reported as `FAILED`.
- A candidate the application runner never inspected (browser session failure or unusable agent state) is recorded as `ERROR` and stops the run; it is never recorded as `SKIPPED` and never creates an application row.
- Empty candidate list reported as "0 eligible jobs found" (not a failure)

**Test Coverage:**
- `backend/tests/test_autonomous_cycle.py` covers eligible native jobs, external jobs, unpaid jobs, excluded jobs, max-applications limit, dry-run flag, current-run isolation, bounded Gemini look-ahead, and terminal/per-job outcome reporting
- Outcome-reporting regression tests assert: limit reached -> `(0, COMPLETED)`; AUTH/SECURITY stop -> `(2, FAILED)`; unclassified stop -> `(3, FAILED)`; runner returned no outcome -> `ERROR` with no application row; genuine skip still `SKIPPED`; execution error stops the cycle instead of mislabelling the remaining candidates
- All tests use isolated temporary SQLite database
- No live Naukri activity, Gemini calls, or Apply clicks in tests

**Usage Examples:**
```powershell
# Dry-run (discovery and analysis only, no Apply clicks)
python run_autonomous_cycle.py --dry-run --max-jobs 10

# First live run with 1 application
python run_autonomous_cycle.py --max-applications 1 --max-jobs 10
```

**Note:** This command builds and tests offline only. Do not run it live yourself; no Apply clicks, no Gemini calls, no weakening of filters/limits/duplicate rules/safety gate. Never apply to EXTERNAL jobs.

## Phase 10 Application-Type Reliability Fix (2026-10-01)

The application-type classifier now uses a single bounded 500 ms observation window only when the initial visible state is inconclusive. Visible external evidence such as `Apply on company site` remains authoritative and is checked before native evidence. Native classification still requires visible stable selectors or exact visible `Apply` text. If neither evidence is visible after settling, the adapter returns `AMBIGUOUS`; the runner maps this to `NEEDS_ATTENTION` and does not create an application record.

Offline validation passed: 96 Naukri adapter tests. Read-only live validation observed Quadrasystems as `AMBIGUOUS` both before and after settling, and Cisco as `EXTERNAL` with visible `Apply on company site`. No application action occurred and automated successful application count remains 0.

## Phase 10 Live Native Application Test: BLOCKED (2026-10-01)

The authenticated persistent Playwright session and local backend were available. Readiness was `ready`, the confirmed profile and preferences were present, the schema was compatible, limits allowed an attempt, and the database contained 10 application records with 0 APPLIED/SUBMITTED records.

A bounded discovery pass inspected five `Data Analyst` results read-only. No candidate satisfied the complete eligibility boundary: four were rejected by duplicate history, employment-type failure, or external classification, and the only native result was already processed. No Apply or Submit control was clicked, no Gemini decision was requested, and no application row changed. Automated successful application count remains 0.

The live submission checkpoint remains incomplete and must not be treated as a successful validation.

## Phase 10 Database Schema Migration

**Status:** Complete (Local SQLite Migrated)

The Phase 10 schema migration addresses the mismatch between the ORM model and the database initialization function. The `Application` model requires `confirmation_evidence` (TEXT NULL) and `is_dry_run` (BOOLEAN) columns for Phase 10 feature delivery, but older databases lack these columns.

**Migration Mechanism:**
- Type: Additive `ALTER TABLE` with column existence checks (extends Phase 9B-4 pattern)
- Pattern: Check if column exists before attempting to add; skip if present (idempotent)
- Timing: Runs automatically during application startup via `initialize_database()` 
- Scope: Runs BEFORE request handling during FastAPI lifespan initialization
- Coverage: Both SQLite and PostgreSQL (verified for SQL syntax compatibility)

**Implementation Details:**
```python
# In backend/database/database.py initialize_database()

# Phase 10: confirmation_evidence column (applied state evidence)
if "confirmation_evidence" not in {
    column["name"] for column in inspect(engine).get_columns("applications")
}:
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE applications ADD COLUMN confirmation_evidence TEXT NULL"
        ))
```

**Runtime Integration:**
- Schema compatibility check added to `/readiness` endpoint via `_check_schema_compatibility()` 
- Reports `schema: compatible` or lists missing columns
- Prevents readiness until schema matches model requirements
- Existing application data is preserved during migration (no destructive operations)

**Standalone Execution:**
```bash
# Manual migration (uses current DATABASE_URL from config/environment)
python -m backend.database.database
```

**Test Coverage:**
- 7 focused migration tests (test_schema_migration.py)
- Test A: Old schema migration adds confirmation_evidence 
- Test B: Migration is idempotent (runs twice without error)
- Test C: Readiness check detects schema compatibility
- Test D: Current schema requires no changes
- Test E: Database isolation (never uses production DB)
- 557 total backend tests passing (includes 7 new migration tests)

**Local Database Verification (SQLite):**
- Database: data/naukri_agent.db
- Backup: data/naukri_agent.db.bak-before-migration (240K, taken before migration)
- Records preserved: 10 application rows (unchanged)
- Record 10 status: APPLICATION_STARTED (unchanged)
- APPLIED/SUBMITTED counts: 0/0 (unchanged)
- Columns added: confirmation_evidence, is_dry_run
- ORM queries: Working without OperationalError

**PostgreSQL Support:**
- SQL syntax validated for PostgreSQL compatibility
- Standard SQL used: ALTER TABLE, ADD COLUMN, BOOLEAN, TEXT, DEFAULT, NULL
- Works on both SQLite and PostgreSQL with no dialect-specific logic

**Neon/Production PostgreSQL:**
To migrate an external PostgreSQL database (e.g., on Neon):

```bash
# Set DATABASE_URL to your Neon connection string
export NAUKRI_AGENT_DATABASE_URL="postgresql://user:password@neon.host/dbname"

# Run migration (uses standard initialization)
python run.py
# OR for standalone migration:
python -m backend.database.database
```

**Verification queries for Neon after migration:**
```sql
-- Verify column exists
SELECT column_name FROM information_schema.columns 
WHERE table_name='applications' AND column_name='confirmation_evidence';

-- Verify application count unchanged
SELECT COUNT(*) FROM applications;

-- Verify record 10 status
SELECT id, status FROM applications WHERE id=10;

-- Verify no APPLIED/SUBMITTED applications
SELECT COUNT(*) FROM applications WHERE status IN ('APPLIED', 'SUBMITTED');
```

**Status Notes:**
- Local SQLite database: Migrated and verified
- Neon/Production PostgreSQL: NOT migrated (manual step after deployment)
- No Alembic framework: Uses existing manual migration pattern
- No business logic changes: Schema-only, additive columns only
- No live Naukri activity: Migration is schema-only, no automation tested
- Application count: Remains 0 (no live submissions)

---

## Phase 9B-4 Safety Hardening Note

The application runner's dry-run contract is pre-Apply inspection only. A dry-run may open and inspect a candidate page, but it cannot click native Apply, click external Apply, invoke question answering, submit, or confirm submission. Dry-run records carry an explicit `is_dry_run` marker and remain outside APPLIED/SUBMITTED duplicate protection. Lifecycle values distinguish PRE_APPLY, APPLICATION_STARTED, FORM_OPENED, APPLIED, SUBMITTED, and NEEDS_ATTENTION; an Apply click is not treated as proof that a form opened or an application was submitted. Native Apply semantics remain UNKNOWN and the Phase 9B-3 live form boundary is unresolved. No live application occurred in this checkpoint.

## Master Product Requirements Document (PRD)

The application runner's dry-run contract is pre-Apply inspection only. A dry-run may open and inspect a candidate page, but it cannot click native Apply, click external Apply, invoke question answering, submit, or confirm submission. Dry-run records carry an explicit `is_dry_run` marker and remain outside APPLIED/SUBMITTED duplicate protection. Lifecycle values distinguish PRE_APPLY, APPLICATION_STARTED, FORM_OPENED, APPLIED, SUBMITTED, and NEEDS_ATTENTION; an Apply click is not treated as proof that a form opened or an application was submitted. Native Apply semantics remain UNKNOWN and the Phase 9B-3 live form boundary is unresolved. No live application occurred in this checkpoint.

## Master Product Requirements Document (PRD)

**Version:** 1.0
**Status:** Master Source of Truth
**Target Platform:** Windows
**Initial Job Platform:** Naukri
**AI Provider:** Google Gemini API
**Architecture:** Local-first, cloud-ready
**Primary Automation:** Playwright
**Backend:** Python + FastAPI
**Frontend:** React + TypeScript
**Database:** SQLite (V1), PostgreSQL (Production Integration Supported)

## Current Phase 9B-3 Validation Note

The V1 Gemini model default is `gemini-flash-lite-latest`. The former `gemini-2.5-flash` model was repeatedly blocked by `429 RESOURCE_EXHAUSTED`; a runtime test confirmed that the alternate model parses the existing structured `JobAnalysis` response successfully. Model selection remains environment-configurable through `NAUKRI_AGENT_GEMINI_MODEL`. `gemini-3.1-flash-lite-preview` also succeeded in testing but is not the V1 default. The live native Naukri application boundary remains pending.

The production JD extraction path now prefers visible `[class*="dang-inner-html"]` and falls back to visible `section[class*="job-desc-container"]`. This matches the runtime-suffixed hashed structures observed on real Naukri pages. Regression tests cover current hashed inner elements, the container fallback, selector precedence, hidden matching elements, and empty results when neither selector exists. Phase 9B-3 remains incomplete until a real native APPLY flow reaches the application boundary; this checkpoint made no Gemini or application calls.

Live JD diagnostics reached a concrete extraction blocker. On two persisted native Naukri job pages, First American and ReactZ Consulting, the authenticated visible pages returned HTTP 200 and contained the JD in rendered DOM text. The current `.job-desc` and exact `.styles_JDC__` selectors matched zero elements. Observed working structures included `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`, both with visible text. Production selectors remain unchanged pending review. Gemini is intentionally deferred while quota is exhausted; no Apply control or submission was invoked, and Phase 9B-3 remains incomplete.

The bounded live diagnostic now fetches each selected job's description through the existing `NaukriAdapter.fetch_job_description()` path, persists it in `Job.description`, and passes the actual value to Gemini instead of using a `(not fetched)` placeholder. It inspects bounded candidates before choosing a native APPLY candidate, excludes external jobs, reuses persisted analyses, stops on quota exhaustion, reports description status/length, and emits ASCII-safe output. This was an offline-only diagnostic change; no live search or Gemini request was run, and Phase 9B-3 live validation remains incomplete.

Live inspection found a genuine Naukri-native job page whose stable application control is `button#apply-button` / `button.apply-button` with visible exact text `Apply`. The adapter previously missed those selectors and returned `EXTERNAL`; the targeted detection and native-start selector fix is now implemented and covered by focused tests. This checkpoint does not include another live run, does not claim the native application boundary has been reached, and no application submission occurred.

The Naukri security boundary must use visible rendered page content and must stop automation for actual visible CAPTCHA, human-verification, security-challenge, authentication, or blocked-access indicators. A false-positive found during live dry-run diagnosis came from treating Naukri's raw HTML `"showCaptcha":false` state value as a security challenge. The targeted adapter fix now inspects rendered body text and does not treat bare `captcha` as a standalone trigger. This preserves the PRD requirement to stop for real security challenges; it does not bypass or weaken those controls.

The fix is covered by 77 Naukri adapter tests, and 509 full backend tests are recorded as passing. Another real visible-browser dry-run is required before claiming Phase 9B-3 live validation complete. No application submission occurred during this checkpoint.

## Current Test Database Safety Note

The runtime SQLite database is persistent application data and must never be reset by tests. The backend test fixtures now use a disposable temporary file-backed SQLite engine, redirect application database sessions to that engine for the test session, and perform schema resets only there. The production database at `data/naukri_agent.db` is not a test fixture dependency. Isolation regression tests, focused profile/application tests, and the full 512-test backend suite passed while the existing production profile/resume rows remained present.

---

# 1. Product Vision

Build a Windows-based AI-powered job application agent that can independently discover suitable jobs on Naukri, evaluate them against the user's explicitly defined job preferences and profile, and automatically submit applications for eligible Naukri-native jobs.

The system should behave like a controlled autonomous agent rather than a simple browser macro.

The agent must:

1. Understand the user's resume/profile.
2. Respect user-defined job-search criteria.
3. Discover relevant Naukri jobs.
4. Apply hard eligibility rules before using AI.
5. Use Gemini for job understanding, matching, classification, and application-question assistance.
6. Validate Gemini's recommendations through deterministic Python rules.
7. Automatically apply to eligible Naukri-native jobs.
8. Stop and notify the user when security challenges or critical failures occur.
9. Record every important action.
10. Provide a professional dashboard showing activity, applications, statistics, and issues.
11. Operate locally on Windows in V1.
12. Be architected so that cloud/24×7 execution and additional job platforms can be added later.

---

# 2. Core Product Principle

## AI is not the final authority.

Gemini is the **reasoning/understanding layer**, not the execution authority.

The architecture must enforce:

```text
Naukri
   ↓
Playwright
   ↓
Python extraction
   ↓
Cheap deterministic filters
   ↓
Duplicate detection
   ↓
Gemini analysis
   ↓
Pydantic validation
   ↓
Python Final Rules Engine
   ↓
APPLY / SKIP / NEEDS_ATTENTION
   ↓
Playwright execution
```

Gemini must never directly control the browser.

Gemini must never return browser commands.

Gemini must never bypass hard eligibility rules.

Gemini must never invent user information.

---

# 3. V1 Scope

## Included

* Windows desktop/local application
* Naukri job discovery
* Naukri job analysis
* Resume PDF upload
* AI profile extraction
* User profile confirmation/editing
* Multiple user-defined job profiles/search categories
* User-defined job titles/search terms
* Hard job eligibility rules
* AI-based matching
* Duplicate detection
* Naukri-native automatic applications
* Application-question handling
* Application history
* Job skip history
* Feedback/learning from explicit user feedback
* Scheduler
* Daily/hourly application limits
* Offline recovery
* Naukri browser-session reuse
* Chrome and Edge support
* CAPTCHA/security challenge detection
* Critical-error handling
* Email notifications
* Evening summary
* Professional dashboard
* AI usage tracking
* SQLite database
* Logging
* Windows packaging

## Explicitly NOT included in V1

* LinkedIn automation
* Indeed automation
* Other job-platform automation
* External company application submission
* CAPTCHA solving/bypass
* Anti-bot/rate-limit bypass
* Automatic recruiter messaging
* Recruiter follow-ups
* Recruiter-status monitoring
* Automatic modification of factual resume information
* Automatic fabrication of answers
* Multiple Naukri accounts
* Cloud execution
* 24/7 execution while the user's PC is turned off

These should remain future capabilities.

---

# 4. Local vs Cloud Strategy

V1 is **local-first**.

The application runs on the user's Windows machine.

Therefore:

```text
PC ON
→ Agent can operate

PC OFF
→ Agent cannot operate
```

The system must NOT pretend to operate while the computer is powered off.

However, the architecture must be cloud-ready.

Cloud readiness infrastructure has been implemented to support future cloud deployment without changing business logic:

- `RuntimeContext` abstraction for environment-specific behavior
- `StorageService` abstraction for file operations (enables future object storage)
- Environment variable configuration with `NAUKRI_AGENT_` prefix
- Database abstraction supporting both SQLite and natively connecting to PostgreSQL using `psycopg` drivers with connection pooling (Phase 8.2)
- No changes to existing V1 functionality or public APIs

Future architecture:

```text
V1
Windows PC
   ↓
Local Agent
   ↓
RuntimeContext (LOCAL_WINDOWS)
   ↓
StorageService (local filesystem)
   ↓
SQLite

Future
Cloud Scheduler
   ↓
Remote Worker
   ↓
RuntimeContext (CLOUD_READY)
   ↓
StorageService (object storage)
   ↓
PostgreSQL
   ↓
Remote Browser Automation
   ↓
Dashboard
```

When the PC starts again, the agent should perform recovery discovery.

It should:

1. Determine the last successful discovery run.
2. Search for jobs posted/discovered since that period where possible.
3. Optionally consider the previous 24 hours.
4. Deduplicate against existing jobs/history.
5. Prioritize fresh and relevant jobs.
6. Apply jobs that are still discoverable and eligible.
7. Never assume a historical job still exists if Naukri cannot currently expose it.

---

# 5. User Profile

The user uploads **one PDF resume** to the application.

The system stores a local copy.

Gemini extracts structured information such as:

* Name
* Education
* Degree
* University
* Graduation year
* Skills
* Programming languages
* Frameworks
* Tools
* Projects
* Certifications
* Work experience
* Experience duration
* Current role
* Previous roles
* Current CTC, if provided
* Notice period, if provided
* Location
* Other explicitly stated professional information

The extracted profile must be shown to the user.

The user must review and confirm it before automation begins.

---

# 6. Resume Management

V1 supports:

```text
Upload Resume
      ↓
Extract text
      ↓
Gemini profile extraction
      ↓
User review/edit
      ↓
Confirm profile
      ↓
Agent enabled
```

If the resume changes:

```text
User uploads new PDF
      ↓
New extraction
      ↓
User reviews
      ↓
Profile updated
```

If the resume upload finds an existing profile in ERROR state (extraction previously failed):

```text
Same PDF re-uploaded
      ↓
Re-run extraction against stored file
      ↓
User reviews
      ↓
Profile recovered
```

No new resume or profile records are created during ERROR recovery. The existing record is updated in-place.

The system must not automatically invent or modify actual profile information.

The application may refresh/re-upload an existing Naukri resume/profile timestamp where technically supported, but it must never alter factual information without user input.

---

# 7. Job Search Configuration

The user controls job-search criteria.

The user can create multiple job profiles.

Example:

```text
Profile 1:
Data Analyst

Profile 2:
Data Scientist

Profile 3:
AI/ML Engineer
```

Each profile can contain:

* Job titles
* Search keywords
* Related titles within user-approved scope
* Locations
* Minimum salary
* Employment types
* Application limits
* Aggressiveness mode

Gemini must NOT have unrestricted authority to invent completely new job categories or search areas.

User-defined search criteria are authoritative.

---

# 8. Location Rules

Location is a **hard filter**.

The user's current required locations are:

* Bengaluru
* Remote

The agent should apply if:

### Case 1

Job location:

```text
Bengaluru
```

→ Apply.

### Case 2

Job location:

```text
Remote
```

→ Apply.

### Case 3

Job location:

```text
Bengaluru / Hyderabad / Pune
```

→ Apply because Bengaluru is included.

# Checkpoint C2 policy

The fresher-only policy is deterministic and authoritative: `max_required_experience_years` defaults to `0`; experience above the cap, and missing/unparseable experience without an entry-level title, is skipped. IT scope requires both an allowed industry/department/role category and an allowed title keyword. The search URL includes Naukri's `experience=0` filter. Native forms containing questions stop at `NEEDS_ATTENTION`; no fields are answered or submitted unless the explicit `answer_questions` flag is enabled.

### Case 4

Job location:

```text
Hyderabad / Pune
```

→ Skip.

The AI cannot override this rule.

---

# 9. Experience Rules

Experience requirements are a hard filter.

If the job explicitly requires more experience than the user's profile supports:

```text
SKIP
```

Example:

```text
User: 1 year experience
Job: Requires 3–5 years

→ SKIP
```

The agent must not apply merely because Gemini thinks the user could perform the job.

---

# 10. Salary Rules

Minimum acceptable salary:

**₹4 LPA**

When salary information exists:

| Job salary    | Decision            |
| ------------- | ------------------- |
| ₹2–4 LPA      | SKIP                |
| ₹3–5 LPA      | APPLY               |
| ₹4–6 LPA      | APPLY               |
| ₹6+ LPA       | APPLY               |
| ₹10+ LPA      | APPLY               |
| Not disclosed | Continue evaluation |

Important:

A salary range is acceptable if it includes ₹4 LPA.

Example:

```text
₹3–5 LPA
```

→ APPLY.

But:

```text
₹2–4 LPA
```

→ SKIP.

If salary is undisclosed, salary does not automatically disqualify the job.

---

# 11. Employment Type

Allowed:

* Full-time
* Internship
* Contract

Other employment types should be skipped unless explicitly configured later.

---

# 12. Company Filtering

V1 has:

```text
No company blacklist
No company whitelist
```

Any company can be considered if all other rules pass.

---

# 13. Consultancy / Recruiter Jobs

Consultancy postings require additional evaluation.

Preferred:

```text
Actual hiring company clearly identifiable
```

If a consultancy/recruiter is involved:

* Identify the actual employer if possible.
* Evaluate job quality.
* Detect suspicious/spam postings.
* Detect obvious duplicates.
* Skip if employer cannot reasonably be identified.

Gemini can classify ambiguous cases.

Python remains responsible for final enforcement.

---

# 14. Job Freshness

Fresh jobs should be prioritized.

However:

**Freshness is not a replacement for relevance.**

Priority should generally be:

```text
Eligible + highly relevant + fresh
```

rather than simply:

```text
Newest job regardless of relevance
```

---

# 15. Skill Matching

The system does not require 100% skill matching.

A job can be applied to if most relevant skills match the user's profile.

Example:

```text
Job requires:
Python
SQL
Power BI
Excel
AWS

User has:
Python
SQL
Power BI
Excel

→ Potential APPLY
```

Missing one non-critical skill should not automatically cause rejection.

However:

* Experience rules remain hard.
* Location rules remain hard.
* Salary rules remain hard.
* Employment rules remain hard.

---

# 16. Poor or Short Job Descriptions

If the job description is incomplete or unusually short:

1. Use available job title.
2. Use available metadata.
3. Apply hard filters.
4. If title strongly matches a user-defined target role, Gemini may evaluate the available information.
5. If still sufficiently relevant, the job may be applied to.

The system should not automatically reject every job with a poor description.

---

# 17. Duplicate Detection

Duplicate detection is mandatory.

Before AI analysis where practical, Python should compare:

* Naukri job ID
* URL
* Company
* Job title
* Description similarity
* Existing application history
* Previously discovered jobs

Possible states:

```text
CLEAR_NEW
LIKELY_DUPLICATE
BORDERLINE_DUPLICATE
CONFIRMED_DUPLICATE
```

Gemini can evaluate borderline cases.

A job already successfully applied to must not be applied to again.

---

# 18. Gemini Responsibilities

Gemini is responsible for:

### Profile understanding

Extract structured information from resume text.

### Job understanding

Determine:

* Role relevance
* Skill relevance
* Experience compatibility
* Job quality
* Suspicious/low-quality indicators
* Consultancy/recruiter classification
* Duplicate likelihood where needed

### Application questions

Generate answers to open-ended application questions using:

* User profile
* Job description
* Question context

### Learning

Analyze explicit user feedback and application history to improve recommendations.

Gemini cannot:

* Override hard rules.
* Trigger application submission.
* Control Playwright.
* Invent user information.
* Bypass CAPTCHA.
* Bypass security.
* Change hard filters automatically.
* Create unrestricted search categories.

---

# 19. Gemini Output Contract

All Gemini responses must use strict structured output.

Preferred implementation:

```text
Gemini
 ↓
JSON
 ↓
Pydantic schema
 ↓
Validation
 ↓
Application logic
```

Example conceptual schema:

```json
{
  "recommendation": "APPLY",
  "match_score": 86,
  "role_match": true,
  "skill_match": true,
  "experience_match": true,
  "job_quality": "GOOD",
  "duplicate_probability": 0.02,
  "suspicious": false,
  "short_reason": "Strong match for Python and data-analysis experience."
}
```

No free-form browser instructions.

No executable instructions.

No chain-of-thought storage.

Only structured analysis and short explanations should be persisted.

---

# 20. AI Decision States

Gemini may return:

```text
APPLY
SKIP
NEEDS_ATTENTION
```

But the actual application decision must be made by the Python rules engine.

Example:

```text
Gemini → APPLY

Python checks:
Location ❌

Final:
SKIP
```

Another example:

```text
Gemini → APPLY

Python checks:
Location ✅
Experience ✅
Salary ✅
Employment type ✅
Duplicate ✅
Daily limit ✅
Required profile data ✅

Final:
APPLY
```

---

# 21. Final Safety Gate

Before every application submission:

```text
FINAL_RULE_CHECK
```

Python must revalidate:

* Location
* Experience
* Salary
* Employment type
* Duplicate status
* Daily application limit
* Hourly application limit
* Required profile information
* Authentication state
* Agent state
* Security state
* Application eligibility

Only after all checks pass can Playwright submit the application.

Gemini cannot bypass this gate.

---

# 22. Application Questions

Application questions have two categories.

## Factual questions

Use fixed user-profile information.

Example:

```text
Years of experience:
```

Use the confirmed profile value.

Gemini should not generate a different number.

## Open-ended questions

Gemini may generate a tailored answer using:

```text
User Profile
+
Job Description
+
Question
```

Example:

```text
Why are you interested in this role?
```

Gemini can produce a concise JD-specific response.

The answer must remain truthful.

---

# 23. Unknown Information

If an application asks:

```text
How many years of AWS experience do you have?
```

and the profile contains no AWS experience:

The system must NOT guess.

Fallback hierarchy:

```text
Configured fallback answer
        ↓
Needs Attention
        ↓
Skip/continue safely according to application context
```

The agent should continue processing other jobs where safe.

---

# 24. Naukri Application Flow

Conceptual flow:

```text
Discover Job
      ↓
Extract Data
      ↓
Hard Filter
      ↓
Duplicate Check
      ↓
Gemini Analysis
      ↓
Pydantic Validation
      ↓
Final Python Rules
      ↓
Eligible?
  /          \
NO            YES
↓              ↓
SKIP        Start Application
               ↓
        Detect Application Type
          /              \
Naukri Native        External Site
     ↓                    ↓
Fill Form          DO NOT SUBMIT
     ↓                    ↓
Validate           Notify User
     ↓
Submit
     ↓
Record Applied
```

---

# 25. External Applications

If Naukri redirects to an external company/application website:

**Do not submit the external application.**

Instead:

1. Stop that job's application flow.
2. Mark it:

```text
EXTERNAL_APPLICATION
```

3. Record:

   * Job title
   * Company
   * URL
   * Reason
   * Discovery timestamp

4. Notify the user by:

   * Dashboard
   * Email

5. Continue with other eligible jobs if the system is in a safe state.

---

# 26. Browser Automation

Use:

**Playwright**

Supported browsers:

* Google Chrome
* Microsoft Edge

Browser should be configurable.

The implementation must use normal browser interaction.

The system must NOT implement:

* CAPTCHA bypass
* Anti-bot bypass
* Rate-limit circumvention
* Security challenge bypass
* Credential theft
* Stealth techniques intended to evade platform security controls

If Naukri presents a security challenge, the agent stops.

---

# 27. Authentication

V1 uses:

**Manual login once + persistent authenticated browser session.**

The user logs into Naukri manually.

The application reuses the authenticated session.

Raw Naukri passwords must not be stored.

If the session expires:

```text
AUTH_REQUIRED
```

The agent must:

1. Stop automation.
2. Notify user.
3. Ask user to log in again.
4. Resume only after authentication is restored.

---

# 28. CAPTCHA / Security Challenge

If the agent encounters:

* CAPTCHA
* Human verification
* Suspicious login
* Security checkpoint
* Unexpected authentication challenge

Then:

```text
STOP AGENT
+
NOTIFY USER
```

No automated bypass is permitted.

The user resolves the challenge manually and restarts/resumes the agent.

---

# 29. Application Limits

Application volume must be configurable.

The user wants dynamic application behavior.

Settings include:

```text
Aggressiveness:
Conservative
Balanced
Aggressive
```

Additionally:

```text
Maximum daily applications
Maximum hourly applications
```

The agent dynamically distributes applications within these absolute limits.

Hard filters always override aggressiveness.

Aggressive mode does NOT mean:

```text
Ignore eligibility rules
```

It means the system can be more willing to apply among jobs that already satisfy hard rules.

---

# 30. AI API Usage Control

The application is designed around the Gemini free tier.

Therefore API calls must be conserved.

Strategies:

* Cheap Python pre-filtering
* Avoid AI analysis for obvious hard-filter failures
* Cache job analysis
* Avoid re-analyzing the same job unnecessarily
* Deduplicate before Gemini
* Configurable AI request limits
* Track usage
* Queue AI work
* Process jobs intelligently

---

# 31. Gemini Quota Exhaustion

If Gemini quota is exhausted:

```text
AI_QUOTA_EXHAUSTED
```

The agent must:

1. Stop AI-dependent decisions.
2. Continue cheap deterministic discovery/filtering where possible.
3. Queue jobs requiring Gemini.
4. Resume processing when quota becomes available.
5. Never switch to uncontrolled AI-free automatic applications.

---

# 32. Gemini Failure Handling

## Job-level failure

If one Gemini request:

* Times out
* Returns invalid JSON
* Fails validation
* Produces unusable output

Then:

```text
Retry
   ↓
If retry fails
   ↓
NEEDS_ATTENTION
```

Continue with other jobs if safe.

## System-level failure

If Gemini/API experiences a broad failure:

```text
STOP AGENT
+
NOTIFY USER
```

Invalid Gemini output must never reach the application engine.

---

# 33. Learning System

The user can explicitly provide feedback.

Examples:

```text
Not interested
Wrong role
Too senior
Not relevant
Don't apply to this type
```

The system stores this feedback.

Gemini can use:

* Explicit feedback
* Application history
* Previous classifications

to improve recommendations.

However:

**AI learning cannot modify hard filters automatically.**

Example:

If user requires Bengaluru:

```text
AI cannot learn:
"User might accept Hyderabad"
```

unless the user explicitly changes the preference.

---

# 34. Application History

Every successful application should be recorded.

Minimum information:

* Job
* Company
* URL
* Date/time
* Application method
* Status

Successful Naukri-native application:

```text
APPLIED
```

Then move on.

V1 does not automatically monitor recruiters or application outcomes.

---

# 35. Job History

The system should maintain historical job records.

Possible states:

```text
DISCOVERED
FILTERED
AI_ANALYZED
SKIPPED
APPROVED_BY_RULES
APPLICATION_STARTED
APPLIED
EXTERNAL_APPLICATION
NEEDS_ATTENTION
```

Skip reasons should be stored.

Examples:

```text
Location mismatch
Experience too high
Salary below minimum
Duplicate
Wrong employment type
Low relevance
Suspicious posting
External application
Missing required information
```

---

# 36. Data Retention

Application history should be retained by default.

The user must be able to manually:

* Delete
* Archive

historical records.

---

# 37. Scheduler

Default discovery frequency:

**Approximately hourly.**

The scheduler may adapt within reasonable platform limits.

The system should avoid unnecessarily aggressive requests.

Conceptually:

```text
Scheduler
    ↓
Discover jobs
    ↓
Filter
    ↓
Analyze
    ↓
Apply
    ↓
Wait
    ↓
Next cycle
```

The scheduler must respect:

* Hourly application limit
* Daily application limit
* AI quota
* Agent state
* Authentication state
* Security state

---

# 38. Windows Startup

V1 should support:

```text
Auto-start with Windows: ON/OFF
```

The user should also have:

```text
START AUTOMATION
STOP AUTOMATION
```

The user remains in control of whether the agent is running.

---

# 39. Agent State Machine

The agent should have explicit states.

Recommended:

```text
IDLE
RUNNING
SEARCHING
FILTERING
ANALYZING
APPLYING
PAUSED
AUTH_REQUIRED
SECURITY_REQUIRED
AI_QUOTA_EXHAUSTED
NEEDS_ATTENTION
STOPPED
CRITICAL_ERROR
```

---

# 40. Frontend UX/UI Design

The frontend dashboard has been redesigned to provide a polished, modern SaaS experience with the following improvements:

## Design Principles

- **Professional SaaS aesthetic**: Modern dashboard layout with clean visual hierarchy
- **User-centric language**: All development-phase terminology removed from user-facing UI
- **Accessibility-first**: Keyboard navigation, focus states, and screen reader support
- **Responsive design**: Works seamlessly across desktop, tablet, and mobile devices
- **Graceful degradation**: Handles backend unavailability with clear user messaging

## Navigation Structure

The dashboard uses a sidebar navigation with the following sections:

- **Overview**: Main command center with agent status, controls, and key metrics
- **Activity**: Timeline of agent actions and events
- **Jobs**: Job discovery interface (coming soon)
- **Applications**: Application tracking dashboard (coming soon)
- **Analytics**: Performance metrics and decision analytics
- **Profile**: Resume and profile management with completion tracking
- **Preferences**: Job search criteria and automation settings

## Visual Language

The design uses a Naukri-inspired color palette:

- Primary Blue: #0073E6
- Deep Blue: #0056B3
- Accent Orange: #FF8A00
- Light Blue: #EAF4FF
- Background: #F7F9FC
- Success: #16A34A
- Warning: #F59E0B
- Error: #DC2626

Design elements include:
- Rounded corners (8-12px) for modern feel
- Subtle shadows for depth
- Smooth transitions and hover states
- Clear typography hierarchy
- Consistent spacing (4px, 8px, 16px, 24px, 32px system)

## User Experience Improvements

### Error Handling
- Technical error messages replaced with user-friendly alternatives
- Backend connection status clearly indicated
- Retry actions provided where appropriate
- Empty states with helpful guidance

### Profile Onboarding
- Visual profile completion indicator
- Clear section organization
- Progress tracking for setup completion
- Guided upload process

### Preferences
- Organized into logical sections (Target Roles, Locations, Compensation, etc.)
- Clear descriptions for each setting
- User-friendly dropdowns with explanations
- Save confirmation feedback

### Analytics
- Compact, readable charts
- Key metrics at a glance
- Decision breakdown visualization
- Skip reasons tracking

### Backend Connection States
The frontend gracefully handles different backend states:

- **Connected**: Agent backend is running and accessible
- **Local agent offline**: Clear message to start the local Windows agent
- **Cloud backend unavailable**: Temporary service disruption message
- **Checking**: Connection verification in progress

## Accessibility Features

- Skip-to-content link for keyboard navigation
- Proper ARIA labels on interactive elements
- Visible focus states on all interactive elements
- Semantic HTML structure
- Sufficient color contrast
- Keyboard-friendly navigation

## Responsive Design

- Desktop: Full sidebar with all navigation items
- Tablet: Collapsed sidebar with icons only
- Mobile: Off-canvas sidebar with hamburger menu
- Card layouts reflow appropriately
- Tables become scrollable on smaller screens

## Performance

- Minimal dependencies (React, TypeScript, Tailwind CSS)
- Optimized build output
- Efficient API calls with proper error handling
- Loading states for better perceived performance

---

# 41. Agent Intelligence and Decision Quality

The agent should provide explainable decision-making with structured priority levels:

```text
Decision Priorities:
- HARD_REJECT: Fails hard filters (location, experience, salary, duplicate)
- SKIP: Low relevance or not worth applying
- LOW_PRIORITY: Weak match but eligible
- NORMAL_PRIORITY: Good match
- HIGH_PRIORITY: Strong match
- NEEDS_ATTENTION: Requires manual review
```

Decision signals should include:
- Role relevance score
- Skill relevance score
- Experience compatibility score
- Location match score
- Salary suitability score
- Job quality score
- Freshness score
- Duplicate probability
- Suspicious probability
- Historical feedback adjustment

Every decision should have:
- Structured reason codes
- Concise explanation
- Signal breakdown
- Priority level
- Decision score (0-100)

---

# 41. Job Prioritization

Jobs should be prioritized before application processing based on:
- Strong role and skill relevance
- Acceptable salary
- Location fit
- Freshness
- Quality
- Low duplicate probability
- Historical user feedback

Hard-filtered jobs must never become higher priority.

Prioritization must be deterministic and reproducible for the same inputs.

---

# 42. Feedback and Learning

The system should support explicit user feedback:

```text
Feedback Types:
- RELEVANT
- NOT_RELEVANT
- APPLIED
- SKIPPED
- INCORRECT_MATCH
- GOOD_MATCH
- TOO_SENIOR
- TOO_JUNIOR
- WRONG_LOCATION
- SALARY_TOO_LOW
```

Feedback influences ranking/prioritization only.

Learning boundaries:
- CANNOT modify hard filters automatically
- CANNOT change salary minimum
- CANNOT change location restrictions
- CANNOT change experience restrictions
- CANNOT remove duplicate protection
- CANNOT bypass safety gate
- CANNOT invent new job categories
- CANNOT silently change user preferences

User-controlled preferences remain authoritative.

---

# 43. Application Analytics

The system should provide comprehensive analytics:

```text
Metrics:
- Discovered jobs
- Eligible jobs
- Skipped jobs
- Applications submitted
- Application success rate
- Top skip reasons
- Top application categories
- AI analysis usage
- AI quota/queue activity
- Applications by day
- Applications by job profile
- Decision priority breakdown
- Primary reason codes
- Feedback summary
```

Analytics should use existing Job, Application, and decision data without creating fake historical data.

The dashboard should display the current state.

---

# 40. Critical Error Handling

If a critical Naukri/browser/system error occurs:

```text
STOP AGENT
+
LOG ERROR
+
NOTIFY USER
```

If a single job fails:

```text
MARK NEEDS_ATTENTION
+
LOG ERROR
+
CONTINUE IF SAFE
```

Examples of critical errors:

* Browser completely unavailable
* Naukri session corruption
* Unexpected authentication failure
* Security challenge
* Critical automation failure
* Database integrity issue

---

# 41. Dashboard

The dashboard should be professional rather than a basic developer console.

Main sections:

### Overview

* Agent status
* Applications today
* Applications this week
* Jobs discovered
* Jobs skipped
* Jobs needing attention
* AI usage
* Application limits

### Live Agent Activity

Show concise activity such as:

```text
Searching Naukri...
Found 34 jobs
Filtered 19
Analyzing 15
Applied to 3
Skipped 11
1 needs attention
```

### Applications

* Company
* Role
* Date
* Status
* Application method

### Jobs

* Job title
* Company
* Location
* Match score
* Status
* Short reason

### Settings

* Resume/profile
* Job profiles
* Locations
* Salary
* Employment types
* Application limits
* Aggressiveness
* Browser
* Notifications

### AI Usage

* Requests
* Successful requests
* Failed requests
* Cached analyses
* Estimated/known quota state

---

# 42. AI Analysis Details

Do not display long reasoning or chain-of-thought.

Store structured fields such as:

```text
Match score
Role match
Skill match
Experience match
Location match
Salary match
Job quality
Duplicate probability
Recommendation
Short reason
```

When the user opens a job, these details can be displayed.

The dashboard should remain clean.

---

# 43. Notifications

Notifications are required for:

### Critical errors

* Browser failure
* Authentication expiry
* Security challenge
* Critical Naukri error
* System-level Gemini failure

### External application

Notify with:

* Company
* Job title
* Link
* Reason external application was not submitted

### Daily summary

Send an evening summary around:

**8–9 PM**

The user should not receive an individual notification for every successful routine application.

---

# 44. Daily Summary

Example:

```text
Today's Job Application Summary

Jobs discovered: 86
Jobs analyzed: 42
Applications submitted: 11
Jobs skipped: 29
Needs attention: 2
External applications: 3

Top reasons for skipping:
• Experience mismatch
• Location mismatch
• Duplicate

AI usage:
42 analyses
8 cached
```

Exact content can evolve.

---

# 45. Email

V1 can use SMTP.

Email should be configurable through secure settings.

Never expose credentials in:

* frontend
* logs
* Git
* source code

---

# 46. Database

V1:

**SQLite**

ORM:

**SQLAlchemy**

Future:

**PostgreSQL**

The database layer should avoid tightly coupling application logic to SQLite.

---

# 47. Core Database Entities

## User

Represents the local application user.

## Profile

Stores confirmed resume-derived information.

## JobPreference

Stores user-defined job criteria.

## JobProfile

Stores multiple search/job categories.

## Job

Stores discovered jobs.

## JobAnalysis

Stores structured Gemini analysis.

## Application

Stores application attempts/results.

## ApplicationAnswer

Stores application questions and answers.

## Feedback

Stores explicit user feedback.

## AgentRun

Stores each automation run.

## Notification

Stores notification history where required.

## AIUsage

Tracks Gemini usage.

---

# 48. Suggested Job Schema

```text
id
platform
external_job_id
url
title
company
description
location
salary_min
salary_max
experience_min
experience_max
employment_type
posted_at
discovered_at
last_seen_at
status
created_at
updated_at
```

---

# 49. Suggested JobAnalysis Schema

```text
id
job_id
match_score
role_match
skill_match
experience_match
location_match
salary_match
job_quality
duplicate_probability
suspicious
recommendation
short_reason
model
created_at
```

---

# 50. Suggested Application Schema

```text
id
job_id
status
application_method
started_at
applied_at
failure_reason
skip_reason
external_url
created_at
updated_at
```

---

# 51. Suggested Profile Schema

```text
id
name
education
experience
skills
projects
certifications
current_role
location
ctc
notice_period
resume_path
resume_hash
confirmed
updated_at
```

---

# 52. Suggested Preferences Schema

```text
id
job_titles
search_terms
locations
minimum_salary
employment_types
aggressiveness
max_daily_applications
max_hourly_applications
created_at
updated_at
```

---

# 53. Technology Stack

## Backend

**Python 3.12+**

Framework:

**FastAPI**

## Browser Automation

**Playwright**

Browsers:

* Chrome
* Edge

## AI

**Google Gemini API**

Use the official Google GenAI Python SDK.

## Validation

**Pydantic**

## Database

**SQLite**

ORM:

**SQLAlchemy**

## Scheduler

**APScheduler**

## Resume extraction

**PyMuPDF**

## Frontend

**React**

**TypeScript**

**Tailwind CSS**

## Charts

**Recharts**

## Testing

**pytest**

## Packaging

**PyInstaller**

## Version control

**Git/GitHub**

---

# 54. AI Architecture

Create an abstraction layer:

```text
AIProvider
   │
   └── GeminiProvider
```

Future:

```text
AIProvider
 ├── GeminiProvider
 ├── OpenAIProvider
 ├── OtherProvider
```

The rest of the application should not directly depend on Gemini-specific implementation details.

---

# 55. Platform Architecture

Naukri should be implemented as an adapter.

```text
JobPlatformAdapter
        │
        └── NaukriAdapter
```

Future:

```text
JobPlatformAdapter
 ├── NaukriAdapter
 ├── LinkedInAdapter
 ├── IndeedAdapter
 └── OtherAdapter
```

The core matching/rules/application architecture should not need major rewrites when another platform is added.

---

# 56. Proposed System Architecture

```text
                    React Dashboard
                          │
                          ▼
                     FastAPI API
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
     Profile          Agent Engine       Settings
     Service              │
                           ▼
                       Scheduler
                           │
                           ▼
                    Job Discovery
                           │
                           ▼
                    Naukri Adapter
                           │
                           ▼
                       Playwright
                           │
                           ▼
                      Naukri
                           │
                           ▼
                    Job Extraction
                           │
                           ▼
                Python Hard Filtering
                           │
                           ▼
                    Duplicate Check
                           │
                           ▼
                    Gemini Provider
                           │
                           ▼
                  Pydantic Validation
                           │
                           ▼
                 Final Rules Engine
                           │
                  ┌────────┴────────┐
                  ▼                 ▼
                SKIP              APPLY
                                    │
                                    ▼
                            Application Engine
                                    │
                                    ▼
                               Playwright
                                    │
                                    ▼
                              Naukri Form
                                    │
                                    ▼
                               Application
                                    │
                                    ▼
                               Database
```

---

# 57. Project Structure

Recommended initial structure:

```text
naukri-ai-agent/
│
├── docs/
│   ├── MASTER_PRD.md
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT_STATUS.md
│   └── DECISIONS.md
│
├── backend/
│   ├── api/
│   ├── services/
│   │   ├── naukri/
│   │   ├── gemini/
│   │   ├── matching/
│   │   ├── applications/
│   │   ├── notifications/
│   │   ├── profile/
│   │   └── learning/
│   │
│   ├── models/
│   ├── schemas/
│   ├── database/
│   ├── scheduler/
│   ├── core/
│   └── main.py
│
├── frontend/
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── hooks/
│       ├── services/
│       └── types/
│
├── data/
│   └── resume/
│
├── logs/
│
├── tests/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── run.py
```

---

# 58. Configuration & Secrets

Development:

```text
.env
```

Production Windows application:

Use secure Windows-local credential storage where practical.

Gemini API key must NEVER be:

* Hardcoded
* Stored in frontend code
* Committed to Git
* Printed in logs
* Returned through API responses

`.env` must be included in `.gitignore`.

---

# 59. Logging

The application should maintain structured logs.

Logs should contain:

* Timestamp
* Component
* Event
* Severity
* Job ID where applicable
* Application ID where applicable
* Error category
* Short diagnostic message

Logs must NOT contain:

* API keys
* Passwords
* Sensitive authentication tokens
* Unnecessary private resume data

---

# 60. Error Taxonomy

Use clear error categories:

```text
AUTH_ERROR
SECURITY_ERROR
BROWSER_ERROR
NETWORK_ERROR
NAUKRI_ERROR
AI_ERROR
AI_QUOTA_ERROR
VALIDATION_ERROR
APPLICATION_ERROR
DATABASE_ERROR
CONFIGURATION_ERROR
```

This allows the UI and notification system to react appropriately.

---

# 61. Agent Execution Safety

The agent must follow these principles:

### Principle 1

Hard filters cannot be overridden by AI.

### Principle 2

AI cannot directly execute browser actions.

### Principle 3

Invalid AI output cannot reach execution.

### Principle 4

Security challenges stop automation.

### Principle 5

External applications are never automatically submitted.

### Principle 6

Application limits cannot be exceeded.

### Principle 7

Duplicate applications must be prevented.

### Principle 8

Unknown factual information must never be fabricated.

### Principle 9

Critical errors stop the agent.

### Principle 10

Single-job failures should not unnecessarily stop the entire system.

---

# 62. Application State Machine

```text
DISCOVERED
    ↓
FILTERED
    ↓
AI_ANALYZED
    ↓
APPROVED_BY_RULES
    ↓
APPLICATION_STARTED
    ↓
SUBMITTED
    ↓
APPLIED
```

Alternative paths:

```text
DISCOVERED
    ↓
FILTERED
    ↓
SKIPPED
```

```text
AI_ANALYZED
    ↓
NEEDS_ATTENTION
```

```text
APPROVED_BY_RULES
    ↓
EXTERNAL_APPLICATION
    ↓
NEEDS_ATTENTION
```

```text
APPLICATION_STARTED
    ↓
NEEDS_ATTENTION
```

---

# 63. Performance Strategy

The system should minimize unnecessary work.

Preferred order:

```text
Discovery
↓
Cheap Python filtering
↓
Deduplication
↓
AI only when necessary
↓
Final validation
↓
Application
```

Do not send every discovered job to Gemini.

---

# 64. Caching

Cache:

* Job analysis
* Resume profile extraction
* Duplicate checks where safe
* Other deterministic results where useful

A job should not be re-analyzed simply because it appeared again in search results.

---

# 65. Recovery

If the application crashes:

1. Persist state frequently.
2. Record agent run.
3. On restart, identify incomplete operations.
4. Avoid duplicate submissions.
5. Recheck application state before attempting a potentially duplicate application.
6. Resume safely.

The system should favor:

```text
Don't accidentally apply twice
```

over:

```text
Apply again just to be safe
```

---

# 66. Security

The application is local-first, but security is still important.

Requirements:

* Secure API-key storage
* No password storage
* Protected local configuration
* Sanitized logs
* Input validation
* Pydantic validation
* API authentication/localhost restrictions where appropriate
* Safe file handling
* Resume files stored locally
* No unnecessary external data transmission

Resume data should only be sent to Gemini when required for the AI operation.

---

# 67. Testing Requirements

Testing should include:

## Unit tests

* Salary rules
* Experience rules
* Location rules
* Employment type rules
* Duplicate detection
* Application limits
* AI schema validation
* Profile parsing
* State transitions

## Integration tests

* Database
* FastAPI
* Gemini provider
* Naukri adapter
* Scheduler
* Notification system

## Browser tests

Use controlled/test environments where possible.

Test:

* Login/session detection
* Job extraction
* Application detection
* Form filling
* External redirect detection
* Security challenge detection

---

# 68. Testing Rule Engine Examples

The final rules engine must have deterministic tests.

Example:

```text
Location = Hyderabad only
→ SKIP
```

```text
Location = Bengaluru / Hyderabad
→ APPLY if all other rules pass
```

```text
Salary = ₹3–5 LPA
→ APPLY
```

```text
Salary = ₹2–4 LPA
→ SKIP
```

```text
Experience required = 3 years
User experience = 1 year
→ SKIP
```

```text
Employment = Full-time
→ eligible
```

```text
Already applied = true
→ SKIP
```

---

# 69. Dashboard UX Principle

The application should look like a real professional product.

Avoid a developer-only interface.

The primary screen should immediately communicate:

```text
Agent Status
Applications Today
Jobs Found
Match/Skip Activity
Issues
AI Usage
```

Live activity should be visible but concise.

---

# 70. Multiple Accounts

V1:

```text
One Naukri account
```

Architecture should support future:

```text
Multiple accounts
```

Each future account should have isolated:

* Browser session
* Profile
* Preferences
* Application history
* AI context
* Limits

---

# 71. Future Platform Expansion

The core system should eventually support:

```text
Naukri
LinkedIn
Indeed
Other job platforms
```

Each platform should implement a common interface.

Example:

```python
class JobPlatformAdapter:
    discover_jobs()
    get_job_details()
    detect_application_type()
    start_application()
    submit_application()
    get_auth_status()
```

Platform-specific behavior stays inside the adapter.

---

# 72. Future Cloud Architecture

The system should eventually support:

```text
Web Dashboard
      ↓
API
      ↓
Cloud Scheduler
      ↓
Job Queue
      ↓
Automation Workers
      ↓
Browser Workers
      ↓
Database
```

Potential future capabilities:

* 24/7 monitoring
* Remote execution
* Multiple accounts
* Multiple platforms
* Centralized analytics
* Mobile notifications

These are not V1 requirements.

---

# 73. Development Phases

## Phase 1 — Foundation & Architecture

Build:

* Repository
* Python backend
* FastAPI
* React frontend
* SQLite
* SQLAlchemy
* Configuration
* Logging
* Base architecture
* Core interfaces
* Documentation system
* Health endpoint
* Basic dashboard shell

No real Naukri automation yet.

---

## Phase 2 — Resume & User Profile

Build:

* PDF upload
* Resume extraction
* Gemini profile extraction
* Pydantic profile schema
* Profile review/edit UI
* Confirmation flow
* Job preferences
* Multiple job profiles

---

## Phase 3 — Gemini AI Engine

Build:

* Gemini provider
* Strict JSON output
* Pydantic validation
* Job-analysis schema
* Profile-analysis schema
* AI usage tracking
* Retry logic
* Quota handling
* Caching

---

## Phase 4 — Matching & Rules Engine

Build deterministic:

* Location rules
* Experience rules
* Salary rules
* Employment rules
* Duplicate rules
* Application limits
* Final safety gate
* AI recommendation integration

---

## Phase 5 — Naukri Job Discovery

Build:

* Browser session
* Chrome support
* Edge support
* Naukri adapter
* Search execution
* Job extraction
* Job detail extraction
* Posted-date extraction
* Deduplication
* Discovery persistence

---

## Phase 6 — Naukri Application Automation

Build:

* Naukri-native application detection
* Form detection
* Fixed factual answers
* Gemini open-ended answers
* Required-field detection
* Final safety validation
* Application submission
* Application history
* External-site detection

---

## Phase 7 — Scheduler & Continuous Agent

Build:

* Hourly discovery
* Adaptive scheduling
* Application limits
* Auto-start
* Start/Stop controls
* Recovery after PC restart
* Job queue
* AI quota queue
* Agent state machine

---

## Phase 8 — Dashboard

Build professional UI:

* Overview
* Live agent
* Applications
* Jobs
* Job details
* Match analysis
* History
* Settings
* AI usage
* Statistics

---

## Phase 9 — Notifications

Build:

* Email
* Critical-error notifications
* Authentication notifications
* Security challenge notifications
* External application notifications
* Evening 8–9 PM summary

Implementation status: the Phase 9 notification boundary, persisted history, SMTP configuration, required event helpers, dashboard history endpoint, minimal dashboard visibility, and daily-deduplicated evening summary are implemented and covered by offline tests. Real SMTP delivery is intentionally not exercised in development; missing configuration and delivery failures are recorded as failed notifications without changing application state.

---

## Phase 10 — Testing, Security & Windows Packaging

Build:

* Unit tests
* Integration tests
* Browser tests
* Recovery tests
* Security hardening
* Credential handling
* PyInstaller package
* Windows installer/run experience

---

## Phase 11 — Integration & Production Hardening

Final integration:

```text
Profile
+
AI
+
Rules
+
Naukri
+
Application
+
Scheduler
+
Dashboard
+
Notifications
```

Perform:

* End-to-end testing
* Crash recovery testing
* Duplicate prevention testing
* AI failure testing
* Security challenge testing
* Quota exhaustion testing
* Application-limit testing
* Performance optimization
* Documentation completion

---

# 74. Master Documentation Rule

This PRD is the **single source of truth**.

It must be stored in:

```text
docs/MASTER_PRD.md
```

Every future development phase must read this file before making changes.

The coding agent must NOT ask the user to upload the PRD again.

Future phase prompts should say:

```text
SOURCE OF TRUTH:
Read docs/MASTER_PRD.md before making any changes.

Also inspect:
docs/ARCHITECTURE.md
docs/DEVELOPMENT_STATUS.md
docs/DECISIONS.md

Treat MASTER_PRD.md as the authoritative product specification.
```

---

# 75. Phase Continuity Rule

Every completed phase must update:

```text
docs/DEVELOPMENT_STATUS.md
```

with:

* Completed features
* Files created/modified
* Database changes
* APIs added
* Components added
* Tests added
* Known limitations
* Remaining work
* Important implementation decisions

This allows the next phase to continue even if the coding agent has no memory of the previous conversation.

---

# 76. Architecture Decision Log

Important architectural decisions must be recorded in:

```text
docs/DECISIONS.md
```

Examples:

```text
Why Playwright instead of Selenium
Why SQLite
Why FastAPI
Why React
Why direct Gemini API
Why Pydantic
Why adapters
Why local-first
Why external applications are not automated
```

Do not silently replace major architectural decisions.

If a change becomes necessary, document it.

---

# 77. Definition of Done

A phase is not considered complete merely because code was generated.

Each phase must:

1. Implement its requirements.
2. Integrate with existing architecture.
3. Run successfully.
4. Include appropriate tests.
5. Avoid breaking previous functionality.
6. Update documentation.
7. Update development status.
8. Record major decisions.
9. Leave the project in a usable state.
10. Clearly identify remaining limitations.

---

# 78. Coding-Agent Operating Rules

Every coding agent working on this project must follow:

### Rule 1

Read:

```text
docs/MASTER_PRD.md
```

before coding.

### Rule 2

Read the current:

```text
docs/DEVELOPMENT_STATUS.md
docs/ARCHITECTURE.md
docs/DECISIONS.md
```

### Rule 3

Do not reimplement existing functionality.

### Rule 4

Do not remove existing functionality unless explicitly required.

### Rule 5

Do not make Gemini more powerful than specified in this PRD.

### Rule 6

Do not bypass Naukri security controls.

### Rule 7

Do not automate external job applications.

### Rule 8

Do not fabricate user information.

### Rule 9

Use typed schemas and validation.

### Rule 10

Keep platform-specific automation isolated.

### Rule 11

Keep AI-provider-specific implementation isolated.

### Rule 12

Run tests before declaring the phase complete.

### Rule 13

Update project documentation after implementation.

### Rule 14

If requirements conflict with this PRD, stop and identify the conflict rather than silently changing the product behavior.

---

# 79. V1 Success Criteria

V1 is successful when a user can:

```text
Install application
      ↓
Upload resume
      ↓
Review AI-extracted profile
      ↓
Configure job preferences
      ↓
Log into Naukri
      ↓
Start agent
      ↓
Agent discovers jobs
      ↓
Hard filters remove invalid jobs
      ↓
Gemini evaluates eligible jobs
      ↓
Python validates decisions
      ↓
Agent applies to eligible Naukri-native jobs
      ↓
Application is recorded
      ↓
Agent continues
      ↓
Dashboard shows activity
      ↓
Evening summary is generated
```

And the system reliably:

* Prevents duplicate applications.
* Enforces hard filters.
* Does not fabricate answers.
* Does not submit external applications.
* Stops for CAPTCHA/security challenges.
* Stops for critical errors.
* Handles Gemini quota limitations.
* Recovers safely after restart.
* Maintains application history.
* Provides useful visibility through the dashboard.

---

# 80. Product Philosophy

The product should not be:

> "An AI that can do anything."

It should be:

> **A controlled autonomous job-application agent where AI provides intelligence, deterministic software provides safety, and the user remains the authority over personal preferences and factual information.**

The most important architectural principle is:

```text
AI decides what a job means.
Rules decide whether it is allowed.
Automation executes only what the rules approve.
```

---

# 81. Production Backend Preparation (Phase 8.1)

The backend has been prepared for production hosting with enhanced configuration, security, and monitoring. This checkpoint does NOT implement actual cloud deployment but ensures the backend is ready for hosted environments.

## Production Configuration

- Environment separation: LOCAL_WINDOWS (V1) vs CLOUD (future)
- Production mode detection: development vs production
- CORS origins: configurable via FRONTEND_ORIGINS (comma-separated)
- Database URL: supports SQLite (default) and PostgreSQL
- Runtime environment: configurable via RUNTIME_ENVIRONMENT
- All configuration driven by environment variables with NAUKRI_AGENT_ prefix

## CORS Configuration

- Development mode: allows localhost origins for convenience
- Production mode: uses only configured origins from FRONTEND_ORIGINS
- Multiple origins supported via comma-separated list
- Wildcard origins NOT used in production
- Configurable methods: GET, POST, PUT, OPTIONS, DELETE
- Configurable headers: Content-Type, X-Request-ID, Authorization

## Health and Readiness Endpoints

- Liveness endpoint (/api/health): simple API process status
- Readiness endpoint (/api/readiness): detailed component status
- Readiness checks: database, configuration, storage, AI provider, runtime environment
- Production mode validates required API keys
- Component status: healthy/unhealthy with detailed error messages
- Ready for container orchestration and health checks

## Error Handling

- Catch-all exception handler prevents sensitive information exposure
- Generic exceptions return safe error messages without stack traces
- Application errors return structured responses with error categories
- Validation errors return 422 with category information
- No filesystem paths, environment variables, or secrets in API responses

## Logging

- Development mode: standard JsonFormatter for debugging
- Production mode: SafeJsonFormatter with automatic redaction
- Sensitive keys redacted: api_key, password, token, secret, credential, auth
- Structured logging with timestamp, level, message, and component
- Extra fields: component, event, error_category, request_id, job_id, application_id
- Logs never contain API keys, credentials, or sensitive user data

## Database Configuration

- SQLite default for local development (sqlite:///./data/naukri_agent.db)
- PostgreSQL support via DATABASE_URL (postgresql://user:pass@host:port/db)
- SQLite directory creation for both relative and absolute paths
- No SQLite-only assumptions preventing hosted operation
- Database initialization works correctly in both modes
- Connection pooling and session management via SQLAlchemy

## Storage Configuration

- StorageService abstraction for file operations
- Local filesystem storage for LOCAL_WINDOWS (V1)
- Methods: store_file, read_file, delete_file, file_exists, get_file_size
- Directory management: create_directory, delete_directory
- Path resolution with resolve_path()
- Ready for future object storage (S3/Azure/GCS) without code changes

## Browser/API Separation

- API process does NOT auto-start Playwright browser
- Browser only starts when explicitly called via DiscoveryService
- Clear separation between API process and browser worker
- RuntimeContext controls browser automation support
- LOCAL_WINDOWS: browser automation supported
- CLOUD: browser automation disabled (future remote browser)
- Safe for future cloud architecture with separate browser worker

## Frontend API Configuration

- Environment-based backend URL via VITE_API_BASE_URL
- Development: http://127.0.0.1:8000/api (default)
- Production: https://<hosted-api>/api (configurable)
- No hardcoded localhost in production frontend code
- Frontend build passes TypeScript compilation
- Frontend build: 267.10 kB JS, 28.43 kB CSS

## Security Considerations

- CORS origins configured, no wildcard in production
- Error responses don't expose stack traces or internal details
- Logging redacts sensitive information automatically
- Configuration properties don't expose API keys or secrets
- API responses never return credentials or sensitive configuration
- No filesystem paths in API responses
- No environment variables in API responses
- No secrets in logs or error messages

## Testing

- Comprehensive production configuration tests (32 new tests)
- Tests for environment separation, CORS, health/readiness, error handling
- Tests for database configuration, storage configuration, browser/API separation
- Total: 401 tests passing
- Frontend build: PASSED (TypeScript compilation successful)

## Remaining Cloud Deployment Work

This checkpoint prepared the backend for production hosting but did NOT implement:

- Actual cloud deployment (Railway, Render, AWS, Azure)
- PostgreSQL production database provisioning
- Object storage provisioning (S3/GCS/Azure Blob)
- Cloud browser worker implementation
- 24/7 Naukri automation
- Docker deployment
- Kubernetes deployment

These belong to future Phase 8 checkpoints.

---

# 82. Hosted FastAPI Deployment Preparation (Phase 8.3)

Phase 8.3 prepares the existing API for normal hosted web-service operation. It does not deploy the service and does not move browser automation to the cloud.

```text
React frontend
      ↓
Hosted FastAPI API
      ↓
PostgreSQL
```

The hosted process is started with `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`. The repository provides a `Procfile` with a local port fallback and a minimal `render.yaml`; neither contains secrets.

Production configuration uses the existing `NAUKRI_AGENT_` environment prefix. A production instance must set `NAUKRI_AGENT_APP_ENV=production`, `NAUKRI_AGENT_DATABASE_URL` to PostgreSQL, `NAUKRI_AGENT_GEMINI_API_KEY`, and explicit comma-separated `NAUKRI_AGENT_FRONTEND_ORIGINS`. Readiness reports configuration as not ready when these values are absent or origins include a wildcard. Local development remains SQLite-capable.

`GET /api/health` is a cheap liveness endpoint and does not contact the database or Gemini. `GET /api/readiness` checks database connectivity and safe application configuration. Production CORS accepts only configured origins and does not enable browser credentials.

Production JSON logging centrally redacts API keys, passwords, tokens, secrets, credentials, authorization headers, cookies, session data, nested values, URL userinfo, and exception details. The frontend continues to use `VITE_API_BASE_URL`, with its localhost default only for development.

Known limitations: no Render/Railway deployment has been performed; PostgreSQL provisioning, frontend hosting, object storage, remote browser workers, and 24/7 cloud automation are not included.

# 83. Vercel Frontend to Hosted FastAPI Preparation (Phase 8.4)

Phase 8.4 prepares the existing Vite dashboard to be hosted on Vercel and connect to the hosted FastAPI service. It does not deploy a Vercel project, a backend, or a database.

The frontend uses public `VITE_API_BASE_URL` configuration. In local development, an omitted value falls back to `http://127.0.0.1:8000`; in production an API URL must be provided, and the client never silently targets localhost. The client normalizes trailing slashes, accepts either an origin or an existing `/api` suffix, and sends requests to the backend API paths exactly once.

All dashboard API consumers use the same client. It applies a request timeout and translates network failure, timeout, HTTP failure, and malformed responses into safe user-facing messages without showing raw backend details. `VITE_` variables are browser-visible and may contain only public values such as the API URL. They must never contain Gemini keys, database credentials, Naukri credentials, cookies, sessions, or private tokens.

The existing root `vercel.json` installs the `frontend` dependencies, runs its Vite build, and publishes `frontend/dist`. The dashboard uses hash links and in-page state, not browser-path client-side routing, so no SPA rewrite is required. The eventual Vercel origin must be configured on the hosted backend through `NAUKRI_AGENT_FRONTEND_ORIGINS`; production CORS remains explicit and credentialed browser requests remain disabled.

Known limitations: no Vercel deployment, hosted URL verification, PostgreSQL provisioning, remote browser worker, or cloud automation is included.

# 84. Responsive Mobile Naukri-Inspired UX (Phase 8.4.1)

Phase 8.4.1 implements a fully responsive mobile-first frontend experience inspired by Naukri's mobile UX patterns and interaction hierarchy.

**Mobile Architecture:**
- Mobile header (56px sticky) with hamburger menu, brand, and notifications.
- Sidebar converted to a mobile drawer that slides in from the left with semi-transparent backdrop overlay.
- Bottom navigation bar (56px sticky) with 5 primary destinations: Home (Overview), Activity, Jobs (disabled), Applications (disabled), More (secondary routes).
- All touch targets minimum ~44x44px for accessibility.

**Responsive Design:**
- Mobile-first CSS with breakpoints at 320px, 360px, 375px, 390px, 414px, 480px, 768px, 1024px, 1280px, 1440px+.
- Desktop layout preserved: sidebar (260px fixed) + topbar + content on screens >768px; mobile header/bottom nav hidden.
- Tablet layout (768px-1024px): sidebar collapses to icons; mobile navigation available.
- Responsive grids: metrics 4-col → 2-col → 1-col; analytics 3-col → 2-col → 1-col; forms 2-col → 1-col.
- Responsive component layouts: cards, buttons, forms, upload zones, status panels all adapt to viewport width.

**Mobile UX Pattern (Naukri-inspired, not copied):**
- Compact mobile header with contextual actions.
- Drawer navigation for secondary menu (auto-closes on selection).
- Bottom navigation for primary destinations.
- Touch-optimized spacing and controls.
- Efficient vertical scrolling information hierarchy.
- Clear status indicators and agent state display.
- Inspired by Naukri's mobile app interaction patterns; uses original Naukri Agent branding and design system.

**Touch & Typography:**
- Form inputs 16px font on mobile (prevents iOS auto-zoom).
- Focus states preserved with visible outline and background.
- No hover states required for mobile interaction.
- Responsive typography: h1 26px (desktop) → 20px (small mobile); h2 18px → 16px.
- Body text readable at all sizes with appropriate line-height and letter-spacing.

**No Backend Changes:**
- Jobs and Applications routes remain disabled (pages do not exist).
- All API contracts unchanged.
- Gemini, scheduler, matching, automation logic unchanged.
- Database, Vercel configuration, Render configuration unchanged.
- No environment variables changed.

**Verification & Testing:**
- CSS logic verified for all breakpoints.
- Build passes with no TypeScript errors.
- Desktop layout and functionality preserved.
- Known limitation: responsive behavior has been CSS-verified and logically tested, but browser-based device simulation at actual viewport sizes was not performed.

Known limitations: responsive layout tested via CSS audit and logical verification; actual device/browser simulation testing at critical breakpoints (320px, 375px, 480px, etc.) was not performed. Mobile UX patterns are Naukri-inspired (patterns only, not assets or proprietary UI); all implementation is original Naukri Agent code.

# 85. Worker Foundation and Registration (Phase 8.5A)

Phase 8.5A introduces a persistent worker identity layer to support future cloud browser coordination without modifying current Windows/Naukri execution.

**Worker Identity Model:**
- Worker model with persistent worker_id (UUID, unique, indexed).
- WorkerType enum: LOCAL_WINDOWS (current V1), CLOUD_BROWSER (future identity-only, not execution).
- WorkerStatus enum: STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR.
- Runtime environment identifier for deployment context.
- Lifecycle timestamps: created_at, updated_at, started_at, stopped_at (UTC).
- No sensitive data: passwords, cookies, sessions, API keys, or Naukri credentials never stored.

**Worker Service Operations:**
- `register_worker(type, environment)`: safely repeatable; same type+environment returns same worker_id.
- `get_worker(worker_id)`: retrieve by ID; returns None if not found.
- `list_workers()`: list all workers with active count (excludes STOPPED/ERROR states).
- `update_worker_status(worker_id, status)`: transition status with lifecycle tracking.

**Worker API Endpoints:**
- `GET /api/worker/status`: list all registered workers and active count.
- `POST /api/worker/register`: register new worker or return existing registration.
- `GET /api/worker/{worker_id}`: retrieve specific worker status; 404 if not found.

**Database Integration:**
- SQLAlchemy ORM model following existing patterns (Mapped types, mapped_column, UTC timestamps).
- Compatible with both SQLite (V1) and PostgreSQL (production).
- Worker table registered in metadata; no migration framework added.

**Testing & Verification:**
- 12 focused tests: type validation, status validation, registration, repeat registration, retrieval, status updates, persistence, listing, active count, API endpoints.
- All 426 existing backend tests pass; no regression.
- Frontend build passes with no changes.
- No changes to existing scheduler, Playwright, NaukriAdapter, or ApplicationRunner.

**Current Scope (8.5A):**
- Worker identity and registration.
- Status lifecycle and transitions.
- Persistent database storage.
- Minimal API for registration and retrieval.
- Idempotent registration behavior.

**Deferred to Future Phases (8.5B-D):**
- Distributed task claiming with PostgreSQL row locking.
- Worker heartbeat and stale-worker detection/recovery.
- Browser lifecycle refactoring (currently direct Playwright calls).
- Cloud browser worker execution.
- Task assignment and worker coordination.

**Architectural Guarantee:**
- Current Windows/local execution path remains exactly as implemented.
- Scheduler-driven execution continues without change.
- Naukri discovery and automation untouched.
- No changes to AgentState lifecycle or state machine.
- No changes to existing API contracts.

Known limitations: Registration does not yet trigger background services or lifecycle hooks. Task claiming, heartbeat, and cloud execution are deferred. Worker identity is persistent but does not yet coordinate work or execute jobs.

# END OF MASTER PRD
## Phase 10 Application Boundary Fix — Offline Checkpoint

The application runner now preserves the safety model while requiring explicit
post-click Applied evidence, scoping questions to visible editable application
containers, using computed profile experience with the existing +2 tolerance,
classifying before recording an application start, rechecking immediately before
Apply, and preventing automatic retries after unresolved attempts. This checkpoint
was tested only with isolated SQLite unit tests. No live Naukri activity, Gemini
call, Apply/Submit click, or real submission occurred; Phase 10 live validation
remains incomplete and the successful application count is 0.
