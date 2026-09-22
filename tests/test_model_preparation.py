import threading
import pytest
from app import storage as s
from app.model_manager import ModelManager


def test_default_install_and_restart_recovery(data, monkeypatch):
    monkeypatch.delenv("SAL0_AUTO_DOWNLOAD_MODELS", raising=False)
    monkeypatch.delenv("SAL0_AUTO_MODELS", raising=False)
    manager = ModelManager()
    monkeypatch.setattr(manager, "loop", lambda: None)
    manager._record("qwen-1.7b", status="downloading")
    manager.start()
    manager.stop()
    assert manager.status("qwen-0.6b")["status"] == "queued"
    assert manager.status("whisper-medium")["status"] == "queued"
    assert manager.status("qwen-1.7b")["status"] == "queued"
    manager.start()
    assert not manager.stop_event.is_set()
    manager.stop()


def test_cancel_between_plan_and_install(data, monkeypatch):
    manager = ModelManager()
    manager.request("qwen-0.6b", accept_license=True)
    calls = []
    def run(ident, args, log):
        calls.append(args)
        manager.cancel(ident)
    monkeypatch.setattr(manager, "_run", run)
    with pytest.raises(InterruptedError):
        manager._download("qwen-0.6b")
    assert len(calls) == 1
    assert manager.status("qwen-0.6b")["status"] == "cancelled"


def test_progress_counts_downloaded_files(data):
    manager = ModelManager()
    folder = data / "models" / "qwen-0.6b"
    folder.mkdir()
    s.atomic_json(folder / "download-plan.json", {"bytes": 100, "files": {"weights": 100}})
    (folder / "weights.incomplete").write_bytes(b"x" * 35)
    manager._record("qwen-0.6b", status="downloading")
    manager._progress("qwen-0.6b")
    assert manager.status("qwen-0.6b")["progress"] == 35


def test_valid_transcription_waits_for_model(owner):
    media = s.put("media", {"audio": True, "path": "media/audio.wav", "owner_username": "admin"})
    project = owner.post("/api/projects", json={"name": "Transcricao", "mode": "asr", "media_id": media["id"]}).json()
    result = owner.post("/api/projects/" + project["id"] + "/generate")
    assert result.status_code == 200
    job = s.get("job", result.json()["id"])
    assert job["status"] == "queued"
    assert job["snapshot"]["media"]["id"] == media["id"]
    assert s.get("model_download", "whisper-medium")["status"] == "queued"


def test_worker_skips_waiting_model_and_runs_ready_job(data, monkeypatch):
    import app.worker as module
    worker = module.Worker()
    def require(engine, kind):
        if engine == "whisper-medium":
            raise ValueError("not ready")
        return {"id": engine, "revision": "fixed"}
    monkeypatch.setattr(module, "require", require)
    waiting = s.put("job", {"status": "queued", "snapshot": {"mode": "asr", "asr_engine": "whisper-medium"}})
    ready = s.put("job", {"status": "queued", "snapshot": {"mode": "tts", "engine": "diagnostic"}})
    monkeypatch.setattr(worker, "execute", lambda job: None)
    monkeypatch.setattr(worker, "check", lambda ident: None)
    monkeypatch.setattr(module, "notify_job", lambda job: worker.stop_event.set())
    worker.loop()
    assert s.get("job", ready["id"])["status"] == "completed"
    assert s.get("job", waiting["id"])["status"] == "queued"
    worker.stop_event.clear()
    monkeypatch.setattr(module, "require", lambda *args: {"revision": "downloaded"})
    worker.loop()
    assert s.get("job", waiting["id"])["status"] == "completed"
    assert s.get("job", waiting["id"])["snapshot"]["model"]["revision"] == "downloaded"


def test_other_user_cannot_reference_admin_media(owner):
    media = s.put("media", {"audio": True, "owner_username": "admin"})
    owner.post("/api/users", json={"username": "maria", "password": "test-password"})
    owner.post("/api/auth/logout")
    owner.post("/api/auth/login", json={"username": "maria", "password": "test-password"})
    response = owner.post("/api/projects", json={"name": "Other", "media_id": media["id"]})
    assert response.status_code == 403
    assert owner.get("/api/media").json() == []
