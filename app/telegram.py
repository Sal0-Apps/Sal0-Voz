"""Telegram notifications contain authenticated app links, never attachments."""
import html
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from urllib.parse import urlencode, urlsplit
from . import storage as s
from . import notification_preferences as preferences

MODES = [('tts', 'Texto em voz'), ('dub', 'Dublar'), ('asr', 'Transcrever / legendar')]
EVENTS = [('queued', 'Entrada na fila'), ('started', 'Início do processamento'),
          ('progress', 'Andamento'), ('completed', 'Resultado concluído'),
          ('failed', 'Erros'), ('paused', 'Pausa e retomada'), ('cancelled', 'Cancelamento')]
DEFAULTS = {'queued': True, 'started': False, 'progress': False, 'completed': True,
            'failed': True, 'paused': False, 'cancelled': False}
DEFAULT_TEXTS = {key: icon+' Sal0 Voz · {modo}\n{titulo}\n{etapa}\n{tempo}\n{link}' for key, icon in
                 [('queued','📌'),('started','▶️'),('progress','🔄'),('completed','✅'),
                  ('failed','⚠️'),('paused','⏸'),('cancelled','⛔')]}
_messages = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voz-telegram')


def policy(config):
    return preferences.normalize(config.get('notification_policy'), MODES, EVENTS, DEFAULTS)


def enqueue_job_notification(job, status=None):
    config = load_config({'username': job.get('owner_username') or 'admin'})
    event = status or {'running': 'started'}.get(job.get('status'), job.get('status', 'queued'))
    mode = (job.get('snapshot') or {}).get('mode', 'tts')
    if config.get('telegram_token') and config.get('telegram_chat_id') and preferences.allowed(policy(config), mode, event):
        _messages.submit(notify_job, dict(job), event)


def _user_key(user):
    return (user or {}).get("username") or "admin"


def _config_path(user):
    return s.DATA/"users"/_user_key(user)/"telegram.json"


def normalize_url(value):
    value = str(value or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError:
        raise ValueError("Endereço do aplicativo inválido.") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError("Use o endereço HTTP ou HTTPS do aplicativo, sem senha ou parâmetros.")
    return value


def load_config(user):
    try:
        return json.loads(_config_path(user).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"telegram_token":"", "telegram_chat_id":"", "telegram_base_url":""}


def save_config(user, token, chat_id, base_url=None, notification_policy=None):
    path = _config_path(user)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = load_config(user)
    if "***" in token:
        token = previous.get("telegram_token", "")
    base_url = normalize_url(previous.get("telegram_base_url", "") if base_url is None else base_url)
    notifications = preferences.normalize(notification_policy, MODES, EVENTS, DEFAULTS) if notification_policy is not None else policy(previous)
    s.atomic_json(path, {"telegram_token":token.strip(), "telegram_chat_id":str(chat_id).strip(),
                         "telegram_base_url":base_url, 'notification_policy': notifications})


def masked(user):
    config = load_config(user)
    token = config.get("telegram_token", "")
    if len(token)>8:
        token = token[:6]+"***"+token[-4:]
    return {"telegram_token":token, "telegram_chat_id":config.get("telegram_chat_id", ""),
            "telegram_base_url":config.get("telegram_base_url", ""),
            'notification_policy': policy(config), 'notification_modes': MODES,
            'notification_events': EVENTS, 'notification_defaults': DEFAULT_TEXTS,
            'notification_variables': ['titulo','modo','etapa','progresso','tempo','link','mensagem']}


def _request(token, fields):
    if not token:
        return False
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(fields).encode(), headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def send_message(config, text):
    return _request(config.get("telegram_token", ""), {
        "chat_id":config.get("telegram_chat_id", ""), "text":text, "parse_mode":"HTML",
        "link_preview_options":{"is_disabled":True},
    })


def format_elapsed(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        return ""
    total = max(0, math.floor(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours} h {minutes} min {seconds} s"


def notify_job(job, status=None):
    config = load_config({"username":job.get("owner_username") or "admin"})
    if not config.get("telegram_token") or not config.get("telegram_chat_id"):
        return
    current = status or job.get("status", "queued")
    event = 'started' if current == 'running' else current
    mode = (job.get('snapshot') or {}).get('mode', 'tts')
    settings = policy(config)
    if not preferences.allowed(settings, mode, event):
        return
    icon = {"completed":"✅", "failed":"⚠️", "cancelled":"⛔", "running":"🔄"}.get(current, "📌")
    name = html.escape(str(job.get("name", "trabalho"))[:160])
    stage = html.escape(str(job.get("stage", current))[:1200])
    elapsed = format_elapsed(job.get("elapsed_seconds"))
    suffix = f" · {elapsed}" if elapsed else ""
    text = f"{icon} <b>Sal0 Voz</b>\n<b>{name}</b>\n{stage}{suffix}"
    base = config.get("telegram_base_url") or os.getenv("SAL0_PUBLIC_URL") or job.get("app_url")
    try:
        base = normalize_url(base)
    except ValueError:
        base = ""
    plain_link = base+"/?"+urlencode({"job":job['id']}) if base else ''
    if base:
        link = html.escape(plain_link, quote=True)
        label = "Abrir resultados" if current == "completed" else "Abrir andamento"
        text += f'\n<a href="{link}">{label}</a>'
    else:
        text += "\nDefina o endereço do aplicativo em Ajustes → Telegram para receber os links."
    template = settings['templates'][mode].get(event, '')
    text = preferences.render(template, {'titulo': job.get('name','trabalho'),
        'modo': dict(MODES).get(mode, mode), 'etapa': job.get('stage', current),
        'progresso': str(round(float(job.get('progress') or 0)))+'%', 'tempo': elapsed,
        'link': plain_link}, text)
    send_message(config, text)
