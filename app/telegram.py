"""Telegram delivery for server-side job status and output files."""
import html
import json
import urllib.request
import uuid
from pathlib import Path
from . import storage as s
def _user_key(user): return (user or {}).get("username") or "admin"
def _config_path(user): return s.DATA/"users"/_user_key(user)/"telegram.json"
def load_config(user):
    try: return json.loads(_config_path(user).read_text(encoding="utf-8"))
    except (OSError,ValueError): return {"telegram_token":"","telegram_chat_id":""}
def save_config(user,token,chat_id):
    path=_config_path(user); path.parent.mkdir(parents=True,exist_ok=True); previous=load_config(user)
    if "***" in token: token=previous.get("telegram_token","")
    s.atomic_json(path,{"telegram_token":token.strip(),"telegram_chat_id":str(chat_id).strip()})
def masked(user):
    config=load_config(user); token=config.get("telegram_token","")
    if len(token)>8: token=token[:6]+"***"+token[-4:]
    return {"telegram_token":token,"telegram_chat_id":config.get("telegram_chat_id","")}
def _request(token,method,fields,file_path=None):
    if not token: return False
    boundary="----Sal0Voz"+uuid.uuid4().hex; body=bytearray()
    for key,value in fields.items(): body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    if file_path:
        path=Path(file_path); body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()); body.extend(path.read_bytes()); body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    request=urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}",data=bytes(body),headers={"Content-Type":f"multipart/form-data; boundary={boundary}"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=120) as response: return 200<=response.status<300
    except Exception: return False
def send_message(config,text):
    return _request(config.get("telegram_token",""),"sendMessage",{"chat_id":config.get("telegram_chat_id",""),"text":text,"parse_mode":"HTML"})
def send_document(config,path,caption):
    return _request(config.get("telegram_token",""),"sendDocument",{"chat_id":config.get("telegram_chat_id",""),"caption":caption[:1024],"parse_mode":"HTML"},path)
def notify_job(job,status=None):
    config=load_config({"username":job.get("owner_username") or "admin"})
    if not config.get("telegram_token") or not config.get("telegram_chat_id"): return
    current=status or job.get("status","queued"); icon={"completed":"✅","failed":"⚠️","cancelled":"⛔","running":"🔄"}.get(current,"📌")
    name=html.escape(str(job.get("name","trabalho"))); stage=html.escape(str(job.get("stage",current))); elapsed=job.get("elapsed_seconds"); suffix=f" · {elapsed:.1f}s" if isinstance(elapsed,(int,float)) else ""
    send_message(config,f"{icon} <b>Sal0 Voz</b>\n<b>{name}</b>\n{stage}{suffix}")
    if current=="completed":
        for output in job.get("outputs",[]):
            try:
                path=s.safe_path(output["path"]); send_document(config,path,f"📥 <b>{html.escape(output.get('name',path.name))}</b>\n{name}")
            except (OSError,ValueError,KeyError): continue
