# Job Scraper: Command Reference

Run everything from the project root (`job_scraper\`). Settings live in `config\`; **`main.py` has no flags**, so
change what it searches, scores and generates in `config\settings.py`. Your resume is `data\resume.json`.

## Daily use
| Command | What it does |
|---|---|
| `python main.py` | Scrape LinkedIn/Indeed, filter, score with Ollama, save to the database, write resume + cover letter for the best matches, then print the summary |
| `python summary.py` | What's new, what's ready to apply to, and what needs you |
| `python show_jobs.py` | Top 10 scored jobs |
| `python apply_jobs.py --list` | Which top jobs can be filled, and which can't and why |
| `python apply_jobs.py --top 3` | Fill the 3 best applications in Firefox (never submits) |
| `python track.py` | Where each application stands |
| `python stats.py` | What's working: funnel, score vs outcome, breakdowns, trends |

## Viewing jobs: `show_jobs.py`
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
| `python summary.py --days D --top N --min-score X` | Window, number of best matches and score cutoff (defaults in `config\settings.py`) |
| `python summary.py --html` | Also save `reports\summary_<date>.html` and open it |
| `python stats.py --days D` | Only the last D days |
| `python stats.py --section funnel,score,breakdown,trends` | Only the sections you list |

## Re-scoring: `rescore.py`
| Flag | Meaning |
|---|---|
| *(none)* | Re-score every scored job (asks to confirm) |
| `--failed-only` | Only jobs whose scoring failed |
| `--include-filtered` | Also re-check filtered jobs against the current rules |
| `-n N` / `--limit N` | At most N jobs |
| `--url URL` | Just one job |
| `-y` / `--yes` | Don't ask for confirmation |

## Rating and calibration: `rating.py`
| Flag | Meaning |
|---|---|
| *(none)* | Rate a batch of jobs you haven't rated yet |
| `-n N` | Jobs per batch |
| `--latest-only` | Tune using only this batch of ratings |
| `--all-ratings` | Tune using every rating (overrides the setting) |
| `--report` | Show the current calibration and exit |
| `--reset` | Delete all ratings and fits (asks you to type RESET) |

## Documents: `documents\application_maker.py`
Run it as a module, because it lives in a package folder:

| Command | Meaning |
|---|---|
| `python -m documents.application_maker --top N` | Resume + cover letter for the top N scored jobs |
| `python -m documents.application_maker --url URL` | One job already in the database |
| `python -m documents.application_maker --top N --min-score X` | Score cutoff (default 6) |
| `python -m documents.application_maker --top N --days D` | Only jobs scraped in the last D days |
| `python -m documents.application_maker --top N --force` | Regenerate even if the folder exists |

Output goes to `data\applications\<company>_<title>_<hash>\` (resume, cover letter, `notes.txt`).

## Applying: `apply_jobs.py`
| Flag | Meaning |
|---|---|
| `--list` | Show what would be filled; open nothing |
| `--top N` | At most N jobs this run |
| `--min-score X` / `--days D` | Who qualifies for this run |
| `--url URL` | One job already in the database |
| `--include-opened` | Also offer jobs you opened but didn't finish |
| `--set-url JOB_URL APPLY_URL` | Give a job's employer link by hand |
| `--recheck-links` | Search again for jobs marked "no link found" |
| `--login` / `--login indeed` | Log in to LinkedIn (or Indeed) by hand, once |

## Tracking: `track.py`
`<job>` can be the job's number, its URL, or part of the company or title. Dates: `2026-11-09`, `11/09`, `today`, `tomorrow`, `+7`.

| Command | Meaning |
|---|---|
| `python track.py` or `python track.py list` | Active applications |
| `python track.py list --all` | Include rejected / ghosted / withdrawn |
| `python track.py list --stage interview` | One stage only |
| `python track.py list --stale 14` | Applied 14+ days ago with no answer |
| `python track.py show <job>` | Stage history, contact, dates, notes |
| `python track.py add <job> [--date D]` | You applied outside the tool |
| `python track.py screening\|interview\|offer\|rejected\|ghosted\|withdrawn <job> [--date D] [--note "..."]` | Move to that stage |
| `python track.py stage <job> <stage>` | Same as the shortcuts above |
| `python track.py note <job> "text"` | Add a note |
| `python track.py contact <job> --name "..." --email "..."` | Save a contact |
| `python track.py schedule <job> <date>` | Interview date |
| `python track.py followup <job> <date>` | Follow-up reminder (shows in the summary) |
| `python track.py sync` | Track jobs already marked "applied" |

## Maintenance
| Command | Meaning |
|---|---|
| `python dedupe.py` | Mark duplicate postings already in the database (`--dry-run` to look first) |
| `python clear.py db` | Empty the jobs database (backup copy first) |
| `python clear.py docs` | Move application folders into an archive folder |
| `python clear.py all` | Both |
| `python clear.py <what> --dry-run` | Preview only |
| `python clear.py <what> -y` | Skip the confirmation |
| `python clear.py db --ratings` | Also delete hand ratings and calibration |
| `python clear.py db --no-backup` | Skip the database backup |
| `python check_setup.py` | Check files, imports, settings, Ollama, Firefox, database and git (`--quick`, `--no-ollama`, `--no-browser`) |
| `python fix_imports.py` | Repair imports after moving files (`--dry-run` first) |

## Diagnostics
| Command | Meaning |
|---|---|
| `python -m applying.check_linkedin_page <linkedin job url>` | What the Apply button is and what the tool would do (`--headless` hides the window) |
| `python -m applying.ats_lookup "Company" "Job title" "City, ST"` | Look for the job on the company's public Greenhouse / Lever / Ashby board |

## Notes
- **Ollama:** scoring and writing use a local model, set by `OLLAMA_MODEL` in `config\settings.py`. The environment variable of the same name overrides it for one PowerShell window only.
- **Database:** `data\jobs_db.sqlite`. All state persists between runs.
- **Files inside `core\`, `applying\` and `documents\`** are libraries; run the ones with a command above using `python -m folder.file`, from the project root.
- **Never submits:** `apply_jobs.py` fills forms and stops. You review and send each one yourself.