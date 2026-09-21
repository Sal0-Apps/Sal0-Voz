"""Sal0 Voz local API. Run one Uvicorn process: the queue owns one worker."""
import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import psutil
from fastapi import FastAPI, Request, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import __version__, storage as s
from .catalog import installed, require
from .media import probe
from .script import compile_script, parse_srt, validate_cues, subtitles
from .worker import Worker

worker = Worker()
auth_lock = threading.Lock()
attempts = {}
STATIC = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(app):
    s.init()
    if os.getenv("SAL0_DISABLE_WORKER") != "1":
        worker.start()
    yield
    worker.stop()

app = FastAPI(title="Sal0 Voz", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

@app.middleware("http")
async def guard(request, call_next):
    path = request.url.path
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
    public = path in ("/", "/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login") or path.startswith("/static/")
    if not public:
        token = request.cookies.get("sal0_session", "")
        try:
            session = s.get("session", hashlib.sha256(token.encode()).hexdigest())
            if session["expires"] < time.time():
                raise KeyError()
        except KeyError:
            return JSONResponse({"detail": "Entre com sua senha local."}, status_code=401)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)

@app.exception_handler(KeyError)
async def not_found(request, exc):
    return JSONResponse({"detail": "Registro não encontrado."}, status_code=404)

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

@app.get("/health")
def health():
    with s.db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "version": __version__, "worker": bool(worker.thread and worker.thread.is_alive())}

@app.get("/api/auth/status")
def auth_status(request: Request):
    logged = False
    try:
        session = s.get("session", hashlib.sha256(request.cookies.get("sal0_session", "").encode()).hexdigest())
        logged = session["expires"] > time.time()
    except KeyError:
        pass
    return {"configured": bool(s.setting("password")), "authenticated": logged}

class Password(BaseModel):
    password: str = Field(min_length=8, max_length=256)

def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

def session_response():
    token = secrets.token_urlsafe(32)
    s.put("session", {"id": hashlib.sha256(token.encode()).hexdigest(), "expires": time.time()+7*86400})
    response = JSONResponse({"ok": True})
    response.set_cookie("sal0_session", token, httponly=True, samesite="strict", secure=os.getenv("SAL0_SECURE_COOKIE")=="1", max_age=7*86400)
    return response

@app.post("/api/auth/setup")
def setup(body: Password):
    with auth_lock:
        if s.setting("password"):
            raise HTTPException(409, "Proprietário já configurado.")
        salt = secrets.token_hex(16)
        s.setting("password", json.dumps({"salt": salt, "hash": password_hash(body.password, salt)}))
    return session_response()

@app.post("/api/auth/login")
def login(body: Password, request: Request):
    ip = request.client.host if request.client else "local"
    with auth_lock:
        recent = [t for t in attempts.get(ip, []) if time.time()-t < 300]
        if len(recent) >= 10:
            raise HTTPException(429, "Muitas tentativas. Aguarde cinco minutos.")
        saved = json.loads(s.setting("password") or "{}")
        if not saved or not hmac.compare_digest(saved["hash"], password_hash(body.password, saved["salt"])):
            attempts[ip] = recent + [time.time()]
            raise HTTPException(401, "Senha incorreta.")
        attempts.pop(ip, None)
    return session_response()

@app.post("/api/auth/logout")
def logout(request: Request):
    ident = hashlib.sha256(request.cookies.get("sal0_session", "").encode()).hexdigest()
    s.put("session", {"id": ident, "expires": 0})
    response = JSONResponse({"ok": True}); response.delete_cookie("sal0_session")
    return response

@app.get("/api/models")
def models():
    return installed()

@app.get("/api/diagnostics")
def diagnostics():
    disk = shutil.disk_usage(s.DATA); memory = psutil.virtual_memory()
    return {"version": __version__, "cpu": "CPU", "threads": int(os.getenv("SAL0_THREADS", "2")), "memory_total": memory.total, "memory_available": memory.available, "disk_free": disk.free, "ffmpeg": bool(shutil.which("ffmpeg") or os.getenv("SAL0_FFMPEG")), "ffprobe": bool(shutil.which("ffprobe") or os.getenv("SAL0_FFPROBE")), "platform": os.name, "validation": "Benchmark do A10 e comparação ElevenLabs pendentes", "features": {"voice_conversion": False, "automatic_emotion": False, "automatic_translation": False, "automatic_separation": False}}

@app.get("/api/{kind}")
def list_records(kind: str, offset: int = 0, limit: int = 50):
    if kind not in ("characters", "projects", "media", "jobs"):
        raise HTTPException(404)
    singular = {"characters": "character", "projects": "project", "media": "media", "jobs": "job"}[kind]
    values = s.listing(singular, max(offset, 0), min(max(limit, 1), 100))
    if kind == "jobs":
        return [{k: v for k, v in x.items() if k != "snapshot"} for x in values]
    return values

