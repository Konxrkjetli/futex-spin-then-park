/* Futex wake-up latency microbenchmark (RQ1).
 *
 * A sleeper thread blocks in FUTEX_WAIT; after an idle delay a waker thread
 * stamps the TSC, changes the futex word and calls FUTEX_WAKE. The sleeper
 * stamps the TSC as soon as it returns to user space. One sample is
 *
 *     wake latency = sleeper's return stamp - waker's stamp
 *
 * which covers the waker's syscall entry, the kernel wake path, any IPI, the
 * sleeper CPU's exit from its idle state, scheduling, and the return to user
 * space. TSC values from two CPUs are comparable because the TSC is invariant
 * and synchronised (checked by `calib tsc-sync`).
 *
 * The waker also records how long its own futex_wake call took (the
 * releaser-side cost) and whether it actually woke someone. A sample where
 * FUTEX_WAKE woke nobody means the sleeper had not blocked yet; it is
 * counted as "missed" and excluded from the latency statistics.
 *
 * Conditions: CPU placement (SMT sibling / other core / same CPU), idle time
 * before the wake (controls how deep the sleeper's CPU goes into C-states),
 * and an optional CPU hog on the sleeper's CPU. */

#include <getopt.h>
#include <math.h>
#include <pthread.h>
#include <stdalign.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <string.h>
#include <sys/prctl.h>
#include <time.h>

#include "cgroup.h"
#include "common.h"
#include "futex.h"
#include "topo.h"
#include "tsc.h"

#define MAX_IDLE_STATES 16

static struct {
    int sleeper_cpu, waker_cpu;
    double idle_us;
    long samples, warmup;
    bool load;
    const char *out;
    const char *label;
} cfg = { .sleeper_cpu = 2, .waker_cpu = 4, .idle_us = 100, .samples = 10000, .warmup = 200 };

static struct {
    alignas(PAD_BYTES) _Atomic uint32_t seq;     /* sleeper waits on this */
    alignas(PAD_BYTES) _Atomic uint32_t ready;   /* waker waits on this */
    alignas(PAD_BYTES) _Atomic int stop_load;
} sh;

/* Each array is written by exactly one thread and read by main after join. */
static uint64_t *wake_at;    /* waker: TSC just before FUTEX_WAKE */
static uint64_t *woke_at;    /* sleeper: TSC on return from FUTEX_WAIT */
static uint64_t *block_at;   /* sleeper: TSC just before FUTEX_WAIT */
static uint64_t *wake_cost;  /* waker: TSC ticks spent in futex_wake */
static uint8_t *woke_one;    /* waker: FUTEX_WAKE return > 0 */
static long total;

static void *alloc_array(size_t n, size_t sz)
{
    size_t bytes = (n * sz + PAD_BYTES - 1) / PAD_BYTES * PAD_BYTES;
    void *p = aligned_alloc(PAD_BYTES, bytes);
    if (!p)
        die("allocation failed");
    memset(p, 0, bytes);
    return p;
}

static void *sleeper(void *arg)
{
    (void)arg;
    if (pin_self(cfg.sleeper_cpu) != 0)
        die("cannot pin sleeper to cpu %d", cfg.sleeper_cpu);
    for (long i = 0; i < total; i++) {
        atomic_store_explicit(&sh.ready, (uint32_t)(i + 1), memory_order_release);
        futex_wake(&sh.ready, 1);
        block_at[i] = tsc_ordered();
        while (atomic_load_explicit(&sh.seq, memory_order_acquire) == (uint32_t)i)
            futex_wait(&sh.seq, (uint32_t)i);
        woke_at[i] = tsc_ordered();
    }
    return NULL;
}

static void *hog(void *arg)
{
    (void)arg;
    if (pin_self(cfg.sleeper_cpu) != 0)
        die("cannot pin hog to cpu %d", cfg.sleeper_cpu);
    while (!atomic_load_explicit(&sh.stop_load, memory_order_relaxed))
        spin_work(10000);
    return NULL;
}

