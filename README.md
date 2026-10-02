# Naukri AI Job Application Agent

## Phase 10 Supervised Live Launcher (Build Only)

`phase10_live_apply_launcher.py` is an explicitly gated launcher for a single manually supervised native-flow validation. It is not executed by the project test suite. It rejects S&P Global job `300926927428`, requires a database backup before any ORM write, requires exact `PROCEED <job_id>` and `SUBMIT <job_id>` confirmations, and uses `ApplicationRunner` with its supervised form-stop boundary. The launcher never bypasses CAPTCHA/security checks and does not retry.

Run manually only after reviewing the pre-flight output:

```powershell
& ".venv\Scripts\python.exe" phase10_live_apply_launcher.py 240926500723
```

Offline launcher and runner tests do not open Naukri, call Gemini, click controls, or write the production database.

## Phase 10 Application-Type Reliability: IMPLEMENTED

`NaukriAdapter.detect_application_type()` now performs one bounded 500 ms settling observation when the initial visible page contains neither definitive external nor native evidence. External indicators remain authoritative, visible native selectors remain required for `NAUKRI_NATIVE`, and no-evidence states return `AMBIGUOUS` rather than being treated as native. The application runner treats ambiguity as `NEEDS_ATTENTION` without creating an application record.

Focused adapter coverage includes delayed native/external evidence, hidden controls/text, external-first precedence, and ambiguous states. The full Naukri adapter suite passed with 96 tests. A read-only live check found Quadrasystems ambiguous on both immediate and settled observations, while Cisco remained clearly external. No Apply or Submit action occurred; automated successful application count remains 0.

## Phase 10 Live Native Application Test: BLOCKED

On 2026-10-01, the authenticated persistent Playwright session opened Naukri successfully and showed no visible CAPTCHA, security challenge, login wall, or access block. The backend readiness endpoint reported `ready`; the confirmed profile, configured preferences, compatible schema, and unused application limits were present.

A single bounded discovery pass inspected five `Data Analyst` results without clicking Apply. No safe eligible native candidate was available: four candidates failed duplicate, employment-type, or external-classification checks, and the one native result was already processed. No Gemini analysis or application flow was started, so no submission was attempted. The database remained unchanged at 10 application records and 0 APPLIED/SUBMITTED records. Automated successful application count remains 0.

Phase 10 live submission validation remains blocked until a fresh candidate passes all configured rules and duplicate protection.

## Phase 10 Database Schema Migration: IMPLEMENTED

The Phase 10 schema migration ensures all databases (SQLite and PostgreSQL) have required columns for explicit applied state detection. The migration runs automatically during application startup via `initialize_database()`, is fully idempotent, and preserves all existing data.

**Key Implementation Details:**
- Migration mechanism: Additive `ALTER TABLE` with column existence checks (Phase 9B-4 pattern)
- Idempotent: Safe to run multiple times; already-present columns are skipped
- Startup integration: Runs before request handling during FastAPI lifespan initialization
- Schema validation: `/readiness` endpoint reports `schema: compatible` or missing columns
- Standalone command: `python -m backend.database.database` for manual execution
- Database support: SQLite (tested) and PostgreSQL (verified for syntax compatibility)
- Local migration: Applied to `data/naukri_agent.db` (backup: `data/naukri_agent.db.bak-before-migration`)
- Test coverage: 7 focused migration tests + 557 full backend suite tests all passing

**Verification Results (Local SQLite):**
- Application count: 10 (unchanged by migration)
- Record 10 status: APPLICATION_STARTED (unchanged)
- APPLIED/SUBMITTED count: 0/0 (unchanged)
- confirmation_evidence column: Added successfully
- is_dry_run column: Already present from Phase 9B-4
- ORM queries: Executing without OperationalError

## Phase 10 Application Boundary Fix: IMPLEMENTED OFFLINE

The focused offline checkpoint now detects explicit post-Apply `Applied` evidence
with bounded waits, scopes question detection to visible editable application
containers, computes profile experience from elapsed dates, classifies native versus
external jobs before creating `APPLICATION_STARTED`, and prevents repeat attempts
after `EXTERNAL_APPLICATION` or `NEEDS_ATTENTION` without a manual reset. Confirmation
evidence is persisted with native application records. Unit and full backend tests
run against the isolated SQLite database only. No live Naukri activity, Gemini call,
Apply/Submit click, or application submission occurred; the successful application
count remains 0.

Windows-first, local-first foundation for a controlled job-application agent. Deterministic rules will remain the execution authority; AI and browser automation are intentionally not implemented in Phase 1.

## Phase 9B-4 Safety Boundary

