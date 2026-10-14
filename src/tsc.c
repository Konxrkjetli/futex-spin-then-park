#include "tsc.h"

#include <stdlib.h>
#include <time.h>

double tsc_hz;
double tsc_ns_per_tick;

static uint64_t mono_raw_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static int cmp_double(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

void tsc_init(void)
{
    if (tsc_hz > 0)
        return;

    const char *env = getenv("FL_TSC_HZ");
    if (env && atof(env) > 0) {
        tsc_hz = atof(env);
    } else {
        double est[5];
        for (int r = 0; r < 5; r++) {
            uint64_t n0 = mono_raw_ns(), t0 = tsc_ordered();
            struct timespec d = { 0, 50 * 1000 * 1000 };
            nanosleep(&d, NULL);
            uint64_t n1 = mono_raw_ns(), t1 = tsc_ordered();
            est[r] = (double)(t1 - t0) * 1e9 / (double)(n1 - n0);
        }
        qsort(est, 5, sizeof est[0], cmp_double);
        tsc_hz = est[2];
    }
    tsc_ns_per_tick = 1e9 / tsc_hz;
}
