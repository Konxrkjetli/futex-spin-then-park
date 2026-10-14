#include <stdlib.h>
#include <string.h>

#include "common.h"
#include "lock.h"

__thread struct lock_tstats lk_stats;

extern const struct lock_ops park_ops, stp_ops, spin_ops, pthread_ops, pthread_adaptive_ops;

/* No-op lock: harness baseline for single-thread runs only. */
static void none_init(void *l, const struct lock_params *p) { (void)l; (void)p; }
static void none_op(void *l) { (void)l; }
static const struct lock_ops none_ops = {
    .name = "none", .size = PAD_BYTES,
    .init = none_init, .lock = none_op, .unlock = none_op,
};

static const struct lock_ops *const registry[] = {
    &park_ops, &spin_ops, &stp_ops, &pthread_ops, &pthread_adaptive_ops, &none_ops,
};
#define NLOCKS (sizeof registry / sizeof registry[0])

const struct lock_ops *lock_lookup(const char *spec, struct lock_params *p)
{
    memset(p, 0, sizeof *p);
    const char *colon = strchr(spec, ':');
    size_t len = colon ? (size_t)(colon - spec) : strlen(spec);

    for (size_t i = 0; i < NLOCKS; i++) {
        const struct lock_ops *o = registry[i];
        if (strlen(o->name) != len || strncmp(o->name, spec, len) != 0)
            continue;
        if (o->arg_name) {
            if (!colon)
                return NULL;
            char *end;
            p->spin_ns = strtod(colon + 1, &end);
            if (end == colon + 1 || *end != '\0' || p->spin_ns < 0)
                return NULL;
        } else if (colon) {
            return NULL;
        }
        return o;
    }
    return NULL;
}

void *lock_create(const struct lock_ops *ops, const struct lock_params *p)
{
    size_t size = (ops->size + PAD_BYTES - 1) / PAD_BYTES * PAD_BYTES;
    void *l = aligned_alloc(PAD_BYTES, size);
    if (!l)
        die("lock allocation failed");
    memset(l, 0, size);
    ops->init(l, p);
    return l;
}

void lock_free(const struct lock_ops *ops, void *l)
{
    if (ops->destroy)
        ops->destroy(l);
    free(l);
}

void lock_list(FILE *f)
{
    for (size_t i = 0; i < NLOCKS; i++) {
        if (registry[i]->arg_name)
            fprintf(f, "%s:<%s>\n", registry[i]->name, registry[i]->arg_name);
        else
            fprintf(f, "%s\n", registry[i]->name);
    }
}
