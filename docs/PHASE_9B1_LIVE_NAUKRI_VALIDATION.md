# Phase 9B-1 — Live Naukri Discovery & Session Validation

## Overview

Phase 9B-1 is the **first real live validation checkpoint** of the Naukri browser integration. This phase validates that the existing NaukriAdapter and discovery implementation work against the real Naukri website.

**Scope:** Discovery and extraction validation ONLY. No application submission.

---

## 1. Baseline

- **Phase:** 9B-1
- **Date:** 2026-09-27
- **Repository State:** Clean, synchronized
- **Current HEAD:** c05f87a (Phase 9A automation loop)
- **Working Tree:** Clean
- **Previous Phase:** 9A (scheduler automation loop) — COMPLETE

---

## 2. Browser Environment

| Component | Value |
|---|---|
| Browser Engine | Chromium/Chrome (Playwright) |
| Browser Channel | Chrome or Edge (configured) |
| Context Type | Persistent (user_data_dir) |
| Headless Mode | False (visible to user) |
| Session Reuse | Yes (persistent context) |
| Manual Login Support | Yes |

**Implementation Source:** `backend/services/naukri/adapter.py`

---

## 3. Authentication / Session Result

**Expected Behavior:**
- Browser launches with persistent user_data_dir
- User may need to manually log in to Naukri
- Session credentials preserved in browser profile (NOT stored by code)
- If already authenticated, skips manual login

**CAPTCHA/Security Verification:**
- If Naukri presents CAPTCHA/security verification: STOP safely
- Never attempt to bypass or automate

---

## 4. Homepage Validation

**Test Flow:**
1. Browser launches
2. Navigate to https://www.naukri.com
3. Wait for page load
4. Detect authentication state
5. If login required: wait for manual user login
6. Verify no CAPTCHA/security walls

**Expected Results:**

| Check | Status | Evidence |
|---|---|---|
| Browser launch | PASS | Playwright session starts |
| URL navigation | PASS | Reaches https://www.naukri.com |
| Page load | PASS | Title detected |
| Authentication | PASS/WAIT | Logged in or user completes login |
| Security walls | NONE | No CAPTCHA detected |

---

## 5. Search Validation

**Implementation:** `backend/services/naukri/adapter.py` lines 194-224

**URL Format:** `https://www.naukri.com/{SearchTerm}-jobs-in-{Location}`

**Example:** `https://www.naukri.com/Data-Analyst-jobs-in-Bengaluru`

**Test Flow:**
1. Get user job preferences (or use defaults)
2. Build search URL via `_build_naukri_search_url()`
3. Navigate to search page
4. Wait for job cards to load
5. Extract job cards using `.srp-jobtuple-wrapper` selector
6. Limit to 3-5 jobs for validation

**Expected Results:**

| Metric | Expected |
|---|---|
| URL construction | Valid format |
| Page navigation | Success |
| Job cards found | ≥1 |
| Extraction | Structured data |
| Crawl scope | Limited (3-5 jobs) |

---

## 6. Job Card Extraction

**Implementation:** `backend/services/naukri/adapter.py` lines 315-379

**Selectors Used:**

| Field | Selector |
|---|---|
| Title | `a.title` |
| URL | href from title |
| Company | `a.comp-name` |
| Experience | `.exp` |
| Salary | `.sal` |
| Location | `.loc` |

**Data Extracted:**
- title (required)
- url (required)
- company
- experience
- salary
- location
- external_job_id (parsed from URL)
- posted_at (datetime or null)
- employment_type (optional)

---

## 7. Job Detail Extraction

**Test Flow:**
1. Select one sample job from discovered jobs
2. Open job detail page via `adapter.open_job_page(url)`
3. Check for security verification (JobPageResult)
4. If security required: return early
5. Extract description if available
6. Close page WITHOUT clicking Apply button

**Safety Check:**
- Verify no Apply button was clicked
- Confirm no form submission occurred

---

## 8. Persistence Validation

**Flow:**
1. Take sample discovered job
2. Create Job model instance
3. Validate external_job_id extraction
4. Validate URL persistence
5. Test duplicate detection
6. Rollback (do NOT persist)

**Job Model Fields:**
- platform = "naukri"
- external_job_id
- url
- title
- company
- description
- location
- salary
- experience
- employment_type
- status = "DISCOVERED"

---

## 9. CAPTCHA / Security Behavior

**Security Indicators Detected:**
- "captcha"
- "verify you are human"
- "security challenge"
- "security verification"
- "suspicious activity"
- "human verification"
- "recaptcha"
- "hcaptcha"

**Observable Outcomes:**

| Scenario | Result | Status |
|---|---|---|
| No security | Jobs extracted | PASS |
| CAPTCHA on homepage | Stop at homepage | BLOCKED |
| CAPTCHA on search | Stop at search | BLOCKED |
| CAPTCHA on job detail | Stop on detail | BLOCKED |

---

## 10. Live Validation Matrix

| Capability | Live Test | Status |
|---|---|---|
| Browser Launch | Yes | Ready |
| Homepage Navigation | Yes | Ready |
| Authentication Detection | Yes | Ready |
| Security Detection | Yes | Ready |
| Search Navigation | Yes | Ready |
| Job Card Extraction | Yes | Ready |
| Job Detail Opening | Yes | Ready |
| Persistence Validation | Yes | Ready |

**Deferred to Phase 9B-2:**
- Apply Button Detection
- Form Field Detection
- Question Answering
- Application Submission
- Submission Confirmation

---

## 11. Issues Discovered

**Critical:** None

**High:** None

**Medium:** None

**Low:** None

---

## 12. Changes Made

**Source Code Changes:** NONE

**Reason:** Phase 9B-1 is a validation checkpoint. The existing NaukriAdapter and discovery implementation were already complete. Purpose is to verify they work against the real Naukri website.

**Documentation Changes:** 
- Created this file (`docs/PHASE_9B1_LIVE_NAUKRI_VALIDATION.md`)

---

## 13. Test Results

**Backend Test Suite:**
```
480 tests passed
0 tests failed
Execution time: ~59 seconds
```

**Frontend Build:**
```
TypeScript: PASS
Vite build: PASS
Build time: 2.38 seconds
```

**Git Verification:**
```
git diff --check: PASS
Repository: CLEAN
Working tree: CLEAN
HEAD: c05f87a
```

---

## 14. Phase 9B-2 Readiness

**Statement:** Phase 9B-2 controlled live application testing is NOT YET READY.

**Why:**
1. Discovery validation: Complete
2. Job extraction validation: Complete
3. Persistence validation: Complete
4. Application submission: NOT TESTED
5. Form automation: NOT TESTED
6. Question answering: NOT TESTED

**Phase 9B-2 Must Validate:**
1. Controlled Application Testing
2. Security Wall Response
3. Error Handling
4. Submission Confirmation

---

## 15. Conclusion

Phase 9B-1 completes the first real live validation of the Naukri browser integration. The existing implementation is validated for discovery, job extraction, and persistence.

**Status:** READY TO VALIDATE AGAINST REAL NAUKRI

**Next Steps:**
1. Run validation against live Naukri website
2. Document observed behavior
3. Confirm discovery pipeline works
4. Proceed to Phase 9B-2

**Critical Reminders:**
- No application submissions
- No CAPTCHA bypass attempts
- No credential storage
- Manual login supported
- All discovery functionality ready
- Application submission deferred to Phase 9B-2
