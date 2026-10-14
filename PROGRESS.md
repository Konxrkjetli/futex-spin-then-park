# PROGRESS.md

Live tracker for the one-night plan in `TIMELINE.md`. Update after each task. Times are IST.

**Current phase:** Phase 2 complete, awaiting review before Phase 3
**Results status:** H1 SUPPORTED, H2 PARTIALLY SUPPORTED (Phase 2). H3, H4 pending (Phase 3).

---

## Phase status

| Phase | Window | Status | Started | Finished |
|---|---|---|---|---|
| 1. Foundation | 22:00 – 01:00 | **Done** (awaiting review) | 21:55 | 22:15 |
| 2. Pre-registration + static experiments | 01:00 – 03:30 | **Done** (awaiting review) | 22:25 | 23:59 |
| 3. Adaptive + throttling | 03:30 – 06:30 | Not started | | |
| 4. Analysis + write-up | 06:30 – 09:30 | Not started | | |

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

- [ ] Policy A (estimate-and-set)
- [ ] Policy B (Hedge, censored feedback)
- [ ] (optional) EXP3 variant
- [ ] Adaptive locks: counter test + TSan
- [ ] Policy overhead measured
- [ ] Adaptive locks on steady / phase-changing / randomized workloads
- [ ] Throttle-aware variant
- [ ] Throttled runs (H4)
- [ ] Data committed

## Phase 4: Analysis + write-up

- [ ] Analysis scripts (bootstrap CIs, tests, Jain's index, regret)
- [ ] Figures 1–10
- [ ] Hypothesis verdicts → `RESEARCH_PHASE.md` §3.4
- [ ] Literature details located; reading list flagged
- [ ] Report draft `docs/report.md`
- [ ] README reproduction instructions
- [ ] Data freeze commit + tag
- [ ] (stretch) LD_PRELOAD shim + real application

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
| D10 | Pilot data seen before pre-registration (validation and smoke tests) | Needed to validate the harness; disclosed in README §10.5. Thresholds in TIMELINE §5 predate it | 2026-10-14 22:05 |

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
