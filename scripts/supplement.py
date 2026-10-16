#!/usr/bin/env python3
"""Supplementary tests for the pre-declared comparisons (RESEARCH_PHASE.md 5.9).

usage: .venv/bin/python scripts/supplement.py      (needs scipy: requirements.txt)

For H1-H4 only: Mann-Whitney U (two-sided) with the probability of
superiority A = P(X > Y) + P(X = Y)/2 and the Hodges-Lehmann shift (on log
scale for latencies, reported as a ratio). p-values are Holm-corrected within
each hypothesis. These tests do NOT change any verdict; verdicts follow the
pre-registered rule (6.1) in scripts/analyze.py.

Writes docs/results/supplement.md and results/analysis/supplement.json.
"""
import csv
import gzip
import json
import math
import sys
from pathlib import Path

from scipy.stats import mannwhitneyu

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import stats  # noqa: E402

RES, DOCS = analyze.RES, analyze.DOCS


def effect(x, y, log=False):
    """MWU p-value, A = P(X > Y) + ties/2, Hodges-Lehmann shift of X - Y
    (ratio of X / Y on log scale when log=True)."""
    r = mannwhitneyu(x, y, alternative="two-sided", method="auto")
    a = r.statistic / (len(x) * len(y))
    if len(x) * len(y) <= 1_000_000:
        if log:
            d = sorted(math.log(u) - math.log(v) for u in x for v in y)
            hl = math.exp(stats.quantile_sorted(d, 0.5))
        else:
            d = sorted(u - v for u in x for v in y)
            hl = stats.quantile_sorted(d, 0.5)
    else:
        hl = float("nan")
    return {"U": r.statistic, "p": r.pvalue, "A": a, "hl": hl, "n_x": len(x), "n_y": len(y)}


def fmt_p(p):
    return "< 1e-300" if p == 0 else f"{p:.2g}"


def holm(tests):
    """Holm step-down adjustment, in place (key 'p_holm')."""
    order = sorted(range(len(tests)), key=lambda i: tests[i]["p"])
    m, running = len(tests), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * tests[i]["p"]))
        tests[i]["p_holm"] = running
    return tests


def runs_by(exp, *keys):
    return analyze.group(analyze.load_runs(exp), *keys)


def per_run_q(exp, r, phases, q):
    h = analyze.run_hist(exp, r)
    return stats.hist_quantile(stats.merge(h.get(i, {}) for i in phases), q)


def h1():
    e1 = json.loads((RES / "analysis" / "e1.json").read_text())["h1"]
    def samples(cid):
        out = []
        for f in sorted((RES / "e1" / "runs").glob(f"{cid}_r*.csv.gz")):
            with gzip.open(f, "rt") as fh:
                out += [float(row["wake_ns"]) for row in csv.DictReader(fh) if row["woke"] == "1"]
        return out
    t = effect(samples(e1["slowest"]), samples(e1["fastest"]))
    t.update({"case": f"{e1['slowest']} vs {e1['fastest']}", "metric": "wake latency (per sample)"})
    return holm([t])


def h2():
    e4 = json.loads((RES / "analysis" / "e4.json").read_text())
    g = runs_by("e4", "schedule", "threads", "lock")
    S = analyze.static_family()
    tests = []
    for c in e4["cases"]:
        t = int(c["case"].split("T=")[1].split()[0])
        post = int(c["case"].split("→")[1])
        a, b = c["a_star"], c["best_after"]
        idx = g[("S1", t, a)][0]["meta"]["logical_phases"].index(post)
        thr = lambda l: [r["result"]["phases"][idx]["throughput_ops_s"] for r in g[("S1", t, l)]]
        best_p99 = min(S, key=lambda l: e4["phases"][f"S1_t{t}_{l}_L{post}"]["p99"])
        p99 = lambda l: [per_run_q("e4", r, [idx], 0.99) for r in g[("S1", t, l)]]
        if a != b:
            x = effect(thr(a), thr(b))
            x.update({"case": c["case"], "metric": f"throughput after shift: {a} vs {b}"})
            tests.append(x)
        if a != best_p99:
            x = effect(p99(a), p99(best_p99), log=True)
            x.update({"case": c["case"], "metric": f"per-run p99 after shift: {a} vs {best_p99}"})
            tests.append(x)
    return holm(tests)


