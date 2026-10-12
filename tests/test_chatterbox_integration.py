"""Download, CPU dispatch and resume contracts; no neural models are executed."""
import hashlib
import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext

import numpy as np
import pytest

from app import storage as s
from app.catalog import CATALOG, DEFAULT_MODELS, models_needed, model_files
from app.engine_policy import choose_profile, MemoryUnavailable
from app.worker import Worker
from app.model_manager import ModelManager
from scripts.models import download_plan, validate_plan

ENGINE = "chatterbox-pt-br"


def fake_source():
    calls, contents = [], {}
    def info(repo, revision, files_metadata, timeout):
        calls.append((repo, revision))
        spec = next(x for x in [CATALOG[ENGINE], *CATALOG[ENGINE]["companions"]] if x["repo"] == repo)
        names = [*spec["files"], "unused-old-decoder.pt"]
        siblings = []
        for name in names:
            value = (repo + "/" + name).encode()
            contents[repo, name] = value
            siblings.append(SimpleNamespace(rfilename=name, size=len(value),
                                           lfs=SimpleNamespace(sha256=hashlib.sha256(value).hexdigest())))
        return SimpleNamespace(sha=revision, siblings=siblings)
    return SimpleNamespace(model_info=info), contents, calls


def test_optional_download_selects_only_ptbr_v3_and_pinned_companions(data, monkeypatch):
    import scripts.models as module
    api, contents, calls = fake_source()
    plan = download_plan(CATALOG[ENGINE], api)
    assert ENGINE not in DEFAULT_MODELS
    assert set(plan["files"]) == {"README.md", "t3_pt_br.safetensors", "s3gen_v3.safetensors",
                                  "grapheme_mtl_merged_expanded_v1.json", "ve.safetensors"}
    assert len(calls) == 2 and all(len(revision) == 40 for _, revision in calls)
    folder = data / "models" / ENGINE
    folder.mkdir()
    s.atomic_json(folder / "download-plan.json", plan)
    downloads = []
    def hf_hub_download(repo_id, revision, local_dir, filename, headers):
        downloads.append((repo_id, revision, filename))
        (Path(local_dir) / filename).write_bytes(contents[repo_id, filename])
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=lambda: api, hf_hub_download=hf_hub_download, constants=SimpleNamespace()))
    monkeypatch.setattr(sys, "argv", ["models", "install", ENGINE, "--accept-license"])
    module.main()
    installed, manifest, source = model_files(ENGINE)
    assert installed == folder and source == "downloaded"
    assert len(downloads) == 5 and len({repo for repo, _, _ in downloads}) == 2
    assert manifest["sources"] == plan["sources"]
    assert all(s.digest(folder / name) == sha for name, sha in manifest["files"].items())
    assert not (folder / "unused-old-decoder.pt").exists()
    (folder / "ve.safetensors").unlink()
    assert model_files(ENGINE)[0] is None  # A partial download never becomes usable.


def test_download_rejects_missing_or_replaced_companion(data):
    api, _, _ = fake_source()
    meta = CATALOG[ENGINE]
    plan = download_plan(meta, api)
    missing = {**plan, "sources": plan["sources"][:1]}
    with pytest.raises(ValueError, match="incompleto"):
        validate_plan(missing, meta, data)
    plan["sources"][1]["revision"] = "bad-revision"
    with pytest.raises(ValueError, match="incompleto"):
        validate_plan(plan, meta, data)


def test_retry_preparation_refreshes_stale_companion_plan(data, monkeypatch):
    folder = data / "models" / ENGINE
    folder.mkdir()
    s.atomic_json(folder / "download-plan.json", {"repo": "old", "files": {}})
    manager = ModelManager()
    manager.request(ENGINE, accept_license=True)
    calls = []
    def run(ident, args, log):
        calls.append(args[3])
        if args[3] == "plan":
            api, _, _ = fake_source()
            s.atomic_json(folder / "download-plan.json", download_plan(CATALOG[ENGINE], api))
        else:
            (folder / "manifest.json").write_text("{}")
    monkeypatch.setattr(manager, "_run", run)
    manager._download(ENGINE)
    assert calls == ["plan", "install"] and manager.status(ENGINE)["status"] == "completed"


def test_chatterbox_keeps_same_float32_model_under_10gib():
    project = {"mode": "tts", "engine": ENGINE, "adaptive_memory": True}
    profile = choose_profile(project, available=9*1024**3, memory_limit=10*1024**3)
    assert profile["engine"] == ENGINE and profile["dtype"] == "float32" and not profile["adapted"]
    with pytest.raises(MemoryUnavailable):
        choose_profile(project, available=4*1024**3)
    with pytest.raises(MemoryUnavailable):
        choose_profile({**project, "dtype": "float32"}, available=4*1024**3, locked=True)


