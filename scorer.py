"""Local Job Scorer - Scores job postings against a resume using local Ollama models."""

import functools
import json
import logging
import os
import re

import ollama

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fast non-reasoning model. Install with:  ollama pull qwen2.5:7b
# Override without editing code:  set OLLAMA_MODEL=deepseek-r1:7b
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# A stuck request raises after this many seconds instead of hanging forever;
# main.py records it as a failed job and moves on.
REQUEST_TIMEOUT_SECONDS = 180
client = ollama.Client(timeout=REQUEST_TIMEOUT_SECONDS)

RESUME_FILE = r"c:/Users/Gwyn/Desktop/Projects/job_scraper/resume.json"

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "match_score": {"type": "number"},
        "matched_skills": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["match_score", "matched_skills", "gaps"],
}

# Postings matching any of these are scored 0 without calling the model
# (small models apply the "rate it zero" prompt rule unreliably).
BLOCKER_PATTERNS = [
    r"security clearance",
    r"\bts\s*/\s*sci\b",
    r"top[- ]secret",
    r"secret clearance",
    r"active clearance",
    r"clearance (is )?required",
    r"polygraph",
    r"(u\.?s\.?|united states) citizen(ship)?\s+(is\s+)?(required|only)",
    r"must be (a )?(u\.?s\.?|united states) citizen",
    r"citizenship (is )?required",
    r"u\.?s\.? citizens? only",
]
NO_BLOCKER_PATTERN = (
    r"no (security )?clearance"
    r"|clearance (is )?not required"
    r"|not require (a )?(security )?clearance"
    r"|without (a )?clearance"
)


@functools.lru_cache(maxsize=1)
def load_resume() -> dict:
    """Load resume data from JSON file (cached after the first read)."""
    with open(RESUME_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def blocked_reason(title: str, description: str) -> str | None:
    """Return a reason if the posting needs clearance / US citizenship, else None."""
    text = f"{title}\n{description}".lower()
    if re.search(NO_BLOCKER_PATTERN, text):
        return None
    for pattern in BLOCKER_PATTERNS:
        if re.search(pattern, text):
            return "Requires clearance or US citizenship (auto-rejected)"
    return None


def normalize_score(raw: dict, default: float = 5) -> dict:
    """Always return match_score / matched_skills / gaps, whatever the model sent."""

    def as_list(v):
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)] if v else []

    try:
        score = float(raw.get("match_score", raw.get("score", default)))
    except (TypeError, ValueError):
        score = default

    return {
        "match_score": max(0.0, min(10.0, score)),
        "matched_skills": as_list(raw.get("matched_skills", raw.get("skills", []))),
        "gaps": as_list(raw.get("gaps", raw.get("key_gaps", []))),
    }


def extract_json(content: str) -> dict:
    """Pull the JSON object out of a model response (strips <think> blocks)."""
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()
    match = (
        re.search(r"```json\s*({.*?})\s*```", content, re.DOTALL)
        or re.search(r"({.*})", content, re.DOTALL)
    )
    if not match:
        raise ValueError("no JSON object found in model response")
    return json.loads(match.group(1))


def score_job(job_title: str, company: str, location: str, description: str) -> dict:
    """Score a job against the resume using Ollama.

    Returns: {"match_score": 0-10, "matched_skills": [...], "gaps": [...]}

    Raises if the model response can't be parsed, so the caller can record the
    failure instead of storing a made-up score.
    """
    description = description or ""

    reason = blocked_reason(job_title, description)
    if reason:
        return {"match_score": 0.0, "matched_skills": [], "gaps": [reason]}

    resume = load_resume()

    experience = resume.get("experience", [])
    has_associate_or_junior = any(
        "associate" in e.get("role", "").lower() or "junior" in e.get("role", "").lower()
        for e in experience
    )
    experience_lines = "\n".join(
        f"    * {e.get('role', '')} at {e.get('company', '')} ({e.get('years', '')}): "
        f"{e.get('description', '')}"
        for e in experience
    )

    prompt = f"""You are a hiring manager reviewing applications for ENTRY-LEVEL positions only.
    I have my resume and a job posting.

    Resume summary (extracted facts ONLY - do NOT invent experience):
    - Name: {resume.get('name', '')}
    - Location: {resume.get('contact', {}).get('location', 'Remote')}
    - Skills from resume: {', '.join(resume.get('skills', []))}
    - Experience ({len(experience)} roles):
{experience_lines}

    IMPORTANT: This is an ENTRY-LEVEL job search. Your match score should reflect whether my skills and ANY actual experience make me suitable for junior/entry-level roles, not senior positions. My Associate/Junior level roles count as entry-level experience. Do NOT heavily penalize gaps if I have relevant foundational skills like Python, Java, or JavaScript. Rate it 0 if it requires any clearance level or does not accept green card holders.

    Job title: {job_title}
    Company: {company}
    Location: {location}
    Description: {description[:2000]}

    Rate your match on a scale of 1-10. Provide:
    - A numeric score (1-10): Associate/Junior roles qualify you even at score 5
    - Which skills from my resume match this job (list them)
    - Any significant gaps I have compared to the job requirements

    Respond with JSON only, using exactly these keys:
    {{"match_score": <number 0-10>, "matched_skills": ["..."], "gaps": ["..."]}}"""

    chat_args = dict(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=SCORE_SCHEMA,  # forces the output shape
        options={"temperature": 0},
    )
    try:
        # think=False stops Qwen3-style models from "thinking" first, which is
        # slow and can stall when combined with a JSON schema constraint.
        response = client.chat(think=False, **chat_args)
    except TypeError:  # older ollama package without the think argument
        response = client.chat(**chat_args)

    raw = extract_json(response.message.content)
    if "match_score" not in raw and "score" not in raw:
        raise ValueError(f"model response had no score: {raw!r}")

    return normalize_score(raw)