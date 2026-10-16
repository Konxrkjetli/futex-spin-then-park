/* Real-application benchmark (Phase 4 stretch): SQLite with one connection
 * shared by T threads in serialized mode, so every API call takes the
 * connection's (recursive) mutex. Run as is for glibc's mutex, or under the
 * LD_PRELOAD shim (src/shim.c) to put a futex-lab lock behind it.
 *
 * Each thread repeats: pick a random key; with probability --write-pct run
 * UPDATE t SET v = v + 1 WHERE k = ?, else SELECT v FROM t WHERE k = ?.
 * Latency = one bind+step+reset, stamped on the TSC. Mutual-exclusion check:
 * at the end SUM(v) must equal the number of UPDATEs executed (counter_ok).
 *
 * Output: one JSON object shaped like bench's (single phase), optional
 * histogram and window CSVs in bench's formats. */

#include <dlfcn.h>
#include <getopt.h>
#include <math.h>
#include <pthread.h>
#include <sqlite3.h>
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

#define MAX_THREADS 128

static struct {
    int threads, rows, write_pct;
    double duration_ms, warmup_ms, window_ms;
    bool pin;
    uint64_t seed;
    const char *hist_out, *windows_out;
} cfg = { .threads = 4, .rows = 10000, .write_pct = 10, .duration_ms = 2000,
          .warmup_ms = 200, .window_ms = 10, .pin = true, .seed = 1 };

static sqlite3 *db;
static uint64_t start_tsc, end_tsc, window_tsc;
static size_t nwin;
static pthread_barrier_t bar;
static void (*shim_tstats)(struct lock_tstats *);

struct tstate {
    alignas(PAD_BYTES) int id, cpu;
    pthread_t th;
    uint64_t ops, updates, errors;
    struct hist hist;
    uint32_t *win;
    struct lock_tstats lst;
};

static void check(int rc, const char *what)
{
    if (rc != SQLITE_OK && rc != SQLITE_DONE && rc != SQLITE_ROW)
        die("sqlite %s: %s", what, sqlite3_errmsg(db));
}

