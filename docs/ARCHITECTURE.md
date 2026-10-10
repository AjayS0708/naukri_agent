# Architecture

## E5-R3 — Freshness-First Discovery & Advisory-Only AI Recommendations

**Status:** COMPLETE — subjective AI recommendation no longer blocks; discovery and candidate selection are freshness-first

**E5-R3 Architecture:**

The final safety gate is the single authoritative decision point before submission. Gemini's output remains advisory at that gate: only the explicit `suspicious` fraud flag blocks, while every deterministic rule is unchanged. To keep the bounded Gemini budget aimed at genuinely new listings, discovery now budgets **new distinct jobs** and candidate ordering is freshness-first.

**Safety gate (`backend/services/applications/service.py`):**

```text
run_final_safety_gate(job, profile, preference, job_analysis)
  1. Job exists
  2. Profile confirmed
  3. Duplicate / already-APPLIED protection
  4. Location overlap
  5. Fresher experience rule + strict IT-scope
  6. Salary minimum (undisclosed allowed; disclosed 0 rejected)
  7. Employment type
  8. Title / search scope
  9. job_analysis.suspicious == True  -> BLOCK   (advisory Gemini; only the fraud flag)
     AI recommendation (APPLY/SKIP/NEEDS_ATTENTION) -> NOT a block
```

**Discovery freshness (`backend/services/naukri/adapter.py`, `backend/services/discovery/service.py`):**

```text
Naukri card -> _parse_posted_date(text): tz-aware UTC or None (never fabricated)
  today / just now / yesterday / N days|weeks ago / 30+ days ago / absolute formats

adapter.search_jobs(): emit each page's cards via _posted_sort_key
  known dates newest-first, unknown dates last; pagination unchanged

DiscoveryService.run_discovery():
  jobs_discovered = all scanned cards (metric)
  max_cards budget applies to NEW distinct jobs
  duplicate -> _refresh_duplicate_job: last_seen advances; newer grounded posted_at adopted only
```

**Candidate ordering (`backend/services/autonomous_cycle/service.py`):**

```text
posted_freshness_key(posted_at): known -> (0, -timestamp); None -> (1, 0.0)
job_freshness_key(job): (posted_freshness_key(posted_at), -discovered_at)

_apply_hard_filters_and_enqueue(): eligible sorted by (job_freshness_key, -match_score)
  -> Gemini budget spent on newest-posted eligible candidates, unknown last
_run_applications(): candidates ordered posted_at DESC (nulls last), discovered_at DESC
```

**Preserved boundaries:** hard filters, duplicate protection, IT-scope/role matching, salary/experience/employment-type policy, `max_applications`/Gemini budgets, and all application limits are unchanged. Unknown posting dates are stored as `None` and sorted last; no date is invented. No URL/sort parameter was added to Naukri requests.

**Test coverage:** 270 focused tests pass across `test_application_safety_gate.py`, `test_naukri_adapter.py`, `test_discovery.py`, and `test_autonomous_cycle.py` (new `TestFreshnessFirstOrdering`). Full backend suite: 878 passed, 0 failed (2026-10-09); the two failures previously reported here were resolved in E5-R3.1 (an outdated C2 IT-scope test expectation on unmodified `matching/engine.py`; a dashboard test-ordering isolation case). Zero regressions.

**Files modified:** `backend/services/applications/service.py`, `backend/services/naukri/adapter.py`, `backend/services/discovery/service.py`, `backend/services/autonomous_cycle/service.py`, and their four test files.

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

---

## E4-R10 — Targeted Role-Matching Improvement

**Status:** COMPLETE — Role-matching coverage improved

**E4-R10 Architecture:**

E4-R10 extends the deterministic role-matching vocabulary in `ALLOWED_ROLE_FAMILIES` to cover relevant entry-level software and data roles that were previously rejected due to title phrase variations. The implementation is surgical: adds specific keywords aligned with user preferences, preserves all safety boundaries, and maintains strict exclusion of unrelated roles.

**Role-family extensions in `backend/services/matching/engine.py`:**

```python
ALLOWED_ROLE_FAMILIES = {
    "data": ["data analyst", "data engineer", "data analytic", "data science", "power bi"],
    "software": ["software engineer", "software developer", "developer", "software development engineer", "software development"],
    "devops": ["devops"],
    "python": ["python developer"],
    "qa": ["qa", "quality assurance"],
    "sql": ["sql developer"],
}
```

**Changes:**
- Data family: added "data science" (data science intern/fresher roles), "power bi" (BI/reporting roles)
- Software family: added "software development" (matches "Software Development Trainee" preference)
- New QA family: "qa", "quality assurance" (matches "QA Engineer Fresher" preference)
- New SQL family: "sql developer" (matches "SQL Developer Fresher" preference; standalone "sql" excluded to prevent SQL Server Administrator matches)

**Constraints preserved:**
- UNWANTED_SPECIALIZATIONS unchanged: "sales", "java", "php", ".net", "hardware", "mechanical", "manufacturing", "hr", "operations" still excluded
- IT-scope filter unchanged: industry/keyword validation still required
- Experience cap unchanged: max_required_experience_years=0 still enforced
- Salary policy unchanged: min_salary_lpa=4 still enforced
- Employment-type policy unchanged: Full Time, Internship, Contract still enforced
- No "associate" catch-all: explicit phrases only
- No broad role families without concrete test cases

**Test coverage in `backend/tests/test_matching_rules.py`:**

New role-matching tests (10):
- `test_role_targeting_allowed_software_development_trainee`: Software Development Trainee roles
- `test_role_targeting_allowed_data_science_roles`: Data Science Intern/Fresher/Engineer roles
- `test_role_targeting_allowed_power_bi_roles`: Power BI Internship/Developer/Analyst roles
- `test_role_targeting_allowed_qa_roles`: QA Engineer/Quality Assurance roles
- `test_role_targeting_allowed_sql_roles`: SQL Developer/Engineer roles

New regression tests (9):
- `test_role_targeting_reject_sql_server_administrator`: SQL Server Administrator rejected (standalone "sql" exclusion)
- `test_role_targeting_boundary_case_sales_mention_in_tech_role`: Pre-Sales Engineer rejected by unwanted specialization
- `test_role_targeting_boundary_case_hardware_with_software`: Hardware Software Engineer rejected by unwanted specialization
- `test_role_targeting_reject_pure_sales_roles`: Sales Executive/Manager rejected
- `test_role_targeting_reject_mechanical_roles`: Mechanical Engineer rejected
- `test_role_targeting_reject_manufacturing_roles`: Manufacturing/Production Engineer rejected
- `test_role_targeting_reject_hr_roles`: HR Manager/Executive rejected
- `test_role_targeting_reject_operations_roles`: Operations Manager/Executive rejected

Total test count: 54 tests in test_matching_rules.py — all PASS

**Verified outcomes:**
- Job 55 (Software Development Trainee): NOW PASS (was FAIL)
- Job 62 (Data Science Intern/Fresher): NOW PASS (was FAIL)
- Job 64 (Power Bi Internship): NOW PASS (was FAIL)
- Job 87 (Qa Engineer): NOW PASS (was FAIL)
- Job 112 (ELK Engineer): FAIL (not in user preferences, DevOps/monitoring-specific — requires separate decision)

**Integration:**
- No changes to MatchEngine logic flow or filter order
- No changes to AI evaluation or safety gate
- No changes to database schema or API endpoints
- Existing experience, salary, IT-scope, and employment-type tests remain passing

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

## E4-R2 Windows Playwright runtime requirement

E4 live validation has NOT yet succeeded. This checkpoint documents a runtime/environment requirement and resolves the E4 browser-startup blocker; it is documentation-only (no E4 execution, no Dashboard Run click, no `POST /api/autonomous-cycle/run` call, no database modification, no backend/frontend source-code modification, no Playwright configuration change, no asyncio workaround).

**Runtime model on Windows:**

```text
uvicorn --reload
  → spawned reload worker uses WindowsSelectorEventLoop
  → Playwright subprocess bootstrap raises NotImplementedError
  → autonomous cycle fails immediately during browser startup

uvicorn (no --reload)
  → ProactorEventLoop
  → Playwright driver starts successfully
  → configured Chromium persistent context starts successfully
  → standalone smoke test PASS
```

**Verified environment:** Windows 11, Python 3.14.2, FastAPI 0.141.1, Starlette 1.6.0, Playwright 1.63.0. The Playwright installation itself was healthy and the Chromium installation is healthy — the blocker was the event loop selected by the reload worker, not the browser installation.

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

## E4-R autonomous-cycle runtime model

The autonomous-cycle router owns a process-local runtime controller. It atomically holds a single execution lock and maintains separate `active_run` and `last_run` records. `active_state` is only `IDLE` or `RUNNING`; terminal `COMPLETED`/`FAILED` values belong only to `last_run`. A fresh backend process constructs an IDLE runtime, while persisted DiscoveryRun/Application records remain historical evidence. `GET /api/autonomous-cycle/status` snapshots this state without constructing `AutonomousCycle` or scheduling work. Completion, exception, and initialization-failure paths clear `active_run` and release the lock.

**Run #52 exercised this model:** the cycle started, acquired the lock (`active_state=RUNNING`), completed normally, and returned to `IDLE` with `lock_held=false`. The `COMPLETED` terminal status and zero-application outcome are recorded in `last_run`, distinct from the active state. The two accidental curl-triggered E4 attempts on 2026-10-08 that failed before browser startup remain preserved in history.

## CHECKPOINT E3: Safe Dashboard Autonomous-Cycle Control

**Status:** COMPLETE — Dashboard can safely trigger autonomous cycles

**E3 Architecture:**

E3 enables safe manual triggering of the autonomous job application cycle from the dashboard by extracting the existing autonomous cycle logic into a reusable service and adding control/status API endpoints. The architecture preserves all safety boundaries while providing explicit user confirmation, status polling, and completion statistics.

**Service extraction (`backend/services/autonomous_cycle/service.py`):**

The `AutonomousCycle` class is extracted from the CLI (`run_autonomous_cycle.py`) and made available to both CLI and FastAPI:

```text
AutonomousCycle
  ├── __init__(max_applications, dry_run, max_jobs, max_cards, enable_cli_output)
  ├── run() → dict {exit_code, run_id, status, stats}
  ├── _apply_hard_filters_and_enqueue() → stats
  ├── _process_ai_queue() → stats
  └── _run_applications() → stats
```

- CLI: `run_autonomous_cycle.py` → `AutonomousCycle(enable_cli_output=True)`
- FastAPI: `POST /api/autonomous-cycle/run` → `AutonomousCycle(enable_cli_output=False)`

**Control/status routes (`backend/api/routes/autonomous_cycle.py`):**

```text
POST /api/autonomous-cycle/run
    Request: {max_applications: 1-10}
    Response: {run_id, status, max_applications, message}
    → Acquires process-level lock (threading.Lock)
    → Returns 409 Conflict if cycle already running
    → Starts cycle in background (asyncio.create_task)
    → Returns immediately with RUNNING status

GET /api/autonomous-cycle/status
    Response: {status, run_id, started_at, completed_at, max_applications, stats}
    → status: IDLE | RUNNING | COMPLETED | FAILED
    → stats: {jobs_discovered, hard_filtered, queued, completed, applied, needs_attention, external, skipped, failed}
```

**Concurrency protection:**

- Process-level lock (`threading.Lock`) prevents concurrent cycles in V1 local-first deployment
- Future cloud deployment would require distributed locking (deferred)
- Lock acquired on POST, released on cycle completion/failure
- HTTP 409 Conflict returned if lock is already held

**Frontend control flow (`frontend/src/app/App.tsx`):**

