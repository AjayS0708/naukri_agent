# Product Requirements

- **Product:** Naukri AI Job Application Agent
- **Current implementation:** E5-R33 (`37b35ed`)
- **Document status:** current product specification
- **Last updated:** 2026-11-01

The original long-form PRD and its historical status notes are preserved in [`docs/archive/MASTER_PRD_THROUGH_E5_R23.md`](archive/MASTER_PRD_THROUGH_E5_R23.md). This document describes the product as implemented now.

---

## 1. Product vision

Give a job seeker a trustworthy local assistant that can search Naukri, evaluate opportunities against their real profile and preferences, submit native applications, and report every outcome honestly.

The product is not a spray-and-pray bot. It is an operator-controlled application agent with explicit safety boundaries, human review for uncertainty, and evidence-based success reporting.

---

## 2. Target user

A single job seeker who:

- Uses Naukri.com.
- Has a PDF resume and a confirmed candidate profile.
- Wants to automate repetitive discovery and native applications.
- Is willing to review unresolved items and answer screening questions.
- Runs the agent on their own Windows machine with their own Naukri session.

The V1 product does not serve teams, recruiters, or multiple accounts.

---

## 3. Goals

1. Reduce repetitive Naukri search and application work.
2. Apply only to jobs that match the user's confirmed profile and preferences.
3. Never submit an external application.
4. Never claim success without visible evidence.
5. Keep the operator informed and in control.
6. Preserve a complete, truthful application history.
7. Make every decision explainable through reasons and stats.
8. Recover safely from interruptions without duplicating applications.

## 4. Non-goals

- Multi-platform job search.
- Recruiter or employer tooling.
- Bulk applications without eligibility checks.
- CAPTCHA or security-control bypass.
- Fabricating candidate facts or credentials.
- Automatic resolution of unresolved attempts.
- Multi-tenant SaaS.
- Cloud browser execution in the current scope.
- Replacing human judgment on sensitive questions.

---

## 5. Product principles

1. **Deterministic rules are authoritative.** AI is advisory.
2. **Truth over volume.** A smaller number of confirmed applications is better than inflated counts.
3. **Uncertainty is visible.** Unknown salary, unknown posted date, ambiguous mode, and ambiguous submission are handled honestly.
4. **External means stop.** External applications are recorded, not submitted.
5. **Human review is a feature.** `NEEDS_ATTENTION` is a deliberate outcome.
6. **One browser, one run.** Concurrency is prevented, not managed optimistically.
7. **History is durable.** Prior attempts and user skips protect future runs.
8. **No silent widening.** Answer scopes and preferences do not expand without explicit action.

---

## 6. Functional requirements

### 6.1 Profile

| ID | Requirement | Status |
|---|---|---|
| PR-1 | Accept a PDF resume up to 10 MB. | Implemented |
| PR-2 | Extract structured profile facts with Gemini. | Implemented |
| PR-3 | Require explicit review and confirmation before automation. | Implemented |
| PR-4 | Allow editing of extracted fields. | Implemented |
| PR-5 | Deduplicate identical resumes by hash. | Implemented |
| PR-6 | Never store Naukri credentials. | Implemented |

### 6.2 Preferences

| ID | Requirement | Status |
|---|---|---|
| PF-1 | Configure target job titles and search scope. | Implemented |
| PF-2 | Configure multiple locations. | Implemented |
| PF-3 | Configure employment types. | Implemented |
| PF-4 | Configure maximum required experience. | Implemented |
| PF-5 | Configure minimum disclosed salary. | Implemented |
| PF-6 | Configure application aggressiveness. | Implemented |
| PF-7 | Preserve saved preferences without silent reset. | Implemented |

### 6.3 Discovery

| ID | Requirement | Status |
|---|---|---|
| D-1 | Search Naukri using configured titles and locations. | Implemented |
| D-2 | Support pagination and multiple search groups. | Implemented |
| D-3 | Deduplicate jobs by canonical identity. | Implemented |
| D-4 | Classify native, external, and ambiguous application modes. | Implemented |
| D-5 | Parse posted dates only when grounded. | Implemented |
| D-6 | Persist discovery progress. | Implemented |
| D-7 | Detect expired listings. | Implemented |
| D-8 | Reject clearly irrelevant roles before expensive work. | Implemented |

### 6.4 Matching

| ID | Requirement | Status |
|---|---|---|
| M-1 | Require a confirmed profile. | Implemented |
| M-2 | Require preferences. | Implemented |
| M-3 | Enforce target-title relevance. | Implemented |
| M-4 | Enforce location, experience, employment type, and salary rules. | Implemented |
| M-5 | Enforce IT-scope policy. | Implemented |
| M-6 | Share one protection rule across all candidate stages. | Implemented |
| M-7 | Explain rejections with stable reasons. | Implemented |
| M-8 | Handle unknown salary without fabricating a rejection. | Implemented |

