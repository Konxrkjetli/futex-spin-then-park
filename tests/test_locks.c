/* Correctness test for every lock.
 *
 * T threads each do `total / T` acquisitions. Inside the critical section a
 * thread (1) flips an `in_cs` flag and counts an overlap if someone else is
 * already inside, (2) increments a plain, non-atomic counter, and sometimes
 * (3) does a little work so waiters reach the spin and park paths. The final
 * counter must equal the number of acquisitions exactly, with zero overlaps.
 *
 * The counter is deliberately non-atomic: under ThreadSanitizer a broken lock
 * shows up as a data race. A watchdog aborts the test if a run hangs, which
 * is how a lost wake-up would show up.
 *
 * usage: test_locks [--total N] [--watchdog S] [spec ...] */

#include <pthread.h>
#include <signal.h>
#include <stdalign.h>
#include <stdatomic.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "common.h"
#include "lock.h"
#include "tsc.h"

static const char *default_specs[] = {
    "park", "spin", "stp:100", "stp:2000", "pthread", "pthread-adaptive",
};
static const int thread_counts[] = { 2, 8, 32 };

static struct {
    alignas(PAD_BYTES) uint64_t counter;           /* protected by the lock */
    alignas(PAD_BYTES) _Atomic int in_cs;
    alignas(PAD_BYTES) _Atomic uint64_t overlaps;
    alignas(PAD_BYTES) _Atomic uint64_t slow, spin_acq, parks, wakes;
} sh;

static const struct lock_ops *g_ops;
static void *g_lock;
static uint64_t g_iters;
static char g_current[96];

static void on_alarm(int sig)
{
    (void)sig;
    static const char msg[] = "\nFAIL watchdog expired (hang, possible lost wake-up) in: ";
    ssize_t r = write(2, msg, sizeof msg - 1);
    r = write(2, g_current, strlen(g_current));
    r = write(2, "\n", 1);
    (void)r;
    _exit(3);
}

static void *worker(void *arg)
{
    uint64_t rng = (uint64_t)(uintptr_t)arg * 0x9E3779B97F4A7C15ull + 1;
    memset(&lk_stats, 0, sizeof lk_stats);

    for (uint64_t i = 0; i < g_iters; i++) {
        rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
        g_ops->lock(g_lock);
        if (atomic_exchange_explicit(&sh.in_cs, 1, memory_order_relaxed) != 0)
            atomic_fetch_add_explicit(&sh.overlaps, 1, memory_order_relaxed);
        sh.counter++;
        if ((rng & 63) == 0)
            spin_work(rng % 4000);      /* occasional long hold: forces parking */
        atomic_store_explicit(&sh.in_cs, 0, memory_order_relaxed);
        g_ops->unlock(g_lock);
        if ((rng & 7) == 0)
            spin_work((rng >> 8) % 500);
    }

    atomic_fetch_add(&sh.slow, lk_stats.slow);
    atomic_fetch_add(&sh.spin_acq, lk_stats.spin_acq);
    atomic_fetch_add(&sh.parks, lk_stats.parks);
    atomic_fetch_add(&sh.wakes, lk_stats.wakes);
    return NULL;
}

static int run_one(const char *spec, int threads, uint64_t total)
{
    struct lock_params lp;
    g_ops = lock_lookup(spec, &lp);
    if (!g_ops) {
        fprintf(stderr, "unknown lock spec: %s\n", spec);
        return 1;
    }
    g_lock = lock_create(g_ops, &lp);
    g_iters = total / (uint64_t)threads;
    sh.counter = 0;
    atomic_store(&sh.in_cs, 0);
    atomic_store(&sh.overlaps, 0);
    atomic_store(&sh.slow, 0);
    atomic_store(&sh.spin_acq, 0);
    atomic_store(&sh.parks, 0);
    atomic_store(&sh.wakes, 0);
    snprintf(g_current, sizeof g_current, "%s T=%d", spec, threads);

    pthread_t th[64];
    uint64_t t0 = tsc_now();
    for (int i = 0; i < threads; i++)
        if (pthread_create(&th[i], NULL, worker, (void *)(uintptr_t)(i + 1)) != 0)
            die("pthread_create failed");
    for (int i = 0; i < threads; i++)
        pthread_join(th[i], NULL);
    double ms = tsc_to_ns(tsc_now() - t0) / 1e6;

    uint64_t expect = g_iters * (uint64_t)threads;
    uint64_t overlaps = atomic_load(&sh.overlaps);
    int ok = sh.counter == expect && overlaps == 0;
    printf("%s %-18s T=%-2d counter=%llu/%llu overlaps=%llu slow=%llu spin_acq=%llu parks=%llu wakes=%llu %.0fms\n",
           ok ? "PASS" : "FAIL", spec, threads,
           (unsigned long long)sh.counter, (unsigned long long)expect,
           (unsigned long long)overlaps,
           (unsigned long long)atomic_load(&sh.slow),
           (unsigned long long)atomic_load(&sh.spin_acq),
           (unsigned long long)atomic_load(&sh.parks),
           (unsigned long long)atomic_load(&sh.wakes), ms);
    fflush(stdout);
    lock_free(g_ops, g_lock);
    return ok ? 0 : 1;
}

int main(int argc, char **argv)
{
    uint64_t total = 2000000;
    unsigned watchdog = 120;
    const char *specs[32];
    int nspecs = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--total") && i + 1 < argc)
            total = strtoull(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--watchdog") && i + 1 < argc)
            watchdog = (unsigned)atoi(argv[++i]);
        else if (nspecs < 32)
            specs[nspecs++] = argv[i];
    }
    if (nspecs == 0) {
        nspecs = (int)(sizeof default_specs / sizeof default_specs[0]);
        memcpy(specs, default_specs, sizeof default_specs);
    }

    tsc_init();
    signal(SIGALRM, on_alarm);

    int failures = 0, runs = 0;
    for (int s = 0; s < nspecs; s++) {
        for (size_t t = 0; t < sizeof thread_counts / sizeof thread_counts[0]; t++) {
            alarm(watchdog);
            failures += run_one(specs[s], thread_counts[t], total);
            alarm(0);
            runs++;
        }
    }
    printf("%s: %d/%d runs passed\n", failures ? "FAILED" : "ALL PASSED", runs - failures, runs);
    return failures ? 1 : 0;
}
