"""Local download, fidelity profiles, native IPC, and recovery; no neural weights."""
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import wave

import numpy as np
import pytest
import soundfile as sf
import yaml

from app import storage as s
from app.audio_files import audio_valid, checkpoint_audio
from app.audio_precision import pcm24
from app.catalog import CATALOG, models_needed, DEFAULT_MODELS
from app.engine_policy import MemoryUnavailable, choose_profile
from app.engine_progress import progress_to
from app.quality_profiles import POCKET_PROFILE, DRAMA_PROFILE
from app.resources import TextCapacityExceeded


def recording(path, rate=24000, seconds=4):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(3); out.setframerate(rate)
        out.writeframes(b"\x01\x01\x00"*rate*seconds)
    checkpoint_audio(path)


def test_gated_access_is_private_admin_only_and_optional(owner, data):
    token = "hf_example_only_not_a_real_token_123456"
    assert owner.post("/api/models/pocket-pt/download", json={"accept_license":True}).status_code == 400
    saved = owner.put("/api/model-access", json={"token":token})
    assert saved.status_code == 200 and saved.json()["configured"]
    for response in [saved, owner.get("/api/model-access"), owner.get("/api/models"),
                     owner.put("/api/model-access", json={"token":token*100})]:
        assert token not in response.text
    assert owner.post("/api/models/pocket-pt/download", json={"accept_license":True}).status_code == 200
    assert owner.post("/api/models/drama3/download", json={"accept_license":True}).status_code == 200
    assert owner.post("/api/models/drama3-original/download", json={"accept_license":True}).status_code == 200
    assert not {"pocket-pt", "drama3", "drama3-original"} & set(DEFAULT_MODELS)
    owner.post("/api/users", json={"username":"reader", "password":"test-password-123", "role":"user"})
    owner.post("/api/auth/logout")
    assert owner.post("/api/auth/login", json={"username":"reader", "password":"test-password-123"}).status_code == 200
    assert owner.get("/api/model-access").json()["writable"] is False
    assert owner.put("/api/model-access", json={"clear":True}).status_code == 403
    assert s.setting("huggingface_token") == token


@pytest.mark.parametrize("engine,profile,rate", [("pocket-pt",POCKET_PROFILE,24000), ("drama3",DRAMA_PROFILE,44100)])
def test_jobs_freeze_quality_and_keep_voice_on_resume(owner, data, engine, profile, rate):
    from app.model_access import save
    save({"role":"admin"}, "hf_example_read_access_123456789")
    ref = data/"media/ref.wav"; recording(ref)
    media = s.put("media", {"path":"media/ref.wav", "audio":True, "owner_username":"admin"})
    voice = owner.post("/api/characters", json={"name":"Minha voz", "reference_id":media["id"], "reference_text":""}).json()
    project = owner.post("/api/projects", json={"name":"Teste", "engine":engine, "character_id":voice["id"], "text":"Minha fala inteira. "*80}).json()
    ident = owner.post("/api/projects/"+project["id"]+"/generate").json()["id"]
    job = s.get("job",ident); snap=job["snapshot"]
    assert snap["quality_profile"] == profile and snap["output_sample_width"] == 3 and snap["output_sample_rate"] == rate
    assert len(snap["segments"]) == 1 and snap["segments"][0]["text"] == project["text"]
    assert models_needed(snap) == ([engine] if engine=="pocket-pt" else [engine,"whisper-large-v3-turbo"])
    from app.worker import Worker
    worker = Worker(); worker.update(ident, status="paused", stage="Pausado")
    assert owner.post("/api/jobs/"+ident+"/resume").status_code == 200
    assert s.get("job",ident)["snapshot"] == snap
    selected = choose_profile(snap, available=9*1024**3, memory_limit=10*1024**3)
    assert selected["engine"] == engine and not selected["adapted"]
    with pytest.raises(MemoryUnavailable): choose_profile(snap, available=2*1024**3, locked=True)


