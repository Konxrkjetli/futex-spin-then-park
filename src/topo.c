#include "topo.h"

#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_CORES 256
#define MAX_SMT 8

static int read_line(const char *path, char *buf, size_t n)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    char *r = fgets(buf, (int)n, f);
    fclose(f);
    return r ? 0 : -1;
}

/* Parses a kernel CPU list such as "0-1,8" into `set`. */
static void parse_cpulist(const char *s, cpu_set_t *set)
{
    CPU_ZERO(set);
    while (*s && *s != '\n') {
        char *end;
        long a = strtol(s, &end, 10), b = a;
        if (end == s)
            break;
        if (*end == '-')
            b = strtol(end + 1, &end, 10);
        for (long c = a; c <= b && c < CPU_SETSIZE; c++)
            CPU_SET((int)c, set);
        s = (*end == ',') ? end + 1 : end;
    }
}

static int siblings_of(int cpu, cpu_set_t *sib)
{
    char path[128], buf[256];
    snprintf(path, sizeof path,
             "/sys/devices/system/cpu/cpu%d/topology/thread_siblings_list", cpu);
    if (read_line(path, buf, sizeof buf) != 0) {
        CPU_ZERO(sib);
        CPU_SET(cpu, sib);
        return -1;
    }
    parse_cpulist(buf, sib);
    return 0;
}

int topo_cpu_order(int *out, int max)
{
    struct core { int first, n, cpus[MAX_SMT]; } cores[MAX_CORES];
    int ncores = 0;
    cpu_set_t allowed;

    if (sched_getaffinity(0, sizeof allowed, &allowed) != 0)
        return 0;

    for (int c = 0; c < CPU_SETSIZE; c++) {
        if (!CPU_ISSET(c, &allowed))
            continue;
        cpu_set_t sib;
        siblings_of(c, &sib);
        int first = c;
        for (int k = 0; k < CPU_SETSIZE; k++)
            if (CPU_ISSET(k, &sib)) { first = k; break; }

        int i;
        for (i = 0; i < ncores && cores[i].first != first; i++)
            ;
        if (i == ncores) {
            if (ncores == MAX_CORES)
                continue;
            cores[ncores].first = first;
            cores[ncores].n = 0;
            ncores++;
        }
        if (cores[i].n < MAX_SMT)
            cores[i].cpus[cores[i].n++] = c;
    }

    /* Rotate the core containing CPU 0 to the end. */
    for (int i = 0; i < ncores; i++) {
        if (cores[i].first == 0) {
            struct core c0 = cores[i];
            memmove(&cores[i], &cores[i + 1], (size_t)(ncores - i - 1) * sizeof cores[0]);
            cores[ncores - 1] = c0;
            break;
        }
    }

    int n = 0;
    for (int lvl = 0; lvl < MAX_SMT; lvl++)
        for (int i = 0; i < ncores; i++)
            if (lvl < cores[i].n && n < max)
                out[n++] = cores[i].cpus[lvl];
    return n;
}

int topo_sibling(int cpu)
{
    cpu_set_t sib;
    if (siblings_of(cpu, &sib) != 0)
        return -1;
    for (int k = 0; k < CPU_SETSIZE; k++)
        if (k != cpu && CPU_ISSET(k, &sib))
            return k;
    return -1;
}

int pin_self(int cpu)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    return pthread_setaffinity_np(pthread_self(), sizeof set, &set);
}
