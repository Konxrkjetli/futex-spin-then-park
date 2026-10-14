#include "hist.h"

#include <math.h>

uint64_t hist_lo(unsigned idx)
{
    if (idx < HIST_SUB)
        return idx;
    unsigned e = idx / HIST_HALF - 1;
    uint64_t m = idx - e * HIST_HALF;
    return m << e;
}

uint64_t hist_hi(unsigned idx)
{
    if (idx < HIST_SUB)
        return idx;
    unsigned e = idx / HIST_HALF - 1;
    uint64_t m = idx - e * HIST_HALF;
    return ((m + 1) << e) - 1;
}

void hist_merge(struct hist *dst, const struct hist *src)
{
    if (src->n == 0)
        return;
    for (unsigned i = 0; i < HIST_BUCKETS; i++)
        dst->b[i] += src->b[i];
    if (dst->n == 0 || src->min < dst->min)
        dst->min = src->min;
    if (src->max > dst->max)
        dst->max = src->max;
    dst->n += src->n;
    dst->sum += src->sum;
}

uint64_t hist_quantile(const struct hist *h, double q)
{
    if (h->n == 0)
        return 0;
    if (q >= 1.0)
        return h->max;
    uint64_t rank = (uint64_t)ceil(q * (double)h->n);
    if (rank < 1)
        rank = 1;
    uint64_t cum = 0;
    for (unsigned i = 0; i < HIST_BUCKETS; i++) {
        cum += h->b[i];
        if (cum >= rank) {
            uint64_t mid = hist_lo(i) + (hist_hi(i) - hist_lo(i)) / 2;
            if (mid < h->min)
                mid = h->min;
            if (mid > h->max)
                mid = h->max;
            return mid;
        }
    }
    return h->max;
}