```text
mount
  ├── getAutonomousCycleStatus() → initial status
  ├── User clicks "Run Autonomous Cycle"
  │   → Confirmation modal (explains safety rules, max_applications)
  │   → Modal includes selectable Maximum applications control (1-10, default 1)
  │   → User confirms → POST /api/autonomous-cycle/run { max_applications }
  │   → Status changes to RUNNING
  │   → Poll GET /api/autonomous-cycle/status every 4 seconds
  │   → On COMPLETED/FAILED: refresh dashboard data
  └── Cycle stats display on completion
```

**Safety boundaries preserved:**

- Server-authoritative `max_applications` (client cannot control Gemini budget)
- Gemini budget internally derived as `max_applications * 2` (not exposed to client)
- All existing safety rules enforced: D6.1, D6.2, C2, D4/D5, D7
- Frontend only calls control/status APIs — no direct Naukri or Gemini access
- Explicit user confirmation required before execution
- Status polling stops immediately on COMPLETED/FAILED/error

**Test files:**
- `backend/tests/test_autonomous_cycle.py` (92 tests: logic, boundaries, budgets, filtering)
- `backend/tests/test_autonomous_cycle_api.py` (11 tests: API endpoints, concurrency, security)

---

## CHECKPOINT E2: Dashboard Operational Visibility & Safe Control Foundation

**Status:** COMPLETE — Dashboard provides accurate operational view

**E2 Architecture:**

E2 extends the E1 read-only dashboard API layer to provide comprehensive operational visibility without introducing execution controls. The dashboard now shows what the system last did, what happened during the latest discovery/autonomous run, application outcomes, jobs needing attention, and system health status.

**Extended read-only routes (`backend/api/routes/dashboard.py`):**

```text
GET /api/dashboard/summary
    → DiscoverySummary (latest completed run stats + total run count)
    → ApplicationCounts (all-time status counts: applied, needs_attention, skipped, external, failed)
    → ProfileSummary (status, confirmed, original_filename — NO secrets, NO resume_hash, NO profile data)

GET /api/dashboard/recent-applications?limit=N   (N capped at 50)
    → RecentApplicationItem[] (Application JOIN Job — title, company, status, method, dates)
    → NO confirmation_evidence, NO external_url, NO credentials

GET /api/dashboard/needs-attention?limit=N      (N capped at 50) [E2 NEW]
    → NeedsAttentionItem[] (Application JOIN Job — title, company, status, skip_reason, failure_reason)
    → NO confirmation_evidence, NO external_url, NO credentials
```

**Schema layer (`backend/schemas/dashboard.py`):**

All schemas use `model_config = ConfigDict(extra="forbid")` to prevent extra fields from leaking into responses. Fields were chosen by explicit positive enumeration — not by forwarding entire model rows.

**Frontend data flow (`frontend/src/app/App.tsx`):**

```text
mount
  ├── getHealth()           → agent state, service version (existing)
  ├── getNotifications()    → notification feed (existing)
  ├── getDashboardSummary() → metrics + profile status (E1)
  ├── getRecentApplications() → activity feed (E1)
  └── getNeedsAttention()   → needs-attention items (E2 NEW)

Per-section state: loading | error | empty | data
Backend offline → each section degrades independently (no crash)
Retry button → re-fetches all dashboard data (E1)
Refresh button → manual refresh with loading state (E2 NEW)
```

**Security boundaries maintained:**
- No secrets, API keys, credentials, cookies, session data, or environment variable values in any new response
- `confirmation_evidence` (internal applied-state field) excluded from recent-applications and needs-attention schemas
- `resume_hash`, `Profile.data` fields excluded from profile summary schema
- All dashboard endpoints are HTTP GET only — no mutations possible via these routes
- No execution controls added: no "Run Agent", "Apply Now", "Retry Application" buttons

**Test file:** `backend/tests/test_dashboard.py` (30 tests: 21 E1 + 9 E2)

---

## CHECKPOINT E1: Frontend/API Integration Foundation

**Status:** COMPLETE — Dashboard connected to real backend data

**E1 Architecture:**

E1 introduces a minimal, read-only dashboard API layer. The frontend no longer holds static placeholder values; it reads live data from the backend on every page load.

**New read-only routes (`backend/api/routes/dashboard.py`):**

```text
GET /api/dashboard/summary
    → DiscoverySummary (latest completed run stats + total run count)
    → ApplicationCounts (all-time status counts: applied, needs_attention, skipped, external, failed)
    → ProfileSummary (status, confirmed, original_filename — NO secrets, NO resume_hash, NO profile data)

GET /api/dashboard/recent-applications?limit=N   (N capped at 50)
    → RecentApplicationItem[] (Application JOIN Job — title, company, status, method, dates)
    → NO confirmation_evidence, NO external_url, NO credentials
```

**Schema layer (`backend/schemas/dashboard.py`):**

All schemas use `model_config = ConfigDict(extra="forbid")` to prevent extra fields from leaking into responses. Fields were chosen by explicit positive enumeration — not by forwarding entire model rows.

**Frontend data flow (`frontend/src/app/App.tsx`):**

```text
mount
  ├── getHealth()           → agent state, service version (existing)
  ├── getNotifications()    → notification feed (existing)
  ├── getDashboardSummary() → metrics + profile status (NEW E1)
  └── getRecentApplications() → activity feed (NEW E1)

Per-section state: loading | error | empty | data
Backend offline → each section degrades independently (no crash)
Retry button → re-fetches all four calls
```

**Security boundaries maintained:**
- No secrets, API keys, credentials, or cookies in any new response
- `confirmation_evidence` (internal applied-state field) excluded from recent-applications schema
- `resume_hash`, `Profile.data` fields excluded from profile summary schema
- All dashboard endpoints are HTTP GET only — no mutations possible via these routes

**Test file:** `backend/tests/test_dashboard.py` (21 tests)

---

## CHECKPOINT D6.2: Bounded Gemini Candidate Evaluation

**Status:** COMPLETE — Gemini budget enforced BEFORE invocation, with queue isolation

**D6.2 Architecture Change:**

D6.1 bounded the AI queue enqueue budget, but MatchEngine was still calling Gemini for every job that passed deterministic filters BEFORE the enqueue budget was applied. This caused uncontrolled Gemini usage during autonomous cycles.

D6.2 Fix Continuation:
- Fixed `_process_ai_queue()` to only process queue items enqueued by the current autonomous cycle
- Added `enqueued_queue_item_ids` tracking to prevent pre-existing queue items from bypassing the budget
- Fixed candidate sorting to match comment (newest discovered_at first)
- Deduplicated deterministic logic in MatchEngine via shared `_run_deterministic_checks()` method

**New Architecture:**

```text
max_applications = N (actual application attempts)
gemini_budget = max_applications * 2 (NEW Gemini evaluation budget)

Pipeline:
discovered (104)
  ↓
deterministic hard filters (profile, duplicate, role, experience, IT, salary, employment)
  ↓
eligible deterministic candidates (varies)
  ↓
bounded candidate selection (top gemini_budget only; E5-R3: newest posted_at first, unknown last, then discovered_at/match_score)
  ↓
enqueue to AI queue with queue_source="AUTONOMOUS_CYCLE"
  ↓
Gemini analysis (ONLY for bounded items from this cycle)
  ↓
application candidates (varies based on Gemini results)
  ↓
actual applications (capped at max_applications)
```

**Implementation in `backend/services/matching/engine.py`:**

Added shared `_run_deterministic_checks()` method and deterministic-only wrapper:

```python
def _run_deterministic_checks(self, job: Job, profile: Profile, preference: JobPreference) -> MatchDecision:
    """
    Shared deterministic hard filter logic.
    Returns a MatchDecision with decision=APPLY if all checks pass,
    or SKIP/NEEDS_ATTENTION if any check fails.
    """
    # 1. Profile Status
    # 2. Duplicate Detection
    # 3. Role/Title Targeting Check
    # 4. Strict fresher experience and IT-only checks
    # 5. Salary Check
    # 6. Employment type check
    # NO Gemini call

def evaluate_job_deterministic(self, job: Job, profile: Profile, preference: JobPreference) -> MatchDecision:
    """Wrapper for deterministic-only evaluation (used by autonomous cycle)."""
    decision = self._run_deterministic_checks(job, profile, preference)
    if decision.decision == MatchDecisionEnum.APPLY:
        decision.reason = "All deterministic checks passed. Ready for Gemini evaluation."
    return decision

def evaluate_job(self, job: Job, profile: Profile, preference: JobPreference) -> MatchDecision:
    """Normal evaluation: deterministic checks then Gemini."""
    decision = self._run_deterministic_checks(job, profile, preference)
    if decision.decision != MatchDecisionEnum.APPLY:
        return decision
    # Call Gemini only if deterministic checks pass
    analysis = self.ai.analyze_job(job_context, profile_context)
    # ... return final decision with Gemini result
```

**Implementation in `run_autonomous_cycle.py`:**

1. Added `enqueued_queue_item_ids` tracking (line 342)
2. Fixed candidate sorting (line 415-423):
   ```python
   eligible_jobs.sort(
       key=lambda x: (
           -x["match_score"],
           -(x["job"].discovered_at.timestamp() if x["job"].discovered_at else 0)
       )
   )
   ```
3. Updated `_process_ai_queue()` to accept `enqueued_queue_item_ids` (line 463)
4. Only processes queue items enqueued by this cycle (queue_source="AUTONOMOUS_CYCLE")
5. Prevents pre-existing queue items (SCHEDULER, MANUAL) from bypassing Gemini budget
```

**Implementation in `run_autonomous_cycle.py`:**

```python
# Line 379: Use deterministic-only evaluation
match_decision = match_engine.evaluate_job_deterministic(job, profile, preferences)

# Line 418: Apply Gemini budget BEFORE enqueuing
gemini_budget = max(1, self.max_applications * 2)
selected_jobs = eligible_jobs[:gemini_budget]
capped_jobs = eligible_jobs[gemini_budget:]
```

**Example Behavior with max_applications=2:**

- 10 eligible jobs pass deterministic filters
- Top 4 (gemini_budget) selected for Gemini evaluation
- Remaining 6 capped at deterministic stage (no Gemini call)
- Gemini evaluates only 4 jobs
- Application attempts: max 2

**Key Behavioral Changes:**

1. **Deterministic filtering happens first** - no Gemini call until job passes all deterministic rules
2. **Gemini budget applied BEFORE invocation** - only bounded candidates are enqueued to AI queue
3. **Cached analyses respected** - jobs with existing analyses don't trigger new Gemini calls
4. **Deterministically rejected jobs never call Gemini** - early exit before AI evaluation

**Safety Verification:**

- NEW Gemini evaluations during autonomous cycle are bounded BEFORE invocation
- For max_applications=1: NEW Gemini evaluations <= 2
- For max_applications=2: NEW Gemini evaluations <= 4
- For max_applications=3: NEW Gemini evaluations <= 6
- Deterministically rejected jobs never call Gemini
- Cached analyses do not cause NEW Gemini calls
- Application attempts remain hard-capped by max_applications
- Gemini remains advisory, Python rules remain final authority
- All existing safety rules held (duplicate protection, current-run isolation, etc.)

**Test Coverage:**

- 8 new D6.2 regression tests in `TestD62BoundedGeminiEvaluation`
- Total: 98 tests passing in test_autonomous_cycle.py (90 autonomous_cycle + 8 D6.2)
- 0 failures

**Note:** D7 live validation has NOT been performed as part of this checkpoint. D6.2 is a source implementation checkpoint only.

---

## CHECKPOINT D7: Multi-Application Live Validation

**Status:** COMPLETE — Multiple applications validated

**D7 Architecture Validation:**

D7 validated the D6.2 Gemini boundary and multi-application pipeline in a live autonomous cycle with max_applications=2. The system successfully discovered, filtered, evaluated, and applied to multiple independent native Naukri jobs while respecting all safety boundaries.

**Live Validation Results (2026-10-07):**

Command: `python run_autonomous_cycle.py --max-applications 2`

Pipeline Execution:
- Discovery run #32: 103 jobs discovered
- Deterministic hard filters: 60 jobs rejected
- Current-run candidates: 4 jobs selected for Gemini (jobs 99, 86, 85, 59)
- D6.2 Gemini budget: 4 (max_applications=2 × 2)
- NEW Gemini evaluations: 4 (exactly at budget)
- Candidates capped: 5 (jobs 58, 56, 51, 20, 19)
- Budget respected: YES

Current-Run Isolation:
- All 4 AI queue items tagged with queue_source="AUTONOMOUS_CYCLE"
- Pre-existing MANUAL/SCHEDULER queue items NOT processed
- Isolation: PASS

Application Pipeline:
- Job 99 (Neorealm Solutions): EXTERNAL classification → EXTERNAL_APPLICATION recorded (no submission)
- Job 86 (Futureacad): NEEDS_ATTENTION (unpaid internship) → SKIPPED
- Job 85 (Access Automation): NAUKRI_NATIVE → APPLIED (record #24, 1 Apply click)
- Job 59 (Capgemini): NAUKRI_NATIVE → APPLIED (record #25, 1 Apply click)
- Total APPLIED: 2
- Total Apply clicks: 2 (exactly once per applied job)

Safety Boundaries Validated:
- Duplicate protection: PASS (no reapplications to existing jobs)
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

**Status:** COMPLETE — Separated Gemini candidate budget from application limit

**D6.1 Architecture Change:**

Previously, `max_applications` was used as both:
1. Maximum Gemini candidates to enqueue
2. Maximum actual application attempts

This prevented backup candidates when initial candidates were rejected.

**New Architecture:**

```text
max_applications = N (actual application attempts)
max_gemini_candidates = max_applications * 2 (Gemini evaluation budget)

