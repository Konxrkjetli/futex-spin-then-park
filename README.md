# futex-lab: When Should a Thread Wait?

An experimental study of Linux futex-based locks under changing contention:
when a waiting thread should spin, when it should park in the kernel, and
whether a lock can learn the right choice online, including under cgroup CPU
throttling.

This README is the **living record** of the project: what exists, how it works,
why it was built this way, what has been checked, and what is still open. It
is updated at the end of every phase.

> **Results status: PENDING.** No experiment data has been collected. The
> numbers below come from harness validation (pilot runs) and are not results.

---

## 1. Status

| Phase | Window (IST, 14–15 Oct 2026) | Status |
|---|---|---|
| 1. Foundation: locks, harness, wake-up benchmark, validation | 22:00 – 01:00 | **Done** (reviewed, approved 22:25) |
| 2. Pre-registration + static experiments (RQ1, RQ2) | 01:00 – 03:30 | **Done** 23:59, awaiting review. H1 supported, H2 partially supported |
| 3. Adaptive locks + throttling (RQ3, H4) | 03:30 – 06:30 | Not started |
| 4. Analysis + write-up | 06:30 – 09:30 | Not started |

Detailed checklist and event log: [`PROGRESS.md`](PROGRESS.md). Plan: [`TIMELINE.md`](TIMELINE.md).

---

## 2. Document map

| File | What it is |
|---|---|
| `README.md` | This file: the record of what was built and why |
| `TIMELINE.md` | The one-night, four-phase plan and its scope cuts |
| `PROGRESS.md` | Live checklist, deviations from plan, timestamped log |
| `BUILD_PHASE.md` | Original build plan (architecture, locks, harness, tests) |
| `RESEARCH_PHASE.md` | Research questions, hypotheses (proposed), methods, stats plan |
| `docs/validation.md` | Latest harness validation report (generated, do not edit) |
| `results/` | Raw data, append-only: `manifests/`, `validation/`, and experiment data from Phase 2 on |
| `config/budgets.json` | Static spin budgets chosen from E1 (Phase 2) |
| `config/policy.json` | Adaptive-policy parameters chosen by the tuning session T3 (Phase 3, tag `prereg-v1-p3`) |
| `docs/results/*.md` | Generated result tables, one per experiment (E1–E8, T3) |

---

## 3. Quick start

```bash
make                    # build/bench, build/wakebench, build/calib, build/test_locks
make test               # lock correctness test (all locks, T = 2, 8, 32)
make test-tsan          # same test under ThreadSanitizer
make validate           # full harness validation -> docs/validation.md (~2 min)
make manifest           # snapshot machine state -> results/manifests/
```

Example runs:

```bash
# Steady workload: 8 threads, 1 us critical section, 1 us think time, 2 s
./build/bench --lock stp:1000 --threads 8 --hold-ns 1000 --think-ns 1000

# Phase-changing workload: short holds, then long holds, then fewer threads
./build/bench --lock park --threads 4 \
    --phase 100:500:4:1000 --phase 20000:500:4:1000 --phase 100:500:2:1000 \
    --windows-out windows.csv --hist-out hist.csv

# Wake-up latency: sleeper on CPU 2, waker on CPU 4, 1 ms idle before each wake
./build/wakebench --sleeper 2 --waker 4 --idle-us 1000 --samples 20000 --out wake.csv

./build/bench --list-locks     # park, spin, stp:<spin_ns>, pthread, pthread-adaptive, none,
                               # ada, hedge, exp3, ta (adaptive, Phase 3)

# Adaptive locks take optional key=value parameters (defaults in src/policy.c)
./build/bench --lock hedge:beta=4 --threads 4 --hold-ns 1000 --think-ns 1000

# Throttled run: own transient scope with a CPU quota (no sudo; cpu controller is delegated)
systemd-run --user --scope --quiet -p CPUQuota=200% -p CPUQuotaPeriodSec=100ms -- \
    ./build/bench --lock ta --threads 16 --hold-ns 1000 --think-ns 1000

./build/calib policy           # cost of one policy decision / update
```

Requirements: gcc, make, Python 3 (standard library only for Phase 1). Phase 4
analysis needs `python-pandas python-scipy python-matplotlib`.

---

## 4. Repository layout

