#!/usr/bin/env python3
"""Run a pre-registered experiment (scripts/experiments.py) and record it.

usage: scripts/run_experiments.py EXPERIMENT [--seed N] [--dry-run] [--allow-dirty]

For experiment X, writes under results/X/:
  session-<ts>.json        manifest, calibration, commit, seed, run order
  runs/<run_id>.json       tool output + metadata (one per run)
  runs/<run_id>.hist.csv   latency histogram (bench)
  runs/<run_id>.win.csv    windowed throughput (bench)
  runs/<run_id>.csv.gz     raw samples (wakebench)
  runs.jsonl               one line per completed run (append-only)

Runs execute in a seeded random order. A run whose JSON already exists is
skipped, so an interrupted session can be resumed by re-running the command.
Refuses to run with uncommitted changes to code or config, so the recorded
commit describes the code that produced the data.
"""
import gzip
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import experiments  # noqa: E402
import manifest  # noqa: E402

BUILD = ROOT / "build"
CODE_PATHS = ["src", "tests", "scripts", "config", "Makefile"]
MAX_RETRIES = 2


def sh(args, **kw):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=ROOT, **kw)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] not in experiments.EXPERIMENTS:
        sys.exit(f"usage: run_experiments.py {{{','.join(experiments.EXPERIMENTS)}}} "
                 "[--seed N] [--dry-run] [--allow-dirty]")
    exp = argv[0]
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 20261014
    dry = "--dry-run" in argv

    runs = experiments.EXPERIMENTS[exp]()
    ids = [r["id"] for r in runs]
    assert len(ids) == len(set(ids)), "duplicate run ids"
    rng = random.Random(seed)
    rng.shuffle(runs)

    if dry:
        tools = {}
        for r in runs:
            tools[r["tool"]] = tools.get(r["tool"], 0) + 1
        print(f"{exp}: {len(runs)} runs {tools}; first 3 in order:")
        for r in runs[:3]:
            print("  ", r["id"], " ".join(map(str, r["args"])))
        return

    dirty = sh(["git", "status", "--porcelain", "--", *CODE_PATHS]).stdout.strip()
    if dirty and "--allow-dirty" not in argv:
        sys.exit(f"refusing to run: uncommitted changes in code/config:\n{dirty}")
    if sh(["make", "-s", "all"]).returncode != 0:
        sys.exit("build failed")

    out = ROOT / "results" / exp
    (out / "runs").mkdir(parents=True, exist_ok=True)
    calib = json.loads(sh([BUILD / "calib", "tsc-hz"]).stdout)
    env = dict(os.environ, FL_TSC_HZ=f"{calib['tsc_hz']:.0f}")
    commit = sh(["git", "rev-parse", "HEAD"]).stdout.strip()
    session_id = time.strftime("%Y%m%dT%H%M%S")
    m = manifest.collect()
    session = {"experiment": exp, "session": session_id, "seed": seed, "commit": commit,
               "dirty": bool(dirty), "calib": calib, "manifest_start": m,
               "order": [r["id"] for r in runs]}
    session_path = out / f"session-{session_id}.json"
    session_path.write_text(json.dumps(session, indent=1) + "\n")

    todo = [r for r in runs if not (out / "runs" / f"{r['id']}.json").exists()]
    print(f"{exp}: {len(runs)} runs, {len(runs) - len(todo)} already done, {len(todo)} to go "
          f"(session {session_id}, commit {commit[:8]}, seed {seed})", flush=True)

    t0 = time.time()
    invalid = 0
    for k, r in enumerate(todo, 1):
        args = [BUILD / r["tool"], *r["args"]]
        base = out / "runs" / r["id"]
        if r["tool"] == "bench":
            args += ["--iters-per-ns", f"{calib['iters_per_ns']:.5f}",
                     "--hist-out", f"{base}.hist.csv", "--windows-out", f"{base}.win.csv"]
        else:
            args += ["--out", f"{base}.csv"]

        for attempt in range(MAX_RETRIES + 1):
            started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            p = sh(args, env=env, timeout=1800)
            ok = p.returncode == 0
            if ok:
                try:
                    data = json.loads(p.stdout)
                except json.JSONDecodeError:
                    ok = False
            if ok and r["tool"] == "bench" and not data.get("counter_ok"):
                ok = False
            if ok:
                break
            invalid += 1
            print(f"  invalid run {r['id']} (attempt {attempt + 1}): rc={p.returncode} "
                  f"{p.stderr.strip()[:200]}", flush=True)
        else:
            sys.exit(f"run {r['id']} failed {MAX_RETRIES + 1} times; stopping")

        if r["tool"] == "wakebench":
            with open(f"{base}.csv", "rb") as fi, gzip.open(f"{base}.csv.gz", "wb") as fo:
                shutil.copyfileobj(fi, fo)
            os.remove(f"{base}.csv")
        record = {"run_id": r["id"], "experiment": exp, "session": session_id, "commit": commit,
                  "machine_id": m["machine_id"], "started_at": started, "attempts": attempt + 1,
                  "meta": r["meta"], "args": [str(a) for a in r["args"]], "result": data}
        base.with_suffix(".json").write_text(json.dumps(record) + "\n")
        with open(out / "runs.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")

        el = time.time() - t0
        eta = el / k * (len(todo) - k)
        print(f"  [{k}/{len(todo)}] {r['id']}  elapsed {el/60:.1f} min, eta {eta/60:.1f} min",
              flush=True)
        time.sleep(0.3)

    session["manifest_end"] = manifest.collect()
    session["invalid_runs"] = invalid
    session["elapsed_s"] = round(time.time() - t0, 1)
    session_path.write_text(json.dumps(session, indent=1) + "\n")
    print(f"{exp}: done in {session['elapsed_s']/60:.1f} min, invalid runs re-run: {invalid}")


if __name__ == "__main__":
    main()