Dry-run application execution is now pre-Apply inspection only. It opens and classifies the candidate page, records an explicit `is_dry_run` inspection record, and stops before any native or external Apply action; it does not invoke `start_application()`, answer questions, submit, or confirm submission. Application lifecycle data distinguishes `PRE_APPLY`, an unverified Apply/form boundary, `FORM_OPENED`, `APPLIED`, `SUBMITTED`, and `NEEDS_ATTENTION`. Native Apply semantics remain unknown, so Phase 9B-3 live form-boundary validation remains incomplete. No live application occurred in this checkpoint.

## Status

**Phase 10 Database Schema Migration: Complete (Local SQLite Migrated)**

Schema migration checkpoint is complete:
- Root cause identified: confirmation_evidence column in ORM model but missing from initialize_database()
- Solution implemented: Idempotent ALTER TABLE with column existence checks
- Startup integration: Runs before request handling
- Readiness check: Added to `/readiness` endpoint with schema compatibility validation
- Full test suite: 557 tests passing (includes 7 new migration tests)
- Local database: Migrated successfully, 10 records preserved, no data loss
- Standalone command: Available via `python -m backend.database.database`
- PostgreSQL support: Verified for SQL syntax compatibility
- Neon deployment: Instructions provided; migration NOT executed

All code changes completed and tested. Local SQLite database migrated and verified. No live Naukri activity, Gemini calls, or application submissions. Successful application count: 0.

The V1 Gemini default is `gemini-flash-lite-latest` (verified after `gemini-2.5-flash` returned `429 RESOURCE_EXHAUSTED`). Model remains configurable through `NAUKRI_AGENT_GEMINI_MODEL`. Phase 9B-3 live form boundary validation remains pending.

The production JD extraction selector fix is implemented. `NaukriAdapter.fetch_job_description()` now prefers visible `[class*="dang-inner-html"]` and falls back to visible `section[class*="job-desc-container"]`, matching the hashed Naukri structures observed during live diagnostics. Focused adapter regression coverage includes both selectors, precedence, hidden-element fallback, and no-match behavior. Phase 9B-3 remains incomplete until a live native APPLY flow reaches the application boundary; no Gemini, Apply, or submission action occurred in this checkpoint.

Phase 9B-3 reached a live JD extraction blocker. A visible authenticated-browser diagnostic inspected two persisted native Naukri job pages: First American (HTTP 200, visible body length 7,264) and ReactZ Consulting (HTTP 200, visible body length 4,486). Both pages contained visible JD text, but `fetch_job_description()` returned empty because `.job-desc` matched 0 elements and the exact `.styles_JDC__` selector matched 0 elements. The live pages used suffixed hashed classes such as `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`; no selector was changed in this diagnostic checkpoint. Gemini is intentionally deferred because quota is exhausted, and no Apply or submission action occurred.

The live diagnostic now reuses `NaukriAdapter.fetch_job_description()` before Gemini analysis, persists the fetched text in `Job.description`, and sends that actual text in the diagnostic Gemini context. It inspects bounded real candidates before selecting, excludes external jobs from native-flow selection, reuses persisted analyses, stops on Gemini quota exhaustion, reports description fetch status/length, and uses ASCII-safe output. This is an offline-tested diagnostic correction only; no live Naukri search was run, Gemini quota was not consumed, and Phase 9B-3 remains incomplete.

Phase 9B-3 native application detection fix is implemented. Live inspection found that a real First American Data Analyst page exposes a visible `button#apply-button` / `button.apply-button` control with exact text `Apply`, but the adapter previously classified it as external. Detection and native start selectors now recognize stable DOM evidence without relying on hashed classes. Focused adapter coverage includes native controls, external application indicators, no-control fallback, and the current native start selector: 84 tests passed. The full backend suite passed with 519 tests and 3 dependency deprecation warnings. The full live native dry-run remains pending; no application was submitted in this checkpoint.

Test database isolation checkpoint is complete. Backend tests now use a disposable temporary SQLite database and never reset the runtime database at `data/naukri_agent.db`. The shared test fixture redirects application database sessions to the isolated engine before tests start; production profile/resume data is not used by or modified by tests. Isolation regression tests passed, focused profile/application tests passed, and the full backend suite passed with 512 tests. The production database remained present with its existing profile/resume rows after the suite.

Phase 9B-3 false-positive-fix checkpoint is in progress. Live validation discovered that the selected RR Groups job page was a normal HTTP 200 Naukri job page, but `_check_security()` incorrectly blocked it because raw HTML contained Naukri's internal `"showCaptcha":false` value. The targeted fix in `backend/services/naukri/adapter.py` checks visible rendered body text instead of raw HTML and does not treat bare `captcha` as a standalone trigger. Regression coverage verifies the raw `showCaptcha:false` value, bare visible `captcha`, explicit visible reCAPTCHA/hCAPTCHA/security indicators, and a normal Naukri job page. 77 Naukri adapter tests and 509 full backend tests pass. Another real visible-browser Naukri dry-run is still required; Phase 9B-3 live validation is not complete, and no application has been submitted.

