"""Verify real isolated runner startup; never initialize neural backends."""
import json
import os
import shutil
import subprocess
import venv
from pathlib import Path

import psutil


def test_isolated_runner_reproduces_missing_psutil_and_starts_after_install(tmp_path):
    root = tmp_path / "engine"
    venv.EnvBuilder(with_pip=False, system_site_packages=False).create(root)
    executable = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    command = [str(executable), "-m", "app.engine_runner", "--check-imports"]
    # No weights, request file, network or third-party engine package is present.
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    failed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=10)
    assert failed.returncode != 0
    assert "prompt_cache.py" in failed.stderr and "resources.py" in failed.stderr
    assert "No module named 'psutil'" in failed.stderr
    site = subprocess.check_output([str(executable), "-c",
                                   "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
    # Use the already installed psutil distribution, including its native module,
    # to keep this regression fully offline and independent of package downloads.
    shutil.copytree(Path(psutil.__file__).parent, Path(site) / "psutil")
    checked = subprocess.run(command, capture_output=True, text=True, env=env, timeout=10)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {"ok": True, "check": "imports"}
    assert not (tmp_path / "data").exists()
