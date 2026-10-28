"""Bounded float WAV -> PCM24, preserving native rate and avoiding clipping."""
from pathlib import Path


def pcm24(source, destination, sample_rate):
    import numpy as np
    import soundfile as sf
    peak, count = 0.0, 0
    with sf.SoundFile(source) as audio:
        if audio.channels != 1 or audio.samplerate != sample_rate:
            raise ValueError("O motor devolveu um formato de áudio inesperado.")
        for block in audio.blocks(blocksize=sample_rate, dtype="float32"):
            if not np.isfinite(block).all():
                raise ValueError("O motor produziu amostras inválidas; nenhum áudio foi confirmado.")
            if len(block):
                peak = max(peak, float(np.max(np.abs(block))))
                count += len(block)
    if not count:
        raise ValueError("O motor não produziu áudio.")
    gain = 0.999/peak if peak >= 1.0 else 1.0
    try:
        with sf.SoundFile(source) as audio, sf.SoundFile(destination, "w", samplerate=sample_rate,
                channels=1, format="WAV", subtype="PCM_24") as output:
            for block in audio.blocks(blocksize=sample_rate, dtype="float32"):
                output.write(block*gain if gain != 1.0 else block)
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise
