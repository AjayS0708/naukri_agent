# Naukri AI Job Application Agent

Windows-first, local-first foundation for a controlled job-application agent. Deterministic rules will remain the execution authority; AI and browser automation are intentionally not implemented in Phase 1.

## Status

Phase 8.2 Checkpoint is complete: PostgreSQL + Production Persistence. Backend seamlessly hosts configurations for SQLite and scaling instances with PostgreSQL `psycopg` integration and connection pooling metrics.

Phase 8.1 Checkpoint is complete: Production Backend Preparation. 401 tests passing. Backend is production-hosting ready with enhanced configuration, security, and monitoring.

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

Phase 8.1 production backend preparation is complete. Backend is production-hosting ready with enhanced configuration, security, and monitoring. Cloud execution NOT implemented (future phase). LinkedIn/Indeed NOT implemented (future phase). CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented. The dashboard includes decision analytics and feedback management, but complex automated learning and external application submission remain future features.

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

Set `GEMINI_API_KEY` in a local `.env`, start the backend and frontend, then open the Profile section. Upload a PDF no larger than 10 MB, review the extracted facts, save any edits, and explicitly confirm the profile. A resume is not usable by future automation until it is confirmed.

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
