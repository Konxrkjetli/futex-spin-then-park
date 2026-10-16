# RESEARCH_PHASE.md

**Project:** *When Should a Thread Wait? An Experimental Study of Linux Futex-Based Synchronization Under Changing Contention*
**Working subtitle:** *Learning When to Park: Competitive Spin-Then-Wait Locking on Linux Futexes Under Non-Stationary Contention and CPU Throttling*
**Team:** 2 students | **Platform:** Omarchy / Arch Linux | **Language:** C

> **Status of this document:** Research planning only. All hypotheses below are **PROPOSED**. **All results are PENDING.** No experiments have been run, and nothing here should be read as a finding. Thresholds are proposed starting points to be committed to version control **before** any final data collection.

> **Update 2026-10-16 (Phases 2–4 complete):** the hypotheses were frozen at
> tag `prereg-v1` (§3.2, §5.6, §5.7, §6.1) and `prereg-v1-p3` (§5.8). All
> four now have verdicts in §3.4: H1 supported, H2/H3/H4 partially supported.
> The planning text below is kept as written; the report draft is
> `docs/report.md`.

> **Note on source material:** No separate PDF was available when this file was created. Scope, terminology and hypotheses are carried over from the project plan developed in the conversation. Literature entries are **candidates to locate and verify**, not confirmed citations.

---

## 1. Research context and problem statement

Multithreaded programs need synchronization to protect shared data, and synchronization has costs. When a thread cannot acquire a lock it may repeatedly check the lock (**spin**), block in the kernel (**sleep/park**), or combine both (**spin-then-park**). Spinning can avoid sleep/wake overhead when waits are very short but wastes CPU time when waits are long. Sleeping saves CPU but incurs blocking and waking costs. On Linux, POSIX mutexes build on futexes, which keep the uncontended path in userspace and enter the kernel only to wait or wake.

No strategy is universally best. The right choice depends on thread count, critical-section duration, CPU topology, scheduler behaviour, and the implementation of the primitive.

### 1.1 Gap this project targets
Adaptive spinning and futex contention are **not new topics**, and a generic "mutex vs. futex" comparison would be a weak novelty claim. The narrower gap proposed here:

- Classic spin-then-block analysis treats the cost of blocking as a fixed, known quantity.
- On a modern Linux system that cost may be a **distribution** that varies with CPU placement, idle state, scheduler load, and cgroup CPU throttling.
- The project asks whether a lock can **learn** the relevant costs online under **non-stationary** workloads, what guarantee can reasonably be stated, and how it behaves in practice, including under container-style CPU throttling.

The existence of this gap must itself be **checked against primary literature** (Section 4) before it is claimed.

---

## 2. Research questions

- **RQ1:** What does the wake-up cost distribution of futex wake-ups look like across CPU placement, idle state, load, and cgroup throttling?
- **RQ2:** How much do static spin budgets lose when hold times or contention shift during a run?
- **RQ3:** Can an online policy stay within a bounded factor of the best static budget in hindsight, and does this hold in practice?

Original overview question (preserved): *How do contention intensity, critical-section duration, and changing workload patterns influence the throughput, latency, and CPU cost of Linux synchronization strategies?*

---

## 3. Hypotheses (ALL PROPOSED, RESULTS PENDING)

### 3.1 Original qualitative hypotheses (from the first project overview)

| ID | Statement | Status |
|---|---|---|
| H1 (original) | Under low contention, synchronization overhead differs significantly between strategies, but the best strategy depends on workload and hardware | **Proposed. Result pending.** |
| H2 (original) | Under sustained high contention, spinning consumes more CPU resources and may reduce useful throughput | **Proposed. Result pending.** |
| H3 (original) | A fixed spinning duration performs inconsistently when critical-section duration changes | **Proposed. Result pending.** |
| H4 (original) | An adaptive strategy can improve at least one metric under changing workloads, although it may lose to standard mutexes under other conditions | **Proposed. Result pending.** |

These are retained for traceability. The refined hypotheses below make them quantitative and falsifiable.

### 3.2 Refined hypotheses: pre-registered version `prereg-v1`

These are the hypotheses that will be tested. They were committed and tagged
`prereg-v1` before any experiment data was collected. Operational definitions
are in §5.6, the experiment matrix in §5.7, and the verdict rules in §6.1.