def test_original_drama_weights_are_download_only(owner):
    assert CATALOG["drama3-original"]["kind"] == "weights" and CATALOG["drama3-original"]["download_only"]
    project = owner.post("/api/projects", json={"name":"Original", "engine":"drama3-original", "text":"Olá"}).json()
    assert owner.post("/api/projects/"+project["id"]+"/generate").status_code == 400


def test_retry_cleans_unconfirmed_model_work_without_removing_checkpoints(data,monkeypatch):
    from app.worker import Worker
    job=s.put("job",{"status":"running","snapshot":{"engine":"drama3"}})
    folder=data/"jobs"/job["id"];folder.mkdir()
    saved=folder/"raw-000000.wav";recording(saved)
    digest=s.digest(saved)
    (folder/"raw-000001.floating.wav").write_bytes(b"unfinished")
    work=folder/"drama3-work-interrupted";work.mkdir();(work/"partial.wav").write_bytes(b"unfinished")
    (folder/"drama3-process.log").write_text("diagnostic")
    worker=Worker();monkeypatch.setattr(worker,"_execute",lambda _:None)
    worker.execute(job)
    assert s.digest(saved)==digest and audio_valid(saved)
    assert not work.exists() and not list(folder.glob("*.floating.wav"))
    assert (folder/"drama3-process.log").is_file()


def test_float_pipeline_preserves_sub_16bit_audio_and_rejects_nan(tmp_path):
    source, output = tmp_path/"float.wav", tmp_path/"raw.wav"
    values = np.asarray([1,257,-129,32767,1,0,-1,1025], dtype=np.float32)/8388608
    sf.write(source, values, 44100, subtype="FLOAT")
    pcm24(source, output, 44100)
    with wave.open(str(output)) as audio:
        assert audio.getsampwidth() == 3 and audio.getframerate() == 44100
        raw = audio.readframes(audio.getnframes())
    expected = (np.asarray([1,257,-129,32767,1,0,-1,1025],dtype="<i4").view(np.uint8).reshape(-1,4)[:,:3]).tobytes()
    assert raw == expected
    sf.write(source, [1.5,-1.25], 44100, subtype="FLOAT")
    pcm24(source, output, 44100)
    assert abs(sf.read(output)[0]).max() <= 0.999001
    sf.write(source, [0,np.nan], 44100, subtype="FLOAT")
    rejected = tmp_path/"invalid.wav"
    with pytest.raises(ValueError,match="inválidas"): pcm24(source,rejected,44100)
    assert not rejected.exists()


@pytest.mark.parametrize("engine,rate", [("pocket-pt",24000),("drama3",44100)])
@pytest.mark.parametrize("extension",["wav","flac","mp3"])
def test_export_keeps_native_rate_real_24bit_and_saved_takes(data,monkeypatch,engine,rate,extension):
    from app.worker import Worker
    from app.quality_profiles import PROFILES
    ref=data/"media/reference.wav";recording(ref,rate)
    character={"reference":{"path":"media/reference.wav"},"reference_text":"Minha referência exata."}
    project={"engine":engine,"mode":"tts","dtype":CATALOG[engine].get("dtype","float32"),
        "quality_profile":PROFILES[engine],"model_seed":7,"output_sample_width":3,"output_sample_rate":rate,
        "name":"Nativo","language":"pt-BR","format":extension,
        "segments":[{"text":"A fala inteira.","character":character,"language":"pt-BR","rate":1,"volume":0},
                    {"pause_ms":100,"text":""}]}
    job=s.put("job",{"status":"running","snapshot":project});calls=[]
    def generate(ident,request,folder):
        calls.append(request.copy())
        assert request["quality_profile"]==PROFILES[engine] and request["model_seed"]==7
        with wave.open(request["reference"]) as audio:assert audio.getsampwidth()==3 and audio.getframerate()==rate
        recording(request["output"],rate,seconds=1)
    worker=Worker();monkeypatch.setattr(worker,"engine",generate)
    worker.execute(job)
    exported=data/"exports"/(job["id"]+"."+extension)
    assert exported.is_file()
    if extension in ("wav","flac"):
        decoded,samplerate=sf.read(exported,dtype="int32")
        assert samplerate==rate and len(decoded)==rate+rate//10
        np.testing.assert_array_equal(decoded[:rate],np.full(rate,257*256,dtype=np.int32))
        assert not decoded[rate:].any()
    else:
        metadata=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_streams","-of","json",str(exported)]))["streams"][0]
        assert metadata["sample_rate"]==str(rate) and metadata["bit_rate"]==("320000" if rate==44100 else "160000")
    worker.execute(s.get("job",job["id"]))
    assert len(calls)==1


