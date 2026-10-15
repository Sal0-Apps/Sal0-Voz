"""Quality profile, real 24-bit audio and recovery; no neural models or weights."""
import json
import subprocess
import sys
import wave
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app import storage as s
from app.audio_files import checkpoint_audio, audio_valid
from app.catalog import CATALOG
from app.generation_limits import omnivoice_capacity
from app.media import ffargs
from app.omnivoice_quality import MAXIMUM_PROFILE, LEGACY_PROFILE, generation_options
from app.resources import ProcessInterrupted, TextCapacityExceeded
from app.worker import Worker


def recording(path, samples=None, seconds=1):
    samples = samples if samples is not None else np.tile([1, 257, -129, 32767], 6000*seconds)
    encoded = np.asarray(samples, dtype="<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(3); out.setframerate(24000)
        out.writeframes(encoded)
    return encoded


def job_for(data, **overrides):
    project = {"engine": "omnivoice", "omnivoice_profile": MAXIMUM_PROFILE,
               "omnivoice_seed": 1234, "output_sample_width": 3, "dtype": "float32",
               "mode": "tts", "language": "pt-BR", "name": "Qualidade", "format": "wav",
               "segments": []}
    project.update(overrides)
    job = s.put("job", {"status": "running", "stage": "Gerando", "snapshot": project})
    folder = data/"jobs"/job["id"]; folder.mkdir(exist_ok=True)
    return job, folder


def test_new_jobs_freeze_maximum_profile_and_unique_seed_without_changing_the_project(owner, data):
    ref = data/"media"/"ref.wav"; recording(ref, seconds=4)
    media = s.put("media", {"path": "media/ref.wav", "audio": True, "owner_username": "admin"})
    voice = owner.post("/api/characters", json={"name": "Voz", "reference_id": media["id"], "reference_text": "Referência correta."}).json()
    project = owner.post("/api/projects", json={"name": "Qualidade", "engine": "omnivoice", "character_id": voice["id"], "text": "Uma fala inteira. "*80}).json()
    jobs = [s.get("job", owner.post("/api/projects/"+project["id"]+"/generate").json()["id"]) for _ in range(2)]
    for job in jobs:
        snap = job["snapshot"]
        assert snap["omnivoice_profile"] == MAXIMUM_PROFILE
        assert snap["output_sample_width"] == 3 and snap["output_sample_rate"] == 24000
        assert len(snap["segments"]) == 1 and snap["segments"][0]["text"] == project["text"]
    assert jobs[0]["snapshot"]["omnivoice_seed"] != jobs[1]["snapshot"]["omnivoice_seed"]
    assert "omnivoice_profile" not in owner.get("/api/projects/"+project["id"]).json()
    assert generation_options(LEGACY_PROFILE)["num_step"] == 32
    with pytest.raises(ValueError, match="desconhecido"):
        generation_options("unknown")


def test_native_context_guard_rejects_overflow_before_attention_and_restores_model():
    calls = []
    def prepare(text, num_target_tokens):
        calls.append(text)
        return {"input_ids": np.empty((1, 8, num_target_tokens+10))}
    model = SimpleNamespace(_prepare_inference_inputs=prepare,
                            config=SimpleNamespace(llm_config=SimpleNamespace(max_position_embeddings=100)))
    with omnivoice_capacity(model):
        assert model._prepare_inference_inputs("Inteiro", 90)["input_ids"].shape[-1] == 100
        with pytest.raises(TextCapacityExceeded): model._prepare_inference_inputs("Referência também conta", 91)
        with pytest.raises(TextCapacityExceeded): model._prepare_inference_inputs("Sem alocação enorme", 100000000)
    assert calls == ["Inteiro", "Referência também conta"] and model._prepare_inference_inputs is prepare


def test_engine_uses_64_steps_untouched_reference_and_repeatable_resume(data, monkeypatch):
    import app.omnivoice_engine as module
    builds, generations, writes, seeds = [], [], [], []
    state = [None]
    @contextmanager
    def fork_rng(devices):
        assert devices == []
        previous = state[0]
        try: yield
        finally: state[0] = previous
    def manual_seed(seed): state[0] = seed; seeds.append(seed)
    class Prompt:
        def __init__(self, text): self.text = text
        def save(self, path): Path(path).write_text(self.text)
        @classmethod
        def load(cls, path, map_location): return cls(Path(path).read_text())
    class Model:
        sampling_rate = 24000
        config = SimpleNamespace(llm_config=SimpleNamespace(max_position_embeddings=40960))
        invalid = False
        def eval(self): return self
        @classmethod
        def from_pretrained(cls, folder, **kwargs):
            assert kwargs["dtype"] == "float32" and kwargs["device_map"] == "cpu" and not kwargs["load_asr"]
            return cls()
        def _prepare_inference_inputs(self, *args): return {"input_ids": np.empty((1, 8, 2000))}
        def create_voice_clone_prompt(self, **kwargs):
            builds.append(kwargs)
            return Prompt(kwargs["ref_text"])
        def generate(self, **kwargs):
            generations.append(kwargs)
            # Exercise the native-context hook used before backend attention.
            self._prepare_inference_inputs(kwargs["text"], 1900)
            value = np.random.default_rng(state[0]).uniform(-0.2, 0.2, 24000).astype(np.float32)
            value[:2] = [1.3, -1.5]
            if self.invalid: value[-1] = np.nan
            return [value]
    torch = SimpleNamespace(float32="float32", backends=SimpleNamespace(nnpack=SimpleNamespace(set_flags=lambda _: None)),
                            set_num_threads=lambda _: None, set_num_interop_threads=lambda _: None,
                            inference_mode=nullcontext, random=SimpleNamespace(fork_rng=fork_rng), manual_seed=manual_seed)
    def write(path, audio, rate, subtype):
        assert subtype == "PCM_24" and rate == 24000
        writes.append(audio.copy())
        recording(path, np.rint(audio*8388607).astype(np.int32))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "omnivoice", SimpleNamespace(OmniVoice=Model, VoiceClonePrompt=Prompt))
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=write))
    monkeypatch.setattr(module, "memory_available", lambda: 10*1024**3)
    folder = data/"models"/"omnivoice"
    for name in CATALOG["omnivoice"]["files"]:
        path = folder/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"substitute")
    ref = data/"media"/"ref.wav"; recording(ref)
    job, output = job_for(data)
    text = "Esta fala mantém o contexto, a referência e as pausas. "*40
    request = {**job["snapshot"], "model_path": str(folder), "model_revision": "fixed",
               "reference": str(ref), "reference_text": "Texto exato sem alterações",
               "text": text, "output": str(output/"raw.wav"), "checkpoint": True}
    engine = module.OmniVoiceEngine(request); engine.generate(request)
    reloaded = module.OmniVoiceEngine(request); reloaded.generate(request)
    assert len(builds) == 1 and builds[0]["preprocess_prompt"] is False
    assert all(x["text"] == text and x["num_step"] == 64 and x["voice_clone_prompt"].text == request["reference_text"] for x in generations)
    assert all(x["normalize_text"] is False and x["postprocess_output"] is False for x in generations)
    assert all(x["audio_chunk_threshold"] > 1000 and x["guidance_scale"] == 2 for x in generations)
    assert seeds[0] == seeds[1] and state[0] is None
    np.testing.assert_array_equal(writes[0], writes[1])
    assert abs(writes[0]).max() <= 0.999001 and audio_valid(request["output"])
    with wave.open(request["output"]) as wav: assert wav.getsampwidth() == 3
    reloaded.model.invalid = True
    invalid = {**request, "output": str(output/"invalid.wav")}
    with pytest.raises(ValueError, match="amostras inválidas"): reloaded.generate(invalid)
    assert not Path(invalid["output"]).exists() and not audio_valid(invalid["output"])


