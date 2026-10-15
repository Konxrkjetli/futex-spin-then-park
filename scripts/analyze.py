#!/usr/bin/env python3
"""Analysis of Phase 2 experiments (standard library only).

usage: scripts/analyze.py {e1,e2,e3,e4,e5,t3,e6,e7,e8,all}

Writes readable tables to docs/results/<exp>.md and machine-readable output to
results/analysis/<exp>.json. Confirmatory verdicts (H1, H2) follow the
pre-registered rules in RESEARCH_PHASE.md 5.6 and 6.1; everything else is
labelled exploratory.
"""
import csv
import gzip
import json
import random
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


def steady_table(exp, runs, title, note, locks=None, best_table=True):
    g = group(runs, "hold_ns", "threads", "lock")
    holds = sorted({k[0] for k in g})
    threads = sorted({k[1] for k in g})
    locks = locks or static_family() + ALL_EXTRA
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
    if best_table:
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
    pinned = json.loads((RES / "analysis" / "e2.json").read_text()) if (RES / "analysis" / "e2.json").exists() else {}
    if pinned:
        md += ["## Unpinned vs pinned (E3 / matching E2 cell)", "",
               "| Config | Lock | Throughput ratio | p99 ratio | Unpinned vol. csw/op | Pinned vol. csw/op |",
               "|---|---|---|---|---|---|"]
        for key, stat in data.items():
            for l, s in stat.items():
                p = pinned.get(key, {}).get(l)
                if p:
                    md.append(f"| {key} | {l} | {s['thr_mean'] / p['thr_mean']:.2f} | {s['p99'] / p['p99']:.2f} | "
                              f"{s['vcsw_per_op']:.3f} | {p['vcsw_per_op']:.3f} |")
        md.append("")
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


# ---- T3: tuning session (RESEARCH_PHASE.md 5.8) -----------------------------------

def run_stats(exp, rs, phases=(0,)):
    """Mean throughput over runs and pooled latency quantiles over the given
    harness phases (used for single-phase steady runs)."""
    thr = [sum(r["result"]["phases"][i]["ops"] for i in phases) /
           sum(r["result"]["phases"][i]["duration_ms"] / 1e3 for i in phases) for r in rs]
    pooled = stats.merge(run_hist(exp, r).get(i, {}) for r in rs for i in phases)
    return {"runs": len(rs), "thr_mean": stats.mean(thr), "p50": stats.hist_quantile(pooled, 0.5),
            "p99": stats.hist_quantile(pooled, 0.99), "p999": stats.hist_quantile(pooled, 0.999)}


def best_static(st):
    """Pre-registered rule: highest throughput; ties within 1% -> lower p99."""
    top = max(v["thr_mean"] for v in st.values())
    tied = [l for l, v in st.items() if v["thr_mean"] >= 0.99 * top]
    return min(tied, key=lambda l: st[l]["p99"])


def pick(scores, final_key):
    """Tuning order (5.8): most holds within both H3 bounds; then highest
    worst-case throughput ratio (within 0.01 counts as a tie); then lowest
    worst-case p99.9 ratio; then final_key."""
    top_ok = max(s["n_ok"] for s in scores.values())
    c = [k for k, s in scores.items() if s["n_ok"] == top_ok]
    best_thr = max(scores[k]["min_thr_ratio"] for k in c)
    c = [k for k in c if scores[k]["min_thr_ratio"] >= best_thr - 0.01]
    best_tail = min(scores[k]["max_tail_ratio"] for k in c)
    c = [k for k in c if scores[k]["max_tail_ratio"] == best_tail]
    return min(c, key=final_key)


