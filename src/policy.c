#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lock.h"
#include "policy.h"
#include "tsc.h"

/* The arm distribution is recomputed every RECOMPUTE updates (K exp() calls
 * each time) so the per-acquisition cost stays a few ns. Sampling and the
 * EXP3 importance weights both use the stored distribution, so they stay
 * consistent between recomputations. */
#define RECOMPUTE 16

/* Defaults. w0 and arms 1-4 are the E1 reference median and the static
 * budgets b1..b4 from config/budgets.json; the last arm is 32 x the median
 * (rounded to 50 ns), a budget long enough to cover nearly any wait. */
void pol_default(struct policy_cfg *c, enum pol_kind kind)
{
    static const double arms[] = { 0, 2350, 4750, 9450, 37850, 151300 };
    memset(c, 0, sizeof *c);
    c->kind = kind;
    c->beta = 1.0;
    c->w0_ns = 4728.9;
    c->alpha = 1.0 / 16;
    c->wcap_ns = 1e6;
    c->window = 1024;
    c->narms = (int)(sizeof arms / sizeof arms[0]);
    memcpy(c->arms_ns, arms, sizeof arms);
    c->poll_us = 1000;
    c->theta = 0.9;
    c->hold_min = 1;
    c->hold_max = 64;
}

static int parse_num(const char *v, double *out)
{
    char *end;
    double x = strtod(v, &end);
    if (end == v || *end != '\0' || !(x >= 0) || isinf(x))
        return -1;
    *out = x;
    return 0;
}

int pol_parse(const char *arg, struct policy_cfg *c)
{
    char buf[512];
    if (!arg || !*arg)
        return 0;
    if (strlen(arg) >= sizeof buf)
        return -1;
    strcpy(buf, arg);
    for (char *save = NULL, *kv = strtok_r(buf, ",", &save); kv; kv = strtok_r(NULL, ",", &save)) {
        char *v = strchr(kv, '=');
        double x;
        if (!v)
            return -1;
        *v++ = '\0';
        if (!strcmp(kv, "base")) {
            if (!c->ta)
                return -1;
            if (!strcmp(v, "ada")) c->kind = POL_A;
            else if (!strcmp(v, "hedge")) c->kind = POL_HEDGE;
            else return -1;
            continue;
        }
        if (!strcmp(kv, "arms")) {
            int n = 0;
            for (char *s2 = NULL, *a = strtok_r(v, "/", &s2); a; a = strtok_r(NULL, "/", &s2)) {
                if (n == POL_MAX_ARMS || parse_num(a, &c->arms_ns[n]) != 0)
                    return -1;
                if (n > 0 && c->arms_ns[n] <= c->arms_ns[n - 1])
                    return -1;
                n++;
            }
            if (n < 2 || c->arms_ns[0] != 0)
                return -1;
            c->narms = n;
            continue;
        }
        if (parse_num(v, &x) != 0)
            return -1;
        if (!strcmp(kv, "beta")) c->beta = x;
        else if (!strcmp(kv, "w0")) c->w0_ns = x;
        else if (!strcmp(kv, "alpha") && x > 0 && x <= 1) c->alpha = x;
        else if (!strcmp(kv, "wcap") && x > 0) c->wcap_ns = x;
        else if (!strcmp(kv, "window") && x >= 1) c->window = x;
        else if (!strcmp(kv, "poll") && c->ta && x >= 100) c->poll_us = x;
        else if (!strcmp(kv, "theta") && c->ta && x > 0) c->theta = x;
        else if (!strcmp(kv, "hmin") && c->ta && x >= 1) c->hold_min = (int)x;
        else if (!strcmp(kv, "hmax") && c->ta && x >= 1) c->hold_max = (int)x;
        else return -1;
    }
    return c->hold_max >= c->hold_min ? 0 : -1;
}

void pol_format(const struct policy_cfg *c, char *buf, size_t n)
{
    static const char *names[] = { "ada", "hedge", "exp3" };
    int k = snprintf(buf, n, "{\"kind\":\"%s\",\"beta\":%g,\"w0_ns\":%g,\"alpha\":%g,\"wcap_ns\":%g,"
                     "\"window\":%g,\"arms_ns\":[", names[c->kind], c->beta, c->w0_ns, c->alpha,
                     c->wcap_ns, c->window);
    for (int i = 0; i < c->narms && k > 0 && (size_t)k < n; i++)
        k += snprintf(buf + k, n - (size_t)k, "%s%g", i ? "," : "", c->arms_ns[i]);
    if (k > 0 && (size_t)k < n)
        k += snprintf(buf + k, n - (size_t)k, "],\"ta\":%s", c->ta ? "true" : "false");
    if (c->ta && k > 0 && (size_t)k < n)
        k += snprintf(buf + k, n - (size_t)k, ",\"poll_us\":%g,\"theta\":%g,\"hold_min\":%d,\"hold_max\":%d",
                      c->poll_us, c->theta, c->hold_min, c->hold_max);
    if (k > 0 && (size_t)k < n)
        snprintf(buf + k, n - (size_t)k, "}");
}

