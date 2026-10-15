"""Native FP32 OmniVoice; versioned quality and one cached reference in RAM."""
from contextlib import nullcontext
import hashlib
import json
import os
import pickle
from pathlib import Path

from . import storage as s
from .audio_files import checkpoint_audio
from .catalog import CATALOG
from .engine_policy import MEMORY_GIB, MemoryUnavailable
from .generation_limits import omnivoice_capacity
from .engine_progress import report, omnivoice_progress
from .omnivoice_quality import LEGACY_PROFILE, MAXIMUM_PROFILE, generation_options
from .resources import memory_available, release_temporary_memory, is_memory_error


class OmniVoiceEngine:
    def __init__(self, request):
        if request.get("dtype", "float32") != "float32":
            raise ValueError("OmniVoice usa float32 completo em CPU.")
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

    def reference_prompt(self, reference, transcript, preprocess=True):
        from omnivoice import VoiceClonePrompt
        key = hashlib.sha256(json.dumps([s.digest(Path(reference)), transcript, self.revision,
                                        "omnivoice-fp32-1" if preprocess else "omnivoice-fp32-unaltered-1"], ensure_ascii=False).encode()).hexdigest()
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
            options = {} if preprocess else {"preprocess_prompt": False}
            prompt = self.model.create_voice_clone_prompt(ref_audio=reference, ref_text=transcript, **options)
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
        profile = request.get("omnivoice_profile", LEGACY_PROFILE)
        options = generation_options(profile)
        maximum = profile == MAXIMUM_PROFILE
        report("reference")
        with torch.inference_mode():
            prompt = self.reference_prompt(request["reference"], transcript, options["preprocess_prompt"])
        # A retry of the same unfinished part keeps its random seed even after
        # reloading the model. A newly submitted job receives a different seed.
        seed = request.get("omnivoice_seed")
        random_state = torch.random.fork_rng(devices=[]) if maximum and seed is not None else nullcontext()
        report("generating")
        with torch.inference_mode(), random_state, omnivoice_capacity(self.model) if maximum else nullcontext(), omnivoice_progress(self.model):
            if maximum and seed is not None:
                material = json.dumps([seed, self.current_key, request["text"], language], ensure_ascii=False)
                torch.manual_seed(int(hashlib.sha256(material.encode()).hexdigest()[:15], 16))
            wavs = self.model.generate(text=request["text"], language=language,
                                       voice_clone_prompt=prompt, **options)
        if not wavs or not len(wavs[0]):
            raise ValueError("O modelo não gerou áudio. Confira sua referência.")
        output = Path(request["output"])
        temporary = output.with_name(output.stem + ".partial.wav")
        report("writing")
        audio = wavs[0]
        if maximum:
            import numpy as np
            peak = 0.0
            for offset in range(0, len(audio), self.model.sampling_rate):
                block = audio[offset:offset+self.model.sampling_rate]
                if not np.isfinite(block).all():
                    raise ValueError("OmniVoice produziu amostras inválidas; nenhum áudio foi confirmado.")
                peak = max(peak, float(np.max(np.abs(block))))
            if peak >= 1.0:
                audio *= 0.999 / peak  # Avoid integer clipping without a compressor.
            sf.write(temporary, audio, self.model.sampling_rate, subtype="PCM_24")
        else:
            sf.write(temporary, audio, self.model.sampling_rate)
        os.replace(temporary, output)
        if request.get("checkpoint"):
            checkpoint_audio(output)
