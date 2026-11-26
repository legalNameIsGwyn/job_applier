# Job Scraper: Command Reference

Run everything from the project root (`job_scraper\`). Settings live in `config\`; each profile overrides them in
`profiles\<name>\profile.py`, and its resume is `profiles\<name>\resume.json`. **`main.py` only takes `--profile`**, so
change what it searches, scores and generates in `config\settings.py` (or the profile).

Only `main.py` and `apply_jobs.py` run as scripts. Everything in `tools\`, `core\`, `documents\`, `applying\` and `db\`
runs as a module: `python -m tools.summary`.

## Choosing a profile
Every command takes `--profile NAME`.


| Command | What it does |
|---|---|
| `python -m tools.profile list` | Every profile, with its resume and data status |
| `python -m tools.profile new NAME` | Guided setup; writes `profiles\NAME\profile.py` |
| `python -m tools.profile show NAME` | What it changes, and where each value comes from |
| `python -m tools.profile check NAME` | Validate it (prompts, patterns, resume, licenses) without running anything |
| `python -m tools.profile rename OLD NEW` | Move the folder and keep its scores, ratings and history |

## Daily use
| Command | What it does |
|---|---|
| `python main.py` | Scrape LinkedIn/Indeed, filter (blockers are removed before any model call), score with Ollama, save, write resume + cover letter for the best matches, then print the summary |
| `python -m tools.summary` | What's new, what's ready to apply to, and what needs you |
| `python -m tools.show_jobs` | Top scored jobs |
| `python apply_jobs.py --list` | Which top jobs can be filled, and which can't and why |
| `python apply_jobs.py --top 3` | Fill the 3 best applications in the browser (never submits) |
| `python -m tools.track` | Where each application stands |
| `python -m tools.stats` | What's working: funnel, score vs outcome, breakdowns, trends |

While `main.py` runs, each job gets `[FILTER] Checking job: …` and then `Removed: …` (with the reason) or `Accepted: …`.
A job removed for a clearance or citizenship requirement (in its title, or in its description) is saved with status `blocked`, the reason and no description.
A posting LinkedIn says is closed is saved with status `closed` and no description. After scoring, a `RE-CHECK` step asks each saved job that has documents
whether it is still open (`[AVAILABILITY] Checking n/N`, with the link). Jobs it can't check are left for you if `AVAILABILITY_ASK = True`: each link opens in your browser and you answer
`o` (open), `c` (closed), `b` (reopen the link), `s` (skip) or `q` (stop).

## Viewing jobs: `tools.show_jobs`
| Flag | Meaning |
|---|---|
| `-n N` | Show N jobs (default from settings) |
| `--bottom` | Lowest scores instead of highest |
| `--min-score X` / `--max-score X` | Only scores in that range |
| `--days D` | Only jobs scraped in the last D days |
| `--hide-zero` | Hide auto-rejected (score 0) jobs |
| `--failed` | Only jobs whose scoring failed |
| `--full` | Include the job description |

## Summary and stats
| Command | Meaning |
|---|---|
| `python -m tools.summary --days D --top N --min-score X` | Window, number of best matches and score cutoff (defaults in `config\settings.py`) |
| `python -m tools.summary --html` | Also save `data\reports\summary_<date>.html` and open it |
| `python -m tools.stats --days D` | Only the last D days |
| `python -m tools.stats --section funnel,score,breakdown,trends` | Only the sections you list |

## Re-scoring (uses the model): `tools.rescore`
| Flag | Meaning |
|---|---|
| *(none)* | Re-score every scored job (asks to confirm) |
| `--failed-only` | Only jobs whose scoring failed |
| `--include-filtered` | Also re-check filtered jobs against the current rules |
| `--include-unscored` | Also score jobs this profile has never seen (for example ones another profile scraped) |
| `-n N` / `--limit N` | At most N jobs |
| `--url URL` | Just one job |
| `-y` / `--yes` | Don't ask for confirmation |

## Checking saved jobs (no model): `tools.check`
| Command | Meaning |
|---|---|
| `python -m tools.check` | Lists the available checks |
| `python -m tools.check --blockers` | Lists saved jobs that need a clearance or citizenship (grouped, with links), asks, then marks them `blocked` and clears their descriptions. Jobs you have an application for are skipped |
| `python -m tools.check --blockers --show-all` | List every job, not just the first 15 per group |
| `python -m tools.check --blockers -y` | Don't ask for confirmation |
| `python -m tools.check --availability` | Asks each saved job that has documents whether it is still open and marks the closed ones. No model; ignores `AVAILABILITY_RECHECK_DAYS`; with `AVAILABILITY_ASK` on, it then opens the unanswered ones one by one |
| `python -m tools.check --mark URL [URL ...]` | You checked the posting yourself: mark it closed (database and applications list). A job you applied to is never changed |
| `python -m tools.check --mark URL --as open` | Undo a closed mark |

## Rating and calibration: `tools.rating`
| Flag            | Meaning                                              |
| --------------- | ---------------------------------------------------- |
| *(none)*        | Rate a batch of jobs you haven't rated yet           |
| `-n N`          | Jobs per batch                                       |
| `--rerate`      | Go back over ratings you already gave                |
| `--latest-only` | Tune using only this batch of ratings                |
| `--all-ratings` | Tune using every rating (overrides the setting)      |
| `--report`      | Show the current calibration and exit                |
| `--reset`       | Delete this profile's ratings and fits (asks you to type RESET) |

## Documents: `documents\application_maker.py`
Run it as a module, because it lives in a package folder:

| Command | Meaning |
|---|---|
| `python -m documents.application_maker --top N` | Resume + cover letter for the top N scored jobs |
| `python -m documents.application_maker --url URL` | One job already in the database |
| `python -m documents.application_maker --top N --min-score X` | Score cutoff (default 6) |
| `python -m documents.application_maker --top N --days D` | Only jobs scored in the last D days |
| `python -m documents.application_maker --top N --force` | Regenerate even if the folder exists |
| `python -m documents.application_maker --url URL --mode auto\|standard\|bridge\|boilerplate` | Choose the tailoring mode for one job |
| `python -m documents.application_maker --url URL --mode bridge --suggest-bridges` | Accept, edit or skip each bridge line first |
| `python -m documents.application_maker --url URL --bridges-only` | Only show the proposed bridge lines |

Output goes to `profiles\<name>\applications\<company>_<title>_<hash>\` (resume, cover letter, `notes.txt`).

## Applying: `apply_jobs.py`
| Flag | Meaning |
|---|---|
| `--list` | Show what would be filled; open nothing |
| `--top N` | At most N jobs this run (`--top 0` only looks for employer links) |
| `--min-score X` / `--days D` | Who qualifies for this run |
| `--url URL` | One job already in the database |
| `--parallel N` | Applications open at once (`1` uses your real browser profile) |
| `--include-opened` | Also offer jobs you opened but didn't finish |
| `--set-url JOB_URL APPLY_URL` | Give a job's employer link by hand |
| `--recheck-links` | Search again for jobs marked "no link found" |
| `--login` / `--login indeed` | Log in to LinkedIn (or Indeed) by hand, once |

## Tracking: `tools.track`
`<job>` can be the job's number, its URL, or part of the company or title. Dates: `2026-11-09`, `11/09`, `today`, `tomorrow`, `+7`.

| Command | Meaning |
|---|---|
| `python -m tools.track` or `python -m tools.track list` | Active applications |
| `python -m tools.track list --all` | Include rejected / ghosted / withdrawn |
| `python -m tools.track list --stage interview` | One stage only |
| `python -m tools.track list --stale 14` | Applied 14+ days ago with no answer |
| `python -m tools.track show <job>` | Stage history, contact, dates, notes |
| `python -m tools.track add <job> [--date D]` | You applied outside the tool |
| `python -m tools.track screening\|interview\|offer\|rejected\|ghosted\|withdrawn <job> [--date D] [--note "..."]` | Move to that stage |
| `python -m tools.track stage <job> <stage>` | Same as the shortcuts above |
| `python -m tools.track note <job> "text"` | Add a note |
| `python -m tools.track contact <job> --name "..." --email "..."` | Save a contact |
| `python -m tools.track schedule <job> <date>` | Interview date |
| `python -m tools.track followup <job> <date>` | Follow-up reminder (shows in the summary) |
| `python -m tools.track sync` | Track jobs already marked "applied" |

## Maintenance
| Command | Meaning |
|---|---|
| `python -m core.dedupe` | Mark duplicate postings already in the database (`--dry-run` to look first) |
| `python -m tools.csv_sync` | Fill blank `status` cells in `applications.xlsx` for jobs the bot applied to or found closed (`--dry-run` first) |
| `python -m tools.clear db` | Empty the jobs database (backup copy first) |
| `python -m tools.clear docs` | Move application folders into an archive folder |
| `python -m tools.clear all` | Both |
| `python -m tools.clear <what> --dry-run` | Preview only |
| `python -m tools.clear <what> -y` | Skip the confirmation |
| `python -m tools.clear db --profile NAME` | Clear only that profile's data |
| `python -m tools.clear db --profile-all` | Clear every profile's data |
| `python -m tools.clear db --ratings` | Also delete hand ratings and calibration |
| `python -m tools.clear db --no-backup` | Skip the database backup |
| `python -m tools.check_setup` | Check files, imports, settings, Ollama, the browser, the database and git (`--quick`, `--no-ollama`, `--no-browser`) |
| `python -m db.migrate` | Copy a database from the old single-table layout into the current one |

## Diagnostics
| Command | Meaning |
|---|---|
| `python -m applying.check_linkedin_page <linkedin job url>` | What the Apply button is and what the tool would do (`--headless` hides the window) |
| `python -m applying.ats_lookup "Company" "Job title" "City, ST"` | Look for the job on the company's public Greenhouse / Lever / Ashby board |

### Model tester
Compare how different Ollama models write resumes and cover letters (more tests coming).
`python -m tools.model_test docs --profiles NAME [NAME...] --models MODEL [MODEL...] --url JOB_URL`
Use `--posting-file FILE.json` for postings you provide (see `tools/model_test/example_postings.json`), `--repeat N` to see how much one model varies, `--run NAME` to resume.
Results: `data/model_tests/<run>/`. Your jobs database and ratings are never touched.

## Notes
- **Ollama:** scoring and writing use a local model, set by `OLLAMA_MODEL` in `config\settings.py`. The environment variable of the same name overrides it for one PowerShell window only.
- **Database:** `data\jobs_db.sqlite`. All state persists between runs. Jobs are stored once; each profile scores them separately.
- **Statuses:** `scored`, `scoring_failed`, `filtered` (title, company, years or applicants), `blocked` (clearance or citizenship; no description kept), `closed` (posting closed; no description kept) and `duplicate`. A saved job found closed later gets an `applications` row with status `closed` instead; its score and documents stay.
- **Licenses and certifications:** list them in `resume.json` (`licenses`, `certifications`). A job that requires one you don't list is flagged with `⚠ license`, never dropped.
- **Never submits:** `apply_jobs.py` fills forms and stops. You review and send each one yourself.
- **More detail:** see the [README](README.md) and the pages in `docs\`.