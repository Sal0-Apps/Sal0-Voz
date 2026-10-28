"""Sal0 Voz local API. Run one Uvicorn process: the queue owns one worker."""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
from functools import wraps
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import psutil
from fastapi import FastAPI, Request, UploadFile, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from . import __version__, storage as s
from .catalog import CATALOG, installed, require, models_needed, DEFAULT_CLONE_MODEL, DEFAULT_ASR_MODEL, DEFAULT_MODELS, is_clone
from .resources import memory_available, cgroup_memory
from .media import probe, ffargs, input_args
from .model_manager import manager as model_manager
from .script import compile_script, parse_srt, validate_cues, subtitles
from .telegram import masked as masked_telegram, notify_job, save_config as save_telegram
from . import model_access
from .worker import Worker
from .omnivoice_quality import MAXIMUM_PROFILE

worker = Worker()
auth_lock = threading.Lock()
attempts = {}
STATIC = Path(__file__).parent / "static"
# One fingerprint covers the page and both of its runtime assets. A browser or
# proxy retaining an older app.js must never combine it with a new DOM/CSS.
UI_REVISION = hashlib.sha256(b"\0".join(
    (STATIC / name).read_bytes() for name in ("index.html", "app.js", "style.css")
)).hexdigest()[:20]
UI_HTML = (STATIC / "index.html").read_text(encoding="utf-8").replace("__UI_REVISION__", UI_REVISION)

@asynccontextmanager
async def lifespan(app):
    s.init()
    from .library import recover_removals
    recover_removals()
    if os.getenv("SAL0_DISABLE_WORKER") != "1":
        model_manager.start()
    if os.getenv("SAL0_DISABLE_WORKER") != "1":
        worker.start()
    yield
    worker.stop()
    model_manager.stop()

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
            session = await run_in_threadpool(s.get, "session", hashlib.sha256(token.encode()).hexdigest())
            if session["expires"] < time.time():
                raise KeyError()
        except KeyError:
            return JSONResponse({"detail": "Entre com sua senha local."}, status_code=401)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if path.startswith("/api") or path in ("/", "/static/index.html", "/static/app.js", "/static/style.css"):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path == "/api/model-access":
        return JSONResponse({"detail": "Configuração de acesso inválida."}, status_code=422)
    return await request_validation_exception_handler(request, exc)

@app.exception_handler(KeyError)
async def not_found(request, exc):
    return JSONResponse({"detail": "Registro não encontrado."}, status_code=404)

@app.get("/")
def index():
    return HTMLResponse(UI_HTML, headers={"Cache-Control": "no-store"})

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
    user = {}
    if logged:
        try:
            session = s.get("session", hashlib.sha256(request.cookies.get("sal0_session", "").encode()).hexdigest())
            user = {"username": session.get("username", "admin"), "role": session.get("role", "admin")}
        except KeyError:
            pass
    return {"configured": bool(s.setting("password")), "authenticated": logged, **user}

class Password(BaseModel):
    username: str = Field(default="admin", min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=256)


def current_user(request: Request):
    token = request.cookies.get("sal0_session", "")
    try:
        session = s.get("session", hashlib.sha256(token.encode()).hexdigest())
        if session["expires"] < time.time():
            raise KeyError()
        return {"username": session.get("username", "admin"), "role": session.get("role", "admin")}
    except KeyError:
        raise HTTPException(401, "Entre com sua senha local.")

def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

def session_response(username="admin", role="admin"):
    token = secrets.token_urlsafe(32)
    s.put("session", {"id": hashlib.sha256(token.encode()).hexdigest(), "username": username, "role": role, "expires": time.time()+7*86400})
    response = JSONResponse({"ok": True})
    response.set_cookie("sal0_session", token, httponly=True, samesite="strict", secure=os.getenv("SAL0_SECURE_COOKIE")=="1", max_age=7*86400)
    return response

@app.post("/api/auth/setup")
def setup(body: Password):
    with auth_lock:
        if s.setting("password"):
            raise HTTPException(409, "Proprietário já configurado.")
        salt = secrets.token_hex(16)
        digest = password_hash(body.password, salt)
        s.setting("password", json.dumps({"salt": salt, "hash": digest}))
        s.put("user", {"id": body.username, "username": body.username, "role": "admin", "salt": salt, "hash": digest})
    return session_response(body.username, "admin")