| ID | Hypothesis (prereg-v1) | Support / refutation criterion | Status |
|---|---|---|---|
| **H1** | The median futex wake-up latency in the slowest of the 12 unloaded placement × idle conditions (§5.7, E1) is at least **2×** the median in the fastest condition | Supported if the ratio ≥ 2; refuted if < 2. The p99/p50 spread of each condition is reported descriptively, not tested | **Pending** |
| **H2** | After a hold-time shift (100 ns ↔ 20 µs), the static policy that was best before the shift either loses ≥ **25%** throughput relative to the best static policy after the shift, or has ≥ **2×** the lowest static p99 after the shift | Evaluated per transition case (§5.6). Supported if met in all 4 cases, partially supported if met in 1–3, refuted if met in none | **Pending** |
| **H3** | Each adaptive policy (A and B, judged separately) reaches ≥ **0.85×** the throughput of the best single static policy over the whole run, with p99.9 ≤ **1.2×** that policy's p99.9, on every workload in the H3 set | Supported if both bounds hold on all 6 H3 workloads; partially supported if they hold on some; refuted if on none | **Pending** |
| **H4** | Under cgroup CPU quota throttling, the throttle-aware variant has (a) ≥ **2×** lower p99.9 than spin-only **and** (b) p99.9 within **1.10×** of the best static policy under the same quota | Evaluated per H4 case (§5.7, E7). Supported if (a) and (b) hold in all cases, partially supported if in some, refuted if in none | **Pending** |

**History.** The earlier proposed wording (H1: p99/p50 spread ≥ 3×; H3: within
15% "in every phase"; H4: ≥ 2× reduction vs spin-heavy locks only) was revised
before any data. The reasons:
- p99/p50 spread within one condition does not show that the best budget
  differs *between* conditions.
- EXP3-style guarantees are against the best *single* static policy, not the
  best per phase.
- Beating spin-only alone would not separate the throttle-aware variant from
  "always park".

The revision was proposed in `TIMELINE.md` §5 and approved with the Phase 2
go-ahead, 2026-10-14 22:25 IST.

### 3.3 Rules for the hypotheses
1. Thresholds above are **proposals**. Any adjustment must be made **before** final data collection, committed to version control, and recorded in the decision log with a justification.
2. Thresholds are **not** changed after seeing results. If results fall short, they are reported as such.
3. Negative and partial findings are reported. A hypothesis that is not supported is a valid outcome.
4. Where a hypothesis is only partially supported (for example, true on one machine but not another), the paper states exactly which conditions support it.

### 3.4 Results table (to be filled only after analysis)

H3 and H4 come from E6 and E7 (Phase 3, sessions 2026-10-15), analysed by
`scripts/analyze.py e6` / `e7` under the rules of §5.6, §6.1, C1 and C2. Full
tables: `docs/results/e6.md`, `docs/results/e7.md`. Interpretation and the
exploratory context (barging, starved threads, a B\*-fixed sensitivity view)
are in README §12; they do not change these verdicts.

| Hypothesis | Threshold | Observed result | Verdict |
|---|---|---|---|
| H1 | slowest/fastest median ≥ 2× | other-core/10 ms idle 30.72 µs ÷ other-core/20 µs idle 2.73 µs = **11.27** (95% CI 11.18–11.37; worst-case run ratio 9.59) | **SUPPORTED** |
| H2 | loss ≥ 25% or p99 ratio ≥ 2×, in each of 4 cases | S1 T=8: 0→1 not met (loss 3.2%, p99 ratio 1.00), 1→2 not met (1.8%, 1.64). S1 T=16: 0→1 met (loss 43.1%), 1→2 met (p99 ratio 2.59) | **PARTIALLY SUPPORTED** (2/4) |
| H3 | throughput ≥ 0.85× and p99.9 ≤ 1.2× of best static, on each of 6 workloads (per policy) | **Policy A (`ada`)**: met S2 T=16; not met S1 T=8 (p99.9 4.60×), S1 T=16 (throughput 0.78×), R1 T=16 (p99.9 1.45×); inconclusive S2 T=8, R1 T=8 (p99.9 interval spans 1.2). **Policy B (`hedge`)**: met S1 T=8, S2 T=16, R1 T=16; not met S1 T=16 (throughput 0.79×); inconclusive S2 T=8 (p99.9), R1 T=8 (throughput 0.84×, CI 0.81–0.86; p99.9) | **A: PARTIALLY SUPPORTED** (1 met / 3 not met / 2 inconclusive); **B: PARTIALLY SUPPORTED** (3 / 1 / 2) |
| H4 | p99.9 ≥ 2× lower than spin and ≤ 1.10× best static, in each of 4 cases | Hold 1 µs: met at 200% (spin/ta 60.8, ta/best static 0.99 vs park) and 400% (55.4, 0.98). Hold 10 µs: not met at 200% (ta/best static 1770× vs stp:37850; spin/ta 2.17 inconclusive) and 400% (1608×; 2.17 inconclusive) | **PARTIALLY SUPPORTED** (2/4) |

---

