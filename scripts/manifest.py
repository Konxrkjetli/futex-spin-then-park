#!/usr/bin/env python3
"""Collect a machine manifest: hardware, OS, toolchain, tuning state, git commit.

Every result file is tagged with the manifest's machine_id and the git commit,
so any number can be traced to the machine state that produced it.

usage: scripts/manifest.py [--stdout]
Writes results/manifests/manifest-<machine_id>-<timestamp>.json unless --stdout.
"""
import glob
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPU_SYS = Path("/sys/devices/system/cpu")


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT, timeout=60)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def machine_id():
    raw = read("/etc/machine-id") or platform.node()
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def lscpu():
    out = {}
    for line in (sh("LC_ALL=C lscpu") or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def topology():
    cpus = []
    for d in sorted(glob.glob(str(CPU_SYS / "cpu[0-9]*")), key=lambda p: int(p.rsplit("cpu", 1)[1])):
        cpus.append({
            "cpu": int(d.rsplit("cpu", 1)[1]),
            "core_id": read(f"{d}/topology/core_id"),
            "siblings": read(f"{d}/topology/thread_siblings_list"),
            "max_khz": read(f"{d}/cpufreq/cpuinfo_max_freq"),
        })
    return cpus


def unique_over_cpus(rel):
    vals = {read(p) for p in glob.glob(str(CPU_SYS / "cpu[0-9]*" / rel))}
    vals.discard(None)
    return sorted(vals)


def cpuidle_states():
    states = []
    for d in sorted(glob.glob(str(CPU_SYS / "cpu0/cpuidle/state*"))):
        states.append({"name": read(f"{d}/name"), "latency_us": read(f"{d}/latency"),
                       "disabled": read(f"{d}/disable")})
    return states


def power():
    out = {}
    for d in glob.glob("/sys/class/power_supply/*"):
        t = read(f"{d}/type")
        if t == "Mains":
            out["ac_online"] = read(f"{d}/online") == "1"
        elif t == "Battery":
            out["battery_status"] = read(f"{d}/status")
            out["battery_capacity"] = read(f"{d}/capacity")
    return out


def relevant_cmdline():
    keys = ("isolcpus", "nohz_full", "rcu_nocbs", "mitigations", "idle", "processor.max_cstate",
            "amd_pstate", "intel_pstate", "nosmt", "threadirqs", "preempt")
    words = (read("/proc/cmdline") or "").split()
    return [w for w in words if w.split("=", 1)[0] in keys]


def calib():
    exe = ROOT / "build" / "calib"
    if not exe.exists():
        return None
    out = sh(f"'{exe}' tsc-hz")
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def collect():
    c = lscpu()
    uid = os.getuid()
    user_cg = f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/cgroup.controllers"
    return {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine_id": machine_id(),
        "cpu": {
            "model": c.get("Model name"),
            "cpus": c.get("CPU(s)"),
            "threads_per_core": c.get("Thread(s) per core"),
            "cores_per_socket": c.get("Core(s) per socket"),
            "sockets": c.get("Socket(s)"),
            "numa_nodes": c.get("NUMA node(s)"),
            "l3": c.get("L3 cache"),
            "tsc_flags": sorted(f for f in (c.get("Flags") or "").split()
                                if f in ("constant_tsc", "nonstop_tsc", "rdtscp", "tsc_known_freq")),
        },
        "topology": topology(),
        "kernel": platform.release(),
        "kernel_cmdline_relevant": relevant_cmdline(),
        "glibc": sh("ldd --version | head -1"),
        "compiler": sh("gcc --version | head -1"),
        "build_flags": sh("make -s print-flags"),
        "python": platform.python_version(),
        "cpufreq": {
            "driver": unique_over_cpus("cpufreq/scaling_driver"),
            "governor": unique_over_cpus("cpufreq/scaling_governor"),
            "epp": unique_over_cpus("cpufreq/energy_performance_preference"),
            "boost": read(CPU_SYS / "cpufreq/boost"),
        },
        "smt_control": read(CPU_SYS / "smt/control"),
        "clocksource": read("/sys/devices/system/clocksource/clocksource0/current_clocksource"),
        "cpuidle_states": cpuidle_states(),
        "cgroup": {
            "fs": sh("stat -fc %T /sys/fs/cgroup"),
            "controllers": read("/sys/fs/cgroup/cgroup.controllers"),
            "user_delegated": read(user_cg),
        },
        "power": power(),
        "perf_event_paranoid": read("/proc/sys/kernel/perf_event_paranoid"),
        "glibc_tunables_env": os.environ.get("GLIBC_TUNABLES"),
        "loadavg": read("/proc/loadavg"),
        "git": {
            "commit": sh("git rev-parse HEAD 2>/dev/null"),
            "dirty": bool(sh("git status --porcelain 2>/dev/null")),
        },
        "calib": calib(),
    }


def main():
    m = collect()
    text = json.dumps(m, indent=2)
    if "--stdout" in sys.argv:
        print(text)
        return
    out_dir = ROOT / "results" / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"manifest-{m['machine_id']}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(text + "\n")
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
