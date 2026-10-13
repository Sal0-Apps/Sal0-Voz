"""Full F16 VoxCPM2 through the pinned CPU GGML engine; weights live on disk."""
import os
import errno
import subprocess
from pathlib import Path

from .audio_files import checkpoint_audio
from .catalog import runtime_binary
from .engine_policy import MEMORY_GIB, MemoryUnavailable
from .resources import memory_available, TextCapacityExceeded
from .voice_styles import instruction


class VoxCPMEngine:
    def __init__(self, request):
        if request.get("dtype", "float16") != "float16":
            raise ValueError("VoxCPM2 usa os pesos F16 completos no motor de CPU.")
        self.binary = runtime_binary("voxcpm2")
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise ValueError("Atualize a imagem para instalar o motor de CPU do VoxCPM2.")
        self.folder = Path(request["model_path"])
        self.weights = [self.folder / "VoxCPM2-BaseLM-F16.gguf", self.folder / "VoxCPM2-Acoustic-F16.gguf"]
        if not all(path.is_file() for path in self.weights):
            raise ValueError("Preparação do VoxCPM2 incompleta. Retome o download em Ajustes.")
        self.check_memory()

    @staticmethod
    def check_memory():
        required = MEMORY_GIB["voxcpm2", "float16"]
        available = memory_available() / 1024**3
        if available < required:
            raise MemoryUnavailable(required, available)

    def generate(self, request):
        self.check_memory()
        transcript = (request.get("reference_text") or "").strip()
        style = instruction(request.get("voice_style", "natural"))
        continuation = not style and not request.get("reaction")
        if continuation and not transcript:
            raise ValueError("A gravação precisa ser transcrita antes da clonagem. Retome a preparação da referência.")
        text = ("(" + style + ")" if style else "") + request["text"]
        output = Path(request["output"])
        temporary = output.with_name(output.stem + ".partial.wav")
        temporary.unlink(missing_ok=True)
        log = output.parent / "voxcpm-process.log"
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = str(self.binary.parent) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        env["GGML_BACKEND_PATH"] = str(self.binary.parent)
        args = [str(self.binary), "--cpu", "--text", text, "--reference", request["reference"],
                # Style control must start at the reference-only input. In
                # continuation, the instruction follows spoken reference text
                # and the model can read it aloud. Natural speech keeps its
                # original continuation; reactions use the isolated speaker.
                *(["--prompt-wav", request["reference"], "--prompt-text", transcript] if continuation else []),
                "--timesteps", "10", "--cfg", "2.0", "--steps", "1024",
                "--output", str(temporary), *(str(path) for path in self.weights)]
        try:
            with log.open("ab") as stream:
                log_start = log.stat().st_size
                result = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, env=env, check=False)
            if result.returncode or not temporary.is_file() or temporary.stat().st_size <= 44:
                with log.open("rb") as stream:
                    stream.seek(max(log_start, log.stat().st_size - 4000))
                    detail = stream.read().decode("utf-8", errors="replace")
                if "SAL0_TEXT_CAPACITY" in detail:
                    raise TextCapacityExceeded("O VoxCPM2 atingiu o limite nativo antes de terminar a fala.")
                if result.returncode == -9:
                    raise MemoryUnavailable(MEMORY_GIB["voxcpm2", "float16"], memory_available()/1024**3)
                if result.returncode == -4:
                    raise ValueError("O motor encontrou uma instrução incompatível com a CPU. " + detail)
                raise RuntimeError("O VoxCPM2 interrompeu a geração do trecho. " + detail)
            os.replace(temporary, output)
            if request.get("checkpoint"):
                checkpoint_audio(output)
        except OSError as exc:
            if exc.errno == errno.E2BIG:
                raise TextCapacityExceeded("O texto ultrapassa o limite de envio ao motor nativo. Será usado um bloco menor.") from exc
            raise
        finally:
            temporary.unlink(missing_ok=True)
