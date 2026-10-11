from types import SimpleNamespace
from app import resources


def readings(root, limit, current, stats):
    (root / "memory.max").write_text(str(limit))
    (root / "memory.current").write_text(str(current))
    (root / "memory.stat").write_text(stats)


def available(root, host, monkeypatch):
    original = resources.cgroup_memory
    monkeypatch.setattr(resources, "cgroup_memory", lambda: original(root))
    monkeypatch.setattr(resources.psutil, "virtual_memory", lambda: SimpleNamespace(available=host))
    return resources.memory_available()


def test_mapped_model_pages_are_reclaimable(tmp_path, monkeypatch):
    readings(tmp_path, 12000, 11000,
             "file 4000\nfile_mapped 3000\nactive_file 3500\ninactive_file 500\n"
             "shmem 500\nfile_dirty 200\nfile_writeback 100\n")
    assert resources.cgroup_memory(tmp_path) == (12000, 7800)
    assert available(tmp_path, 20000, monkeypatch) == 4200


def test_dirty_and_shared_pages_still_count(tmp_path, monkeypatch):
    readings(tmp_path, 12000, 11800,
             "file 1000\nshmem 600\nfile_dirty 400\nfile_writeback 100\n")
    assert resources.cgroup_memory(tmp_path) == (12000, 11800)
    assert available(tmp_path, 20000, monkeypatch) == 200


def test_unlimited_container_uses_host_memory(tmp_path, monkeypatch):
    readings(tmp_path, "max", 10000, "")
    assert resources.cgroup_memory(tmp_path) is None
    assert available(tmp_path, 5000, monkeypatch) == 5000
