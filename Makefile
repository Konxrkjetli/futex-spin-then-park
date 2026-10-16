CC          := gcc
CFLAGS      := -std=gnu11 -O2 -g -Wall -Wextra -pthread -D_GNU_SOURCE
TSAN_CFLAGS := -std=gnu11 -O1 -g -Wall -Wextra -pthread -D_GNU_SOURCE -fsanitize=thread
LDLIBS      := -lm

LIB_SRC := src/tsc.c src/topo.c src/hist.c src/lock_registry.c \
           src/lock_futex.c src/lock_spin.c src/lock_pthread.c \
           src/policy.c src/lock_adaptive.c src/cgroup.c
HDRS    := $(wildcard src/*.h)
BINS    := build/bench build/wakebench build/calib build/test_locks build/sqlbench build/libflshim.so

.PHONY: all tsan test test-tsan test-shim validate manifest figures print-flags clean

all: $(BINS)

build build-tsan:
	mkdir -p $@

build/%: src/%.c $(LIB_SRC) $(HDRS) | build
	$(CC) $(CFLAGS) -Isrc -o $@ $< $(LIB_SRC) $(LDLIBS)

# Phase 4 stretch: SQLite benchmark (glibc mutex unless run under the shim)
build/sqlbench: src/sqlbench.c src/tsc.c src/topo.c src/hist.c $(HDRS) | build
	$(CC) $(CFLAGS) -Isrc -o $@ src/sqlbench.c src/tsc.c src/topo.c src/hist.c -lsqlite3 -ldl $(LDLIBS)

# LD_PRELOAD shim: only pthread_mutex_* / pthread_cond_* and fl_shim_* are exported
build/libflshim.so: src/shim.c $(LIB_SRC) $(HDRS) | build
	$(CC) $(CFLAGS) -fPIC -shared -fvisibility=hidden -Isrc -o $@ src/shim.c $(LIB_SRC) $(LDLIBS)

build/test_locks: tests/test_locks.c $(LIB_SRC) $(HDRS) | build
	$(CC) $(CFLAGS) -Isrc -o $@ $< $(LIB_SRC) $(LDLIBS)

build-tsan/test_locks: tests/test_locks.c $(LIB_SRC) $(HDRS) | build-tsan
	$(CC) $(TSAN_CFLAGS) -Isrc -o $@ $< $(LIB_SRC) $(LDLIBS)

tsan: build-tsan/test_locks

test: build/test_locks
	./build/test_locks

test-shim: build/sqlbench build/libflshim.so
	for l in park spin stp:4750 ada hedge; do \
	  FL_SHIM_LOCK=$$l LD_PRELOAD=./build/libflshim.so ./build/sqlbench --threads 8 --duration-ms 300 \
	    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['lock'], 'counter_ok', d['counter_ok'], d['shim']); sys.exit(not d['counter_ok'])" || exit 1; \
	done

figures:
	python3 scripts/figures.py

test-tsan: build-tsan/test_locks
	./build-tsan/test_locks --total 200000 --watchdog 300

validate: all tsan
	python3 scripts/validate.py

manifest: all
	python3 scripts/manifest.py

print-flags:
	@echo "CC=$(CC) CFLAGS=$(CFLAGS) LDLIBS=$(LDLIBS)"

clean:
	rm -rf build build-tsan
