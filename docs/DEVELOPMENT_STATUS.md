# Development Status

- **Current implementation:** E5-R33
- **Implementation commit:** `37b35ed` — `E5-R33: redesign frontend UI and improve dashboard clarity`
- **Documentation verified:** 2026-11-01
- **Backend suite:** 1,438 passed, 0 failed, 34 warnings
- **Frontend build:** passed, 1,610 modules transformed

This is the current status document. Detailed historical checkpoint narratives through E5-R23 are preserved in [`docs/archive/DEVELOPMENT_STATUS_THROUGH_E5_R23.md`](archive/DEVELOPMENT_STATUS_THROUGH_E5_R23.md). Decisions are recorded in [DECISIONS.md](DECISIONS.md).

---

## 1. Release summary

The application is a working local-first Naukri agent with:

- A React operations console covering run control, jobs, manual apply, applications, attention, AI queue, analytics, activity, notifications, profile, and preferences.
- A FastAPI backend with 87 documented HTTP operations across 18 route groups.
- A deterministic candidate pipeline with shared relevance and protection rules.
- Bounded Gemini analysis through a persistent queue.
- A shared Playwright browser session for multi-job batches.
- Human-in-the-loop screening questions with scoped answer memory.
- DB-backed singleton locking across autonomous, manual, and scheduler apply paths.
- Session-loss recovery bounded to three restarts per batch.
- Per-job skip requests honored at safe job boundaries.
- Truthful outcome accounting with evidence-based `APPLIED` confirmation.

The system remains Naukri-only and local-first.

---

## 2. Verification performed for this revision

### Backend

```powershell
$env:NAUKRI_AGENT_BROWSER_USER_DATA_DIR = Join-Path $env:TEMP ("naukri-tests-" + [guid]::NewGuid())
.\.venv\Scripts\python.exe -m pytest backend/tests -q --disable-warnings
```

Result:

```text
1438 passed, 34 warnings in 1009.28s (0:16:49)
```

The isolated browser profile was used because a live backend and Chrome process were already holding the default `.agent/browser_session` profile. The default-profile run failed at a browser-session test for that environmental reason; the same test passed with an isolated profile, and the full isolated-profile suite passed.

### Frontend

```powershell
Set-Location frontend
npm run build
```

Result:

```text
vite v6.4.3
1610 modules transformed
dist/index.html                 0.41 kB
dist/assets/index-*.css        51.24 kB
dist/assets/index-*.js        349.79 kB
built in 34.25s
```

### Documentation verification boundaries

- No live Naukri discovery, application, or submission was performed during this documentation revision.
- No application database records were modified.
- No backend service was restarted.
- No credentials were read or exposed.
- Historical live evidence is summarized from the repository record; it is not re-verified here.

---

## 3. Implemented capabilities

### 3.1 Profile and preferences

- PDF resume upload with size and text-length validation.
- Text extraction through PyMuPDF.
- Structured profile extraction through Gemini.
- Review, edit, and explicit confirmation.
- Resume deduplication by hash.
- Profile status lifecycle: `EMPTY`, `RESUME_UPLOADED`, `EXTRACTING`, `REVIEW_REQUIRED`, `CONFIRMED`, `ERROR`.
- Preferences for target titles, locations, employment types, experience, salary floor, aggressiveness, IT industry allowlist, and IT keyword list.

### 3.2 Discovery

- Multiple configured locations and target search groups.
- Pagination.
- Freshness-first ordering with grounded posted dates.
- Canonical-URL deduplication.
- Application-mode classification: native, external, ambiguous.
- Bounded mode backfills.
- Per-search progress reporting.
- Relevance pre-check before expensive lookups.
- Expired-listing detection.

### 3.3 Matching and eligibility

- Shared relevance gate across discovery, matching, final safety gate, and manual apply.
- Target-role families and title scope.
- Unwanted specialization and responsibility exclusions.
- IT-scope structural checks.
- Experience, location, employment type, and salary rules.
- Salary parsing with honest handling of unknown values.
- Shared application-history protection.
- User-skip protection.
- Duplicate and protected-job handling.

### 3.4 AI

- Structured Gemini profile extraction, job analysis, and answer generation.
- Persistent AI queue with statuses `QUEUED`, `PROCESSING`, `COMPLETED`, `RETRY_PENDING`, `QUOTA_BLOCKED`, `NEEDS_ATTENTION`, `FAILED`.
- Native-first priority.
- Deterministic fallback when analysis is unavailable.
- Quota exhaustion is recorded honestly and never marked as a completed analysis.
- AI remains advisory; only a suspicious flag blocks deterministically eligible work.

