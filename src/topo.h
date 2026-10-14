#ifndef FL_TOPO_H
#define FL_TOPO_H

/* "Cores-first" CPU order within the current affinity mask: the first SMT
 * thread of every physical core, then the second thread of every core, and so
 * on. The core holding CPU 0 goes last at each level because CPU 0 takes most
 * housekeeping interrupts. Returns the number of CPUs written. */
int topo_cpu_order(int *out, int max);

/* An SMT sibling of `cpu`, or -1 if it has none. */
int topo_sibling(int cpu);

/* Pins the calling thread to one CPU. Returns 0 on success. */
int pin_self(int cpu);

#endif
