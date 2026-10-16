#!/usr/bin/env python3
"""Figures 1-7 and 10 and tables 8-9 of RESEARCH_PHASE.md section 7, from the raw
data and the analysis outputs.

usage: .venv/bin/python scripts/figures.py      (needs matplotlib: requirements.txt)
       (run scripts/analyze.py all first; it writes results/analysis/*.json)

Writes docs/figures/figN-<name>.svg (light), figN-<name>-dark.svg, and
figN-<name>.csv (the data behind each figure, its table view), plus
docs/figures/tables.md (tables 8 and 9).

Colours follow the entity across every figure: ada blue, hedge orange, ta aqua,
spin yellow, park magenta, exp3 violet, glibc green (pthread / native) and red
(pthread-adaptive); static stp:<budget> locks are neutral greys, darker for
longer budgets. Palettes validated with the dataviz validator (adjacent CVD
dE >= 9.2 light, 9.4 dark). Light-mode magenta/yellow/aqua are below 3:1 on
the surface, so those series are always direct-labelled.
"""
import csv
import gzip
import json
import math
import sys
from bisect import bisect_right
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import stats  # noqa: E402

ROOT = analyze.ROOT
RES = analyze.RES
OUT = ROOT / "docs" / "figures"

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "band": "#f0efec",
        "lock": {"ada": "#2a78d6", "hedge": "#eb6834", "ta": "#1baf7a", "spin": "#eda100",
                 "park": "#e87ba4", "exp3": "#6250d6", "pthread": "#008300", "native": "#008300",
                 "pthread-adaptive": "#e34948",
                 "stp:2350": "#a7a59f", "stp:4750": "#898781", "stp:9450": "#6d6c67", "stp:37850": "#52514e"},
        "idle": ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],          # blue ordinal ramp 250..700
        "budget": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#0d366b"],
        "quota": ["#a7a59f", "#6d6c67", "#0b0b0b"],
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "band": "#232322",
        "lock": {"ada": "#3987e5", "hedge": "#d95926", "ta": "#199e70", "spin": "#c98500",
                 "park": "#d55181", "exp3": "#9085e9", "pthread": "#008300", "native": "#008300",
                 "pthread-adaptive": "#e66767",
                 "stp:2350": "#5c5b57", "stp:4750": "#7a7974", "stp:9450": "#9a9890", "stp:37850": "#c3c2b7"},
        "idle": ["#184f95", "#2a78d6", "#6da7ec", "#b7d3f6"],
        "budget": ["#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"],
        "quota": ["#5c5b57", "#9a9890", "#f0efec"],
    },
}
T = THEMES["light"]


def style(theme):
    global T
    T = THEMES[theme]
    plt.rcParams.update({
        "svg.fonttype": "none", "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Liberation Sans", "Arial"], "font.size": 9,
        "figure.facecolor": T["surface"], "axes.facecolor": T["surface"], "savefig.facecolor": T["surface"],
        "axes.edgecolor": T["axis"], "axes.labelcolor": T["ink2"], "axes.titlecolor": T["ink"],
        "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "xtick.color": T["muted"], "ytick.color": T["muted"], "xtick.labelcolor": T["ink2"],
        "ytick.labelcolor": T["ink2"], "text.color": T["ink"],
        "axes.grid": True, "grid.color": T["grid"], "grid.linewidth": 0.75, "grid.linestyle": "-",
        "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
        "lines.linewidth": 1.5, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
        "legend.frameon": False, "legend.labelcolor": T["ink2"],
    })


def save(fig, name, theme):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}{'' if theme == 'light' else '-dark'}.svg", bbox_inches="tight")
    plt.close(fig)


def write_csv(name, header, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def jload(name):
    return json.loads((RES / "analysis" / f"{name}.json").read_text())


def us(x):
    return x / 1e3


def lc(lock):
    return T["lock"].get(lock, T["ink2"])


def bottom_legend(fig, ax, ncol, title=None):
    """One legend under all panels, outside the plot area, so it never sits
    on data."""
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=ncol, fontsize=8, bbox_to_anchor=(0.5, -0.01),
               title=title, title_fontsize=8)
    fig.tight_layout(rect=(0, 0.08, 1, 1))


