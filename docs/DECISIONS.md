# Architecture Decisions

| Decision | Rationale |
| --- | --- |
| Python + FastAPI | Typed, lightweight local API with strong validation support. |
| React + TypeScript + Tailwind | Product-ready dashboard foundation with typed frontend contracts. |
| SQLite + SQLAlchemy | Simple local V1 storage while retaining a route to PostgreSQL. |
| Playwright later | The PRD selects Playwright, but platform interaction is deferred to Phase 5. |
| AI provider abstraction | Keeps Gemini-specific code isolated and prevents provider code from controlling execution. |
| Platform adapter abstraction | Keeps Naukri-specific behavior out of matching, rules, and applications. |
| Local-first | V1 runs on the user's Windows machine and does not claim cloud execution. |
| No Naukri automation in Phase 1 | The safety-oriented architecture is established before any platform interaction. |
| SHA-256 resume storage names | Avoids trusting user filenames, supports duplicate detection, and prevents path traversal. |
| JSON profile payload with typed Pydantic contract | Keeps the initial local SQLite schema small while enforcing structured, portable profile data. |
| Narrow Gemini profile extraction | Gemini receives only normalized resume text and must return schema-validated, source-grounded facts; it has no browser capability. |
| Reconfirmation after edits | Editing a profile clears confirmation so future automation can only rely on explicitly approved facts. |
| Clean NPM Installation (Phase 3) | Resolves Vite 8 / Rolldown native binding issues blocking the frontend on Windows environments. |
| `google-genai` SDK for Gemini | Prioritized over LangChain for minimal, type-safe, and native `response_schema` bounds. |
| Integrated AI Database Tracking | Enforces AI usage awareness by recording requests, caching outcomes, and managing model configurations directly in SQLite to preserve request quota limits. |
| Runtime and Storage Abstractions | Cloud readiness infrastructure implemented before actual cloud deployment. RuntimeContext and StorageService provide clean interfaces for environment-specific behavior and file operations, enabling future cloud/24×7 execution without changing business logic. V1 continues to run in LOCAL_WINDOWS mode; future cloud deployment will use CLOUD_READY mode with object storage and PostgreSQL. |
| Environment Variable Prefix | All configuration uses `NAUKRI_AGENT_` prefix for consistency and to prevent conflicts with other environment variables. This enables clean cloud deployment via environment configuration. |
| Path Resolution Properties | Storage paths changed from Path fields to string fields with property resolution. This supports both relative and absolute paths and enables future cloud path configuration without code changes. |
| Database URL Flexibility | Database configuration supports both SQLite and PostgreSQL via `DATABASE_URL`. This enables future PostgreSQL migration without code changes while maintaining SQLite for V1. |
| Singleton Pattern for Abstractions | RuntimeContext and StorageService use singleton pattern with global getter functions. This ensures consistent behavior across the application and simplifies testing. |
| No Business Logic Changes | Cloud readiness infrastructure is purely foundational - no changes to existing business logic, public APIs, or V1 functionality. All existing tests pass without modification. |
| Decision Quality Model | Structured decision quality assessment with priority levels (HARD_REJECT, SKIP, LOW_PRIORITY, NORMAL_PRIORITY, HIGH_PRIORITY, NEEDS_ATTENTION) and explainable reason codes. Hard filters remain authoritative; AI recommendations are advisory only. |
| Explainable Decisions | Every decision includes structured reason codes, concise explanations, signal breakdown, and priority level. Decision quality is deterministic and reproducible for the same inputs. |
| Job Prioritization | Jobs are prioritized before application processing using deterministic scoring based on role relevance, skill relevance, experience compatibility, location match, salary suitability, job quality, freshness, duplicate probability, and historical feedback. Hard-filtered jobs never become higher priority. |
| Feedback-Learning Boundaries | Explicit user feedback influences ranking/prioritization only. Learning cannot modify hard filters, change user preferences, remove duplicate protection, or bypass safety gates. User-controlled preferences remain authoritative. |
| Analytics from Existing Data | Application analytics use existing Job, Application, DecisionQualityRecord, and JobFeedback data without creating fake historical data. All metrics are derived from actual system activity. |
| Modern Frontend Architecture | React 19.1.0 + TypeScript 5.8.3 + Vite 6.3.5 + Tailwind CSS 4.1.4 stack with production-ready build pipeline, reusable state components, and clean component architecture for SaaS dashboard experience. |
| Production-Ready Frontend | Frontend codebase verified for production readiness with TypeScript compilation passing, stable build pipeline (17.59s build time), modern React patterns, and minimal dependency footprint. |
| Production Configuration Separation | Environment separation (LOCAL_WINDOWS/CLOUD) enables production hosting while preserving local-first V1 behavior. Configuration is environment-variable driven with NAUKRI_AGENT_ prefix. |
| Production-Safe CORS | CORS configuration uses configurable origins via FRONTEND_ORIGINS. Development mode allows localhost for convenience; production mode uses only configured origins. No wildcard origins in production. |
| Separate Health/Readiness Endpoints | Liveness endpoint (/api/health) for simple process status. Readiness endpoint (/api/readiness) for detailed component status (database, configuration, storage, AI provider, runtime environment). Ready for container orchestration. |
| Production-Safe Error Handling | Catch-all exception handler prevents sensitive information exposure. Generic exceptions return safe error messages without stack traces. No filesystem paths, environment variables, or secrets in API responses. |
| Production-Safe Logging | SafeJsonFormatter automatically redacts sensitive information (api_key, password, token, secret, credential, auth). Production mode uses SafeJsonFormatter; development mode uses standard JsonFormatter for debugging. |
| Browser/API Separation | API process does NOT auto-start Playwright browser. Browser only starts when explicitly called via DiscoveryService. Clear separation for future cloud architecture with separate browser worker. |
| Frontend Environment Configuration | Frontend API URL configured via VITE_API_BASE_URL environment variable. Development: http://127.0.0.1:8000/api (default). Production: https://<hosted-api>/api (configurable). No hardcoded localhost in production code. |
