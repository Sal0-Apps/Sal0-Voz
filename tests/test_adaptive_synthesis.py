"""Whole text and overload recovery with substitutes and real FFmpeg; no weights."""
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app import storage as s
from app.audio_files import checkpoint_audio, audio_valid
from app.engine_policy import MemoryUnavailable
from app.generation_limits import chatterbox_capacity, qwen_capacity
from app.resources import ProcessInterrupted, TextCapacityExceeded
from app.script import compile_script, split_text
from app.worker import Worker


def recording(path):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
        out.writeframes(b"\x10\x00"*2400)
    checkpoint_audio(path)


@pytest.mark.parametrize("failure", [MemoryUnavailable, TextCapacityExceeded])
def test_only_overloaded_parts_split_and_saved_parts_resume_with_same_profile(data, monkeypatch, failure):
    import app.worker as module
    ref = data/"media"/"ref.wav"; recording(ref)
    text = "Primeira frase para preservar o contexto e a interpretação. "*16
    project = {"engine":"qwen-1.7b", "dtype":"float32", "mode":"tts", "segments":compile_script(text)}
    job = s.put("job", {"status":"running", "stage":"Gerando", "snapshot":project})
    folder = data/"jobs"/job["id"]; folder.mkdir()
    request = {"engine":"qwen-1.7b", "language":"pt-BR", "text":text, "reference":str(ref),
               "reference_text":"Referência", "voice_style":"natural", "expressiveness":0.7,
               "output":str(folder/"raw-000000.wav"), "checkpoint":True}
    calls, sessions, progress = [], [], []
    lost = [False]
    class Session:
        def __init__(self, *_):
            self.closed = False; sessions.append(self)
            assert all(x.closed for x in sessions[:-1])
        def close(self): self.closed = True
        def generate(self, req):
            calls.append(dict(req))
            if len(req["text"]) > len(text)//2+1:
                raise failure(9.5, 8) if failure is MemoryUnavailable else failure("Text limit")
            worker.engine_progress(job["id"], {"phase":"sampling", "completed":2, "total":4, "unit":"steps", "elapsed_seconds":10})
            progress.append(s.get("job",job["id"])["progress"])
            recording(Path(req["output"]))
            if not lost[0]:
                lost[0] = True
                raise ProcessInterrupted("Reply lost after checkpoint")
    monkeypatch.setattr(module, "EngineSession", Session)
    worker = Worker()
    worker.begin_progress(job["id"],0,85,"Trecho 1 de 1")
    with pytest.raises(failure): worker.synthesize(job["id"], request, folder)
    assert calls[0]["text"] == text
    plan = json.loads((folder/"raw-000000.parts.json").read_text())
    assert len(plan["parts"]) == 2  # Several sentences per part, not one per call.
    assert "".join(p["text"] for p in plan["parts"]) == text
    assert Worker.speech_started(project, folder)
    worker.close_clone()
    worker.begin_progress(job["id"],0,85,"Trecho 1 de 1")
    with pytest.raises(ProcessInterrupted): worker.synthesize(job["id"], request, folder)
    saved = next(folder.glob("raw-*.part-*.wav")); digest = s.digest(saved)
    worker.close_clone()
    worker.begin_progress(job["id"],0,85,"Trecho 1 de 1")
    worker.synthesize(job["id"], request, folder); worker.close_clone()
    assert len(calls) == 3 and all(x.closed for x in sessions)
    assert "".join(c["text"] for c in calls[1:]) == text
    assert {(c["engine"],c["dtype"]) for c in calls} == {("qwen-1.7b","float32")}
    assert all(c["reference"] == str(ref) for c in calls)
    assert s.digest(saved) == digest and audio_valid(request["output"])
    assert 0 < progress[0] < progress[1] < 85 and progress[1] > 40
    assert s.get("job",job["id"])["progress"] == 85
    with wave.open(request["output"]) as out:
        assert out.getnframes() == 4800


