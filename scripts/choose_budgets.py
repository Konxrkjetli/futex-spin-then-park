#!/usr/bin/env python3
"""Apply the pre-registered spin-budget rule (RESEARCH_PHASE.md section 5.6).

m = median wake-up latency of E1 condition other-core / idle 100 us / unloaded,
pooled over all its runs; budgets = {0.5, 1, 2, 8} x m, rounded to 50 ns.
Writes config/budgets.json.
"""
import csv
import gzip
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "other-core_idle100us"
MULTIPLIERS = [0.5, 1, 2, 8]


def main():
    runs_dir = ROOT / "results" / "e1" / "runs"
    files = sorted(runs_dir.glob(f"{REFERENCE}_r*.csv.gz"))
    if not files:
        raise SystemExit(f"no E1 data for {REFERENCE}")
    samples = []
    for f in files:
        with gzip.open(f, "rt") as fh:
            for row in csv.DictReader(fh):
                if row["woke"] == "1":
                    samples.append(float(row["wake_ns"]))
    m = statistics.median(samples)
    budgets = [int(round(m * k / 50.0)) * 50 for k in MULTIPLIERS]
    out = {
        "rule": "budgets = {0.5, 1, 2, 8} x median wake latency (other-core, idle 100 us, unloaded), rounded to 50 ns",
        "reference_condition": REFERENCE,
        "reference_runs": [f.name for f in files],
        "reference_samples": len(samples),
        "reference_median_ns": round(m, 1),
        "multipliers": MULTIPLIERS,
        "budgets_ns": budgets,
    }
    path = ROOT / "config" / "budgets.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