### 6.5 AI

| ID | Requirement | Status |
|---|---|---|
| A-1 | Use Gemini for structured job analysis. | Implemented |
| A-2 | Keep AI advisory. | Implemented |
| A-3 | Use a durable queue with retry states. | Implemented |
| A-4 | Record quota exhaustion honestly. | Implemented |
| A-5 | Support deterministic fallback when analysis is unavailable. | Implemented |
| A-6 | Cache analyses for reuse. | Implemented |
| A-7 | Only an explicit suspicious flag can block. | Implemented |

### 6.6 Applications

| ID | Requirement | Status |
|---|---|---|
| AP-1 | Apply only to native Naukri listings. | Implemented |
| AP-2 | Re-verify application mode before clicking. | Implemented |
| AP-3 | Require visible evidence for `APPLIED`. | Implemented |
| AP-4 | Record unconfirmed submissions as `SUBMITTED`. | Implemented |
| AP-5 | Reconcile ambiguous submissions against history. | Implemented |
| AP-6 | Record unresolved attempts as `NEEDS_ATTENTION`. | Implemented |
| AP-7 | Never submit external applications. | Implemented |
| AP-8 | Stop on CAPTCHA or security challenge. | Implemented |
| AP-9 | Support legacy forms and conversational drawers. | Implemented |
| AP-10 | Bound conversational steps, prompts, and answers. | Implemented |
| AP-11 | Use one shared browser session per batch. | Implemented |
| AP-12 | Recover a session lost before an attempt, up to three restarts. | Implemented |
| AP-13 | Never blindly retry a session lost during an attempt. | Implemented |
| AP-14 | Honor stop and skip at safe boundaries. | Implemented |

### 6.7 Screening

| ID | Requirement | Status |
|---|---|---|
| SQ-1 | Resolve saved memory, profile, AI, then human review. | Implemented |
| SQ-2 | Support scoped answer memory. | Implemented |
| SQ-3 | Never store or auto-answer sensitive questions. | Implemented |
| SQ-4 | Require authorization for global reuse of context-sensitive answers. | Implemented |
| SQ-5 | Expire stale profile and option answers. | Implemented |
| SQ-6 | Let the operator answer, skip, or stop. | Implemented |
| SQ-7 | Re-validate login after a wait. | Implemented |
| SQ-8 | Continue the batch after a wait timeout. | Implemented |

### 6.8 Run control

| ID | Requirement | Status |
|---|---|---|
| RC-1 | Start only on explicit user action. | Implemented |
| RC-2 | Prevent concurrent apply processes. | Implemented |
| RC-3 | Return the active run identity on conflict. | Implemented |
| RC-4 | Support idempotent stop. | Implemented |
| RC-5 | Report a user stop as `CANCELLED`. | Implemented |
| RC-6 | Keep active state separate from last-run history. | Implemented |
| RC-7 | Do not auto-start the scheduler on startup. | Implemented |
| RC-8 | Persist progress and waiting state. | Implemented |
| RC-9 | Report remaining jobs as unstarted after a stop. | Implemented |

### 6.9 Manual apply

| ID | Requirement | Status |
|---|---|---|
| MA-1 | Apply to stored jobs without running discovery. | Implemented |
| MA-2 | Show per-job eligibility and exclusion reasons. | Implemented |
| MA-3 | Support search, pagination, and eligibility filtering. | Implemented |
| MA-4 | Support multi-select and dry run. | Implemented |
| MA-5 | Use the same safety pipeline as the autonomous cycle. | Implemented |
| MA-6 | Share the singleton apply lock. | Implemented |
| MA-7 | Support per-job skip without interrupting a submission. | Implemented |
| MA-8 | Protect user-skipped jobs from future runs. | Implemented |

### 6.10 Dashboard and reporting

| ID | Requirement | Status |
|---|---|---|
| UI-1 | Show live run state and progress. | Implemented |
| UI-2 | Show queue health and attention items. | Implemented |
| UI-3 | Show job and application detail. | Implemented |
| UI-4 | Show real analytics, not estimates. | Implemented |
| UI-5 | Show notifications and activity. | Implemented |
| UI-6 | Support profile and preference editing. | Implemented |
| UI-7 | Support screening answers in the dashboard. | Implemented |
| UI-8 | Provide responsive desktop and mobile layouts. | Implemented |

---

## 7. Safety requirements

