# Job Scraper

Finds jobs, scores how well each one fits your resume using a **local** LLM (Ollama), works out how compatible
you are with each posting, writes a tailored resume and cover letter for the ones worth applying to (including jobs
outside your usual field), and lists them in a CSV you can click through. If you want, it also fills in the
applications in visible browser windows for you to review and submit. Everything runs on your own machine. Nothing
is sent to a cloud model.

```
python main.py                       (semi-auto: this is all you need)
   scrape (LinkedIn, Indeed)
   -> filter by title / company rules
   -> fetch LinkedIn descriptions (and applicant counts)
   -> filter by years of experience required and by number of applicants
   -> skip reposts (duplicate detection)
   -> score with the local model, blend with a keyword score, apply your calibration
   -> compatibility % (rough, and detailed for jobs at or above MIN_SCORE)
   -> save to SQLite
   -> write a tailored resume + cover letter (.docx) for every job at or above MIN_SCORE
      (standard, bridge or boilerplate, picked per job from its compatibility %)
   -> add each job to profiles/<name>/applications.csv
   -> print a summary of what's new and what needs you

python apply_jobs.py                 (full-auto: a separate command you run on purpose)
   -> find the employer's application link, check the posting is still open
   -> open up to PARALLEL_JOBS browser windows, each with its documents attached
   -> fill the form, then STOP (it never clicks Submit)
```

**Status:** scraping, filtering, duplicate detection, profiles (one per kind of job search), scoring, per-profile
calibration, compatibility percentages, three tailoring modes with bridge lines, the applications CSV, the summary,
application tracking and form filling (Greenhouse, Lever, Ashby, Workday, and a generic filler for other employer
sites) are built. The form fillers were tested on mock pages; check each kind on a real job before trusting it.
LinkedIn Easy Apply and Indeed's own forms are **not** supported (see [Not built yet](#not-built-yet)).

---

## Setup

