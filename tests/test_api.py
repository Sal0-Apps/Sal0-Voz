import io
from app import storage as s

def test_owner_setup_and_session(client):
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/setup", json={"password":"test-password"}).status_code == 200
    assert client.post("/api/auth/setup", json={"password":"test-password"}).status_code == 409
    assert client.get("/api/projects").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/login", json={"password":"incorrect-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"password":"test-password"}).status_code == 200

def test_csrf(owner):
    assert owner.post("/api/projects", json={"name":"Bad"}, headers={"Origin":"https://evil.example"}).status_code == 403

def test_project_history_and_character_versions(owner):
    c = owner.post("/api/characters", json={"name":"Luna"}).json()
    c2 = owner.put("/api/characters/"+c["id"], json={"name":"Luna nova"}).json()
    assert c2["versions"][0]["name"] == "Luna"
    assert c2["version"] == 2
    p = owner.post("/api/projects", json={"name":"Primeiro","text":"Olá"}).json()
    result = owner.put("/api/projects/"+p["id"], json={"name":"Segundo","text":"Novo"}).json()
    assert result["revision"] == 2
    old = owner.get("/api/projects/"+p["id"]+"/revisions").json()
    assert old[0]["text"] == "Olá"

def test_unavailable_model_does_not_fake_success(owner):
    p = owner.post("/api/projects", json={"name":"Clone","text":"Olá","engine":"qwen-1.7b"}).json()
    result = owner.post("/api/projects/"+p["id"]+"/generate")
    assert result.status_code == 400
    assert "referência" in result.json()["detail"]
    assert owner.get("/api/jobs").json() == []

def test_script_upload_and_safe_download(owner, data):
    result = owner.post("/api/media", files={"file":("../../escape.txt",b"script","text/plain")})
    assert result.status_code == 200
    media = result.json()
    assert media["name"] == "escape.txt"
    assert owner.get("/api/media/"+media["id"]+"/file").content == b"script"
    assert not (data.parent / "escape.txt").exists()
    assert owner.post("/api/media", files={"file":("bad.exe",b"bad")}).status_code == 400

def test_job_states(owner):
    j = s.put("job", {"status":"queued","name":"test","snapshot":{},"progress":0})
    assert owner.post("/api/jobs/"+j["id"]+"/pause").json()["status"] == "paused"
    assert owner.post("/api/jobs/"+j["id"]+"/resume").json()["status"] == "queued"
    assert owner.post("/api/jobs/"+j["id"]+"/cancel").json()["status"] == "cancelled"
    assert owner.post("/api/jobs/"+j["id"]+"/pause").status_code == 409
    assert "snapshot" not in owner.get("/api/jobs").json()[0]

def test_snapshot_freezes_character(owner, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "require", lambda *args: {"revision":"fixed"})
    c = owner.post("/api/characters", json={"name":"Luna"}).json()
    p = owner.post("/api/projects", json={"name":"Teste","text":"Oi","engine":"diagnostic","character_id":c["id"]}).json()
    j = owner.post("/api/projects/"+p["id"]+"/generate").json()
    owner.put("/api/characters/"+c["id"], json={"name":"Nova"})
    assert s.get("job", j["id"])["snapshot"]["segments"][0]["character"]["name"] == "Luna"

def test_dom_assets_and_no_external_runtime(owner):
    assert owner.get("/").status_code == 200
    for path in ("app.js","style.css","icon.svg","manifest.webmanifest"):
        result = owner.get("/static/"+path)
        assert result.status_code == 200
    assert "frame-ancestors 'none'" in owner.get("/").headers["Content-Security-Policy"]

def test_manual_subtitle_export(owner):
    p = owner.post("/api/projects", json={"name":"Legendas","cues":[{"start_ms":0,"end_ms":1000,"text":"Oi"}]}).json()
    output = owner.get("/api/projects/"+p["id"]+"/subtitles/srt")
    assert "00:00:00,000 --> 00:00:01,000" in output.text

