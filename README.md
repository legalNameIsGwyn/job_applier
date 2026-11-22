# Job Scraper

Finds jobs, scores how well each one fits your resume using a **local** LLM (Ollama), works out how compatible
you are with each posting, writes a tailored resume and cover letter for the ones worth applying to (including jobs
outside your usual field), and lists them in a spreadsheet you can click through. If you want, it also fills in the
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
   -> add each job to profiles/<name>/applications.xlsx
   -> print a summary of what's new and what needs you

python apply_jobs.py                 (full-auto: a separate command you run on purpose)
   -> find the employer's application link, check the posting is still open
   -> open up to PARALLEL_JOBS browser windows, each with its documents attached
   -> fill the form, then STOP (it never clicks Submit)
```

**Status:** scraping, filtering, duplicate detection, profiles (one per kind of job search), scoring, per-profile
calibration, compatibility percentages, three tailoring modes with bridge lines, the applications spreadsheet, the summary,
application tracking and form filling (Greenhouse, Lever, Ashby, Workday, and a generic filler for other employer
sites) are built. The form fillers were tested on mock pages; check each kind on a real job before trusting it.
LinkedIn Easy Apply and Indeed's own forms are **not** supported (see [Not built yet](docs/reference.md#not-built-yet)).

---

## Setup

**Requirements:** Python 3.10+, [Ollama](https://ollama.com) running locally.

```powershell
pip install -r requirements.txt
python -m playwright install chromium      # one time, only for apply_jobs.py (BROWSER in config/apply_settings.py)
ollama pull qwen2.5:7b                     # or any model you prefer
```

Updating an existing install? Run `pip install openpyxl` once (the applications list is now an `.xlsx`).

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
python main.py                    # scrape -> filter -> score -> compat -> documents -> spreadsheet -> summary
python -m tools.summary           # what's new and what needs you
python -m tools.show_jobs         # browse scored jobs in the same layout as main.py, with each job's db id (the number tools.track accepts), scrape date and full link
```

Open `profiles\<name>\applications.xlsx`, click through the jobs, apply, and write anything in the `status` column
(applied, rejected, interview...).

**Full-auto: the bot fills the forms and stops before Submit.**

```powershell
python main.py
python apply_jobs.py --list       # which jobs can be filled, and which can't and why
python apply_jobs.py --top 0      # find employer links without opening any forms
python apply_jobs.py --top 3      # fill 3 forms; review each, submit by hand, answer "a"
python -m tools.csv_sync          # copy applied / closed from the database into the list
python -m tools.summary
```

Both flows check the database **and** the applications list, so a job is never handled twice (see
[Applications list](docs/applying.md#applications-list)).

**Now and then:**

```powershell
python -m tools.rating            # hand-rate 20 jobs to tune the scores (do this early)
python -m tools.rescore --yes     # score stored jobs again after changing a prompt, the model or the resume
python -m tools.check --blockers  # no model: block saved jobs that need a clearance or citizenship, and clear their descriptions
python -m tools.check --availability  # are the saved jobs that have documents still open? marks the closed ones
python -m tools.check --mark URL  # you checked a posting yourself: mark it closed (--as open undoes it)
python -m tools.stats             # what's working: funnel, score vs outcome, breakdowns, trends
python -m tools.track             # where each application stands
python -m tools.check_setup       # is everything in place?
```

Every command and flag is listed in [CMDLIST.md](CMDLIST.md).

Runs are **resumable and cheap to repeat**: each job is saved the moment it is scored, jobs already scored, filtered
or marked duplicate are skipped (matched by `job_url`), and Ctrl-C loses nothing. The search itself runs every time,
but only new jobs cost description fetching and model time. Jobs whose scoring failed, or that had no description
yet, are retried on the next run.

**Stopping a run.** Press Ctrl-C once while descriptions are downloading and the download stops after the current request.
By default the run then scores the descriptions already downloaded and carries on; set `STOP_FETCH_THEN_SCORE = False`
in `config/settings.py` to go straight to the summary instead. Jobs not downloaded are retried next run. A second Ctrl-C
does nothing extra.

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
    applications.xlsx  your click-through list
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

## Documentation

- **[How it works](docs/how-it-works.md)**: filters (title, company, years, applicants, duplicates and hard blockers),
  scoring and calibration, the compatibility percentage (including how licenses and certifications are flagged), and the
  tailored documents with their standard, bridge and boilerplate modes.
- **[Applying and tracking](docs/applying.md)**: the applications list, tracking results with `tools.track` and
  `tools.stats`, and `apply_jobs.py`: which sites it fills, how it finds the employer's link, the checks before a job is
  offered, and how questions get answered.
- **[Settings](docs/settings.md)**: what is in each `config/` file, how profile overrides work, and how to change the
  console colors.
- **[Reference](docs/reference.md)**: project layout, the `resume.json` fields, the database tables, and what isn't built yet.
- **[CMDLIST.md](CMDLIST.md)**: every command and flag.

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
  they are already in the applications list. Raise `MAX_APPLICANTS` or set it to `None`.
- **No new documents for a job:** it is already in `applications.xlsx`, has a folder, was applied to or closed, or scores
  below `MIN_SCORE`. Delete its row (and folder) to redo it.
- **`[CSV] Could not write ...`:** the file is open in Excel. Close it; the rows are added on the next run.
- **No `applications.xlsx` yet:** it is created the first time any command reads the list (for example
  `python main.py`). If an `applications.csv` is beside it, its rows are imported once.
- **`ModuleNotFoundError: openpyxl`:** `pip install openpyxl`.
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

## Privacy

`data\` (database, reports, learned answers), `profiles\*\resume.json`, `profiles\*\applications\`,
`profiles\*\applications.csv`, `profiles\*\applications.xlsx` and the browser profile folders hold your personal details and logins. Keep them out of any
public repository. The `.gitignore` should list `data/`, `browser_profile*/`, `profiles/*/resume.json` (with
`!profiles/_generic/resume.json`), `profiles/*/applications/`, `profiles/*/applications.csv`, `profiles/*/applications.xlsx`, `*.sqlite` and
`__pycache__/`; keep the repository **private**. Run `python -m tools.check_setup` before you push: its last section
lists any private file that git tracks. If a private file was ever pushed, deleting it later does not remove it from
older commits, so a public repository can still expose it.