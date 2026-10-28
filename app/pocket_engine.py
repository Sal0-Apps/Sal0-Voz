"""Portuguese undistilled Pocket TTS, full FP32, local clone weights only."""
from importlib.resources import files
import os
from pathlib import Path
import time

from . import storage as s
from .audio_files import checkpoint_audio
from .audio_precision import pcm24
from .engine_policy import MEMORY_GIB, MemoryUnavailable
from .engine_progress import report
from .quality_profiles import POCKET_PROFILE, seed_for
from .resources import memory_available, release_temporary_memory, TextCapacityExceeded


class PocketEngine:
    def __init__(self, request):
        if request.get("dtype", "float32") != "float32":
            raise ValueError("Pocket PT 24 camadas mantém FP32, sem quantização.")
        required = MEMORY_GIB["pocket-pt", "float32"]
        available = memory_available()/1024**3
        if available < required:
            raise MemoryUnavailable(required, available)
        import torch
        import yaml
        # Pocket's module sets one thread at import; apply the user's cap after it.
        from pocket_tts import TTSModel
        torch.backends.nnpack.set_flags(False)
        # Autoregressive generation and waveform decoding use parallel workers.
        torch.set_num_threads(max(1, int(os.getenv("SAL0_THREADS", "4"))//2))
        torch.set_num_interop_threads(1)
        root = Path(request["model_path"])
        weights = root/"languages/portuguese_24l/model.safetensors"
        tokenizer = root/"languages/portuguese_24l/tokenizer.json"
        if not weights.is_file() or not tokenizer.is_file():
            raise ValueError("Baixe os pesos completos de clonagem do Pocket TTS em Ajustes.")
        config = yaml.safe_load(files("pocket_tts").joinpath("config/portuguese_24l.yaml").read_text())
        config["weights_path"] = str(weights)
        config.pop("weights_path_without_voice_cloning", None)
        config["flow_lm"]["lookup_table"]["tokenizer_path"] = str(tokenizer)
        if (config["flow_lm"]["transformer"]["num_layers"] != 24 or
                config["flow_lm"]["dtype"] != "float32" or config["mimi"]["dtype"] != "float32"):
            raise ValueError("O ambiente Pocket não corresponde ao perfil de qualidade fixado.")
        config_path = Path(request["output"]).parent/"pocket-local.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        # Fail at the native EOS guard instead of accepting incomplete speech.
        os.environ["KPOCKET_TTS_ERROR_WITHOUT_EOS"] = "1"
        self.model = TTSModel.load_model(config=str(config_path), quantize=False, sampler_decode_steps=5).eval()
        self.model.max_decoder_frames_per_call = 1
        if not self.model.has_voice_cloning:
            raise ValueError("O Pocket foi carregado sem clonagem. Baixe os pesos autorizados no Hugging Face.")
        self.reference_key = None
        self.voice_state = None

    def generate(self, request):
        if request.get("quality_profile", POCKET_PROFILE) != POCKET_PROFILE:
            raise ValueError("Perfil Pocket desconhecido; atualize o app antes de retomar.")
        if request["language"] != "pt-BR":
            raise ValueError("Este Pocket TTS é o modelo de português. Escolha Português brasileiro.")
        import torch
        import numpy as np
        import soundfile as sf
        report("reference")
        key = s.digest(request["reference"])
        if self.reference_key != key:
            self.voice_state = None
            release_temporary_memory()
            with torch.inference_mode():
                self.voice_state = self.model.get_state_for_audio_prompt(Path(request["reference"]), truncate=False)
            self.reference_key = key
        output = Path(request["output"])
        floating = output.with_name(output.stem+".floating.wav")
        temporary = output.with_name(output.stem+".partial.wav")
        generated, last_report = 0, 0.0
        report("generating", generated_seconds=0, generated_frames=0)
        try:
            with torch.inference_mode(), torch.random.fork_rng(devices=[]), sf.SoundFile(
                    floating, "w", samplerate=24000, channels=1, format="WAV", subtype="FLOAT") as audio:
                torch.manual_seed(seed_for(request, key))
                # The app owns overload recovery. Do not silently split every 50 text tokens.
                stream = self.model.generate_audio_stream(self.voice_state, request["text"],
                                                          max_tokens=1_000_000_000, copy_state=True)
                for chunk in stream:
                    block = chunk.detach().cpu().numpy().reshape(-1)
                    if not np.isfinite(block).all():
                        raise ValueError("Pocket produziu amostras inválidas.")
                    audio.write(block)
                    generated += len(block)
                    now = time.monotonic()
                    if now-last_report >= 0.5:
                        report("generating", generated_seconds=generated/24000, generated_frames=round(generated/1920))
                        last_report = now
            report("writing")
            pcm24(floating, temporary, 24000)
            os.replace(temporary, output)
            if request.get("checkpoint"):
                checkpoint_audio(output)
        except RuntimeError as exc:
            if "maximum length without EOS" in str(exc) or "Maximum generation length" in str(exc):
                raise TextCapacityExceeded("Pocket atingiu o limite nativo antes de concluir a fala.") from exc
            raise
        finally:
            floating.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
