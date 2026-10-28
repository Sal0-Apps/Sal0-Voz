"""Memory/recovery regressions with media tools and substitutes, never neural models."""
import contextlib
import dataclasses
import json
import queue
import subprocess
import sys
import wave
import weakref
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from app import storage as s
from app.asr_memory import DiskFeatures
from app.audio_files import audio_valid, checkpoint_audio
from app.engine_policy import MemoryUnavailable
from app.engine_session import EngineSession
from app.prompt_cache import PromptCache
from app.resources import ProcessInterrupted
from app.worker import Worker
from vendor.whisper_feature_v111 import FeatureExtractor


@pytest.mark.parametrize("length,padding", [(1301, 0), (1301, 160), (48123, 160), (48000, 0), (96017, 160)])
def test_disk_features_match_pinned_whisper_math_and_bound_fft(length, padding, tmp_path, monkeypatch):
    audio = np.random.default_rng(23).standard_normal(length).astype("float32") * 1e-5
    audio[:min(length, 300)] *= 1e5  # Global dynamic range must span quiet blocks.
    original = FeatureExtractor(feature_size=128)
    expected = original(audio, padding=padding)
    extractor = DiskFeatures(original, tmp_path, block_frames=7)
    observed = []
    stft = original.stft
    def bounded(samples, *args, **kwargs):
        observed.append(samples.size)
        return stft(samples, *args, **kwargs)
    monkeypatch.setattr(original, "stft", bounded)
    try:
        actual = extractor(audio, padding=padding)
        assert isinstance(actual, np.memmap) and actual.shape == expected.shape
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-6)
        assert max(observed) <= 6*original.hop_length+original.n_fft
    finally:
        extractor.close()
    assert actual._mmap.closed


def test_short_features_keep_original_path_and_chunk_options(tmp_path):
    original = FeatureExtractor(feature_size=128)
    extractor = DiskFeatures(original, tmp_path)
    audio = np.zeros(1023, dtype="float32")
    np.testing.assert_array_equal(extractor(audio, chunk_length=17), original(audio, chunk_length=17))
    assert extractor.n_samples == 17*16000 and not extractor.maps


class Tensor:
    def __init__(self, values, dtype):
        self.values, self.dtype = tuple(values), dtype
    def detach(self):
        return self
    def clone(self):
        return Tensor(self.values, self.dtype)


@dataclasses.dataclass
class Prompt:
    ref_code: Tensor
    ref_spk_embedding: Tensor
    x_vector_only_mode: bool
    icl_mode: bool
    ref_text: str


class TensorArchive:
    """Tiny codec substitute; verify CPU/weights-only loading without importing torch."""
    @staticmethod
    def save(records, path):
        def convert(value):
            return {"values": value.values, "dtype": value.dtype} if isinstance(value, Tensor) else value
        Path(path).write_text(json.dumps([{key:convert(value) for key,value in item.items()} for item in records]))
    @staticmethod
    def load(path, **options):
        assert options == {"map_location":"cpu", "weights_only":True}
        return [{key:Tensor(value["values"], value["dtype"]) if isinstance(value, dict) else value
                 for key,value in item.items()} for item in json.loads(Path(path).read_text())]


def test_only_current_voice_is_retained_and_full_prompt_reloads_from_disk(tmp_path):
    cache = PromptCache(tmp_path, "qwen-1.7b", "bfloat16", "fixed")
    built = []
    def build(text):
        built.append(text)
        return [Prompt(Tensor([1,2,3],"int64"), Tensor([.1,.2],"bfloat16"), False, True, text)]
    first = cache.get("A.wav", "Texto A", lambda:build("Texto A"), Prompt, TensorArchive)
    old = weakref.ref(first[0])
    assert cache.get("A.wav", "Texto A", lambda:pytest.fail("Already resident"), Prompt, TensorArchive) is first
    del first
    cache.get("B.wav", "Texto B", lambda:build("Texto B"), Prompt, TensorArchive)
    assert old() is None
    restored = cache.get("A.wav", "Texto A", lambda:pytest.fail("Use disk prompt"), Prompt, TensorArchive)[0]
    assert built == ["Texto A", "Texto B"]
    assert restored.ref_text == "Texto A" and restored.icl_mode and not restored.x_vector_only_mode
    assert restored.ref_code.values == (1,2,3) and restored.ref_spk_embedding.dtype == "bfloat16"
    assert len(list(tmp_path.glob("*.pt"))) == 2


