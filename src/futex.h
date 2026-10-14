#ifndef FL_FUTEX_H
#define FL_FUTEX_H

#include <linux/futex.h>
#include <stdatomic.h>
#include <stdint.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

/* Thin wrappers over the futex system call. All threads share one process,
 * so the PRIVATE variants are used (no cross-process hashing). */

/* Sleeps only if *addr still equals `expected` (checked atomically by the
 * kernel, which prevents lost wake-ups). Returns 0 when woken, -1 with errno
 * EAGAIN if the value had already changed, or EINTR. Callers re-check state
 * in a loop either way. */
static inline long futex_wait(_Atomic uint32_t *addr, uint32_t expected)
{
    return syscall(SYS_futex, (void *)addr, FUTEX_WAIT_PRIVATE, expected, NULL, NULL, 0);
}

/* Wakes up to `n` waiters; returns how many were woken. */
static inline long futex_wake(_Atomic uint32_t *addr, int n)
{
    return syscall(SYS_futex, (void *)addr, FUTEX_WAKE_PRIVATE, n, NULL, NULL, 0);
}

#endif
