"""Optional downloads, CPU contracts and checkpoints; no neural inference."""
import hashlib
import json
import sys
import wave
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app import storage as s
from app.catalog import CATALOG, DEFAULT_MODELS, models_needed, model_files
from app.engine_policy import choose_profile, MemoryUnavailable
from app.worker import Worker
from scripts.models import download_plan, validate_plan


def recording(path, seconds=1, rate=24000):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(b"\0\0" * round(seconds * rate))


@pytest.mark.parametrize("engine", ["omnivoice", "voxcpm2"])
def test_optional_pinned_download_is_complete_and_resumable(data, monkeypatch, engine):
    import scripts.models as module
    meta = CATALOG[engine]
    values = {name: (engine + name).encode() for name in meta["files"]}
    siblings = [SimpleNamespace(rfilename=name, size=len(value),
                                lfs=SimpleNamespace(sha256=hashlib.sha256(value).hexdigest()))
                for name, value in {**values, "unused-checkpoint.bin": b"unused"}.items()]
    def info(repo, revision, files_metadata, timeout):
        assert repo == meta["repo"] and revision == meta["revision"] and files_metadata
        return SimpleNamespace(sha=revision, siblings=siblings)
    api = SimpleNamespace(model_info=info)
    plan = download_plan(meta, api)
    assert engine not in DEFAULT_MODELS and set(plan["files"]) == set(meta["files"])
    folder = data / "models" / engine
    folder.mkdir()
    s.atomic_json(folder / "download-plan.json", plan)
    # Preserve one already downloaded file across the installation attempt.
    existing = folder / "README.md"
    existing.write_bytes(values["README.md"])
    downloads = []
    def hf_hub_download(repo_id, revision, local_dir, filename, headers):
        downloads.append((repo_id, revision, filename))
        assert existing.read_bytes() == values["README.md"]
        assert headers["Cache-Control"] == "no-cache"
        target = Path(local_dir) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(values[filename])
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=lambda: api, hf_hub_download=hf_hub_download, constants=SimpleNamespace()))
    monkeypatch.setattr(sys, "argv", ["models", "install", engine, "--accept-license"])
    module.main()
    assert {name for _, _, name in downloads} == set(meta["files"]) - {"README.md"}
    assert all((repo, rev) == (meta["repo"], meta["revision"]) for repo, rev, _ in downloads)
    installed, manifest, source = model_files(engine)
    assert installed == folder and source == "downloaded"
    assert all(s.digest(folder / name) == sha for name, sha in manifest["files"].items())
    assert not (folder / "unused-checkpoint.bin").exists()
    incomplete = {**plan, "files": {"README.md": plan["files"]["README.md"]}}
    with pytest.raises(ValueError, match="incompleto"):
        validate_plan(incomplete, meta, folder)
    (folder / meta["files"][-1]).unlink()
    assert model_files(engine)[0] is None


@pytest.mark.parametrize("engine,dtype", [("omnivoice", "float32"), ("voxcpm2", "float16")])
def test_full_precision_is_locked_under_10gib(engine, dtype):
    project = {"mode": "tts", "engine": engine, "adaptive_memory": True}
    result = choose_profile(project, available=9*1024**3, memory_limit=10*1024**3)
    assert result["engine"] == engine and result["dtype"] == dtype and not result["adapted"]
    with pytest.raises(MemoryUnavailable):
        choose_profile({**project, "dtype": dtype}, available=3*1024**3, locked=True)


@pytest.mark.parametrize("engine", ["omnivoice", "voxcpm2"])
def test_models_need_whisper_only_when_reference_or_original_needs_transcription(engine):
    project = {"mode": "tts", "engine": engine, "segments": [{"character": {"reference": {"id": "sample"}, "reference_text": ""}}]}
    assert models_needed(project) == [engine, "whisper-large-v3-turbo"]
    project["segments"][0]["character"]["reference_text"] = "A transcrição exata."
    assert models_needed(project) == [engine]
    assert models_needed({**project, "automatic_dub": True}) == [engine, "whisper-large-v3-turbo"]


