# RESEARCH_PHASE.md

**Project:** *When Should a Thread Wait? An Experimental Study of Linux Futex-Based Synchronization Under Changing Contention*
**Working subtitle:** *Learning When to Park: Competitive Spin-Then-Wait Locking on Linux Futexes Under Non-Stationary Contention and CPU Throttling*
**Team:** 2 students | **Platform:** Omarchy / Arch Linux | **Language:** C

> **Status of this document:** Research planning only. All hypotheses below are **PROPOSED**. **All results are PENDING.** No experiments have been run, and nothing here should be read as a finding. Thresholds are proposed starting points to be committed to version control **before** any final data collection.

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

### 3.2 Refined hypotheses with proposed thresholds

| ID | Proposed hypothesis | Proposed refutation / support criterion | Status |
|---|---|---|---|
| **H1** | Wake-up latency varies by at least 3x between p50 and p99 across placement and idle-state conditions, so no single fixed spin budget can be near-optimal across them | Refuted if the p99/p50 spread is below the threshold in all conditions | **Proposed. Pending.** |
| **H2** | When hold time shifts (for example from about 100 ns to about 20 µs), the best static budget from before the shift loses at least 25% throughput or at least doubles p99 latency afterwards | Refuted if the degradation is below both thresholds | **Proposed. Pending.** |
| **H3** | The adaptive lock stays within 15% of the best static policy in every phase, with p99.9 latency no worse than 1.2x the best policy's, across tested workloads | Refuted if either bound is exceeded in any pre-declared phase | **Proposed. Pending.** |
| **H4** | Under cgroup CPU quota throttling, spin-heavy locks show inflated p99.9 latency that the throttle-aware variant reduces by at least 2x | Refuted if the reduction is below 2x | **Proposed. Pending.** |

### 3.3 Rules for the hypotheses
1. Thresholds above are **proposals**. Any adjustment must be made **before** final data collection, committed to version control, and recorded in the decision log with a justification.
2. Thresholds are **not** changed after seeing results. If results fall short, they are reported as such.
3. Negative and partial findings are reported. A hypothesis that is not supported is a valid outcome.
4. Where a hypothesis is only partially supported (for example, true on one machine but not another), the paper states exactly which conditions support it.

### 3.4 Results table (to be filled only after analysis)

| Hypothesis | Threshold | Observed result | Verdict |
|---|---|---|---|
| H1 | PENDING | PENDING | PENDING |
| H2 | PENDING | PENDING | PENDING |
| H3 | PENDING | PENDING | PENDING |
| H4 | PENDING | PENDING | PENDING |

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

### 5.6 Pre-declared definitions (to finalise before data collection)
- What counts as a "phase" and how the first moments after a shift are treated.
- How the "best static policy in hindsight" is determined for each workload.
- How "within 15%" and "within 1.2x" are computed (per phase, per run, per machine).
- Which workloads count toward each hypothesis.

---

## 6. Statistical analysis plan

- **Repetitions:** target at least 30 runs per configuration for main experiments; if fewer are used for large sweeps, state so explicitly.
- **Summaries:** medians and percentiles with **95% bootstrap confidence intervals**.
- **Comparisons:** report effect sizes alongside a non-parametric test (for example Mann-Whitney U). Pre-declare the comparisons to avoid selective testing. Account for multiple comparisons or limit the number of confirmatory tests.
- **Tail latency:** compute percentiles over pooled samples with documented handling of run-to-run variation; report variation across runs as well.
- **Regret analysis (RQ3):** for each workload, compute the cumulative cost of the adaptive lock and that of the best static budget in hindsight; report the difference over time.
- **Theory component (modest, optional):** state assumptions explicitly and cite known results only after verifying them. If a proof is not achieved, report the empirical regret analysis only and say so.
- **Hypothesis verdicts:** compare observed values against the pre-committed thresholds and fill the table in Section 3.4.
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