def analyze_t3():
    runs = load_runs("t3")
    S = static_family()
    g = group(runs, "hold_ns", "lock")
    holds = sorted({k[0] for k in g})
    cands = sorted({k[1] for k in g} - set(S), key=lambda l: (l.split("-b")[0], float(l.split("-b")[1])))
    data = {"holds": {}, "scores": {}}
    md = ["# T3: tuning session for the adaptive policies (steady, T = 4)", "",
          "Generated by `scripts/analyze.py t3`. Tuning set allowed by prereg-v1 (steady, T = 4 only); "
          "selection rule in RESEARCH_PHASE.md 5.8. 5 runs per cell; throughput = mean over runs; "
          "p99/p99.9 from histograms pooled over runs. Ratios are against the best static lock at that hold.", ""]
    for h in holds:
        st = {l: run_stats("t3", g[(h, l)]) for l in S}
        bstar = best_static(st)
        cs = {}
        for c in cands:
            x = run_stats("t3", g[(h, c)])
            x["thr_ratio"] = x["thr_mean"] / st[bstar]["thr_mean"]
            x["tail_ratio"] = x["p999"] / st[bstar]["p999"]
            x["ok"] = x["thr_ratio"] >= 0.85 and x["tail_ratio"] <= 1.2
            cs[c] = x
        data["holds"][str(h)] = {"static": st, "best_static": bstar, "candidates": cs}
        md += [f"## hold {fmt_ns(h)}: best static **{bstar}** ({st[bstar]['thr_mean']/1e6:.3f} M ops/s, "
               f"p99 {fmt_ns(st[bstar]['p99'])}, p99.9 {fmt_ns(st[bstar]['p999'])})", "",
               "| Lock | Throughput (M ops/s) | p99 | p99.9 | thr ratio | p99.9 ratio | within H3 bounds |",
               "|---|---|---|---|---|---|---|"]
        for l in S:
            md.append(f"| {l} | {st[l]['thr_mean']/1e6:.3f} | {fmt_ns(st[l]['p99'])} | {fmt_ns(st[l]['p999'])} | | | |")
        for c in cands:
            x = cs[c]
            md.append(f"| {c} | {x['thr_mean']/1e6:.3f} | {fmt_ns(x['p99'])} | {fmt_ns(x['p999'])} | "
                      f"{x['thr_ratio']:.3f} | {x['tail_ratio']:.2f} | {'yes' if x['ok'] else 'no'} |")
        md.append("")
    for c in cands:
        per = [data["holds"][str(h)]["candidates"][c] for h in holds]
        data["scores"][c] = {"kind": c.split("-b")[0], "beta": float(c.split("-b")[1]),
                             "n_ok": sum(x["ok"] for x in per),
                             "min_thr_ratio": min(x["thr_ratio"] for x in per),
                             "max_tail_ratio": max(x["tail_ratio"] for x in per)}
    sc = data["scores"]
    win = {k: pick({c: v for c, v in sc.items() if v["kind"] == k}, lambda c: sc[c]["beta"])
           for k in ("ada", "hedge")}
    base = pick({win["ada"]: sc[win["ada"]], win["hedge"]: sc[win["hedge"]]},
                lambda c: 0 if sc[c]["kind"] == "ada" else 1)
    data["selected"] = {"ada": win["ada"], "hedge": win["hedge"], "ta_base": sc[base]["kind"]}
    md += ["## Scores and selection", "",
           "| Candidate | Holds within both bounds | Worst throughput ratio | Worst p99.9 ratio |", "|---|---|---|---|"]
    for c in cands:
        mark = " **(selected)**" if c in win.values() else ""
        md.append(f"| {c}{mark} | {sc[c]['n_ok']}/{len(holds)} | {sc[c]['min_thr_ratio']:.3f} | {sc[c]['max_tail_ratio']:.2f} |")
    md += ["", f"- Policy A: **{win['ada']}**; Policy B: **{win['hedge']}**; EXP3 uses Policy B's beta.",
           f"- Throttle-aware base policy: **{sc[base]['kind']}** (better of the two winners by the same order; full tie goes to ada).",
           "", "Tuning results are in-sample for T = 4 steady workloads and are not evidence for H3."]
    write("t3", md, data)
    return data


# ---- Phase 3 helpers --------------------------------------------------------------

ADAPTIVE = ["ada", "hedge", "exp3", "ta"]
H3_POLICIES = ["ada", "hedge"]
K_ARMS = 6


