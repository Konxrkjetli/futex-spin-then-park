# BUILD_PHASE.md

**Project:** *When Should a Thread Wait? An Experimental Study of Linux Futex-Based Synchronization Under Changing Contention*
**Working subtitle:** *Learning When to Park: Competitive Spin-Then-Wait Locking on Linux Futexes Under Non-Stationary Contention and CPU Throttling*
**Team:** 2 students | **Duration:** 10 weeks (plus a Week 0 study period) | **Platform:** Omarchy / Arch Linux | **Language:** C

> **Status of this document:** Planning documentation only. It describes what will be built and how. No code has been written, no experiments have been run, and **no results exist yet**. All hypotheses referenced here are **proposed** and are defined in `RESEARCH_PHASE.md`.

> **Note on source material:** This document is derived from the project plan developed in the conversation that produced it. No separate PDF or existing repository was available when this file was created, so scope, terminology and hypotheses were carried over from that plan rather than from a PDF.

---

## 1. Purpose and scope of the build phase

The build phase produces the software artifacts needed by the research phase:

1. A **measurement harness** that can generate controlled lock workloads and record accurate per-acquisition latency and throughput.
2. A family of **futex-based locks** implemented by the team so that comparisons are fair and under the team's control.
3. An **adaptive spin-then-park lock** (the project's proposed contribution) and a **throttle-aware variant**.
4. A **wake-up latency microbenchmark** to characterise the cost of futex wake-ups.
5. **Workload generators** for steady, phase-changing and randomized contention.
6. **Experiment automation and analysis scripts** so every run is reproducible.
7. An optional **LD_PRELOAD interposition shim** to evaluate a real application.

### In scope
- Userspace C implementations of locks built on the Linux `futex` system call.
- Comparison against glibc's default pthread mutex and the adaptive pthread mutex type.
- Benchmarks under varying thread counts, critical-section durations, and contention patterns.
- Runs inside a cgroup v2 CPU quota to study throttling.
- Correctness testing and benchmark-harness validation.

### Out of scope (unless time remains)
- Kernel modifications or patched kernels.
- Writing a custom scheduler or eBPF scheduler.
- Formal verification of the locks.
- Energy measurement (optional extension only).

---

## 2. Terminology (preserved from the project plan)

| Term | Meaning in this project |
|---|---|
| Thread | A worker inside a program that competes for the lock |
| Lock / mutex | Mechanism allowing one thread at a time into a critical section |
| Critical section | Code that runs while holding the lock; its duration is the *hold time* |
| Spinning | Repeatedly checking whether the lock is free |
| Sleeping / parking | Blocking in the kernel until woken |
| Spin-then-park | Spin for a bounded budget, then park |
| Spin budget | How long (in nanoseconds) a waiter spins before parking |
| Futex | A 32-bit userspace word plus a kernel wait queue; kernel is involved only to sleep or wake |
| Wake-up cost | Delay between a wake request and the waiter running again |
| Contention | Degree to which threads compete for the same lock |
| Non-stationary | Workload characteristics that change over time |
| Throttling | Cgroup CPU bandwidth limits that pause a whole group of threads |
| Adaptive lock | A lock that adjusts its spin budget at run time |
| Tail latency | High percentiles (p99, p99.9) of lock-acquire latency |

---

## 3. Technologies and dependencies

### 3.1 Platform
- OS: Omarchy / Arch Linux (record exact kernel version for every run).
- Cgroups: cgroup v2 (verify the layout on the team's machine).
- Languages: C for locks and harness; Python for orchestration and analysis.

### 3.2 Tooling (to be installed and verified in Week 0)
| Category | Tools |
|---|---|
| Compilers and build | gcc, clang, make or cmake |
| Profiling and tracing | perf, strace, bpftrace (optional) |
| Topology and affinity | hwloc (lstopo), numactl, taskset, cpupower |
| Correctness | ThreadSanitizer (via compiler flag) |
| Latency recording | A histogram library (for example HdrHistogram) or preallocated per-thread arrays |
| Analysis | Python with pandas, scipy, matplotlib |
| Version control | git |

### 3.3 Dependency principles
- Locks use only the C standard library, the Linux futex interface, and standard atomics.
- The harness avoids shared writable state during timed runs.
- Every dependency version is recorded in a machine manifest committed with the results.

---

## 4. Architecture

### 4.1 Repository layout (proposed)

```
futex-lab/
  README.md
  BUILD_PHASE.md
  RESEARCH_PHASE.md
  src/
    futex support          (system-call wrapper, spin-relax hint, timing helpers)
    lock interface         (common acquire/release contract used by all locks)
    park-only lock
    spin-only lock
    static spin-then-park lock
    adaptive lock          (project contribution)
    throttle-aware lock
    pthread wrappers       (default and adaptive types)
    benchmark harness
    wake-up latency microbenchmark
    LD_PRELOAD shim        (optional, Weeks 7-8)
  scripts/
    experiment runner      (executes the configuration matrix, writes CSV)
    analysis and plotting
    cgroup run helper
    machine manifest collector
  results/                 (raw data; append-only; never hand-edited)
  docs/                    (notes, decisions log, paper drafts)
```

### 4.2 Component responsibilities

| Component | Responsibility |
|---|---|
| Common lock interface | Gives every lock the same acquire/release contract so the harness is lock-agnostic |
| Benchmark harness | Spawns threads, applies pinning, drives the workload, records latency, stops cleanly |
| Workload generator | Applies hold time, think time, thread count and phase schedule |
| Recorder | Stores per-acquisition latency and per-thread counts without touching shared memory during the run |
| Runner script | Iterates the configuration matrix, repeats runs, tags rows with commit hash and machine id |
| Analysis scripts | Compute medians, percentiles, confidence intervals and produce figures |

### 4.3 Data flow
1. The runner reads a configuration (lock, workload, threads, pinning, cgroup settings).
2. The runner records the machine manifest and starts the harness.
3. The harness runs the workload and writes raw latency and counter data.
4. The runner appends one summary row per run to the results store.
5. Analysis scripts read the results store and generate tables and figures.

---

## 5. Futex locking algorithms (conceptual description)

All locks share a single 32-bit state word on its own cache line. This section describes behaviour only.

### 5.1 Futex fundamentals
- A waiter asks the kernel to sleep **only if** the word still holds an expected value. This check prevents lost wake-ups.
- A releaser asks the kernel to wake a limited number of sleepers.
- The uncontended path stays entirely in userspace (one atomic operation).
- Private futex mode is used because all threads share one process.

### 5.2 Three-state lock word
The baseline design uses three states:
- **Unlocked.**
- **Locked, no waiters known.**
- **Locked, waiters possible.**

A waiter that cannot acquire the lock marks the word as "waiters possible" and sleeps. The releaser checks whether waiters may exist; if so, it clears the word and requests a wake-up of one sleeper. This design is described in the well-known futex-lock literature (to be located and read; see `RESEARCH_PHASE.md`, Section 4).

### 5.3 Lock variants

| Variant | Behaviour |
|---|---|
| **Park-only** | Spin budget is zero; waiters sleep immediately |
| **Spin-only** | Waiters spin with bounded backoff and never enter the kernel |
| **Static spin-then-park** | Waiters spin for a fixed time budget, then park. Several budgets are tested (proposed set: 50 ns, 200 ns, 1 µs, 5 µs, 20 µs; final values decided after wake-up measurements) |
| **pthread default** | glibc's standard mutex (external baseline) |
| **pthread adaptive** | glibc's adaptive mutex type (external baseline) |
| **Adaptive spin-then-park** | Spin budget chosen at run time by a learning policy (Section 5.4) |
| **Throttle-aware adaptive** | Adaptive lock that reduces spinning when cgroup throttling is detected (Section 5.5) |

Spin budgets are defined as **time (nanoseconds)**, not iteration counts, so results transfer across CPUs.

### 5.4 Adaptive policies (both to be designed, built and compared)

**Policy A: estimate-and-set**
- Maintain a moving average (EWMA) of the observed wake-up cost.
- Set the spin budget to that estimate, clamped to a minimum and maximum.
- Optionally maintain a moving average of hold times and skip spinning when hold times greatly exceed the wake-up estimate.
- Rationale: the classic ski-rental argument says spinning for about the cost of blocking is within a factor of two of the best offline choice when that cost is constant and known.

**Policy B: bandit over budgets**
- A small set of candidate budgets are the "arms" (proposed: about six values spanning zero to tens of microseconds).
- Each acquisition chooses an arm using an adversarial-bandit algorithm such as EXP3.
- The cost of an acquisition is spin time plus estimated wake-up cost if it parked, normalised to a bounded range.
- Non-stationarity is handled with a sliding window or periodic restarts.
- Statistics are kept per thread and merged infrequently so the policy does not create a new contended cache line.

**Design constraint (both policies):** policy bookkeeping must not become a bottleneck. Its overhead is measured separately and reported.

### 5.5 Throttle-aware variant
- Detects throttling from cgroup CPU statistics (counts and time throttled) via a periodic helper, and/or indirectly from unusually long holder absences.
- When throttling is recent or imminent, sets the spin budget to zero so waiters park rather than burn their quota.
- The detection mechanism and its overhead are documented and evaluated.

### 5.6 Fairness considerations
Each lock's fairness is characterised through per-thread acquisition counts. No fairness mechanism is promised; fairness is a **measured** property.

---

## 6. Benchmark design

### 6.1 Workload loop
Each thread repeats: acquire the lock, perform a calibrated amount of work for the hold time, release, perform calibrated work for the think time. The harness records acquire latency for each operation.

### 6.2 Workload families

| Family | Description |
|---|---|
| **Steady** | Fixed hold time and thread count. Proposed sweep of hold times from tens of nanoseconds to about 100 µs and thread counts at 1x, 2x and 4x the core count |
| **Phase-changing** | Scheduled changes in hold time (for example short, then long, then short) and in the number of active threads |
| **Randomized** | Hold times drawn from a mixture of short and long, plus bursty arrivals |
| **Throttled** | Same workloads run inside a cgroup quota set below thread demand |
| **Real application** | One or two applications run with their mutexes replaced through an interposition shim (candidate applications: SQLite, LevelDB; final choice after feasibility check) |

### 6.3 Factors varied
- Thread count (below, at, and above core count)
- Pinned and unpinned threads
- SMT on and off (if the machine allows)
- Hold time and think time
- Cgroup quota and period (throttled runs)
- Governor and turbo state (documented; controlled where possible)

### 6.4 Metrics recorded
- Throughput (overall and in fixed time windows for phase-change plots)
- Acquire latency: p50, p99, p99.9, maximum
- Fairness (per-thread acquisition share; Jain's fairness index)
- CPU time and context switches (via perf)
- Policy overhead (adaptive locks)
- Cgroup throttling counters (throttled runs)
- Optional: energy via RAPL if permissions allow

### 6.5 Wake-up latency microbenchmark
Two cooperating threads measure the time from a wake request to the sleeper running. Conditions varied: CPU placement (SMT sibling, same socket, different socket if available), idle duration before the wake (to vary sleep depth), background load on the waiter's core, and cgroup throttling. At least 100,000 samples per condition are targeted.

---

## 7. Testing and validation plan

### 7.1 Lock correctness
- Shared-counter test: many threads perform a large number of increments; final value must be exact.
- Run every lock under ThreadSanitizer.
- Stress tests with varied thread counts and pinning.
- Cross-review: each lock is reviewed by the student who did not write it.

### 7.2 Harness validation (must pass before any research data is collected)

- [ ] Final counter is exact for every lock.
- [ ] Single-thread, no-lock throughput behaves sensibly.
- [ ] Changing hold time changes throughput proportionally.
- [ ] Repeated runs agree within an acceptable variation (threshold to be decided in Week 2 and recorded).
- [ ] Timer overhead measured and documented.
- [ ] Calibrated work loops are not removed or altered by the compiler (verified by inspection or measurement).
- [ ] No false sharing between lock words and per-thread data.
- [ ] Context-switch counts match expectations (near zero for spin-only, high for park-only).

### 7.3 Environment stability
- Record CPU model, core and SMT layout, kernel version, governor, turbo state, compiler and flags.
- Use the performance governor; keep the machine plugged in and thermally stable.
- Minimise background load; consider core isolation if feasible.

### 7.4 Reproducibility
- Every result row carries the git commit and machine identifier.
- Raw data is append-only.
- Experiment runs are scripted and re-runnable.

---

## 8. Student responsibilities (build phase)

| Area | Student A (systems focus) | Student B (analysis and theory focus) |
|---|---|---|
| Futex support and baseline locks | Lead | Reviewer |
| Static and adaptive locks | Lead (implementation) | Policy design and parameter choices |
| Benchmark harness | Lead | Reviewer and validation tester |
| Workload generators | Support | Lead |
| Experiment runner and scripts | Support | Lead |
| Cgroup and throttling setup | Lead | Support |
| Wake-up microbenchmark | Shared | Shared |
| Interposition shim and real application | Lead | Support |
| Statistics and figures | Support | Lead |
| Decision log and repository hygiene | Shared | Shared |

Roles are proposed and may be rebalanced after Week 2.

---

## 9. Timeline (10 weeks)

| Week | Build goals | Deliverables |
|---|---|---|
| 0 | Study period; environment setup; warm-up exercises | Environment notes; warm-up programs working |
| 1 | Futex support; baseline locks; correctness tests | All baseline locks pass counter and ThreadSanitizer tests |
| 2 | Harness; harness validation; wake-up microbenchmark | Validation checklist complete; first wake-up data |
| 3 | Steady-state workloads and static lock sweeps | Results store populated for steady workloads |
| 4 | Phase-changing workloads | Time-windowed throughput data |
| 5 | Adaptive Policy A, then Policy B | Working adaptive locks; overhead measured |
| 6 | Policy tuning; empirical regret computation support | Adaptive-vs-static comparison data |
| 7 | Cgroup throttling runs; throttle-aware variant | Throttled-run data |
| 8 | Interposition shim; real application; second machine | End-to-end data; cross-machine subset |
| 9 | Re-runs for final statistics; data freeze | Frozen dataset |
| 10 | Artifact packaging | Public-ready repository with README and reproduction instructions |

### Cut order if time is short
1. Optional energy measurement
2. Second real application
3. Bandit policy (retain Policy A)
4. Second machine reduced to a minimal subset

---

## 10. Risks specific to the build

| Risk | Mitigation |
|---|---|
| Noisy measurements | Core isolation, performance governor, more repetitions, honest reporting of variance |
| Subtle lock bugs | Cross-review, sanitizers, stress tests before any benchmarking |
| Adaptive bookkeeping creates contention | Thread-local statistics, infrequent merges, separate overhead measurement |
| Interposition breaks on condition variables | Choose applications that avoid heavy condition-variable use, or limit scope |
| Cgroup configuration differs on the team's system | Verify the layout early; document exact commands used |
| Scope creep | Follow the cut order above |

---

## 11. Definition of done (build phase)

- [ ] All lock variants implemented, reviewed and passing correctness tests.
- [ ] Harness validation checklist fully ticked and documented.
- [ ] Wake-up microbenchmark produces data under all planned conditions.
- [ ] Steady, phase-changing, randomized and throttled workloads implemented.
- [ ] Experiment runner reproduces any configuration from the results store metadata.
- [ ] Machine manifests captured for every machine used.
- [ ] Repository documentation allows a third party to reproduce the main experiments.

**Results status: PENDING.** Nothing in this document reports or predicts measured outcomes.
