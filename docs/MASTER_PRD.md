# Naukri AI Job Application Agent

## Master Product Requirements Document (PRD)

**Version:** 1.0
**Status:** Master Source of Truth
**Target Platform:** Windows
**Initial Job Platform:** Naukri
**AI Provider:** Google Gemini API
**Architecture:** Local-first, cloud-ready
**Primary Automation:** Playwright
**Backend:** Python + FastAPI
**Frontend:** React + TypeScript
**Database:** SQLite (V1), PostgreSQL-ready

---

# 1. Product Vision

Build a Windows-based AI-powered job application agent that can independently discover suitable jobs on Naukri, evaluate them against the user's explicitly defined job preferences and profile, and automatically submit applications for eligible Naukri-native jobs.

The system should behave like a controlled autonomous agent rather than a simple browser macro.

The agent must:

1. Understand the user's resume/profile.
2. Respect user-defined job-search criteria.
3. Discover relevant Naukri jobs.
4. Apply hard eligibility rules before using AI.
5. Use Gemini for job understanding, matching, classification, and application-question assistance.
6. Validate Gemini's recommendations through deterministic Python rules.
7. Automatically apply to eligible Naukri-native jobs.
8. Stop and notify the user when security challenges or critical failures occur.
9. Record every important action.
10. Provide a professional dashboard showing activity, applications, statistics, and issues.
11. Operate locally on Windows in V1.
12. Be architected so that cloud/24×7 execution and additional job platforms can be added later.

---

# 2. Core Product Principle

## AI is not the final authority.

Gemini is the **reasoning/understanding layer**, not the execution authority.

The architecture must enforce:

```text
Naukri
   ↓
Playwright
   ↓
Python extraction
   ↓
Cheap deterministic filters
   ↓
Duplicate detection
   ↓
Gemini analysis
   ↓
Pydantic validation
   ↓
Python Final Rules Engine
   ↓
APPLY / SKIP / NEEDS_ATTENTION
   ↓
Playwright execution
```

Gemini must never directly control the browser.

Gemini must never return browser commands.

Gemini must never bypass hard eligibility rules.

Gemini must never invent user information.

---

# 3. V1 Scope

## Included

* Windows desktop/local application
* Naukri job discovery
* Naukri job analysis
* Resume PDF upload
* AI profile extraction
* User profile confirmation/editing
* Multiple user-defined job profiles/search categories
* User-defined job titles/search terms
* Hard job eligibility rules
* AI-based matching
* Duplicate detection
* Naukri-native automatic applications
* Application-question handling
* Application history
* Job skip history
* Feedback/learning from explicit user feedback
* Scheduler
* Daily/hourly application limits
* Offline recovery
* Naukri browser-session reuse
* Chrome and Edge support
* CAPTCHA/security challenge detection
* Critical-error handling
* Email notifications
* Evening summary
* Professional dashboard
* AI usage tracking
* SQLite database
* Logging
* Windows packaging

## Explicitly NOT included in V1

* LinkedIn automation
* Indeed automation
* Other job-platform automation
* External company application submission
* CAPTCHA solving/bypass
* Anti-bot/rate-limit bypass
* Automatic recruiter messaging
* Recruiter follow-ups
* Recruiter-status monitoring
* Automatic modification of factual resume information
* Automatic fabrication of answers
* Multiple Naukri accounts
* Cloud execution
* 24/7 execution while the user's PC is turned off

These should remain future capabilities.

---

# 4. Local vs Cloud Strategy

V1 is **local-first**.

The application runs on the user's Windows machine.

Therefore:

```text
PC ON
→ Agent can operate

PC OFF
→ Agent cannot operate
```

The system must NOT pretend to operate while the computer is powered off.

However, the architecture must be cloud-ready.

Cloud readiness infrastructure has been implemented to support future cloud deployment without changing business logic:

- `RuntimeContext` abstraction for environment-specific behavior
- `StorageService` abstraction for file operations (enables future object storage)
- Environment variable configuration with `NAUKRI_AGENT_` prefix
- Database abstraction supporting both SQLite and PostgreSQL
- No changes to existing V1 functionality or public APIs

Future architecture:

```text
V1
Windows PC
   ↓
Local Agent
   ↓
RuntimeContext (LOCAL_WINDOWS)
   ↓
StorageService (local filesystem)
   ↓
SQLite

Future
Cloud Scheduler
   ↓
Remote Worker
   ↓
RuntimeContext (CLOUD_READY)
   ↓
StorageService (object storage)
   ↓
PostgreSQL
   ↓
Remote Browser Automation
   ↓
Dashboard
```

When the PC starts again, the agent should perform recovery discovery.

It should:

1. Determine the last successful discovery run.
2. Search for jobs posted/discovered since that period where possible.
3. Optionally consider the previous 24 hours.
4. Deduplicate against existing jobs/history.
5. Prioritize fresh and relevant jobs.
6. Apply jobs that are still discoverable and eligible.
7. Never assume a historical job still exists if Naukri cannot currently expose it.

---

# 5. User Profile

The user uploads **one PDF resume** to the application.

The system stores a local copy.

Gemini extracts structured information such as:

* Name
* Education
* Degree
* University
* Graduation year
* Skills
* Programming languages
* Frameworks
* Tools
* Projects
* Certifications
* Work experience
* Experience duration
* Current role
* Previous roles
* Current CTC, if provided
* Notice period, if provided
* Location
* Other explicitly stated professional information

The extracted profile must be shown to the user.

The user must review and confirm it before automation begins.

---

# 6. Resume Management

V1 supports:

```text
Upload Resume
      ↓
Extract text
      ↓
Gemini profile extraction
      ↓
User review/edit
      ↓
Confirm profile
      ↓
Agent enabled
```

If the resume changes:

```text
User uploads new PDF
      ↓
New extraction
      ↓
User reviews
      ↓
Profile updated
```

The system must not automatically invent or modify actual profile information.

The application may refresh/re-upload an existing Naukri resume/profile timestamp where technically supported, but it must never alter factual information without user input.

---

# 7. Job Search Configuration

The user controls job-search criteria.

The user can create multiple job profiles.

Example:

```text
Profile 1:
Data Analyst

Profile 2:
Data Scientist

Profile 3:
AI/ML Engineer
```

Each profile can contain:

