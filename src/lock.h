#ifndef FL_LOCK_H
#define FL_LOCK_H

#include <stdint.h>
#include <stdio.h>

#include "policy.h"

/* Common lock interface. Every lock is used through these function pointers,
 * so the harness is lock-agnostic and every lock pays the same (predictable)
 * indirect-call cost. */

struct lock_params {
    double spin_ns;           /* spin budget for spin-then-park locks */
    struct policy_cfg pol;    /* adaptive locks */
};

struct lock_ops {
    const char *name;
    const char *arg_name;   /* non-NULL if the spec takes ":<arg>" */
    /* If set, ":<arg>" is optional and parsed by this hook (0 = valid);
     * otherwise a required arg is a number stored in spin_ns. */
    int (*parse)(const char *arg, struct lock_params *p);
    size_t size;
    void (*init)(void *l, const struct lock_params *p);
    void (*lock)(void *l);
    void (*unlock)(void *l);
    void (*destroy)(void *l);   /* may be NULL */
    /* Optional: writes a JSON value describing the lock's own state. */
    void (*report)(void *l, FILE *f);
};

/* Per-thread slow-path counters, updated only by the team's locks (the
 * pthread wrappers leave them at zero). Fast-path acquisitions are not
 * counted; they equal total acquisitions minus `slow`. */
struct lock_tstats {
    uint64_t slow;       /* acquisitions that missed the uncontended fast path */
    uint64_t spin_acq;   /* acquired while spinning */
    uint64_t parks;      /* futex_wait calls */
    uint64_t wakes;      /* futex_wake calls issued by unlock */
    uint64_t spin_tsc;   /* TSC ticks spent spinning */
    /* Adaptive locks only (zero for the others). */
    uint64_t budget_tsc; /* sum of the spin budgets chosen on the slow path */
    uint64_t forced;     /* slow paths forced to budget 0 by throttle detection */
    uint64_t wake_n;     /* wake-latency samples taken inside the lock */
    uint64_t wake_tsc;   /* their sum */
    uint64_t arm_n[POL_MAX_ARMS];   /* times each arm was used */
    double cost_real;               /* policy cost actually paid (ns, cost model) */
    double cost_arm[POL_MAX_ARMS];  /* counterfactual cost of each fixed arm (ns) */
};
extern __thread struct lock_tstats lk_stats;

/* Spec: park | spin | stp:<ns> | pthread | pthread-adaptive | none
 *       | ada[:k=v,...] | hedge[:k=v,...] | exp3[:k=v,...] | ta[:k=v,...] */
const struct lock_ops *lock_lookup(const char *spec, struct lock_params *p);
void *lock_create(const struct lock_ops *ops, const struct lock_params *p);
void lock_free(const struct lock_ops *ops, void *l);
void lock_list(FILE *f);

#endif
