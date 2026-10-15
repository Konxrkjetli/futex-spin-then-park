/* Adaptive spin-then-park locks (Phase 3): the three-state futex lock of
 * lock_futex.c with the spin budget chosen per slow path by a policy
 * (policy.h). lock_futex.c is left untouched so the static locks run exactly
 * the code measured in Phase 2.
 *
 *   ada     Policy A, estimate-and-set
 *   hedge   Policy B, Hedge with counterfactual ("censored") feedback
 *   exp3    EXP3 over the same arms (bandit feedback only)
 *   ta      throttle-aware: a base policy (ada or hedge) whose budget is
 *           forced to 0 while cgroup CPU throttling is recent or imminent
 *
 * Differences from the static lock, all off the uncontended fast path:
 * - Slow path: the policy picks the budget (a TLS load for ada; one random
 *   draw over K arms for hedge/exp3) and the outcome is recorded.
 * - Unlock with waiters: after releasing the word, the releaser stamps the
 *   TSC into rel_tsc just before FUTEX_WAKE. A woken waiter subtracts it to
 *   get one wake-latency sample, the quantity Policy A estimates.
 * - The policy update (EWMA, Hedge weights) runs in unlock *after* the
 *   release, so it never lengthens the critical section. */

#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <stdalign.h>
#include <stdatomic.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "cgroup.h"
#include "common.h"
#include "futex.h"
#include "lock.h"
#include "policy.h"
#include "tsc.h"

struct ta_helper;

struct ada_lock {
    alignas(PAD_BYTES) _Atomic uint32_t word;
    alignas(PAD_BYTES) _Atomic uint64_t rel_tsc;      /* written by releasers that wake */
    alignas(CACHELINE) _Atomic uint64_t park_until;   /* ta: park mode until this TSC */
    alignas(PAD_BYTES) struct policy_cfg cfg;         /* read-only after init */
    struct ta_helper *ta;
};

/* Per-thread policy state for the lock this thread last contended on. */
static __thread struct pol_state pst;

static void ada_lock(void *p)
{
    struct ada_lock *l = p;
    uint32_t c = 0;

    if (likely(atomic_compare_exchange_strong_explicit(&l->word, &c, 1,
                                                       memory_order_acquire,
                                                       memory_order_relaxed)))
        return;
    lk_stats.slow++;

    struct pol_state *s = &pst;
    if (unlikely(s->owner != l))
        pol_init(s, &l->cfg, l);
    const uint64_t t0 = tsc_now();
    int arm;
    uint64_t budget = pol_choose(s, &arm);
    if (s->cfg.ta && t0 < atomic_load_explicit(&l->park_until, memory_order_relaxed)) {
        budget = 0;
        arm = s->cfg.kind == POL_A ? -1 : 0;   /* arms_ns[0] == 0 */
        lk_stats.forced++;
    }
    lk_stats.budget_tsc += budget;
    if (arm >= 0)
        lk_stats.arm_n[arm]++;

    struct pol_obs *o = &s->obs;
    o->arm = arm;
    o->b_ns = arm >= 0 ? s->cfg.arms_ns[arm] : tsc_to_ns(budget);
    o->woke = false;
    o->spun = true;

    if (budget) {
        uint64_t now, deadline = t0 + budget;
        do {
            cpu_relax();
            c = atomic_load_explicit(&l->word, memory_order_relaxed);
            if (c == 0 &&
                atomic_compare_exchange_weak_explicit(&l->word, &c, 1,
                                                      memory_order_acquire,
                                                      memory_order_relaxed)) {
                now = tsc_now();
                lk_stats.spin_acq++;
                lk_stats.spin_tsc += now - t0;
                o->w_ns = tsc_to_ns(now - t0);
                s->pending = true;
                return;
            }
            now = tsc_now();
        } while (now < deadline);
        lk_stats.spin_tsc += now - t0;
    }

    /* Park, as in lock_futex.c, noting the release that let us in. */
    const uint64_t tpark = tsc_now();
    uint64_t rel = 0, wake = 0;
    c = atomic_exchange_explicit(&l->word, 2, memory_order_acquire);
    while (c != 0) {
        o->spun = false;
        lk_stats.parks++;
        long r = futex_wait(&l->word, 2);
        if (r == 0) {
            uint64_t now = tsc_now();
            uint64_t rs = atomic_load_explicit(&l->rel_tsc, memory_order_relaxed);
            if (rs >= tpark && rs <= now) {
                rel = rs;
                wake = now - rs;
            } else {
                rel = 0;
            }
        }
        c = atomic_exchange_explicit(&l->word, 2, memory_order_acquire);
    }
    const uint64_t t1 = tsc_now();
    if (rel) {
        o->woke = true;
        o->wake_ns = tsc_to_ns(wake);
        o->w_ns = tsc_to_ns(rel - t0);
        lk_stats.wake_n++;
        lk_stats.wake_tsc += wake;
    } else {
        /* Never slept (the word changed under every FUTEX_WAIT), or no usable
         * stamp: the time to acquisition is the best estimate. */
        o->w_ns = tsc_to_ns(t1 - t0);
    }
    s->pending = true;
}

