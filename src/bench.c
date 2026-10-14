/* Lock benchmark harness.
 *
 * Each worker repeats: acquire, critical section (increment shared counter,
 * touch shared lines, calibrated hold work), release, calibrated think work.
 * Acquire latency is the TSC delta around lock(). Everything hot is
 * thread-private during the run (histograms, window counters, op counts);
 * shared state is either the lock itself, the critical-section data, or
 * read-only configuration.
 *
 * A run is a schedule of phases (hold, think, active threads, duration). A
 * steady workload is a single phase. Output is one JSON object on stdout;
 * histograms and windowed throughput optionally go to CSV files. */

#include <getopt.h>
#include <glob.h>
#include <math.h>
#include <pthread.h>
#include <stdalign.h>
#include <stdbool.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

#include "common.h"
#include "hist.h"
#include "lock.h"
#include "topo.h"
#include "tsc.h"

#define MAX_THREADS 256
#define MAX_PHASES 8

struct phase {
    double hold_ns, think_ns, dur_ms;
    int active;
    uint64_t hold_iters, hold_long_iters, think_iters;
    uint64_t start_tsc, end_tsc;
};

static struct {
    const char *lock_spec;
    int threads;
    double hold_ns, think_ns, duration_ms, warmup_ms, window_ms;
    double hold_long_ns, hold_long_p;
    bool think_exp, timing, pin;
    int cs_lines;
    double iters_per_ns;
    uint64_t seed;
    const char *hist_out, *windows_out;
    int nphases;
    struct phase ph[MAX_PHASES];
} cfg = {
    .threads = 4, .hold_ns = 1000, .think_ns = 1000, .duration_ms = 2000,
    .warmup_ms = 200, .window_ms = 10, .timing = true, .pin = true,
    .cs_lines = 1, .seed = 1,
};

/* Written by main before the start barrier, read-only afterwards. */
static struct {
    alignas(PAD_BYTES) uint64_t start_tsc, end_tsc, window_tsc;
    size_t nwin;
    const struct lock_ops *ops;
    void *lock;
} g;

/* Shared data written inside the critical section; line 0 word 0 is the
 * counter that must end up equal to the total number of acquisitions. */
static uint64_t (*cs_data)[CACHELINE / sizeof(uint64_t)];

static pthread_barrier_t bar_ready, bar_go;

struct tstate {
    alignas(PAD_BYTES) int id, cpu;
    pthread_t th;
    uint64_t ops_total;            /* every acquisition, including warm-up */
    uint64_t ops[MAX_PHASES];      /* measured acquisitions per phase */
    struct hist *hist;             /* [nphases], TSC ticks */
    uint32_t *win;                 /* [nwin] acquisitions per window */
    struct lock_tstats lst;
};
_Static_assert(sizeof(struct tstate) % PAD_BYTES == 0, "tstate must be padded to PAD_BYTES");

static uint64_t rng_next(uint64_t *s)
{
    uint64_t x = *s;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    *s = x;
    return x * 0x2545F4914F6CDD1Dull;
}

static double rng_unit(uint64_t *s) { return (double)(rng_next(s) >> 11) * 0x1.0p-53; }

/* One sleep per call (re-armed only on early return) so a sleeping main
 * thread adds ~1 voluntary context switch, not one per millisecond. */
static void sleep_until_tsc(uint64_t t)
{
    for (;;) {
        uint64_t now = tsc_now();
        if (now >= t)
            return;
        double ns = tsc_to_ns(t - now);
        struct timespec d = { (time_t)(ns / 1e9), (long)fmod(ns, 1e9) };
        nanosleep(&d, NULL);
    }
}