* Job titles
* Search keywords
* Related titles within user-approved scope
* Locations
* Minimum salary
* Employment types
* Application limits
* Aggressiveness mode

Gemini must NOT have unrestricted authority to invent completely new job categories or search areas.

User-defined search criteria are authoritative.

---

# 8. Location Rules

Location is a **hard filter**.

The user's current required locations are:

* Bengaluru
* Remote

The agent should apply if:

### Case 1

Job location:

```text
Bengaluru
```

→ Apply.

### Case 2

Job location:

```text
Remote
```

→ Apply.

### Case 3

Job location:

```text
Bengaluru / Hyderabad / Pune
```

→ Apply because Bengaluru is included.

### Case 4

Job location:

```text
Hyderabad / Pune
```

→ Skip.

The AI cannot override this rule.

---

# 9. Experience Rules

Experience requirements are a hard filter.

If the job explicitly requires more experience than the user's profile supports:

```text
SKIP
```

Example:

```text
User: 1 year experience
Job: Requires 3–5 years

→ SKIP
```

The agent must not apply merely because Gemini thinks the user could perform the job.

---

# 10. Salary Rules

Minimum acceptable salary:

**₹4 LPA**

When salary information exists:

| Job salary    | Decision            |
| ------------- | ------------------- |
| ₹2–4 LPA      | SKIP                |
| ₹3–5 LPA      | APPLY               |
| ₹4–6 LPA      | APPLY               |
| ₹6+ LPA       | APPLY               |
| ₹10+ LPA      | APPLY               |
| Not disclosed | Continue evaluation |

Important:

A salary range is acceptable if it includes ₹4 LPA.

Example:

```text
₹3–5 LPA
```

→ APPLY.

But:

```text
₹2–4 LPA
```

→ SKIP.

If salary is undisclosed, salary does not automatically disqualify the job.

---

# 11. Employment Type

Allowed:

* Full-time
* Internship
* Contract

Other employment types should be skipped unless explicitly configured later.

---

# 12. Company Filtering

V1 has:

```text
No company blacklist
No company whitelist
```

Any company can be considered if all other rules pass.

---

# 13. Consultancy / Recruiter Jobs

Consultancy postings require additional evaluation.

Preferred:

```text
Actual hiring company clearly identifiable
```

If a consultancy/recruiter is involved:

* Identify the actual employer if possible.
* Evaluate job quality.
* Detect suspicious/spam postings.
* Detect obvious duplicates.
* Skip if employer cannot reasonably be identified.

Gemini can classify ambiguous cases.

Python remains responsible for final enforcement.

---

# 14. Job Freshness

Fresh jobs should be prioritized.

However:

**Freshness is not a replacement for relevance.**

Priority should generally be:

```text
Eligible + highly relevant + fresh
```

rather than simply:

```text
Newest job regardless of relevance
```

---

# 15. Skill Matching

The system does not require 100% skill matching.

A job can be applied to if most relevant skills match the user's profile.

Example:

```text
Job requires:
Python
SQL
Power BI
Excel
AWS

User has:
Python
SQL
Power BI
Excel

→ Potential APPLY
```

Missing one non-critical skill should not automatically cause rejection.

However:

* Experience rules remain hard.
* Location rules remain hard.
* Salary rules remain hard.
* Employment rules remain hard.

---

# 16. Poor or Short Job Descriptions

If the job description is incomplete or unusually short:

1. Use available job title.
2. Use available metadata.
3. Apply hard filters.
4. If title strongly matches a user-defined target role, Gemini may evaluate the available information.
5. If still sufficiently relevant, the job may be applied to.

The system should not automatically reject every job with a poor description.

---

# 17. Duplicate Detection

Duplicate detection is mandatory.

Before AI analysis where practical, Python should compare:

* Naukri job ID
* URL
* Company
* Job title
* Description similarity
* Existing application history
* Previously discovered jobs

Possible states:

```text
CLEAR_NEW
LIKELY_DUPLICATE
BORDERLINE_DUPLICATE
CONFIRMED_DUPLICATE
```

Gemini can evaluate borderline cases.

A job already successfully applied to must not be applied to again.

---

# 18. Gemini Responsibilities

Gemini is responsible for:

### Profile understanding

Extract structured information from resume text.

### Job understanding

Determine:

* Role relevance
* Skill relevance
* Experience compatibility
* Job quality
* Suspicious/low-quality indicators
* Consultancy/recruiter classification
* Duplicate likelihood where needed

### Application questions

Generate answers to open-ended application questions using:

* User profile
* Job description
* Question context

### Learning

Analyze explicit user feedback and application history to improve recommendations.

Gemini cannot:

* Override hard rules.
* Trigger application submission.
* Control Playwright.
* Invent user information.
* Bypass CAPTCHA.
* Bypass security.
* Change hard filters automatically.
* Create unrestricted search categories.

---

# 19. Gemini Output Contract

All Gemini responses must use strict structured output.

Preferred implementation:

```text
Gemini
 ↓
JSON
 ↓
Pydantic schema
 ↓
Validation
 ↓
Application logic
```

Example conceptual schema:

```json
{
  "recommendation": "APPLY",
  "match_score": 86,
  "role_match": true,
  "skill_match": true,
  "experience_match": true,
  "job_quality": "GOOD",
  "duplicate_probability": 0.02,
  "suspicious": false,
  "short_reason": "Strong match for Python and data-analysis experience."
}
```

No free-form browser instructions.

No executable instructions.

No chain-of-thought storage.

Only structured analysis and short explanations should be persisted.

---

# 20. AI Decision States

Gemini may return:

```text
APPLY
SKIP
NEEDS_ATTENTION
```

But the actual application decision must be made by the Python rules engine.

Example:

```text
Gemini → APPLY

Python checks:
Location ❌

Final:
SKIP
```

Another example:

```text
Gemini → APPLY

Python checks:
Location ✅
Experience ✅
Salary ✅
Employment type ✅
Duplicate ✅
Daily limit ✅
Required profile data ✅

Final:
APPLY
```

---

# 21. Final Safety Gate

Before every application submission:

```text
FINAL_RULE_CHECK
```

Python must revalidate:

* Location
* Experience
* Salary
* Employment type
* Duplicate status
* Daily application limit
* Hourly application limit
* Required profile information
* Authentication state
* Agent state
* Security state
* Application eligibility

