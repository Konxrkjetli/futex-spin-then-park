#!/usr/bin/env python3
"""Harness validation (BUILD_PHASE.md section 7.2).

Runs every check, stores raw outputs in results/validation/validation-<ts>.json
and writes a readable report to docs/validation.md. Data produced here is
pilot/validation data only and is never part of the experiment dataset.

Uses only the Python standard library.
usage: scripts/validate.py [--quick]
"""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
QUICK = "--quick" in sys.argv
RUNS_REPEAT = 3 if QUICK else 5
DUR_MS = 1000 if QUICK else 2000

# Proposed run-to-run threshold (BUILD_PHASE.md 7.2 asks for one to be set
# and recorded): coefficient of variation of throughput across repeats.
CV_THRESHOLD = 0.05

checks = []
raw = {}


def run(args, timeout=600):
    args = [str(a) for a in args]
    r = subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=timeout)
    if r.returncode not in (0,):
        raise RuntimeError(f"{' '.join(map(str, args))} exited {r.returncode}: {r.stderr.strip()}")
    return r.stdout


def run_json(args):
    return json.loads(run(args))


def bench(*args):
    d = run_json([str(BUILD / "bench"), *map(str, args)])
    raw.setdefault("bench_runs", []).append(d)
    return d


def check(name, criterion, measured, ok, note=""):
    checks.append({"check": name, "criterion": criterion, "measured": measured,
                   "pass": bool(ok), "note": note})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {measured}", flush=True)


