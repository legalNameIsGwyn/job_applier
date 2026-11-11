# Job Scraper

Finds entry-level jobs, scores how well each one fits your resume using a **local** LLM (Ollama),
writes a tailored resume and cover letter for the best matches, and fills in the applications in a
visible Firefox window for you to review and submit. Everything runs on your own machine. Nothing
is sent to a cloud model.

```
python main.py
   scrape (LinkedIn, Indeed)
   -> filter by title / company rules
   -> fetch LinkedIn descriptions (and applicant counts)
   -> filter by years of experience required and by number of applicants
   -> skip reposts (duplicate detection)
   -> score with the local model, blend with a keyword score, apply your calibration
   -> save to SQLite
   -> write a tailored resume + cover letter (.docx) for the best matches
   -> print a summary of what's new and what needs you

python apply_jobs.py
   -> find the employer's application link (read from the LinkedIn Apply button, or set by hand)
   -> check the posting is still open
   -> fill the form with your documents attached, then STOP (it never clicks Submit)
```

**Status:** scraping, filtering, duplicate detection, scoring, calibration, document generation, the
summary and form filling (Greenhouse, Lever, Ashby, Workday, and a generic filler for other
employer sites) are built. The form fillers were tested on mock pages; check each kind on a real job
before trusting it. LinkedIn Easy Apply and Indeed's own forms are **not** supported (see
[Not built yet](#not-built-yet)).

---

## Setup

**Requirements:** Python 3.10+, [Ollama](https://ollama.com) running locally.

```powershell
pip install -r requirements.txt
python -m playwright install firefox       # one time, for apply_jobs.py
ollama pull qwen2.5:7b                     # or any model you prefer
```

(`python -m playwright ...` works even when the `playwright` command isn't on your PATH.)

**Choose the model.** Set `OLLAMA_MODEL` in `config/settings.py` (the default is `qwen2.5:7b`). The
`OLLAMA_MODEL` environment variable overrides it for one PowerShell window only:

```powershell
$env:OLLAMA_MODEL = "qwen3.5:4b"
```

A new window forgets that, and the default applies again. If the name doesn't match something in
`ollama list`, every model call fails with `model ... not found (404)`. The scorer sends `think=False`
so "thinking" models (Qwen3 and similar) don't stall.

**Fill in `data\resume.json`.** It is the single source of truth for scoring, every generated
document and the form answers. See [resume.json](#resumejson).

**Run `python check_setup.py`** to check the files, imports, settings, Ollama, Firefox, the database and git. Add `--quick` to skip Ollama, the browser and the database. It changes nothing.

**Log in once for applying:** `python apply_jobs.py --login` opens Firefox on LinkedIn's sign-in page. Log in
by hand (including any verification), then press Enter in the terminal. The login is kept in the browser
profile folder; the code never sees a password.

---

## Everyday use

```powershell
python check_setup.py             # is everything in place and working?
python main.py                    # scrape -> filter -> score -> save -> make documents -> summary
python summary.py                 # what's new and what needs you
python show_jobs.py               # look at the results
python rating.py                  # hand-rate 20 jobs to tune the scores (do this early)
python apply_jobs.py --list       # what could be applied to
python apply_jobs.py --top 3      # fill the 3 best, review each one, submit by hand
python track.py                   # where each application stands
python stats.py                   # what's working
```

Every command and flag is listed in `CMDLIST.md`.

### Settings (the `config/` folder)

**Every editable setting lives in `config/`. `data\resume.json` is the one exception.** The code reads
these files when it starts, so restart a running script after editing.

| File | What's in it |
|---|---|
| `config/settings.py` | file locations (`RESUME_FILE`, `DB_PATH`, `CALIBRATION_FILE`, `APPLICATIONS_DIR`); what to search (`SITES`, `SEARCH_TERMS`, `LOCATION`, `RESULTS_WANTED`, `HOURS_OLD`); the model, timeouts and temperatures; scraping delays, `LINKEDIN_RESULTS_WANTED` and rate-limit backoff; document options (`MAKE_DOCS`, `DOC_MIN_SCORE`, `MAX_DOCS_PER_RUN`, `DOC_WINDOW_DAYS`, `MAX_PROJECTS`, `FONT`, greeting and sign-off); **file name templates**; score blending and rating options; summary options (`SUMMARY_AFTER_RUN`, `SUMMARY_DAYS`, `SUMMARY_TOP`, `SUMMARY_MIN_SCORE`, `SUMMARY_DIR`); the applicant filter (`MAX_APPLICANTS`, `KEEP_UNKNOWN_APPLICANTS`). Optional: `BACKUP_DIR`, `ARCHIVE_DIR` (used by `clear.py`) |
| `config/apply_settings.py` | which jobs to apply to (`APPLY_MIN_SCORE`, `APPLY_MAX_PER_RUN`, `APPLY_WINDOW_DAYS`); `ENABLED_SITES`; the browser (`BROWSER`, `BROWSER_PROFILE_DIR`, `HEADLESS`, `SLOW_MO_MS`, `PAGE_TIMEOUT_MS`); `CHECK_STILL_OPEN`; Workday (`WORKDAY_AUTO_ADVANCE`, `WORKDAY_MAX_STEPS`); generic sites (`GENERIC_AUTO_ADVANCE`, `GENERIC_MAX_STEPS`); link finding (`AUTO_FIND_LINKS`, `FIND_LINKS_MAX`, `LINKEDIN_CLICK_APPLY`, `LINKEDIN_CLICK_MAX`, `LINKEDIN_CLICK_DELAY`); answers (`ASK_ABOUT_UNKNOWN`, `DRAFT_FREE_TEXT`, `FREE_TEXT_MAX_WORDS`, `LEARNED_ANSWERS_FILE`) |
| `config/answers.py` | the rules that answer form questions from `resume.json`, and `NEVER_ANSWER` |
| `config/filter_rules.py` | senior-title words, staffing agencies to skip, `MAX_MIN_YEARS`, clearance / citizenship patterns |
| `config/keywords.py` | `SKILL_ALIASES` and `COMMON_TERMS` for keyword matching; optional `CASE_SENSITIVE_TERMS` (default `Go`, `Swift`, so "go above and beyond" doesn't count as the Go language) |
| `config/job_notes.py` | the special notes (contract, part-time, travel, on-call, sponsorship...) flagged in rating cards |
| `config/writing_style.py` | the resume-tailoring and cover-letter prompts, style rules, truthfulness rules, and the AI-phrasing patterns to catch |
| `config/prompts.py` | the prompt the model scores jobs with |

Prompts are Python format strings with `{placeholders}` (listed in a comment above each one). A typo gives an
error that names the file, the prompt and the allowed placeholders.

**Current configuration at a glance** (change any of these in `config/`):

| Setting | Value |
|---|---|
| Model | `qwen2.5:7b` |
| Sites / location | LinkedIn and Indeed, Norfolk, VA |
| Search terms | junior software engineer, software developer, python developer, associate software engineer |
| Per search | 50 results (LinkedIn capped at 15), jobs up to 72 hours old |
| Documents | made for jobs scoring 6+ from the last 7 days, at most 10 per run |
| Applying | jobs scoring 7+ from the last 14 days, at most 5 per run; Firefox; Greenhouse, Lever, Ashby, Workday and generic sites on; Indeed off |
| Link finding | reads LinkedIn Apply buttons (`LINKEDIN_CLICK_APPLY`, at most 10 per run, 8 to 20 seconds apart); company-board search off (`AUTO_FIND_LINKS = False`; set it to `True` to use `applying\ats_lookup.py`) |
| Applicant limit | skips LinkedIn jobs with more than 10 applicants (`MAX_APPLICANTS`); jobs with no count shown are kept |

Runs are **resumable and cheap to repeat**: each job is saved the moment it's scored, jobs already scored,
filtered or marked duplicate are skipped (matched by `job_url`), and Ctrl-C loses nothing. The search itself runs
every time, but only new jobs cost description fetching and model time. Jobs whose scoring failed, or that had no
description yet, are retried on the next run.

### `show_jobs.py`: view results

```powershell
python show_jobs.py                       # top 10
python show_jobs.py -n 5 --bottom         # 5 lowest scores
python show_jobs.py -n 20 --min-score 6 --days 3
python show_jobs.py --hide-zero           # hide auto-rejected / filtered jobs
python show_jobs.py --failed              # jobs whose scoring failed
python show_jobs.py -n 3 --full           # include descriptions
```

A score of 0 with the reason "Requires clearance or US citizenship" is the automatic reject; `--bottom` shows each job's reason.

### `summary.py`: what's new and what needs you

```powershell
python summary.py                  # last 24 hours, in the terminal
python summary.py --days 7
python summary.py --top 15 --min-score 6
python summary.py --html           # also save reports\summary_<date>.html and open it
```

It shows how many jobs are new (scored, filtered, duplicates, failed), the best new matches, how many jobs are
ready to apply to and why the rest can't be, and what needs you (failed scoring, unfinished applications, hand
ratings). `main.py` prints it at the end of every run, including runs that find nothing new (`SUMMARY_AFTER_RUN`).
It only reads the database.

### `rescore.py`: score stored jobs again

Use it after changing the model, the scoring prompt, `config/keywords.py`, the filter rules or `resume.json`, or to
retry jobs whose scoring failed. Nothing is scraped. Jobs that now match a filter rule (for example a staffing
agency you added) are filtered instead of scored.

```powershell
python rescore.py                  # every scored job (asks to confirm)
python rescore.py --failed-only    # only jobs whose scoring failed
python rescore.py --include-filtered
python rescore.py -n 20            # at most 20 jobs
python rescore.py --url <job_url>  # one job
python rescore.py --yes            # don't ask
```

### `documents\application_maker.py`: resume + cover letter

`main.py` runs this automatically for the best recent jobs. To run it yourself (as a module, from the project root):

```powershell
python -m documents.application_maker --top 5                   # best 5 jobs scoring 6+
python -m documents.application_maker --top 10 --min-score 7 --days 3
python -m documents.application_maker --url <job_url>           # one job already in the database
python -m documents.application_maker --top 5 --force           # regenerate existing ones
```

Output goes to `data\applications\<company>_<title>_<hash>\`:

- a resume and a cover letter, named from your `resume.json`, e.g. `Jane_Doe_Resume.docx` and `Jane_Doe_Cover_Letter.docx`
- `notes.txt`: the job link, its score, which of the posting's keywords you do and don't have, and warnings to check before sending

A job that already has a folder is skipped; use `--force` to rebuild (for example after editing `resume.json`).
The letter parser accepts a reply as separate paragraphs, one string with line breaks, or one block (which it splits
in three). If the model's reply is still unusable it asks once more, and the error shows what the model sent.

**File names are dynamic.** They're built from `resume.json` and the job using templates in `config/settings.py`:

```python
RESUME_FILENAME = "{name}_Resume"
COVER_LETTER_FILENAME = "{name}_Cover_Letter"
APPLICATION_FOLDER = "{company}_{title}_{hash}"
```

Placeholders: `{name}`, `{first}`, `{last}`, `{company}`, `{title}`, `{hash}` (unique to the posting) and `{date}`.
Keep `{hash}` in `APPLICATION_FOLDER` and don't put `{date}` there: the folder name is how finished jobs are
recognized. If you change `APPLICATIONS_DIR`, move the existing folders too, or those jobs get new documents.

**Read every cover letter before sending it.** They are drafts from a small local model.

### `rating.py`: hand-rate jobs to tune the scores

```powershell
python rating.py                  # rate 20 jobs you haven't rated yet
python rating.py -n 10
python rating.py --latest-only    # tune using only this batch of ratings
python rating.py --all-ratings    # tune on every rating (overrides FIT_ON_ALL_RATINGS)
python rating.py --report         # show the current calibration
python rating.py --reset          # delete all ratings and fits (asks you to type RESET)
```

It shows 20 unrated jobs spread across the score range, in shuffled order, with the model's score hidden. Each card
shows the salary, special notes, the model's matching skills and gaps, and a summary of the posting. Rate each 0 to
10 (`d` for the full posting, `s` to skip, `q` to stop; ratings save as you go).

**Ratings add up.** Each batch is added to every earlier one, and the tuning is re-fitted on the whole pool (at
least 10 ratings). The new fit is appended to a history in `data\calibration.json`, the latest fit is in use, and
every job's score in the database is recomputed with it, including its keyword score. Around 50+ ratings makes
the result much steadier. Only `--reset` ever discards ratings.

### `clear.py`: clear the database, archive documents

```powershell
python clear.py db               # empty the jobs database (a backup copy is made first)
python clear.py docs             # move the application folders into an archive folder
python clear.py all              # both
python clear.py all --dry-run    # preview; options go before or after, in any combination
python clear.py db docs --yes    # no confirmation prompt
python clear.py db --ratings     # also delete hand ratings and the calibration
python clear.py db --no-backup
```

- **`db`** deletes every job and application record. Your hand ratings and calibration are kept unless you add
  `--ratings` (ratings match jobs by URL, so they still count when the same jobs are scraped again). The database is
  copied to `data\backups\` first; copy that file back over `data\jobs_db.sqlite` to undo.
- **`docs`** moves the folders in `data\applications` into `data\archived_applications\applications_<date>\`.
  Nothing is deleted. Jobs left without documents get new ones on the next `main.py`.
- Each command asks you to type `CLEAR` unless you pass `--yes`. After `db`, the next `main.py` scrapes and scores everything again.

### `track.py` and `stats.py`: track applications, see what's working

`apply_jobs.py` logs an application as soon as you answer `a` (I submitted it). Everything after that is recorded with `track.py`.
Stages: `applied` -> `screening` -> `interview` -> `offer`, or an ending: `rejected`, `ghosted`, `withdrawn`.

```powershell
python track.py                          # active applications (same as: list)
python track.py list --all               # include rejected / ghosted / withdrawn
python track.py list --stale 14          # applied 14+ days ago with no answer
python track.py show acme                # stage history, contact, dates, notes

python track.py add acme --date 11/03    # you applied outside the tool
python track.py screening acme           # they replied
python track.py interview acme --date 11/12 --note "technical, 45 min"
python track.py offer acme               # also: rejected, ghosted, withdrawn
python track.py note acme "Decision by Friday"
python track.py contact acme --name "Sam Lee" --email sam@acme.com
python track.py schedule acme 11/15      # interview date
python track.py followup acme +7         # reminder in 7 days
python track.py sync                     # start tracking jobs already marked "applied"
```

A job can be named by its `#` (shown in lists), its URL, or part of the company or title. If a name matches several jobs,
it lists them and asks you to be specific. Dates accept `2026-11-09`, `11/09`, `today`, `tomorrow` and `+7`. Each application also
remembers where you applied (job site, applicant system), the score it had, and which documents folder it used.
Due follow-ups and applications with no answer for 14+ days appear under "NEEDS YOU" in `summary.py`.

```powershell
python stats.py                          # all time
python stats.py --days 30
python stats.py --section funnel,score   # funnel | score | breakdown | trends
```

- **Funnel:** scraped -> scored -> good matches -> applied -> heard back -> interview -> offer. "Heard back" means screening,
  interview, offer or a rejection. Ghosted and withdrawn don't count.
- **Score vs outcome:** answer and interview rates by score band, so you can see whether higher scores really get more replies.
- **Breakdown:** by job site, applicant system, company and title keyword.
- **Trends:** jobs scraped, applications and replies per week, and the median days to hear back.

With only a handful of applications the percentages are noisy; `stats.py` says so. The data lives in two extra tables in
`data\jobs_db.sqlite` (`tracking`, `tracking_events`). `clear.py db` empties the jobs and applications but not these two.

---

## Applying (`apply_jobs.py`)

Fills applications in a visible Firefox window and **stops before Submit**. You review and send each one. It never
asks for, reads or stores a password.

```powershell
python apply_jobs.py --list                         # which top jobs can be filled, and which can't and why
python apply_jobs.py --top 3                        # fill the 3 best
python apply_jobs.py --url "<job url>"              # one job already in the database
python apply_jobs.py --min-score 6 --days 30        # change who qualifies for this run
python apply_jobs.py --include-opened               # also offer jobs you opened but didn't finish
python apply_jobs.py --set-url "<job url>" "<employer application url>"   # give a link by hand
python apply_jobs.py --recheck-links                # search again for jobs marked "no link found"
python apply_jobs.py --login                        # log in to LinkedIn by hand, once (or: --login indeed)
```

Defaults for score, count and age come from `config\apply_settings.py`. To use Chromium instead, set
`BROWSER = "chromium"` and `python -m playwright install chromium`. Each browser keeps its own logins, so give
each its own `BROWSER_PROFILE_DIR` (for example `browser_profile_firefox`) and log in again after switching.

### Which sites get filled

| Kind | How |
|---|---|
| Greenhouse, Lever, Ashby | Fills the form on the page |
| Workday | Walks the wizard: "Autofill with Resume", each page, Save and Continue where nothing needs you, stops at Review. Needs an account per employer: the first time, the tool pauses so you sign in or create it in the browser window |
| Generic (`generic.py`) | iCIMS, Taleo, SuccessFactors, SmartRecruiters, Workable, BambooHR, Jobvite, Breezy, Recruitee, Oracle, UKG, Paylocity, ADP, JazzHR, Rippling, Teamtailor, and **any other employer career page**. Best effort: it presses Apply if the form isn't on the page, pauses when the site asks you to sign in, fills each page, clicks only Next / Continue buttons (`GENERIC_AUTO_ADVANCE`, at most `GENERIC_MAX_STEPS` pages) and stops when only Submit / Finish / Review is left |
| Job boards (ZipRecruiter, Glassdoor...) | Skipped: not application pages. Use `--set-url` with the employer's link |
| LinkedIn Easy Apply, Indeed's own forms | Not supported |

Every filler pauses when a page has fields that need you ("NEEDS YOUR ATTENTION") instead of moving on. Each site type is
a switch in `ENABLED_SITES`; `"generic"` covers all the generic ones (on unless you set it to `False`).

### Finding the employer's link

Most jobs come from LinkedIn, which hides the employer's link from logged-out visitors. In order, the tool tries:

1. **The link saved at scrape time** (`apply_url`), or the job's own URL when it is already a supported application page.
2. **Reading the LinkedIn Apply button.** With the saved, logged-in browser profile it opens the job page and reads the
   button's address, which wraps the employer's URL (`linkedin.com/safety/go/?url=...`). **Nothing is clicked.** It only
   works for jobs whose Apply button is an external link, and "Easy Apply" jobs are recognized and skipped. It runs when
   `LINKEDIN_CLICK_APPLY = True`, is capped at `LINKEDIN_CLICK_MAX` jobs per run, pauses `LINKEDIN_CLICK_DELAY` seconds
   between jobs, and stops at the first login wall. LinkedIn forbids automation, so keep it low volume. The code is in
   `applying\linkedin_resolver.py`.
3. **The company's public job board** (`applying\ats_lookup.py`). Set `AUTO_FIND_LINKS = True` to use it. It looks for the same job (company and title)
   on the company's public Greenhouse, Lever or Ashby board, and returns nothing when it isn't sure. Test it with
   `python -m applying.ats_lookup "Company" "Job title" "City, ST"`.
4. **By hand** with `--set-url`.

Whatever it finds is saved once per job. Jobs with no link are marked "none" and not searched again until you run
`--recheck-links`.

### Checks before a job is offered

- **Still open:** `CHECK_STILL_OPEN` checks the posting is still live (Greenhouse, Lever, Ashby and Workday job APIs,
  LinkedIn's public page, or the page text) and records closed ones as `closed` so they aren't offered again. An unclear
  result counts as open.
- **Duplicates:** the same posting listed twice (same title, and the same company and place, or nearly identical text) is
  saved with status `duplicate`, score 0, and left out of ratings, rankings and applications. `main.py` checks each new
  job; `python dedupe.py` cleans up what is already in the database (`--dry-run` to look first). Two genuinely different
  openings with the same title, company and city would be treated as duplicates, so check the dry run.

### Answering questions

Rules in `config\answers.py` (filled from `resume.json`), then answers you typed before (`learned_answers.json`), then
long "why us?" questions drafted by the local model (read them; they're flagged), then it asks you in the terminal and
remembers the answer. Gender, race, veteran and disability questions are answered "decline" by default. Legal attestations,
signatures and consent checkboxes are **never** filled for you. A required field that no rule can fill is listed under
"NEEDS YOUR ATTENTION". Afterwards it asks `a` (I submitted it), `s` (skip for good) or Enter (not yet), and records that.

### Diagnostics

```powershell
python -m applying.check_linkedin_page <linkedin job url>   # what the Apply button is, and what the tool would do
```

It prints a `Decision:` line (`direct`, `easy`, `apply` or `none`) and the visible buttons, which is what to send when a
link isn't found. It saves a screenshot, which can show your Messaging dock, so look before sharing it.

---

## How it works

### Filters (`core\filters.py`)

Cheap rules that skip jobs before they cost model time. Skipped jobs are saved with status `filtered` and the reason, so
they're never re-fetched.

- **Title / company** (before descriptions are fetched): senior-level titles (Senior, Sr., Staff, Principal, Lead, Manager,
  Director, Architect, VP...), Engineer III/IV/V, and a list of staffing agencies.
- **Experience** (needs the description): rejected only when *every* "N years of experience" requirement is above
  `MAX_MIN_YEARS` (default 2). "1-3 years" passes; "3+ years" doesn't.
- **Applicants** (needs the job page): LinkedIn jobs with more than `MAX_APPLICANTS` applicants are skipped, so you spend your time on
  postings that few people have applied to. The count is read from the public job page ("42 applicants", "Over 200 applicants").
  "Be among the first 25 applicants" counts as unknown, and `KEEP_UNKNOWN_APPLICANTS` decides whether such jobs are kept. Set
  `MAX_APPLICANTS = None` to turn the filter off. The count isn't stored in the database; it is only used to filter.
- **Duplicates** (`dedupe.py`): see above.

### Scoring (`core\scorer.py`, `core\calibration.py`)

1. **Hard rejects in code:** postings mentioning security clearance or US-citizen-only requirements score 0 without calling
   the model (unless they say "no clearance required").
2. **Model score:** the local model rates the job 0-10 against your resume, returning JSON (`match_score`, `matched_skills`,
   `gaps`) constrained by a schema. Requests time out after 180 seconds; a failed job is recorded (score -1) and retried next
   run, or with `rescore.py --failed-only`.
3. **Keyword score:** 0-10 from how many of your skills the posting mentions versus common terms it asks for that you don't have.
4. **Final score:** `a * (w * model + (1 - w) * keyword) + b`, clipped to 0-10. Defaults are 70% model, 30% keywords. After you
   hand-rate jobs, `w`, `a` and `b` are fitted to your ratings. A model score of 0 always stays 0.

### Documents (`documents\application_maker.py`)

The model only chooses **emphasis**: it rewrites the summary, picks the most relevant projects, and writes the cover letter body.
Employers, titles, dates, education and bullet text are copied verbatim from `resume.json`, so the resume can't contain invented
experience. Skills and projects the model returns are checked against your resume; unknown ones are dropped. Skills the posting
mentions are listed first. Invented numbers in the letter are flagged, and AI-sounding phrasing is cleaned up or flagged. The
format is ATS-friendly: single column, no tables or images, standard headings, and no hidden text.

---

## Project layout

```
job_scraper\
  main.py  apply_jobs.py  summary.py  stats.py  track.py  show_jobs.py
  rating.py  rescore.py  dedupe.py  clear.py  check_setup.py  fix_imports.py
  README.md  CMDLIST.md  requirements.txt  .gitignore
  config\       every editable setting
  core\         db, scraper, filters, scorer, calibration, job_info, job_status, tracking
  documents\    application_maker
  applying\     ats, ats_lookup, form_filler, answering, workday, generic,
                linkedin_resolver, check_linkedin_page
  data\         resume.json, jobs_db.sqlite, calibration.json, applications\, backups\, archived_applications\
  reports\      HTML summaries from summary.py --html
  archive\      retired files
  browser_profile_firefox\   the browser's saved logins (name depends on BROWSER_PROFILE_DIR)
  learned_answers.json       form answers you typed in
```

The files in `core\`, `applying\` and `documents\` are libraries. The few that have commands are run as modules from the
project root, for example `python -m documents.application_maker` or `python -m applying.check_linkedin_page`.

| File | Purpose |
|---|---|
| `main.py` | The pipeline. Run this. |
| `summary.py` | What's new and what needs you |
| `stats.py` | Funnel, score vs outcome, breakdowns and weekly trends |
| `track.py` | Tracks applications after you apply (stage, contact, dates, notes) |
| `show_jobs.py` | View top or bottom jobs |
| `rating.py` | Hand-rating tool that tunes the calibration |
| `rescore.py` | Re-scores jobs already in the database |
| `dedupe.py` | Finds the same posting listed twice |
| `clear.py` | Clears the database and archives documents |
| `apply_jobs.py` | Finds links, opens applications in a browser and fills them in (never submits) |
| `check_setup.py` | Checks that files, imports, settings, Ollama, Firefox, the database and git are all fine |
| `fix_imports.py` | Repairs imports after files are moved between folders |
| `core\db.py` | SQLite schema, migrations and saving |
| `core\scraper.py` | Scrapes via JobSpy; fetches LinkedIn descriptions and applicant counts with rate-limit backoff |
| `core\filters.py` | Pre-scoring rules (title, company, years of experience) |
| `core\scorer.py` | Local-model scoring and hard rejects |
| `core\calibration.py` | Keyword score, blending, and fitting to your ratings |
| `core\job_info.py` | Pulls salary, special notes and a bullet summary out of a posting (used by `rating.py`) |
| `core\job_status.py` | Checks whether a posting is still open |
| `core\tracking.py` | The application-tracking tables and functions behind `track.py` and `stats.py` |
| `documents\application_maker.py` | Tailored resume and cover letter generation |
| `applying\ats.py` | Works out which applicant system a link belongs to |
| `applying\ats_lookup.py` | Finds a job's employer link on the company's public job board |
| `applying\form_filler.py`, `applying\answering.py` | The form scanner/filler and the answer logic |
| `applying\workday.py` | The Workday application wizard filler |
| `applying\generic.py` | The filler for every other employer site |
| `applying\linkedin_resolver.py` | Reads the employer link from a LinkedIn job's Apply button |
| `applying\check_linkedin_page.py` | Diagnostic for the link reader |

### `resume.json`

```
name, contact {email, phone, location, github, gitlab}, work_authorization, availability, summary,
skills [...], certifications [{name, date, credential_id | url}], education [{degree, school, years}],
experience [{role, company, years, bullets [...], description}],
projects [{name, url, bullets [...], description, skills [...]}]
```

Optional: `legal_name` (used for "legal name" fields). Use a location like `Norfolk, VA` (city, then state): a form's state
field is filled from the second part. Only list things that are true; documents and form answers are built only from this file.

### Database (`data\jobs_db.sqlite`)

**`jobs` table**

| Column | Meaning |
|---|---|
| `job_url` | Unique key; how repeats are detected |
| `match_score` | **Final** score (blended and calibrated). `-1` = scoring failed; `0` = rejected, filtered or duplicate |
| `model_score`, `keyword_score` | The raw model score and the keyword score behind the final one |
| `matched_skills`, `gaps` | JSON lists from the model (or the filter reason) |
| `status` | `scored`, `scoring_failed`, `filtered` or `duplicate` |
| `salary` | Pay range from the job board, when it gave one |
| `apply_url` | The employer's application link when known; `none` / `none:clicked` = looked for, not found |

**`ratings` table:** your hand ratings. **`applications` table:** one row per job you opened, with a status of `applied`,
`skipped`, `opened` or `closed`. Older databases are upgraded automatically.

---

## Troubleshooting

- **`model 'xxx' not found (404)`:** Ollama doesn't have that model. Run `ollama list`, then set `OLLAMA_MODEL` in
  `config/settings.py` to a name it shows, or `ollama pull` the one you want. An environment variable set in one PowerShell
  window is gone in the next.
- **Stuck on "Scoring job 1" or `timed out`:** the model call is slow or hanging. Check `ollama list` and that the Ollama
  app is running. A timed-out job is saved as failed and retried next run (`python rescore.py --failed-only`).
  The run stops after 3 failures in a row.
- **The model is slow / running on the CPU:** run `ollama ps`. If it says CPU, quit Ollama completely (tray icon) and start it
  again; it only detects the GPU at startup. Check `nvidia-smi` that the GPU is visible.
- **`INFO:httpx` lines in the output:** harmless logging. To hide them, add
  `logging.getLogger("httpx").setLevel(logging.WARNING)` below `logging.basicConfig(...)` in `scorer.py`.
- **No descriptions / many jobs skipped / HTTP 429:** LinkedIn is rate limiting. The scraper backs off and stops after repeated
  429s. Wait a while, lower `LINKEDIN_RESULTS_WANTED`, search fewer terms, or run `main.py` less often. Skipped jobs are retried next run.
- **Indeed returns odd results or errors:** remove `"indeed"` from `SITES` in `config/settings.py`.
- **Cover letter: "no usable cover letter paragraphs":** the error now includes what the model sent. Send it to get the parser extended,
  or try another model.
- **`ModuleNotFoundError` or "cannot import name" after moving files:** run `python fix_imports.py` (use `--dry-run` first), then `python check_setup.py`.
- **`ModuleNotFoundError: docx`:** `pip install python-docx` (not `docx`).
- **`playwright` is not recognized:** use `python -m playwright install firefox`.
- **The browser says the profile is in use:** another window is still open on that profile. Close it.
- **Error naming a file in `config\`:** a prompt or file-name template has a typo. The message lists the placeholders you can use.
- **Scores don't look right:** run `python rating.py --report`; weak agreement with you means the prompt or model needs work, not just the blend.
- **"employer link not looked up yet" or "none" for a LinkedIn job:** run `python apply_jobs.py --login` once, then
  `python apply_jobs.py --recheck-links`. If a job still isn't found, run `python -m applying.check_linkedin_page <job url>` and read its
  `Decision:` line. `easy` means Easy Apply, which can't be filled.
- **Fewer jobs than expected:** the applicant filter may be skipping them. Look for `[FILTER] ... applicants (limit N)` lines, or raise `MAX_APPLICANTS` (or set it to `None`) in `config/settings.py`.
- **Apply opened but fields are empty:** the site may use a custom form. Check "NEEDS YOUR ATTENTION" and add a rule to
  `config\answers.py` for any question it asks about repeatedly.

---

## Not built yet

- Filling LinkedIn Easy Apply and Indeed's own forms
- Finding the employer link for Indeed jobs
- Showing the applicant count in `show_jobs.py` and `summary.py` (it isn't stored in the database yet)
- Tracking by email (outcomes are entered by hand with `track.py`)
- Salary is saved only for jobs scraped after that feature; older jobs show a salary only if the posting text quotes one
- PDF export (documents are `.docx`)
- Scheduled runs (Windows Task Scheduler can run `python main.py` for you)
- Automated tests (the fillers were checked on mock pages only)

## Privacy

`data\` (your resume, database, generated documents), `learned_answers.json` and the browser profile folder hold your personal
details and logins. Keep them out of any public repository. The `.gitignore` should list `data/`, `applications/`,
`browser_profile*/`, `learned_answers.json`, `reports/`, `*.sqlite`, `jobs.csv`, `archive/` and `__pycache__/`; keep the
repository **private**. Run `python check_setup.py` before you push: its last section lists any private file that git tracks.
If a private file was ever pushed, deleting it later does not remove it from older commits, so a public repository can still
expose it.