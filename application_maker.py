"""Generate a tailored resume and cover letter (.docx) for scored jobs.

The local Ollama model only chooses WHAT to emphasize (summary wording, skill
order, which projects to show) and writes the cover letter body. Everything
else (employers, titles, dates, education, bullet text) is copied verbatim from
resume.json, so the resume cannot contain invented experience.

Usage (from the project folder):
    python application_maker.py --top 5                  # best 5 jobs scoring >= 6
    python application_maker.py --top 10 --min-score 7 --days 3
    python application_maker.py --url https://www.linkedin.com/jobs/view/123...
    python application_maker.py --top 5 --force          # regenerate existing ones

Output goes to the applications folder (APPLICATIONS_DIR in config/settings.py), one
subfolder per job: a resume, a cover letter and notes.txt (job link plus anything to
double-check). The file and folder names are built from your resume.json name and the job;
see the file-name templates in config/settings.py. Always read the cover letter before sending it.
"""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

import config.keywords as _keywords
from config.keywords import COMMON_TERMS, SKILL_ALIASES
from config.settings import (
    APPLICATION_FOLDER, APPLICATIONS_DIR, COVER_LETTER_FILENAME, COVER_LETTER_GREETING, COVER_LETTER_SIGN_OFF,
    DESCRIPTION_CHARS_WRITING, FONT, MAX_PROJECTS, NOTES_FILENAME, RESUME_FILENAME, TAILOR_MAX_SKILLS,
    WRITING_TEMPERATURE,
)
from config.writing_style import (
    LETTER_AUTHORIZATION_RULE, LETTER_AVAILABILITY_CLAUSE, LETTER_KEYWORD_RULE, LETTER_PROMPT, LETTER_STRUCTURE,
    LETTER_WARN_WORDS, SLOP_PATTERNS, STYLE_RULES, TAILOR_PROMPT, TRUTH_RULES,
)
from db import DB_PATH
from scorer import MODEL, client, extract_json, load_resume
from show_jobs import get_jobs

OUTPUT_DIR = Path(APPLICATIONS_DIR)

TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "relevant_skills": {"type": "array", "items": {"type": "string"}},
        "project_names": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "relevant_skills", "project_names"],
}

LETTER_SCHEMA = {
    "type": "object",
    "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
    "required": ["paragraphs"],
}

# ------------------------------------------------------------------ writing style
# Plain, specific writing without the usual AI tells. Rules go into the prompt,
# then clean_style() fixes mechanical tells and slop_flags() catches the rest.

# STYLE_RULES and SLOP_PATTERNS are edited in config/writing_style.py


def clean_style(text: str) -> str:
    """Fix mechanical AI tells: curly quotes and em/en dashes."""
    text = (text.replace("‘", "'").replace("’", "'")
                .replace("“", '"').replace("”", '"'))
    text = re.sub(r"\s*[—–]\s*", ", ", text)  # em dash / en dash -> comma
    return re.sub(r"\s+", " ", text).strip()


def slop_flags(text: str) -> list[str]:
    """Return 'category: matched text' for each AI-sounding pattern found."""
    flags = []
    for label, pattern in SLOP_PATTERNS.items():
        for m in re.finditer(pattern, text, re.I):
            flags.append(f"{label}: \"{m.group(0).strip()}\"")
    return flags


# ------------------------------------------------------------- keyword matching
# ATS software and AI screeners look for the posting's own terms. This finds which
# of YOUR real skills the posting mentions (so they can be listed first and used in
# the letter) and which common terms it asks for that you don't have. Nothing is ever
# added to the resume from here; it only reorders and reports.

# SKILL_ALIASES and COMMON_TERMS are edited in config/keywords.py


# Terms that are also ordinary English words ("go above and beyond", "swift response"). They only
# count when written exactly as given. Add more in config/keywords.py (CASE_SENSITIVE_TERMS).
CASE_SENSITIVE_TERMS = set(getattr(_keywords, "CASE_SENSITIVE_TERMS", ("Go", "Swift")))


