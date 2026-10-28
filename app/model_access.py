"""Private Hugging Face download credentials; never return the token to clients."""
import os
import re
from . import storage as s


def access_token():
    return os.getenv("HF_TOKEN", "").strip() or (s.setting("huggingface_token") or "").strip()


def status(user):
    return {"configured": bool(access_token()), "writable": user.get("role") == "admin",
            "source": "environment" if os.getenv("HF_TOKEN", "").strip() else "settings" if access_token() else None}


def save(user, token=None, clear=False):
    if user.get("role") != "admin":
        raise PermissionError("Somente administradores podem configurar o acesso aos modelos.")
    if clear:
        s.setting("huggingface_token", "")
    elif token and token.strip():
        token = token.strip()
        if not re.fullmatch(r"hf_[A-Za-z0-9_-]{8,500}", token):
            raise ValueError("Informe um token de leitura válido do Hugging Face, começando por hf_.")
        s.setting("huggingface_token", token)
    return status(user)


def redact(text):
    token = access_token()
    if token:
        text = text.replace(token, "[token oculto]")
    return re.sub(r"hf_[A-Za-z0-9_-]{8,}", "[token oculto]", text)