@app.post("/api/auth/login")
def login(body: Password, request: Request):
    ip = request.client.host if request.client else "local"
    with auth_lock:
        recent = [t for t in attempts.get(ip, []) if time.time()-t < 300]
        if len(recent) >= 10:
            raise HTTPException(429, "Muitas tentativas. Aguarde cinco minutos.")
        saved = json.loads(s.setting("password") or "{}")
        try:
            user = s.get("user", body.username)
            valid = hmac.compare_digest(user["hash"], password_hash(body.password, user["salt"]))
            role = user.get("role", "user")
        except KeyError:
            valid = not s.listing("user", limit=1) and body.username == "admin" and bool(saved) and hmac.compare_digest(saved["hash"], password_hash(body.password, saved["salt"]))
            role = "admin"
        if not valid:
            attempts[ip] = recent + [time.time()]
            raise HTTPException(401, "Senha incorreta.")
        attempts.pop(ip, None)
    if valid and not s.listing("user", limit=1):
        s.put("user", {"id": body.username, "username": body.username, "role": role, **saved})
    return session_response(body.username, role)

@app.post("/api/auth/logout")
def logout(request: Request):
    ident = hashlib.sha256(request.cookies.get("sal0_session", "").encode()).hexdigest()
    s.put("session", {"id": ident, "expires": 0})
    response = JSONResponse({"ok": True}); response.delete_cookie("sal0_session")
    return response

@app.get("/api/models")
def models():
    return model_manager.snapshot()


class ModelDownload(BaseModel):
    accept_license: bool = True


class ModelAccess(BaseModel):
    token: str | None = Field(default=None, max_length=512)
    clear: bool = False


@app.get("/api/model-access")
def get_model_access(request: Request):
    return model_access.status(current_user(request))


@app.put("/api/model-access")
def put_model_access(body: ModelAccess, request: Request):
    user = current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Somente administradores podem configurar o acesso aos modelos.")
    return model_access.save(user, token=body.token, clear=body.clear)


@app.post("/api/models/{ident}/download")
def download_model(ident: str, body: ModelDownload):
    return model_manager.request(ident, accept_license=body.accept_license)


@app.post("/api/models/{ident}/cancel")
def cancel_model(ident: str):
    return model_manager.cancel(ident)

@app.post("/api/models/prepare")
def prepare_models():
    needed = set(DEFAULT_MODELS)
    for ident in s.job_ids("queued"):
        job = s.get("job", ident)
        if job.get("status") == "queued" and job.get("snapshot", {}).get("mode"):
            needed.update(models_needed(job["snapshot"]))
    return [model_manager.request(ident, accept_license=True) for ident in sorted(needed)
            if ident in CATALOG and "repo" in CATALOG[ident]]


class TelegramConfig(BaseModel):
    telegram_token: str = Field(default="", max_length=256)
    telegram_chat_id: str = Field(default="", max_length=128)
    telegram_base_url: str = Field(default="", max_length=2048)


@app.get("/api/telegram")
def get_telegram(request: Request):
    return masked_telegram(current_user(request))


@app.put("/api/telegram")
def put_telegram(body: TelegramConfig, request: Request):
    save_telegram(current_user(request), body.telegram_token, body.telegram_chat_id,
                  body.telegram_base_url or str(request.base_url))
    return masked_telegram(current_user(request))


@app.get("/api/users")
def list_users(request: Request):
    user = current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Apenas administradores podem gerenciar usuários.")
    return [{k: value for k, value in item.items() if k not in {"hash", "salt"}} for item in s.listing("user", limit=-1)]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default="user", pattern=r"^(user|admin)$")


@app.post("/api/users")
def create_user(body: UserCreate, request: Request):
    if current_user(request).get("role") != "admin":
        raise HTTPException(403, "Apenas administradores podem criar usuários.")
    try:
        s.get("user", body.username)
        raise HTTPException(409, "Este usuário já existe.")
    except KeyError:
        pass
    salt = secrets.token_hex(16)
    s.put("user", {"id": body.username, "username": body.username, "role": body.role, "salt": salt, "hash": password_hash(body.password, salt)})
    return {"username": body.username, "role": body.role}