def _term_regex(term: str) -> re.Pattern:
    flags = 0 if term in CASE_SENSITIVE_TERMS else re.I
    return re.compile(r"(?<![A-Za-z0-9+#.])" + re.escape(term) + r"(?![A-Za-z0-9+#])", flags)


def matched_skills(job_text: str, skills: list[str]) -> list[str]:
    """Resume skills the posting mentions, most-mentioned first (ties: earliest in the posting)."""
    hits = []
    for skill in skills:
        starts = set()  # unique positions, so a skill that equals its own alias isn't counted twice
        for term in [skill] + SKILL_ALIASES.get(skill, []):
            starts.update(m.start() for m in _term_regex(term).finditer(job_text))
        if starts:
            hits.append((-len(starts), min(starts), skill))
    return [s for _, _, s in sorted(hits)]


def missing_terms(job_text: str, resume: dict) -> list[str]:
    """Common terms the posting uses that no skill, alias or project on the resume covers."""
    have = " ".join(resume.get("skills", []) + [t for p in resume.get("projects", []) for t in p.get("skills", [])])
    return [t for t in COMMON_TERMS if _term_regex(t).search(job_text) and not _term_regex(t).search(have)]


# --------------------------------------------------------------------------- LLM


def _ask(prompt: str, schema: dict) -> dict:
    args = dict(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=schema,
        options={"temperature": WRITING_TEMPERATURE},
    )
    try:
        response = client.chat(think=False, **args)
    except TypeError:  # older ollama package without the think argument
        response = client.chat(**args)
    return extract_json(response.message.content)


def _pick(valid: list[str], requested: list, limit: int | None = None) -> list[str]:
    """Keep only requested items that really exist in `valid` (case-insensitive), deduplicated."""
    canon = {v.lower(): v for v in valid}
    out: list[str] = []
    for item in requested or []:
        name = canon.get(str(item).strip().lower())
        if name and name not in out:
            out.append(name)
    return out[:limit] if limit else out


def unsupported_numbers(text: str, *sources: str) -> list[str]:
    """Numbers in `text` that appear in none of the sources (a sign of invented metrics)."""
    haystack = " ".join(sources)
    found = re.findall(r"\d+(?:[.,]\d+)?%?", text)
    return sorted({n for n in found if n not in haystack})


def _fill(template_name: str, template: str, **values) -> str:
    """Fill a prompt template from config/writing_style.py; explain clearly if it has a typo."""
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(
            f"{template_name} in config/writing_style.py has a problem ({e!r}). "
            f"Allowed placeholders: {', '.join('{' + k + '}' for k in values)}. "
            "Write a literal brace as {{ or }}."
        ) from None


def _resume_facts(resume: dict) -> str:
    """Compact, duplicate-free view of the resume for prompts (and for number checking)."""
    facts = {
        "summary": resume.get("summary", ""),
        "work_authorization": resume.get("work_authorization", ""),
        "availability": resume.get("availability", ""),
        "skills": resume.get("skills", []),
        "experience": [
            {
                "role": e.get("role"),
                "company": e.get("company"),
                "years": e.get("years"),
                "details": e.get("bullets") or sentences(e.get("description", "")),
            }
            for e in resume.get("experience", [])
        ],
        "projects": [
            {
                "name": p["name"],
                "details": p.get("bullets") or [p.get("description", "")],
                "tech": p.get("skills", []),
            }
            for p in resume.get("projects", [])
        ],
        "certifications": [{"name": c["name"], "date": c.get("date")} for c in resume.get("certifications", [])],
        "education": resume.get("education", []),
    }
    return json.dumps({k: v for k, v in facts.items() if v}, indent=1)


