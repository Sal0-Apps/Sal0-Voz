"""Online release check: bootstrap real models and exercise ASR and cloning."""
import http.cookiejar
import json
import secrets
import time
import urllib.request

BASE = "http://127.0.0.1:7860"
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def api(path, value=None):
    body = json.dumps(value).encode() if value is not None else None
    req = urllib.request.Request(BASE+path, data=body, headers={"Content-Type":"application/json"})
    with opener.open(req, timeout=30) as response:
        return json.load(response)

def job(project):
    created = api("/api/projects", project)
    return api("/api/projects/"+created["id"]+"/generate", {})["id"]

def wait_job(ident, timeout=900):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=next(x for x in api("/api/jobs") if x["id"]==ident)
        if value["status"]=="completed":return value
        if value["status"] in {"failed","paused"}:
            raise AssertionError({"job":value,"log":api("/api/jobs/"+ident+"/log")})
        time.sleep(3)
    raise AssertionError("Job timeout: "+ident)

def main():
    api("/api/auth/setup", {"password":secrets.token_urlsafe(24)})
    reference_text="Hello, this is a reference voice for the local speech test."
    source=wait_job(job({"name":"Reference", "engine":"diagnostic", "language":"en-US", "text":reference_text}))
    with opener.open(BASE+"/api/jobs/"+source["id"]+"/output/0") as response:
        audio=response.read()
    boundary=secrets.token_hex(16)
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reference.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+audio+f'\r\n--{boundary}--\r\n'.encode())
    req=urllib.request.Request(BASE+"/api/media",data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    with opener.open(req) as response:media=json.load(response)
    # Submit while bootstrap is still running: the server must resume this job itself.
    transcription=job({"name":"Automatic ASR", "mode":"asr", "language":"en-US", "media_id":media["id"]})
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline:
        models=[x for x in api("/api/models") if x["id"] in {"qwen-0.6b","whisper-medium"}]
        print([(m["id"],m["available"],m.get("download",{}).get("progress")) for m in models],flush=True)
        for model in models:
            assert model.get("download",{}).get("status") != "failed", model
        if all(m["available"] for m in models):break
        time.sleep(15)
    else:raise AssertionError("Automatic model download timed out")
    assert wait_job(transcription)["cues"], "Whisper produced no subtitles"
    character=api("/api/characters", {"name":"Synthetic test reference", "language":"en-US", "reference_id":media["id"], "reference_text":reference_text})
    clone=wait_job(job({"name":"Real Qwen CPU", "engine":"qwen-0.6b", "language":"en-US", "text":"Hello from Sal0.", "character_id":character["id"]}))
    with opener.open(BASE+"/api/jobs/"+clone["id"]+"/output/0") as response:
        result=response.read()
    assert result[:4]==b"RIFF" and len(result)>1000
    print("PASS: automatic downloads, queued ASR, real Whisper and Qwen CPU audio",flush=True)

if __name__=="__main__":main()
