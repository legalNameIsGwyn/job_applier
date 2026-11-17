"""Compatibility percentage: how much of a posting your resume covers.

Two numbers are worked out so you can compare them:

  rough     free. matched_skills / (matched_skills + gaps) from the scoring call. Computed for every scored job.
  detailed  one extra model call. The model only READS THE POSTING and lists its requirements (required or
            preferred). It never sees your resume. This file then checks each requirement against your resume
            in plain code, so the same resume and posting always give the same answer. Only for jobs at or above
            MIN_SCORE (switch it off with COMPAT_DETAIL = False).

The detailed percentage is capped at HARD_REQ_CAP when the posting REQUIRES something in HARD_REQ_KINDS
(clearance, work authorization, a license or certification) that your resume doesn't show. A degree is
counted in the percentage but never caps it. Requirements the resume doesn't cover are listed as "missing".

Nothing here changes the 0-10 match score; it only adds the percentages and the missing list.
"""

import re

import config.keywords as _keywords
from config.prompts import COMPAT_PROMPT
from config.settings import (
    COMPAT_DETAIL, DESCRIPTION_CHARS_SCORING, HARD_REQ_CAP, HARD_REQ_KINDS, MIN_SCORE, SCORING_TEMPERATURE,
)

KINDS = ("skill", "experience", "education", "clearance", "work_authorization", "license_or_certification", "other")
MAX_REQUIREMENTS = 20
_MET_VALUE = {"yes": 1.0, "partial": 0.5, "no": 0.0}

COMPAT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "required": {"type": "boolean"},
                },
                "required": ["text", "kind", "required"],
            },
        }
    },
    "required": ["requirements"],
}


# ------------------------------------------------------------------------------------ rough


def rough_pct(matched, gaps) -> float | None:
    """Share of (matched skills + gaps) that are matched, 0-100. None when the model listed neither."""
    m, g = len(matched or []), len(gaps or [])
    return round(100 * m / (m + g), 1) if m + g else None


# --------------------------------------------------------------------------------- detailed


# Words that say nothing about WHICH skill is asked for. They are ignored when matching a requirement.
_STOP = frozenset("""a an the and or of in on at to for with within using use used via by from as into per
experience experienced knowledge ability able skills skill understanding familiarity familiar proficiency proficient
strong solid good excellent working work worked development developing develop tools tool technologies technology
systems system environment environments methodologies methodology processes process related relevant plus years year
minimum preferred required requirement requirements preferably including include includes etc other similar
operating operate operations operation framework frameworks hands handson hand have has be is are will""".split())
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.]*[a-z0-9+#]|[a-z0-9]")


def _stem(token: str) -> str:
    """Crude, applied to both sides, so 'testing', 'tested' and 'tests' meet in the middle."""
    if not token.isalpha():
        return token
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _words(text: str) -> list[str]:
    return [t.strip(".") for t in _TOKEN.findall((text or "").lower().replace("\u2019s", "").replace("'s", ""))]


def _significant(text: str) -> list[str]:
    """The words of a requirement that actually name something (stemmed, no duplicates, order kept)."""
    seen, out = set(), []
    for w in _words(text):
        if w in _STOP or (len(w) < 2 and w not in ("c", "r")):
            continue
        w = _stem(w)
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _resume_text(resume: dict) -> str:
    """Everything the resume says, plus the aliases of your skills (config/keywords.py), as one lowercase string."""
    aliases = getattr(_keywords, "SKILL_ALIASES", {})
    parts = [resume.get("summary", ""), resume.get("work_authorization", "")]
    for skill in resume.get("skills", []):
        parts += [skill] + list(aliases.get(skill, []))
    for e in resume.get("experience", []):
        parts += [e.get("role", ""), e.get("company", ""), e.get("description", "")] + list(e.get("bullets", []))
    for p in resume.get("projects", []):
        parts += [p.get("name", ""), p.get("description", "")] + list(p.get("bullets", [])) + list(p.get("skills", []))
    parts += [c.get("name", "") for c in resume.get("certifications", [])]
    for ed in resume.get("education", []):
        parts += [ed.get("degree", ""), ed.get("school", "")]
    if resume.get("education"):
        parts.append("degree")   # "Bachelor of Science" is a degree even though the word isn't written
    parts += list(resume.get("transferable_experience", []))
    return " ".join(str(p) for p in parts if p).lower()


def _as_bool(value) -> bool:
    return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "yes", "1")