def tailor_resume(job: dict, resume: dict) -> dict:
    """Ask the model how to emphasize the resume for this job, then validate its choices."""
    prompt = _fill(
        "TAILOR_PROMPT", TAILOR_PROMPT,
        resume_facts=_resume_facts(resume), job_title=job["title"], company=job["company"],
        description=(job.get("description") or "")[:DESCRIPTION_CHARS_WRITING],
        truth_rules=TRUTH_RULES, max_skills=TAILOR_MAX_SKILLS, max_projects=MAX_PROJECTS,
    )
    raw = _ask(prompt, TAILOR_SCHEMA)

    summary = clean_style(str(raw.get("summary", "")))
    allowed = _resume_facts(resume) + " " + job["title"] + " " + (job.get("description") or "")
    if not (30 <= len(summary) <= 450) or unsupported_numbers(summary, allowed) or slop_flags(summary):
        summary = resume.get("summary", "")  # fall back to the original, always safe

    skills = _pick(resume.get("skills", []), raw.get("relevant_skills"), TAILOR_MAX_SKILLS)
    project_names = _pick([p["name"] for p in resume.get("projects", [])], raw.get("project_names"), MAX_PROJECTS)
    job_text = f"{job['title']}\n{job.get('description') or ''}"
    keyword_hits = matched_skills(job_text, resume.get("skills", []))

    # Top up to MAX_PROJECTS with the projects whose tech overlaps the posting's keywords most
    def overlap(p: dict) -> int:
        return len(set(p.get("skills", [])) & set(keyword_hits))

    for p in sorted(resume.get("projects", []), key=overlap, reverse=True):
        if len(project_names) >= MAX_PROJECTS:
            break
        if p["name"] not in project_names:
            project_names.append(p["name"])

    # Skill order: skills the posting itself mentions (exact keyword matches) first,
    # then the model's picks, then everything else. Every skill is kept.
    ordered: list[str] = []
    for s in keyword_hits + skills + resume.get("skills", []):
        if s not in ordered:
            ordered.append(s)
    return {"summary": summary, "skills": ordered, "project_names": project_names}


def _parse_letter(raw: dict) -> list[str]:
    """Clean the model's paragraphs: drop greetings/sign-offs, fix punctuation, reject placeholders."""
    paragraphs = []
    for p in raw.get("paragraphs", []):
        p = clean_style(str(p))
        if p and not re.match(r"(dear|sincerely|best regards|regards)\b", p, re.I):
            paragraphs.append(p)
    if len(paragraphs) < 2:
        raise ValueError("model returned no usable cover letter paragraphs")
    if re.search(r"\[[^\]]+\]", " ".join(paragraphs)):
        raise ValueError("cover letter contained a [placeholder]")
    return paragraphs