static void ada_unlock(void *p)
{
    struct ada_lock *l = p;

    if (atomic_fetch_sub_explicit(&l->word, 1, memory_order_release) != 1) {
        atomic_store_explicit(&l->word, 0, memory_order_release);
        atomic_store_explicit(&l->rel_tsc, tsc_now(), memory_order_relaxed);
        lk_stats.wakes++;
        futex_wake(&l->word, 1);
    }
    /* Off the critical section: the lock is already released. */
    if (pst.pending) {
        pst.pending = false;
        pol_update(&pst, &pst.obs);
    }
}

/* ---- throttle-aware helper ----------------------------------------------
 *
 * One helper thread per "ta" lock polls the process's own cgroup. With no CPU
 * quota (cpu.max = "max") it only re-checks cpu.max every 100 ms. With a
 * quota it reads cpu.stat every poll_us and triggers park mode when
 *   - nr_throttled increased (throttling is recent), or
 *   - the group's CPU usage over the last poll interval reached
 *     theta x quota/period (throttling is imminent).
 * Park mode lasts `hold` quota periods. A trigger during park mode extends
 * it (parking did not prevent it, so spinning would only make it worse). A
 * trigger within one period after park mode ended means the probe back into
 * spinning failed, so `hold` doubles (up to hold_max); a later trigger starts
 * again from hold_min. Waiters read park_until once per slow path. */

struct ta_helper {
    pthread_t th;
    struct ada_lock *l;
    _Atomic int stop;
    char dir[512];
    /* Written by the helper, read by report() after the run. */
    _Atomic long long quota_us, period_us;
    _Atomic uint64_t polls, triggers, events, imminent, backoffs, park_tsc, hold_peak;
};

static void sleep_ns(double ns)
{
    struct timespec d = { (time_t)(ns / 1e9), (long)fmod(ns, 1e9) };
    while (clock_nanosleep(CLOCK_MONOTONIC, 0, &d, &d) == EINTR)
        ;
}

static void *ta_main(void *arg)
{
    struct ta_helper *h = arg;
    const struct policy_cfg *cfg = &h->l->cfg;
    long long quota = -1, period = 100000;
    uint64_t period_tsc = 0, until = 0, prev_t = 0;
    int hold = cfg->hold_min, fd = -1;
    struct cg_stat prev = { 0 }, cur;
    bool have_prev = false;

    while (!atomic_load_explicit(&h->stop, memory_order_relaxed)) {
        if (quota <= 0) {
            if (cg_read_max(h->dir, &quota, &period) != 0 || quota <= 0 || period <= 0) {
                quota = -1;
                for (int i = 0; i < 10 && !atomic_load(&h->stop); i++)
                    sleep_ns(10e6);
                continue;
            }
            if (fd < 0 && (fd = cg_open_stat(h->dir)) < 0) {
                quota = -1;
                sleep_ns(100e6);
                continue;
            }
            period_tsc = ns_to_tsc((double)period * 1e3);
            atomic_store(&h->quota_us, quota);
            atomic_store(&h->period_us, period);
            have_prev = false;
        }
        sleep_ns(cfg->poll_us * 1e3);
        if (cg_read_stat_fd(fd, &cur) != 0)
            continue;
        const uint64_t now = tsc_now();
        atomic_fetch_add_explicit(&h->polls, 1, memory_order_relaxed);
        if (have_prev) {
            if (now < until)
                atomic_fetch_add_explicit(&h->park_tsc, now - prev_t, memory_order_relaxed);
            const double dt_us = tsc_to_ns(now - prev_t) / 1e3;
            const double rate = (double)(cur.usage_usec - prev.usage_usec) / dt_us;
            const bool event = cur.nr_throttled > prev.nr_throttled;
            const bool soon = rate >= cfg->theta * (double)quota / (double)period;
            if (event || soon) {
                if (now < until) {
                    if (now + (uint64_t)hold * period_tsc > until)
                        until = now + (uint64_t)hold * period_tsc;
                } else if (until && now < until + period_tsc) {
                    hold = hold * 2 > cfg->hold_max ? cfg->hold_max : hold * 2;
                    atomic_fetch_add_explicit(&h->backoffs, 1, memory_order_relaxed);
                    until = now + (uint64_t)hold * period_tsc;
                } else {
                    hold = cfg->hold_min;
                    until = now + (uint64_t)hold * period_tsc;
                }
                if ((uint64_t)hold > atomic_load(&h->hold_peak))
                    atomic_store(&h->hold_peak, (uint64_t)hold);
                atomic_fetch_add_explicit(&h->triggers, 1, memory_order_relaxed);
                atomic_fetch_add_explicit(event ? &h->events : &h->imminent, 1, memory_order_relaxed);
                atomic_store_explicit(&h->l->park_until, until, memory_order_relaxed);
            }
        }
        prev = cur;
        prev_t = now;
        have_prev = true;
    }
    if (fd >= 0)
        close(fd);
    return NULL;
}

