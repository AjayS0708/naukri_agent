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