```
src/
  common.h          cache-line constants, cpu_relax (pause), spin_work (calibrated busy loop)
  tsc.h, tsc.c      TSC timestamps (fenced and unfenced), calibration against CLOCK_MONOTONIC_RAW
  futex.h           futex_wait / futex_wake wrappers (private futexes)
  lock.h            common lock interface + per-thread slow-path counters
  lock_registry.c   lock lookup by spec string, aligned allocation, no-op "none" lock
  lock_futex.c      park-only and static spin-then-park locks (three-state futex lock)
  lock_spin.c       spin-only lock (TTAS + bounded exponential backoff)
  lock_pthread.c    glibc default and adaptive mutex wrappers
  policy.h, policy.c  spin-budget policies: Policy A (ada), Policy B (hedge), EXP3 (Phase 3)
  lock_adaptive.c   adaptive spin-then-park locks + throttle-aware helper (Phase 3)
  cgroup.h, cgroup.c  read cpu.max / cpu.stat of the process's own cgroup (Phase 3)
  topo.h, topo.c    CPU topology, cores-first pinning order, SMT sibling lookup
  hist.h, hist.c    log-linear latency histogram (<= 0.8% bucket width)
  bench.c           lock benchmark harness
  wakebench.c       futex wake-up latency microbenchmark
  calib.c           timer cost, TSC cross-CPU check, work-loop accuracy
tests/
  test_locks.c      correctness test (exact counter, overlap detector, hang watchdog)
scripts/
  manifest.py       machine manifest collector
  validate.py       harness validation suite -> docs/validation.md
  experiments.py    pre-registered experiment matrix (E1-E8, T3)
  run_experiments.py  runner: seeded random order, resumable, clean-code check
  choose_budgets.py, choose_policy.py  pre-declared selection rules (E1 -> budgets, T3 -> policy)
  stats.py, analyze.py  statistics and per-experiment analysis
results/            raw data (append-only)
docs/               generated reports, later the paper draft
```

---

## 5. The locks

Every lock implements the same interface (`src/lock.h`): `init`, `lock`,
`unlock`, `destroy`, called through function pointers so the harness is
lock-agnostic and every lock pays the same indirect-call cost. Each lock object
is aligned and padded to 128 bytes (two cache lines) so nothing else shares
its line, including through the adjacent-line prefetcher.

| Spec | Lock | How waiting works |
|---|---|---|
| `park` | Three-state futex lock, spin budget 0 | Contended waiter parks in the kernel immediately |
| `stp:<ns>` | Same lock with a spin phase | Contended waiter spins up to `<ns>` nanoseconds (timed on the TSC, not iterations), then parks |
| `spin` | Test-and-test-and-set | Spins forever with exponential backoff capped at 16 `pause`s (~230 ns); never enters the kernel |
| `pthread` | glibc default mutex | External baseline |
| `pthread-adaptive` | glibc `PTHREAD_MUTEX_ADAPTIVE_NP` | External baseline; glibc spins a bounded count, then blocks |
| `none` | No-op | Harness overhead baseline, single thread only |
| `ada[:k=v,..]` | Policy A, estimate-and-set (Phase 3) | Spins β × (measured wake latency), then parks |
| `hedge[:k=v,..]` | Policy B, Hedge over 6 budgets (Phase 3) | Draws a budget per slow path; learns from the counterfactual cost of every budget |
| `exp3[:k=v,..]` | EXP3 over the same budgets (Phase 3, exploratory) | As hedge, but learns only from the budget it used |
| `ta[:k=v,..]` | Throttle-aware (Phase 3) | A base policy (ada or hedge); budget forced to 0 while cgroup throttling is recent or imminent |

**Three-state futex lock** (`src/lock_futex.c`), after Drepper's "Futexes Are
Tricky" (mutex3; to be checked against the paper itself, per `RESEARCH_PHASE.md` §4):

- Word = 0 unlocked, 1 locked, 2 locked with waiters possibly parked.
- Lock fast path: CAS 0→1 (one atomic, no kernel).
- Slow path: optional spin (`stp`), then `xchg(word, 2)`; while the old value
  was not 0, `futex_wait(word, 2)` and retry. The kernel sleeps only if the
  word is still 2, so a wake-up cannot be lost.
- Unlock: `fetch_sub(1)`; if the old value was 2, store 0 and `futex_wake(1)`.
- A spinner may take the lock 0→1 while sleepers exist. That is safe because
  the woken sleeper sets the word back to 2 when it runs.

**Per-thread slow-path counters** (`lk_stats`): our locks count slow-path
entries, spin acquisitions, parks, wakes and spin time per thread with no
shared writes. The pthread baselines report zeros here.

---

## 6. How measurement works

**Clock.** All timing uses the TSC (3.194 GHz on this machine). It is invariant
(`constant_tsc`, `nonstop_tsc`), it is the kernel's clocksource, and
`calib tsc-sync` shows no measurable skew between CPUs (±10 ns, which is the
ping-pong resolution). Latency stamps use `lfence; rdtsc; lfence`. One fenced
stamp pair costs about 20 ns (minimum 10 ns), and that cost is included in
every acquire-latency sample.

**Work loop.** Hold and think times are a fixed number of iterations of
`spin_work` (one loop-carried increment per iteration, made opaque to the
compiler by an empty `asm`). It is calibrated to ns at the start of each run, or
passed in with `--iters-per-ns` so a batch of runs shares one calibration. The
loop represents a fixed amount of *work*, not wall time, so a holder that is
preempted or throttled still has its remaining work to do, as a real critical
section would. Consequence: if the core clock falls, the same work takes longer
in ns (see §8, drift).