Phase 9B-2C Checkpoint is complete: Profile Duplicate ERROR Recovery. Fixed a live-validation blocker where uploading a PDF whose existing profile was in ERROR state returned the broken profile without re-running extraction. The duplicate path now checks profile status: CONFIRMED/REVIEW_REQUIRED duplicates are reused as before; ERROR duplicates re-read the stored PDF and re-run the full extraction pipeline against the existing profile record (no new records created). On success: ERROR → REVIEW_REQUIRED, confirmed remains false. On failure: remains ERROR. 6 regression tests added. 503 total backend tests passing (+6). No live Naukri activity.

Phase 9B-2B Defect Fix Checkpoint is complete: Two runtime defects discovered during live dry-run attempts were fixed. (1) `prompt_version` NOT NULL persistence defect in `AIQueueService.process_item()` — now uses `JOB_ANALYSIS_PROMPT_V1` constant from `prompts.py` instead of a disconnected literal. (2) Experience year computation in `MatchEngine` replaced `len(experience_list)` with `compute_profile_experience_years()` which calculates actual elapsed years from `start_date`/`end_date` fields. 497 total backend tests passing (+14). No live Naukri activity in this checkpoint.

Phase 9A Checkpoint is complete: Scheduler Automation Loop. Implemented complete Phase 9A orchestration connecting all existing components into one automatic local execution flow. Scheduler now:
1. Discovers jobs via NaukriAdapter
2. Applies deterministic hard filters (MatchEngine) before queueing
3. Processes AI queue with Gemini analysis
4. Invokes ApplicationRunner for jobs with completed analysis
5. Records results with cycle statistics

Fixed all three audit gaps:
- **GAP-C1**: Scheduler automatically processes AI queue after discovery
- **GAP-C2**: Scheduler invokes ApplicationRunner for completed AI jobs  
- **GAP-C3**: Hard filters integrated into runtime discovery/matching path

Safety preserved: hard filters authoritative, ApplicationRunner sole executor, final safety gate always runs. Failure isolation ensures single job failures don't cascade. 480 total backend tests passing (previously 475, +5 Phase 9A tests). Frontend builds successfully. No live Naukri submissions (infrastructure only; Phase 9B will add live validation).

Phase 8.5B Checkpoint is complete: Distributed Work Coordination. Implemented worker-owned AI queue work claiming and coordination without race conditions. PostgreSQL uses atomic SELECT...FOR UPDATE SKIP LOCKED; SQLite uses transaction-safe fallback with explicit documentation of semantic differences. Stale work detection (30+ minutes without heartbeat) and safe recovery (escalates to NEEDS_ATTENTION if max_attempts exceeded) preserve existing application safety gates. Work ownership is strict: only claiming worker can heartbeat/release/complete/fail. 49 focused coordination tests passing; 475 total backend tests (previously 426, +49 coordination). No regression in existing AI queue, application runner, duplicate detection, or safety gates. Frontend unchanged.

Phase 8.5A Checkpoint is complete: Worker Foundation and Registration. Persistent worker identity layer introduced to support future cloud browser coordination without modifying current Naukri execution. WorkerType (LOCAL_WINDOWS, CLOUD_BROWSER) and WorkerStatus (STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR) enums defined. Worker model persists identity, type, status, runtime environment, and lifecycle timestamps. WorkerService provides registration (safely repeatable), retrieval, listing, and status updates. Minimal worker API endpoints: GET /api/worker/status (list), POST /api/worker/register (register), GET /api/worker/{worker_id} (get). 12 focused tests; 426 total tests passing. No changes to existing scheduler, Playwright, or NaukriAdapter.

Phase 8.4.1 Checkpoint is complete: Responsive Mobile Naukri-Inspired UX. The frontend is now fully responsive across mobile (320px-480px), tablet (768px-1024px), and desktop (1024px+) viewports. Mobile experience features a compact header with hamburger menu, sidebar drawer, and bottom navigation bar inspired by Naukri mobile app patterns. All touch targets are minimum ~44x44px. Desktop layout and functionality are preserved. No backend changes. Build passes; no TypeScript errors.

Phase 8.4 Checkpoint is complete: Vercel frontend preparation. All frontend API calls use a single public `VITE_API_BASE_URL` configuration, and the existing Vercel configuration builds the `frontend` Vite app. No Vercel deployment has been performed.

Phase 8.3 Checkpoint is complete: hosted FastAPI deployment preparation. The repository includes Render and Procfile service definitions, explicit production configuration validation, secure structured logs, and environment-driven CORS/frontend API configuration. This is preparation only; no service has been deployed.

Phase 8.2 Checkpoint is complete: PostgreSQL + Production Persistence. Backend seamlessly hosts configurations for SQLite and scaling instances with PostgreSQL `psycopg` integration and connection pooling metrics.