Pipeline:
discovered (104)
  ↓
hard filters (69 rejected)
  ↓
eligible candidates (varies)
  ↓
deterministic ranking by match_score
  ↓
enqueue top max_gemini_candidates (e.g., 4 when max_applications=2)
  ↓
Gemini analysis (bounded by max_gemini_candidates)
  ↓
application candidates (varies based on Gemini results)
  ↓
actual applications (capped at max_applications)
```

**Implementation in `run_autonomous_cycle.py`:**

```python
# Line 413: Bounded Gemini budget
gemini_budget = max(1, self.max_applications * 2)
selected_jobs = eligible_jobs[:gemini_budget]
capped_jobs = eligible_jobs[gemini_budget:]
```

**Example Behavior with max_applications=2:**

- 10 eligible jobs pass hard filters
- Top 4 (max_gemini_candidates) enqueued to Gemini
- Gemini results:
  - Candidate 1 → EXTERNAL (no application attempt)
  - Candidate 2 → NEEDS_ATTENTION (no application attempt)
  - Candidate 3 → APPLY (application attempt 1)
  - Candidate 4 → APPLY (application attempt 2)
- Final: 2 applications attempted, max_applications respected

**Safety Verification:**

- Gemini budget remains explicitly bounded (max_applications * 2)
- No uncontrolled AI processing
- No fallback to AI-free application
- Existing quota exhaustion behavior preserved
- Current-run isolation unchanged
- All existing safety rules held

**Test Coverage:**

- 11 new D6.1 regression tests in `TestD61BoundedGeminiLookAhead`
- Updated 3 existing tests to reflect new budget logic
- Total: 261 tests passing, 0 failures

**Note:** D6.1's original implementation bounded the downstream AI queue, but MatchEngine could still invoke Gemini before that boundary. D6.2 fixes this by bounding NEW Gemini evaluations before invocation.

---

## CHECKPOINT D5: Post-Click Evidence — Reload-Based Confirmation

**Status:** COMPLETE — First verified native application confirmed

**Root cause of D4 Boundary H failure:**

Naukri instant-apply replaces the Apply button with `<span id="already-applied" class="already-applied">Applied</span>` only AFTER the page state is updated server-side. This transition does not happen within the 8-second in-page polling window. The page must be reloaded to show the persistent Applied badge.

**D5 architecture change in `start_application()`:**

```text
Apply click
    ↓
8-second in-page polling (Phase 10 behavior; page-wide Applied scan deferred past the window)
    ↓ timeout without evidence
One bounded page reload (20s, domcontentloaded)
    ↓
post_apply_reload_settle_seconds wait (5s, configurable)
    ↓
_check_security() (security gate preserved)
    ↓
detect_applied_state()
    ↓
APPLIED / FORM_OPENED / NEEDS_ATTENTION
```

**Evidence selectors confirmed live (D5 investigation):**

```html
<!-- What Naukri renders after successful instant-apply -->
<div class="styles_jhc__apply-button-container__...">
  <span id="already-applied" class="styles_already-applied__... already-applied">Applied</span>
</div>
```

Selector `#already-applied` (by ID), `.already-applied` (by class), and `#job_header #already-applied` all match this element. The existing `detect_applied_state()` selectors were already correct — only the timing was wrong.

**New class-level constant:** `post_apply_reload_settle_seconds = 5` (configurable in tests via `adapter.post_apply_reload_settle_seconds = 0`)

**Safety preserved:**
- The reload does NOT click Apply again
- Security check runs on reloaded page
- `detect_applied_state()` uses same strict visible-evidence selectors
- Reload failure → `NEEDS_ATTENTION` (no false APPLIED)
- Single reload only — no loop

**Confirmed live:**
- Application 18 (Job 23): APPLIED, method=NAUKRI_NATIVE, confirmation_evidence="Applied"
- APPLIED count: 1

---

## CHECKPOINT D4: First Verified Native Naukri Application

**Status:** Apply button clicked (evidence confirmed by D5)

The D4 live run reached the physical Apply button for a real Naukri-native job and clicked it once. The 8-second post-click observation window ran but the `detect_applied_state` selectors found no matching Applied state evidence.

**D4 Architecture observations:**

- `_apply_hard_filters_and_enqueue`: Fixed to count pre-existing analyses as `pre_analyzed` (not `hard_filtered`) so the cycle proceeds to applications when all current-run jobs have prior analyses.
- `run_final_safety_gate` title check: Replaced strict configured-title substring matching with `title_matches_allowed_role()` to prevent false rejections of valid-scope jobs.
- `detect_applied_state`: Polls `#already-applied`, `.already-applied`, exact "Applied" text, or `Applied to "<title>"`. None matched for NetM Corporate Solutions job within 8s.
- `_has_visible_application_container`: Polls `[role="dialog"]`, `.apply-drawer`, `.apply-modal`, `form`. None matched either.
- Result: `ApplicationStartResult.NEEDS_ATTENTION` — no retry, no false APPLIED.

**Next investigation boundary:** Inspect what Naukri actually shows after Apply click on a native job — does it open a form not captured by current container selectors, or use different text for the Applied state confirmation?

**APPLIED count: 0 — no verified application has occurred.**

---

## CHECKPOINT D1: Autonomous Discovery Tracking

Current-run job ID tracking prevents historical DB jobs from being processed when live discovery fails. The autonomous cycle now tracks the current DiscoveryRun and only processes jobs from that specific run.