static void idle_delay(bool sleep_mode)
{
    if (sleep_mode) {
        double ns = cfg.idle_us * 1e3;
        struct timespec d = { (time_t)(ns / 1e9), (long)fmod(ns, 1e9) };
        clock_nanosleep(CLOCK_MONOTONIC, 0, &d, NULL);
    } else {
        uint64_t end = tsc_now() + ns_to_tsc(cfg.idle_us * 1e3);
        while (tsc_now() < end)
            cpu_relax();
    }
}

static void waker_loop(void)
{
    if (pin_self(cfg.waker_cpu) != 0)
        die("cannot pin waker to cpu %d", cfg.waker_cpu);
    prctl(PR_SET_TIMERSLACK, 1UL, 0, 0, 0);
    /* On the same CPU the waker must block during the delay or the sleeper
     * never gets to run and block. Long delays also sleep, so the waker's own
     * CPU idles too; short delays busy-wait for precision. */
    bool sleep_mode = cfg.sleeper_cpu == cfg.waker_cpu || cfg.idle_us >= 50;

    for (long i = 0; i < total; i++) {
        while (atomic_load_explicit(&sh.ready, memory_order_acquire) == (uint32_t)i)
            futex_wait(&sh.ready, (uint32_t)i);
        idle_delay(sleep_mode);
        uint64_t w = tsc_ordered();
        wake_at[i] = w;
        atomic_store_explicit(&sh.seq, (uint32_t)(i + 1), memory_order_release);
        long n = futex_wake(&sh.seq, 1);
        wake_cost[i] = tsc_ordered() - w;
        woke_one[i] = n > 0;
    }
}

struct idle_state { char name[32]; unsigned long long usage, time_us; };

static int read_idle(int cpu, struct idle_state *st)
{
    int n = 0;
    for (; n < MAX_IDLE_STATES; n++) {
        char path[160];
        FILE *f;
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/cpuidle/state%d/name", cpu, n);
        if (!(f = fopen(path, "r")))
            break;
        if (fscanf(f, "%31s", st[n].name) != 1)
            st[n].name[0] = '\0';
        fclose(f);
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/cpuidle/state%d/usage", cpu, n);
        if ((f = fopen(path, "r"))) {
            if (fscanf(f, "%llu", &st[n].usage) != 1)
                st[n].usage = 0;
            fclose(f);
        }
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/cpuidle/state%d/time", cpu, n);
        if ((f = fopen(path, "r"))) {
            if (fscanf(f, "%llu", &st[n].time_us) != 1)
                st[n].time_us = 0;
            fclose(f);
        }
    }
    return n;
}

