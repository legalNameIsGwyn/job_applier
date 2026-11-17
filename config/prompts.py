"""The prompt the local model uses to score a job against your resume.

This is a Python format string. Placeholders in {braces} are filled in by the code:
    {name} {location} {skills} {n_roles} {experience_lines}
    {job_title} {company} {job_location} {description}
A literal brace must be doubled, as in the JSON example at the bottom: {{ and }}.
Keep the last paragraph: the code needs the model to answer with exactly those keys.
"""

SCORING_PROMPT = """You are a hiring manager reviewing applications for ENTRY-LEVEL positions only.
I have my resume and a job posting.

Resume summary (extracted facts ONLY - do NOT invent experience):
- Name: {name}
- Location: {location}
- Skills from resume: {skills}
- Experience ({n_roles} roles):
{experience_lines}

IMPORTANT: This is an ENTRY-LEVEL job search. Your match score should reflect whether my skills and ANY actual experience make me suitable for junior/entry-level roles, not senior positions. My Associate/Junior level roles count as entry-level experience. Do NOT heavily penalize gaps if I have relevant foundational skills like Python, Java, or JavaScript. Rate it 0 if it requires any clearance level or does not accept green card holders.

Job title: {job_title}
Company: {company}
Location: {job_location}
Description: {description}

Rate your match on a scale of 1-10. Provide:
- A numeric score (1-10): Associate/Junior roles qualify you even at score 5
- Which skills from my resume match this job (list them)
- Any significant gaps I have compared to the job requirements

Respond with JSON only, using exactly these keys:
{{"match_score": <number 0-10>, "matched_skills": ["..."], "gaps": ["..."]}}"""

COMPAT_PROMPT = """You are reading one job posting and listing what it asks for. You are not given any applicant's information; do not guess about one.

JOB: {job_title} at {company}
{description}

List the concrete requirements this posting states, at most {max_requirements}. For each one give:
- "text": the requirement in under 12 words, using the posting's own words
- "kind": skill, experience, education, clearance, work_authorization, license_or_certification, or other
- "required": true if the posting says must, required or minimum; false if it says preferred, nice to have or a plus

Only list what the posting actually states. Merge near-duplicates into one item.

Return JSON: {{"requirements": [{{"text": "...", "kind": "skill", "required": true}}]}}"""

from config.profile_loader import apply_overrides  # noqa: E402
apply_overrides(globals())