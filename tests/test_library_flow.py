"""Real API coverage for studio startup, bulk removal and audio dubbing."""
import io
import json
import wave
from contextlib import contextmanager

import numpy as np
import pytest
from app import storage as s
from app.media import probe


def audio_bytes(seconds=4):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        samples = (np.sin(2*np.pi*180*np.arange(24000*seconds)/24000)*10000).astype("<i2")
        wav.writeframes(samples.tobytes())
    return out.getvalue()


def upload(owner, name="sample.wav"):
    response = owner.post("/api/media", files={"file": (name, audio_bytes())})
    assert response.status_code == 200, response.text
    return response.json()


def remove(owner, kind, ids):
    response = owner.post("/api/items/delete", json={"kind": kind, "ids": ids})
    assert response.status_code == 200, response.text
    return response.json()


def test_all_studio_bootstrap_routes_are_reachable(owner):
    for path in ("characters", "media", "projects", "jobs", "reactions", "models"):
        response = owner.get("/api/" + path)
        assert response.status_code == 200, (path, response.text)
        assert isinstance(response.json(), list)
    assert len(owner.get("/api/reactions").json()) == 33


def test_bulk_files_delete_unused_and_keep_voice_reference(owner):
    reference, first, second = [upload(owner, name) for name in ("reference.wav", "first.wav", "second.wav")]
    owner.post("/api/characters", json={"name": "Minha voz", "reference_id": reference["id"]})
    project = owner.post("/api/projects", json={"name": "Meu texto", "text": "Preserve este texto.", "media_id": first["id"]}).json()
    result = remove(owner, "media", [reference["id"], first["id"], second["id"], first["id"]])
    assert result["deleted"] == [first["id"], second["id"]]
    assert result["blocked"][0]["id"] == reference["id"] and "Minha voz" in result["blocked"][0]["reason"]
    assert s.safe_path(reference["path"]).exists()
    assert not s.safe_path(first["path"]).exists() and not s.safe_path(second["path"]).exists()
    saved = owner.get("/api/projects/" + project["id"]).json()
    assert saved["text"] == project["text"] and saved["media_id"] is None


def test_remove_voices_preserves_frozen_job_and_original_files(owner):
    reference = upload(owner)
    voices = [owner.post("/api/characters", json={"name": name, "reference_id": reference["id"]}).json() for name in ("Luna", "Sol")]
    project = owner.post("/api/projects", json={"name": "Cena", "character_id": voices[0]["id"], "text": "Olá."}).json()
    job_id = owner.post("/api/projects/" + project["id"] + "/generate").json()["id"]
    result = remove(owner, "characters", [v["id"] for v in voices])
    assert len(result["deleted"]) == 2 and not result["blocked"]
    assert owner.get("/api/characters").json() == []
    assert s.get("job", job_id)["snapshot"]["segments"][0]["character"]["name"] == "Luna"
    assert s.safe_path(reference["path"]).exists()
    assert owner.get("/api/projects/" + project["id"]).json()["character_id"] is None
    assert remove(owner, "media", [reference["id"]])["blocked"]
    assert owner.post("/api/jobs/" + job_id + "/cancel").status_code == 200
    assert remove(owner, "results", [job_id])["deleted"] == [job_id]
    assert remove(owner, "media", [reference["id"]])["deleted"] == [reference["id"]]


def test_results_remove_exports_checkpoints_but_keep_active_work(owner, data, monkeypatch):
    from app.main import worker
    jobs = [s.put("job", {"name": status, "owner_username": "admin", "status": status, "snapshot": {}}) for status in ("completed", "failed", "running", "paused")]
    for job in jobs:
        folder = data / "jobs" / job["id"]; folder.mkdir()
        (folder / "segment.wav").write_bytes(audio_bytes(1))
        for extension in ("wav", "srt", "partial.wav"):
            (data / "exports" / (job["id"] + "." + extension)).write_bytes(b"output")
    monkeypatch.setattr(worker, "active_job_id", jobs[3]["id"])
    result = remove(owner, "results", [j["id"] for j in jobs])
    assert result["deleted"] == [jobs[0]["id"], jobs[1]["id"]]
    assert {j["id"] for j in result["blocked"]} == {jobs[2]["id"], jobs[3]["id"]}
    for job in jobs[:2]:
        assert not (data / "jobs" / job["id"]).exists()
        assert not list((data / "exports").glob(job["id"] + ".*"))
    assert (data / "jobs" / jobs[2]["id"]).exists()


