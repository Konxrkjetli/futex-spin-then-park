#ifndef FL_COMMON_H
#define FL_COMMON_H

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define CACHELINE 64
/* Shared objects are aligned and padded to two lines so the adjacent-line
 * prefetcher never couples one object with its neighbour. */
#define PAD_BYTES 128

#define likely(x)   __builtin_expect(!!(x), 1)
#define unlikely(x) __builtin_expect(!!(x), 0)

static inline void cpu_relax(void) { __builtin_ia32_pause(); }

/* Calibrated busy work. The empty asm makes `i` opaque on every iteration,
 * so the compiler can neither delete the loop nor collapse it into one step.
 * Runs at roughly one iteration per core cycle. */
static inline void spin_work(uint64_t iters)
{
    for (uint64_t i = 0; i < iters; i++)
        __asm__ __volatile__("" : "+r"(i));
}

__attribute__((noreturn, format(printf, 1, 2)))
static inline void die(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(2);
}

#endif