## 4. Literature review plan

**Important:** The entries below are **candidate sources the team should locate, read and verify**. Bibliographic details come from memory and are unconfirmed. No claim about their contents should be written into the paper until the primary source has been read. Nothing in this section is a verified citation.

### 4.1 Candidate sources by topic

| Topic | Candidate source (to locate and verify) | Why it may be relevant |
|---|---|---|
| Futex lock design | Drepper, "Futexes Are Tricky" | Futex lock design and pitfalls |
| Linux interfaces | Linux manual pages for futex, pthread mutex attributes, cgroups, perf | Authoritative interface behaviour |
| Competitive spinning | Karlin et al., "Empirical Studies of Competitive Spinning for a Shared-Memory Multiprocessor" (SOSP 1991) | Spin-then-block analysis |
| Evaluating many locks on real software | Guiroux, Lachaize, Quéma, "Multicore Locks: The Case Is Not Closed Yet" (USENIX ATC 2016) | Lock comparison methodology; interposition approach |
| Hardware effects on synchronization | David, Guerraoui, Trigonakis, "Everything You Always Wanted to Know About Synchronization But Were Afraid to Ask" (SOSP 2013) | Hardware-level cost of synchronization |
| Energy of locking | Falsafi et al., "Unlocking Energy" (USENIX ATC 2016) | Energy side of spin vs. sleep (extension only) |
| Queue locks | Mellor-Crummey and Scott, "Algorithms for Scalable Synchronization on Shared-Memory Multiprocessors" (1991) | Background on queue locks and fairness |
| Adversarial bandits | Auer, Cesa-Bianchi, Freund, Schapire, "The Nonstochastic Multiarmed Bandit Problem" | Basis for EXP3 and regret statements |
| Online algorithms | A textbook or course notes on online algorithms and competitive analysis | Ski-rental framing |
| Bandits (general) | A bandit-algorithms textbook (freely available versions may exist; confirm) | Regret analysis and non-stationary variants |
| Operating systems background | OSTEP (Operating Systems: Three Easy Pieces) | Threads, locks, condition variables |
| Linux scheduler bandwidth control | Linux kernel documentation on scheduler bandwidth control and the cgroup v2 guide | Meaning of CPU quota and throttling |
| Measurement rigor | Papers or talks on rigorous benchmarking, measurement bias, and coordinated omission (team to search) | Methodology |

### 4.2 Searches the team must perform (not yet done)
- Kernel mailing list archives for earlier discussions of adaptive futex spinning or futex lock throughput. **Read the primary threads.** The original overview mentioned a recent kernel-development discussion of futex wait overhead; this has **not been verified** and must not be cited from a secondary summary.
- Literature on adaptive mutexes, lock-holder preemption, container CPU throttling and its effect on locks, and scheduler-cooperative locking (titles unverified).
- Literature on non-stationary or switching-regret bandits.

### 4.3 How the related-work section will be written
For each verified source, state in the team's own words:
1. What it studied.
2. What it did **not** answer relative to RQ1 to RQ3.
3. How this project's setup differs.

If the search shows the gap is already covered, the framing must be narrowed or changed rather than the claim kept.

---

## 5. Experimental methodology

### 5.1 Systems under test
- Team-implemented futex locks: park-only, spin-only, static spin-then-park (several budgets), adaptive spin-then-park (Policy A and Policy B), throttle-aware adaptive.
- External baselines: glibc default pthread mutex and adaptive pthread mutex type.
- Implementation details are in `BUILD_PHASE.md`.

### 5.2 Workloads and factors
- **Steady, phase-changing, randomized, throttled** workloads, and one or two real applications via interposition.
- Factors: thread count (1x, 2x, 4x cores and below core count), pinned vs. unpinned, SMT on/off where possible, hold time, think time, cgroup quota and period.