Only after all checks pass can Playwright submit the application.

Gemini cannot bypass this gate.

---

# 22. Application Questions

Application questions have two categories.

## Factual questions

Use fixed user-profile information.

Example:

```text
Years of experience:
```

Use the confirmed profile value.

Gemini should not generate a different number.

## Open-ended questions

Gemini may generate a tailored answer using:

```text
User Profile
+
Job Description
+
Question
```

Example:

```text
Why are you interested in this role?
```

Gemini can produce a concise JD-specific response.

The answer must remain truthful.

---

# 23. Unknown Information

If an application asks:

```text
How many years of AWS experience do you have?
```

and the profile contains no AWS experience:

The system must NOT guess.

Fallback hierarchy:

```text
Configured fallback answer
        ↓
Needs Attention
        ↓
Skip/continue safely according to application context
```

The agent should continue processing other jobs where safe.

---

# 24. Naukri Application Flow

Conceptual flow:

```text
Discover Job
      ↓
Extract Data
      ↓
Hard Filter
      ↓
Duplicate Check
      ↓
Gemini Analysis
      ↓
Pydantic Validation
      ↓
Final Python Rules
      ↓
Eligible?
  /          \
NO            YES
↓              ↓
SKIP        Start Application
               ↓
        Detect Application Type
          /              \
Naukri Native        External Site
     ↓                    ↓
Fill Form          DO NOT SUBMIT
     ↓                    ↓
Validate           Notify User
     ↓
Submit
     ↓
Record Applied
```

---

# 25. External Applications

If Naukri redirects to an external company/application website:

**Do not submit the external application.**

Instead:

1. Stop that job's application flow.
2. Mark it:

```text
EXTERNAL_APPLICATION
```

3. Record:

   * Job title
   * Company
   * URL
   * Reason
   * Discovery timestamp

4. Notify the user by:

   * Dashboard
   * Email

5. Continue with other eligible jobs if the system is in a safe state.

---

# 26. Browser Automation

Use:

**Playwright**

Supported browsers:

* Google Chrome
* Microsoft Edge

Browser should be configurable.

The implementation must use normal browser interaction.

The system must NOT implement:

* CAPTCHA bypass
* Anti-bot bypass
* Rate-limit circumvention
* Security challenge bypass
* Credential theft
* Stealth techniques intended to evade platform security controls

If Naukri presents a security challenge, the agent stops.

---

# 27. Authentication

V1 uses:

**Manual login once + persistent authenticated browser session.**

The user logs into Naukri manually.

The application reuses the authenticated session.

Raw Naukri passwords must not be stored.

If the session expires:

```text
AUTH_REQUIRED
```

The agent must:

1. Stop automation.
2. Notify user.
3. Ask user to log in again.
4. Resume only after authentication is restored.

---

# 28. CAPTCHA / Security Challenge

If the agent encounters:

* CAPTCHA
* Human verification
* Suspicious login
* Security checkpoint
* Unexpected authentication challenge

Then:

```text
STOP AGENT
+
NOTIFY USER
```

No automated bypass is permitted.

The user resolves the challenge manually and restarts/resumes the agent.

---

# 29. Application Limits

Application volume must be configurable.

The user wants dynamic application behavior.

Settings include:

```text
Aggressiveness:
Conservative
Balanced
Aggressive
```

Additionally:

```text
Maximum daily applications
Maximum hourly applications
```

The agent dynamically distributes applications within these absolute limits.

Hard filters always override aggressiveness.

Aggressive mode does NOT mean:

```text
Ignore eligibility rules
```

It means the system can be more willing to apply among jobs that already satisfy hard rules.

---

# 30. AI API Usage Control

The application is designed around the Gemini free tier.

Therefore API calls must be conserved.

Strategies:

* Cheap Python pre-filtering
* Avoid AI analysis for obvious hard-filter failures
* Cache job analysis
* Avoid re-analyzing the same job unnecessarily
* Deduplicate before Gemini
* Configurable AI request limits
* Track usage
* Queue AI work
* Process jobs intelligently

---

# 31. Gemini Quota Exhaustion

If Gemini quota is exhausted:

```text
AI_QUOTA_EXHAUSTED
```

The agent must:

1. Stop AI-dependent decisions.
2. Continue cheap deterministic discovery/filtering where possible.
3. Queue jobs requiring Gemini.
4. Resume processing when quota becomes available.
5. Never switch to uncontrolled AI-free automatic applications.

---

# 32. Gemini Failure Handling

## Job-level failure

If one Gemini request:

* Times out
* Returns invalid JSON
* Fails validation
* Produces unusable output

Then:

```text
Retry
   ↓
If retry fails
   ↓
NEEDS_ATTENTION
```

Continue with other jobs if safe.

## System-level failure

If Gemini/API experiences a broad failure:

```text
STOP AGENT
+
NOTIFY USER
```

Invalid Gemini output must never reach the application engine.

---

# 33. Learning System

The user can explicitly provide feedback.

Examples:

```text
Not interested
Wrong role
Too senior
Not relevant
Don't apply to this type
```

The system stores this feedback.

Gemini can use:

* Explicit feedback
* Application history
* Previous classifications

to improve recommendations.

However:

**AI learning cannot modify hard filters automatically.**

Example:

If user requires Bengaluru:

```text
AI cannot learn:
"User might accept Hyderabad"
```

unless the user explicitly changes the preference.

---

# 34. Application History

Every successful application should be recorded.

Minimum information:

* Job
* Company
* URL
* Date/time
* Application method
* Status

Successful Naukri-native application:

```text
APPLIED
```

Then move on.

V1 does not automatically monitor recruiters or application outcomes.

---

# 35. Job History

The system should maintain historical job records.

Possible states:

```text
DISCOVERED
FILTERED
AI_ANALYZED
SKIPPED
APPROVED_BY_RULES
APPLICATION_STARTED
APPLIED
EXTERNAL_APPLICATION
NEEDS_ATTENTION
```

Skip reasons should be stored.

Examples:

```text
Location mismatch
Experience too high
Salary below minimum
Duplicate
Wrong employment type
Low relevance
Suspicious posting
External application
Missing required information
```

---

# 36. Data Retention

Application history should be retained by default.

The user must be able to manually:

* Delete
* Archive

historical records.

---

# 37. Scheduler

Default discovery frequency:

**Approximately hourly.**