def span_phases(r):
    """Harness phases inside the H3 span (transition windows excluded)."""
    lm = r["meta"].get("logical_phases")
    return [i for i, L in enumerate(lm) if L is not None] if lm else [0]


def span_run(exp, r):
    """(throughput over the span, histogram pooled over the span's phases)."""
    ph = span_phases(r)
    res = r["result"]["phases"]
    thr = sum(res[i]["ops"] for i in ph) / sum(res[i]["duration_ms"] / 1e3 for i in ph)
    h = run_hist(exp, r)
    return thr, stats.merge(h.get(i, {}) for i in ph)


def combine(*vs):
    """C1: met only if every bound is met; not met if any bound is not met."""
    if "not met" in vs:
        return "not met"
    return "met" if all(v == "met" for v in vs) else "inconclusive"


def overall(results):
    n = len(results)
    met, nm = results.count("met"), results.count("not met")
    return ("SUPPORTED" if met == n else "REFUTED" if nm == n else
            "PARTIALLY SUPPORTED" if met > 0 else "INCONCLUSIVE")


def boot_eval(evaluate, sizes):
    """Point estimate and 2,000 bootstrap evaluations; runs are resampled
    with replacement independently for each lock (C2)."""
    point = evaluate({l: list(range(n)) for l, n in sizes.items()})
    rng = random.Random(stats.SEED)
    reps = []
    for _ in range(stats.BOOT):
        reps.append(evaluate({l: [rng.randrange(n) for _ in range(n)] for l, n in sizes.items()}))
    return point, reps


def run_extras(r, phases):
    """Per-run exploratory metrics over the given harness phases."""
    res = r["result"]
    ph = [res["phases"][i] for i in phases]
    ls = res["lock_stats"]
    # Worst thread's p99; a thread with no acquisition at all in a phase
    # waited the whole phase, so it counts as the phase length.
    worst = -1.0
    for p in ph:
        for x in p.get("per_thread_p99_ns", [])[:p["active"]]:
            worst = max(worst, x if x >= 0 else p["duration_ms"] * 1e6)
    jain = stats.mean([p["jain"] for p in ph])
    k = K_ARMS
    arms = ls.get("cost_arm_ms", [0] * k)[:k]
    pol_regret = (ls["cost_real_ms"] - min(arms)) / ls["slow"] * 1e6 if ls.get("slow") and any(arms) else float("nan")
    return {"jain": jain, "worst_thread_p99": worst, "cpu_util": res["cpu_util"],
            "budget_mean_ns": ls.get("budget_mean_ns", 0.0),
            "forced_frac": ls.get("forced", 0) / ls["slow"] if ls.get("slow") else 0.0,
            "wake_mean_ns": ls.get("wake_mean_ns", 0.0), "wake_n": ls.get("wake_n", 0),
            "policy_regret_ns_per_slow": pol_regret,
            "arm_share": [a / max(sum(ls.get("arm_n", [0])[:k]), 1) for a in ls.get("arm_n", [0] * k)[:k]],
            "cgroup": res.get("cgroup"), "lock_report": res.get("lock_report")}


def mean_of(xs):
    xs = [x for x in xs if x == x]
    return stats.mean(xs) if xs else float("nan")


def median_of(xs):
    xs = sorted(x for x in xs if x == x)
    return stats.quantile_sorted(xs, 0.5) if xs else float("nan")


def windows_series(exp, rs):
    """Mean over runs of per-window ops and slow-path counters."""
    acc = None
    for r in rs:
        with open(RES / exp / "runs" / f"{r['run_id']}.win.csv") as f:
            rows = list(csv.DictReader(f))
        if acc is None:
            acc = [{"t_ms": float(w["t_ms"]), "phase": int(w["phase"]), "ops": 0.0, "slow": 0.0,
                    "parks": 0.0, "forced": 0.0, "budget": 0.0} for w in rows]
        for a, w in zip(acc, rows):
            a["ops"] += int(w["ops"]) / len(rs)
            a["slow"] += int(w["slow"]) / len(rs)
            a["parks"] += int(w["parks"]) / len(rs)
            a["forced"] += int(w["forced"]) / len(rs)
            a["budget"] += float(w["budget_ns_sum"]) / len(rs)
    return acc