def test_tts_reference_does_not_require_whisper_but_dubbing_does():
    project = {"mode": "tts", "engine": ENGINE,
               "segments": [{"text": "Olá", "character": {"reference": {"path": "voice.wav"}, "reference_text": ""}}]}
    assert models_needed(project) == [ENGINE]
    project.update(mode="dub", automatic_dub=True, asr_engine="whisper-large-v3-turbo")
    assert models_needed(project) == [ENGINE, "whisper-large-v3-turbo"]


def test_api_queues_download_without_transcription_and_freezes_expression(owner):
    media = s.put("media", {"audio": True, "path": "media/reference.wav", "owner_username": "admin"})
    character = owner.post("/api/characters", json={"name": "Minha voz", "reference_id": media["id"]}).json()
    project = owner.post("/api/projects", json={"name": "Expressão", "engine": ENGINE,
                         "character_id": character["id"], "text": "Que surpresa!", "expressiveness": 0.9}).json()
    response = owner.post("/api/projects/" + project["id"] + "/generate")
    assert response.status_code == 200, response.text
    saved = s.get("job", response.json()["id"])
    assert saved["snapshot"]["engine"] == ENGINE and saved["snapshot"]["expressiveness"] == 0.9
    assert [item["id"] for item in s.listing("model_download", limit=-1)] == [ENGINE]
    assert owner.post("/api/projects", json={"name": "Invalid", "engine": ENGINE, "expressiveness": 10}).status_code == 422


@pytest.mark.parametrize("text,language", [("Olá", "en-US"), ("[idioma=en-US]Hello", "pt-BR")])
def test_specialized_ptbr_model_rejects_unsupported_output_language(owner, text, language):
    media = s.put("media", {"audio": True, "path": "media/reference.wav", "owner_username": "admin"})
    character = owner.post("/api/characters", json={"name": "Minha voz", "reference_id": media["id"]}).json()
    project = owner.post("/api/projects", json={"name": "Teste", "engine": ENGINE, "character_id": character["id"],
                         "text": text, "language": language}).json()
    response = owner.post("/api/projects/" + project["id"] + "/generate")
    assert response.status_code == 400 and "Português brasileiro" in response.text


def recording(path, seconds=1):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
        out.writeframes(b"\x10\x00" * (24000*seconds))


def test_worker_clones_without_asr_and_resume_reuses_disk_chunks(data, monkeypatch):
    import app.worker as module
    source = data / "media" / "reference.wav"
    recording(source, 6)
    character = {"name": "Minha voz", "number": 1, "reference": {"path": "media/reference.wav"}, "reference_text": ""}
    project = {"mode": "tts", "engine": ENGINE, "dtype": "float32", "expressiveness": 0.85,
               "name": "Expressão", "language": "pt-BR", "format": "wav",
               "segments": [{"text": text, "language": "pt-BR", "rate": 1, "volume": 0, "character": dict(character)}
                            for text in ["Uma surpresa!", "Que alegria."]]}
    job = s.put("job", {"status": "running", "stage": "Preparando", "name": "Expressão", "snapshot": project})
    sessions, requests = [], []
    class Session:
        def __init__(self, worker, ident, request, folder):
            sessions.append(self); self.closed = False
        def generate(self, request):
            assert request["engine"] == ENGINE  # ASR must never run for this reference.
            requests.append(dict(request)); recording(request["output"])
        def close(self): self.closed = True
    monkeypatch.setattr(module, "EngineSession", Session)
    worker = Worker()
    worker.execute(job)
    assert len(sessions) == 1 and sessions[0].closed and len(requests) == 2
    assert [r["text"] for r in requests] == ["Uma surpresa!", "Que alegria."]
    assert all(r["expressiveness"] == 0.85 and r["dtype"] == "float32" and r["reference_text"] == "" for r in requests)
    worker.execute(s.get("job", job["id"]))
    assert len(sessions) == 1 and len(requests) == 2