**Harness loop** (`src/bench.c`), per thread:
`t0 = stamp; lock; t1 = stamp; counter++ (and --cs-lines shared lines); work(hold); unlock; work(think)`.
Acquire latency = `t1 - t0`. Nothing shared is written outside the lock: each
thread's histograms, window counters and op counts live in memory that thread
allocated itself.

**Built-in correctness check.** The critical section increments a shared
non-atomic counter. At the end of every run it must equal the total number of
acquisitions across all threads (`counter_ok`). The run exits non-zero
otherwise.

**Latency histograms.** Log-linear, HdrHistogram-style (`src/hist.h`): exact
below 256 ticks, then 128 sub-buckets per power of two (≤ 0.8% width). There is
no sample cap, they can be merged across threads and runs, and quantiles are
nearest-rank and report the bucket midpoint.

**Phases.** A run is a list of phases `hold:think:active_threads:duration_ms`.
Threads with id ≥ `active` sleep during that phase. Throughput is also counted
in fixed windows (default 10 ms) for phase-change plots. A steady workload is a
single phase. There is also a bimodal hold option (`--hold-long-ns/-p`) and an
exponential think option (`--think-exp`) for the randomized workloads.

**Pinning.** `--pin cores` (default) uses the cores-first order: one thread per
physical core (CPU 2, 4, …, 14, then 0), then the SMT siblings (3, 5, …, 15,
then 1). Core 0 goes last because CPU 0 takes most housekeeping interrupts. More
threads than CPUs wrap around (oversubscription). `--pin none` leaves placement
to the scheduler.

**Warm-up.** 200 ms by default, unrecorded. Lock counters are reset when a
thread crosses the measurement start.

**Drift covariates.** Each run records CPU temperature (k10temp `Tctl`) before
and after, and re-measures the work-loop rate right after the run
(`iters_per_ns_after`).

### bench JSON output (one object per run on stdout)

| Field | Meaning |
|---|---|
| `lock`, `threads`, `pin`, `cpus` | Configuration and the CPU each thread was pinned to (-1 = unpinned) |
| `timing` | Whether per-acquisition stamps were taken (`--no-timing` turns them off) |
| `ops_measured`, `throughput_ops_s` | Acquisitions inside the measured window and per second |
| `counter_ok` | Shared counter equals total acquisitions (mutual-exclusion check) |
| `cpu_user_s`, `cpu_sys_s`, `cpu_util` | Process CPU time over the window; `cpu_util` is in cores |
| `vcsw`, `ivcsw` | Voluntary (blocking) and involuntary (preemption) context switches |
| `lock_stats` | Summed slow-path counters: `slow`, `spin_acq`, `parks`, `wakes`, `spin_ms` |
| `phases[]` | Per phase: `ops`, `throughput_ops_s`, `jain` (fairness over active threads), `lat_ns` {mean, min, p50, p90, p99, p999, max}, `per_thread_ops` |
| `tsc_hz`, `iters_per_ns`, `iters_per_ns_after` | Clock calibration and post-run work rate (drift) |
| `lock_stats` (Phase 3 fields) | `budget_mean_ns`, `forced` (throttle-forced parks), `wake_n`/`wake_mean_ns` (wake latency measured inside the lock), `arm_n`, `cost_real_ms`, `cost_arm_ms` (policy cost paid vs each fixed budget) |
| `cgroup` | `cpu_max` and deltas of `usage_usec`, `nr_periods`, `nr_throttled`, `throttled_usec` (summed over CPUs) over the measured window |
| `lock_report` | Adaptive locks: policy configuration; `ta`: detector counters (triggers, throttle events, back-offs, park time) over the process lifetime |
| `phases[].per_thread_p99_ns`, `per_thread_p999_ns`, `per_thread_max_ns` | Per-thread tail latency (−1 for a thread with no acquisition in that phase) |
| `temp_c_before`, `temp_c_after` | CPU temperature around the run |

Optional CSVs: `--hist-out` (phase, lo_ns, hi_ns, count) and `--windows-out`
(window, t_ms, phase, ops, slow, parks, forced, budget_ns_sum; the last four
are slow-path counters, nonzero budgets only for adaptive locks).

### Wake-up benchmark (`src/wakebench.c`)

The sleeper announces it is about to block, then blocks in `FUTEX_WAIT`. After
`--idle-us`, the waker stamps the TSC, changes the word and calls `FUTEX_WAKE`.
The sleeper stamps on return. **Wake latency = sleeper stamp − waker stamp**.
That includes the waker's syscall, the kernel wake path, any IPI, the sleeper
CPU leaving its idle state, scheduling, and the return to user space.

Each sample also records the waker's own `futex_wake` time (releaser-side cost),
how long the sleeper actually stayed blocked, and whether the wake found a
sleeper. A wake that woke nobody counts as missed and is excluded. Idle-state
entry counts for the sleeper's CPU (from `cpuidle` sysfs) are reported, so the
C-state depth each condition reached is visible, not assumed. The idle delay
controls sleep depth: on this CPU 20 µs mostly gives C1, 100 µs C2, and 1 ms C3.

