import json
import sys
import wave
from pathlib import Path
import pytest
from app import storage as s
from app.catalog import installed, model_files, models_needed, DEFAULT_ASR_MODEL
from app.worker import Worker
from scripts.models import verify_file

def model(root, ident, content=b"weights"):
    folder=root/ident
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/"weights.bin"
    path.write_bytes(content)
    s.atomic_json(folder/"manifest.json", {"revision":"fixed", "files":{"weights.bin":s.digest(path)}, "file_sizes":{"weights.bin":len(content)}})
    return folder

def test_empty_data_volume_uses_bundled_models_without_download(owner, data, tmp_path, monkeypatch):
    import app.catalog as catalog
    root=tmp_path/"image-models"
    model(root,"qwen-1.7b");model(root,DEFAULT_ASR_MODEL)
    monkeypatch.setenv("SAL0_BUNDLED_MODELS",str(root))
    monkeypatch.setattr(catalog,"runtime",lambda _:sys.executable)
    voice=next(m for m in installed() if m["id"]=="qwen-1.7b")
    assert voice["available"] and voice["source"]=="bundled"
    asr=next(m for m in installed() if m["id"]==DEFAULT_ASR_MODEL)
    assert asr["available"] and asr["source"]=="bundled"
    media=s.put("media",{"audio":True,"path":"media/ref.wav","owner_username":"admin"})
    char=owner.post("/api/characters",json={"name":"Minha voz","reference_id":media["id"]}).json()
    project=owner.post("/api/projects",json={"name":"Clone","text":"Olá, mundo.","character_id":char["id"]}).json()
    assert project["engine"]=="qwen-1.7b"
    job=owner.post("/api/projects/"+project["id"]+"/generate")
    assert job.status_code==200 and s.listing("model_download",limit=-1)==[]

def test_truncated_persistent_model_falls_back_to_image(data,tmp_path,monkeypatch):
    root=tmp_path/"image-models";expected=model(root,"qwen-1.7b")
    local=model(data/"models","qwen-1.7b")
    (local/"weights.bin").write_bytes(b"bad")
    monkeypatch.setenv("SAL0_BUNDLED_MODELS",str(root))
    folder,_,source=model_files("qwen-1.7b")
    assert folder==expected and source=="bundled"

def test_download_matches_upstream_hash(tmp_path):
    path=tmp_path/"weights";path.write_bytes(b"correct weights")
    sha=s.digest(path)
    assert verify_file(path,{"sha256":sha})
    path.write_bytes(b"corrupt weights")
    assert not verify_file(path,{"sha256":sha})

def test_clone_without_manual_text_waits_for_asr_too():
    project={"mode":"tts","engine":"qwen-1.7b","segments":[{"character":{"reference":{"path":"ref.wav"},"reference_text":""}}]}
    assert models_needed(project)==["qwen-1.7b",DEFAULT_ASR_MODEL]
    project["segments"][0]["character"]["reference_text"]="Texto exato."
    assert models_needed(project)==["qwen-1.7b"]

@pytest.mark.parametrize("selected", [None, "whisper-medium"])
def test_new_transcription_defaults_to_turbo_and_preserves_explicit_model(owner, selected):
    payload={"name":"Transcrição", "mode":"asr"}
    if selected:
        payload["asr_engine"]=selected
    response=owner.post("/api/projects", json=payload)
    assert response.status_code==200
    assert response.json()["asr_engine"]==(selected or "whisper-large-v3-turbo")

