# Naukri AI Job Application Agent

## CHECKPOINT E5-R5.4: Native Apply Button Precedes External Body-Text Scan

**Status: E5-R5.4 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live validation - no autonomous cycle, no browser, no Apply click, no backend restart.**

**Root cause (proven from Git + code + offline evidence):** `_observe_application_type()` scanned the entire visible body for external-apply phrases (`apply on company site`, `external application`, `redirecting to`, ...) and returned `EXTERNAL` *before* checking for a visible native Apply button. A native Naukri job page whose job-description prose coincidentally contained one of those phrases was misclassified `EXTERNAL` and never clicked. The ordering was already present at D7 (`e9bf7ac`) and unchanged through `1850cd8` (verified by `git diff`), and an existing test (`test_visible_external_evidence_wins_over_visible_native`) codified it. It is the mechanism that, combined with the pre-E5-R4.1 fabricated-URL defect, locked the 16 jobs: they were classified `EXTERNAL` via this body-scan, and the old `get_external_redirect_url` recorded the identical AmbitionBox page-chrome URL for all of them because no genuine external CTA link existed - i.e., the phrase was incidental prose with a native Apply button present but overridden. The saved real-page snapshot contains none of the phrases (grep), so the defect is a latent false positive that fires only on pages whose prose carries a phrase.

**Fix (`backend/services/naukri/adapter.py`):** `_observe_application_type()` now checks `_find_scoped_apply_button()` first; a visible native Apply control returns `NAUKRI_NATIVE` immediately. The external body-scan runs only when no native control is visible, so genuine external CTAs (which never render a native Apply button) are still detected. This is the smallest evidence-backed change and restores the native-first ordering the D7 success relied on.

**Safety preserved:** `APPLIED` still requires positive confirmation; external applications are still never clicked or submitted; the E5-R4.3 historical-snapshot test (real page -> `NAUKRI_NATIVE`, no false-EXTERNAL log) and CTA URL-grounding still pass; jobs 87/120 (`NEEDS_ATTENTION`) untouched; no scheduler launched; no live cycle.

**Tests (3 new, offline):** `backend/tests/test_naukri_adapter.py` +2 unit (native button wins over unrelated prose phrase; no-button + phrase still `EXTERNAL`), with the old external-wins test updated to the new contract; `backend/tests/test_naukri_adapter_offline_dom.py` +1 Playwright (native button + prose phrase -> `NAUKRI_NATIVE`, no false-EXTERNAL log). Focused: adapter classification 23 passed, offline DOM 10 passed; full backend suite **924 passed, 0 failed** (baseline 921 + 3).

---

## CHECKPOINT E5-R5.3: Signature-Scoped Reconciliation of False External Classifications

**Status: E5-R5.3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live validation - the endpoint has NOT been invoked against the live database, no autonomous cycle, no browser, no Apply click, no backend restart.**

**Blocker (proven from run-61 evidence):** after profile re-confirmation, the dashboard cycle completed with 19 pre-analyzed jobs but only 1 candidate and 0 applications: 16 of the 19 carry `EXTERNAL_APPLICATION` rows all holding the identical `https://www.ambitionbox.com/interviews?utm_source=naukri&utm_medium=desktop&utm_campaign=gnb` URL - the page-chrome false positive fixed by E5-R4.1 (external-classified jobs are never clicked or submitted, so no application was ever opened for them). Two layers permanently lock those jobs out: the candidacy query excludes any job whose application status is not SKIPPED, and the runner's unresolved-prior-attempt guard skips EXTERNAL/NEEDS_ATTENTION with "manual reset required" - yet no reset mechanism existed anywhere in the product. 10 of the 16 locked jobs have APPLY-recommended analyses (scores 65-85).

**Fix (human-triggered, signature-scoped only):** `ApplicationService.reconcile_stale_externals()` (backend/services/applications/service.py) selects only `EXTERNAL_APPLICATION` rows whose `external_url` exactly equals the named constant `STALE_EXTERNAL_PAGE_CHROME_URL`, reclassifies them to `SKIPPED`, records the audit reason `STALE_EXTERNAL_RECONCILE_SKIP_REASON` (stating the prior classification came from the known page-chrome URL, that no external application was opened/submitted/confirmed, and that the job returns to the normal candidate pipeline), clears `needs_attention`, and preserves the record and its URL/method history. It returns the affected count, application IDs, job IDs, and signature, and is idempotent (a second call matches nothing). Exposed as `POST /api/applications/reconcile-stale-externals` (no parameters), which returns `{affected_count, application_ids, job_ids, signature}`. The endpoint is not scheduled, has no scheduler hook, no frontend trigger, and no generic arbitrary-status reset.

**Safety exclusions:** `APPLIED`, `SUBMITTED` (the persisted status of `SUBMITTED_UNCONFIRMED`), `NEEDS_ATTENTION`, `FAILED`, and already-`SKIPPED` rows are never modified even when carrying the signature URL; nothing is deleted; the autonomous cycle never reconciles automatically; released jobs re-enter through the normal deterministic filters (no filter, duplicate rule, safety gate, or limit is bypassed). Jobs 87/120 (`NEEDS_ATTENTION`) remain locked - their real application status is uncertain and must be resolved by a human.

**Live status:** the endpoint has NOT been invoked against the live database; the 16 proven-false rows remain `EXTERNAL_APPLICATION`; the running backend (PID 25760) predates E5-R5.2 and this checkpoint and was not restarted. To use it: approve a backend restart, invoke the endpoint, then trigger a cycle with `max_applications >= 2`.

**Tests (7 new, isolated test databases):** exact-signature rows become `SKIPPED` with history preserved; audit reason recorded (references the URL and "page-chrome"); different external URLs unchanged; `NEEDS_ATTENTION`/`APPLIED`/`SUBMITTED`/`FAILED`/already-`SKIPPED` rows with the signature URL unchanged; second call is a no-op; endpoint reports count/IDs/job IDs/signature accurately; endpoint performs no unrelated status changes. Focused: **7 passed**; full backend suite: **921 passed, 0 failed** (421.12s; baseline 914 + 7).

**Files:** `backend/services/applications/service.py`, `backend/api/routes/application.py`, `backend/schemas/application.py`, `backend/tests/test_reconcile_stale_externals.py` (new).

---

## CHECKPOINT E5-R5.2: Truthful Application Outcomes and Bounded Error Recovery

**Status: E5-R5.2 IMPLEMENTED, TESTED, AND VERIFIED (offline only; all tests mocked). No live validation - no browser, no Apply click, no autonomous-cycle run.**

**A. Truthful unconfirmed submissions:** when the submit button was clicked but `confirm_submission()` found no positive success evidence, `ApplicationRunner` previously returned `APPLIED` (runner.py, "submission may have succeeded even without confirmation"), so the cycle's budget and summary counted an unconfirmed click as a success. Now: the database keeps the existing truthful `SUBMITTED` status and its `applied_at`/history semantics (no retry, no resubmission), and the runner returns a distinct outcome `SUBMITTED_UNCONFIRMED`. Runner and cycle result structures gain a dedicated `submitted_unconfirmed` count; the outcome never increments `applications_count` and never appears under "Applied" in the step-4 printout or SUMMARY (both print `Submitted (unconfirmed): N` instead). The cycle maps `submitted_unconfirmed > 0` to outcome `SUBMITTED_UNCONFIRMED` (tracker app_type `NATIVE`) and includes the key in `reported_outcomes` so an unconfirmed-only result can never be misread as `ERROR`. API compatibility: `AutonomousCycleRunResponse.stats` is a free-form dict, so the new key serializes additively - no schema change, no breaking change.

**B. Bounded error recovery:** `_run_applications` no longer aborts on the first runner `ERROR`. The first isolated `ERROR` is recorded (`failed += 1`) and the loop continues to the next candidate; a **second consecutive** `ERROR` aborts with `stop_reason = "Two consecutive runner errors; aborting remaining candidates"` (non-normal stop, exit code 3 / FAILED). Any valid non-ERROR outcome (`APPLIED`, `SUBMITTED_UNCONFIRMED`, `SKIPPED`, `EXTERNAL`, `NEEDS_ATTENTION`, `FAILED`) resets the consecutive-error counter; a per-candidate exception neither increments nor resets it. `SECURITY_REQUIRED` and `AUTH_REQUIRED` still abort immediately; the max-applications budget, duplicate safeguards, safety gates, and hourly/daily limits remain authoritative. No retry or restart loops were introduced.

**Tests (10 new, all mocked):** `backend/tests/test_autonomous_cycle_outcomes.py` (8: unconfirmed not counted in budget; EXTERNAL/NEEDS_ATTENTION/FAILED free; confirmed APPLIED consumes budget and stops at the limit; one ERROR continues; two consecutive ERRORs stop; a valid outcome resets the counter; SECURITY/AUTH abort immediately) plus 2 runner-level tests in `backend/tests/test_application_runner.py` (unconfirmed submission → `SUBMITTED_UNCONFIRMED` with DB status `SUBMITTED`; confirmed submission still → `APPLIED`). `test_execution_error_stops_cycle_and_reports_failure` in `backend/tests/test_autonomous_cycle.py` was updated to the new two-consecutive-error contract. Focused run: **130 passed**; full backend suite: **914 passed, 0 failed** (446.67s; baseline 904 + 10).

**Live-only uncertainties:** whether a real unconfirmed submission actually succeeded remotely (SUBMITTED rows stay flagged for manual review); whether an isolated session-start ERROR occurs live and whether the next candidate can recover the runtime (a CRITICAL_ERROR state still aborts via the runner).

---

## CHECKPOINT E5-R4.3: Offline Chromium DOM Regression Tests (optional)

**Status: E5-R4.3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live validation - no autonomous cycle, no browser against Naukri, no Apply click, no submit, no DB/retry/preference writes.**

**Scope:** optional offline DOM regression tests in `backend/tests/test_naukri_adapter_offline_dom.py` (9 tests) that exercise the real `NaukriAdapter` read-only detection methods against real Chromium DOM semantics using `page.set_content()` only - the saved historical snapshot `data/job_page_snapshot.html` (gitignored local artifact; tests skip with a clear reason when absent) plus a controlled synthetic page.