static int cmp_double(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

/* Nearest-rank quantile of a sorted array. */
static double q_sorted(const double *v, long n, double q)
{
    if (n == 0)
        return NAN;
    long r = (long)ceil(q * (double)n);
    if (r < 1)
        r = 1;
    if (r > n)
        r = n;
    return v[r - 1];
}

static void usage(FILE *f)
{
    fprintf(f,
"usage: wakebench [options]\n"
"  --sleeper CPU     CPU of the thread that blocks (default 2)\n"
"  --waker CPU       CPU of the thread that wakes it (default 4; may equal --sleeper)\n"
"  --idle-us X       delay between the sleeper blocking and the wake (default 100)\n"
"  --samples N       measured samples (default 10000)\n"
"  --warmup N        discarded leading samples (default 200)\n"
"  --load            run a CPU hog pinned to the sleeper's CPU\n"
"  --label TEXT      condition label copied into the JSON\n"
"  --out FILE        write raw samples as CSV\n");
}

int main(int argc, char **argv)
{
    static const struct option opts[] = {
        { "sleeper", required_argument, 0, 's' }, { "waker", required_argument, 0, 'w' },
        { "idle-us", required_argument, 0, 'i' }, { "samples", required_argument, 0, 'n' },
        { "warmup", required_argument, 0, 'W' },  { "load", no_argument, 0, 'L' },
        { "label", required_argument, 0, 'b' },   { "out", required_argument, 0, 'o' },
        { "help", no_argument, 0, 'h' },          { 0, 0, 0, 0 },
    };
    int c;
    while ((c = getopt_long(argc, argv, "s:w:i:n:W:Lb:o:h", opts, NULL)) != -1) {
        switch (c) {
        case 's': cfg.sleeper_cpu = atoi(optarg); break;
        case 'w': cfg.waker_cpu = atoi(optarg); break;
        case 'i': cfg.idle_us = atof(optarg); break;
        case 'n': cfg.samples = atol(optarg); break;
        case 'W': cfg.warmup = atol(optarg); break;
        case 'L': cfg.load = true; break;
        case 'b': cfg.label = optarg; break;
        case 'o': cfg.out = optarg; break;
        case 'h': usage(stdout); return 0;
        default: usage(stderr); return 2;
        }
    }
    if (cfg.samples < 1 || cfg.warmup < 0 || cfg.idle_us < 0)
        die("bad arguments");

    tsc_init();
    total = cfg.warmup + cfg.samples;
    wake_at = alloc_array((size_t)total, sizeof *wake_at);
    woke_at = alloc_array((size_t)total, sizeof *woke_at);
    block_at = alloc_array((size_t)total, sizeof *block_at);
    wake_cost = alloc_array((size_t)total, sizeof *wake_cost);
    woke_one = alloc_array((size_t)total, sizeof *woke_one);

    const char *placement = cfg.sleeper_cpu == cfg.waker_cpu ? "same-cpu"
                          : topo_sibling(cfg.sleeper_cpu) == cfg.waker_cpu ? "smt-sibling"
                          : "other-core";

    struct idle_state idle0[MAX_IDLE_STATES], idle1[MAX_IDLE_STATES];
    int nidle = read_idle(cfg.sleeper_cpu, idle0);

    /* cgroup CPU bandwidth counters over the whole measurement (Phase 4,
     * E10: the run may execute in a transient scope with a CPU quota). */
    char cg_dir[512], cg_max[64] = "";
    struct cg_stat cg0 = { 0 }, cg1 = { 0 };
    int cg_fd = -1;
    if (cg_self_dir(cg_dir, sizeof cg_dir) == 0) {
        long long q, per;
        if (cg_read_max(cg_dir, &q, &per) == 0)
            snprintf(cg_max, sizeof cg_max, q < 0 ? "max %lld" : "%lld %lld", q < 0 ? per : q, per);
        cg_fd = cg_open_stat(cg_dir);
    }
    bool cg_ok = cg_fd >= 0 && cg_read_stat_fd(cg_fd, &cg0) == 0;
    uint64_t run_t0 = tsc_now();

    pthread_t th_hog, th_sleeper;
    if (cfg.load && pthread_create(&th_hog, NULL, hog, NULL) != 0)
        die("pthread_create failed");
    if (pthread_create(&th_sleeper, NULL, sleeper, NULL) != 0)
        die("pthread_create failed");
    waker_loop();
    pthread_join(th_sleeper, NULL);
    if (cfg.load) {
        atomic_store(&sh.stop_load, 1);
        pthread_join(th_hog, NULL);
    }
    read_idle(cfg.sleeper_cpu, idle1);
    double run_s = tsc_to_ns(tsc_now() - run_t0) / 1e9;
    cg_ok = cg_ok && cg_read_stat_fd(cg_fd, &cg1) == 0;

    /* ---- statistics over measured, non-missed samples ---- */
    double *lat = malloc((size_t)cfg.samples * sizeof *lat);
    double *cost = malloc((size_t)cfg.samples * sizeof *cost);
    double *blocked = malloc((size_t)cfg.samples * sizeof *blocked);
    if (!lat || !cost || !blocked)
        die("allocation failed");
    long n = 0, missed = 0;
    double sum = 0;
    for (long i = cfg.warmup; i < total; i++) {
        if (!woke_one[i]) {
            missed++;
            continue;
        }
        lat[n] = tsc_to_ns(woke_at[i] - wake_at[i]);
        cost[n] = tsc_to_ns(wake_cost[i]);
        blocked[n] = tsc_to_ns(wake_at[i] - block_at[i]);
        sum += lat[n];
        n++;
    }

    if (cfg.out) {
        FILE *f = fopen(cfg.out, "w");
        if (!f)
            die("cannot write %s", cfg.out);
        fprintf(f, "i,wake_ns,waker_syscall_ns,blocked_ns,woke\n");
        for (long i = cfg.warmup; i < total; i++)
            fprintf(f, "%ld,%.1f,%.1f,%.1f,%d\n", i - cfg.warmup,
                    tsc_to_ns(woke_at[i] - wake_at[i]), tsc_to_ns(wake_cost[i]),
                    tsc_to_ns(wake_at[i] - block_at[i]), woke_one[i]);
        fclose(f);
    }

    qsort(lat, (size_t)n, sizeof *lat, cmp_double);
    qsort(cost, (size_t)n, sizeof *cost, cmp_double);
    qsort(blocked, (size_t)n, sizeof *blocked, cmp_double);

    printf("{\"tool\":\"wakebench\",\"label\":\"%s\",\"placement\":\"%s\",\"sleeper_cpu\":%d,"
           "\"waker_cpu\":%d,\"idle_us\":%g,\"load\":%s,\"samples\":%ld,\"warmup\":%ld,",
           cfg.label ? cfg.label : "", placement, cfg.sleeper_cpu, cfg.waker_cpu, cfg.idle_us,
           cfg.load ? "true" : "false", cfg.samples, cfg.warmup);
    printf("\"valid\":%ld,\"missed\":%ld,\"tsc_hz\":%.0f,", n, missed, tsc_hz);
    printf("\"wake_ns\":{\"mean\":%.1f,\"min\":%.1f,\"p50\":%.1f,\"p90\":%.1f,\"p99\":%.1f,"
           "\"p999\":%.1f,\"max\":%.1f},",
           n ? sum / (double)n : NAN, q_sorted(lat, n, 0), q_sorted(lat, n, 0.5),
           q_sorted(lat, n, 0.9), q_sorted(lat, n, 0.99), q_sorted(lat, n, 0.999),
           q_sorted(lat, n, 1.0));
    printf("\"waker_syscall_ns\":{\"p50\":%.1f,\"p99\":%.1f},",
           q_sorted(cost, n, 0.5), q_sorted(cost, n, 0.99));
    printf("\"blocked_ns\":{\"p50\":%.1f,\"p99\":%.1f},",
           q_sorted(blocked, n, 0.5), q_sorted(blocked, n, 0.99));
    printf("\"run_s\":%.3f,", run_s);
    if (cg_ok)
        printf("\"cgroup\":{\"cpu_max\":\"%s\",\"usage_usec\":%lld,\"nr_periods\":%lld,"
               "\"nr_throttled\":%lld,\"throttled_usec\":%lld},",
               cg_max, cg1.usage_usec - cg0.usage_usec, cg1.nr_periods - cg0.nr_periods,
               cg1.nr_throttled - cg0.nr_throttled, cg1.throttled_usec - cg0.throttled_usec);
    else
        printf("\"cgroup\":null,");
    printf("\"sleeper_cpuidle\":[");
    for (int s = 0; s < nidle; s++)
        printf("%s{\"state\":\"%s\",\"entries\":%llu,\"time_us\":%llu}", s ? "," : "",
               idle0[s].name, idle1[s].usage - idle0[s].usage, idle1[s].time_us - idle0[s].time_us);
    printf("]}\n");
    return 0;
}