The scheduler may adapt within reasonable platform limits.

The system should avoid unnecessarily aggressive requests.

Conceptually:

```text
Scheduler
    ↓
Discover jobs
    ↓
Filter
    ↓
Analyze
    ↓
Apply
    ↓
Wait
    ↓
Next cycle
```

The scheduler must respect:

* Hourly application limit
* Daily application limit
* AI quota
* Agent state
* Authentication state
* Security state

---

# 38. Windows Startup

V1 should support:

```text
Auto-start with Windows: ON/OFF
```

The user should also have:

```text
START AUTOMATION
STOP AUTOMATION
```

The user remains in control of whether the agent is running.

---

# 39. Agent State Machine

The agent should have explicit states.

Recommended:

```text
IDLE
RUNNING
SEARCHING
FILTERING
ANALYZING
APPLYING
PAUSED
AUTH_REQUIRED
SECURITY_REQUIRED
AI_QUOTA_EXHAUSTED
NEEDS_ATTENTION
STOPPED
CRITICAL_ERROR
```

---

# 40. Frontend UX/UI Design

The frontend dashboard has been redesigned to provide a polished, modern SaaS experience with the following improvements:

## Design Principles

- **Professional SaaS aesthetic**: Modern dashboard layout with clean visual hierarchy
- **User-centric language**: All development-phase terminology removed from user-facing UI
- **Accessibility-first**: Keyboard navigation, focus states, and screen reader support
- **Responsive design**: Works seamlessly across desktop, tablet, and mobile devices
- **Graceful degradation**: Handles backend unavailability with clear user messaging

## Navigation Structure

The dashboard uses a sidebar navigation with the following sections:

- **Overview**: Main command center with agent status, controls, and key metrics
- **Activity**: Timeline of agent actions and events
- **Jobs**: Job discovery interface (coming soon)
- **Applications**: Application tracking dashboard (coming soon)
- **Analytics**: Performance metrics and decision analytics
- **Profile**: Resume and profile management with completion tracking
- **Preferences**: Job search criteria and automation settings

## Visual Language

The design uses a Naukri-inspired color palette:

- Primary Blue: #0073E6
- Deep Blue: #0056B3
- Accent Orange: #FF8A00
- Light Blue: #EAF4FF
- Background: #F7F9FC
- Success: #16A34A
- Warning: #F59E0B
- Error: #DC2626

Design elements include:
- Rounded corners (8-12px) for modern feel
- Subtle shadows for depth
- Smooth transitions and hover states
- Clear typography hierarchy
- Consistent spacing (4px, 8px, 16px, 24px, 32px system)

## User Experience Improvements

### Error Handling
- Technical error messages replaced with user-friendly alternatives
- Backend connection status clearly indicated
- Retry actions provided where appropriate
- Empty states with helpful guidance

### Profile Onboarding
- Visual profile completion indicator
- Clear section organization
- Progress tracking for setup completion
- Guided upload process

### Preferences
- Organized into logical sections (Target Roles, Locations, Compensation, etc.)
- Clear descriptions for each setting
- User-friendly dropdowns with explanations
- Save confirmation feedback

### Analytics
- Compact, readable charts
- Key metrics at a glance
- Decision breakdown visualization
- Skip reasons tracking

### Backend Connection States
The frontend gracefully handles different backend states:

- **Connected**: Agent backend is running and accessible
- **Local agent offline**: Clear message to start the local Windows agent
- **Cloud backend unavailable**: Temporary service disruption message
- **Checking**: Connection verification in progress

## Accessibility Features

- Skip-to-content link for keyboard navigation
- Proper ARIA labels on interactive elements
- Visible focus states on all interactive elements
- Semantic HTML structure
- Sufficient color contrast
- Keyboard-friendly navigation

## Responsive Design

- Desktop: Full sidebar with all navigation items
- Tablet: Collapsed sidebar with icons only
- Mobile: Off-canvas sidebar with hamburger menu
- Card layouts reflow appropriately
- Tables become scrollable on smaller screens

## Performance

- Minimal dependencies (React, TypeScript, Tailwind CSS)
- Optimized build output
- Efficient API calls with proper error handling
- Loading states for better perceived performance

---

# 41. Agent Intelligence and Decision Quality

The agent should provide explainable decision-making with structured priority levels:

```text
Decision Priorities:
- HARD_REJECT: Fails hard filters (location, experience, salary, duplicate)
- SKIP: Low relevance or not worth applying
- LOW_PRIORITY: Weak match but eligible
- NORMAL_PRIORITY: Good match
- HIGH_PRIORITY: Strong match
- NEEDS_ATTENTION: Requires manual review
```

Decision signals should include:
- Role relevance score
- Skill relevance score
- Experience compatibility score
- Location match score
- Salary suitability score
- Job quality score
- Freshness score
- Duplicate probability
- Suspicious probability
- Historical feedback adjustment

Every decision should have:
- Structured reason codes
- Concise explanation
- Signal breakdown
- Priority level
- Decision score (0-100)

---

# 41. Job Prioritization

Jobs should be prioritized before application processing based on:
- Strong role and skill relevance
- Acceptable salary
- Location fit
- Freshness
- Quality
- Low duplicate probability
- Historical user feedback

Hard-filtered jobs must never become higher priority.

Prioritization must be deterministic and reproducible for the same inputs.

---

# 42. Feedback and Learning

The system should support explicit user feedback:

```text
Feedback Types:
- RELEVANT
- NOT_RELEVANT
- APPLIED
- SKIPPED
- INCORRECT_MATCH
- GOOD_MATCH
- TOO_SENIOR
- TOO_JUNIOR
- WRONG_LOCATION
- SALARY_TOO_LOW
```

Feedback influences ranking/prioritization only.

Learning boundaries:
- CANNOT modify hard filters automatically
- CANNOT change salary minimum
- CANNOT change location restrictions
- CANNOT change experience restrictions
- CANNOT remove duplicate protection
- CANNOT bypass safety gate
- CANNOT invent new job categories
- CANNOT silently change user preferences

User-controlled preferences remain authoritative.

---

# 43. Application Analytics

The system should provide comprehensive analytics:

```text
Metrics:
- Discovered jobs
- Eligible jobs
- Skipped jobs
- Applications submitted
- Application success rate
- Top skip reasons
- Top application categories
- AI analysis usage
- AI quota/queue activity
- Applications by day
- Applications by job profile
- Decision priority breakdown
- Primary reason codes
- Feedback summary
```