def plain_log(axis):
    """Log axis with plain tick labels (1, 2, 5 x 10^k) instead of 10^k."""
    axis.set_major_locator(matplotlib.ticker.LogLocator(base=10, subs=(1, 2, 5)))
    axis.set_minor_locator(matplotlib.ticker.NullLocator())
    axis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))


def end_label(ax, x, y, text, color_mark):
    """Direct label at a line end: text in ink, identity from the line itself."""
    ax.annotate(text, (x, y), xytext=(4, 0), textcoords="offset points", va="center", ha="left",
                fontsize=8, color=T["ink2"])


# ---- Figure 1: wake-up latency CDFs (E1) -----------------------------------------

def fig1_data():
    conds = {}
    for f in sorted((RES / "e1" / "runs").glob("*.csv.gz")):
        cid = f.name.rsplit("_r", 1)[0]
        if "load" in cid:
            continue
        with gzip.open(f, "rt") as fh:
            conds.setdefault(cid, []).extend(float(r["wake_ns"]) for r in csv.DictReader(fh) if r["woke"] == "1")
    for v in conds.values():
        v.sort()
    return conds


def fig1(theme, conds):
    places = [("smt-sibling", "SMT sibling (CPU 2 ↔ 3)"), ("other-core", "Other core (CPU 2 ↔ 4)"),
              ("same-cpu", "Same CPU (2 ↔ 2)")]
    idles = [(20, "20 µs"), (100, "100 µs"), (1000, "1 ms"), (10000, "10 ms")]
    grid = [10 ** (0 + 3.5 * i / 299) for i in range(300)]          # 1 µs .. ~3.2 ms
    fig, axs = plt.subplots(1, 3, figsize=(10, 3.2), sharey=True)
    rows = []
    for ax, (p, title) in zip(axs, places):
        for k, (idle, lab) in enumerate(idles):
            v = conds[f"{p}_idle{idle}us"]
            ys = [bisect_right(v, x * 1e3) / len(v) for x in grid]
            ax.plot(grid, ys, color=T["idle"][k], label=f"idle {lab}")
            med = stats.quantile_sorted(v, 0.5)
            rows += [(p, idle, f"{x:.4g}", f"{y:.5f}") for x, y in zip(grid[::10], ys[::10])]
            rows.append((p, idle, "median_us", f"{med/1e3:.3f}"))
        ax.set_xscale("log")
        ax.set_xlim(1, 3000)
        ax.set_ylim(0, 1.01)
        ax.set_title(title)
        ax.set_xlabel("wake-up latency (µs, log scale)")
    axs[0].set_ylabel("fraction of wake-ups ≤ x")
    axs[0].legend(loc="lower right", fontsize=8, title="sleeper idle before wake", title_fontsize=8)
    fig.suptitle("Figure 1. Futex wake-up latency depends on how long the sleeper's CPU idled (E1, 3 runs per condition)",
                 x=0.01, ha="left", fontsize=10, color=T["ink"])
    fig.tight_layout()
    save(fig, "fig1-wake-cdf", theme)
    return rows


# ---- Figure 2: best static lock per hold x threads (E2) ----------------------------

BUDGET_ORDER = ["park", "stp:2350", "stp:4750", "stp:9450", "stp:37850", "spin"]


