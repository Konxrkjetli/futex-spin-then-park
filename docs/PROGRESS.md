# PROGRESS.md

Live tracker for the one-night plan in `TIMELINE.md`. Update after each task. Times are IST.

**Current phase:** All four phases complete (Phase 4 finished 2026-10-16 23:18 IST); data frozen at tag `data-freeze-v1`; awaiting review
**Results status:** H1 SUPPORTED, H2 PARTIALLY SUPPORTED (Phase 2). H3 PARTIALLY SUPPORTED for Policy A (1/6) and Policy B (3/6); H4 PARTIALLY SUPPORTED (2/4) (Phase 3).

---

## Phase status

| Phase | Window | Status | Started | Finished |
|---|---|---|---|---|
| 1. Foundation | 22:00 – 01:00 | **Done** (awaiting review) | 21:55 | 22:15 |
| 2. Pre-registration + static experiments | 01:00 – 03:30 | **Done** (accepted with the Phase 3 go-ahead) | 22:25 | 23:59 |
| 3. Adaptive + throttling | 03:30 – 06:30 | **Done** (awaiting review) | 15 Oct 21:52 | 16 Oct 00:09 |
| 4. Analysis + write-up | 06:30 – 09:30 | **Done** (awaiting review) | 16 Oct 22:51 | 16 Oct 23:18 |

---

## Phase 1: Foundation

- [ ] (you) Install perf, strace, cpupower, python-pandas, python-scipy, python-matplotlib — **not done yet; Phase 1 worked around it (getrusage, stdlib-only scripts); pandas/scipy needed by Phase 4**
- [ ] (you, optional) Turn off boost, or confirm it stays on and is recorded — **boost still on; validation shows 4–7% clock drift under load (README §7, §10.1); decide before Phase 2**
- [x] git init + repository layout + Makefile
- [x] Machine manifest script
- [x] futex wrappers, cpu_relax, TSC timing + calibration
- [x] Common lock interface
- [x] Park-only lock
- [x] Spin-only lock
- [x] Static spin-then-park lock
- [x] pthread default + adaptive wrappers
- [x] Shared-counter correctness test, all locks
- [x] ThreadSanitizer build clean
- [x] Benchmark harness (pinning, hold/think work, per-thread latency buffers, CSV)
- [x] Wake-up latency microbenchmark
- [x] Harness validation checklist (`BUILD_PHASE.md` §7.2)
  - [x] Counter exact for every lock
  - [x] Single-thread no-lock throughput sensible
  - [x] Throughput tracks hold time proportionally
  - [x] Run-to-run variation measured; threshold recorded
  - [x] Timer overhead measured
  - [x] Work loops not optimised away
  - [x] No false sharing
  - [x] Context switches: near zero for spin-only, high for park-only

## Phase 2: Pre-registration + static experiments

- [x] Hypothesis decisions (`TIMELINE.md` §5) applied to `RESEARCH_PHASE.md`
- [x] Pre-declared definitions written (`RESEARCH_PHASE.md` §5.6)
- [x] Commit + tag `prereg-v1` (before any data)
- [x] RQ1 wake-up microbenchmark data
- [x] Final static budget set chosen by the pre-declared rule
- [x] Steady sweep (static locks)
- [x] Unpinned subset
- [x] Phase-changing workload data
- [x] Randomized workload data
- [x] Data committed

## Phase 3: Adaptive + throttling

- [x] Policy A (estimate-and-set)
- [x] Policy B (Hedge, censored feedback)
- [x] (optional) EXP3 variant
- [x] Adaptive locks: counter test + TSan (39/39 pass, 0 TSan warnings; `ta` also under a 50% quota)
- [x] Policy overhead measured (`calib policy`, `calib timer`)
- [x] Phase 3 protocol written before any Phase 3 data (RESEARCH_PHASE §5.8)
- [x] Tuning session T3 (steady T = 4, 320 runs, 0 invalid) → `config/policy.json` (ada β = 8, hedge β = 8, ta base = ada), tag `prereg-v1-p3`
- [x] Adaptive locks on steady / phase-changing / randomized workloads (E6: 720 runs; E8: 288 runs; 0 invalid)
- [x] Throttle-aware variant (`ta`, built with the other locks)
- [x] Throttled runs (H4) (E7: 550 runs, 0 invalid)
- [x] Analysis: H3, H4 verdicts → RESEARCH_PHASE §3.4; README §12
- [x] Data committed

## Phase 4: Analysis + write-up

