import json
import shutil
import time
import wave
import pytest
from app import storage as s
from app.worker import Worker, Interrupted

def test_resume_after_restart(data):
    job = s.put("job", {"status":"running","name":"restart","snapshot":{},"progress":25})
    worker = Worker()
    worker.stop_event.set()
    worker.start()
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

