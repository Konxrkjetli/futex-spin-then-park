#ifndef FL_POLICY_H
#define FL_POLICY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Spin-budget policies for the adaptive spin-then-park lock (Phase 3).
 *
 * Shared cost model (ski rental, BUILD_PHASE.md 5.4). A waiter finds the lock
 * held at t0 and would get it by spinning after w ns. With spin budget b it
 * pays
 *     cost(b) = w        if w <= b   (spun until the lock came free)
 *             = b + C    if w >  b   (spun b, then paid the cost of blocking)
 * with C = beta * W_hat, where W_hat is the thread's running estimate (EWMA)
 * of the futex wake-up latency measured inside the lock: the releaser stamps
 * the TSC just before FUTEX_WAKE, the woken waiter subtracts it on return.
 * beta scales the measured wake latency into the full cost of a park (the
 * releaser's FUTEX_WAKE, the lost turn, cache refill); beta = 1 is the
 * textbook rule "spin for as long as a block costs".
 *
 *   ada    Policy A, estimate-and-set: b = clamp(C, 0, largest arm).
 *   hedge  Policy B, Hedge over K budgets ("arms") with discounted
 *          cumulative cost (horizon N acquisitions) for non-stationarity.
 *          Each round's costs are shifted by their minimum (Hedge is
 *          invariant to a common shift) and divided by C, clipped at 1, so
 *          differences are measured in units of the blocking cost.
 *          Feedback is the whole counterfactual cost vector. It is exact when
 *          the waiter acquired by spinning. When it parked, arms <= its
 *          budget cost b + C, and longer arms are imputed from the release
 *          that let it in (w_est = release stamp - t0), an upper bound on the
 *          wait a spinner would have seen ("censored" feedback).
 *   exp3   Same arms and cost, but only the chosen arm's cost is used
 *          (importance-weighted bandit feedback, cost / 2C clipped at 1).
 *          Shows what the counterfactual feedback is worth.
 *
 * All state is per thread and per lock (re-initialised when a thread moves to
 * another lock), so the policies add no shared writes. */

#define POL_MAX_ARMS 8

enum pol_kind { POL_A, POL_HEDGE, POL_EXP3 };

struct policy_cfg {
    enum pol_kind kind;
    double beta;        /* blocking cost C = beta * W_hat */
    double w0_ns;       /* prior for W_hat */
    double alpha;       /* EWMA weight of a new wake-latency sample */
    double wcap_ns;     /* a single wake-latency sample is capped here */
    double window;      /* discount horizon N, in slow-path acquisitions */
    int narms;
    double arms_ns[POL_MAX_ARMS];   /* ascending, arms_ns[0] == 0 */
    /* throttle-aware variant (lock "ta") */
    bool ta;
    double poll_us;     /* cpu.stat poll interval while a quota is set */
    double theta;       /* "imminent" when usage rate >= theta * quota */
    int hold_min, hold_max;   /* park-mode hold-off, in quota periods */
};

/* What one slow-path acquisition observed; applied after the unlock. */
struct pol_obs {
    bool spun;          /* acquired without sleeping: w_ns is exact */
    bool woke;          /* wake_ns is a valid wake-latency sample */
    int arm;            /* arm used (hedge, exp3, forced park), -1 for ada */
    double b_ns;        /* budget used */
    double w_ns;        /* spun: wait until acquired; parked: release stamp - t0 */
    double wake_ns;
};

struct pol_state {
    const void *owner;          /* lock this state belongs to */
    struct policy_cfg cfg;      /* thread-local copy */
    double w_hat;               /* wake-latency estimate, ns */
    double eta, explore, gamma;
    uint64_t budget_tsc;        /* ada: current budget */
    uint64_t arm_tsc[POL_MAX_ARMS];
    double L[POL_MAX_ARMS];     /* discounted cumulative (estimated) cost */
    double p[POL_MAX_ARMS], cdf[POL_MAX_ARMS];
    uint64_t rng;
    unsigned since;             /* updates since p was recomputed */
    bool pending;
    struct pol_obs obs;
};

void pol_default(struct policy_cfg *c, enum pol_kind kind);
/* Parses "key=value,..." (keys: beta w0 alpha wcap window arms base poll
 * theta hmin hmax; arms are '/'-separated ns). Returns 0 or -1. */
int pol_parse(const char *arg, struct policy_cfg *c);
/* JSON object describing the configuration. */
void pol_format(const struct policy_cfg *c, char *buf, size_t n);

void pol_init(struct pol_state *s, const struct policy_cfg *c, const void *owner);
void pol_update(struct pol_state *s, const struct pol_obs *o);

static inline double pol_unit(uint64_t *x)
{
    *x ^= *x >> 12;
    *x ^= *x << 25;
    *x ^= *x >> 27;
    return (double)((*x * 0x2545F4914F6CDD1Dull) >> 11) * 0x1.0p-53;
}

/* Spin budget in TSC ticks for the next slow path; *arm = arm index or -1. */
static inline uint64_t pol_choose(struct pol_state *s, int *arm)
{
    if (s->cfg.kind == POL_A) {
        *arm = -1;
        return s->budget_tsc;
    }
    double u = pol_unit(&s->rng);
    int k = 0;
    while (k + 1 < s->cfg.narms && s->cdf[k] <= u)
        k++;
    *arm = k;
    return s->arm_tsc[k];
}

#endif
