import json
import os
import shutil
import subprocess
from pathlib import Path

def ffmpeg():
    binary = os.getenv("SAL0_FFMPEG") or shutil.which("ffmpeg")
    if not binary:
        raise ValueError("FFmpeg não encontrado. A imagem Docker inclui este programa.")
    return binary

def probe(path):
    binary = os.getenv("SAL0_FFPROBE") or shutil.which("ffprobe")
    if not binary:
        raise ValueError("ffprobe não encontrado.")
    result = subprocess.run([binary, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Mídia inválida ou codec não reconhecido pelo ffprobe.")
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if not any(x.get("codec_type") in ("audio", "video") for x in streams):
        raise ValueError("O arquivo não contém áudio ou vídeo.")
    return {"duration": float(info.get("format", {}).get("duration", 0)), "video": any(x.get("codec_type") == "video" for x in streams), "audio": any(x.get("codec_type") == "audio" for x in streams), "streams": [{"type": x.get("codec_type"), "codec": x.get("codec_name"), "channels": x.get("channels")} for x in streams]}

def ffargs(*args):
    return [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)]