Analytics should use existing Job, Application, and decision data without creating fake historical data.

The dashboard should display the current state.

---

# 40. Critical Error Handling

If a critical Naukri/browser/system error occurs:

```text
STOP AGENT
+
LOG ERROR
+
NOTIFY USER
```

If a single job fails:

```text
MARK NEEDS_ATTENTION
+
LOG ERROR
+
CONTINUE IF SAFE
```

Examples of critical errors:

* Browser completely unavailable
* Naukri session corruption
* Unexpected authentication failure
* Security challenge
* Critical automation failure
* Database integrity issue

---

# 41. Dashboard

The dashboard should be professional rather than a basic developer console.

Main sections:

### Overview

* Agent status
* Applications today
* Applications this week
* Jobs discovered
* Jobs skipped
* Jobs needing attention
* AI usage
* Application limits

### Live Agent Activity

Show concise activity such as:

```text
Searching Naukri...
Found 34 jobs
Filtered 19
Analyzing 15
Applied to 3
Skipped 11
1 needs attention
```

### Applications

* Company
* Role
* Date
* Status
* Application method

### Jobs

* Job title
* Company
* Location
* Match score
* Status
* Short reason

### Settings

* Resume/profile
* Job profiles
* Locations
* Salary
* Employment types
* Application limits
* Aggressiveness
* Browser
* Notifications

### AI Usage

* Requests
* Successful requests
* Failed requests
* Cached analyses
* Estimated/known quota state

---

# 42. AI Analysis Details

Do not display long reasoning or chain-of-thought.

Store structured fields such as:

```text
Match score
Role match
Skill match
Experience match
Location match
Salary match
Job quality
Duplicate probability
Recommendation
Short reason
```

When the user opens a job, these details can be displayed.

The dashboard should remain clean.

---

# 43. Notifications

Notifications are required for:

### Critical errors

* Browser failure
* Authentication expiry
* Security challenge
* Critical Naukri error
* System-level Gemini failure

### External application

Notify with:

* Company
* Job title
* Link
* Reason external application was not submitted

### Daily summary

Send an evening summary around:

**8–9 PM**

The user should not receive an individual notification for every successful routine application.

---

# 44. Daily Summary

Example:

```text
Today's Job Application Summary

Jobs discovered: 86
Jobs analyzed: 42
Applications submitted: 11
Jobs skipped: 29
Needs attention: 2
External applications: 3

Top reasons for skipping:
• Experience mismatch
• Location mismatch
• Duplicate

AI usage:
42 analyses
8 cached
```

Exact content can evolve.

---

# 45. Email

V1 can use SMTP.

Email should be configurable through secure settings.

Never expose credentials in:

* frontend
* logs
* Git
* source code

---

# 46. Database

V1:

**SQLite**

ORM:

**SQLAlchemy**

Future:

**PostgreSQL**

The database layer should avoid tightly coupling application logic to SQLite.

---

# 47. Core Database Entities

## User

Represents the local application user.

## Profile

Stores confirmed resume-derived information.

## JobPreference

Stores user-defined job criteria.

## JobProfile

Stores multiple search/job categories.

## Job

Stores discovered jobs.

## JobAnalysis

Stores structured Gemini analysis.

## Application

Stores application attempts/results.

## ApplicationAnswer

Stores application questions and answers.

## Feedback

Stores explicit user feedback.

## AgentRun

Stores each automation run.

## Notification

Stores notification history where required.

## AIUsage

Tracks Gemini usage.

---

# 48. Suggested Job Schema

```text
id
platform
external_job_id
url
title
company
description
location
salary_min
salary_max
experience_min
experience_max
employment_type
posted_at
discovered_at
last_seen_at
status
created_at
updated_at
```

---

# 49. Suggested JobAnalysis Schema

```text
id
job_id
match_score
role_match
skill_match
experience_match
location_match
salary_match
job_quality
duplicate_probability
suspicious
recommendation
short_reason
model
created_at
```

---

# 50. Suggested Application Schema

```text
id
job_id
status
application_method
started_at
applied_at
failure_reason
skip_reason
external_url
created_at
updated_at
```

---

# 51. Suggested Profile Schema

```text
id
name
education
experience
skills
projects
certifications
current_role
location
ctc
notice_period
resume_path
resume_hash
confirmed
updated_at
```

---

# 52. Suggested Preferences Schema

```text
id
job_titles
search_terms
locations
minimum_salary
employment_types
aggressiveness
max_daily_applications
max_hourly_applications
created_at
updated_at
```

---

# 53. Technology Stack

## Backend

**Python 3.12+**

Framework:

**FastAPI**

## Browser Automation

**Playwright**

Browsers:

* Chrome
* Edge

## AI

**Google Gemini API**

Use the official Google GenAI Python SDK.

## Validation

**Pydantic**

## Database

**SQLite**

ORM:

**SQLAlchemy**

## Scheduler

**APScheduler**

## Resume extraction

**PyMuPDF**

## Frontend

**React**

**TypeScript**

**Tailwind CSS**

## Charts

**Recharts**

## Testing

**pytest**

## Packaging

**PyInstaller**

## Version control

**Git/GitHub**

---

# 54. AI Architecture

Create an abstraction layer:

```text
AIProvider
   │
   └── GeminiProvider
```

Future:

```text
AIProvider
 ├── GeminiProvider
 ├── OpenAIProvider
 ├── OtherProvider
```

The rest of the application should not directly depend on Gemini-specific implementation details.

---

# 55. Platform Architecture

Naukri should be implemented as an adapter.

```text
JobPlatformAdapter
        │
        └── NaukriAdapter
```

Future:

```text
JobPlatformAdapter
 ├── NaukriAdapter
 ├── LinkedInAdapter
 ├── IndeedAdapter
 └── OtherAdapter
```

The core matching/rules/application architecture should not need major rewrites when another platform is added.

---

# 56. Proposed System Architecture