def fig2(theme):
    e2 = jload("e2")
    holds, threads = [100, 1000, 10000, 50000], [4, 8, 16, 32]
    fig, ax = plt.subplots(figsize=(8.8, 4.4))
    rows = []
    for i, h in enumerate(holds):
        for j, t in enumerate(threads):
            stat = e2[f"h{h}_t{t}"]
            st = {l: v for l, v in stat.items() if l in BUDGET_ORDER}
            best = analyze.best_static(st)
            overall = max(stat, key=lambda l: stat[l]["thr_mean"])
            ratio_park = st[best]["thr_mean"] / st["park"]["thr_mean"]
            k = BUDGET_ORDER.index(best)
            fill = T["budget"][k]
            ax.add_patch(plt.Rectangle((j + 0.03, i + 0.03), 0.94, 0.94, color=fill, lw=0))
            r, g, b = (int(fill[1 + 2 * q:3 + 2 * q], 16) / 255 for q in range(3))
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            tc = "#0b0b0b" if lum > 0.45 else "#fcfcfb"
            label = f"{best}\n{st[best]['thr_mean']/1e6:.3g} M ops/s\n{ratio_park:.2f}× park"
            if overall != best:
                label += f"\n(overall best: {overall})"
            ax.text(j + 0.5, i + 0.5, label, ha="center", va="center", fontsize=7.5, color=tc, linespacing=1.3)
            rows.append((h, t, best, f"{st[best]['thr_mean']:.0f}", f"{ratio_park:.3f}", overall))
    ax.set_xlim(0, 4)
    ax.set_ylim(0, 4)
    ax.set_xticks([x + 0.5 for x in range(4)], [f"T = {t}" for t in threads])
    ax.set_yticks([y + 0.5 for y in range(4)], ["100 ns", "1 µs", "10 µs", "50 µs"])
    ax.set_xlabel("threads (8 = physical cores, 16 = logical CPUs)")
    ax.set_ylabel("critical-section hold time")
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    handles = [Patch(color=T["budget"][k], label=n) for k, n in enumerate(BUDGET_ORDER)]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8,
              title="best static lock\n(shorter → longer spin)", title_fontsize=8)
    ax.set_title("Figure 2. No static lock wins everywhere: best of the static family per cell (E2, 5 runs, pinned)")
    fig.tight_layout()
    save(fig, "fig2-best-lock-map", theme)
    return rows


# ---- Figure 3: throughput over time across the hold-time shifts (E4, S1) ------------------

FIG3_LOCKS = ["park", "stp:4750", "stp:37850", "spin"]


def window_mean(exp, rs):
    """Mean ops per window over runs (works for Phase 2 window files, which
    have no slow-path columns)."""
    acc = None
    for r in rs:
        with open(RES / exp / "runs" / f"{r['run_id']}.win.csv") as f:
            rows = list(csv.DictReader(f))
        if acc is None:
            acc = [{"t_ms": float(w["t_ms"]), "ops": 0.0} for w in rows]
        for a, w in zip(acc, rows):
            a["ops"] += int(w["ops"]) / len(rs)
    return acc


def fig3(theme):
    g = analyze.group(analyze.load_runs("e4"), "schedule", "threads", "lock")
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.4), sharey=True)
    rows = []
    for ax, t in zip(axs, (8, 16)):
        for x0, x1 in ((1.5, 1.6), (3.0, 3.1)):
            ax.axvspan(x0, x1, color=T["band"], lw=0, zorder=0)
        for l in FIG3_LOCKS:
            ws = window_mean("e4", g[("S1", t, l)])
            xs = [w["t_ms"] / 1e3 for w in ws]
            ys = [max(w["ops"] / 0.01 / 1e6, 1e-3) for w in ws]
            ax.plot(xs, ys, color=lc(l), label=l, lw=1.25)
            rows += [(t, l, f"{x:.2f}", f"{y:.4f}") for x, y in zip(xs, ys)]
        ax.set_yscale("log")
        plain_log(ax.yaxis)
        ax.set_ylim(0.02, 6)
        ax.set_xlim(0, 4.5)
        ax.set_title(f"T = {t}")
        ax.set_xlabel("time (s)   —   hold 100 ns | 20 µs | 100 ns; shaded: 100 ms transition windows")
    axs[0].set_ylabel("throughput per 10 ms window (M ops/s, log)")
    fig.suptitle("Figure 3. The best static lock before a hold-time shift is not the best after it (E4 S1, mean of 10 runs)",
                 x=0.01, ha="left", fontsize=10, color=T["ink"])
    bottom_legend(fig, axs[0], 4)
    save(fig, "fig3-phase-change", theme)
    return rows


# ---- Figure 4a: H3 ratios with intervals; 4b: regret over time (E6) -------------------------

WORKLOADS = ["S1_t8", "S1_t16", "S2_t8", "S2_t16", "R1_t8", "R1_t16"]


def wl_label(w):
    sc, t = w.split("_t")
    return f"{sc}, T={t}"