### 3.5 Application execution

- Shared browser session per batch.
- Native and conversational application surfaces.
- Header-scoped Apply control selection.
- Mode re-verification before click.
- Bounded post-click evidence window.
- Applied-state evidence requirement.
- External applications never submitted.
- CAPTCHA and security challenges stop the attempt.
- Ambiguous submissions reconciled against Naukri history.
- Browser session restart before an attempt, bounded to three per batch.
- Session loss during an attempt becomes `NEEDS_ATTENTION`.
- Per-job cancellation and skip boundaries.
- Stage timing and outcome instrumentation.

### 3.6 Screening and human-in-the-loop

- Saved answer memory, then profile facts, then AI, then human review.
- `PendingQuestion` lifecycle: `WAITING`, `ANSWERED`, `SKIPPED`, `CANCELLED`, `EXPIRED`.
- Dashboard answer/skip controls with optional memory save.
- Scoped answer memory: `GLOBAL`, `EMPLOYER`, `JOB`.
- Sensitive-question hard block.
- Context-sensitive global reuse authorization.
- Profile-hash and option-list staleness.
- Login re-validation after an answered wait.
- One-hour wait window before timeout.

### 3.7 Run control and observability

- DB-backed singleton apply lock.
- Duplicate-start `409` with active run identity.
- Idempotent stop and cooperative cancellation.
- Active state separated from last-run history.
- Per-run progress persisted to the control row.
- Waiting-for-user display state.
- Dashboard summary, recent applications, needs-attention list, and job list.
- Analytics for outcomes, skip reasons, decisions, and feedback.
- Persistent notifications and optional SMTP delivery.
- Windows autostart controls.

### 3.8 Manual apply queue

- Lists previously discovered jobs with per-job eligibility verdicts.
- Server-side pagination and search.
- Eligibility filtering.
- Multi-select and dry-run.
- Shared safety pipeline with the autonomous cycle.
- Shared lock with autonomous and scheduler apply paths.
- Per-job skip:
  - recorded immediately when idle;
  - queued during a live batch;
  - honored at the next job boundary;
  - never interrupts an in-progress submission;
  - protected from future runs.
- Honest exclusion reasons for external, expired, protected, user-skipped, irrelevant, profile-missing, preference-missing, and hard-filtered jobs.

### 3.9 Frontend

- E5-R33 page-based shell with grouped navigation:
  - Work: Overview, Jobs, Apply Queue, Applications, Needs Attention, AI Queue.
  - Insights: Analytics, Activity, Notifications.
  - Settings: Profile, Preferences.
- Responsive desktop and mobile navigation.
- Explicit loading, empty, error, and success states.
- Confirmation controls for destructive actions.
- Live progress and waiting-for-answer panels.
- Job cards, data tables, detail drawers, pagination, filters, and status badges.
- Screening question panel with answer, skip, and memory options.

---

## 4. Recent implementation checkpoints

| Checkpoint | Commit | Change |
|---|---|---|
| E5-R24 | `fcf1f13` | Fixed candidate selection and target-role filtering; added coverage for target titles and candidate-pool re-filtering. |
| E5-R25 | `730d915` | Fixed salary filtering and recovery of eligible previously discovered jobs; added salary gate and queue recovery tests. |
| E5-R28 | `f88d336` | Corrected the end-to-end candidate pipeline; introduced shared application-history protection and run diagnostics. |
| E5-R29 | `e29ba09` | Added the manual apply queue, dashboard stall handling, and scheduler lock sharing. |
| E5-R30 | `5b3c82d`, `6e59d97` | Fixed .NET relevance inconsistency across paths and improved manual apply reliability, runner boundaries, and salary-threshold behavior. |
| E5-R31 | `f7b03ff` | Fixed browser session lifecycle and batch processing; added bounded mid-run restart and truthful outcome reconciliation. |
| E5-R32 | `4da6c95` | Fixed screening lifecycle and per-job skip; added user-skip protection and stale-answer guards. |
| E5-R33 | `37b35ed` | Redesigned the frontend into pages, added shared UI primitives, and improved dashboard clarity. |

There is no separate E5-R26 or E5-R27 commit in the current history.

---

## 5. Current constraints

### Product