def clean_requirements(raw) -> list[dict]:
    """Whatever the model sent -> [{"text", "kind", "required", "met": None}]. Unreadable items and repeats are dropped."""
    items = raw.get("requirements") if isinstance(raw, dict) else raw
    out, seen = [], set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text", "")).split())
        if not text:
            continue
        key = frozenset(_significant(text)) or text.lower()
        if key in seen:
            continue
        seen.add(key)
        kind = str(item.get("kind", "other")).strip().lower().replace(" ", "_")
        out.append({"text": text[:120], "kind": kind if kind in KINDS else "other",
                    "required": _as_bool(item.get("required", True)), "met": None})
    return out[:MAX_REQUIREMENTS]


def judge(req: dict, resume: dict, text: str | None = None, have: set | None = None) -> str | None:
    """Does the resume show this requirement? "yes", "partial", "no", or None when the wording names nothing to check.

    Clearance, work authorization and the other hard kinds have their own rules. Everything else compares the
    requirement's key words with the resume: 60% or more found is "yes", a real overlap is "partial", the rest "no".
    """
    text = _resume_text(resume) if text is None else text
    have = {_stem(w) for w in _words(text)} if have is None else have
    low = req["text"].lower()

    if req["kind"] == "clearance":
        return "yes" if "clearance" in text else "no"
    if req["kind"] == "work_authorization":
        auth = str(resume.get("work_authorization", "")).lower()
        if "citizen" in low:
            return "yes" if "citizen" in auth and "green" not in auth else "no"
        return "yes" if any(w in auth for w in ("authorized", "citizen", "green card", "permanent resident")) else "no"

    words = _significant(req["text"])
    if not words:
        return None
    found = sum(1 for w in words if w in have)
    share = found / len(words)
    if share >= 0.6:
        return "yes"
    # One stray word in a longer requirement ("design" in "Model-Based Design") isn't a partial match, but
    # finding one item of a comma-separated list ("Linux, Windows, WSL2, Docker") is.
    if found >= 2 or share >= 0.5 or (found and "," in req["text"]):
        return "partial"
    return "no"


def judge_all(reqs: list[dict], resume: dict) -> list[dict]:
    """Set "met" on every requirement; requirements with nothing checkable in them are dropped."""
    text = _resume_text(resume)
    have = {_stem(w) for w in _words(text)}
    out = []
    for r in reqs:
        met = judge(r, resume, text, have)
        if met is not None:
            out.append({**r, "met": met})
    return out


def is_hard(req: dict, hard_kinds=None) -> bool:
    return bool(req["required"]) and req["kind"] in (HARD_REQ_KINDS if hard_kinds is None else hard_kinds)


def detailed_result(reqs: list[dict], cap: float = HARD_REQ_CAP, hard_kinds=None) -> dict | None:
    """{"detail_pct", "missing", "capped"} from cleaned requirements, or None when there were none.

    Required requirements count 1, preferred ones 0.5. "yes" earns the full weight, "partial" half, "no" nothing.
    """
    if not reqs:
        return None
    weights = [1.0 if r["required"] else 0.5 for r in reqs]
    earned = sum(w * _MET_VALUE[r["met"]] for w, r in zip(weights, reqs))
    pct = 100 * earned / sum(weights)

    blockers = [r for r in reqs if is_hard(r, hard_kinds) and r["met"] == "no"]
    capped = bool(blockers) and pct > cap
    if capped:
        pct = float(cap)

    missing = [{"text": r["text"], "hard": is_hard(r, hard_kinds), "required": r["required"]}
               for r in reqs if r["met"] == "no"]
    missing.sort(key=lambda m: (not m["hard"], not m["required"]))   # hard blockers, then required, then preferred
    return {"detail_pct": round(pct, 1), "missing": missing, "capped": capped}


