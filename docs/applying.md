[← README](../README.md)

# Applying and tracking

## Applications list

`profiles\<name>\applications.xlsx` is the list you click through. One row per job that has documents:

`job_url, score, compat_pct, title, folder, status, company, location, mode, date, last_checked`

- **Sorted every time it is written:** newest date first, then jobs with no `status`, then highest `score`, then
  highest `compat_pct`. Jobs with a `status` sit at the bottom of their date. Sorting by hand in Excel is undone on
  the next write.
- **Links:** `job_url` links to the posting and `folder` links to that application's folder. The links are rewritten
  automatically the first time any command reads the sheet after you move the project.
- A job already in the file is never added again. A job in the list is never redone, even if you delete its folder;
  delete its row to redo it.
- `status` is yours. Write anything (applied, rejected, interview, skip). **Any non-blank status counts as handled**,
  so auto-apply skips that job.
- A job that has a folder but no row (made before the list existed) gets its row added on the next run, with the
  mode left blank.
- The compat column is the detailed percentage, or the rough one if there is no detailed one. `score` and
  `compat_pct` are stored as numbers.
- Close the file in Excel before a run, or the new rows are added on the next run. `CSV_LOG = False` turns the list
  off; `CSV_LOG_PATH` moves it.
- **File type:** `LOG_FORMAT = "xlsx"` (default) or `"csv"` in `config/settings.py`. With `"csv"` you get
  `applications.csv` instead (same sorting, no links). The first time the `.xlsx` is read, an existing
  `applications.csv` beside it is imported once and left untouched.
- `python -m tools.csv_sync` (`--dry-run` to look first) fills **blank** `status` cells with `auto-applied` or `closed`
  for jobs the database knows the bot applied to or found closed. A status you typed is never changed.
- `last_checked` is the date the availability re-check last got an answer for the job (added to older files automatically). A re-check
  that finds a job closed writes `closed` into a **blank** `status` only; `python -m tools.check --mark URL` does the same by hand.
- Documents are not made for jobs that are already in the list, that the bot applied to, or that it found closed.

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
`applications.xlsx` are never offered (naming one with `--url` still works).

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
| Workday | Walks the wizard: "Autofill with Resume", each page, Save and Continue where nothing needs you, stops at Review. Needs an account per employer: the first time, the tool pauses so you sign in or create it.
- **Apply button:** waits for Workday's Apply control, accepts links, buttons or other tags acting as buttons (ignoring cookie/privacy/"Apply Manually" items), falls back to the posting's `/apply` address, and finally pauses so you can click it yourself. |
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
- **Already handled:** a job with an application row (applied, skipped, closed) or a `status` in the applications list is skipped.

### Answering questions

Rules in `config\answers.py` (filled from `resume.json`), then answers you typed before (`data\learned_answers.json`,
shared by all profiles), then long "why us?" questions drafted by the local model (read them; they're flagged), then
it asks you in the terminal and remembers the answer. Gender, race, veteran, disability, nationality, sexual orientation
and transgender questions are answered from the `self_identification` block of `resume.json`, or "decline" if it's
empty. Start-date and notice-period questions are answered "Immediately" / "None" (edit the lists in
`config\answers.py`); date pickers are left for you. LinkedIn questions use `contact.linkedin`. Legal attestations,
signatures and consent checkboxes are **never** filled for you. A required
field that no rule can fill is listed under "NEEDS YOUR ATTENTION".

### Diagnostics

```powershell
python -m applying.check_linkedin_page <linkedin job url>            # what the Apply button is, and what the tool would do
python -m applying.ats_lookup "Company" "Job title" "City, ST"       # look for the job on the company's public board
```

`check_linkedin_page` prints a `Decision:` line (`direct`, `easy`, `apply` or `none`) and the visible buttons. It saves a
screenshot, which can show your Messaging dock, so look before sharing it.