def h3():
    e6 = json.loads((RES / "analysis" / "e6.json").read_text())
    g = runs_by("e6", "schedule", "threads", "lock")
    tests = []
    for wl, w in e6["workloads"].items():
        sc, t = wl.split("_t")[0], int(wl.split("_t")[1])
        b = w["bstar"]
        span = lambda l: [analyze.span_run("e6", r) for r in g[(sc, int(t), l)]]
        sb = span(b)
        for a in analyze.H3_POLICIES:
            sa = span(a)
            x = effect([v[0] for v in sa], [v[0] for v in sb])
            x.update({"case": f"{sc} T={t}", "metric": f"span throughput: {a} vs B* {b}"})
            tests.append(x)
            q = lambda s: [stats.hist_quantile(v[1], 0.999) for v in s]
            x = effect(q(sa), q(sb), log=True)
            x.update({"case": f"{sc} T={t}", "metric": f"per-run p99.9: {a} vs B* {b}"})
            tests.append(x)
    return holm(tests)


def h4():
    e7 = json.loads((RES / "analysis" / "e7.json").read_text())
    g = runs_by("e7", "hold_ns", "quota_pct", "lock")
    tests = []
    for c in e7["cases"].values():
        if "h4" not in c:
            continue
        h, q = c["hold_ns"], c["quota_pct"]
        p999 = lambda l: [per_run_q("e7", r, [0], 0.999) for r in g[(h, q, l)]]
        ta = p999("ta")
        x = effect(p999("spin"), ta, log=True)
        x.update({"case": f"hold {h} ns, quota {q}%", "metric": "(a) per-run p99.9: spin vs ta"})
        tests.append(x)
        b = c["h4"]["best_static_tail"]
        x = effect(ta, p999(b), log=True)
        x.update({"case": f"hold {h} ns, quota {q}%", "metric": f"(b) per-run p99.9: ta vs {b}"})
        tests.append(x)
    return holm(tests)


def main():
    out = {"H1": h1(), "H2": h2(), "H3": h3(), "H4": h4()}
    md = ["# Supplementary tests for the pre-declared comparisons (H1–H4)", "",
          "Generated by `scripts/supplement.py` (scipy " + __import__("scipy").__version__ + "). "
          "Mann–Whitney U, two-sided; A = P(X > Y) + ½ P(X = Y) (0.5 = no difference, 0 or 1 = complete separation); "
          "Hodges–Lehmann (HL) shift of X − Y, or the ratio X / Y for latencies (computed on log scale). "
          "p-values Holm-corrected within each hypothesis. Per-run comparisons have n = 10 per side (H1: per sample). "
          "**These tests do not change any verdict**; verdicts follow RESEARCH_PHASE.md §6.1 (point estimate decides, "
          "interval can veto) and are in §3.4. Per-run tail quantiles from about 10 runs are noisy, which is why the "
          "pre-registered rule uses pooled histograms.", ""]
    for hyp, tests in out.items():
        md += [f"## {hyp}", "", "| Case | Comparison (X vs Y) | n | U | A | HL shift / ratio | p | p (Holm) |",
               "|---|---|---|---|---|---|---|---|"]
        for t in tests:
            ratio = "ratio" in t["metric"] or "p99" in t["metric"]
            hl = "–" if t["hl"] != t["hl"] else (f"×{t['hl']:.3g}" if ratio else f"{t['hl']/1e6:+.4f} M ops/s"
                                                  if "throughput" in t["metric"] else f"{t['hl']:.3g}")
            md.append(f"| {t['case']} | {t['metric']} | {t['n_x']}/{t['n_y']} | {t['U']:.0f} | {t['A']:.3f} | "
                      f"{hl} | {fmt_p(t['p'])} | {fmt_p(t['p_holm'])} |")
        md.append("")
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "supplement.md").write_text("\n".join(md) + "\n")
    (RES / "analysis" / "supplement.json").write_text(json.dumps(out, indent=1) + "\n")
    print("wrote docs/results/supplement.md and results/analysis/supplement.json")


if __name__ == "__main__":
    main()