Placements: `smt-sibling` (e.g. 2 and 3), `other-core` (e.g. 2 and 4),
`same-cpu`. `--load` pins a CPU hog to the sleeper's CPU.

---

## 7. Validation (Phase 1 exit gate)

Full report: [`docs/validation.md`](docs/validation.md) (regenerated by
`make validate`). Raw outputs: `results/validation/`.

Latest run: **15/15 checks pass** (2026-10-14 22:12 IST, boost on, AC power).

| Check | Measured |
|---|---|
| Correctness: 6 locks × T = 2, 8, 32, counter exact, zero overlaps | 18/18 pass; slow-path counters show both spin and park paths were exercised |
| ThreadSanitizer | 18/18 pass, 0 warnings |
| Timer overhead | fenced TSC pair 20 ns (min 10); `clock_gettime` 19 ns; `pause` 14 ns; `futex_wake` with no waiter ~295 ns |
| TSC across CPUs | skew ≤ 10 ns (the resolution), one-way cache transfer 20 ns (SMT sibling) to 30–45 ns (other core) |
| Work loop | 1 µs → 1012 ns, 10 µs → 10169 ns, 100 µs → 99526 ns (includes the ~20 ns stamp cost) |
| Single thread, no lock | 0.74 of ideal with per-op stamps, 0.87 without |
| Throughput ∝ hold (spin, T=4, think 0) | throughput × hold = 0.89 at 1 µs … 0.96 at 8 µs (the gap is handoff cost) |
| Repeatability (T=8, 5 runs) | throughput CV: park 2.7%, stp:1000 1.7% (threshold 5%); **p99 CV 16–43%** |
| Context switches | voluntary per op: spin 0.00000, park 0.98 |
| Wake benchmark | 0% missed wakes |
| Counter check in every bench run | 20/20 |

**Honest notes on validation:**

1. **Repeatability is borderline on this laptop.** The throughput-CV check
   passed, failed (stp:1000 CV 7.2%), then passed across three validation runs.
   The failing run showed throughput falling steadily across consecutive runs.
   The drift covariates added afterwards show why: after *every* run the work
   loop ran 4–7% slower than at calibration, with `Tctl` climbing 65 → 70 °C.
   Under sustained load, boost clocks fall, so nominal hold times run about
   5% long.
2. **Two validation criteria were revised after the first run**, both recorded
   in `scripts/validate.py` and `docs/validation.md`:
   - The work-loop tolerance went from a flat 5% to 5% + 10 ns, because the
     subtracted stamp cost is itself uncertain by about 10 ns.
   - The context-switch check now counts voluntary switches only. Involuntary
     ones come from other processes and are still reported. That first run also
     exposed a harness bug (the main thread slept in 1 ms chunks, adding about
     2,000 voluntary switches per run), which is fixed.

   These are harness-validation criteria, not hypothesis thresholds.
3. **Tail latency (p99) varies a lot run to run** (CV 16–43%). Tail
   comparisons in Phase 2+ need pooled histograms across runs and bootstrap
   CIs, as the stats plan already says. Single runs will not do.
4. False sharing is ruled out by construction (`_Static_assert` on layouts),
   not by measurement, because `perf c2c` is not installed.

---

## 8. Environment

| Item | Value |
|---|---|
| CPU | AMD Ryzen 7 6800H: 8 cores / 16 threads, 1 socket, 1 NUMA node, one 16 MiB L3 |
| SMT siblings | adjacent CPUs (0-1, 2-3, …, 14-15) |
| Kernel | 7.2.5-3-omarchy (Omarchy / Arch) |
| glibc / gcc | 2.44 / 16.2.1; flags `-std=gnu11 -O2 -g -pthread -D_GNU_SOURCE` |
| cpufreq | amd-pstate-epp, governor `performance`, EPP `performance`, **boost on** |
| Idle states | POLL, C1 (1 µs), C2 (18 µs), C3 (350 µs) |
| Clocksource | tsc, 3.194 GHz |
| cgroup | v2; `cpu` controller delegated to the user session (throttled runs need no sudo) |
| Not installed | perf, strace, cpupower, pandas/scipy/matplotlib |

Full snapshot: `results/manifests/` (`make manifest`).

---

## 9. Design decisions