| ID | Requirement | Status |
|---|---|---|
| S-1 | External applications are never submitted. | Enforced |
| S-2 | `APPLIED` requires positive visible evidence. | Enforced |
| S-3 | Ambiguous submissions are not blindly retried. | Enforced |
| S-4 | CAPTCHA and security challenges stop automation. | Enforced |
| S-5 | Blocking history always prevents re-application. | Enforced |
| S-6 | User skips protect jobs from future runs. | Enforced |
| S-7 | One apply lock covers autonomous, manual, and scheduler paths. | Enforced |
| S-8 | One process owns the persistent browser profile. | Enforced |
| S-9 | AI cannot override deterministic rejection. | Enforced |
| S-10 | Candidate facts are never fabricated. | Enforced |
| S-11 | No automatic scheduler start. | Enforced |
| S-12 | Production CORS origins are explicit. | Enforced |
| S-13 | Credentials are not exposed in dashboard schemas. | Enforced |
| S-14 | Public exposure requires an external authentication layer. | Operational requirement |

---

## 8. Key user journeys

### 8.1 First setup

1. Upload resume.
2. Review extracted facts.
3. Confirm profile.
4. Save preferences.
5. Open a run and log in to Naukri manually.

**Success:** profile is confirmed and the Naukri session is usable.

### 8.2 Autonomous run

1. Start the cycle.
2. Watch discovery, filtering, AI, and application progress.
3. Answer a screening question if one appears.
4. Review final stats and attention items.

**Success:** every attempted job has a truthful terminal outcome.

### 8.3 Manual batch

1. Open Apply Queue.
2. Filter or search stored jobs.
3. Select eligible jobs.
4. Start the batch, optionally dry-run.
5. Skip a job if it is no longer wanted.
6. Review outcomes.

**Success:** selected eligible jobs are processed through the same safety gates as an autonomous run.

### 8.4 Resolve attention

1. Open Needs Attention.
2. Inspect the job, attempt, and evidence.
3. Decide whether to resolve externally or leave it protected.

**Success:** no unresolved attempt is silently retried.

---

## 9. Acceptance criteria

### 9.1 Current release acceptance

- Profile can be uploaded, reviewed, confirmed, and edited.
- Preferences persist.
- Discovery returns and classifies jobs.
- Deterministic filters and protection reject ineligible jobs.
- AI queue processes and records failures honestly.
- Native applications require evidence.
- External applications are never submitted.
- Manual apply works over stored jobs.
- Screening HITL works end to end.
- A second apply process is refused.
- The frontend builds and exposes all documented pages.
- The backend test suite passes.

### 9.2 Live multi-job acceptance

The product's broader live acceptance criterion is:

> One dashboard-initiated run completes at least two native applications in a single cycle, with no manual intervention, and reports every outcome truthfully.

This criterion is **not claimed as re-verified** for this documentation revision. Earlier live evidence includes verified single-job applications and a controlled live run with one application; those records are historical and are not a substitute for a fresh multi-job run.

---

## 10. Success measures

| Measure | Definition |
|---|---|
| Truthful applications | Applications with evidence, never inferred from a click |
| False-positive applications | Must be zero |
| External submissions | Must be zero |
| Duplicate applications | Must be zero for protected jobs |
| Unresolved attempts | Visible in Needs Attention, never hidden |
| Candidate quality | Eligible jobs pass shared relevance and hard filters |
| Operator control | Stop and skip honored at safe boundaries |
| Recoverability | Interrupted runs leave a coherent, inspectable state |

Volume is not a success measure by itself.

---

## 11. Product constraints

- Naukri-only.
- Windows-first live automation.
- Local single-user deployment.
- Gemini availability and quota.
- Naukri markup and session behavior.
- No CAPTCHA bypass.
- No external application submission.
- No cloud browser in the current scope.
- No built-in authentication.

---

## 12. Future work outside the current release

- Multi-platform support.
- Multi-account support.
- Cloud browser workers.
- Recruiter-side automation.
- Automatic resolution of unresolved applications.
- Full answer-engine autonomy without human review.
- Multi-tenant SaaS controls.

See [FUTURE_IMPLEMENTATION_ROADMAP.md](FUTURE_IMPLEMENTATION_ROADMAP.md) for planned work.

---

## 13. Related documents

- [README](../README.md)
- [Architecture](ARCHITECTURE.md)
- [API reference](API.md)
- [Architecture decisions](DECISIONS.md)
- [Development status](DEVELOPMENT_STATUS.md)
- [Future roadmap](FUTURE_IMPLEMENTATION_ROADMAP.md)
- [Historical PRD through E5-R23](archive/MASTER_PRD_THROUGH_E5_R23.md)
