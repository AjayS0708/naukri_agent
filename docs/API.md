# API Reference

**Current implementation:** E5-R33 (`37b35ed`)  
**Base URL:** `http://127.0.0.1:8000`  
**OpenAPI UI:** `http://127.0.0.1:8000/api/docs` in development

The API is a local-first FastAPI service. It has **no built-in authentication**. Do not expose it to an untrusted network without an authenticated reverse proxy or gateway.

---

## Conventions

- All routes are under `/api`.
- JSON is used for request and response bodies, except resume upload (`multipart/form-data`).
- Job, application, and queue-item IDs are integers; worker IDs are strings.
- Timestamps are ISO 8601.
- Errors return a JSON object with `detail`; some routes return `detail` as an object with `code` and `message`, and some validation errors add `category`.
- The API uses explicit CORS origins. In development, local Vite and localhost origins are allowed.
- A second apply process receives `409 Conflict` with the active run identity.

Common status codes:

| Code | Meaning |
|---|---|
| `200` | Success |
| `201` | Created where applicable |
| `400` | Invalid request or business rule violation |
| `404` | Resource not found |
| `409` | Conflict, stale state, or another run holds the lock |
| `422` | Request validation failed |
| `500` | Internal error |

---

## Health and readiness

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness and basic agent state. |
| `GET` | `/api/readiness` | Database, schema, storage, AI provider, and runtime readiness. |

---

## AI provider

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/ai/status` | Gemini provider status and configuration summary. |

---

## Profile

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/profile/resume` | Upload a PDF resume; extract and validate profile facts. |
| `GET` | `/api/profile` | Get the current profile, status, and resume metadata. |
| `PUT` | `/api/profile` | Replace editable profile data. |
| `POST` | `/api/profile/confirm` | Confirm the reviewed profile for automation. |

Resume upload constraints: PDF only, maximum 10 MB, minimum extracted text length 80 characters.

---

## Preferences and matching

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/matching/preferences` | Get job-search preferences. |
| `PUT` | `/api/matching/preferences` | Update preferences. |
| `POST` | `/api/matching/evaluate` | Deterministically evaluate a supplied job. |

---

## Decision

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/decision/evaluate/{job_id}` | Evaluate a stored job and persist the decision. |
| `GET` | `/api/decision/history/{job_id}` | Decision history for a job. |
| `POST` | `/api/decision/prioritize` | Prioritize a supplied set of jobs. |

---

## Discovery

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/discovery/start` | Start a discovery run. |
| `GET` | `/api/discovery/status` | Current discovery state and last-run summary. |
| `POST` | `/api/discovery/stop` | Request discovery cancellation. |

---

## Autonomous cycle

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/autonomous-cycle/run` | Start the autonomous cycle. |
| `POST` | `/api/autonomous-cycle/stop` | Request cancellation; idempotent. |
| `GET` | `/api/autonomous-cycle/status` | Active state, lock state, active run, and last run. |
| `GET` | `/api/autonomous-cycle/pending-question` | Get the screening question the active run is waiting on. |
| `POST` | `/api/autonomous-cycle/answer-question` | Answer or skip the pending screening question. |
| `GET` | `/api/autonomous-cycle/screening-answers` | List saved screening answers. |
| `PUT` | `/api/autonomous-cycle/screening-answers/{answer_id}` | Update a saved answer. |
| `DELETE` | `/api/autonomous-cycle/screening-answers/{answer_id}` | Delete a saved answer. |

`POST /api/autonomous-cycle/run` accepts an optional `max_applications` field for compatibility. It is ignored; runs process all eligible candidates.

`POST /api/autonomous-cycle/stop` accepts an optional `run_token`. When supplied, it stops the active run only if the token matches.

Screening answer errors include:

- `PENDING_QUESTION_NOT_FOUND`
- `PENDING_QUESTION_NOT_WAITING`
- `PENDING_QUESTION_STALE`
- `ANSWER_REQUIRED`
- `INVALID_OPTION`
- `SENSITIVE_QUESTION`
- `MEMORY_SAVE_REFUSED`
- `INVALID_SCOPE`

---

## Manual apply

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/manual-apply/eligible` | List stored jobs with eligibility verdicts. |
| `POST` | `/api/manual-apply/start` | Start a manual batch over selected job IDs. |
| `GET` | `/api/manual-apply/status` | Live manual batch status and last manual summary. |
| `POST` | `/api/manual-apply/stop` | Request cancellation at a safe boundary. |
| `POST` | `/api/manual-apply/skip` | Skip one job immediately or queue a skip for the live batch. |

Eligibility listing query parameters:

- `limit` (default 200)
- `offset` (default 0)
- `only_eligible` (default false)
- `q` (case-insensitive title/company search)

Manual start body:

```json
{
  "job_ids": [101, 102, 103],
  "dry_run": false
}
```

Skip body:

```json
{
  "job_id": 101
}
```

Skip responses use a `mode` of `RECORDED`, `QUEUED`, `ALREADY_SKIPPED`, `ALREADY_PROCESSED`, or `NOT_ELIGIBLE`.

---

## Applications

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/applications/history` | List application history. |
| `GET` | `/api/applications/job/{job_id}` | Get the application record for a job. |
| `GET` | `/api/applications/{application_id}` | Get one application. |
| `PUT` | `/api/applications/{application_id}` | Update an application record. |
| `POST` | `/api/applications/run` | Run the application workflow for a job. |
| `POST` | `/api/applications/start` | Start an application attempt. |
| `POST` | `/api/applications/stop` | Request application cancellation. |
| `POST` | `/api/applications/reconcile-history` | Reconcile local records against Naukri history. |
| `POST` | `/api/applications/reconcile-stale-externals` | Reconcile known false external classifications. |

