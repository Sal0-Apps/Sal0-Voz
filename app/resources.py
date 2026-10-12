"""Effective memory, including the container limit, without loading any model."""
from pathlib import Path
import psutil

def cgroup_memory(root=None):
    root = root if root is not None else Path("/sys/fs/cgroup")
    try:
        limit = (root / "memory.max").read_text().strip()
        if limit != "max":
            used = int((root / "memory.current").read_text())
            stats = dict(line.split() for line in (root / "memory.stat").read_text().splitlines())
            # Read-only mapped model pages can be reclaimed. Keep tmpfs and
            # dirty/writeback pages in the working set used by the guard.
            clean = max(0, int(stats.get("file", stats.get("inactive_file", 0)))
                        - int(stats.get("shmem", 0)) - int(stats.get("file_dirty", 0))
                        - int(stats.get("file_writeback", 0)))
            return int(limit), max(0, used - clean)
    except (OSError, ValueError):
        pass
    return None

def memory_available():
    available = psutil.virtual_memory().available
    usage = cgroup_memory()
    if usage:
        limit, working = usage
        available = min(available, max(0, limit - working))
    return available

def oom_kills():
    try:
        return int(dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines()).get("oom_kill", 0))
    except (OSError, ValueError):
        return 0
