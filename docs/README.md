# Documentation

Current documentation for the Naukri AI Job Application Agent.

**Implementation:** E5-R33 (`37b35ed`)  
**Verified:** 2026-11-01

## Start here

| Document | Use it for |
|---|---|
| [README](../README.md) | Setup, quick start, UI overview, configuration, testing, deployment. |
| [Architecture](ARCHITECTURE.md) | Components, run lifecycles, candidate pipeline, locks, session recovery, data model. |
| [API reference](API.md) | All HTTP route groups and endpoint behavior. |
| [Development status](DEVELOPMENT_STATUS.md) | What is implemented, what was verified, recent checkpoints, known risks. |
| [Product requirements](MASTER_PRD.md) | Product goals, requirements, safety rules, acceptance criteria. |
| [Architecture decisions](DECISIONS.md) | Decision history and rationale. |
| [Future roadmap](FUTURE_IMPLEMENTATION_ROADMAP.md) | Planned work and checkpoint sequence. |

## Historical records

| Document | Use it for |
|---|---|
| [Archive index](archive/README.md) | Historical snapshots through E5-R23. |
| [Phase 9 audit](PHASE_9_AUDIT.md) | Historical end-to-end audit evidence. |
| [Phase 9B validation records](PHASE_9B1_LIVE_NAUKRI_VALIDATION.md) | Historical live and dry-run validation evidence. |

Historical files are evidence, not current operating instructions.

## Documentation rules

1. Current behavior belongs in the current documents.
2. Historical checkpoint narratives belong in the archive or the decision log.
3. A claim about live behavior must be backed by an actual live run.
4. Test counts and build results must include a date.
5. Safety boundaries must be described as implemented, not aspirational.
6. Do not document credentials, secrets, or private session data.
7. Update the relevant document when a checkpoint changes behavior.
