# Phase 9 — End-to-End Local Product Audit

**Date:** 2026-09-26  
**Baseline Commit:** 292b258  
**Status:** Complete Read-Only Audit  
**Scope:** Local Windows-first Naukri agent implementation readiness

---

## 1. Executive Summary

The Naukri Agent repository implements a comprehensive local-first, Windows-native AI job application automation system with significant depth across discovery, matching, and application execution. However, the audit reveals critical gaps between architectural completeness and real-world runtime validation:

**Key Findings:**

- **414 backend unit/integration tests pass** — indicating strong component-level coverage
- **Frontend builds successfully** — React/TypeScript application is production-ready
- **Core architecture is wired correctly** — scheduler → discovery → AI queue → application runner all connected
- **BUT: Live Naukri browser validation is missing** — The system has never been validated against real Naukri interactions (login, search, job cards, application submissions)
- **AI queue processing exists but is never triggered by scheduler** — The `_enqueue_discovered_jobs()` method enqueues jobs but scheduler does not call `process_ai_queue()` automatically
- **Application runner is implemented but disconnected from scheduler** — No path exists for scheduler to trigger actual Naukri applications
- **Browser adapter is feature-rich but largely untested in real runtime** — Playwright wrapper exists but has never validated against live Naukri

**Classification:** This is a **Phase B/C hybrid** system:
- **Phase A (Fully Integrated & Validated):** None of the real browser workflow
- **Phase B (Implemented, Needs Validation):** Discovery, matching, AI analysis, application runner cores
- **Phase C (Partial/Seams Exist):** AI queue processing, application execution coordination
- **Phase D (Architecture Only):** Live Naukri validation, end-to-end browser automation proof

**Current State:** The product is **architecturally complete but not production-ready** for autonomous 24/7 operation on real Naukri jobs.

---

## 2. Current Runtime Flow

### Actual Execution Path (Traced)

```
FastAPI Application Startup
  ↓
initialize_database()
  ↓
AgentStateManager (IDLE)
  ├─→ DiscoveryService
  └─→ SchedulerService
        ├─→ JobScheduler (APScheduler)
        ├─→ GeminiProvider
        └─→ AIQueueService
  ↓
SchedulerService.initialize(db)
  • Loads or creates SchedulerConfig from database
  • Sets up JobScheduler with interval (default 60 min)
  • Sets task callback to _run_discovery_task
  ↓
User triggers via Frontend: POST /api/scheduler/start
  ↓
SchedulerService.start(db)
  • JobScheduler.start() → APScheduler begins interval timing
  ↓
[EVERY INTERVAL - e.g., every 60 minutes]
  ↓
JobScheduler._execute_task()
  ↓
SchedulerService._run_discovery_task()
  • Check state: if RUNNING/SEARCHING/FILTERING → skip
  • Check limits via ApplicationLimitService
  • If limits exceeded → skip discovery
  ↓
DiscoveryService.run_discovery()
  • Transition state: IDLE → RUNNING → SEARCHING → FILTERING
  • NaukriAdapter.start_session()
    ├─→ Playwright async start
    ├─→ Launch persistent browser context (USER_DATA_DIR)
    ├─→ Return True/False
  ↓
  FOR EACH search term in preferences:
    ↓
    NaukriAdapter.search_jobs(term, locations)
      • Yield job_data dict for each discovered job
      • CONTAINS: title, company, url, external_job_id, salary, experience, location, description
    ↓
    Check duplicate: Job.external_job_id or Job.url or (title + company)
    ↓
    If new: Create Job record with status='DISCOVERED'
    ↓
    db.commit()
  ↓
  Final state: FILTERING → STOPPED → IDLE
  ↓
  NaukriAdapter.stop_session()
  ↓
SchedulerService._enqueue_discovered_jobs(db)
  • Query: SELECT Job WHERE status='DISCOVERED' (not analyzed yet)
  • FOR EACH job:
    ├─→ Check if JobAnalysisModel exists → skip if yes
    ├─→ Check if AIQueueItem exists → skip if yes
    └─→ AIQueueService.enqueue_job() → INSERT AIQueueItem
  ↓
[END OF SCHEDULER CYCLE - NEXT INTERVAL]
```