def test_prompt_revision_and_corruption_do_not_reuse_stale_data(tmp_path):
    builds = []
    def build():
        builds.append(1)
        return [Prompt(Tensor([3],"int64"), Tensor([.2],"float32"),False,True,"Texto")]
    PromptCache(tmp_path,"qwen-1.7b","float32","old").get("A.wav","Texto",build,Prompt,TensorArchive)
    path = next(tmp_path.glob("*.pt")); path.write_text("corrupt")
    PromptCache(tmp_path,"qwen-1.7b","float32","old").get("A.wav","Texto",build,Prompt,TensorArchive)
    PromptCache(tmp_path,"qwen-1.7b","float32","new").get("A.wav","Texto",build,Prompt,TensorArchive)
    assert len(builds) == 3


def recording(path, value=1500, seconds=1):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(np.full(24000*seconds,value,dtype="<i2").tobytes())


def speech_job(data):
    ref = data/"media"/"ref.wav"; recording(ref, seconds=6)
    character = {"number":1,"name":"Voz","language":"pt-BR","reference":{"path":"media/ref.wav"},"reference_text":"Minha referência."}
    project = {"mode":"tts","engine":"qwen-1.7b","language":"pt-BR","name":"Cena","format":"wav",
               "segments":[{"text":text,"language":"pt-BR","rate":1,"volume":0,"character":dict(character)} for text in ("Primeira.","Segunda.")]}
    return s.put("job",{"status":"queued","stage":"Fila","name":"Cena","snapshot":project,"progress":0})


