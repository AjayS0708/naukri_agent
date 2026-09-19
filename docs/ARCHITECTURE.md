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
