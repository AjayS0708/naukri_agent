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