@pytest.mark.parametrize("failure", ["memory", "lost_reply"])
def test_automatic_resume_reloads_model_and_keeps_saved_audio(data, monkeypatch, failure):
    import app.worker as module
    import app.engine_policy as policy
    job = speech_job(data); worker = Worker(); clock = [1000]
    monkeypatch.setattr(module,"time",SimpleNamespace(time=lambda:clock[0],monotonic=lambda:clock[0]))
    monkeypatch.setattr(worker.wake,"wait",lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    monkeypatch.setattr(module,"require",lambda *args:{"revision":"fixed"})
    monkeypatch.setattr(policy,"memory_available",lambda:10*1024**3)
    monkeypatch.setattr(policy,"cgroup_memory",lambda:(10*1024**3,0))
    sessions, calls, profiles, saved_hash = [], [], [], []
    failed = [False]
    class Session:
        def __init__(self,*args):
            assert all(x.closed for x in sessions)
            self.closed=False; sessions.append(self)
        def generate(self, request):
            calls.append(request["text"]); profiles.append((request["engine"],request["dtype"]))
            if failure=="memory" and request["text"]=="Segunda." and not failed[0]:
                failed[0]=True
                raise MemoryUnavailable(6,5)
            recording(Path(request["output"]), 1500 if request["text"]=="Primeira." else 2300)
            checkpoint_audio(request["output"])
            if request["text"]=="Primeira.":
                saved_hash.append(s.digest(request["output"]))
                if failure=="lost_reply" and not failed[0]:
                    failed[0]=True
                    raise ProcessInterrupted("Reply lost after saving complete audio")
        def close(self):
            self.closed=True
    monkeypatch.setattr(module,"EngineSession",Session)
    monkeypatch.setattr(module,"notify_job",lambda _:worker.stop_event.set())
    worker.loop()
    result=s.get("job",job["id"]); folder=data/"jobs"/job["id"]
    assert result["status"]=="completed" and result["automatic_retries"]==1
    assert len(sessions)==2 and all(x.closed for x in sessions)
    assert calls == (["Primeira.","Segunda.","Segunda."] if failure=="memory" else ["Primeira.","Segunda."])
    assert set(profiles)=={("qwen-1.7b","bfloat16")}
    assert saved_hash==[s.digest(folder/"raw-000000.wav")]
    assert audio_valid(folder/"raw-000000.wav") and audio_valid(folder/"segment-000001.wav")
    assert not result["snapshot"].get("memory_failed_profiles")


def test_retry_backoff_resets_on_progress_and_respects_manual_stop(data):
    job=speech_job(data); worker=Worker(); ident=job["id"]
    folder=data/"jobs"/ident; folder.mkdir()
    for delay in (5,10,20):
        worker.update(ident,status="running")
        worker.retry(ident,ProcessInterrupted("Stopped"))
        assert f"em {delay}s" in s.get("job",ident)["stage"]
    recording(folder/"raw-000000.wav"); checkpoint_audio(folder/"raw-000000.wav")
    worker.update(ident,status="running"); worker.retry(ident,ProcessInterrupted("Stopped"))
    assert "em 5s" in s.get("job",ident)["stage"]
    assert Worker.speech_started(job["snapshot"],folder)
    for status in ("paused","cancelled"):
        worker.update(ident,status=status)
        worker.retry(ident,MemoryUnavailable(6,5))
        assert s.get("job",ident)["status"]==status


def test_sigkill_is_recoverable_without_cgroup_oom_counter(data, monkeypatch):
    import app.engine_session as module
    job=speech_job(data); worker=Worker(); worker.update(job["id"],status="running")
    monkeypatch.setattr(module,"oom_kills",lambda:0)
    session=EngineSession.__new__(EngineSession)
    session.worker=worker; session.ident=job["id"]; session.profile=("qwen-1.7b","bfloat16"); session.oom_before=0
    session.responses=queue.Queue(); session.responses.put(None)
    session.process=subprocess.Popen([sys.executable,"-c","import os,signal;os.kill(os.getpid(),signal.SIGKILL)"])
    with pytest.raises(MemoryUnavailable):
        session.wait()
    assert session.process.returncode==-9


def test_start_recovers_legacy_memory_stops_and_preserves_user_pause(data, monkeypatch):
    cases=[("failed","O modelo de voz foi interrompido.","queued"),
           ("paused","Pouca memória disponível","queued"),
           ("paused","Pausado","paused"),
           ("cancelled","Cancelado","cancelled"),
           ("failed","A gravação não contém fala.","failed")]
    ids=[s.put("job",{"status":status,"stage":stage,"snapshot":{}})["id"] for status,stage,_ in cases]
    worker=Worker(); monkeypatch.setattr(worker,"loop",lambda:None)
    worker.start(); worker.stop()
    assert [s.get("job",ident)["status"] for ident in ids]==[expected for _,_,expected in cases]


def test_catalog_polling_pages_before_decoding_and_omits_snapshots(data, monkeypatch):
    for index in range(15):
        s.put("job",{"status":"completed","name":str(index),"owner_username":"maria" if index%2 else "admin","snapshot":{"text":"x"*50000}})
    sizes=[]; loads=s.json.loads
    def bounded(body,*args,**kwargs):
        sizes.append(len(body)); return loads(body,*args,**kwargs)
    monkeypatch.setattr(s.json,"loads",bounded)
    records=s.catalog_page("job",{"username":"maria","role":"user"},offset=1,limit=3)
    assert len(records)==3 and all(x["owner_username"]=="maria" and "snapshot" not in x for x in records)
    assert len(sizes)==3 and max(sizes)<500
    assert len(s.job_ids("completed"))==15
    assert s.job_state(records[0]["id"])["status"]=="completed"


def test_telegram_sends_only_small_json_message_without_attachments(monkeypatch):
    import app.telegram as module
    seen = []
    def urlopen(request, **options):
        seen.append(request)
        assert request.full_url.endswith('/sendMessage')
        assert isinstance(request.data, bytes)
        assert request.get_header('Content-type') == 'application/json'
        assert options['timeout'] == 30
        return contextlib.nullcontext(SimpleNamespace(status=200))
    monkeypatch.setattr(module.urllib.request, 'urlopen', urlopen)
    assert module.send_message({'telegram_token':'dummy', 'telegram_chat_id':'local'}, 'Um link')
    assert json.loads(seen[0].data)['link_preview_options'] == {'is_disabled':True}
    assert not hasattr(module, 'send_document')


@pytest.mark.parametrize("interrupted",[False,True])
def test_whisper_workspace_is_removed_before_clone_even_on_failure(data,monkeypatch,interrupted):
    import app.worker as module
    job=speech_job(data); worker=Worker(); worker.update(job["id"],status="running")
    folder=data/"jobs"/job["id"]; folder.mkdir()
    def run(ident,args,progress_file=None):
        request=json.loads((folder/"request.json").read_text())
        assert progress_file == folder/"engine-progress.json" and request["progress_file"] == str(progress_file)
        progress_file.write_text('{"phase":"transcribing","completed":1,"total":2}')
        work=Path(request["work_dir"]); work.mkdir(); (work/"pcm.f32").write_bytes(b"temporary")
        if interrupted:raise ProcessInterrupted("ASR stopped")
        Path(request["output"]).write_text("[]")
    monkeypatch.setattr(worker,"run",run)
    request={"engine":"whisper-large-v3-turbo","language":"pt-BR","source":"source.wav","output":str(folder/"cues.json")}
    if interrupted:
        with pytest.raises(ProcessInterrupted):worker.engine(job["id"],request,folder)
    else:
        worker.engine(job["id"],request,folder)
    assert not (folder/"asr-work").exists() and worker.processing_engine is None
    assert not (folder/"engine-progress.json").exists()
    class Session:
        def __init__(self,*args):assert not (folder/"asr-work").exists()
        def generate(self,request):pass
        def close(self):pass
    monkeypatch.setattr(module,"EngineSession",Session)
    worker.engine(job["id"],{"engine":"qwen-1.7b","output":str(folder/"raw.wav")},folder)
    worker.close_clone()


def test_exited_parent_does_not_leave_a_child_using_resources(data):
    import os, time
    if os.name != "posix":pytest.skip("Process groups are POSIX")
    job=speech_job(data); worker=Worker(); worker.update(job["id"],status="running")
    folder=data/"jobs"/job["id"]; folder.mkdir(); heartbeat=folder/"child-heartbeat"
    # Observe actual descendant activity, without relying on host /proc PID aliases.
    child_code="import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nfor i in range(1000):\n p.write_text(str(i));time.sleep(.01)"
    code="import subprocess,sys,pathlib,time; child=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]])\nwhile not pathlib.Path(sys.argv[1]).exists():time.sleep(.005)\nsys.exit(1)"
    with pytest.raises(ValueError):
        worker.run(job["id"],[sys.executable,"-c",code,str(heartbeat),child_code])
    previous=heartbeat.read_text()
    time.sleep(.2)
    assert heartbeat.read_text()==previous, "Child kept working after its parent exited"


@pytest.mark.parametrize("message", ["raise MemoryError('allocation failed')", "raise RuntimeError('Unable to allocate 512 MiB')"])
def test_memory_failure_in_a_one_shot_process_is_recoverable(data,message):
    job=speech_job(data); worker=Worker(); worker.update(job["id"],status="running")
    (data/"jobs"/job["id"]).mkdir()
    with pytest.raises(MemoryUnavailable):
        worker.run(job["id"],[sys.executable,"-c",message])


def test_generation_runtime_failure_requests_resume_but_bad_input_does_not(monkeypatch):
    from app import engine_runner as module
    replies=[]; monkeypatch.setattr(module,"reply",replies.append)
    request={"engine":"qwen-1.7b","dtype":"bfloat16"}
    module.error_reply(RuntimeError("Inference interrupted"),request,retryable=True)
    module.error_reply(ValueError("Invalid reference"),request,retryable=True)
    module.error_reply(RuntimeError("Invalid model environment"),request)
    assert replies[0]["kind"]=="interrupted"
    assert "kind" not in replies[1] and "kind" not in replies[2]


def test_old_memory_log_does_not_hide_a_new_input_failure(data):
    job=speech_job(data); worker=Worker(); worker.update(job["id"],status="running")
    (data/"jobs"/job["id"]).mkdir()
    with pytest.raises(MemoryUnavailable):
        worker.run(job["id"],[sys.executable,"-c","raise MemoryError('previous attempt')"])
    with pytest.raises(ValueError,match="invalid-current-input"):
        worker.run(job["id"],[sys.executable,"-c","raise RuntimeError('invalid-current-input')"])
