"""Apply to several jobs at once: one terminal window and one browser window per job.

This terminal (where you ran  python apply_jobs.py) only shows a short summary. Each job gets its own
window with the full details. In that window the tool fills the form, and then waits for you:

  - "ready: review the form and press Submit"   nothing needed you; check the browser window and submit it
  - "ready: N field(s) need you, then submit"   fill in what is listed under NEEDS YOUR ATTENTION, then submit
  - "waiting for your answer"                   the tool asked a question in that window; type the answer

When you have submitted (or decided not to), answer the last question in that window:
a = I submitted it,  s = skip this job for good,  Enter = not yet. The window then closes by itself.
It NEVER clicks Submit.

How it works: the main program writes the documents (one at a time, because the local model does the
writing), then starts at most PARALLEL_JOBS windows. Each runs  python -m applying.worker <job file>  with
its own copy of your saved browser profile, because one profile can't be open in two browsers at once.
When a window finishes, the next job starts. Copies are deleted afterwards, so a site account you create
inside one of these windows (a Workday account, for example) is not kept: create it once with
python apply_jobs.py --url <job> --parallel 1  which uses your real profile.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from config.settings import PROJECT_DIR
import config.apply_settings as _cfg

PROJECT_DIR = Path(PROJECT_DIR)
RUNS_DIR = PROJECT_DIR / "data" / "apply_runs"
PARALLEL_PROFILE_DIR = Path(getattr(_cfg, "PARALLEL_PROFILE_DIR", PROJECT_DIR / "browser_profile_workers"))
# Things in a browser profile that are caches or locks: not needed, and they make copying slow or fail.
PROFILE_SKIP = shutil.ignore_patterns(
    "Cache", "Cache2", "cache2", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache", "Crashpad",
    "crashes", "minidumps", "Singleton*", "lock", ".parentlock", "parent.lock", "*.lock", "*.tmp")


# ------------------------------------------------------------------------------ status files


def _write_status(path: Path, **fields) -> None:
    """Update a job's status file (written atomically so the main window never reads half of it)."""
    data = _read_status(path)
    data.update(fields, updated=time.time())
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:   # the reader has it open for a moment
            time.sleep(0.1)