def write_cover_letter(job: dict, resume: dict) -> tuple[list[str], list[str]]:
    """Return (body paragraphs, warnings). Greeting and sign-off are added in code."""
    job_text = f"{job['title']}\n{job.get('description') or ''}"
    keywords = matched_skills(job_text, resume.get("skills", []))[:6]
    keyword_rule = _fill("LETTER_KEYWORD_RULE", LETTER_KEYWORD_RULE, keywords=", ".join(keywords)) if keywords else ""
    auth = resume.get("work_authorization")
    availability_clause = (
        _fill("LETTER_AVAILABILITY_CLAUSE", LETTER_AVAILABILITY_CLAUSE, availability=resume["availability"].lower())
        if resume.get("availability") else ""
    )
    authorization_rule = (
        _fill("LETTER_AUTHORIZATION_RULE", LETTER_AUTHORIZATION_RULE,
              work_authorization=auth, availability_clause=availability_clause)
        if auth else ""
    )
    prompt = _fill(
        "LETTER_PROMPT", LETTER_PROMPT,
        name=resume["name"], resume_facts=_resume_facts(resume), job_title=job["title"], company=job["company"],
        job_location=job.get("location", ""), description=(job.get("description") or "")[:DESCRIPTION_CHARS_WRITING],
        truth_rules=TRUTH_RULES, letter_structure=LETTER_STRUCTURE, keyword_rule=keyword_rule,
        authorization_rule=authorization_rule, style_rules=STYLE_RULES,
    )
    paragraphs = _parse_letter(_ask(prompt, LETTER_SCHEMA))

    # If the draft still sounds like AI, ask once more, naming exactly what to remove.
    flags = slop_flags(" ".join(paragraphs))
    if flags:
        retry = _ask(
            prompt + "\n\nYour previous draft used these patterns, so rewrite it without them: " + "; ".join(flags),
            LETTER_SCHEMA,
        )
        try:
            second = _parse_letter(retry)
            if len(slop_flags(" ".join(second))) < len(flags):
                paragraphs = second
        except ValueError:
            pass  # keep the first draft

    text = " ".join(paragraphs)
    warnings = []
    leftover = slop_flags(text)
    if leftover:
        warnings.append("Cover letter may still sound like AI writing (" + "; ".join(leftover) + "). Consider rewording.")
    allowed = _resume_facts(resume) + " " + job["title"] + " " + (job.get("description") or "")
    bad = unsupported_numbers(text, allowed)
    if bad:
        warnings.append(f"Cover letter mentions numbers not found in your resume or the job post: {', '.join(bad)}. Verify or remove.")
    if len(text.split()) > LETTER_WARN_WORDS:
        warnings.append("Cover letter is longer than expected; consider trimming.")
    return paragraphs, warnings


# ------------------------------------------------------------------- documents


def _style_doc(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.left_margin = section.right_margin = Inches(0.75)
    section.top_margin = section.bottom_margin = Inches(0.6)
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = Pt(10.5)


def _para(doc, text="", *, bold=False, size=None, align=None, after=2, before=0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.line_spacing = 1.05
    if align:
        p.alignment = align
    if text:
        run = p.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
    return p


def _heading(doc, text: str) -> None:
    p = _para(doc, text.upper(), bold=True, size=11, before=8, after=3)
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "808080")):
        bottom.set(qn(f"w:{k}"), v)
    border.append(bottom)
    p._p.get_or_add_pPr().append(border)


def _bullet(doc, text: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.05
    p.add_run(text)


def _title_line(doc, left: str, right: str, sub: str = "") -> None:
    p = _para(doc, after=0, before=3)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(7.0), WD_TAB_ALIGNMENT.RIGHT)
    p.add_run(left).bold = True
    if sub:
        p.add_run(f", {sub}")
    p.add_run(f"\t{right}")


def _header(doc, resume: dict) -> None:
    c = resume.get("contact", {})
    _para(doc, resume["name"], bold=True, size=20, align=WD_ALIGN_PARAGRAPH.CENTER, after=0)
    line = "  |  ".join(x for x in (c.get("email"), c.get("phone"), c.get("location")) if x)
    _para(doc, line, align=WD_ALIGN_PARAGRAPH.CENTER, after=0)
    links = "  |  ".join(
        f"{label}: {c[key]}" for label, key in (("GitHub", "github"), ("GitLab", "gitlab")) if c.get(key)
    )
    _para(doc, links, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)


def _set_metadata(doc: Document, resume: dict, title: str) -> None:
    """Replace python-docx's default author/title so the file's properties are yours."""
    props = doc.core_properties
    props.author = resume["name"]
    props.last_modified_by = resume["name"]
    props.title = title
    props.subject = ""
    props.comments = ""
    props.keywords = ""


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=\.)\s+", text.strip()) if s.strip()]


