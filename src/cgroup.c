#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "cgroup.h"

int cg_self_dir(char *buf, size_t n)
{
    char line[512];
    FILE *f = fopen("/proc/self/cgroup", "r");
    if (!f)
        return -1;
    int rc = -1;
    while (fgets(line, sizeof line, f)) {
        if (strncmp(line, "0::", 3) != 0)   /* the cgroup v2 entry */
            continue;
        line[strcspn(line, "\n")] = '\0';
        if ((size_t)snprintf(buf, n, "/sys/fs/cgroup%s", line + 3) < n)
            rc = 0;
        break;
    }
    fclose(f);
    return rc;
}

int cg_read_max(const char *dir, long long *quota_us, long long *period_us)
{
    char path[600], q[32];
    snprintf(path, sizeof path, "%s/cpu.max", dir);
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    int rc = fscanf(f, "%31s %lld", q, period_us) == 2 ? 0 : -1;
    fclose(f);
    if (rc == 0)
        *quota_us = strcmp(q, "max") == 0 ? -1 : atoll(q);
    return rc;
}

int cg_open_stat(const char *dir)
{
    char path[600];
    snprintf(path, sizeof path, "%s/cpu.stat", dir);
    return open(path, O_RDONLY | O_CLOEXEC);
}

/* pread at offset 0 makes the kernel regenerate the file, so one fd serves
 * every poll without reopening. */
int cg_read_stat_fd(int fd, struct cg_stat *s)
{
    char buf[1024];
    ssize_t len = pread(fd, buf, sizeof buf - 1, 0);
    if (len <= 0)
        return -1;
    buf[len] = '\0';
    memset(s, 0, sizeof *s);
    int have_usage = 0;
    for (char *p = buf; p && *p; p = strchr(p, '\n') ? strchr(p, '\n') + 1 : NULL) {
        char key[32];
        long long v;
        if (sscanf(p, "%31s %lld", key, &v) != 2)
            continue;
        if (!strcmp(key, "usage_usec")) { s->usage_usec = v; have_usage = 1; }
        else if (!strcmp(key, "nr_periods")) s->nr_periods = v;
        else if (!strcmp(key, "nr_throttled")) s->nr_throttled = v;
        else if (!strcmp(key, "throttled_usec")) s->throttled_usec = v;
    }
    /* The throttling keys exist only where the cpu controller is enabled;
     * usage_usec always does. */
    return have_usage ? 0 : -1;
}
