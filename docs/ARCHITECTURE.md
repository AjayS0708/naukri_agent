# Architecture

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