def build_resume(resume: dict, tailored: dict, path: Path) -> None:
    doc = Document()
    _style_doc(doc)
    _header(doc, resume)

    _heading(doc, "Summary")
    _para(doc, tailored["summary"])
    auth = resume.get("work_authorization")
    if auth and "authorized to work" not in tailored["summary"].lower():
        extra = f"Work authorization: {auth}."
        if resume.get("availability"):
            extra += f" Availability: {resume['availability']}."
        _para(doc, extra, before=2)

    _heading(doc, "Skills")
    _para(doc, ", ".join(tailored["skills"]))

    _heading(doc, "Experience")
    for e in resume.get("experience", []):
        _title_line(doc, e["role"], e.get("years", ""), e.get("company", ""))
        for s in e.get("bullets") or sentences(e.get("description", "")):
            _bullet(doc, s)

    projects = {p["name"]: p for p in resume.get("projects", [])}
    _heading(doc, "Projects")
    for name in tailored["project_names"]:
        p = projects[name]
        para = _para(doc, after=0, before=3)
        para.add_run(name).bold = True
        if p.get("url"):
            para.add_run(f"  ({p['url']})")
        for s in p.get("bullets") or [p.get("description", "")]:
            _bullet(doc, s)

    if resume.get("certifications"):
        _heading(doc, "Certifications")
        for c in resume["certifications"]:
            detail = f"Credential ID {c['credential_id']}" if c.get("credential_id") else c.get("url", "")
            _title_line(doc, c["name"], c.get("date", ""), detail)

    _heading(doc, "Education")
    for ed in resume.get("education", []):
        _title_line(doc, ed["degree"], ed.get("years", ""), ed.get("school", ""))

    _set_metadata(doc, resume, f"{resume['name']} - Resume")
    doc.save(path)


def build_cover_letter(resume: dict, job: dict, paragraphs: list[str], path: Path) -> None:
    doc = Document()
    _style_doc(doc)
    doc.styles["Normal"].font.size = Pt(11)
    _header(doc, resume)
    _para(doc, date.today().strftime("%B %d, %Y").replace(" 0", " "), before=10, after=8)
    _para(doc, "Hiring Team", after=0)
    _para(doc, job["company"], after=0)
    if job.get("location"):
        _para(doc, job["location"], after=10)
    _para(doc, COVER_LETTER_GREETING, after=8)
    for p in paragraphs:
        _para(doc, p, after=8)
    _para(doc, COVER_LETTER_SIGN_OFF, before=4, after=0)
    _para(doc, resume["name"])
    _set_metadata(doc, resume, f"{resume['name']} - Cover Letter")
    doc.save(path)


# ------------------------------------------------------------------------ driver


def _slug(text: str, limit: int = 30) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit] or "job"


def _safe(text: str) -> str:
    """Keep letters (any language), digits, '-', '_' and '.'; everything else becomes '_'."""
    return re.sub(r"[^\w.-]+", "_", text).strip("._") or "file"


def name_fields(resume: dict, job: dict | None = None) -> dict:
    """Values available to the file-name templates in config/settings.py."""
    words = resume["name"].split() or ["resume"]
    fields = {
        "name": _safe("_".join(words)),
        "first": _safe(words[0]),
        "last": _safe(words[-1]),
        "date": date.today().isoformat(),
    }
    if job:
        fields.update(
            company=_slug(job["company"]),
            title=_slug(job["title"]),
            hash=hashlib.md5((job.get("job_url") or job["title"]).encode()).hexdigest()[:6],
        )
    return fields


def render_name(template: str, fields: dict) -> str:
    """Fill a file-name template; a clear error if it uses a placeholder that doesn't exist."""
    try:
        return _safe(template.format(**fields))
    except KeyError as e:
        raise ValueError(
            f"Unknown placeholder {e} in a file-name template in config/settings.py. "
            f"Available: {', '.join('{' + k + '}' for k in fields)}"
        ) from None


def job_folder(job: dict, out_root: Path = OUTPUT_DIR) -> Path:
    return Path(out_root) / render_name(APPLICATION_FOLDER, name_fields(load_resume(), job))