static void *worker(void *arg)
{
    struct tstate *ts = arg;

    if (cfg.pin && pin_self(ts->cpu) != 0)
        die("failed to pin thread %d to cpu %d", ts->id, ts->cpu);
    ts->hist = calloc((size_t)cfg.nphases, sizeof *ts->hist);
    ts->win = calloc(g.nwin, sizeof *ts->win);
    if (!ts->hist || !ts->win)
        die("worker allocation failed");

    const struct lock_ops *ops = g.ops;
    void *l = g.lock;
    const bool timing = cfg.timing, think_exp = cfg.think_exp;
    const double long_p = cfg.hold_long_p;
    const int np = cfg.nphases, cs_lines = cfg.cs_lines;
    uint64_t rng = (cfg.seed + 1) * 0x9E3779B97F4A7C15ull + (uint64_t)ts->id * 7919u + 1;
    uint64_t ops_total = 0, ops_ph[MAX_PHASES] = { 0 };
    bool measuring = false;
    int p = 0;

    pthread_barrier_wait(&bar_ready);
    pthread_barrier_wait(&bar_go);
    const uint64_t start = g.start_tsc, end = g.end_tsc, wtsc = g.window_tsc;

    for (;;) {
        uint64_t now = tsc_now();
        if (now >= end)
            break;
        while (p + 1 < np && now >= cfg.ph[p].end_tsc)
            p++;
        const struct phase *ph = &cfg.ph[p];
        if (ts->id >= ph->active) {
            sleep_until_tsc(ph->end_tsc < end ? ph->end_tsc : end);
            continue;
        }
        if (!measuring && now >= start) {
            memset(&lk_stats, 0, sizeof lk_stats);
            measuring = true;
        }

        uint64_t hold = ph->hold_iters;
        if (long_p > 0 && rng_unit(&rng) < long_p)
            hold = ph->hold_long_iters;

        uint64_t t0 = 0, t1 = 0;
        if (timing)
            t0 = tsc_ordered();
        ops->lock(l);
        if (timing)
            t1 = tsc_ordered();
        for (int i = 0; i < cs_lines; i++)
            cs_data[i][0]++;
        spin_work(hold);
        ops->unlock(l);
        ops_total++;

        uint64_t tref = timing ? t1 : now;
        if (measuring && tref < end) {
            ops_ph[p]++;
            if (timing)
                hist_add(&ts->hist[p], t1 - t0);
            ts->win[(tref - start) / wtsc]++;
        }

        uint64_t think = ph->think_iters;
        if (think_exp && think)
            think = (uint64_t)(-log(1.0 - rng_unit(&rng)) * (double)think);
        spin_work(think);
    }

    ts->ops_total = ops_total;
    memcpy(ts->ops, ops_ph, sizeof ops_ph);
    ts->lst = lk_stats;
    return NULL;
}

/* CPU package temperature in degrees C from the first k10temp/coretemp
 * hwmon device, or NAN. Recorded before and after each run as a drift
 * covariate (boost clocks fall as a laptop heats up). */
static double read_cpu_temp_c(void)
{
    glob_t gl;
    double t = NAN;
    if (glob("/sys/class/hwmon/hwmon*/name", 0, NULL, &gl) != 0)
        return NAN;
    for (size_t i = 0; i < gl.gl_pathc && isnan(t); i++) {
        char name[32] = "", path[256];
        FILE *f = fopen(gl.gl_pathv[i], "r");
        if (!f)
            continue;
        if (!fgets(name, sizeof name, f))
            name[0] = '\0';
        fclose(f);
        if (strncmp(name, "k10temp", 7) && strncmp(name, "coretemp", 8))
            continue;
        snprintf(path, sizeof path, "%.*s/temp1_input",
                 (int)(strlen(gl.gl_pathv[i]) - strlen("/name")), gl.gl_pathv[i]);
        if ((f = fopen(path, "r"))) {
            long milli;
            if (fscanf(f, "%ld", &milli) == 1)
                t = (double)milli / 1000.0;
            fclose(f);
        }
    }
    globfree(&gl);
    return t;
}

/* Iterations of spin_work per nanosecond on this core right now. `rounds`
 * trades precision for time (5 rounds of 20M iterations is ~25 ms). */
static double measure_work_rate(int rounds, uint64_t n)
{
    double best = 1e30;
    for (int r = 0; r < rounds; r++) {
        uint64_t t0 = tsc_ordered();
        spin_work(n);
        double ns = tsc_to_ns(tsc_ordered() - t0);
        if (ns < best)
            best = ns;
    }
    return (double)n / best;
}

static double calibrate_work(void)
{
    const uint64_t n = 20u * 1000 * 1000;
    spin_work(n);   /* let the core reach its working frequency */
    return measure_work_rate(5, n);
}

static double tv_sec(struct timeval tv) { return (double)tv.tv_sec + (double)tv.tv_usec / 1e6; }

