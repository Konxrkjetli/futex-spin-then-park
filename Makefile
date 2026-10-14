CC          := gcc
CFLAGS      := -std=gnu11 -O2 -g -Wall -Wextra -pthread -D_GNU_SOURCE
TSAN_CFLAGS := -std=gnu11 -O1 -g -Wall -Wextra -pthread -D_GNU_SOURCE -fsanitize=thread
LDLIBS      := -lm

LIB_SRC := src/tsc.c src/topo.c src/hist.c src/lock_registry.c \
           src/lock_futex.c src/lock_spin.c src/lock_pthread.c
HDRS    := $(wildcard src/*.h)
BINS    := build/bench build/wakebench build/calib build/test_locks

.PHONY: all tsan test test-tsan validate manifest print-flags clean

all: $(BINS)

build build-tsan:
	mkdir -p $@

build/%: src/%.c $(LIB_SRC) $(HDRS) | build
	$(CC) $(CFLAGS) -Isrc -o $@ $< $(LIB_SRC) $(LDLIBS)

build/test_locks: tests/test_locks.c $(LIB_SRC) $(HDRS) | build
	$(CC) $(CFLAGS) -Isrc -o $@ $< $(LIB_SRC) $(LDLIBS)

build-tsan/test_locks: tests/test_locks.c $(LIB_SRC) $(HDRS) | build-tsan
	$(CC) $(TSAN_CFLAGS) -Isrc -o $@ $< $(LIB_SRC) $(LDLIBS)

tsan: build-tsan/test_locks

test: build/test_locks
	./build/test_locks

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