Phase 8.1 Checkpoint is complete: Production Backend Preparation. 414 tests passing. Backend is production-hosting ready with enhanced configuration, security, and monitoring.

Phase 7 Checkpoint 4 is complete: Agent intelligence, decision quality, job prioritization, feedback/learning, and application analytics.

Frontend UX/UI Redesign Checkpoint is complete: Professional SaaS dashboard design with modern UI/UX, improved accessibility, and responsive layout.

Frontend Codebase Structure Verification is complete: Production-ready React 19.1.0 + TypeScript 5.8.3 + Vite 6.3.5 + Tailwind CSS 4.1.4 stack with clean component architecture and stable build pipeline.


## Stack

Python 3.12+, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite, Tailwind CSS, pytest, Playwright, Gemini, and PyMuPDF.

## Layout

`backend/` contains the FastAPI API, core services, schemas, database, and tests. `frontend/` contains the React dashboard shell. `docs/` contains the product and continuity documentation. `data/` contains ignored local runtime data.

## Prerequisites

- Python 3.12+
- Node.js 20+

## Backend Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

The backend runs at `http://127.0.0.1:8000`; health is at `http://127.0.0.1:8000/api/health`.

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

The dashboard runs at `http://127.0.0.1:5173` and reads the backend health endpoint.

## Tests

```powershell
python -m pytest backend/tests
```

## Current Limitations

Phase 8.3 prepares only the hosted FastAPI API. Cloud browser execution, object storage, database provisioning, frontend deployment, and platform automation remain out of scope.

## Hosted FastAPI Deployment (Phase 8.3)

Run the API on a hosting platform with:

```text
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

`Procfile` provides a local-port fallback and `render.yaml` describes an equivalent Render web service. Set these host environment variables; do not commit their values:

- `NAUKRI_AGENT_APP_ENV=production`
- `NAUKRI_AGENT_DATABASE_URL` — external PostgreSQL URL
- `NAUKRI_AGENT_GEMINI_API_KEY`
- `NAUKRI_AGENT_FRONTEND_ORIGINS` — one or more comma-separated frontend origins

Production readiness rejects SQLite, a missing Gemini key, missing origins, and wildcard origins. `GET /api/health` is process-only and does not query the database or Gemini; `GET /api/readiness` reports whether database, configuration, storage, AI configuration, and runtime are ready. CORS allows only configured production origins and deliberately disables credentialed browser requests. `SafeJsonFormatter` recursively redacts credentials, API keys, authorization headers, cookies, sessions, nested values, and database URL userinfo.

## Vercel Frontend Preparation (Phase 8.4)

The root `vercel.json` installs, builds, and publishes the Vite app in `frontend/` (`npm --prefix frontend ci`, `npm --prefix frontend run build`, and `frontend/dist`). Set `VITE_API_BASE_URL` in Vercel to the public HTTPS FastAPI origin, for example `https://your-api-host.example`; the client normalizes it to `/api`. Locally, omit the variable to use `http://127.0.0.1:8000`.

`VITE_` values are public browser configuration. Never put Gemini keys, database URLs with credentials, Naukri credentials, cookies, sessions, or private tokens in them. Configure the deployed Vercel origin separately in `NAUKRI_AGENT_FRONTEND_ORIGINS` on the backend. The dashboard uses in-page state and hash links, not browser-path routing, so no SPA rewrite was added. API failures use safe user-facing messages and a request timeout; raw backend error details are not displayed.

## Production Readiness (Phase 8.1)

The backend has been prepared for production hosting with enhanced configuration, security, and monitoring:

- **Production Configuration**: Environment separation (LOCAL_WINDOWS/CLOUD), production detection, configurable CORS origins
- **CORS Configuration**: Production-safe with configurable multiple origins via FRONTEND_ORIGINS
- **Health/Readiness Endpoints**: Separate liveness (/api/health) and readiness (/api/readiness) endpoints for container orchestration
- **Error Handling**: Catch-all exception handler prevents sensitive information exposure
- **Logging**: Production-safe logging with automatic sensitive information redaction (api_key, password, token, secret, credential, auth)
- **Database Configuration**: Supports both SQLite (default) and PostgreSQL via DATABASE_URL
- **Storage Configuration**: StorageService abstraction ready for future object storage integration
- **Browser/API Separation**: API process does NOT auto-start Playwright browser; clear separation for future cloud architecture
- **Frontend Configuration**: Environment-based backend URL via VITE_API_BASE_URL (development: localhost, production: configurable)
- **Security**: No wildcard CORS in production, no stack traces in errors, no secrets in logs or API responses

## Cloud Readiness

The application includes cloud readiness infrastructure to support future cloud deployment while maintaining local-first V1 operation:

