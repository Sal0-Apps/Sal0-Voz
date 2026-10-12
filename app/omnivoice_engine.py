"""Native OmniVoice cloning, full FP32/32 steps, one cached reference in RAM."""
import hashlib
import json
import os
import pickle
from pathlib import Path

from . import storage as s
from .audio_files import checkpoint_audio
from .catalog import CATALOG
from .engine_policy import MEMORY_GIB, MemoryUnavailable
from .resources import memory_available, release_temporary_memory, is_memory_error


class OmniVoiceEngine:
    def __init__(self, request):
        if request.get("dtype", "float32") != "float32":
            raise ValueError("OmniVoice usa float32 em CPU e 32 passos completos.")
        self.check_memory()
        import torch
        from omnivoice import OmniVoice
        torch.backends.nnpack.set_flags(False)
        torch.set_num_threads(max(1, int(os.getenv("SAL0_THREADS", "4"))))
        torch.set_num_interop_threads(1)
        folder = Path(request["model_path"])
        if not all((folder / name).is_file() for name in CATALOG["omnivoice"]["files"]):
            raise ValueError("Preparação do OmniVoice incompleta. Retome o download em Ajustes.")
        self.model = OmniVoice.from_pretrained(
            str(folder), device_map="cpu", dtype=torch.float32, attn_implementation="sdpa",
            local_files_only=True, low_cpu_mem_usage=True, load_asr=False,
        ).eval()
        self.cache = Path(request["output"]).parent / "omnivoice-prompts"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.revision = request.get("model_revision")
        self.current_key, self.prompt = None, None

    @staticmethod
    def check_memory():
        required = MEMORY_GIB["omnivoice", "float32"]
        available = memory_available() / 1024**3
        if available < required:
            raise MemoryUnavailable(required, available)

    def reference_prompt(self, reference, transcript):
        from omnivoice import VoiceClonePrompt
        key = hashlib.sha256(json.dumps([s.digest(Path(reference)), transcript, self.revision,
                                        "omnivoice-fp32-1"], ensure_ascii=False).encode()).hexdigest()
        if key == self.current_key:
            return self.prompt
        self.prompt, self.current_key = None, None
        release_temporary_memory()
        path, meta = self.cache / (key + ".pt"), self.cache / (key + ".json")
        try:
            if s.digest(path) != json.loads(meta.read_text())["sha256"]:
                raise ValueError("Cache incompleto")
            prompt = VoiceClonePrompt.load(str(path), map_location="cpu")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, EOFError, pickle.UnpicklingError) as exc:
            if is_memory_error(exc):
                raise
            prompt = self.model.create_voice_clone_prompt(ref_audio=reference, ref_text=transcript)
            temporary = path.with_suffix(".partial.pt")
            try:
                prompt.save(str(temporary))
                with temporary.open("rb") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                s.atomic_json(meta, {"sha256": s.digest(path)})
            finally:
                temporary.unlink(missing_ok=True)
        self.current_key, self.prompt = key, prompt
        return prompt

    def generate(self, request):
        import torch
        import soundfile as sf
        transcript = (request.get("reference_text") or "").strip()
        if not transcript:
            raise ValueError("A gravação precisa ser transcrita antes da clonagem. Retome a preparação da referência.")
        language = {"pt-BR": "pt", "en-US": "en"}.get(request["language"])
        if language is None:
            raise ValueError("Idioma de clonagem não disponível.")
        with torch.inference_mode():
            prompt = self.reference_prompt(request["reference"], transcript)
            wavs = self.model.generate(text=request["text"], language=language,
                                       voice_clone_prompt=prompt, num_step=32,
                                       normalize_text=False, preprocess_prompt=True)
        if not wavs or not len(wavs[0]):
            raise ValueError("O modelo não gerou áudio. Confira sua referência.")
        output = Path(request["output"])
        temporary = output.with_name(output.stem + ".partial.wav")
        sf.write(temporary, wavs[0], self.model.sampling_rate)
        os.replace(temporary, output)
        if request.get("checkpoint"):
            checkpoint_audio(output)
