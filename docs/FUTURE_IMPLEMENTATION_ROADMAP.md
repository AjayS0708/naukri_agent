# Future Implementation Roadmap

- **Current implementation:** E5-R33 (`37b35ed`)
- **Last updated:** 2026-11-01

This is a planning document. Nothing here is implemented unless explicitly marked. Historical roadmap material through E5-R23 is preserved in [`docs/archive/FUTURE_ROADMAP_THROUGH_E5_R23.md`](archive/FUTURE_ROADMAP_THROUGH_E5_R23.md).

---

## 1. Planning principles

1. Keep deterministic safety rules authoritative.
2. Verify one change at a time.
3. Never combine unrelated features in one checkpoint.
4. Keep live automation explicit and operator-controlled.
5. Prefer truthful `NEEDS_ATTENTION` over optimistic retries.
6. Never bypass CAPTCHA or security controls.
7. Never submit external applications.
8. Preserve application history and user skips.
9. Keep AI advisory.
10. Do not claim live success without a live verification run.

---

## 2. Current baseline

Implemented through E5-R33:

- Discovery with multi-location search, pagination, freshness, deduplication, and mode classification.
- Shared relevance and deterministic hard filters.
- Persistent AI queue with quota, retry, and attention states.
- Native application runner with evidence-based outcomes.
- Conversational and legacy form handling.
- Shared multi-job browser session with bounded restart recovery.
- Human-in-the-loop screening with scoped answer memory.
- Application-history and user-skip protection.
- DB-backed singleton apply lock.
- Manual apply queue with per-job skip.
- Dashboard with overview, jobs, apply, applications, attention, AI queue, analytics, activity, notifications, profile, and preferences.
- 1,438 passing backend tests and a passing frontend production build.

The current revision is offline-verified. A fresh live multi-job acceptance run is not claimed.

---

## 3. Priority 1: live acceptance and reliability

### 3.1 Fresh multi-job live acceptance

**Goal:** one dashboard-initiated run completes at least two native applications in a single cycle with no manual intervention.

**Why:** the broader product acceptance criterion is not re-verified in the current revision.

**Scope:**

- Use an isolated, controlled run.
- Capture discovery, filter, AI, and application stats.
- Verify every outcome has evidence or an honest attention state.
- Confirm protected jobs are untouched.
- Confirm no external submission occurs.

**Exit criteria:**

- At least two native applications in one run.
- Zero false-positive `APPLIED` records.
- Zero external submissions.
- All remaining outcomes explainable.
- Dashboard reflects the same terminal state as the database.

### 3.2 Selector resilience

**Goal:** reduce breakage from Naukri DOM changes.

**Scope:**

- Expand offline DOM regression fixtures.
- Add selector-health diagnostics without live mutation.
- Prefer semantic and text-scoped selectors over hashed classes.
- Surface selector failures as explicit attention reasons.

**Exit criteria:**

- Adapter tests cover each critical selector family.
- A selector miss never produces a false success.

### 3.3 Session and recovery hardening

**Goal:** make long batches more predictable.

**Scope:**

- Improve session-loss classification.
- Add clearer restart telemetry.
- Verify stop and skip behavior across restart boundaries.
- Keep the three-restart cap.

**Exit criteria:**

- No unbounded restart loop.
- Session loss during an attempt remains non-retryable.
- Remaining jobs are accounted for after any stop.

### 3.4 Screening memory quality

**Goal:** reduce unnecessary human interruptions without weakening safety.

**Scope:**

- Improve employer/job scope matching.
- Improve stale-answer detection.
- Expand tests for context-sensitive answers.
- Keep sensitive questions blocked.

**Exit criteria:**

- No sensitive answer is stored.
- No scope widens without explicit authorization.
- Stale answers are never reused.

---

## 4. Priority 2: security and operations

### 4.1 Authentication and access control

**Goal:** make public or shared deployment safe.

**Scope:**

- Add authentication at the API boundary.
- Add role or operator identity where needed.
- Protect all mutating routes.
- Keep CORS explicit.
- Add audit logging for operator actions.

**Exit criteria:**

- Unauthenticated requests are rejected.
- Browser automation cannot be started by an unauthorized caller.
- No secret is exposed to the frontend.

### 4.2 Deployment hardening

**Goal:** make hosted API operation reproducible.

