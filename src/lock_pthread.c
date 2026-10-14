/* External baselines: glibc's default mutex and its adaptive type
 * (PTHREAD_MUTEX_ADAPTIVE_NP, which spins a bounded number of times before
 * blocking; the bound is the glibc.pthread.mutex_spin_count tunable). */

#include <pthread.h>
#include <stdalign.h>

#include "common.h"
#include "lock.h"

struct pt_lock {
    alignas(PAD_BYTES) pthread_mutex_t m;
};

static void pt_init(void *p, const struct lock_params *lp)
{
    (void)lp;
    if (pthread_mutex_init(&((struct pt_lock *)p)->m, NULL) != 0)
        die("pthread_mutex_init failed");
}

static void pt_adaptive_init(void *p, const struct lock_params *lp)
{
    pthread_mutexattr_t a;
    (void)lp;
    pthread_mutexattr_init(&a);
    pthread_mutexattr_settype(&a, PTHREAD_MUTEX_ADAPTIVE_NP);
    if (pthread_mutex_init(&((struct pt_lock *)p)->m, &a) != 0)
        die("pthread_mutex_init (adaptive) failed");
    pthread_mutexattr_destroy(&a);
}

static void pt_lock(void *p) { pthread_mutex_lock(&((struct pt_lock *)p)->m); }
static void pt_unlock(void *p) { pthread_mutex_unlock(&((struct pt_lock *)p)->m); }
static void pt_destroy(void *p) { pthread_mutex_destroy(&((struct pt_lock *)p)->m); }

const struct lock_ops pthread_ops = {
    .name = "pthread", .size = sizeof(struct pt_lock),
    .init = pt_init, .lock = pt_lock, .unlock = pt_unlock, .destroy = pt_destroy,
};

const struct lock_ops pthread_adaptive_ops = {
    .name = "pthread-adaptive", .size = sizeof(struct pt_lock),
    .init = pt_adaptive_init, .lock = pt_lock, .unlock = pt_unlock, .destroy = pt_destroy,
};