def test_failed_download_keeps_job_and_recovers_automatically(data,monkeypatch):
    import app.worker as module
    worker=Worker();ready=False
    def require(*args):
        if not ready:raise ValueError("waiting")
        return {"id":"qwen-1.7b","revision":"fixed"}
    monkeypatch.setattr(module,"require",require)
    module.model_manager._record("qwen-1.7b",status="failed",error="network interruption")
    job=s.put("job",{"status":"queued","snapshot":{"mode":"tts","engine":"qwen-1.7b"}})
    monkeypatch.setattr(worker.wake,"wait",lambda _:worker.stop_event.set())
    worker.loop()
    assert s.get("job",job["id"])["status"]=="queued"
    ready=True;worker.stop_event.clear()
    monkeypatch.setattr(worker,"execute",lambda _:None)
    monkeypatch.setattr(worker,"check",lambda _:None)
    monkeypatch.setattr(module,"notify_job",lambda _:worker.stop_event.set())
    worker.loop()
    assert s.get("job",job["id"])["status"]=="completed"

def reference_job(data,text=""):
    source=data/"media"/"reference.wav"
    with wave.open(str(source),"wb") as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
        out.writeframes(b"\0\0"*24000*6)
    character={"number":1,"name":"Minha voz","language":"pt-BR","reference_id":"media-1",
               "reference":{"path":"media/reference.wav"},"reference_text":text}
    project={"mode":"tts","engine":"qwen-0.6b","language":"pt-BR","name":"Clone","owner_username":"admin","format":"wav",
             "segments":[{"text":"O texto novo continua intacto.","character_id":"voice-1","character":character.copy(),"language":"pt-BR","rate":1,"volume":0},
                         {"text":"Outro trecho.","character_id":"voice-1","character":character.copy(),"language":"pt-BR","rate":1,"volume":0}]}
    return s.put("job",{"status":"running","stage":"Preparando","name":"Clone","snapshot":project,"progress":0})

def test_auto_reference_cache_and_single_clone_process(data,monkeypatch):
    import app.worker as module
    job=reference_job(data);worker=Worker();asr_calls=[];sessions=[];requests=[]
    monkeypatch.setattr(module,"require",lambda *args:{"revision":"fixed"})
    old_engine=worker.engine
    def engine(ident,request,folder):
        if request["engine"].startswith("whisper"):
            asr_calls.append(request)
            Path(request["output"]).write_text(json.dumps([{"text":"Texto exato da gravação."}]))
        else:old_engine(ident,request,folder)
    monkeypatch.setattr(worker,"engine",engine)
    class Session:
        def __init__(self,*args):sessions.append(self);self.closed=False
        def generate(self,request):
            requests.append(request)
            with wave.open(request["output"],"wb") as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000);out.writeframes(b"\0\0"*24000)
        def close(self):self.closed=True
    monkeypatch.setattr(module,"EngineSession",Session)
    worker.execute(job)
    assert len(asr_calls)==1 and len(sessions)==1 and sessions[0].closed
    assert asr_calls[0]["engine"]=="whisper-large-v3-turbo"
    assert [r["text"] for r in requests]==["O texto novo continua intacto.","Outro trecho."]
    assert all(r["reference_text"]=="Texto exato da gravação." for r in requests)
    original=job["snapshot"]["segments"][0]["character"]
    assert original["reference_text"]==""  # Automatic preparation does not rewrite the saved version.
    updated=s.get("job",job["id"])
    worker.execute(updated)
    assert len(asr_calls)==1 and len(sessions)==1  # Resume reuses prepared reference and checkpoints.

def test_empty_reference_transcript_never_uses_reduced_clone(data,monkeypatch):
    import app.worker as module
    worker=Worker();job=reference_job(data)
    monkeypatch.setattr(module,"require",lambda *args:{"revision":"fixed"})
    def empty_asr(ident,request,folder):Path(request["output"]).write_text("[]")
    monkeypatch.setattr(worker,"engine",empty_asr)
    with pytest.raises(ValueError,match="fala na gravação"):
        worker.execute(job)

def test_reference_transcript_is_private(owner):
    char=owner.post("/api/characters",json={"name":"Privada","reference_text":"Minha gravação privada."}).json()
    owner.post("/api/users",json={"username":"maria","password":"test-password"})
    owner.post("/api/auth/logout")
    owner.post("/api/auth/login",json={"username":"maria","password":"test-password"})
    assert owner.get("/api/characters/"+char["id"]+"/reference-text").status_code==403