# ---- E6 / H3 -----------------------------------------------------------------

def analyze_e6():
    runs = load_runs("e6")
    S = static_family()
    g = group(runs, "schedule", "threads", "lock")
    locks_all = S + ALL_EXTRA + ADAPTIVE
    workloads = [(sc, t) for sc in ("S1", "S2", "R1") for t in (8, 16)]
    md = ["# E6: adaptive vs static locks on the H3 workloads (RQ3, H3)", "",
          "Generated by `scripts/analyze.py e6`. One session, static and adaptive locks interleaved in random order, "
          "10 runs per lock and workload. Span = whole run minus the 100 ms transition windows. Throughput = mean over runs "
          "of span ops / span time; p99/p99.9 from histograms pooled over the span and all runs. Intervals: bootstrap over runs "
          "(2,000 resamples), best static B* recomputed in each resample (C2).", ""]
    data = {"h3": {}, "workloads": {}}
    verdict_rows = []
    case_results = {a: [] for a in H3_POLICIES}
    win_rows, reg_rows = [], []

    for sc, t in workloads:
        wl = f"{sc}_t{t}"
        span = {l: [span_run("e6", r) for r in sorted(g[(sc, t, l)], key=lambda r: r["meta"]["rep"])]
                for l in locks_all if (sc, t, l) in g}
        comp = S + [a for a in ADAPTIVE if a in span]
        thr = {l: [x[0] for x in span[l]] for l in comp}
        ts = {l: stats.TailSet([x[1] for x in span[l]], 0.99) for l in comp}

        def evaluate(idx):
            m = {l: stats.mean([thr[l][i] for i in idx[l]]) for l in comp}
            top = max(m[l] for l in S)
            tied = [l for l in S if m[l] >= 0.99 * top]
            b = min(tied, key=lambda l: ts[l].quantile(idx[l], 0.99))
            pb = ts[b].quantile(idx[b], 0.999)
            out = {"bstar": b}
            for a in comp:
                if a not in S:
                    out[a] = (m[a] / m[b], ts[a].quantile(idx[a], 0.999) / pb)
            return out

        point, reps = boot_eval(evaluate, {l: len(thr[l]) for l in comp})
        bstar = point["bstar"]
        bstar_share = sum(r["bstar"] == bstar for r in reps) / len(reps)
        wd = {"bstar": bstar, "bstar_share_in_bootstrap": bstar_share, "locks": {}, "phases": {}}

        for a in [x for x in comp if x not in S]:
            tr, tl = point[a]
            tci = stats.percentile_interval([r[a][0] for r in reps])
            lci = stats.percentile_interval([r[a][1] for r in reps])
            vt, vl = verdict(tr, 0.85, tci), verdict(tl, 1.2, lci, higher_is_support=False)
            res = combine(vt, vl)
            wd["locks"][a] = {"thr_ratio": tr, "thr_ci": tci, "thr_verdict": vt,
                              "tail_ratio": tl, "tail_ci": lci, "tail_verdict": vl, "result": res,
                              "confirmatory": a in H3_POLICIES}
            if a in H3_POLICIES:
                case_results[a].append(res)
                verdict_rows.append(f"| {sc} T={t} | {a} | {bstar} ({bstar_share:.0%}) | {tr:.3f} [{tci[0]:.3f}, {tci[1]:.3f}] ({vt}) | "
                                    f"{tl:.2f} [{lci[0]:.2f}, {lci[1]:.2f}] ({vl}) | **{res}** |")

        # descriptive table over the span, every lock
        rows = []
        for l in [x for x in locks_all if x in span]:
            rs = sorted(g[(sc, t, l)], key=lambda r: r["meta"]["rep"])
            pooled = stats.merge(x[1] for x in span[l])
            ex = [run_extras(r, span_phases(r)) for r in rs]
            row = {"thr_mean": stats.mean([x[0] for x in span[l]]), "p50": stats.hist_quantile(pooled, 0.5),
                   "p99": stats.hist_quantile(pooled, 0.99), "p999": stats.hist_quantile(pooled, 0.999),
                   "wait_weighted_p50": stats.weighted_quantile(pooled, 0.5),
                   "wait_weighted_p99": stats.weighted_quantile(pooled, 0.99),
                   "jain": mean_of([e["jain"] for e in ex]),
                   "worst_thread_p99": median_of([e["worst_thread_p99"] for e in ex]),
                   "cpu_util": mean_of([e["cpu_util"] for e in ex]),
                   "budget_mean_ns": mean_of([e["budget_mean_ns"] for e in ex]),
                   "forced_frac": mean_of([e["forced_frac"] for e in ex]),
                   "wake_mean_ns": mean_of([e["wake_mean_ns"] for e in ex if e["wake_n"]]),
                   "policy_regret_ns_per_slow": mean_of([e["policy_regret_ns_per_slow"] for e in ex]),
                   "arm_share": [mean_of([e["arm_share"][k] for e in ex]) for k in range(K_ARMS)]}
            wd["locks"].setdefault(l, {}).update(row)
            rows.append((l, row))

            # per logical phase (exploratory)
            lm = rs[0]["meta"].get("logical_phases")
            if lm:
                for L in sorted({x for x in lm if x is not None}):
                    i = lm.index(L)
                    pthr = stats.mean([r["result"]["phases"][i]["throughput_ops_s"] for r in rs])
                    ph = stats.merge(run_hist("e6", r).get(i, {}) for r in rs)
                    wd["phases"].setdefault(str(L), {})[l] = {
                        "thr_mean": pthr, "p99": stats.hist_quantile(ph, 0.99), "p999": stats.hist_quantile(ph, 0.999),
                        "jain": stats.mean([r["result"]["phases"][i]["jain"] for r in rs]),
                        "budget_mean_ns": mean_of([run_extras(r, [i])["budget_mean_ns"] for r in rs])}

            # windows: regret against B* and adaptation time series
            ws = windows_series("e6", rs)
            for w in ws:
                win_rows.append({"workload": wl, "lock": l, "t_ms": w["t_ms"], "phase": w["phase"],
                                 "ops": round(w["ops"], 1),
                                 "budget_mean_ns": round(w["budget"] / w["slow"], 1) if w["slow"] else "",
                                 "park_per_slow": round(w["parks"] / w["slow"], 4) if w["slow"] else "",
                                 "forced_frac": round(w["forced"] / w["slow"], 4) if w["slow"] else ""})
            wd["locks"][l]["_windows"] = ws

        base = wd["locks"][bstar]["_windows"]
        for l in wd["locks"]:
            ws = wd["locks"][l].pop("_windows")
            if l == bstar:
                continue
            cum_b = cum_l = 0.0
            for wb, wl_ in zip(base, ws):
                cum_b += wb["ops"]
                cum_l += wl_["ops"]
                reg_rows.append({"workload": wl, "lock": l, "bstar": bstar, "t_ms": wb["t_ms"],
                                 "cum_ops_bstar": round(cum_b, 1), "cum_ops_lock": round(cum_l, 1),
                                 "regret_ops": round(cum_b - cum_l, 1)})
            wd["locks"][l]["final_regret_frac"] = (cum_b - cum_l) / cum_b if cum_b else float("nan")
        data["workloads"][wl] = wd

        md += [f"## {sc}, T={t} (B* = {bstar}; chosen in {bstar_share:.0%} of bootstrap resamples)", "",
               "| Lock | Throughput (M ops/s) | vs B* | p50 | p99 | p99.9 | p99.9 vs B* | Wait-weighted p50 / p99 | Jain | Worst-thread p99 (median run) | CPU (cores) | Mean budget | Regret vs B* |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        b = wd["locks"][bstar]
        for l, row in sorted(rows, key=lambda x: -x[1]["thr_mean"]):
            reg = wd["locks"][l].get("final_regret_frac")
            bud = fmt_ns(row["budget_mean_ns"]) if l in ADAPTIVE else "–"
            md.append(f"| {l}{' (B*)' if l == bstar else ''} | {row['thr_mean']/1e6:.3f} | {row['thr_mean']/b['thr_mean']:.3f} | "
                      f"{fmt_ns(row['p50'])} | {fmt_ns(row['p99'])} | {fmt_ns(row['p999'])} | {row['p999']/b['p999']:.2f} | "
                      f"{fmt_ns(row['wait_weighted_p50'])} / {fmt_ns(row['wait_weighted_p99'])} | {row['jain']:.3f} | "
                      f"{fmt_ns(row['worst_thread_p99'])} | {row['cpu_util']:.2f} | {bud} | "
                      f"{'–' if reg is None else f'{reg:+.1%}'} |")
        md.append("")
        if wd["phases"]:
            md += ["Per phase (exploratory; transition windows excluded): throughput in M ops/s, p99.9.", "",
                   "| Lock | " + " | ".join(f"Phase {L} thr | Phase {L} p99.9" for L in sorted(wd["phases"])) + " |",
                   "|---|" + "---|---|" * len(wd["phases"])]
            for l in [x for x in locks_all if x in span]:
                cells = []
                for L in sorted(wd["phases"]):
                    x = wd["phases"][L][l]
                    best = max(wd["phases"][L][s_]["thr_mean"] for s_ in S)
                    cells += [f"{x['thr_mean']/1e6:.3f} ({x['thr_mean']/best:.2f})", fmt_ns(x["p999"])]
                md.append(f"| {l} | " + " | ".join(cells) + " |")
            md += ["", "(ratio in brackets: vs the best static lock in that phase)", ""]

    for a in H3_POLICIES:
        rs_ = case_results[a]
        data["h3"][a] = {"met": rs_.count("met"), "not_met": rs_.count("not met"),
                         "inconclusive": rs_.count("inconclusive"), "verdict": overall(rs_)}
    md += ["## H3 (confirmatory)", "",
           "Per workload: throughput ratio ≥ 0.85 **and** p99.9 ratio ≤ 1.2 against B*, the best static lock over the span. "
           "Each bound is judged by the pre-registered rule (point estimate decides; a 95% interval containing the threshold makes "
           "it inconclusive); bounds combine per C1.", "",
           "| Workload | Policy | B* (bootstrap share) | Throughput ratio [95% CI] | p99.9 ratio [95% CI] | Result |",
           "|---|---|---|---|---|---|"] + verdict_rows + [""]
    for a in H3_POLICIES:
        h = data["h3"][a]
        md.append(f"- **Policy {'A (ada)' if a == 'ada' else 'B (hedge)'}: H3 {h['verdict']}** "
                  f"({h['met']} met, {h['not_met']} not met, {h['inconclusive']} inconclusive of 6)")
    md += ["", "Exploratory rows (exp3, ta) in the tables above are not part of the verdict."]
    write("e6", md, data)
    write_csv("e6_windows", win_rows)
    write_csv("e6_regret", reg_rows)
    return data["h3"]


def write_csv(name, rows):
    if not rows:
        return
    path = RES / "analysis" / f"{name}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}")


