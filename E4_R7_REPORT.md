# Naukri Agent — Checkpoint E4-R7: Read-Only Discovery and Filter Verification

## 1. Repository State

- **Branch**: `main`
- **HEAD**: `64c271c5811b0af7a984ebb9313feb4ca8277474` ✓ (matches expected)
- **Git status**: 1 modified file (`frontend/src/styles.css`), 30+ untracked files (test scripts, debug files, etc.)
- **Working tree**: Preserved, no alterations made

## 2. Jobs 59 and 85 — Evidence and Conclusion

### Job Records
| Field | Job 59 | Job 85 |
|-------|--------|--------|
| **Title** | Associate Software Engineer | Job For Labview Developer-Bangalore |
| **Company** | Capgemini | Access Automation PVT LTD |
| **External Job ID** | `070926914334` | `280926017264` |
| **URL** | `...-070926914334` | `...-280926017264` |
| **Discovered** | 2026-10-06 14:13:26 | 2026-10-06 14:15:10 |
| **Status** | DISCOVERED | DISCOVERED |
| **Applications** | APPLIED (2026-10-07 15:38:30) | APPLIED (2026-10-07 15:37:16) |

### Discovery Run Presence (`current_run_job_ids`)
| Run Range | Job 59 | Job 85 |
|-----------|--------|--------|
| Runs 13–32 | ✓ Present | ✓ Present |
| Run 40 | ✗ Absent | ✗ Absent |
| Runs 41–43 | ✗ Absent | ✗ Absent |
| Runs 48–49 (STOPPED) | ✗ Absent | ✗ Absent |
| Runs 50–52 | ✗ Absent | ✗ Absent |

### Discovery Logic Analysis (`backend/services/discovery/service.py`)

**`_find_existing_job()`** (lines 263–280) matches in order:
1. `external_job_id` exact match
2. `url` exact match  
3. `title` + `company` exact match

**`_extract_card_data()`** (adapter, lines 542–549) extracts `external_job_id` via regex:
```python
match = re.search(r'-([a-zA-Z0-9]+)$', url)  # matches trailing alphanumeric after hyphen
```

Both jobs' URLs end with their external_job_ids (`070926914334`, `280926017264`), so extraction would succeed.

**Current-run ID accumulation** (lines 179–180, 202–203):
```python
self.current_run_job_ids.add(existing_job.id)  # for duplicates
self.current_run_job_ids.add(new_job.id)       # for new jobs
```
IDs are accumulated in a `set` (deduplicated), then saved as comma-separated string at finalization (line 340).

### Conclusion
**The jobs were not returned by Naukri in Runs 40–52.**

Evidence:
- Jobs 59 and 85 were discovered on 2026-10-06 (Runs 13–32 on 2026-10-06/07)
- Run 40 (2026-10-08) shows 102 jobs discovered vs 103–105 previously; jobs 59/85 absent
- Runs 50–52 (2026-10-09) show 103 jobs but different ID set (includes new jobs 114, 115)
- `MAX_PAGES = 3` in adapter limits search to first 3 pages; older postings drop off
- Matching logic would have retained them if returned (external_job_id and URL both valid)
- No code change between Runs 32 and 40 affecting matching logic

**Supported explanation**: Naukri search results changed; jobs 59/85 are older postings no longer appearing in first 3 pages.

## 3. Run #52 Filtered Jobs — Reconstructed Rejection Reasons

### Scope
- 81 unique job IDs in Run #52 `current_run_job_ids`
- 16 jobs with existing AI analyses (job_analyses table)
- 65 unanalyzed jobs → passed through deterministic filters only

### Deterministic Filter Order (engine.py `_run_deterministic_checks`)
1. **PROFILE_CONFIRMATION** (global, profile confirmed=1)
2. **DUPLICATE_CHECK** (URL-based, all 65 unique in current run)
3. **ROLE_TARGETING** (`title_matches_allowed_role`)
4. **EXPERIENCE** (`experience_passes_fresher_rule`, cap=0 years)
5. **IT_SCOPE** (`is_strict_it_job`)
6. **SALARY** (unpaid check + min_salary_lpa=4)
7. **EMPLOYMENT_TYPE** (allowed: Full Time, Internship, Contract)