static void *worker(void *arg)
{
    struct tstate *ts = arg;
    if (cfg.pin && pin_self(ts->cpu) != 0)
        die("cannot pin thread %d to cpu %d", ts->id, ts->cpu);
    ts->win = calloc(nwin, sizeof *ts->win);
    sqlite3_stmt *sel, *upd;
    check(sqlite3_prepare_v2(db, "SELECT v FROM t WHERE k = ?", -1, &sel, NULL), "prepare");
    check(sqlite3_prepare_v2(db, "UPDATE t SET v = v + 1 WHERE k = ?", -1, &upd, NULL), "prepare");
    uint64_t rng = (cfg.seed + 1) * 0x9E3779B97F4A7C15ull + (uint64_t)ts->id * 7919u + 1;
    bool measuring = false;
    pthread_barrier_wait(&bar);
    pthread_barrier_wait(&bar);

    for (;;) {
        uint64_t now = tsc_now();
        if (now >= end_tsc)
            break;
        if (!measuring && now >= start_tsc) {
            if (shim_tstats)
                memset(&ts->lst, 0, sizeof ts->lst);   /* baseline taken below */
            measuring = true;
            if (shim_tstats)
                shim_tstats(&ts->lst);
        }
        rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
        int key = (int)(rng % (uint64_t)cfg.rows) + 1;
        bool write = (int)((rng >> 32) % 100) < cfg.write_pct;
        sqlite3_stmt *st = write ? upd : sel;
        uint64_t t0 = tsc_ordered();
        sqlite3_bind_int(st, 1, key);
        int rc = sqlite3_step(st);
        sqlite3_reset(st);
        uint64_t t1 = tsc_ordered();
        if (rc != SQLITE_DONE && rc != SQLITE_ROW)
            ts->errors++;
        if (write && rc == SQLITE_DONE)
            ts->updates++;                 /* counted for the SUM check */
        if (measuring && t1 < end_tsc) {
            ts->ops++;
            hist_add(&ts->hist, t1 - t0);
            ts->win[(t1 - start_tsc) / window_tsc]++;
        }
    }
    if (shim_tstats) {
        struct lock_tstats endst;
        shim_tstats(&endst);
        ts->lst.slow = endst.slow - ts->lst.slow;
        ts->lst.spin_acq = endst.spin_acq - ts->lst.spin_acq;
        ts->lst.parks = endst.parks - ts->lst.parks;
        ts->lst.wakes = endst.wakes - ts->lst.wakes;
        ts->lst.budget_tsc = endst.budget_tsc - ts->lst.budget_tsc;
    }
    sqlite3_finalize(sel);
    sqlite3_finalize(upd);
    return NULL;
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

static double tv_sec(struct timeval tv) { return (double)tv.tv_sec + (double)tv.tv_usec / 1e6; }

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

int main(int argc, char **argv)
{
    static const struct option opts[] = {
        { "threads", required_argument, 0, 't' }, { "rows", required_argument, 0, 'r' },
        { "write-pct", required_argument, 0, 'w' }, { "duration-ms", required_argument, 0, 'd' },
        { "warmup-ms", required_argument, 0, 'u' }, { "window-ms", required_argument, 0, 'W' },
        { "pin", required_argument, 0, 'p' }, { "seed", required_argument, 0, 's' },
        { "hist-out", required_argument, 0, 'H' }, { "windows-out", required_argument, 0, 'O' },
        { 0, 0, 0, 0 },
    };
    int c;
    while ((c = getopt_long(argc, argv, "t:", opts, NULL)) != -1) {
        switch (c) {
        case 't': cfg.threads = atoi(optarg); break;
        case 'r': cfg.rows = atoi(optarg); break;
        case 'w': cfg.write_pct = atoi(optarg); break;
        case 'd': cfg.duration_ms = atof(optarg); break;
        case 'u': cfg.warmup_ms = atof(optarg); break;
        case 'W': cfg.window_ms = atof(optarg); break;
        case 'p': cfg.pin = strcmp(optarg, "none") != 0; break;
        case 's': cfg.seed = strtoull(optarg, NULL, 10); break;
        case 'H': cfg.hist_out = optarg; break;
        case 'O': cfg.windows_out = optarg; break;
        default:
            fprintf(stderr, "usage: sqlbench [--threads N] [--rows N] [--write-pct P] [--duration-ms X] "
                    "[--warmup-ms X] [--pin cores|none] [--seed N] [--hist-out F] [--windows-out F]\n");
            return 2;
        }
    }
    if (cfg.threads < 1 || cfg.threads > MAX_THREADS || cfg.rows < 1)
        die("bad arguments");
    tsc_init();

    int (*active)(void) = (int (*)(void))dlsym(RTLD_DEFAULT, "fl_shim_active");
    void (*info)(char *, size_t) = (void (*)(char *, size_t))dlsym(RTLD_DEFAULT, "fl_shim_info");
    shim_tstats = (void (*)(struct lock_tstats *))dlsym(RTLD_DEFAULT, "fl_shim_tstats");
    bool shimmed = active && active();
    const char *spec = getenv("FL_SHIM_LOCK");
    if (spec && *spec && !shimmed)
        die("FL_SHIM_LOCK is set but the shim is not loaded (LD_PRELOAD?)");

    if (!sqlite3_threadsafe())
        die("this SQLite was built without thread safety");
    check(sqlite3_open_v2(":memory:", &db, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                          SQLITE_OPEN_FULLMUTEX, NULL), "open");
    check(sqlite3_exec(db, "CREATE TABLE t(k INTEGER PRIMARY KEY, v INTEGER NOT NULL, pad TEXT);"
                       "BEGIN;", NULL, NULL, NULL), "create");
    sqlite3_stmt *ins;
    check(sqlite3_prepare_v2(db, "INSERT INTO t VALUES (?, 0, ?)", -1, &ins, NULL), "prepare");
    for (int k = 1; k <= cfg.rows; k++) {
        sqlite3_bind_int(ins, 1, k);
        sqlite3_bind_text(ins, 2, "futex-lab-padding-row-0123456789", -1, SQLITE_STATIC);
        check(sqlite3_step(ins), "insert");
        sqlite3_reset(ins);
    }
    sqlite3_finalize(ins);
    check(sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL), "commit");

    window_tsc = ns_to_tsc(cfg.window_ms * 1e6);
    nwin = (size_t)ceil(cfg.duration_ms / cfg.window_ms) + 1;
    int order[MAX_THREADS * 2];
    int ncpu = topo_cpu_order(order, MAX_THREADS * 2);
    struct tstate *ts = aligned_alloc(PAD_BYTES, (size_t)cfg.threads * sizeof *ts);
    memset(ts, 0, (size_t)cfg.threads * sizeof *ts);
    pthread_barrier_init(&bar, NULL, (unsigned)cfg.threads + 1);
    for (int i = 0; i < cfg.threads; i++) {
        ts[i].id = i;
        ts[i].cpu = cfg.pin ? order[i % ncpu] : -1;
        if (pthread_create(&ts[i].th, NULL, worker, &ts[i]) != 0)
            die("pthread_create failed");
    }
    pthread_barrier_wait(&bar);
    start_tsc = tsc_now() + ns_to_tsc(cfg.warmup_ms * 1e6 + 1e6);
    end_tsc = start_tsc + ns_to_tsc(cfg.duration_ms * 1e6);
    pthread_barrier_wait(&bar);
    struct rusage r0, r1;
    sleep_until_tsc(start_tsc);
    getrusage(RUSAGE_SELF, &r0);
    sleep_until_tsc(end_tsc);
    getrusage(RUSAGE_SELF, &r1);
    for (int i = 0; i < cfg.threads; i++)
        pthread_join(ts[i].th, NULL);

    uint64_t ops = 0, updates = 0, errors = 0, per[MAX_THREADS];
    struct hist *h = calloc(1, sizeof *h);
    struct lock_tstats lst = { 0 };
    for (int i = 0; i < cfg.threads; i++) {
        ops += ts[i].ops;
        updates += ts[i].updates;
        errors += ts[i].errors;
        per[i] = ts[i].ops;
        hist_merge(h, &ts[i].hist);
        lst.slow += ts[i].lst.slow;
        lst.spin_acq += ts[i].lst.spin_acq;
        lst.parks += ts[i].lst.parks;
        lst.wakes += ts[i].lst.wakes;
        lst.budget_tsc += ts[i].lst.budget_tsc;
    }
    sqlite3_stmt *sum;
    check(sqlite3_prepare_v2(db, "SELECT SUM(v) FROM t", -1, &sum, NULL), "prepare");
    check(sqlite3_step(sum), "sum");
    long long total_v = sqlite3_column_int64(sum, 0);
    sqlite3_finalize(sum);
    bool counter_ok = (uint64_t)total_v == updates && errors == 0;

    char shim_info[1024] = "null";
    if (shimmed && info)
        info(shim_info, sizeof shim_info);
    double wall = cfg.duration_ms / 1e3;
    double user_s = tv_sec(r1.ru_utime) - tv_sec(r0.ru_utime);
    double sys_s = tv_sec(r1.ru_stime) - tv_sec(r0.ru_stime);
    printf("{\"tool\":\"sqlbench\",\"lock\":\"%s\",\"shim\":%s,\"sqlite\":\"%s\",\"threads\":%d,"
           "\"rows\":%d,\"write_pct\":%d,\"pin\":\"%s\",\"warmup_ms\":%g,\"duration_ms\":%g,\"seed\":%llu,"
           "\"tsc_hz\":%.0f,\"ops_measured\":%llu,\"throughput_ops_s\":%.1f,\"updates\":%llu,"
           "\"sum_v\":%lld,\"errors\":%llu,\"counter_ok\":%s,\"cpu_user_s\":%.4f,\"cpu_sys_s\":%.4f,"
           "\"cpu_util\":%.3f,\"vcsw\":%ld,\"ivcsw\":%ld,",
           shimmed ? spec : "native", shim_info, sqlite3_libversion(), cfg.threads, cfg.rows,
           cfg.write_pct, cfg.pin ? "cores" : "none", cfg.warmup_ms, cfg.duration_ms,
           (unsigned long long)cfg.seed, tsc_hz, (unsigned long long)ops, (double)ops / wall,
           (unsigned long long)updates, total_v, (unsigned long long)errors,
           counter_ok ? "true" : "false", user_s, sys_s, (user_s + sys_s) / wall,
           r1.ru_nvcsw - r0.ru_nvcsw, r1.ru_nivcsw - r0.ru_nivcsw);
    printf("\"lock_stats\":{\"slow\":%llu,\"spin_acq\":%llu,\"parks\":%llu,\"wakes\":%llu,\"budget_mean_ns\":%.1f},",
           (unsigned long long)lst.slow, (unsigned long long)lst.spin_acq, (unsigned long long)lst.parks,
           (unsigned long long)lst.wakes, lst.slow ? tsc_to_ns(lst.budget_tsc) / (double)lst.slow : 0.0);
    printf("\"phases\":[{\"idx\":0,\"active\":%d,\"duration_ms\":%g,\"ops\":%llu,\"throughput_ops_s\":%.1f,"
           "\"jain\":%.4f,", cfg.threads, cfg.duration_ms, (unsigned long long)ops, (double)ops / wall,
           jain(per, cfg.threads));
    if (h->n)
        printf("\"lat_ns\":{\"n\":%llu,\"mean\":%.1f,\"min\":%.1f,\"p50\":%.1f,\"p90\":%.1f,\"p99\":%.1f,"
               "\"p999\":%.1f,\"max\":%.1f},", (unsigned long long)h->n, tsc_to_ns(h->sum) / (double)h->n,
               tsc_to_ns(h->min), tsc_to_ns(hist_quantile(h, 0.5)), tsc_to_ns(hist_quantile(h, 0.9)),
               tsc_to_ns(hist_quantile(h, 0.99)), tsc_to_ns(hist_quantile(h, 0.999)), tsc_to_ns(h->max));
    printf("\"per_thread_ops\":[");
    for (int i = 0; i < cfg.threads; i++)
        printf("%s%llu", i ? "," : "", (unsigned long long)per[i]);
    printf("],\"per_thread_p99_ns\":[");
    for (int i = 0; i < cfg.threads; i++)
        printf("%s%.1f", i ? "," : "", ts[i].hist.n ? tsc_to_ns(hist_quantile(&ts[i].hist, 0.99)) : -1.0);
    printf("]}]}\n");

    if (cfg.hist_out) {
        FILE *f = fopen(cfg.hist_out, "w");
        if (!f)
            die("cannot write %s", cfg.hist_out);
        fprintf(f, "phase,lo_ns,hi_ns,count\n");
        for (unsigned i = 0; i < HIST_BUCKETS; i++)
            if (h->b[i])
                fprintf(f, "0,%.2f,%.2f,%llu\n", tsc_to_ns(hist_lo(i)), tsc_to_ns(hist_hi(i)),
                        (unsigned long long)h->b[i]);
        fclose(f);
    }
    if (cfg.windows_out) {
        FILE *f = fopen(cfg.windows_out, "w");
        if (!f)
            die("cannot write %s", cfg.windows_out);
        fprintf(f, "window,t_ms,phase,ops\n");
        for (size_t w = 0; w + 1 < nwin; w++) {
            uint64_t sumw = 0;
            for (int i = 0; i < cfg.threads; i++)
                sumw += ts[i].win[w];
            fprintf(f, "%zu,%.3f,0,%llu\n", w, (double)w * cfg.window_ms, (unsigned long long)sumw);
        }
        fclose(f);
    }
    sqlite3_close(db);
    return counter_ok ? 0 : 1;
}