### 5.3 Metrics
Throughput (overall and windowed), acquire latency (p50, p99, p99.9, max), fairness (per-thread share, Jain's index), CPU time and context switches, policy overhead, throttling counters, optional energy.

### 5.4 Procedure
1. Validate the harness (checklist in `BUILD_PHASE.md`, Section 7.2).
2. Commit hypotheses and thresholds.
3. Run RQ1 measurements (wake-up latency).
4. Run steady and phase-changing sweeps for static locks (RQ2).
5. Run adaptive locks on the same workloads (RQ3).
6. Run throttled experiments (H4).
7. Run real-application experiments.
8. Repeat a reduced matrix on a second machine, if available.
9. Freeze data, then analyse.

### 5.5 Controls and record-keeping
- Record CPU model, topology, kernel, governor, turbo state, SMT state, compiler and flags for every run.
- Randomize or interleave the run order of configurations to reduce drift effects.
- Include warm-up periods and report them.
- Do not discard slow samples; tail behaviour is part of the result.

### 5.6 Pre-declared definitions (prereg-v1)

**Lock families.**
- *Static family* S = {`park`, `stp:b1`, `stp:b2`, `stp:b3`, `stp:b4`, `spin`}, the team's
  implementations, which share one code path except for the spin budget.
- *External baselines* {`pthread`, `pthread-adaptive`} are measured and reported
  in every experiment but are **not** candidates for "best static policy".
- *Adaptive*: Policy A, Policy B (Phase 3). *Throttle-aware*: Phase 3.

**Spin-budget rule.** Let m be the median wake-up latency of E1 condition
`other-core / idle 100 µs / unloaded`, pooled over its runs. Then
b1..b4 = {0.5, 1, 2, 8} × m, each rounded to the nearest 50 ns. The budgets
are computed by `scripts/choose_budgets.py` and committed to
`config/budgets.json` before E2–E5 run.

**Phases and transitions.** A *phase* is a span of fixed hold time, think time
and active thread count. The first **100 ms** after every shift is a
*transition window*, implemented as its own harness phase and **excluded** from
all phase metrics. It is still recorded and shown in time-series figures.

**Metrics.**
- *Throughput* of a policy in a span = mean over runs of that run's throughput
  in the span.
- *Tail latency* (p99, p99.9) = nearest-rank quantile of the histogram pooled
  over all runs of that configuration.

**Best static policy.** For a given span, the member of S with the highest
throughput. Ties within 1% go to the lower p99.

**H2 transition cases.** Workload S1 (§5.7) at T ∈ {8, 16} has two shifts
(100 ns → 20 µs, then 20 µs → 100 ns), giving 4 cases. For each case let A\* be
the best static policy in the pre-shift phase. Then
- loss = 1 − throughput(A\*, post) / max over s∈S of throughput(s, post),
- tail ratio = p99(A\*, post) / min over s∈S of p99(s, post).

The case meets H2 if loss ≥ 0.25 or tail ratio ≥ 2.

**H3.**
- Workload set: S1, S2 and R1 (§5.7) at T ∈ {8, 16}, 6 workloads in total.
- The span is the whole run minus the transition windows.
- Best static policy B\* is chosen per workload by the rule above.
- Bounds per workload: throughput(adaptive) ≥ 0.85 × throughput(B\*), and
  p99.9(adaptive) ≤ 1.2 × p99.9(B\*).
- H3 data comes from one Phase 3 session in which static and adaptive locks run
  interleaved in random order, so session-to-session drift cannot favour
  either side.
- Adaptive-policy parameters may be tuned **only** on steady workloads at
  T = 4 (tuning set), never on H3 workloads.

**H4.** For each H4 case (§5.7, E7):
- (a) p99.9(spin) / p99.9(throttle-aware) ≥ 2;
- (b) p99.9(throttle-aware) ≤ 1.10 × min over s∈S of p99.9(s) under the same quota.

**Data exclusion.** No samples or runs are dropped for being slow. A run is
invalid only if the harness reports `counter_ok = false` or the process fails.
Invalid runs are re-run, and their number is reported.

**Run order and environment.** Every experiment runs in a seeded random order
across all its configurations. One work-loop calibration and one TSC
calibration are shared per session. Turbo boost stays **on** (team decision,
2026-10-14), and drift covariates (temperature, post-run work rate) are
recorded per run and reported.

### 5.7 Experiment matrix (prereg-v1)

All bench runs use cores-first pinning (except E3), think time 1 µs (except
E5), 200 ms warm-up, 10 ms throughput windows, a latency histogram per run,
and the 8 locks S ∪ {pthread, pthread-adaptive}.

| ID | Experiment | Configurations | Runs | Serves |
|---|---|---|---|---|
| E1 | Wake-up latency | placements {smt-sibling 2↔3, other-core 2↔4, same-cpu 2↔2} × idle {20 µs, 100 µs, 1 ms, 10 ms}, unloaded (12 conditions); plus a CPU hog on the sleeper's CPU for smt-sibling and other-core at 1 ms idle (2 descriptive conditions). Samples per run: 33,400 (7,000 at 10 ms idle) | 3 per condition | RQ1, H1, budget rule |
| E2 | Steady sweep | hold {100 ns, 1 µs, 10 µs, 50 µs} × T {4, 8, 16, 32}, 2 s | 5 | RQ2 (best lock map) |
| E3 | Unpinned subset | hold {1 µs, 10 µs} × T {8, 32}, no pinning, 2 s | 3 | Pinning sensitivity |
| E4 | Phase-changing | S1: hold 100 ns → 20 µs → 100 ns at T active; S2: hold 1 µs, active T/4 → T → T/4. Each phase 1.5 s (first 100 ms is transition). T ∈ {8, 16} | 10 | RQ2, H2 (S1) |
| E5 | Randomized | R1: hold 200 ns, or 20 µs with probability 0.1; exponential think, mean 2 µs; T ∈ {8, 16}, 3 s | 10 | RQ2 |
| E6 | H3 session (Phase 3) | S1, S2, R1 at T ∈ {8, 16}, static and adaptive locks interleaved | 10 | H3 |
| E7 | Throttled (Phase 3) | steady hold {1 µs, 10 µs}, T = 16, under `CPUQuota` {200%, 400%}, period 100 ms: 4 cases | 10 | H4 |

### 5.8 Phase 3 protocol (written 2026-10-15, before any Phase 3 experiment data)

This section fills in what `prereg-v1` left open for Phase 3: the exact
policies, the tuning procedure, the E6/E7 lock lists and launcher, and how the
H3/H4 intervals are computed. It changes **no** threshold, workload or verdict
rule of `prereg-v1`. It is committed before the tuning session T3. The
parameters chosen by T3 are committed in `config/policy.json` and tagged
`prereg-v1-p3` before any E6–E8 data.

**Locks** (`src/lock_adaptive.c`, `src/policy.c`). Every adaptive lock is the
three-state futex lock of the static family, with the spin budget chosen on
each slow path. `src/lock_futex.c` is unchanged, so the static locks run the
code measured in Phase 2.

- *Cost model shared by both policies (ski rental).* A waiter that would get
  the lock by spinning after w ns pays cost(b) = w if w ≤ b, else b + C, with
  C = β·Ŵ.
  - Ŵ is a per-thread EWMA (α = 1/16) of the wake-up latency measured inside
    the lock: the releaser stamps the TSC just before `FUTEX_WAKE`, and the
    woken waiter subtracts that stamp when it returns.
  - Samples are capped at 1 ms. The prior is the E1 reference median
    m = 4728.9 ns.
  - β is the one tuned parameter. It scales the measured wake latency into
    the full cost of parking (the releaser's `FUTEX_WAKE`, the lost turn,
    cache refill).
- *Policy A* (`ada`): budget = clamp(β·Ŵ, 0, 151.3 µs).
- *Policy B* (`hedge`): Hedge over K = 6 arms
  {0, 2350, 4750, 9450, 37850, 151300} ns, i.e. {0, b1..b4, 32·m}.
  - Learning: discounted cumulative cost with horizon N = 1024 slow-path
    acquisitions (γ = 1 − 1/N), η = √(8 ln K / N).
  - Each round's costs are shifted by their minimum and divided by C,
    clipped at 1.
  - Feedback is the whole counterfactual cost vector. It is exact for spin
    acquisitions. For a parked acquisition, arms ≤ the chosen budget cost
    b + C, and longer arms are imputed from the stamp of the release that let
    the waiter in.
  - The arm is drawn at random from the Hedge distribution.
- *EXP3* (`exp3`, exploratory): same arms, but only the chosen arm's cost is
  used, importance-weighted (cost / 2C, clipped at 1). The explore rate and η
  use the standard horizon-N formulas, and β is the same as Policy B's.
- *Throttle-aware* (`ta`): a base policy plus a helper thread that polls the
  process's own cgroup `cpu.stat` every 1 ms while `cpu.max` sets a quota.
  - Trigger: `nr_throttled` increased, or CPU usage over the last poll
    reached 0.9 × quota/period.
  - Effect: budget 0 ("park mode") for `hold` quota periods. A trigger during
    park mode extends it. A trigger within one period after park mode ended
    doubles `hold` (1 → 64 periods max); any later trigger resets it to 1.
  - These detector parameters are fixed by design, not tuned.
- All policy state is per thread. The policy update runs in `unlock` after
  the release, so it never lengthens a critical section.

**Disclosures before tuning.**
1. *Design iteration on the tuning set.* The first Hedge version divided costs
   by (largest arm + C). In a 1 s smoke run at T = 4, hold 1 µs (inside the
   tuning set), it barely separated the arms: they kept 0.1–24% each. The
   normalisation was changed to the shift-and-divide-by-C form above before
   T3.
2. *Smoke runs.* All development runs of the adaptive locks were steady T = 4
   (tuning set) or the correctness test. No adaptive lock was run on an
   H3 workload (S1/S2/R1 at T = 8/16) or an H4 case before the freeze.
3. *Mechanism check of the throttled launcher.* One 1 s run each of `spin`
   and `ta:base=hedge,beta=4` at T = 8, hold 1 µs, `CPUQuota=100%` (not an
   H4 case). It checked the scope launcher, the throttling counters and the
   detector.
   - Both runs were throttled in 10 of 10 periods, and `ta` forced 100% of
     its slow paths to park.
   - p99.9 was 67 µs for spin and 499 µs for `ta`.
   - No parameter was changed after this check.
4. *Phase 2 results were known* when the policies were designed (they are in
   the README). The design follows `BUILD_PHASE.md` §5.4–5.5; the numeric
   choices are either derived from E1 (prior, arms) or tuned on T = 4 only.

**Tuning session T3** (the tuning set allowed by `prereg-v1`).
- Workloads: steady, T = 4, hold {100 ns, 1 µs, 10 µs, 50 µs}, think 1 µs,
  2 s, pinned, 5 runs, seeded random order.
- Locks: the static family S, plus `ada` and `hedge` with
  β ∈ {1, 2, 4, 8, 16}.
- Scoring, for each candidate c and hold h:
  - B\*_h = best static lock, by the §5.6 rule;
  - thr ratio = throughput(c) / throughput(B\*_h);
  - tail ratio = p99.9(c) / p99.9(B\*_h), from histograms pooled over runs;
  - the hold *passes* if thr ratio ≥ 0.85 and tail ratio ≤ 1.2.
- Selection, per policy:
  1. most holds passed;
  2. then the highest worst-case thr ratio (differences of 0.01 or less are
     ties);
  3. then the lowest worst-case tail ratio;
  4. then the smaller β.
- EXP3 uses Policy B's β. The throttle-aware base is the better of the two
  winners by the same order; a full tie goes to `ada`.
- `scripts/choose_policy.py` writes the result to `config/policy.json`.

**E6 (H3).** As §5.7: S1 and S2 as in E4, R1 as in E5, T ∈ {8, 16}, 10 runs,
one session, seeded random order. Locks:
- S, `pthread`, `pthread-adaptive`;
- `ada` and `hedge` (confirmatory);
- `exp3` and `ta` (exploratory).

**E7 (H4).**
- Workload: steady, hold {1 µs, 10 µs}, think 1 µs, T = 16, 2 s, pinned,
  10 runs.
- Each run gets its own systemd transient scope:
  `systemd-run --user --scope -p CPUQuota={200,400}% -p CPUQuotaPeriodSec=100ms`.
- Locks: S, `pthread`, `pthread-adaptive`, `ada`, `hedge`, `ta`.
- Throttling counters (`cpu.stat` deltas over the measured window) are
  recorded per run.
- Exploratory unthrottled reference: the same runs in a scope without a
  quota, 5 runs.

**E8 (exploratory).** The E2 steady grid (4 holds × T {4, 8, 16, 32}),
3 runs, with locks `ada`, `hedge`, `exp3`, `ta`, plus `park` and `spin` as
anchors for session drift against E2.

**Clarification C2 (H3/H4 computation).**
- H3 span: all non-transition harness phases. Throughput per run = ops in the
  span / span duration, then mean over runs. p99.9 is pooled over the span's
  phases and all runs.
- Bootstrap: 2,000 resamples, runs resampled with replacement independently
  for each lock.
  - B\* (H3) is recomputed by the §5.6 rule in every resample, as "best
    after the shift" was in C1.
  - The minimum over S in H4(b) is recomputed in every resample.
- Verdicts:
  - Bounds combine per C1.
  - Overall verdict: SUPPORTED if met in every case; REFUTED if not met in
    every case; PARTIALLY SUPPORTED if met in at least one; otherwise
    INCONCLUSIVE.

**Exploratory analyses** (labelled as such, not tests):
- per-phase adaptive vs best static, transition windows excluded;
- throughput regret against B\* over 10 ms windows;
- regret in the policies' own cost model (cost paid minus the best fixed arm
  in hindsight);
