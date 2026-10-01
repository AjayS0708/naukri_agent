# Naukri AI Job Application Agent

Windows-first, local-first foundation for a controlled job-application agent. Deterministic rules will remain the execution authority; AI and browser automation are intentionally not implemented in Phase 1.

## Status

The live diagnostic now reuses `NaukriAdapter.fetch_job_description()` before Gemini analysis, persists the fetched text in `Job.description`, and sends that actual text in the diagnostic Gemini context. This is an offline-tested diagnostic correction only; no live Naukri search was run, Gemini quota was not consumed, and Phase 9B-3 remains incomplete.

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

1. Foundation and architecture - complete
2. Resume and user profile - complete
3. Gemini AI engine - complete
4. Matching and rules engine - complete
5. Naukri job discovery - complete
6. Naukri-native application automation - complete
7. Scheduler and continuous agent - complete
8. Agent intelligence and decision quality - complete
9. Dashboard expansion - complete
10. Production backend preparation - complete
11. Cloud deployment - pending
12. Notifications - pending
13. Testing, security, and Windows packaging - pending
14. Integration and production hardening - pending

Note: Cloud readiness infrastructure (runtime/storage abstractions) was implemented as foundational work to support future cloud deployment without changing business logic. This is not a separate phase but enables future cloud execution. Phase 8.1 prepared the backend for production hosting without actual deployment.