def _read_status(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


# ------------------------------------------------------------------- main window: launcher


def _spawn(spec: Path):
    """Start one worker in a NEW console window (Windows)."""
    return subprocess.Popen([sys.executable, "-m", "applying.worker", str(spec)], cwd=str(PROJECT_DIR),
                            creationflags=subprocess.CREATE_NEW_CONSOLE)


def launch_all(ready: list, parallel: int, prepare=None, poll: float = 2.0, spawn=None) -> list[dict]:
    """Open every (job, link, ats) in ready, `parallel` at a time, and show a summary here.

    prepare(job) is called first for each job, one after another (it makes the resume and cover letter).
    Returns one dict per job with its final state.
    """
    spawn = spawn or _spawn
    if spawn is _spawn and os.name != "nt":
        print("[APPLY] Separate terminal windows are only set up for Windows. Use  --parallel 1  here.")
        return []
    run_dir = RUNS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    total = len(ready)
    parallel = max(1, min(parallel, total))
    print(f"[APPLY] {total} application(s), {parallel} window(s) at a time. Details are in each window; "
          f"this one shows progress.\n")

    queue = []
    for n, (job, link, ats) in enumerate(ready, start=1):
        label = f"{job['title'][:38]} - {job['company'][:22]}"
        if prepare:
            print(f"[APPLY] Documents {n}/{total}: {label}")
            try:
                prepare(job)
            except Exception as e:
                print(f"  Couldn't make the documents ({type(e).__name__}: {e}). Skipping this job.")
                continue
        spec, status = run_dir / f"job{n}.json", run_dir / f"job{n}.status.json"
        spec.write_text(json.dumps({"job": job, "link": link, "ats": ats, "n": n, "total": total,
                                    "status_file": str(status), "run": run_dir.name}), encoding="utf-8")
        _write_status(status, state="queued", text="waiting for a free window")
        queue.append({"n": n, "label": label, "spec": spec, "status": status})

    running, shown, results = {}, {}, []
    try:
        while queue or running:
            while queue and len(running) < parallel:
                item = queue.pop(0)
                running[item["n"]] = (spawn(item["spec"]), item)
                print(f"[APPLY] Opened window {item['n']}/{total}: {item['label']}")
            for n, (proc, item) in list(running.items()):
                st = _read_status(item["status"])
                text = st.get("text", "")
                if text and shown.get(n) != text:
                    print(f"  [{n}/{total}] {item['label']}: {text}")
                    shown[n] = text
                if proc.poll() is not None:
                    del running[n]
                    st = _read_status(item["status"])
                    if st.get("state") not in ("done", "error"):
                        print(f"  [{n}/{total}] {item['label']}: window closed before finishing (not recorded)")
                        st = {"state": "closed", "text": "window closed before finishing"}
                    results.append({"n": n, "label": item["label"], **st})
            time.sleep(poll)
    except KeyboardInterrupt:
        print("\n[APPLY] Stopped watching. Windows that are already open keep running on their own.")
        return results

    print(f"\n[APPLY] Finished {len(results)} application(s):")
    for r in sorted(results, key=lambda r: r["n"]):
        print(f"  {r['n']}. {r['label']}: {r.get('text', r.get('state'))}")
    return results


# -------------------------------------------------------------------- job window: worker


def _set_title(title: str) -> None:
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


def _copy_profile(src: Path, dst: Path) -> None:
    """A private copy of your saved browser profile (logins) for this window."""
    src, dst = Path(src), Path(dst)
    shutil.rmtree(dst, ignore_errors=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        return
    try:
        shutil.copytree(src, dst, ignore=PROFILE_SKIP, dirs_exist_ok=True)
    except shutil.Error as e:   # a few locked files: the rest is copied, which is what matters
        print(f"  (couldn't copy {len(e.args[0])} profile file(s); continuing)")


def worker_main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    job, link, ats = spec["job"], spec["link"], spec["ats"]
    status_file = Path(spec["status_file"])
    n, total = spec["n"], spec["total"]
    label = f"{job['title'][:45]} - {job['company'][:25]}"

    def status(state: str, text: str) -> None:
        _write_status(status_file, state=state, text=text)

    _set_title(f"[{n}/{total}] {job['company'][:30]}")
    print(f"{'=' * 60}\n[{n}/{total}] {job['title']} - {job['company']}  (score {job['match_score']:g})\n  {link}\n{'=' * 60}")
    status("working", "starting a browser window")

    profile = PARALLEL_PROFILE_DIR / f"{spec['run']}_job{n}"
    result, failed = None, False
    try:
        import apply_jobs as aj                      # the same filling code the single-window mode uses
        from playwright.sync_api import sync_playwright

        attention = {"n": 0}
        show_report = aj.print_report

        def report(r) -> None:
            show_report(r)
            attention["n"] = len(r.attention)
            status("working", f"filled a page ({attention['n']} field(s) need you)" if attention["n"] else "filled a page")

        aj.print_report = report                     # apply_to_job looks this name up when it runs

        def ask(prompt: str = "") -> str:
            if "submit it yourself" in prompt:       # the final question: the form is waiting for you
                text = (f"ready: {attention['n']} field(s) need you, then submit" if attention["n"]
                        else "ready: review the form and press Submit")
                _set_title(f"[{n}/{total}] READY - {job['company'][:28]}")
            else:
                text = "waiting for your answer in its window"
                _set_title(f"[{n}/{total}] QUESTION - {job['company'][:26]}")
            status("waiting", text)
            try:
                return input(prompt)
            finally:
                status("working", "working")

        print("  Copying your browser profile...")
        _copy_profile(aj.BROWSER_PROFILE_DIR, profile)
        status("working", "filling the form")
        with sync_playwright() as p:
            context = aj._open_profile(p, profile)
            try:
                result = aj.apply_to_job(context, job, link, ats, ask=ask)
            finally:
                context.close()

        aj.record_application(job["job_url"], result, apply_url=link, ats=ats)
        if result == "applied":
            try:
                import core.tracking as tracking
                from documents.application_maker import job_folder
                tracking.log_applied(job["job_url"], ats=ats, folder=job_folder(job).name)
            except Exception as e:                   # tracking must never break applying
                print(f"  (couldn't start tracking: {e})")
        status("done", {"applied": "applied (recorded)", "skipped": "skipped for good", "opened": "left open, not finished",
                        "closed": "posting is closed"}.get(result, result))
        print(f"\n  Recorded as: {result}")
    except KeyboardInterrupt:
        status("error", "stopped with Ctrl-C (not recorded)")
        failed = True
    except Exception as e:
        status("error", f"failed: {type(e).__name__}: {e}")
        print(f"\n  Failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        failed = True
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    if failed:
        try:
            input("\nPress Enter to close this window: ")
        except (EOFError, KeyboardInterrupt):
            pass
        return 1
    print("  Closing this window...")
    time.sleep(3)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("This is started by  python apply_jobs.py --parallel N ; it is not run by hand.")
    sys.exit(worker_main(sys.argv[1]))
