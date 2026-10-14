/* Three-state futex lock with an optional bounded spin phase.
 *
 * Word states (Drepper, "Futexes Are Tricky", mutex3; to be verified against
 * the paper, see RESEARCH_PHASE.md section 4):
 *   0  unlocked
 *   1  locked, no waiters known
 *   2  locked, waiters may be parked in the kernel
 *
 * park:      spin budget 0, a contended waiter parks immediately.
 * stp:<ns>:  a contended waiter spins up to <ns> nanoseconds (measured on the
 *            TSC, not in iterations) trying to grab the lock, then parks.
 *
 * A spinner that wins takes the word 0 -> 1 even if sleepers exist. That is
 * safe: the unlock that produced 0 already woke one sleeper, and that sleeper
 * sets the word back to 2 when it runs, so the next unlock wakes again. */

#include <stdalign.h>
#include <stdatomic.h>

#include "common.h"
#include "futex.h"
#include "lock.h"
#include "tsc.h"

struct futex_lock {
    alignas(PAD_BYTES) _Atomic uint32_t word;
    alignas(CACHELINE) uint64_t budget_tsc;   /* read-only after init, off the word's line */
};
_Static_assert(sizeof(struct futex_lock) == PAD_BYTES, "futex_lock layout");

static void park_init(void *p, const struct lock_params *lp)
{
    struct futex_lock *l = p;
    (void)lp;
    atomic_init(&l->word, 0);
    l->budget_tsc = 0;
}

static void stp_init(void *p, const struct lock_params *lp)
{
    struct futex_lock *l = p;
    atomic_init(&l->word, 0);
    l->budget_tsc = lp->spin_ns > 0 ? ns_to_tsc(lp->spin_ns) : 0;
}

static void flock_lock(void *p)
{
    struct futex_lock *l = p;
    uint32_t c = 0;

    if (likely(atomic_compare_exchange_strong_explicit(&l->word, &c, 1,
                                                       memory_order_acquire,
                                                       memory_order_relaxed)))
        return;
    lk_stats.slow++;

    if (l->budget_tsc) {
        uint64_t t0 = tsc_now(), now, deadline = t0 + l->budget_tsc;
        do {
            cpu_relax();
            c = atomic_load_explicit(&l->word, memory_order_relaxed);
            if (c == 0 &&
                atomic_compare_exchange_weak_explicit(&l->word, &c, 1,
                                                      memory_order_acquire,
                                                      memory_order_relaxed)) {
                lk_stats.spin_acq++;
                lk_stats.spin_tsc += tsc_now() - t0;
                return;
            }
            now = tsc_now();
        } while (now < deadline);
        lk_stats.spin_tsc += now - t0;
    }

    /* Park: mark "waiters possible" and sleep while the lock stays held. */
    c = atomic_exchange_explicit(&l->word, 2, memory_order_acquire);
    while (c != 0) {
        lk_stats.parks++;
        futex_wait(&l->word, 2);
        c = atomic_exchange_explicit(&l->word, 2, memory_order_acquire);
    }
}

static void flock_unlock(void *p)
{
    struct futex_lock *l = p;

    /* 1 -> 0: nobody parked, done. 2 -> 1 means waiters may exist. */
    if (atomic_fetch_sub_explicit(&l->word, 1, memory_order_release) != 1) {
        atomic_store_explicit(&l->word, 0, memory_order_release);
        lk_stats.wakes++;
        futex_wake(&l->word, 1);
    }
}

const struct lock_ops park_ops = {
    .name = "park", .size = sizeof(struct futex_lock),
    .init = park_init, .lock = flock_lock, .unlock = flock_unlock,
};

const struct lock_ops stp_ops = {
    .name = "stp", .arg_name = "spin_ns", .size = sizeof(struct futex_lock),
    .init = stp_init, .lock = flock_lock, .unlock = flock_unlock,
};
