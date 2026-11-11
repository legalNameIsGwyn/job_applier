"""Track your applications after you apply: stage, contact, dates, notes.

    python track.py                         # active applications (same as: list)
    python track.py list --all              # include rejected / ghosted / withdrawn
    python track.py list --stage interview
    python track.py list --stale 14         # applied 14+ days ago with no answer
    python track.py show acme               # everything about one application

    python track.py add acme                # you applied (outside the tool, or the tool missed it)
    python track.py add acme --date 11/03   # ...on a past day
    python track.py screening acme          # they replied / phone screen
    python track.py interview acme --date 11/12 --note "technical, 45 min"
    python track.py offer acme
    python track.py rejected acme           # also: ghosted, withdrawn
    python track.py stage acme interview    # same as the shortcuts above

    python track.py note acme "Recruiter said decision by Friday"
    python track.py contact acme --name "Sam Lee" --email sam@acme.com
    python track.py schedule acme 11/15     # interview date
    python track.py followup acme +7        # remind me in 7 days (shown in list and summary)
    python track.py sync                    # start tracking jobs the apply tool already marked "applied"

<job> can be the job's number (the # column), its URL, or part of the company / title.
Dates: 2026-11-09, 11/09, 11/09/2026, today, tomorrow, +7 (days from now).
"""

import argparse
import sys

import core.tracking as T


def _pick(ref: str) -> str:
    url, matches = T.resolve(ref)
    if url:
        return url
    if not matches:
        sys.exit(f"[TRACK] No job matches '{ref}'. Use the # from `python show_jobs.py`/`track.py list`, a URL, or part of the company.")
    print(f"[TRACK] '{ref}' matches {len(matches)} jobs. Be more specific (use the # number):")
    for r in matches:
        print(f"   #{r['id']:<5} {r['company']} - {r['title']}")
    sys.exit(1)


def _title(url: str) -> str:
    conn = T.connect()
    try:
        r = conn.execute("SELECT id, title, company FROM jobs WHERE job_url = ?", (url,)).fetchone()
    finally:
        conn.close()
    return f"#{r['id']} {r['company']} - {r['title']}" if r else url


def _row(r) -> str:
    when = r["updated_on"] or r["applied_on"] or ""
    flag = ""
    if r["follow_up_on"] and r["follow_up_on"] <= T.today() and r["stage"] not in T.ENDINGS + ("offer",):
        flag = "  << follow up"
    elif r["follow_up_on"]:
        flag = f"  (follow up {r['follow_up_on']})"
    if r["interview_on"] and r["stage"] in ("screening", "interview"):
        flag += f"  [interview {r['interview_on']}]"
    num = f"#{r['job_id']}" if r["job_id"] else "-"
    return f"{num:<6}{r['stage']:<10}{when:<11}{(r['company'] or '?')[:24]:<25}{(r['title'] or r['job_url'])[:38]}{flag}"


def cmd_list(args):
    T.sync_applied()
    rows = T.get_tracked(stage=args.stage, stale_days=args.stale, active_only=not (args.all or args.stage))
    if not rows:
        print("[TRACK] Nothing tracked yet." if not (args.stage or args.stale) else "[TRACK] Nothing matches.")
        return
    print(f"{'#':<6}{'stage':<10}{'updated':<11}{'company':<25}title")
    for r in rows:
        print(_row(r))
    due = [r for r in T.due_follow_ups()]
    if due and not args.stale:
        print(f"\n{len(due)} follow-up(s) due.")


def cmd_show(args):
    url = _pick(args.job)
    conn = T.connect()
    try:
        t = conn.execute("SELECT * FROM tracking WHERE job_url = ?", (url,)).fetchone()
    finally:
        conn.close()
    print(_title(url))
    print(f"  {url}")
    if not t:
        print("  Not tracked yet. Start with: python track.py add", args.job)
        return
    print(f"  Stage: {t['stage']}   applied {t['applied_on']}   updated {t['updated_on']}")
    print(f"  Applied via: {t['site'] or '?'} / {t['ats'] or '?'}   score then: "
          f"{'' if t['score_at_apply'] is None else format(t['score_at_apply'], 'g')}")
    if t["folder"]:
        print(f"  Documents: {t['folder']}")
    if t["contact_name"] or t["contact_email"]:
        print(f"  Contact: {t['contact_name'] or ''} {t['contact_email'] or ''}".rstrip())
    if t["interview_on"]:
        print(f"  Interview: {t['interview_on']}")
    if t["follow_up_on"]:
        print(f"  Follow up: {t['follow_up_on']}")
    print("  History:")
    for e in T.get_events(url):
        print(f"    {e['on_date']}  {e['stage']}" + (f"  - {e['note']}" if e["note"] else ""))
    if t["notes"]:
        print("  Notes:\n    " + t["notes"].replace("\n", "\n    "))


