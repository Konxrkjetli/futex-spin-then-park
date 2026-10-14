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
| 2. Pre-registration + static experiments (RQ1, RQ2) | 01:00 – 03:30 | **In progress**: `prereg-v1` tagged 22:28:12 (git tagger date); experiments running |
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

./build/bench --list-locks     # park, spin, stp:<spin_ns>, pthread, pthread-adaptive, none
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
| `temp_c_before`, `temp_c_after` | CPU temperature around the run |

Optional CSVs: `--hist-out` (phase, lo_ns, hi_ns, count) and `--windows-out`
(window, t_ms, phase, ops).

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

## 11. Phase 2: pre-registration and static experiments

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
| E2 | Steady sweep: 8 locks × hold {100 ns, 1 µs, 10 µs, 50 µs} × T {4, 8, 16, 32} | 640 | running (started 22:50) |
| E3 | Unpinned subset | 96 | after E2 |
| E4 | Phase-changing S1 (hold shift) and S2 (thread shift), T {8, 16} | 320 | after E3 |
| E5 | Randomized R1 (bimodal hold, exponential think), T {8, 16} | 160 | after E4 |

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