def fig4a(theme):
    e6 = jload("e6")
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    rows = []
    for ax, (key, ci, thr, xl, log) in zip(axs, [
            ("thr_ratio", "thr_ci", 0.85, "throughput ÷ best static (B*)", False),
            ("tail_ratio", "tail_ci", 1.2, "p99.9 ÷ p99.9 of B* (log; lower is better)", True)]):
        ax.axvline(thr, color=T["ink2"], lw=1)
        ax.annotate(f"H3 bound {thr}", (thr, len(WORKLOADS) - 0.45), xytext=(3, 0), textcoords="offset points",
                    fontsize=7.5, color=T["ink2"], va="center")
        for k, a in enumerate(["ada", "hedge"]):
            for i, w in enumerate(WORKLOADS):
                x = e6["workloads"][w]["locks"][a]
                y = len(WORKLOADS) - 1 - i + (0.15 if k == 0 else -0.15)
                lo, hi = x[ci]
                ax.plot([lo, hi], [y, y], color=lc(a), lw=1.5, solid_capstyle="butt")
                ax.plot([x[key]], [y], "o", ms=6, color=lc(a), mec=T["surface"], mew=1.5,
                        label=("Policy A (ada)" if a == "ada" else "Policy B (hedge)") if i == 0 else None)
                rows.append((w, a, key, f"{x[key]:.4f}", f"{lo:.4f}", f"{hi:.4f}", x["result"]))
        if log:
            ax.set_xscale("log")
            plain_log(ax.xaxis)
        ax.set_xlabel(xl)
        ax.set_ylim(-0.6, len(WORKLOADS) - 0.4)
        ax.grid(axis="y", visible=False)
    axs[0].set_yticks(range(len(WORKLOADS)), [wl_label(w) for w in reversed(WORKLOADS)])
    axs[0].tick_params(axis="y", length=0)
    axs[0].set_title("Throughput (must be ≥ 0.85)")
    axs[1].set_title("Tail latency (must be ≤ 1.2)")
    fig.suptitle("Figure 4a. H3: adaptive policies against the best static lock per workload (E6; dots = point estimate, "
                 "bars = 95% bootstrap interval)", x=0.01, ha="left", fontsize=10, color=T["ink"])
    bottom_legend(fig, axs[0], 2)
    save(fig, "fig4a-h3-ratios", theme)
    return rows


def fig4b(theme):
    reg = {}
    with open(RES / "analysis" / "e6_regret.csv") as f:
        for r in csv.DictReader(f):
            reg.setdefault((r["workload"], r["lock"]), []).append(
                (float(r["t_ms"]) / 1e3, (float(r["cum_ops_bstar"]) - float(r["cum_ops_lock"])) /
                 max(float(r["cum_ops_bstar"]), 1) * 100, r["bstar"]))
    fig, axs = plt.subplots(2, 3, figsize=(10, 5), sharex=True)
    rows = []
    for ax, w in zip(axs.flat, WORKLOADS):
        if not w.startswith("R1"):
            for x0, x1 in ((1.5, 1.6), (3.0, 3.1)):
                ax.axvspan(x0, x1, color=T["band"], lw=0, zorder=0)
        ax.axhline(0, color=T["axis"], lw=1)
        bstar = None
        for a in ["ada", "hedge", "exp3", "ta"]:
            pts = reg.get((w, a))
            if not pts:
                continue
            bstar = pts[0][2]
            xs, ys = [p[0] for p in pts[1:]], [p[1] for p in pts[1:]]
            ax.plot(xs, ys, color=lc(a), label=a, lw=1.25)
            rows += [(w, a, bstar, f"{x:.2f}", f"{y:.3f}") for x, y in zip(xs[::5], ys[::5])]
        ax.set_title(f"{wl_label(w)} (B* = {bstar})")
    for ax in axs[1]:
        ax.set_xlabel("time (s)")
    for ax in axs[:, 0]:
        ax.set_ylabel("cumulative regret vs B*\n(% of B*'s operations)")
    fig.suptitle("Figure 4b. Throughput regret against the best static lock over time (E6, mean of 10 runs; "
                 "below 0 = ahead of B*)", x=0.01, ha="left", fontsize=10, color=T["ink"])
    bottom_legend(fig, axs[0, 0], 4)
    save(fig, "fig4b-regret", theme)
    return rows


# ---- Figure 5: tails under oversubscription (T = 32; E2 static, E8 adaptive) -------------------

