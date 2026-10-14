#ifndef FL_HIST_H
#define FL_HIST_H

#include <stdint.h>

/* Log-linear histogram (HdrHistogram-style) over raw TSC ticks.
 * Values below 256 get their own bucket; above that every power-of-two range
 * is split into 128 sub-buckets, so a bucket spans at most 1/128 (0.8%) of its
 * value. Fixed memory (~59 KB), O(1) insert, no sample cap, mergeable across
 * threads and runs. */

#define HIST_SUB_BITS 8
#define HIST_SUB      (1u << HIST_SUB_BITS)          /* 256 */
#define HIST_HALF     (1u << (HIST_SUB_BITS - 1))    /* 128 */
#define HIST_BUCKETS  ((64 - HIST_SUB_BITS + 2) * HIST_HALF)

struct hist {
    uint64_t n, sum, max;
    uint64_t min;      /* valid only when n > 0 */
    uint64_t b[HIST_BUCKETS];
};

static inline unsigned hist_index(uint64_t v)
{
    if (v < HIST_SUB)
        return (unsigned)v;
    unsigned msb = 63u - (unsigned)__builtin_clzll(v);
    unsigned e = msb - HIST_SUB_BITS + 1;
    return e * HIST_HALF + (unsigned)(v >> e);
}

static inline void hist_add(struct hist *h, uint64_t v)
{
    h->b[hist_index(v)]++;
    if (h->n == 0 || v < h->min)
        h->min = v;
    if (v > h->max)
        h->max = v;
    h->n++;
    h->sum += v;
}

uint64_t hist_lo(unsigned idx);   /* smallest value in bucket idx */
uint64_t hist_hi(unsigned idx);   /* largest value in bucket idx */
void hist_merge(struct hist *dst, const struct hist *src);
/* Nearest-rank quantile; returns the bucket midpoint, clamped to [min, max]. */
uint64_t hist_quantile(const struct hist *h, double q);

#endif
