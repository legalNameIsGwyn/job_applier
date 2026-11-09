# Job Scraper Command Reference

## Main Pipeline
| Command | Description |
|---------|-------------|
| `python main.py` | Full pipeline: scrape LinkedIn/Indeed → score with Ollama → save to DB |
| `python main.py --top N` | Run full pipeline; then generate tailored resume/cover letter for top N matches |
| `python main.py --min-score X` | Filter jobs to minimum score (default 6) before generating docs |
| `python main.py --days D` | Only consider jobs scraped in the last D days (default 7) |

## Database & Jobs View
| Command | Description |
|---------|-------------|
| `python show_jobs.py --top N` | List best-scoring jobs from DB (N rows, default 10) |
| `python show_jobs.py --bottom N` | List filtered-out/rejected jobs (N rows) |
| `python show_jobs.py --search "text"` | Filter shown results by keyword search |

## Rescoring & Ratings
| Command | Description |
|---------|-------------|
| `python rescore.py` | Re-score all jobs in DB with current model/prompts |
| `python rescore.py --failed-only` | Re-score only jobs whose previous scoring failed |
| `python rescore.py --include-filtered` | Also re-check filtered jobs (may now pass rules) |
| `python rescore.py -n 20` | Limit to at most 20 jobs (oldest first) |
| `python rescore.py --url <link>` | Re-score just one specific job URL |
| `python rating.py` | Interactive UI: hand-rate top N jobs to calibrate scores |
| `python calibration.py` | View/edit current score calibration values (JSON view) |

## Application Generation
| Command | Description |
|---------|-------------|
| `python application_maker.py --top N` | Generate tailored resume + cover letter for top N scored jobs |
| `python application_maker.py --min-score X` | Only generate docs for jobs scoring >= X |
| `python application_maker.py --days D` | Only consider jobs from last D days |
| `python application_maker.py --url <link>` | Generate for one specific job URL |
| `python application_maker.py --force` | Regenerate even if folder already exists |

## Configuration & Utilities
| Command | Description |
|---------|-------------|
| `python dedupe.py` | List/view duplicate job detection logic output |
| `python generic.py` | Generic utilities and helpers (scraping, parsing) |

## Notes:
- **Ollama required**: All scoring/generating uses local Ollama (`qwen2.5:7b`) via environment variable `OLLAMA_MODEL`.
- **Database**: SQLite file at `data/jobs_db.sqlite` — all state persists between runs.
- **Documents**: Output folder: `data/applications/`; folder name: `{company}_{title}_{hash}`.
- **Resume source**: Always read from `data/resume.json`; not in config files.