def _ask_model(prompt: str) -> dict:
    from core.scorer import MODEL, client, extract_json   # imported here so the maths above works without Ollama
    args = dict(model=MODEL, messages=[{"role": "user", "content": prompt}], format=COMPAT_SCHEMA,
                options={"temperature": SCORING_TEMPERATURE})
    try:
        response = client.chat(think=False, **args)
    except TypeError:   # older ollama package without the think argument
        response = client.chat(**args)
    return extract_json(response.message.content)


def detailed(job: dict, resume: dict | None = None, ask=None) -> dict | None:
    """The detailed check for one job. `ask(prompt) -> dict` is the model call (a stand-in in tests)."""
    if resume is None:
        from core.scorer import load_resume
        resume = load_resume()
    values = dict(job_title=job.get("title", ""), company=job.get("company", ""),
                  description=(job.get("description") or "")[:DESCRIPTION_CHARS_SCORING],
                  max_requirements=MAX_REQUIREMENTS)
    try:
        prompt = COMPAT_PROMPT.format(**values)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"COMPAT_PROMPT in config/prompts.py has a problem ({e!r}). "
                         f"Allowed placeholders: {', '.join('{' + k + '}' for k in values)}. "
                         "Write a literal brace as {{ or }}.") from None
    return detailed_result(judge_all(clean_requirements((ask or _ask_model)(prompt)), resume))


# --------------------------------------------------------------------------------- the entry point


def compute(job: dict, score: dict, final_score: float, resume: dict | None = None, ask=None) -> dict:
    """Everything save_job(compat=...) needs. All four keys are always present, so a re-score replaces old values.

    job:         title, company, description
    score:       the scorer's result (matched_skills, gaps)
    final_score: the calibrated 0-10 score; jobs below MIN_SCORE get only the rough percentage
    """
    out = {"pct": None, "detail_pct": None, "missing": [], "capped": False}
    if final_score <= 0:    # auto-rejected or failed: nothing to measure
        return out
    out["pct"] = rough_pct(score.get("matched_skills"), score.get("gaps"))
    if COMPAT_DETAIL and final_score >= MIN_SCORE:
        try:
            result = detailed(job, resume, ask)
            if result:
                out.update(result)
        except Exception as e:   # the extra check must never cost a job its score
            print(f"[COMPAT] Detailed check skipped for '{job.get('title', '')[:40]}': {e}")
    return out


# ----------------------------------------------------------------------------- text for display


def compat_label(job: dict) -> str:
    """'72% rough / 58% detailed (capped)' from a job dict (queries.get_jobs), or '' when there is none."""
    parts = []
    if job.get("compat_pct") is not None:
        parts.append(f"{job['compat_pct']:g}% rough")
    if job.get("compat_detail_pct") is not None:
        parts.append(f"{job['compat_detail_pct']:g}% detailed" + (" (capped)" if job.get("compat_capped") else ""))
    return " / ".join(parts)


def describe(result: dict) -> str:
    """The same label from compute()'s result, for the line printed while scoring."""
    return compat_label({"compat_pct": result.get("pct"), "compat_detail_pct": result.get("detail_pct"),
                         "compat_capped": result.get("capped")})


def missing_label(job: dict) -> str:
    """'[HARD] Security clearance; Kubernetes' from a job dict, or '' when nothing is missing."""
    items = [m for m in (job.get("compat_missing") or []) if isinstance(m, dict) and m.get("text")]
    return "; ".join(("[HARD] " if m.get("hard") else "") + m["text"] for m in items)