- arm use and mean budget over time;
- fairness: Jain's index, worst-thread p99, and the waiting-time-weighted
  latency distribution (the barging view raised in the Phase 2 review);
- CPU use;
- EXP3 vs Hedge, and `ta` vs its base policy without a quota;
- wake latency measured inside the lock vs E1;
- throttling counters.


### 5.9 Phase 4 additions (written 2026-10-16, before any E9 data)

**E9 (exploratory, no hypothesis): real application.** SQLite 3.53.4, one
in-memory database and **one connection shared by T threads** in serialized
mode. Every API call therefore takes the connection's recursive mutex. 10,000
rows. Each operation is a point SELECT (90%) or an `UPDATE v = v + 1` (10%) on
a random key. 2 s measured, 200 ms warm-up, pinned, T ∈ {4, 8, 16, 32},
5 runs, seeded random order.

- Locks: `native` (glibc's mutex, no shim), plus the static family S, `ada`,
  `hedge`, `exp3` and `ta`, all with the frozen `prereg-v1-p3` parameters.
  The non-native locks run through the LD_PRELOAD shim (`src/shim.c`), which
  maps each `pthread_mutex_t` to its own futex-lab lock and implements
  recursion in the shim.
- Validity: SUM(v) at the end must equal the number of UPDATEs executed.
  Otherwise the run is invalid and re-run, as for `counter_ok`.
- Reported: throughput, latency per operation (bind + step + reset, which
  includes the time inside SQLite), Jain's index, CPU.
- Smoke runs before this declaration: 300 ms at T = 8 for every lock (to
  check the shim and the SUM check), not used as data.

**Supplementary tests for the pre-declared comparisons** (§6). For H1–H4
only, the Mann–Whitney U test with an effect size (probability of
superiority A, and the Hodges–Lehmann shift where meaningful), on:

- per-sample wake latencies (H1);
- per-run throughput, per-run p99 or p99.9 (H2–H4).

p-values are Holm-corrected within each hypothesis. These tests do not change
any verdict: verdicts follow §6.1. Per-run tail quantiles from about 10 runs
are noisy, which is why the verdict rule uses pooled histograms.

---

## 6. Statistical analysis plan

- **Repetitions:** target at least 30 runs per configuration for main experiments; if fewer are used for large sweeps, state so explicitly.
- **Summaries:** medians and percentiles with **95% bootstrap confidence intervals**.
- **Comparisons:** report effect sizes alongside a non-parametric test (for example Mann-Whitney U). Pre-declare the comparisons to avoid selective testing. Account for multiple comparisons or limit the number of confirmatory tests.
- **Tail latency:** compute percentiles over pooled samples with documented handling of run-to-run variation; report variation across runs as well.
- **Regret analysis (RQ3):** for each workload, compute the cumulative cost of the adaptive lock and that of the best static budget in hindsight; report the difference over time.
- **Theory component (modest, optional):** state assumptions explicitly and cite known results only after verifying them. If a proof is not achieved, report the empirical regret analysis only and say so.
- **Hypothesis verdicts:** compare observed values against the pre-committed thresholds and fill the table in Section 3.4.

### 6.1 Verdict and interval rules (prereg-v1)

- **Point estimate decides; the interval can veto.** A case meets or misses a
  threshold based on the point estimate. If the 95% interval of the deciding
  quantity contains the threshold, the case is marked **inconclusive**. It is
  counted as neither met nor missed, and reported as such.
- **Intervals:**
  - Throughput ratios: bootstrap over runs (2,000 resamples, percentile intervals).
  - Pooled tail-latency quantiles and their ratios: bootstrap over runs, merging
    the resampled runs' histograms (2,000 resamples).
  - Wake-up medians (E1): distribution-free order-statistic interval for each
    median. For the H1 ratio, the conservative interval
    [lo(slow) / hi(fast), hi(slow) / lo(fast)].
  - The target of ≥ 10,000 bootstrap resamples (§6) is reduced to 2,000
    because analysis runs in pure Python (numpy/scipy not installed). This is
    a recorded deviation.
- **Multiple comparisons:** only the H1–H4 comparisons above are
  confirmatory. Everything else (heatmaps, pthread comparisons, fairness,
  unpinned runs) is exploratory and labelled as such.
- **No changes after data.** Thresholds, definitions, workloads and these rules
  are frozen at tag `prereg-v1`. Any later change is reported as a deviation,
  with both the pre-registered and the changed analysis shown.

**Clarification C1 (written 2026-10-14 ~22:33 IST, after `prereg-v1` (22:28:12) but
before any E4 data; no thresholds changed).** H2 is an OR of two metrics. Each
metric is judged by the rule above. A case is *met* if at least one metric is
met, *not met* if both are not met, and *inconclusive* otherwise. In the H2
bootstrap, A\* stays the policy identified from the point estimates, and the
"best after the shift" is recomputed in every resample. The same treatment
applies to the AND-combination in H3/H4: a case meets the hypothesis only if
every bound is met, misses it if any bound is not met, and is inconclusive
otherwise.
- **Cross-machine consistency:** compare the ranking of locks and the direction of effects across machines.

---

## 7. Expected figures and tables (planned; no data yet)

| # | Planned figure/table | Supports |
|---|---|---|
| 1 | Wake-up latency distributions (CDFs) by placement and idle condition | RQ1, H1 |
| 2 | Heatmap of best lock as a function of hold time and thread count | RQ2 |
| 3 | Throughput over time across a phase change for each lock | RQ2, H2 |
| 4 | Adaptive lock vs. best static in each phase; cumulative regret curve | RQ3, H3 |
| 5 | p99 and p99.9 latency under oversubscription | H3 |
| 6 | Throttled vs. unthrottled comparison, including throttle-aware variant | H4 |
| 7 | Real-application end-to-end throughput and latency | Real-workload relevance |
| 8 | Fairness table (Jain's index) | Fairness |
| 9 | Hypothesis summary table (Section 3.4) | All |
| 10 | Policy overhead measurement | Validity of adaptive-lock comparison |

All figures are **placeholders** until data exists. Figure designs must not be adjusted to match hoped-for results.

---

## 8. Paper structure (proposed)

1. **Abstract:** problem, approach, main quantitative findings (only after results exist), limitations.
2. **Introduction:** motivation, gap (as verified), contributions list.
3. **Background:** futexes, spin vs. park, ski-rental framing, bandit framing.
4. **Related work:** verified sources only; what each leaves open.
5. **Design:** locks, adaptive policies, throttle-aware variant, any theory.
6. **Methodology:** machines, workloads, metrics, procedure, statistics.
7. **Results:** RQ1, RQ2, RQ3, H4, real application, cross-machine check.
8. **Discussion:** when adaptation helps, when it does not, practical guidance.
9. **Threats to validity and limitations.**
10. **Conclusion** and artifact availability.

The contribution list is written last and must match what the evidence supports.

---

## 9. Limitations and threats to validity (anticipated)

- Results may be specific to the tested CPU(s), kernel version and configuration.
- Only one or two machines are likely available; generality is limited.
- Synthetic workloads may not represent real programs; only a small number of real applications are planned.
- Timer, harness and policy overhead may influence results despite validation.
- Frequency scaling, thermal behaviour and background activity can introduce drift.
- Interposition may alter behaviour of applications that rely heavily on condition variables.
- The learning policy's effectiveness depends on parameter choices; tuning on the same workloads used for evaluation would overstate performance, so tuning and evaluation workloads must be kept distinct.
- Thread interactions may violate independence assumptions in any theoretical bound.
- The novelty of the gap has not yet been confirmed by literature search.
- Scopus indexing status of any target venue must be checked independently; it is not guaranteed by this plan.

---

## 10. Research responsibilities

| Area | Student A (systems focus) | Student B (analysis and theory focus) |
|---|---|---|
| Literature search (kernel archives, systems papers) | Shared | Shared |
| Bandit and online-algorithm background | Support | Lead |
| Hypothesis and threshold commitment | Joint | Joint |
| Experimental procedure and environment control | Lead | Support |
| Statistical analysis | Support | Lead |
| Figures | Support | Lead |
| Regret analysis and theory (if attempted) | Support | Lead |
| Real-application and throttling experiments | Lead | Support |
| Paper drafting | Shared by section | Shared by section |
| Cross-review of claims against data | Joint | Joint |
| Artifact release and reproducibility check | Joint | Joint |

Roles are proposed and may be rebalanced.

---

## 11. Research timeline (aligned with `BUILD_PHASE.md`)

| Week | Research activities |
|---|---|
| 0 | Study plan (OS basics, futex mechanics, hardware effects, statistics, ski rental, bandits); begin literature collection |
| 1-2 | Verify literature; draft hypotheses commitment; RQ1 data collection after harness validation |
| 3-4 | RQ2 data collection; begin related-work and methodology drafting |
| 5-6 | RQ3 data collection; empirical regret analysis; theory attempt (optional) |
| 7 | Throttling experiments (H4) |
| 8 | Real application and second machine |
| 9 | Freeze data; run statistical analysis; evaluate hypotheses against pre-committed thresholds |
| 10 | Complete paper draft; internal review; supervisor review; artifact release |

---

## 12. Venue and integrity notes

- Venue choice and its **Scopus indexing status must be verified** on the venue's page and the Scopus source list before submission.
- The target venue's policies on authorship, AI-assisted writing, and data and code availability must be checked and followed.
- All citations must be confirmed against primary sources.
- Faculty or supervisor review is recommended before submission.

---

## 13. Definition of done (research phase)

- [ ] Literature search completed; every citation verified against its primary source.
- [ ] Gap statement confirmed, narrowed or revised based on the search.
- [ ] Hypotheses and thresholds committed before final data collection.
- [ ] All planned experiments run, or omissions documented.
- [ ] Statistics performed as specified; deviations documented.
- [ ] Hypothesis table completed with observed results and verdicts.
- [ ] Limitations written candidly.
- [ ] Paper draft reviewed; claims traced to figures or tables.

**Results status: PENDING.** No outcome has been observed or assumed.