def test_model_load_failure_does_not_split_text(data, monkeypatch):
    import app.worker as module
    ref = data/"media"/"ref.wav"; recording(ref)
    job = s.put("job", {"status":"running", "stage":"Preparando", "snapshot":{"engine":"qwen-1.7b", "dtype":"float32"}})
    folder=data/"jobs"/job["id"]; folder.mkdir()
    def fail(*_): raise MemoryUnavailable(9.5, 5)
    monkeypatch.setattr(module, "EngineSession", fail)
    req={"engine":"qwen-1.7b", "text":"Uma frase inteira. "*80, "reference":str(ref), "output":str(folder/"raw-000000.wav")}
    with pytest.raises(MemoryUnavailable): Worker().synthesize(job["id"], req, folder)
    assert not list(folder.glob("*.parts.json"))


def test_reduction_keeps_words_and_multiple_sentences():
    text="Dr. Silva pagou 3.14 reais. São 12:30 agora! Mais uma frase. "*8
    parts=list(split_text(text, maximum=150))
    assert "".join(parts) == text
    assert all(len(part)>60 for part in parts[:-1])
    assert all(not part.startswith("14") for part in parts)
    assert list(split_text("palavra"*100, maximum=80)) == ["palavra"*100]


@pytest.mark.parametrize("length,eos,allowed", [(5,True,True),(5,False,False),(4,False,True)])
def test_chatterbox_does_not_accept_capped_speech_as_complete(length,eos,allowed):
    result=np.ones((1,length),dtype=int); result[0,-1]=9 if eos else 1
    original=lambda **_:result
    t3=SimpleNamespace(hp=SimpleNamespace(input_pos_emb="learned",max_text_tokens=10,stop_speech_token=9),inference=original)
    model=SimpleNamespace(t3=t3)
    with chatterbox_capacity(model):
        if allowed:
            assert t3.inference(text_tokens=np.zeros((2,12)),max_new_tokens=5) is result
        else:
            with pytest.raises(TextCapacityExceeded): t3.inference(text_tokens=np.zeros((2,12)),max_new_tokens=5)
    assert t3.inference is original
    with chatterbox_capacity(model), pytest.raises(TextCapacityExceeded):
        t3.inference(text_tokens=np.zeros((2,13)),max_new_tokens=5)
    assert t3.inference is original


@pytest.mark.parametrize("length,eos,allowed", [(5,True,True),(5,False,False),(4,False,True)])
def test_qwen_keeps_sampling_and_rejects_only_a_capped_unfinished_sequence(length,eos,allowed):
    sequence=np.ones((1,length),dtype=int); sequence[0,-1]=9 if eos else 1
    result=SimpleNamespace(sequences=sequence)
    options=[]
    def original(**kwargs): options.append(kwargs); return result
    talker=SimpleNamespace(generate=original)
    with qwen_capacity(talker):
        if allowed:
            assert talker.generate(max_new_tokens=5,eos_token_id=9,temperature=0.8) is result
        else:
            with pytest.raises(TextCapacityExceeded): talker.generate(max_new_tokens=5,eos_token_id=9,temperature=0.8)
    assert talker.generate is original
    assert options == [{"max_new_tokens":5,"eos_token_id":9,"temperature":0.8}]


def test_text_capacity_uses_its_own_engine_protocol(capsys):
    import queue
    from app.engine_runner import error_reply
    from app.engine_session import EngineSession
    error_reply(TextCapacityExceeded("Capacity"), {"engine":"qwen-1.7b"})
    line=capsys.readouterr().out
    assert json.loads(line)["kind"]=="text_capacity"
    session=EngineSession.__new__(EngineSession)
    session.worker=SimpleNamespace(check=lambda _:None); session.ident="test"
    session.responses=queue.Queue(); session.responses.put(line)
    with pytest.raises(TextCapacityExceeded): session.wait()