- **RuntimeContext**: Environment detection and behavior abstraction (LOCAL_WINDOWS for V1, CLOUD_READY for future)
- **StorageService**: File operations abstraction enabling future object storage (S3/Azure/GCS)
- **Environment configuration**: All settings use `NAUKRI_AGENT_` prefix for clean cloud deployment
- **Database flexibility**: Supports both SQLite (V1) and PostgreSQL (future)
- **No business logic changes**: V1 functionality unchanged; abstractions enable future cloud without code changes

Future cloud deployment will require: remote browser automation, object storage integration, PostgreSQL deployment, and cloud infrastructure setup.

## Profile Setup

Set `NAUKRI_AGENT_GEMINI_API_KEY` in a local `.env`, start the backend and frontend, then open the Profile section. Upload a PDF no larger than 10 MB, review the extracted facts, save any edits, and explicitly confirm the profile. A resume is not usable by future automation until it is confirmed.

The Phase 2 backend tests pass. In this environment the frontend build is currently blocked by a malformed native Vite dependency tree; remove `frontend/node_modules` and reinstall dependencies once Windows releases that generated directory.

## Development Phases

The formal product roadmap is defined by `docs/MASTER_PRD.md`.

1. Foundation and architecture - complete
2. Resume and user profile - complete
3. Gemini AI engine - complete
4. Matching and rules engine - complete
5. Naukri job discovery - complete
6. Naukri application automation - implementation complete; live native form-boundary validation remains unresolved
7. Scheduler and continuous agent - complete
8. Dashboard - complete
9. Notifications - implemented offline; SMTP delivery requires configuration
10. Testing, security, and Windows packaging - pending
11. Integration and production hardening - pending

Cloud deployment preparation is documented as supporting Phase 8.x/production-readiness work; it is not a separate formal product phase in the master roadmap.

Phase 9 notifications are isolated behind `NotificationService`. The implementation persists notification history, supports critical-error, authentication-required, security-challenge, external-application, and evening-summary events, and exposes `GET /api/notifications` for the dashboard. SMTP settings use the `NAUKRI_AGENT_` environment prefix; tests use a fake sender and no real email was sent. The evening summary is evaluated in the configured timezone during the configured 8 PM hour with daily deduplication. Live SMTP delivery remains unverified.

Note: Cloud readiness infrastructure (runtime/storage abstractions) was implemented as foundational work to support future cloud deployment without changing business logic. This is not a separate phase but enables future cloud execution. Phase 8.1 prepared the backend for production hosting without actual deployment.

## Phase 9B-4 Safety Boundary

Dry-run application execution is now pre-Apply inspection only. It opens and classifies the candidate page, records an explicit `is_dry_run` inspection record, and stops before any native or external Apply action; it does not invoke `start_application()`, answer questions, submit, or confirm submission. Application lifecycle data distinguishes `PRE_APPLY`, an unverified Apply/form boundary, `FORM_OPENED`, `APPLIED`, `SUBMITTED`, and `NEEDS_ATTENTION`. Native Apply semantics remain unknown, so Phase 9B-3 live form-boundary validation remains incomplete. No live application occurred in this checkpoint.

## Status

**Phase 10 Application Boundary Fix: Implemented (Offline Validated)**

The application boundary is now evidence-driven:
- Post-click state detection waits for explicit visible applied evidence (8s bounded wait)
- Question detection scopes to visible application containers only
- Experience computation uses elapsed years from `start_date`/`end_date`, not entry count
- Native/external classification happens BEFORE creating APPLICATION_STARTED
- No-repeat enforcement: EXTERNAL_APPLICATION and NEEDS_ATTENTION require manual reset

All validation performed with isolated temporary SQLite tests only. No live Naukri activity, Apply/Submit clicks, or Gemini calls. Production database untouched. Successful application count: 0.

The V1 Gemini default is `gemini-flash-lite-latest` (verified after `gemini-2.5-flash` returned `429 RESOURCE_EXHAUSTED`). Model remains configurable through `NAUKRI_AGENT_GEMINI_MODEL`. Phase 9B-3 live form boundary validation remains pending.

The production JD extraction selector fix is implemented. `NaukriAdapter.fetch_job_description()` now prefers visible `[class*="dang-inner-html"]` and falls back to visible `section[class*="job-desc-container"]`, matching the hashed Naukri structures observed during live diagnostics. Focused adapter regression coverage includes both selectors, precedence, hidden-element fallback, and no-match behavior. Phase 9B-3 remains incomplete until a live native APPLY flow reaches the application boundary; no Gemini, Apply, or submission action occurred in this checkpoint.

Phase 9B-3 reached a live JD extraction blocker. A visible authenticated-browser diagnostic inspected two persisted native Naukri job pages: First American (HTTP 200, visible body length 7,264) and ReactZ Consulting (HTTP 200, visible body length 4,486). Both pages contained visible JD text, but `fetch_job_description()` returned empty because `.job-desc` matched 0 elements and the exact `.styles_JDC__` selector matched 0 elements. The live pages used suffixed hashed classes such as `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`; no selector was changed in this diagnostic checkpoint. Gemini is intentionally deferred because quota is exhausted, and no Apply or submission action occurred.

