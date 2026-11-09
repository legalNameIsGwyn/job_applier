# Job Scraper

Finds entry-level jobs, scores how well each one fits your resume using a **local** LLM (Ollama),
generates a tailored resume and cover letter for the best matches, and fills in the applications in
a visible browser for you to review and submit. Everything runs on your own machine. Nothing is sent
to a cloud model.

```
scrape (LinkedIn, Indeed)
   -> filter by title / company rules
   -> fetch LinkedIn descriptions (and the employer's apply link when the page carries it)
   -> filter by years of experience required
   -> skip reposts (duplicate detection)
   -> score with the local model, blend with a keyword score, apply your calibration
   -> save to SQLite
   -> write a tailored resume + cover letter (.docx) for the best matches

apply_jobs.py
   -> find the employer's application link (LinkedIn Apply button, company job board, or by hand)
   -> check the posting is still open
   -> fill the form in a browser window with your documents attached, then STOP (never submits)
```

**Status:** scraping, filtering, duplicate detection, scoring, calibration, document generation and
form filling (Greenhouse, Lever, Ashby, Workday) are built. The form fillers have been tested on
mock pages; test each on a real job before trusting it. Easy Apply, Indeed links and employers'
custom career sites are **not** supported (see [Not built yet](#not-built-yet)).

---

## Setup

**Requirements:** Python 3.10+ (uses `X | None` type hints), [Ollama](https://ollama.com) running locally.

```powershell
pip install python-jobspy ollama pandas python-docx requests beautifulsoup4 playwright
pip install -U ollama                    # recent version needed for think=False
python -m playwright install chromium   # one time, for apply_jobs.py
ollama pull qwen2.5:7b                   # or any model you prefer
```

(`python -m playwright ...` works even when the `playwright` command isn't on your PATH.)

**Choose the model.** Set `OLLAMA_MODEL` in `config/settings.py`, or override it for one session
(PowerShell, in the window you run from):

```powershell
$env:OLLAMA_MODEL = "qwen3.5:4b"
```

The default is `qwen2.5:7b`. Small non-reasoning models are fastest. The scorer sends
`think=False` so "thinking" models (Qwen3 and similar) don't stall.

**Paths need no editing.** The database, calibration file, `applications\` folder, learned answers,
browser profile and `resume.json` are found relative to the project folder. To move any of them,
change the path at the top of `config/settings.py` (the database and calibration file can live in
a `data\` folder this way) or `config/apply_settings.py`.

**Fill in `resume.json`.** It is the single source of truth for scoring, every generated
document and the form answers. See [resume.json](#resumejson).

---

## Everyday use

```powershell
python main.py                    # scrape -> filter -> score -> save -> make documents
python show_jobs.py               # look at the results
python rating.py                  # hand-rate 20 jobs to tune the scores (do this early)
python apply_jobs.py --list       # what could be applied to
python apply_jobs.py --top 3      # fill the 3 best, review each one, submit by hand
```

### Settings (the `config/` folder)

**Every editable setting lives in `config/`. `resume.json` is the one exception.** The code reads
these files when it starts, so restart a running script after editing. Nothing in them needs code changes.

| File | What's in it |
|---|---|
| `config/settings.py` | file locations; what to search (`SITES`, `SEARCH_TERMS`, `LOCATION`, `RESULTS_WANTED`, `HOURS_OLD`); the model, timeouts and temperatures; scraping delays, LinkedIn result cap and rate-limit backoff; document options (`MAKE_DOCS`, `DOC_MIN_SCORE`, `MAX_DOCS_PER_RUN`, `MAX_PROJECTS`, `FONT`, greeting and sign-off); **file name templates**; score blending and rating options |
| `config/apply_settings.py` | which jobs to apply to (`APPLY_MIN_SCORE`, `APPLY_MAX_PER_RUN`, `APPLY_WINDOW_DAYS`); `ENABLED_SITES`; browser (`BROWSER_PROFILE_DIR`, `HEADLESS`, `SLOW_MO_MS`, `PAGE_TIMEOUT_MS`); `CHECK_STILL_OPEN`; Workday (`WORKDAY_AUTO_ADVANCE`, `WORKDAY_MAX_STEPS`); link finding (`AUTO_FIND_LINKS`, `FIND_LINKS_MAX`, `LINKEDIN_CLICK_APPLY`, `LINKEDIN_CLICK_MAX`, `LINKEDIN_CLICK_DELAY`); answers (`ASK_ABOUT_UNKNOWN`, `DRAFT_FREE_TEXT`, `FREE_TEXT_MAX_WORDS`, `LEARNED_ANSWERS_FILE`) |
| `config/answers.py` | the rules that answer form questions from `resume.json`, and `NEVER_ANSWER` |
| `config/filter_rules.py` | senior-title words, staffing agencies to skip, `MAX_MIN_YEARS`, clearance / citizenship patterns |
| `config/keywords.py` | `SKILL_ALIASES` and `COMMON_TERMS` for keyword matching |
| `config/job_notes.py` | the special notes (work setup, degree, travel, on-call, sponsorship...) flagged in rating cards |
| `config/writing_style.py` | the resume-tailoring and cover-letter prompts, style rules, truthfulness rules, and the AI-phrasing patterns to catch |
| `config/prompts.py` | the prompt the model scores jobs with |

Prompts are Python format strings with `{placeholders}` (listed in a comment above each one). A
typo gives an error that names the file, the prompt and the allowed placeholders.

To change what a run searches for, edit `SEARCH_TERMS`, `LOCATION` and the others in
`config/settings.py`, then run `python main.py` as usual.

Runs are **resumable and cheap to repeat**: each job is saved the moment it's scored, jobs
already scored or filtered are skipped (matched by `job_url`), and Ctrl-C loses nothing. The first
run is slow (fetching LinkedIn pages and scoring each job with a local model); later runs only
handle new jobs.

### `show_jobs.py`: view results

```powershell
python show_jobs.py                       # top 10
python show_jobs.py -n 5 --bottom         # 5 lowest scores
python show_jobs.py -n 20 --min-score 6 --days 3
python show_jobs.py --hide-zero           # hide auto-rejected / filtered jobs
python show_jobs.py --failed              # jobs whose scoring failed
python show_jobs.py -n 3 --full           # include descriptions
```

From code: `from show_jobs import show_jobs, get_jobs`.

### `rescore.py`: score stored jobs again

Use it after changing the model, the scoring prompt, `config/keywords.py` or `resume.json`, or to retry jobs
whose scoring failed. It works on jobs already in the database; nothing is scraped.

```powershell
python rescore.py                  # every scored job (asks to confirm)
python rescore.py --failed-only    # only jobs whose scoring failed
python rescore.py --include-filtered
python rescore.py -n 20            # at most 20 jobs
python rescore.py --url <job_url>  # one job
python rescore.py --yes            # don't ask
```

### `application_maker.py`: resume + cover letter

`main.py` runs this automatically for the best recent jobs. To run it yourself:

```powershell
python application_maker.py --top 5                   # best 5 jobs scoring 6+
python application_maker.py --top 10 --min-score 7 --days 3
python application_maker.py --url <job_url>           # one job already in the database
python application_maker.py --top 5 --force           # regenerate existing ones
```

Output goes to `applications\<company>_<title>_<hash>\`:

- a resume and a cover letter, named from your `resume.json`, e.g. `Jane_Doe_Resume.docx` and
  `Jane_Doe_Cover_Letter.docx`
- `notes.txt`: the job link, its score, which of the posting's keywords you do and don't have, and
  warnings to check before sending

A job that already has a folder is skipped; use `--force` to rebuild (for example after editing
`resume.json`).

**File names are dynamic.** They're built from `resume.json` and the job using the templates in
`config/settings.py`:

```python
RESUME_FILENAME = "{name}_Resume"
COVER_LETTER_FILENAME = "{name}_Cover_Letter"
APPLICATION_FOLDER = "{company}_{title}_{hash}"
```

Placeholders: `{name}` (full name from `resume.json`), `{first}`, `{last}`, `{company}`, `{title}`,
`{hash}` (unique to the posting) and `{date}` (today). Letters in any language are kept, and anything
unsafe for a file name becomes `_`. Change the name in `resume.json` and every new file follows.
Keep `{hash}` in `APPLICATION_FOLDER`, and don't put `{date}` there: the folder name is how finished
jobs are recognized, so changing it makes existing jobs look new.

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

Or from code: `from rating import rate_jobs; rate_jobs()`.

It shows 20 unrated jobs spread across the score range, in shuffled order, with the model's score
hidden. Each card shows the salary (from the job board, or quoted in the posting, or "not listed"), special
notes (work setup, years of experience, degree, contract, travel, on-call, sponsorship and so on), the
model's matching skills and gaps, and a summary of the posting's responsibilities and requirements. Rate
each 0 to 10 (`d` to read the full posting, `s` to skip, `q` to stop; ratings save as you go).
What is shown is set in `config\settings.py` (`RATING_DESCRIPTION`, `RATING_SHOW_MODEL_NOTES`) and the
notes it flags are in `config\job_notes.py`.

**Ratings add up.** Each batch is added to every earlier one, and the tuning is re-fitted on the whole
pool (needs at least 10 ratings). The new fit is appended to a history in `calibration.json`, the latest
fit is the one in use, and every job's score in the database is recomputed with it. Each run prints how
well the model agrees with you, the agreement fit by fit, and where the model disagrees with you most.
`--latest-only` fits on just the newest batch (or set `FIT_ON_ALL_RATINGS = False`). Nothing but `--reset`
ever discards ratings. Around 50+ ratings makes the result much steadier.

---

## Applying (`apply_jobs.py`)

Fills applications in a visible browser window and **stops before Submit**. You review and send each one.
It never asks for, reads or stores a password.

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

Defaults for score, count and age come from `config\apply_settings.py`.

### Which sites get filled

Greenhouse, Lever, Ashby and Workday (each on/off in `ENABLED_SITES`). LinkedIn and Indeed are
opt-in switches that only print a notice; their fillers (Easy Apply, Indeed's own forms) aren't built.

- **Workday** needs an account per employer: the first time, the tool pauses so you sign in or create
  it in the browser window (the login is kept in `browser_profile\`; the code never sees a password).
  It uses "Autofill with Resume", fills each page, clicks Save and Continue where nothing needs you
  (`WORKDAY_AUTO_ADVANCE`, at most `WORKDAY_MAX_STEPS` pages), and stops at Review.

### Finding the employer's link

Most jobs come from LinkedIn, which hides the employer's link from logged-out visitors. In order, the
tool tries:

1. **The link saved at scrape time** (`apply_url`), or the job's own URL when it is already a
   Greenhouse / Lever / Ashby / Workday page.
2. **Reading the LinkedIn Apply button.** With the saved, logged-in browser profile, it opens the job page
   and reads the button's address, which wraps the employer's URL (`linkedin.com/safety/go/?url=...`).
   **Nothing is clicked**, so it only works for jobs whose Apply button is an external link. Log in once
   with `python apply_jobs.py --login`. LinkedIn forbids automation, so this is capped (`FIND_LINKS_MAX`),
   paced and stops at the first login wall. Jobs that are LinkedIn "Easy Apply" are recognized and skipped.
3. **The company's public job board.** It searches Greenhouse / Lever / Ashby for the same company and
   title (`ats_lookup.py`; optional, `AUTO_FIND_LINKS`).
4. **Clicking Apply** and recording the page that opens. This is off by default and higher risk
   (`LINKEDIN_CLICK_APPLY = True`, `LINKEDIN_CLICK_MAX`, `LINKEDIN_CLICK_DELAY`).
5. **By hand** with `--set-url`.

Whatever it finds is saved once per job. Jobs with no link are marked "none" and not searched again until
you run `--recheck-links`. Employers on their own career sites (for example, company-hosted pages) are
found but have no filler yet, so they're listed as "can't fill" in `--list`.

### Checks before a job is offered

- **Still open:** `CHECK_STILL_OPEN` checks the posting is still live (Greenhouse, Lever, Ashby and
  Workday job APIs, LinkedIn's public page, or the page text) and records closed ones as `closed` so they
  aren't offered again. An unclear result counts as open.
- **Duplicates:** the same posting listed twice (same title, and the same company and place, or nearly
  identical text) is saved with status `duplicate`, score 0, and left out of ratings, rankings and
  applications. `main.py` checks each new job; `python dedupe.py` cleans up what is already in the
  database (`python dedupe.py --dry-run` to look first).

### Answering questions

Rules in `config\answers.py` (filled from `resume.json`), then answers you typed before
(`learned_answers.json`), then long "why us?" questions drafted by the local model (read them; they're
flagged), then it asks you in the terminal and remembers the answer. Gender, race, veteran and disability
questions are answered "decline" by default. Legal attestations, signatures, salary and consent checkboxes
are **never** filled for you: they're listed under "NEEDS YOUR ATTENTION".

Afterwards it asks `a` (I submitted it), `s` (skip for good) or Enter (not yet), and records that.

### Diagnostics

```powershell
python check_linkedin_page.py <linkedin job url>   # shows what the Apply button is, and what the tool would do
python check_link.py <linkedin job url>            # older check of the logged-out page (rarely needed)
```

`check_linkedin_page.py` prints a `Decision:` line (`direct`, `easy`, `apply` or `none`) and the visible
buttons, which is what to send when a link isn't found.

---

## How it works

### Filters (`filters.py`)

Cheap rules that skip jobs before they cost model time. Skipped jobs are saved with status
`filtered` and the reason, so they're never re-fetched.

- **Title / company** (runs *before* descriptions are fetched): senior-level titles (Senior, Sr.,
  Staff, Principal, Lead, Manager, Director, Architect, VP...), Engineer III/IV/V, and a list of
  staffing agencies.
- **Experience** (needs the description): rejected only when *every* "N years of experience"
  requirement is above `MAX_MIN_YEARS` (default 2). "1-3 years" passes; "3+ years" doesn't.
- **Duplicates** (`dedupe.py`): see above.

Edit `SENIOR_TITLE_WORDS`, `BLOCKED_COMPANIES` and `MAX_MIN_YEARS` in `config/filter_rules.py`.

### Scoring (`scorer.py`, `calibration.py`)

1. **Hard rejects in code:** postings mentioning security clearance or US-citizen-only requirements
   score 0 without calling the model (unless they say "no clearance required").
2. **Model score:** the local model rates the job 0-10 against your resume, returning JSON
   (`match_score`, `matched_skills`, `gaps`) constrained by a schema. Requests time out after 180
   seconds, and a failed job is recorded (score -1) and retried next run (or with `rescore.py --failed-only`).
3. **Keyword score:** 0-10 from how many of your skills the posting mentions versus common terms it
   asks for that you don't have.
4. **Final score:** `a * (w * model + (1 - w) * keyword) + b`, clipped to 0-10. Defaults are 70%
   model, 30% keywords (`DEFAULT_MODEL_WEIGHT` in `config/settings.py`). After you hand-rate jobs, `w`, `a` and `b` are fitted to your ratings and
   appended to `calibration.json`. A model score of 0 always stays 0.

### Documents (`application_maker.py`)

The model only chooses **emphasis**: it rewrites the summary, picks the most relevant projects, and
writes the cover letter body. Employers, titles, dates, education and bullet text are copied verbatim
from `resume.json`, so the resume can't contain invented experience. Further safeguards:

- Skills and projects the model returns are checked against your resume; unknown ones are dropped.
- Skills the posting mentions (including variants such as "Spring Boot" or "REST APIs") are listed first.
- Invented numbers in the letter are flagged; AI-sounding phrasing is cleaned up or flagged.
- The format is ATS-friendly: single column, no tables or images, standard headings. There are no hidden
  keywords or invisible text; applicant systems and employers penalize that.

---

## Project layout

| File | Purpose |
|---|---|
| `main.py` | The pipeline. Run this. |
| `config\` | **Every editable setting** (see above) |
| `scraper.py` | Scrapes via JobSpy; fetches LinkedIn descriptions with rate-limit backoff |
| `filters.py` | Pre-scoring rules (title, company, years of experience) |
| `scorer.py` | Local-model scoring and hard rejects |
| `calibration.py` | Keyword score, blending, and fitting to your ratings |
| `rating.py` | Hand-rating tool that tunes the calibration |
| `rescore.py` | Re-scores jobs already in the database |
| `db.py` | SQLite schema, migrations and saving |
| `show_jobs.py` | View top or bottom jobs |
| `job_info.py` | Pulls salary, special notes and a bullet summary out of a posting (used by `rating.py`) |
| `application_maker.py` | Tailored resume and cover letter generation |
| `dedupe.py` | Finds the same posting listed twice |
| `job_status.py` | Checks whether a posting is still open |
| `apply_jobs.py` | Finds links, opens applications in a browser and fills them in (never submits) |
| `form_filler.py`, `answering.py` | The form scanner/filler and the answer logic |
| `ats.py` | Works out which applicant system a link belongs to |
| `workday.py` | The Workday application wizard filler |
| `linkedin_resolver.py` | Reads the employer link from a LinkedIn job's Apply button |
| `ats_lookup.py` | *Optional.* Searches a company's public job board for the same job |
| `check_linkedin_page.py` | Diagnostic for the LinkedIn link reader |
| `resume.json` | Your resume data (the source of truth; the one setting-like file outside `config\`) |
| `calibration.json` | *Generated.* The score tuning and its history of fits |
| `jobs_db.sqlite` | *Generated.* The database (location set by `DB_PATH`) |
| `applications\` | *Generated.* One folder of documents per job |
| `learned_answers.json` | *Generated.* Form answers you typed in, remembered for next time |
| `browser_profile\` | *Generated.* The browser's saved logins for `apply_jobs.py` |

### `resume.json`

```
name, contact {email, phone, location, github, gitlab}, work_authorization, availability, summary,
skills [...], certifications [{name, date, credential_id | url}], education [{degree, school, years}],
experience [{role, company, years, bullets [...], description}],
projects [{name, url, bullets [...], description, skills [...]}]
```

Optional: `legal_name` (used for "legal name" fields). Only list things that are true. The documents and
form answers are built only from this file.

### Database

**`jobs` table**

| Column | Meaning |
|---|---|
| `job_url` | Unique key; how repeats are detected |
| `match_score` | **Final** score (blended and calibrated). `-1` = scoring failed; `0` = rejected, filtered or duplicate |
| `model_score`, `keyword_score` | The raw model score and the keyword score behind the final one |
| `matched_skills`, `gaps` | JSON lists from the model (or the filter reason) |
| `status` | `scored`, `scoring_failed`, `filtered` or `duplicate` |
| `salary` | Pay range from the job board (text), when it gave one |
| `apply_url` | The employer's application link when known; `none` / `none:clicked` = looked for, not found |

**`ratings` table:** your hand ratings. **`applications` table:** one row per job you opened, with a status of
`applied`, `skipped`, `opened` or `closed`. Existing databases are upgraded automatically the first time you
run newer code.

---

## Troubleshooting

- **Stuck on "Scoring job 1":** the model call is hanging. Check `ollama list`, make sure the Ollama app
  is running, and test one job with:
  `python -c "import scorer; print(scorer.score_job('Junior Python Developer','Acme','Remote','Entry-level role using Python and SQL.'))"`.
  The run stops after 3 failures in a row, and requests time out after 180 seconds.
- **The model is slow / running on the CPU:** run `ollama ps`. If it says CPU, quit Ollama completely (tray
  icon) and start it again; it only detects the GPU at startup. Check with `nvidia-smi` that the GPU is visible.
- **No descriptions / many jobs skipped / HTTP 429:** LinkedIn is rate limiting. The scraper backs off and
  stops after repeated 429s. Wait a while, lower `LINKEDIN_RESULTS_WANTED`, keep
  `LINKEDIN_JOBSPY_FETCH_DESCRIPTIONS = False`, or search fewer terms per run. Skipped jobs are retried next run.
- **Indeed returns odd results or errors:** remove `"indeed"` from the sites list in `config/settings.py`.
- **`ModuleNotFoundError: docx`:** `pip install python-docx` (not `docx`).
- **`playwright` is not recognized:** use `python -m playwright install chromium`.
- **Slow with a thinking model:** upgrade the `ollama` package so `think=False` is accepted, or use a
  non-reasoning model.
- **Error naming a file in `config\`:** a prompt or file-name template has a typo. The message lists the placeholders you can use.
- **Scores don't look right:** run `python rating.py --report`; a weak model-vs-you agreement
  means the prompt or model needs work, not just the blend.
- **"employer link not looked up yet" or "none" for a LinkedIn job:** run `python apply_jobs.py --login` once,
  then `python apply_jobs.py --recheck-links`. If a job still isn't found, run
  `python check_linkedin_page.py <job url>` and read its `Decision:` line. `easy` means LinkedIn Easy Apply,
  which can't be filled.
- **Apply opened but fields are empty:** the site may use a custom form. Check the "NEEDS YOUR ATTENTION"
  list, and add a rule to `config\answers.py` for any question it asks about repeatedly.

---

## Not built yet

- Filling LinkedIn Easy Apply, Indeed's own forms, and employers' custom career sites (iCIMS, Taleo, in-house portals)
- Finding the employer link for Indeed jobs
- Application tracking after you apply (interviewing / rejected)
- Salary is saved only for jobs scraped after that feature; older jobs show a salary only if the posting text quotes one
- PDF export (documents are `.docx`)
- Scheduled runs and a summary report
- Automated tests (the fillers were checked on mock pages only)

## Privacy

`resume.json`, the database, `learned_answers.json`, `browser_profile\` and the generated documents contain your
personal details and logins. Keep them out of any public repository.