@pytest.mark.parametrize("engine", ["omnivoice", "voxcpm2"])
def test_catalog_download_and_job_freeze_model_style_and_precision(owner, engine):
    models = {row["id"]: row for row in owner.get("/api/models").json()}
    assert engine in models and models[engine]["clone"] and not models[engine]["available"]
    assert owner.post("/api/models/" + engine + "/download", json={"accept_license": True}).status_code == 200
    reference = s.put("media", {"path": "media/reference.wav", "audio": True, "owner_username": "admin"})
    voice = owner.post("/api/characters", json={"name": "Voz nova", "reference_id": reference["id"], "reference_text": "Texto exato."}).json()
    project = owner.post("/api/projects", json={"name": "Clonagem", "engine": engine, "voice_style": "happy", "text": "Que alegria!", "character_id": voice["id"]}).json()
    created = owner.post("/api/projects/" + project["id"] + "/generate").json()
    job = s.get("job", created["id"])
    assert job["status"] == "queued" and job["snapshot"]["engine"] == engine
    assert job["snapshot"]["voice_style"] == "happy"
    assert job["snapshot"]["output_sample_rate"] == CATALOG[engine].get("sample_rate", 24000)
    owner.put("/api/projects/" + project["id"], json={**project, "voice_style": "sad"})
    assert s.get("job", created["id"])["snapshot"]["voice_style"] == "happy"


def test_omnivoice_full_steps_and_prompt_survive_engine_reload(data, monkeypatch):
    import app.omnivoice_engine as module
    builds, generations, loads = [], [], []
    class Prompt:
        def __init__(self, transcript): self.transcript = transcript
        def save(self, path): Path(path).write_text(self.transcript)
        @classmethod
        def load(cls, path, map_location):
            assert map_location == "cpu"; loads.append(path)
            return cls(Path(path).read_text())
    class Model:
        sampling_rate = 24000
        def eval(self): return self
        @classmethod
        def from_pretrained(cls, folder, **kwargs):
            assert kwargs["device_map"] == "cpu" and kwargs["dtype"] == "float32"
            assert kwargs["local_files_only"] and kwargs["load_asr"] is False
            return cls()
        def create_voice_clone_prompt(self, ref_audio, ref_text):
            builds.append(ref_audio); return Prompt(ref_text)
        def generate(self, **kwargs):
            generations.append(kwargs); return [np.zeros(24000, dtype=np.float32)]
    torch = SimpleNamespace(float32="float32", backends=SimpleNamespace(nnpack=SimpleNamespace(set_flags=lambda _: None)),
                            set_num_threads=lambda _: None, set_num_interop_threads=lambda _: None, inference_mode=nullcontext)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "omnivoice", SimpleNamespace(OmniVoice=Model, VoiceClonePrompt=Prompt))
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=lambda path, *_: recording(path)))
    monkeypatch.setattr(module, "memory_available", lambda: 10*1024**3)
    folder = data / "models" / "omnivoice"
    for name in CATALOG["omnivoice"]["files"]:
        path = folder / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"substitute")
    reference = data / "media" / "reference.wav"
    reference.write_bytes(b"reference substitute")
    request = {"model_path": str(folder), "model_revision": "fixed", "dtype": "float32", "reference": str(reference),
               "reference_text": "Texto da voz.", "text": "Alegria!", "language": "pt-BR", "output": str(data / "jobs" / "raw.wav"), "checkpoint": True}
    engine = module.OmniVoiceEngine(request)
    engine.generate(request); engine.generate(request)
    engine = module.OmniVoiceEngine(request); engine.generate(request)
    assert len(builds) == 1 and len(loads) == 1
    assert all(item["num_step"] == 32 and item["language"] == "pt" and item["text"] == "Alegria!" for item in generations)
    assert all(item["voice_clone_prompt"].transcript == "Texto da voz." for item in generations)
    assert (data / "jobs" / "raw.json").is_file()


