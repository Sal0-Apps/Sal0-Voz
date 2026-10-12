import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from app.engine_runner import decode_audio, transcribe


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "reference.wav"
    samples = (np.sin(2*np.pi*220*np.arange(60000)/24000)*16000).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(24000)
        out.writeframes(samples.tobytes())
    return path


def test_decoder_preserves_audio_and_resamples(recording):
    with decode_audio(recording, recording.parent) as audio:
        assert isinstance(audio, np.memmap) and audio.dtype == np.float32 and len(audio) == 40000
        assert np.isfinite(audio).all() and abs(audio).max() > .3
        assert abs(audio[-1600:]).max() > .3
        backing = str(audio.filename)
    from pathlib import Path
    assert not Path(backing).exists() and audio._mmap.closed


def test_transcriber_receives_decoded_audio_and_cpu_options(recording, tmp_path, monkeypatch):
    import json
    calls = {}
    class Whisper:
        def __init__(self, path, **options):
            calls.update(path=path, options=options)
            self.feature_extractor = SimpleNamespace()
        def transcribe(self, audio, **options):
            calls.update(audio=audio.copy(), disk_audio=isinstance(audio, np.memmap), transcribe=options)
            return iter([SimpleNamespace(start=.5, end=2.25, text=" Olá. "),
                         SimpleNamespace(start=2.25, end=2.5, text=" ")]), None
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Whisper))
    monkeypatch.setenv("SAL0_THREADS", "4")
    output = tmp_path / "cues.json"
    transcribe({"model_path": "/models/turbo", "source": str(recording),
                "language": "pt-BR", "output": str(output)})
    assert calls["options"] == {"device": "cpu", "compute_type": "int8", "cpu_threads": 4,
                                "num_workers": 1, "local_files_only": True}
    assert isinstance(calls["audio"], np.ndarray) and len(calls["audio"]) == 40000
    assert calls["disk_audio"]
    assert calls["transcribe"] == {"language": "pt", "beam_size": 5, "vad_filter": True,
                                   "word_timestamps": True, "condition_on_previous_text": False}
    assert json.loads(output.read_text()) == [{"start_ms": 500, "end_ms": 2250, "text": "Olá."}]


def test_invalid_recording_has_a_useful_error(tmp_path):
    path = tmp_path / "invalid.wav"
    path.write_bytes(b"invalid audio")
    with pytest.raises(ValueError, match="Não foi possível ler o áudio"):
        with decode_audio(path, tmp_path):
            pytest.fail("Invalid audio must not be mapped")
