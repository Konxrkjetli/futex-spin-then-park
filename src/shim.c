/* LD_PRELOAD shim (Phase 4 stretch): runs an unmodified program's
 * pthread mutexes on a futex-lab lock.
 *
 *   FL_SHIM_LOCK=<spec> LD_PRELOAD=build/libflshim.so ./program
 *
 * <spec> is any lock spec of the registry except the pthread wrappers
 * (park, spin, stp:<ns>, ada, hedge, exp3; ta works but starts one helper
 * thread per mutex). Every pthread_mutex_t gets its own lock object. Its
 * pointer is kept inside the mutex itself, in bytes 24..31 (the __list field
 * of glibc's x86-64 layout, used only by robust mutexes), so static
 * initialisers work: the object is created on first use and installed with
 * a CAS.
 *
 * Supported: default, error-checking (treated as default) and recursive
 * mutexes; lock, trylock, timedlock (polling), unlock, init, destroy.
 * Not supported: condition variables. glibc's pthread_cond_wait releases and
 * re-takes the mutex through internal calls the shim cannot see, so the shim
 * aborts if one is called rather than corrupt the program. Robust,
 * priority-inheritance and process-shared mutexes are not supported either.
 *
 * trylock is a CAS of the lock word 0 -> 1 at offset 0 of the lock object,
 * which is the uncontended acquire of every futex-lab lock (futex, spin and
 * adaptive families). */

#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "common.h"
#include "lock.h"
#include "tsc.h"

#define EXPORT __attribute__((visibility("default")))

struct shim_mutex {
    void *lock;
    int recursive;
    _Atomic(const void *) owner;   /* holder's identity (recursive mutexes) */
    unsigned count;
};
_Static_assert(sizeof(pthread_mutex_t) >= 32, "pthread_mutex_t layout");

static const struct lock_ops *g_ops;
static struct lock_params g_params;
static char g_spec[512];
static _Atomic int g_state;          /* 0 = not set up, 1 = in progress, 2 = ready */
static _Atomic long g_created, g_destroyed;
static __thread char t_id;           /* its address identifies the thread */

static void setup(void)
{
    int s = 0;
    if (atomic_compare_exchange_strong(&g_state, &s, 1)) {
        const char *spec = getenv("FL_SHIM_LOCK");
        if (!spec || !*spec)
            spec = "park";
        snprintf(g_spec, sizeof g_spec, "%s", spec);
        tsc_init();
        g_ops = lock_lookup(g_spec, &g_params);
        if (!g_ops || !strncmp(g_ops->name, "pthread", 7) || !strcmp(g_ops->name, "none")) {
            fprintf(stderr, "flshim: unusable FL_SHIM_LOCK '%s'\n", g_spec);
            abort();
        }
        atomic_store(&g_state, 2);
    }
    while (atomic_load(&g_state) != 2)
        cpu_relax();
}

__attribute__((constructor)) static void shim_ctor(void) { setup(); }

static inline _Atomic(struct shim_mutex *) *slot(pthread_mutex_t *m)
{
    return (_Atomic(struct shim_mutex *) *)((char *)m + 24);
}

static struct shim_mutex *make(int recursive)
{
    struct shim_mutex *s = calloc(1, sizeof *s);
    if (!s)
        abort();
    s->lock = lock_create(g_ops, &g_params);
    s->recursive = recursive;
    atomic_fetch_add(&g_created, 1);
    return s;
}

static void unmake(struct shim_mutex *s)
{
    lock_free(g_ops, s->lock);
    free(s);
    atomic_fetch_add(&g_destroyed, 1);
}

/* Object for m, created on first use for statically initialised mutexes;
 * glibc's __kind (offset 16) says whether the initialiser was recursive. */
static inline struct shim_mutex *get(pthread_mutex_t *m)
{
    struct shim_mutex *s = atomic_load_explicit(slot(m), memory_order_acquire);
    if (likely(s))
        return s;
    if (atomic_load(&g_state) != 2)
        setup();
    int kind = *(int *)((char *)m + 16) & 3;
    struct shim_mutex *n = make(kind == PTHREAD_MUTEX_RECURSIVE), *expect = NULL;
    if (atomic_compare_exchange_strong(slot(m), &expect, n))
        return n;
    unmake(n);
    return expect;
}