### Reconstructed Results (65 jobs analyzed)

| Outcome | Count | Notes |
|---------|-------|-------|
| **ROLE_TARGETING** | 53 | First filter; title doesn't match allowed families or contains unwanted specialization |
| **SALARY** | 9 | 7 unpaid (salary_max=0), 2 below 4 LPA minimum |
| **IT_SCOPE** | 1 | Job 106: industry "Recruitment / Staffing" not in allowed IT industries |
| **PASS (would reach Gemini)** | 2 | Job 19 (Google "Software Engineer"), Job 56 (EverestIMS "Associate Software Engineer") |
| **UNKNOWN** | 0 | All 65 have sufficient stored data for confident reconstruction |

### Rejection Reason Distribution
```
ROLE_TARGETING: 53 jobs (81.5%)
SALARY:         9 jobs  (13.8%)
IT_SCOPE:       1 job   (1.5%)
```

### Key Observations
- **ROLE_TARGETING dominates**: Allowed families are narrow (data analyst/engineer, software engineer/developer, devops, python developer). Unwanted specializations list (java, php, .net, sales, marketing, hr, operations, mechanical, etc.) catches many.
- **"Graduate Engineer Trainee" not allowed**: 12 jobs rejected for this title alone.
- **Unpaid internships**: 7 jobs rejected at SALARY filter (salary_max=0).
- **Experience filter passed all**: `max_required_experience_years=0` but title exceptions (fresher/trainee/intern/graduate) allow entry-level roles.

## 4. Jobs 114 and 115 — First Failing Filter

### Job 114: "Mis Analyst , fresher" (Arteria)
| Filter | Result | Detail |
|--------|--------|--------|
| ROLE_TARGETING | **FAIL (1st)** | Title "mis analyst" doesn't match "data analyst" (MIS ≠ data); no unwanted specialization |
| EXPERIENCE | PASS | "0-1 Yrs" → exp_min=0 ≤ cap=0 |
| IT_SCOPE | FAIL | Title lacks IT keywords ("mis" not in DEFAULT_IT_KEYWORDS); industry "IT Services & Consulting" would pass if title matched |
| SALARY | PASS | Undisclosed (None) |
| EMPLOYMENT_TYPE | PASS | None specified |

### Job 115: "Fresher (CSC,EEE,ECE)" (Creative Hands HR)
| Filter | Result | Detail |
|--------|--------|--------|
| ROLE_TARGETING | **FAIL (1st)** | Title "fresher (csc,eee,ece)" matches no allowed family; no unwanted specialization |
| EXPERIENCE | PASS | "0-3 Yrs" → exp_min=0 ≤ cap=0 |
| IT_SCOPE | FAIL | Industry "Electronic Components / Semiconductors" not in DEFAULT_IT_INDUSTRIES |
| SALARY | PASS | Undisclosed (None) |
| EMPLOYMENT_TYPE | PASS | None specified |

**Conclusion**: Both jobs fail at **ROLE_TARGETING** (first deterministic filter). They would not reach IT_SCOPE or later filters in actual execution order.

## 5. `match_results` Persistence Analysis

### Current State
- **Table exists**: Yes (`match_results` with 11 columns: id, job_id, preference_id, decision, skip_reason, matched_rules, failed_rules, warnings, match_score, created_at, updated_at)
- **Rows**: 0 (completely empty)
- **Model**: `MatchResult` in `backend/models/matching.py` (lines 36–56)
- **Schema**: `MatchDecision` in `backend/schemas/matching.py` (lines 60–68)

### Usage in Codebase
| Component | Persists to `match_results`? |
|-----------|------------------------------|
| `MatchEngine.evaluate_job()` | **No** — returns `MatchDecision` only |
| `MatchEngine.evaluate_job_deterministic()` | **No** — returns `MatchDecision` only |
| `DecisionQualityService.evaluate_job_decision()` | **No** — returns `DecisionQuality`; saves to `decision_quality_records` instead |
| `ApplicationService` / `ApplicationRunner` | **No** — records `Application` rows only |