def dot_rows(ax, items, series, xlabel):
    """items: [(label, {series_key: value})]; series: [(key, label, color, filled)]."""
    n = len(items)
    for i, (lab, vals) in enumerate(items):
        y = n - 1 - i
        xs = [vals[k] for k, _, _, _ in series if vals.get(k) == vals.get(k)]
        if len(xs) > 1:
            ax.plot([min(xs), max(xs)], [y, y], color=T["axis"], lw=1, zorder=1)
        for k, sl, col, filled in series:
            v = vals.get(k)
            if v is None or v != v:
                continue
            if filled:   # filled dot with a 2 px surface ring, so overlapping dots stay legible
                ax.plot([v], [y], "o", ms=7.5, color=col, mfc=col, mec=T["surface"], mew=1.5, zorder=2,
                        label=sl if i == 0 else None)
            else:        # hollow ring: a second series that can share a row with the filled one
                ax.plot([v], [y], "o", ms=6, color=col, mfc=T["surface"], mec=col, mew=1.5, zorder=3,
                        label=sl if i == 0 else None)
    ax.set_yticks(range(n), [lab for lab, _ in reversed(items)])
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_xscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylim(-0.6, n - 0.4)


def fig5(theme):
    e2, e8 = jload("e2"), jload("e8")
    fig, axs = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    rows = []
    series = [("p99", "p99", T["ink2"], False), ("p999", "p99.9", T["ink"], True)]
    for ax, h in zip(axs, (1000, 10000)):
        key = f"h{h}_t32"
        items = []
        for l in BUDGET_ORDER + ["pthread", "pthread-adaptive"]:
            items.append((f"{l} (E2)", e2[key][l]))
        for l in analyze.ADAPTIVE:
            items.append((f"{l} (E8)", e8[key][l]))
        dot_rows(ax, items, series, "acquire latency (log)")
        ax.set_title(f"hold {'1 µs' if h == 1000 else '10 µs'}, T = 32 on 16 CPUs")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: f"{v/1e6:g} ms" if v >= 1e6 else f"{v/1e3:g} µs" if v >= 1e3 else f"{v:g} ns"))
        rows += [(h, lab, f"{v['p99']:.1f}", f"{v['p999']:.1f}", f"{v['thr_mean']:.0f}") for lab, v in items]
    fig.suptitle("Figure 5. Tail latency under 2× oversubscription (static: E2; adaptive: E8, a later session, "
                 "3 runs; pooled histograms)", x=0.01, ha="left", fontsize=10, color=T["ink"])
    bottom_legend(fig, axs[0], 2)
    save(fig, "fig5-oversubscription", theme)
    return rows


# ---- Figure 6: throttled vs unthrottled p99.9 (E7) -------------------------------------------

def fig6(theme):
    e7 = jload("e7")
    locks = BUDGET_ORDER + ["pthread", "pthread-adaptive", "ada", "hedge", "ta"]
    fig, axs = plt.subplots(1, 2, figsize=(10, 4.4), sharey=True)
    rows = []
    series = [("none", "no quota (5 runs)", T["quota"][0], True), ("400", "quota 400%", T["quota"][1], True),
              ("200", "quota 200%", T["quota"][2], True)]
    for ax, h in zip(axs, (1000, 10000)):
        items = []
        for l in locks:
            vals = {q: e7["cases"][f"hold{h}_q{q}"]["locks"][l]["p999"] for q in ("none", "400", "200")}
            items.append(("ta (throttle-aware)" if l == "ta" else l, vals))
            rows.append((h, l, *(f"{vals[q]:.1f}" for q in ("none", "400", "200"))))
        dot_rows(ax, items, series, "p99.9 acquire latency (log)")
        ax.set_title(f"hold {'1 µs' if h == 1000 else '10 µs'}, T = 16, period 100 ms")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: f"{v/1e6:g} ms" if v >= 1e6 else f"{v/1e3:g} µs" if v >= 1e3 else f"{v:g} ns"))
    fig.suptitle("Figure 6. CPU quota throttling and the throttle-aware lock (E7, 10 runs per quota; "
                 "H4 compares ta with spin and with the lowest static p99.9)", x=0.01, ha="left", fontsize=10, color=T["ink"])
    bottom_legend(fig, axs[0], 3)
    save(fig, "fig6-throttling", theme)
    return rows