@app.delete("/api/users/{username}")
def delete_user(username: str, request: Request):
    if current_user(request).get("role") != "admin":
        raise HTTPException(403, "Apenas administradores podem excluir usuários.")
    if username == current_user(request).get("username"):
        raise HTTPException(400, "Você não pode excluir a si mesmo.")
    s.get("user", username)
    with s.db() as conn:
        conn.execute("DELETE FROM records WHERE kind='user' AND id=?", (username,))
        for session in s.listing("session", limit=-1):
            if session.get("username") == username:
                conn.execute("DELETE FROM records WHERE kind='session' AND id=?", (session["id"],))
    return {"ok": True}

@app.get("/api/diagnostics")
def diagnostics():
    disk = shutil.disk_usage(s.DATA); memory = psutil.virtual_memory()
    usage = cgroup_memory()
    return {"version": __version__, "cpu": "CPU", "threads": int(os.getenv("SAL0_THREADS", "4")), "memory_total": memory.total, "memory_available": memory_available(), "memory_host_available": memory.available, "memory_container_limit": usage[0] if usage else None, "disk_free": disk.free, "ffmpeg": bool(shutil.which("ffmpeg") or os.getenv("SAL0_FFMPEG")), "ffprobe": bool(shutil.which("ffprobe") or os.getenv("SAL0_FFPROBE")), "platform": os.name, "validation": "Benchmark no servidor do proprietário pendente", "features": {"voice_conversion": False, "automatic_emotion": False, "automatic_translation": False, "automatic_separation": False, "reactions": True, "automatic_dubbing": True}}

def visible(value, user):
    return user.get("role") == "admin" or value.get("owner_username") == user.get("username")


def list_records(kind: str, request: Request, offset: int = 0, limit: int = 50):
    if kind not in ("characters", "projects", "media", "jobs"):
        raise HTTPException(404)
    singular = {"characters": "character", "projects": "project", "media": "media", "jobs": "job"}[kind]
    return s.catalog_page(singular, current_user(request), offset, limit)

@app.get("/api/characters")
def list_characters(request: Request, offset: int = 0, limit: int = 50):
    return list_records("characters", request, offset, limit)

@app.get("/api/projects")
def list_projects(request: Request, offset: int = 0, limit: int = 50):
    return list_records("projects", request, offset, limit)

@app.get("/api/media")
def list_media(request: Request, offset: int = 0, limit: int = 50):
    return list_records("media", request, offset, limit)

@app.get("/api/jobs")
def list_jobs(request: Request, offset: int = 0, limit: int = 50):
    return list_records("jobs", request, offset, limit)

class DeleteItems(BaseModel):
    kind: str = Field(pattern=r"^(media|characters|results)$")
    ids: list[str] = Field(min_length=1, max_length=100)

@app.post("/api/items/delete")
def delete_items(body: DeleteItems, request: Request):
    from .library import remove_items
    return remove_items(body.kind, body.ids, current_user(request), worker)

def catalog_write(function):
    """Reference writes and removal share the queue's catalog lock."""
    @wraps(function)
    def locked(*args, **kwargs):
        with worker.lock:
            return function(*args, **kwargs)
    return locked

