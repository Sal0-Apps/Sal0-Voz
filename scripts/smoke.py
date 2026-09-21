"""Exercise the installed image through HTTP; use only an empty test volume."""
import http.cookiejar
import json
import secrets
import time
import urllib.request

def run(base="http://127.0.0.1:7860"):
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, value=None):
        body=json.dumps(value).encode() if value is not None else None
        req=urllib.request.Request(base+path, data=body, headers={"Content-Type":"application/json"})
        with opener.open(req, timeout=10) as response:
            return json.load(response)
    assert request("/health")["status"]=="ok"
    assert not request("/api/auth/status")["configured"], "Use somente um volume vazio de teste"
    request("/api/auth/setup", {"password":secrets.token_urlsafe(20)})
    for language,text in [("pt-BR","Esta voz foi gerada localmente."),("en-US","This voice was generated locally.")]:
        project=request("/api/projects", {"name":"Docker smoke "+language,"mode":"tts","engine":"diagnostic","language":language,"text":text,"format":"wav"})
        job=request("/api/projects/"+project["id"]+"/generate", {})
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            saved=next(j for j in request("/api/jobs") if j["id"]==job["id"])
            if saved["status"] in ("completed","failed","paused"):
                break
            time.sleep(0.5)
        assert saved["status"]=="completed", saved
        with opener.open(base+"/api/jobs/"+job["id"]+"/output/0") as audio:
            assert audio.read(4)==b"RIFF"
        with opener.open(base+"/api/jobs/"+job["id"]+"/output/1") as srt:
            assert "-->" in srt.read().decode()
    print("HTTP authentication, persistent queue, real pt-BR/en-US speech, WAV and SRT: PASS")

if __name__=="__main__":
    run()