The live diagnostic now reuses `NaukriAdapter.fetch_job_description()` before Gemini analysis, persists the fetched text in `Job.description`, and sends that actual text in the diagnostic Gemini context. It inspects bounded real candidates before selecting, excludes external jobs from native-flow selection, reuses persisted analyses, stops on Gemini quota exhaustion, reports description fetch status/length, and uses ASCII-safe output. This is an offline-tested diagnostic correction only; no live Naukri search was run, Gemini quota was not consumed, and Phase 9B-3 remains incomplete.

Phase 9B-3 native application detection fix is implemented. Live inspection found that a real First American Data Analyst page exposes a visible `button#apply-button` / `button.apply-button` control with exact text `Apply`, but the adapter previously classified it as external. Detection and native start selectors now recognize stable DOM evidence without relying on hashed classes. Focused adapter coverage includes native controls, external application indicators, no-control fallback, and the current native start selector: 84 tests passed. The full backend suite passed with 519 tests and 3 dependency deprecation warnings. The full live native dry-run remains pending; no application was submitted in this checkpoint.

Test database isolation checkpoint is complete. Backend tests now use a disposable temporary SQLite database and never reset the runtime database at `data/naukri_agent.db`. The shared test fixture redirects application database sessions to the isolated engine before tests start; production profile/resume data is not used by or modified by tests. Isolation regression tests passed, focused profile/application tests passed, and the full backend suite passed with 512 tests. The production database remained present with its existing profile/resume rows after the suite.

Phase 9B-3 false-positive-fix checkpoint is in progress. Live validation discovered that the selected RR Groups job page was a normal HTTP 200 Naukri job page, but `_check_security()` incorrectly blocked it because raw HTML contained Naukri's internal `"showCaptcha":false` value. The targeted fix in `backend/services/naukri/adapter.py` checks visible rendered body text instead of raw HTML and does not treat bare `captcha` as a standalone trigger. Regression coverage verifies the raw `showCaptcha:false` value, bare visible `captcha`, explicit visible reCAPTCHA/hCAPTCHA/security indicators, and a normal Naukri job page. 77 Naukri adapter tests and 509 full backend tests pass. Another real visible-browser Naukri dry-run is still required; Phase 9B-3 live validation is not complete, and no application has been submitted.

Phase 9B-2C Checkpoint is complete: Profile Duplicate ERROR Recovery. Fixed a live-validation blocker where uploading a PDF whose existing profile was in ERROR state returned the broken profile without re-running extraction. The duplicate path now checks profile status: CONFIRMED/REVIEW_REQUIRED duplicates are reused as before; ERROR duplicates re-read the stored PDF and re-run the full extraction pipeline against the existing profile record (no new records created). On success: ERROR → REVIEW_REQUIRED, confirmed remains false. On failure: remains ERROR. 6 regression tests added. 503 total backend tests passing (+6). No live Naukri activity.

Phase 9B-2B Defect Fix Checkpoint is complete: Two runtime defects discovered during live dry-run attempts were fixed. (1) `prompt_version` NOT NULL persistence defect in `AIQueueService.process_item()` — now uses `JOB_ANALYSIS_PROMPT_V1` constant from `prompts.py` instead of a disconnected literal. (2) Experience year computation in `MatchEngine` replaced `len(experience_list)` with `compute_profile_experience_years()` which calculates actual elapsed years from `start_date`/`end_date` fields. 497 total backend tests passing (+14). No live Naukri activity in this checkpoint.

Phase 9A Checkpoint is complete: Scheduler Automation Loop. Implemented complete Phase 9A orchestration connecting all existing components into one automatic local execution flow. Scheduler now:
1. Discovers jobs via NaukriAdapter
2. Applies deterministic hard filters (MatchEngine) before queueing
3. Processes AI queue with Gemini analysis
4. Invokes ApplicationRunner for jobs with completed analysis
5. Records results with cycle statistics

Fixed all three audit gaps:
- **GAP-C1**: Scheduler automatically processes AI queue after discovery
- **GAP-C2**: Scheduler invokes ApplicationRunner for completed AI jobs  
- **GAP-C3**: Hard filters integrated into runtime discovery/matching path

Safety preserved: hard filters authoritative, ApplicationRunner sole executor, final safety gate always runs. Failure isolation ensures single job failures don't cascade. 480 total backend tests passing (previously 475, +5 Phase 9A tests). Frontend builds successfully. No live Naukri submissions (infrastructure only; Phase 9B will add live validation).

