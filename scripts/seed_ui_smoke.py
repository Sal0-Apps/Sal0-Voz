"""Disposable UI fixtures. No model downloads, imports or inference."""
import os
import struct
import wave

from app import storage as s


def seed():
    if os.getenv("SAL0_DISABLE_WORKER") != "1":
        raise RuntimeError("UI fixtures require a disabled worker and temporary SAL0_DATA")
    if (s.DATA / "app.sqlite").exists():
        raise RuntimeError("Refusing to seed an existing database")
    s.init()
    for relative in ("media/11111111111111111111111111111111.wav", "jobs/33333333333333333333333333333333/result.wav"):
        destination = s.DATA / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(struct.pack("<h", 0) * 24000 * 4)
    source = s.DATA / "media/11111111111111111111111111111111.wav"
    reference = s.put("media", {"id": "11111111111111111111111111111111", "name": "Referência de teste.wav",
                   "path": "media/11111111111111111111111111111111.wav", "size": source.stat().st_size,
                   "sha256": s.digest(source), "type": "media", "audio": True,
                   "video": False, "duration": 4, "owner_username": "admin"})
    character = {"id": "22222222222222222222222222222222", "name": "Voz de teste", "version": 1,
                       "language": "pt-BR", "origin": "own", "description": "",
                       "reference_id": "11111111111111111111111111111111", "reference_text": "Referência para testar a interface.",
                 "reactions": {}, "owner_username": "admin"}
    character["versions"] = [{**character, "number": 1, "reference": reference, "reaction_media": {}}]
    s.put("character", character)
    s.put("job", {"id": "33333333333333333333333333333333", "name": "Resultado de teste.wav", "status": "completed",
                 "progress": 100, "stage": "Concluído", "elapsed_seconds": 6537,
                 "snapshot": {}, "owner_username": "admin", "outputs": [
                     {"name": "Resultado de teste.wav", "type": "audio", "path": "jobs/33333333333333333333333333333333/result.wav"}
                 ]})


if __name__ == "__main__":
    seed()
