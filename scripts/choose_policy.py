#!/usr/bin/env python3
"""Apply the pre-declared tuning rule (RESEARCH_PHASE.md 5.8) to the T3
session and write config/policy.json, which fixes the adaptive locks used in
E6-E8. Run once, after T3 and before any of E6-E8; commit the result and tag
it prereg-v1-p3."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import experiments  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    data = analyze.analyze_t3()
    sel = data["selected"]
    sc = data["scores"]
    beta = {k: sc[sel[k]]["beta"] for k in ("ada", "hedge")}
    base = sel["ta_base"]
    out = {
        "rule": "RESEARCH_PHASE.md 5.8: per policy, most T=4 holds within both H3 bounds; then highest "
                "worst-case throughput ratio (0.01 tie); then lowest worst-case p99.9 ratio; then smaller beta. "
                "exp3 uses hedge's beta. ta base = better of the two winners (full tie -> ada); "
                "ta detector parameters fixed by design.",
        "tuning_session": "t3",
        "ada": {"beta": beta["ada"]},
        "hedge": {"beta": beta["hedge"]},
        "exp3": {"beta": beta["hedge"]},
        "ta": {"base": base, "beta": beta[base], **experiments.TA_PARAMS},
        "common": experiments.policy_common(),
        "scores": sc,
    }
    path = ROOT / "config" / "policy.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {path.relative_to(ROOT)}: ada beta={beta['ada']:g}, hedge beta={beta['hedge']:g}, ta base={base}")
    for label, spec in experiments.tuned_locks().items():
        print(f"  {label}: {spec}")


if __name__ == "__main__":
    main()
