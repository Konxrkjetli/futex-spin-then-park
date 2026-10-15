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


# ---- fast pooled tail quantiles for bootstrap over runs ----------------------

class TailSet:
    """Run histograms of one comparison reduced to a shared bucket grid above
    a floor, so a resample's pooled tail quantile needs only a vector sum.

    Exact for every quantile >= q_floor: a pooled nearest-rank quantile is
    never below the smallest per-run quantile at the same level (fewer than
    q*n_i samples of run i lie below it, so fewer than q*n in total), so
    buckets under the lowest per-run q_floor bucket can be merged into one
    'below' count without changing any answer."""

    def __init__(self, run_hists, q_floor=0.99):
        keys = sorted(set().union(*[h.keys() for h in run_hists]))
        pos = {k: i for i, k in enumerate(keys)}
        floor = min(pos[self._qkey(h, q_floor)] for h in run_hists if sum(h.values()))
        self.keys = keys[floor:]
        self.q_floor = q_floor
        self.runs = []
        for h in run_hists:
            vec = [0] * len(self.keys)
            below = 0
            for k, c in h.items():
                i = pos[k] - floor
                if i < 0:
                    below += c
                else:
                    vec[i] += c
            self.runs.append((sum(h.values()), below, vec))

    @staticmethod
    def _qkey(h, q):
        n = sum(h.values())
        rank = max(1, math.ceil(q * n))
        cum = 0
        for k in sorted(h):
            cum += h[k]
            if cum >= rank:
                return k
        return max(h)

    def quantile(self, idx, q):
        """Pooled quantile (bucket midpoint) over the runs with indices idx
        (repeats allowed)."""
        assert q >= self.q_floor
        rs = [self.runs[i] for i in idx]
        n = sum(r[0] for r in rs)
        rank = max(1, math.ceil(q * n))
        cum = sum(r[1] for r in rs)
        assert cum < rank, "floor too high"
        for k, c in zip(self.keys, map(sum, zip(*(r[2] for r in rs)))):
            cum += c
            if cum >= rank:
                return (k[0] + k[1]) / 2
        return (self.keys[-1][0] + self.keys[-1][1]) / 2


def weighted_quantile(h, q):
    """Quantile of the waiting-time-weighted distribution: each sample counts
    in proportion to its own latency, i.e. 'the latency a unit of waiting time
    was spent in'. Long waits that barging hides from the per-acquisition
    quantiles dominate this view."""
    items = sorted(h.items())
    tot = sum((lo + hi) / 2 * c for (lo, hi), c in items)
    if tot <= 0:
        return float("nan")
    cum = 0
    for (lo, hi), c in items:
        cum += (lo + hi) / 2 * c
        if cum >= q * tot:
            return (lo + hi) / 2
    return items[-1][0][1]