**Scope:**

- Document PostgreSQL migration and backup procedures.
- Add readiness and liveness checks for deployment platforms.
- Define safe log retention.
- Document the split between hosted API and local browser worker.
- Add a supported worker-to-API communication model if remote execution is pursued.

**Exit criteria:**

- A production deployment can be configured without editing source.
- Readiness reports actionable errors.
- Secrets are supplied only through environment configuration.

### 4.3 Observability

**Goal:** make failures diagnosable without database spelunking.

**Scope:**

- Structured run diagnostics.
- Stable reason codes for skips and attention.
- Correlation IDs across API, cycle, queue, and runner logs.
- Operator-facing export of a run summary.

**Exit criteria:**

- Every terminal outcome has a reason and a correlation path.
- A failed run can be diagnosed from logs and the dashboard.

---

## 5. Priority 3: product expansion

### 5.1 Answer engine

**Goal:** expand structured, profile-grounded answer coverage.

**Scope:**

- More question families.
- Better profile evidence selection.
- Confidence and verification metadata.
- Human review for low-confidence or consequential answers.

**Exit criteria:**

- Answers are traceable to profile facts or explicit user input.
- Sensitive and consequential questions still require review.

### 5.2 Notifications and summaries

**Goal:** make asynchronous operation useful.

**Scope:**

- Verify SMTP delivery end to end.
- Add run-completion and attention summaries.
- Add deduplication and timezone handling tests.

**Exit criteria:**

- A completed run produces a truthful summary.
- Delivery failure does not affect application state.

### 5.3 Cloud browser worker

**Goal:** decouple the API from the Windows browser host.

**Scope:**

- Define a worker protocol.
- Keep the singleton apply lock authoritative.
- Keep the persistent profile on the worker.
- Add remote health and ownership checks.

**Exit criteria:**

- Only one worker can own the browser.
- The API never assumes a remote application succeeded without evidence.

This is a larger architectural change and should not be started until live local acceptance is stable.

### 5.4 Additional job platforms

**Goal:** support platforms beyond Naukri.

**Scope:**

- Introduce a platform adapter boundary.
- Keep platform-specific classification and submission logic isolated.
- Reuse the shared candidate, protection, and outcome model.

**Exit criteria:**

- A new platform cannot bypass shared safety rules.
- External application behavior remains platform-specific and non-submitting unless explicitly supported.

This is explicitly outside V1.

---

## 6. Explicitly deferred

- Automatic resolution of `NEEDS_ATTENTION`.
- CAPTCHA solving or bypass.
- Unbounded application volume.
- Multi-tenant SaaS.
- Recruiter automation.
- Automatic external application submission.
- Silent scope widening for answer memory.
- AI-only approval of applications.

---

## 7. Suggested checkpoint sequence

| Order | Checkpoint | Outcome |
|---|---|---|
| 1 | Live multi-job acceptance | Re-verify the core product claim. |
| 2 | Selector resilience | Reduce live DOM risk. |
| 3 | Session/recovery telemetry | Make long batches diagnosable. |
| 4 | Screening memory quality | Reduce interruptions safely. |
| 5 | Authentication | Enable safe shared deployment. |
| 6 | Deployment hardening | Reproducible hosted operation. |
| 7 | Observability | Faster diagnosis and audit. |
| 8 | Answer engine | Broader grounded coverage. |
| 9 | Notifications | Useful asynchronous operation. |
| 10 | Cloud browser worker | Decouple API from browser host. |
| 11 | Additional platforms | Expand beyond Naukri. |

Each checkpoint should have its own tests, documentation update, and explicit acceptance criteria.

---

## 8. Roadmap status rule

A roadmap item is complete only when:

- The implementation is merged or present in the working tree.
- Tests cover the behavior.
- Documentation describes the current behavior.
- Any required live verification has actually been performed.

Until then, the item remains planned.

---

## 9. Related documents

- [README](../README.md)
- [Architecture](ARCHITECTURE.md)
- [API reference](API.md)
- [Architecture decisions](DECISIONS.md)
- [Development status](DEVELOPMENT_STATUS.md)
- [Product requirements](MASTER_PRD.md)
- [Historical roadmap through E5-R23](archive/FUTURE_ROADMAP_THROUGH_E5_R23.md)