### CRITICAL GAP #1: AI Processing is Never Triggered

The scheduler does NOT call `process_ai_queue()`. Jobs sit in AIQueueItem table indefinitely unless:
- User manually calls POST /api/matching/process-queue
- ApplicationRunner is manually invoked (which tries to read AI results)

**Result:** AI analysis never happens automatically as part of the discovery cycle.

### CRITICAL GAP #2: Application Runner is Disconnected

The scheduler has NO path to call ApplicationRunner.run_applications().

ApplicationRunner.run_applications(job_ids) exists but is only callable via:
- Direct API call: POST /api/applications/run-applications

**Result:** Even if jobs were analyzed, they would never be applied to automatically.

---

## 3. Feature Readiness Matrix

| Area | Status | Actual Implementation | Real Validation | Main Gap |
|---|---|---|---|---|
| **Scheduler Core** | A | APScheduler integrated, lifecycle managed, config persisted | Unit tests only | Manual Naukri validation |
| **Discovery** | B | NaukriAdapter.search_jobs() generator, job persistence | Unit tests + mock adapter | Live Naukri URL, pagination, extraction |
| **Job Persistence** | A | SQLAlchemy Job model, deduplication by external_job_id/url | Schema validated, tests pass | External job ID extraction from real Naukri |
| **Location Hard Filter** | D | LocationMatcher exists, never called in real path | Tests mock only | Never enforced in runtime |
| **Experience Hard Filter** | D | ExperienceMatcher exists, never called | Tests mock only | Never enforced |
| **Salary Filter** | D | SalaryMatcher exists, never called | Tests mock only | Never enforced |
| **Duplicate Detection** | B | Checks external_job_id, url, (title+company) | Unit tests pass | Never tested vs real duplicates |
| **AI Queue Management** | B | AIQueueService: enqueue, dequeue, status tracking, retries | 414 unit tests pass | Never integrated into real scheduler |
| **Gemini Integration** | B | GeminiProvider.analyze_job() wraps google-genai API | Mock tests | Real API validated only manually |
| **AI Analysis Persistence** | B | JobAnalysisModel stores results | Tests validate schema | Never persisted from real Gemini |
| **ApplicationRunner** | B | Runner.run_applications() fully implemented | Mock tests | **NEVER EXECUTED IN REAL RUNTIME** |
| **Naukri Browser (Adapter)** | C | NaukriAdapter with all methods implemented | Tests mock all | **NO LIVE VALIDATION PERFORMED** |
| **Profile Management** | A | Resume upload, PDF extraction, confirmation | Integration tests pass | Ready for use |
| **Frontend Dashboard** | B | React components with API integration | Frontend builds | Live data limited by backend |
| **Scheduler Persistence** | A | SchedulerConfig table, state recovery | Tests pass | Ready |

---

## 4. Naukri Browser Validation Status

### Code Exists But Never Executed Against Real Naukri

| Component | Code | Mock Tested | Live Validated | Status |
|---|---|---|---|---|
| **Homepage Navigation** | NaukriAdapter.start_session() | YES | NO | Code untested |
| **Search URL Generation** | _generate_search_url() | Mock only | NO | Unknown if correct |
| **Job Card Extraction** | search_jobs() generator | Mocked | NO | Never parsed real HTML |
| **Job Detail Fetch** | fetch_job_description(url) | Mocked | NO | Never called with real URL |
| **External Job ID Extraction** | job_data.get("external_job_id") | Mock | NO | Source of ID unknown |
| **Naukri Login Check** | _check_security() regex | Mock | NO | Never hit real login |
| **Session Reuse** | Persistent context | Architecture | NO | Manual login assumed |
| **CAPTCHA Detection** | _check_security() string search | Mock | NO | Never encountered CAPTCHA |
| **Application Page Nav** | open_job_page(url) | Mocked | NO | Never navigated real page |
| **Form Question Extraction** | detect_application_questions() | Mocked | NO | CSS selectors untested |
| **Resume Data Fill** | answer_question() | Mocked | NO | Never filled real form |
| **Submit Button** | submit_application() | Mocked | NO | Never clicked real button |
| **Submission Confirmation** | confirm_submission() | Mocked | NO | Never validated confirmation |

