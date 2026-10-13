"""Effective memory, including the container limit, without loading any model."""
import gc
import os
import signal
import subprocess
import time
import sys
from pathlib import Path
import psutil

def release_temporary_memory():
    """Return unused CPU allocations; keep live model tensors untouched."""
    gc.collect()
    if sys.platform.startswith("linux"):
        import ctypes
        try:
            trim = ctypes.CDLL(None).malloc_trim
            trim.argtypes = [ctypes.c_size_t]
            trim.restype = ctypes.c_int
            trim(0)
        except (AttributeError, OSError):
            pass

class ProcessInterrupted(RuntimeError):
    """A subprocess exited unexpectedly and can restart from disk checkpoints."""
    pass

class TextCapacityExceeded(ValueError):
    """A native text/token limit requires smaller utterances, not lower precision."""
    pass

def is_memory_error(value):
    return isinstance(value, MemoryError) or any(term in str(value).lower() for term in (
        "defaultcpuallocator", "not enough memory", "out of memory", "std::bad_alloc",
        "unable to allocate", "cannot allocate memory", "memoryerror"))

def stop_process_tree(process):
    """Release the isolated process group, even if its parent already exited."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            process.wait()
            return
        members = []
        for member in psutil.process_iter(["pid"]):
            try:
                if member.pid != process.pid and os.getpgid(member.pid) == process.pid:
                    members.append(member)
            except (ProcessLookupError, PermissionError, psutil.NoSuchProcess):
                pass
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # A descendant can ignore TERM or outlive an OOM-killed parent.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        # Signal delivery is asynchronous. Wait for descendants to release
        # their address spaces before the next model starts; zombies hold no RAM.
        deadline = time.monotonic()+5
        while members and time.monotonic() < deadline:
            remaining = []
            for member in members:
                try:
                    if member.is_running() and member.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                        remaining.append(member)
                except psutil.NoSuchProcess:
                    pass
            members = remaining
            if members:
                time.sleep(0.01)
    elif process.poll() is None:
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.kill()
            parent.kill()
            psutil.wait_procs(children+[parent], timeout=5)
        except psutil.NoSuchProcess:
            pass
        process.wait()

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