@app.post("/api/media")
def upload(file: UploadFile):
    name = Path((file.filename or "arquivo").replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    allowed = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".mp4", ".mkv", ".webm", ".mov", ".txt", ".srt"}
    if suffix not in allowed:
        raise ValueError("Formato não suportado.")
    ident = s.uid(); path = s.DATA / "media" / (ident + suffix)
    try:
        with path.open("wb") as output:
            while block := file.file.read(1024*1024):
                if shutil.disk_usage(s.DATA).free < 256*1024**2:
                    raise ValueError("Disco sem espaço suficiente.")
                output.write(block)
        if suffix in (".txt", ".srt"):
            content = path.read_text(encoding="utf-8-sig")
            metadata = {"text": content, "type": "script"}
            if suffix == ".srt":
                metadata["cues"] = parse_srt(content)
        else:
            metadata = {**probe(path), "type": "media"}
        return s.put("media", {"id": ident, "name": name, "path": path.relative_to(s.DATA).as_posix(), "size": path.stat().st_size, "sha256": s.digest(path), **metadata})
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()

@app.get("/api/media/{ident}/file")
def media_file(ident: str):
    media = s.get("media", ident)
    return FileResponse(s.safe_path(media["path"]), filename=media["name"], content_disposition_type="inline")

class Character(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    language: str = "pt-BR"
    origin: str = "own"
    reference_id: str | None = None
    reference_text: str = ""

def save_character(body, previous=None):
    value = body.model_dump()
    if value["language"] not in ("pt-BR", "en-US") or value["origin"] not in ("own", "authorized", "licensed"):
        raise ValueError("Idioma ou origem inválidos.")
    reference = s.get("media", body.reference_id) if body.reference_id else None
    if reference and (not reference.get("audio") or reference.get("video")):
        raise ValueError("Selecione uma referência somente de áudio.")
    version = {"number": len(previous.get("versions", []))+1 if previous else 1, **value, "reference": reference}
    versions = previous["versions"] + [version] if previous else [version]
    return s.put("character", {**value, "id": previous["id"] if previous else s.uid(), "versions": versions, "version": version["number"]})

@app.post("/api/characters")
def create_character(body: Character):
    return save_character(body)

@app.put("/api/characters/{ident}")
def update_character(ident: str, body: Character):
    return save_character(body, s.get("character", ident))

class Project(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    mode: str = "tts"
    text: str = ""
    language: str = "pt-BR"
    engine: str = "qwen-1.7b"
    asr_engine: str = "whisper-medium"
    character_id: str | None = None
    media_id: str | None = None
    background_id: str | None = None
    rate: float = Field(default=1, ge=0.8, le=1.2)
    format: str = "wav"
    cues: list[dict] = Field(default_factory=list)

def project_data(body, ident=None):
    if body.mode not in ("tts", "asr", "dub"):
        raise ValueError("Modo indisponível nesta versão.")
    if body.language not in ("pt-BR", "en-US") or body.format not in ("wav", "flac", "mp3", "opus"):
        raise ValueError("Idioma ou formato inválido.")
    old = s.get("project", ident) if ident else None
    value = {**body.model_dump(), "id": ident or s.uid(), "revision": old["revision"]+1 if old else 1}
    if old:
        history = {**old, "id": old["id"] + "-" + str(old["revision"])}
        s.put("project_revision", history)
    return s.put("project", value)

@app.post("/api/projects")
def create_project(body: Project):
    return project_data(body)

@app.put("/api/projects/{ident}")
def update_project(ident: str, body: Project):
    return project_data(body, ident)

@app.get("/api/projects/{ident}")
def get_project(ident: str):
    return s.get("project", ident)

@app.get("/api/projects/{ident}/revisions")
def project_revisions(ident: str):
    s.get("project", ident)
    return [x for x in s.listing("project_revision", limit=-1) if x["id"].startswith(ident+"-")]

@app.post("/api/script/validate")
def validate_script(body: Project):
    return {"segments": compile_script(body.text, body.language, body.character_id, body.rate), "capabilities": {"pause": "exact", "rate": "postprocessing", "volume": "postprocessing", "emotion": "unavailable", "reactions": "unavailable"}}

def snapshot(project):
    value = dict(project)
    if project["mode"] in ("asr", "dub"):
        if not project["media_id"]:
            raise ValueError("Selecione a mídia original.")
        value["media"] = s.get("media", project["media_id"])
        if not value["media"].get("audio"):
            raise ValueError("A mídia precisa ter uma faixa de áudio.")
    if project["mode"] == "asr":
        value["model"] = require(project["asr_engine"], "asr")
        return value
    value["model"] = require(project["engine"], "tts")
    if project["mode"] == "dub":
        if not value["media"].get("video"):
            raise ValueError("Selecione um vídeo para dublar.")
        cues = validate_cues(project["cues"])
        if not cues:
            raise ValueError("Importe e revise um SRT antes de dublar.")
        previous_end = 0
        for cue in cues:
            if cue["start_ms"] < previous_end or cue["end_ms"] > value["media"]["duration"]*1000:
                raise ValueError("Falas sobrepostas ou além do vídeo precisam de revisão manual.")
            previous_end = cue["end_ms"]
        value["segments"] = []
        for cue in cues:
            parsed = compile_script(cue["text"], project["language"], cue.get("character_id") or project["character_id"], project["rate"])
            if len(parsed) != 1 or parsed[0].get("pause_ms"):
                raise ValueError("Divida as falas longas em mais de uma legenda antes de dublar.")
            value["segments"].append({**parsed[0], "start_ms": cue["start_ms"], "end_ms": cue["end_ms"]})
        if project["background_id"]:
            value["background"] = s.get("media", project["background_id"])
            if not value["background"].get("audio") or value["background"].get("video"):
                raise ValueError("O ambiente separado deve ser um arquivo de áudio.")
    else:
        value["segments"] = compile_script(project["text"], project["language"], project["character_id"], project["rate"])
    for segment in value["segments"]:
        if segment.get("pause_ms") is not None:
            continue
        char_id = segment.get("character_id")
        if char_id:
            character = s.get("character", char_id)
            segment["character"] = character["versions"][-1]
        if project["engine"].startswith("qwen-"):
            character = segment.get("character")
            if not character or not character["reference"] or not character["reference_text"].strip():
                raise ValueError("Clonagem exige personagem com áudio de referência e sua transcrição.")
    return value

@app.post("/api/projects/{ident}/generate")
def generate(ident: str):
    project = snapshot(s.get("project", ident))
    job = s.put("job", {"project_id": ident, "name": project["name"], "snapshot": project, "status": "queued", "stage": "Aguardando executor", "progress": 0, "outputs": [], "created": time.time()})
    (s.DATA / "jobs" / job["id"]).mkdir(parents=True, exist_ok=True)
    worker.wake.set()
    return {"id": job["id"], "status": job["status"]}

@app.post("/api/jobs/{ident}/{action}")
def job_action(ident: str, action: str):
    with worker.lock:
        job = s.get("job", ident)
        allowed = {"pause": ("queued", "running"), "resume": ("paused", "failed", "cancelled"), "cancel": ("queued", "running", "paused", "failed")}
        if action not in allowed or job["status"] not in allowed[action]:
            raise HTTPException(409, "Transição não permitida para este trabalho.")
        status = {"pause": "paused", "resume": "queued", "cancel": "cancelled"}[action]
        job = worker.update(ident, status=status, stage={"paused": "Pausado", "queued": "Aguardando retomada", "cancelled": "Cancelado"}[status], error=None)
    worker.wake.set()
    return {"id": ident, "status": status}

@app.get("/api/jobs/{ident}/output/{index}")
def output(ident: str, index: int):
    job = s.get("job", ident)
    if index < 0 or index >= len(job.get("outputs", [])):
        raise HTTPException(404)
    out = job["outputs"][index]
    return FileResponse(s.safe_path(out["path"]), filename=out["name"], content_disposition_type="inline")

@app.get("/api/jobs/{ident}/log")
def job_log(ident: str):
    s.get("job", ident)
    path = s.DATA / "jobs" / ident / "process.log"
    if not path.exists():
        return {"text": "Nenhum log de processo disponível."}
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size-16000))
        return {"text": stream.read().decode("utf-8", errors="replace")}

class Cues(BaseModel):
    cues: list[dict]

@app.put("/api/projects/{ident}/cues")
def update_cues(ident: str, body: Cues):
    project = s.get("project", ident)
    project["cues"] = validate_cues(body.cues)
    return project_data(Project(**project), ident)

@app.get("/api/projects/{ident}/subtitles/{extension}")
def export_cues(ident: str, extension: str):
    if extension not in ("srt", "vtt"):
        raise HTTPException(404)
    project = s.get("project", ident)
    from fastapi.responses import Response
    return Response(subtitles(project["cues"], extension=="vtt"), media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="legendas.{extension}"'})

@app.get("/api/events/stream")
async def events(request: Request):
    import asyncio
    async def stream():
        previous = ""
        while not await request.is_disconnected():
            jobs = [{k: v for k, v in x.items() if k != "snapshot"} for x in s.listing("job", limit=50)]
            data = json.dumps(jobs, ensure_ascii=False)
            if data != previous:
                yield "data: " + data + "\n\n"
                previous = data
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