def test_native_voxcpm_limit_preserves_stop_predictor_and_flags_only_exhaustion(tmp_path):
    import shutil
    import subprocess
    from scripts.configure_voxcpm import configure_decode_limit
    compiler=shutil.which("g++")
    if not compiler: pytest.skip("Native C++ compiler is provided by CI")
    # Minimal decoder substitute exercises the actual source transformation.
    original='''void VoxCPM2Runtime::decode_loop(const Params & params) {
    for (int i = 0; i < params.max_steps; ++i) {
        auto step = decode_step();
        if (step.latent_patch.empty()) {
            break;
        }
        if (params.stop_on_predictor && i > params.min_steps && step.should_stop) {
            break;
        }
    }
}

std::vector<float> VoxCPM2Runtime::decode_pool_range_to_waveform() { return {}; }
'''
    configured=configure_decode_limit(original)
    assert configure_decode_limit(configured)==configured
    prefix='''#include <vector>
#include <string>
#include <cassert>
struct Params { int max_steps=5, min_steps=0; bool stop_on_predictor=true; };
struct Step { std::vector<float> latent_patch; bool should_stop; };
class VoxCPM2Runtime { public:
int count=0, stop=3, empty=-1; std::string error;
Step decode_step() { ++count; return { count==empty ? std::vector<float>{} : std::vector<float>{1}, count==stop }; }
void fail(const char * text) { error=text; }
void decode_loop(const Params &); std::vector<float> decode_pool_range_to_waveform();
};
'''
    checks='''int main() {
Params p; VoxCPM2Runtime normal; normal.decode_loop(p); assert(normal.count==3 && normal.error.empty());
VoxCPM2Runtime capped; capped.stop=6; capped.decode_loop(p); assert(capped.count==5 && capped.error.find("SAL0_TEXT_CAPACITY")!=std::string::npos);
VoxCPM2Runtime empty; empty.empty=2; empty.decode_loop(p); assert(empty.count==2 && empty.error.empty());
p.stop_on_predictor=false; VoxCPM2Runtime explicit_limit; explicit_limit.decode_loop(p); assert(explicit_limit.count==5 && explicit_limit.error.empty());
}'''
    source=tmp_path/"capacity.cpp"; source.write_text(prefix+configured+checks)
    binary=tmp_path/"capacity"
    built=subprocess.run([compiler,"-std=c++17",str(source),"-o",str(binary)],capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    assert subprocess.run([str(binary)],capture_output=True).returncode==0


@pytest.mark.parametrize("capacity",[True,False])
def test_voxcpm_capacity_signal_does_not_reuse_a_previous_log_error(data,monkeypatch,capacity):
    import sys
    import app.voxcpm_engine as module
    binary=data/"native-substitute"
    message="SAL0_TEXT_CAPACITY: output cap" if capacity else "Different native failure"
    binary.write_text("#!"+sys.executable+"\nimport sys\nprint("+repr(message)+",file=sys.stderr)\nraise SystemExit(1)\n")
    binary.chmod(0o755)
    monkeypatch.setattr(module,"runtime_binary",lambda _:binary)
    monkeypatch.setattr(module,"memory_available",lambda:10*1024**3)
    model=data/"fake-files";model.mkdir()
    for name in ("VoxCPM2-BaseLM-F16.gguf","VoxCPM2-Acoustic-F16.gguf"):
        (model/name).write_bytes(b"substitute, never loaded")
    folder=data/"jobs"/"test";folder.mkdir()
    (folder/"voxcpm-process.log").write_text("SAL0_TEXT_CAPACITY: previous attempt\n")
    req={"model_path":str(model),"text":"Texto", "voice_style":"happy", "reference":"unused.wav", "output":str(folder/"raw.wav")}
    engine=module.VoxCPMEngine(req)
    with pytest.raises(TextCapacityExceeded if capacity else RuntimeError): engine.generate(req)
    assert not (folder/"raw.json").exists()


def test_large_native_argument_is_a_text_capacity_error(data,monkeypatch):
    import errno
    import app.voxcpm_engine as module
    binary=data/"unused-cli"; binary.write_text("unused"); binary.chmod(0o755)
    monkeypatch.setattr(module,"runtime_binary",lambda _:binary)
    monkeypatch.setattr(module,"memory_available",lambda:10*1024**3)
    for name in ("VoxCPM2-BaseLM-F16.gguf","VoxCPM2-Acoustic-F16.gguf"):
        (data/name).write_bytes(b"substitute, never loaded")
    def fail(*args,**kwargs): raise OSError(errno.E2BIG,"Argument list too long")
    monkeypatch.setattr(module.subprocess,"run",fail)
    req={"model_path":str(data),"text":"Texto "*30000,"voice_style":"happy","reference":"unused.wav","output":str(data/"raw.wav")}
    engine=module.VoxCPMEngine(req)
    with pytest.raises(TextCapacityExceeded): engine.generate(req)