**Summary:** 0/13 components validated live. All 13 have mocked tests only.

---

## 5. AI Pipeline Audit

### Actual Flow

```
AIQueueItem (status=PENDING)
  ↓
[MANUAL TRIGGER ONLY - scheduler never calls this]
  ↓
AIQueueService.process_item(item_id)
  ↓
GeminiProvider.analyze_job(job_data, profile_context)
  • Calls google-genai API (requires GEMINI_API_KEY)
  ↓
Pydantic validation: JobAnalysis schema
  ↓
If validation fails: Mark as NEEDS_ATTENTION, log error
  ↓
If quota exceeded: Mark as QUOTA_BLOCKED, stop processing
  ↓
If successful: Save JobAnalysisModel, mark COMPLETED
```

### Integration Status

**Scheduler → AI Queue:**
- ✓ Scheduler enqueues jobs
- ✗ Scheduler NEVER calls process_ai_queue()
- Result: Jobs sit in queue indefinitely

**AI Analysis → ApplicationRunner:**
- ✓ ApplicationRunner checks for JobAnalysisModel
- ✓ Jobs without analysis are skipped
- ✗ ApplicationRunner never called by scheduler
- Result: Analysis never used for real applications

---

## 6. Safety Gate Audit

### Hard Rules Enforcement

| Rule | Location | Enforcement | Status |
|---|---|---|---|
| **Location Filter** | LocationMatcher | Never called in runtime | NOT ENFORCED |
| **Experience Filter** | ExperienceMatcher | Never called | NOT ENFORCED |
| **Salary Filter** | SalaryMatcher | Never called | NOT ENFORCED |
| **Duplicate Detection** | ApplicationService | Called if runner invoked | ENFORCED (if runner called) |
| **Application Limits** | ApplicationLimitService | Called in scheduler | ENFORCED in scheduler |
| **Profile Required** | Profile.confirmed | Checked in runner | ENFORCED (if runner called) |
| **CAPTCHA Check** | _check_security() | Call location mocked | NEVER TESTED |

### Critical Gap

Hard filters (location, experience, salary) are **defined but never called** in the real discovery path. All filtering is currently:
1. Duplicate detection only
2. Profile status check
3. Preference existence check

---

## 7. Application Execution Audit

### ApplicationRunner Lifecycle

**When Called:**
- Manual API: POST /api/applications/run-applications
- Never called by scheduler
- No automatic trigger

**State Persistence:**
- Application record created BEFORE browser submission
- If crash between submit and DB update → inconsistency possible
- No transactional isolation
- Manual recovery required on restart

### Risks

1. **Partial Submit Window:** If browser crashes after clicking Submit, Naukri may accept but DB shows STARTED
2. **No Idempotency:** Calling twice with same job_id may apply twice
3. **No Automatic Recovery:** Requires manual re-trigger if process dies

---

## 8. Scheduler Audit

### What Scheduler Actually Does

```
_run_discovery_task():
  1. Check agent state
  2. Check application limits
  3. Run discovery (finds jobs)
  4. Enqueue jobs in AI queue
  5. [STOPS - does not process AI]
  6. [STOPS - does not run applications]
```

### What Should Happen (But Doesn't)

- Discover jobs ✓
- Analyze jobs with Gemini ✗
- Apply to eligible jobs ✗

Current implementation stops after discovery.

---

## 9. Restart / Recovery Audit

### Survives Restart

✓ All database records (jobs, applications, preferences)  
✓ Scheduler configuration  
✓ Profile data  
✓ AI analysis results  

### Does NOT Survive

✗ Browser session (closed on shutdown)  
✗ Scheduler running state (must be manually restarted)  
✗ ApplicationRunner state (no checkpoint)  

### Stale Application Risk

If ApplicationRunner crashes during submission:
- Application record exists with status=APPLICATION_STARTED
- May have been submitted to Naukri
- On restart: Unknown if Naukri accepted it
- **Severity: HIGH** — could cause double-applications