**Current-Run Job ID Tracking:**
- `DiscoveryRun` model includes `current_run_job_ids` column (comma-separated for SQLite compatibility)
- DiscoveryService tracks job IDs in memory during discovery (`current_run_job_ids: set[int]`)
- Both new jobs and existing jobs (duplicates) are added to current-run tracking
- On completion, job IDs are persisted as comma-separated string
- Autonomous cycle parses current-run job IDs and filters jobs to only those in the current run
- Fallback to timestamp comparison if job IDs not available (shouldn't happen)
- Cycle stops with error if `current_run.jobs_discovered == 0`

**Direct Naukri Search Navigation:**
- Removed homepage navigation dependency - navigates directly to search URL
- Simplified security check to single call after search navigation
- Removed bounded wait for homepage elements
- Reduced navigation time and potential failure points

**Role Targeting and Metadata Enrichment:**
- Deterministic role/title targeting in MatchEngine before IT metadata gate
- Explicitly rejects unwanted specializations: Java, PHP, .NET, C#, C++, Power Platform, Platform Engineer, Salesforce, SAP, ServiceNow, embedded, firmware, hardware, electrical, mechanical, civil, sales, marketing, HR, operations
- Allowed role families: data (analyst, engineer), software (engineer, developer), devops, python developer
- Enhanced NaukriAdapter metadata extraction with JSON-LD parsing, "Other Details" section extraction, and fallback body text scanning
- Always fetches job details for IT metadata enrichment (industry/department/role_category) even when description is present

**Historical Job Exclusion:**
- Jobs not returned by current search are excluded from current-run tracking
- Autonomous cycle only processes jobs with IDs in `current_run_job_ids`
- Historical jobs remain in database but are not sent to Gemini or ApplicationRunner

**Live Read-Only Validation (2026-10-06):**
- 105 job cards discovered across 11 pages
- 82 jobs tracked in current run (including existing duplicates)
- 21 historical jobs excluded from current run
- Current-run tracking confirmed working
- Focused current-run tracking tests: 12 passed
- Full backend suite: 681 passed, 0 failures

## CHECKPOINT C: Autonomous Cycle Command

The autonomous cycle command (`run_autonomous_cycle.py`) provides a command-line interface for running the complete job application flow with explicit controls:

**Command-Line Interface:**
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
- All tests use isolated temporary SQLite database
- No live Naukri activity, Gemini calls, or Apply clicks in tests

## Phase 10 Application-Type Reliability

Application-surface classification is evidence-driven and conservative. `detect_application_type()` checks visible external indicators first, then visible native selectors. When neither is present, it waits exactly 500 ms and observes again without reloading. The result is `AMBIGUOUS` if evidence remains absent. `ApplicationRunner` converts ambiguity to `NEEDS_ATTENTION` before application creation, preserving the rule that unknown state is never native.

The full adapter suite passed with 96 tests. A read-only live check found no security challenge; Quadrasystems had hidden/non-visible native selector nodes but no visible evidence and remained `AMBIGUOUS` after settling, while Cisco showed visible `Apply on company site` and remained `EXTERNAL`.

## Phase 10 Live Native Application Test: Blocked Candidate Boundary

The 2026-10-01 live check used the existing persistent Playwright/Naukri adapter. Authentication was valid and no visible security challenge was encountered. The backend was ready, the profile was confirmed, preferences existed, schema columns were present, and application limits were unused.

The adapter performed one bounded read-only discovery pass for the configured `Data Analyst` title and inspected five results. It did not click Apply. Four results failed duplicate, employment-type, or native-classification checks; the only native result was already processed. Because no candidate reached the complete hard-filter and AI-approved boundary, the application runner was not invoked and the database was not modified. This preserves the rule that no application is created or marked successful without a safe eligible candidate and observed confirmation evidence.

Automated successful application count remains 0; live submission validation is still pending.

## Phase 10 Database Schema Migration

**Mechanism:** Idempotent additive schema migration using column existence checks.

**Implementation Pattern:**

```python
# In backend/database/database.py initialize_database()

def initialize_database() -> None:
    """Initialize schema and apply additive migrations."""
    Base.metadata.create_all(bind=engine)

    # Migration 1: is_dry_run column (Phase 9B-4)
    if "is_dry_run" not in {
        column["name"] for column in inspect(engine).get_columns("applications")
    }:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE applications ADD COLUMN is_dry_run BOOLEAN NOT NULL DEFAULT FALSE"
            ))

    # Migration 2: confirmation_evidence column (Phase 10)
    if "confirmation_evidence" not in {
        column["name"] for column in inspect(engine).get_columns("applications")
    }:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE applications ADD COLUMN confirmation_evidence TEXT NULL"
            ))
```

**Characteristics:**
- Runs during FastAPI lifespan initialization (before request handling)
- Idempotent: checks column existence before attempting to add
- Non-destructive: additive only, no drops or truncates
- Data-preserving: existing rows unaffected
- Dialect-compatible: uses standard SQL for both SQLite and PostgreSQL

**Schema Validation:**

```python
# In backend/api/routes/health.py

def _check_schema_compatibility(db: Session) -> dict:
    """Phase 10: Check if database schema matches current models."""
    engine = db.get_bind()
    inspector = inspect(engine)
    
    required_columns = [
        ("applications", "confirmation_evidence"),
        ("applications", "is_dry_run"),
    ]
    
    missing = []
    for table_name, column_name in required_columns:
        columns = inspector.get_columns(table_name)
        column_names = {col["name"] for col in columns}
        if column_name not in column_names:
            missing.append(f"{table_name}.{column_name}")
    
    return {
        "compatible": len(missing) == 0,
        "missing": missing
    }
```

## Checkpoint C2 policy

The cycle enforces a zero-year experience cap and a strict IT-scope gate in
both `MatchEngine` and the final safety gate. A job passes IT scope when its
industry/department/role-category metadata is an allowed IT value; since the D5
relaxation, a missing industry field also passes when the title contains an IT
role/title keyword, and unrelated titles are still rejected upstream by
deterministic role targeting. Discovery rejects
over-cap cards before opening their pages and bounds scanning with
`--max-cards` (default 150). External links are recorded without following
company links, and visible native questions stop the flow for review.

**Readiness Integration:**

- `GET /api/readiness` includes schema compatibility check
- Reports `schema: compatible` on success
- Reports `schema: incompatible: <missing columns>` if migration needed
- Returns `ready: not_ready` until schema is compatible

**Standalone Execution:**

```bash
python -m backend.database.database
# Outputs: Migration status, SUCCESS/FAILED, exit code 0/1
```

**Compatibility:**
- SQLite: Fully tested and working (data/naukri_agent.db migrated and verified)
- PostgreSQL: SQL syntax validated for compatibility
- Column types: BOOLEAN (INTEGER in SQLite, BOOLEAN in PG), TEXT (standard)

**Test Coverage:**
- 7 focused migration tests in backend/tests/test_schema_migration.py
- Old schema migration adds confirmation_evidence
- Migration preserves existing rows and statuses
- Migration is idempotent (runs twice safely)
- Current schema requires no changes
- Database isolation (never uses production DB)
- Full suite: 557 tests passing

---

## Phase 9 Notifications

`NotificationService` is the single notification boundary. It persists notification records before delivery and uses the replaceable `SMTPEmailSender` only for email transport. SMTP credentials and recipients come from `NAUKRI_AGENT_` settings and are never included in logs. Delivery failures and missing configuration produce a `FAILED` notification record and do not raise into application/job processing. The service exposes typed helpers for critical errors, authentication requirements, security challenges, external applications, and evening summaries.

The scheduler evaluates the evening summary during the configured 8 PM hour in `notification_timezone`; a date-based deduplication key prevents duplicate delivery. The history endpoint is `GET /api/notifications`, and the dashboard shows recent persisted records. Tests use a fake sender; no real SMTP delivery has been performed.

## Phase 10 Application Boundary Fix

`NotificationService` is the single notification boundary. It persists notification records before delivery and uses the replaceable `SMTPEmailSender` only for email transport. SMTP credentials and recipients come from `NAUKRI_AGENT_` settings and are never included in logs. Delivery failures and missing configuration produce a `FAILED` notification record and do not raise into application/job processing. The service exposes typed helpers for critical errors, authentication requirements, security challenges, external applications, and evening summaries.

The scheduler evaluates the evening summary during the configured 8 PM hour in `notification_timezone`; a date-based deduplication key prevents duplicate delivery. The history endpoint is `GET /api/notifications`, and the dashboard shows recent persisted records. Tests use a fake sender; no real SMTP delivery has been performed.

## Phase 10 Application Boundary Fix

The application boundary is now evidence-driven and offline-validated. After a native Apply click,
the adapter waits for explicit visible evidence within 8 seconds:

```text
Apply button click
    ↓
Wait for post-click evidence (max 8s)
    ↓
Applied evidence detected?
    ├─ YES: #already-applied, .already-applied, exact "Applied", or 'Applied to "<title>"'
    │   → Return ApplicationStartResult.APPLIED
    │
Visible application container detected?
    ├─ YES: Dialog, drawer, modal, or form element visible
    │   → Return ApplicationStartResult.FORM_OPENED (proceed to questions)
    │
Neither detected within timeout?
    └─ → Return ApplicationStartResult.NEEDS_ATTENTION (no retry without manual reset)
```

**Post-click window mechanics (Run #59 fix):** each polling iteration runs the
header/banner applied checks and then the application-container check. The
page-wide element scan inside `detect_applied_state()` (two round trips per
element across ~1,000 elements on a captured Naukri job page) is deferred: it
runs exactly once after the window expires, before the reload decision, via
`detect_applied_state(page, scan_whole_page=False)` inside the loop. Run #59
measured the previous ordering consuming the entire window in one pass (Apply
click `03:12:49.075`, reload decision `03:13:02.379` = 13.3s for an 8s bound),
leaving the container check effectively unobserved. The terminal
`NEEDS_ATTENTION` warning records `page.url`.

**External application evidence (E5-R5.4 native-first ordering):**
`_observe_application_type()` first checks for a visible native Apply control
(`_find_scoped_apply_button`); when one exists the page is `NAUKRI_NATIVE` and
the external scan never runs - a visible native button is authoritative, so an
external-apply phrase appearing only in job-description prose cannot reclassify
a native page as `EXTERNAL`. Only when no native control is visible does the
external body-scan run over the `external_text_indicators` vocabulary, logging
which indicator matched so an `EXTERNAL` decision is attributable. Genuine
external CTAs never render a native Apply button, so they still classify
`EXTERNAL`. The URL persisted for an `EXTERNAL_APPLICATION` row comes from
`get_external_redirect_url()`, which returns only a non-Naukri link whose own
visible text matches that same vocabulary; when no such link exists it returns
`None` and the runner records `job.url`. Page-chrome links (promos, footers,
social) are never recorded as redirect targets - 19 of the 20 historical
`EXTERNAL_APPLICATION` rows carried the identical AmbitionBox promo URL and the
remaining one a Naukri Facebook URL, because the old code returned the first
non-Naukri anchor on the page.

**Validation instrumentation (E5-R4.2, read-only):** the apply flow emits an
attributable trail without changing any application behavior:

```text
External classification      -> matched indicator + page URL
External URL resolution      -> CTA link text + href  (or explicit job-url fallback)
Apply click                  -> page url before click, page url after click
New tab / popup              -> bounded wait_for_event("page") over
                                window + reload settle + 5s grace
                                -> new_tab_detected=yes|no  (read-only observer)
Each bounded-window check    -> post-click check #N at +X.XXs: applied=... container=...
Window close                 -> post-click window closed: elapsed=... checks=...
Terminal NEEDS_ATTENTION     -> terminal_state=NEEDS_ATTENTION checks=N screenshot=<path>
                                (data/apply_terminal_<label>_<stamp>.png)
```

The observer never clicks, fills, navigates, or closes the page it watches;
no form is submitted, no application/retry-queue/preference record is written,
security checks still run after the click and after the reload, and `APPLIED`
still requires positive visible evidence.

**Offline DOM harness (E5-R4.3, optional):** the detection layer above is
covered without touching Naukri by `backend/tests/test_naukri_adapter_offline_dom.py`
(9 tests). Each test starts headless Chromium with no persistent profile,
aborts every request at the context level (`context.route("**/*")`, zero
network egress), and feeds the real adapter's read-only methods a
`page.set_content()` document: the saved snapshot `data/job_page_snapshot.html`
(gitignored local artifact; skipped when absent) for native classification,
duplicate-ID header selection, absent applied/container evidence, page-chrome
external links (`get_external_redirect_url` -> `None`), and the security gate;
and a controlled synthetic page for external attribution, CTA grounding,
applied-state evidence, form-container detection, screenshot capture under
`tmp_path`, and both popup-observer outcomes. The popup probe clicks a neutral
local button that opens `about:blank` - no Apply control exists on the page.
The module is skipped with a clear reason when `playwright` or its Chromium
binaries are unavailable, so the normal backend suite does not depend on
Chromium. What remains live-only: whether Naukri's real Apply click opens a
popup, server-side instant-apply persistence behind the D5 reload decision,
real click/redirect timing, live security challenges, DOM drift versus the
2026-10-02 snapshot, and auth/session-gated rendering.

**Stale-external reconciliation (E5-R5.3):** jobs locked by the pre-E5-R4.1
false external classification are released by a human-triggered,
signature-scoped reconciliation - never automatically:

```text
ApplicationService.reconcile_stale_externals()   (service.py; POST
/api/applications/reconcile-stale-externals; no parameters)
  selects  ONLY  status == EXTERNAL_APPLICATION
           AND  external_url == STALE_EXTERNAL_PAGE_CHROME_URL
                (exact byte-for-byte match; the proven AmbitionBox
                 page-chrome URL, never a job-specific external CTA)
  reclassifies matching rows -> SKIPPED
  records  STALE_EXTERNAL_RECONCILE_SKIP_REASON  (prior classification
           came from the known page-chrome URL; no external application
           was opened, submitted, or confirmed; job released to the
           normal candidate pipeline)
  clears   needs_attention
  preserves the record, external_url, and application_method (audit)
  returns  {affected_count, application_ids, job_ids, signature}
  idempotent: a second call matches nothing
```

Never modified, even when carrying the signature URL: `APPLIED`,
`SUBMITTED` (the persisted `SUBMITTED_UNCONFIRMED` status),
`NEEDS_ATTENTION` (jobs 87/120 stay locked - remote status uncertain,
human resolution required), `FAILED`, already-`SKIPPED`. Nothing is
deleted; the autonomous cycle never calls this path; released jobs
re-enter through the normal candidacy query, runner guard, duplicate
protection, safety gate, and limits - no filter is bypassed. The
reconciled `SKIPPED` status satisfies both lock layers (the candidacy
query's `status == SKIPPED` branch and the runner's EXTERNAL/
NEEDS_ATTENTION guard), so the job becomes a candidate again only if
every deterministic rule passes on its own merits.

**Truthful outcomes and bounded error recovery (E5-R5.2):** the runner/cycle
outcome path separates a clicked-but-unconfirmed submission from a confirmed
application, and isolates runner errors:

```text
submit clicked + confirm_submission() positive   -> APPLIED
                                                   (status=APPLIED, evidence stored,
                                                    applications_count += 1)
submit clicked + confirmation absent             -> SUBMITTED_UNCONFIRMED
                                                   (status stays SUBMITTED, applied_at
                                                    set, no retry/resubmission,
                                                    submitted_unconfirmed += 1,
                                                    budget NOT consumed, never
                                                    reported under "Applied")
runner ERROR (no outcome reported)               -> 1st: recorded, loop continues
                                                   2nd consecutive: abort with
                                                   "Two consecutive runner errors;
                                                   aborting remaining candidates"
                                                   (non-normal stop, exit code 3)
valid non-ERROR outcome                          -> resets the consecutive-error counter
per-candidate exception                          -> neither increments nor resets it
SECURITY_REQUIRED / AUTH_REQUIRED                -> immediate abort (unchanged)
```

`ApplicationRunner.stats` and the cycle's `_run_applications` stats both carry
`submitted_unconfirmed`; `_process_single_job` includes it in
`reported_outcomes` so an unconfirmed-only result can never be misread as
`ERROR`. `AutonomousCycleRunResponse.stats` is a free-form dict, so the key
serializes additively with no schema change. Budget, duplicate safeguards,
safety gates, and hourly/daily limits are unchanged and remain authoritative.

### Question Detection Scoping (Phase 10)

Questions are detected only within visible application containers. Each field must satisfy:
- Visible on page
- Enabled (not disabled)
- Non-zero bounding box (width > 0, height > 0)
- Not readonly
- Not hidden-type input
- Not header/search input patterns

Rejected fields are skipped silently; question detection returns only qualified fields.

### Experience Computation (Phase 10)

`compute_profile_experience_years()` computes actual elapsed years from `start_date`/`end_date`:
- Parses multiple date formats (YYYY-MM, Month YYYY, etc.)
- Handles "Present" as current datetime
- Calculates (end - start) / 365.25 years
- Falls back to entry count if dates unparseable
- Returns 0.0 for no experience

Used consistently in:
- Final safety gate experience check
- Profile answer generation
- Experience hard filter evaluation

The +2 year tolerance is preserved and reported in rejection reasons.

## Gemini V1 Model Configuration

The V1 default Gemini model is `gemini-flash-lite-latest`, selected after `gemini-2.5-flash` repeatedly returned `429 RESOURCE_EXHAUSTED` and the alternate completed the existing structured `JobAnalysis` flow. `GeminiProvider` continues to pass the configurable `Settings.gemini_model` value directly to the `google.genai` client; `NAUKRI_AGENT_GEMINI_MODEL` can override the default. `gemini-3.1-flash-lite-preview` was also tested successfully but is not selected for V1. Prompts, schema parsing, retry behavior, and provider abstraction are unchanged. Phase 9B-3 live native form validation remains incomplete.

## Phase 9B-3 Production JD Extraction Fix

`NaukriAdapter.fetch_job_description()` preserves the security check and extracts rendered text using this order:

1. visible `[class*="dang-inner-html"]`
2. visible `section[class*="job-desc-container"]`

The first valid visible element wins. The method returns normalized text and returns an empty string only when neither selector yields a visible element or when the existing guarded fetch path fails. This fixes the runtime-suffixed Naukri hashed-class mismatch identified by live diagnostics without changing application, matching, scheduler, or Gemini behavior. Focused adapter tests cover selector variants, precedence, hidden-element fallback, and no-match behavior. Phase 9B-3 live native application validation remains incomplete.

## Phase 9B-3 Live JD Extraction Diagnostic: BLOCKER IDENTIFIED

The current live diagnostic inspected two persisted native Naukri pages without clicking Apply or invoking application code. First American returned HTTP 200 with visible body text length 7,264; ReactZ Consulting returned HTTP 200 with visible body text length 4,486. Both pages exposed JD text in rendered DOM elements. `NaukriAdapter.fetch_job_description()` currently checks `.job-desc` and exact `.styles_JDC__`; both matched zero elements on both pages. Observed structures were `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`, with visible JD text lengths of 2,835/2,096 and 1,416/687 respectively. No iframe was involved. This is a selector-strategy defect, not missing page content. Production selectors were not changed in this checkpoint. Gemini is deferred because quota is exhausted, and no Apply or submit action occurred.

## Phase 9B-3 Diagnostic Job Description Flow

The bounded live diagnostic now reuses `NaukriAdapter.fetch_job_description()` for each selected real job before Gemini analysis. The returned text is assigned to the diagnostic `Job.description`, persisted, and included in the Gemini context. Candidate inspection occurs before selection; only native candidates with an existing or newly obtained APPLY recommendation can be selected, while external candidates are excluded. Persisted analyses are reused and quota exhaustion stops further analysis. This keeps the diagnostic data flow aligned with production DiscoveryService without changing production discovery, Gemini, matching, scheduler, or application code. The change was validated offline only; no live search or Gemini request was run, and Phase 9B-3 remains incomplete.

## Phase 9B-3 Native Application Detection Fix

Live inspection of a real First American Data Analyst page found a Naukri-native application surface: a visible `button#apply-button` / `button.apply-button` control with exact text `Apply`, and no `Apply on company site` control. The adapter previously recognized only older selectors and incorrectly returned `EXTERNAL`.

`NaukriAdapter.detect_application_type()` now checks rendered external indicators first, then stable native selectors and visible exact-text `Apply` buttons. `start_application()` uses the same stable `#apply-button` and `button.apply-button` selectors so the detected native flow can start. Hashed CSS classes are not used. Focused regression tests cover native controls, external indicators, pages without controls, and the current native start selector. A new live browser run is still required; this checkpoint did not submit an application.

## Test Database Isolation Checkpoint

Runtime persistence and test persistence are separate. The application continues to use the configured V1 SQLite database at `data/naukri_agent.db`, while `backend/tests/conftest.py` creates a disposable temporary file-backed SQLite engine for tests. Before tests run, database/session references used by the FastAPI app and directly imported services are redirected to that test engine. `Base.metadata.drop_all()` and `create_all()` therefore operate only on the disposable test database.

This prevents the test suite from deleting profiles, resumes, jobs, analyses, preferences, or applications in the runtime database. Regression coverage verifies that the test path differs from the production path and that resetting the test schema leaves production row counts unchanged. Focused persistence tests passed, and the full backend suite passed with 512 tests.

## Phase 9B-3 False-Positive Fix Checkpoint

Live Naukri diagnosis found that a normal HTTP 200 job page was incorrectly classified as a security challenge because raw HTML contained Naukri's internal `"showCaptcha":false` state value. `NaukriAdapter._check_security()` now evaluates `page.inner_text("body")` rather than raw `page.content()`. Bare `captcha` is not a standalone visible-text trigger; explicit visible reCAPTCHA/hCAPTCHA labels, human-verification phrases, security challenges, login indicators, and blocked-access indicators remain safety gates. This preserves the rule that actual visible security challenges stop automation without adding bypass or stealth behavior.

The targeted regression suite covers the raw `showCaptcha:false` value, bare visible `captcha`, explicit visible security indicators, and a normal Naukri job page. 77 Naukri adapter tests and 509 full backend tests are recorded as passing. A second real visible-browser Naukri dry-run remains the next validation step; this checkpoint does not claim Phase 9B-3 live validation is complete, and no application submission occurred.

## Profile Duplicate ERROR Recovery (Phase 9B-2C)

When a duplicate resume upload finds an existing profile in `ERROR` status, the pipeline recovers:

```text
Duplicate resume upload (same SHA-256)
    ↓
Existing Resume record found
    ↓
Check existing Profile status
    ↓
CONFIRMED / REVIEW_REQUIRED → reuse existing profile (no extraction)
    ↓
ERROR → read stored PDF bytes from disk
    ↓
Re-run PDF text extraction (PdfTextExtractor)
    ↓
Re-run Gemini profile extraction (_extract_profile_with_retry)
    ↓
Update existing Profile record in-place (no new records)
    ↓
Success: ERROR → REVIEW_REQUIRED, confirmed=false
Failure: remains ERROR
```

---

## Phase 9B-2B Defect Fixes

### prompt_version Persistence (Issue 1)

`AIQueueService.process_item()` now uses `JOB_ANALYSIS_PROMPT_V1` from `prompts.py`:

```text
Gemini analysis completes
    ↓
JobAnalysisModel created with prompt_version=JOB_ANALYSIS_PROMPT_V1
    ↓
Persisted to database (non-null, traceable to actual prompt)
```

### Experience Year Computation (Issue 2)

`compute_profile_experience_years()` in `normalizer.py` replaces `len(experience_list)`:

```text
Experience list from profile
    ↓
For each entry: parse start_date + end_date
    ↓
Compute elapsed years (positive deltas only)
    ↓
Sum across all entries
    ↓
Fallback: len(list) if no dates parseable
```

Hard-filter flow unchanged:

```text
MatchEngine.evaluate_job()
    ↓
compute_profile_experience_years(profile.experience)
    ↓
if exp_min > user_exp_years + 2 → SKIP (never reaches Gemini)
    ↓
else → Gemini analysis (advisory)
```

---

## Phase 9A: Scheduler Automation Loop (Complete Pipeline)

The scheduler now orchestrates the complete Phase 9A automation loop:

```text
Scheduler Cycle (triggered every N minutes or manually)
    ↓
1. Discover Jobs (NaukriAdapter: search, fetch descriptions, deduplicate)
    ↓
2. Persist Jobs (Database: store in Job table with status=DISCOVERED)
    ↓
3. Apply Hard Filters (MatchEngine: deterministic rules on location, salary, experience, employment type)
    ↓
4. Enqueue Eligible Jobs (AIQueueService: jobs passing hard filters → AI queue)
    ↓
5. Process AI Queue (GeminiProvider: analyze jobs, validate Pydantic schema)
    ↓
6. AI Results Persist (JobAnalysisModel: store match_score, recommendation, etc.)
    ↓
7. Identify Completed Jobs (AIQueueItem.status = COMPLETED)
    ↓
8. Invoke ApplicationRunner (pass job IDs to ApplicationRunner.run_applications)
    ↓
9. Application Runner Flow (described below - unchanged from Phase 8)
    ↓
10. Record Results (Application model: status, applied_at, failure_reason, etc.)
```

### Key Guarantees

- **Hard filters are authoritative**: Gemini analysis is advisory only. Hard filters block jobs from entering the application path.
- **ApplicationRunner remains sole executor**: All application submission goes through ApplicationRunner, which runs the final safety gate.
- **Failure isolation**: Single job failures don't cascade; processing continues safely.
- **Quota enforcement**: If Gemini quota is exhausted, queue processing stops gracefully without applying jobs.
- **No live submissions in Phase 9A**: Infrastructure ready, but real Naukri submissions deferred to Phase 9B.

### Scheduler Methods

- `_apply_hard_filters_and_enqueue(db)` → Apply MatchEngine hard filters to DISCOVERED jobs, enqueue eligible ones
  - Returns stats: discovered, hard_filtered, queued, errors
  - Skips jobs already analyzed or queued
  - Continues on individual job failures

- `_process_ai_queue_items(db)` → Process up to 5 queue items per cycle through Gemini
  - Returns stats: processed, completed, retry_pending, quota_blocked, needs_attention, failed, errors
  - Recovers stale items first
  - Stops gracefully on quota exhaustion

- `_invoke_application_runner(db)` → Find jobs with completed AI analysis, pass to ApplicationRunner
  - Returns stats: candidates, applied, skipped, needs_attention, failed, errors
  - Skips jobs without AI analysis (final safety gate requires analysis)
  - ApplicationRunner runs in same database session

---

## Distributed Work Coordination Architecture (Phase 8.5B)

Multiple workers safely claim and process distributed AI queue work without race conditions:

```text
AI Queue Work Items (Jobs requiring Gemini analysis)
    ↓
Work Coordination Fields (claimed_by, last_heartbeat_at, available_at)
    ↓
Worker Claiming (PostgreSQL: SELECT...FOR UPDATE SKIP LOCKED, SQLite: transaction-safe)
    ↓
Ownership Verification (only claiming worker can heartbeat/release/complete/fail)
    ↓
Heartbeat Tracking (prevents stale detection, updates last_heartbeat_at)
    ↓
Stale Detection (items without heartbeat > 30min)
    ↓
Stale Recovery (safe escalation to NEEDS_ATTENTION if max_attempts exceeded)
    ↓
Release/Complete/Fail Operations (terminal states, idempotent where appropriate)
    ↓
Existing Application Safety Gates (duplicate detection, safety gate, application limits) - UNCHANGED
```

### Work Coordination Fields (AIQueueItem Extensions)

- `claimed_by` (String, nullable, indexed): worker_id currently owning this item
- `last_heartbeat_at` (DateTime UTC, nullable): timestamp of latest heartbeat from claiming worker
- `available_at` (DateTime UTC, nullable, indexed): timestamp after which item is eligible for claiming again

### Work Coordination Service

**Claiming:**
- `claim_next_work(worker_id)` → atomically select next eligible item and assign to worker
  - Selection: QUEUED or RETRY_PENDING status, no owner, available_at null or past
  - Ordering: priority descending, then created_at ascending (deterministic)
  - PostgreSQL: SELECT...FOR UPDATE SKIP LOCKED (prevents race conditions)
  - SQLite: transaction-safe selection (see compatibility below)
  - Returns work dict or None if no eligible work

**Ownership:**
- `heartbeat_work(worker_id, work_id)` → update last_heartbeat_at if owner
  - Requires: worker owns item, item not in terminal state (COMPLETED/FAILED/NEEDS_ATTENTION)
  - Updates: last_heartbeat_at = now
  - Raises: WorkNotOwnedError if worker doesn't own, WorkStateError if terminal state

**Stale Detection & Recovery:**
- `detect_stale_work()` → find items with owner but no heartbeat > 30min
  - Returns: list of stale work dicts
  - Does not modify state
  - Ignores: completed, failed, needs_attention, unclaimed items

- `recover_stale_work(work_id)` → clear ownership and advance stale item safely
  - Safety: if max_attempts NOT exceeded → RETRY_PENDING (eligible immediately)
  - Safety: if max_attempts exceeded → NEEDS_ATTENTION (human review required)
  - Preserves: existing duplicate detection, safety gates, application limits
  - Never blindly retries with uncertain execution outcome

**Lifecycle:**
- `release_work(worker_id, work_id)` → release ownership with 5min backoff
  - Requires: worker owns item
  - Result: claimed_by cleared, available_at set to now+5min
  - Use case: worker cannot process now, defer to later or different worker

- `complete_work(worker_id, work_id)` → mark COMPLETED, clear ownership
  - Requires: worker owns item (idempotent if already completed)
  - Allows: repeated calls (idempotent)
  - Result: status = COMPLETED, ownership cleared, terminal

- `fail_work(worker_id, work_id, error, reason)` → mark FAILED, clear ownership
  - Requires: worker owns item
  - Result: status = FAILED, ownership cleared, terminal
  - Captures: error details for debugging

**Worker Load:**
- `get_worker_load(worker_id)` → current work stats
  - Returns: claimed_count (all owned items), processing_count (PROCESSING status)

### Database Compatibility

**PostgreSQL (Production):**
- Uses atomic `SELECT...FOR UPDATE SKIP LOCKED`
- Prevents race conditions: one worker locks the best item, others skip to next
- Guarantees: no two workers claim the same item
- Transactions: isolation level READ COMMITTED sufficient
- Best for: high concurrency, multiple workers

**SQLite (Development/Testing):**
- Uses transaction-safe fallback without row-level locking
- Fallback: deterministic selection + commit within transaction
- Limitation: multiple workers may briefly see the same item (no SKIP LOCKED)
- Workaround: deterministic ordering ensures consistent behavior across runs
- Testing: all 49 coordination tests pass with SQLite
- Note: for production multi-worker scenarios, PostgreSQL required

### Safety Preservation

**Existing Application Safety is Authoritative:**
- Duplicate detection: existing ApplicationService.check_duplicate_application() unchanged
- Safety gate: existing ApplicationService.run_final_safety_gate() unchanged
- Application limits: existing ApplicationLimitService.check_limits() unchanged
- Stale recovery never bypasses these gates

**Stale Recovery Safety:**
- If execution outcome is uncertain (browser crash, no heartbeat, max_attempts exceeded):
  - Recovery escalates to NEEDS_ATTENTION (requires human review)
  - Never blindly retries application
  - Preserves existing safety architecture

**Ownership Rules:**
- Only claiming worker can heartbeat/release/complete/fail
- Different worker attempting operation raises WorkNotOwnedError
- Prevents accidental work theft or overlap

### Current Scope (Phase 8.5B)

- Atomic work claiming
- Ownership verification
- Heartbeat tracking
- Stale detection
- Stale recovery (safety-preserving)
- Release/complete/fail operations
- Worker load tracking
- PostgreSQL and SQLite support

### Future Scope (Phase 8.5C+)

- Cloud browser execution
- Browser session migration
- Remote browser lifecycle management
- Cloud browser providers (Browserless, Browserbase)
- Persistent cloud browser sessions
- Kubernetes orchestration
- Redis/Celery/RabbitMQ integration
- Multi-region infrastructure

---

## Worker Foundation Architecture (Phase 8.5A)


Persistent worker identity layer enabling future cloud coordination:

```text
Worker Registration & Identity
    ↓
Worker Types (LOCAL_WINDOWS, CLOUD_BROWSER)
    ↓
Worker Status Lifecycle (STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR)
    ↓
Worker Service Layer (register, get, list, update_status)
    ↓
Worker API Endpoints (status, register, get by ID)
    ↓
Future: Distributed Task Claiming, Heartbeat, Stale Recovery (Phase 8.5B+)
```

### Worker Model

- `worker_id` (UUID, unique, indexed): persistent identity across sessions
- `worker_type` (Enum): LOCAL_WINDOWS (current) or CLOUD_BROWSER (future)
- `status` (Enum): STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR
- `runtime_environment` (String): identifies deployment context
- `created_at`, `updated_at`, `started_at`, `stopped_at` (DateTime UTC): lifecycle tracking
- No sensitive data: passwords, cookies, sessions, API keys, or Naukri credentials never stored

### Worker Service

- `register_worker(request)`: safely repeatable; same type+environment returns same worker_id
- `get_worker(worker_id)`: retrieve by ID; returns None if not found
- `list_workers()`: all workers with active count (excludes STOPPED/ERROR)
- `update_worker_status(worker_id, status)`: transitions status; tracks started_at on RUNNING, stopped_at on STOPPED/ERROR

### Worker API

- `GET /api/worker/status`: list all workers with active count
- `POST /api/worker/register`: register new or return existing worker
- `GET /api/worker/{worker_id}`: retrieve specific worker; 404 if not found

### Current Scope

- Worker identity and registration
- Status lifecycle tracking
- Persistent database storage (SQLite/PostgreSQL)
- No task claiming, heartbeat, or stale recovery
- No browser lifecycle refactoring
- No cloud execution

### Future Scope (Phase 8.5B-D)

- Distributed task claiming with PostgreSQL row locking
- Worker heartbeat and stale-worker detection/recovery
- Browser lifecycle refactoring (currently direct)
- Cloud browser worker execution
- Task assignment and worker coordination

---

## Hosted FastAPI Deployment Architecture (Phase 8.3)

The backend has been prepared for production hosting with enhanced configuration, security, and monitoring:

```text
Production Configuration
    ↓
Environment Separation (LOCAL_WINDOWS/CLOUD)
    ↓
CORS Configuration (configurable origins)
    ↓
Health/Readiness Endpoints
    ↓
Production-Safe Error Handling
    ↓
Production-Safe Logging (sensitive info redaction)
    ↓
Database Configuration (SQLite/PostgreSQL)
    ↓
Storage Configuration (abstraction ready for object storage)
    ↓
Browser/API Separation (no auto-start)
```

### Production Configuration

- Environment detection: LOCAL_WINDOWS (V1) vs CLOUD (future)
- Production mode detection: development vs production
- CORS origins: configurable via `NAUKRI_AGENT_FRONTEND_ORIGINS` (comma-separated)
- Database URL: SQLite locally and external PostgreSQL required for production readiness
- Runtime environment: configurable via RUNTIME_ENVIRONMENT
- All configuration driven by environment variables with NAUKRI_AGENT_ prefix

### CORS Strategy

- Development mode: allows localhost origins for convenience
- Production mode: uses only configured origins from FRONTEND_ORIGINS
- Multiple origins supported via comma-separated list
- Wildcard origins NOT used in production
- Configurable methods: GET, POST, PUT, OPTIONS, DELETE
- Configurable headers: Content-Type, X-Request-ID, Authorization

### Health and Readiness

- Liveness endpoint (/api/health): process-only status; no database or Gemini work
- Readiness endpoint (/api/readiness): detailed component status
- Readiness checks: database, configuration, storage, AI provider, runtime environment
- Production mode requires PostgreSQL, Gemini configuration, and explicit non-wildcard frontend origins
- Component status uses safe machine-readable values without raw exception details
- Ready for container orchestration and health checks

### Error Handling

- Catch-all exception handler prevents sensitive information exposure
- Generic exceptions return safe error messages without stack traces
- Application errors return structured responses with error categories
- Validation errors return 422 with category information
- No filesystem paths, environment variables, or secrets in API responses

### Logging

- Development mode: standard JsonFormatter for debugging
- Production mode: SafeJsonFormatter with automatic redaction
- Sensitive keys, nested structures, credential URLs, authorization headers, cookies, sessions, and exception details are redacted or omitted
- Structured logging with timestamp, level, message, and component
- Extra fields: component, event, error_category, request_id, job_id, application_id
- Logs never contain API keys, credentials, or sensitive user data

### Database Configuration

- SQLite default for local development (sqlite:///./data/naukri_agent.db)
- PostgreSQL support via `NAUKRI_AGENT_DATABASE_URL`, with transparent `postgresql://` to `postgresql+psycopg://` conversion (Phase 8.2)
- PostgreSQL connection pooling enabled for cloud deployment (`pool_size`, `max_overflow`)
- SQLite directory creation for both relative and absolute paths
- No SQLite-only assumptions preventing hosted operation
- Database initialization works correctly in both modes
- Connection pooling and session management via SQLAlchemy

### Storage Configuration

- StorageService abstraction for file operations
- Local filesystem storage for LOCAL_WINDOWS (V1)
- Methods: store_file, read_file, delete_file, file_exists, get_file_size
- Directory management: create_directory, delete_directory
- Path resolution with resolve_path()
- Ready for future object storage (S3/Azure/GCS) without code changes

### Browser/API Separation

- API process does NOT auto-start Playwright browser
- Browser only starts when explicitly called via DiscoveryService
- Clear separation between API process and browser worker
- RuntimeContext controls browser automation support
- LOCAL_WINDOWS: browser automation supported
- CLOUD: browser automation disabled (future remote browser)
- Safe for future cloud architecture with separate browser worker

### Frontend API Configuration

- Environment-based backend URL via VITE_API_BASE_URL
- Development: `http://127.0.0.1:8000` fallback when the variable is absent
- Production: a required public HTTPS `VITE_API_BASE_URL`; production never falls back to localhost
- The centralized client normalizes a trailing slash and appends `/api` once, so either an API origin or an existing `/api` URL is accepted
- All frontend API consumers use the centralized client, with timeout, network, HTTP, and malformed-response handling that does not expose backend details

### Vercel Frontend Configuration (Phase 8.4)

- The existing root `vercel.json` builds the `frontend` subproject with `npm --prefix frontend ci`, `npm --prefix frontend run build`, and output `frontend/dist`.
- `VITE_API_BASE_URL` is public browser configuration only. It must not contain API keys, credentials, cookies, session data, or private tokens.
- The Vercel origin is configured on the backend through `NAUKRI_AGENT_FRONTEND_ORIGINS`; multiple explicit origins remain supported.
- The current dashboard uses in-page state and hash links rather than client-side browser-path routes, so no Vercel SPA rewrite is required.
- This configuration is deployment preparation; no Vercel site has been deployed or verified.

### Responsive Mobile Frontend Architecture (Phase 8.4.1)

**Mobile-First Responsive Design:**
- Responsive CSS with mobile-first breakpoints: 320px, 360px, 375px, 390px, 414px, 480px, 768px, 1024px, 1280px, 1440px+
- Desktop layout (>768px): Sidebar (260px fixed) + topbar + content; mobile header and bottom nav hidden
- Tablet layout (768px-1024px): Sidebar collapses to icons only (80px); mobile nav available
- Mobile layout (<768px): Mobile header (56px) + content + bottom navigation (56px)

**Mobile Header (56px, sticky):**
- Hamburger menu button (44x44px touch target)
- Brand text and icon ("Naukri Agent")
- Notifications bell button (44x44px)
- Hidden on desktop (>768px)

**Sidebar Drawer (Mobile):**
- Positioned fixed, slides in from left (left: -100% → left: 0)
- Semi-transparent backdrop overlay (rgba(0,0,0,0.5), z-index 99)
- Auto-closes when navigation item clicked or backdrop clicked
- Full navigation menu maintained (Overview, Activity, Analytics, Profile, Preferences)
- Jobs and Applications remain disabled (routes not implemented)

**Bottom Navigation (56px, sticky, mobile only):**
- 5 primary destinations: Home (Overview), Activity, Jobs (disabled), Apps (disabled), More (Analytics)
- Active state indicator (color: primary-blue)
- 44x44px+ touch targets per navigation item
- Icon + label layout, vertically stacked
- Hidden on desktop (>768px)

**Responsive Component Layouts:**
- Metrics: 4-column (desktop) → 2-column (tablet) → 1-column (mobile)
- Analytics: 3-column (desktop) → 2-column (tablet) → 1-column (mobile)
- Forms: 2-column (desktop/tablet) → 1-column (mobile)
- Buttons: flex-wrap (desktop) → stack vertically (mobile)
- Profile upload zone: horizontal layout → vertical stacking (mobile)
- Status panels, cards, activity sections: responsive padding and margins

**Touch-Friendly Controls:**
- All interactive elements minimum ~44x44px
- Form inputs on mobile: 16px font size (prevents iOS zoom-on-focus)
- Focus states preserved with blue outline and light background
- No hover states required for mobile interaction

**Typography Responsiveness:**
- h1: 26px (desktop) → 20px (small mobile)
- h2: 18px (desktop) → 16px (small mobile)
- Body text: 14px with responsive adjustments
- Labels and badges: readable at all sizes

**Content Safety:**
- No accidental horizontal scrolling at critical breakpoints (320px, 360px, 375px, 390px, 414px)
- All cards and components constrained to viewport width
- Long text wraps properly
- Tables/charts contained or scrollable within component bounds
- Content padding-bottom accounts for fixed bottom nav (80px total)

**Mobile UX Inspiration (Naukri-inspired, not copied):**
- Compact mobile header with contextual actions
- Drawer navigation pattern for secondary menu
- Bottom navigation for primary destinations
- Card-based presentation for jobs/applications/activity
- Efficient vertical scrolling information hierarchy
- Touch-optimized spacing and controls
- Clear status indicators and agent state display

**Desktop Preservation:**
- Sidebar remains 260px fixed left on desktop (>1024px)
- Topbar remains visible with page header and backend state
- Content area max-width 1200px maintained
- All desktop metrics/analytics/form layouts preserved
- No mobile header or bottom nav on desktop
- No functional regressions

### Hosted Service Configuration

- `Procfile` runs `uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
- `render.yaml` defines a Python web service using root `requirements.txt` and the platform-provided `PORT`.
- Render configuration contains only environment-variable placeholders for PostgreSQL, Gemini, and frontend origins; it contains no secret values.
- `python run.py` remains the local-development entry point and binds to its configured local host/port.

### Security Considerations

- CORS origins configured, no wildcard in production
- Error responses don't expose stack traces or internal details
- Logging redacts sensitive information automatically
- Configuration properties don't expose API keys or secrets
- API responses never return credentials or sensitive configuration
- No filesystem paths in API responses
- No environment variables in API responses
- No secrets in logs or error messages

---

## Cloud Readiness Architecture

The application includes runtime and storage abstractions to support future cloud deployment while maintaining local-first V1 operation:

```text
RuntimeContext (environment detection)
    ↓
StorageService (file operations abstraction)
    ↓
Settings (environment variable driven configuration)
    ↓
Database (SQLite/PostgreSQL flexibility)
```

### Runtime Abstraction

`RuntimeContext` provides environment-specific information and behavior without scattering environment checks throughout the codebase:

- `RuntimeEnvironment.LOCAL_WINDOWS`: Desktop application on Windows (V1 current)
- `RuntimeEnvironment.CLOUD_READY`: Server/cloud environment (future, not implemented in V1)
- Auto-detects current runtime (Windows vs others)
- Properties for: browser automation support, Windows auto-start support, persistent browser session support
- Methods for: database URL retrieval, storage path resolution, directory paths
- Global singleton instance with `get_runtime_context()` and `set_runtime_context()`

### Storage Abstraction

`StorageService` provides a clean interface for file operations, abstracting the underlying storage mechanism:

- Methods for: `store_file`, `read_file`, `delete_file`, `file_exists`, `get_file_size`
- Methods for: `list_files`, `create_directory`, `delete_directory`
- Path resolution with `resolve_path()`
- Directory management: resume storage, data storage, log storage, browser user data
- Atomic file operations with temporary files
- Global singleton instance with `get_storage_service()`

### Configuration Enhancement

Settings are now environment variable driven with `NAUKRI_AGENT_` prefix:

- Storage paths changed from Path fields to string fields with property resolution
- Properties for absolute path resolution: `resume_storage_path`, `data_path`, `log_path`, `browser_user_data_path`
- Added `runtime_environment` configuration field
- Support for both relative and absolute paths
- Database URL supports both SQLite and PostgreSQL

### Integration Points

- `NaukriAdapter` uses `get_browser_user_data_dir()` from settings
- `ResumeService` uses `StorageService` for file operations
- All path resolution goes through storage abstraction
- Database configuration supports both SQLite and PostgreSQL

### Future Cloud Direction

The abstractions enable future cloud deployment without changing business logic:

- Cloud environments will use `CLOUD_READY` runtime mode
- Storage abstraction enables S3/Azure Blob/GCS integration
- Database abstraction enables PostgreSQL migration
- Remote browser automation will be needed for cloud deployment
- All existing V1 functionality remains local Windows only

## Phase 1 Foundation

The application is Windows-first and local-first. React provides the local dashboard, FastAPI owns API and orchestration boundaries, and SQLAlchemy isolates application code from SQLite-specific behavior.

```text
React + TypeScript dashboard
           |
        FastAPI API
           |
  Services / typed schemas
     |                 |
AIProvider       JobPlatformAdapter
GeminiProvider   NaukriAdapter
           |
 SQLAlchemy database boundary
           |
        SQLite (V1)
```

## Boundaries

- API routes translate HTTP requests into typed schemas and service calls.
- Services contain product behavior; Phase 1 includes only state and adapter boundaries.
- `AIProvider` cannot access browser automation. `GeminiProvider` makes no API call until Phase 3.
- `JobPlatformAdapter` isolates platform-specific work. `NaukriAdapter` contains Playwright-based job discovery automation implemented in Phase 5.
- The database module owns engines and sessions. Future PostgreSQL support is configured through `DATABASE_URL`.

## State Foundation

`AgentState` is a typed API contract. `AgentStateManager` permits only declared transitions; persistence, scheduling, and recovery arrive in Phase 7.

## Future Cloud Direction

The boundaries permit later queue-backed workers and PostgreSQL while retaining API, rules, provider, and platform-adapter contracts. No cloud infrastructure is part of Phase 1.

Cloud readiness infrastructure (implemented as foundational abstractions):

- `RuntimeContext` enables environment-specific behavior without code changes
- `StorageService` enables object storage (S3/Azure/GCS) without code changes
- Database abstraction enables PostgreSQL migration without code changes
- Environment variable configuration enables cloud deployment via environment
- All V1 functionality remains local Windows only
- Future cloud deployment will require: remote browser automation, object storage integration, PostgreSQL deployment

## Profile Workflow (Phase 2)

```text
PDF upload -> validation -> SHA-256 storage -> PyMuPDF text extraction
    -> narrow Gemini profile extractor -> Pydantic validation
    -> REVIEW_REQUIRED -> user edit/save -> explicit CONFIRMED
```

`ProfileService` owns the workflow. It stores only generated resume filenames and hashes in the database; API responses never expose local paths or raw resume text. A newly uploaded resume is current but cannot overwrite its predecessor's confirmed facts until its own review is explicitly confirmed.

## AI Engine Workflow (Phase 3)

The reasoning bounds run exclusively through a centralized `GeminiProvider`.

```text
Gemini SDK (google-genai) -> Provide System Instruction Context
    -> Response -> Pydantic Schema Validation (Strict JSON)
    -> SQLAlchemy Record (JobAnalysis / AIUsage)
    -> Backend App Logic
```

The app's AI integration does NOT make direct browser-related commands or manipulate business execution; it strictly conforms to JSON-bound models (e.g. returning a deterministic `recommendation: AIRecommendation`) and catches rate-limiting or quota errors proactively.

## Discovery Workflow (Phase 5)

```text
DiscoveryService orchestrates job discovery:
    ↓
NaukriAdapter (Playwright) starts browser session
    ↓
Navigate Naukri search with user's job titles/locations
    ↓
Extract job cards (title, company, location, salary, experience, posted_at, employment_type, external_job_id)
    ↓
Paginate through search results (pages_processed tracking)
    ↓
Fetch job descriptions from individual pages when needed
    ↓
Normalize and deduplicate (by external_job_id, URL, title+company)
    ↓
Persist to SQLite (Job, DiscoveryRun with statistics)
    ↓
Handle security/authentication failures (AUTH_REQUIRED, SECURITY_REQUIRED states)
    ↓
AgentState lifecycle management (RUNNING → SEARCHING → FILTERING → IDLE/STOPPED/ERROR)
```

`DiscoveryService` owns the workflow. It uses Playwright for normal browser interactions without evasion techniques. Security challenges (CAPTCHA, human verification) halt discovery and transition to SECURITY_REQUIRED state. Authentication failures transition to AUTH_REQUIRED state. The service tracks pages_processed, jobs_discovered, new_jobs, duplicate_jobs, and errors in DiscoveryRun statistics.

## Scheduler Workflow (Phase 7 - Checkpoint 1)

```text
SchedulerService orchestrates scheduled job discovery:
    ↓
JobScheduler (APScheduler AsyncIOScheduler)
    ↓
Configurable interval (default hourly, max_instances=1)
    ↓
Scheduled task callback triggers DiscoveryService
    ↓
Agent state check (skip if agent is busy)
    ↓
DiscoveryService.run_discovery()
    ↓
SchedulerConfig persistence (enabled, interval, state, timestamps)
    ↓
AgentState lifecycle management
```

`SchedulerService` owns the orchestration and persistence. It uses APScheduler for timing with `max_instances=1` to prevent overlapping runs. Configuration (enabled, interval_minutes, max_instances) is persisted to the database for recovery across restarts. The scheduler respects agent state - it skips discovery when the agent is in RUNNING, SEARCHING, FILTERING, or APPLYING states. The scheduler is timing/orchestration only - business rules remain in DiscoveryService. API routes provide control (start, stop, pause, resume) and status reporting. Safe startup/shutdown is integrated with the FastAPI lifespan.

## Application Limits Workflow (Phase 7 - Checkpoint 2A)

```text
ApplicationLimitService enforces hourly/daily volume limits:
    ↓
Uses existing JobPreference model (max_hourly_applications, max_daily_applications)
    ↓
Counts only successful applications (APPLIED/SUBMITTED status)
    ↓
Hourly usage: applications with applied_at >= now - 1 hour
    ↓
Daily usage: applications with applied_at >= now - 24 hours
    ↓
Limit check: blocks if hourly_used >= max_hourly OR daily_used >= max_daily
    ↓
ApplicationRunner: checks limits AFTER duplicate check, BEFORE safety gate
    ↓
SchedulerService: checks limits BEFORE starting discovery
    ↓
Deterministic Python logic only - Gemini never decides limits
```

`ApplicationLimitService` owns the limit enforcement logic. It uses the existing JobPreference model which already had limit fields from Phase 4. Only successful applications (APPLIED or SUBMITTED status) count toward limits - failed, skipped, or external applications do not. The limit check happens in two places: (1) in ApplicationRunner after duplicate check but before the safety gate, and (2) in SchedulerService before starting discovery. This ensures resources aren't wasted on applications that would be blocked, and the scheduler doesn't start discovery when limits are reached. Limits are enforced using deterministic Python logic only - Gemini never decides whether a limit is exceeded. API routes provide limit status and configuration management.

## AI Queue Workflow (Phase 7 - Checkpoint 2B)

```text
AIQueueService manages persistent work queue for Gemini analysis:
    ↓
Enqueue discovered jobs (SCHEDULER or MANUAL source)
    ↓
Priority-based processing (higher priority first)
    ↓
Sequential processing with quota handling
    ↓
Retry logic (1min, 5min, 15min delays)
    ↓
Stale item recovery (PROCESSING stuck > 30min)
    ↓
Status tracking: QUEUED, PROCESSING, COMPLETED, RETRY_PENDING, QUOTA_BLOCKED, NEEDS_ATTENTION, FAILED
```

`AIQueueService` owns the queue management. It uses AIQueueItem model for persistence with status, priority, attempt tracking, and retry scheduling. Items are enqueued from scheduler after discovery or manually via API. Processing is sequential with GeminiProvider for analysis. Quota exhaustion items are marked QUOTA_BLOCKED and retried when quota becomes available. Stale items (stuck in PROCESSING > 30min) are recovered to RETRY_PENDING or NEEDS_ATTENTION on startup. The queue respects deterministic priority calculation based on job freshness, description completeness, and title relevance. API routes provide queue status, enqueue, and manual processing triggers.

## Agent Lifecycle Workflow (Phase 7 - Checkpoint 3)

```text
AgentLifecycleService orchestrates agent lifecycle:
    ↓
Safe startup recovery (recover stale queue, reset active states to IDLE)
    ↓
Prerequisite validation (confirmed profile, job preferences, API key)
    ↓
START: Validate prerequisites → Start scheduler → Transition to RUNNING
    ↓
PAUSE: Pause scheduler → Transition to PAUSED (queue preserved)
    ↓
RESUME: Validate prerequisites → Resume scheduler → Transition to RUNNING
    ↓
STOP: Stop scheduler → Transition to STOPPED (queue preserved)
    ↓
State transitions follow AgentStateManager rules
```

`AgentLifecycleService` owns lifecycle orchestration without duplicating AgentStateManager. It provides safe start/stop/pause/resume operations with prerequisite validation. Startup recovery resets active states (RUNNING, SEARCHING, FILTERING, APPLYING) to IDLE to prevent automatic application submission after restart. Problem states (AUTH_REQUIRED, SECURITY_REQUIRED) are preserved for user attention. Stale AI queue items are recovered on startup. The service integrates with SchedulerService and AIQueueService for complete lifecycle management. API routes provide lifecycle status and control endpoints.

## Windows Auto-Start Workflow (Phase 7 - Checkpoint 3)

```text
WindowsAutoStartService manages Windows Task Scheduler integration:
    ↓
Enable: Create Task Scheduler task (ONLOGON trigger, user-level)
    ↓
Disable: Delete Task Scheduler task
    ↓
Status: Check if task exists and is enabled
    ↓
Platform-aware: Only available on Windows
```

`WindowsAutoStartService` owns Windows auto-start management using Task Scheduler. It creates user-level tasks (no admin required) with ONLOGON trigger to start the application when the user logs in. The task runs with HIGHEST privileges which may be needed for browser automation. Auto-start is optional and user-controlled - not automatic during development. The service checks task status, enables/disables via schtasks command, and provides platform-aware behavior (no-op on non-Windows). API routes provide auto-start status and control. This allows the application to start automatically with Windows while still requiring explicit user action to begin job processing (safe default).

## Decision Quality Workflow (Phase 7 - Checkpoint 4)

```text
DecisionQualityService evaluates job decision quality:
    ↓
Hard filter checks (authoritative Python rules):
    - Profile confirmation
    - Location match
    - Experience compatibility
    - Salary minimum
    - Employment type
    - Job title scope
    - Duplicate protection
    ↓
If hard filter fails → HARD_REJECT
    ↓
AI Analysis integration (advisory only):
    - Role relevance
    - Skill relevance
    - Job quality
    - Suspicious detection
    ↓
Signal calculation:
    - Role relevance score (0-1)
    - Skill relevance score (0-1)
    - Experience compatibility score (0-1)
    - Location match score (0-1)
    - Salary suitability score (0-1)
    - Job quality score (0-1)
    - Freshness score (0-1)
    - Duplicate probability (0-1)
    - Suspicious probability (0-1)
    - Feedback adjustment (-1 to 1)
    ↓
Decision score calculation (0-100)
    ↓
Priority determination:
    - HIGH_PRIORITY (score ≥ 80)
    - NORMAL_PRIORITY (score ≥ 60)
    - LOW_PRIORITY (score ≥ 40)
    - SKIP (score ≥ 20)
    - HARD_REJECT (hard filter failed)
    - NEEDS_ATTENTION (special cases)
    ↓
Explainable decision with reason codes
    ↓
DecisionQualityRecord persistence for analytics
```

`DecisionQualityService` owns decision quality assessment. Hard filters remain authoritative - Gemini recommendations are advisory only. The service combines deterministic Python rules with AI analysis to produce explainable decisions with structured reason codes. Decision scores are calculated using weighted signal combination. Priority levels are determined based on decision scores and special cases. All decisions are persisted to DecisionQualityRecord for analytics and learning.

## Job Prioritization Workflow (Phase 7 - Checkpoint 4)

```text
JobPrioritizationService prioritizes jobs for application:
    ↓
Get list of job IDs to prioritize
    ↓
For each job:
    - Evaluate decision quality via DecisionQualityService
    - Calculate priority level
    - Generate explanation
    ↓
Sort by priority (descending):
    - HIGH_PRIORITY → 5
    - NORMAL_PRIORITY → 4
    - LOW_PRIORITY → 3
    - SKIP → 2
    - HARD_REJECT → 1
    - NEEDS_ATTENTION → 0
    ↓
Within same priority, sort by decision score (descending)
    ↓
Return prioritized job list
    ↓
Filter to eligible jobs (HIGH/NORMAL/LOW priority only)
    ↓
Apply limit if specified
```

`JobPrioritizationService` owns job prioritization logic. It uses DecisionQualityService for job evaluation and sorts jobs by priority level and decision score. The service provides methods to get all prioritized jobs, eligible jobs only, and eligible jobs with limit. Prioritization is deterministic and reproducible for the same inputs. Hard-filtered jobs (HARD_REJECT) never become higher priority than eligible jobs.

## Feedback and Learning Workflow (Phase 7 - Checkpoint 4)

```text
FeedbackService manages user feedback:
    ↓
Submit feedback for a job:
    - Feedback type (RELEVANT, NOT_RELEVANT, etc.)
    - Optional comments
    ↓
Store in JobFeedback model
    ↓
Feedback influence on decision quality:
    - Positive feedback → increase adjustment
    - Negative feedback → decrease adjustment
    - Adjustment range: -1 to 1
    ↓
Get feedback summary:
    - Total feedback count
    - Feedback type breakdown
    - Relevance rate calculation
```

`FeedbackService` owns feedback management. It stores explicit user feedback in JobFeedback model and provides methods to submit, retrieve, and summarize feedback. Feedback influences decision quality by adjusting the feedback_adjustment signal in DecisionQualityService. Learning boundaries are enforced - feedback cannot modify hard filters, change user preferences, or bypass safety gates. Feedback is used for ranking/prioritization only.

## Application Analytics Workflow (Phase 7 - Checkpoint 4)

```text
AnalyticsService provides application analytics:
    ↓
Analytics summary:
    - Discovered jobs
    - Total applications
    - Successful applications
    - Skipped applications
    - Needs attention
    - External applications
    - Success rate
    - AI requests
    - AI analyses
    - Discovery runs
    ↓
Skip reasons analysis:
    - Top skip reasons with counts
    - Configurable time period
    ↓
Decision breakdown:
    - Priority distribution
    - Counts and percentages
    ↓
Applications by day:
    - Daily application counts
    - Time-series data
    ↓
Applications by job profile:
    - Breakdown by job title
    - Application counts per title
    ↓
Primary reason codes:
    - Top decision reason codes
    - Aggregated statistics
    ↓
Feedback summary:
    - Total feedback
    - Feedback type breakdown
    - Relevance rate
    ↓
Recent decision activity:
    - Latest decision quality records
    - Priority, score, reason codes
```

`AnalyticsService` owns analytics and reporting. It uses existing Job, Application, DecisionQualityRecord, and JobFeedback data to provide comprehensive analytics without creating fake historical data. All analytics respect configurable time periods and provide aggregate metrics for decision-making and performance monitoring.

## Frontend Architecture

The frontend is built with modern React architecture for production-ready SaaS dashboard experience:

```text
React 19.1.0 + TypeScript 5.8.3
    ↓
Vite 6.3.5 (build tooling)
    ↓
Tailwind CSS 4.1.4 (styling)
    ↓
Lucide React 0.468.0 (icons)
    ↓
Component-based architecture
```

**Component Structure:**
- App shell with navigation and layout
- Reusable state components (LoadingState, EmptyState, ErrorState, BackendState)
- Feature-specific components (AnalyticsDashboard, AgentControl, ProfileWorkspace, JobPreferences)
- Type-safe API integration with TypeScript
- Modern React patterns with hooks

**Design System:**
- Naukri-inspired color palette (primary blue, deep blue, accent orange)
- Consistent spacing system (4px, 8px, 16px, 24px, 32px)
- Responsive design (desktop, tablet, mobile)
- Accessibility-first approach (ARIA labels, keyboard navigation, focus states)
- Modern visual language with rounded corners, shadows, and transitions

**Build Pipeline:**
- TypeScript compilation for type safety
- Vite production build with code splitting
- CSS bundling with Tailwind
- Optimized bundle size (267.10 kB JS, 28.43 kB CSS)
- Fast build times (17.59s)

**API Integration:**
- RESTful API communication with FastAPI backend
- Type-safe API contracts with TypeScript interfaces
- Error handling and loading states
- Backend connection state management
- Graceful degradation for offline scenarios
## Phase 10 Application Boundary Fix

The application boundary is now evidence-driven offline. After a native Apply click,
the adapter waits for explicit visible `#already-applied`, `.already-applied`, exact
`Applied`, or `Applied to "<title>"` evidence before marking an application APPLIED.
If a visible application container appears, question handling is scoped to that
container and excludes hidden, disabled, zero-sized, and readonly controls. If
neither state appears within the bounded wait, the attempt becomes NEEDS_ATTENTION.
Native/external classification occurs before creating APPLICATION_STARTED and is
rechecked immediately before the click. Unresolved EXTERNAL_APPLICATION and
NEEDS_ATTENTION attempts require manual reset before retry. This checkpoint was
validated offline only; no live browser action or submission occurred.