# ---- E7 / H4 -----------------------------------------------------------------

def analyze_e7():
    runs = load_runs("e7")
    S = static_family()
    g = group(runs, "hold_ns", "quota_pct", "lock")
    locks_all = S + ALL_EXTRA + ["ada", "hedge", "ta"]
    md = ["# E7: throttled runs (H4)", "",
          "Generated by `scripts/analyze.py e7`. Steady workload, T = 16, think 1 µs, 2 s, pinned; each run in its own systemd "
          "scope with `CPUQuota` (period 100 ms). p99.9 from histograms pooled over runs; intervals by bootstrap over runs "
          "(2,000 resamples), the minimum over S recomputed in each resample (C2). The `none` rows are an exploratory "
          "unthrottled reference (scope without a quota, 5 runs).", ""]
    data = {"cases": {}, "h4": {}}
    results, vrows = [], []
    for h in sorted({k[0] for k in g}):
        for q in [200, 400, None]:
            if not any(k[0] == h and k[1] == q for k in g):
                continue
            case = f"hold{h}_q{q if q else 'none'}"
            rows = {}
            for l in locks_all:
                rs = g.get((h, q, l))
                if not rs:
                    continue
                pooled = stats.merge(run_hist("e7", r)[0] for r in rs)
                ex = [run_extras(r, [0]) for r in rs]
                cg = [e["cgroup"] for e in ex if e["cgroup"]]
                ta = [e["lock_report"]["ta"] for e in ex if e["lock_report"] and "ta" in e["lock_report"]]
                rows[l] = {"runs": len(rs), "thr_mean": stats.mean([r["result"]["throughput_ops_s"] for r in rs]),
                           "p50": stats.hist_quantile(pooled, 0.5), "p99": stats.hist_quantile(pooled, 0.99),
                           "p999": stats.hist_quantile(pooled, 0.999),
                           "wait_weighted_p99": stats.weighted_quantile(pooled, 0.99),
                           "jain": mean_of([e["jain"] for e in ex]),
                           "worst_thread_p99": median_of([e["worst_thread_p99"] for e in ex]),
                           "cpu_util": mean_of([e["cpu_util"] for e in ex]),
                           "forced_frac": mean_of([e["forced_frac"] for e in ex]),
                           "budget_mean_ns": mean_of([e["budget_mean_ns"] for e in ex]),
                           "throttled_periods_frac": mean_of([c["nr_throttled"] / c["nr_periods"] for c in cg if c["nr_periods"]]),
                           # cpu.stat throttled_usec is summed over CPUs
                           "throttled_cpu_ms_per_s": mean_of([c["throttled_usec"] / 1e3 / 2.0 for c in cg]),
                           "usage_cores": mean_of([c["usage_usec"] / 2e6 for c in cg]),
                           "ta_triggers": mean_of([x["triggers"] for x in ta]) if ta else None,
                           "ta_park_ms": mean_of([x["park_ms"] for x in ta]) if ta else None,
                           "_tail": stats.TailSet([run_hist("e7", r)[0] for r in rs], 0.999)}
            cd = {"hold_ns": h, "quota_pct": q, "locks": rows}
            if q is not None:
                comp = S + ["ta"]

                def evaluate(idx):
                    p = {l: rows[l]["_tail"].quantile(idx[l], 0.999) for l in comp}
                    return (p["spin"] / p["ta"], p["ta"] / min(p[s_] for s_ in S),
                            min(S, key=lambda s_: p[s_]))

                point, reps = boot_eval(evaluate, {l: rows[l]["runs"] for l in comp})
                aci = stats.percentile_interval([r[0] for r in reps])
                bci = stats.percentile_interval([r[1] for r in reps])
                va, vb = verdict(point[0], 2.0, aci), verdict(point[1], 1.10, bci, higher_is_support=False)
                res = combine(va, vb)
                results.append(res)
                cd["h4"] = {"spin_over_ta": point[0], "spin_over_ta_ci": aci, "a_verdict": va,
                            "ta_over_best_static": point[1], "ta_over_best_static_ci": bci, "b_verdict": vb,
                            "best_static_tail": point[2], "result": res}
                vrows.append(f"| hold {fmt_ns(h)}, quota {q}% | {point[0]:.2f} [{aci[0]:.2f}, {aci[1]:.2f}] ({va}) | "
                             f"{point[2]} | {point[1]:.2f} [{bci[0]:.2f}, {bci[1]:.2f}] ({vb}) | **{res}** |")
            for l in rows:
                rows[l].pop("_tail")
            data["cases"][case] = cd
            md += [f"## hold {fmt_ns(h)}, quota {str(q) + '%' if q else 'none (exploratory reference)'}", "",
                   "| Lock | Throughput (M ops/s) | p50 | p99 | p99.9 | Wait-weighted p99 | Jain | Worst-thread p99 | CPU used (cores) | Throttled periods | Throttled CPU-ms/s | Forced parks | Mean budget |",
                   "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for l, x in sorted(rows.items(), key=lambda kv: kv[1]["p999"]):
                md.append(f"| {l} | {x['thr_mean']/1e6:.3f} | {fmt_ns(x['p50'])} | {fmt_ns(x['p99'])} | {fmt_ns(x['p999'])} | "
                          f"{fmt_ns(x['wait_weighted_p99'])} | {x['jain']:.3f} | {fmt_ns(x['worst_thread_p99'])} | "
                          f"{x['usage_cores']:.2f} | {x['throttled_periods_frac']:.0%} | {x['throttled_cpu_ms_per_s']:.0f} | "
                          f"{x['forced_frac']:.0%} | {fmt_ns(x['budget_mean_ns']) if l in ADAPTIVE else '–'} |")
            md.append("")
    data["h4"] = {"met": results.count("met"), "not_met": results.count("not met"),
                  "inconclusive": results.count("inconclusive"), "verdict": overall(results)}
    md += ["## H4 (confirmatory)", "",
           "Per case: (a) p99.9(spin) / p99.9(ta) ≥ 2 **and** (b) p99.9(ta) ≤ 1.10 × the lowest static p99.9 under the same quota. "
           "Bounds combine per C1.", "",
           "| Case | (a) spin / ta [95% CI] | Lowest-p99.9 static | (b) ta / best static [95% CI] | Result |",
           "|---|---|---|---|---|"] + vrows + ["",
           f"**Verdict: H4 {data['h4']['verdict']}** ({data['h4']['met']} met, {data['h4']['not_met']} not met, "
           f"{data['h4']['inconclusive']} inconclusive of {len(results)} cases)."]
    write("e7", md, data)
    return data["h4"]


# ---- E8: steady sweep of the adaptive locks (exploratory) -------------------------

def analyze_e8():
    runs = load_runs("e8")
    locks = ADAPTIVE + ["park", "spin"]
    md, data = steady_table("e8", runs, "E8: adaptive locks on the steady grid (exploratory)",
                            "Generated by `scripts/analyze.py e8`. 3 runs per cell. T = 4 cells are the tuning set "
                            "(in-sample). Compared with E2 (a different session) below; park and spin are anchors "
                            "re-run here to show session drift.", locks=locks, best_table=False)
    e2 = json.loads((RES / "analysis" / "e2.json").read_text())
    md += ["## Against E2 (different session; exploratory)", "",
           "Throughput of each lock divided by the best static lock of E2 in the same cell; anchors show E8/E2 for the same lock.", "",
           "| Cell | E2 best static | " + " | ".join(ADAPTIVE) + " | park E8/E2 | spin E8/E2 |",
           "|---|---|" + "---|" * (len(ADAPTIVE) + 2)]
    comp = {}
    for key, stat in data.items():
        ref = e2.get(key)
        if not ref:
            continue
        sref = {l: v for l, v in ref.items() if l in static_family()}
        b = max(sref, key=lambda l: sref[l]["thr_mean"])
        comp[key] = {"e2_best": b, **{l: stat[l]["thr_mean"] / sref[b]["thr_mean"] for l in ADAPTIVE if l in stat},
                     "park_anchor": stat["park"]["thr_mean"] / ref["park"]["thr_mean"],
                     "spin_anchor": stat["spin"]["thr_mean"] / ref["spin"]["thr_mean"]}
        c = comp[key]
        md.append(f"| {key} | {b} | " + " | ".join(f"{c[l]:.2f}" for l in ADAPTIVE if l in c) +
                  f" | {c['park_anchor']:.2f} | {c['spin_anchor']:.2f} |")
    data["vs_e2"] = comp
    write("e8", md, data)


ANALYSES = {"e1": analyze_e1, "e2": analyze_e2, "e3": analyze_e3, "e4": analyze_e4, "e5": analyze_e5,
            "t3": analyze_t3, "e6": analyze_e6, "e7": analyze_e7, "e8": analyze_e8}

if __name__ == "__main__":
    which = sys.argv[1:] or ["all"]
    for w in (ANALYSES if which == ["all"] else which):
        ANALYSES[w]()