def create_application(job: dict, out_root: Path = OUTPUT_DIR, force: bool = False) -> Path | None:
    """Create the resume, cover letter (.docx) and notes.txt for one job.

    Returns the folder, or None if it already existed (and force is False).
    """
    folder = job_folder(job, out_root)
    if folder.exists() and not force:
        print(f"[APPLY] Already exists, skipping: {folder.name}")
        return None

    resume = load_resume()
    # File names come from resume.json + the templates in config/settings.py. Render them first,
    # so a typo in a template fails immediately, before any model time is spent.
    fields = name_fields(resume, job)
    resume_file = f"{render_name(RESUME_FILENAME, fields)}.docx"
    letter_file = f"{render_name(COVER_LETTER_FILENAME, fields)}.docx"

    tailored = tailor_resume(job, resume)
    paragraphs, warnings = write_cover_letter(job, resume)

    is_new_folder = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        build_resume(resume, tailored, folder / resume_file)
        build_cover_letter(resume, job, paragraphs, folder / letter_file)
    except Exception:
        if is_new_folder:  # don't leave a half-built folder that later runs would treat as done
            shutil.rmtree(folder, ignore_errors=True)
        raise

    job_text = f"{job['title']}\n{job.get('description') or ''}"
    have = matched_skills(job_text, resume.get("skills", []))
    lacking = missing_terms(job_text, resume)
    letter_text = " ".join(paragraphs).lower()
    unused = [s for s in have[:6] if s.lower() not in letter_text]

    notes = [
        f"{job['title']} - {job['company']}",
        f"Location:    {job.get('location', '')}",
        f"Match score: {job.get('match_score', 'n/a')}",
        f"Apply here:  {job.get('job_url', '')}",
        "",
        "Keyword match (the posting's terms vs your real skills):",
        f"- On your resume and in the posting: {', '.join(have) or 'none found'}",
        f"- In the posting but NOT on your resume: {', '.join(lacking) or 'none of the common terms'}",
        "  (only add these to your resume if you really have them)",
        *([f"- Posting skills your letter doesn't mention: {', '.join(unused)}"] if unused else []),
        "",
        "Review before sending:",
        "- Read the cover letter; the model can be wrong or generic.",
        *[f"- WARNING: {w}" for w in warnings],
    ]
    (folder / NOTES_FILENAME).write_text("\n".join(notes) + "\n", encoding="utf-8")
    print(f"[APPLY] Created {folder}")
    for w in warnings:
        print(f"[APPLY]   WARNING: {w}")
    return folder


def get_job_by_url(url: str, db_path: str = DB_PATH) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT title, company, location, job_url, description, match_score FROM jobs WHERE job_url = ?",
            (url,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Generate tailored resumes and cover letters.")
    p.add_argument("--top", type=int, help="generate for the top N scored jobs")
    p.add_argument("--url", help="generate for one job already in the database")
    p.add_argument("--min-score", type=float, default=6, help="with --top: minimum score (default 6)")
    p.add_argument("--days", type=int, help="with --top: only jobs scraped in the last N days")
    p.add_argument("--force", action="store_true", help="regenerate even if the folder exists")
    args = p.parse_args()

    if args.url:
        job = get_job_by_url(args.url)
        if not job:
            raise SystemExit("That URL isn't in the database. Run main.py first.")
        jobs = [job]
    elif args.top:
        jobs = get_jobs(args.top, "top", min_score=args.min_score, days=args.days, include_zero=False)
    else:
        raise SystemExit("Use --top N or --url JOB_URL (see --help).")

    print(f"[APPLY] {len(jobs)} job(s), model: {MODEL}")
    made, failures = 0, 0
    for job in jobs:
        print(f"\n[APPLY] {job['title'][:50]} - {job['company'][:30]}")
        try:
            if create_application(job, force=args.force):
                made += 1
            failures = 0
        except Exception as e:
            failures += 1
            print(f"[APPLY] Failed: {e}")
            if failures >= 3:
                print("[APPLY] 3 failures in a row. Is Ollama running? Stopping.")
                break
    print(f"\n[APPLY] Done. {made} created in {OUTPUT_DIR}")