@pytest.mark.parametrize("extension", ["wav", "flac", "mp3", "opus"])
def test_full_export_and_pause_preserve_real_24_bit_samples(data, monkeypatch, extension):
    ref = data/"media"/"ref.wav"; reference_bytes = recording(ref, seconds=4)
    character = {"reference": {"path": "media/ref.wav"}, "reference_text": "Minha gravação exata."}
    segment = {"text": "A fala inteira.", "character": character, "language": "pt-BR", "rate": 1, "volume": 0}
    job, folder = job_for(data, format=extension, segments=[segment, {"pause_ms": 100, "text": ""}])
    worker = Worker(); calls = []
    def engine(ident, request, directory):
        calls.append(dict(request))
        with wave.open(request["reference"]) as wav:
            assert wav.getsampwidth() == 3 and wav.readframes(wav.getnframes()) == reference_bytes
        recording(request["output"])
    monkeypatch.setattr(worker, "engine", engine)
    worker.execute(job)
    assert calls[0]["omnivoice_profile"] == MAXIMUM_PROFILE and calls[0]["omnivoice_seed"] == 1234
    expected = np.concatenate([np.tile([1,257,-129,32767],6000), np.zeros(2400, dtype=np.int32)])
    with wave.open(str(folder/"joined.wav")) as wav:
        assert wav.getsampwidth() == 3 and wav.getnframes() == 26400
    exported = data/"exports"/(job["id"]+"."+extension)
    decoded = subprocess.run(ffargs("-i", exported, "-f", "s32le", "-c:a", "pcm_s32le", "-"), capture_output=True, check=True).stdout
    if extension in ("wav", "flac"):
        np.testing.assert_array_equal(np.frombuffer(decoded, dtype="<i4"), expected.astype(np.int32)*256)
    else:
        assert len(decoded) >= len(expected)*4
        metadata = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(exported)]))["streams"][0]
        assert metadata["channels"] == 1
        if extension == "mp3":
            assert metadata["bit_rate"] == "160000" and metadata["sample_rate"] == "24000"
    worker.execute(s.get("job",job["id"]))
    assert len(calls) == 1  # Neither the reference nor a confirmed take is regenerated.
    assert not list(folder.glob("*.pcm"))