```text
                    React Dashboard
                          │
                          ▼
                     FastAPI API
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
     Profile          Agent Engine       Settings
     Service              │
                           ▼
                       Scheduler
                           │
                           ▼
                    Job Discovery
                           │
                           ▼
                    Naukri Adapter
                           │
                           ▼
                       Playwright
                           │
                           ▼
                      Naukri
                           │
                           ▼
                    Job Extraction
                           │
                           ▼
                Python Hard Filtering
                           │
                           ▼
                    Duplicate Check
                           │
                           ▼
                    Gemini Provider
                           │
                           ▼
                  Pydantic Validation
                           │
                           ▼
                 Final Rules Engine
                           │
                  ┌────────┴────────┐
                  ▼                 ▼
                SKIP              APPLY
                                    │
                                    ▼
                            Application Engine
                                    │
                                    ▼
                               Playwright
                                    │
                                    ▼
                              Naukri Form
                                    │
                                    ▼
                               Application
                                    │
                                    ▼
                               Database
```

---

# 57. Project Structure

Recommended initial structure:

```text
naukri-ai-agent/
│
├── docs/
│   ├── MASTER_PRD.md
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT_STATUS.md
│   └── DECISIONS.md
│
├── backend/
│   ├── api/
│   ├── services/
│   │   ├── naukri/
│   │   ├── gemini/
│   │   ├── matching/
│   │   ├── applications/
│   │   ├── notifications/
│   │   ├── profile/
│   │   └── learning/
│   │
│   ├── models/
│   ├── schemas/
│   ├── database/
│   ├── scheduler/
│   ├── core/
│   └── main.py
│
├── frontend/
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── hooks/
│       ├── services/
│       └── types/
│
├── data/
│   └── resume/
│
├── logs/
│
├── tests/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── run.py
```

---

# 58. Configuration & Secrets

Development:

```text
.env
```

Production Windows application:

Use secure Windows-local credential storage where practical.

Gemini API key must NEVER be:

* Hardcoded
* Stored in frontend code
* Committed to Git
* Printed in logs
* Returned through API responses

`.env` must be included in `.gitignore`.

---

# 59. Logging

The application should maintain structured logs.

Logs should contain:

* Timestamp
* Component
* Event
* Severity
* Job ID where applicable
* Application ID where applicable
* Error category
* Short diagnostic message

Logs must NOT contain:

* API keys
* Passwords
* Sensitive authentication tokens
* Unnecessary private resume data

---

# 60. Error Taxonomy

Use clear error categories:

```text
AUTH_ERROR
SECURITY_ERROR
BROWSER_ERROR
NETWORK_ERROR
NAUKRI_ERROR
AI_ERROR
AI_QUOTA_ERROR
VALIDATION_ERROR
APPLICATION_ERROR
DATABASE_ERROR
CONFIGURATION_ERROR
```

This allows the UI and notification system to react appropriately.

---

# 61. Agent Execution Safety

The agent must follow these principles:

### Principle 1

Hard filters cannot be overridden by AI.

### Principle 2

AI cannot directly execute browser actions.

### Principle 3

Invalid AI output cannot reach execution.

### Principle 4

Security challenges stop automation.

### Principle 5

External applications are never automatically submitted.

### Principle 6

Application limits cannot be exceeded.

### Principle 7

Duplicate applications must be prevented.

### Principle 8

Unknown factual information must never be fabricated.

### Principle 9

Critical errors stop the agent.

### Principle 10

Single-job failures should not unnecessarily stop the entire system.

---

# 62. Application State Machine

```text
DISCOVERED
    ↓
FILTERED
    ↓
AI_ANALYZED
    ↓
APPROVED_BY_RULES
    ↓
APPLICATION_STARTED
    ↓
SUBMITTED
    ↓
APPLIED
```

Alternative paths:

```text
DISCOVERED
    ↓
FILTERED
    ↓
SKIPPED
```

```text
AI_ANALYZED
    ↓
NEEDS_ATTENTION
```

```text
APPROVED_BY_RULES
    ↓
EXTERNAL_APPLICATION
    ↓
NEEDS_ATTENTION
```

```text
APPLICATION_STARTED
    ↓
NEEDS_ATTENTION
```

---

# 63. Performance Strategy

The system should minimize unnecessary work.

Preferred order:

```text
Discovery
↓
Cheap Python filtering
↓
Deduplication
↓
AI only when necessary
↓
Final validation
↓
Application
```

Do not send every discovered job to Gemini.

---

# 64. Caching

Cache:

* Job analysis
* Resume profile extraction
* Duplicate checks where safe
* Other deterministic results where useful

A job should not be re-analyzed simply because it appeared again in search results.

---

# 65. Recovery

If the application crashes:

1. Persist state frequently.
2. Record agent run.
3. On restart, identify incomplete operations.
4. Avoid duplicate submissions.
5. Recheck application state before attempting a potentially duplicate application.
6. Resume safely.

The system should favor:

```text
Don't accidentally apply twice
```

over:

```text
Apply again just to be safe
```

---

# 66. Security

The application is local-first, but security is still important.

Requirements:

* Secure API-key storage
* No password storage
* Protected local configuration
* Sanitized logs
* Input validation
* Pydantic validation
* API authentication/localhost restrictions where appropriate
* Safe file handling
* Resume files stored locally
* No unnecessary external data transmission

Resume data should only be sent to Gemini when required for the AI operation.

---

# 67. Testing Requirements

Testing should include:

## Unit tests

* Salary rules
* Experience rules
* Location rules
* Employment type rules
* Duplicate detection
* Application limits
* AI schema validation
* Profile parsing
* State transitions

## Integration tests

* Database
* FastAPI
* Gemini provider
* Naukri adapter
* Scheduler
* Notification system

## Browser tests

Use controlled/test environments where possible.

Test:

* Login/session detection
* Job extraction
* Application detection
* Form filling
* External redirect detection
* Security challenge detection

---

# 68. Testing Rule Engine Examples

The final rules engine must have deterministic tests.

Example:

```text
Location = Hyderabad only
→ SKIP
```

```text
Location = Bengaluru / Hyderabad
→ APPLY if all other rules pass
```

```text
Salary = ₹3–5 LPA
→ APPLY
```

```text
Salary = ₹2–4 LPA
→ SKIP
```

```text
Experience required = 3 years
User experience = 1 year
→ SKIP
```

```text
Employment = Full-time
→ eligible
```

```text
Already applied = true
→ SKIP
```

---

# 69. Dashboard UX Principle

The application should look like a real professional product.

Avoid a developer-only interface.

The primary screen should immediately communicate:

