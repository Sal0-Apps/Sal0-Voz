"""Experimental native Drama 3: explicit Q4 profile, bounded disk expert cache."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from . import storage as s
from .audio_files import checkpoint_audio
from .audio_precision import pcm24
from .catalog import CATALOG, runtime_binary
from .engine_policy import MEMORY_GIB, MemoryUnavailable
from .engine_progress import report
from .quality_profiles import DRAMA_PROFILE, seed_for
from .resources import memory_available, is_memory_error, ProcessInterrupted, TextCapacityExceeded


class Drama3Engine:
    def __init__(self, request):
        if request.get("dtype", "q4-bf16") != "q4-bf16":
            raise ValueError("Drama 3 CPU usa o perfil experimental Q4/BF16 indicado no catálogo.")
        self.binary = runtime_binary("drama3")
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise ValueError("Atualize a imagem para instalar o motor experimental Drama 3.")
        self.weights = Path(request["model_path"])/CATALOG["drama3"]["files"][-1]
        if not self.weights.is_file():
            raise ValueError("Baixe o pacote Drama 3 CPU Q4 em Ajustes.")
        self.check_memory()

    @staticmethod
    def check_memory():
        required = MEMORY_GIB["drama3", "q4-bf16"]
        available = memory_available()/1024**3
        if available < required:
            raise MemoryUnavailable(required, available)

    def generate(self, request):
        if request.get("quality_profile", DRAMA_PROFILE) != DRAMA_PROFILE:
            raise ValueError("Perfil Drama 3 desconhecido; atualize o app antes de retomar.")
        self.check_memory()
        transcript = (request.get("reference_text") or "").strip()
        if not transcript:
            raise ValueError("Transcreva a gravação da voz antes de usar o Drama 3.")
        output = Path(request["output"])
        temporary = output.with_name(output.stem+".partial.wav")
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = str(self.binary.parent)+(":"+env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        env["GGML_BACKEND_PATH"] = str(self.binary.parent)
        threads = str(max(1, int(os.getenv("SAL0_THREADS", "4"))))
        report("loading")
        try:
            with tempfile.TemporaryDirectory(prefix="drama3-work-", dir=output.parent) as work:
                folder = Path(work)
                floating, result = folder/"floating.wav", folder/"result.json"
                sequence = folder/"request.json"
                s.atomic_json(sequence, [{"id":"voice", "text":request["text"],
                    "language":request["language"].split("-")[0], "voice_ref":str(Path(request["reference"]).resolve()),
                    "reference_text":transcript, "options":{"seed":str(seed_for(request, s.digest(request["reference"]))),
                    "max_tokens":"1024", "text_chunk_size":"1000000000", "temperature":"1.0", "top_p":"0.9", "top_k":"4097"}}])
                args = [str(self.binary), "--task", "tts", "--family", "fish_drama3", "--backend", "cpu",
                    "--mode", "offline", "--model", str(self.weights), "--threads", threads,
                    "--request-sequence", str(sequence), "--batch-merge-audio", "concat",
                    "--batch-manifest-out", str(result), "--out", str(floating), "--out-dir", str(folder/"artifacts"),
                    "--out-format", "float32", "--session-option", "fish_drama3.disk_experts=true",
                    "--session-option", "fish_drama3.pin_experts=false",
                    "--session-option", "fish_drama3.expert_cache_size=8",
                    "--session-option", "fish_drama3.disk_expert_read_threads="+threads,
                    "--session-option", "fish_drama3.cpu_expert_layers=0",
                    "--session-option", "fish_drama3.context_length=4096",
                    "--session-option", "fish_drama3.kv_cache_type=f32",
                    "--session-option", "fish_drama3.codec_encoder_chunk_samples=65536"]
                log = output.parent/"drama3-process.log"
                tail = ""
                last_report = 0.0
                with log.open("a", encoding="utf-8") as stream:
                    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               text=True, encoding="utf-8", errors="replace", env=env)
                    try:
                        for line in process.stdout:
                            stream.write(line); stream.flush()
                            tail = (tail+line)[-4000:]
                            if line.startswith("SAL0_DRAMA_FRAME="):
                                try:
                                    frames = int(line.strip().split("=", 1)[1])
                                except ValueError:
                                    continue
                                now = time.monotonic()
                                if now-last_report >= 0.5:
                                    report("generating", generated_seconds=frames*2048/44100, generated_frames=frames)
                                    last_report = now
                        code = process.wait()
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            try: process.wait(timeout=5)
                            except subprocess.TimeoutExpired: process.kill(); process.wait()
                        process.stdout.close()
                if code:
                    if code == -9 or is_memory_error(tail):
                        raise MemoryUnavailable(MEMORY_GIB["drama3", "q4-bf16"], memory_available()/1024**3)
                    if any(term in tail.lower() for term in ("capacity", "context_length", "prompt plus max_tokens")):
                        raise TextCapacityExceeded("Drama 3 ultrapassou seu contexto nativo; o trecho será reduzido.")
                    if code == -4:
                        raise ValueError("O motor Drama 3 encontrou uma instrução incompatível com esta CPU. "+tail)
                    if code < 0:
                        raise ProcessInterrupted("O motor Drama 3 foi interrompido. "+tail)
                    raise ValueError("Drama 3 não concluiu a geração. "+tail)
                try:
                    record = json.loads(result.read_text())["requests"][0]["custom_schema_output"]
                    if record["schema"] != "drama3_generation_v1":
                        raise ValueError("Resposta de outro motor")
                    limited = record["data"]["reached_limit"]
                    frames = record["data"]["frames"]
                    if not isinstance(limited, bool) or not isinstance(frames, (int, float)) or frames <= 0:
                        raise ValueError("Contagem de áudio inválida")
                except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                    raise ValueError("O motor Drama 3 não confirmou a conclusão da fala.") from exc
                if limited:
                    raise TextCapacityExceeded("Drama 3 atingiu o limite antes de concluir a fala.")
                report("writing")
                pcm24(floating, temporary, 44100)
                os.replace(temporary, output)
                if request.get("checkpoint"):
                    checkpoint_audio(output)
        finally:
            temporary.unlink(missing_ok=True)
