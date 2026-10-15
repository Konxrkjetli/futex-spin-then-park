#ifndef FL_CGROUP_H
#define FL_CGROUP_H

#include <stddef.h>

/* cgroup v2 CPU bandwidth files of the calling process's own cgroup.
 * Used by the throttle-aware lock (to detect throttling) and by the bench
 * (to record throttling counters around the measured window). */

struct cg_stat {
    long long usage_usec, nr_periods, nr_throttled, throttled_usec;
};

/* "/sys/fs/cgroup/<path from /proc/self/cgroup>". Returns 0 on success. */
int cg_self_dir(char *buf, size_t n);

/* cpu.max: quota and period in microseconds; *quota_us = -1 for "max"
 * (no quota). Returns 0 on success. */
int cg_read_max(const char *dir, long long *quota_us, long long *period_us);

/* Opens <dir>/cpu.stat for repeated reads with cg_read_stat_fd. */
int cg_open_stat(const char *dir);
int cg_read_stat_fd(int fd, struct cg_stat *s);

#endif