| # | Decision | Why |
|---|---|---|
| B1 | All locks behind one function-pointer interface | Harness is lock-agnostic; identical call overhead for every lock |
| B2 | Lock objects aligned and padded to 128 B | No false sharing, including from the adjacent-line prefetcher |
| B3 | `park` and `stp` share one implementation (budget 0 vs > 0) | The only difference between them is the spin phase, so comparisons isolate spinning |
| B4 | Spin budgets in TSC time, not iterations | Budgets mean the same thing at any core frequency (`BUILD_PHASE.md` §5.3) |
| B5 | Spin-lock backoff cap 16 pauses (was 64) | `pause` costs 14 ns on Zen 3+, so 64 would let waiters sleep about 0.9 µs past a release |
| B6 | Hold/think = fixed work (iterations), not a TSC deadline | A preempted or throttled holder still owes its remaining work, like a real critical section |
| B7 | Histograms instead of raw latency arrays in `bench` | No sample cap, fixed memory, mergeable; 0.8% resolution is far below run-to-run noise |
| B8 | Raw samples kept in `wakebench` | RQ1 needs full CDFs; 100k samples per condition fit easily |
| B9 | Wake latency measured cross-CPU with the TSC | Validated by `calib tsc-sync`; avoids the waiter guessing from its own sleep time |
| B10 | `getrusage` for CPU time and context switches | perf is not installed; counts voluntary and involuntary switches per run |
| B11 | Cores-first pinning, core 0 last | Spreads threads over physical cores before SMT; keeps off the IRQ-heavy CPU 0 |
| B12 | Python scripts use only the standard library so far | pandas/scipy are not installed; analysis in Phase 4 will need them |
| B13 | Drift covariates recorded in every run | Validation showed 4–7% clock drop under load; the analysis can account for it |
| B14 | Adaptive locks in their own file; `lock_futex.c` untouched | The static locks run exactly the Phase 2 code, so E6/E7 static rows are comparable with E4/E5 |
| B15 | One cost model for both policies (ski rental: spin time, or budget + C if parked; C = β × measured wake latency) | Matches `BUILD_PHASE.md` §5.4; β is the single tuned knob and means "a park costs β wake latencies" |
| B16 | Wake latency measured inside the lock (releaser stamps the TSC just before `FUTEX_WAKE`) | The planned estimate-and-set input; costs one TSC read and one store on the wake path, after the word is released |
| B17 | Policy update in `unlock`, after the release | Bookkeeping never lengthens a critical section |
| B18 | Per-thread policy state, keyed by lock | No shared writes. A thread that alternates between locks resets its state (not an issue for the benchmark's one lock) |
| B19 | Hedge arms = {0, b1..b4, 32·m}; costs shifted by the round minimum and divided by C | The arms include every static budget, so "best fixed arm" lines up with the static family. The first, range-normalised version could not separate arms (D15) |
| B20 | Throttle detector: own cgroup's `cpu.stat` polled at 1 ms; trigger on a new throttle event or usage ≥ 90% of quota; park mode for 1–64 periods with doubling | "Recent or imminent" per `BUILD_PHASE.md` §5.5; doubling limits repeated probes that would burn quota |
| B21 | Throttled runs in a fresh `systemd-run --user --scope` per run | No sudo; counters start from zero per run; the scope's `cpu.max` is exactly the quota under test |

---

## 10. Known issues and open questions (for review)

1. **Boost and thermal drift (biggest measurement risk).** The fix is
   `echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost` before Phase 2.
   Clocks then sit at base (~3.2 GHz) and stop drifting. If boost stays on, the
   drift covariates go into the analysis and the limitation is stated.
2. **Background load.** Browser and desktop apps were running during validation
   (load average ~2–3.7). Close heavy apps during measurement windows.
3. **Tail-latency noise** needs pooling across runs (see §7, note 3).
4. **Barging/unfairness observed** in a pilot: with 20 µs holds, `stp:2000` let
   one thread re-acquire repeatedly while parked waiters were still waking
   (per-thread ops 16919 / 1555 / 2 / 4395). This is expected behaviour for
   this lock family and is why fairness (Jain's index) is recorded. It is a pilot
   observation, not a result.
5. **Pilot data has been seen.** Validation and smoke tests produced wake-up
   latencies (a few µs, depending on idle depth) and lock behaviour before
   the Phase 2 pre-registration. The hypothesis thresholds proposed in
   `TIMELINE.md` §5 were written *before* any pilot run. This disclosure goes
   into the paper's methodology.

---

## 11. Phase 2: pre-registration and static experiments (done)

### 11.1 Pre-registration (`prereg-v1`)

Before any experiment data existed, the hypotheses, operational definitions,
experiment matrix and verdict rules were written into `RESEARCH_PHASE.md`
(§3.2, §5.6, §5.7, §6.1), committed, and tagged:

```bash
git show prereg-v1          # the frozen version
git diff prereg-v1 -- RESEARCH_PHASE.md   # anything changed since (must be logged)
```

What is frozen, in short:

| Hypothesis | Test |
|---|---|
| H1 | median wake latency of the slowest / fastest of 12 unloaded conditions ≥ 2× |
| H2 | after a 100 ns ↔ 20 µs hold shift, the previously best static lock loses ≥ 25% throughput or has ≥ 2× p99, in each of 4 cases |
| H3 | each adaptive policy ≥ 0.85× throughput and ≤ 1.2× p99.9 of the best single static lock, on each of 6 workloads (Phase 3) |
| H4 | throttle-aware: ≥ 2× lower p99.9 than spin and ≤ 1.10× the best static lock, in each of 4 throttled cases (Phase 3) |

Verdict rule: the point estimate decides; if the 95% interval contains the
threshold, the case is *inconclusive*. One clarification (C1, how H2's OR of
two metrics combines with that rule) was added after the tag but before any E4
data, with no threshold changes.

Integrity notes: the TIMELINE §5 hypothesis wording was proposed before any
pilot data. Validation pilot data was seen before the tag (README §10.5).

### 11.2 Experiments (matrix in `scripts/experiments.py`)

| ID | What | Runs | Status |
|---|---|---|---|
| E1 | Wake-up latency: 3 placements × 4 idle depths, plus 2 loaded conditions | 42 | **done** 22:48, 0 invalid |
| E2 | Steady sweep: 8 locks × hold {100 ns, 1 µs, 10 µs, 50 µs} × T {4, 8, 16, 32} | 640 | **done** 23:17, 0 invalid |
| E3 | Unpinned subset | 96 | **done** 23:21, 0 invalid |
| E4 | Phase-changing S1 (hold shift) and S2 (thread shift), T {8, 16} | 320 | **done** 23:47, 0 invalid |
| E5 | Randomized R1 (bimodal hold, exponential think), T {8, 16} | 160 | **done** 23:56, 0 invalid |

The 8 locks are `park`, `stp:b1..b4`, `spin`, `pthread` and `pthread-adaptive`.
The budgets b1..b4 = {0.5, 1, 2, 8} × the median wake latency of E1
`other-core / idle 100 µs`, computed by `scripts/choose_budgets.py` into
`config/budgets.json` after E1 and before E2.

**Budgets chosen (2026-10-14 22:49):** reference median 4728.9 ns (100,200
samples), so the static locks are `stp:2350`, `stp:4750`, `stp:9450` and
`stp:37850`.

### 11.3 How experiments are run and recorded

```bash
python3 scripts/run_experiments.py e1 --dry-run   # show the run list, no data
python3 scripts/run_experiments.py e1             # run (resumable: re-run to continue)
python3 scripts/choose_budgets.py                 # after E1: writes config/budgets.json
python3 scripts/analyze.py e1                     # tables -> docs/results/e1.md
```

- **Order:** runs execute in a seeded random order (seed 20261014), so drift is
  spread across all locks instead of hitting whichever runs last.
- **Calibration:** one TSC calibration and one work-loop calibration per
  session, shared by every run in it.
- **Clean code only:** the runner refuses to start if code or config has
  uncommitted changes, so the commit hash in every record is the code that ran.
- **Invalid runs:** a failed process or `counter_ok = false` is re-run (up to 2
  retries) and counted. Slow runs are never dropped.
- **Layout:** `results/<exp>/runs.jsonl` (one line per run, append-only),
  `results/<exp>/runs/<id>.json`, and per run `.hist.csv` and `.win.csv`
  (bench) or `.csv.gz` (raw wake samples). Session files hold the start and
  end manifests and the run order.

### 11.4 Analysis (`scripts/analyze.py`, `scripts/stats.py`)

Standard library only (numpy/scipy are not installed):

- **Throughput:** mean over runs.
- **Tail latency:** quantiles of histograms pooled over runs.
- **Intervals:** bootstrap over runs with 2,000 resamples (deviation D12 from
  the planned 10,000). For wake-up medians, distribution-free order-statistic
  intervals.
- **Labels:** only H1–H4 are confirmatory; every other table is labelled
  exploratory.

Outputs go to `docs/results/<exp>.md` and `results/analysis/<exp>.json`.

### 11.5 Results so far

**H1: SUPPORTED** (confirmatory; full table in `docs/results/e1.md`).

- Fastest unloaded condition: other-core, 20 µs idle, median **2.73 µs**.
- Slowest: other-core, 10 ms idle, median **30.72 µs**.
- Ratio **11.27** (conservative 95% interval 11.18–11.37), threshold 2.
- Robustness check that does not assume independent samples: the lowest
  per-run median of the slowest condition over the highest of the fastest is
  still **9.59**.

E1 observations (descriptive, not tested):

| Idle before wake | other-core median | smt-sibling median | same-cpu median | Mostly reached |
|---|---|---|---|---|
| 20 µs | 2.73 µs | 3.00 µs | 3.10 µs | C1 |
| 100 µs | 4.73 µs | 4.14 µs | 4.59 µs | C2 |
| 1 ms | 5.70 µs | 6.67 µs | 4.76 µs | C2/C3 |
| 10 ms | 30.72 µs | 14.36 µs | 11.83 µs | C2/C3 |

- **Idle depth drives the median.** The longer the sleeper's CPU idles, the
  deeper its C-state and the slower the wake. The 10 ms condition is also the
  least stable between runs: per-run medians of 26–35 µs (other-core) and
  9–15 µs (same-cpu).
- **Tails are heavy and grow with idle depth.** p99/p50 is 1.3–2.7 at 20 µs
  idle but 15–36 at 1–10 ms (smt-sibling / other-core). p99.9 is
  0.2–1.6 ms for smt-sibling and other-core (84 µs at other-core / 20 µs
  idle). Same-cpu tails are much shorter (p99.9 9–35 µs) except at 10 ms
  idle (1.3 ms).
- **The waker's own `futex_wake` cost also grows with idle depth**: 0.56 µs
  (other-core, 20 µs idle) up to 3.0–3.5 µs (10 ms idle), and 1.5–8.3 µs for
  same-cpu. The releaser side of a lock pays part of the wake cost too.
- **With a CPU hog on the sleeper's CPU** the median is lower (3.5–3.7 µs at
  1 ms idle, because the CPU never enters idle), but p99.9 is about 0.8 ms.
- **Missed wakes:** 4 of 100,200 in one condition (other-core, 20 µs idle),
  0 elsewhere.

**H2: PARTIALLY SUPPORTED** (confirmatory, 2 of 4 cases; `docs/results/e4.md`).

| Case | A\* (best before) | Throughput loss after shift | p99 ratio | Result |
|---|---|---|---|---|
| S1 T=8, 100 ns → 20 µs | stp:2350 | 3.2% [1.5, 4.5] | 1.00 | not met |
| S1 T=8, 20 µs → 100 ns | spin | 1.8% [0.6, 2.9] | 1.64 [1.62, 1.68] | not met |
| S1 T=16, 100 ns → 20 µs | spin | **43.1%** [42.4, 44.1] | 86,517 (artefact, see below) | **met** |
| S1 T=16, 20 µs → 100 ns | stp:4750 | 16.1% [15.4, 16.8] | **2.59** [2.57, 2.63] | **met** |

- **Reading:** at T = 8 (one thread per physical core), every lock that spins
  at all performs about the same in both phases, so a static budget loses
  nothing when the hold time shifts. At T = 16 (all SMT threads busy), spin is
  best for short holds but loses 43% once holds become long. The lock that is
  best during long holds is 16% slower, with 2.6× the p99, once holds become
  short again.
- **Tie-break check:** in the last case, all futex locks were tied in the long
  phase. The case is met whichever of them the tie-break picks: `park` on
  loss (37%), each `stp` lock on p99 ratio (2.3–2.7). These are point
  estimates; no intervals were computed for the alternatives.

**Methodology finding: barging makes acquisition-weighted percentiles
misleading in long-hold phases.**
- With 20 µs holds, every futex-based lock (ours and glibc's) turns unfair:
  Jain's index 0.33–0.54, with the top thread taking 20–56% of acquisitions.
- The releasing thread re-acquires through the fast path before parked
  waiters wake. Their wake-up costs 3–30 µs (E1), longer than the 1 µs think
  time.
- Most acquisitions are therefore uncontended re-acquisitions, so p99 is about
  30 ns while the parked threads starve. Spin stays fair (Jain 0.98–0.99).
- Effect on H2: the p99 criterion understates the harm in the T=8 long-hold
  case and inflates the ratio in the T=16 case. The T=16 case is met on the
  43% throughput loss alone.
- The pre-registered verdict is kept unchanged. A per-thread or
  waiting-time-weighted latency metric is a candidate *exploratory* analysis
  for Phase 4.

**E2–E5 observations** (exploratory; tables in `docs/results/e2.md`, `e3.md`, `e5.md`):

- **Short holds (100 ns), T ≤ 8:** any lock that spins reaches 3.1–4.6 M ops/s.
  `park` and `pthread` reach 2.4–2.9 M ops/s, and their p99 is about 4× worse
  at T=8 and about 20× worse at T=4.
- **Long holds (10 µs), T = 4–32:** `stp:37850` (budget > hold) is fastest,
  about 15% above the other futex locks (0.091–0.095 vs 0.078–0.084 M ops/s),
  but uses about 2.2 CPU cores instead of 1.2. Spin uses every core it has
  (4 at T=4, 15.7 at T=16) and collapses once T > 8 (0.050 M ops/s at T=16,
  0.025 at T=32).
- **Oversubscription (T = 32 on 16 CPUs):** spin is the slowest lock at every
  hold time: 30% below the best at 100 ns, and 3–4× below at ≥ 1 µs (e.g.
  0.23 vs 0.67 M ops/s for `stp:9450` at 1 µs). The best lock depends on hold
  time: `stp:2350` at 100 ns, `stp:9450` at 1 µs.
- **No single lock wins everywhere.** Over the 16 hold × T cells, the
  highest-throughput lock is spin in 3, `stp:2350`, `stp:4750` and `stp:9450`
  in 6 between them, `stp:37850` in 4, and park or pthread-adaptive in the
  50 µs cells, where every futex lock is within 2%.
- **Unpinned (E3, vs pinned):** results are mixed.
  - At 1 µs holds and T=8, `park` and `pthread` lose about 25% throughput and
    get 1.8–2.6× worse p99.
  - At T=32 they gain about 40% throughput with much lower p99, because the
    scheduler balances 32 threads better than 2 pinned per CPU.
  - `stp:9450` at 10 µs, T=32 has 128× worse p99 unpinned, from a pinned p99
    of about 0.1 µs that barging produces.
- **Randomized R1:** spin has the highest throughput at T=8 (0.40 vs 0.32–0.38
  M ops/s) but the lowest at T=16 (0.22). `stp:37850` is highest at T=16
  (0.32). The other futex locks are within about 3% of each other.
- **Run-to-run stability:** median throughput CV 1.0% (max 4.6%) across E2
  cells. Drift: the work loop ran 3.0% slower after a run on average (worst
  −13.7%), with boost on.

---

## 12. Phase 3: adaptive locks and throttling

### 12.1 What was built

All four adaptive locks are the three-state futex lock of §5. The only
difference is that a policy chooses the spin budget on every slow path
(`src/lock_adaptive.c`, `src/policy.c`). The uncontended fast path is the
same single CAS.

**Cost model (shared).** A waiter that would get the lock by spinning after
*w* ns pays, with budget *b*:

- *w* if *w* ≤ *b* (it spun until the lock came free);
- *b* + C otherwise (it spun, gave up, and paid the cost of blocking).

C = β × Ŵ, where Ŵ is the thread's running average (EWMA, α = 1/16) of the
wake-up latency **measured inside the lock**:

- On an unlock that has to wake someone, the releaser stamps the TSC just
  before `FUTEX_WAKE`.
- The woken waiter subtracts that stamp when it returns.
- The prior is the E1 reference median (4.73 µs).

This is the classic ski-rental setting. β = 1 is the textbook "spin for as
long as a block costs" rule. β is the one parameter that was tuned.

| Lock | Policy |
|---|---|
| `ada` (Policy A) | Budget = β × Ŵ, capped at 151.3 µs |
| `hedge` (Policy B) | Hedge over 6 arms {0, 2.35, 4.75, 9.45, 37.85, 151.3} µs: no spin, the four static budgets, and 32 × the E1 median. Discounted cumulative cost with a horizon of 1,024 slow paths and η = √(8 ln 6 / 1024). The arm is drawn at random. |
| `exp3` (exploratory) | Same arms, learns only from the arm it used (importance-weighted) |
| `ta` | Base policy (chosen by the tuning rule) + throttle detector |

**Why Hedge can learn from every arm at once ("censored" feedback).**

- If the waiter got the lock while spinning, *w* is known exactly, so the
  cost of every arm is known.
- If it parked, every arm no longer than its own budget would have parked
  too, so those arms cost *b* + C.
- Longer arms are estimated from the stamp of the release that finally let
  it in. This is an upper bound on the wait a spinner would have seen, so the
  estimate leans toward parking.

**Throttle-aware variant.**

- A helper thread reads the process's own cgroup `cpu.stat` every 1 ms while
  `cpu.max` sets a quota. With no quota, it re-checks `cpu.max` every 100 ms
  and otherwise does nothing.
- Trigger: `nr_throttled` went up, or the last millisecond's CPU usage
  reached 90% of the quota.
- On a trigger, waiters park immediately (budget 0) for `hold` quota
  periods.
  - If the next trigger comes within one period after park mode ends (the
    probe back into spinning failed), `hold` doubles, up to 64 periods.
  - Any later trigger resets it to 1.
- These parameters were fixed by design before any throttled data and were
  not tuned.

**Overheads** (`calib policy`, `calib timer`; single thread):

| | choose (slow path, before spinning) | update (after release) | uncontended lock+unlock |
|---|---|---|---|
| park (static) | – | – | 2.87 ns |
| ada | 0.3 ns | 14.7 ns | 3.16 ns |
| hedge | 10.5 ns | 27.9 ns | 3.16 ns |
| exp3 | 10.5 ns | 18.4 ns | 3.15 ns |
| ta | as base | as base | 3.36 ns |

Neither cost lands inside a critical section. The choice happens while the
lock is held by someone else, and the update runs after the release.

**Correctness.** 39/39 counter tests pass (13 lock specs × T = 2, 8, 32), and
ThreadSanitizer reports 0 warnings. `ta` also passes inside a 50% CPU quota,
where 60–90% of its slow paths were forced to park, so that path is
exercised.

### 12.2 Protocol (RESEARCH_PHASE.md §5.8, written before any Phase 3 data)

Commit `7df4987` (22:15:45) holds the code and the protocol and predates all
Phase 3 data. The protocol fixes:

- the tuning rule;
- the E6/E7/E8 lock lists;
- the throttled launcher;
- clarification C2: the best static lock (H3) and the minimum over S (H4)
  are recomputed in every bootstrap resample.

Disclosed in the protocol:

- One design iteration on the tuning set (Hedge normalisation, D15).
- One throttled mechanism check at T = 8, 100% quota (not an H4 case). In it,
  spin's p99.9 (67 µs) was *lower* than `ta`'s (499 µs). Nothing was changed
  after it.
- The Phase 2 results were known when the policies were designed.
