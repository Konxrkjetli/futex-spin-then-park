#!/usr/bin/env python3
"""Analysis of Phase 2 experiments (standard library only).

usage: scripts/analyze.py {e1,e2,e3,e4,e5,all}

Writes readable tables to docs/results/<exp>.md and machine-readable output to
results/analysis/<exp>.json. Confirmatory verdicts (H1, H2) follow the
pre-registered rules in RESEARCH_PHASE.md 5.6 and 6.1; everything else is
labelled exploratory.
"""
import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stats  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
DOCS = ROOT / "docs" / "results"


def load_runs(exp):
    path = RES / exp / "runs.jsonl"
    if not path.exists():
        raise SystemExit(f"no data for {exp}")
    runs = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        runs[r["run_id"]] = r          # last record wins if a run was redone
    return list(runs.values())


def budgets():
    return json.loads((ROOT / "config" / "budgets.json").read_text())["budgets_ns"]


def static_family():
    return ["park", *[f"stp:{b}" for b in budgets()], "spin"]


ALL_EXTRA = ["pthread", "pthread-adaptive"]


def fmt_ns(x):
    if x != x:
        return "–"
    if x >= 1e6:
        return f"{x/1e6:.2f} ms"
    if x >= 1e3:
        return f"{x/1e3:.2f} µs"
    return f"{x:.0f} ns"


def write(exp, md_lines, data):
    DOCS.mkdir(parents=True, exist_ok=True)
    (RES / "analysis").mkdir(parents=True, exist_ok=True)
    (DOCS / f"{exp}.md").write_text("\n".join(md_lines) + "\n")
    (RES / "analysis" / f"{exp}.json").write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote docs/results/{exp}.md and results/analysis/{exp}.json")


def verdict(value, threshold, ci, higher_is_support=True):
    """Pre-registered rule: point estimate decides, CI containing the
    threshold makes it inconclusive."""
    lo, hi = ci
    if lo <= threshold <= hi:
        return "inconclusive"
    met = value >= threshold if higher_is_support else value <= threshold
    return "met" if met else "not met"


# ---- E1 / H1 -----------------------------------------------------------------