def main():
    t_start = time.time()
    raw["manifest"] = json.loads(run([sys.executable, str(ROOT / "scripts" / "manifest.py"), "--stdout"]))
    ipn = run_json([str(BUILD / "calib"), "tsc-hz"])
    raw["tsc_hz"] = ipn
    # One calibration shared by every run in this validation.
    common = ["--iters-per-ns", f"{ipn['iters_per_ns']:.5f}", "--duration-ms", DUR_MS]

    # 1. Correctness
    out = run([str(BUILD / "test_locks")])
    raw["test_locks"] = out
    last = out.strip().splitlines()[-1]
    check("Lock correctness (counter exact, no overlap, all locks, T=2/8/32)",
          "all runs PASS", last, last.startswith("ALL PASSED"))

    tsan = ROOT / "build-tsan" / "test_locks"
    r = subprocess.run([str(tsan), "--total", "200000", "--watchdog", "300"],
                       capture_output=True, text=True, cwd=ROOT, timeout=900)
    warnings = r.stdout.count("WARNING: ThreadSanitizer") + r.stderr.count("WARNING: ThreadSanitizer")
    raw["tsan"] = {"returncode": r.returncode, "stdout_tail": r.stdout[-2000:], "warnings": warnings}
    check("ThreadSanitizer", "exit 0 and zero TSan warnings",
          f"exit={r.returncode}, warnings={warnings}", r.returncode == 0 and warnings == 0)

    # 2. Timer overhead and TSC consistency
    timer = run_json([str(BUILD / "calib"), "timer"])
    raw["timer"] = timer
    pair = timer["tsc_ordered_pair_ns"]["median"]
    check("Timer overhead measured", "recorded (no threshold)",
          f"ordered TSC pair median {pair:.1f} ns (min {timer['tsc_ordered_pair_ns']['min']:.1f}); "
          f"clock_gettime {timer['clock_gettime_ns']:.1f} ns; pause {timer['pause_ns']:.1f} ns; "
          f"futex_wake (no waiter) {timer['futex_wake_nowaiter_ns']:.0f} ns", True)

    syncs = [run_json([str(BUILD / "calib"), "tsc-sync", a, b]) for a, b in (("2", "3"), ("2", "4"), ("2", "14"))]
    raw["tsc_sync"] = syncs
    check("TSC consistent across CPUs", "both ping-pong minima > 0 for every pair",
          "; ".join(f"{s['cpu_a']}->{s['cpu_b']} skew {s['skew_estimate_ns']:.1f} ns, one-way {s['one_way_ns']:.1f} ns"
                    for s in syncs),
          all(s["consistent"] for s in syncs))

    # 3. Work loop accuracy (also proves the loop is not optimised away)
    work = run_json([str(BUILD / "calib"), "work"])
    raw["work"] = work
    # Tolerance revised after the first validation run: the timer overhead
    # being subtracted is itself uncertain by ~10 ns (pair cost 10-20 ns), so
    # the bound is 5% + 10 ns rather than a flat 5%.
    ok = all(abs(p["median_ns"] - pair - p["target_ns"]) <= 0.05 * p["target_ns"] + 10
             for p in work["points"] if p["target_ns"] >= 100)
    check("Calibrated work loop accurate and not optimised away",
          "|measured - timer overhead - target| <= 5% of target + 10 ns, for targets >= 100 ns",
          ", ".join(f"{p['target_ns']:g}ns->{p['median_ns']:.0f}ns" for p in work["points"]),
          ok, "tolerance revised after first run (timer uncertainty); boost on adds frequency drift")

    # 4. Single-thread, no-lock throughput
    d = bench("--lock", "none", "--threads", 1, "--hold-ns", 100, "--think-ns", 100, *common)
    d_nt = bench("--lock", "none", "--threads", 1, "--hold-ns", 100, "--think-ns", 100, "--no-timing", *common)
    ideal = 1e9 / 200
    eff, eff_nt = d["throughput_ops_s"] / ideal, d_nt["throughput_ops_s"] / ideal
    check("Single-thread no-lock throughput sensible",
          "0.7 <= throughput / (1 / (hold + think)) <= 1.0",
          f"{d['throughput_ops_s']/1e6:.2f} M ops/s = {eff:.2f} of ideal "
          f"({eff_nt:.2f} without per-op timestamps)", 0.7 <= eff <= 1.0)

    # 5. Throughput tracks hold time (saturated spin lock: throughput ~ 1/hold)
    effs = []
    for hold in (1000, 2000, 4000, 8000):
        d = bench("--lock", "spin", "--threads", 4, "--hold-ns", hold, "--think-ns", 0, *common)
        effs.append((hold, d["throughput_ops_s"] * hold / 1e9))
    check("Throughput proportional to hold time (spin, T=4, think 0)",
          "throughput x hold in [0.80, 1.0] at every hold time",
          ", ".join(f"{h}ns:{e:.3f}" for h, e in effs), all(0.80 <= e <= 1.0 for _, e in effs))

    # 6. Repeatability
    drift, temps = [], []
    for spec in ("park", "stp:1000"):
        thr, p99 = [], []
        for seed in range(RUNS_REPEAT):
            d = bench("--lock", spec, "--threads", 8, "--hold-ns", 1000, "--think-ns", 1000,
                      "--seed", seed + 1, *common)
            thr.append(d["throughput_ops_s"])
            p99.append(d["phases"][0]["lat_ns"]["p99"])
            drift.append(d["iters_per_ns_after"] / d["iters_per_ns"] - 1)
            temps.append(d["temp_c_after"])
        cv = statistics.stdev(thr) / statistics.mean(thr)
        cv99 = statistics.stdev(p99) / statistics.mean(p99)
        check(f"Run-to-run variation ({spec}, T=8, hold 1 us, think 1 us, {RUNS_REPEAT} runs)",
              f"throughput CV <= {CV_THRESHOLD:.0%} (proposed threshold)",
              f"throughput CV {cv:.1%}, p99 CV {cv99:.1%}; runs in order: "
              f"{', '.join(f'{t/1e3:.0f}k' for t in thr)} ops/s",
              cv <= CV_THRESHOLD,
              "p99 CV is reported, not thresholded")
    check("Frequency/thermal drift during repeat runs", "recorded (no threshold)",
          f"work-rate change after each run: {', '.join(f'{x:+.1%}' for x in drift)}; "
          f"Tctl after runs: {', '.join(f'{t:.0f}' for t in temps if t is not None)} C", True,
          "a negative change means the core clock was lower after the run than at calibration")

    # 7. Cost of per-acquisition timestamps under contention
    a = bench("--lock", "spin", "--threads", 4, "--hold-ns", 1000, "--think-ns", 1000, *common)
    b = bench("--lock", "spin", "--threads", 4, "--hold-ns", 1000, "--think-ns", 1000, "--no-timing", *common)
    diff = (b["throughput_ops_s"] - a["throughput_ops_s"]) / b["throughput_ops_s"]
    check("Timestamp overhead on contended throughput", "recorded (no threshold)",
          f"spin T=4: with timing {a['throughput_ops_s']/1e6:.3f} M/s, without {b['throughput_ops_s']/1e6:.3f} M/s "
          f"({diff:+.1%})", True)

    # 8. Context switches match expectations
    s = bench("--lock", "spin", "--threads", 8, "--hold-ns", 1000, "--think-ns", 1000, *common)
    p = bench("--lock", "park", "--threads", 8, "--hold-ns", 1000, "--think-ns", 1000, *common)
    # Voluntary switches are the lock's doing (blocking); involuntary ones come
    # from other processes preempting the workers and are reported only.
    vs, vp = s["vcsw"] / s["ops_measured"], p["vcsw"] / p["ops_measured"]
    check("Context switches: spin-only near zero, park-only high (T=8 < 16 CPUs)",
          "voluntary switches: spin < 0.001 per op and park > 0.1 per op",
          f"voluntary: spin {vs:.5f}/op ({s['vcsw']}), park {vp:.3f}/op; "
          f"involuntary: spin {s['ivcsw']}, park {p['ivcsw']}",
          vs < 0.001 and vp > 0.1,
          "criterion changed to voluntary-only after first run; first run also exposed 1 ms main-thread sleep chunks (fixed)")

    # 9. Built-in counter check on every bench run
    runs = raw["bench_runs"]
    check("Shared counter == total acquisitions in every bench run",
          "counter_ok true for all runs", f"{sum(r['counter_ok'] for r in runs)}/{len(runs)}",
          all(r["counter_ok"] for r in runs))

    # 10. False sharing: enforced by construction
    check("No false sharing between lock words and per-thread data",
          "_Static_assert on lock and tstate layout; per-thread buffers allocated by their owner",
          "compile-time asserts hold (build succeeded); PAD_BYTES=128", True,
          "Layout argument, not a measurement; perf c2c not installed")

    # 11. Wake-up benchmark sanity
    w = run_json([str(BUILD / "wakebench"), "--sleeper", 2, "--waker", 4, "--idle-us", 100, "--samples", 2000])
    raw["wakebench"] = w
    entries = {x["state"]: x["entries"] for x in w["sleeper_cpuidle"]}
    miss = w["missed"] / (w["missed"] + w["valid"])
    check("Wake-up benchmark: wakes land on a blocked sleeper",
          "missed < 1% (other-core, idle 100 us)",
          f"missed {miss:.2%}; sleeper idle-state entries {entries}", miss < 0.01)

    raw["checks"] = checks
    raw["elapsed_s"] = round(time.time() - t_start, 1)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out_dir = ROOT / "results" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"validation-{stamp}.json"
    json_path.write_text(json.dumps(raw, indent=1) + "\n")

    m = raw["manifest"]
    lines = [
        "# Harness validation report",
        "",
        "Generated by `scripts/validate.py`. Do not edit by hand; re-run the script instead.",
        "",
        f"- **When:** {m['collected_at']}",
        f"- **Machine:** {m['cpu']['model']} (machine_id `{m['machine_id']}`), kernel {m['kernel']}",
        f"- **Governor / EPP / boost:** {m['cpufreq']['governor']} / {m['cpufreq']['epp']} / boost={m['cpufreq']['boost']}",
        f"- **AC power:** {m['power'].get('ac_online')}",
        f"- **Git commit:** `{m['git']['commit']}` (dirty={m['git']['dirty']})",
        f"- **Raw output:** `{json_path.relative_to(ROOT)}`",
        f"- **Mode:** {'quick' if QUICK else 'full'} ({RUNS_REPEAT} repeats, {DUR_MS} ms runs), took {raw['elapsed_s']} s",
        "",
        "This is validation (pilot) data. It is not part of the experiment dataset.",
        "",
        "| # | Check | Criterion | Measured | Result |",
        "|---|---|---|---|---|",
    ]
    for i, c in enumerate(checks, 1):
        note = f" *({c['note']})*" if c["note"] else ""
        lines.append(f"| {i} | {c['check']} | {c['criterion']} | {c['measured']}{note} | "
                     f"{'PASS' if c['pass'] else '**FAIL**'} |")
    failed = [c for c in checks if not c["pass"]]
    lines += ["", f"**Summary:** {len(checks) - len(failed)}/{len(checks)} checks passed."]
    (ROOT / "docs" / "validation.md").write_text("\n".join(lines) + "\n")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed; report in docs/validation.md, raw in {json_path.relative_to(ROOT)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