def test_regular_user_cannot_partially_delete_mixed_ownership(owner):
    foreign = upload(owner, "admin.wav")
    assert owner.post("/api/users", json={"username": "maria", "password": "test-password"}).status_code == 200
    owner.post("/api/auth/logout"); owner.post("/api/auth/login", json={"username": "maria", "password": "test-password"})
    own = upload(owner, "maria.wav")
    response = owner.post("/api/items/delete", json={"kind": "media", "ids": [own["id"], foreign["id"]]})
    assert response.status_code == 403
    assert s.safe_path(own["path"]).exists() and s.safe_path(foreign["path"]).exists()
    assert len(owner.get("/api/media").json()) == 1


def test_staged_removal_is_restored_when_database_commit_fails(owner, monkeypatch):
    media = upload(owner)
    real_db = s.db
    @contextmanager
    def failing_db():
        with real_db() as conn:
            class Proxy:
                execute = conn.execute
                def commit(self):
                    raise OSError("simulated commit failure")
            yield Proxy()
    monkeypatch.setattr(s, "db", failing_db)
    with pytest.raises(OSError, match="commit failure"):
        remove(owner, "media", [media["id"]])
    monkeypatch.setattr(s, "db", real_db)
    assert s.get("media", media["id"])["path"] == media["path"]
    assert s.safe_path(media["path"]).read_bytes() == audio_bytes()


def test_restart_recovers_an_interrupted_file_removal(owner, data):
    from app.library import recover_removals
    media = upload(owner)
    folder = data / "trash" / s.uid(); folder.mkdir(parents=True)
    s.safe_path(media["path"]).rename(folder / "move-0")
    s.atomic_json(folder / "manifest.json", {"kind": "media", "moves": [{"id": media["id"], "source": media["path"], "target": "move-0"}]})
    recover_removals()
    assert not folder.exists() and s.safe_path(media["path"]).read_bytes() == audio_bytes()


def test_default_uses_same_model_economically_with_ten_gib():
    from app.engine_policy import choose_profile
    project = {"engine": "qwen-1.7b"}
    profile = choose_profile(project, available=9.8*1024**3, memory_limit=10*1024**3)
    assert profile["engine"] == "qwen-1.7b" and profile["dtype"] == "bfloat16"
    project.update(engine="qwen-1.7b", dtype="float32")
    assert choose_profile(project, available=9.8*1024**3, memory_limit=10*1024**3, locked=True)["dtype"] == "float32"


def test_audio_source_is_automatically_dubbed_to_video(owner, data, monkeypatch):
    from app.worker import Worker
    media = upload(owner)
    voice = owner.post("/api/characters", json={"name": "Luna", "reference_id": media["id"]}).json()
    project = owner.post("/api/projects", json={"name": "Dublar áudio", "mode": "dub", "media_id": media["id"], "character_id": voice["id"]}).json()
    response = owner.post("/api/projects/" + project["id"] + "/generate")
    assert response.status_code == 200, response.text
    job = s.get("job", response.json()["id"])
    worker = Worker()
    def engine(ident, request, folder):
        if request["engine"].startswith("whisper-"):
            type(data)(request["output"]).write_text(json.dumps([{"start_ms": 250, "end_ms": 3250, "text": "Olá! Tudo bem?"}]))
        else:
            type(data)(request["output"]).write_bytes(audio_bytes(1))
    def prepare(ident, project, folder):
        for segment in project["segments"]:
            segment["character"].update(prepared_reference=media["path"], prepared_reference_text="Referência de teste.")
    monkeypatch.setattr(worker, "engine", engine); monkeypatch.setattr(worker, "prepare_references", prepare)
    worker.update(job["id"], status="running"); worker.execute(job)
    result = s.get("job", job["id"])
    out = result["outputs"][0]
    info = probe(s.safe_path(out["path"]))
    assert out["type"] == "video" and out["name"] == "Luna 1.mp4"
    assert info["audio"] and info["video"] and abs(info["duration"] - 4) < .06
    assert result["cues"][0]["text"] == "Olá!  Tudo bem?" or result["cues"][0]["text"] == "Olá! Tudo bem?"


def test_refresh_and_restart_keep_jobs_and_saved_text(owner, data):
    project = owner.post("/api/projects", json={"name": "Longo", "text": "Não perder meu texto."}).json()
    job = s.put("job", {"owner_username": "admin", "name": "Longo 1", "project_id": project["id"], "status": "paused", "progress": 30, "snapshot": project})
    s.init()
    assert owner.get("/api/reactions").status_code == 200
    assert owner.get("/api/jobs").json()[0]["id"] == job["id"]
    assert owner.get("/api/projects/" + project["id"]).json()["text"] == project["text"]
    assert remove(owner, "media", [s.uid()])["missing"]
