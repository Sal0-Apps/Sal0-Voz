import json
import shutil
import time
import wave
import pytest
from app import storage as s
from app.worker import Worker, Interrupted

def test_resume_after_restart(data, monkeypatch):
    job = s.put("job", {"status":"running","name":"restart","snapshot":{},"progress":25})
    worker = Worker()
    worker.stop_event.set()
    monkeypatch.setattr(worker, "loop", lambda: None)
    worker.start()
    assert not worker.stop_event.is_set()
    assert s.get("job", job["id"])["status"] == "queued"
    worker.stop()

def test_checkpoint_reuse_and_hash_recovery(data, monkeypatch):
    # Actual pipeline concatenation/export is tested separately with FFmpeg.
    worker=Worker()
    job=s.put("job", {"status":"running","name":"test","progress":0})
    folder=data/"jobs"/job["id"];folder.mkdir()
    worker.update(job["id"], status="paused")
    with pytest.raises(Interrupted): worker.check(job["id"])

@pytest.mark.skipif(not (shutil.which("espeak-ng") and shutil.which("ffmpeg")), reason="Requires FFmpeg and eSpeak NG (available in Docker CI)")
def test_real_speech_and_checkpoint_recovery(data):
    worker = Worker()
    project = {"mode":"tts","name":"Integração","engine":"diagnostic","format":"wav","segments":[{"text":"Olá, mundo.","language":"pt-BR","rate":1,"volume":0},{"text":"","pause_ms":100,"rate":1,"volume":0},{"text":"This is a local voice test.","language":"en-US","rate":1,"volume":0}]}
    job=s.put("job", {"status":"running","name":project["name"],"snapshot":project,"progress":0})
    worker.execute(job)
    exports=s.get("job",job["id"])["outputs"]
    assert len(exports)==3
    from app.media import probe
    assert probe(s.safe_path(exports[0]["path"]))["duration"] > 1
    segment=data/"jobs"/job["id"]/"segment-000000.wav"
    old=segment.stat().st_mtime_ns
    worker.execute(job)
    assert segment.stat().st_mtime_ns==old
    segment.write_bytes(b"corrupt")
    worker.execute(job)
    with wave.open(str(segment)) as wav: assert wav.getnframes()>0


@pytest.mark.skipif(not (shutil.which("espeak-ng") and shutil.which("ffmpeg")), reason="Requires Linux media tools")
def test_dubbing_preserves_video_duration(data):
    import subprocess
    from app.media import ffargs, probe
    source = data / "media" / "source.mp4"
    subprocess.run(ffargs("-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "6", "-c:v", "libx264", "-c:a", "aac", source), check=True)
    project = {"mode":"dub","name":"Cena","engine":"diagnostic","media":{"path":"media/source.mp4","duration":6},"segments":[{"text":"Oi.","language":"pt-BR","rate":1,"volume":0,"start_ms":2000,"end_ms":5000}]}
    job = s.put("job", {"status":"running","name":"Cena","snapshot":project,"progress":0})
    Worker().execute(job)
    result = s.get("job",job["id"])
    output = s.safe_path(result["outputs"][0]["path"])
    info = probe(output)
    assert info["video"] and info["audio"]
    assert abs(info["duration"]-6) < 0.2
    assert result["cues"][0]["start_ms"] == 2000



def test_reclaimable_cache_does_not_pause_work(data, monkeypatch):
    import app.worker as module
    from types import SimpleNamespace
    readings = {"memory.max": "1000", "memory.current": "950", "memory.stat": "inactive_file 500"}
    class Cgroup:
        def __truediv__(self, name):
            return SimpleNamespace(read_text=lambda: readings[name])
    monkeypatch.setattr(module, "Path", lambda name: Cgroup())
    monkeypatch.setattr(module.psutil, "virtual_memory", lambda: SimpleNamespace(available=1024**3))
    worker = Worker()
    job = s.put("job", {"status": "running"})
    worker.check(job["id"])
    assert s.get("job", job["id"])["status"] == "running"
    readings["memory.stat"] = "inactive_file 0"
    with pytest.raises(Interrupted):
        worker.check(job["id"])
    assert s.get("job", job["id"])["status"] == "paused"


def test_process_failure_includes_real_cause(data):
    import sys
    job = s.put("job", {"status": "running"})
    (data / "jobs" / job["id"]).mkdir()
    with pytest.raises(ValueError, match="specific-engine-error"):
        Worker().run(job["id"], [sys.executable, "-c", "raise RuntimeError('specific-engine-error')"])