**Offline guarantees:** headless Chromium, no persistent/login profile, `context.route("**/*")` aborts every request (zero network egress), no live Naukri URL loaded, and no Apply control is clicked - the popup-observer probe clicks a neutral local button that opens `about:blank`.

**Coverage:** indicator scan reports `NAUKRI_NATIVE` on the real page with no false-EXTERNAL log; the header Apply selector beats the duplicate `#apply-button` (2 present on that page); no applied evidence with both scan modes and no application container; `get_external_redirect_url` returns `None` despite facebook.com and naukri.com page-chrome links (the E5-R4.1 regression case on real DOM); security gate passes a normal page. Synthetic: `EXTERNAL` classification with indicator attribution; CTA grounding returns the example link and rejects the facebook footer; applied-state evidence `'Applied to "Synthetic Role"'`; visible form container; evidence screenshot under pytest `tmp_path`; popup observer records `new_tab_detected=yes` (real context event) and `new_tab_detected=no` (timeout).

**Optional by design:** module-level `pytest.importorskip("playwright")` and a fixture that skips with `Chromium unavailable for E5-R4.3 offline tests: ...` when browser binaries are missing - the normal backend suite does not depend on Chromium. Prerequisite for running them: `playwright install chromium`.

**Deliberate-violation verification:** a throwaway out-of-repo pytest run injected three regressions (broken header selector, empty external-indicator vocabulary, CTA grounding without indicator match); the corresponding correct-behavior assertions all failed (3 failed, exit code 1), so the tests detect real regressions. No existing test or production code was altered.

**Test results:** focused file **9 passed** (19.51s); full backend suite **904 passed, 0 failed** (400.36s; baseline 895 + 9).

**Remains unverified live:** whether Naukri's real Apply click opens a popup; server-side instant-apply persistence behind the D5 reload decision; real click/redirect timing; live security challenges; DOM drift vs the 2026-10-02 snapshot; auth/session-gated rendering.

**Files added:** `backend/tests/test_naukri_adapter_offline_dom.py` (only new tracked file). Existing modifications preserved; nothing committed or pushed.

---

## CHECKPOINT E5-R4.2: Run #59 Validation Instrumentation (prepared; backend restarted on approval)

**Status: E5-R4.2 IMPLEMENTED, TESTED, AND SERVED. Backend restarted on 2026-10-10 10:48:32 with explicit approval; no live validation executed (no cycle, no browser, no Apply click).**

**Purpose:** make the next controlled live run observable without changing application behavior. The instrumentation is read-only: it never clicks an additional control, fills or submits a form, skips a security check, or writes an application, retry-queue, preference, or limit record.

**What is recorded** (`backend/services/naukri/adapter.py`, plus one log line in `backend/services/applications/runner.py`):

1. **External evidence** - the matched `external_text_indicators` phrase with the page URL; the external CTA link's visible text and href when one exists, otherwise the explicit fallback to the job URL; and `Job <id> requires external application (external_url=...)`.
2. **Page URL around the Apply click** - `Apply click: page url before click: ...` and `Apply click: page url after click: ...`.
3. **Popup / new tab** - a bounded `page.context.wait_for_event("page", ...)` observer spanning the post-click window + reload settle + 5s grace, logging `new_tab_detected=yes url=...` or `new_tab_detected=no`. The observed page is only read: never clicked, filled, navigated, or closed.
4. **Timestamped bounded-window container checks** - `post-click check #N at +X.XXs: applied=... container=...` for every iteration, then `post-click window closed: elapsed=... checks=...`.
5. **Terminal state** - both `NEEDS_ATTENTION` exits log `terminal_state=NEEDS_ATTENTION ... screenshot=<path>`, with a PNG written to `data/apply_terminal_<label>_<stamp>.png` (covered by the existing `data/*.png` ignore rule).

**Evidence discipline unchanged:** `APPLIED` still requires positive visible evidence; external applications are still never clicked or submitted; the security check still runs after the click and after the reload.

**Runtime state (verified 2026-10-10):** the pre-restart backend (PID 18732 / child 22596, started 08:39:13) predates the adapter edits (09:26:54) and was stopped on approval. Port 8000 was confirmed free, then a new backend was started at **10:48:32** as PID **25760** (parent 17088) via `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` (no `--reload`, E4-R2 requirement). Verified after start: `GET /api/health` → `status=ok, agent_state=IDLE`; `GET /api/readiness` → all components healthy (database, schema, configuration, storage, ai_provider, runtime_environment); `GET /api/autonomous-cycle/status` → `IDLE`, no active run; `GET /api/agent/status` → scheduler `is_running=false`, `last_run_at=null` (startup does not auto-start the scheduler, `backend/main.py:81`); startup recovery completed with no errors; log shows only dashboard status polling - no apply, discovery, or click activity. Because the adapter module is imported at process start from the working tree, the running process serves the E5-R4.1/E5-R4.2 adapter code.

**Restart executed (approved - "Restart backend only"):**

```powershell
Stop-Process -Id 22596, 18732                 # executed 10:48; port 8000 then confirmed free
& "C:\Users\ajays\Desktop\Naukri Agent\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000   # executed; new PID 25760
```

**Test coverage:** 6 new tests in `TestValidationInstrumentation`; `test_naukri_adapter.py` 143 passed; full backend suite **895 passed, 0 failed**.

**Not performed:** dashboard cycle, browser session, Apply click, application attempt, commit/push.

---

## CHECKPOINT E5-R4.1: Run #59 Post-Click Window & External Evidence Grounding

**Status: E5-R4.1 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live cycle run - awaiting human review.**

**Run #59 (dashboard-triggered, `max_applications = 2`, 2026-10-10):** 79 discovered, 62 hard-filtered, 17 pre-analyzed, 5 candidates, **0 genuine Naukri-native applications** - 3 `EXTERNAL_APPLICATION` (jobs 55/57/86), 1 `NEEDS_ATTENTION` (job 87), 1 skipped.

**Root causes (demonstrated offline):**

