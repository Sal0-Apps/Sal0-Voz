"""Disk-backed audio/features, with the same Whisper samples and normalization."""
import contextlib
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from .media import ffargs, input_args


@contextlib.contextmanager
def decode_audio(source, directory):
    """FFmpeg writes float32 PCM to disk instead of a whole-file stdout buffer."""
    with tempfile.TemporaryDirectory(prefix="decode-", dir=directory) as folder:
        path = Path(folder) / "audio.f32"
        result = subprocess.run(ffargs(*input_args(source), "-map", "0:a:0", "-vn",
                                      "-ac", "1", "-ar", "16000", "-f", "f32le", path),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        if result.returncode or not path.exists() or not path.stat().st_size or path.stat().st_size % 4:
            raise ValueError("Não foi possível ler o áudio para transcrição. Confira a gravação.")
        audio = np.memmap(path, dtype="<f4", mode="r")
        try:
            yield audio
        finally:
            audio._mmap.close()


class DiskFeatures:
    """Compute long spectrograms in bounded blocks, preserving global log-Mel range.

    Keep Whisper's full timeline/VAD and decoding options. Blocks overlap by the
    FFT context; only the file edges use reflection and final zero padding.
    """
    def __init__(self, original, directory, block_frames=3000):
        self.original = original
        self.directory = Path(directory)
        self.block_frames = block_frames
        self.maps = []

    def __getattr__(self, name):
        return getattr(self.original, name)

    def __call__(self, waveform, padding=160, chunk_length=None):
        base = self.original
        if waveform.size <= self.block_frames * base.hop_length:
            return base(waveform, padding=padding, chunk_length=chunk_length)
        if chunk_length is not None:
            base.n_samples = chunk_length * base.sampling_rate
            base.nb_max_frames = base.n_samples // base.hop_length
        frames = (waveform.size + padding) // base.hop_length
        path = self.directory / f"features-{len(self.maps)}.f32"
        features = np.memmap(path, dtype="float32", mode="w+", shape=(base.mel_filters.shape[0], frames))
        self.maps.append(features)
        window = np.hanning(base.n_fft + 1)[:-1].astype("float32")
        peak = np.float32(-np.inf)
        logical_size = waveform.size + padding
        for first in range(0, frames, self.block_frames):
            last = min(first + self.block_frames, frames)
            indices = np.arange(first*base.hop_length - base.n_fft//2,
                                (last-1)*base.hop_length + base.n_fft//2)
            indices = np.where(indices < 0, -indices, indices)
            indices = np.where(indices >= logical_size, 2*(logical_size-1)-indices, indices)
            samples = np.zeros(indices.size, dtype="float32")
            present = indices < waveform.size
            samples[present] = waveform[indices[present]]
            stft = base.stft(samples, base.n_fft, base.hop_length, window=window,
                             center=False, return_complex=True).astype("complex64")
            magnitudes = np.abs(stft) ** 2
            mel = base.mel_filters @ magnitudes
            block = np.log10(np.clip(mel, a_min=1e-10, a_max=None))
            features[:, first:last] = block
            peak = np.maximum(peak, block.max())
            del indices, present, samples, stft, magnitudes, mel, block
        features.flush()
        for first in range(0, frames, self.block_frames):
            block = features[:, first:first+self.block_frames]
            np.maximum(block, peak-8.0, out=block)
            np.add(block, 4.0, out=block)
            np.divide(block, 4.0, out=block)
        features.flush()
        return features

    def close(self):
        for array in self.maps:
            array._mmap.close()
        self.maps.clear()