def test_dubbing_keeps_24_bit_timing_through_tempo_adjustment_and_exports_aac(data, monkeypatch):
    ref = data/"media"/"ref.wav"; recording(ref, seconds=4)
    character = {"reference": {"path": "media/ref.wav"}, "reference_text": "Minha gravação exata."}
    segment = {"text": "A fala inteira.", "character": character, "language": "pt-BR", "rate": 1,
               "volume": 0, "start_ms": 500, "end_ms": 1000}
    job, folder = job_for(data, mode="dub", automatic_dub=True,
                          media={"path": "media/ref.wav", "duration": 2, "audio": True, "video": False},
                          segments=[segment])
    worker = Worker()
    monkeypatch.setattr(worker, "engine", lambda ident, request, directory: recording(request["output"]))
    worker.execute(job)
    with wave.open(str(folder/"joined.wav")) as wav:
        assert wav.getsampwidth() == 3 and wav.getnframes() == 48000
        assert wav.readframes(12000) == b"\0"*36000
    fitted = sorted(folder.glob("fitted-*.wav"))[-1]
    with wave.open(str(fitted)) as wav:
        assert wav.getsampwidth() == 3 and wav.getnframes() <= 12000
    output = data/"exports"/(job["id"]+".mp4")
    streams = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)]))["streams"]
    audio = next(x for x in streams if x["codec_type"] == "audio")
    assert audio["codec_name"] == "aac" and audio["sample_rate"] == "24000"
    assert not list(folder.glob("*.pcm"))


def test_24_bit_timeline_keeps_exact_positions_and_rejects_incompatible_parts(data):
    job, folder = job_for(data)
    source = folder/"source.wav"; samples = np.tile([1,-129,257], 8000); recording(source, samples)
    worker = Worker(); joined = folder/"timeline.wav"
    worker.timeline([(source, 500)], joined, 48000, job["id"], sample_width=3)
    with wave.open(str(joined)) as wav:
        assert wav.getnframes() == 48000 and wav.getsampwidth() == 3
        assert wav.readframes(12000) == b"\0"*36000
        assert wav.readframes(24000) == source.read_bytes()[44:]
        assert wav.readframes(12000) == b"\0"*36000
    with pytest.raises(ValueError, match="incompatíveis"):
        worker.concatenate([source], joined, job["id"], sample_width=2)


def test_overload_and_lost_reply_keep_64_steps_seed_and_24_bit_checkpoints(data, monkeypatch):
    import app.worker as module
    ref = data/"media"/"ref.wav"; recording(ref)
    text = "Uma frase que preserva cada palavra e o contexto completo. "*20
    job, folder = job_for(data)
    request = {"engine": "omnivoice", "text": text, "language": "pt-BR", "reference": str(ref),
               "reference_text": "Minha voz.", "output": str(folder/"raw-000000.wav"), "checkpoint": True}
    calls, lost = [], [False]
    class Session:
        def __init__(self, *_): pass
        def close(self): pass
        def generate(self, req):
            calls.append(dict(req))
            if len(req["text"]) > len(text)//2+1: raise TextCapacityExceeded("Native context")
            recording(req["output"]); checkpoint_audio(req["output"])
            if not lost[0]: lost[0] = True; raise ProcessInterrupted("Saved, reply lost")
    monkeypatch.setattr(module, "EngineSession", Session)
    worker = Worker()
    with pytest.raises(TextCapacityExceeded): worker.synthesize(job["id"], request, folder)
    worker.close_clone()
    with pytest.raises(ProcessInterrupted): worker.synthesize(job["id"], request, folder)
    worker.close_clone(); worker.synthesize(job["id"], request, folder); worker.close_clone()
    assert len(calls) == 3 and "".join(x["text"] for x in calls[1:]) == text
    assert all(x["omnivoice_profile"] == MAXIMUM_PROFILE and x["omnivoice_seed"] == 1234 and x["dtype"] == "float32" for x in calls)
    with wave.open(request["output"]) as wav: assert wav.getsampwidth() == 3 and wav.getnframes() == 48000
    assert audio_valid(request["output"])