static void recompute(struct pol_state *s)
{
    const int K = s->cfg.narms;
    double m = s->L[0], sum = 0, acc = 0;
    for (int i = 1; i < K; i++)
        if (s->L[i] < m)
            m = s->L[i];
    for (int i = 0; i < K; i++) {
        s->p[i] = exp(-s->eta * (s->L[i] - m));
        sum += s->p[i];
    }
    for (int i = 0; i < K; i++) {
        s->p[i] /= sum;
        if (s->cfg.kind == POL_EXP3)
            s->p[i] = (1 - s->explore) * s->p[i] + s->explore / K;
        acc += s->p[i];
        s->cdf[i] = acc;
    }
    s->cdf[K - 1] = 1.0;
    s->since = 0;
}

void pol_init(struct pol_state *s, const struct policy_cfg *c, const void *owner)
{
    memset(s, 0, sizeof *s);
    s->owner = owner;
    s->cfg = *c;
    const int K = c->narms;
    const double N = c->window;
    s->w_hat = c->w0_ns;
    s->gamma = 1.0 - 1.0 / N;
    if (c->kind == POL_EXP3) {
        /* Standard EXP3 tuning for horizon N (Auer et al.). */
        s->explore = fmin(1.0, sqrt(K * log(K) / ((M_E - 1) * N)));
        s->eta = s->explore / K;
    } else {
        s->eta = sqrt(8.0 * log(K) / N);   /* standard Hedge rate for horizon N */
    }
    double b = fmin(c->beta * s->w_hat, c->arms_ns[K - 1]);
    s->budget_tsc = ns_to_tsc(b);
    for (int i = 0; i < K; i++)
        s->arm_tsc[i] = ns_to_tsc(c->arms_ns[i]);
    s->rng = ((uint64_t)(uintptr_t)s ^ tsc_now()) | 1;
    recompute(s);
}

void pol_update(struct pol_state *s, const struct pol_obs *o)
{
    const int K = s->cfg.narms;

    if (o->woke) {
        double x = o->wake_ns < s->cfg.wcap_ns ? o->wake_ns : s->cfg.wcap_ns;
        s->w_hat += s->cfg.alpha * (x - s->w_hat);
    }
    const double C = s->cfg.beta * s->w_hat;
    const double unit = C > 1.0 ? C : 1.0;   /* normalisation, ns */
    if (s->cfg.kind == POL_A)
        s->budget_tsc = ns_to_tsc(fmin(C, s->cfg.arms_ns[K - 1]));

    /* Counterfactual cost of every arm, for every policy: Hedge learns from
     * it, and all three log it so regret against the best fixed arm can be
     * computed afterwards. */
    double c[POL_MAX_ARMS], cmin = INFINITY;
    const double real = o->spun ? o->w_ns : o->b_ns + C;
    for (int i = 0; i < K; i++) {
        const double b = s->cfg.arms_ns[i];
        if (o->spun || b > o->b_ns)
            c[i] = o->w_ns <= b ? o->w_ns : b + C;
        else
            c[i] = b + C;   /* parked with budget >= b: this arm parks too */
        lk_stats.cost_arm[i] += c[i];
        if (c[i] < cmin)
            cmin = c[i];
    }
    lk_stats.cost_real += real;

    if (s->cfg.kind == POL_HEDGE) {
        for (int i = 0; i < K; i++)
            s->L[i] = s->gamma * s->L[i] + fmin((c[i] - cmin) / unit, 1.0);
    } else if (s->cfg.kind == POL_EXP3 && o->arm >= 0) {
        for (int i = 0; i < K; i++)
            s->L[i] *= s->gamma;
        s->L[o->arm] += fmin(real / (2 * unit), 1.0) / s->p[o->arm];
    } else {
        return;
    }
    if (++s->since >= RECOMPUTE)
        recompute(s);
}
