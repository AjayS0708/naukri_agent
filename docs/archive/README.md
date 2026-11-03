# Historical Documentation Archive

This directory contains snapshots of project documentation through **E5-R23**. They are retained for evidence, auditability, and design history.

**These files are not current documentation.** They describe earlier states, including open defects and unverified live behavior that have since been addressed. Use the current documents for operator and developer guidance.

## Current documents

- [README](../../README.md)
- [Architecture](../ARCHITECTURE.md)
- [API reference](../API.md)
- [Architecture decisions](../DECISIONS.md)
- [Development status](../DEVELOPMENT_STATUS.md)
- [Product requirements](../MASTER_PRD.md)
- [Future roadmap](../FUTURE_IMPLEMENTATION_ROADMAP.md)

## Archived snapshots

| File | Original document | Snapshot point |
|---|---|---|
| `ARCHITECTURE_THROUGH_E5_R23.md` | `docs/ARCHITECTURE.md` | Through E5-R23, 2026-10-13 |
| `DEVELOPMENT_STATUS_THROUGH_E5_R23.md` | `docs/DEVELOPMENT_STATUS.md` | Through E5-R23, 2026-10-13 |
| `MASTER_PRD_THROUGH_E5_R23.md` | `docs/MASTER_PRD.md` | Through E5-R23, 2026-10-13 |
| `FUTURE_ROADMAP_THROUGH_E5_R23.md` | `docs/FUTURE_IMPLEMENTATION_ROADMAP.md` | Through E5-R23, 2026-10-13 |

## Phase validation records

The Phase 9 validation records remain in `docs/` because they are referenced as historical evidence:

- [`PHASE_9_AUDIT.md`](../PHASE_9_AUDIT.md)
- [`PHASE_9B1_LIVE_NAUKRI_VALIDATION.md`](../PHASE_9B1_LIVE_NAUKRI_VALIDATION.md)
- [`PHASE_9B2A_APPLICATION_SURFACE_VALIDATION.md`](../PHASE_9B2A_APPLICATION_SURFACE_VALIDATION.md)
- [`PHASE_9B2B_DRY_RUN_VALIDATION.md`](../PHASE_9B2B_DRY_RUN_VALIDATION.md)
- [`PHASE_9B2B_LIVE_DRY_RUN_VALIDATION.md`](../PHASE_9B2B_LIVE_DRY_RUN_VALIDATION.md)

These files describe the system as it existed during Phase 9. They are not current behavior specifications.

## Why archive rather than delete

The checkpoint record contains:

- Root-cause evidence for past defects.
- Live-validation observations that cannot be reconstructed offline.
- Decision context for current safety boundaries.
- Audit trails for application records and test counts.

Deleting it would lose evidence. Treating it as current would mislead. Archiving preserves both the record and the distinction.

## How to use these files

- For current setup and operation, start with the [README](../../README.md).
- For current behavior, use [ARCHITECTURE.md](../ARCHITECTURE.md) and [DEVELOPMENT_STATUS.md](../DEVELOPMENT_STATUS.md).
- For why a safety rule exists, use [DECISIONS.md](../DECISIONS.md).
- For historical evidence, read the archived snapshot with its date and status in mind.
