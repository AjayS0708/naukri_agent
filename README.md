# Naukri AI Job Application Agent

Windows-first, local-first foundation for a controlled job-application agent. Deterministic rules will remain the execution authority; AI and browser automation are intentionally not implemented in Phase 1.

## Status

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
