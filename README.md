# Job Scraper

Finds entry-level jobs, scores how well each one fits your resume using a **local** LLM (Ollama),
and generates a tailored resume and cover letter for the best matches. Everything runs on your
own machine. Nothing is sent to a cloud model.

```
scrape (LinkedIn, Indeed)
   -> filter by title / company rules
   -> fetch LinkedIn descriptions
   -> filter by years of experience required
   -> score with the local model, blend with a keyword score
   -> save to SQLite
   -> write a tailored resume + cover letter (.docx) for the best matches
```

**Status:** scraping, filtering, scoring, calibration and document generation work. Auto-applying,
application tracking and salary storage are **not built yet** (see [Not built yet](#not-built-yet)).

---

## Setup

**Requirements:** Python 3.10+ (uses `X | None` type hints), [Ollama](https://ollama.com) running locally.

```powershell
pip install python-jobspy ollama pandas python-docx requests beautifulsoup4
pip install -U ollama          # recent version needed for think=False
ollama pull qwen2.5:7b         # or any model you prefer
```

**Choose the model.** Set `OLLAMA_MODEL` in `config/settings.py`, or override it for one session
(PowerShell, in the window you run from):

```powershell
$env:OLLAMA_MODEL = "qwen3.5:4b"
```

The default is `qwen2.5:7b`. Small non-reasoning models are fastest. The scorer sends
`think=False` so "thinking" models (Qwen3 and similar) don't stall.

**Paths need no editing.** The database, calibration file, `applications\` folder and `resume.json`
are all found relative to the project folder. To move any of them, change the path at the top of
`config/settings.py`.

**Fill in `resume.json`.** It is the single source of truth for scoring and for every generated
document. See [resume.json](#resumejson).

---

## Everyday use

```powershell
python main.py                    # scrape -> filter -> score -> save -> make documents
python show_jobs.py               # look at the results
python rating.py                  # hand-rate 20 jobs to tune the scores (do this early)
```

### Settings (the `config/` folder)

**Every editable setting lives in `config/`. `resume.json` is the one exception.** The code reads
these files when it starts, so restart a running script after editing. Nothing in them needs code changes.

| File | What's in it |
|---|---|
| `config/settings.py` | file locations; what to search (`SITES`, `SEARCH_TERMS`, `LOCATION`, `RESULTS_WANTED`, `HOURS_OLD`); the model, timeouts and temperatures; scraping delays and rate-limit backoff; document options (`MAKE_DOCS`, `DOC_MIN_SCORE`, `MAX_DOCS_PER_RUN`, `MAX_PROJECTS`, `FONT`, greeting and sign-off); **file name templates**; score blending and rating options |
| `config/filter_rules.py` | senior-title words, staffing agencies to skip, `MAX_MIN_YEARS`, clearance / citizenship patterns |
| `config/keywords.py` | `SKILL_ALIASES` and `COMMON_TERMS` for keyword matching |
| `config/writing_style.py` | the resume-tailoring and cover-letter prompts, style rules, truthfulness rules, and the AI-phrasing patterns to catch |
| `config/prompts.py` | the prompt the model scores jobs with |

Prompts are Python format strings with `{placeholders}` (listed in a comment above each one). A
typo gives an error that names the file, the prompt and the allowed placeholders.

Runs are **resumable** (see below). To change what a run searches for, edit `SEARCH_TERMS`,
`LOCATION` and the others in `config/settings.py`, then run `python main.py` as usual.

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
python rating.py --report         # show the current calibration
```

Or from code: `from rating import rate_jobs; rate_jobs()`.

It shows 20 unrated jobs spread across the score range, in shuffled order, with the model's score
hidden. Rate each 0 to 10 (`s` to skip, `q` to stop; ratings save as you go).

**Ratings add up.** Each batch is added to every earlier one, and the tuning is re-fitted on the whole
pool (needs at least 10 ratings). The new fit is appended to a history in `calibration.json`, the latest
fit is the one in use, and every job's score in the database is recomputed with it. Each run prints how
well the model agrees with you, the agreement fit by fit, and where the model disagrees with you most.

Options: `--latest-only` fits on just the newest batch (or set `FIT_ON_ALL_RATINGS = False`),
`--all-ratings` overrides that setting, and `--reset` deletes all ratings and fits and returns every
score to the default blend (it asks you to type RESET first). Nothing else ever discards ratings.
Around 50+ ratings makes the result much steadier.

---

## Applying (`apply_jobs.py`)

Fills applications in a visible browser window and **stops before Submit**. You review and send each one.

```powershell
pip install playwright
playwright install chromium          # one time

python apply_jobs.py --list          # which top jobs can be filled, and which can't and why
python apply_jobs.py --top 3         # fill the 3 best
python apply_jobs.py --set-url "<job url>" "<employer application url>"
```

- **Sites:** Greenhouse, Lever and Ashby. Workday, LinkedIn and Indeed are listed as off switches in
  `config\apply_settings.py` and print a notice; their fillers aren't built yet.
- **Which link:** it uses the employer's link (`apply_url`) when the scrape captured one, otherwise the job
  link if that is itself a Greenhouse / Lever / Ashby page. Jobs already in your database from before this
  feature have no `apply_url`; use `--set-url` or re-scrape.
- **Answers:** rules in `config\answers.py` (filled from `resume.json`), then answers you typed before,
  then long "why us?" questions drafted by the local model, then it asks you in the terminal and remembers.
  Gender, race, veteran and disability questions are answered "decline" by default.
- **Never filled for you:** legal attestations and consent checkboxes; they're listed under "NEEDS YOUR ATTENTION".
- **Afterwards** it asks `a` (I submitted it), `s` (skip for good) or Enter (not yet), and records that.

## How it works

### Filters (`filters.py`)

Cheap rules that skip jobs before they cost model time. Skipped jobs are saved with status
`filtered` and the reason, so they're never re-fetched.

- **Title / company** (runs *before* descriptions are fetched): senior-level titles (Senior, Sr.,
  Staff, Principal, Lead, Manager, Director, Architect, VP...), Engineer III/IV/V, and a list of
  staffing agencies.
- **Experience** (needs the description): rejected only when *every* "N years of experience"
  requirement is above `MAX_MIN_YEARS` (default 2). "1-3 years" passes; "3+ years" doesn't.

Edit `SENIOR_TITLE_WORDS`, `BLOCKED_COMPANIES` and `MAX_MIN_YEARS` in `config/filter_rules.py`.

### Scoring (`scorer.py`, `calibration.py`)

1. **Hard rejects in code:** postings mentioning security clearance or US-citizen-only requirements
   score 0 without calling the model (unless they say "no clearance required").
2. **Model score:** the local model rates the job 0-10 against your resume, returning JSON
   (`match_score`, `matched_skills`, `gaps`) constrained by a schema. Requests time out after 180
   seconds, and a failed job is recorded (score -1) and retried next run.
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
- The format is ATS-friendly: single column, no tables or images, standard headings.

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
| `db.py` | SQLite schema, migrations and saving |
| `show_jobs.py` | View top or bottom jobs |
| `application_maker.py` | Tailored resume and cover letter generation |
| `apply_jobs.py` | Opens applications in a browser and fills them in (never submits) |
| `form_filler.py`, `answering.py`, `ats.py` | The form scanner/filler, the answer logic, and ATS detection |
| `rescore.py` | Re-scores jobs already in the database |
| `resume.json` | Your resume data (the source of truth; the one setting-like file outside `config\`) |
| `calibration.json` | *Generated.* The score tuning and its history of fits |
| `jobs_db.sqlite` | *Generated.* The database |
| `applications\` | *Generated.* One folder of documents per job |
| `learned_answers.json` | *Generated.* Form answers you typed in, remembered for next time |
| `browser_profile\` | *Generated.* The browser's saved logins for `apply_jobs.py` |

`local_scorer.py` and `test.py` are older scratch files that the pipeline doesn't use.

### `resume.json`

```
name, contact {email, phone, location, github, gitlab}, work_authorization, availability, summary,
skills [...], certifications [{name, date, credential_id | url}], education [{degree, school, years}],
experience [{role, company, years, bullets [...], description}],
projects [{name, url, bullets [...], description, skills [...]}]
```

Only list things that are true. The documents are built only from this file.

### Database (`jobs` table)

| Column | Meaning |
|---|---|
| `job_url` | Unique key; how duplicates are detected |
| `match_score` | **Final** score (blended and calibrated). `-1` = scoring failed; `0` = rejected or filtered |
| `model_score`, `keyword_score` | The raw model score and the keyword score behind the final one |
| `matched_skills`, `gaps` | JSON lists from the model (or the filter reason) |
| `status` | `scored`, `scoring_failed` or `filtered` |

`apply_url` is the employer's own application link when the job board provides one. A separate `ratings` table
holds your hand ratings, and an `applications` table records each job you opened (`applied`, `skipped`, `opened`). Existing databases are upgraded automatically
the first time you run the new code.

---

## Troubleshooting

- **Stuck on "Scoring job 1":** the model call is hanging. Check `ollama list`, make sure the Ollama app
  is running, and test one job with:
  `python -c "import scorer; print(scorer.score_job('Junior Python Developer','Acme','Remote','Entry-level role using Python and SQL.'))"`.
  The run stops after 3 failures in a row, and requests time out after 180 seconds.
- **No descriptions / many jobs skipped:** LinkedIn is likely rate limiting. The scraper backs off and
  stops after repeated 429s; wait a while, lower `results_wanted`, or search fewer terms per run. Skipped
  jobs are retried next run.
- **Indeed returns odd results or errors:** remove `"indeed"` from `site_names` in `main.py`.
- **`ModuleNotFoundError: docx`:** `pip install python-docx` (not `docx`).
- **Slow with a thinking model:** upgrade the `ollama` package so `think=False` is accepted, or use a
  non-reasoning model.
- **Error naming a file in `config\`:** a prompt or file-name template has a typo. The message lists the placeholders you can use.
- **Scores don't look right:** run `python rating.py` and read the report; a weak model-vs-you agreement
  means the prompt or model needs work, not just the blend.

---

## Not built yet

- Auto-applying on Workday, LinkedIn Easy Apply and Indeed (opt-in switches exist but the fillers aren't built)
- Application tracking after you apply (interviewing / rejected)
- Salary storage (JobSpy returns it, but it isn't saved)
- PDF export (documents are `.docx`)
- Detecting the same job reposted or listed on both sites under different URLs
- Checking that a posting is still open before generating documents
- Scheduled runs and a summary report

## Privacy

`resume.json`, the database and the generated documents contain your personal details. Keep them out
of any public repository.
