"""Local Job Scorer - Scores job postings against a resume using local Ollama models.

Settings live in config/: the model and timeouts in settings.py, the clearance rules in
filter_rules.py, and the prompt in prompts.py.
"""

import functools
import json
import logging
import re

import ollama

from config.filter_rules import BLOCKER_PATTERNS, NO_BLOCKER_PATTERN
from config.prompts import SCORING_PROMPT
from config.settings import (
    DESCRIPTION_CHARS_SCORING, OLLAMA_MODEL, REQUEST_TIMEOUT_SECONDS, RESUME_FILE, SCORING_TEMPERATURE,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL = OLLAMA_MODEL

# A stuck request raises after REQUEST_TIMEOUT_SECONDS instead of hanging forever;
# main.py records it as a failed job and moves on.
client = ollama.Client(timeout=REQUEST_TIMEOUT_SECONDS)

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "match_score": {"type": "number"},
        "matched_skills": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["match_score", "matched_skills", "gaps"],
}


@functools.lru_cache(maxsize=1)
def load_resume() -> dict:
    """Load resume data from JSON file (cached after the first read)."""
    with open(RESUME_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def blocked_reason(title: str, description: str) -> str | None:
    """Return a reason if the posting needs clearance / US citizenship, else None."""
    text = f"{title}\n{description}".lower()
    no_clearance = re.search(NO_BLOCKER_PATTERN, text)
    for pattern in BLOCKER_PATTERNS:
        if no_clearance and "citizen" not in pattern:
            continue    # "no clearance required" cancels clearance rules only, never citizenship
        for m in re.finditer(pattern, text):
            if re.match(r"[^.\n]{0,40}?:\s*(no|false|n/?a)\b", text[m.end():m.end() + 50]):
                continue    # "US Citizenship Required for this Position: No"
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
    experience_lines = "\n".join(
        f"    * {e.get('role', '')} at {e.get('company', '')} ({e.get('years', '')}): "
        f"{e.get('description', '')}"
        for e in experience
    )

    values = dict(
        name=resume.get("name", ""),
        location=resume.get("contact", {}).get("location", "Remote"),
        skills=", ".join(resume.get("skills", [])),
        n_roles=len(experience),
        experience_lines=experience_lines,
        job_title=job_title,
        company=company,
        job_location=location,
        description=description[:DESCRIPTION_CHARS_SCORING],
    )
    try:
        prompt = SCORING_PROMPT.format(**values)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(
            f"SCORING_PROMPT in config/prompts.py has a problem ({e!r}). "
            f"Allowed placeholders: {', '.join('{' + k + '}' for k in values)}. "
            "Write a literal brace as {{ or }}."
        ) from None

    chat_args = dict(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=SCORE_SCHEMA,  # forces the output shape
        options={"temperature": SCORING_TEMPERATURE},
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
