import threading
import pytest
from app import storage as s
from app.model_manager import ModelManager
from app.catalog import CATALOG, DEFAULT_ASR_MODEL, DEFAULT_MODELS


@pytest.mark.parametrize("status", ["queued", "failed"])
def test_old_download_record_is_completed_when_image_already_has_model(data, monkeypatch, status):
    import app.model_manager as module
    manager=ModelManager()
    manager._record("qwen-1.7b", status=status, error="old interruption", retry_at=1)
    monkeypatch.setattr(module, "installed", lambda:[{"id":"qwen-1.7b", "available":True}])
    def download(_):
        pytest.fail("An installed model must not be downloaded again")
    monkeypatch.setattr(manager, "_download", download)
    monkeypatch.setattr(manager.wake, "wait", lambda _:manager.stop_event.set())
    manager.loop()
    record=manager.status("qwen-1.7b")
    assert record["status"]=="completed" and record["progress"]==100
    assert record["error"] is None and record["retry_at"] is None


def test_default_install_and_restart_recovery(data, monkeypatch):
    monkeypatch.delenv("SAL0_AUTO_DOWNLOAD_MODELS", raising=False)
    monkeypatch.delenv("SAL0_AUTO_MODELS", raising=False)
    manager = ModelManager()
    monkeypatch.setattr(manager, "loop", lambda: None)
    manager._record("qwen-1.7b", status="downloading")
    manager.start()
    manager.stop()
    assert manager.status("qwen-0.6b") is None  # Optional models wait for a user's choice.
    assert manager.status(DEFAULT_ASR_MODEL)["status"] == "queued"
    assert manager.status("qwen-1.7b")["status"] == "queued"
    manager.start()
    assert not manager.stop_event.is_set()
    manager.stop()


def test_installed_models_survive_manager_recreation_without_download(data, tmp_path, monkeypatch):
    import app.catalog as catalog
    import sys
    monkeypatch.delenv("SAL0_AUTO_DOWNLOAD_MODELS", raising=False)
    monkeypatch.delenv("SAL0_AUTO_MODELS", raising=False)
    monkeypatch.setenv("SAL0_BUNDLED_MODELS", str(tmp_path / "empty-image"))
    monkeypatch.setattr(catalog, "runtime", lambda _: sys.executable)
    for ident in DEFAULT_MODELS:
        folder = data / "models" / ident
        folder.mkdir()
        (folder / "weights.bin").write_bytes(b"persisted weights substitute")
        s.atomic_json(folder / "manifest.json", {
            "revision": CATALOG[ident]["revision"], "files": {"weights.bin": s.digest(folder / "weights.bin")},
            "file_sizes": {"weights.bin": (folder / "weights.bin").stat().st_size},
        })
    for _ in range(2):
        manager = ModelManager()
        monkeypatch.setattr(manager, "loop", lambda: None)
        manager.start()
        manager.stop()
        assert s.listing("model_download", limit=-1) == []
        assert all(item["available"] and item["source"] == "downloaded"
                   for item in manager.snapshot() if item["id"] in DEFAULT_MODELS)


