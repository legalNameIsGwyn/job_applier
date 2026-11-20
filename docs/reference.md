[← README](../README.md)

# Reference

## Project layout

```
job_scraper\
  main.py  apply_jobs.py
  README.md  CMDLIST.md  requirements.txt  .gitignore
  docs\        how-it-works, applying, settings, reference
  config\       every editable setting, and the profile loader
  profiles\     one folder per profile (profile.py, resume.json, applications\, applications.csv); _generic is the template
  db\           models, session, repo, queries, ratings, calibrations, tracking, migrate
  core\         scraper, filters, scorer, calibration, compat, dedupe, job_info, job_status, csv_log
  documents\    application_maker
  applying\     ats, ats_lookup, form_filler, answering, workday, generic, linkedin_resolver, worker, check_linkedin_page
  tools\        profile, show_jobs, summary, rescore, check, rating, stats, track, clear, check_setup, csv_sync
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
projects [{name, url, bullets [...], description, skills [...]}],
licenses [{name, state, expires}]
```

`licenses` (for example a driver's license) is optional but recommended: only `name` is required, and `[]` means you hold none. A job that requires a license or certification you don't list is flagged, never dropped.

Optional: `legal_name` (used for "legal name" fields); `interests` and `transferable_experience` (lists of short
phrases; bridge lines may use them, and anything written there is treated as a true fact about you). Use a location
like `Norfolk, VA` (city, then state): a form's state field is filled from the second part. Only list things that are
true; documents and form answers are built only from this file.

### Database (`data\jobs_db.sqlite`, SQLAlchemy over SQLite)

| Table | Holds |
|---|---|
| `profiles` | one row per profile |
| `jobs` | the scraped posting, stored once (`job_url` is unique), with `apply_url`, `salary`, `is_duplicate` |
| `job_scores` | one row per job and profile: status (`scored`, `scoring_failed`, `filtered`, `blocked`), final `match_score` (`-1` = failed, `0` = rejected), `model_score`, `keyword_score`, `compat_pct`, `compat_detail_pct`, `compat_missing`, `compat_capped`, `matched_skills`, `gaps` |
| `ratings`, `calibrations` | your hand ratings and every fit of the score blend, per profile |
| `applications` | one row per job you opened to apply: `applied`, `skipped`, `opened` or `closed` |
| `tracking`, `tracking_events` | application stage, contact, dates and notes, and the history behind `tools.stats` |

Older databases are upgraded automatically (new columns are added on start). `python -m db.migrate` copies a database
from the old single-table layout into this one without changing the old file.

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