Phase 8.5B Checkpoint is complete: Distributed Work Coordination. Implemented worker-owned AI queue work claiming and coordination without race conditions. PostgreSQL uses atomic SELECT...FOR UPDATE SKIP LOCKED; SQLite uses transaction-safe fallback with explicit documentation of semantic differences. Stale work detection (30+ minutes without heartbeat) and safe recovery (escalates to NEEDS_ATTENTION if max_attempts exceeded) preserve existing application safety gates. Work ownership is strict: only claiming worker can heartbeat/release/complete/fail. 49 focused coordination tests passing; 475 total backend tests (previously 426, +49 coordination). No regression in existing AI queue, application runner, duplicate detection, or safety gates. Frontend unchanged.

Phase 8.5A Checkpoint is complete: Worker Foundation and Registration. Persistent worker identity layer introduced to support future cloud browser coordination without modifying current Naukri execution. WorkerType (LOCAL_WINDOWS, CLOUD_BROWSER) and WorkerStatus (STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR) enums defined. Worker model persists identity, type, status, runtime environment, and lifecycle timestamps. WorkerService provides registration (safely repeatable), retrieval, listing, and status updates. Minimal worker API endpoints: GET /api/worker/status (list), POST /api/worker/register (register), GET /api/worker/{worker_id} (get). 12 focused tests; 426 total tests passing. No changes to existing scheduler, Playwright, or NaukriAdapter.

Phase 8.4.1 Checkpoint is complete: Responsive Mobile Naukri-Inspired UX. The frontend is now fully responsive across mobile (320px-480px), tablet (768px-1024px), and desktop (1024px+) viewports. Mobile experience features a compact header with hamburger menu, sidebar drawer, and bottom navigation bar inspired by Naukri mobile app patterns. All touch targets are minimum ~44x44px. Desktop layout and functionality are preserved. No backend changes. Build passes; no TypeScript errors.

Phase 8.4 Checkpoint is complete: Vercel frontend preparation. All frontend API calls use a single public `VITE_API_BASE_URL` configuration, and the existing Vercel configuration builds the `frontend` Vite app. No Vercel deployment has been performed.

Phase 8.3 Checkpoint is complete: hosted FastAPI deployment preparation. The repository includes Render and Procfile service definitions, explicit production configuration validation, secure structured logs, and environment-driven CORS/frontend API configuration. This is preparation only; no service has been deployed.

Phase 8.2 Checkpoint is complete: PostgreSQL + Production Persistence. Backend seamlessly hosts configurations for SQLite and scaling instances with PostgreSQL `psycopg` integration and connection pooling metrics.

Phase 8.1 Checkpoint is complete: Production Backend Preparation. 414 tests passing. Backend is production-hosting ready with enhanced configuration, security, and monitoring.

Phase 7 Checkpoint 4 is complete: Agent intelligence, decision quality, job prioritization, feedback/learning, and application analytics.

Frontend UX/UI Redesign Checkpoint is complete: Professional SaaS dashboard design with modern UI/UX, improved accessibility, and responsive layout.

Frontend Codebase Structure Verification is complete: Production-ready React 19.1.0 + TypeScript 5.8.3 + Vite 6.3.5 + Tailwind CSS 4.1.4 stack with clean component architecture and stable build pipeline.


## Stack

Python 3.12+, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite, Tailwind CSS, pytest, Playwright, Gemini, and PyMuPDF.

## Layout

`backend/` contains the FastAPI API, core services, schemas, database, and tests. `frontend/` contains the React dashboard shell. `docs/` contains the product and continuity documentation. `data/` contains ignored local runtime data.

## Prerequisites

- Python 3.12+
- Node.js 20+

## Backend Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

The backend runs at `http://127.0.0.1:8000`; health is at `http://127.0.0.1:8000/api/health`.

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

The dashboard runs at `http://127.0.0.1:5173` and reads the backend health endpoint.

## Tests

```powershell
python -m pytest backend/tests
```

## Current Limitations

Phase 8.3 prepares only the hosted FastAPI API. Cloud browser execution, object storage, database provisioning, frontend deployment, and platform automation remain out of scope.

## Hosted FastAPI Deployment (Phase 8.3)

Run the API on a hosting platform with:

```text
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

`Procfile` provides a local-port fallback and `render.yaml` describes an equivalent Render web service. Set these host environment variables; do not commit their values:

- `NAUKRI_AGENT_APP_ENV=production`
- `NAUKRI_AGENT_DATABASE_URL` — external PostgreSQL URL
- `NAUKRI_AGENT_GEMINI_API_KEY`
- `NAUKRI_AGENT_FRONTEND_ORIGINS` — one or more comma-separated frontend origins

Production readiness rejects SQLite, a missing Gemini key, missing origins, and wildcard origins. `GET /api/health` is process-only and does not query the database or Gemini; `GET /api/readiness` reports whether database, configuration, storage, AI configuration, and runtime are ready. CORS allows only configured production origins and deliberately disables credentialed browser requests. `SafeJsonFormatter` recursively redacts credentials, API keys, authorization headers, cookies, sessions, nested values, and database URL userinfo.

## Vercel Frontend Preparation (Phase 8.4)

The root `vercel.json` installs, builds, and publishes the Vite app in `frontend/` (`npm --prefix frontend ci`, `npm --prefix frontend run build`, and `frontend/dist`). Set `VITE_API_BASE_URL` in Vercel to the public HTTPS FastAPI origin, for example `https://your-api-host.example`; the client normalizes it to `/api`. Locally, omit the variable to use `http://127.0.0.1:8000`.

