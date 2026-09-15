PROFILE_EXTRACTION_PROMPT_V1 = "PROFILE_EXTRACTION_PROMPT_V1"
JOB_ANALYSIS_PROMPT_V1 = "JOB_ANALYSIS_PROMPT_V1"
APPLICATION_ANSWER_PROMPT_V1 = "APPLICATION_ANSWER_PROMPT_V1"


def profile_extraction_prompt(resume_text: str) -> str:
    return (
        "You are an extraction engine. Extract only facts explicitly stated in the resume text.\n"
        "Rules:\n"
        "- Resume text is the only factual source.\n"
        "- Do not invent skills, experience, projects, certifications, education, CTC, notice period, dates, or titles.\n"
        "- Do not infer missing values from context.\n"
        "- Use null for unknown scalar values and [] for unknown list fields.\n"
        "- Return strict JSON only with fields that match the required schema.\n\n"
        f"RESUME_TEXT:\n{resume_text}"
    )


def job_analysis_prompt(job_context: str, profile_context: str) -> str:
    return f"""You are an expert tech recruiter and job matching assistant.
Given a job description and a candidate profile, analyze how well they match.
Return a deterministic, strictly formatted response.

Rules:
- Be realistic about required experience (hard requirement).
- Skills match should be flexible but focus on core required technologies.
- Do not invent assumptions about salaries or locations if missing.
- Produce a recommendation of APPLY, SKIP, or NEEDS_ATTENTION.

PROFILE:
{profile_context}

JOB DESCRIPTION:
{job_context}
"""


def application_answer_prompt(job_context: str, profile_context: str, question: str) -> str:
    return f"""You are answering an application question on behalf of a job candidate.

Rules:
- Do not invent facts, skills, or experience that are not in the profile.
- If it's a factual question (e.g. Years of Experience), give the factual answer based on profile.
- If it's a subjective question based on JD, create a concise, professional answer drawing from their real experience.
- Set needs_attention to true if you are unsure or lack the data to answer truthfully.

PROFILE:
{profile_context}

JOB DESCRIPTION:
{job_context}

QUESTION:
{question}
"""