EXPORT int pthread_mutex_init(pthread_mutex_t *m, const pthread_mutexattr_t *a)
{
    int type = PTHREAD_MUTEX_DEFAULT, pshared = PTHREAD_PROCESS_PRIVATE;
    if (a) {
        pthread_mutexattr_gettype(a, &type);
        pthread_mutexattr_getpshared(a, &pshared);
    }
    if (pshared != PTHREAD_PROCESS_PRIVATE) {
        fprintf(stderr, "flshim: process-shared mutexes are not supported\n");
        abort();
    }
    if (atomic_load(&g_state) != 2)
        setup();
    memset(m, 0, sizeof *m);
    *(int *)((char *)m + 16) = type == PTHREAD_MUTEX_RECURSIVE ? PTHREAD_MUTEX_RECURSIVE : 0;
    atomic_store_explicit(slot(m), make(type == PTHREAD_MUTEX_RECURSIVE), memory_order_release);
    return 0;
}

EXPORT int pthread_mutex_destroy(pthread_mutex_t *m)
{
    struct shim_mutex *s = atomic_exchange(slot(m), NULL);
    if (s)
        unmake(s);
    return 0;
}

EXPORT int pthread_mutex_lock(pthread_mutex_t *m)
{
    struct shim_mutex *s = get(m);
    if (s->recursive) {
        if (atomic_load_explicit(&s->owner, memory_order_relaxed) == &t_id) {
            s->count++;
            return 0;
        }
        g_ops->lock(s->lock);
        atomic_store_explicit(&s->owner, &t_id, memory_order_relaxed);
        s->count = 1;
        return 0;
    }
    g_ops->lock(s->lock);
    return 0;
}

EXPORT int pthread_mutex_trylock(pthread_mutex_t *m)
{
    struct shim_mutex *s = get(m);
    if (s->recursive && atomic_load_explicit(&s->owner, memory_order_relaxed) == &t_id) {
        s->count++;
        return 0;
    }
    uint32_t zero = 0;
    if (!atomic_compare_exchange_strong_explicit((_Atomic uint32_t *)s->lock, &zero, 1,
                                                 memory_order_acquire, memory_order_relaxed))
        return EBUSY;
    if (s->recursive) {
        atomic_store_explicit(&s->owner, &t_id, memory_order_relaxed);
        s->count = 1;
    }
    return 0;
}

EXPORT int pthread_mutex_unlock(pthread_mutex_t *m)
{
    struct shim_mutex *s = get(m);
    if (s->recursive) {
        if (--s->count)
            return 0;
        atomic_store_explicit(&s->owner, NULL, memory_order_relaxed);
    }
    g_ops->unlock(s->lock);
    return 0;
}

static int timed(pthread_mutex_t *m, clockid_t clk, const struct timespec *abst)
{
    for (;;) {
        if (pthread_mutex_trylock(m) == 0)
            return 0;
        struct timespec now;
        clock_gettime(clk, &now);
        if (now.tv_sec > abst->tv_sec || (now.tv_sec == abst->tv_sec && now.tv_nsec >= abst->tv_nsec))
            return ETIMEDOUT;
        struct timespec d = { 0, 1000 };
        nanosleep(&d, NULL);
    }
}

EXPORT int pthread_mutex_timedlock(pthread_mutex_t *m, const struct timespec *t)
{
    return timed(m, CLOCK_REALTIME, t);
}

EXPORT int pthread_mutex_clocklock(pthread_mutex_t *m, clockid_t c, const struct timespec *t)
{
    return timed(m, c, t);
}

__attribute__((noreturn)) static void no_condvars(const char *fn)
{
    fprintf(stderr, "flshim: %s is not supported (glibc re-takes the mutex internally)\n", fn);
    abort();
}

EXPORT int pthread_cond_wait(pthread_cond_t *c, pthread_mutex_t *m)
{
    (void)c; (void)m;
    no_condvars("pthread_cond_wait");
}

EXPORT int pthread_cond_timedwait(pthread_cond_t *c, pthread_mutex_t *m, const struct timespec *t)
{
    (void)c; (void)m; (void)t;
    no_condvars("pthread_cond_timedwait");
}

EXPORT int pthread_cond_clockwait(pthread_cond_t *c, pthread_mutex_t *m, clockid_t k, const struct timespec *t)
{
    (void)c; (void)m; (void)k; (void)t;
    no_condvars("pthread_cond_clockwait");
}

/* ---- introspection for the benchmark (looked up with dlsym) ------------- */

EXPORT int fl_shim_active(void) { return atomic_load(&g_state) == 2; }

EXPORT void fl_shim_info(char *buf, size_t n)
{
    snprintf(buf, n, "{\"spec\":\"%s\",\"mutexes_created\":%ld,\"mutexes_destroyed\":%ld}",
             g_spec, atomic_load(&g_created), atomic_load(&g_destroyed));
}

/* The calling thread's slow-path counters (for all shimmed mutexes). */
EXPORT void fl_shim_tstats(struct lock_tstats *out) { *out = lk_stats; }