- [x] Analysis scripts (bootstrap CIs, tests, Jain's index, regret): `analyze.py` (Phases 2–3) + `supplement.py` (Mann–Whitney U, effect sizes, Holm; pre-declared comparisons only)
- [x] Figures 1–10: `scripts/figures.py` → `docs/figures/` (7 figure files + tables 8, 9; light/dark SVG + CSV twin each; palette CVD-validated; every figure rendered and inspected)
- [x] Hypothesis verdicts → `RESEARCH_PHASE.md` §3.4 (H1–H4, done in Phases 2–3; unchanged)
- [x] Literature details located; reading list flagged: `docs/literature.md` (24 sources verified, 1 still to locate; **none read by the team yet**)
- [x] Report draft `docs/report.md` (claims checked against generated tables; 10 corrections before commit)
- [x] README reproduction instructions (README §14)
- [x] Data freeze commit + tag `data-freeze-v1`
- [x] (stretch) LD_PRELOAD shim + real application: `src/shim.c`, `src/sqlbench.c`, E9 (220 runs)
- [x] Python libraries installed (`.venv/`, `requirements.txt`) at the team's request

---

## Deviations from the original plan

| # | Deviation | Reason | Logged at |
|---|---|---|---|
| D1 | 10-week timeline compressed to one night | Team decision | 2026-10-14 21:45 |
| D2 | 5 runs (sweeps) / 10 runs (confirmatory) instead of 30 | Machine time | 2026-10-14 21:45 |
| D3 | Second machine and energy cut; real application is a stretch goal | Time | 2026-10-14 21:45 |
| D4 | SMT left on; no "different socket" condition | Needs root / single-socket machine | 2026-10-14 21:45 |
| D5 | Policy B uses Hedge with censored feedback (EXP3 optional) | Richer feedback is available; to be confirmed at Phase 1 review | 2026-10-14 21:45 |
| D6 | Context switches and CPU time from `getrusage`, not perf | perf not installed | 2026-10-14 22:00 |
| D7 | Spin-lock backoff cap 64 → 16 pauses | `pause` measured at 14 ns on this CPU | 2026-10-14 22:03 |
| D8 | Two validation criteria revised after the first run (work-loop tolerance 5% → 5% + 10 ns; context-switch check voluntary-only) | Timer uncertainty; involuntary switches come from other processes. Harness-validation criteria only, not hypothesis thresholds | 2026-10-14 22:11 |
| D9 | Drift covariates added to every bench run (Tctl before/after, post-run work rate) | Validation exposed 4–7% clock drop under sustained load | 2026-10-14 22:12 |
| D11 | Boost left on for all experiments | Team gave the Phase 2 go-ahead without disabling boost; drift covariates recorded, limitation stated | 2026-10-14 22:25 |
| D12 | Bootstrap resamples 2,000 instead of ≥ 10,000; order-statistic CIs for wake medians | Pure-Python analysis (numpy/scipy not installed) | 2026-10-14 22:28 |
| D13 | Run records stored as JSON lines (`runs.jsonl`) plus per-run files instead of one CSV | Nested per-phase data; analysis flattens to CSV/tables | 2026-10-14 22:28 |
| D14 | Phase 2 review questions resolved by the go-ahead "complete the phase 3": (1) per-thread / waiting-time-weighted latency added as **exploratory** analysis only; (2) boost stays **on** (same as Phase 2, so E6 static locks are comparable with E4/E5) | No change requested by the team | 2026-10-15 21:52 |
| D15 | Hedge cost normalisation changed after a tuning-set smoke run (range-normalised → shifted by the round minimum and divided by C) | Range normalisation made per-acquisition differences ~0.5% of the range; Hedge did not separate arms. Tuning set only (T = 4 steady); disclosed in §5.8 | 2026-10-15 22:11 |
| D16 | Harness additions for Phase 3: per-window slow-path counters, cgroup counters, per-thread tail quantiles, lock report (output only; one index comparison per op in the hot loop) | Needed for adaptation time series, H4 and the barging view. E6/E7 compare static and adaptive locks within one session, so the change applies to both sides | 2026-10-15 22:15 |
| D17 | Exploratory views added after seeing E6/E7 data: B*-fixed sensitivity for H3, runs with a starved thread, policy internals (arm shares, cost-model regret), `ta` detector counters, in-lock wake latency (E8) | Explain the confirmatory results (barging, B* switching, detector behaviour). Labelled exploratory; confirmatory computation unchanged | 2026-10-16 00:05 |
| D18 | Not done in Phase 3: wake-up latency under throttling (RQ1 condition), a per-window park-mode time metric, LD_PRELOAD stretch goal | Time / scope; listed in README §12.8 | 2026-10-16 00:09 |
| D19 | Python libraries (numpy, scipy, pandas, matplotlib) installed with pip into a project `.venv/` instead of pacman | sudo needs a password; pinned in `requirements.txt`. Phase 2/3 analysis stays stdlib-only. perf/strace/cpupower still not installed (need sudo) | 2026-10-16 22:56 |
| D20 | E9 first session stopped at run 2 (LD_PRELOAD split the checkout path at its space); 1 valid `native` run kept; resumed after a path fix | The sqlbench guard prevented any unshimmed run from being recorded as shimmed | 2026-10-16 22:58 |
| D21 | Figure 2 uses the pre-registered best-static rule (1% ties → lower p99); README §11.5 counts plain highest-throughput cells | Consistency with H2/H3 definitions; both counts reported | 2026-10-16 23:10 |
| D22 | Related work in the report is a skeleton: bibliographic details verified, no content claims until the team reads each source | Integrity rule, RESEARCH_PHASE §4 | 2026-10-16 23:14 |
| D10 | Pilot data seen before pre-registration (validation and smoke tests) | Needed to validate the harness; disclosed in README §10.5. Thresholds in TIMELINE §5 predate it | 2026-10-14 22:05 |
| D23 | Documentation reorganised; the 11 `results/*-console.log` files moved to `results/logs/` (`git mv`, contents untouched). **One-time exception to the append-only rule for raw data** (a rename only; nothing in scripts, Makefile or docs read these paths) | Clean repository root for GitHub | 2026-10-17 21:40 |

## Log

| Time | Event |
|---|---|
| 21:43 | Machine checked: Ryzen 7 6800H, kernel 7.2.5, glibc 2.44, cgroup v2 with cpu delegated to user, governor performance |
| 21:45 | Plan written (`TIMELINE.md`, `PROGRESS.md`); waiting for go-ahead |
| 21:55 | Go-ahead received for Phase 1 ("done"); TIMELINE §5 hypothesis decisions still to be confirmed at review; git init |
| 22:00 | Locks + correctness test: 18/18 pass; TSan 18/18 pass, 0 warnings |
| 22:03 | calib: TSC 3.194 GHz, stamp pair 20 ns, pause 14 ns, futex_wake (no waiter) 295 ns, TSC consistent across CPUs |
| 22:05 | Harness + wakebench smoke tests OK; pilot observation: barging/unfairness for stp:2000 at 20 µs holds |
| 22:10 | Validation run 1: crashed at the wakebench check (script bug) after two FAILs (work-loop tolerance, spin context switches) |
| 22:11 | Validation run 2: 13/14 — stp:1000 repeatability CV 7.2% (monotonic throughput decline across runs) |
| 22:13 | Drift covariates added; validation run 3: 15/15 pass; drift −4…−7% per run, Tctl 65→70 °C |
| 22:15 | README written; Phase 1 committed; awaiting review |
| 22:25 | Phase 2 go-ahead (TIMELINE §5 decisions approved as written); boost still on; packages not installed |
| 22:28 | Pre-registration committed and tagged `prereg-v1` (git tagger date 22:28:12; the tag message says "22:35", an estimate made while writing it; git's date is authoritative) |
| 22:28:18 | E1 first run started (first experiment data; after the tag) |
| 22:33 | Clarification C1 (H2 OR-rule × inconclusive rule) added to RESEARCH_PHASE §6.1; analysis scripts written |
| 22:48 | E1 done: 42 runs, 0 invalid, 20.6 min |
| 22:49 | Budget rule applied: reference median 4728.9 ns → stp:2350/4750/9450/37850 (config/budgets.json) |
| 22:49 | E1 analysed: **H1 SUPPORTED** (ratio 11.27, CI 11.18–11.37; worst-case run ratio 9.59) |
| 22:50 | Committed a5ccb55 (E1 data, budgets, analysis, C1); E2→E5 chain started |
| 22:52 | Committed a4e233c (analysis-only: E3 pinned-vs-unpinned table) so the runner's clean-code check passes for E3–E5 |
| 23:17 | E2 done: 640 runs, 0 invalid, 26.8 min |
| 23:21 | E3 done: 96 runs, 0 invalid, 4.0 min |
| 23:47 | E4 done: 320 runs, 0 invalid, 26.7 min |
| 23:56 | E5 done: 160 runs, 0 invalid, 9.4 min |
| 23:58 | Analyses run: **H2 PARTIALLY SUPPORTED** (2/4 cases). Barging artefact in long-hold p99 identified (Jain 0.33–0.54 for futex locks); verdict kept as pre-registered |
| 23:59 | README / RESEARCH_PHASE §3.4 / PROGRESS updated (claims re-checked against data; 4 wording fixes); Phase 2 committed; awaiting review |
| **15 Oct** | |
| 21:52 | Phase 3 go-ahead ("complete the phase 3"). Machine freshly rebooted (load 0.5), boost on |
| 22:09 | Adaptive locks built: `ada`, `hedge`, `exp3`, `ta` (`src/policy.c`, `src/lock_adaptive.c`, `src/cgroup.c`); 39/39 correctness, TSan clean |
| 22:10 | `calib policy`: choose / update = ada 0.3 / 14.7 ns, hedge 10.5 / 27.9 ns, exp3 10.5 / 18.4 ns (off the critical section). Uncontended lock+unlock: park 2.87 ns, adaptive 3.15–3.36 ns |
| 22:11 | Tuning-set smoke run (T = 4, hold 1 µs): Hedge did not separate arms → normalisation fixed (D15); re-tested 39/39, TSan clean |
| 22:13 | Throttled-launcher mechanism check (T = 8, 100% quota, not an H4 case): counters recorded, `ta` forced 100% of slow paths; disclosed in §5.8 |
| 22:15 | Phase 3 protocol (RESEARCH_PHASE §5.8, C2) written; committed `7df4987` (22:15:45) before T3 |
| 22:15:50 | T3 started (first Phase 3 data) |
| 22:29 | T3 done: 320 runs, 0 invalid, 13.4 min. Rule applied: ada β = 8 (4/4 tuning holds within the H3 bounds), hedge β = 8 (2/4: p99.9 6.3× at 1 µs, throughput 0.91× at 10 µs), ta base = ada |
| 22:29:46 | `config/policy.json` committed (`d9a009b`), tagged `prereg-v1-p3` |
| 22:31 | E6/E7 analysis dry-run on a miniature scratch dataset (2 runs, phases ÷ 10; not research data) found one bug (E7 per-second columns assumed 2 s); fixed, committed `7744476` (analysis only) |
| 22:32:09 | E6 started (first H3 data), chain E6 → E7 → E8 |
| 23:26 | E6 done: 720 runs, 0 invalid, 54.1 min; E7 started 23:26:18 |
| 23:49 | E7 done: 550 runs, 0 invalid, 23.2 min |
| **16 Oct** | |
| 00:01 | E8 done: 288 runs, 0 invalid, 12.1 min. Overheads recorded (`results/overhead/`, 3 repeats) |
| 00:03 | Analyses run: **H3 PARTIALLY SUPPORTED** for ada (1 met / 3 not met / 2 inconclusive) and hedge (3 / 1 / 2); **H4 PARTIALLY SUPPORTED** (2/4: met at 1 µs holds, not met at 10 µs) |
| 00:05 | Exploratory views added (D17); starvation verified from raw per-thread counts (all in S1's 20 µs phase; E7 10 µs holds) |
| 00:09 | README §12, RESEARCH_PHASE §3.4, PROGRESS updated; claims checked against the generated tables (15 wording fixes before commit, incl. one wrong claim about Hedge's per-phase behaviour, found after fixing a per-phase budget bug in the analysis); Phase 3 committed; awaiting review |
| 22:51 | Phase 4 go-ahead ("complete Phase 4"). matplotlib/numpy not installed; SQLite headers present |
| 22:55 | LD_PRELOAD shim and SQLite benchmark built; all 8 lock specs pass SUM(v) = #UPDATE under the shim (smoke runs, not data) |
| 22:56 | Team asked to install all libraries: sudo needs a password → numpy, scipy, pandas, matplotlib installed into `.venv/` with pip; `requirements.txt` pinned (D19) |
| 22:57:35 | E9 declared (RESEARCH_PHASE §5.9) and committed `651e8c2` before any E9 data |
| 22:57:41 | E9 session 1: run 2 failed 3× (LD_PRELOAD path with a space); 1 native run kept (D20). Fix committed `1e4516f` 22:58:31 |
| 22:58:43 | E9 resumed: 219 runs, 0 invalid, 9.2 min. Literature searches during the run (Crossref, publisher pages) |
| 23:01 | `docs/literature.md` written: 24 sources verified, gap-check leads (kernel adaptive-futex threads 2010/2014/2024) |
| 23:08 | Supplementary tests run: all directions agree with the pre-registered verdicts |
| 23:10 | Figures generated, rendered to PNG and inspected; layout fixes (label overflow, legends over data, colliding end labels) |
| 23:14 | Report draft written; 10 claims corrected against the generated tables before commit |
| 23:15 | All analyses regenerated from raw data: every committed Phase 2–3 output byte-identical (reproducibility check) |
| 23:18 | README §13–14, PROGRESS updated; Phase 4 committed; tag `data-freeze-v1` |