def test_http_startup_does_not_wait_for_model_download(data, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    monkeypatch.setenv("SAL0_DISABLE_WORKER", "0")
    monkeypatch.delenv("SAL0_AUTO_DOWNLOAD_MODELS", raising=False)
    monkeypatch.delenv("SAL0_AUTO_MODELS", raising=False)
    monkeypatch.setenv("SAL0_BUNDLED_MODELS", str(tmp_path / "empty-image"))
    manager = ModelManager()
    started = threading.Event()
    def download(ident):
        manager._record(ident, status="downloading", progress=12)
        started.set()
        assert manager.stop_event.wait(5), "The HTTP app must remain usable during preparation"
    monkeypatch.setattr(manager, "_download", download)
    monkeypatch.setattr(main, "model_manager", manager)
    monkeypatch.setattr(main.worker, "start", lambda: None)
    monkeypatch.setattr(main.worker, "stop", lambda: None)
    with TestClient(main.app) as client:
        assert started.wait(2)
        assert client.get("/health").json()["status"] == "ok"
        assert client.post("/api/auth/setup", json={"password": "test-password-123"}).status_code == 200
        models = {item["id"]: item for item in client.get("/api/models").json()}
        assert all(not models[ident]["available"] for ident in DEFAULT_MODELS)
        assert {models[ident]["download"]["status"] for ident in DEFAULT_MODELS} == {"queued", "downloading"}
        assert "download" not in models["qwen-0.6b"]
        assert client.get("/api/jobs").json() == []
    assert not manager.thread.is_alive()


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
    assert s.get("model_download", DEFAULT_ASR_MODEL)["status"] == "queued"


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


@pytest.mark.parametrize("weights_present", [False, True])
def test_old_queued_job_rechecks_model_files(data, tmp_path, monkeypatch, weights_present):
    import app.worker as module
    monkeypatch.setenv("SAL0_BUNDLED_MODELS", str(tmp_path / "empty-image"))
    monkeypatch.setenv("SAL0_ENGINES", str(tmp_path / "empty-runtimes"))
    if weights_present:
        folder = data / "models" / "qwen-0.6b"
        folder.mkdir()
        (folder / "weights.bin").write_bytes(b"persisted substitute")
        s.atomic_json(folder / "manifest.json", {
            "revision": CATALOG["qwen-0.6b"]["revision"], "files": {"weights.bin": s.digest(folder / "weights.bin")},
            "file_sizes": {"weights.bin": (folder / "weights.bin").stat().st_size},
        })
    manager = ModelManager()
    manager._record("qwen-0.6b", status="completed", progress=100)
    monkeypatch.setattr(module, "model_manager", manager)
    monkeypatch.setattr(module, "choose_profile", lambda *args, **kwargs: None)
    worker = module.Worker()
    pending = s.put("job", {"status": "queued", "snapshot": {"mode": "tts", "engine": "qwen-0.6b"}})
    monkeypatch.setattr(worker.wake, "wait", lambda _: worker.stop_event.set())
    monkeypatch.setattr(worker, "execute", lambda _: pytest.fail("Wait until the weights are downloaded"))
    worker.loop()
    job = s.get("job", pending["id"])
    if weights_present:
        assert job["status"] == "failed" and "ambiente do modelo" in job["error"]
        assert manager.status("qwen-0.6b")["status"] == "completed"
    else:
        assert job["status"] == "queued" and job["waiting_models"] == ["qwen-0.6b"]
        assert manager.status("qwen-0.6b")["status"] == "queued"
        assert manager.status("qwen-0.6b")["automatic"] is True


def test_other_user_cannot_reference_admin_media(owner):
    media = s.put("media", {"audio": True, "owner_username": "admin"})
    owner.post("/api/users", json={"username": "maria", "password": "test-password"})
    owner.post("/api/auth/logout")
    owner.post("/api/auth/login", json={"username": "maria", "password": "test-password"})
    response = owner.post("/api/projects", json={"name": "Other", "media_id": media["id"]})
    assert response.status_code == 403
    assert owner.get("/api/media").json() == []


def test_clone_without_transcript(owner):
    media = s.put("media", {"audio": True, "path": "media/reference.wav", "owner_username": "admin"})
    character = owner.post("/api/characters", json={"name": "Voice", "reference_id": media["id"]}).json()
    project = owner.post("/api/projects", json={"name": "Clone", "text": "Ola", "engine": "qwen-0.6b", "character_id": character["id"]}).json()
    result = owner.post("/api/projects/" + project["id"] + "/generate")
    assert result.status_code == 200, result.text
    assert s.get("job", result.json()["id"])["snapshot"]["segments"][0]["character"]["reference_text"] == ""


def test_corrupt_job_does_not_stop_the_queue(data, monkeypatch):
    import app.worker as module
    worker = module.Worker()
    invalid = s.put("job", {"status": "queued", "snapshot": {}})
    ready = s.put("job", {"status": "queued", "snapshot": {"mode": "tts", "engine": "diagnostic"}})
    monkeypatch.setattr(module, "require", lambda *args: {"id": "diagnostic"})
    monkeypatch.setattr(worker, "execute", lambda job: None)
    monkeypatch.setattr(worker, "check", lambda ident: None)
    monkeypatch.setattr(module, "notify_job", lambda job: worker.stop_event.set())
    worker.loop()
    assert s.get("job", invalid["id"])["status"] == "failed"
    assert s.get("job", ready["id"])["status"] == "completed"