# ---- Figure 7: real application (E9, SQLite through the shim) ----------------------------------

FIG7_LOCKS = ["native", "park", "stp:37850", "spin", "ada", "hedge", "ta"]


def fig7(theme):
    e9 = jload("e9")
    threads = sorted(int(k[1:]) for k in e9)
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    rows = []
    for ax, (key, yl, scale) in zip(axs, [("thr_mean", "throughput (M ops/s)", 1e6), ("p99", "p99 operation latency (µs)", 1e3)]):
        for l in FIG7_LOCKS:
            ys = [e9[f"t{t}"][l][key] / scale for t in threads]
            ax.plot(threads, ys, "-o", color=lc(l), ms=5, mec=T["surface"], mew=1.5,
                    label="native (glibc mutex)" if l == "native" else l)
            rows += [(l, t, key, f"{y:.4f}") for t, y in zip(threads, ys)]
        ax.set_xscale("log", base=2)
        ax.set_xticks(threads, [str(t) for t in threads])
        ax.set_xlim(threads[0] * 0.85, threads[-1] * 1.15)
        ax.set_xlabel("threads sharing one SQLite connection")
        ax.set_ylabel(yl)
        if key == "p99":
            ax.set_yscale("log")
            plain_log(ax.yaxis)
    axs[0].set_title("Throughput")
    axs[1].set_title("Tail latency")
    fig.suptitle("Figure 7. SQLite (serialized mode) with glibc's mutex vs futex-lab locks via LD_PRELOAD (E9, 5 runs)",
                 x=0.01, ha="left", fontsize=10, color=T["ink"])
    bottom_legend(fig, axs[0], 7)
    save(fig, "fig7-sqlite", theme)
    return rows


# ---- Figure 10: policy overhead -----------------------------------------------------------------

