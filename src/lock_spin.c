/* Spin-only lock: test-and-test-and-set with bounded exponential backoff.
 * Waiters never enter the kernel. */

#include <stdalign.h>
#include <stdatomic.h>

#include "common.h"
#include "lock.h"
#include "tsc.h"

/* Upper bound on pause instructions between polls. `pause` costs ~14 ns on
 * this Zen 3+ CPU (calib timer), so 16 caps a backoff at ~230 ns; a larger
 * cap lets waiters sleep through short critical sections. */
#define SPIN_BACKOFF_MAX 16

struct spin_lock {
    alignas(PAD_BYTES) _Atomic uint32_t word;
};
_Static_assert(sizeof(struct spin_lock) == PAD_BYTES, "spin_lock layout");

static void spin_init(void *p, const struct lock_params *lp)
{
    (void)lp;
    atomic_init(&((struct spin_lock *)p)->word, 0);
}

static void spin_acquire(void *p)
{
    struct spin_lock *l = p;

    if (likely(atomic_exchange_explicit(&l->word, 1, memory_order_acquire) == 0))
        return;
    lk_stats.slow++;

    uint64_t t0 = tsc_now();
    unsigned backoff = 1;
    for (;;) {
        while (atomic_load_explicit(&l->word, memory_order_relaxed) != 0) {
            for (unsigned i = 0; i < backoff; i++)
                cpu_relax();
            if (backoff < SPIN_BACKOFF_MAX)
                backoff <<= 1;
        }
        if (atomic_exchange_explicit(&l->word, 1, memory_order_acquire) == 0)
            break;
    }
    lk_stats.spin_acq++;
    lk_stats.spin_tsc += tsc_now() - t0;
}

static void spin_release(void *p)
{
    atomic_store_explicit(&((struct spin_lock *)p)->word, 0, memory_order_release);
}

const struct lock_ops spin_ops = {
    .name = "spin", .size = sizeof(struct spin_lock),
    .init = spin_init, .lock = spin_acquire, .unlock = spin_release,
};
