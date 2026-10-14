/* Calibration and harness-validation measurements. Each subcommand prints a
 * JSON object.
 *
 *   calib tsc-hz            calibrated TSC frequency and work-loop rate
 *   calib timer             cost of timestamps, pause, futex_wake with no
 *                           waiters, and uncontended lock+unlock per lock
 *   calib tsc-sync A B      cross-CPU TSC consistency check (ping-pong)
 *   calib work              requested vs measured duration of spin_work */

#include <math.h>
#include <pthread.h>
#include <stdalign.h>
#include <stdatomic.h>
#include <string.h>
#include <time.h>

#include "common.h"
#include "futex.h"
#include "lock.h"
#include "topo.h"
#include "tsc.h"

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

static double calibrate_work(void)
{
    const uint64_t n = 20u * 1000 * 1000;
    spin_work(n);
    double best = 1e30;
    for (int r = 0; r < 5; r++) {
        uint64_t t0 = tsc_ordered();
        spin_work(n);
        double ns = tsc_to_ns(tsc_ordered() - t0);
        if (ns < best)
            best = ns;
    }
    return (double)n / best;
}

static int cmd_tsc_hz(void)
{
    printf("{\"tsc_hz\":%.0f,\"iters_per_ns\":%.5f}\n", tsc_hz, calibrate_work());
    return 0;
}

/* Median and minimum gap between back-to-back reads, in ticks. */
static void back_to_back(int ordered, uint64_t *min_out, uint64_t *med_out)
{
    enum { N = 100000 };
    static uint64_t d[N];
    for (int i = 0; i < N; i++) {
        uint64_t a, b;
        if (ordered) { a = tsc_ordered(); b = tsc_ordered(); }
        else { a = tsc_now(); b = tsc_now(); }
        d[i] = b - a;
    }
    qsort(d, N, sizeof d[0], cmp_u64);
    *min_out = d[0];
    *med_out = d[N / 2];
}

static int cmd_timer(void)
{
    uint64_t omin, omed, umin, umed;
    back_to_back(1, &omin, &omed);
    back_to_back(0, &umin, &umed);

    enum { NCG = 1000000, NP = 1000000, NW = 200000, NL = 5000000 };
    struct timespec ts;
    uint64_t t0 = tsc_ordered();
    for (int i = 0; i < NCG; i++)
        clock_gettime(CLOCK_MONOTONIC, &ts);
    double cg_ns = tsc_to_ns(tsc_ordered() - t0) / NCG;

    t0 = tsc_ordered();
    for (int i = 0; i < NP; i++)
        cpu_relax();
    double pause_ns = tsc_to_ns(tsc_ordered() - t0) / NP;

    static alignas(PAD_BYTES) _Atomic uint32_t fw;
    t0 = tsc_ordered();
    for (int i = 0; i < NW; i++)
        futex_wake(&fw, 1);
    double wake_ns = tsc_to_ns(tsc_ordered() - t0) / NW;

    printf("{\"tool\":\"calib-timer\",\"tsc_hz\":%.0f,", tsc_hz);
    printf("\"tsc_ordered_pair_ns\":{\"min\":%.2f,\"median\":%.2f},",
           tsc_to_ns(omin), tsc_to_ns(omed));
    printf("\"tsc_unordered_pair_ns\":{\"min\":%.2f,\"median\":%.2f},",
           tsc_to_ns(umin), tsc_to_ns(umed));
    printf("\"clock_gettime_ns\":%.2f,\"pause_ns\":%.2f,\"futex_wake_nowaiter_ns\":%.1f,",
           cg_ns, pause_ns, wake_ns);

    static const char *specs[] = { "park", "spin", "stp:1000", "pthread", "pthread-adaptive", "none" };
    printf("\"uncontended_lock_unlock_ns\":{");
    for (size_t s = 0; s < sizeof specs / sizeof specs[0]; s++) {
        struct lock_params lp;
        const struct lock_ops *ops = lock_lookup(specs[s], &lp);
        void *l = lock_create(ops, &lp);
        for (int i = 0; i < 100000; i++) {
            ops->lock(l);
            ops->unlock(l);
        }
        t0 = tsc_ordered();
        for (int i = 0; i < NL; i++) {
            ops->lock(l);
            ops->unlock(l);
        }
        double ns = tsc_to_ns(tsc_ordered() - t0) / NL;
        printf("%s\"%s\":%.2f", s ? "," : "", specs[s], ns);
        lock_free(ops, l);
    }
    printf("}}\n");
    return 0;
}

/* ---- tsc-sync: A stamps and hands over to B, B stamps on receipt, and the
 * other way round. With skew s = TSC_B - TSC_A and one-way latency L:
 *   min(B - A) = L + s,  min(A - B) = L - s.
 * Both minima must be positive if the TSCs are consistent. */

