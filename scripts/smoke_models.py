"""Manual opt-in check after model downloads; never run in release CI."""
import http.cookiejar
import json
import os
import secrets
import time
import urllib.request
from app.catalog import DEFAULT_MODELS, DEFAULT_ASR_MODEL

BASE = os.getenv("SAL0_SMOKE_BASE", "http://127.0.0.1:7860")
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def api(path, value=None):
    body = json.dumps(value).encode() if value is not None else None
    req = urllib.request.Request(BASE+path, data=body, headers={"Content-Type":"application/json"})
    with opener.open(req, timeout=30) as response:
        return json.load(response)

def job(project):
    created = api("/api/projects", project)
    return api("/api/projects/"+created["id"]+"/generate", {})["id"]

def wait_job(ident, timeout=1800):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=next(x for x in api("/api/jobs") if x["id"]==ident)
        if value["status"]=="completed":return value
        if value["status"] in {"failed","paused"}:
            raise AssertionError({"job":value,"log":api("/api/jobs/"+ident+"/log")})
        time.sleep(3)
    raise AssertionError("Job timeout: "+ident)

def main():
    engine=os.getenv("SAL0_SMOKE_CLONE_ENGINE", "qwen-0.6b")
    password=os.getenv("SAL0_SMOKE_PASSWORD") or secrets.token_urlsafe(24)
    auth=api("/api/auth/status")
    api("/api/auth/login" if auth["configured"] else "/api/auth/setup", {"password":password})
    catalog={m["id"]:m for m in api("/api/models")}
    for ident in set(DEFAULT_MODELS) | {engine}:
        assert catalog[ident]["available"], catalog[ident]
    reference_text=("Hello, this is a reference voice for the local speech test. "
                    "I am reading clearly, with short pauses, to help the model reproduce this voice.")
    source=wait_job(job({"name":"Reference", "engine":"diagnostic", "language":"en-US", "text":reference_text}))
    with opener.open(BASE+"/api/jobs/"+source["id"]+"/output/0") as response:
        audio=response.read()
    boundary=secrets.token_hex(16)
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reference.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+audio+f'\r\n--{boundary}--\r\n'.encode())
    req=urllib.request.Request(BASE+"/api/media",data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    with opener.open(req) as response:media=json.load(response)
    transcription=job({"name":"Automatic ASR", "mode":"asr", "language":"en-US", "media_id":media["id"]})
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline:
        models=[x for x in api("/api/models") if x["id"] in {engine,DEFAULT_ASR_MODEL}]
        print([(m["id"],m["available"],m.get("download",{}).get("progress")) for m in models],flush=True)
        for model in models:
            assert model.get("download",{}).get("status") != "failed", model
        if all(m["available"] for m in models):break
        time.sleep(15)
    else:raise AssertionError("Automatic model download timed out")
    assert wait_job(transcription)["cues"], "Whisper produced no subtitles"
    character=api("/api/characters", {"name":"Synthetic test reference", "language":"en-US", "reference_id":media["id"]})
    clone=wait_job(job({"name":"Real Qwen CPU", "engine":engine, "language":"pt-BR", "text":"Olá, esta é minha voz. [pausa=250ms] Agora, outro trecho.", "character_id":character["id"]}))
    expected_dtype = os.getenv("SAL0_SMOKE_EXPECT_DTYPE", "float32")
    assert clone["profile"]["dtype"] == expected_dtype, clone["profile"]
    if expected_dtype == "bfloat16":
        assert clone["profile"]["engine"] == os.getenv("SAL0_SMOKE_EXPECT_ENGINE", "qwen-0.6b") and clone["profile"]["adapted"], clone["profile"]
    with opener.open(BASE+"/api/jobs/"+clone["id"]+"/output/0") as response:
        result=response.read()
    assert result[:4]==b"RIFF" and len(result)>1000
    assert len(clone["cues"])==2, "Clone did not generate both speech segments"
    prepared=api("/api/characters/"+character["id"]+"/reference-text")
    assert prepared["automatic"] and prepared["text"], "Clone did not use an automatic full reference transcript"
    print("PASS: installed models, real large-v3-turbo ASR and two-segment "+clone["profile"]["name"]+" CPU cloning with automatic full reference transcription",flush=True)

if __name__=="__main__":main()