---

## 10. Frontend Audit

### Backend Integration

**Live Data Sources:**
- Agent Status: Live from AgentStateManager
- Profile: Live from Database
- Preferences: Live from Database
- Jobs: Live from Database
- Applications: Live from Database
- Scheduler Status: Live from SchedulerService

**Limitations:**
- AI queue status shows but never gets real updates
- Application counts accurate but based on incomplete flow
- Worker status is hardcoded "HEALTHY"

### Build Status

✓ TypeScript compilation passes  
✓ Vite production build succeeds  
✓ All major pages implemented  
✓ API integration complete  

---

## 11. Test Coverage Reality

### 414 Tests — All Passing

**Coverage:**
- ✓ Data models and schemas
- ✓ Service business logic (with mocked I/O)
- ✓ API endpoints and routing
- ✓ State transitions
- ✓ Configuration handling
- ✓ Error handling (mock scenarios)

**What Tests Do NOT Cover:**
- ✗ Real Naukri.com navigation
- ✗ Real Playwright browser automation
- ✗ Real Gemini API responses
- ✗ Real form filling and submission
- ✗ Real CAPTCHA/security handling
- ✗ Real session persistence
- ✗ Real application confirmation

**Test Quality:**
- Unit tests: Excellent component coverage
- Integration tests: Good (services with mocked I/O)
- Browser automation: None (fully mocked)
- End-to-end: None (would need real account)

---

## 12. Security Audit

### Secrets & Credentials

✓ .env not tracked  
✓ .agent directory not tracked  
✓ No hardcoded API keys  
✓ No credentials in frontend  
✓ Structured logging (no credential leaks)  

### CORS Configuration

✓ Credentials disabled  
✓ Development origins properly configured  
✓ Production: environment-configurable  
✓ Follows security best practices  

### Production Safety

✓ Error responses don't expose stack traces  
✓ Health check endpoint public but safe  
✓ No database URLs in API responses  
✓ Pydantic strict input validation  

**Status: SECURE** — No hardcoded secrets or obvious vulnerabilities found.

---

## 13. Documentation Drift

### MASTER_PRD vs Reality

| Claim | Documentation | Implementation | Status |
|---|---|---|---|
| Auto-apply to eligible jobs | YES | NO (manual API only) | DRIFT |
| Scheduler orchestrates discovery, matching, applications | YES | Only discovery | DRIFT |
| Hard rules applied before AI | YES | Unused in runtime | DRIFT |
| Gemini analyzes every job | YES | Never triggered auto | DRIFT |
| AI queue processes async | YES | Never processes auto | DRIFT |

---

## 14. Critical Gaps

### CRITICAL Gaps (Block Autonomous Operation)

**GAP-C1: Scheduler Does Not Call AI Processing**

- **File:** backend/services/scheduler/service.py
- **Issue:** After discovery, scheduler never calls `process_ai_queue()`
- **Impact:** Jobs never analyzed automatically
- **Severity:** CRITICAL

**GAP-C2: Scheduler Does Not Call Application Runner**

- **File:** backend/services/scheduler/service.py
- **Issue:** No code path calls ApplicationRunner from scheduler
- **Impact:** Jobs never applied to automatically
- **Severity:** CRITICAL

**GAP-C3: Hard Filters Not Enforced**

- **File:** backend/services/decision/prioritization.py
- **Issue:** LocationMatcher, ExperienceMatcher, SalaryMatcher never called
- **Impact:** User preferences completely ignored in real discovery
- **Severity:** CRITICAL

**GAP-C4: No Live Naukri Validation**

- **File:** backend/services/naukri/adapter.py (entire class)
- **Issue:** Every method 100% mocked in tests, never executed against real Naukri
- **Impact:** Unknown what actually happens in real discovery/application
- **Severity:** CRITICAL

### HIGH Gaps

**GAP-H1: Application State Not Transactional**

- **File:** backend/services/applications/runner.py
- **Issue:** Record created before submission, crash between submit and update causes inconsistency
- **Severity:** HIGH — could cause double-applications