static struct {
    alignas(PAD_BYTES) _Atomic uint64_t slot;
    alignas(PAD_BYTES) _Atomic int turn;
} ps;
static int sync_cpu[2];
enum { SYNC_ROUNDS = 20000 };
static int64_t d_ab[SYNC_ROUNDS], d_ba[SYNC_ROUNDS];

static void *sync_b(void *arg)
{
    (void)arg;
    if (pin_self(sync_cpu[1]) != 0)
        die("cannot pin to cpu %d", sync_cpu[1]);
    for (int r = 0; r < SYNC_ROUNDS; r++) {
        while (atomic_load_explicit(&ps.turn, memory_order_acquire) != 1)
            cpu_relax();
        uint64_t now = tsc_ordered();
        d_ab[r] = (int64_t)(now - atomic_load_explicit(&ps.slot, memory_order_relaxed));
        atomic_store_explicit(&ps.slot, tsc_ordered(), memory_order_relaxed);
        atomic_store_explicit(&ps.turn, 2, memory_order_release);
    }
    return NULL;
}

static int cmp_i64(const void *a, const void *b)
{
    int64_t x = *(const int64_t *)a, y = *(const int64_t *)b;
    return (x > y) - (x < y);
}

static int cmd_tsc_sync(int a, int b)
{
    sync_cpu[0] = a;
    sync_cpu[1] = b;
    pthread_t th;
    if (pthread_create(&th, NULL, sync_b, NULL) != 0)
        die("pthread_create failed");
    if (pin_self(a) != 0)
        die("cannot pin to cpu %d", a);
    for (int r = 0; r < SYNC_ROUNDS; r++) {
        atomic_store_explicit(&ps.slot, tsc_ordered(), memory_order_relaxed);
        atomic_store_explicit(&ps.turn, 1, memory_order_release);
        while (atomic_load_explicit(&ps.turn, memory_order_acquire) != 2)
            cpu_relax();
        uint64_t now = tsc_ordered();
        d_ba[r] = (int64_t)(now - atomic_load_explicit(&ps.slot, memory_order_relaxed));
        atomic_store_explicit(&ps.turn, 0, memory_order_relaxed);
    }
    pthread_join(th, NULL);
    qsort(d_ab, SYNC_ROUNDS, sizeof d_ab[0], cmp_i64);
    qsort(d_ba, SYNC_ROUNDS, sizeof d_ba[0], cmp_i64);
    double ab = tsc_to_ns((uint64_t)llabs(d_ab[0])) * (d_ab[0] < 0 ? -1 : 1);
    double ba = tsc_to_ns((uint64_t)llabs(d_ba[0])) * (d_ba[0] < 0 ? -1 : 1);
    printf("{\"tool\":\"calib-tsc-sync\",\"cpu_a\":%d,\"cpu_b\":%d,\"min_a_to_b_ns\":%.1f,"
           "\"min_b_to_a_ns\":%.1f,\"skew_estimate_ns\":%.1f,\"one_way_ns\":%.1f,\"consistent\":%s}\n",
           a, b, ab, ba, (ab - ba) / 2, (ab + ba) / 2, (d_ab[0] > 0 && d_ba[0] > 0) ? "true" : "false");
    return 0;
}

static int cmd_work(void)
{
    double ipn = calibrate_work();
    static const double targets[] = { 50, 100, 1000, 10000, 100000 };
    enum { R = 201 };
    uint64_t d[R];
    printf("{\"tool\":\"calib-work\",\"iters_per_ns\":%.5f,\"points\":[", ipn);
    for (size_t k = 0; k < sizeof targets / sizeof targets[0]; k++) {
        uint64_t iters = (uint64_t)(targets[k] * ipn + 0.5);
        for (int r = 0; r < R; r++) {
            uint64_t t0 = tsc_ordered();
            spin_work(iters);
            d[r] = tsc_ordered() - t0;
        }
        qsort(d, R, sizeof d[0], cmp_u64);
        double med = tsc_to_ns(d[R / 2]);
        printf("%s{\"target_ns\":%g,\"iters\":%llu,\"median_ns\":%.1f,\"ratio\":%.3f}",
               k ? "," : "", targets[k], (unsigned long long)iters, med, med / targets[k]);
    }
    printf("]}\n");
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2)
        die("usage: calib tsc-hz | timer | tsc-sync CPU_A CPU_B | work");
    tsc_init();
    if (!strcmp(argv[1], "tsc-hz"))
        return cmd_tsc_hz();
    if (!strcmp(argv[1], "timer"))
        return cmd_timer();
    if (!strcmp(argv[1], "tsc-sync") && argc == 4)
        return cmd_tsc_sync(atoi(argv[2]), atoi(argv[3]));
    if (!strcmp(argv[1], "work"))
        return cmd_work();
    die("unknown subcommand '%s'", argv[1]);
}
