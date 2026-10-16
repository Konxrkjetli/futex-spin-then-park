# Literature: verified bibliographic details and reading list

Phase 4, 2026-10-16. This file implements `RESEARCH_PHASE.md` §4.

> **Integrity rule.** Every entry below has been **located**, and its
> bibliographic details (authors, title, venue, year, pages, DOI) were checked
> against a primary or registry source (Crossref, the publisher's page, or the
> authors' institutional page), listed under "verified against".
> **None of these papers has been read by the team.** The "relevant for"
> column says why a source is on the list; it is *not* a claim about what the
> paper says. Before the report states what a source found, a team member
> must read it, and then tick "read" here. The one-line notes come from
> abstracts or publisher pages and are there to help prioritise reading,
> nothing more.

## 1. Sources from the original candidate list (§4.1)

| # | Reference (verified) | Verified against | Relevant for | Read by team |
|---|---|---|---|---|
| L1 | Ulrich Drepper. *Futexes Are Tricky.* Red Hat white paper. Several revisions: June 2004, January 2008, v1.6 2011 (cite the revision actually read). | Copies hosted at unicamp.br and labri.fr; Wikipedia's "Futex" article cites v1.6 (2011) | Three-state futex lock ("mutex3") used by `src/lock_futex.c` and `src/lock_adaptive.c`; lost-wake-up reasoning | ☐ |
| L2 | Hubertus Franke, Rusty Russell, Matthew Kirkwood. *Fuss, Futexes and Furwocks: Fast Userlevel Locking in Linux.* Proc. Ottawa Linux Symposium 2002, pp. 479–495. | kernel.org/doc/ols/2002/ols2002-pages-479-495.pdf; futex(7) man page | Origin and design of futexes | ☐ |
| L3 | Linux man-pages: `futex(2)`, `futex(7)`, `pthread_mutexattr_settype(3)`; Linux kernel documentation: *CFS Bandwidth Control* (`Documentation/scheduler/sched-bwc.rst`) and *Control Group v2* (`Documentation/admin-guide/cgroup-v2.rst`, `cpu.max`, `cpu.stat`). | docs.kernel.org/scheduler/sched-bwc.html (the page itself points to cgroup-v2.rst for the v2 interface) | Interface semantics: quota and period, `nr_throttled`, `throttled_usec` | ☐ |
| L4 | Anna R. Karlin, Kai Li, Mark S. Manasse, Susan Owicki. *Empirical Studies of Competitive Spinning for a Shared-Memory Multiprocessor.* Proc. 13th ACM SOSP, 1991, pp. 41–55. DOI 10.1145/121132.286599 (also ACM SIGOPS OSR, DOI 10.1145/121133.286599). Princeton TR-319-91 is an earlier version. | Crossref; Princeton CS tech-report page | Spin-then-block strategies, ski-rental framing, adaptive vs non-adaptive spinning: the closest classic prior work to Policy A | ☐ |
| L5 | Hugo Guiroux, Renaud Lachaize, Vivien Quéma. *Multicore Locks: The Case Is Not Closed Yet.* USENIX ATC 2016, pp. 649–662. | usenix.org ATC '16 presentation page; HAL hal-01486527 | Lock comparison methodology on real applications; interposition (LD_PRELOAD) approach like our shim | ☐ |
| L6 | Rachid Guerraoui, Hugo Guiroux, Renaud Lachaize. *Lock–Unlock: Is That All? A Pragmatic Analysis of Locking in Software Systems.* ACM Transactions on Computer Systems, 2019. (Volume and issue not yet checked against ACM DL.) | EPFL Infoscience record 266761; HAL hal-02084060 | Follow-up of L5; tail latency and the wider lock API (trylock, condition variables), which our shim does not support | ☐ |
| L7 | Tudor David, Rachid Guerraoui, Vasileios Trigonakis. *Everything You Always Wanted to Know About Synchronization but Were Afraid to Ask.* Proc. 24th ACM SOSP, 2013. DOI 10.1145/2517349.2522714. | EPFL Infoscience record 199104; SOSP 2013 program | Hardware cost of synchronization (cache-line transfer, SMT) | ☐ |
| L8 | Babak Falsafi, Rachid Guerraoui, Javier Picorel, Vasileios Trigonakis. *Unlocking Energy.* USENIX ATC 2016, pp. 393–406. | usenix.org ATC '16 page; EPFL Infoscience 221135 | Energy of spinning vs sleeping (energy was cut from this study); its MUTEXEE design is a spin-then-park futex mutex | ☐ |
| L9 | John M. Mellor-Crummey, Michael L. Scott. *Algorithms for Scalable Synchronization on Shared-Memory Multiprocessors.* ACM Transactions on Computer Systems 9(1):21–65, February 1991. DOI 10.1145/103727.103729. | Crossref | Queue locks and fairness, context for the barging/starvation finding | ☐ |
| L10 | Peter Auer, Nicolò Cesa-Bianchi, Yoav Freund, Robert E. Schapire. *The Nonstochastic Multiarmed Bandit Problem.* SIAM Journal on Computing 32(1):48–77, 2002. DOI 10.1137/S0097539701398375. | Crossref | EXP3 and its regret bound (our `exp3` lock and its parameter formulas) | ☐ |
| L11 | Yoav Freund, Robert E. Schapire. *A Decision-Theoretic Generalization of On-Line Learning and an Application to Boosting.* Journal of Computer and System Sciences 55(1):119–139, 1997. DOI 10.1006/jcss.1997.1504. | doi.org link; Princeton research portal | Hedge (our Policy B) and its learning-rate choice | ☐ |
| L12 | Allan Borodin, Ran El-Yaniv. *Online Computation and Competitive Analysis.* Cambridge University Press, 1998 (paperback 2005, ISBN 9780521619462). | Cambridge University Press catalogue; Technion book page; library record (1998) | Ski rental and competitive analysis | ☐ |
| L13 | Tor Lattimore, Csaba Szepesvári. *Bandit Algorithms.* Cambridge University Press, 2020. DOI 10.1017/9781108571401. A free online edition may exist on the authors' site (not yet confirmed). | Cambridge Core listing and front matter | Regret, adversarial and non-stationary bandits | ☐ |
| L14 | Remzi H. Arpaci-Dusseau, Andrea C. Arpaci-Dusseau. *Operating Systems: Three Easy Pieces.* Arpaci-Dusseau Books (free online at ostep.org). Chapter number of "Locks" (believed 28) to be checked on ostep.org. | Publisher listing; course reading lists | Background on locks, two-phase locks, futexes | ☐ |
| L15 | Todd Mytkowicz, Amer Diwan, Matthias Hauswirth, Peter F. Sweeney. *Producing Wrong Data Without Doing Anything Obviously Wrong!* Proc. ASPLOS 2009, pp. 265–276. | USI project page (sape.inf.usi.ch/publications/asplos09) | Measurement bias, setup randomisation (we randomise run order) | ☐ |
| L16 | Torsten Hoefler, Roberto Belli. *Scientific Benchmarking of Parallel Computing Systems: Twelve Ways to Tell the Masses When Reporting Performance Results.* Proc. SC '15, pp. 1–12. DOI 10.1145/2807591.2807644. | Crossref | Reporting rules: CIs, non-parametric tests, variance | ☐ |
| L17 | Gil Tene. *How NOT to Measure Latency* (talk; coordinated omission). | Not yet located as a citable primary source; find a recorded version or the HdrHistogram documentation | Our closed-loop harness does not suffer from coordinated omission in the usual sense, but the report should say why | ☐ |

## 2. Sources found by the §4.2 searches (gap check)

| # | Reference (verified) | Verified against | Relevant for | Read by team |
|---|---|---|---|---|
| G1 | Beng-Hong Lim, Anant Agarwal. *Reactive Synchronization Algorithms for Multiprocessors.* Proc. ASPLOS VI, 1994, pp. 25–35 (in ACM SIGPLAN Notices 29(11)). DOI 10.1145/195470.195490. | Crossref | Switching between synchronization protocols online by contention: prior work on *adaptive* locks that the novelty claim must be distinguished from | ☐ |
| G2 | Dave Dice. *Malthusian Locks.* Proc. EuroSys 2017. DOI 10.1145/3064176.3064203; extended version arXiv:1511.06035. | arXiv record (states the DOI) | Concurrency restriction; relevant to our starved-thread finding | ☐ |
| G3 | Yuvraj Patel, Leon Yang, Leo Arulraj, Andrea C. Arpaci-Dusseau, Remzi H. Arpaci-Dusseau, Michael M. Swift. *Avoiding Scheduler Subversion using Scheduler-Cooperative Locks.* Proc. EuroSys 2020. DOI 10.1145/3342195.3387521. | NSF PAR record; unpaywall | Lock usage vs scheduler goals; lock-usage fairness (our Jain / starvation view) | ☐ |
| G4 | Aurélien Garivier, Eric Moulines. *On Upper-Confidence Bound Policies for Switching Bandit Problems.* Proc. ALT 2011, LNCS, pp. 174–188. DOI 10.1007/978-3-642-24412-4_16; preprint arXiv:0805.3415. | mlanthology ALT 2011 record; arXiv | Discounted / sliding-window bandits (our discounted Hedge) | ☐ |
| G5 | Volkmar Uhlig, Joshua LeVasseur, Espen Skoglund, Uwe Dannowski. *Towards Scalable Multiprocessor Virtual Machines.* Proc. 3rd USENIX VM Research and Technology Symposium (VM '04), 2004, pp. 43–56. | usenix.org VM '04 page; KIT project page | Lock-holder preemption: the closest established concept to "throttled holder" | ☐ |
| G6 | Odin Ugedal (with co-authors; author list to be checked). *Mitigating Unnecessary Throttling in Linux CFS Bandwidth Control.* SBAC-PAD 2022. | Author-hosted PDF (rakeshk.folk.ntnu.no/pubs/SBACPAD22.pdf) | CFS bandwidth throttling behaviour and period length | ☐ |
| G7 | Linux kernel mailing-list threads on adaptive futex spinning: (a) Darren Hart, "[PATCH] futex: Add FUTEX_LOCK with optional adaptive spinning", LKML, April 2010 (forward port of a Peter Zijlstra FUTEX_WAIT_ADAPTIVE proposal); (b) Waiman Long, "futex: introduce an optimistic spinning futex", 2014 (LWN article 606051); (c) André Almeida, "[RFC PATCH 0/1] Add FUTEX_SPIN operation", LKML, April 2024. | lkml.org / lkml.iu.edu archives; lwn.net/Articles/606051 | **The kernel discussion the original overview mentioned.** All three spin while the lock *owner is running*, which needs owner information that our user-space locks do not have. Status (merged or not) not yet checked | ☐ |
| G8 | "sched/fair: Defer CFS throttling to exit to user mode" RFC patch series, LKML, February 2025; and the Linux Plumbers Conference 2024 talk *Priority Inheritance for CFS Bandwidth Control*. | lkml.iu.edu archive; lpc.events slides | Throttled lock holders inside the kernel; the kernel-side counterpart of our H4 question | ☐ |

## 3. What the searches say about the gap (§1.1), and what is still open

These are leads, not conclusions; none of the sources has been read.

1. **Adaptive spin-then-block is old** (L4, 1991; G1, 1994). The project must
   not claim adaptive spinning as new. Policy A is essentially the classic
   rule with a measured blocking cost.
2. **Owner-aware adaptive spinning is the kernel's answer** (G7, 2010–2024).
   A user-space lock without owner-run-state information is a different
   setting; that difference is a candidate for the paper's framing.
3. **No source found yet uses an online-learning (bandit / Hedge) policy for
   spin budgets**, or targets cgroup CPU-quota throttling from user space.
   Two searches are not a literature review. Before claiming novelty, the
   team should search the ACM DL, IEEE Xplore and Google Scholar for:
   "adaptive mutex" AND (learning OR bandit), "spin-then-park" OR
   "spin-then-block" AND adaptive, "lock-holder preemption" AND (container OR
   cgroup OR quota), "CPU throttling" AND lock, "competitive spinning" (papers
   citing L4).
4. **Barging and starvation of futex locks** (our main exploratory finding)
   is likely discussed in L5/L6, L9, G2 and G3. Read them before presenting
   it as a finding rather than a confirmation.

## 4. Reading priority for the team

1. L4 (Karlin et al.), G1 (Lim & Agarwal), G7 (kernel threads): they decide
   how the contribution must be framed.
2. L1 (Drepper): confirm that our lock is mutex3 as described.
3. L5, L6, G2, G3: barging, fairness and lock comparison methodology.
4. L10, L11, G4, L13: before writing any regret statement.
5. L3 (kernel docs), G5, G6, G8: throttling and lock-holder preemption.
6. L7, L8, L14–L17: background and methodology.
