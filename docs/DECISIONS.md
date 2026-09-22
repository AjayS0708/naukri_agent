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