```text
Agent Status
Applications Today
Jobs Found
Match/Skip Activity
Issues
AI Usage
```

Live activity should be visible but concise.

---

# 70. Multiple Accounts

V1:

```text
One Naukri account
```

Architecture should support future:

```text
Multiple accounts
```

Each future account should have isolated:

* Browser session
* Profile
* Preferences
* Application history
* AI context
* Limits

---

# 71. Future Platform Expansion

The core system should eventually support:

```text
Naukri
LinkedIn
Indeed
Other job platforms
```

Each platform should implement a common interface.

Example:

```python
class JobPlatformAdapter:
    discover_jobs()
    get_job_details()
    detect_application_type()
    start_application()
    submit_application()
    get_auth_status()
```

Platform-specific behavior stays inside the adapter.

---

# 72. Future Cloud Architecture

The system should eventually support:

```text
Web Dashboard
      ↓
API
      ↓
Cloud Scheduler
      ↓
Job Queue
      ↓
Automation Workers
      ↓
Browser Workers
      ↓
Database
```

Potential future capabilities:

* 24/7 monitoring
* Remote execution
* Multiple accounts
* Multiple platforms
* Centralized analytics
* Mobile notifications

These are not V1 requirements.

---

# 73. Development Phases

## Phase 1 — Foundation & Architecture

Build:

* Repository
* Python backend
* FastAPI
* React frontend
* SQLite
* SQLAlchemy
* Configuration
* Logging
* Base architecture
* Core interfaces
* Documentation system
* Health endpoint
* Basic dashboard shell

No real Naukri automation yet.

---

## Phase 2 — Resume & User Profile

Build:

* PDF upload
* Resume extraction
* Gemini profile extraction
* Pydantic profile schema
* Profile review/edit UI
* Confirmation flow
* Job preferences
* Multiple job profiles

---

## Phase 3 — Gemini AI Engine

Build:

* Gemini provider
* Strict JSON output
* Pydantic validation
* Job-analysis schema
* Profile-analysis schema
* AI usage tracking
* Retry logic
* Quota handling
* Caching

---

## Phase 4 — Matching & Rules Engine

Build deterministic:

* Location rules
* Experience rules
* Salary rules
* Employment rules
* Duplicate rules
* Application limits
* Final safety gate
* AI recommendation integration

---

## Phase 5 — Naukri Job Discovery

Build:

* Browser session
* Chrome support
* Edge support
* Naukri adapter
* Search execution
* Job extraction
* Job detail extraction
* Posted-date extraction
* Deduplication
* Discovery persistence

---

## Phase 6 — Naukri Application Automation

Build:

* Naukri-native application detection
* Form detection
* Fixed factual answers
* Gemini open-ended answers
* Required-field detection
* Final safety validation
* Application submission
* Application history
* External-site detection

---

## Phase 7 — Scheduler & Continuous Agent

Build:

* Hourly discovery
* Adaptive scheduling
* Application limits
* Auto-start
* Start/Stop controls
* Recovery after PC restart
* Job queue
* AI quota queue
* Agent state machine

---

## Phase 8 — Dashboard

Build professional UI:

* Overview
* Live agent
* Applications
* Jobs
* Job details
* Match analysis
* History
* Settings
* AI usage
* Statistics

---

## Phase 9 — Notifications

Build:

* Email
* Critical-error notifications
* Authentication notifications
* Security challenge notifications
* External application notifications
* Evening 8–9 PM summary

---

## Phase 10 — Testing, Security & Windows Packaging

Build:

* Unit tests
* Integration tests
* Browser tests
* Recovery tests
* Security hardening
* Credential handling
* PyInstaller package
* Windows installer/run experience

---

## Phase 11 — Integration & Production Hardening

Final integration:

```text
Profile
+
AI
+
Rules
+
Naukri
+
Application
+
Scheduler
+
Dashboard
+
Notifications
```

Perform:

* End-to-end testing
* Crash recovery testing
* Duplicate prevention testing
* AI failure testing
* Security challenge testing
* Quota exhaustion testing
* Application-limit testing
* Performance optimization
* Documentation completion

---

# 74. Master Documentation Rule

This PRD is the **single source of truth**.

It must be stored in:

```text
docs/MASTER_PRD.md
```

Every future development phase must read this file before making changes.

The coding agent must NOT ask the user to upload the PRD again.

Future phase prompts should say:

```text
SOURCE OF TRUTH:
Read docs/MASTER_PRD.md before making any changes.

Also inspect:
docs/ARCHITECTURE.md
docs/DEVELOPMENT_STATUS.md
docs/DECISIONS.md

Treat MASTER_PRD.md as the authoritative product specification.
```

---

# 75. Phase Continuity Rule

Every completed phase must update:

```text
docs/DEVELOPMENT_STATUS.md
```

with:

* Completed features
* Files created/modified
* Database changes
* APIs added
* Components added
* Tests added
* Known limitations
* Remaining work
* Important implementation decisions

This allows the next phase to continue even if the coding agent has no memory of the previous conversation.

---

# 76. Architecture Decision Log

Important architectural decisions must be recorded in:

```text
docs/DECISIONS.md
```

Examples:

```text
Why Playwright instead of Selenium
Why SQLite
Why FastAPI
Why React
Why direct Gemini API
Why Pydantic
Why adapters
Why local-first
Why external applications are not automated
```

Do not silently replace major architectural decisions.

If a change becomes necessary, document it.

---

# 77. Definition of Done

A phase is not considered complete merely because code was generated.

Each phase must:

1. Implement its requirements.
2. Integrate with existing architecture.
3. Run successfully.
4. Include appropriate tests.
5. Avoid breaking previous functionality.
6. Update documentation.
7. Update development status.
8. Record major decisions.
9. Leave the project in a usable state.
10. Clearly identify remaining limitations.

---

# 78. Coding-Agent Operating Rules

Every coding agent working on this project must follow:

### Rule 1

Read:

```text
docs/MASTER_PRD.md
```

before coding.

### Rule 2

Read the current:

```text
docs/DEVELOPMENT_STATUS.md
docs/ARCHITECTURE.md
docs/DECISIONS.md
```

### Rule 3

Do not reimplement existing functionality.

### Rule 4

Do not remove existing functionality unless explicitly required.

### Rule 5

Do not make Gemini more powerful than specified in this PRD.

