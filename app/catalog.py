import json
import os
import shutil
import sys
from pathlib import Path
from . import storage as s

CATALOG = {
    "diagnostic": {"name": "Voz de diagnóstico", "kind": "tts", "clone": False, "license": "GPL-3.0 (eSpeak NG)", "notice": "Voz sintética simples para testar o app; não representa a qualidade final."},
    "qwen-1.7b": {"name": "Qwen3-TTS · 1.7B Base", "kind": "tts", "clone": True, "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "runtime": "qwen", "license": "Apache-2.0", "notice": "Clonagem candidata. Qualidade e memória ainda precisam ser medidas no A10."},
    "qwen-0.6b": {"name": "Qwen3-TTS · 0.6B Base", "kind": "tts", "clone": True, "repo": "Qwen/Qwen3-TTS-12Hz-0.6B-Base", "runtime": "qwen", "license": "Apache-2.0", "notice": "Alternativa de memória; não substitui o modelo escolhido automaticamente."},
    "whisper-medium": {"name": "Whisper medium · INT8", "kind": "asr", "repo": "Systran/faster-whisper-medium", "runtime": "whisper", "license": "MIT", "notice": "Transcrição local em CPU. Revise as legendas."},
    "whisper-large-v3": {"name": "Whisper large-v3 · INT8", "kind": "asr", "repo": "Systran/faster-whisper-large-v3", "runtime": "whisper", "license": "MIT", "notice": "Candidato de qualidade; valide RAM e precisão na máquina alvo."},
}

def runtime(engine):
    family = CATALOG[engine].get("runtime")
    if not family:
        return sys.executable
    root = Path(os.getenv("SAL0_ENGINES", "/opt/engines"))
    path = root / family / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(path)

def installed():
    out = []
    for ident, meta in CATALOG.items():
        item = {"id": ident, **meta}
        if ident == "diagnostic":
            item["available"] = bool(shutil.which("espeak-ng") or shutil.which("espeak"))
        else:
            folder = s.DATA / "models" / ident
            manifest = folder / "manifest.json"
            try:
                saved = json.loads(manifest.read_text())
                item["available"] = Path(runtime(ident)).is_file() and all((folder / f).is_file() for f in saved["files"]) and bool(saved["files"])
                item["revision"] = saved["revision"]
            except (OSError, ValueError, KeyError):
                item["available"] = False
        item["validation"] = "Não avaliado no A10"
        out.append(item)
    return out

def require(ident, kind):
    item = next((x for x in installed() if x["id"] == ident), None)
    if not item or item["kind"] != kind:
        raise ValueError("Motor incompatível com esta operação.")
    if not item["available"]:
        raise ValueError(f"Modelo ou ambiente {item['name']} não instalado. Consulte Ajustes.")
    return item