Reconciliation endpoints are operator-triggered. They do not submit applications.

---

## Dashboard

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/dashboard/summary` | Profile, discovery, application, and attention counts. |
| `GET` | `/api/dashboard/jobs` | Paginated job list with application state. |
| `GET` | `/api/dashboard/applications` | Paginated application list. |
| `GET` | `/api/dashboard/recent-applications` | Recent applications for the overview. |
| `GET` | `/api/dashboard/needs-attention` | Unresolved attempts requiring review. |

Dashboard schemas explicitly enumerate fields. Sensitive profile data and secrets are not returned.

---

## AI queue

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/ai-queue/enqueue` | Add a job to the AI queue. |
| `GET` | `/api/ai-queue/items` | List queue items. |
| `GET` | `/api/ai-queue/next` | Get the next claimable item. |
| `GET` | `/api/ai-queue/status` | Counts by status and next item. |
| `POST` | `/api/ai-queue/{item_id}/process` | Process an item with Gemini. |
| `POST` | `/api/ai-queue/{item_id}/mark-processing` | Mark an item as processing. |
| `POST` | `/api/ai-queue/{item_id}/mark-completed` | Mark an item completed. |
| `POST` | `/api/ai-queue/{item_id}/mark-retry-pending` | Mark an item for retry. |
| `POST` | `/api/ai-queue/{item_id}/mark-quota-blocked` | Mark an item blocked by quota. |
| `POST` | `/api/ai-queue/{item_id}/mark-needs-attention` | Escalate an item for review. |
| `POST` | `/api/ai-queue/{item_id}/mark-failed` | Mark an item failed. |
| `POST` | `/api/ai-queue/recover-stale` | Recover stale processing items. |

Queue statuses: `QUEUED`, `PROCESSING`, `COMPLETED`, `RETRY_PENDING`, `QUOTA_BLOCKED`, `NEEDS_ATTENTION`, `FAILED`.

---

## Scheduler

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/scheduler/status` | Scheduler state, interval, last run, next run. |
| `PUT` | `/api/scheduler/config` | Update enabled state and interval. |
| `POST` | `/api/scheduler/start` | Start the scheduler. |
| `POST` | `/api/scheduler/stop` | Stop the scheduler. |
| `POST` | `/api/scheduler/pause` | Pause scheduling. |
| `POST` | `/api/scheduler/resume` | Resume scheduling. |
| `POST` | `/api/scheduler/run-cycle` | Trigger one scheduler cycle manually. |

The scheduler shares the singleton apply lock. It does not auto-start on application startup.

---

## Agent lifecycle

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/agent/status` | Agent, scheduler, and AI queue status. |
| `POST` | `/api/agent/start` | Start the agent after prerequisite checks. |
| `POST` | `/api/agent/stop` | Stop the agent. |
| `POST` | `/api/agent/pause` | Pause the agent. |
| `POST` | `/api/agent/resume` | Resume a paused agent. |
| `POST` | `/api/agent/recovery` | Run startup-style recovery. |

---

## Analytics

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/analytics/summary` | Overall outcome summary. |
| `GET` | `/api/analytics/applications-by-day` | Application counts by day. |
| `GET` | `/api/analytics/applications-by-profile` | Application counts by profile. |
| `GET` | `/api/analytics/decision-breakdown` | Decision category breakdown. |
| `GET` | `/api/analytics/primary-reasons` | Primary decision reasons. |
| `GET` | `/api/analytics/skip-reasons` | Skip reason breakdown. |
| `GET` | `/api/analytics/recent-decisions` | Recent decision records. |
| `GET` | `/api/analytics/feedback-summary` | Feedback summary. |

Analytics are computed from stored records. They are not estimated.

---

## Feedback

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/feedback/submit` | Submit feedback for a job. |
| `GET` | `/api/feedback/job/{job_id}` | Feedback for a job. |
| `GET` | `/api/feedback/summary` | Feedback summary. |
| `DELETE` | `/api/feedback/{feedback_id}` | Delete feedback. |

---

## Notifications

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/notifications` | List persisted notifications. |

Notification delivery may use SMTP when configured. Delivery failure does not change application state.

---

## Worker coordination

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/worker/register` | Register a worker. |
| `GET` | `/api/worker/status` | Worker status summary. |
| `GET` | `/api/worker/{worker_id}` | Get one worker. |

Worker coordination is for AI queue ownership and heartbeats. It does not provide a cloud browser.

---

## System

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/system/autostart` | Read Windows autostart configuration. |
| `POST` | `/api/system/autostart/enable` | Enable Windows autostart. |
| `POST` | `/api/system/autostart/disable` | Disable Windows autostart. |

Enabling autostart does not auto-start an application run; the agent still starts in `IDLE`.

---

## Endpoint summary

- 83 paths
- 87 HTTP operations
- 18 route groups

The live OpenAPI document is authoritative for request and response schemas. This page is a grouped reference for operators and maintainers.

---

## Related documents

- [README](../README.md)
- [Architecture](ARCHITECTURE.md)
- [Development status](DEVELOPMENT_STATUS.md)
- [Product requirements](MASTER_PRD.md)