**Requirements:** Python 3.10+, [Ollama](https://ollama.com) running locally.

```powershell
pip install -r requirements.txt
python -m playwright install chromium      # one time, only for apply_jobs.py (BROWSER in config/apply_settings.py)
ollama pull qwen2.5:7b                     # or any model you prefer
```

**Choose the model.** Set `OLLAMA_MODEL` in `config/settings.py` (default `qwen2.5:7b`). The `OLLAMA_MODEL`
environment variable overrides it for one PowerShell window only (`$env:OLLAMA_MODEL = "qwen3.5:4b"`). If the name
doesn't match something in `ollama list`, every model call fails with `model ... not found (404)`.

**Create a profile and fill in its resume.** Each profile has its own `resume.json`; there is no shared fallback.

```powershell
python -m tools.profile new NAME         # guided setup; writes profiles\NAME\profile.py
# then copy profiles\_generic\resume.json to profiles\NAME\resume.json and fill it in
python -m tools.profile check NAME       # validate it without running anything
```

**Run `python -m tools.check_setup`** to check the files, imports, settings, Ollama, the browser, the database and
git. Add `--quick` to skip Ollama, the browser and the database. It changes nothing.

**Log in once for applying:** `python apply_jobs.py --login` opens the browser on LinkedIn's sign-in page. Log in by
hand, then press Enter in the terminal. The login is kept in the browser profile folder; the code never sees a
password. (`--login indeed` does the same for Indeed.)

---

## Everyday use

Pick the profile once per PowerShell window, or pass `--profile NAME` to any command:

```powershell
$env:JOB_PROFILE = "software"
```

**Semi-auto (default): the program scrapes, scores, works out compatibility and makes documents; you apply by hand.**

```powershell
python main.py                    # scrape -> filter -> score -> compat -> documents -> CSV -> summary
python -m tools.summary           # what's new and what needs you
python -m tools.show_jobs         # browse scored jobs, with compatibility and missing requirements
```

Open `profiles\<name>\applications.csv`, click through the jobs, apply, and write anything in the `status` column
(applied, rejected, interview...).

**Full-auto: the bot fills the forms and stops before Submit.**

```powershell
python main.py
python apply_jobs.py --list       # which jobs can be filled, and which can't and why
python apply_jobs.py --top 0      # find employer links without opening any forms
python apply_jobs.py --top 3      # fill 3 forms; review each, submit by hand, answer "a"
python -m tools.csv_sync          # copy applied / closed from the database into the CSV
python -m tools.summary
```

Both flows check the database **and** the CSV, so a job is never handled twice (see
[Applications CSV](#applications-csv)).

**Now and then:**

```powershell
python -m tools.rating            # hand-rate 20 jobs to tune the scores (do this early)
python -m tools.rescore --yes     # score stored jobs again after changing a prompt, the model or the resume
python -m tools.stats             # what's working: funnel, score vs outcome, breakdowns, trends
python -m tools.track             # where each application stands
python -m tools.check_setup       # is everything in place?
```

Every command and flag is listed in `CMDLIST.md`.

Runs are **resumable and cheap to repeat**: each job is saved the moment it is scored, jobs already scored, filtered
or marked duplicate are skipped (matched by `job_url`), and Ctrl-C loses nothing. The search itself runs every time,
but only new jobs cost description fetching and model time. Jobs whose scoring failed, or that had no description
yet, are retried on the next run.

---

## Profiles

One profile per kind of job search (software, IT support, accounting...). Each has its own search terms, prompts,
filters, keyword lists, resume, documents, scores, ratings and calibration.

```
profiles\
  _generic\            template and sample resume to copy
  software\
    profile.py         only the settings that differ from config\
    resume.json        this profile's resume (required; there is no fallback)
    applications\      generated resumes and cover letters, one folder per job
    applications.csv   your click-through list
data\                  shared: the database, backups, reports, learned_answers.json
```

- **Choosing one:** `--profile NAME` on the command line, the `JOB_PROFILE` environment variable, or `DEFAULT_PROFILE`
  in `config/settings.py`. Every command takes `--profile`.
- **Managing them:**
  ```powershell
  python -m tools.profile list           # every profile, with its resume and data status
  python -m tools.profile new NAME       # guided setup; can generate the prompts for your field
  python -m tools.profile show NAME      # what it changes, and where each value comes from
  python -m tools.profile check NAME     # validate it (prompts fill in, patterns compile, resume exists)
  python -m tools.profile rename OLD NEW # move the folder and keep its scores, ratings and history
  ```
- **Extending:** `EXTENDS = "software"` in a profile.py lists only the differences from one parent. Several parents
  aren't supported yet. Lists and prompts are replaced whole, not merged.
- **What a profile can't change:** machine-wide settings (database, browser, scraping speed, timeouts, parallel
  jobs...). `python -m tools.profile check NAME` tells you if a profile tries.
- **Per profile:** scores (`job_scores`), hand ratings, calibration and application folders. A job scraped once is
  stored once and scored separately by each profile. **Shared:** the jobs themselves, application tracking
  (`applications`, `tracking`) and `learned_answers.json`.

---

## How it works

### Filters (`core\filters.py`)

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

### Scoring (`core\scorer.py`, `core\calibration.py`)

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

### Compatibility percentage (`core\compat.py`)

Each scored job gets two numbers:

- **Rough:** matched skills against gaps (quick, but inflated, because easy generic terms count as much as hard ones).
- **Detailed** (jobs at or above `MIN_SCORE`, when `COMPAT_DETAIL` is on): the model only reads the posting and lists
  its requirements; **code** then checks each against your resume, so the result is repeatable. Each requirement is
  yes (100%), partial (50%) or no (0%); required items weigh 1, preferred items 0.5.
- **Hard requirement cap:** if a required item of kind clearance, work authorization or license/certification is
  missing, the detailed percentage is capped at `HARD_REQ_CAP` (60). A missing degree never caps it.

The missing requirements are listed in `tools.show_jobs`, in each application's `notes.txt`, and the percentages show
in `tools.summary`. Add synonyms to `SKILL_ALIASES` in `config/keywords.py` to improve matching. Jobs scored before
this feature have no percentage until `python -m tools.rescore --yes`.

### Documents (`documents\application_maker.py`)

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

---

## Applications CSV

`profiles\<name>\applications.csv` is the list you click through. One row per job that has documents:

`date, title, company, location, score, compat_pct, mode, job_url, folder, status`

- Rows are only ever appended, and a job already in the file is never added again. A job in the CSV is never
  redone, even if you delete its folder; delete its row to redo it.
- `status` is yours. Write anything (applied, rejected, interview, skip). **Any non-blank status counts as handled**,
  so auto-apply skips that job.
- A job that has a folder but no CSV row (made before the CSV existed) gets its row added on the next run, with the
  mode left blank.
- The compat column is the detailed percentage, or the rough one if there is no detailed one.
- Close the file in Excel before a run, or the new rows are added on the next run. `CSV_LOG = False` turns the CSV off;
  `CSV_LOG_PATH` moves it.
- `python -m tools.csv_sync` (`--dry-run` to look first) fills **blank** `status` cells with `auto-applied` or `closed`
  for jobs the database knows the bot applied to or found closed. A status you typed is never changed.
- Documents are not made for jobs that are already in the CSV, that the bot applied to, or that it found closed.

---

## Tracking applications and results

`apply_jobs.py` logs an application as soon as you answer `a` (I submitted it). Everything after that is recorded
with `tools.track`. Stages: `applied` -> `screening` -> `interview` -> `offer`, or an ending: `rejected`, `ghosted`,
`withdrawn`.

```powershell
python -m tools.track                          # active applications (same as: list)
python -m tools.track list --all               # include rejected / ghosted / withdrawn
python -m tools.track list --stale 14          # applied 14+ days ago with no answer
python -m tools.track show acme                # stage history, contact, dates, notes
python -m tools.track add acme --date 11/03    # you applied outside the tool
python -m tools.track interview acme --date 11/12 --note "technical, 45 min"
python -m tools.track note acme "Decision by Friday"
python -m tools.track contact acme --name "Sam Lee" --email sam@acme.com
python -m tools.track followup acme +7         # reminder in 7 days
python -m tools.track sync                     # start tracking jobs already marked "applied"
```

A job can be named by its `#`, its URL, or part of the company or title. Dates accept `2026-11-09`, `11/09`, `today`,
`tomorrow` and `+7`. Due follow-ups and applications with no answer for 14+ days appear under "NEEDS YOU" in
`tools.summary`.

```powershell
python -m tools.stats                          # all time
python -m tools.stats --days 30
python -m tools.stats --section funnel,score   # funnel | score | breakdown | trends
```

Funnel: scraped -> scored -> good matches -> applied -> heard back -> interview -> offer. Score vs outcome shows answer
and interview rates by score band. With only a handful of applications the percentages are noisy; `tools.stats` says so.

`tools.summary` shows what's new, the best matches, how many jobs are ready to apply to and why the rest can't be, and
what needs you. `main.py` prints it at the end of every run (`SUMMARY_AFTER_RUN`). It only reads the database;
`--html` also saves a report under `data\reports\`.

---

## Applying (`apply_jobs.py`)

Opens each application in a visible browser window, attaches this job's resume and cover letter (making them first
if needed), fills every field it has an answer for, and **stops before Submit**. You review and send each one. It never
asks for, reads or stores a password.

```powershell
python apply_jobs.py --list                         # which top jobs can be filled, and which can't and why
python apply_jobs.py --top 3                        # fill the 3 best
python apply_jobs.py --url "<job url>"              # one job already in the database
python apply_jobs.py --min-score 6 --days 30        # change who qualifies for this run
python apply_jobs.py --parallel 1                   # one window at a time, with your real browser profile
python apply_jobs.py --include-opened               # also offer jobs you opened but didn't finish
python apply_jobs.py --set-url "<job url>" "<employer application url>"   # give a link by hand
python apply_jobs.py --recheck-links                # search again for jobs marked "no link found"
python apply_jobs.py --login                        # log in to LinkedIn by hand, once (or: --login indeed)
```

Defaults for count and age come from `config\apply_settings.py`; the score cutoff is `MIN_SCORE`. Jobs with a status in
`applications.csv` are never offered (naming one with `--url` still works).

**Several at once.** The terminal where you ran the command only shows a short summary. Up to `PARALLEL_JOBS`
applications open at once, each in its own terminal window and its own browser window, using a temporary copy of your
saved browser profile (one profile can't be open in two browsers at once). In each window, check the form, fix what is
listed under NEEDS YOUR ATTENTION, press Submit yourself, then answer `a` (I submitted it), `s` (skip for good) or
Enter (not yet). Because the copies are deleted afterwards, an account you create on a site inside one of these windows
(a Workday account, for example) is not kept: create it once with `python apply_jobs.py --url <job> --parallel 1`.

### Which sites get filled

| Kind | How |
|---|---|
| Greenhouse, Lever, Ashby | Fills the form on the page |
| Workday | Walks the wizard: "Autofill with Resume", each page, Save and Continue where nothing needs you, stops at Review. Needs an account per employer: the first time, the tool pauses so you sign in or create it |
| Generic (`generic.py`) | iCIMS, Taleo, SuccessFactors, SmartRecruiters, Workable, BambooHR, Jobvite, Breezy, Recruitee, Oracle, UKG, Paylocity, ADP, JazzHR, Rippling, Teamtailor, and **any other employer career page**. Best effort: presses Apply if the form isn't on the page, pauses when the site asks you to sign in, clicks only Next / Continue (`GENERIC_AUTO_ADVANCE`, at most `GENERIC_MAX_STEPS` pages), and stops when only Submit / Finish / Review is left |
| Job boards (ZipRecruiter, Glassdoor...) | Skipped: not application pages. Use `--set-url` with the employer's link |
| LinkedIn Easy Apply, Indeed's own forms | Not supported |

Every filler pauses when a page has fields that need you instead of moving on. Each site type is a switch in
`ENABLED_SITES`.

### Finding the employer's link

Most jobs come from LinkedIn, which hides the employer's link from logged-out visitors. In order, the tool tries:

1. **The link saved at scrape time** (`apply_url`), or the job's own URL when it is already a supported application page.
2. **Reading the LinkedIn Apply button.** With the saved, logged-in browser profile it opens the job page and reads the
   button's address, which wraps the employer's URL. It only works for jobs whose Apply button is an external link;
   "Easy Apply" jobs are recognized and skipped. It runs when `LINKEDIN_CLICK_APPLY = True`, is capped at
   `LINKEDIN_CLICK_MAX` jobs per run, pauses `LINKEDIN_CLICK_DELAY` seconds between jobs, and stops at the first login
   wall. `python apply_jobs.py --top 0` runs just this step. LinkedIn forbids automation, so keep it low volume.
3. **The company's public job board** (`applying\ats_lookup.py`), when `AUTO_FIND_LINKS = True`. It looks for the same
   job on the company's public Greenhouse, Lever or Ashby board and returns nothing when it isn't sure.
4. **By hand** with `--set-url`.

Whatever it finds is saved once per job. Jobs with no link are marked "none" and not searched again until you run
`--recheck-links`.

### Checks before a job is offered

- **Still open:** `CHECK_STILL_OPEN` checks the posting is still live (Greenhouse, Lever, Ashby and Workday job APIs,
  LinkedIn's public page, or the page text) and records closed ones as `closed` so they aren't offered or given
  documents again. An unclear result counts as open. Scripts, styles and comments in a page are ignored when looking
  for "no longer accepting applications" text.
- **Already handled:** a job with an application row (applied, skipped, closed) or a `status` in the CSV is skipped.

### Answering questions

Rules in `config\answers.py` (filled from `resume.json`), then answers you typed before (`data\learned_answers.json`,
shared by all profiles), then long "why us?" questions drafted by the local model (read them; they're flagged), then
it asks you in the terminal and remembers the answer. Gender, race, veteran and disability questions are answered
"decline" by default. Legal attestations, signatures and consent checkboxes are **never** filled for you. A required
field that no rule can fill is listed under "NEEDS YOUR ATTENTION".

### Diagnostics

```powershell
python -m applying.check_linkedin_page <linkedin job url>            # what the Apply button is, and what the tool would do
python -m applying.ats_lookup "Company" "Job title" "City, ST"       # look for the job on the company's public board
```

`check_linkedin_page` prints a `Decision:` line (`direct`, `easy`, `apply` or `none`) and the visible buttons. It saves a
screenshot, which can show your Messaging dock, so look before sharing it.

---

## Settings (the `config/` folder)

**Every editable setting lives in `config/`, and a profile can override most of them.** `profiles\<name>\resume.json`
is the one exception. The code reads these files when it starts, so restart a running script after editing.

| File | What's in it |
|---|---|
| `config/settings.py` | `DEFAULT_PROFILE`, `MIN_SCORE`; file locations; what to search (`SITES`, `SEARCH_TERMS`, `LOCATION`, `RESULTS_WANTED`, `HOURS_OLD`); the model, timeouts and temperatures; scraping delays and rate-limit backoff; document options (`MAKE_DOCS`, `MAX_DOCS_PER_RUN`, `DOC_WINDOW_DAYS`, `MAX_PROJECTS`, `FONT`, greeting and sign-off); file name templates; score blending and rating options (`DEFAULT_MODEL_WEIGHT`, `MIN_RATINGS`, `FULL_TRUST_RATINGS`); compatibility (`COMPAT_DETAIL`, `HARD_REQ_CAP`, `HARD_REQ_KINDS`); tailoring (`TAILOR_MODE`, `TAILOR_AUTO_BRIDGE_BELOW`, `TAILOR_AUTO_BOILERPLATE_BELOW`, `MAX_BRIDGE_LINES`); the CSV (`CSV_LOG`, optional `CSV_LOG_PATH`); summary options; the applicant filter (`MAX_APPLICANTS`, `KEEP_UNKNOWN_APPLICANTS`) |
| `config/apply_settings.py` | which jobs to apply to (`APPLY_MAX_PER_RUN`, `APPLY_WINDOW_DAYS`); `ENABLED_SITES`; the browser (`BROWSER`, `BROWSER_PROFILE_DIR`, `HEADLESS`, `SLOW_MO_MS`, `PAGE_TIMEOUT_MS`); `PARALLEL_JOBS`; `CHECK_STILL_OPEN`; Workday and generic limits; link finding (`AUTO_FIND_LINKS`, `LINKEDIN_CLICK_*`); answers (`ASK_ABOUT_UNKNOWN`, `DRAFT_FREE_TEXT`, `FREE_TEXT_MAX_WORDS`, `LEARNED_ANSWERS_FILE`) |
| `config/answers.py` | the rules that answer form questions from `resume.json`, and `NEVER_ANSWER` |
| `config/filter_rules.py` | senior-title words, staffing agencies to skip, `MAX_MIN_YEARS`, clearance / citizenship patterns |
| `config/keywords.py` | `SKILL_ALIASES` and `COMMON_TERMS` for keyword matching; optional `CASE_SENSITIVE_TERMS` |
| `config/job_notes.py` | the special notes (contract, part-time, travel, on-call, sponsorship...) flagged in rating cards |
| `config/writing_style.py` | the tailoring, cover-letter, bridge and boilerplate prompts, style rules, truthfulness rules, and the AI-phrasing patterns to catch |
| `config/prompts.py` | the prompts the model scores jobs and extracts requirements with |
| `config/profile_loader.py` | picks and applies the active profile (not a settings file) |

Prompts are Python format strings with `{placeholders}` (listed in a comment above each one). A typo gives an error
that names the file, the prompt and the allowed placeholders. Setting precedence: `config/` defaults, then the
profile's parent, then the profile.

### Console colors

Colors only appear in a terminal, never when `NO_COLOR` is set. `CONSOLE_COLOR` in `config/settings.py` forces them on or off, and `CONSOLE_LINKS` controls the clickable "open posting" link (otherwise the full URL is shown).

To change a color:

1. `python -m core.console --colors` lists the color names (add `all` for the numbers 0-255).
2. In `config/settings.py`, edit `CONSOLE_COLORS` (parts of the output) or `CONSOLE_TAG_COLORS` (the `[TAG]` labels). A value is a name, a number 0-255, or `"#rrggbb"`. `"auto"` (suitability, compat) means green / yellow / gray by how high the number is.
3. `python -m core.console` prints a sample of every kind of output so you can check the result without running the pipeline.

A line you delete from either dictionary falls back to its default. A profile can override them like any other setting.

The job block starts with a header: title, then company and location, then `suitability` (the 0-10 score), `compat` (the detailed percentage; the rough one only when there is no detailed one), the site, the documents mode and the pay. A hard requirement you don't meet is shown as `✗ blocker` under it. The lines below only add what the header doesn't say: `about`, `requires`, `has`, `gaps`, `notes` and the link. A requirement you're missing is listed once, under `gaps`.

---

## Project layout

```
job_scraper\
  main.py  apply_jobs.py
  README.md  CMDLIST.md  requirements.txt  .gitignore
  config\       every editable setting, and the profile loader
  profiles\     one folder per profile (profile.py, resume.json, applications\, applications.csv); _generic is the template
  db\           models, session, repo, queries, ratings, calibrations, tracking, migrate
  core\         scraper, filters, scorer, calibration, compat, dedupe, job_info, job_status, csv_log
  documents\    application_maker
  applying\     ats, ats_lookup, form_filler, answering, workday, generic, linkedin_resolver, worker, check_linkedin_page
  tools\        profile, show_jobs, summary, rescore, rating, stats, track, clear, check_setup, csv_sync
  data\         jobs_db.sqlite, backups\, reports\, archived_applications\, apply_runs\, learned_answers.json
  browser_profile\   the browser's saved logins (name depends on BROWSER_PROFILE_DIR)
```

Files in `core\`, `db\`, `applying\`, `documents\` and `tools\` are libraries or run as modules from the project root,
for example `python -m tools.show_jobs`. Only `main.py` and `apply_jobs.py` run as scripts.

### `resume.json`

```
name, contact {email, phone, location, github, gitlab}, work_authorization, availability, summary,
skills [...], certifications [{name, date, credential_id | url}], education [{degree, school, years}],
experience [{role, company, years, bullets [...], description}],
projects [{name, url, bullets [...], description, skills [...]}]
```

Optional: `legal_name` (used for "legal name" fields); `interests` and `transferable_experience` (lists of short
phrases; bridge lines may use them, and anything written there is treated as a true fact about you). Use a location
like `Norfolk, VA` (city, then state): a form's state field is filled from the second part. Only list things that are
true; documents and form answers are built only from this file.

### Database (`data\jobs_db.sqlite`, SQLAlchemy over SQLite)

| Table | Holds |
|---|---|
| `profiles` | one row per profile |
| `jobs` | the scraped posting, stored once (`job_url` is unique), with `apply_url`, `salary`, `is_duplicate` |
| `job_scores` | one row per job and profile: status (`scored`, `scoring_failed`, `filtered`), final `match_score` (`-1` = failed, `0` = rejected), `model_score`, `keyword_score`, `compat_pct`, `compat_detail_pct`, `compat_missing`, `compat_capped`, `matched_skills`, `gaps` |
| `ratings`, `calibrations` | your hand ratings and every fit of the score blend, per profile |
| `applications` | one row per job you opened to apply: `applied`, `skipped`, `opened` or `closed` |
| `tracking`, `tracking_events` | application stage, contact, dates and notes, and the history behind `tools.stats` |

Older databases are upgraded automatically (new columns are added on start). `python -m db.migrate` copies a database
from the old single-table layout into this one without changing the old file.

---

## Troubleshooting

- **`[PROFILE] No profile named ...` / `has no resume at ...`:** run `python -m tools.profile list`, create the profile
  with `python -m tools.profile new NAME`, and copy `profiles\_generic\resume.json` to `profiles\NAME\resume.json`.
- **`model 'xxx' not found (404)`:** Ollama doesn't have that model. Run `ollama list`, then set `OLLAMA_MODEL` in
  `config/settings.py` to a name it shows, or `ollama pull` the one you want. An environment variable set in one
  PowerShell window is gone in the next.
- **Stuck on "Scoring job 1" or `timed out`:** the model call is slow or hanging. Check `ollama list` and that the Ollama
  app is running. A timed-out job is saved as failed and retried next run (`python -m tools.rescore --failed-only`).
- **The model is slow / running on the CPU:** run `ollama ps`. If it says CPU, quit Ollama completely (tray icon) and
  start it again; it only detects the GPU at startup.
- **No descriptions / many jobs skipped / HTTP 429:** LinkedIn is rate limiting. The scraper backs off and stops after
  repeated 429s. Wait a while, lower `LINKEDIN_RESULTS_WANTED`, search fewer terms, or run `main.py` less often.
- **Indeed returns odd results or errors:** remove `"indeed"` from `SITES`.
- **Fewer jobs than expected:** the applicant filter may be skipping them (look for `[FILTER] ... applicants` lines), or
  they are already in the CSV. Raise `MAX_APPLICANTS` or set it to `None`.
- **No new documents for a job:** it is already in `applications.csv`, has a folder, was applied to or closed, or scores
  below `MIN_SCORE`. Delete its CSV row (and folder) to redo it.
- **`[CSV] Could not write ...`:** the CSV is open in Excel. Close it; the rows are added on the next run.
- **No compatibility percentage on a job:** it was scored before the feature, or scored below `MIN_SCORE` (only the
  rough one is computed). Run `python -m tools.rescore --yes`.
- **`ModuleNotFoundError` or "cannot import name":** run `python -m tools.check_setup`. Config settings were renamed
  (`DOC_MIN_SCORE`, `APPLY_MIN_SCORE`, `SUMMARY_MIN_SCORE` are now `MIN_SCORE`).
- **`ModuleNotFoundError: docx`:** `pip install python-docx` (not `docx`).
- **`playwright` is not recognized:** use `python -m playwright install chromium`.
- **The browser says the profile is in use:** another window is still open on that profile. Close it.
- **Error naming a file in `config\`:** a prompt or file-name template has a typo. The message lists the placeholders
  you can use.
- **Scores don't look right:** run `python -m tools.rating --report`; weak agreement with you means the prompt or model
  needs work, not just the blend.
- **"employer link not looked up yet" or "none" for a LinkedIn job:** run `python apply_jobs.py --login` once, then
  `python apply_jobs.py --recheck-links`. If a job still isn't found, run
  `python -m applying.check_linkedin_page <job url>` and read its `Decision:` line. `easy` means Easy Apply, which
  can't be filled.
- **Apply opened but fields are empty:** the site may use a custom form. Check "NEEDS YOUR ATTENTION" and add a rule to
  `config\answers.py` for any question it asks about repeatedly.

---

## Not built yet

- "Why low" reasons under low-scoring jobs (for example "requires PhD", "requires secret clearance")
- Several parents for a profile (`EXTENDS = ["a", "b"]`); the `--profile` lookup still reads `sys.argv` instead of a
  settings lookup
- `tools.profile check` doesn't validate the compatibility, bridge and boilerplate prompts; the generic profile template
  doesn't list `COMPAT_DETAIL`, `HARD_REQ_CAP`, `TAILOR_MODE`, `MAX_BRIDGE_LINES` or the CSV settings
- Showing only the detailed compatibility percentage (the rough one is still shown beside it); a command that fills
  compatibility for old jobs without re-scoring them; an ignore list for vague requirements such as "gain hands-on
  technical expertise"
- A cover-letter warning for "-ing" significance phrases
- Filling LinkedIn Easy Apply and Indeed's own forms; finding the employer link for Indeed jobs
- Showing the applicant count in `tools.show_jobs` and `tools.summary` (it isn't stored in the database)
- Tracking by email (outcomes are entered by hand with `tools.track`, or in the CSV)
- PDF export (documents are `.docx`)
- Scheduled runs (Windows Task Scheduler can run `python main.py` for you)
- Automated tests (the fillers were checked on mock pages only)

## Privacy

`data\` (database, reports, learned answers), `profiles\*\resume.json`, `profiles\*\applications\`,
`profiles\*\applications.csv` and the browser profile folders hold your personal details and logins. Keep them out of any
public repository. The `.gitignore` should list `data/`, `browser_profile*/`, `profiles/*/resume.json` (with
`!profiles/_generic/resume.json`), `profiles/*/applications/`, `profiles/*/applications.csv`, `*.sqlite` and
`__pycache__/`; keep the repository **private**. Run `python -m tools.check_setup` before you push: its last section
lists any private file that git tracks. If a private file was ever pushed, deleting it later does not remove it from
older commits, so a public repository can still expose it.