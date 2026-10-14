#ifndef FL_TSC_H
#define FL_TSC_H

#include <stdint.h>
#include <x86intrin.h>

/* Time-stamp counter helpers. The TSC on this machine is invariant
 * (constant_tsc, nonstop_tsc) and is the kernel's clocksource, so it ticks at
 * a fixed rate regardless of core frequency and is synchronised across cores
 * (checked by `calib tsc-sync`). */

extern double tsc_hz;          /* ticks per second, set by tsc_init() */
extern double tsc_ns_per_tick;

/* Calibrates against CLOCK_MONOTONIC_RAW (~250 ms), or takes FL_TSC_HZ from
 * the environment so repeated runs share one calibration. */
void tsc_init(void);

/* Cheap read; may be reordered with neighbouring instructions. */
static inline uint64_t tsc_now(void) { return __rdtsc(); }

/* Read fenced on both sides: earlier instructions have completed and later
 * ones have not started. Used for latency timestamps. */
static inline uint64_t tsc_ordered(void)
{
    _mm_lfence();
    uint64_t t = __rdtsc();
    _mm_lfence();
    return t;
}

static inline uint64_t ns_to_tsc(double ns) { return (uint64_t)(ns * tsc_hz / 1e9 + 0.5); }
static inline double tsc_to_ns(uint64_t t) { return (double)t * tsc_ns_per_tick; }

#endif
