# TIMELINE.md: one-night build and research plan

**Start:** 2026-10-14 ~22:00 IST | **Target finish:** 2026-10-15 ~09:30 IST | **Machine:** Ryzen 7 6800H (8C/16T, 1 socket, 1 NUMA node, one shared L3), kernel 7.2.5-3-omarchy, glibc 2.44

This file replaces the 10-week timeline in `BUILD_PHASE.md` §9 and `RESEARCH_PHASE.md` §11 for a single all-night session. The scope and method in those documents still apply except where §1 below lists a deviation. Every deviation is also logged in `PROGRESS.md`.

> **Results status: PENDING.** This is a plan. No experiments have been run.

---

## 1. Scope changes required by a one-night schedule

| Original plan | Tonight | Reason |
|---|---|---|
| 30 runs per configuration | **5 runs** for sweeps, **10 runs** for the confirmatory configurations behind H2–H4 | The full matrix would take about 96 machine-hours |
| Full factorial (pinning × SMT × …) | Pinned runs only for the main sweep; a small unpinned subset; SMT left **on** (stated as a limitation) | Changing SMT needs root and a full re-run |
| Second machine | **Cut** | Not available |
| Energy (RAPL) | **Cut** | Optional in the original plan |
| Real application via LD_PRELOAD | **Stretch goal** (Phase 4, only if time is left) | First item on the original cut list after energy |
| Literature review | Phase 4: Claude finds and checks the bibliographic details of the candidate sources; **the team must read a paper before citing what it says** | Integrity rule from `RESEARCH_PHASE.md` §4 |
| Policy B = EXP3 | Policy B = **Hedge with censored full-information feedback**; EXP3 as a cheap comparison if time allows | A spin-then-park waiter can compute the counterfactual cost of most arms (see review point 3) |
| "Different socket" wake-up condition | **Dropped** | This machine has one socket and one L3 |
| "Cores" undefined | Thread counts **T ∈ {4, 8, 16, 32}** (8 = physical cores, 16 = logical CPUs) | Removes ambiguity |

---

## 2. Phases at a glance

| Phase | Window (IST) | Goal | Gate to leave the phase |
|---|---|---|---|
| **1. Foundation** | 22:00 – 01:00 | Repository, all non-adaptive locks, harness, wake-up microbenchmark, all validated | Correctness tests and the harness validation checklist pass |
| **2. Pre-registration + static experiments** | 01:00 – 03:30 | Commit hypotheses/thresholds, then collect RQ1 and RQ2 data | Thresholds committed **before** data; RQ1/RQ2 raw data in `results/` |
| **3. Adaptive + throttling** | 03:30 – 06:30 | Policy A, Policy B, throttle-aware variant; RQ3 and H4 data | Adaptive locks pass correctness; overhead measured; RQ3/H4 data collected |
| **4. Analysis + write-up** | 06:30 – 09:30 | Statistics, figures, hypothesis verdicts, report draft, reproducible artifact | Results table filled from data; README reproduces every figure |

Buffer: each phase window has about 20–30 min of slack built in. If a phase overruns, apply the cut order in §6.

---

## 3. Phase details

### Phase 1: Foundation (22:00 – 01:00)

**Setup (you):** install the missing tools: `sudo pacman -S perf strace cpupower python-pandas python-scipy python-matplotlib`. Optionally turn off boost for stable timing: `echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost`. If boost stays on, its state is recorded instead.

**Build (Claude):**
1. `git init`, repository layout from `BUILD_PHASE.md` §4.1, Makefile (`-O2`, plus TSan and debug targets).
2. Machine manifest script: CPU, topology, kernel, glibc, governor/EPP, boost, SMT, compiler versions and flags, git commit. Output to `results/manifest-*.json`.
3. `futex support`: `futex_wait`/`futex_wake` wrappers (private), `cpu_relax` (`pause`), TSC timing with `rdtscp` and a calibrated ns conversion.
4. Common lock interface (init / lock / unlock / destroy / name), lock word on its own 64-byte cache line.
5. Locks: park-only (three-state, Drepper-style), spin-only (bounded exponential backoff), static spin-then-park (budget in ns), pthread default, pthread adaptive (`PTHREAD_MUTEX_ADAPTIVE_NP`).
6. Correctness: shared-counter test for every lock over T ∈ {2, 8, 32}, plus a ThreadSanitizer build.
7. Benchmark harness: threads pinned or unpinned, calibrated hold/think work (protected from compiler optimisation), per-thread preallocated latency buffers, per-thread acquisition counts, timed duration, CSV output, `getrusage` for CPU time and context switches.
8. Wake-up microbenchmark: the waker writes a TSC timestamp, then calls `FUTEX_WAKE`; the sleeper measures the delta on return. Conditions: placement (SMT sibling / other core / same CPU), idle time before the wake (≈0, 100 µs, 1 ms, 10 ms), background load on the sleeper's CPU (on/off).

**Exit gate:** the counter is exact for every lock; TSan reports nothing; `BUILD_PHASE.md` §7.2 checklist complete (timer overhead measured, throughput scales with hold time, run-to-run variation recorded, no false sharing, context-switch counts sensible for spin-only versus park-only).

### Phase 2: Pre-registration + static experiments (01:00 – 03:30)