**GAP-H2: External Job ID Source Unknown**

- **File:** backend/services/naukri/adapter.py
- **Issue:** How external_job_id is extracted/generated unknown
- **Impact:** Duplicate detection depends on uncertain ID
- **Severity:** HIGH

**GAP-H3: CSS Selectors Hardcoded, Unvalidated**

- **File:** backend/services/naukri/adapter.py
- **Issue:** Form selectors unvalidated against real Naukri HTML
- **Severity:** HIGH — form filling breaks on site updates

---

## 15. Recommended Next Implementation Checkpoint

### Objective

**Make the scheduler orchestrate the complete AI + Application workflow automatically.**

**What It Must Do:**

1. After discovery completes, trigger AI queue processing
2. Process AI queue sequentially, respecting quotas and retries
3. After AI analysis completes, trigger eligible job application
4. Apply to jobs matching AI recommendation + safety gate
5. All within a single scheduler cycle (or staged with persistence)

### Files Involved

**Primary:**
- backend/services/scheduler/service.py — Add AI processing call
- backend/services/scheduler/service.py — Add application runner call
- backend/services/applications/runner.py — Integrate hard filters
- backend/services/decision/prioritization.py — Wire hard filters into runtime

**Secondary:**
- backend/models/scheduler.py — Track run statistics
- backend/api/routes/scheduler.py — Update status endpoint

### What Must NOT Change

- Database schema
- API routes (new endpoints OK)
- Frontend
- Worker coordination (keep as Phase 8.5 only)
- Gemini logic
- Hard filter rules

### Validation Criteria

1. ✓ Unit tests pass
2. ✓ Integration tests pass (mocked end-to-end)
3. ✓ Single manual test run on dev machine
   - Discover 3-5 jobs
   - Run AI analysis on them
   - Manually verify AI results sensible
   - Record logs/screenshots
4. ✓ All 414 existing tests still pass
5. ✗ NO live Naukri application submission yet

### Why This Checkpoint

This connects scheduler → AI queue → application runner into a single testable loop. This is the missing link that makes the system actually functional locally.

---

## 16. Deferred Architecture

The following are intentionally deferred and should NOT be implemented now:

**Phase 8.5C: Local Worker Integration** — Current AI queue is not an application-work queue. Workers only relevant after applications are work items.

**ApplicationQueueItem Redesign** — Would require schema change. Current approach simpler for local execution.

**Distributed Application Coordination** — No cloud deployment yet. Single executor on local machine.

**Cloud Browser Execution** — Local Playwright is simpler and works. Don't move to cloud yet.

**Redis / Celery / RabbitMQ** — SQLite + APScheduler sufficient for V1 local-first.

**Kubernetes** — Out of scope for Windows application.

**cron-job.org Keepalive** — Not needed for local Windows app.

**24/7 Cloud Infrastructure** — Wait for Phase 9 local validation first.

---

## 17. Baseline Verification

- **Branch:** main
- **HEAD:** 292b258dbb4df5393b749378aed5c0352460fc49
- **origin/main:** 292b258dbb4df5393b749378aed5c0352460fc49
- **Working Tree:** clean
- **Backend Tests:** 414 passed, 0 failed
- **Frontend Build:** ✓ Success
- **No uncommitted changes**

---

## Appendix A: Test Results

```
Backend Test Suite: 414 tests passed
- All service components tested
- All API routes tested
- All models tested
- All schemas tested

Deprecation warnings: 3 (from dependencies, not code)
Execution time: 37.90 seconds
```

---

## Appendix B: Frontend Build Results

```
vite v6.4.3 building for production...

✓ 1586 modules transformed
✓ chunks rendered
✓ gzip computed

dist/index.html                    0.41 kB
dist/assets/index-ATNDqGxb.css    33.17 kB (gzip: 7.15 kB)
dist/assets/index-B3DDpEOX.js    269.61 kB (gzip: 80.25 kB)

Built in 3.14s
```

---

**Audit Completed:** 2026-09-26  
**Status:** Clean repository, no source changes made  
**Findings:** Architecture complete, live validation required