def overhead_data():
    unc, pol = {}, {}
    for f in sorted((RES / "overhead").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r["tool"] == "calib-timer":
                for k, v in r["uncontended_lock_unlock_ns"].items():
                    unc.setdefault(k, []).append(v)
            elif r["tool"] == "calib-policy":
                for k, v in r["policies"].items():
                    pol.setdefault(k, {"choose": [], "update": []})
                    pol[k]["choose"].append(v["choose_ns"])
                    pol[k]["update"].append(v["update_ns"])
    med = lambda v: stats.quantile_sorted(sorted(v), 0.5)
    return {k: med(v) for k, v in unc.items()}, {k: {m: med(x) for m, x in v.items()} for k, v in pol.items()}


def fig10(theme):
    unc, pol = overhead_data()
    order = ["none", "spin", "park", "stp:1000", "ada", "hedge", "exp3", "ta", "pthread", "pthread-adaptive"]
    order = [k for k in order if k in unc]
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.4), gridspec_kw={"width_ratios": [1.2, 1]})
    rows = []
    ax = axs[0]
    ys = list(range(len(order)))[::-1]
    ax.barh(ys, [unc[k] for k in order], height=0.55, color=T["ink2"])
    for y, k in zip(ys, order):
        ax.text(unc[k] + 0.12, y, f"{unc[k]:.2f} ns", va="center", fontsize=8, color=T["ink2"])
        rows.append(("uncontended_lock_unlock", k, f"{unc[k]:.3f}"))
    ax.set_yticks(ys, order)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(unc.values()) * 1.25)
    ax.set_xlabel("uncontended lock + unlock (ns, median of 3)")
    ax.set_title("Fast path (no contention)")
    ax = axs[1]
    ks = [k for k in ("ada", "hedge", "exp3") if k in pol]
    ys = list(range(len(ks)))[::-1]
    h = 0.32
    ax.barh([y + h / 2 + 0.02 for y in ys], [pol[k]["choose"] for k in ks], height=h, color=T["quota"][1],
            label="choose (slow path, before spinning)")
    ax.barh([y - h / 2 - 0.02 for y in ys], [pol[k]["update"] for k in ks], height=h, color=T["ink"],
            label="update (after the release)")
    for y, k in zip(ys, ks):
        ax.text(pol[k]["choose"] + 0.5, y + h / 2 + 0.02, f"{pol[k]['choose']:.1f}", va="center", fontsize=8, color=T["ink2"])
        ax.text(pol[k]["update"] + 0.5, y - h / 2 - 0.02, f"{pol[k]['update']:.1f}", va="center", fontsize=8, color=T["ink2"])
        rows += [("policy_choose", k, f"{pol[k]['choose']:.3f}"), ("policy_update", k, f"{pol[k]['update']:.3f}")]
    ax.set_yticks(ys, ks)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(max(v.values()) for v in pol.values()) * 1.25)
    ax.set_xlabel("ns per slow-path acquisition (median of 3)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=7.5)
    ax.set_title("Policy bookkeeping (off the critical section)")
    fig.suptitle("Figure 10. Overhead of the adaptive locks (calib timer / calib policy, single thread)",
                 x=0.01, ha="left", fontsize=10, color=T["ink"])
    fig.tight_layout()
    save(fig, "fig10-overhead", theme)
    return rows


# ---- Tables 8 and 9 ------------------------------------------------------------------------------

def tables():
    e6, e7 = jload("e6"), jload("e7")
    locks = BUDGET_ORDER + ["pthread", "pthread-adaptive"] + analyze.ADAPTIVE
    md = ["# Tables 8 and 9", "", "Generated by `scripts/figures.py` from `results/analysis/e6.json`, `e7.json` and "
          "`RESEARCH_PHASE.md` §3.4.", "",
          "## Table 8. Fairness (exploratory): Jain's index over the span, and runs (of 10) in which an active thread "
          "got zero acquisitions in a measured phase", "",
          "| Lock | " + " | ".join(wl_label(w) for w in WORKLOADS) + " | E7 hold 10 µs, 400% | E7 hold 10 µs, no quota (of 5) |",
          "|---|" + "---|" * (len(WORKLOADS) + 2)]
    for l in locks:
        cells = []
        for w in WORKLOADS:
            x = e6["workloads"][w]["locks"][l]
            cells.append(f"{x['jain']:.2f} ({x['starved_runs']})")
        for c in ("hold10000_q400", "hold10000_qnone"):
            x = e7["cases"][c]["locks"].get(l)
            cells.append(f"{x['jain']:.2f} ({x['starved_runs']})" if x else "– (not run)")
        md.append(f"| {l} | " + " | ".join(cells) + " |")
    md += ["", "Cell: Jain's index (1 = equal shares) and, in brackets, the starved-run count.", "",
           "## Table 9. Hypothesis summary (confirmatory; RESEARCH_PHASE.md §3.4)", ""]
    text = (ROOT / "RESEARCH_PHASE.md").read_text()
    sec = text[text.index("| Hypothesis | Threshold | Observed result | Verdict |"):]
    md += sec[:sec.index("\n\n")].splitlines()
    (OUT / "tables.md").write_text("\n".join(md) + "\n")


def main():
    conds = fig1_data()
    figs = [("fig1-wake-cdf", ["placement", "idle_us", "latency_us", "cdf"], lambda th: fig1(th, conds)),
            ("fig2-best-lock-map", ["hold_ns", "threads", "best_static", "thr_ops_s", "ratio_vs_park", "overall_best"], fig2),
            ("fig3-phase-change", ["threads", "lock", "t_s", "throughput_mops"], fig3),
            ("fig4a-h3-ratios", ["workload", "policy", "metric", "value", "ci_lo", "ci_hi", "result"], fig4a),
            ("fig4b-regret", ["workload", "lock", "bstar", "t_s", "regret_pct"], fig4b),
            ("fig5-oversubscription", ["hold_ns", "lock (experiment)", "p99_ns", "p999_ns", "thr_ops_s"], fig5),
            ("fig6-throttling", ["hold_ns", "lock", "p999_ns_noquota", "p999_ns_q400", "p999_ns_q200"], fig6),
            ("fig7-sqlite", ["lock", "threads", "metric", "value"], fig7),
            ("fig10-overhead", ["measure", "lock", "ns"], fig10)]
    for name, header, fn in figs:
        rows = None
        for th in ("light", "dark"):
            style(th)
            rows = fn(th)
        write_csv(name, header, rows)
        print(f"wrote docs/figures/{name}.svg, {name}-dark.svg, {name}.csv")
    tables()
    print("wrote docs/figures/tables.md")


if __name__ == "__main__":
    main()