- Naukri only.
- Single user; no built-in authentication or multi-tenant isolation.
- External applications are recorded but never submitted.
- CAPTCHA and security challenges are never bypassed.
- No bulk resolution for `NEEDS_ATTENTION` items by design.
- `max_applications` is accepted for compatibility but ignored at runtime.
- No project-imposed hourly or daily application cap.

### Runtime

- Live browser automation is Windows-first.
- Uvicorn must run without `--reload` for Playwright automation on Windows.
- Only one apply process may hold the browser at a time.
- Only one process may own the persistent Chrome profile.
- Hosted API deployment does not provide a cloud browser.
- AI functionality requires a Gemini key and available quota.
- The app has no built-in public-internet authentication layer.

### Verification

- The current revision is offline-test verified.
- A fresh live multi-job acceptance run was not performed for this documentation revision.
- Naukri DOM changes remain an external risk; selector coverage is tested offline but cannot guarantee future live markup.
- Current UI screenshots are not committed.

---

## 6. Test coverage map

| Area | Representative test files |
|---|---|
| Application runner and outcomes | `test_application_runner.py`, `test_autonomous_cycle_outcomes.py` |
| Autonomous cycle | `test_autonomous_cycle.py`, `test_e5_r23_explicit_start_and_dedup.py`, `test_e5_r28_pipeline_regression.py` |
| Manual apply | `test_e5_r29_manual_apply.py`, `test_e5_r30_manual_queue_api.py`, `test_e5_r30_runner_boundaries.py` |
| Batch session lifecycle | `test_e5_r31_batch_processing.py` |
| Screening and skip | `test_e5_r21_multi_job_hitl.py`, `test_e5_r32_batch_screening.py` |
| Matching and relevance | `test_matching_rules.py`, `test_e5_r24_target_titles_and_candidate_filter.py`, `test_e5_r30_dotnet_relevance.py` |
| Salary rules | `test_e5_r25_salary_gate_and_queue_recovery.py`, `test_e5_r30_salary_threshold.py` |
| Discovery | `test_discovery.py`, `test_metadata_enrichment.py` |
| Naukri adapter | `test_naukri_adapter.py`, `test_naukri_adapter_offline_dom.py` |
| API and dashboard | `test_api_*`, `test_dashboard*`, route-specific tests |
| Profile and AI | `test_profile*`, `test_ai_*`, `test_gemini*` |
| Scheduler, worker, notifications | `test_scheduler*`, `test_worker*`, `test_notification*` |

The suite uses a temporary file-backed database and does not reset the runtime database. Adapter tests that use Chromium abort network requests and do not contact Naukri.

---

## 7. Open items and risks

| Item | Impact | Current handling |
|---|---|---|
| Naukri DOM drift | Selectors or flow steps can break | Offline adapter tests, evidence-based outcomes, honest `NEEDS_ATTENTION` |
| Gemini quota exhaustion | AI analysis unavailable | `QUOTA_BLOCKED`, deterministic fallback, no fabricated analysis |
| Browser profile contention | A second process cannot start | Cross-process profile lock and clear error |
| Ambiguous submission | Remote state unknown | History reconciliation, then `NEEDS_ATTENTION`; no blind retry |
| HITL timeout | Operator does not answer within an hour | Attempt becomes `NEEDS_ATTENTION`; batch continues |
| External-only listings | No native application possible | Excluded from native queue; recorded as external |
| No built-in auth | Unsafe public exposure | Trusted-local deployment; add an auth proxy before public exposure |
| Historical docs | Can mislead if read as current | Archived; current docs are the source of truth |

---

## 8. Definition of current done

For this revision, “done” means:

- The documented behavior matches the E5-R33 code.
- The backend suite passes in an isolated test environment.
- The frontend production build passes.
- The documentation distinguishes current behavior from historical checkpoints.
- No application code, database records, secrets, or workflows were changed by the documentation pass.

It does not mean:

- A new live Naukri acceptance run has been completed.
- Multi-job live acceptance is guaranteed.
- The system is ready for unauthenticated public exposure.
- Naukri selectors are guaranteed against future site changes.

---

## 9. Related documents

- [README](../README.md)
- [Architecture](ARCHITECTURE.md)
- [API reference](API.md)
- [Architecture decisions](DECISIONS.md)
- [Product requirements](MASTER_PRD.md)
- [Future roadmap](FUTURE_IMPLEMENTATION_ROADMAP.md)
- [Historical status through E5-R23](archive/DEVELOPMENT_STATUS_THROUGH_E5_R23.md)