1. The bounded post-click window was not honored. `start_application()` ran `detect_applied_state()` first in every polling iteration; that method walks every element of the page (a visibility + text round trip each; 1,009 elements in `data/job_page_snapshot.html`) before the application-container check. The whole 8s window elapsed in a single pass: Apply click `03:12:49.075` to reload decision `03:13:02.379` = 13.3s, so the container was observed at most once, at or after the deadline.
2. The recorded external URL was fabricated. `get_external_redirect_url()` returned the first non-Naukri anchor, which is page chrome. Of the 20 `EXTERNAL_APPLICATION` rows, 19 (including run #59's three) and their notifications carry the identical AmbitionBox promo URL - which occurs 30 times on the captured Naukri page - and the remaining row carries Naukri's Facebook URL. Neither is a redirect target.

**Fix:**

- `detect_applied_state(page, scan_whole_page: bool = True)` - the bounded loop passes `scan_whole_page=False` (header/banner evidence only) and the page-wide scan runs exactly once after the window, before the reload decision. Container checks now repeat inside the window. The terminal `NEEDS_ATTENTION` warning logs `page.url`.
- `get_external_redirect_url()` returns only a non-Naukri link whose own visible text matches the shared `external_text_indicators`; otherwise `None`, so the runner records `job.url`. `_observe_application_type()` logs the matched indicator so an `EXTERNAL` decision is attributable.

**Unchanged:** classification precedence and external-first ordering; external jobs are never clicked or submitted; `APPLIED` still requires confirmation evidence; safety gates, duplicate protection, `max_applications`, hourly/daily limits, preferences. No application row, retry queue, preference, limit, or database record was modified.

**Test coverage:** 9 new focused tests (`TestPostClickBoundedWindow`, `TestExternalRedirectEvidence`); `test_naukri_adapter.py` 137 passed; runner/flow/safety/cycle/AI files 187 passed; full backend suite **889 passed, 0 failed**.

**Files modified:** `backend/services/naukri/adapter.py`, `backend/tests/test_naukri_adapter.py`

**Open item (not resolvable offline):** job 87's apply surface never appeared in the main page - no Applied badge even after the reload, no visible container matching `[role="dialog"] / .apply-drawer / .apply-modal / form`, and the post-click security check found no login/CAPTCHA text. Offline evidence cannot distinguish a no-op click, a surface opened in a new tab, or markup unmatched by the existing container selectors, and no selector was guessed.

---

## CHECKPOINT E5-R3: Freshness-First Discovery & Advisory-Only AI Recommendations

**Status: E5-R3 IMPLEMENTED, TESTED, AND VERIFIED (offline only). No live cycle run — awaiting human review.**

Two defects silently reduced and misranked eligible candidates. First, the final safety gate rejected jobs that matched the user's saved preferences and passed every deterministic rule solely because Gemini returned a subjective `NEEDS_ATTENTION` recommendation. Second, discovery counted every scanned card against its scan budget while the cycle ordered candidates by raw `discovered_at`, so pages dominated by already-known duplicates could consume the budget and leave fresh eligible jobs unprocessed.

**Implementation:**

- `backend/services/applications/service.py`: `run_final_safety_gate()` no longer blocks on the AI recommendation — Gemini is advisory and the only AI-derived block is the explicit `job_analysis.suspicious` fraud flag. All deterministic gates (confirmed profile, duplicate/`APPLIED` protection, location, fresher/experience, IT-scope, salary minimum, employment type, title/search scope) are unchanged and remain authoritative.
- `backend/services/naukri/adapter.py`: `_parse_posted_date()` returns a timezone-aware UTC datetime for `today`/`just now`, `yesterday`, `N days/weeks ago`, `30+ days ago`, and common absolute formats; unrecognised text returns `None` (never fabricated). Each page's cards are emitted freshness-first (known dates newest-first, unknown last). No Naukri URL/sort parameter or pagination behavior was changed.
- `backend/services/discovery/service.py`: the scan budget (`max_cards`) now applies to **new distinct jobs**, so duplicate-heavy pages cannot starve fresh jobs. Re-seen duplicates advance `last_seen` and adopt a newer grounded `posted_at` (unknown never overwrites known).
- `backend/services/autonomous_cycle/service.py`: freshness-first ordering. `_apply_hard_filters_and_enqueue()` spends the bounded Gemini budget on the newest-posted eligible jobs (unknown date last), then by `discovered_at` and `match_score`; `_run_applications()` processes newest-posted candidates first (nulls last).

**Constraints honored:** no saved-preference changes; no hard-filter, duplicate-protection, safety-check, or limit bypass; no URL/sort-parameter change; unknown dates never invented; no live Naukri cycle, browser, Apply click, or Gemini call; no database writes; no commit/push.

**Test coverage:** 270 focused tests pass across `test_application_safety_gate.py` (20), `test_discovery.py` (15), `test_naukri_adapter.py` (128), and `test_autonomous_cycle.py` (new `TestFreshnessFirstOrdering`). Full backend suite: 878 passed, 0 failed (2026-10-09); the two failures previously reported here were resolved in E5-R3.1 — an outdated C2 IT-scope test expectation and a dashboard test-ordering isolation case. Zero regressions.

**Files modified:** `backend/services/applications/service.py`, `backend/services/naukri/adapter.py`, `backend/services/discovery/service.py`, `backend/services/autonomous_cycle/service.py`, and the four corresponding test files.

**Documentation updated:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md`

---

## CHECKPOINT E4-R10: Targeted Role-Matching Improvement

**Status: E4-R10 IMPLEMENTED, TESTED, AND VERIFIED**

E4-R10 improves deterministic role matching so clearly relevant entry-level software and data roles are not rejected merely because their titles use reasonable variations of existing target-role names. The goal is greater relevant-job coverage, not simply more candidates.

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

**Test coverage:**
- 10 new tests for role-matching improvements: software development trainee, data science roles, power bi roles, qa roles, sql roles
- 9 new regression tests: SQL Server Administrator exclusion, boundary cases (sales mention in tech role, hardware with software), pure sales, mechanical, manufacturing, HR, operations roles
- Total: 54 tests in test_matching_rules.py — all PASS
- All verified failing jobs now PASS role-matching:
  - Job 55 (Software Development Trainee): PASS
  - Job 62 (Data Science Intern/Fresher): PASS
  - Job 64 (Power Bi Internship): PASS
  - Job 87 (Qa Engineer): PASS
  - Job 112 (ELK Engineer): FAIL (not in user preferences, DevOps/monitoring-specific, requires separate decision)

**Files modified:** `backend/services/matching/engine.py`, `backend/tests/test_matching_rules.py`

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

**Files modified:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md` (documentation only).

---

## CHECKPOINT E4-R2: Windows Playwright Runtime Requirement (Documentation Only)

**Status: DOCUMENTATION ONLY — E4 live validation has NOT yet succeeded. No live cycle was run in this checkpoint.**

This checkpoint documents the runtime/environment requirement discovered during E4 validation and resolves the E4 browser-startup blocker. It is a documentation-only checkpoint: no E4 execution occurred, no Dashboard Run was clicked, no `POST /api/autonomous-cycle/run` was called, no database was modified, no backend/frontend source code was modified, no Playwright configuration was changed, and no asyncio workaround was added.

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

**E4 status tracking:**

- E4 live validation has NOT yet succeeded.
- Historical E4 FAILED runs (including the two accidental curl-triggered attempts on 2026-10-08 that failed before browser startup) remain preserved and unaltered.
- The next checkpoint is E4 final live validation against a non-reload Uvicorn backend.

**Do not claim E4 PASS.**

**Files modified:** `README.md`, `docs/MASTER_PRD.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_STATUS.md`, `docs/DECISIONS.md` (documentation only).

---

## CHECKPOINT E4-UI: Dashboard max_applications Control

**Status: E4-UI COMPLETE — Dashboard can select max_applications=1 — VALIDATED LIVE IN RUN #52**

**APPLIED count: 3 (unchanged — no new applications in E4-UI or Run #52)**

The E3 dashboard hardcoded `max_applications = 2` and exposed no user control, so it could not satisfy the E4 live-validation requirement of `max_applications = 1`. E4-UI adds a selectable Maximum applications dropdown (1-10, default 1) to the Run Autonomous Cycle confirmation modal in `frontend/src/app/App.tsx`.

**Frontend changes:**
- `maxApplications` initial state changed from `2` to `1`
- `MAX_APPLICATION_OPTIONS` constant (1-10) matching the server schema
- `handleMaxApplicationsChange()` rejects out-of-range values
- Modal `select` control bound to `max_applications`, disabled while starting, with `aria-label`
- Live confirmation line stating how many real Naukri applications will be attempted

**Backend: NO CHANGES.** `POST /api/autonomous-cycle/run` and `GET /api/autonomous-cycle/status` are untouched; server validation (1-10) and the `max_applications * 2` Gemini budget remain authoritative.

**Verification:** `npm run build` PASS (1588 modules, 289.06 kB JS bundle). Built bundle verified to contain the select control and no `useState(2)` literal.

**Live validation (Run #52):** The Dashboard UI control was used to trigger the cycle with `max_applications = 1`. The cycle executed and returned `COMPLETED` with `lock_held = false`, confirming the UI control, confirmation modal, status polling, and completion handling all work end-to-end. Zero applications were submitted in Run #52 (see CHECKPOINT E4 above); the three pre-existing applications belong to earlier runs.

**Files modified:** `frontend/src/app/App.tsx`

**No live Naukri action performed in E4-UI beyond the documented Run #52 cycle.**

---

## CHECKPOINT E4-R: Autonomous Cycle Recovery & Execution-Safety Hardening

**Status: COMPLETE (source/test hardening only); E4 live cycle subsequently EXECUTED in Run #52 (see CHECKPOINT E4).** On 2026-10-08, two accidental curl-triggered E4 attempts failed before a browser session started. No jobs were discovered, no Apply click or CAPTCHA/security event occurred, and no application was submitted. E4-R does not run a live cycle; it prepared the runtime state model and recovery paths that Run #52 later exercised successfully.

Runtime diagnostics now distinguish process-local `active_state` (`IDLE`/`RUNNING`) from the historical `last_run` result. `GET /api/autonomous-cycle/status` is strictly read-only and reports lock state plus safe active/last-run details; it cannot execute a cycle. The execution lock is released on success, failure, and initialization errors. Browser launch failures retain the underlying Playwright exception in the failed discovery-run record and server log instead of only the former generic message.

**Run #52 exercised these paths:** the cycle started, acquired the lock (`active_state=RUNNING`), completed normally, and returned to `IDLE` with `lock_held=false`. The `COMPLETED` terminal status and zero-application outcome are recorded in `last_run`, distinct from the active state.

## CHECKPOINT E3: Safe Dashboard Autonomous-Cycle Control

**Status: E3 COMPLETE — Dashboard can safely trigger autonomous cycles**

**APPLIED count: 3 (unchanged from D7 — no new applications in E3)**

E3 enables safe manual triggering of the autonomous job application cycle from the dashboard by extracting the existing autonomous cycle logic into a reusable service and adding control/status API endpoints. The dashboard now provides explicit user confirmation, status polling, and completion statistics while preserving all safety boundaries.

**New control/status API endpoints:**
- `POST /api/autonomous-cycle/run` — start autonomous cycle with max_applications limit (1-10, default 2)
- `GET /api/autonomous-cycle/status` — get current cycle status (IDLE/RUNNING/COMPLETED/FAILED) with stats

**Service extraction:**
- `backend/services/autonomous_cycle/service.py` — extracted `AutonomousCycle` class from CLI
- Both CLI and FastAPI now use the same service for consistent behavior
- All safety boundaries preserved: D6.1, D6.2, C2, D4/D5, D7

**Frontend changes:**
- Autonomous Cycle status panel: shows IDLE/RUNNING/COMPLETED/FAILED state
- Run Autonomous Cycle button with explicit confirmation modal
- Confirmation modal explains: real Naukri applications, max_applications limit, safety rules, concurrency protection
- Status polling at 4-second intervals while RUNNING
- Dashboard data refresh after COMPLETED/FAILED
- Completion stats display: applied, needs_attention, external applications
- HTTP 409 Conflict handling: shows "An autonomous cycle is already running"

**Safety:**
- Process-level concurrency lock (threading.Lock) prevents concurrent cycles
- Server-authoritative max_applications (client cannot control Gemini budget)
- HTTP 409 Conflict returned if cycle already running
- No secrets, API keys, credentials, cookies, or session data in any response
- Frontend only calls control/status APIs — no direct Naukri or Gemini access

**Test coverage:**
- 92 backend tests (`test_autonomous_cycle.py`): logic, boundaries, budgets, filtering — all PASS
- 11 backend tests (`test_autonomous_cycle_api.py`): API endpoints, concurrency, security — all PASS
- 30 dashboard tests (E1/E2): PASS
- 181 total tests (autonomous_cycle + matching_rules + application_safety_gate + dashboard): PASS
- Frontend TypeScript: PASS
- Frontend production build: PASS (23.76s)

**Files added:** `backend/services/autonomous_cycle/service.py`, `backend/api/routes/autonomous_cycle.py`, `backend/schemas/autonomous_cycle.py`, `backend/tests/test_autonomous_cycle.py`, `backend/tests/test_autonomous_cycle_api.py`

**Files modified:** `backend/main.py`, `backend/tests/conftest.py`, `run_autonomous_cycle.py`, `frontend/src/types/api.ts`, `frontend/src/services/api.ts`, `frontend/src/app/App.tsx`

**Scheduler:** Discovery-only. Integration with autonomous cycle deferred.

**No live Naukri action performed in E3.**

---

## CHECKPOINT E2: Dashboard Operational Visibility & Safe Control Foundation

**Status: E2 COMPLETE — Dashboard provides accurate operational view**

**APPLIED count: 3 (unchanged from D7 — no new applications in E2)**

E2 builds on E1's real backend → frontend integration to make the dashboard an accurate operational view of the Naukri Agent. The dashboard now provides visibility into what the system last did, what happened during the latest discovery/autonomous run, application outcomes, jobs needing attention, and system health status.

**New read-only API endpoint:**
- `GET /api/dashboard/needs-attention` — applications requiring user review with job title/company

**Frontend changes:**
- Latest Run section: displays latest discovery run status, ID, jobs discovered, new jobs, completion date
- Needs Attention section: dedicated section for applications requiring review with skip/failure reasons
- Refresh button: manual refresh with loading state and visual feedback (spin animation)
- System Health: improved presentation using existing health endpoint data
- E1 sections preserved: Metrics, Profile panel, Activity feed with real data

**Security:** No secrets, API keys, credentials, cookies, `confirmation_evidence`, or `resume_hash` in any new response. All new endpoints are GET-only. No execution controls added.

**Test coverage:**
- 30 backend tests (`test_dashboard.py`): 21 E1 + 9 E2 — all PASS
- Key regressions (41 tests): PASS
- Frontend TypeScript: PASS
- Frontend production build: PASS (3.10s)

**Files modified:** `backend/schemas/dashboard.py`, `backend/api/routes/dashboard.py`, `backend/tests/test_dashboard.py`, `frontend/src/types/api.ts`, `frontend/src/services/api.ts`, `frontend/src/app/App.tsx`

---

## CHECKPOINT E1: Frontend/API Integration Foundation

**Status: E1 COMPLETE — Dashboard connected to real backend data**

**APPLIED count: 3 (unchanged from D7 — no new applications in E1)**

E1 connects the React + TypeScript dashboard to the already-proven FastAPI backend with real read-only data. Placeholder values such as "Not available" and "Not configured" are replaced by live backend state.

**New read-only API endpoints:**
- `GET /api/dashboard/summary` — discovery stats, application counts, profile status (no secrets)
- `GET /api/dashboard/recent-applications` — application records enriched with job title and company

**Frontend changes:**
- Metrics: Applications applied, Jobs discovered, Discovery runs, Needs attention — all real values
- Profile panel: real `status` and `confirmed` from backend
- Activity feed: real application records with job title, company, status, applied date
- Per-section loading/error/empty states — backend offline does not crash the dashboard
- Retry re-fetches all dashboard data

**Security:** No secrets, API keys, credentials, cookies, `confirmation_evidence`, or `resume_hash` in any new response. All new endpoints are GET-only.

**Test coverage:**
- 21 new backend tests (`test_dashboard.py`): empty DB, counts, job enrichment, limit capping, no-secrets checks, read-only (405 on mutations) — all PASS
- Key regressions (95 tests): PASS
- Frontend TypeScript: PASS
- Frontend production build: PASS (15.81s)

**Files added:** `backend/api/routes/dashboard.py`, `backend/schemas/dashboard.py`, `backend/tests/test_dashboard.py`

**Files modified:** `backend/main.py`, `frontend/src/types/api.ts`, `frontend/src/services/api.ts`, `frontend/src/app/App.tsx`

---

## CHECKPOINT D6.2: Bounded Gemini Candidate Evaluation

**Status: D6.2 IMPLEMENTED, TESTED, AND VERIFIED**

**APPLIED count: 1 (from D4/D5 - no new applications in D6.2)**

D6.1 bounded the AI queue enqueue budget, but MatchEngine was still calling Gemini for every job that passed deterministic filters BEFORE the enqueue budget was applied. This caused uncontrolled Gemini usage during autonomous cycles.

**D6.2 Fix:**
- Added `evaluate_job_deterministic()` method to MatchEngine that runs only deterministic checks (no Gemini)
- Autonomous cycle now: deterministic filters → bounded candidate selection → Gemini evaluation for only bounded candidates
- Gemini budget formula: `max_applications * 2` (unchanged from D6.1)
- Application limit: `max_applications` (unchanged)
- Fixed queue isolation: `_process_ai_queue()` only processes items enqueued by this cycle
- Fixed candidate sorting: newest discovered_at first (matches comment)
- Deduplicated deterministic logic via shared `_run_deterministic_checks()` method

**D6.2 Test Coverage:**
- 92 tests passing in test_autonomous_cycle.py (includes 10 D6.2 tests)
- 41 tests passing in test_matching_rules.py
- 0 failures

**Gemini Safety Verification:**
- NEW Gemini evaluations during autonomous cycle are bounded BEFORE invocation
- Pre-existing queue items from other sources are NOT processed by autonomous cycle
- For max_applications=1: NEW Gemini evaluations <= 2
- For max_applications=2: NEW Gemini evaluations <= 4
- For max_applications=3: NEW Gemini evaluations <= 6
- Deterministically rejected jobs never call Gemini
- Cached analyses do not cause NEW Gemini calls

**Note:** D7 live validation has NOT been performed. D6.2 is a source implementation checkpoint only.

---

## CHECKPOINT D7: Multi-Application Live Validation

**Status: D7 LIVE VALIDATION PASSED**

**APPLIED count: 3 (1 from D4/D5, 2 from D7)**

D7 validated the autonomous cycle can process multiple independent eligible Naukri candidates and apply to more than one job when safe candidates are available.

**D7 Live Validation (2026-10-07):**

Command: `python run_autonomous_cycle.py --max-applications 2`

Results:
- Discovery run #32: 103 jobs discovered, 60 hard filtered
- D6.2 Gemini budget: 4 (max_applications=2 × 2)
- NEW Gemini evaluations: 4 (exactly at budget)
- Candidates capped: 5
- Budget respected: YES
- Current-run isolation: PASS (only AUTONOMOUS_CYCLE queue items processed)

Application Outcomes:
- Job 99 (Neorealm Solutions): EXTERNAL_APPLICATION (no submission)
- Job 86 (Futureacad): SKIPPED (unpaid internship)
- Job 85 (Access Automation): APPLIED (record #24, NAUKRI_NATIVE)
- Job 59 (Capgemini): APPLIED (record #25, NAUKRI_NATIVE)

Final:
- APPLIED: 2
- NEEDS_ATTENTION: 1
- SKIPPED: 1
- EXTERNAL: 1
- Apply clicks: 2 (exactly once per applied job)

Safety:
- Duplicate protection: PASS
- Current-run isolation: PASS
- No external submissions
- No CAPTCHA/security bypass
- No fabricated answers
- max_applications hard cap: PASS

**D7 Verdict:** PASS — multiple applications validated

**Source Changes:** NONE (D7 is a validation checkpoint only)

---

## CHECKPOINT D6.1: Bounded Gemini Look-Ahead for Multi-Application Runs

**Status: D6.1 IMPLEMENTED AND TESTED**

**APPLIED count: 1 (from D4/D5 - no new applications in D6.1)**

D6 exposed that `max_applications` was incorrectly used as both the Gemini candidate cap AND the actual application limit. This prevented backup candidates when initial candidates were rejected.

**D6.1 Fix:**
- Separated Gemini candidate budget from actual application limit
- New formula: `max_gemini_candidates = max_applications * 2`
- Example: `max_applications=2` enqueues 4 candidates to Gemini, but only attempts 2 applications
- This provides bounded look-ahead (backup candidates) while preventing uncontrolled Gemini usage

**D6.1 Live Validation (2026-10-07):**
- Command: `python run_autonomous_cycle.py --max-applications 2`
- Result: 103 jobs discovered, 69 hard filtered, 11 pre-analyzed, 0 newly queued
- Cycle was safe: 0 Apply clicks, 0 new APPLIED
- No external applications submitted
- No questionnaires answered
- Application 18 (from D4/D5) correctly excluded

**Test coverage:** 261 tests passing (83 autonomous_cycle + 41 matching_rules + 119 naukri_adapter + 18 application_safety_gate), 11 new D6.1 tests, 0 failures

---

## CHECKPOINT D5: First Verified Native Naukri Application

**Status: FIRST VERIFIED NATIVE NAUKRI APPLICATION: SUCCESS**

**APPLIED count: 1**

- Job 23, NetM Corporate Solutions, "Software Engineer / Developer"
- D4 applied click submitted the application to Naukri
- D5 investigation confirmed `#already-applied` span visible after page reload
- `detect_applied_state()` returns `(True, "Applied")` on live page
- Database: application 18 → APPLIED, applied_at=2026-10-07, method=NAUKRI_NATIVE, confirmation_evidence="Applied"

**D5 Fix (surgical):**

`start_application()` in [`backend/services/naukri/adapter.py`](backend/services/naukri/adapter.py) now adds one bounded page reload after the 8-second in-page timeout. If `detect_applied_state()` finds evidence on the reloaded page, the application is confirmed as APPLIED. This is read-only — the Apply button is NOT clicked again.

**Test coverage:** 238 focused tests passing, 14 new D5 tests, 0 failures

---

## CHECKPOINT D4: First Verified Native Naukri Application (Apply clicked — evidence confirmed by D5)

**Status:** Physical Apply click reached and executed. Evidence confirmed by D5 reload validation.

**Live run (conducted):**
- Discovery: 103–104 current-run jobs
- 70 hard-filtered; 11 pre-analyzed candidates proceeded to application phase
- 7 EXTERNAL detected (no external submission)
- 1 candidate (NetM Corporate Solutions) reached NAUKRI_NATIVE classification
- Apply button physically clicked ONCE
- No post-click Applied evidence within 8 seconds
- Application 18 recorded as NEEDS_ATTENTION with no confirmation_evidence

**Bug fixes applied:**
- `run_autonomous_cycle.py`: Pre-existing analyses no longer block the cycle (tracked as `pre_analyzed`)
- `backend/services/applications/service.py`: Title scope check uses `title_matches_allowed_role()` instead of strict substring matching

**Test coverage:** 224 focused tests passing, 0 failures

---

## CHECKPOINT D1: Autonomous Discovery Tracking

Implemented current-run job ID tracking to prevent historical DB jobs from being processed when live discovery fails. The autonomous cycle now tracks the current DiscoveryRun and only processes jobs from that specific run.

**Key Features:**
- `DiscoveryRun` model includes `current_run_job_ids` column (comma-separated for SQLite compatibility)
- DiscoveryService tracks job IDs in memory during discovery
- Both new jobs and existing jobs (duplicates) are added to current-run tracking
- Autonomous cycle filters jobs to only those in the current run
- Cycle stops with error if `current_run.jobs_discovered == 0`

**Direct Naukri Search Navigation:**
- Removed homepage navigation dependency - navigates directly to search URL
- Simplified security check to single call after search navigation
- Reduced navigation time and potential failure points

**Role Targeting and Metadata Enrichment:**
- Deterministic role/title targeting in MatchEngine before IT metadata gate
- Explicitly rejects unwanted specializations: Java, PHP, .NET, C#, C++, Power Platform, Platform Engineer, Salesforce, SAP, ServiceNow, embedded, firmware, hardware, electrical, mechanical, civil, sales, marketing, HR, operations
- Allowed role families: data (analyst, engineer), software (engineer, developer), devops, python developer
- Enhanced NaukriAdapter metadata extraction with JSON-LD parsing, "Other Details" section extraction, and fallback body text scanning

**Live Read-Only Validation (2026-10-06):**
- 105 job cards discovered across 11 pages
- 82 jobs tracked in current run (including existing duplicates)
- 21 historical jobs excluded from current run
- Current-run tracking confirmed working
- Focused current-run tracking tests: 12 passed
- Full backend suite: 681 passed, 0 failures

## CHECKPOINT C: Autonomous Cycle Command

`run_autonomous_cycle.py` provides a command-line interface for running the complete autonomous job application cycle:
discovery → hard filters → AI queue → Gemini → final safety gate → ApplicationRunner.

**Flags:**
- `--max-applications N`: Limit on real applications (default: 1). Gemini candidate budget is `max_applications * 2` to provide backup candidates.
- `--dry-run`: Discovery and analysis only, no Apply clicks or application records
- `--max-jobs N`: Cap on jobs inspected per run (default: unlimited)

**Behavior:**
- Uses saved profile and job preferences
- Searches Naukri, applies hard filters, runs AI analysis, executes final safety gate
- Applies to eligible NATIVE jobs only (external jobs are skipped)
- Re-classifies native/external immediately before the click
- Requires post-click Applied evidence and records APPLIED with applied_at, method, and confirmation_evidence
- Stops after N real applications, on hourly/daily limits, on SECURITY_REQUIRED or AUTH_REQUIRED, on critical error, or when candidate list is exhausted
- S&P job `300926927428` is always excluded
- No input() prompts anywhere

**Output:**
- Per-job decision table (company, title, native/external, salary/experience/employment filter result, Gemini result, gate result, outcome)
- Final summary with counts
- Exit code 0 on normal completion, non-zero on AUTH/SECURITY/critical stop
- "Normal completion" includes reaching the configured `--max-applications` limit and an exhausted candidate list: these return exit code 0 with terminal status `COMPLETED`. AUTH/SECURITY stops return exit code 2; any other critical stop returns exit code 3. Both are reported as `FAILED`.
- A candidate the application runner could not inspect (browser session did not start, or the agent state was unusable) is reported as `ERROR`, never as `SKIPPED`, and stops the run. No application row is created for it.
- Empty candidate list reported as "0 eligible jobs found" (not a failure)

**Examples:**

Dry-run (discovery and analysis only, no Apply clicks):
```powershell
python run_autonomous_cycle.py --dry-run --max-jobs 10
```

First live run with 1 application:
```powershell
python run_autonomous_cycle.py --max-applications 1 --max-jobs 10
```

**Note:** This command builds and tests offline only. Do not run it live yourself; no Apply clicks, no Gemini calls, no weakening of filters/limits/duplicate rules/safety gate. Never apply to EXTERNAL jobs. Tests must be fully green before any commit.

## Phase 10 Supervised Live Launcher (Build Only)

`phase10_live_apply_launcher.py` is an explicitly gated launcher for a single manually supervised native-flow validation. It is not executed by the project test suite. It rejects S&P Global job `300926927428`, requires a database backup before any ORM write, requires exact `PROCEED <job_id>` and `SUBMIT <job_id>` confirmations, and uses `ApplicationRunner` with its supervised form-stop boundary. The launcher never bypasses CAPTCHA/security checks and does not retry.

Run manually only after reviewing the pre-flight output:

```powershell
& ".venv\Scripts\python.exe" phase10_live_apply_launcher.py 240926500723
```

Offline launcher and runner tests do not open Naukri, call Gemini, click controls, or write the production database.

## Phase 10 Application-Type Reliability: IMPLEMENTED

`NaukriAdapter.detect_application_type()` now performs one bounded 500 ms settling observation when the initial visible page contains neither definitive external nor native evidence. External indicators remain authoritative, visible native selectors remain required for `NAUKRI_NATIVE`, and no-evidence states return `AMBIGUOUS` rather than being treated as native. The application runner treats ambiguity as `NEEDS_ATTENTION` without creating an application record.

Focused adapter coverage includes delayed native/external evidence, hidden controls/text, external-first precedence, and ambiguous states. The full Naukri adapter suite passed with 96 tests. A read-only live check found Quadrasystems ambiguous on both immediate and settled observations, while Cisco remained clearly external. No Apply or Submit action occurred; automated successful application count remains 0.

## Phase 10 Live Native Application Test: BLOCKED

On 2026-10-01, the authenticated persistent Playwright session opened Naukri successfully and showed no visible CAPTCHA, security challenge, login wall, or access block. The backend readiness endpoint reported `ready`; the confirmed profile, configured preferences, compatible schema, and unused application limits were present.

A single bounded discovery pass inspected five `Data Analyst` results without clicking Apply. No safe eligible native candidate was available: four candidates failed duplicate, employment-type, or external-classification checks, and the one native result was already processed. No Gemini analysis or application flow was started, so no submission was attempted. The database remained unchanged at 10 application records and 0 APPLIED/SUBMITTED records. Automated successful application count remains 0.

Phase 10 live submission validation remains blocked until a fresh candidate passes all configured rules and duplicate protection.

## Phase 10 Database Schema Migration: IMPLEMENTED

The Phase 10 schema migration ensures all databases (SQLite and PostgreSQL) have required columns for explicit applied state detection. The migration runs automatically during application startup via `initialize_database()`, is fully idempotent, and preserves all existing data.

**Key Implementation Details:**
- Migration mechanism: Additive `ALTER TABLE` with column existence checks (Phase 9B-4 pattern)
- Idempotent: Safe to run multiple times; already-present columns are skipped
- Startup integration: Runs before request handling during FastAPI lifespan initialization
- Schema validation: `/readiness` endpoint reports `schema: compatible` or missing columns
- Standalone command: `python -m backend.database.database` for manual execution
- Database support: SQLite (tested) and PostgreSQL (verified for syntax compatibility)
- Local migration: Applied to `data/naukri_agent.db` (backup: `data/naukri_agent.db.bak-before-migration`)
- Test coverage: 7 focused migration tests + 557 full backend suite tests all passing

**Verification Results (Local SQLite):**
- Application count: 10 (unchanged by migration)
- Record 10 status: APPLICATION_STARTED (unchanged)
- APPLIED/SUBMITTED count: 0/0 (unchanged)
- confirmation_evidence column: Added successfully
- is_dry_run column: Already present from Phase 9B-4
- ORM queries: Executing without OperationalError

## Phase 10 Application Boundary Fix: IMPLEMENTED OFFLINE

The focused offline checkpoint now detects explicit post-Apply `Applied` evidence
with bounded waits, scopes question detection to visible editable application
containers, computes profile experience from elapsed dates, classifies native versus
external jobs before creating `APPLICATION_STARTED`, and prevents repeat attempts
after `EXTERNAL_APPLICATION` or `NEEDS_ATTENTION` without a manual reset. Confirmation
evidence is persisted with native application records. Unit and full backend tests
run against the isolated SQLite database only. No live Naukri activity, Gemini call,
Apply/Submit click, or application submission occurred; the successful application
count remains 0.

Windows-first, local-first foundation for a controlled job-application agent. Deterministic rules will remain the execution authority; AI and browser automation are intentionally not implemented in Phase 1.

## Phase 9B-4 Safety Boundary

Dry-run application execution is now pre-Apply inspection only. It opens and classifies the candidate page, records an explicit `is_dry_run` inspection record, and stops before any native or external Apply action; it does not invoke `start_application()`, answer questions, submit, or confirm submission. Application lifecycle data distinguishes `PRE_APPLY`, an unverified Apply/form boundary, `FORM_OPENED`, `APPLIED`, `SUBMITTED`, and `NEEDS_ATTENTION`. Native Apply semantics remain unknown, so Phase 9B-3 live form-boundary validation remains incomplete. No live application occurred in this checkpoint.

## Status

**Phase 10 Database Schema Migration: Complete (Local SQLite Migrated)**

Schema migration checkpoint is complete:
- Root cause identified: confirmation_evidence column in ORM model but missing from initialize_database()
- Solution implemented: Idempotent ALTER TABLE with column existence checks
- Startup integration: Runs before request handling
- Readiness check: Added to `/readiness` endpoint with schema compatibility validation
- Full test suite: 557 tests passing (includes 7 new migration tests)
- Local database: Migrated successfully, 10 records preserved, no data loss
- Standalone command: Available via `python -m backend.database.database`
- PostgreSQL support: Verified for SQL syntax compatibility
- Neon deployment: Instructions provided; migration NOT executed

All code changes completed and tested. Local SQLite database migrated and verified. No live Naukri activity, Gemini calls, or application submissions. Successful application count: 0.

The V1 Gemini default is `gemini-flash-lite-latest` (verified after `gemini-2.5-flash` returned `429 RESOURCE_EXHAUSTED`). Model remains configurable through `NAUKRI_AGENT_GEMINI_MODEL`. Phase 9B-3 live form boundary validation remains pending.

The production JD extraction selector fix is implemented. `NaukriAdapter.fetch_job_description()` now prefers visible `[class*="dang-inner-html"]` and falls back to visible `section[class*="job-desc-container"]`, matching the hashed Naukri structures observed during live diagnostics. Focused adapter regression coverage includes both selectors, precedence, hidden-element fallback, and no-match behavior. Phase 9B-3 remains incomplete until a live native APPLY flow reaches the application boundary; no Gemini, Apply, or submission action occurred in this checkpoint.

Phase 9B-3 reached a live JD extraction blocker. A visible authenticated-browser diagnostic inspected two persisted native Naukri job pages: First American (HTTP 200, visible body length 7,264) and ReactZ Consulting (HTTP 200, visible body length 4,486). Both pages contained visible JD text, but `fetch_job_description()` returned empty because `.job-desc` matched 0 elements and the exact `.styles_JDC__` selector matched 0 elements. The live pages used suffixed hashed classes such as `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`; no selector was changed in this diagnostic checkpoint. Gemini is intentionally deferred because quota is exhausted, and no Apply or submission action occurred.

The live diagnostic now reuses `NaukriAdapter.fetch_job_description()` before Gemini analysis, persists the fetched text in `Job.description`, and sends that actual text in the diagnostic Gemini context. It inspects bounded real candidates before selecting, excludes external jobs from native-flow selection, reuses persisted analyses, stops on Gemini quota exhaustion, reports description fetch status/length, and uses ASCII-safe output. This is an offline-tested diagnostic correction only; no live Naukri search was run, Gemini quota was not consumed, and Phase 9B-3 remains incomplete.

Phase 9B-3 native application detection fix is implemented. Live inspection found that a real First American Data Analyst page exposes a visible `button#apply-button` / `button.apply-button` control with exact text `Apply`, but the adapter previously classified it as external. Detection and native start selectors now recognize stable DOM evidence without relying on hashed classes. Focused adapter coverage includes native controls, external application indicators, no-control fallback, and the current native start selector: 84 tests passed. The full backend suite passed with 519 tests and 3 dependency deprecation warnings. The full live native dry-run remains pending; no application was submitted in this checkpoint.

Test database isolation checkpoint is complete. Backend tests now use a disposable temporary SQLite database and never reset the runtime database at `data/naukri_agent.db`. The shared test fixture redirects application database sessions to the isolated engine before tests start; production profile/resume data is not used by or modified by tests. Isolation regression tests passed, focused profile/application tests passed, and the full backend suite passed with 512 tests. The production database remained present with its existing profile/resume rows after the suite.

Phase 9B-3 false-positive-fix checkpoint is in progress. Live validation discovered that the selected RR Groups job page was a normal HTTP 200 Naukri job page, but `_check_security()` incorrectly blocked it because raw HTML contained Naukri's internal `"showCaptcha":false` value. The targeted fix in `backend/services/naukri/adapter.py` checks visible rendered body text instead of raw HTML and does not treat bare `captcha` as a standalone trigger. Regression coverage verifies the raw `showCaptcha:false` value, bare visible `captcha`, explicit visible reCAPTCHA/hCAPTCHA/security indicators, and a normal Naukri job page. 77 Naukri adapter tests and 509 full backend tests pass. Another real visible-browser Naukri dry-run is still required; Phase 9B-3 live validation is not complete, and no application has been submitted.

Phase 9B-2C Checkpoint is complete: Profile Duplicate ERROR Recovery. Fixed a live-validation blocker where uploading a PDF whose existing profile was in ERROR state returned the broken profile without re-running extraction. The duplicate path now checks profile status: CONFIRMED/REVIEW_REQUIRED duplicates are reused as before; ERROR duplicates re-read the stored PDF and re-run the full extraction pipeline against the existing profile record (no new records created). On success: ERROR → REVIEW_REQUIRED, confirmed remains false. On failure: remains ERROR. 6 regression tests added. 503 total backend tests passing (+6). No live Naukri activity.

Phase 9B-2B Defect Fix Checkpoint is complete: Two runtime defects discovered during live dry-run attempts were fixed. (1) `prompt_version` NOT NULL persistence defect in `AIQueueService.process_item()` — now uses `JOB_ANALYSIS_PROMPT_V1` constant from `prompts.py` instead of a disconnected literal. (2) Experience year computation in `MatchEngine` replaced `len(experience_list)` with `compute_profile_experience_years()` which calculates actual elapsed years from `start_date`/`end_date` fields. 497 total backend tests passing (+14). No live Naukri activity in this checkpoint.

Phase 9A Checkpoint is complete: Scheduler Automation Loop. Implemented complete Phase 9A orchestration connecting all existing components into one automatic local execution flow. Scheduler now:
1. Discovers jobs via NaukriAdapter
2. Applies deterministic hard filters (MatchEngine) before queueing
3. Processes AI queue with Gemini analysis
4. Invokes ApplicationRunner for jobs with completed analysis
5. Records results with cycle statistics

Fixed all three audit gaps:
- **GAP-C1**: Scheduler automatically processes AI queue after discovery
- **GAP-C2**: Scheduler invokes ApplicationRunner for completed AI jobs  
- **GAP-C3**: Hard filters integrated into runtime discovery/matching path

Safety preserved: hard filters authoritative, ApplicationRunner sole executor, final safety gate always runs. Failure isolation ensures single job failures don't cascade. 480 total backend tests passing (previously 475, +5 Phase 9A tests). Frontend builds successfully. No live Naukri submissions (infrastructure only; Phase 9B will add live validation).

Phase 8.5B Checkpoint is complete: Distributed Work Coordination. Implemented worker-owned AI queue work claiming and coordination without race conditions. PostgreSQL uses atomic SELECT...FOR UPDATE SKIP LOCKED; SQLite uses transaction-safe fallback with explicit documentation of semantic differences. Stale work detection (30+ minutes without heartbeat) and safe recovery (escalates to NEEDS_ATTENTION if max_attempts exceeded) preserve existing application safety gates. Work ownership is strict: only claiming worker can heartbeat/release/complete/fail. 49 focused coordination tests passing; 475 total backend tests (previously 426, +49 coordination). No regression in existing AI queue, application runner, duplicate detection, or safety gates. Frontend unchanged.

Phase 8.5A Checkpoint is complete: Worker Foundation and Registration. Persistent worker identity layer introduced to support future cloud browser coordination without modifying current Naukri execution. WorkerType (LOCAL_WINDOWS, CLOUD_BROWSER) and WorkerStatus (STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR) enums defined. Worker model persists identity, type, status, runtime environment, and lifecycle timestamps. WorkerService provides registration (safely repeatable), retrieval, listing, and status updates. Minimal worker API endpoints: GET /api/worker/status (list), POST /api/worker/register (register), GET /api/worker/{worker_id} (get). 12 focused tests; 426 total tests passing. No changes to existing scheduler, Playwright, or NaukriAdapter.

Phase 8.4.1 Checkpoint is complete: Responsive Mobile Naukri-Inspired UX. The frontend is now fully responsive across mobile (320px-480px), tablet (768px-1024px), and desktop (1024px+) viewports. Mobile experience features a compact header with hamburger menu, sidebar drawer, and bottom navigation bar inspired by Naukri mobile app patterns. All touch targets are minimum ~44x44px. Desktop layout and functionality are preserved. No backend changes. Build passes; no TypeScript errors.

Phase 8.4 Checkpoint is complete: Vercel frontend preparation. All frontend API calls use a single public `VITE_API_BASE_URL` configuration, and the existing Vercel configuration builds the `frontend` Vite app. No Vercel deployment has been performed.

Phase 8.3 Checkpoint is complete: hosted FastAPI deployment preparation. The repository includes Render and Procfile service definitions, explicit production configuration validation, secure structured logs, and environment-driven CORS/frontend API configuration. This is preparation only; no service has been deployed.

Phase 8.2 Checkpoint is complete: PostgreSQL + Production Persistence. Backend seamlessly hosts configurations for SQLite and scaling instances with PostgreSQL `psycopg` integration and connection pooling metrics.

Phase 8.1 Checkpoint is complete: Production Backend Preparation. 414 tests passing. Backend is production-hosting ready with enhanced configuration, security, and monitoring.

Phase 7 Checkpoint 4 is complete: Agent intelligence, decision quality, job prioritization, feedback/learning, and application analytics.

Frontend UX/UI Redesign Checkpoint is complete: Professional SaaS dashboard design with modern UI/UX, improved accessibility, and responsive layout.

Frontend Codebase Structure Verification is complete: Production-ready React 19.1.0 + TypeScript 5.8.3 + Vite 6.3.5 + Tailwind CSS 4.1.4 stack with clean component architecture and stable build pipeline.


## Stack

Python 3.12+, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite, Tailwind CSS, pytest, Playwright, Gemini, and PyMuPDF.

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

Phase 8.3 prepares only the hosted FastAPI API. Cloud browser execution, object storage, database provisioning, frontend deployment, and platform automation remain out of scope.

## Hosted FastAPI Deployment (Phase 8.3)

Run the API on a hosting platform with:

```text
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

`Procfile` provides a local-port fallback and `render.yaml` describes an equivalent Render web service. Set these host environment variables; do not commit their values:

- `NAUKRI_AGENT_APP_ENV=production`
- `NAUKRI_AGENT_DATABASE_URL` — external PostgreSQL URL
- `NAUKRI_AGENT_GEMINI_API_KEY`
- `NAUKRI_AGENT_FRONTEND_ORIGINS` — one or more comma-separated frontend origins

Production readiness rejects SQLite, a missing Gemini key, missing origins, and wildcard origins. `GET /api/health` is process-only and does not query the database or Gemini; `GET /api/readiness` reports whether database, configuration, storage, AI configuration, and runtime are ready. CORS allows only configured production origins and deliberately disables credentialed browser requests. `SafeJsonFormatter` recursively redacts credentials, API keys, authorization headers, cookies, sessions, nested values, and database URL userinfo.

## Vercel Frontend Preparation (Phase 8.4)

The root `vercel.json` installs, builds, and publishes the Vite app in `frontend/` (`npm --prefix frontend ci`, `npm --prefix frontend run build`, and `frontend/dist`). Set `VITE_API_BASE_URL` in Vercel to the public HTTPS FastAPI origin, for example `https://your-api-host.example`; the client normalizes it to `/api`. Locally, omit the variable to use `http://127.0.0.1:8000`.

`VITE_` values are public browser configuration. Never put Gemini keys, database URLs with credentials, Naukri credentials, cookies, sessions, or private tokens in them. Configure the deployed Vercel origin separately in `NAUKRI_AGENT_FRONTEND_ORIGINS` on the backend. The dashboard uses in-page state and hash links, not browser-path routing, so no SPA rewrite was added. API failures use safe user-facing messages and a request timeout; raw backend error details are not displayed.

## Production Readiness (Phase 8.1)

The backend has been prepared for production hosting with enhanced configuration, security, and monitoring:

- **Production Configuration**: Environment separation (LOCAL_WINDOWS/CLOUD), production detection, configurable CORS origins
- **CORS Configuration**: Production-safe with configurable multiple origins via FRONTEND_ORIGINS
- **Health/Readiness Endpoints**: Separate liveness (/api/health) and readiness (/api/readiness) endpoints for container orchestration
- **Error Handling**: Catch-all exception handler prevents sensitive information exposure
- **Logging**: Production-safe logging with automatic sensitive information redaction (api_key, password, token, secret, credential, auth)
- **Database Configuration**: Supports both SQLite (default) and PostgreSQL via DATABASE_URL
- **Storage Configuration**: StorageService abstraction ready for future object storage integration
- **Browser/API Separation**: API process does NOT auto-start Playwright browser; clear separation for future cloud architecture
- **Frontend Configuration**: Environment-based backend URL via VITE_API_BASE_URL (development: localhost, production: configurable)
- **Security**: No wildcard CORS in production, no stack traces in errors, no secrets in logs or API responses

## Cloud Readiness

The application includes cloud readiness infrastructure to support future cloud deployment while maintaining local-first V1 operation:

- **RuntimeContext**: Environment detection and behavior abstraction (LOCAL_WINDOWS for V1, CLOUD_READY for future)
- **StorageService**: File operations abstraction enabling future object storage (S3/Azure/GCS)
- **Environment configuration**: All settings use `NAUKRI_AGENT_` prefix for clean cloud deployment
- **Database flexibility**: Supports both SQLite (V1) and PostgreSQL (future)
- **No business logic changes**: V1 functionality unchanged; abstractions enable future cloud without code changes

Future cloud deployment will require: remote browser automation, object storage integration, PostgreSQL deployment, and cloud infrastructure setup.

## Profile Setup

Set `NAUKRI_AGENT_GEMINI_API_KEY` in a local `.env`, start the backend and frontend, then open the Profile section. Upload a PDF no larger than 10 MB, review the extracted facts, save any edits, and explicitly confirm the profile. A resume is not usable by future automation until it is confirmed.

The Phase 2 backend tests pass. In this environment the frontend build is currently blocked by a malformed native Vite dependency tree; remove `frontend/node_modules` and reinstall dependencies once Windows releases that generated directory.

## Development Phases

The formal product roadmap is defined by `docs/MASTER_PRD.md`.

1. Foundation and architecture - complete
2. Resume and user profile - complete
3. Gemini AI engine - complete
4. Matching and rules engine - complete
5. Naukri job discovery - complete
6. Naukri application automation - implementation complete; live native form-boundary validation remains unresolved
7. Scheduler and continuous agent - complete
8. Dashboard - complete
9. Notifications - implemented offline; SMTP delivery requires configuration
10. Testing, security, and Windows packaging - pending
11. Integration and production hardening - pending

Cloud deployment preparation is documented as supporting Phase 8.x/production-readiness work; it is not a separate formal product phase in the master roadmap.

Phase 9 notifications are isolated behind `NotificationService`. The implementation persists notification history, supports critical-error, authentication-required, security-challenge, external-application, and evening-summary events, and exposes `GET /api/notifications` for the dashboard. SMTP settings use the `NAUKRI_AGENT_` environment prefix; tests use a fake sender and no real email was sent. The evening summary is evaluated in the configured timezone during the configured 8 PM hour with daily deduplication. Live SMTP delivery remains unverified.

Note: Cloud readiness infrastructure (runtime/storage abstractions) was implemented as foundational work to support future cloud deployment without changing business logic. This is not a separate phase but enables future cloud execution. Phase 8.1 prepared the backend for production hosting without actual deployment.

## Checkpoint C2: Fresher-only IT-only autonomous policy

The autonomous cycle uses `experience=0`, defaults to fresher/trainee search titles, and enforces a zero-year maximum required experience. Missing or unparseable experience is skipped unless the title explicitly identifies a fresher, trainee, intern, or graduate role. Jobs must also have an allowed IT industry/department/role category and an IT title keyword; missing or unknown metadata is skipped.

External applications are recorded as `EXTERNAL_APPLICATION` with `external - needs review` and are never opened through a company link. Native questionnaire or chat forms are recorded as `NEEDS_ATTENTION` with `questions - needs review`; question answering is disabled by default with `NAUKRI_AGENT_ANSWER_QUESTIONS=false`. The cycle reports card scans, experience and non-IT skips, external records, question reviews, applied jobs, and opened jobs.

## Phase 9B-4 Safety Boundary

Dry-run application execution is now pre-Apply inspection only. It opens and classifies the candidate page, records an explicit `is_dry_run` inspection record, and stops before any native or external Apply action; it does not invoke `start_application()`, answer questions, submit, or confirm submission. Application lifecycle data distinguishes `PRE_APPLY`, an unverified Apply/form boundary, `FORM_OPENED`, `APPLIED`, `SUBMITTED`, and `NEEDS_ATTENTION`. Native Apply semantics remain unknown, so Phase 9B-3 live form-boundary validation remains incomplete. No live application occurred in this checkpoint.

## Status

**Phase 10 Application Boundary Fix: Implemented (Offline Validated)**

The application boundary is now evidence-driven:
- Post-click state detection waits for explicit visible applied evidence (8s bounded wait)
- Question detection scopes to visible application containers only
- Experience computation uses elapsed years from `start_date`/`end_date`, not entry count
- Native/external classification happens BEFORE creating APPLICATION_STARTED
- No-repeat enforcement: EXTERNAL_APPLICATION and NEEDS_ATTENTION require manual reset

All validation performed with isolated temporary SQLite tests only. No live Naukri activity, Apply/Submit clicks, or Gemini calls. Production database untouched. Successful application count: 0.

The V1 Gemini default is `gemini-flash-lite-latest` (verified after `gemini-2.5-flash` returned `429 RESOURCE_EXHAUSTED`). Model remains configurable through `NAUKRI_AGENT_GEMINI_MODEL`. Phase 9B-3 live form boundary validation remains pending.

The production JD extraction selector fix is implemented. `NaukriAdapter.fetch_job_description()` now prefers visible `[class*="dang-inner-html"]` and falls back to visible `section[class*="job-desc-container"]`, matching the hashed Naukri structures observed during live diagnostics. Focused adapter regression coverage includes both selectors, precedence, hidden-element fallback, and no-match behavior. Phase 9B-3 remains incomplete until a live native APPLY flow reaches the application boundary; no Gemini, Apply, or submission action occurred in this checkpoint.

Phase 9B-3 reached a live JD extraction blocker. A visible authenticated-browser diagnostic inspected two persisted native Naukri job pages: First American (HTTP 200, visible body length 7,264) and ReactZ Consulting (HTTP 200, visible body length 4,486). Both pages contained visible JD text, but `fetch_job_description()` returned empty because `.job-desc` matched 0 elements and the exact `.styles_JDC__` selector matched 0 elements. The live pages used suffixed hashed classes such as `section.styles_job-desc-container__txpYf` and `div.styles_JDC__dang-inner-html__h0K4t`; no selector was changed in this diagnostic checkpoint. Gemini is intentionally deferred because quota is exhausted, and no Apply or submission action occurred.

The live diagnostic now reuses `NaukriAdapter.fetch_job_description()` before Gemini analysis, persists the fetched text in `Job.description`, and sends that actual text in the diagnostic Gemini context. It inspects bounded real candidates before selecting, excludes external jobs from native-flow selection, reuses persisted analyses, stops on Gemini quota exhaustion, reports description fetch status/length, and uses ASCII-safe output. This is an offline-tested diagnostic correction only; no live Naukri search was run, Gemini quota was not consumed, and Phase 9B-3 remains incomplete.

Phase 9B-3 native application detection fix is implemented. Live inspection found that a real First American Data Analyst page exposes a visible `button#apply-button` / `button.apply-button` control with exact text `Apply`, but the adapter previously classified it as external. Detection and native start selectors now recognize stable DOM evidence without relying on hashed classes. Focused adapter coverage includes native controls, external application indicators, no-control fallback, and the current native start selector: 84 tests passed. The full backend suite passed with 519 tests and 3 dependency deprecation warnings. The full live native dry-run remains pending; no application was submitted in this checkpoint.

Test database isolation checkpoint is complete. Backend tests now use a disposable temporary SQLite database and never reset the runtime database at `data/naukri_agent.db`. The shared test fixture redirects application database sessions to the isolated engine before tests start; production profile/resume data is not used by or modified by tests. Isolation regression tests passed, focused profile/application tests passed, and the full backend suite passed with 512 tests. The production database remained present with its existing profile/resume rows after the suite.

Phase 9B-3 false-positive-fix checkpoint is in progress. Live validation discovered that the selected RR Groups job page was a normal HTTP 200 Naukri job page, but `_check_security()` incorrectly blocked it because raw HTML contained Naukri's internal `"showCaptcha":false` value. The targeted fix in `backend/services/naukri/adapter.py` checks visible rendered body text instead of raw HTML and does not treat bare `captcha` as a standalone trigger. Regression coverage verifies the raw `showCaptcha:false` value, bare visible `captcha`, explicit visible reCAPTCHA/hCAPTCHA/security indicators, and a normal Naukri job page. 77 Naukri adapter tests and 509 full backend tests pass. Another real visible-browser Naukri dry-run is still required; Phase 9B-3 live validation is not complete, and no application has been submitted.

Phase 9B-2C Checkpoint is complete: Profile Duplicate ERROR Recovery. Fixed a live-validation blocker where uploading a PDF whose existing profile was in ERROR state returned the broken profile without re-running extraction. The duplicate path now checks profile status: CONFIRMED/REVIEW_REQUIRED duplicates are reused as before; ERROR duplicates re-read the stored PDF and re-run the full extraction pipeline against the existing profile record (no new records created). On success: ERROR → REVIEW_REQUIRED, confirmed remains false. On failure: remains ERROR. 6 regression tests added. 503 total backend tests passing (+6). No live Naukri activity.

Phase 9B-2B Defect Fix Checkpoint is complete: Two runtime defects discovered during live dry-run attempts were fixed. (1) `prompt_version` NOT NULL persistence defect in `AIQueueService.process_item()` — now uses `JOB_ANALYSIS_PROMPT_V1` constant from `prompts.py` instead of a disconnected literal. (2) Experience year computation in `MatchEngine` replaced `len(experience_list)` with `compute_profile_experience_years()` which calculates actual elapsed years from `start_date`/`end_date` fields. 497 total backend tests passing (+14). No live Naukri activity in this checkpoint.

Phase 9A Checkpoint is complete: Scheduler Automation Loop. Implemented complete Phase 9A orchestration connecting all existing components into one automatic local execution flow. Scheduler now:
1. Discovers jobs via NaukriAdapter
2. Applies deterministic hard filters (MatchEngine) before queueing
3. Processes AI queue with Gemini analysis
4. Invokes ApplicationRunner for jobs with completed analysis
5. Records results with cycle statistics

Fixed all three audit gaps:
- **GAP-C1**: Scheduler automatically processes AI queue after discovery
- **GAP-C2**: Scheduler invokes ApplicationRunner for completed AI jobs  
- **GAP-C3**: Hard filters integrated into runtime discovery/matching path

Safety preserved: hard filters authoritative, ApplicationRunner sole executor, final safety gate always runs. Failure isolation ensures single job failures don't cascade. 480 total backend tests passing (previously 475, +5 Phase 9A tests). Frontend builds successfully. No live Naukri submissions (infrastructure only; Phase 9B will add live validation).

Phase 8.5B Checkpoint is complete: Distributed Work Coordination. Implemented worker-owned AI queue work claiming and coordination without race conditions. PostgreSQL uses atomic SELECT...FOR UPDATE SKIP LOCKED; SQLite uses transaction-safe fallback with explicit documentation of semantic differences. Stale work detection (30+ minutes without heartbeat) and safe recovery (escalates to NEEDS_ATTENTION if max_attempts exceeded) preserve existing application safety gates. Work ownership is strict: only claiming worker can heartbeat/release/complete/fail. 49 focused coordination tests passing; 475 total backend tests (previously 426, +49 coordination). No regression in existing AI queue, application runner, duplicate detection, or safety gates. Frontend unchanged.

Phase 8.5A Checkpoint is complete: Worker Foundation and Registration. Persistent worker identity layer introduced to support future cloud browser coordination without modifying current Naukri execution. WorkerType (LOCAL_WINDOWS, CLOUD_BROWSER) and WorkerStatus (STARTING, IDLE, RUNNING, PAUSED, STOPPING, STOPPED, ERROR) enums defined. Worker model persists identity, type, status, runtime environment, and lifecycle timestamps. WorkerService provides registration (safely repeatable), retrieval, listing, and status updates. Minimal worker API endpoints: GET /api/worker/status (list), POST /api/worker/register (register), GET /api/worker/{worker_id} (get). 12 focused tests; 426 total tests passing. No changes to existing scheduler, Playwright, or NaukriAdapter.

Phase 8.4.1 Checkpoint is complete: Responsive Mobile Naukri-Inspired UX. The frontend is now fully responsive across mobile (320px-480px), tablet (768px-1024px), and desktop (1024px+) viewports. Mobile experience features a compact header with hamburger menu, sidebar drawer, and bottom navigation bar inspired by Naukri mobile app patterns. All touch targets are minimum ~44x44px. Desktop layout and functionality are preserved. No backend changes. Build passes; no TypeScript errors.

Phase 8.4 Checkpoint is complete: Vercel frontend preparation. All frontend API calls use a single public `VITE_API_BASE_URL` configuration, and the existing Vercel configuration builds the `frontend` Vite app. No Vercel deployment has been performed.

Phase 8.3 Checkpoint is complete: hosted FastAPI deployment preparation. The repository includes Render and Procfile service definitions, explicit production configuration validation, secure structured logs, and environment-driven CORS/frontend API configuration. This is preparation only; no service has been deployed.

Phase 8.2 Checkpoint is complete: PostgreSQL + Production Persistence. Backend seamlessly hosts configurations for SQLite and scaling instances with PostgreSQL `psycopg` integration and connection pooling metrics.

Phase 8.1 Checkpoint is complete: Production Backend Preparation. 414 tests passing. Backend is production-hosting ready with enhanced configuration, security, and monitoring.

Phase 7 Checkpoint 4 is complete: Agent intelligence, decision quality, job prioritization, feedback/learning, and application analytics.

Frontend UX/UI Redesign Checkpoint is complete: Professional SaaS dashboard design with modern UI/UX, improved accessibility, and responsive layout.

Frontend Codebase Structure Verification is complete: Production-ready React 19.1.0 + TypeScript 5.8.3 + Vite 6.3.5 + Tailwind CSS 4.1.4 stack with clean component architecture and stable build pipeline.


## Stack

Python 3.12+, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite, Tailwind CSS, pytest, Playwright, Gemini, and PyMuPDF.

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

Phase 8.3 prepares only the hosted FastAPI API. Cloud browser execution, object storage, database provisioning, frontend deployment, and platform automation remain out of scope.

## Hosted FastAPI Deployment (Phase 8.3)

Run the API on a hosting platform with:

```text
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

`Procfile` provides a local-port fallback and `render.yaml` describes an equivalent Render web service. Set these host environment variables; do not commit their values:

- `NAUKRI_AGENT_APP_ENV=production`
- `NAUKRI_AGENT_DATABASE_URL` — external PostgreSQL URL
- `NAUKRI_AGENT_GEMINI_API_KEY`
- `NAUKRI_AGENT_FRONTEND_ORIGINS` — one or more comma-separated frontend origins

Production readiness rejects SQLite, a missing Gemini key, missing origins, and wildcard origins. `GET /api/health` is process-only and does not query the database or Gemini; `GET /api/readiness` reports whether database, configuration, storage, AI configuration, and runtime are ready. CORS allows only configured production origins and deliberately disables credentialed browser requests. `SafeJsonFormatter` recursively redacts credentials, API keys, authorization headers, cookies, sessions, nested values, and database URL userinfo.

## Vercel Frontend Preparation (Phase 8.4)

The root `vercel.json` installs, builds, and publishes the Vite app in `frontend/` (`npm --prefix frontend ci`, `npm --prefix frontend run build`, and `frontend/dist`). Set `VITE_API_BASE_URL` in Vercel to the public HTTPS FastAPI origin, for example `https://your-api-host.example`; the client normalizes it to `/api`. Locally, omit the variable to use `http://127.0.0.1:8000`.

`VITE_` values are public browser configuration. Never put Gemini keys, database URLs with credentials, Naukri credentials, cookies, sessions, or private tokens in them. Configure the deployed Vercel origin separately in `NAUKRI_AGENT_FRONTEND_ORIGINS` on the backend. The dashboard uses in-page state and hash links, not browser-path routing, so no SPA rewrite was added. API failures use safe user-facing messages and a request timeout; raw backend error details are not displayed.

## Production Readiness (Phase 8.1)

The backend has been prepared for production hosting with enhanced configuration, security, and monitoring:

- **Production Configuration**: Environment separation (LOCAL_WINDOWS/CLOUD), production detection, configurable CORS origins
- **CORS Configuration**: Production-safe with configurable multiple origins via FRONTEND_ORIGINS
- **Health/Readiness Endpoints**: Separate liveness (/api/health) and readiness (/api/readiness) endpoints for container orchestration
- **Error Handling**: Catch-all exception handler prevents sensitive information exposure
- **Logging**: Production-safe logging with automatic sensitive information redaction (api_key, password, token, secret, credential, auth)
- **Database Configuration**: Supports both SQLite (default) and PostgreSQL via DATABASE_URL
- **Storage Configuration**: StorageService abstraction ready for future object storage integration
- **Browser/API Separation**: API process does NOT auto-start Playwright browser; clear separation for future cloud architecture
- **Frontend Configuration**: Environment-based backend URL via VITE_API_BASE_URL (development: localhost, production: configurable)
- **Security**: No wildcard CORS in production, no stack traces in errors, no secrets in logs or API responses

## Cloud Readiness

The application includes cloud readiness infrastructure to support future cloud deployment while maintaining local-first V1 operation:

- **RuntimeContext**: Environment detection and behavior abstraction (LOCAL_WINDOWS for V1, CLOUD_READY for future)
- **StorageService**: File operations abstraction enabling future object storage (S3/Azure/GCS)
- **Environment configuration**: All settings use `NAUKRI_AGENT_` prefix for clean cloud deployment
- **Database flexibility**: Supports both SQLite (V1) and PostgreSQL (future)
- **No business logic changes**: V1 functionality unchanged; abstractions enable future cloud without code changes

Future cloud deployment will require: remote browser automation, object storage integration, PostgreSQL deployment, and cloud infrastructure setup.

## Profile Setup

Set `NAUKRI_AGENT_GEMINI_API_KEY` in a local `.env`, start the backend and frontend, then open the Profile section. Upload a PDF no larger than 10 MB, review the extracted facts, save any edits, and explicitly confirm the profile. A resume is not usable by future automation until it is confirmed.

The Phase 2 backend tests pass. In this environment the frontend build is currently blocked by a malformed native Vite dependency tree; remove `frontend/node_modules` and reinstall dependencies once Windows releases that generated directory.

## Development Phases

The formal product roadmap is defined by `docs/MASTER_PRD.md`.

1. Foundation and architecture - complete
2. Resume and user profile - complete
3. Gemini AI engine - complete
4. Matching and rules engine - complete
5. Naukri job discovery - complete
6. Naukri application automation - implementation complete; live native form-boundary validation remains unresolved
7. Scheduler and continuous agent - complete
8. Dashboard - complete
9. Notifications - implemented offline; SMTP delivery requires configuration
10. Testing, security, and Windows packaging - pending
11. Integration and production hardening - pending

Cloud deployment preparation is documented as supporting Phase 8.x/production-readiness work; it is not a separate formal product phase in the master roadmap.

Phase 9 notifications are isolated behind `NotificationService`. The implementation persists notification history, supports critical-error, authentication-required, security-challenge, external-application, and evening-summary events, and exposes `GET /api/notifications` for the dashboard. SMTP settings use the `NAUKRI_AGENT_` environment prefix; tests use a fake sender and no real email was sent. The evening summary is evaluated in the configured timezone during the configured 8 PM hour with daily deduplication. Live SMTP delivery remains unverified.

Note: Cloud readiness infrastructure (runtime/storage abstractions) was implemented as foundational work to support future cloud deployment without changing business logic. This is not a separate phase but enables future cloud execution. Phase 8.1 prepared the backend for production hosting without actual deployment.
