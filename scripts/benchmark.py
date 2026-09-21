"""Record target hardware without making any model-quality claim."""
import json
import platform
import shutil
import subprocess
from pathlib import Path
import psutil
from app import storage as s

s.init()
report = {"cpu": platform.processor(), "system": platform.platform(), "architecture": platform.machine(), "memory": dict(psutil.virtual_memory()._asdict()), "disk": dict(shutil.disk_usage(s.DATA)._asdict()), "logical_cores": psutil.cpu_count(), "quality_evaluation": "pending", "elevenlabs_comparison": "not_evaluated"}
if Path("/proc/cpuinfo").exists():
    report["cpuinfo"] = Path("/proc/cpuinfo").read_text()
s.atomic_json(s.DATA / "benchmark-hardware.json", report)
print(json.dumps(report, ensure_ascii=False, indent=2))