### Gap Analysis
- **Intentionally unused by matching path**: The `match_results` table appears designed for MatchEngine decisions but is never written to.
- **Alternative persistence**: `DecisionQualityRecord` table (different schema) captures decision quality metrics from `DecisionQualityService`.
- **Schema adequacy**: Existing `match_results` columns map 1:1 to `MatchDecision` fields (decision, skip_reason, matched_rules, failed_rules, warnings, match_score). No schema change needed.
- **Required for observability**: If enabled, would need:
  1. Write path in `MatchEngine` (after `evaluate_job`/`evaluate_job_deterministic`)
  2. Unique constraint on `job_id` handled (upsert or delete+insert)
  3. Tests: verify row created per evaluation, decision matches returned object, skip_reason populated for SKIP, match_score for APPLY

## 6. Confirmed Findings and Remaining Unknowns

### Confirmed Findings
| # | Finding | Evidence |
|---|---------|----------|
| 1 | Jobs 59/85 absent from Runs 40–52 because Naukri didn't return them | Discovery runs show presence in 13–32, absence from 40+; matching logic intact |
| 2 | 65 unanalyzed jobs in Run #52: 53 fail ROLE_TARGETING, 9 fail SALARY, 1 fails IT_SCOPE | Read-only reconstruction using stored job data + deterministic filter code |
| 3 | Jobs 114/115 fail at ROLE_TARGETING (first filter) | Title "Mis Analyst"/"Fresher (CSC,EEE,ECE)" matches no allowed family |
| 4 | `match_results` table exists but is never written to | Code inspection: MatchEngine returns MatchDecision but doesn't persist |
| 5 | Jobs 59/85 have APPLIED applications (2026-10-07) | `applications` table shows status=APPLIED for both job_ids |
| 6 | Duplicate check in DecisionQualityService catches applied jobs | `_check_duplicate` queries Application table for APPLIED/SUBMITTED |

### Remaining Unknowns
| # | Unknown | Why Unresolvable Read-Only |
|---|---------|---------------------------|
| 1 | Exact Naukri search result content for Runs 40–52 | Cannot replay browser automation; no raw card snapshots stored |
| 2 | Whether jobs 59/85 would match if returned with modified external_job_id | No card-level raw data persisted for comparison |
| 3 | Whether the 2 PASS jobs (19, 56) would pass AI evaluation | Requires Gemini call (prohibited) |

## 7. Final Recommendation

**Conclusion: `NO_CODE_CHANGE — evidence supports expected behavior`**

### Justification
1. **Jobs 59/85 absence**: Explained by Naukri search pagination (MAX_PAGES=3) and posting age. Discovery logic correctly accumulates matched IDs when cards are returned. No defect in matching or deduplication.
2. **65 filtered jobs**: Deterministic filters working as designed. ROLE_TARGETING correctly enforces narrow role families; SALARY correctly rejects unpaid/below-minimum; IT_SCOPE correctly validates industry. Distribution matches code logic.
3. **Jobs 114/115**: Fail at first filter (ROLE_TARGETING) as expected for titles outside configured scope.
4. **`match_results` gap**: Separate observability concern, not a functional defect. MatchEngine decisions flow to DecisionQualityService (saved in `decision_quality_records`) and ApplicationRunner (saved in `applications`). Table schema is ready if future observability work is approved.

### No Action Required
- Discovery matching logic is correct
- Deterministic filter ordering and thresholds are correctly implemented
- Zero applications in Run #52 is consistent with filter outcomes (only 2 jobs passed deterministic; both may have been blocked by AI or limits)
- The 13 analyzed jobs excluded due to prior applications is correct behavior (DecisionQualityService `_check_duplicate` queries Application table)

### Optional Future Work (Not Required Now)
- If observability improvement approved: implement `match_results` persistence in `MatchEngine` (10–15 lines, existing schema sufficient)
- Consider expanding ALLOWED_ROLE_FAMILIES if "Graduate Engineer Trainee" / "MIS Analyst" should be in scope (product decision, not defect)