def cmd_add(args):
    url = _pick(args.job)
    if T.log_applied(url, on_date=T.parse_date(args.date), note=args.note, ats=args.ats):
        print(f"[TRACK] Tracking: {_title(url)}")
    else:
        print(f"[TRACK] Already tracked: {_title(url)}")


def _set(url, stage, date_text, note):
    try:
        T.set_stage(url, stage, T.parse_date(date_text), note)
    except KeyError:   # not tracked yet: start it so one command is enough
        T.log_applied(url)
        T.set_stage(url, stage, T.parse_date(date_text), note)
    print(f"[TRACK] {_title(url)} -> {stage}")


def cmd_stage(args):
    _set(_pick(args.job), args.stage, args.date, args.note)


def cmd_note(args):
    url = _pick(args.job)
    _ensure(url)
    T.append_note(url, args.text)
    print(f"[TRACK] Note saved for {_title(url)}")


def _ensure(url):
    T.log_applied(url)   # no-op if already tracked


def cmd_contact(args):
    url = _pick(args.job)
    _ensure(url)
    T.update_fields(url, contact_name=args.name, contact_email=args.email)
    print(f"[TRACK] Contact saved for {_title(url)}")


def cmd_schedule(args):
    url = _pick(args.job)
    _ensure(url)
    T.update_fields(url, interview_on=T.parse_date(args.date))
    print(f"[TRACK] Interview date set for {_title(url)}")


def cmd_followup(args):
    url = _pick(args.job)
    _ensure(url)
    T.update_fields(url, follow_up_on=T.parse_date(args.date))
    print(f"[TRACK] Follow-up date set for {_title(url)}")


def cmd_sync(args):
    n = T.sync_applied()
    print(f"[TRACK] Started tracking {n} application(s) already marked applied." if n else
          "[TRACK] Nothing to sync.")


def main():
    p = argparse.ArgumentParser(description="Track applications after you apply.", epilog=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("list", help="show tracked applications")
    s.add_argument("--all", action="store_true", help="include rejected / ghosted / withdrawn")
    s.add_argument("--stage", choices=T.STAGES)
    s.add_argument("--stale", type=int, metavar="DAYS", help="applied DAYS+ ago, no answer yet")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="everything about one application")
    s.add_argument("job")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("add", help="start tracking an application")
    s.add_argument("job")
    s.add_argument("--date", help="when you applied (default today)")
    s.add_argument("--note")
    s.add_argument("--ats", help="applicant system / where, if known")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("stage", help="set the stage")
    s.add_argument("job")
    s.add_argument("stage", choices=T.STAGES)
    s.add_argument("--date", help="when it happened (default today)")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_stage)

    for stage in T.STAGES[1:]:   # shortcuts: python track.py interview acme
        s = sub.add_parser(stage, help=f"set the stage to {stage}")
        s.add_argument("job")
        s.add_argument("--date", help="when it happened (default today)")
        s.add_argument("--note")
        s.set_defaults(fn=cmd_stage, stage=stage)

    s = sub.add_parser("note", help="add a note")
    s.add_argument("job")
    s.add_argument("text")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("contact", help="save a recruiter / contact")
    s.add_argument("job")
    s.add_argument("--name")
    s.add_argument("--email")
    s.set_defaults(fn=cmd_contact)

    s = sub.add_parser("schedule", help="set the interview date")
    s.add_argument("job")
    s.add_argument("date")
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("followup", help="set a follow-up reminder date")
    s.add_argument("job")
    s.add_argument("date")
    s.set_defaults(fn=cmd_followup)

    s = sub.add_parser("sync", help="track jobs already marked applied by apply_jobs.py")
    s.set_defaults(fn=cmd_sync)

    args = p.parse_args()
    if not args.cmd:
        args = p.parse_args(["list"])
    try:
        args.fn(args)
    except ValueError as e:
        sys.exit(f"[TRACK] {e}")


if __name__ == "__main__":
    main()