/* ---- lock_ops -------------------------------------------------------------- */

static void ada_init(void *p, const struct lock_params *lp)
{
    struct ada_lock *l = p;
    atomic_init(&l->word, 0);
    atomic_init(&l->rel_tsc, 0);
    atomic_init(&l->park_until, 0);
    l->cfg = lp->pol;
    l->ta = NULL;
    if (!l->cfg.ta)
        return;
    struct ta_helper *h = calloc(1, sizeof *h);
    if (!h)
        die("allocation failed");
    h->l = l;
    atomic_init(&h->quota_us, -1);
    if (cg_self_dir(h->dir, sizeof h->dir) != 0)
        die("ta: cannot find this process's cgroup");
    if (pthread_create(&h->th, NULL, ta_main, h) != 0)
        die("ta: pthread_create failed");
    l->ta = h;
}

static void ada_destroy(void *p)
{
    struct ada_lock *l = p;
    if (l->ta) {
        atomic_store(&l->ta->stop, 1);
        pthread_join(l->ta->th, NULL);
        free(l->ta);
        l->ta = NULL;
    }
}

static void ada_report(void *p, FILE *f)
{
    struct ada_lock *l = p;
    char buf[1024];
    pol_format(&l->cfg, buf, sizeof buf);
    fprintf(f, "{\"policy\":%s", buf);
    if (l->ta) {
        struct ta_helper *h = l->ta;
        fprintf(f, ",\"ta\":{\"quota_us\":%lld,\"period_us\":%lld,\"polls\":%llu,\"triggers\":%llu,"
                "\"throttle_events\":%llu,\"imminent\":%llu,\"backoffs\":%llu,\"hold_peak\":%llu,"
                "\"park_ms\":%.1f}",
                atomic_load(&h->quota_us), atomic_load(&h->period_us),
                (unsigned long long)atomic_load(&h->polls), (unsigned long long)atomic_load(&h->triggers),
                (unsigned long long)atomic_load(&h->events), (unsigned long long)atomic_load(&h->imminent),
                (unsigned long long)atomic_load(&h->backoffs), (unsigned long long)atomic_load(&h->hold_peak),
                tsc_to_ns(atomic_load(&h->park_tsc)) / 1e6);
    }
    fputc('}', f);
}

static int parse_kind(const char *arg, struct lock_params *p, enum pol_kind kind, bool ta)
{
    memset(p, 0, sizeof *p);
    pol_default(&p->pol, kind);
    p->pol.ta = ta;
    return pol_parse(arg, &p->pol);
}

static int ada_parse(const char *a, struct lock_params *p) { return parse_kind(a, p, POL_A, false); }
static int hedge_parse(const char *a, struct lock_params *p) { return parse_kind(a, p, POL_HEDGE, false); }
static int exp3_parse(const char *a, struct lock_params *p) { return parse_kind(a, p, POL_EXP3, false); }
static int ta_parse(const char *a, struct lock_params *p) { return parse_kind(a, p, POL_HEDGE, true); }

#define ADA_OPS(id, nm, parser)                                                     \
    const struct lock_ops id = {                                                    \
        .name = nm, .arg_name = "key=value,...", .parse = parser,                   \
        .size = sizeof(struct ada_lock), .init = ada_init, .lock = ada_lock,        \
        .unlock = ada_unlock, .destroy = ada_destroy, .report = ada_report,         \
    }

ADA_OPS(ada_ops, "ada", ada_parse);
ADA_OPS(hedge_ops, "hedge", hedge_parse);
ADA_OPS(exp3_ops, "exp3", exp3_parse);
ADA_OPS(ta_ops, "ta", ta_parse);
