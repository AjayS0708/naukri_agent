# Architecture

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