### Rule 6

Do not bypass Naukri security controls.

### Rule 7

Do not automate external job applications.

### Rule 8

Do not fabricate user information.

### Rule 9

Use typed schemas and validation.

### Rule 10

Keep platform-specific automation isolated.

### Rule 11

Keep AI-provider-specific implementation isolated.

### Rule 12

Run tests before declaring the phase complete.

### Rule 13

Update project documentation after implementation.

### Rule 14

If requirements conflict with this PRD, stop and identify the conflict rather than silently changing the product behavior.

---

# 79. V1 Success Criteria

V1 is successful when a user can:

```text
Install application
      ↓
Upload resume
      ↓
Review AI-extracted profile
      ↓
Configure job preferences
      ↓
Log into Naukri
      ↓
Start agent
      ↓
Agent discovers jobs
      ↓
Hard filters remove invalid jobs
      ↓
Gemini evaluates eligible jobs
      ↓
Python validates decisions
      ↓
Agent applies to eligible Naukri-native jobs
      ↓
Application is recorded
      ↓
Agent continues
      ↓
Dashboard shows activity
      ↓
Evening summary is generated
```

And the system reliably:

* Prevents duplicate applications.
* Enforces hard filters.
* Does not fabricate answers.
* Does not submit external applications.
* Stops for CAPTCHA/security challenges.
* Stops for critical errors.
* Handles Gemini quota limitations.
* Recovers safely after restart.
* Maintains application history.
* Provides useful visibility through the dashboard.

---

# 80. Product Philosophy

The product should not be:

> "An AI that can do anything."

It should be:

> **A controlled autonomous job-application agent where AI provides intelligence, deterministic software provides safety, and the user remains the authority over personal preferences and factual information.**

The most important architectural principle is:

```text
AI decides what a job means.
Rules decide whether it is allowed.
Automation executes only what the rules approve.
```

---

# 81. Production Backend Preparation (Phase 8.1)

The backend has been prepared for production hosting with enhanced configuration, security, and monitoring. This checkpoint does NOT implement actual cloud deployment but ensures the backend is ready for hosted environments.

## Production Configuration

- Environment separation: LOCAL_WINDOWS (V1) vs CLOUD (future)
- Production mode detection: development vs production
- CORS origins: configurable via FRONTEND_ORIGINS (comma-separated)
- Database URL: supports SQLite (default) and PostgreSQL
- Runtime environment: configurable via RUNTIME_ENVIRONMENT
- All configuration driven by environment variables with NAUKRI_AGENT_ prefix

## CORS Configuration

- Development mode: allows localhost origins for convenience
- Production mode: uses only configured origins from FRONTEND_ORIGINS
- Multiple origins supported via comma-separated list
- Wildcard origins NOT used in production
- Configurable methods: GET, POST, PUT, OPTIONS, DELETE
- Configurable headers: Content-Type, X-Request-ID, Authorization

## Health and Readiness Endpoints

- Liveness endpoint (/api/health): simple API process status
- Readiness endpoint (/api/readiness): detailed component status
- Readiness checks: database, configuration, storage, AI provider, runtime environment
- Production mode validates required API keys
- Component status: healthy/unhealthy with detailed error messages
- Ready for container orchestration and health checks

## Error Handling

- Catch-all exception handler prevents sensitive information exposure
- Generic exceptions return safe error messages without stack traces
- Application errors return structured responses with error categories
- Validation errors return 422 with category information
- No filesystem paths, environment variables, or secrets in API responses

## Logging

- Development mode: standard JsonFormatter for debugging
- Production mode: SafeJsonFormatter with automatic redaction
- Sensitive keys redacted: api_key, password, token, secret, credential, auth
- Structured logging with timestamp, level, message, and component
- Extra fields: component, event, error_category, request_id, job_id, application_id
- Logs never contain API keys, credentials, or sensitive user data

## Database Configuration

- SQLite default for local development (sqlite:///./data/naukri_agent.db)
- PostgreSQL support via DATABASE_URL (postgresql://user:pass@host:port/db)
- SQLite directory creation for both relative and absolute paths
- No SQLite-only assumptions preventing hosted operation
- Database initialization works correctly in both modes
- Connection pooling and session management via SQLAlchemy

## Storage Configuration

- StorageService abstraction for file operations
- Local filesystem storage for LOCAL_WINDOWS (V1)
- Methods: store_file, read_file, delete_file, file_exists, get_file_size
- Directory management: create_directory, delete_directory
- Path resolution with resolve_path()
- Ready for future object storage (S3/Azure/GCS) without code changes

## Browser/API Separation

- API process does NOT auto-start Playwright browser
- Browser only starts when explicitly called via DiscoveryService
- Clear separation between API process and browser worker
- RuntimeContext controls browser automation support
- LOCAL_WINDOWS: browser automation supported
- CLOUD: browser automation disabled (future remote browser)
- Safe for future cloud architecture with separate browser worker

## Frontend API Configuration

- Environment-based backend URL via VITE_API_BASE_URL
- Development: http://127.0.0.1:8000/api (default)
- Production: https://<hosted-api>/api (configurable)
- No hardcoded localhost in production frontend code
- Frontend build passes TypeScript compilation
- Frontend build: 267.10 kB JS, 28.43 kB CSS

## Security Considerations

- CORS origins configured, no wildcard in production
- Error responses don't expose stack traces or internal details
- Logging redacts sensitive information automatically
- Configuration properties don't expose API keys or secrets
- API responses never return credentials or sensitive configuration
- No filesystem paths in API responses
- No environment variables in API responses
- No secrets in logs or error messages

## Testing

- Comprehensive production configuration tests (32 new tests)
- Tests for environment separation, CORS, health/readiness, error handling
- Tests for database configuration, storage configuration, browser/API separation
- Total: 401 tests passing
- Frontend build: PASSED (TypeScript compilation successful)

## Remaining Cloud Deployment Work

This checkpoint prepared the backend for production hosting but did NOT implement:

- Actual cloud deployment (Railway, Render, AWS, Azure)
- PostgreSQL production database provisioning
- Object storage provisioning (S3/GCS/Azure Blob)
- Cloud browser worker implementation
- 24/7 Naukri automation
- Docker deployment
- Kubernetes deployment

These belong to future Phase 8 checkpoints.

---

# END OF MASTER PRD
