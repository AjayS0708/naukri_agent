# Naukri AI Job Application Agent

Windows-first, local-first foundation for a controlled job-application agent. Deterministic rules will remain the execution authority; AI and browser automation are intentionally not implemented in Phase 1.

## Status

Phase 1 is complete: FastAPI backend, SQLite/SQLAlchemy foundation, React/TypeScript/Tailwind dashboard shell, typed architecture boundaries, and backend tests.

## Stack

Python 3.12+, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite, Tailwind CSS, and pytest. Later phases add Gemini, Playwright, APScheduler, and PyMuPDF.

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

There is no Naukri login, browsing, discovery, job analysis, scheduling, or application submission. Gemini is limited to source-grounded profile extraction; the complete AI engine belongs to Phase 3. The dashboard contains no controls for unimplemented automation.

## Profile Setup

Set `GEMINI_API_KEY` in a local `.env`, start the backend and frontend, then open the Profile section. Upload a PDF no larger than 10 MB, review the extracted facts, save any edits, and explicitly confirm the profile. A resume is not usable by future automation until it is confirmed.

The Phase 2 backend tests pass. In this environment the frontend build is currently blocked by a malformed native Vite dependency tree; remove `frontend/node_modules` and reinstall dependencies once Windows releases that generated directory.

## Development Phases

1. Foundation and architecture - complete
2. Resume and user profile
3. Gemini AI engine
4. Matching and rules engine
5. Naukri job discovery
6. Naukri-native application automation
7. Scheduler and continuous agent
8. Dashboard expansion
9. Notifications
10. Testing, security, and Windows packaging
11. Integration and production hardening