`VITE_` values are public browser configuration. Never put Gemini keys, database URLs with credentials, Naukri credentials, cookies, sessions, or private tokens in them. Configure the deployed Vercel origin separately in `NAUKRI_AGENT_FRONTEND_ORIGINS` on the backend. The dashboard uses in-page state and hash links, not browser-path routing, so no SPA rewrite was added. API failures use safe user-facing messages and a request timeout; raw backend error details are not displayed.

## Production Readiness (Phase 8.1)

The backend has been prepared for production hosting with enhanced configuration, security, and monitoring:

- **Production Configuration**: Environment separation (LOCAL_WINDOWS/CLOUD), production detection, configurable CORS origins
- **CORS Configuration**: Production-safe with configurable multiple origins via FRONTEND_ORIGINS
- **Health/Readiness Endpoints**: Separate liveness (/api/health) and readiness (/api/readiness) endpoints for container orchestration
- **Error Handling**: Catch-all exception handler prevents sensitive information exposure
- **Logging**: Production-safe logging with automatic sensitive information redaction (api_key, password, token, secret, credential, auth)
- **Database Configuration**: Supports both SQLite (default) and PostgreSQL via DATABASE_URL
- **Storage Configuration**: StorageService abstraction ready for future object storage integration
- **Browser/API Separation**: API process does NOT auto-start Playwright browser; clear separation for future cloud architecture
- **Frontend Configuration**: Environment-based backend URL via VITE_API_BASE_URL (development: localhost, production: configurable)
- **Security**: No wildcard CORS in production, no stack traces in errors, no secrets in logs or API responses

## Cloud Readiness

The application includes cloud readiness infrastructure to support future cloud deployment while maintaining local-first V1 operation:

- **RuntimeContext**: Environment detection and behavior abstraction (LOCAL_WINDOWS for V1, CLOUD_READY for future)
- **StorageService**: File operations abstraction enabling future object storage (S3/Azure/GCS)
- **Environment configuration**: All settings use `NAUKRI_AGENT_` prefix for clean cloud deployment
- **Database flexibility**: Supports both SQLite (V1) and PostgreSQL (future)
- **No business logic changes**: V1 functionality unchanged; abstractions enable future cloud without code changes

Future cloud deployment will require: remote browser automation, object storage integration, PostgreSQL deployment, and cloud infrastructure setup.

## Profile Setup

Set `NAUKRI_AGENT_GEMINI_API_KEY` in a local `.env`, start the backend and frontend, then open the Profile section. Upload a PDF no larger than 10 MB, review the extracted facts, save any edits, and explicitly confirm the profile. A resume is not usable by future automation until it is confirmed.

The Phase 2 backend tests pass. In this environment the frontend build is currently blocked by a malformed native Vite dependency tree; remove `frontend/node_modules` and reinstall dependencies once Windows releases that generated directory.

## Development Phases

The formal product roadmap is defined by `docs/MASTER_PRD.md`.

1. Foundation and architecture - complete
2. Resume and user profile - complete
3. Gemini AI engine - complete
4. Matching and rules engine - complete
5. Naukri job discovery - complete
6. Naukri application automation - implementation complete; live native form-boundary validation remains unresolved
7. Scheduler and continuous agent - complete
8. Dashboard - complete
9. Notifications - implemented offline; SMTP delivery requires configuration
10. Testing, security, and Windows packaging - pending
11. Integration and production hardening - pending

Cloud deployment preparation is documented as supporting Phase 8.x/production-readiness work; it is not a separate formal product phase in the master roadmap.

Phase 9 notifications are isolated behind `NotificationService`. The implementation persists notification history, supports critical-error, authentication-required, security-challenge, external-application, and evening-summary events, and exposes `GET /api/notifications` for the dashboard. SMTP settings use the `NAUKRI_AGENT_` environment prefix; tests use a fake sender and no real email was sent. The evening summary is evaluated in the configured timezone during the configured 8 PM hour with daily deduplication. Live SMTP delivery remains unverified.

Note: Cloud readiness infrastructure (runtime/storage abstractions) was implemented as foundational work to support future cloud deployment without changing business logic. This is not a separate phase but enables future cloud execution. Phase 8.1 prepared the backend for production hosting without actual deployment.
