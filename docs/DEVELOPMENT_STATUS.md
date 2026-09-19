# Development Status

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
- Scheduler is NOT implemented (Phase 7)
- 24/7 cloud execution is NOT implemented (Phase 7+)

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