def test_loader_uses_ptbr_and_v3_decoder_locally_in_cpu(data, monkeypatch):
    from app.chatterbox_engine import load_model
    calls = []
    class Module:
        ignore_state_dict_missing = ()
        def load_state_dict(self, state, **kwargs): calls.append((state, kwargs))
        def to(self, device): assert device == "cpu"; return self
        def eval(self): return self
    class Decoder(Module):
        ignore_state_dict_missing = ("tokenizer._mel_filters", "tokenizer.window")
        def get_buffer(self, name): return "derived-" + name
    class BaseTokenizer:
        def __init__(self, _): pytest.fail("Portuguese must not load Chinese segmentation")
        def check_vocabset_sot_eot(self): self.checked = True
    monkeypatch.setitem(sys.modules, "safetensors.torch", SimpleNamespace(load_file=lambda name, device: {"file": name}))
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", SimpleNamespace(ChatterboxMultilingualTTS=lambda *args, **kw: (args, kw)))
    monkeypatch.setitem(sys.modules, "chatterbox.models.t3", SimpleNamespace(T3=lambda config: Module()))
    monkeypatch.setitem(sys.modules, "chatterbox.models.t3.modules.t3_config", SimpleNamespace(T3Config=SimpleNamespace(multilingual=lambda: "multilingual")))
    monkeypatch.setitem(sys.modules, "chatterbox.models.s3gen", SimpleNamespace(S3Gen=Decoder))
    monkeypatch.setitem(sys.modules, "chatterbox.models.voice_encoder", SimpleNamespace(VoiceEncoder=Module))
    monkeypatch.setitem(sys.modules, "chatterbox.models.tokenizers", SimpleNamespace(MTLTokenizer=BaseTokenizer))
    monkeypatch.setitem(sys.modules, "tokenizers", SimpleNamespace(Tokenizer=SimpleNamespace(from_file=lambda path: path)))
    args, kwargs = load_model(data, SimpleNamespace())
    assert [Path(state["file"]).name for state, _ in calls] == ["ve.safetensors", "t3_pt_br.safetensors", "s3gen_v3.safetensors"]
    assert calls[-1][0]["tokenizer._mel_filters"] == "derived-tokenizer._mel_filters"
    assert calls[-1][0]["tokenizer.window"] == "derived-tokenizer.window"
    assert all(options == {"strict": True, "assign": True} for _, options in calls)
    assert args[-1] == "cpu" and kwargs == {"conds": None}
    assert args[-2].checked and args[-2].cangjie_converter is None


def test_reference_cache_and_expression_are_restored_after_engine_reload(data, monkeypatch):
    import app.chatterbox_engine as module
    builds, outputs, loads = [], [], []
    class Conditions:
        def __init__(self, reference): self.reference = reference
        def save(self, path): Path(path).write_text(self.reference)
        @classmethod
        def load(cls, path, map_location):
            assert map_location == "cpu"; loads.append(path); return cls(Path(path).read_text())
    class Tensor:
        def squeeze(self, *_): return self
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return np.zeros(24000, dtype=np.float32)
    class Model:
        sr = 24000
        conds = None
        def prepare_conditionals(self, reference, exaggeration):
            builds.append(reference); self.conds = Conditions(reference)
        def generate(self, text, **options):
            outputs.append((text, self.conds.reference, options)); return Tensor()
    torch = SimpleNamespace(backends=SimpleNamespace(nnpack=SimpleNamespace(set_flags=lambda _: None)),
                            set_num_threads=lambda _: None, set_num_interop_threads=lambda _: None,
                            inference_mode=nullcontext)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=lambda path, *_: recording(path)))
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", SimpleNamespace(Conditionals=Conditions))
    monkeypatch.setattr(module, "load_model", lambda *_: Model())
    monkeypatch.setattr(module, "memory_available", lambda: 10*1024**3)
    references = [data / "media" / "one.wav", data / "media" / "two.wav"]
    references[0].write_bytes(b"reference one"); references[1].write_bytes(b"reference two")
    request = {"model_path": str(data / "models"), "model_revision": "pinned", "dtype": "float32",
               "reference": str(references[0]), "text": "Fala intacta!", "language": "pt-BR",
               "expressiveness": 0.9, "checkpoint": True, "output": str(data / "jobs" / "raw.wav")}
    engine = module.ChatterboxEngine(request)
    engine.generate(request); engine.generate({**request, "reference": str(references[1])})
    assert len(builds) == 2
    engine = module.ChatterboxEngine(request)
    engine.generate(request)
    assert len(builds) == 2 and len(loads) == 1
    assert outputs[-1][:2] == ("Fala intacta!", str(references[0]))
    assert outputs[-1][2]["exaggeration"] == 0.9 and outputs[-1][2]["language_id"] == "pt"
    assert outputs[-1][2]["audio_prompt_path"] is None and engine.model.conds.reference == str(references[0])
    assert (data / "jobs" / "raw.json").is_file()
