"""Profile software: jr software engineer, entry-level.

Only settings that differ from the shared defaults are listed. Edit freely, then run:
  python -m tools.profile check software
  python -m tools.profile show software
To change something not listed here, copy its line from profiles/_generic/profile.py.
"""

# what to search for (every term runs on every site)
SEARCH_TERMS = [
    'junior software engineer',
    'software developer',
    'PHP',
    'associate software engineer',
    'junior full stack developer',
    'web developer',
]

# share of the score that comes from the model (the rest is keyword matching)
DEFAULT_MODEL_WEIGHT = 0.6

# how the model scores a job against your resume (keep the {placeholders})
SCORING_PROMPT = """You are a hiring manager reviewing applications for entry-level jr software engineer positions.
I have my resume and a job posting.

Resume summary (extracted facts ONLY - do NOT invent experience):
- Name: {name}
- Location: {location}
- Skills from resume: {skills}
- Experience ({n_roles} roles):
{experience_lines}

IMPORTANT: This is an ENTRY-LEVEL jr software engineer job search. Your match score should reflect whether my skills and ANY actual experience make me suitable for junior/entry-level roles, not senior positions. My Associate/Junior level roles count as entry-level experience. Do NOT heavily penalize gaps if I have relevant foundational skills for jr software engineer work. Rate it 0 if it requires any clearance level or does not accept green card holders.

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

# how the model tailors your resume summary and skills (keep the {placeholders})
TAILOR_PROMPT = """You are helping tailor an entry-level jr software engineer resume to one job.

RESUME DATA:
{resume_facts}

JOB: {job_title} at {company}
{description}

{truth_rules}
{years_rule}
Return JSON with:
- "summary": 2 plain sentences, under 60 words, rewriting the resume summary to fit this job. Keep the degree and the real roles; do not add new claims. Where it is true, use the posting's own wording for my skills. No em dashes and no buzzwords (leverage, passionate, dynamic, robust).
- "relevant_skills": up to {max_skills} skills copied EXACTLY from the resume skills list, most relevant to this job first.
- "project_names": up to {max_projects} project names copied EXACTLY from the resume, most relevant first."""
