"""One test cell: one profile, one model, one posting. Run by runner.py as a subprocess, not by hand.

A profile is fixed when the config loads, and the model is fixed when core.scorer is imported, so each
(profile, model) pair needs a fresh Python process. This worker calls the program's own create_application()
and only watches it (wrapping its model call and its steps to record what came back); it changes no behavior.
Writes result.json next to the documents.
"""

import argparse
import json
import time
import traceback
from pathlib import Path


def _run(args, out: Path, result: dict) -> None:
    import documents.application_maker as am
    from config.settings import ACTIVE_PROFILE
    from core.scorer import MODEL, load_resume

    result["model_used"], result["profile_used"] = MODEL, ACTIVE_PROFILE
    if ACTIVE_PROFILE != args.profile:
        raise RuntimeError(f"asked for profile '{args.profile}' but '{ACTIVE_PROFILE}' was loaded")

    job = json.loads(Path(args.job_file).read_text(encoding="utf-8"))
    resume = load_resume()
    mode, why = am.choose_mode(job, args.mode)
    result.update(mode=mode, mode_why=why)

    calls = result["ask_calls"] = []
    kinds = {id(am.TAILOR_SCHEMA): "tailor", id(am.LETTER_SCHEMA): "letter", id(am.BRIDGE_SCHEMA): "bridge"}
    real_ask = am._ask

    def watched_ask(prompt, schema):
        record = {"kind": kinds.get(id(schema), "other"), "prompt_chars": len(prompt)}
        calls.append(record)
        started = time.time()
        try:
            record["response"] = real_ask(prompt, schema)
            return record["response"]
        except Exception as e:
            record["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            record["seconds"] = round(time.time() - started, 2)

    captured = {}

    def watch(name):
        real = getattr(am, name)

        def wrapper(*a, **k):
            captured[name] = real(*a, **k)
            return captured[name]
        setattr(am, name, wrapper)

    am._ask = watched_ask
    for name in ("suggest_bridges", "tailor_resume", "write_cover_letter"):
        watch(name)

    folder = am.create_application(job, out_root=out / "docs", force=True, mode=args.mode, review=False)

    tailored = captured.get("tailor_resume") or {}
    paragraphs, warnings = captured.get("write_cover_letter") or ([], [])
    result.update(
        folder=str(folder.relative_to(out)) if folder else None,
        files=sorted(f.name for f in folder.iterdir()) if folder else [],
        bridges=captured.get("suggest_bridges") or [],
        tailored=tailored,
        # the program silently keeps your original summary when the model's is rejected; show that here
        summary_fallback=bool(tailored) and mode != "boilerplate" and tailored.get("summary") == resume.get("summary", ""),
        paragraphs=paragraphs,
        letter_words=len(" ".join(paragraphs).split()),
        warnings=warnings,
    )


def main() -> None:
    p = argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument("--profile", required=True)   # read by the config loader from the command line
    p.add_argument("--job-file", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--mode", default="standard")
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"profile": args.profile, "mode_requested": args.mode, "ok": False, "error": None}
    started = time.time()
    try:
        _run(args, out, result)
        result["ok"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
    finally:
        result["seconds"] = round(time.time() - started, 1)
        (out / "result.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