static void usage(FILE *f)
{
    fprintf(f,
"usage: bench --lock SPEC [options]\n"
"  --lock SPEC          park | spin | stp:<ns> | pthread | pthread-adaptive | none\n"
"  --threads N          worker threads (default 4)\n"
"  --hold-ns X          critical-section work per acquisition (default 1000)\n"
"  --think-ns X         work between acquisitions (default 1000)\n"
"  --duration-ms X      measured duration of a single-phase run (default 2000)\n"
"  --phase H:T:A:MS     add a phase: hold ns, think ns, active threads, duration ms\n"
"                       (repeatable; replaces --hold-ns/--think-ns/--duration-ms)\n"
"  --hold-long-ns X     bimodal hold: X ns with probability --hold-long-p\n"
"  --hold-long-p P\n"
"  --think-exp          exponential think time with the given mean (bursty arrivals)\n"
"  --warmup-ms X        unrecorded warm-up before measuring (default 200)\n"
"  --pin cores|none     cores-first pinning (default) or no pinning\n"
"  --no-timing          no per-acquisition timestamps (to measure timer overhead)\n"
"  --cs-lines N         shared cache lines written per critical section (default 1)\n"
"  --window-ms X        throughput window length (default 10)\n"
"  --iters-per-ns X     work-loop calibration override (default: calibrate)\n"
"  --seed N             RNG seed (default 1)\n"
"  --hist-out FILE      write latency histogram buckets as CSV\n"
"  --windows-out FILE   write windowed throughput as CSV\n"
"  --list-locks         print available lock specs\n");
}

static void parse_args(int argc, char **argv)
{
    enum { O_HOLD = 256, O_THINK, O_DUR, O_PHASE, O_HLONG, O_HLONGP, O_TEXP, O_WARM,
           O_PIN, O_NOTIME, O_CSL, O_WIN, O_IPN, O_SEED, O_HOUT, O_WOUT, O_LIST };
    static const struct option opts[] = {
        { "lock", required_argument, 0, 'l' },
        { "threads", required_argument, 0, 't' },
        { "hold-ns", required_argument, 0, O_HOLD },
        { "think-ns", required_argument, 0, O_THINK },
        { "duration-ms", required_argument, 0, O_DUR },
        { "phase", required_argument, 0, O_PHASE },
        { "hold-long-ns", required_argument, 0, O_HLONG },
        { "hold-long-p", required_argument, 0, O_HLONGP },
        { "think-exp", no_argument, 0, O_TEXP },
        { "warmup-ms", required_argument, 0, O_WARM },
        { "pin", required_argument, 0, O_PIN },
        { "no-timing", no_argument, 0, O_NOTIME },
        { "cs-lines", required_argument, 0, O_CSL },
        { "window-ms", required_argument, 0, O_WIN },
        { "iters-per-ns", required_argument, 0, O_IPN },
        { "seed", required_argument, 0, O_SEED },
        { "hist-out", required_argument, 0, O_HOUT },
        { "windows-out", required_argument, 0, O_WOUT },
        { "list-locks", no_argument, 0, O_LIST },
        { "help", no_argument, 0, 'h' },
        { 0, 0, 0, 0 },
    };
    int c;
    while ((c = getopt_long(argc, argv, "l:t:h", opts, NULL)) != -1) {
        switch (c) {
        case 'l': cfg.lock_spec = optarg; break;
        case 't': cfg.threads = atoi(optarg); break;
        case O_HOLD: cfg.hold_ns = atof(optarg); break;
        case O_THINK: cfg.think_ns = atof(optarg); break;
        case O_DUR: cfg.duration_ms = atof(optarg); break;
        case O_PHASE: {
            if (cfg.nphases == MAX_PHASES)
                die("at most %d phases", MAX_PHASES);
            struct phase *ph = &cfg.ph[cfg.nphases++];
            if (sscanf(optarg, "%lf:%lf:%d:%lf", &ph->hold_ns, &ph->think_ns,
                       &ph->active, &ph->dur_ms) != 4)
                die("bad --phase '%s' (want HOLD_NS:THINK_NS:ACTIVE:MS)", optarg);
            break;
        }
        case O_HLONG: cfg.hold_long_ns = atof(optarg); break;
        case O_HLONGP: cfg.hold_long_p = atof(optarg); break;
        case O_TEXP: cfg.think_exp = true; break;
        case O_WARM: cfg.warmup_ms = atof(optarg); break;
        case O_PIN:
            if (!strcmp(optarg, "cores")) cfg.pin = true;
            else if (!strcmp(optarg, "none")) cfg.pin = false;
            else die("--pin must be cores or none");
            break;
        case O_NOTIME: cfg.timing = false; break;
        case O_CSL: cfg.cs_lines = atoi(optarg); break;
        case O_WIN: cfg.window_ms = atof(optarg); break;
        case O_IPN: cfg.iters_per_ns = atof(optarg); break;
        case O_SEED: cfg.seed = strtoull(optarg, NULL, 10); break;
        case O_HOUT: cfg.hist_out = optarg; break;
        case O_WOUT: cfg.windows_out = optarg; break;
        case O_LIST: lock_list(stdout); exit(0);
        case 'h': usage(stdout); exit(0);
        default: usage(stderr); exit(2);
        }
    }
    if (!cfg.lock_spec) {
        usage(stderr);
        exit(2);
    }
}

