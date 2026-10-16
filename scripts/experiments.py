"""Experiment matrix, as pre-registered in RESEARCH_PHASE.md section 5.7
(Phase 3 additions: section 5.8).

Each experiment is a function returning a list of run specs:
    {"id": unique run id, "tool": "bench" | "wakebench", "args": [...], "meta": {...}}
The runner (run_experiments.py) shuffles, executes and records them.
Changing anything here after tag prereg-v1 is a deviation and must be logged.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGETS_FILE = ROOT / "config" / "budgets.json"
POLICY_FILE = ROOT / "config" / "policy.json"

THINK_NS = 1000
WARMUP_MS = 200
WINDOW_MS = 10
TRANSITION_MS = 100
PHASE_MS = 1500


def static_family():
    """park, stp:b1..b4, spin; budgets come from config/budgets.json (E1 + rule)."""
    if not BUDGETS_FILE.exists():
        raise SystemExit("config/budgets.json missing: run E1 and scripts/choose_budgets.py first")
    budgets = json.loads(BUDGETS_FILE.read_text())["budgets_ns"]
    return ["park", *[f"stp:{b}" for b in budgets], "spin"]


def all_locks():
    return static_family() + ["pthread", "pthread-adaptive"]


# ---- E1: wake-up latency ------------------------------------------------

E1_SLEEPER = 2
E1_PLACEMENTS = {"smt-sibling": 3, "other-core": 4, "same-cpu": 2}
E1_IDLE_US = [20, 100, 1000, 10000]
E1_RUNS = 3


def e1_samples(idle_us):
    return 7000 if idle_us >= 10000 else 33400


def e1():
    runs = []
    conds = [(p, w, idle, False) for p, w in E1_PLACEMENTS.items() for idle in E1_IDLE_US]
    conds += [("smt-sibling", 3, 1000, True), ("other-core", 4, 1000, True)]
    for place, waker, idle, load in conds:
        for rep in range(E1_RUNS):
            cid = f"{place}_idle{idle}us{'_load' if load else ''}"
            args = ["--sleeper", E1_SLEEPER, "--waker", waker, "--idle-us", idle,
                    "--samples", e1_samples(idle), "--label", cid]
            if load:
                args.append("--load")
            runs.append({"id": f"{cid}_r{rep}", "tool": "wakebench", "args": args,
                         "meta": {"condition": cid, "placement": place, "idle_us": idle,
                                  "load": load, "rep": rep,
                                  "confirmatory": not load}})
    return runs


# ---- E2: steady sweep ---------------------------------------------------

E2_HOLDS = [100, 1000, 10000, 50000]
E2_THREADS = [4, 8, 16, 32]
E2_RUNS = 5
E2_MS = 2000


def steady_run(exp, lock, hold, threads, rep, ms, pin="cores"):
    rid = f"{exp}_{lock.replace(':', '-')}_h{hold}_t{threads}_{pin}_r{rep}"
    return {"id": rid, "tool": "bench",
            "args": ["--lock", lock, "--threads", threads, "--hold-ns", hold,
                     "--think-ns", THINK_NS, "--duration-ms", ms, "--warmup-ms", WARMUP_MS,
                     "--window-ms", WINDOW_MS, "--pin", pin, "--seed", rep + 1],
            "meta": {"lock": lock, "hold_ns": hold, "threads": threads, "pin": pin, "rep": rep}}


def e2():
    return [steady_run("e2", l, h, t, r, E2_MS)
            for l in all_locks() for h in E2_HOLDS for t in E2_THREADS for r in range(E2_RUNS)]


# ---- E3: unpinned subset ------------------------------------------------

def e3():
    return [steady_run("e3", l, h, t, r, E2_MS, pin="none")
            for l in all_locks() for h in (1000, 10000) for t in (8, 32) for r in range(3)]


# ---- E4: phase-changing (S1 hold shift, S2 thread shift) ----------------

def schedule(spans, threads):
    """spans: list of (hold_ns, active). Each span becomes a 100 ms transition
    phase (except the first) plus the remainder of PHASE_MS. Returns --phase
    arguments and the logical-phase map (harness phase -> logical index or
    None for transitions)."""
    args, logical = [], []
    for i, (hold, active) in enumerate(spans):
        if i == 0:
            args += ["--phase", f"{hold}:{THINK_NS}:{active}:{PHASE_MS}"]
            logical.append(0)
        else:
            args += ["--phase", f"{hold}:{THINK_NS}:{active}:{TRANSITION_MS}"]
            logical.append(None)
            args += ["--phase", f"{hold}:{THINK_NS}:{active}:{PHASE_MS - TRANSITION_MS}"]
            logical.append(i)
    return args, logical


def s1(threads):
    return schedule([(100, threads), (20000, threads), (100, threads)], threads)


def s2(threads):
    return schedule([(1000, threads // 4), (1000, threads), (1000, threads // 4)], threads)


E4_THREADS = [8, 16]
E4_RUNS = 10


def phase_run(exp, sched_name, lock, threads, rep):
    args, logical = (s1 if sched_name == "S1" else s2)(threads)
    rid = f"{exp}_{sched_name}_{lock.replace(':', '-')}_t{threads}_r{rep}"
    return {"id": rid, "tool": "bench",
            "args": ["--lock", lock, "--threads", threads, "--warmup-ms", WARMUP_MS,
                     "--window-ms", WINDOW_MS, "--pin", "cores", "--seed", rep + 1, *args],
            "meta": {"lock": lock, "schedule": sched_name, "threads": threads, "rep": rep,
                     "logical_phases": logical}}


def e4():
    return [phase_run("e4", s, l, t, r)
            for s in ("S1", "S2") for l in all_locks() for t in E4_THREADS for r in range(E4_RUNS)]


# ---- E5: randomized ------------------------------------------------------

def random_run(exp, lock, threads, rep):
    rid = f"{exp}_R1_{lock.replace(':', '-')}_t{threads}_r{rep}"
    return {"id": rid, "tool": "bench",
            "args": ["--lock", lock, "--threads", threads, "--hold-ns", 200,
                     "--hold-long-ns", 20000, "--hold-long-p", 0.1,
                     "--think-ns", 2000, "--think-exp", "--duration-ms", 3000,
                     "--warmup-ms", WARMUP_MS, "--window-ms", WINDOW_MS, "--pin", "cores",
                     "--seed", rep + 1],
            "meta": {"lock": lock, "schedule": "R1", "threads": threads, "rep": rep}}


def e5():
    return [random_run("e5", l, t, r) for l in all_locks() for t in (8, 16) for r in range(10)]


# ---- Phase 3: adaptive locks (RESEARCH_PHASE.md 5.8) ------------------------

def policy_common():
    """Parameters shared by every adaptive lock, derived from E1 and the static
    budgets: prior wake latency = E1 reference median m; arms = {0, b1..b4,
    32 m rounded to 50 ns}."""
    b = json.loads(BUDGETS_FILE.read_text())
    m = b["reference_median_ns"]
    arms = [0, *b["budgets_ns"], int(round(32 * m / 50.0)) * 50]
    return {"w0_ns": m, "arms_ns": arms, "window": 1024, "alpha": 0.0625, "wcap_ns": 1e6}


def policy_spec(kind, beta, base=None, ta=None):
    c = policy_common()
    parts = []
    if kind == "ta":
        parts.append(f"base={base}")
    parts += [f"beta={beta:g}", f"w0={c['w0_ns']:g}", "arms=" + "/".join(f"{a:g}" for a in c["arms_ns"]),
              f"window={c['window']:g}", f"alpha={c['alpha']:g}", f"wcap={c['wcap_ns']:g}"]
    if kind == "ta":
        parts += [f"poll={ta['poll_us']:g}", f"theta={ta['theta']:g}",
                  f"hmin={ta['hold_min']}", f"hmax={ta['hold_max']}"]
    return f"{kind}:" + ",".join(parts)


# Throttle-aware detector parameters, fixed by design before any throttled
# data (not tuned): 1 ms polls, "imminent" at 90% of the quota, park-mode
# hold-off from 1 to 64 quota periods.
TA_PARAMS = {"poll_us": 1000, "theta": 0.9, "hold_min": 1, "hold_max": 64}


def tuned_locks():
    """(label, spec) of the frozen adaptive locks from config/policy.json."""
    if not POLICY_FILE.exists():
        raise SystemExit("config/policy.json missing: run t3 and scripts/choose_policy.py first")
    pol = json.loads(POLICY_FILE.read_text())
    ta = pol["ta"]
    return {"ada": policy_spec("ada", pol["ada"]["beta"]),
            "hedge": policy_spec("hedge", pol["hedge"]["beta"]),
            "exp3": policy_spec("exp3", pol["exp3"]["beta"]),
            "ta": policy_spec("ta", ta["beta"], base=ta["base"], ta=ta)}


def lock_entries(names):
    """[(label, spec)] for static/baseline names and tuned adaptive labels."""
    tuned = None
    out = []
    for n in names:
        if n in ("ada", "hedge", "exp3", "ta"):
            tuned = tuned or tuned_locks()
            out.append((n, tuned[n]))
        else:
            out.append((n, n))
    return out


def with_spec(run, label, spec):
    """Replace --lock in a run built for `label` by the full spec."""
    args = run["args"]
    args[args.index("--lock") + 1] = spec
    run["meta"]["lock"] = label
    run["meta"]["spec"] = spec
    return run


# ---- T3: tuning session (steady, T = 4 only) ------------------------------

T3_BETAS = [1, 2, 4, 8, 16]
T3_RUNS = 5


def t3_candidates():
    out = []
    for kind in ("ada", "hedge"):
        for b in T3_BETAS:
            out.append((f"{kind}-b{b}", policy_spec(kind, b)))
    return out


def t3():
    locks = [(l, l) for l in static_family()] + t3_candidates()
    runs = []
    for label, spec in locks:
        for h in E2_HOLDS:
            for r in range(T3_RUNS):
                runs.append(with_spec(steady_run("t3", label, h, 4, r, E2_MS), label, spec))
    return runs


# ---- E6: H3 session (S1, S2, R1 at T in {8, 16}) ---------------------------

E6_RUNS = 10


def e6_locks():
    names = static_family() + ["pthread", "pthread-adaptive", "ada", "hedge", "exp3", "ta"]
    return lock_entries(names)


def e6():
    runs = []
    for label, spec in e6_locks():
        for t in E4_THREADS:
            for r in range(E6_RUNS):
                for sched in ("S1", "S2"):
                    runs.append(with_spec(phase_run("e6", sched, label, t, r), label, spec))
                runs.append(with_spec(random_run("e6", label, t, r), label, spec))
    return runs


# ---- E7: throttled (H4) ------------------------------------------------------

E7_HOLDS = [1000, 10000]
E7_QUOTAS = [200, 400]          # CPUQuota percent, period 100 ms
E7_THREADS = 16
E7_RUNS = 10
E7_REF_RUNS = 5                 # exploratory unthrottled reference (no quota)


def e7_locks():
    return lock_entries(static_family() + ["pthread", "pthread-adaptive", "ada", "hedge", "ta"])


def scope_wrap(quota):
    w = ["systemd-run", "--user", "--scope", "--quiet", "--collect"]
    if quota is not None:
        w += ["-p", f"CPUQuota={quota}%", "-p", "CPUQuotaPeriodSec=100ms"]
    return w + ["--"]


def e7():
    runs = []
    for label, spec in e7_locks():
        for h in E7_HOLDS:
            for quota, nruns in [(q, E7_RUNS) for q in E7_QUOTAS] + [(None, E7_REF_RUNS)]:
                for r in range(nruns):
                    run = with_spec(steady_run("e7", label, h, E7_THREADS, r, E2_MS), label, spec)
                    qtag = f"q{quota}" if quota else "qnone"
                    run["id"] = run["id"].replace("e7_", f"e7_{qtag}_", 1)
                    run["wrap"] = scope_wrap(quota)
                    run["meta"].update({"quota_pct": quota, "period_ms": 100,
                                        "confirmatory": quota is not None})
                    runs.append(run)
    return runs


# ---- E8: adaptive locks on the steady grid (exploratory) ---------------------

E8_RUNS = 3


def e8():
    runs = []
    for label, spec in lock_entries(["ada", "hedge", "exp3", "ta", "park", "spin"]):
        for h in E2_HOLDS:
            for t in E2_THREADS:
                for r in range(E8_RUNS):
                    runs.append(with_spec(steady_run("e8", label, h, t, r, E2_MS), label, spec))
    return runs


# ---- E9: real application (SQLite via the LD_PRELOAD shim; exploratory) -----

E9_THREADS = [4, 8, 16, 32]
E9_RUNS = 5
SHIM = ROOT / "build" / "libflshim.so"


def e9():
    runs = []
    locks = [("native", None)] + lock_entries(static_family() + ["ada", "hedge", "exp3", "ta"])
    for label, spec in locks:
        for t in E9_THREADS:
            for r in range(E9_RUNS):
                rid = f"e9_{label.replace(':', '-')}_t{t}_r{r}"
                run = {"id": rid, "tool": "sqlbench",
                       "args": ["--threads", t, "--rows", 10000, "--write-pct", 10, "--duration-ms", 2000,
                                "--warmup-ms", WARMUP_MS, "--window-ms", WINDOW_MS, "--pin", "cores",
                                "--seed", r + 1],
                       "meta": {"lock": label, "spec": spec or "native", "threads": t, "rep": r,
                                "app": "sqlite"}}
                if spec:
                    run["wrap"] = ["env", f"LD_PRELOAD={SHIM}", f"FL_SHIM_LOCK={spec}"]
                runs.append(run)
    return runs


EXPERIMENTS = {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e5": e5,
               "t3": t3, "e6": e6, "e7": e7, "e8": e8, "e9": e9}
