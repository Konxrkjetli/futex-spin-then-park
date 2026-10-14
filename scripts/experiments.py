"""Experiment matrix, as pre-registered in RESEARCH_PHASE.md section 5.7.

Each experiment is a function returning a list of run specs:
    {"id": unique run id, "tool": "bench" | "wakebench", "args": [...], "meta": {...}}
The runner (run_experiments.py) shuffles, executes and records them.
Changing anything here after tag prereg-v1 is a deviation and must be logged.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGETS_FILE = ROOT / "config" / "budgets.json"

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


EXPERIMENTS = {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e5": e5}
