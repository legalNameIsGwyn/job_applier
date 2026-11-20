[← README](../README.md)

# Settings (the `config/` folder)

**Every editable setting lives in `config/`, and a profile can override most of them.** `profiles\<name>\resume.json`
is the one exception. The code reads these files when it starts, so restart a running script after editing.

| File | What's in it |
|---|---|
| `config/settings.py` | `DEFAULT_PROFILE`, `MIN_SCORE`; file locations; what to search (`SITES`, `SEARCH_TERMS`, `LOCATION`, `RESULTS_WANTED`, `HOURS_OLD`); the model, timeouts and temperatures; scraping delays and rate-limit backoff; document options (`MAKE_DOCS`, `MAX_DOCS_PER_RUN`, `DOC_WINDOW_DAYS`, `MAX_PROJECTS`, `FONT`, greeting and sign-off); file name templates; score blending and rating options (`DEFAULT_MODEL_WEIGHT`, `MIN_RATINGS`, `FULL_TRUST_RATINGS`); compatibility (`COMPAT_DETAIL`, `HARD_REQ_CAP`, `HARD_REQ_KINDS`, `DROP_ON_MISSING_KINDS`); tailoring (`TAILOR_MODE`, `TAILOR_AUTO_BRIDGE_BELOW`, `TAILOR_AUTO_BOILERPLATE_BELOW`, `MAX_BRIDGE_LINES`); the CSV (`CSV_LOG`, optional `CSV_LOG_PATH`); summary options; the applicant filter (`MAX_APPLICANTS`, `KEEP_UNKNOWN_APPLICANTS`) |
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

## Console colors

Colors only appear in a terminal, never when `NO_COLOR` is set. `CONSOLE_COLOR` in `config/settings.py` forces them on or off, and `CONSOLE_LINKS` controls the clickable "open posting" link (otherwise the full URL is shown).

To change a color:

1. `python -m core.console --colors` lists the color names (add `all` for the numbers 0-255).
2. In `config/settings.py`, edit `CONSOLE_COLORS` (parts of the output) or `CONSOLE_TAG_COLORS` (the `[TAG]` labels). A value is a name, a number 0-255, or `"#rrggbb"`. `"auto"` (suitability, compat) means green / yellow / gray by how high the number is.
3. `python -m core.console` prints a sample of every kind of output so you can check the result without running the pipeline.

A line you delete from either dictionary falls back to its default. A profile can override them like any other setting.

The job block starts with a header: title, then company and location, then `suitability` (the 0-10 score), `compat` (the detailed percentage; the rough one only when there is no detailed one), the site, the documents mode and the pay. A hard requirement you don't meet is shown as `✗ blocker` under it, and a required license or certification you don't list as `⚠ license`. The lines below only add what the header doesn't say: `about`, `requires`, `has`, `gaps`, `notes` and the link. A requirement you're missing is listed once, under `gaps`.
