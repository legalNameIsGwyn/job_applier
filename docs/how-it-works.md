[← README](../README.md)

# How it works

## Filters (`core\filters.py`)

Cheap rules that skip jobs before they cost model time. Skipped jobs are saved with status `filtered` and the
reason, so they're never re-fetched. All the rules come from the active profile.

- **Title / company** (before descriptions are fetched): senior-level titles, Engineer III/IV/V, and staffing
  agencies (`SENIOR_TITLE_WORDS`, `LEVEL_SUFFIX_PATTERN`, `BLOCKED_COMPANIES`).
- **Experience** (needs the description): rejected only when *every* "N years of experience" requirement is above
  `MAX_MIN_YEARS`. "1-3 years" passes; "3+ years" doesn't.
- **Applicants** (needs the job page): LinkedIn jobs with more than `MAX_APPLICANTS` applicants are skipped.
  "Be among the first 25 applicants" counts as unknown, and `KEEP_UNKNOWN_APPLICANTS` decides whether those are kept.
  `MAX_APPLICANTS = None` turns it off.
- **Duplicates** (`core\dedupe.py`): the same posting listed twice (same title, and the same company and place, or
  nearly identical text) is saved with status `duplicate`, score 0, and left out of ratings, rankings and
  applications. `main.py` checks each new job; `python -m core.dedupe` cleans up what is already in the database
  (`--dry-run` to look first).
- **Hard blockers:** a security clearance or U.S. citizenship requirement is checked on the title in the pre-filter (for example
  "(w/ active Secret)"), so no description is downloaded for it, and again on the description right after it is downloaded, before any model call. The job is saved with status `blocked`, the reason and **no description**,
  and the log shows `[FILTER] Checking job` followed by `Removed: …` or `Accepted: …`. Jobs saved earlier can be re-checked
  with `python -m tools.check --blockers` (no model; it lists them first and asks).
- **Closed postings:** with `CHECK_AVAILABILITY` on, LinkedIn's page (downloaded anyway for the description) is read for "no longer accepting
  applications" wording; a closed job is saved with status `closed`, score 0 and no description. `CHECK_AVAILABILITY_OTHER_SITES` also asks Greenhouse,
  Lever, Ashby, Workday and other sites (one extra request per job; many sites just answer "unknown", which counts as open).
  If no description can be fetched (the site is not LinkedIn and sent none, or LinkedIn kept answering 429), the log says why, and the job is retried next run.
- **Saved jobs are re-checked too** (`core\availability.py`): after scoring, each run asks whether jobs that already have documents (rows in the CSV
  with a blank `status`) are still open. Skipped: jobs from this run's scrape, jobs you applied to, skipped or tracked, and jobs checked within
  `AVAILABILITY_RECHECK_DAYS` days. A closed one gets an `applications` row with status `closed` (score and documents stay) and `closed` in the CSV `status`.
  Every answer stamps `last_checked` (database and CSV). A job a site won't answer for is tried again next run, and with `AVAILABILITY_ASK = True` you are
  asked about it after the summary: each link opens in your browser and you answer open / closed / skip. `python -m tools.check --availability` does the
  same on demand, and `python -m tools.check --mark URL` marks a job closed by hand.
- **Drops after the detailed check:** a required item whose kind is in `DROP_ON_MISSING_KINDS` (default: clearance) that your
  resume doesn't show drops the job the same way (status `blocked`, no description). Licenses and certifications are only
  flagged as missing. Add `"work_authorization"` to `DROP_ON_MISSING_KINDS` in your profile to drop those too.

## Scoring (`core\scorer.py`, `core\calibration.py`)

1. **Hard rejects in code:** postings matching `BLOCKER_PATTERNS` (security clearance wordings such as "Secret-level clearance",
   "TS clearance", "Public Trust", "access to classified information"; and "U.S. citizen" wordings) score 0 without calling
   the model. The reason quotes the words that matched. They are skipped when the posting says "no clearance required", and a
   citizenship phrase that also says "or permanent resident / green card" is not treated as a blocker.
2. **Model score:** the local model rates the job 0-10 against your resume with the profile's `SCORING_PROMPT`,
   returning JSON (`match_score`, `matched_skills`, `gaps`) constrained by a schema. A failed job is recorded
   (score -1) and retried next run, or with `rescore --failed-only`. The run stops after
   `MAX_CONSECUTIVE_FAILURES` failures in a row.
3. **Keyword score:** 0-10 from how many of your skills the posting mentions versus common terms it asks for that
   you don't have (`SKILL_ALIASES`, `COMMON_TERMS`).
4. **Final score:** `a * (w * model + (1 - w) * keyword) + b`, clipped to 0-10. Before you rate anything the blend is
   `DEFAULT_MODEL_WEIGHT` model / the rest keywords. After you hand-rate jobs, `w`, `a` and `b` are fitted to your
   ratings. A model score of 0 always stays 0.
5. **One cutoff:** `MIN_SCORE` (default 5) decides who gets documents, a detailed compatibility check, a place in the
   summary and a place in the apply list.