def pocket_substitute(data, monkeypatch):
    import app.pocket_engine as module
    state = [None]; seeds=[]; builds=[]; calls=[]
    @contextmanager
    def fork_rng(devices):
        old=state[0]
        try: yield
        finally: state[0]=old
    def seed(value): state[0]=value; seeds.append(value)
    class Tensor:
        def __init__(self, values): self.values=values
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return self.values
    class Model:
        has_voice_cloning=True
        capped=False
        @classmethod
        def load_model(cls, **options):
            config=yaml.safe_load(Path(options["config"]).read_text())
            assert config["flow_lm"]["transformer"]["num_layers"]==24
            assert config["flow_lm"]["dtype"]==config["mimi"]["dtype"]=="float32"
            assert "weights_path_without_voice_cloning" not in config
            assert Path(config["weights_path"]).is_file() and Path(config["flow_lm"]["lookup_table"]["tokenizer_path"]).is_file()
            assert options["quantize"] is False and options["sampler_decode_steps"]==5
            return cls()
        def eval(self): return self
        def get_state_for_audio_prompt(self, reference, truncate):
            assert truncate is False; builds.append(str(reference)); return {"speaker":"chosen"}
        def generate_audio_stream(self, voice, text, **options):
            assert voice=={"speaker":"chosen"} and options=={"max_tokens":1_000_000_000,"copy_state":True}
            calls.append(text)
            yield Tensor(np.random.default_rng(state[0]).uniform(-.2,.2,24000).astype(np.float32))
            if self.capped: raise RuntimeError("Generation reached maximum length without EOS!")
    torch=SimpleNamespace(backends=SimpleNamespace(nnpack=SimpleNamespace(set_flags=lambda _:None)),set_num_threads=lambda _:None,
                          set_num_interop_threads=lambda _:None, inference_mode=nullcontext, random=SimpleNamespace(fork_rng=fork_rng), manual_seed=seed)
    monkeypatch.setitem(sys.modules,"torch",torch)
    monkeypatch.setitem(sys.modules,"pocket_tts",SimpleNamespace(TTSModel=Model))
    package=data/"package"; (package/"config").mkdir(parents=True)
    config={"weights_path":"hf://gated", "weights_path_without_voice_cloning":"hf://wrong", "flow_lm":{"dtype":"float32","transformer":{"num_layers":24},"lookup_table":{}},"mimi":{"dtype":"float32"}}
    (package/"config/portuguese_24l.yaml").write_text(yaml.safe_dump(config))
    monkeypatch.setattr(module,"files",lambda _:package)
    monkeypatch.setattr(module,"memory_available",lambda:10*1024**3)
    monkeypatch.setenv("KPOCKET_TTS_ERROR_WITHOUT_EOS","1")
    root=data/"models/pocket-pt"; (root/"languages/portuguese_24l").mkdir(parents=True)
    for name in ("model.safetensors","tokenizer.json"): (root/"languages/portuguese_24l"/name).write_bytes(b"substitute")
    reference=data/"media/ref.wav"; recording(reference)
    request={"engine":"pocket-pt","dtype":"float32","quality_profile":POCKET_PROFILE,"model_seed":321,
             "model_path":str(root),"output":str(data/"jobs/raw.wav"),"reference":str(reference),"text":"Uma fala inteira. "*60,"language":"pt-BR","checkpoint":True}
    return module,request,builds,calls,seeds


