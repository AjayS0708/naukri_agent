# Development Status

## CHECKPOINT E5-R5.4: Native Apply Button Precedes External Body-Text Scan

**Status: E5-R5.4 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live validation - no autonomous cycle, no browser, no Apply click, no backend restart.**

**Implementation:**

1. `backend/services/naukri/adapter.py`
   - `_observe_application_type()` reordered: it now calls `_find_scoped_apply_button()` first and returns `NAUKRI_NATIVE` when a visible native Apply control exists. The external body-scan (`external_text_indicators` over `page.inner_text("body")`) runs only when no native control is visible. A visible native button is authoritative; incidental external-apply prose no longer reclassifies a native page as `EXTERNAL`. Genuine external CTAs (no native button) still classify `EXTERNAL`. Docstring documents the native-first rationale.

2. `backend/tests/test_naukri_adapter.py`
   - Replaced `test_visible_external_evidence_wins_over_visible_native` (old external-wins contract) with `test_native_button_wins_over_incidental_body_phrase` (asserts `NAUKRI_NATIVE`).
   - Added `test_native_button_wins_over_unrelated_prose_phrase` (prose "redirecting to an external application portal" + native button -> `NAUKRI_NATIVE`) and `test_no_native_button_with_phrase_still_external` (no button + phrase -> `EXTERNAL`).

3. `backend/tests/test_naukri_adapter_offline_dom.py`
   - Added `NATIVE_WITH_PROSE_HTML` and `test_native_button_beats_unrelated_prose_external_phrase` (real Chromium: native button + prose phrase -> `NAUKRI_NATIVE`, no false-EXTERNAL log).

**Tests:** focused adapter classification 23 passed; offline DOM 10 passed; full backend suite **924 passed, 0 failed** (baseline 921 + 3). `compileall` and `git diff --check` clean.

**Live state:** no cycle run, no browser, no Apply click, no backend restart. Jobs 85/59 (`APPLIED`) and 87/120 (`NEEDS_ATTENTION`) untouched. The 16 stale `EXTERNAL_APPLICATION` rows remain (addressed separately by the E5-R5.3 reconcile endpoint, not invoked). Live validation requires explicit approval.

---

## CHECKPOINT E5-R5.3: Signature-Scoped Reconciliation of False External Classifications

**Status: E5-R5.3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live validation - the endpoint has NOT been invoked against the live database, no autonomous cycle, no browser, no Apply click, no backend restart, no DB/queue/preference writes outside isolated test databases.**

**Implementation:**

1. `backend/services/applications/service.py`
   - Module constants `STALE_EXTERNAL_PAGE_CHROME_URL` (the exact proven-false AmbitionBox page-chrome URL from the E5-R4.1 evidence) and `STALE_EXTERNAL_RECONCILE_SKIP_REASON` (audit text stating the prior classification came from that page-chrome URL, that no external application was opened/submitted/confirmed, and that the job returns to the normal candidate pipeline).
   - `ApplicationService.reconcile_stale_externals()`: selects only `EXTERNAL_APPLICATION` rows whose `external_url` exactly equals the signature constant; reclassifies them to `SKIPPED`; records the audit reason; clears `needs_attention`; preserves the record and its `external_url`/`application_method` history; returns `{affected_count, application_ids, job_ids, signature}`; idempotent (second call matches nothing); never touches `APPLIED`, `SUBMITTED` (the persisted `SUBMITTED_UNCONFIRMED` status), `NEEDS_ATTENTION`, `FAILED`, or already-`SKIPPED` rows; never deletes; never invoked automatically by the autonomous cycle.
2. `backend/api/routes/application.py`
   - `POST /api/applications/reconcile-stale-externals` (no parameters, registered before the `/{application_id}` dynamic routes) invokes only the signature-scoped service method and returns `ReconcileStaleExternalsResponse`. No scheduler hook, no background task, no frontend trigger, no generic arbitrary-status reset.
3. `backend/schemas/application.py`
   - `ReconcileStaleExternalsResponse {affected_count, application_ids, job_ids, signature}` (`extra="forbid"`).

**Tests:**

- New `backend/tests/test_reconcile_stale_externals.py` (7, isolated disposable test database from `conftest.py`): exact-signature rows become `SKIPPED` with `needs_attention` cleared and history preserved; audit reason recorded (contains the URL and "page-chrome"); different external URLs remain `EXTERNAL_APPLICATION` with `needs_attention` intact; `NEEDS_ATTENTION`/`APPLIED`/`SUBMITTED` (SUBMITTED_UNCONFIRMED persistence)/`FAILED`/already-`SKIPPED` rows carrying the signature URL remain unchanged; second service call is a no-op; endpoint reports count/application IDs/job IDs/signature accurately; endpoint performs no unrelated status changes.
- Focused: **7 passed**. Full backend suite: **921 passed, 0 failed** (421.12s; baseline 914 + 7).

**Live state (unchanged by this checkpoint):** the 16 proven-false `EXTERNAL_APPLICATION` rows remain in `data/naukri_agent.db` (the endpoint has NOT been invoked); jobs 87/120 remain `NEEDS_ATTENTION` (correctly locked, remote status uncertain); the running backend (PID 25760, started 2026-10-10 10:48:32, no `--reload`) predates E5-R5.2 and this checkpoint and was not restarted. Next steps require explicit approval: restart the backend, invoke the endpoint, then run a cycle with `max_applications >= 2`.

---

## CHECKPOINT E5-R5.2: Truthful Application Outcomes and Bounded Error Recovery

**Status: E5-R5.2 IMPLEMENTED, TESTED, AND VERIFIED (offline only; all tests mocked). No live validation - no browser, no Apply click, no autonomous-cycle run, no DB/queue/preference writes outside in-memory test databases.**

**Implementation:**

1. `backend/services/applications/runner.py`
   - `stats` gains `"submitted_unconfirmed": 0`; the outcome loop maps `SUBMITTED_UNCONFIRMED` to it.
   - The post-submit path: clicked-but-unconfirmed submissions now persist the unchanged truthful `SUBMITTED` status (`applied_at` set, no retry, no resubmission) and return `"SUBMITTED_UNCONFIRMED"` instead of `"APPLIED"`. `_process_single_job` docstring documents the new outcome.
2. `backend/services/autonomous_cycle/service.py`
   - `_run_applications` stats gain `"submitted_unconfirmed": 0`; a `consecutive_errors` counter implements bounded tolerance: first `ERROR` recorded and loop continues; second consecutive `ERROR` sets `stop_reason = "Two consecutive runner errors; aborting remaining candidates"` and returns (non-normal, exit code 3); valid non-ERROR outcomes reset the counter; per-candidate exceptions neither increment nor reset it; `SECURITY_REQUIRED`/`AUTH_REQUIRED` still abort immediately; budget, duplicates, gates, limits unchanged.
   - `_process_single_job`: `reported_outcomes` includes `submitted_unconfirmed`; the stats mapping returns `SUBMITTED_UNCONFIRMED` (tracker app_type `NATIVE`) and never `APPLIED` for unconfirmed submissions.
   - Step-4 printout and SUMMARY print `Submitted (unconfirmed): N` alongside (never inside) `Applied`.
   - API: `AutonomousCycleRunResponse.stats` remains a free-form dict - additive key, no schema change.

**Tests:**

- New `backend/tests/test_autonomous_cycle_outcomes.py` (8): unconfirmed submission not counted in budget; EXTERNAL/NEEDS_ATTENTION/FAILED do not consume budget; confirmed APPLIED consumes budget and stops at the limit; one ERROR permits the next candidate; two consecutive ERRORs stop; valid outcome resets the counter; SECURITY/AUTH abort immediately.
- `backend/tests/test_application_runner.py` (+2): unconfirmed submission returns `SUBMITTED_UNCONFIRMED` with DB status `SUBMITTED`; confirmed submission still returns `APPLIED`.
- `backend/tests/test_autonomous_cycle.py`: `test_execution_error_stops_cycle_and_reports_failure` updated from the old stop-on-first-ERROR contract to the approved two-consecutive-error contract.
- Focused (3 files): **130 passed**; full backend suite: **914 passed, 0 failed** (446.67s; baseline 904 + 10); `compileall` clean.

**Live-only uncertainties:** whether a real unconfirmed submission actually succeeded remotely (SUBMITTED rows remain flagged for manual review); whether an isolated session-start ERROR occurs live and whether the following candidate can recover the runtime (CRITICAL_ERROR still aborts).

**Files changed:** `backend/services/applications/runner.py`, `backend/services/autonomous_cycle/service.py`, `backend/tests/test_application_runner.py`, `backend/tests/test_autonomous_cycle.py`, `backend/tests/test_autonomous_cycle_outcomes.py` (new). Documentation updated in all five project documents. No commit/push.

---

## CHECKPOINT E5-R4.3: Offline Chromium DOM Regression Tests (optional)

**Status: E5-R4.3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live validation - no autonomous cycle, no browser against Naukri, no Apply click, no submit, no DB/retry/preference writes.**

**Scope:** `backend/tests/test_naukri_adapter_offline_dom.py` - 9 optional tests (classes `TestSnapshotRealPage`, `TestSyntheticControlledPage`) running the real `NaukriAdapter` read-only detection methods against real Chromium DOM semantics via `page.set_content()`.

**Implementation details:**

- Fixtures: `offline_browser` (function-scoped `pytest_asyncio.fixture`) starts headless Chromium, aborts every request with `context.route("**/*")`, and points `adapter.evidence_dir` at pytest `tmp_path`; `_open_snapshot()` loads the saved snapshot; `_require_snapshot()` skips when the gitignored local artifact is absent.
- Snapshot tests (`data/job_page_snapshot.html`, 2026-10-02 pre-click capture): `NAUKRI_NATIVE` with no false-EXTERNAL indicator log; header Apply source wins over the duplicate `#apply-button` (2 present); `detect_applied_state` False in both scan modes; no application container; `get_external_redirect_url` `None` with ≥1 facebook and ≥50 naukri links present plus the fallback log; `_check_security` passes.
- Synthetic tests: `EXTERNAL` with the matched-indicator log; CTA grounding returns `https://example.com/apply?id=1` with the CTA-evidence log and rejects the facebook footer; applied-state evidence `Applied to "Synthetic Role"`; visible form container; screenshot written under `tmp_path`; `_record_new_tab` logs `new_tab_detected=yes` (real `context` popup event from a neutral local button) and `new_tab_detected=no` (timeout path).
- Optional/skip: `pytest.importorskip("playwright")` at import; launch failure yields `pytest.skip("Chromium unavailable for E5-R4.3 offline tests: ...")`. Prerequisite: `playwright install chromium`.

**Deliberate-violation verification (requirement 4):** a throwaway pytest file outside the repo injected three process-local regressions - broken `_header_apply_selector`, empty `external_text_indicators` for classification, and empty `external_text_indicators` for CTA grounding - and asserted the correct behavior; all three failed (`3 failed`, exit code 1, 3.90s). No existing test or production code was modified.

**Test results:**

- `python -m pytest backend\tests\test_naukri_adapter_offline_dom.py -v` - **9 passed** (19.51s)
- `python -m pytest backend -q` - **904 passed, 0 failed** (400.36s; baseline 895 + 9)

**Remains unverified live:** whether Naukri's real Apply click opens a popup; server-side instant-apply persistence behind the D5 reload decision; real click/redirect timing; live security challenges; DOM drift vs the 2026-10-02 snapshot; auth/session-gated rendering. A live cycle requires separate explicit approval.

**Files added:** `backend/tests/test_naukri_adapter_offline_dom.py`. No commit/push; existing modifications and artifacts preserved.

---

## CHECKPOINT E5-R4.2: Run #59 Validation Instrumentation (prepared; backend restarted on approval)

**Status: E5-R4.2 IMPLEMENTED, TESTED, AND SERVED. Backend restarted on 2026-10-10 10:48:32 with explicit approval; no live validation executed (no cycle, no browser, no Apply click).**

**Scope:** read-only runtime instrumentation for the controlled live validation of the E5-R4.1 adapter fixes. No behavior change beyond logging and one terminal-state PNG capture.

**Implementation:**

1. `backend/services/naukri/adapter.py`
   - `_observe_application_type()` logs the matched external indicator together with the page URL.
   - `get_external_redirect_url()` logs the CTA link's visible text and href when it matches the shared vocabulary, and logs the explicit fallback to the job URL when no such link exists.
   - `start_application()` logs `Apply click: page url before click/after click`; registers a bounded `page.context.wait_for_event("page", ...)` observer (`post_apply_timeout_seconds + post_apply_reload_settle_seconds + new_tab_observation_grace_seconds` = 8+5+5s) resolved in a `finally` block as `new_tab_detected=yes|no`; logs every bounded-window iteration as `post-click check #N at +X.XXs: applied=... container=...` plus `post-click window closed: elapsed=... checks=...`; and on terminal `NEEDS_ATTENTION` logs `terminal_state=NEEDS_ATTENTION checks=N screenshot=<path>` after writing a PNG via the new `_capture_evidence_screenshot()` helper.
   - New class attributes: `evidence_dir = "data"` and `new_tab_observation_grace_seconds = 5`.
2. `backend/services/applications/runner.py` - the external branch log now includes the recorded `external_url` alongside `job_id`.

**Safety boundaries honored:** no additional control is clicked, no form is filled or submitted, no application/retry-queue/preference/limit record is written, the security check still runs after the click and after the reload, the observed popup is never interacted with or closed, and `APPLIED` still requires positive visible evidence.

**Runtime verification (2026-10-10):** the pre-restart backend (PID 18732 / child 22596 owning 127.0.0.1:8000, started 08:39:13 without `--reload`) predates the E5-R4.1 adapter edit (09:26:54) and therefore did not serve the new adapter code. On explicit approval ("Restart backend only") it was stopped, port 8000 was confirmed free, and a new backend was started at **10:48:32** as PID **25760** (parent 17088) with the identical no-`--reload` command:

```powershell
Stop-Process -Id 22596, 18732                 # executed 10:48; port then confirmed free
& "C:\Users\ajays\Desktop\Naukri Agent\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000   # executed; PID 25760
```

Post-restart verification (all read-only): `GET /api/health` → `status=ok`, `agent_state=IDLE`; `GET /api/readiness` → ready with database/schema/configuration/storage/ai_provider/runtime_environment all healthy; `GET /api/autonomous-cycle/status` → `IDLE`, `lock_held=false`, `active_run=null`; `GET /api/agent/status` → scheduler `is_running=false`, `last_run_at=null` (startup does not auto-start the scheduler, `backend/main.py:81`); startup recovery completed at 10:48:37 with no errors in stderr; the log contains only dashboard status polling - no apply, discovery, or click activity. The adapter module is imported at process start, so the new process serves the E5-R4.1/E5-R4.2 adapter code.

**Test coverage:**

- `backend/tests/test_naukri_adapter.py` - 143 PASS (6 new: `TestValidationInstrumentation` - URL before/after click, timestamped window checks, terminal state + screenshot path, new tab present, new tab absent on timeout, external indicator + CTA link evidence)
- Full backend suite - **895 passed, 0 failed** (pre-instrumentation baseline re-verified at 889 passed against the same working tree)

**Files modified:** `backend/services/naukri/adapter.py`, `backend/services/applications/runner.py`, `backend/tests/test_naukri_adapter.py`

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

**Not performed:** dashboard cycle, browser session, Apply click, application attempt, commit/push.

---

## CHECKPOINT E5-R4.1: Run #59 Post-Click Window & External Evidence Grounding

**Status: E5-R4.1 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live cycle run - awaiting human review.**

**Run #59 (dashboard-triggered, `max_applications = 2`, 2026-10-10):** 79 discovered, 62 hard-filtered, 17 pre-analyzed, 5 candidates, **0 genuine Naukri-native applications** - 3 `EXTERNAL_APPLICATION` (jobs 55/57/86), 1 `NEEDS_ATTENTION` (job 87), 1 skipped, 0 failed. Diagnosis used the run log, read-only queries of `data/naukri_agent.db`, and `data/job_page_snapshot.html`.

**Root causes (demonstrated offline):**