@app.post("/api/media")
def upload(file: UploadFile, request: Request):
    name = Path((file.filename or "arquivo").replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
        suffix = ".media"
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
        return s.put("media", {"id": ident, "owner_username": current_user(request)["username"], "name": name, "path": path.relative_to(s.DATA).as_posix(), "size": path.stat().st_size, "sha256": s.digest(path), **metadata})
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()

@app.get("/api/media/{ident}/file")
def media_file(ident: str, request: Request):
    media = s.get("media", ident)
    if not visible(media, current_user(request)):
        raise HTTPException(403, "Arquivo pertence a outro usuário.")
    import mimetypes
    guessed = mimetypes.guess_type(media["name"])[0] or "application/octet-stream"
    content_type = guessed if guessed.startswith(("audio/", "video/")) else "text/plain" if media["type"] in ("text", "script", "subtitle") else "application/octet-stream"
    return FileResponse(s.safe_path(media["path"]), media_type=content_type, filename=media["name"], content_disposition_type="inline")

class Character(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    language: str = "pt-BR"
    origin: str = "own"
    reference_id: str | None = None
    reference_text: str = ""
    reactions: dict[str, str] = Field(default_factory=dict)

@catalog_write
def save_character(body, previous=None, owner=None):
    value = body.model_dump()
    if value["language"] not in ("pt-BR", "en-US") or value["origin"] not in ("own", "authorized", "licensed"):
        raise ValueError("Idioma ou origem inválidos.")
    reference = s.get("media", body.reference_id) if body.reference_id else None
    if reference and not visible(reference, owner):
        raise HTTPException(403, "Arquivo pertence a outro usuário.")
    if reference and not reference.get("audio"):
        raise ValueError("O arquivo de referência precisa conter áudio. Um vídeo sem faixa de áudio não pode ser usado para clonar a voz.")
    from .reactions import reaction
    reaction_media = {}
    for key, ident in body.reactions.items():
        reaction(key)
        media = s.get("media", ident)
        if not visible(media, owner):
            raise HTTPException(403, "Arquivo de reação pertence a outro usuário.")
        if not media.get("audio"):
            raise ValueError("A gravação da reação precisa conter áudio.")
        reaction_media[key] = media
    version = {"number": len(previous.get("versions", []))+1 if previous else 1, **value, "reference": reference, "reaction_media": reaction_media}
    versions = previous["versions"] + [version] if previous else [version]
    return s.put("character", {**value, "owner_username": previous.get("owner_username") if previous else owner["username"], "id": previous["id"] if previous else s.uid(), "versions": versions, "version": version["number"]})

@app.post("/api/characters")
def create_character(body: Character, request: Request):
    return save_character(body, owner=current_user(request))

@app.put("/api/characters/{ident}")
@catalog_write
def update_character(ident: str, body: Character, request: Request):
    previous = s.get("character", ident)
    if not visible(previous, current_user(request)):
        raise HTTPException(403, "Personagem pertence a outro usuário.")
    return save_character(body, previous, current_user(request))

@app.get("/api/characters/{ident}/reference-text")
def reference_text(ident: str, request: Request):
    character = s.get("character", ident)
    if not visible(character, current_user(request)):
        raise HTTPException(403, "Voz pertence a outro usuário.")
    if character.get("reference_text", "").strip():
        return {"text": character["reference_text"], "automatic": False}
    try:
        value = s.get("reference_preparation", ident+"-"+str(character["version"]))
        return {key: value[key] for key in ("text", "automatic", "seconds")}
    except KeyError:
        return {"text": "", "automatic": True}

@app.get("/api/characters/{ident}/reference-file")
def character_reference_file(ident: str, request: Request):
    character = s.get("character", ident)
    if not visible(character, current_user(request)):
        raise HTTPException(403, "Voz pertence a outro usuário.")
    reference = character["versions"][-1].get("reference")
    if not reference or not reference.get("audio"):
        raise ValueError("Esta voz ainda não tem uma referência com áudio.")
    source = s.safe_path(reference["path"])
    folder = s.DATA / "cache" / "reference-preview"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / (s.digest(source) + ".wav")
    if not output.is_file():
        import subprocess
        temporary = folder / (s.uid() + ".partial.wav")
        try:
            result = subprocess.run(ffargs(*input_args(source), "-map", "0:a:0", "-t", "30", "-vn",
                                          "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", temporary),
                                    capture_output=True, timeout=120)
            if result.returncode or not temporary.is_file() or temporary.stat().st_size <= 44:
                raise ValueError("Não foi possível extrair o áudio desta referência. Confira o arquivo original.")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return FileResponse(output, media_type="audio/wav", filename="referencia.wav", content_disposition_type="inline")

class Project(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    mode: str = "tts"
    text: str = ""
    language: str = "pt-BR"
    engine: str = DEFAULT_CLONE_MODEL
    asr_engine: str = DEFAULT_ASR_MODEL
    adaptive_memory: bool = True
    expressiveness: float = Field(default=0.7, ge=0.25, le=1.2)
    voice_style: str = "natural"
    audio_name: str = Field(default="", max_length=160)
    character_id: str | None = None
    media_id: str | None = None
    background_id: str | None = None
    rate: float = Field(default=1, ge=0.8, le=1.2)
    format: str = "wav"
    cues: list[dict] = Field(default_factory=list)

@catalog_write
def project_data(body, ident=None, owner=None):
    from .voice_styles import instruction
    instruction(body.voice_style)
    if body.mode not in ("tts", "asr", "dub"):
        raise ValueError("Modo indisponível nesta versão.")
    if body.language not in ("pt-BR", "en-US") or body.format not in ("wav", "flac", "mp3", "opus"):
        raise ValueError("Idioma ou formato inválido.")
    for kind, ref in [("character", body.character_id), ("media", body.media_id), ("media", body.background_id)] + [("character", cue.get("character_id")) for cue in body.cues]:
        if ref and owner and not visible(s.get(kind, ref), owner):
            raise HTTPException(403, "Referência pertence a outro usuário.")
    old = s.get("project", ident) if ident else None
    value = {**body.model_dump(), "owner_username": old.get("owner_username") if old else owner["username"], "id": ident or s.uid(), "revision": old["revision"]+1 if old else 1}
    if old:
        history = {**old, "id": old["id"] + "-" + str(old["revision"])}
        s.put("project_revision", history)
    return s.put("project", value)

@app.post("/api/projects")
def create_project(body: Project, request: Request):
    return project_data(body, owner=current_user(request))

@app.put("/api/projects/{ident}")
def update_project(ident: str, body: Project, request: Request):
    old = s.get("project", ident)
    if not visible(old, current_user(request)):
        raise HTTPException(403, "Projeto pertence a outro usuário.")
    return project_data(body, ident, current_user(request))

@app.get("/api/projects/{ident}")
def get_project(ident: str, request: Request):
    value = s.get("project", ident)
    if not visible(value, current_user(request)):
        raise HTTPException(403, "Projeto pertence a outro usuário.")
    return value

@app.get("/api/projects/{ident}/revisions")
def project_revisions(ident: str, request: Request):
    value = s.get("project", ident)
    if not visible(value, current_user(request)):
        raise HTTPException(403, "Projeto pertence a outro usuário.")
    return [x for x in s.listing("project_revision", limit=-1) if x["id"].startswith(ident+"-") and visible(x, current_user(request))]

@app.post("/api/script/validate")
def validate_script(body: Project):
    return {"segments": compile_script(body.text, body.language, body.character_id, body.rate), "capabilities": {"pause": "exact", "rate": "postprocessing", "volume": "postprocessing", "emotion": "model_dependent", "reactions": "selected_voice"}}

@app.get("/api/reactions")
def get_reactions():
    from .reactions import catalog
    return [{key: item[key] for key in ("id", "name", "category", "native_models", "generation")} for item in catalog()]

@app.get("/api/reactions/{ident}/file")
def get_reaction_file(ident: str):
    from .reactions import reaction
    reaction(ident)
    raise HTTPException(410, "As reações agora são geradas com a voz escolhida. Insira a reação no roteiro e gere o áudio.")

def model_for_job(ident, kind):
    if ident not in CATALOG or CATALOG[ident]["kind"] != kind:
        raise ValueError("Motor incompatível com esta operação.")
    try:
        return require(ident, kind)
    except ValueError:
        if "repo" not in CATALOG[ident]:
            raise
        return {"id": ident, **CATALOG[ident], "available": False}

def snapshot(project, owner=None):
    def owned(kind, ident):
        item = s.get(kind, ident)
        if owner and not visible(item, owner):
            raise HTTPException(403, "Referência pertence a outro usuário.")
        return item
    value = dict(project)
    value["output_sample_rate"] = CATALOG.get(project.get("engine"), {}).get("sample_rate", 24000)
    if project.get("engine") == "omnivoice" and project["mode"] != "asr":
        value.update(omnivoice_profile=MAXIMUM_PROFILE, omnivoice_seed=secrets.randbits(32), output_sample_width=3)
    from .quality_profiles import PROFILES
    if project.get("engine") in PROFILES and project["mode"] != "asr":
        value.update(quality_profile=PROFILES[project["engine"]], model_seed=secrets.randbits(32),
                     dtype=CATALOG[project["engine"]].get("dtype", "float32"), output_sample_width=3)
    if project["mode"] in ("asr", "dub"):
        if not project["media_id"]:
            raise ValueError("Selecione a mídia original.")
        value["media"] = owned("media", project["media_id"])
        if not value["media"].get("audio"):
            raise ValueError("A mídia precisa ter uma faixa de áudio.")
    if project["mode"] == "asr":
        value["model"] = model_for_job(project["asr_engine"], "asr")
        return value
    if project["mode"] == "dub":
        cues = validate_cues(project["cues"])
        value["automatic_dub"] = not bool(cues)
        if not cues and project.get("character_id"):
            character = owned("character", project["character_id"])
            value["default_character"] = character["versions"][-1]
        if not cues and is_clone(project["engine"]) and not value.get("default_character", {}).get("reference"):
            raise ValueError("Selecione uma voz com gravação de referência para dublar o áudio ou vídeo.")
        previous_end = 0
        for cue in cues:
            if cue["start_ms"] < previous_end or cue["end_ms"] > value["media"]["duration"]*1000:
                raise ValueError("Falas sobrepostas ou além do vídeo precisam de revisão manual.")
            previous_end = cue["end_ms"]
        value["segments"] = []
        for cue_index, cue in enumerate(cues):
            parsed = compile_script(cue["text"], project["language"], cue.get("character_id") or project["character_id"], project["rate"])
            value["segments"].extend({**part, "cue_index": cue_index, "start_ms": cue["start_ms"], "end_ms": cue["end_ms"]} for part in parsed)
        if project["background_id"]:
            value["background"] = owned("media", project["background_id"])
            if not value["background"].get("audio") or value["background"].get("video"):
                raise ValueError("O ambiente separado deve ser um arquivo de áudio.")
    else:
        value["segments"] = compile_script(project["text"], project["language"], project["character_id"], project["rate"])
    for segment in value["segments"]:
        if segment.get("pause_ms") is not None:
            continue
        char_id = segment.get("character_id")
        if char_id:
            character = owned("character", char_id)
            segment["character"] = character["versions"][-1]
        if is_clone(project["engine"]):
            character = segment.get("character")
            if not character or not character.get("reference"):
                raise ValueError("Selecione um áudio de referência para clonar a voz.")
    if models_needed(value):
        languages = CATALOG.get(project["engine"], {}).get("languages")
        if languages and any(segment.get("pause_ms") is None and segment["language"] not in languages for segment in value["segments"]):
            raise ValueError("Escolha Português brasileiro para usar este modelo de voz.")
        if languages and value.get("automatic_dub") and project["language"] not in languages:
            raise ValueError("Escolha Português brasileiro para usar este modelo de voz.")
        value["model"] = model_for_job(project["engine"], "tts")
    elif project["engine"] not in CATALOG or CATALOG[project["engine"]]["kind"] != "tts":
        raise ValueError("Motor incompatível com esta operação.")
    return value

@app.post("/api/projects/{ident}/generate")
@catalog_write
def generate(ident: str, request: Request):
    owner = current_user(request)
    project_record = s.get("project", ident)
    if not visible(project_record, owner):
        raise HTTPException(403, "Projeto pertence a outro usuário.")
    project = snapshot(project_record, owner)
    from .output_names import output_name
    project["output_name"] = output_name(project, owner["username"])
    waiting = False
    for engine in models_needed(project):
        model = model_for_job(engine, "asr" if engine.startswith("whisper-") else "tts")
        if model.get("available") is False:
            waiting = True
            model_manager.request(engine, accept_license=True, automatic=True)
    job = s.put("job", {"project_id": ident, "owner_username": owner["username"], "app_url": str(request.base_url).rstrip("/"), "name": project["output_name"], "snapshot": project, "status": "queued", "stage": "Aguardando modelo — o trabalho começará automaticamente" if waiting else "Aguardando executor", "progress": 0, "outputs": [], "created": time.time()})
    threading.Thread(target=notify_job, args=(job,), daemon=True).start()
    (s.DATA / "jobs" / job["id"]).mkdir(parents=True, exist_ok=True)
    worker.wake.set()
    return {"id": job["id"], "status": job["status"]}

@app.post("/api/jobs/{ident}/{action}")
def job_action(ident: str, action: str, request: Request):
    with worker.lock:
        job = s.get("job", ident)
        if not visible(job, current_user(request)):
            raise HTTPException(403, "Trabalho pertence a outro usuário.")
        allowed = {"pause": ("queued", "running"), "resume": ("paused", "failed", "cancelled"), "cancel": ("queued", "running", "paused", "failed")}
        if action not in allowed or job["status"] not in allowed[action]:
            raise HTTPException(409, "Transição não permitida para este trabalho.")
        if action == "resume":
            project = job.get("snapshot", {})
            engine = project.get("asr_engine") if project.get("mode") == "asr" else project.get("engine")
            download = model_manager.status(engine) if engine else None
            if download and download.get("status") in {"failed", "cancelled"}:
                model_manager.request(engine, accept_license=True, automatic=True)
        status = {"pause": "paused", "resume": "queued", "cancel": "cancelled"}[action]
        job = worker.update(ident, status=status, stage={"paused": "Pausado", "queued": "Aguardando retomada", "cancelled": "Cancelado"}[status], error=None, retry_at=None, consecutive_retries=0)
    worker.wake.set()
    return {"id": ident, "status": status}

@app.get("/api/jobs/{ident}")
def get_job(ident: str, request: Request):
    job = s.get("job", ident)
    if not visible(job, current_user(request)):
        raise HTTPException(403, "Trabalho pertence a outro usuário.")
    return {key: value for key, value in job.items() if key != "snapshot"}


@app.get("/api/jobs/{ident}/output/{index}")
def output(ident: str, index: int, request: Request):
    job = s.get("job", ident)
    if not visible(job, current_user(request)):
        raise HTTPException(403, "Trabalho pertence a outro usuário.")
    if index < 0 or index >= len(job.get("outputs", [])):
        raise HTTPException(404)
    out = job["outputs"][index]
    return FileResponse(s.safe_path(out["path"]), filename=out["name"], content_disposition_type="inline")

@app.get("/api/jobs/{ident}/log")
def job_log(ident: str, request: Request):
    job = s.get("job", ident)
    if not visible(job, current_user(request)):
        raise HTTPException(403, "Trabalho pertence a outro usuário.")
    path = s.DATA / "jobs" / ident / "process.log"
    if not path.exists():
        return {"text": "Nenhum log de processo disponível."}
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size-16000))
        return {"text": stream.read().decode("utf-8", errors="replace")}

class Cues(BaseModel):
    cues: list[dict]

@app.put("/api/projects/{ident}/cues")
def update_cues(ident: str, body: Cues, request: Request):
    project = s.get("project", ident)
    if not visible(project, current_user(request)):
        raise HTTPException(403, "Projeto pertence a outro usuário.")
    project["cues"] = validate_cues(body.cues)
    return project_data(Project(**project), ident, current_user(request))

@app.get("/api/projects/{ident}/subtitles/{extension}")
def export_cues(ident: str, extension: str, request: Request):
    if extension not in ("srt", "vtt"):
        raise HTTPException(404)
    project = s.get("project", ident)
    if not visible(project, current_user(request)):
        raise HTTPException(403, "Projeto pertence a outro usuário.")
    from fastapi.responses import Response
    return Response(subtitles(project["cues"], extension=="vtt"), media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="legendas.{extension}"'})

@app.get("/api/events/stream")
def events(request: Request):
    """Finite snapshot for older clients; never reserve a browser HTTP socket."""
    from fastapi.responses import Response
    owner = current_user(request)
    data = json.dumps(s.catalog_page("job", owner, limit=50), ensure_ascii=False)
    return Response("retry: 5000\ndata: " + data + "\n\n", media_type="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"})