def test_pocket_uses_full_local_clone_preserves_seed_and_rejects_capped_take(data,monkeypatch):
    module,request,builds,calls,seeds=pocket_substitute(data,monkeypatch)
    engine=module.PocketEngine(request); events=[]
    assert engine.model.max_decoder_frames_per_call==1
    with progress_to(events.append): engine.generate(request)
    first=s.digest(request["output"]); engine.generate(request)
    assert len(builds)==1 and calls==[request["text"],request["text"]] and seeds[0]==seeds[1]
    assert s.digest(request["output"])==first and audio_valid(request["output"])
    assert any(e.get("generated_seconds",0)>0 for e in events)
    with wave.open(request["output"]) as audio: assert audio.getsampwidth()==3
    engine.model.capped=True
    capped={**request,"output":str(data/"jobs/capped.wav")}
    with pytest.raises(TextCapacityExceeded):engine.generate(capped)
    assert not audio_valid(capped["output"]) and not list((data/"jobs").glob("*.floating.wav"))
    with pytest.raises(ValueError,match="Português"):engine.generate({**request,"language":"en-US"})


@pytest.mark.parametrize("outcome",["ok","limit","context","missing","oom-load","oom-generate"])
def test_drama_native_protocol_disk_cache_reference_and_no_truncated_checkpoint(data,monkeypatch,outcome):
    import app.drama3_engine as module
    binary=data/"audiocpp_cli"
    binary.write_text("#!"+sys.executable+"\n"+'''import sys,json,pathlib,soundfile as sf,numpy as np
args=sys.argv[1:]; get=lambda key:args[args.index(key)+1]
request=json.loads(pathlib.Path(get('--request-sequence')).read_text())[0]
pathlib.Path(sys.argv[0]+'.seen.json').write_text(json.dumps({'args':args,'request':request}))
if request['text']=='context':print('Drama 3 prompt plus max_tokens exceeds fish_drama3.context_length');sys.exit(1)
if request['text']=='oom-load':print('std::bad_alloc');sys.exit(1)
print('SAL0_DRAMA_FRAME=32',flush=True)
if request['text']=='oom-generate':print('std::bad_alloc');sys.exit(1)
sf.write(get('--out'),np.tile(np.asarray([1,257,-129],dtype=np.float32)/8388608,14700),44100,subtype='FLOAT')
if request['text']!='missing':pathlib.Path(get('--batch-manifest-out')).write_text(json.dumps({'requests':[{'custom_schema_output':{'schema':'drama3_generation_v1','data':{'frames':32,'reached_limit':request['text']=='limit'}}}]}))
''')
    binary.chmod(0o755)
    monkeypatch.setattr(module,"runtime_binary",lambda _:binary)
    monkeypatch.setattr(module,"memory_available",lambda:10*1024**3)
    root=data/"models/drama3";root.mkdir()
    (root/CATALOG["drama3"]["files"][-1]).write_bytes(b"substitute")
    ref=data/"media/reference.wav";recording(ref,44100)
    request={"engine":"drama3","dtype":"q4-bf16","quality_profile":DRAMA_PROFILE,"model_seed":321,
        "model_path":str(root),"reference":str(ref),"reference_text":"Minha referência literal.","text":outcome,
        "language":"pt-BR","output":str(data/"jobs/raw.wav"),"checkpoint":True}
    engine=module.Drama3Engine(request);events=[]
    with progress_to(events.append):
        if outcome in ("limit","context"):
            with pytest.raises(TextCapacityExceeded):engine.generate(request)
        elif outcome=="missing":
            with pytest.raises(ValueError,match="não confirmou"):engine.generate(request)
        elif outcome.startswith("oom-"):
            with pytest.raises(MemoryUnavailable) as failure:engine.generate(request)
            assert failure.value.allow_split == (outcome=="oom-generate")
        else:engine.generate(request)
    seen=json.loads(Path(str(binary)+".seen.json").read_text());args=seen["args"]
    assert args[args.index("--backend")+1]=="cpu" and args[args.index("--out-format")+1]=="float32"
    assert seen["request"]["text"]==outcome and seen["request"]["reference_text"]==request["reference_text"]
    assert seen["request"]["options"]["text_chunk_size"]=="1000000000"
    for option in ("fish_drama3.disk_experts=true","fish_drama3.pin_experts=false","fish_drama3.expert_cache_size=8","fish_drama3.kv_cache_type=f32"):
        assert option in args
    if outcome=="ok":
        assert audio_valid(request["output"]) and any(e.get("generated_frames")==32 for e in events)
        with wave.open(request["output"]) as wav: assert wav.getframerate()==44100 and wav.getsampwidth()==3
    else:assert not audio_valid(request["output"])
    assert not [path for path in (data/"jobs").glob("drama3-work-*") if path.is_dir()]


