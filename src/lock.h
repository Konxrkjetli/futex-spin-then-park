#ifndef FL_LOCK_H
#define FL_LOCK_H

#include <stdint.h>
#include <stdio.h>

/* Common lock interface. Every lock is used through these function pointers,
 * so the harness is lock-agnostic and every lock pays the same (predictable)
 * indirect-call cost. */

struct lock_params {
    double spin_ns;   /* spin budget for spin-then-park locks */
};

struct lock_ops {
    const char *name;
    const char *arg_name;   /* non-NULL if the spec takes ":<arg>" */
    size_t size;
    void (*init)(void *l, const struct lock_params *p);
    void (*lock)(void *l);
    void (*unlock)(void *l);
    void (*destroy)(void *l);   /* may be NULL */
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
};
extern __thread struct lock_tstats lk_stats;

/* Spec: park | spin | stp:<ns> | pthread | pthread-adaptive | none */
const struct lock_ops *lock_lookup(const char *spec, struct lock_params *p);
void *lock_create(const struct lock_ops *ops, const struct lock_params *p);
void lock_free(const struct lock_ops *ops, void *l);
void lock_list(FILE *f);

#endif
