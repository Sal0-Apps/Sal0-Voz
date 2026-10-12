import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def safe_demuxers():
    excluded = {"hls", "dash", "concat", "image2", "avisynth", "vapoursynth", "sbg", "lavfi"}
    binary = os.getenv("SAL0_FFPROBE") or shutil.which("ffprobe")
    if not binary:
        raise ValueError("ffprobe não encontrado.")
    result = subprocess.run([binary, "-hide_banner", "-demuxers"], capture_output=True, text=True, timeout=30)
    formats = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "D":
            formats.extend(name for name in fields[1].split(",") if name not in excluded)
    if result.returncode or not formats:
        raise ValueError("Não foi possível consultar os formatos de mídia do servidor.")
    return ",".join(formats)

def input_args(path):
    return ["-protocol_whitelist", "file,pipe", "-format_whitelist", safe_demuxers(), "-i", str(path)]

def ffmpeg():
    binary = os.getenv("SAL0_FFMPEG") or shutil.which("ffmpeg")
    if not binary:
        raise ValueError("FFmpeg não encontrado. A imagem Docker inclui este programa.")
    return binary

def probe(path):
    binary = os.getenv("SAL0_FFPROBE") or shutil.which("ffprobe")
    if not binary:
        raise ValueError("ffprobe não encontrado.")
    result = subprocess.run([binary, "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", safe_demuxers(), "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Não foi possível ler este arquivo. Envie um áudio ou vídeo válido com codec reconhecido pelo FFmpeg.")
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if not any(x.get("codec_type") in ("audio", "video") for x in streams):
        raise ValueError("O arquivo não contém áudio ou vídeo.")
    return {"duration": float(info.get("format", {}).get("duration", 0)), "video": any(x.get("codec_type") == "video" for x in streams), "audio": any(x.get("codec_type") == "audio" for x in streams), "streams": [{"type": x.get("codec_type"), "codec": x.get("codec_name"), "channels": x.get("channels"), "pixel_format": x.get("pix_fmt")} for x in streams]}

def ffargs(*args):
    return [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)]