@pytest.mark.parametrize("allow_split",[False,True])
def test_memory_phase_survives_runner_protocol(data,capsys,allow_split):
    import queue
    from app.engine_runner import error_reply
    from app.engine_session import EngineSession
    error_reply(MemoryUnavailable(8,2,allow_split=allow_split),{"engine":"drama3","dtype":"q4-bf16"})
    message=capsys.readouterr().out
    session=EngineSession.__new__(EngineSession)
    session.worker=SimpleNamespace(check=lambda _:None)
    session.ident="test";session.responses=queue.Queue();session.responses.put(message)
    with pytest.raises(MemoryUnavailable) as failure:session.wait()
    assert failure.value.allow_split is allow_split


@pytest.mark.parametrize("started",[False,True])
def test_killed_native_adapter_keeps_memory_phase(data,monkeypatch,started):
    import queue
    import app.engine_session as module
    session=module.EngineSession.__new__(module.EngineSession)
    session.worker=SimpleNamespace(check=lambda _:None)
    session.ident="test";session.profile=("drama3","q4-bf16")
    session.native_generation_started=started;session.oom_before=0
    session.process=SimpleNamespace(wait=lambda **_: -9)
    session.responses=queue.Queue();session.responses.put(None)
    monkeypatch.setattr(module,"oom_kills",lambda:0)
    with pytest.raises(MemoryUnavailable) as failure:session.wait()
    assert failure.value.allow_split is started


@pytest.mark.parametrize("allow_split",[False,True])
def test_native_load_memory_does_not_split_text_after_adapter_ready(data,monkeypatch,allow_split):
    from app.worker import Worker
    job=s.put("job",{"status":"running","snapshot":{"engine":"drama3","dtype":"q4-bf16"}})
    folder=data/"jobs"/job["id"];folder.mkdir()
    reference=data/"media/ref.wav";recording(reference)
    request={"engine":"drama3","text":"Uma frase inteira com espaços e pontuação. "*20,
             "language":"pt-BR","reference_text":"Minha referência.","reference":str(reference),"output":str(folder/"raw.wav")}
    worker=Worker();worker.clone_session=object()
    monkeypatch.setattr(worker,"check",lambda _:None)
    def fail(*_):raise MemoryUnavailable(8,2,allow_split=allow_split)
    monkeypatch.setattr(worker,"engine",fail)
    with pytest.raises(MemoryUnavailable):worker.synthesize(job["id"],request,folder)
    plan=folder/"raw.parts.json"
    assert plan.exists() is allow_split
    if allow_split:
        parts=json.loads(plan.read_text())["parts"]
        assert len(parts)>1 and "".join(part["text"] for part in parts)==request["text"]
