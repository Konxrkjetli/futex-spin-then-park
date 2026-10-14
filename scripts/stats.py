"""Statistics helpers (standard library only), implementing RESEARCH_PHASE.md 6.1.

- Order-statistic (distribution-free) interval for a median.
- Bootstrap over runs for means and ratios of means.
- Pooled log-linear histograms: load, merge, nearest-rank quantile, and
  bootstrap over runs by merging resampled runs' histograms.
"""
import csv
import math
import random
from collections import Counter

BOOT = 2000          # resamples (pre-registered; see deviation D12)
SEED = 20261014


def quantile_sorted(v, q):
    """Nearest-rank quantile of a sorted list."""
    if not v:
        return float("nan")
    r = max(1, min(len(v), math.ceil(q * len(v))))
    return v[r - 1]


def median_ci(sorted_v, level=0.95):
    """Distribution-free interval for the median via order statistics
    (normal approximation to the binomial; n is large here). Assumes
    independent samples, so it is optimistic if samples are autocorrelated;
    run-to-run spread is reported alongside it."""
    n = len(sorted_v)
    z = 1.959963984540054 if level == 0.95 else 2.5758293035489
    half = z * math.sqrt(n) / 2
    lo = max(1, math.floor(n / 2 - half))
    hi = min(n, math.ceil(n / 2 + half + 1))
    return sorted_v[lo - 1], sorted_v[hi - 1]


def percentile_interval(values, level=0.95):
    v = sorted(values)
    a = (1 - level) / 2
    return quantile_sorted(v, a), quantile_sorted(v, 1 - a)


def mean(v):
    return sum(v) / len(v)


def bootstrap(stat, groups, n=BOOT, seed=SEED):
    """groups: list of per-group run lists. Each resample draws runs with
    replacement independently within each group, then calls stat(*groups')."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        res = [[g[rng.randrange(len(g))] for _ in range(len(g))] for g in groups]
        out.append(stat(*res))
    return percentile_interval(out)


# ---- histograms ------------------------------------------------------------

def load_hists(path):
    """bench --hist-out CSV -> {phase: Counter{(lo, hi): count}}"""
    h = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            p = int(row["phase"])
            h.setdefault(p, Counter())[(float(row["lo_ns"]), float(row["hi_ns"]))] += int(row["count"])
    return h


def merge(hists):
    m = Counter()
    for h in hists:
        m.update(h)
    return m


def hist_quantile(h, q):
    """Nearest-rank quantile of a pooled histogram; bucket midpoint."""
    n = sum(h.values())
    if n == 0:
        return float("nan")
    rank = max(1, math.ceil(q * n))
    cum = 0
    for (lo, hi) in sorted(h):
        cum += h[(lo, hi)]
        if cum >= rank:
            return (lo + hi) / 2
    return max(hi for _, hi in h)


def pooled_quantile(run_hists, q):
    return hist_quantile(merge(run_hists), q)