def test_voxcpm_cpu_full_weights_style_and_atomic_checkpoint(data, monkeypatch):
    import app.voxcpm_engine as module
    binary = data / "native-cli"
    binary.write_text("#!" + sys.executable + "\n" + '''import sys,json,wave,pathlib
args=sys.argv[1:]
out=pathlib.Path(args[args.index('--output')+1])
out.with_suffix('.args.json').write_text(json.dumps(args))
with wave.open(str(out),'wb') as wav:
 wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(48000);wav.writeframes(b'\\0\\0'*48000)
''')
    binary.chmod(0o755)
    monkeypatch.setattr(module, "runtime_binary", lambda _: binary)
    monkeypatch.setattr(module, "memory_available", lambda: 10*1024**3)
    folder = data / "models" / "voxcpm2"; folder.mkdir()
    for name in CATALOG["voxcpm2"]["files"]: (folder / name).write_bytes(b"substitute")
    reference = data / "media" / "reference.wav"; recording(reference, rate=16000)
    request = {"model_path": str(folder), "dtype": "float16", "reference": str(reference), "reference_text": "Texto da voz.",
               "text": "Que alegria!", "voice_style": "happy", "output": str(data / "jobs" / "raw.wav"), "checkpoint": True}
    engine = module.VoxCPMEngine(request); engine.generate(request)
    args = json.loads((data / "jobs" / "raw.partial.args.json").read_text())
    assert "--cpu" in args and args[args.index("--prompt-text")+1] == "Texto da voz."
    assert args[args.index("--text")+1] == "(cheerful, joyful tone)Que alegria!"
    assert args[args.index("--timesteps")+1] == "10"
    assert all("Q8" not in arg for arg in args)
    assert (data / "jobs" / "raw.json").is_file() and not (data / "jobs" / "raw.partial.wav").exists()
    with wave.open(str(data / "jobs" / "raw.wav")) as wav: assert wav.getframerate() == 48000
    monkeypatch.setattr(module, "memory_available", lambda: 2*1024**3)
    with pytest.raises(MemoryUnavailable): engine.generate(request)


@pytest.mark.parametrize("engine,seconds,rate", [("omnivoice", 10, 24000), ("voxcpm2", 30, 16000)])
def test_reference_is_prepared_for_selected_engine(data, monkeypatch, engine, seconds, rate):
    import app.worker as module
    source = data / "media" / "source.wav"; recording(source, seconds=35)
    character = {"reference": {"path": "media/source.wav"}, "reference_text": ""}
    project = {"engine": engine, "language": "pt-BR", "segments": [{"text": "Fala", "character": character}]}
    job = s.put("job", {"status": "running", "snapshot": project})
    folder = data / "jobs" / job["id"]; folder.mkdir()
    worker = Worker()
    monkeypatch.setattr(module, "require", lambda *_: {"revision": "fixed-asr"})
    def asr(ident, request, output_folder):
        assert request["engine"] == "whisper-large-v3-turbo"
        with wave.open(request["source"]) as wav:
            assert wav.getframerate() == rate and wav.getnframes()/wav.getframerate() == seconds
        s.atomic_json(request["output"], [{"text": "Texto exato do trecho."}])
    monkeypatch.setattr(worker, "engine", asr)
    worker.prepare_references(job["id"], project, folder)
    assert character["prepared_reference_text"] == "Texto exato do trecho."
    monkeypatch.setattr(worker, "engine", lambda *_: pytest.fail("Reuse the prepared transcript"))
    worker.prepare_references(job["id"], project, folder)


def test_voxcpm_export_preserves_48khz_and_saved_segments(data, monkeypatch):
    import app.worker as module
    source = data / "media" / "source.wav"; recording(source, seconds=3, rate=16000)
    project = {"name": "Clonagem", "engine": "voxcpm2", "dtype": "float16", "mode": "tts", "language": "pt-BR", "format": "wav", "voice_style": "happy",
               "segments": [{"text": "Que alegria!", "language": "pt-BR", "rate": 1, "volume": 0,
                             "character": {"reference": {"path": "media/source.wav"}, "reference_text": "Texto."}}]}
    job = s.put("job", {"status": "running", "snapshot": project})
    worker = Worker(); calls = []
    def engine(ident, request, folder):
        calls.append(request); recording(request["output"], rate=48000)
    monkeypatch.setattr(worker, "engine", engine)
    worker.execute(job)
    with wave.open(str(data / "jobs" / job["id"] / "joined.wav")) as wav:
        assert wav.getframerate() == 48000 and wav.getnframes() == 48000
    assert calls[0]["voice_style"] == "happy" and calls[0]["engine"] == "voxcpm2"
    worker.execute(s.get("job", job["id"]))
    assert len(calls) == 1