def analyze_e1():
    runs = load_runs("e1")
    conds = {}
    for r in runs:
        conds.setdefault(r["meta"]["condition"], []).append(r)

    rows, table = {}, []
    for cid, rs in sorted(conds.items()):
        samples, run_medians, syscall, blocked, idle = [], [], [], [], {}
        valid = missed = 0
        for r in sorted(rs, key=lambda x: x["meta"]["rep"]):
            res = r["result"]
            valid += res["valid"]
            missed += res["missed"]
            run_s = []
            with gzip.open(RES / "e1" / "runs" / f"{r['run_id']}.csv.gz", "rt") as f:
                for row in csv.DictReader(f):
                    if row["woke"] == "1":
                        run_s.append(float(row["wake_ns"]))
                        syscall.append(float(row["waker_syscall_ns"]))
                        blocked.append(float(row["blocked_ns"]))
            run_s.sort()
            run_medians.append(stats.quantile_sorted(run_s, 0.5))
            samples += run_s
            for st in res["sleeper_cpuidle"]:
                idle[st["state"]] = idle.get(st["state"], 0) + st["entries"]
        samples.sort()
        syscall.sort()
        blocked.sort()
        med = stats.quantile_sorted(samples, 0.5)
        lo, hi = stats.median_ci(samples)
        tot_idle = sum(idle.values()) or 1
        m = rs[0]["meta"]
        rows[cid] = {
            "placement": m["placement"], "idle_us": m["idle_us"], "load": m["load"],
            "confirmatory": m["confirmatory"], "runs": len(rs), "valid": valid, "missed": missed,
            "median_ns": med, "median_ci": [lo, hi], "run_medians": run_medians,
            "p90": stats.quantile_sorted(samples, 0.9), "p99": stats.quantile_sorted(samples, 0.99),
            "p999": stats.quantile_sorted(samples, 0.999), "max": samples[-1],
            "p99_over_p50": stats.quantile_sorted(samples, 0.99) / med,
            "waker_syscall_p50": stats.quantile_sorted(syscall, 0.5),
            "blocked_p50": stats.quantile_sorted(blocked, 0.5),
            "idle_share": {k: v / tot_idle for k, v in idle.items()},
        }

    conf = {k: v for k, v in rows.items() if v["confirmatory"]}
    fast = min(conf, key=lambda k: conf[k]["median_ns"])
    slow = max(conf, key=lambda k: conf[k]["median_ns"])
    ratio = conf[slow]["median_ns"] / conf[fast]["median_ns"]
    ci = (conf[slow]["median_ci"][0] / conf[fast]["median_ci"][1],
          conf[slow]["median_ci"][1] / conf[fast]["median_ci"][0])
    v = verdict(ratio, 2.0, ci)
    # Robustness (not part of the verdict): the most pessimistic ratio using
    # per-run medians, which does not assume independent samples.
    worst = min(conf[slow]["run_medians"]) / max(conf[fast]["run_medians"])
    h1 = {"fastest": fast, "slowest": slow, "ratio": ratio, "ci": ci, "threshold": 2.0,
          "worst_case_run_ratio": worst,
          "verdict": {"met": "SUPPORTED", "not met": "REFUTED"}.get(v, "INCONCLUSIVE")}

    order = {"smt-sibling": 0, "other-core": 1, "same-cpu": 2}
    md = ["# E1: futex wake-up latency (RQ1, H1)", "",
          "Generated by `scripts/analyze.py e1`. Pooled over runs; medians with distribution-free 95% intervals.",
          "", "| Condition | Runs | Valid | Missed | Median [95% CI] | Run medians | p90 | p99 | p99.9 | max | p99/p50 | Waker syscall p50 | Sleeper idle-state entries |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for cid, r in sorted(rows.items(), key=lambda kv: (kv[1]["load"], order[kv[1]["placement"]], kv[1]["idle_us"])):
        idle = ", ".join(f"{k} {v:.0%}" for k, v in r["idle_share"].items() if v >= 0.01)
        md.append(f"| {cid}{'' if r['confirmatory'] else ' (descriptive)'} | {r['runs']} | {r['valid']} | {r['missed']} | "
                  f"{fmt_ns(r['median_ns'])} [{fmt_ns(r['median_ci'][0])}, {fmt_ns(r['median_ci'][1])}] | "
                  f"{', '.join(fmt_ns(x) for x in r['run_medians'])} | {fmt_ns(r['p90'])} | {fmt_ns(r['p99'])} | "
                  f"{fmt_ns(r['p999'])} | {fmt_ns(r['max'])} | {r['p99_over_p50']:.2f} | "
                  f"{fmt_ns(r['waker_syscall_p50'])} | {idle} |")
    md += ["", "## H1 (confirmatory)", "",
           f"- Fastest unloaded condition: **{fast}** (median {fmt_ns(conf[fast]['median_ns'])})",
           f"- Slowest unloaded condition: **{slow}** (median {fmt_ns(conf[slow]['median_ns'])})",
           f"- Ratio slowest/fastest = **{ratio:.2f}**, conservative 95% interval [{ci[0]:.2f}, {ci[1]:.2f}], threshold 2.0",
           f"- **Verdict: H1 {h1['verdict']}** (pre-registered rule, RESEARCH_PHASE.md 6.1)",
           f"- Robustness check (not part of the verdict): lowest per-run median of the slowest condition / "
           f"highest per-run median of the fastest condition = **{worst:.2f}**", "",
           "Caveat: the per-condition median intervals assume independent samples; the spread of the per-run medians is shown for comparison."]
    write("e1", md, {"conditions": rows, "h1": h1})
    return h1


# ---- bench helpers ---------------------------------------------------------------

def phase_metrics(r, harness_phase):
    p = r["result"]["phases"][harness_phase]
    return p["throughput_ops_s"]


def run_hist(exp, r):
    return stats.load_hists(RES / exp / "runs" / f"{r['run_id']}.hist.csv")


def group(runs, *keys):
    g = {}
    for r in runs:
        g.setdefault(tuple(r["meta"][k] for k in keys), []).append(r)
    return g


def steady_table(exp, runs, title, note):
    g = group(runs, "hold_ns", "threads", "lock")
    holds = sorted({k[0] for k in g})
    threads = sorted({k[1] for k in g})
    locks = static_family() + ALL_EXTRA
    data, md = {}, [f"# {title}", "", note, ""]
    best_rows = ["| hold \\ T | " + " | ".join(str(t) for t in threads) + " |",
                 "|---|" + "---|" * len(threads)]
    for h in holds:
        cells = []
        for t in threads:
            stat = {}
            for l in locks:
                rs = g.get((h, t, l), [])
                if not rs:
                    continue
                thr = [r["result"]["throughput_ops_s"] for r in rs]
                hists = [run_hist(exp, r)[0] for r in rs]
                pooled = stats.merge(hists)
                stat[l] = {"runs": len(rs), "thr_mean": stats.mean(thr),
                           "thr_cv": (stats.mean([(x - stats.mean(thr)) ** 2 for x in thr]) ** 0.5) / stats.mean(thr),
                           "p50": stats.hist_quantile(pooled, 0.5), "p99": stats.hist_quantile(pooled, 0.99),
                           "p999": stats.hist_quantile(pooled, 0.999),
                           "jain": stats.mean([r["result"]["phases"][0]["jain"] for r in rs]),
                           "cpu_util": stats.mean([r["result"]["cpu_util"] for r in rs]),
                           "vcsw_per_op": stats.mean([r["result"]["vcsw"] / max(r["result"]["ops_measured"], 1) for r in rs]),
                           "drift": stats.mean([r["result"]["iters_per_ns_after"] / r["result"]["iters_per_ns"] - 1 for r in rs])}
            data[f"h{h}_t{t}"] = stat
            best = max(stat, key=lambda l: stat[l]["thr_mean"])
            best_s = max((l for l in stat if l in static_family()), key=lambda l: stat[l]["thr_mean"])
            cells.append(f"{best} ({stat[best]['thr_mean']/1e6:.2f} M/s)" + ("" if best == best_s else f"; static: {best_s}"))
        best_rows.append(f"| {fmt_ns(h)} | " + " | ".join(cells) + " |")
    md += ["## Highest-throughput lock per configuration (exploratory)", ""] + best_rows + [""]
    for key, stat in data.items():
        md += [f"### {key.replace('h', 'hold ').replace('_t', ' ns, T=')}", "",
               "| Lock | Throughput (M ops/s) | CV | p50 | p99 | p99.9 | Jain | CPU (cores) | vol. csw/op | drift |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for l, s in sorted(stat.items(), key=lambda kv: -kv[1]["thr_mean"]):
            md.append(f"| {l} | {s['thr_mean']/1e6:.3f} | {s['thr_cv']:.1%} | {fmt_ns(s['p50'])} | {fmt_ns(s['p99'])} | "
                      f"{fmt_ns(s['p999'])} | {s['jain']:.3f} | {s['cpu_util']:.2f} | {s['vcsw_per_op']:.3f} | {s['drift']:+.1%} |")
        md.append("")
    return md, data


def analyze_e2():
    runs = load_runs("e2")
    md, data = steady_table("e2", runs, "E2: steady sweep (RQ2, exploratory)",
                            "Generated by `scripts/analyze.py e2`. Mean throughput over runs; latency quantiles from pooled histograms. "
                            "Think time 1 µs, cores-first pinning, 5 runs per cell.")
    write("e2", md, data)


def analyze_e3():
    runs = load_runs("e3")
    md, data = steady_table("e3", runs, "E3: unpinned subset (exploratory)",
                            "Generated by `scripts/analyze.py e3`. Same as E2 but threads unpinned; compare with the matching E2 cells.")
    write("e3", md, data)


# ---- E4 / H2 -----------------------------------------------------------------

def logical_series(exp, rs, logical):
    """Per logical phase: list of run throughputs and list of run histograms."""
    lmap = rs[0]["meta"]["logical_phases"]
    idx = lmap.index(logical)
    thr = [r["result"]["phases"][idx]["throughput_ops_s"] for r in rs]
    hists = [run_hist(exp, r).get(idx, {}) for r in rs]
    return thr, hists


def analyze_e4():
    runs = load_runs("e4")
    S = static_family()
    g = group(runs, "schedule", "threads", "lock")
    md = ["# E4: phase-changing workloads (RQ2, H2)", "",
          "Generated by `scripts/analyze.py e4`. Transition windows (first 100 ms after each shift) excluded. "
          "Throughput = mean over runs; p99 from pooled histograms; intervals by bootstrap over runs (2,000 resamples).", ""]
    data = {"cases": [], "phases": {}}

    for sched in ("S1", "S2"):
        for t in sorted({k[1] for k in g if k[0] == sched}):
            md += [f"## {sched}, T={t}", "", "| Lock | Phase 0 thr | Phase 1 thr | Phase 2 thr | Phase 0 p99 | Phase 1 p99 | Phase 2 p99 |",
                   "|---|---|---|---|---|---|---|"]
            for l in S + ALL_EXTRA:
                rs = g.get((sched, t, l))
                if not rs:
                    continue
                cells_t, cells_p = [], []
                for L in (0, 1, 2):
                    thr, hists = logical_series("e4", rs, L)
                    p99 = stats.pooled_quantile(hists, 0.99)
                    data["phases"][f"{sched}_t{t}_{l}_L{L}"] = {"thr_mean": stats.mean(thr), "p99": p99, "runs": len(rs)}
                    cells_t.append(f"{stats.mean(thr)/1e6:.3f} M/s")
                    cells_p.append(fmt_ns(p99))
                md.append(f"| {l} | " + " | ".join(cells_t + cells_p) + " |")
            md.append("")

    # H2: S1 transitions 0->1 and 1->2 at T in {8, 16}
    md += ["## H2 (confirmatory)", "",
           "Case meets H2 if loss ≥ 25% **or** p99 ratio ≥ 2. Each metric is judged by the pre-registered rule "
           "(point estimate decides; a 95% interval containing the threshold makes that metric inconclusive). "
           "A case is met if either metric is met, not met if both are not met, otherwise inconclusive.", "",
           "| Case | A* (best before) | Best after | Loss [95% CI] | p99 ratio [95% CI] | Result |", "|---|---|---|---|---|---|"]
    met = notmet = inconc = 0
    for t in sorted({k[1] for k in g if k[0] == "S1"}):
        series = {l: {L: logical_series("e4", g[("S1", t, l)], L) for L in (0, 1, 2)} for l in S if ("S1", t, l) in g}
        for pre, post in ((0, 1), (1, 2)):
            def best_before():
                cands = sorted(series, key=lambda l: -stats.mean(series[l][pre][0]))
                top = stats.mean(series[cands[0]][pre][0])
                tied = [l for l in cands if stats.mean(series[l][pre][0]) >= 0.99 * top]
                return min(tied, key=lambda l: stats.pooled_quantile(series[l][pre][1], 0.99))
            a = best_before()
            best_after = max(series, key=lambda l: stats.mean(series[l][post][0]))
            loss = 1 - stats.mean(series[a][post][0]) / max(stats.mean(series[l][post][0]) for l in series)
            ratio = stats.pooled_quantile(series[a][post][1], 0.99) / min(stats.pooled_quantile(series[l][post][1], 0.99) for l in series)
            locks = list(series)
            loss_ci = stats.bootstrap(
                lambda *gs: 1 - stats.mean(gs[locks.index(a)]) / max(stats.mean(x) for x in gs),
                [series[l][post][0] for l in locks])
            ratio_ci = stats.bootstrap(
                lambda *gs: stats.pooled_quantile(gs[locks.index(a)], 0.99) / min(stats.pooled_quantile(x, 0.99) for x in gs),
                [series[l][post][1] for l in locks])
            vl, vr = verdict(loss, 0.25, loss_ci), verdict(ratio, 2.0, ratio_ci)
            res = "met" if "met" in (vl, vr) else ("not met" if vl == vr == "not met" else "inconclusive")
            met += res == "met"
            notmet += res == "not met"
            inconc += res == "inconclusive"
            case = f"S1 T={t} phase {pre}→{post}"
            data["cases"].append({"case": case, "a_star": a, "best_after": best_after, "loss": loss, "loss_ci": loss_ci,
                                  "loss_verdict": vl, "p99_ratio": ratio, "p99_ratio_ci": ratio_ci, "ratio_verdict": vr,
                                  "result": res})
            md.append(f"| {case} | {a} | {best_after} | {loss:.1%} [{loss_ci[0]:.1%}, {loss_ci[1]:.1%}] ({vl}) | "
                      f"{ratio:.2f} [{ratio_ci[0]:.2f}, {ratio_ci[1]:.2f}] ({vr}) | **{res}** |")
    n = met + notmet + inconc
    overall = ("SUPPORTED" if met == n else "REFUTED" if notmet == n else
               "PARTIALLY SUPPORTED" if met > 0 else "INCONCLUSIVE")
    data["h2"] = {"met": met, "not_met": notmet, "inconclusive": inconc, "verdict": overall}
    md += ["", f"**Verdict: H2 {overall}** ({met} met, {notmet} not met, {inconc} inconclusive of {n} cases)."]
    write("e4", md, data)
    return data["h2"]


# ---- E5 ------------------------------------------------------------------------

def analyze_e5():
    runs = load_runs("e5")
    g = group(runs, "threads", "lock")
    md = ["# E5: randomized workload R1 (RQ2, exploratory)", "",
          "Generated by `scripts/analyze.py e5`. Hold 200 ns, or 20 µs with p = 0.1; exponential think time with mean 2 µs.", ""]
    data = {}
    for t in sorted({k[0] for k in g}):
        md += [f"## T={t}", "", "| Lock | Throughput (M ops/s) | p50 | p99 | p99.9 | Jain | CPU (cores) |", "|---|---|---|---|---|---|---|"]
        rows = []
        for l in static_family() + ALL_EXTRA:
            rs = g.get((t, l))
            if not rs:
                continue
            pooled = stats.merge(run_hist("e5", r)[0] for r in rs)
            s = {"thr_mean": stats.mean([r["result"]["throughput_ops_s"] for r in rs]),
                 "p50": stats.hist_quantile(pooled, 0.5), "p99": stats.hist_quantile(pooled, 0.99),
                 "p999": stats.hist_quantile(pooled, 0.999),
                 "jain": stats.mean([r["result"]["phases"][0]["jain"] for r in rs]),
                 "cpu_util": stats.mean([r["result"]["cpu_util"] for r in rs])}
            data[f"t{t}_{l}"] = s
            rows.append((l, s))
        for l, s in sorted(rows, key=lambda x: -x[1]["thr_mean"]):
            md.append(f"| {l} | {s['thr_mean']/1e6:.3f} | {fmt_ns(s['p50'])} | {fmt_ns(s['p99'])} | {fmt_ns(s['p999'])} | "
                      f"{s['jain']:.3f} | {s['cpu_util']:.2f} |")
        md.append("")
    write("e5", md, data)


ANALYSES = {"e1": analyze_e1, "e2": analyze_e2, "e3": analyze_e3, "e4": analyze_e4, "e5": analyze_e5}

if __name__ == "__main__":
    which = sys.argv[1:] or ["all"]
    for w in (ANALYSES if which == ["all"] else which):
        ANALYSES[w]()
