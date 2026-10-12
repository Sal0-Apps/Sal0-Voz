"""Durable, hash-checked audio checkpoints; read samples only in bounded blocks."""
import json
import os
import wave
from pathlib import Path
from . import storage as s


def audio_valid(path):
    path = Path(path)
    try:
        meta = json.loads(path.with_suffix(".json").read_text())
        return meta.get("sha256") == s.digest(path) and meta.get("duration", 0) > 0
    except (OSError, ValueError, KeyError, TypeError):
        return False


def checkpoint_audio(path):
    path = Path(path)
    with wave.open(str(path), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    if duration <= 0:
        raise ValueError("Motor produziu áudio vazio.")
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    s.atomic_json(path.with_suffix(".json"), {"sha256": s.digest(path), "duration": duration})
    return duration