1. **Pre-registration commit (before any experiment data):** apply the hypothesis decisions in §5 to `RESEARCH_PHASE.md`, fill in the pre-declared definitions (§5.6 of that file: phase boundaries, transition window, how the best static policy is chosen), commit, and tag `prereg-v1`.
2. **RQ1 / H1:** wake-up microbenchmark across all conditions (target 100k samples; 20k for the 10 ms idle condition).
3. Choose the final static budget set from the RQ1 data using a rule written down beforehand (proposed: {0, ½×, 1×, 2×, 8×} the median wake-up latency of the other-core condition, plus spin-only).
4. **Steady sweep:** 9 locks × hold ∈ {100 ns, 1 µs, 10 µs, 50 µs} × T ∈ {4, 8, 16, 32} × 5 runs × 2 s, pinned. Small unpinned subset.
5. **Phase-changing workload (RQ2 / H2):** schedules short→long→short hold time and few→many→few threads, throughput recorded in 10 ms windows, 10 runs.
6. Randomized workload (mixture of hold times, bursty arrivals): a single small configuration.

**Exit gate:** raw CSVs and manifests in `results/`, committed; the pre-registration tag is older than every data file.

### Phase 3: Adaptive + throttling (03:30 – 06:30)

1. **Policy A (estimate-and-set):** EWMA of the measured wake-up cost (the releaser's TSC stamp, as in the microbenchmark), budget clamped to [min, max]; optional skip when the hold-time EWMA is much larger than the wake-up EWMA. Per-thread state.
2. **Policy B (learned budget):** K ≈ 6 arms; Hedge over censored counterfactual costs, with discounting or a sliding window for non-stationarity; per-thread weights. EXP3 variant if time allows.
3. Correctness tests and TSan for both; **policy overhead** measured on the uncontended path and under contention.
4. Adaptive locks on the same steady, phase-changing and randomized workloads as Phase 2 (RQ3 / H3); cumulative regret logged in time windows.
5. **Throttle-aware variant:** a helper thread polls `cpu.stat` (`nr_throttled`, `throttled_usec`) and forces budget = 0 for a hold-off window after a throttle event.
6. **Throttled runs (H4):** `systemd-run --user --scope -p CPUQuota=…` (no sudo needed; the cpu controller is delegated) with a quota below demand (proposed 200% and 400% for T=16), period recorded; record the throttling counters. 10 runs.

**Exit gate:** RQ3 and H4 data committed; overhead numbers recorded.

### Phase 4: Analysis + write-up (06:30 – 09:30)

1. Analysis scripts: medians and percentiles with 95% bootstrap CIs, Mann-Whitney U plus effect sizes for the **pre-declared** comparisons only, Jain's fairness index, regret curves.
2. Figures 1–10 from `RESEARCH_PHASE.md` §7, generated by one script from the raw data.
3. Hypothesis verdicts against the **committed** thresholds → fill `RESEARCH_PHASE.md` §3.4.
4. Literature: find and record the bibliographic details of the candidate sources; flag which ones the team still has to read.
5. Report draft (`docs/report.md`) following the paper structure in `RESEARCH_PHASE.md` §8, including limitations: single laptop, SMT on, fewer repetitions, one night.
6. README with exact reproduction commands; final data-freeze commit and tag.
7. *Stretch:* LD_PRELOAD shim + SQLite run.

**Exit gate:** every number in the report traces to a file in `results/` and a script in `scripts/`.

---

## 4. Machine-time budget (estimates)

| Experiment | Configurations × runs × duration | ≈ Time |
|---|---|---|
| Harness validation | ad hoc | 10 min |
| Wake-up microbenchmark | 3 placements × 4 idle × 2 load | 15–20 min |
| Steady sweep (static) | 9 × 4 × 4 × 5 × 2 s (+ subset) | 25–30 min |
| Phase-changing + randomized (static) | ~9 locks × 3 schedules × 10 × 6 s | 25–30 min |
| Adaptive on the same workloads | ~3 locks, same matrix | 20–25 min |
| Throttled | ~6 locks × 2 quotas × 10 × 5 s | 10–15 min |
| **Total** | | **≈ 2–2.5 h** |

Benchmarks run while Claude does lightweight work. **Nothing heavy (compiles, browser video, games) should run during measurement windows.** Claude will say when a measurement window starts and ends.

---

## 5. Decisions needed before Phase 2 (proposed; confirm or edit)

These fix review points 1, 2, 3 and 6. They will be committed as part of `prereg-v1`, before any data.

- **H1 (rewrite):** "Median futex wake-up latency in the slowest placement/idle condition is at least **2×** the median in the fastest condition." p99/p50 spread is reported descriptively, not as the test.
- **H3 (comparator fix):** compare against the **best single static budget over the whole run** (matching RQ3). Bounds unchanged: throughput within 15% and p99.9 ≤ 1.2×. Per-phase comparison is reported descriptively, with the **first 100 ms after each shift excluded**.
- **H4 (stronger baseline):** primary test: the throttle-aware variant cuts p99.9 by ≥ **2×** versus spin-only **and** is within 10% of the best static lock's p99.9 under the same quota. This shows it is more than "always park".
- **Policy B:** Hedge with censored feedback, as in §1.

---

## 6. Cut order if the night runs long

1. LD_PRELOAD / real application (already a stretch goal)
2. EXP3 comparison variant
3. Randomized workload (keep steady + phase-changing)
4. Unpinned subset
5. Reduce confirmatory runs from 10 to 5 (logged as a deviation)

Not cut under any circumstances: correctness tests, harness validation, pre-registration before data, and honest reporting of the results.