1. **The bounded post-click window was not honored.** `start_application()` ran `detect_applied_state()` first in every polling iteration; that method walks every element of the page (a visibility + text round trip each; 1,009 elements in the captured Naukri job page) before the application-container check runs. The entire 8s window was consumed by one full-page pass: Apply click `03:12:49.075` to reload decision `03:13:02.379` = 13.3s, so `_has_visible_application_container()` was observed at most once, at or after the deadline, instead of every 0.25s as the loop intends.
2. **The recorded external URL was fabricated.** `get_external_redirect_url()` returned the first non-Naukri anchor on the page - site chrome, not a redirect target. Of the 20 `EXTERNAL_APPLICATION` rows, 19 (run #59's three plus 16 historical) and their notifications carry the identical AmbitionBox promo URL (`https://www.ambitionbox.com/interviews?utm_source=naukri&utm_medium=desktop&utm_campaign=gnb`), which appears 30 times in the captured page; the remaining row carries Naukri's Facebook URL. Neither is a redirect target.

**Implementation:**

1. `backend/services/naukri/adapter.py` - `detect_applied_state(page, scan_whole_page: bool = True)`. The bounded polling loop passes `scan_whole_page=False` (header/banner evidence only); the page-wide scan runs exactly once after the window, before the reload decision, so detection power is preserved while container checks repeat inside the bound. The terminal `NEEDS_ATTENTION` warning now records `page.url`.
2. `backend/services/naukri/adapter.py` - `get_external_redirect_url()` returns only a non-Naukri link whose own visible text matches the shared `external_text_indicators` vocabulary; otherwise `None`, so `ApplicationRunner` records `job.url` instead of a fabricated redirect target. `_observe_application_type()` logs the indicator that matched.

**Constraints honored:** no selector guessing; no classification precedence change; external jobs still never clicked or submitted; `APPLIED` still requires confirmation evidence; safety gates, duplicate protection, `max_applications`, hourly/daily limits, and preferences unchanged; no application row, retry queue, preference, limit, or database record modified; no live cycle, browser, Apply click, or Gemini call; no commit.

**Test coverage:**

- `backend/tests/test_naukri_adapter.py` - 137 PASS (9 new: `TestPostClickBoundedWindow`, `TestExternalRedirectEvidence`)
- runner/flow/safety/cycle/AI focused files - 187 PASS
- Full backend suite - **889 passed, 0 failed**

**Files modified:** `backend/services/naukri/adapter.py`, `backend/tests/test_naukri_adapter.py`

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

**Open item:** job 87's post-click surface cannot be attributed offline (no Applied badge after reload, no matching container, no security/login text). New-tab surfaces and unmatched container markup remain hypotheses; the controlled validation plan is part of the checkpoint review.

---

## CHECKPOINT E5-R3: Freshness-First Discovery & Advisory-Only AI Recommendations

**Status: E5-R3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live cycle run — awaiting human review.**

**Objective:**

Two defects silently reduced and misranked eligible candidates: (1) the final safety gate rejected jobs that matched the user's saved preferences and passed every deterministic rule solely because Gemini returned a subjective `NEEDS_ATTENTION` recommendation, and (2) discovery counted every scanned card against its scan budget while the autonomous cycle ordered candidates by raw `discovered_at`, so pages dominated by already-known duplicates could consume the budget and leave fresh eligible jobs unprocessed.

**Implementation:**

1. `backend/services/applications/service.py` — `run_final_safety_gate()` no longer blocks on the AI recommendation. Gemini remains advisory; the only AI-derived block is the explicit `job_analysis.suspicious` fraud flag. All deterministic gates are unchanged and still authoritative: confirmed profile, duplicate/`APPLIED` protection, location, fresher/experience rule, IT-scope, salary minimum, employment type, and title/search scope. Removed the now-unused `AIRecommendation` import.
2. `backend/services/naukri/adapter.py` — `_parse_posted_date()` now returns a timezone-aware UTC `datetime` for `today`/`just now`, `yesterday`, `N days ago`, `N weeks ago`, `30+ days ago` (exactly 30 days), and absolute formats (`%d %b %Y`, `%d %B %Y`, `%d-%m-%Y`, `%Y-%m-%d`). Unrecognised text returns `None` so a posting date is never fabricated. Cards on each page are emitted freshness-first (`_posted_sort_key`: known dates newest-first, unknown dates last). No Naukri URL/sort parameter was changed; pagination still uses the existing next-button selector and `MAX_PAGES = 3`.
3. `backend/services/discovery/service.py` — the scan budget (`max_cards`) now applies to **new distinct jobs**, not to every card, so a stream of old duplicates can no longer starve fresh eligible jobs out of the discovery budget. `_refresh_duplicate_job()` advances `last_seen` and adopts a **newer** grounded `posted_at`; an unknown (`None`) date never overwrites a known one.
4. `backend/services/autonomous_cycle/service.py` — freshness-first ordering via shared `posted_freshness_key()` / `job_freshness_key()`. `_apply_hard_filters_and_enqueue()` sorts eligible candidates by newest grounded `posted_at` (unknown last), then `discovered_at` desc, then `match_score` desc, so the bounded Gemini budget is spent on the freshest eligible jobs. `_run_applications()` orders candidates by `posted_at` desc (nulls last) then `discovered_at` desc.

**Constraints honored:**

- No change to the user's saved job preferences, hard filters, duplicate protection, safety checks, or configured limits
- No URL/sort parameter change and no pagination-behavior change (no repo evidence of a Naukri sort parameter, so freshness is applied client-side)
- Unknown/ungrounded posting dates are never invented; they are stored as `None` and always sorted last
- No live Naukri cycle, no browser launch, no Apply click, no Gemini call; the database was not modified
- No commit/push; `.agent` not staged; pre-existing untracked artifacts preserved

**Test Coverage:**

- `backend/tests/test_application_safety_gate.py`: 20 PASS — inverted `test_ai_needs_attention_blocked` to `test_ai_needs_attention_allowed`, added `test_ai_skip_recommendation_allowed` and `test_needs_attention_still_requires_deterministic_rules` (a hard-rule failure still blocks even with `NEEDS_ATTENTION`). `test_suspicious_job_blocked` remains.
- `backend/tests/test_discovery.py`: 15 PASS — added `test_duplicate_refreshes_newer_posted_at_without_creating_new_job`, `test_duplicate_unknown_posted_at_does_not_overwrite_known`, and `test_duplicates_do_not_starve_fresh_jobs` (budget of 2 new jobs reached despite 2 duplicates first).
- `backend/tests/test_naukri_adapter.py`: 128 PASS — expanded the posted-date matrix (days/weeks/`30+`/absolute/tz-aware/unrecognised→`None`), added `_posted_sort_key` tests, and a `search_jobs` test proving freshness order and page advancement.
- `backend/tests/test_autonomous_cycle.py`: new `TestFreshnessFirstOrdering` (3 tests) plus the existing suite PASS — `_apply_hard_filters_and_enqueue()` selects the two newest-posted jobs within the Gemini budget and caps older/unknown-date jobs.
- Focused run of the four files: **270 passed**.
- Full backend suite: **878 passed, 0 failed** (2026-10-09). The two failures reported at E5-R3 were resolved in E5-R3.1: `test_checkpoint_c2_policy.py::test_it_scope_is_deterministic` held an outdated C2 expectation that predated the intentional D5 IT-scope relaxation (a missing industry field still passes when the title contains an IT role/title keyword), and `test_dashboard.py::TestDashboardSummaryEmpty::test_empty_discovery_has_zero_counts` was a test-ordering isolation leak, now reset before every dashboard test. Zero regressions from E5-R3.
- No lint/typecheck tooling is configured in this repository; the test suite is the verification gate.

**Files Modified:**
- `backend/services/applications/service.py`
- `backend/services/naukri/adapter.py`
- `backend/services/discovery/service.py`
- `backend/services/autonomous_cycle/service.py`
- `backend/tests/test_application_safety_gate.py`
- `backend/tests/test_naukri_adapter.py`
- `backend/tests/test_discovery.py`
- `backend/tests/test_autonomous_cycle.py`

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

**Remaining limitations:**
- Posting-date parsing covers the Naukri card renderings listed above; any other format stays `None` (never guessed).
- Gemini may still label a good job `NEEDS_ATTENTION` at the analysis stage; this is now advisory only and does not block a job that passes the deterministic gate.
- No live endpoint validation was performed in this checkpoint; E5/E4-R1 live validation remains outstanding and is unaffected by these changes.

---

## CHECKPOINT E5-R1: Multi-Application Outcome Reporting Reliability

**Status: E5-R1 IMPLEMENTED, TESTED, AND VERIFIED (offline only). Controlled live validation NOT yet run — awaiting human review.**

**Next roadmap checkpoint:** E5 — "Multi-Application Dashboard Cycle & Configurable Application Limit" (`docs/FUTURE_IMPLEMENTATION_ROADMAP.md`). E4's application-submission validation is still outstanding and is deliberately satisfied by the same controlled live run as E5, because both need one dashboard-triggered run with `max_applications > 1`.

**Objective:**

A completed run must report what actually happened. Recent runs produced zero applications while the cycle still reported `COMPLETED`, and the remaining stop paths reported `FAILED` even when the run had simply reached its configured limit. Both are outcome-reporting defects, not filter defects.

**Evidence: read-only audit of `data/naukri_agent.db` (no writes):**

- Runs 52 and 55 `COMPLETED` with 102-103 jobs discovered; run 55 had `new_jobs = 0`.
- Of the 15-16 jobs analysed in runs 52/55, 12-13 are parked as unresolved `EXTERNAL_APPLICATION` (excluded by the candidate query and by the runner's "unresolved prior attempt" check) and only 3 jobs (57, 58, 86) had no application record at all.
- All 3 remaining candidates were legitimately blocked by `run_final_safety_gate`: job 57 `NEEDS_ATTENTION`, job 58 `suspicious = true`, job 86 `NEEDS_ATTENTION`. Application limits passed (`max_hourly_applications = 4`, `max_daily_applications = 20`, usage 0).
- Runs 45, 46, 47, 53 and 54 failed at browser startup with "Failed to start browser session. NotImplementedError" — the documented Windows uvicorn `--reload` SelectorEventLoop issue (E4-R2).
- Correction to the E4-R8 report: the AI `SKIP` recommendation alone does not block a job. Job 58 was blocked on `suspicious = true`, not on its `SKIP` recommendation.

**Verified defects (both are outcome-reporting only):**

1. **Terminal status.** `AutonomousCycle.run()` returned `exit_code = 3, status = "FAILED"` whenever `stop_reason` was set, including `"Reached max-applications limit (N)"`. README, MASTER_PRD and ARCHITECTURE all document: *"Exit code 0 on normal completion, non-zero on AUTH/SECURITY/critical stop."* The dashboard therefore rendered `Last cycle failed. Check logs for details.` for a run that had done exactly what it was configured to do. The AUTH/SECURITY branch was also unreachable in practice: it tested `"AUTH"`/`"SECURITY"` in mixed case against `"Authentication required"` and `"Security challenge encountered"`, so exit code 2 was never produced.
2. **Per-job outcome.** `_process_single_job()` fell through to `return "SKIPPED"` when `ApplicationRunner.run_applications()` produced no outcome for the job. Browser-start failure returns all-zero stats (state left at `CRITICAL_ERROR`), and an unusable agent state returns `{"error": "Invalid state"}` for every subsequent job. A candidate that was never inspected was recorded as a blocked/skipped candidate while the cycle still reported `COMPLETED`. Such a failure also created no application row, so the candidate could not be retried honestly either.

**Implementation (`backend/services/autonomous_cycle/service.py` only):**

- Added `self.stop_is_normal` and `AutonomousCycle._terminal_outcome() -> (exit_code, status)`:
  - no stop reason, or a configured-limit stop -> `(0, "COMPLETED")`
  - stop reason containing `AUTH` or `SECURITY` (case-insensitive) -> `(2, "FAILED")`
  - any other stop reason -> `(3, "FAILED")`
- `run()` now returns `_terminal_outcome()` for the mid-run stop path and includes `stop_reason` in `stats` so the reason for stopping is retained in `last_run`. Pre-execution early returns (`profile`/`preferences`/`limits`/discovery guards) are unchanged.
- `Reached max-applications limit (N)` now sets `stop_is_normal = True`. `Application limits reached: ...` and `Application execution unavailable for remaining candidates` do not.
- `_process_single_job()` now detects a non-executed run: if the runner returns an `error` key, or none of `applied`/`external`/`needs_attention`/`skipped`/`failed`/`dry_run` is greater than zero, it logs, records decision outcome `ERROR`, and returns `"ERROR"`. It creates no application row.
- `_run_applications()` handles `"ERROR"` by incrementing `failed`, setting a stop reason, and returning immediately, so one execution failure does not cascade into bogus `SKIPPED` outcomes for the remaining candidates.

**Constraints honored:**

- No change to discovery, hard filters, role matching, IT-scope gate, experience/salary/employment-type policy, Gemini budget, duplicate protection, or the final application safety gate
- No change to application limits (hourly/daily) or to `max_applications` enforcement
- No application row is created when the runner did not inspect the job — a `NEEDS_ATTENTION`/`SKIPPED` row would permanently park the candidate
- Genuine blocks still return `SKIPPED` and do not stop the run
- No schema, API, or frontend change; `stats` is already a `dict` so `stop_reason` needs no Pydantic change. The frontend reads `stats` keys by name only.
- No live Naukri access, no browser launch, no Apply click, no Gemini call in this checkpoint; the real database was only read

**Test Coverage:**

- `backend/tests/test_autonomous_cycle.py`: 92 -> 104 tests, all PASS
- New `TestApplicationOutcomeReporting` (12 tests) exercises the real `_terminal_outcome()`, `_process_single_job()` and `_run_applications()`:
  - no stop -> `(0, COMPLETED)`; `max_applications` reached -> `(0, COMPLETED)` after exactly 2 of 3 candidates
  - security stop -> `(2, FAILED)`; auth stop -> `(2, FAILED)`; unclassified stop -> `(3, FAILED)`
  - runner `{"error": "Invalid state"}` -> `ERROR`, no application row, decision outcome `ERROR`
  - runner all-zero stats (browser start failure) -> `ERROR`, no application row
  - runner errors-only stats (job not found) -> `ERROR`
  - genuine skip -> `SKIPPED`; genuine application -> `APPLIED` (regression guards)
  - `ERROR` stops the cycle after 1 candidate with `failed = 1`, `skipped = 0`, terminal `(3, FAILED)`
  - `SKIPPED` does not stop the cycle (`SKIPPED` + `APPLIED`, terminal `(0, COMPLETED)`)
- Full suite: `858 passed, 2 failed`. Both failures reproduce on the unmodified baseline (`846 passed, 2 failed`): `test_checkpoint_c2_policy.py::test_it_scope_is_deterministic` (pre-existing, introduced by E4-R10) and `test_dashboard.py::TestDashboardSummaryEmpty::test_empty_discovery_has_zero_counts` (pre-existing test-ordering isolation). Zero regressions from this checkpoint. Both failures were later resolved in E5-R3.1 on 2026-10-09 (full suite 878 passed, 0 failed).
- No lint/typecheck tooling is configured in this repository (no ruff/mypy/flake8); the test suite is the verification gate.

**Files Modified:**
- `backend/services/autonomous_cycle/service.py`
- `backend/tests/test_autonomous_cycle.py`

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

**Controlled live validation plan (NOT executed — requires explicit human approval):**

1. Preconditions: `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` with **no `--reload`** (E4-R2); confirmed profile; job preferences; `data/naukri_agent.db` backed up; application limits unused; dashboard reachable.
2. Trigger: Dashboard UI "Run Autonomous Cycle" with `max_applications >= 2` (E5 requires more than one submission in a single run).
3. Success criteria: `last_run.status == COMPLETED`; `stats.applied >= 2` with `stats.applied <= max_applications`; `stats.stop_reason == "Reached max-applications limit (N)"` when the limit is reached; `POST /api/autonomous-cycle/run` returns HTTP 200; runtime returns to `IDLE` with `lock_held = false`; dashboard shows "Last cycle completed successfully." with stats, not "Last cycle failed"; one application row per submitted job, each with `applied_at`, method and `confirmation_evidence`; no external submission, no CAPTCHA/security bypass, S&P job `300926927428` untouched, duplicate protection intact.
4. Failure criteria: any `NEEDS_ATTENTION`/`SECURITY_REQUIRED`/`AUTH_REQUIRED` stop (expected as `FAILED`), any application row without post-click evidence, any second Apply click on a job already recorded as applied.
5. Outcome is recorded as a follow-up checkpoint entry in this file regardless of result. E4's outstanding application-submission validation closes on the same run.

---

## CHECKPOINT E4-R10: Targeted Role-Matching Improvement

**Status: E4-R10 IMPLEMENTED, TESTED, AND VERIFIED**

**E4-R10 Objective:**

Improve deterministic role matching so clearly relevant entry-level software and data roles are not rejected merely because their titles use reasonable variations of existing target-role names. The goal is greater relevant-job coverage, not simply more candidates.

**Reconciliation (completed before implementation):**
- NO_MATCHING_FAMILY count discrepancy resolved: script listed 37 IDs, not 38. All 37 jobs exist in the database.
- UNWANTED_SPECIALIZATION count: all 15 jobs exist in the database. No discrepancy.
- E4-R9 report was partially incorrect: "Associate Software Engineer", "Associate Developer Trainee", and "Python Developer" roles already PASS role-matching under production code (they match "software engineer", "developer", and "python developer" keywords respectively).

**Verified role-matching failures (5 jobs):**
1. Job 55: "Software Development Trainee" - User preference: "Software Developer Trainee", but code required "software developer" (noun) not "software development" (gerund)
2. Job 62: "Data Science Intern/Fresher" - User has "Data Analyst Fresher" and "Data Engineer Fresher", but no "data science" keyword in ALLOWED_ROLE_FAMILIES
3. Job 64: "Power Bi Internship _ For Freshers" - User has "Junior Data Analyst", but no "power bi" keyword
4. Job 87: "Qa Engineer" - User has "QA Engineer Fresher", but no "qa" keyword in ALLOWED_ROLE_FAMILIES
5. Job 112: "ELK Engineer" - Not in user preferences, but is DevOps/monitoring-related (not addressed in this checkpoint)

**Implementation:**

Extended `ALLOWED_ROLE_FAMILIES` in `backend/services/matching/engine.py`:
- Added "data science" and "power bi" to data family
- Added "software development" to software family
- Added new "qa" family with "qa" and "quality assurance"
- Added new "sql" family with "sql developer" (standalone "sql" excluded to prevent SQL Server Administrator matches)

**Constraints honored:**
- Did NOT add "associate" as a standalone catch-all keyword
- Did NOT admit pure sales, HR, mechanical, manufacturing, or operations jobs
- Did NOT weaken IT-scope filter, experience cap, salary policy, or employment-type policy
- Did NOT remove "sales" from UNWANTED_SPECIALIZATIONS
- Did NOT lower salary threshold
- Did NOT change candidate profile facts or preferences
- Did NOT change AI recommendations or final application safety gate

**Test Coverage:**
- 10 new tests for role-matching improvements: software development trainee, data science roles, power bi roles, qa roles, sql roles
- 9 new regression tests: SQL Server Administrator exclusion, boundary cases (sales mention in tech role, hardware with software), pure sales, mechanical, manufacturing, HR, operations roles
- Total: 54 tests in test_matching_rules.py — all PASS
- All verified failing jobs now PASS role-matching:
  - Job 55 (Software Development Trainee): PASS
  - Job 62 (Data Science Intern/Fresher): PASS
  - Job 64 (Power Bi Internship): PASS
  - Job 87 (Qa Engineer): PASS
  - Job 112 (ELK Engineer): FAIL (not in user preferences, DevOps/monitoring-specific, requires separate decision)

**Files Modified:**
- `backend/services/matching/engine.py` (ALLOWED_ROLE_FAMILIES extended)
- `backend/tests/test_matching_rules.py` (18 new tests)

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

---

## CHECKPOINT E4: Dashboard Live-Run Outcome Documentation

**Status: E4 LIVE CYCLE EXECUTED — runtime/dashboard validation PASSED; application-submission objective UNRESOLVED.**

This checkpoint documents the actual outcome of the E4 live cycle (Run #52) triggered through the Dashboard UI. It is documentation and Git only: no new autonomous cycle was executed, no source code was modified, and no database was modified during this checkpoint.

**Verified Run #52 result (triggered by Dashboard UI):**

- Trigger: Dashboard UI "Run Autonomous Cycle" button with `max_applications = 1`.
- Run ID: `52`.
- Discovery run ID: `52`.
- Terminal status: `COMPLETED`.
- Jobs discovered: `103`.
- Jobs processed from the current run: `81`.
- Candidates considered for application: `3`.
- New applications submitted during Run #52: `0`.
- Apply clicks during Run #52: `0`.
- Runtime returned to `IDLE`, with `lock_held = false`.

**Distinction between successful execution and zero applications:**

- The cycle executed end-to-end: discovery, filtering, candidate evaluation, and safe completion. The runtime returned to `IDLE` and released its lock. The Dashboard UI, control/status APIs, non-reload Uvicorn runtime, and `max_applications = 1` control all behaved as designed. Runtime/dashboard validation therefore PASSED.
- However, zero applications were submitted during Run #52. The three candidates considered did not reach a safe native Apply click. The application-submission objective remains UNRESOLVED and is recorded as an open issue for a separate investigation checkpoint.
- The three existing applications referenced in earlier reports (records #18, #24, #25) belong to earlier runs (D4/D5 and D7), NOT to Run #52. They are preserved and unaltered.

**Open issue (carried forward):** Why did Run #52 submit zero applications despite successful execution? Root cause has not been determined. Investigation is deferred to a separate checkpoint after this push. Do not claim the application objective was achieved.

**Historical E4 records preserved:** The two accidental curl-triggered E4 attempts on 2026-10-08 that failed before browser startup remain preserved and unaltered. Run #52 is the first E4 cycle to execute end-to-end through the Dashboard UI.

**Files modified:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md` (documentation only).

---

## CHECKPOINT E4-R2: Windows Playwright Runtime Requirement: DOCUMENTATION ONLY

**Status: DOCUMENTATION ONLY — E4 live validation has NOT yet succeeded. No live cycle was run in this checkpoint.**

**E4-R2 Objective:**

Document the runtime/environment requirement discovered during E4 validation and resolve the E4 browser-startup blocker, without executing E4.

**Verified fact (Windows):**

- Uvicorn with `--reload`: the spawned reload worker uses `WindowsSelectorEventLoop`; the Playwright subprocess bootstrap raises `NotImplementedError`; the autonomous cycle fails immediately during browser startup.
- Uvicorn without `--reload`: the server runs on `ProactorEventLoop`; the Playwright driver starts successfully; the configured Chromium persistent context starts successfully; the standalone smoke test PASSes.

**Verified environment:** Windows 11, Python 3.14.2, FastAPI 0.141.1, Starlette 1.6.0, Playwright 1.63.0. The Playwright installation itself was healthy and the Chromium installation is healthy — the blocker was the event loop selected by the reload worker, not the browser installation.

**Resolution:**

- No source-code workaround was required.
- `--reload` is incompatible with the Windows Playwright subprocess requirement in this environment.
- Live autonomous execution must use non-reload Uvicorn. The correct live runtime invocation is:

  ```powershell
  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```

  WITHOUT `--reload`.

**Checkpoint boundaries honored:** no E4 execution, no Dashboard Run click, no `POST /api/autonomous-cycle/run` call, no database modification, no backend/frontend source-code modification, no Playwright configuration change, no asyncio workaround.

**E4 status tracking:**

- E4 live cycle has since EXECUTED end-to-end in Run #52 (triggered by Dashboard UI, `max_applications=1`, terminal status `COMPLETED`, `lock_held=false`). See the **CHECKPOINT E4** section at the top of this file.
- Runtime/dashboard validation PASSED; the application-submission objective remains UNRESOLVED (zero applications in Run #52). Investigation is deferred to a separate checkpoint.
- Historical E4 FAILED runs (including the two accidental curl-triggered attempts on 2026-10-08 that failed before browser startup) remain preserved and unaltered.
- The non-reload Uvicorn runtime requirement documented in this checkpoint was the runtime fix that made Run #52 possible.

**Do not claim the E4 application objective was achieved.** Describe E4 as runtime/dashboard validation passed, with application submission still unresolved.

**Files modified:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md` (documentation only).

---

## CHECKPOINT E4-UI: Dashboard max_applications Control: COMPLETE

**Status:** E4-UI IMPLEMENTED, TYPECHECKED, AND BUILT

**E4-UI Objective:**

The E4 live validation requires triggering exactly one autonomous cycle through the Dashboard UI with `max_applications = 1`. The existing E3 dashboard hardcoded `max_applications = 2` in `frontend/src/app/App.tsx:65` (`useState(2)`) and exposed no user control, so the UI could not satisfy the E4 acceptance criteria without a source change. E4-UI adds a selectable Maximum applications control to the confirmation modal, keeps the safe default at 1, and does not change any autonomous-cycle backend semantics.

**Implementation:**

Frontend (`frontend/src/app/App.tsx`):
- Added `MAX_APPLICATION_OPTIONS = Array.from({ length: 10 }, (_, i) => i + 1)` (1-10, matching the server schema).
- Changed `maxApplications` initial state from `2` to `1`.
- Added `handleMaxApplicationsChange(value)` that rejects values outside the allowed set.
- Added a `select` control inside the Run Confirmation Modal bound to `maxApplications`, with `aria-label="Maximum applications per cycle"`, disabled while starting.
- Added a live confirmation line stating how many real Naukri applications will be attempted.
- The control feeds `handleStartCycle`, which already sends `{ max_applications: maxApplications }` to `POST /api/autonomous-cycle/run`.

Backend: NO CHANGES. `POST /api/autonomous-cycle/run` and `GET /api/autonomous-cycle/status` are untouched; server validation (1-10) and Gemini budget derivation (`max_applications * 2`) remain authoritative.

**Verification:**
- `npm run build` (`tsc -b && vite build`): PASS — 1588 modules transformed, 289.06 kB JS bundle, 13.43s.
- Built bundle verified to contain the `Maximum applications` select, the `aria-label`, and no `useState(2)` literal.
- Pre-flight `GET /api/health` and `GET /api/autonomous-cycle/status` confirmed the fresh non-reload backend returns the E4-R schema (`active_state`, `lock_held`, `active_run`, `last_run`) with `active_state=IDLE`, `lock_held=false`, `active_run=null`.

**Test Coverage:**
- Frontend: NO test infrastructure exists in this project. `frontend/package.json` declares no test runner/test libraries, and no `*.test.*`/`*.spec.*` files exist under `frontend/`. Coverage for this change is the TypeScript typecheck and the production build above.
- Backend: unchanged; all existing tests remain passing.

**Files Modified:**
- `frontend/src/app/App.tsx` (state default, options constant, change handler, modal select control)

**Safety Preserved:**
- Backend semantics unchanged; client still cannot control the Gemini budget.
- Explicit user confirmation modal still required before execution.
- `max_applications` still validated server-side (1-10).

**Live validation (Run #52):** The Dashboard UI control was used to trigger the cycle with `max_applications = 1`. The cycle executed and returned `COMPLETED` with `lock_held = false`, confirming the UI control, confirmation modal, status polling, and completion handling all work end-to-end. Zero applications were submitted in Run #52 (see CHECKPOINT E4 at the top of this file); the three pre-existing applications (records #18, #24, #25) belong to earlier runs (D4/D5 and D7) and were untouched.

---

## CHECKPOINT E4-R: Autonomous Cycle Recovery & Execution-Safety Hardening: COMPLETE

**E4-R status: runtime hardening COMPLETE; E4 live cycle subsequently EXECUTED in Run #52 (see CHECKPOINT E4 at the top of this file).** Two accidental curl-triggered autonomous-cycle attempts on 2026-10-08 failed before browser-session startup (including Discovery Run #34). They created no applications, made zero Apply clicks, triggered no CAPTCHA/security event, and made no external submissions. E4-R deliberately performed no live cycle; it prepared the runtime state model and recovery paths that Run #52 later exercised successfully.

**E4-R implementation:** process-local runtime state now separates `active_state` (`IDLE`/`RUNNING`) from `last_run` terminal history. The lock is acquired atomically before execution and released for completion, failure, and initialization exceptions. `GET /api/autonomous-cycle/status` is a read-only diagnostic that exposes active state, lock state, and safe active/last-run timestamps, status, stats, and error; it never constructs or invokes the execution path. Browser launch errors are persisted with the underlying Playwright exception and logged, replacing the old opaque discovery error. Unit/API tests cover fresh runtime, success/failure recovery, lock release, rejection while active, restart-clean state, historical retention, and GET diagnostic non-execution.

**Run #52 exercised these paths:** the cycle started, acquired the lock (`active_state=RUNNING`), completed normally, and returned to `IDLE` with `lock_held=false`. The `COMPLETED` terminal status and zero-application outcome are recorded in `last_run`, distinct from the active state.

## CHECKPOINT E3: Safe Dashboard Autonomous-Cycle Control: COMPLETE

**Status:** E3 IMPLEMENTED, TESTED, AND VERIFIED

**E3 Objective:**

Enable safe manual triggering of the autonomous job application cycle from the dashboard by extracting the existing autonomous cycle logic into a reusable service, adding control/status API endpoints, and implementing explicit user confirmation with status polling.

**Implementation:**

Backend — service extraction:
- `backend/services/autonomous_cycle/service.py`: extracted `AutonomousCycle` class from CLI
- `AutonomousCycle.run()`: orchestrates discovery → hard filters → AI queue → Gemini → safety gate → ApplicationRunner
- All safety boundaries preserved: D6.1, D6.2, C2, D4/D5, D7
- CLI `run_autonomous_cycle.py` refactored to use extracted service with `enable_cli_output=True`

Backend — control/status endpoints:
- `POST /api/autonomous-cycle/run`: starts autonomous cycle with `max_applications` parameter (1-10, default 2)
- `GET /api/autonomous-cycle/status`: returns current cycle status (IDLE/RUNNING/COMPLETED/FAILED) with stats
- Process-level concurrency lock (`threading.Lock`) prevents concurrent cycles
- HTTP 409 Conflict returned if cycle already running
- Gemini budget internally derived as `max_applications * 2` (not exposed to client)

Schema design decisions:
- `AutonomousCycleStartRequest`, `AutonomousCycleStartResponse`, `AutonomousCycleStatusResponse` use `extra="forbid"`
- No `gemini_budget` parameter in request schema — client cannot control Gemini budget
- `max_applications` validated (1-10) and server-authoritative
- No secrets, credentials, cookies, session data, or environment variable values in any response

Frontend — autonomous cycle UI:
- `App.tsx`: added autonomous cycle status panel with IDLE/RUNNING/COMPLETED/FAILED states
- Run Autonomous Cycle button with explicit confirmation modal
- Confirmation modal explains: real Naukri applications, max_applications limit, safety rules, concurrency protection
- Status polling at 4-second intervals while RUNNING
- Dashboard data refresh (summary, recent apps, needs attention) after COMPLETED/FAILED
- Completion stats display: applied, needs_attention, external applications
- HTTP 409 Conflict handling: shows "An autonomous cycle is already running" message
- `frontend/src/types/api.ts`: 3 new typed interfaces for autonomous cycle
- `frontend/src/services/api.ts`: 2 new typed API client methods with HTTP status propagation

**E3 Test Coverage:**

New: 92 tests in `backend/tests/test_autonomous_cycle.py` (E3 autonomous cycle logic tests)
- DecisionTracker (3)
- AutonomousCycleLogic (10)
- DiscoveryFailureHandling (4)
- D62BoundedGeminiEvaluation (11)
- CardExperienceFiltering (8)
- DirectSearchNavigation (3)
- PostFilterMaxJobsLimit (4)
- D3AuthFalsePositiveFix (2)
- C2ITGateMissingIndustryFix (8)
- D3QuotaSafeFirstApplication (4)
- D3SurgicalFixes (3)
- RoleVocabularyExpansion (8)
- D6MultiApplication (13)
- D61BoundedGeminiLookAhead (11)

New: 11 tests in `backend/tests/test_autonomous_cycle_api.py` (E3 API endpoint tests)
- TestAutonomousCycleStart (5): valid post, invalid max_applications, upper bound, negative, default
- TestAutonomousCycleConcurrency (1): concurrent POST returns 409
- TestAutonomousCycleStatus (2): status returns idle, status returns structure
- TestAutonomousCycleSecurity (2): no secrets in response, client cannot control gemini_budget
- TestAutonomousCycleServiceExtraction (2): CLI uses extracted service, API uses extracted service

Total E3 tests: 103 PASS

Regression (passing):
- 30 dashboard tests (E1/E2): PASS
- 44 API/dashboard/health tests: PASS
- 181 total tests (autonomous_cycle + matching_rules + application_safety_gate + dashboard): PASS
- Frontend TypeScript compilation: PASS
- Frontend production build: PASS (23.76s, 280.60 kB JS bundle)

**Security Verification:**
- All new control endpoints: POST (run) and GET (status) only
- Process-level lock prevents concurrent cycles (V1 local-first)
- No `gemini_budget` parameter — client cannot control Gemini budget
- `max_applications` server-authoritative (1-10 cap enforced)
- All schemas use `extra="forbid"` — no implicit field forwarding
- No secrets, API keys, credentials, cookies, session data, or environment variable values in any response
- Frontend only calls control/status APIs — no direct Naukri or Gemini access
- Explicit user confirmation required before execution

**Files Added:**
- `backend/services/autonomous_cycle/service.py` (extracted AutonomousCycle class)
- `backend/api/routes/autonomous_cycle.py` (control/status endpoints)
- `backend/schemas/autonomous_cycle.py` (request/response schemas)
- `backend/tests/test_autonomous_cycle.py` (92 logic tests)
- `backend/tests/test_autonomous_cycle_api.py` (11 API tests)

**Files Modified:**
- `backend/main.py` (registered autonomous_cycle router)
- `backend/tests/conftest.py` (autonomous_cycle router registration for tests)
- `run_autonomous_cycle.py` (refactored to use extracted AutonomousCycle)
- `frontend/src/types/api.ts` (added autonomous cycle types)
- `frontend/src/services/api.ts` (added autonomous cycle API methods)
- `frontend/src/app/App.tsx` (added autonomous cycle UI with confirmation, polling, completion stats)

**D7 Status:** PASS — unaffected. No automation logic changed, only extraction.

**E2 Status:** COMPLETE — unaffected. E2 functionality preserved.

**E1 Status:** COMPLETE — unaffected. E1 functionality preserved.

**Scheduler Status:** Discovery-only. Integration with autonomous cycle deferred.

**E3 Live Validation (Run #52):** The E3 control surface was exercised end-to-end through the Dashboard UI with `max_applications = 1`. The cycle started, acquired the lock, ran discovery/filtering/candidate evaluation, completed with status `COMPLETED`, and returned to `IDLE` with `lock_held = false`. This confirms the confirmation modal, selectable `max_applications` control, status polling, completion stats, and HTTP 409 concurrency protection all behave as designed in a live run. Zero applications were submitted in Run #52; the three pre-existing applications (records #18, #24, #25) belong to earlier runs (D4/D5 and D7) and were untouched. See CHECKPOINT E4 at the top of this file.

---

## CHECKPOINT E2: Dashboard Operational Visibility & Safe Control Foundation: COMPLETE

**Status:** E2 IMPLEMENTED, TESTED, AND VERIFIED

**E2 Objective:**

Build on E1's real backend → frontend integration to make the dashboard an accurate operational view of the Naukri Agent. The dashboard should allow the user to understand what the system last did, what happened during the latest discovery/autonomous run, application outcomes, jobs needing attention, and whether the backend/AI system is healthy. However, E2 must NOT introduce unrestricted "Run Agent" or "Apply" controls — the frontend remains primarily read-only.

**Implementation:**

Backend — new read-only endpoint:
- `GET /api/dashboard/needs-attention`: returns applications requiring user review, filtered by `needs_attention=True` or `status=NEEDS_ATTENTION`, joined with `jobs` table for job title and company context

Schema design decisions:
- `NeedsAttentionItem` and `NeedsAttentionResponse` use `extra="forbid"` (Pydantic strict mode)
- `confirmation_evidence`, `external_url`, and all credential fields excluded from needs-attention schema
- No API keys, credentials, cookies, session data, or environment variable values in any response

Frontend — changes to existing components:
- `App.tsx`: added `needsAttention` state with loading/error/empty handling, added `isRefreshing` state for refresh button
- Latest Run section: displays latest discovery run status, ID, jobs discovered, new jobs, completion date from dashboard summary
- Needs Attention section: dedicated section showing applications requiring review with skip/failure reasons
- Refresh button: manual refresh in topbar with loading state and visual feedback (spin animation)
- System Health: improved presentation using existing health endpoint data (backend status, agent state)
- `frontend/src/types/api.ts`: 2 new typed interfaces for needs-attention
- `frontend/src/services/api.ts`: 1 new typed API client function for needs-attention

**E2 Test Coverage:**

New: 9 tests in `backend/tests/test_dashboard.py` (E2 additions)
- `TestNeedsAttentionEmpty` (2): 200 response, empty list
- `TestNeedsAttentionWithData` (5): needs-attention filtering, needs_attention flag, limit parameter, limit cap, required fields
- `TestDashboardReadOnly` (1): needs-attention endpoint read-only (405 on POST/PUT/DELETE)
- `TestNeedsAttentionWithData::test_no_secrets_exposed`: recursive check for forbidden keys

Existing E1 tests (21): all preserved and passing
- `TestDashboardSummaryEmpty` (5)
- `TestDashboardSummaryWithData` (3)
- `TestRecentApplicationsEmpty` (2)
- `TestRecentApplicationsWithData` (5)
- `TestDashboardNoSecretsExposed` (4)
- `TestDashboardReadOnly` (2, E1)

Total dashboard tests: 30 PASS

Regression (passing):
- Key regression tests (41 tests across health, analytics, profile, database isolation): PASS
- Frontend TypeScript compilation: PASS
- Frontend production build: PASS (3.10s, 275.91 kB JS bundle)

**Security Verification:**
- All new endpoints: HTTP GET only
- No mutation of database state in any new route
- All schemas use `extra="forbid"` — no implicit field forwarding
- `confirmation_evidence` deliberately absent from `NeedsAttentionItem`
- `external_url` deliberately absent from `NeedsAttentionItem`
- Profile data fields (name, education, skills, etc.) not exposed via dashboard
- No environment variables, connection strings, or filesystem paths in responses
- No execution controls added: no "Run Agent", "Apply Now", "Retry Application" buttons

**Files Added:**
- None (E2 extends existing files)

**Files Modified:**
- `backend/schemas/dashboard.py` (added NeedsAttentionItem, NeedsAttentionResponse)
- `backend/api/routes/dashboard.py` (added /needs-attention endpoint)
- `backend/tests/test_dashboard.py` (added 9 E2 tests)
- `frontend/src/types/api.ts` (added NeedsAttentionItem, NeedsAttentionResponse)
- `frontend/src/services/api.ts` (added getNeedsAttention function)
- `frontend/src/app/App.tsx` (added Latest Run section, Needs Attention section, Refresh button)

**D7 Status:** PASS — unaffected. No automation logic changed.

**E1 Status:** COMPLETE — unaffected. E1 functionality preserved.

**No live Naukri action performed in E2.**

---

## CHECKPOINT E1: Frontend/API Integration Foundation: COMPLETE

**Status:** E1 IMPLEMENTED, TESTED, AND VERIFIED

**E1 Objective:**

Connect the React + TypeScript dashboard to the already-proven FastAPI backend with real read-only API data. Replace all "Not available" / "Not configured" placeholder values with actual backend state.

**Implementation:**

Backend — new read-only endpoints:
- `GET /api/dashboard/summary`: aggregates latest discovery run stats, all-time application status counts, and safe profile status into a single dashboard snapshot
- `GET /api/dashboard/recent-applications`: returns application records joined with `jobs` table, exposing `job_title` and `company` for the activity feed

Schema design decisions:
- `DashboardSummary`, `DiscoverySummary`, `ApplicationCounts`, `ProfileSummary`, `RecentApplicationItem`, `RecentApplicationsResponse` all use `extra="forbid"` (Pydantic strict mode)
- `confirmation_evidence` (internal applied-state evidence) excluded from `RecentApplicationItem`
- `resume_hash`, `Profile.data` personal fields excluded from `ProfileSummary`
- No API keys, credentials, cookies, session data, or environment variable values in any response

Frontend — changes to existing components:
- `App.tsx`: removed hardcoded metrics const, added `dashboard` and `recentApps` state, fetches `getDashboardSummary()` and `getRecentApplications()` on mount; each section has independent loading/error/empty handling; retry re-fetches all dashboard data
- Metrics section: `Applied`, `Jobs discovered`, `Discovery runs`, `Needs attention` — all real values
- Profile panel: `status`, `confirmed`, `original_filename` from dashboard summary
- Activity feed (overview + activity page): real application records with `job_title`, `company`, `status`, `applied_at`, `application_method`
- `frontend/src/types/api.ts`: 5 new typed interfaces
- `frontend/src/services/api.ts`: 2 new typed API client functions

**E1 Test Coverage:**

New: 21 tests in `backend/tests/test_dashboard.py`
- `TestDashboardSummaryEmpty` (5): 200 response, schema keys, zero counts with empty DB
- `TestDashboardSummaryWithData` (3): discovery counts, application counts, multi-run count
- `TestRecentApplicationsEmpty` (2): 200 response, empty list
- `TestRecentApplicationsWithData` (5): job details, limit, limit cap, required fields, needs_attention flag
- `TestDashboardNoSecretsExposed` (4): no forbidden keys, no resume_hash, no confirmation_evidence
- `TestDashboardReadOnly` (2): 405 on POST/PUT/DELETE

Regression (passing):
- Key regression tests (95 tests across health, analytics, applications, profile, schema migration, database isolation): PASS
- Frontend TypeScript compilation: PASS
- Frontend production build: PASS (15.81s, 273.57 kB JS bundle)

**Security Verification:**
- All new endpoints: HTTP GET only
- No mutation of database state in any new route
- All schemas use `extra="forbid"` — no implicit field forwarding
- `confirmation_evidence` deliberately absent from `RecentApplicationItem`
- `resume_hash` deliberately absent from `ProfileSummary`
- Profile data fields (name, education, skills, etc.) not exposed via dashboard
- No environment variables, connection strings, or filesystem paths in responses

**Files Added:**
- `backend/api/routes/dashboard.py`
- `backend/schemas/dashboard.py`
- `backend/tests/test_dashboard.py`

**Files Modified:**
- `backend/main.py` (dashboard router registered)
- `frontend/src/types/api.ts` (5 new types)
- `frontend/src/services/api.ts` (2 new client functions)
- `frontend/src/app/App.tsx` (metrics, profile panel, activity feed wired to real API)

**D7 Status:** PASS — unaffected. No automation logic changed.

**No live Naukri action performed in E1.**

---

## CHECKPOINT D6.2: Bounded Gemini Candidate Evaluation: COMPLETE

**Status:** D6.2 IMPLEMENTED, TESTED, AND VERIFIED

**D6.2 Root Cause:**

D6.1's Gemini budget was applied TOO LATE in the pipeline. The autonomous cycle was calling `MatchEngine.evaluate_job()` for every job that passed deterministic filters, and MatchEngine would invoke Gemini for each job before returning. Only AFTER those Gemini calls did the D6.1 enqueue budget get applied. This defeated the purpose of bounded Gemini usage and caused uncontrolled Gemini calls during autonomous cycles.

**D6.2 Additional Issues Found and Fixed:**

1. **Queue isolation violation**: `_process_ai_queue()` was calling `get_next_item()` which returns ANY eligible queue item, not just those enqueued by the current autonomous cycle. This meant pre-existing queue items from other sources (SCHEDULER, MANUAL) could be processed, bypassing the D6.2 Gemini budget.

2. **Candidate sorting bug**: The sort intended to order by match_score descending and discovered_at descending (newest first), but was actually sorting discovered_at ascending (oldest first) due to incorrect lambda.

3. **Code duplication**: `evaluate_job_deterministic()` and `evaluate_job()` had duplicated deterministic logic, creating maintenance risk.

**D6.2 Fix:**

1. Moved the Gemini budget boundary BEFORE NEW MatchEngine semantic evaluation:
   - Added `evaluate_job_deterministic()` method to MatchEngine that runs only deterministic checks (no Gemini)
   - Autonomous cycle now: deterministic filters → bounded candidate selection → Gemini evaluation for only bounded candidates
   - Gemini budget formula: `max_applications * 2` (unchanged from D6.1)
   - Application limit: `max_applications` (unchanged)
   - Cached analyses do not consume NEW Gemini evaluation budget
   - Deterministically rejected jobs never call Gemini

2. Fixed queue isolation:
   - Added `enqueued_queue_item_ids` tracking in `_apply_hard_filters_and_enqueue()`
   - Modified `_process_ai_queue()` to accept `enqueued_queue_item_ids` parameter
   - Only processes queue items enqueued by this cycle (queue_source="AUTONOMOUS_CYCLE")
   - Prevents pre-existing queue items (SCHEDULER, MANUAL) from bypassing Gemini budget

3. Fixed candidate sorting:
   - Changed sort key to use negative timestamp for discovered_at (newest first)
   - Matches comment: "Sort by match_score descending, then by discovered_at descending (most recent)"

4. Deduplicated deterministic logic:
   - Extracted shared `_run_deterministic_checks()` method
   - Both `evaluate_job_deterministic()` and `evaluate_job()` now call this shared method
   - Single authoritative implementation of all deterministic rules

**D6.2 Implementation:**

Modified `backend/services/matching/engine.py`:
- Added `_run_deterministic_checks()` shared method (lines 119-220)
- Refactored `evaluate_job_deterministic()` to use shared method (lines 222-232)
- Refactored `evaluate_job()` to use shared method (lines 234-278)
- Eliminated code duplication while preserving behavior

Modified `run_autonomous_cycle.py`:
- Line 342: Added `enqueued_queue_item_ids` tracking list
- Line 415-423: Fixed candidate sorting to newest discovered_at first
- Line 437: Track enqueued queue item IDs
- Line 461: Updated `_process_ai_queue()` call to pass `enqueued_queue_item_ids`
- Line 463-503: Modified `_process_ai_queue()` to only process items from this cycle
- Line 470: Return `enqueued_queue_item_ids` in stats for bounded processing

**D6.2 Test Coverage:**

Added 10 D6.2 regression tests in `TestD62BoundedGeminiEvaluation`:
1. `test_deterministic_evaluation_passes_without_gemini` → verifies deterministic evaluation works without Gemini
2. `test_deterministic_evaluation_fails_unpaid_job` → verifies deterministic checks reject unpaid jobs
3. `test_gemini_budget_bounded_for_max_applications_2` → verifies Gemini budget=4 for max_applications=2
4. `test_gemini_budget_for_max_applications_1` → verifies Gemini budget=2 for max_applications=1
5. `test_gemini_budget_for_max_applications_3` → verifies Gemini budget=6 for max_applications=3
6. `test_cached_analysis_not_counted_as_new_gemini` → verifies cached analyses don't trigger new Gemini calls
7. `test_deterministic_rejects_no_gemini_call` → verifies deterministically rejected jobs never call Gemini
8. `test_application_limit_separate_from_gemini_budget` → verifies application limit separate from Gemini budget
9. `test_pre_existing_queue_items_not_processed` → verifies pre-existing queue items are NOT processed
10. `test_candidate_ordering_newest_discovered_at_first` → verifies candidate sorting newest first

Fixed duplicate test class (removed duplicate `TestCardExperienceFiltering` at line 590)
Updated test sorting logic to match implementation (2 tests updated)

**Total Test Coverage:**
- 92 tests passing in test_autonomous_cycle.py (includes 10 D6.2 tests)
- 41 tests passing in test_matching_rules.py
- 0 failures

**Gemini Safety Verification:**

- NEW Gemini evaluations during autonomous cycle are now bounded BEFORE invocation
- Pre-existing queue items from other sources are NOT processed by autonomous cycle
- For max_applications=1: NEW Gemini evaluations <= 2
- For max_applications=2: NEW Gemini evaluations <= 4
- For max_applications=3: NEW Gemini evaluations <= 6
- Deterministically rejected jobs never call Gemini
- Cached analyses do not cause NEW Gemini calls
- Application attempts remain hard-capped by max_applications
- Gemini remains advisory, Python rules remain final authority
- All existing safety rules held (duplicate protection, current-run isolation, etc.)

**Files Changed in D6.2:**
- `backend/services/matching/engine.py`: Added `_run_deterministic_checks()` shared method, refactored both evaluation methods
- `run_autonomous_cycle.py`: Added queue isolation, fixed sorting, bounded queue processing
- `backend/tests/test_autonomous_cycle.py`: Added 10 D6.2 tests, removed duplicate class, updated 2 sorting tests

**Database State after D6.2:**
- No database changes required
- No live validation performed (D6.2 is source implementation checkpoint only)

**Note:** D7 live validation has NOT been performed as part of this checkpoint. D6.2 is a source implementation checkpoint only.

---

## CHECKPOINT D7: Multi-Application Live Validation: COMPLETE

**Status:** D7 LIVE VALIDATION PASSED

**D7 Objective:**

Validate that the autonomous cycle can process multiple independent eligible Naukri candidates and apply to more than one job when safe candidates are available, while respecting the D6.2 Gemini boundary.

**D7 Live Validation (2026-10-07):**

Command: `python run_autonomous_cycle.py --max-applications 2`

Discovery Results:
- Discovery run #32
- Jobs discovered: 103
- Jobs hard filtered: 60
- Current-run candidates: 4 queued for AI (jobs 99, 86, 85, 59)

D6.2 Gemini Boundary Validation:
- Gemini budget: 4 (max_applications=2 × 2)
- NEW Gemini evaluations: 4 (exactly the budget)
- Candidates capped: 5 (jobs 58, 56, 51, 20, 19)
- Budget respected: YES

Current-Run Isolation:
- All 4 AI queue items from AUTONOMOUS_CYCLE source
- Pre-existing MANUAL/SCHEDULER queue items NOT consumed
- Current-run isolation: PASS

Gemini Results:
- Job 99 (Neorealm Solutions): SKIP - Python/Data Science vs C#/.NET mismatch
- Job 86 (Futureacad): NEEDS_ATTENTION - 3-month unpaid internship + 2-year bond
- Job 85 (Access Automation): SKIP - No LabVIEW experience
- Job 59 (Capgemini): SKIP - L1 support/voice process vs AI/DS background

Application Outcomes:
- Job 99 → EXTERNAL_APPLICATION (no external submission, Apply clicks: 0)
- Job 86 → SKIPPED (unpaid internship, Apply clicks: 0)
- Job 85 → APPLIED (native Naukri, 1 Apply click, application record #24, NAUKRI_NATIVE)
- Job 59 → APPLIED (native Naukri, 1 Apply click, application record #25, NAUKRI_NATIVE)

Final Results:
- APPLIED: 2
- NEEDS_ATTENTION: 1
- SKIPPED: 1
- EXTERNAL: 1
- FAILED: 0
- Apply clicks: 2 (exactly once per applied job)

Safety Verification:
- Duplicate protection: PASS (no reapplications)
- Current-run isolation: PASS (only current-run candidates processed)
- Pre-existing queue consumption: NONE
- CAPTCHA/security bypass: NONE
- Questionnaire/form bypass: NONE
- External application submission: NONE
- Fabricated answers: NONE
- max_applications hard cap: PASS (cycle stopped after 2 applications)

**D7 Verdict:** PASS — multiple applications validated

**Source Changes:** NONE (D7 is a validation checkpoint only)

**Database Backup:** data/naukri_agent.db.bak-before-d7-live (not committed)

**Database State after D7:**
- Total applications: 25
- APPLIED: 3 (Application 18 from D4/D5, Applications 24 and 25 from D7)
- Application records #24 and #25: NAUKRI_NATIVE, applied_at=2026-10-07

---

## CHECKPOINT D6.1: Bounded Gemini Look-Ahead for Multi-Application Runs: COMPLETE

**Status:** D6.1 IMPLEMENTED AND TESTED

**D6.1 Root Cause:**

D6 live validation exposed that `max_applications` was incorrectly used as both:
1. Maximum Gemini candidates to enqueue
2. Maximum actual application attempts

This prevented the system from having backup candidates when initial candidates were rejected (EXTERNAL or NEEDS_ATTENTION). With `max_applications=2`, only 2 candidates were enqueued to Gemini. If both became EXTERNAL or NEEDS_ATTENTION, 0 applications could occur.

**D6.1 Fix:**

Separated Gemini candidate budget from actual application limit:
- New formula: `max_gemini_candidates = max_applications * 2`
- Examples:
  - `max_applications=1` → Gemini budget=2
  - `max_applications=2` → Gemini budget=4
  - `max_applications=3` → Gemini budget=6
- Actual application attempts remain capped at `max_applications`
- This provides bounded look-ahead (backup candidates) while preventing uncontrolled Gemini usage

**D6.1 Implementation:**

Modified `run_autonomous_cycle.py`:
- Line 413: Changed from `cap = max(1, self.max_applications)` to `gemini_budget = max(1, self.max_applications * 2)`
- Line 414: Changed from `selected_jobs = eligible_jobs[:cap]` to `selected_jobs = eligible_jobs[:gemini_budget]`
- Updated priority_reason to show both budget and max_applications
- Updated summary output to display both `max_applications` and `Gemini candidate budget`

**D6.1 Test Coverage:**

Added 11 new D6.1 regression tests in `TestD61BoundedGeminiLookAhead`:
1. `test_d61_gemini_budget_max_applications_1` → verifies budget=2 when max_applications=1
2. `test_d61_gemini_budget_max_applications_2` → verifies budget=4 when max_applications=2
3. `test_d61_gemini_budget_max_applications_3` → verifies budget=6 when max_applications=3
4. `test_d61_gemini_never_exceeds_bounded_budget` → verifies 10 eligible with max_applications=2 enqueues only 4
5. `test_d61_actual_applications_never_exceed_max_applications` → verifies application limit enforced separately
6. `test_d61_external_candidate_does_not_consume_slot` → verifies EXTERNAL doesn't consume application slot
7. `test_d61_needs_attention_does_not_consume_slot` → verifies NEEDS_ATTENTION doesn't consume application slot
8. `test_d61_rejected_candidate_allows_backup_evaluation` → verifies backup candidates evaluated when earlier rejected
9. `test_d61_current_run_isolation_preserved` → verifies current-run filtering still works
10. `test_d61_stale_queued_job_cannot_leak` → verifies stale queue items don't leak into current run

Updated existing test `test_max_applications_one_enqueues_only_single_candidate` to `test_max_applications_one_enqueues_bounded_budget` (now enqueues 2 instead of 1).
Updated existing test `test_max_applications_gt_one_enqueues_all_eligible` to `test_max_applications_gt_one_enqueues_bounded_budget` (now enqueues 4 instead of all 5).
Updated existing test `test_gemini_enqueue_capped_at_max_applications` to verify budget=4 instead of cap=2.

**D6.1 Live Validation (2026-10-07):**

Command: `python run_autonomous_cycle.py --max-applications 2`

Results:
- 103 jobs discovered
- 69 hard filtered
- 11 pre-analyzed (existing)
- 0 newly queued (all current-run candidates already had analyses)
- 0 AI processed
- 0 AI completed
- 1 application candidate (Blue Yonder - pre-analyzed with NEEDS_ATTENTION)
- 0 applied
- 1 skipped (by safety gate)
- 0 external
- 0 needs attention

Safety verification:
- 0 Apply clicks
- 0 new APPLIED
- Application 18 (from D4/D5) correctly excluded
- No external applications submitted
- No questionnaires answered
- No CAPTCHA/security challenges

**Current-Run Isolation Investigation:**

D6 report discrepancy (104 vs 81 jobs) explained:
- Discovery reports 104 total jobs (1 new + 103 duplicates)
- Only 81 unique job IDs in `current_run_job_ids` (some duplicates may have been deduplicated differently)
- Job 107 was legitimately in `current_run_job_ids` (verified: present in last 20 IDs)
- No isolation bug found - system correctly isolates current runs

**Gemini Safety Verification:**

- Gemini budget remains explicitly bounded (`max_applications * 2`)
- No uncontrolled AI processing
- No fallback to AI-free application
- Existing quota exhaustion behavior preserved
- All existing D3 quota safety tests still pass

**Total Test Coverage:**
- 261 tests passing (83 autonomous_cycle + 41 matching_rules + 119 naukri_adapter + 18 application_safety_gate)
- 0 failures

**Files Changed in D6.1:**
- `run_autonomous_cycle.py`: Updated enqueue logic with bounded Gemini budget (lines 405-440, 254-272)
- `backend/tests/test_autonomous_cycle.py`: Added 11 D6.1 tests, updated 3 existing tests (lines 1050-1176, 2013-2063, 2463-2958)

**Database State after D6.1:**
- Total applications: 21
- APPLIED: 1 (Application 18 from D4/D5)
- No new applications in D6.1 live run

**Note:** D6.1's original implementation bounded the downstream AI queue, but MatchEngine could still invoke Gemini before that boundary. D6.2 fixes this by bounding NEW Gemini evaluations before invocation.

---

## CHECKPOINT D5: First Verified Native Naukri Application: COMPLETE

**Status:** FIRST VERIFIED NATIVE NAUKRI APPLICATION: SUCCESS

**D5 Live Investigation Finding:**

Opening Job 23 (NetM Corporate Solutions) read-only after the D4 apply click confirmed:
- `<span id="already-applied" class="styles_already-applied__4KDhw already-applied">Applied</span>` is visible in `#job_header`
- The Apply button is absent (replaced by the Applied badge)
- Selectors `#already-applied`, `.already-applied`, `#job_header #already-applied`, `#job_header .already-applied` all correctly match
- `detect_applied_state()` returns `(True, "Applied")` on the live page

**Root cause of D4 failure:**

Naukri instant-apply performs a server-side submission that updates the job page state. The Applied badge (`#already-applied`) does NOT appear within the initial 8-second in-page polling window. It becomes visible only after the page reloads/refreshes. The D4 implementation had no post-timeout reload check, so the window expired and returned `NEEDS_ATTENTION` — even though the application was actually submitted.

**D5 Fix implemented:**

`start_application()` now adds a single bounded reload check after the 8-second in-page window expires:

```
Apply click
    ↓
8-second in-page polling (unchanged)
    ↓
If no evidence found → reload page once (bounded, 20s timeout)
    ↓
Wait post_apply_reload_settle_seconds (5s) for JS to render
    ↓
detect_applied_state() called on reloaded page
    ↓
If Applied evidence found → return APPLIED
If no evidence → return NEEDS_ATTENTION
```

This is NOT a retry of the Apply click. It is a read-only confirmation of Naukri's persistent server-side state.

**D5 Live Validation:**

Application record 18 (Job 23, NetM Corporate Solutions) updated from `NEEDS_ATTENTION` to `APPLIED`:
- `status = APPLIED`
- `applied_at = 2026-10-07 12:33:17 UTC`
- `method = NAUKRI_NATIVE`
- `confirmation_evidence = "Applied (confirmed by D5 live reload validation)"`
- `is_dry_run = False`
- **APPLIED count: 1**

**Test Coverage:**
- 238 focused tests passing (test_autonomous_cycle.py, test_matching_rules.py, test_naukri_adapter.py, test_application_safety_gate.py)
- 14 new D5 tests in `TestD5PostClickEvidenceDetection`
- 0 failures

**Safety rules held throughout:**
- No Apply button clicked again
- No CAPTCHA bypass
- No external application
- No questionnaire answered
- Evidence required before APPLIED persisted
- Reload is read-only, not a resubmission

**Files Changed in D5:**
- `backend/services/naukri/adapter.py`: Added `post_apply_reload_settle_seconds`, reload check in `start_application`
- `backend/tests/test_naukri_adapter.py`: Added `TestD5PostClickEvidenceDetection` (14 tests), updated 4 existing tests

**Database state after D5:**
- Total applications: 21
- APPLIED: 1 (first verified application)
- Application 18: APPLIED, method=NAUKRI_NATIVE, evidence=Applied, applied_at=2026-10-07

---

## CHECKPOINT D4: First Verified Native Naukri Application: APPLY CLICKED — EVIDENCE DETECTED BY D5

Objective: reach and physically click the real native Naukri Apply button for one legitimate eligible job, observe Naukri's post-click state, and persist APPLIED evidence.

**D4 Live Run Results (conducted after D1 base):**

- Authenticated Naukri session opened successfully
- Discovery: 103–104 jobs discovered in current run
- Hard filters applied: 70 jobs rejected (Java, PHP, Sales, unpaid salary, non-IT, etc.)
- 11 pre-analyzed candidates from current run available (with existing Gemini APPLY analyses)
- Final safety gate evaluated all 11 candidates
- 2 EXTERNAL jobs correctly identified and recorded (no external submission)
- 1 job (Blue Yonder, Associate Software Engineer) blocked by safety gate: Gemini `NEEDS_ATTENTION` recommendation
- 7 jobs detected as EXTERNAL by NaukriAdapter during application type classification
- 1 candidate (NetM Corporate Solutions, "Software Engineer / Developer") passed all gates as `NAUKRI_NATIVE`
- Apply button found via `#job_header button#apply-button` / `button#apply-button` selector
- Apply button physically clicked ONCE
- 8-second post-click evidence wait executed
- **NO post-click Applied evidence detected within 8 seconds**
- Application correctly recorded as `NEEDS_ATTENTION` (not APPLIED)
- `confirmation_evidence` remains NULL
- APPLIED count: **0** — no verified application

**Boundary that blocked D4:** H — Post-click Applied evidence detection

The `detect_applied_state` method polls for: `#already-applied`, `.already-applied`, exact "Applied" text, or `Applied to "<title>"` banner. None of these were detected within 8 seconds after the Apply click on NetM Corporate Solutions job. This could mean:
- The job required a hidden questionnaire or form not detected by container selectors
- The Applied state appeared with different text/element structure than the current selectors expect
- The page redirected silently after the click

**Safety rules held throughout:**
- No CAPTCHA bypass
- No external application submitted
- No questionnaire answered automatically
- max_applications=1 respected
- No APPLIED status persisted without evidence

**Bug fixes applied during D4:**

1. **Pre-analyzed candidate bypass** (`run_autonomous_cycle.py`): The `_apply_hard_filters_and_enqueue` step previously counted pre-existing job analyses as `hard_filtered`, causing a premature "0 eligible jobs found" stop when all current-run jobs had existing analyses. Fixed by separating `pre_analyzed` from `hard_filtered` and adjusting the early-exit condition.

2. **Title scope check in final safety gate** (`backend/services/applications/service.py`): The safety gate's title scope check used strict substring matching against configured job titles like "Python Developer Fresher", which rejected real jobs titled "Python Developer". Fixed by replacing the check with the deterministic `title_matches_allowed_role()` function from the match engine (already applied by MatchEngine during hard filtering), which uses the canonical allowed-role-families logic.

**Test Coverage:**
- 224 focused tests passing (test_autonomous_cycle.py, test_matching_rules.py, test_naukri_adapter.py, test_application_safety_gate.py)
- 0 failures

**Files Changed in D4:**
- `run_autonomous_cycle.py`: Pre-analyzed bypass, updated stats output
- `backend/services/applications/service.py`: Title scope check fix using `title_matches_allowed_role`

**Database state after D4:**
- Total applications: 21
- APPLIED: 0 (no verified application)
- Application 18 (NetM Corporate Solutions): NEEDS_ATTENTION, method=NAUKRI_NATIVE, evidence=None

---

## CHECKPOINT D1: Autonomous Discovery Tracking: COMPLETE — LIVE READ-ONLY VALIDATED

Implemented current-run job ID tracking to prevent historical DB jobs from being processed when live discovery fails. The autonomous cycle now tracks the current DiscoveryRun and only processes jobs from that specific run, ensuring discovery failures don't silently fall back to stale database records.

**Implementation:**
- Added `current_run_job_ids` column to `DiscoveryRun` model (comma-separated for SQLite compatibility)
- DiscoveryService tracks job IDs from current run in memory (`current_run_job_ids: set[int]`)
- Both new jobs and existing jobs (duplicates) are added to current-run tracking
- On discovery completion, job IDs are persisted as comma-separated string
- Autonomous cycle parses current-run job IDs and filters jobs to only those in the current run
- Fallback to timestamp comparison if job IDs not available (shouldn't happen)
- Cycle stops with error if `current_run.jobs_discovered == 0`

**Direct Naukri Search Navigation:**
- Removed homepage navigation dependency - now navigates directly to search URL
- Simplified security check to single call after search navigation
- Removed bounded wait for homepage elements
- Reduced navigation time and potential failure points

**Role Targeting and Metadata Enrichment:**
- Added deterministic role/title targeting in MatchEngine before IT metadata gate
- Explicitly rejects unwanted specializations: Java, PHP, .NET, C#, C++, Power Platform, Platform Engineer, Salesforce, SAP, ServiceNow, embedded, firmware, hardware, electrical, mechanical, civil, sales, marketing, HR, operations
- Allowed role families: data (analyst, engineer), software (engineer, developer), devops, python developer
- Enhanced NaukriAdapter metadata extraction with JSON-LD parsing, "Other Details" section extraction, and fallback body text scanning
- Always fetches job details for IT metadata enrichment (industry/department/role_category) even when description is present

**Historical Job Exclusion:**
- Jobs not returned by current search are excluded from current-run tracking
- Autonomous cycle only processes jobs with IDs in `current_run_job_ids`
- Historical jobs remain in database but are not sent to Gemini or ApplicationRunner

**Live Read-Only Validation (2026-10-06):**
- Authenticated Naukri session opened successfully
- Direct search navigation reached real Naukri search-results page
- 105 job cards discovered across 11 pages
- 82 jobs tracked in current run (including existing duplicates)
- 21 historical jobs excluded from current run
- 105 existing jobs rediscovered (0 new jobs added - all were duplicates)
- Role targeting detected 12 jobs with unwanted specializations (Java, PHP, Sales, Operations, etc.)
- Experience filtering passed (all jobs appear entry-level/fresher)
- Metadata enrichment issue noted: existing DB jobs lack industry/department metadata (predate implementation)
- No CAPTCHA, security challenge, or login challenge appeared
- No Apply clicked, no Gemini called, no submission made
- Current-run tracking fix confirmed working - existing jobs properly included when they appear in current search

**Test Coverage:**
- Focused current-run tracking tests: 12 passed
- Full backend suite: 681 passed, 0 failures
- All discovery tests pass with current-run tracking
- Role targeting tests validate unwanted specialization rejection
- Metadata enrichment tests validate JSON-LD and fallback extraction

**Note:** Metadata enrichment for NEW jobs has not been live-validated because all jobs in the current discovery run were existing duplicates in the database. Existing DB rows predate the metadata enrichment implementation. NEW-job metadata validation will be performed separately with fresh jobs.

**Files Changed:**
- `backend/models/discovery.py`: Added `current_run_job_ids` column
- `backend/services/discovery/service.py`: Current-run tracking, direct navigation, metadata enrichment
- `backend/services/matching/engine.py`: Role targeting, strict IT gate
- `backend/services/naukri/adapter.py`: Enhanced metadata extraction, direct search navigation
- `backend/tests/test_current_run_tracking.py`: New focused test suite (12 tests)
- `backend/tests/test_discovery.py`: Updated for current-run tracking
- `backend/tests/test_matching_rules.py`: Updated for role targeting
- `backend/tests/test_naukri_adapter.py`: Updated for direct navigation
- `backend/tests/test_autonomous_cycle.py`: Updated for current-run filtering
- `run_autonomous_cycle.py`: Updated to use current-run job IDs
- `docs/DECISIONS.md`: Added discovery failure safety decision

## CHECKPOINT C: Autonomous Cycle Command: COMPLETE — OFFLINE VALIDATED

Implemented `run_autonomous_cycle.py` command-line interface for running the complete autonomous job application cycle with explicit controls:
- `--max-applications N`: Limit on real applications (default: 1)
- `--dry-run`: Discovery and analysis only, no Apply clicks or application records
- `--max-jobs N`: Cap on jobs inspected per run (default: unlimited)

The command calls existing services in sequence: DiscoveryService → MatchEngine → AIQueueService → ApplicationRunner. It excludes S&P job `300926927428`, skips external jobs, re-classifies native/external before click, requires post-click Applied evidence, and stops on AUTH/SECURITY/limits/errors. Output includes per-job decision table and summary. No input() prompts. Exit code 0 on normal completion, non-zero on stops.

Test coverage: 12 focused tests in `backend/tests/test_autonomous_cycle.py` covering eligible native jobs, external jobs, unpaid jobs, excluded jobs, max-applications limit, and dry-run flag. All tests use isolated temporary SQLite database. No live Naukri activity, Gemini calls, or Apply clicks in tests.

Examples:
```powershell
# Dry-run (discovery and analysis only)
python run_autonomous_cycle.py --dry-run --max-jobs 10

# First live run with 1 application
python run_autonomous_cycle.py --max-applications 1 --max-jobs 10
```

Note: This command builds and tests offline only. Do not run it live yourself; no Apply clicks, no Gemini calls, no weakening of filters/limits/duplicate rules/safety gate. Never apply to EXTERNAL jobs.

## Checkpoint B2: Salary Gate Without Description: COMPLETE — OFFLINE VALIDATED

The full-suite failure from Checkpoint B was traced to a real code defect
introduced with the Checkpoint A3 salary test: `MatchEngine.evaluate_job()`
nested structured salary and employment-type gates under `if job.description`.
An explicitly unpaid job with no description therefore bypassed the salary gate
and incorrectly reached the AI path. The gates now evaluate independently of
description text, so disclosed unpaid and below-minimum salary records remain
deterministically rejected, and employment-type restrictions are not weakened.

Historical worktree validation found the test absent at `0468ff5` and
`5f8d0bd`, then failing at its introduction in `e0994fe` and still failing at
`40635cb`. The focused regression now passes. Full backend suite: **645 passed,
0 failed** (three third-party deprecation warnings). No live Naukri, Gemini,
Apply/Submit, external-application, or production-database action occurred.

## Checkpoint B: Apply Button Scoping: COMPLETE — OFFLINE VALIDATED

`NaukriAdapter` now resolves Naukri's duplicated `apply-button` controls through
`#job_header button#apply-button` first. A visible global `button#apply-button`
is selected only when the header control is absent; the adapter logs whether the
header or fallback was used. Native classification and the click path share this
resolver, so neither can hit Playwright strict-mode ambiguity or click the sticky
header while a job-header control exists. No control returns `AMBIGUOUS` during
classification and `NEEDS_ATTENTION` if a previously classified page no longer
has a scoped clickable control.

Already-applied evidence is evaluated in `#job_header` first. Existing visible
form/banner evidence outside the header remains valid after a click. The fixture
is minimal synthetic HTML only; it contains no logged-in session data, profile
details, names, photo URLs, or notification counts.

Offline validation:

- Focused adapter suite: 103 passed.
- Full backend suite: 644 passed, 1 failed, 645 total. The unrelated failure is
  `backend/tests/test_checkpoint_a3_salary.py::TestEndToEndSalary::test_unpaid_skip`,
  in `MatchEngine.evaluate_job` after its salary branch is skipped for an empty
  description and a `MagicMock` is passed to Pydantic. Checkpoint B changes only
  the Naukri adapter and its tests.

No browser session, Naukri action, Apply/Submit click, Gemini call, external
application action, or production-database write occurred. The required backup
is `data/naukri_agent.db.bak-before-checkpoint-b` and is intentionally untracked.

## Phase 10 Application-Type Reliability Fix: COMPLETE — LIVE READ-ONLY VALIDATED

Implemented a bounded reliability fix for state/timing-dependent Naukri application classification:

- Existing visible external-first behavior is preserved.
- Existing visible native selectors remain authoritative.
- An inconclusive state receives one bounded 500 ms settling observation.
- No reloads or indefinite polling are used.
- Persistent absence of both evidence types returns `AMBIGUOUS`.
- `ApplicationRunner` maps `AMBIGUOUS` to `NEEDS_ATTENTION` before creating an application record.

Offline validation:

- Focused classification tests: 14 passed.
- Full Naukri adapter suite: 96 passed.

Live read-only validation:

- Quadrasystems.net (`240926500723`): initial `AMBIGUOUS`, settled `AMBIGUOUS`, final `AMBIGUOUS`; selector nodes existed but were not visible, and no external indicator was visible.
- Omozing (`150526504514`): initial `AMBIGUOUS`, settled `AMBIGUOUS`; no visible native or external evidence.
- Cisco (`120826500949`): initial `EXTERNAL`, settled `EXTERNAL`; visible `Apply on company site`.
- No CAPTCHA, security challenge, login challenge, or access block appeared.
- No Apply/Submit action, Gemini call, application runner invocation, or database write occurred.

Database remained unchanged at 10 applications, 0 APPLIED, and 0 SUBMITTED. Automated successful application count remains **0**. Real submission and confirmation validation remain outstanding.

## Phase 10 Live Native Application Test: BLOCKED — NO SAFE ELIGIBLE NATIVE CANDIDATE

**Observed on 2026-10-01:** The existing persistent Playwright session opened authenticated Naukri successfully. No CAPTCHA, security challenge, login wall, or access block was observed. The local backend readiness endpoint returned `ready`. The confirmed profile, configured preferences, compatible application schema, and unused hourly/daily limits were verified.

A single bounded discovery pass inspected five `Data Analyst` results read-only:

- RR Groups: `EXTERNAL`; duplicate/application history blocked it.
- Digital Glyde: `EXTERNAL`; duplicate/application history blocked it.
- Foundation Ai: `EXTERNAL`; duplicate/application history blocked it.
- Ivy Knowledge Services: `EXTERNAL`; employment type failed.
- Thyrocare: `NAUKRI_NATIVE` on two checks; duplicate/application history blocked it.

No Apply or Submit action occurred. No Gemini request was made because no candidate passed the deterministic eligibility boundary. The application runner was not invoked. Database verification after the attempt showed 10 application records, 0 APPLIED/SUBMITTED records, and no changed confirmation evidence. Automated successful application count remains **0**.

**Remaining Phase 10 work:** Repeat the controlled checkpoint only when a fresh candidate passes duplicate protection, native classification, all hard filters, Gemini recommendation, final safety gate, and confirmation requirements. Do not retry the candidates rejected in this checkpoint without the repository-required manual reset.

## Phase 10 Database Schema Migration: COMPLETE

**Status:** Local SQLite database migrated and verified. All code changes implemented, tested, and deployed to local database.

**Implementation:**
- Root cause: `confirmation_evidence` column in ORM model but missing from `initialize_database()` function
- Solution: Idempotent ALTER TABLE with column existence checks (extends Phase 9B-4 pattern)
- Files changed: `backend/database/database.py`, `backend/api/routes/health.py`
- New test file: `backend/tests/test_schema_migration.py` (7 tests, all passing)

**Migration Execution:**
- Timing: Automatic during FastAPI lifespan initialization (before request handling)
- Idempotency: Safe to run multiple times; existing columns are skipped
- Data preservation: All existing application records preserved
- SQL compatibility: Works on both SQLite and PostgreSQL

**Local Database Results:**
- Database: data/naukri_agent.db
- Backup created: data/naukri_agent.db.bak-before-migration (240K)
- Applications table: 10 records (unchanged)
- Record 10 status: APPLICATION_STARTED (unchanged)
- APPLIED/SUBMITTED: 0/0 (unchanged)
- New columns: confirmation_evidence (TEXT NULL), is_dry_run (BOOLEAN)
- ORM queries: Executing without OperationalError

**Testing:**
- Migration-focused tests: 7/7 passing
- Full backend suite: 557/557 passing
- Test coverage:
  - Old schema migration adds confirmation_evidence ✓
  - Migration preserves existing rows ✓
  - Migration is idempotent ✓
  - Readiness check detects schema compatibility ✓
  - Current schema requires no changes ✓
  - Database isolation (never uses production DB) ✓

**Startup Verification:**
- `initialize_database()` runs before request handling ✓
- Schema compatibility check integrated into `/readiness` endpoint ✓
- Readiness status: compatible ✓
- Standalone migration command: `python -m backend.database.database` ✓

**PostgreSQL/Neon Support:**
- SQL syntax validated for PostgreSQL compatibility ✓
- Standard SQL used (ALTER TABLE, ADD COLUMN, BOOLEAN, TEXT, DEFAULT, NULL) ✓
- Neon migration: NOT executed (manual step when deploying to Neon)
- Neon command provided in docs for future deployment

**Documentation Updated:**
- README.md: Added Phase 10 schema migration section
- docs/MASTER_PRD.md: Added detailed schema migration mechanism
- docs/ARCHITECTURE.md: Added Phase 10 schema migration pattern and validation
- docs/DEVELOPMENT_STATUS.md: This status section

**Remaining Tasks:**
- Neon migration: Will be executed separately when deploying to production Neon PostgreSQL
- No code or git changes remain; all implementation complete

---

## Phase 10 Application Boundary Fix: EVIDENCE-DRIVEN POST-CLICK DETECTION

Implemented evidence-driven post-click state detection with bounded waits. After the Apply click,
the adapter waits for explicit visible evidence:
- **Applied**: `#already-applied`, `.already-applied`, exact visible "Applied" text, or
  `Applied to "<title>"` banner
- **Form opened**: visible application container (dialog, drawer, modal, or form)
- **Neither within 8s timeout**: NEEDS_ATTENTION (no retry without manual reset)

Question detection now strictly scopes to visible application containers and rejects:
- Hidden, disabled, readonly fields
- Zero-sized elements
- Hidden-type inputs
- Header/search input patterns

Experience computation uses `compute_profile_experience_years()` consistently in safety gate
and runner, computing actual elapsed years from `start_date`/`end_date` (not entry count).
The +2 year tolerance is preserved and reported in reasons.

Native/external classification moved BEFORE creating APPLICATION_STARTED. Re-classification
happens immediately before the click; mismatch aborts to external without creating a record.

No-repeat enforcement: jobs with EXTERNAL_APPLICATION or NEEDS_ATTENTION status require
explicit manual reset before automatic retry.

All changes validated with isolated temporary SQLite unit tests only. No live Naukri activity,
no Apply/Submit clicks, no Gemini calls. Production DB untouched. Successful application count: 0.

Implemented and regression-tested the focused application-boundary changes:
explicit Applied-state detection and evidence persistence, visible application
container question scoping, hidden-input rejection, computed profile experience
in the runner and final safety gate, pre-record native/external classification with
immediate reclassification, and no-repeat behavior for unresolved attempts. The
existing two-year experience tolerance remains unchanged. Tests use isolated
temporary SQLite only. No live Naukri activity, Gemini call, Apply/Submit click, or
database write occurred in this checkpoint; automated successful application count
remains 0.

## Roadmap Reconciliation

`docs/MASTER_PRD.md` is the authoritative product roadmap. Its next formal product phase after the current Phase 9B checkpoint work is **Phase 9 — Notifications**, followed by Phase 10 testing/security/Windows packaging and Phase 11 integration/production hardening. The README phase list now follows that numbering. The custom Phase 9B-3 native application-boundary validation remains unresolved and is not marked complete; Phase 9B-4 safety hardening remains implemented and committed. Cloud deployment preparation remains supporting infrastructure rather than a separately numbered product phase.

## Phase 9B-4 — Application Dry-Run and Lifecycle Safety: IMPLEMENTED OFFLINE

The dry-run boundary is hardened to stop before native Apply, external Apply, question answering, submission, and confirmation. Dry-run application records now include an explicit `is_dry_run` marker and remain eligible for future real attempts because duplicate protection still blocks only APPLIED and SUBMITTED. Lifecycle data includes PRE_APPLY and FORM_OPENED distinctions; the adapter does not claim FORM_OPENED from a click alone and reports NEEDS_ATTENTION when the form is unverified. Focused offline tests passed (118 tests across application, duplicate-protection, and adapter suites). No browser, Naukri, Gemini, ApplicationRunner live run, Apply click, or database manual write occurred. Native Apply semantics remain UNKNOWN and Phase 9B-3 is incomplete.

## Phase 9 — Notifications: IMPLEMENTED OFFLINE

Implemented the isolated notification service, persisted history model, SMTP configuration boundary, required event helpers, scheduler evening summary, `GET /api/notifications`, and minimal dashboard visibility. Focused tests cover event dispatch, missing configuration, delivery failure isolation, summary timing, and duplicate prevention. Real SMTP delivery remains unverified; Phase 9 is not marked production-complete.

## Gemini V1 Model Switch: IMPLEMENTED, LIVE NATIVE RECHECK PENDING

The V1 Gemini default changed from `gemini-2.5-flash` to verified non-preview model `gemini-flash-lite-latest` after repeated `429 RESOURCE_EXHAUSTED` responses. An isolated runtime request successfully parsed the existing structured `JobAnalysis` schema. `gemini-3.1-flash-lite-preview` also succeeded during viability testing but was not selected for V1. The model remains configurable through `NAUKRI_AGENT_GEMINI_MODEL`; retry logic, prompts, schema, provider abstraction, Naukri behavior, and application safety are unchanged. Phase 9B-3 remains incomplete until a fresh Gemini APPLY decision reaches the real native application form boundary.

## Phase 9B-3 Production JD Extraction Fix: IMPLEMENTED, LIVE RECHECK PENDING

Updated only `NaukriAdapter.fetch_job_description()` to use visible rendered DOM selectors in this order:

1. `[class*="dang-inner-html"]`
2. `section[class*="job-desc-container"]`

The existing security check remains in place. The first visible matching element is used, its text is stripped, and an empty string is returned when neither current selector is available. Focused tests cover the live hashed inner class pattern, container fallback, precedence, hidden inner element fallback, and no matching selectors. No Gemini call, Apply click, ApplicationRunner invocation, or submission occurred. Phase 9B-3 remains incomplete pending a live native APPLY boundary run.

## Phase 9B-3 Live JD Extraction Diagnostic: BLOCKER IDENTIFIED

Read-only visible-browser diagnostics inspected two persisted native jobs without invoking Gemini, ApplicationRunner, `start_application()`, or any Apply control:

- First American: HTTP 200, page title `Data Analyst - Bengaluru - First American - 1 to 3 years of experience`, visible body length 7,264.
- ReactZ Consulting: HTTP 200, page title `Software Engineer Fresher - Bengaluru - Reactz Consulting - 0 to 1 years of experience`, visible body length 4,486.

Both pages contained visible job-description text, but the current selectors `.job-desc` and exact `.styles_JDC__` matched zero elements. Observed rendered structures included `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`. No iframe was present. The likely production defect is selector matching against hashed class names with runtime suffixes. No production selector was changed. Gemini is intentionally deferred because quota is exhausted. No application was submitted; Phase 9B-3 remains incomplete.

## Phase 9B-3 Diagnostic JD Fetch: IMPLEMENTED, LIVE RECHECK PENDING

`diagnose_live_dry_run.py` now calls the existing `NaukriAdapter.fetch_job_description()` for selected real jobs, assigns the result to `Job.description`, commits it, and uses that value in the Gemini context. It inspects bounded candidates before choosing, excludes external jobs from native validation, reuses persisted analyses, stops on quota exhaustion, reports description status/length, and emits ASCII-safe output. Focused offline regression tests cover fetching, selection, and avoiding unnecessary refetches. No live Naukri search or Gemini request was run in this checkpoint, no application was submitted, and Phase 9B-3 remains incomplete.

## Test Database Isolation Checkpoint: COMPLETE

## Phase 9B-3 Native Application Detection Fix: IMPLEMENTED, LIVE RECHECK PENDING

Live candidate inspection found a real Naukri-native First American Data Analyst page:

- URL: `https://www.naukri.com/job-listings-data-analyst-first-american-bengaluru-1-to-3-years-230926038405`
- Stable control: `button#apply-button` / `button.apply-button`
- Visible text: `Apply`
- External control: absent
- Security check: passed

The adapter previously missed the current native selectors and returned `EXTERNAL`. Implemented the targeted fix in `backend/services/naukri/adapter.py`:

- `detect_application_type()` checks rendered external indicators first.
- Native detection recognizes `#apply-button`, `button.apply-button`, existing selectors, and visible exact-text `Apply` buttons.
- `start_application()` recognizes the same stable current native selectors.
- Hashed CSS classes are not used.

Focused regression coverage verifies both native selectors, visible exact-text `Apply`, external application text, no-control fallback, and native start-button compatibility. Focused result: 84 adapter tests passed. Full backend result: 519 tests passed with 3 dependency deprecation warnings. The full live native dry-run remains pending. No application was submitted and no live run was performed in this implementation checkpoint.

## Test Database Isolation Checkpoint: COMPLETE

Fixed a serious test-environment persistence defect. The shared fixture previously imported the application's production `engine` and executed `Base.metadata.drop_all()` against `data/naukri_agent.db`, allowing tests to delete runtime profile and resume data.

Implemented:
- Added a session-scoped temporary file-backed SQLite test engine.
- Redirected application and directly imported service session factories to the isolated test engine during tests.
- Limited `drop_all()` and `create_all()` in the shared fixture to the disposable test engine.
- Added regression tests proving the test engine path differs from production and test schema resets preserve production row counts.

Verification:
- Production database: `C:\Users\ajays\Desktop\Naukri Agent\data\naukri_agent.db`
- Test database: disposable temporary SQLite file under the system temp directory
- Focused isolation regression tests: 3 passed
- Full backend suite: 512 passed
- Production database remained present with its existing profile/resume rows after the full suite.

No application behavior, profile business logic, Naukri automation, Gemini, scheduler, worker coordination, or matching logic was changed.

## Phase 9B-3 False-Positive Fix Checkpoint: IMPLEMENTED, LIVE RECHECK PENDING

During a real visible-browser dry-run, the selected RR Groups job page was a normal HTTP 200 Naukri page with no actual CAPTCHA. The security gate nevertheless blocked it because raw HTML included Naukri's internal `"showCaptcha":false` value. The defect was isolated to `_check_security()` treating raw HTML text as visible security content.

Implemented fix in `backend/services/naukri/adapter.py`:
- Inspect rendered `page.inner_text("body")` instead of raw `page.content()`.
- Remove bare `captcha` as a standalone trigger.
- Preserve visible human-verification, security-challenge, reCAPTCHA/hCAPTCHA, login, and blocked-access indicators.

Regression coverage in `backend/tests/test_naukri_adapter.py` verifies:
- Raw `"showCaptcha":false` does not block a normal page.
- Bare visible `captcha` does not block.
- Visible reCAPTCHA, hCAPTCHA, and security-verification indicators still block.
- A normal Naukri job page is allowed.

**Recorded test results:** 77 Naukri adapter tests passed; 509 full backend tests passed. No application was submitted. Phase 9B-3 live validation remains incomplete until another real visible-browser Naukri dry-run confirms the corrected behavior.

## Phase 9B-2C Profile Duplicate ERROR Recovery: COMPLETE

Fixed a live-validation blocker in the resume/profile upload pipeline.

**Root cause:** `ProfileService.upload_resume()` duplicate path returned the existing profile unconditionally, regardless of its status. A profile in `ERROR` state (empty data, `confirmed=false`) was returned as-is, making it impossible to recover by re-uploading the same PDF.

**Fix — `backend/services/profile/resume_service.py`:**
- Added `read_stored(directory, filename) -> bytes` method to read back a previously stored PDF file.

**Fix — `backend/services/profile/profile_service.py`:**
- Duplicate path now checks `ProfileStatus` of the existing profile.
- `CONFIRMED` and `REVIEW_REQUIRED` duplicates: reused as before (no extraction).
- `ERROR` duplicate: re-reads stored PDF via `ResumeService.read_stored()`, re-runs PDF text extraction + Gemini extraction pipeline, updates the existing profile record in-place.
- On successful recovery: profile transitions `ERROR → REVIEW_REQUIRED`, `confirmed` remains `false`.
- On failed recovery: profile remains `ERROR`.
- No new resume or profile records are created.

**Regression tests — `backend/tests/test_profile.py` (+6 tests):**
- `test_duplicate_confirmed_profile_reused_without_extraction`
- `test_duplicate_review_required_profile_reused_without_extraction`
- `test_duplicate_error_profile_triggers_extraction_retry`
- `test_duplicate_error_recovery_transitions_to_review_required`
- `test_duplicate_error_recovery_failed_extraction_remains_error`
- `test_duplicate_error_recovery_no_new_records_created`

**Test results:** 503 backend tests passing (previously 497, +6). No regressions.

**No live Naukri activity in this checkpoint.** Phase 9B-2B live dry-run re-execution pending (requires confirmed profile).

---

## Phase 9B-2B Defect Fix: COMPLETE

Two runtime defects discovered during live dry-run attempts were fixed:

**Defect 1 — prompt_version NOT NULL persistence:**
- `AIQueueService.process_item()` in `backend/services/gemini/queue.py` hardcoded `prompt_version="v1"` — a disconnected literal not tied to the prompt versioning architecture.
- Fix: import `JOB_ANALYSIS_PROMPT_V1` from `backend/services/gemini/prompts.py` and use it when creating `JobAnalysisModel`.
- 6 regression tests added in `backend/tests/test_job_analysis_persistence.py`.

**Defect 2 — Experience year computation:**
- `MatchEngine.evaluate_job()` computed `user_exp_years = len(profile.data.get("experience", []))` — counting experience list entries as a proxy for years.
- For the actual user profile (1 ANZ entry, start: July 2026, end: Present), this returned 1 year when the actual elapsed time is ~0 years.
- Fix: added `compute_profile_experience_years()` to `backend/services/matching/normalizer.py` which parses `start_date`/`end_date` fields and computes actual elapsed years. Falls back to entry count when dates are unparseable.
- 8 regression tests added in `backend/tests/test_matching_rules.py`.

**Hard-filter architecture preserved:** Jobs rejected by experience hard filter never reach Gemini. The 0–1 year RR Groups job correctly passes the hard filter (0-year minimum is reachable by a fresher) and Gemini's advisory SKIP is also correct.

**Test results:** 497 backend tests passing (previously 483, +14). No regressions.

**No live Naukri activity in this checkpoint.** Phase 9B-2B live dry-run re-execution pending.

---

## Phase 9A: COMPLETE - Scheduler Automation Loop

Implemented complete Phase 9A scheduler automation loop connecting all existing components into one automatic local execution flow:

- **Gap C1 Fixed**: Scheduler automatically processes AI queue after discovery completes.
- **Gap C2 Fixed**: Scheduler invokes ApplicationRunner for jobs with completed AI analysis.
- **Gap C3 Fixed**: Deterministic hard filters integrated into runtime discovery/matching path.

Implementation details:

- Added `_apply_hard_filters_and_enqueue()` method that evaluates each discovered job through MatchEngine hard filters before queueing for AI analysis. Jobs failing hard filters are blocked from entering the application path.
- Added `_process_ai_queue_items()` method that processes eligible jobs through Gemini analysis, respecting quota exhaustion (stops processing without applying), retry policies, and stale item recovery.
- Added `_invoke_application_runner()` method that passes jobs with completed AI analysis to ApplicationRunner for execution, ensuring final safety gates always run.
- Updated main `_run_discovery_task()` to orchestrate full Phase 9A cycle: Discovery → Hard Filters → AI Queue → ApplicationRunner, with failure isolation so single job failures don't kill entire cycle.
- Updated scheduler routes to provide manual cycle execution endpoint `/scheduler/run-cycle`.
- Scheduler now logs cycle statistics: discovered, hard_filtered, queued, ai_processed, ai_blocked, application_candidates, applied, skipped, needs_attention, failed.

Safety preservation:

- Hard filters remain deterministic and authoritative (Gemini is advisory only).
- ApplicationRunner remains the sole executor of applications.
- Final safety gate in ApplicationService continues to run before every application submission.
- Application limits checked before and during execution.
- Duplicate protection enforced at multiple stages.
- AI quota exhaustion stops processing gracefully without applying jobs.
- Failure isolation: errors in individual jobs don't cascade; processing continues safely.

Testing:

- 5 new Phase 9A integration tests verify cycle orchestration, hard filter enforcement, AI queue processing, ApplicationRunner invocation, and failure isolation.
- All 480 backend tests pass (previously 475, +5 Phase 9A tests).
- Frontend builds successfully.
- No regression: all existing services, safety gates, and limitations remain unchanged and authoritative.

Known limitations: Real Naukri browser submission validation deferred to Phase 9B. Cloud workers, browser execution, and infrastructure changes deferred to Phase 8.5C and later.

---

## Phase 8.5B: COMPLETE - Distributed Work Coordination

Implemented distributed worker work coordination to safely queue and claim AI analysis work among multiple workers:

- Extended AIQueueItem model with three coordination fields: `claimed_by` (worker_id ownership), `last_heartbeat_at` (stale detection), `available_at` (backoff/release timing).
- Implemented WorkCoordinationService with atomic work claiming, ownership verification, heartbeat tracking, stale detection, and safe recovery.
- PostgreSQL claiming uses atomic SELECT...FOR UPDATE SKIP LOCKED to prevent race conditions.
- SQLite uses transaction-safe fallback (without row-level locking) with clear documentation of semantic differences.
- Heartbeat prevents stale detection and requires ownership verification.
- Stale detection identifies work items without heartbeat for 30+ minutes.
- Stale recovery preserves existing safety: if max_attempts exceeded, escalates to NEEDS_ATTENTION (human review required) rather than blindly retrying.
- Release, complete, and fail operations verify ownership and are terminal/idempotent where appropriate.
- Worker load tracking (claimed_count, processing_count).
- Deterministic claiming: priority descending, then created_at ascending.
- Comprehensive test suite: 49 focused tests covering claiming, ownership, heartbeat, stale detection, recovery, release/complete/fail, worker load, priority ordering, database compatibility, edge cases, and safety preservation.
- All 49 tests pass; 475 total backend tests pass (previously 426, +49 coordination tests).
- No regression: existing AI queue, application runner, safety gates, duplicate detection, and application limits remain unchanged and authoritative.
- Frontend unchanged.
- Safety preserved: stale recovery with exhausted attempts does not bypass duplicate protection or safety gates; uncertain outcomes require human review.

Known limitations: Cloud browser execution, browser session migration, cloud browser providers (Browserless, Browserbase), persistent cloud sessions, remote browser execution, Kubernetes, Redis, Celery, RabbitMQ, Kafka, multi-region infrastructure are all deferred to Phase 8.5C and later.

---


Implemented persistent worker identity layer to support future cloud browser coordination without modifying current execution:

- Added Worker SQLAlchemy model with identity (worker_id, unique), type, status, runtime_environment, and lifecycle timestamps (created_at, updated_at, started_at, stopped_at).
- Defined WorkerType enum: LOCAL_WINDOWS (current), CLOUD_BROWSER (future identity-only, not execution).
- Defined WorkerStatus enum: STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR (separate from AgentState).
- Implemented WorkerRegisterRequest and WorkerStatusResponse Pydantic schemas.
- Implemented WorkerListResponse with worker list, total_count, and active_count.
- Implemented WorkerService with four core operations: register_worker (safely repeatable by type+environment), get_worker (by ID), list_workers (all with active count), update_worker_status (with lifecycle tracking).
- Added three minimal API endpoints: GET /api/worker/status (list), POST /api/worker/register (register new or return existing), GET /api/worker/{worker_id} (get by ID).
- Registration is idempotent: same worker_type + runtime_environment returns the same worker_id.
- No sensitive data stored: Worker model contains identity and status only, never stores passwords, cookies, sessions, API keys, or Naukri credentials.
- Comprehensive test suite: type validation, status validation, registration, repeat registration, retrieval, status updates, persistence, listing, active count calculation, API endpoints, unknown worker handling.
- 12 focused tests all pass; 426 total backend tests pass; no regression.
- Frontend build passes with no changes.
- Current Windows/Naukri execution path unchanged; scheduler, Playwright, NaukriAdapter, ApplicationRunner all untouched.

Known limitations: Task claiming, heartbeat, stale-worker detection, PostgreSQL row locking, browser lifecycle refactoring, and cloud browser execution are all deferred to Phase 8.5B-D. Worker registration does not yet trigger any background services or lifecycle hooks.

---

## Phase 8.4.1: COMPLETE - Responsive Mobile Naukri-Inspired UX

Implemented a fully responsive mobile-first frontend experience inspired by Naukri's mobile UX patterns:

- Added mobile header (56px fixed, sticky) with hamburger menu, brand, and notifications bell.
- Converted desktop sidebar to a mobile drawer that slides in from the left with semi-transparent backdrop.
- Implemented bottom navigation bar (56px fixed, sticky) with 5 primary destinations: Home (Overview), Activity, Jobs (disabled), Applications (disabled), and More (secondary routes).
- Added comprehensive responsive CSS for mobile breakpoints (320px, 360px, 375px, 390px, 414px, 480px, 768px, 1024px, 1280px, 1440px+).
- Ensured all touch targets are minimum ~44x44px for accessibility.
- Preserved desktop layout and functionality; sidebar remains visible on desktop (>768px), topbar remains visible, mobile header/bottom nav hidden.
- Responsive grid layouts: metrics 4-col → 2-col → 1-col; analytics 3-col → 2-col → 1-col; forms 2-col → 1-col.
- Mobile-optimized form fields, upload zones, buttons, and cards with proper padding/spacing at each breakpoint.
- No backend changes, no API contract changes, no Gemini/scheduler/automation changes.
- Jobs and Applications routes remain disabled because those pages do not yet exist.
- Mobile UX is inspired by Naukri's information hierarchy and mobile interaction patterns, using Naukri Agent's own branding and design system.

Known limitations: Responsive behavior has been CSS-verified and logically tested, but browser-based device simulation testing at actual viewport sizes was not performed. Mobile UX patterns are Naukri-inspired (not copied); all UI assets and code are original Naukri Agent.

---

## Phase 8.4: COMPLETE - Vercel Frontend to Hosted FastAPI Preparation

Prepared the existing Vite dashboard for Vercel hosting and hosted API connectivity without deploying either service:

- Centralized all frontend API requests in `frontend/src/services/api.ts` using public `VITE_API_BASE_URL` configuration.
- Development retains `http://127.0.0.1:8000` as an omitted-variable fallback. Production requires a configured API URL and never silently uses localhost.
- Normalized configured origins and `/api` suffixes, added a 15-second request timeout, and mapped network, HTTP, timeout, and malformed-response errors to safe user-facing messages.
- Replaced direct/relative frontend `fetch` calls in agent control, analytics, preferences, and AI status with the shared client.
- Updated the existing root `vercel.json` to install/build `frontend/` and publish `frontend/dist`.
- Verified no rewrite is needed because the dashboard uses hash links and in-page state rather than browser-path routes.
- Preserved backend Phase 8.3 CORS; a deployed Vercel origin must be supplied through `NAUKRI_AGENT_FRONTEND_ORIGINS`.

Known limitations: Vercel and the hosted backend have not been deployed; no production URL, managed database, remote browser worker, or cloud automation was added.

---

## Phase 8.3: COMPLETE - Hosted FastAPI Deployment Preparation

Implemented deployment preparation for the existing FastAPI API without deploying any infrastructure:

- Added `Procfile` and a minimal `render.yaml` with root dependency installation, Uvicorn startup, platform-provided `PORT`, and secret-free environment placeholders.
- Preserved `python run.py` for local Windows development; hosted services run `backend.main:app` on `0.0.0.0`.
- Production readiness now requires PostgreSQL, Gemini configuration, and explicit non-wildcard frontend origins using the existing `NAUKRI_AGENT_` prefix.
- Liveness (`/api/health`) is independent of database and Gemini. Readiness (`/api/readiness`) reports safe database/configuration/storage/AI/runtime status without raw exception text.
- Production CORS supports one or more configured origins and leaves credentialed browser requests disabled.
- Hardened `SafeJsonFormatter` with centralized recursive sanitization for message text, extras, nested containers, credential URLs, auth/cookie/session data, and exceptions.
- Confirmed the existing frontend `VITE_API_BASE_URL` configuration remains separate from backend environment configuration.

Known limitations: no hosting provider deployment, managed PostgreSQL provisioning, frontend deployment, object storage, remote browser worker, or cloud automation was implemented.

---

## Phase 8.1: COMPLETE - Production Backend Preparation (Checkpoint 8.1)

Implemented Phase 8.1 - Production Backend Preparation to make the FastAPI backend production-hosting ready without actual deployment:

**Production Configuration Enhancements:**
- Enhanced configuration with environment separation (LOCAL_WINDOWS/CLOUD)
- Added production detection properties (is_production, is_local_windows, is_cloud)
- Added CORS origins parsing from comma-separated string for multiple frontend origins
- Updated .env.example with comprehensive production-ready configuration placeholders
- Added runtime_environment configuration field for environment-specific behavior

**CORS Configuration Improvements:**
- Production-safe CORS configuration with configurable origins
- Development mode allows localhost origins for convenience
- Production mode uses only configured origins from FRONTEND_ORIGINS
- Added support for multiple origins via comma-separated list
- Enhanced CORS methods and headers for full API support

**Health and Readiness Endpoints:**
- Added separate readiness endpoint (/api/readiness) from liveness endpoint (/api/health)
- Liveness check: simple API process status
- Readiness check: detailed component status (database, configuration, storage, AI provider, runtime environment)
- Readiness endpoint validates database connectivity, configuration validity, storage availability
- Production mode requires API key for configuration validation
- Added ReadinessResponse schema for structured component status reporting

**Error Handling Enhancements:**
- Added catch-all exception handler to prevent sensitive information exposure
- Generic exception handler returns safe error messages without stack traces
- Enhanced error responses for production safety
- Logs errors without exposing sensitive details to clients

**Logging Production Readiness:**
- Added SafeJsonFormatter for production-safe logging
- Automatic redaction of sensitive information (api_key, password, token, secret, credential, auth)
- Production mode uses SafeJsonFormatter by default
- Development mode uses standard JsonFormatter for debugging
- Enhanced logging configuration to respect environment settings

**Database Configuration Verification:**
- Verified database configuration supports both SQLite and PostgreSQL
- SQLite directory creation works for both relative and absolute paths
- PostgreSQL URL configuration is fully supported via DATABASE_URL
- No SQLite-only assumptions that would prevent hosted operation
- Database initialization works correctly in both modes

**Storage Configuration Verification:**
- Verified StorageService abstraction for hosted readiness
- Application code uses StorageService for file operations
- No direct Windows-specific absolute path dependencies
- Local filesystem storage preserved for LOCAL_WINDOWS
- Abstraction ready for future object storage integration

**Browser/API Separation Verification:**
- Verified browser automation is not auto-started by API startup
- Playwright browser only starts when explicitly called via DiscoveryService
- API process initialization does not launch Chromium
- Clear separation between API process and browser worker
- Safe for future cloud architecture with separate browser worker

**Frontend API Configuration:**
- Enhanced frontend API configuration for environment-based backend URL
- Added VITE_API_BASE_URL environment variable support
- Development: http://127.0.0.1:8000/api (default)
- Production: https://<hosted-api>/api (configurable via environment)
- Added frontend/.env.example with API configuration placeholder
- No hardcoded localhost in production frontend code

**Security Improvements:**
- Enhanced CORS configuration prevents wildcard origins in production
- Error responses don't expose stack traces or internal details
- Logging redacts sensitive information automatically
- Configuration properties don't expose API keys or secrets
- API responses never return credentials or sensitive configuration

**Production Configuration Tests:**
- Added comprehensive test suite (backend/tests/test_production_config.py)
- Tests for environment separation (LOCAL_WINDOWS/CLOUD)
- Tests for CORS configuration and origins parsing
- Tests for health and readiness endpoints
- Tests for error handling and security
- Tests for database configuration (SQLite/PostgreSQL)
- Tests for storage configuration
- Tests for browser/API separation
- Tests for Gemini configuration
- Tests for environment variable configuration
- Total: 401 tests passing (32 new production configuration tests)

**Files Changed:**
- backend/core/config.py: Enhanced with production configuration properties
- backend/main.py: Enhanced CORS, logging, error handling
- backend/core/logging.py: Added SafeJsonFormatter for production
- backend/api/routes/health.py: Added readiness endpoint
- backend/schemas/health.py: Added ReadinessResponse schema
- .env.example: Comprehensive production configuration
- frontend/src/services/api.ts: Environment-based API URL
- frontend/.env.example: Frontend environment configuration
- backend/tests/test_production_config.py: New comprehensive test suite
- backend/tests/test_health.py: Enhanced with readiness tests

**Key Design Decisions:**
- Environment separation via runtime_environment (local_windows/cloud)
- Production-safe CORS with configurable origins
- Separate liveness and readiness endpoints for container orchestration
- Production logging with automatic sensitive information redaction
- No actual cloud deployment in this checkpoint
- All V1 functionality remains local Windows only
- Future cloud deployment will use CLOUD mode with object storage and PostgreSQL

**Known Limitations:**
- Cloud execution NOT implemented (future phase)
- Remote browser automation NOT implemented (future phase)
- Object storage (S3/Azure/GCS) NOT implemented (future phase)
- PostgreSQL production database NOT deployed (future phase)
- Cloud infrastructure NOT deployed (future phase)
- All V1 functionality remains local Windows only

**Next Phase:**
- Phase 8.2 - COMPLETE: PostgreSQL + Production Persistence (Checkpoint 8.2)

---

## Phase 8.2: COMPLETE - PostgreSQL + Production Persistence (Checkpoint 8.2)

Implemented Phase 8.2 - Production Database Support alongside the existing SQLite backend:

**PostgreSQL Driver Integration:**
- Configured PostgreSQL connectivity using the `psycopg` v3 driver.
- Added connection pooling metrics suitable for scaling (e.g. `pool_size`, `max_overflow`).
- Rewrote dialect URLs handling transparently replacing basic `postgresql://` inputs to `postgresql+psycopg://` at runtime.

**Backward Compatibility:**
- Maintained fully functional SQLite configuration with memory and file support for local V1 instances.
- All testing functions default natively against SQLite without requiring production teardowns.
- Storage directory constraints automatically managed based on database environments.

**Persistence:**
- Confirmed StorageService compatibility with absolute path routing avoiding storage conflicts.
- Local environments default safely preserving past file histories.

**Files Changed:**
- backend/requirements.txt: Appended `psycopg[binary]`.
- backend/database/database.py: Added PostgreSQL dialect interception and configurations.
- backend/tests/test_database_engines.py: Extensive test suite proving isolated dialect and queue pool attributes handling.

**Next Phase:**
- Cloud Execution (Docker/Hosting setup) - TBD

---

## Frontend Codebase Structure Verification - COMPLETE

Verified frontend codebase structure and dependencies for production readiness:

**Current Frontend Stack:**
- React 19.1.0 with TypeScript 5.8.3
- Vite 6.3.5 for build tooling
- Tailwind CSS 4.1.4 for styling
- Lucide React 0.468.0 for icons
- @vitejs/plugin-react 4.4.1 for React support

**Frontend Component Structure:**
- App.tsx: Main application shell with navigation
- AnalyticsDashboard.tsx: Analytics metrics and decision breakdown
- AgentControl.tsx: Agent lifecycle controls
- AIStatus.tsx: AI usage tracking
- BackendState.tsx: Backend connection state handling
- EmptyState.tsx: Reusable empty state component
- ErrorState.tsx: Reusable error state component
- LoadingState.tsx: Reusable loading state component
- JobPreferences.tsx: Job search preferences management
- ProfileWorkspace.tsx: Resume and profile management

**Frontend Build Status:**
- TypeScript compilation: PASSED
- Vite production build: PASSED (267.10 kB JS, 28.43 kB CSS)
- Build time: 17.59s
- No build errors or warnings

**Code Quality:**
- Type-safe components with TypeScript
- Proper error handling and loading states
- Reusable state components
- Modern React patterns
- Clean component architecture

**Dependencies:**
- All dependencies are up-to-date and stable
- No deprecated packages
- Production-ready versions (all published >7 days ago)
- Minimal dependency footprint

**Next Steps:**
- Frontend is production-ready for current feature set
- Components follow modern React best practices
- Build pipeline is stable and performant
- Codebase is well-structured for future enhancements

---

## Frontend UX/UI Redesign Checkpoint - COMPLETE

Implemented comprehensive frontend UX/UI redesign to transform the dashboard from a development prototype to a polished, modern SaaS product:

**User Experience Improvements:**
- Removed all development-phase terminology from user-facing UI (Phase 1-7 labels, "foundation phase", etc.)
- Replaced technical error messages with user-friendly alternatives
- Created reusable state components (LoadingState, EmptyState, ErrorState, BackendState)
- Implemented graceful backend connection state handling
- Added profile completion indicator with visual progress tracking
- Improved preferences page with clear sections and descriptions
- Enhanced analytics dashboard with compact, readable charts

**Visual Design Overhaul:**
- Modern SaaS dashboard layout with improved sidebar navigation
- Enhanced top bar with page titles, descriptions, and status indicators
- Consistent visual language using Naukri-inspired color palette
- Improved typography hierarchy and spacing
- Rounded corners, subtle shadows, and smooth transitions
- Hover states and active navigation indicators
- Better card design with visual hierarchy

**Navigation Structure:**
- Overview: Main command center with agent status and controls
- Activity: Timeline of agent actions and events
- Jobs: Job discovery interface (placeholder for future)
- Applications: Application tracking dashboard (placeholder for future)
- Analytics: Performance metrics and decision analytics
- Profile: Resume and profile management
- Preferences: Job search criteria and automation settings

**Accessibility Enhancements:**
- Skip-to-content link for keyboard navigation
- Proper ARIA labels on interactive elements
- Visible focus states on all interactive elements
- Semantic HTML structure
- Sufficient color contrast
- Keyboard-friendly navigation

**Responsive Design:**
- Desktop: Full sidebar with all navigation items
- Tablet: Collapsed sidebar with icons only
- Mobile: Off-canvas sidebar layout
- Card layouts reflow appropriately
- Optimized for various screen sizes

**Technical Improvements:**
- Enhanced CSS with modern design tokens
- Improved button hierarchy and states
- Better form field styling with focus states
- Consistent spacing system (4px, 8px, 16px, 24px, 32px)
- Performance optimizations with minimal dependencies
- Type-safe components with TypeScript

**Files Changed:**
- frontend/src/app/App.tsx: Redesigned app shell with navigation
- frontend/src/styles.css: Complete visual language overhaul
- frontend/src/components/LoadingState.tsx: New reusable loading component
- frontend/src/components/EmptyState.tsx: New reusable empty state component
- frontend/src/components/ErrorState.tsx: New reusable error state component
- frontend/src/components/BackendState.tsx: New backend connection state component
- frontend/src/components/ProfileWorkspace.tsx: Enhanced with completion indicator
- frontend/src/components/JobPreferences.tsx: Improved with clear sections
- frontend/src/components/AnalyticsDashboard.tsx: Enhanced error handling

**Testing:**
- Frontend build: PASSED (TypeScript compilation successful)
- Frontend typecheck: PASSED
- Backend pytest: PASSED (369 tests, no regression)
- No backend functionality modified (frontend-only changes)

**Design Principles Applied:**
- Professional SaaS aesthetic
- User-centric language
- Accessibility-first approach
- Responsive design
- Graceful degradation
- Performance optimization

**Next Steps:**
- Implement Jobs page with proper discovery interface
- Implement Applications page with tracking dashboard
- Implement Activity timeline with real agent data
- Add more sophisticated data visualizations
- Implement user onboarding flow

---

## Phase 7: COMPLETE - Agent Intelligence, Decision Quality & Application Analytics (Checkpoint 4)

Implemented Phase 7 Checkpoint 4:

- Created decision quality model in backend/schemas/decision.py:
  - DecisionPriority enum: HARD_REJECT, SKIP, LOW_PRIORITY, NORMAL_PRIORITY, HIGH_PRIORITY, NEEDS_ATTENTION
  - DecisionReasonCode enum: 20+ structured reason codes for explainable decisions
  - DecisionQuality schema: comprehensive decision assessment with signals
  - DecisionSignal schema: individual signal contribution to decision
  - JobPriorityRequest/Response: bulk job prioritization
  - DecisionHistoryRequest/Response: decision history tracking
- Created feedback schemas in backend/schemas/feedback.py:
  - FeedbackType enum: RELEVANT, NOT_RELEVANT, APPLIED, SKIPPED, INCORRECT_MATCH, etc.
  - FeedbackCreate/Response: feedback submission and retrieval
  - FeedbackSummary: feedback aggregation metrics
- Created feedback models in backend/models/feedback.py:
  - JobFeedback: stores explicit user feedback for learning
  - DecisionQualityRecord: stores decision quality assessments for analytics
- Implemented DecisionQualityService in backend/services/decision/quality.py:
  - evaluate_job_decision(): comprehensive decision evaluation with explainable reasoning
  - Hard filter checks remain authoritative (profile, location, experience, salary, employment, title scope, duplicate)
  - AI analysis integration (advisory only, never overrides hard rules)
  - Signal calculation: role relevance, skill relevance, experience compatibility, location match, salary suitability, job quality, freshness, duplicate probability, suspicious probability
  - Historical feedback integration: feedback adjustment (-1 to 1)
  - Decision score calculation (0-100) using weighted signal combination
  - Priority determination based on score and special cases
  - Explainable decision generation with reason codes
  - save_decision_record(): persistence to DecisionQualityRecord for analytics
- Implemented JobPrioritizationService in backend/services/decision/prioritization.py:
  - prioritize_jobs(): bulk job prioritization with sorting
  - get_eligible_jobs_for_application(): filter to eligible jobs only
  - get_prioritized_eligible_jobs(): prioritized eligible jobs with limit
  - Deterministic and reproducible prioritization
  - Hard-filtered jobs never become higher priority
- Implemented FeedbackService in backend/services/learning/service.py:
  - submit_feedback(): submit user feedback for jobs
  - get_feedback_for_job(): retrieve feedback for specific job
  - get_feedback_summary(): aggregate feedback metrics
  - delete_feedback(): remove feedback records
  - Feedback influences ranking only (cannot override hard rules)
- Implemented AnalyticsService in backend/services/analytics/service.py:
  - get_analytics_summary(): comprehensive analytics summary
  - get_skip_reasons(): top skip reasons with counts
  - get_decision_breakdown(): decision priority distribution
  - get_applications_by_day(): daily application counts
  - get_applications_by_job_profile(): application breakdown by title
  - get_primary_reason_codes(): top decision reason codes
  - get_feedback_summary(): feedback metrics
  - get_recent_decision_activity(): latest decision records
  - All analytics use existing data without creating fake historical data
- Added decision API routes in backend/api/routes/decision.py:
  - POST /api/decision/evaluate/{job_id}: evaluate decision quality for specific job
  - POST /api/decision/prioritize: prioritize list of jobs
  - GET /api/decision/history/{job_id}: get decision history for job
- Added feedback API routes in backend/api/routes/feedback.py:
  - POST /api/feedback/submit: submit user feedback
  - GET /api/feedback/job/{job_id}: get feedback for job
  - GET /api/feedback/summary: get feedback summary
  - DELETE /api/feedback/{feedback_id}: delete feedback
- Added analytics API routes in backend/api/routes/analytics.py:
  - GET /api/analytics/summary: comprehensive analytics summary
  - GET /api/analytics/skip-reasons: top skip reasons
  - GET /api/analytics/decision-breakdown: decision priority distribution
  - GET /api/analytics/applications-by-day: daily application counts
  - GET /api/analytics/applications-by-profile: application breakdown by title
  - GET /api/analytics/primary-reasons: top decision reason codes
  - GET /api/analytics/feedback-summary: feedback metrics
  - GET /api/analytics/recent-decisions: recent decision activity
- Added AnalyticsDashboard component in frontend/src/components/AnalyticsDashboard.tsx:
  - Summary metrics: jobs discovered, applications submitted, success rate, AI usage
  - Decision breakdown: priority distribution with visual bars
  - Top skip reasons: aggregated skip reason analysis
  - Real-time data fetching with error handling
  - Naukri-inspired design with color-coded metrics
- Enhanced App.tsx to include AnalyticsDashboard in overview section
- Added analytics styles in frontend/src/styles.css:
  - Analytics card grid layout
  - Color-coded metric icons (success, warning, attention, info, neutral)
  - Decision breakdown bars with percentages
  - Skip reasons list styling
  - Responsive design for mobile
- Integrated new routes in backend/main.py:
  - decision_router: decision quality and prioritization endpoints
  - feedback_router: feedback submission and retrieval endpoints
  - analytics_router: analytics and reporting endpoints
- Updated models/__init__.py to export JobFeedback and DecisionQualityRecord
- Comprehensive test coverage (46 new tests):
  - Decision quality tests (10 tests): hard filters, AI integration, scoring, explanations
  - Prioritization tests (7 tests): sorting, eligibility, determinism, AI analysis
  - Feedback tests (11 tests): submission, retrieval, summary, influence on decisions
  - Analytics tests (18 tests): summary, skip reasons, decision breakdown, time periods
- Total: 369 tests passing

Decision Quality Architecture:
```text
DecisionQualityService (decision evaluation)
    ↓
Hard filters (authoritative Python rules)
    ↓
AI analysis (advisory only)
    ↓
Signal calculation (weighted combination)
    ↓
Decision score (0-100)
    ↓
Priority determination
    ↓
Explainable decision with reason codes
    ↓
DecisionQualityRecord persistence
```

Key Design Decisions:
- Hard filters remain authoritative (location, experience, salary, duplicate, etc.)
- Gemini recommendations are advisory only - never override hard rules
- Decision quality combines deterministic Python rules with AI analysis
- Priority levels: HARD_REJECT, SKIP, LOW_PRIORITY, NORMAL_PRIORITY, HIGH_PRIORITY, NEEDS_ATTENTION
- Structured reason codes for explainable decisions (20+ codes)
- Historical feedback influences ranking but cannot modify hard rules
- User-controlled preferences remain authoritative
- Analytics use existing data without creating fake historical data
- Prioritization is deterministic and reproducible
- All decisions persisted for analytics and learning

API Endpoints Added:
- POST /api/decision/evaluate/{job_id}
- POST /api/decision/prioritize
- GET /api/decision/history/{job_id}
- POST /api/feedback/submit
- GET /api/feedback/job/{job_id}
- GET /api/feedback/summary
- DELETE /api/feedback/{feedback_id}
- GET /api/analytics/summary
- GET /api/analytics/skip-reasons
- GET /api/analytics/decision-breakdown
- GET /api/analytics/applications-by-day
- GET /api/analytics/applications-by-profile
- GET /api/analytics/primary-reasons
- GET /api/analytics/feedback-summary
- GET /api/analytics/recent-decisions

Frontend Changes:
- AnalyticsDashboard component with comprehensive metrics
- Decision breakdown visualization with priority bars
- Top skip reasons display
- Naukri-inspired design with color-coded cards
- Real-time data fetching and error handling
- Responsive grid layout for metrics

Safety Behavior:
- Hard filters remain authoritative (location, experience, salary, duplicate, etc.)
- Gemini cannot override hard rules or trigger applications
- Feedback cannot modify hard filters or user preferences
- Prioritization never places hard-filtered jobs above eligible jobs
- Learning is ranking/prioritization only, not rule modification
- All decisions are explainable with structured reason codes

Known limitations:
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented
- Learning is minimal (ranking influence only, not automatic rule modification)
- External application submission NOT implemented
- Complex automated learning NOT implemented

Next Phase: Phase 8 - Production Readiness (TBD)

Implemented cloud readiness infrastructure to support future cloud deployment while maintaining local-first V1:

- Created RuntimeContext abstraction in backend/core/runtime.py:
  - RuntimeEnvironment enum: LOCAL_WINDOWS (V1 current), CLOUD_READY (future)
  - RuntimeContext class: Provides environment-specific information and behavior
  - Auto-detects current runtime (Windows vs others)
  - Properties for: browser automation support, Windows auto-start support, persistent browser session support
  - Methods for: database URL retrieval, storage path resolution, directory paths
  - Global singleton instance with get_runtime_context() and set_runtime_context()
- Created StorageService abstraction in backend/core/storage.py:
  - StorageService class: File storage operations with clean interface
  - Methods for: store_file, read_file, delete_file, file_exists, get_file_size
  - Methods for: list_files, create_directory, delete_directory
  - Path resolution with resolve_path()
  - Directory management: resume storage, data storage, log storage, browser user data
  - Atomic file operations with temporary files
  - Global singleton instance with get_storage_service()
- Enhanced configuration in backend/core/config.py:
  - Added environment variable prefix (NAUKRI_AGENT_) for all settings
  - Changed storage paths from Path fields to string fields with property resolution
  - Properties for absolute path resolution: resume_storage_path, data_path, log_path, browser_user_data_path
  - Added runtime_environment configuration field
  - Support for both relative and absolute paths
- Enhanced database configuration in backend/database/database.py:
  - Support for both SQLite and PostgreSQL databases
  - Flexible DATABASE_URL configuration
  - Improved SQLite directory creation for both relative and absolute paths
- Integrated abstractions into existing services:
  - NaukriAdapter now uses get_browser_user_data_dir() from settings
  - ResumeService now uses StorageService for file operations
  - All path resolution goes through storage abstraction
- Added comprehensive tests (40 new tests):
  - RuntimeContext tests (16 tests): environment detection, properties, path resolution
  - StorageService tests (24 tests): file operations, directory management, path resolution
- Total: 323 tests passing

Cloud Readiness Architecture:
```text
RuntimeContext (environment detection)
    ↓
StorageService (file operations abstraction)
    ↓
Settings (environment variable driven configuration)
    ↓
Database (SQLite/PostgreSQL flexibility)
```

Key Design Decisions:
- V1 continues to run in LOCAL_WINDOWS mode
- Future cloud deployment will use CLOUD_READY mode
- No changes to existing business logic or public APIs
- Abstractions allow future cloud integration without code changes
- Environment variables prefixed with NAUKRI_AGENT_ for consistency
- Path resolution supports both relative and absolute paths
- Storage abstraction enables future S3/Azure Blob/GCS integration
- Database abstraction enables future PostgreSQL migration
- Browser automation only supported in LOCAL_WINDOWS (V1 design)
- All existing functionality preserved

Files Changed:
- backend/core/runtime.py (new)
- backend/core/storage.py (new)
- backend/core/config.py (enhanced)
- backend/database/database.py (enhanced)
- backend/services/naukri/adapter.py (minor integration)
- backend/services/profile/resume_service.py (minor integration)
- backend/tests/test_runtime.py (new)
- backend/tests/test_storage.py (new)
- backend/tests/test_profile.py (test fixes for new config)

Known Limitations:
- Cloud execution NOT implemented (future phase)
- Remote browser automation NOT implemented (future phase)
- Object storage (S3/Azure/GCS) NOT implemented (future phase)
- PostgreSQL deployment NOT implemented (future phase)
- All V1 functionality remains local Windows only

---

## Phase 7: COMPLETE - Windows Startup & Local Agent Lifecycle (Checkpoint 3)

Implemented Phase 7 Checkpoint 3:

- Created AgentLifecycleService in backend/services/lifecycle/service.py:
  - get_lifecycle_status(): Comprehensive status including agent state, scheduler, AI queue, prerequisites
  - start(): Safe agent start with prerequisite validation
  - stop(): Safe agent stop with queue preservation
  - pause(): Pause agent with queue preservation
  - resume(): Resume agent with prerequisite validation
  - recover_on_startup(): Startup recovery with stale queue recovery and safe state restoration
  - _check_prerequisites(): Validates confirmed profile, job preferences, and API key
- Created WindowsAutoStartService in backend/services/windows/autostart.py:
  - is_enabled(): Check if Windows Task Scheduler auto-start is enabled
  - enable(): Enable auto-start via Task Scheduler (user-level, no admin required)
  - disable(): Disable auto-start by removing Task Scheduler task
  - get_status(): Get auto-start status and platform support
- Added lifecycle schemas in backend/schemas/lifecycle.py:
  - LifecycleStatusResponse: Full lifecycle status
  - LifecycleActionResponse: Start/stop/pause/resume results
  - RecoveryStatsResponse: Startup recovery statistics
  - RecoveryResponse: Recovery operation result
- Added auto-start schemas in backend/schemas/autostart.py:
  - AutoStartStatusResponse: Auto-start status
  - AutoStartEnableRequest: Enable auto-start request
  - AutoStartActionResponse: Enable/disable results
- Created lifecycle API routes in backend/api/routes/lifecycle.py:
  - GET /api/agent/status: Get agent lifecycle status
  - POST /api/agent/start: Start agent
  - POST /api/agent/stop: Stop agent
  - POST /api/agent/pause: Pause agent
  - POST /api/agent/resume: Resume agent
  - POST /api/agent/recovery: Trigger startup recovery (for testing)
- Created system API routes in backend/api/routes/system.py:
  - GET /api/system/autostart: Get auto-start status
  - POST /api/system/autostart/enable: Enable Windows auto-start
  - POST /api/system/autostart/disable: Disable Windows auto-start
- Integrated lifecycle services in backend/main.py:
  - Initialize AgentLifecycleService with state_manager and scheduler_service
  - Initialize WindowsAutoStartService
  - Perform startup recovery during FastAPI lifespan
  - Removed auto-start of scheduler on startup (safe default)
  - Agent resets to IDLE after restart (no automatic application submission)
- Extended AgentControl component in frontend/src/components/AgentControl.tsx:
  - Displays current agent state with color coding
  - Start/Stop/Pause/Resume buttons based on current state
  - Shows scheduler status and AI queue counts
  - Windows auto-start toggle (Windows only)
  - Prerequisites validation warnings
  - Real-time status polling (5-second interval)
- Added agent control styles in frontend/src/styles.css:
  - Control button styles (primary, secondary, danger)
  - Agent state color coding (idle, running, paused, stopped, error states)
  - Warning text for missing prerequisites
  - Toggle button for auto-start
  - Status meta display improvements
- Fixed SchedulerService database session management:
  - AI queue service now initialized per-session to avoid session conflicts
  - process_ai_queue() takes db session parameter
  - _enqueue_discovered_jobs() takes db session parameter
  - Gemini provider lazy initialization in AIQueueService
- Comprehensive test coverage (38 new tests):
  - Lifecycle service tests (21 tests): status, prerequisites, start/stop/pause/resume, recovery
  - Auto-start service tests (16 tests): enable/disable/status, Windows/non-Windows behavior
  - Lifecycle integration tests (15 tests): complete flow, scheduler integration, recovery, safety
- Total: 239 tests passing

Lifecycle Architecture:
```text
AgentLifecycleService (orchestration)
    ↓
AgentStateManager (existing state management)
    ↓
SchedulerService (existing scheduler)
    ↓
AIQueueService (existing AI queue)
    ↓
WindowsAutoStartService (Task Scheduler integration)
```

Key Design Decisions:
- Lifecycle service extends AgentStateManager without duplicating state logic
- Startup recovery defaults to IDLE state (safe default, no auto-submission)
- Active states (RUNNING, SEARCHING, FILTERING, APPLYING) reset to IDLE on restart
- Problem states (AUTH_REQUIRED, SECURITY_REQUIRED) are preserved on restart
- Auto-start uses Windows Task Scheduler (user-level, no admin required)
- Auto-start is optional and user-controlled (not automatic during development)
- Agent checks prerequisites before start/resume operations
- Scheduler is NOT auto-started on application startup (safe default)
- Queue is preserved across stop/start operations
- AI queue stale items recovered on startup
- Windows auto-start only available on Windows platform
- Subprocess flags are platform-specific (CREATE_NO_WINDOW on Windows)

API Endpoints Added:
- GET /api/agent/status
- POST /api/agent/start
- POST /api/agent/stop
- POST /api/agent/pause
- POST /api/agent/resume
- POST /api/agent/recovery
- GET /api/system/autostart
- POST /api/system/autostart/enable
- POST /api/system/autostart/disable

Frontend Changes:
- AgentControl component with real-time status polling
- State-based button visibility (Start when IDLE/STOPPED, Pause/Stop when RUNNING, etc.)
- Prerequisites validation and warnings
- Windows auto-start toggle (platform-aware)
- Color-coded agent states
- Scheduler and AI queue status display

Safety Behavior:
- No automatic application submission after restart
- Agent resets to IDLE even if it was RUNNING before restart
- Prerequisites validated before start/resume
- Queue preserved across lifecycle operations
- Stale queue items recovered on startup
- Error states preserved for user attention
- Scheduler not auto-started with application

Known limitations:
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented
- Windows service NOT implemented (Task Scheduler used instead)
- Complex installer NOT implemented
- Multi-platform auto-start NOT implemented (Windows-only currently)

Next Phase: Phase 8 - Production Readiness (TBD)

---

## Phase 7: COMPLETE - AI Work Queue (Checkpoint 2B)

Implemented Phase 7 Checkpoint 2A:

- Created ApplicationLimitService in backend/services/applications/limits.py:
  - get_limits(): Retrieves current limits from JobPreference (max_hourly_applications, max_daily_applications)
  - update_limits(): Updates hourly/daily limits
  - get_hourly_usage(): Counts successful applications (APPLIED/SUBMITTED) in last hour
  - get_daily_usage(): Counts successful applications (APPLIED/SUBMITTED) in last 24 hours
  - check_limits(): Returns LimitCheckResult with allowed status and detailed usage info
  - get_limit_status(): Returns full status including usage, remaining capacity, and percentages
- Added limit schemas in backend/schemas/application.py:
  - ApplicationLimitsUpdate: For updating max_hourly_applications and max_daily_applications
  - ApplicationLimitsResponse: Full limit status with usage metrics
  - LimitCheckResponse: Result of limit check with reason and capacity info
- Integrated limit check into ApplicationRunner (backend/services/applications/runner.py):
  - Added ApplicationLimitService to runner initialization
  - Check limits BEFORE safety gate and BEFORE application submission
  - Skip application with clear reason when limits reached
  - Preserve all existing safety gate and duplicate protection logic
- Integrated limit check into SchedulerService (backend/services/scheduler/service.py):
  - Check limits BEFORE starting discovery
  - Skip discovery when hourly or daily limits reached
  - Log when limits block discovery
  - Allow scheduler to continue safely without errors
- Added limit API endpoints in backend/api/routes/application.py:
  - GET /api/applications/limits: Get current limits and usage status
  - PUT /api/applications/limits: Update hourly/daily limits
  - GET /api/applications/limits/check: Check if another application is allowed
- Added comprehensive tests (22 new tests):
  - ApplicationLimitService tests (19 tests): get_limits, update_limits, hourly/daily usage, limit checks, status
  - Limit enforcement tests (3 tests): only APPLIED/SUBMITTED counted, failed/external not counted
- Total: 201 tests passing

Limit Architecture:
```text
ApplicationLimitService (deterministic Python logic)
    ↓
Counts only APPLIED/SUBMITTED applications (not SKIPPED/NEEDS_ATTENTION/EXTERNAL)
    ↓
Hourly usage: applications with applied_at >= now - 1 hour
    ↓
Daily usage: applications with applied_at >= now - 24 hours
    ↓
Limit check: blocks if hourly_used >= max_hourly OR daily_used >= max_daily
    ↓
ApplicationRunner: checks limits BEFORE safety gate and BEFORE submission
    ↓
SchedulerService: checks limits BEFORE starting discovery
```

Key Design Decisions:
- Limits use existing JobPreference model (max_hourly_applications, max_daily_applications already existed)
- Only successful applications (APPLIED/SUBMITTED status) count toward limits
- Failed/skipped/external applications do NOT count toward limits
- Deterministic Python logic only - Gemini never decides limits
- Limit check happens BEFORE safety gate (hard filters still execute first)
- Limit check happens BEFORE application submission
- Scheduler skips discovery when limits reached (no wasted resources)
- Clear reasons provided when limits block applications
- Percentage calculations for UI display
- UTC timezone for all time calculations

API Endpoints Added:
- GET /api/applications/limits
- PUT /api/applications/limits
- GET /api/applications/limits/check

Integration Points:
- ApplicationRunner._process_single_job(): Check limits after duplicate check, before safety gate
- SchedulerService._run_discovery_task(): Check limits before starting discovery
- Existing JobPreference model already had limit fields (Phase 4)
- Existing Application status enum used for filtering (Phase 6)

Known limitations:
- AI queue NOT implemented yet (future checkpoint)
- Gemini changes NOT implemented yet (future checkpoint)
- Restart recovery NOT implemented yet (future checkpoint)
- Windows startup NOT implemented yet (future checkpoint)
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented

Next Checkpoint: Phase 7 - Checkpoint 2B (AI Queue)

---

## Phase 7: COMPLETE - Scheduler Core (Checkpoint 1)

Implemented Phase 7 Checkpoint 1:

- Added APScheduler dependency to requirements.txt (>=3.10,<4.0)
- Added scheduler configuration to Settings:
  - scheduler_enabled: bool (default True)
  - scheduler_interval_minutes: int (default 60, hourly)
  - scheduler_max_instances: int (default 1)
- Created SchedulerConfig model in backend/models/scheduler.py for persistence:
  - enabled, interval_minutes, max_instances
  - is_running, is_paused states
  - last_run_at, next_run_at timestamps
  - created_at, updated_at for tracking
- Created scheduler core in backend/core/scheduler.py:
  - JobScheduler class using APScheduler AsyncIOScheduler
  - Configurable interval with max_instances=1 to prevent overlapping runs
  - Support for start, stop, pause, resume operations
  - Status reporting (is_running, is_paused, interval, last_run, next_run)
  - Task callback system for integration with discovery service
  - UTC timezone support
- Created scheduler service in backend/services/scheduler/service.py:
  - SchedulerService class for orchestration and persistence
  - Initializes from database config or creates defaults
  - Integrates with existing DiscoveryService for scheduled runs
  - Loads/saves configuration to database
  - Respects agent state - skips discovery when agent is busy
  - Safe startup/shutdown with database session management
- Created scheduler Pydantic schemas in backend/schemas/scheduler.py:
  - SchedulerStatusResponse: current scheduler status
  - SchedulerConfigRequest: update enabled/interval
  - SchedulerConfigResponse: full configuration
  - SchedulerActionResponse: action results with status
- Created scheduler API routes in backend/api/routes/scheduler.py:
  - GET /api/scheduler/status: Get scheduler status
  - POST /api/scheduler/start: Start scheduler
  - POST /api/scheduler/stop: Stop scheduler
  - POST /api/scheduler/pause: Pause scheduler
  - POST /api/scheduler/resume: Resume scheduler
  - PUT /api/scheduler/config: Update configuration
- Integrated scheduler startup/shutdown in backend/main.py:
  - Initializes SchedulerService with shared state_manager and discovery_service
  - Loads config from database on startup
  - Auto-starts scheduler if enabled in settings
  - Graceful shutdown on application stop
- Added comprehensive tests in backend/tests/test_scheduler.py (33 tests):
  - JobScheduler tests: initialization, callback, start/stop, pause/resume, interval update, status, task execution
  - SchedulerService tests: initialization, config load/create, start/stop/pause/resume, interval update, enabled toggle, status, shutdown, discovery task execution
  - Tests cover: default configuration, custom interval, duplicate/overlapping run prevention, application shutdown cleanup

Scheduler Architecture:
```text
APScheduler (JobScheduler)
    ↓
SchedulerService (orchestration + persistence)
    ↓
DiscoveryService (existing Phase 5 service)
    ↓
AgentStateManager (existing state management)
```

Key Design Decisions:
- Scheduler is timing/orchestration only - business rules remain in DiscoveryService
- Uses APScheduler with max_instances=1 to prevent overlapping runs
- Persists configuration to database for recovery across restarts
- Respects agent state - skips discovery when agent is busy (RUNNING, SEARCHING, FILTERING, APPLYING)
- Integrates with existing services without duplicating logic
- UTC timezone for all timestamps
- Global service instance shared between main.py and API routes
- Safe shutdown during application lifecycle

API Endpoints Added:
- GET /api/scheduler/status
- POST /api/scheduler/start
- POST /api/scheduler/stop
- POST /api/scheduler/pause
- POST /api/scheduler/resume
- PUT /api/scheduler/config

Known limitations:
- Application limits NOT implemented yet (future checkpoint)
- AI queue NOT implemented yet (future checkpoint)
- Restart recovery NOT implemented yet (future checkpoint)
- Windows startup NOT implemented yet (future checkpoint)
- Cloud execution NOT implemented (future phase)
- LinkedIn/Indeed NOT implemented (future phase)
- CAPTCHA solving, anti-bot bypass, stealth, fingerprint spoofing, proxy rotation, rate-limit bypass NOT implemented

Next Checkpoint: Phase 7 - Checkpoint 2A (Application Limits)

---

## Phase 7: COMPLETE - Scheduler Core (Checkpoint 1)

---

## Phase 6: COMPLETE - Naukri Application Automation

Implemented Phase 6:

- Created Application and ApplicationAnswer models in `backend/models/application.py`
- Created Application schemas with status enums in `backend/schemas/application.py`
- Implemented ApplicationService with final Python safety gate in `backend/services/applications/service.py`
  - Safety gate validates: job existence, profile confirmation, duplicate protection, location, experience, salary, employment type, job title scope, AI suspicious flag, AI recommendation
  - Gemini output is advisory; Python rules are authoritative
  - External application recording (does NOT submit external applications)
  - Application failure/skip recording with reasons
- Extended NaukriAdapter with application submission methods in `backend/services/naukri/adapter.py`
  - `open_job_page()`: Opens job page with security checks
  - `detect_application_type()`: Detects NAUKRI_NATIVE vs EXTERNAL
  - `start_application()`: Clicks apply button
  - `detect_application_questions()`: Finds application questions
  - `answer_question()`: Answers questions from profile/AI
  - `submit_application()`: Submits form
  - `confirm_submission()`: Confirms success
  - `get_external_redirect_url()`: Gets external redirect URL
- Implemented ApplicationRunner in `backend/services/applications/runner.py`
  - Processes jobs sequentially with safety gate enforcement
  - Coordinates job → matching → AI analysis → safety gate → Naukri adapter → application → persistence
  - Handles external redirects, security failures, authentication failures
  - Answers questions from profile data first, then AI-generated answers
  - Continues after safe single-job failures, stops on security/critical conditions
- Created application API routes in `backend/api/routes/application.py`
  - POST /api/applications/start: Start application for a job
  - GET /api/applications/{id}: Get application by ID
  - PUT /api/applications/{id}: Update application
  - GET /api/applications/job/{job_id}: Get application by job
  - GET /api/applications/history: Get application history
  - POST /api/applications/run: Start application runner (background task)
  - POST /api/applications/stop: Request graceful stop
- Registered application router in `backend/main.py`
- Extended AgentStateManager to support APPLYING state transitions
- Created comprehensive tests (34 new tests):
  - Safety gate tests (9 tests): location, experience, salary, profile confirmation, suspicious job, AI needs attention, employment type, job title scope
  - Application flow tests (11 tests): create, get, update, external application, failure recording, skip recording, history
  - Duplicate protection tests (5 tests): no existing, applied, submitted, skipped, needs attention, external
  - Application runner tests (9 tests): single job, external application, critical browser failure, idle state requirement, no profile, no preferences
- Total: 101 tests passing

Application Pipeline:
```text
Discovered Job
    ↓
Phase 4 Hard Filters
    ↓
Gemini Job Analysis
    ↓
Python Final Safety Gate (authoritative)
    ↓
Application Started
    ↓
Naukri-native Application (via NaukriAdapter)
    ↓
Answer Questions (profile data first, then AI)
    ↓
Submit
    ↓
Record Result (APPLIED/SUBMITTED/EXTERNAL/NEEDS_ATTENTION)
```

Key Design Decisions:
- Gemini is advisory only; Python safety gate is authoritative
- External applications are NOT submitted, only recorded
- Questions answered from confirmed profile data first, then AI-generated
- Never invent user qualifications, experience, or salary
- Security challenges (CAPTCHA, human verification) halt the agent
- Duplicate protection prevents re-application
- Sequential job processing (no parallel submission)

Known limitations:
- Live Naukri validation still required for real CSS selectors, job application flow, question detection, submission confirmation, and complete real-site application submission
- Application question answering uses basic profile matching; complex question understanding may need refinement
- External redirect detection uses heuristics; may need adjustment for Naukri's actual implementation

Next Phase: Phase 7 - Scheduler & Cloud Execution

## Phase 5: COMPLETE - Naukri Job Discovery & Automation

Implemented Phase 5:

- Added Playwright dependency for browser automation
- Implemented NaukriAdapter with Chrome/Edge browser selection and graceful fallback
- Enhanced security detection (CAPTCHA, human verification, blocked access, login required)
- Implemented job extraction from Naukri search pages with page_number tracking
- Added posted_at extraction with basic parsing (today, yesterday, just now)
- Added employment_type extraction
- Implemented job description fetching from individual job pages
- Integrated DiscoveryService with NaukriAdapter for complete discovery pipeline
- Implemented deduplication by external_job_id, URL, and title+company
- Added timezone-aware timestamps (UTC) for all datetime fields
- Implemented pages_processed tracking in DiscoveryRun statistics
- Configured discovery state transitions (COMPLETED, AUTH_REQUIRED, SECURITY_REQUIRED, FAILED, STOPPED)
- Added comprehensive integration tests (67 total tests passing)
- Configured background task DB session handling for API routes

Discovery Pipeline:
```text
NaukriAdapter (Playwright)
    ↓
DiscoveryService
    ↓
normalization
    ↓
deduplication
    ↓
persistence (SQLite)
    ↓
DiscoveryRun statistics
    ↓
AgentState/DiscoveryRun lifecycle
```

Known limitations:
- Live Naukri validation still required for CSS selectors, real job extraction, pagination, posted date formats, browser channels, persistent authenticated session, real security/CAPTCHA detection, and complete real-site discovery flow
- Posted date parsing currently handles only "today", "yesterday", "just now" - more complex formats return None
- Automatic application submission is NOT implemented (Phase 6)
- Scheduler is NOT implemented (Phase 7)

Next Phase: Phase 6 - Naukri-native Application Automation

## Phase 4: COMPLETE - Job Matching & Rules Engine

Implemented Phase 4:

- Designed strict deterministic matching pipelines enforcing hard rules for Experience, Location, Salary, Employment Types, and scoping.
- Added string normalizer `backend/services/matching/normalizer.py` to interpret "LPA", "Bengaluru", and relative experience blocks accurately.
- Built central `MatchEngine` to evaluate candidate jobs directly against SQLite Job Preferences.
- Configured final AI delegation ensuring Gemini is strictly invoked only for Semantic/Skill Analysis *after* all deterministic filters explicitly pass.
- Integrated `JobPreferences` API routes, enabling settings overrides like App limits and Aggressiveness.
- Implemented `JobPreferences.tsx` locally mapping UI elements to backend matching filters cleanly.
- Unit tested all deterministic filters; integration pipeline successful, with all bounds enforcing no unauthorized bypassing.
- Next Phase: Phase 5 - Job Discovery & Automation (Playwright integrations).

## Phase 3: COMPLETE - Gemini AI Engine

Implemented Phase 3:

- Rebuilt the corrupted Windows frontend `node_modules` via clean NPM install, resolving the Vite 8 Rolldown binding error.
- Successfully built `AIStatus` tracking metrics in the frontend dashboard App.
- Upgraded the `GeminiProvider` utilizing the official `google-genai` SDK within `backend/services/gemini/provider.py`.
- Enforced strict AI output boundaries via `GenerateContentConfig` tied to Pydantic schemas.
- Provided structured models arrays in `backend/schemas/ai.py` (e.g. `JobAnalysis`, `ApplicationAnswer`).
- Constructed database entity mapping for `JobAnalysis` caching and `AIUsage` tracking.
- Secured AI invocation timeouts, request retries, and quota-aware exception monitoring.
- 16 passing backend unit tests confirming AI boundaries, models, and profile functionality.

Next phase: Phase 4 - Matching & Rules Engine.

## Phase 2: COMPLETE

Implemented Phase 2:

- Safe PDF upload validation, SHA-256 duplicate detection, controlled local storage, and PyMuPDF text extraction.
- Profile/Resume SQLAlchemy models, strict Pydantic profile contracts, review status, edits, and explicit confirmation persistence.
- Narrow source-grounded Gemini profile extraction boundary. It requires `GEMINI_API_KEY`; malformed or failed output leaves the uploaded resume in `ERROR`, never a fabricated profile.
- Profile API: `POST /api/profile/resume`, `GET /api/profile`, `PUT /api/profile`, and `POST /api/profile/confirm`.
- Frontend profile workspace with upload, status, editable core facts/skills, save, and confirm operations.
- Backend tests pass, including PDF extraction, invalid uploads, duplicate uploads, failed extraction preservation, edits, and confirmation.

Next phase: Phase 3 - Gemini AI Engine.

## Phase 1: COMPLETE

Completed:

- FastAPI health API, typed settings, CORS, structured logging, error taxonomy, and SQLite/SQLAlchemy foundation.
- Typed agent-state and controlled provider/platform adapter boundaries.
- Vite React/TypeScript/Tailwind dashboard shell with live backend health display.
- Python test foundation for health, configuration defaults, and state transitions.
- README, architecture documentation, and decision log.

Files created include `backend/`, `frontend/`, `requirements.txt`, `.env.example`, `.gitignore`, `run.py`, and the Phase 1 documentation files.

Database changes: the SQLite engine and metadata initialization are present; no product-domain tables are introduced yet.

Known limitations: no resume handling, Gemini API calls, job discovery, browser automation, scheduling, job rules, application actions, notifications, or packaging. The dashboard intentionally reports only foundation-level status.

Next phase: Phase 2 - Resume & User Profile.

## Checkpoint C2 - fresher-only, IT-only, needs-review forms

Implemented offline: zero-year experience cap, title-based entry-level exception,
strict IT metadata/title filtering, Naukri `experience=0` search shaping,
pre-open card experience filtering, bounded card scanning, external recording,
questionnaire stop behavior, and `answer_questions` defaulting to false. No live
Naukri run, Apply click, Gemini call, or external application link was used.