static double jain(const uint64_t *x, int n)
{
    double s = 0, s2 = 0;
    for (int i = 0; i < n; i++) {
        s += (double)x[i];
        s2 += (double)x[i] * (double)x[i];
    }
    return s2 > 0 ? s * s / ((double)n * s2) : 1.0;
}

int main(int argc, char **argv)
{
    parse_args(argc, argv);
    tsc_init();
    if (cfg.iters_per_ns <= 0)
        cfg.iters_per_ns = calibrate_work();

    if (cfg.nphases == 0) {
        cfg.nphases = 1;
        cfg.ph[0] = (struct phase){ .hold_ns = cfg.hold_ns, .think_ns = cfg.think_ns,
                                    .active = cfg.threads, .dur_ms = cfg.duration_ms };
    }
    if (cfg.threads < 1 || cfg.threads > MAX_THREADS)
        die("--threads must be 1..%d", MAX_THREADS);
    if (cfg.cs_lines < 1 || cfg.cs_lines > 64)
        die("--cs-lines must be 1..64");
    if (cfg.hold_long_p > 0 && cfg.hold_long_ns <= 0)
        die("--hold-long-p needs --hold-long-ns");

    double total_ms = 0;
    for (int p = 0; p < cfg.nphases; p++) {
        struct phase *ph = &cfg.ph[p];
        if (ph->active < 1 || ph->active > cfg.threads)
            die("phase %d: active threads must be 1..%d", p, cfg.threads);
        ph->hold_iters = (uint64_t)(ph->hold_ns * cfg.iters_per_ns + 0.5);
        ph->hold_long_iters = (uint64_t)(cfg.hold_long_ns * cfg.iters_per_ns + 0.5);
        ph->think_iters = (uint64_t)(ph->think_ns * cfg.iters_per_ns + 0.5);
        total_ms += ph->dur_ms;
    }

    struct lock_params lp;
    g.ops = lock_lookup(cfg.lock_spec, &lp);
    if (!g.ops)
        die("unknown lock spec '%s' (try --list-locks)", cfg.lock_spec);
    if (!strcmp(g.ops->name, "none") && cfg.threads != 1)
        die("lock 'none' is only valid with --threads 1");
    g.lock = lock_create(g.ops, &lp);

    size_t cs_bytes = ((size_t)cfg.cs_lines * CACHELINE + PAD_BYTES - 1) / PAD_BYTES * PAD_BYTES;
    cs_data = aligned_alloc(PAD_BYTES, cs_bytes);
    if (!cs_data)
        die("allocation failed");
    memset(cs_data, 0, cs_bytes);

    g.window_tsc = ns_to_tsc(cfg.window_ms * 1e6);
    g.nwin = (size_t)ceil(total_ms / cfg.window_ms) + 1;

    int order[MAX_THREADS];
    int ncpu = topo_cpu_order(order, MAX_THREADS);
    if (cfg.pin && ncpu < 1)
        die("could not read CPU topology");

    struct tstate *ts = aligned_alloc(PAD_BYTES, (size_t)cfg.threads * sizeof *ts);
    if (!ts)
        die("allocation failed");
    memset(ts, 0, (size_t)cfg.threads * sizeof *ts);

    double temp_before = read_cpu_temp_c();
    pthread_barrier_init(&bar_ready, NULL, (unsigned)cfg.threads + 1);
    pthread_barrier_init(&bar_go, NULL, (unsigned)cfg.threads + 1);
    for (int i = 0; i < cfg.threads; i++) {
        ts[i].id = i;
        ts[i].cpu = cfg.pin ? order[i % ncpu] : -1;
        if (pthread_create(&ts[i].th, NULL, worker, &ts[i]) != 0)
            die("pthread_create failed");
    }

    pthread_barrier_wait(&bar_ready);
    g.start_tsc = tsc_now() + ns_to_tsc(cfg.warmup_ms * 1e6 + 1e6);
    uint64_t t = g.start_tsc;
    for (int p = 0; p < cfg.nphases; p++) {
        cfg.ph[p].start_tsc = t;
        t += ns_to_tsc(cfg.ph[p].dur_ms * 1e6);
        cfg.ph[p].end_tsc = t;
    }
    g.end_tsc = t;
    pthread_barrier_wait(&bar_go);

    struct rusage r0, r1;
    sleep_until_tsc(g.start_tsc);
    getrusage(RUSAGE_SELF, &r0);
    sleep_until_tsc(g.end_tsc);
    getrusage(RUSAGE_SELF, &r1);
    for (int i = 0; i < cfg.threads; i++)
        pthread_join(ts[i].th, NULL);
    double temp_after = read_cpu_temp_c();
    /* Work-loop rate right after the run, while the CPU is still warm. A
     * drop versus iters_per_ns means the core clock fell during the run, so
     * the same iteration count took longer than its nominal ns. */
    double ipn_after = measure_work_rate(3, 5u * 1000 * 1000);

    /* ---- aggregate ---- */
    uint64_t ops_all = 0, ops_measured = 0;
    struct lock_tstats lst = { 0 };
    for (int i = 0; i < cfg.threads; i++) {
        ops_all += ts[i].ops_total;
        for (int p = 0; p < cfg.nphases; p++)
            ops_measured += ts[i].ops[p];
        lst.slow += ts[i].lst.slow;
        lst.spin_acq += ts[i].lst.spin_acq;
        lst.parks += ts[i].lst.parks;
        lst.wakes += ts[i].lst.wakes;
        lst.spin_tsc += ts[i].lst.spin_tsc;
    }
    bool counter_ok = cs_data[0][0] == ops_all;
    double wall_s = total_ms / 1e3;
    double user_s = tv_sec(r1.ru_utime) - tv_sec(r0.ru_utime);
    double sys_s = tv_sec(r1.ru_stime) - tv_sec(r0.ru_stime);
    long vcsw = r1.ru_nvcsw - r0.ru_nvcsw, ivcsw = r1.ru_nivcsw - r0.ru_nivcsw;

    struct hist *merged = calloc((size_t)cfg.nphases, sizeof *merged);
    if (!merged)
        die("allocation failed");
    for (int p = 0; p < cfg.nphases; p++)
        for (int i = 0; i < cfg.threads; i++)
            hist_merge(&merged[p], &ts[i].hist[p]);

    /* ---- JSON summary ---- */
    printf("{\"tool\":\"bench\",\"lock\":\"%s\",\"threads\":%d,\"pin\":\"%s\",\"timing\":%s,",
           cfg.lock_spec, cfg.threads, cfg.pin ? "cores" : "none", cfg.timing ? "true" : "false");
    printf("\"warmup_ms\":%g,\"duration_ms\":%g,\"window_ms\":%g,\"cs_lines\":%d,",
           cfg.warmup_ms, total_ms, cfg.window_ms, cfg.cs_lines);
    printf("\"hold_long_ns\":%g,\"hold_long_p\":%g,\"think_exp\":%s,\"seed\":%llu,",
           cfg.hold_long_ns, cfg.hold_long_p, cfg.think_exp ? "true" : "false",
           (unsigned long long)cfg.seed);
    printf("\"tsc_hz\":%.0f,\"iters_per_ns\":%.5f,\"iters_per_ns_after\":%.5f,\"compiler\":\"%s\",",
           tsc_hz, cfg.iters_per_ns, ipn_after, __VERSION__);
    if (isnan(temp_before) || isnan(temp_after))
        printf("\"temp_c_before\":null,\"temp_c_after\":null,");
    else
        printf("\"temp_c_before\":%.1f,\"temp_c_after\":%.1f,", temp_before, temp_after);
    printf("\"cpus\":[");
    for (int i = 0; i < cfg.threads; i++)
        printf("%s%d", i ? "," : "", ts[i].cpu);
    printf("],");
    printf("\"ops_total\":%llu,\"ops_measured\":%llu,\"throughput_ops_s\":%.1f,\"counter_ok\":%s,",
           (unsigned long long)ops_all, (unsigned long long)ops_measured,
           (double)ops_measured / wall_s, counter_ok ? "true" : "false");
    printf("\"cpu_user_s\":%.4f,\"cpu_sys_s\":%.4f,\"cpu_util\":%.3f,\"vcsw\":%ld,\"ivcsw\":%ld,",
           user_s, sys_s, (user_s + sys_s) / wall_s, vcsw, ivcsw);
    printf("\"lock_stats\":{\"slow\":%llu,\"spin_acq\":%llu,\"parks\":%llu,\"wakes\":%llu,\"spin_ms\":%.3f},",
           (unsigned long long)lst.slow, (unsigned long long)lst.spin_acq,
           (unsigned long long)lst.parks, (unsigned long long)lst.wakes,
           tsc_to_ns(lst.spin_tsc) / 1e6);
    printf("\"phases\":[");
    for (int p = 0; p < cfg.nphases; p++) {
        const struct phase *ph = &cfg.ph[p];
        const struct hist *h = &merged[p];
        uint64_t per[MAX_THREADS], ops_p = 0;
        for (int i = 0; i < ph->active; i++) {
            per[i] = ts[i].ops[p];
            ops_p += per[i];
        }
        printf("%s{\"idx\":%d,\"hold_ns\":%g,\"think_ns\":%g,\"active\":%d,\"duration_ms\":%g,",
               p ? "," : "", p, ph->hold_ns, ph->think_ns, ph->active, ph->dur_ms);
        printf("\"ops\":%llu,\"throughput_ops_s\":%.1f,\"jain\":%.4f,",
               (unsigned long long)ops_p, (double)ops_p / (ph->dur_ms / 1e3), jain(per, ph->active));
        if (cfg.timing && h->n)
            printf("\"lat_ns\":{\"n\":%llu,\"mean\":%.1f,\"min\":%.1f,\"p50\":%.1f,\"p90\":%.1f,"
                   "\"p99\":%.1f,\"p999\":%.1f,\"max\":%.1f},",
                   (unsigned long long)h->n, tsc_to_ns(h->sum) / (double)h->n, tsc_to_ns(h->min),
                   tsc_to_ns(hist_quantile(h, 0.50)), tsc_to_ns(hist_quantile(h, 0.90)),
                   tsc_to_ns(hist_quantile(h, 0.99)), tsc_to_ns(hist_quantile(h, 0.999)),
                   tsc_to_ns(h->max));
        printf("\"per_thread_ops\":[");
        for (int i = 0; i < cfg.threads; i++)
            printf("%s%llu", i ? "," : "", (unsigned long long)ts[i].ops[p]);
        printf("]}");
    }
    printf("]}\n");

    if (cfg.hist_out) {
        FILE *f = fopen(cfg.hist_out, "w");
        if (!f)
            die("cannot write %s", cfg.hist_out);
        fprintf(f, "phase,lo_ns,hi_ns,count\n");
        for (int p = 0; p < cfg.nphases; p++)
            for (unsigned i = 0; i < HIST_BUCKETS; i++)
                if (merged[p].b[i])
                    fprintf(f, "%d,%.2f,%.2f,%llu\n", p, tsc_to_ns(hist_lo(i)),
                            tsc_to_ns(hist_hi(i)), (unsigned long long)merged[p].b[i]);
        fclose(f);
    }
    if (cfg.windows_out) {
        FILE *f = fopen(cfg.windows_out, "w");
        if (!f)
            die("cannot write %s", cfg.windows_out);
        fprintf(f, "window,t_ms,phase,ops\n");
        for (size_t w = 0; w + 1 < g.nwin; w++) {
            uint64_t wstart = g.start_tsc + (uint64_t)w * g.window_tsc, sum = 0;
            int p = 0;
            while (p + 1 < cfg.nphases && wstart >= cfg.ph[p].end_tsc)
                p++;
            for (int i = 0; i < cfg.threads; i++)
                sum += ts[i].win[w];
            fprintf(f, "%zu,%.3f,%d,%llu\n", w, (double)w * cfg.window_ms, p,
                    (unsigned long long)sum);
        }
        fclose(f);
    }

    lock_free(g.ops, g.lock);
    return counter_ok ? 0 : 1;
}