**Calibration** (`python -m tools.rating`). It shows 20 unrated jobs spread across the score range, in shuffled order,
with the model's score hidden. Rate each 0-10 (`d` for the full posting, `s` to skip, `q` to stop; ratings save as you
go). Ratings add up: the tuning is re-fitted on the whole pool (at least `MIN_RATINGS`), pulled toward the defaults
until you reach `FULL_TRUST_RATINGS`, and every job's score is recomputed. Each profile keeps its own ratings and fits.
`--report` shows the current fit, `--latest-only` / `--all-ratings` choose what to fit on, `--rerate` goes back over
old ratings, `--reset` deletes this profile's ratings and fits (asks first).

## Compatibility percentage (`core\compat.py`)

Each scored job gets two numbers:

- **Rough:** matched skills against gaps (quick, but inflated, because easy generic terms count as much as hard ones).
- **Detailed** (jobs at or above `MIN_SCORE`, when `COMPAT_DETAIL` is on): the model only reads the posting and lists
  its requirements; **code** then checks each against your resume, so the result is repeatable. Each requirement is
  yes (100%), partial (50%) or no (0%); required items weigh 1, preferred items 0.5.
- **Hard requirement cap:** if a required clearance or work authorization is missing, the detailed percentage is capped at
  `HARD_REQ_CAP` (60). A missing degree, license or certification never caps it.
- **Licenses and certifications:** a required one that isn't in the `licenses` or `certifications` lists of `resume.json`
  is shown on its own `⚠ license` line (and as `[LICENSE]` in `tools.show_jobs`). It never drops the job or lowers the
  percentage, and document bridging skips it.

The missing requirements are listed in `tools.show_jobs`, in each application's `notes.txt`, and the percentages show
in `tools.summary`. Add synonyms to `SKILL_ALIASES` in `config/keywords.py` to improve matching. Jobs scored before
this feature have no percentage until `python -m tools.rescore --yes`.

## Documents (`documents\application_maker.py`)

`main.py` makes documents for every recent job at or above `MIN_SCORE` that has none yet (`DOC_WINDOW_DAYS`, and
`MAX_DOCS_PER_RUN`, where `None` means no limit). The model only chooses **emphasis**: it rewrites the summary, picks
the most relevant projects, and writes the cover letter body. Employers, titles, dates, education and bullet text
are copied verbatim from `resume.json`, so the resume can't contain invented experience. Skills and projects the model
returns are checked against your resume; unknown ones are dropped. Invented numbers in the letter are flagged and
AI-sounding phrasing is cleaned up or flagged (`config/writing_style.py`). The format is ATS-friendly: single column,
no tables or images, standard headings.

**Tailoring modes** (`TAILOR_MODE` in `config/settings.py`, or `--mode` on the command line):

| Mode | What you get | Used by `auto` when compatibility is |
|---|---|---|
| `standard` | The posting's wording applied to your real skills and projects | 70% or more |
| `bridge` | Also ties real experience to requirements you lack, one honest sentence each (up to `MAX_BRIDGE_LINES`) | 30% to 70% |
| `boilerplate` | Your resume exactly as written plus a short 2-paragraph letter from the job title, company and resume facts (the posting is deliberately not shown to the model) | under 30% |

`auto` (the default) uses the detailed percentage, falling back to the rough one, with the thresholds
`TAILOR_AUTO_BRIDGE_BELOW` and `TAILOR_AUTO_BOILERPLATE_BELOW`. Bridge lines must name a real source on the resume, may
not contain invented numbers or AI phrasing, and are never written for hard requirements (clearance, work authorization,
licenses). Anything you write under `transferable_experience` and `interests` in `resume.json` is treated as true.
The terminal shows `[APPLY] Mode: ...` and each `[BRIDGE]` line as it is added; `notes.txt` records the mode and the
bridge lines.

```powershell
python -m documents.application_maker --top 5                       # best 5 jobs scoring 6+
python -m documents.application_maker --url <job url>               # one job already in the database
python -m documents.application_maker --url <job url> --mode boilerplate --force
python -m documents.application_maker --url <job url> --mode bridge --suggest-bridges   # accept, edit or skip each bridge line first
python -m documents.application_maker --url <job url> --bridges-only                    # only show the proposed bridge lines
python -m documents.application_maker --top 5 --force               # regenerate existing ones
```

Output goes to `profiles\<name>\applications\<company>_<title>_<hash>\`: a resume and a cover letter (named from your
`resume.json`, e.g. `Jane_Doe_Resume.docx`) and `notes.txt` (job link, score, compatibility, missing requirements,
mode, bridge lines, which of the posting's keywords you do and don't have, and warnings to check before sending).
A job that already has a folder is skipped; `--force` rebuilds it. **Read every cover letter before sending it.** They
are drafts from a small local model.

**File names are dynamic** (templates in `config/settings.py`): `RESUME_FILENAME = "{name}_Resume"`,
`COVER_LETTER_FILENAME = "{name}_Cover_Letter"`, `APPLICATION_FOLDER = "{company}_{title}_{hash}"`. Placeholders:
`{name}`, `{first}`, `{last}`, `{company}`, `{title}`, `{hash}` and `{date}`. Keep `{hash}` in `APPLICATION_FOLDER` and
don't put `{date}` there: the folder name is how finished jobs are recognized.
