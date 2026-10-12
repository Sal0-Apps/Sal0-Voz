"""CPU engines run in isolated processes; a clone job loads Qwen only once."""
import contextlib
import json
import io
import os
import subprocess
import sys
from pathlib import Path

LANGUAGES = {"pt-BR": "Portuguese", "en-US": "English"}

# Set before importing any model runtime, including Gradio's optional analytics.
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

def decode_audio(source):
    """Use our FFmpeg decoder instead of depending on PyAV's changing API."""
    import numpy as np
    from .media import ffargs, input_args
    result = subprocess.run(ffargs(*input_args(source),
                                  "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                                  "-f", "f32le", "pipe:1"),
                            capture_output=True, timeout=300)
    if result.returncode or not result.stdout:
        raise ValueError("Não foi possível ler o áudio para transcrição. Confira a gravação.")
    return np.frombuffer(result.stdout, dtype="<f4")

class QwenEngine:
    def __init__(self, request):
        from .engine_policy import MEMORY_GIB, MemoryUnavailable
        from .resources import memory_available
        self.dtype = request.get("dtype", "float32")
        needed = MEMORY_GIB.get((request["engine"], self.dtype))
        if needed is None:
            raise ValueError("Perfil de voz incompatível com CPU.")
        available = memory_available() / 1024**3
        if available < needed:
            raise MemoryUnavailable(needed, available)
        import torch
        startup = io.StringIO()
        with contextlib.redirect_stdout(startup):
            from qwen_tts import Qwen3TTSModel
        for line in startup.getvalue().splitlines():
            if line.strip() and line.strip() != "********" and "flash-attn is not installed" not in line:
                print(line, file=sys.stderr)
        torch.backends.nnpack.set_flags(False)
        torch.set_num_threads(max(1, int(os.getenv("SAL0_THREADS", "4"))))
        torch.set_num_interop_threads(1)
        self.model = Qwen3TTSModel.from_pretrained(
            request["model_path"], device_map="cpu", dtype=getattr(torch, self.dtype),
            attn_implementation="eager", local_files_only=True, low_cpu_mem_usage=True,
        )
        self.model.model.talker.generation_config.pad_token_id = self.model.model.config.talker_config.codec_eos_token_id
        print(f"CPU · atenção PyTorch eager · {self.dtype} · sem CUDA", file=sys.stderr)
        self.prompts = {}

    def generate(self, request):
        import torch
        import soundfile as sf
        transcript = (request.get("reference_text") or "").strip()
        if not transcript:
            raise ValueError("A gravação precisa ser transcrita antes da clonagem. Confira a preparação da referência.")
        key = (request["reference"], transcript)
        with torch.inference_mode(), torch.autocast(device_type="cpu", dtype=torch.bfloat16, enabled=self.dtype == "bfloat16"):
            if key not in self.prompts:
                self.prompts[key] = self.model.create_voice_clone_prompt(
                    ref_audio=request["reference"], ref_text=transcript, x_vector_only_mode=False,
                )
            wavs, sr = self.model.generate_voice_clone(
                text=request["text"], language=LANGUAGES[request["language"]],
                voice_clone_prompt=self.prompts[key], non_streaming_mode=True, max_new_tokens=4096,
            )
        if not wavs or not len(wavs[0]):
            raise ValueError("O modelo não gerou áudio. Confira sua referência.")
        sf.write(request["output"], wavs[0], sr)

def transcribe(request):
    from faster_whisper import WhisperModel
    threads = max(1, int(os.getenv("SAL0_THREADS", "4")))
    model = WhisperModel(request["model_path"], device="cpu", compute_type="int8",
                         cpu_threads=threads, num_workers=1, local_files_only=True)
    segments, _ = model.transcribe(
        decode_audio(request["source"]), language=request["language"].split("-")[0],
        beam_size=5, vad_filter=True, word_timestamps=True, condition_on_previous_text=False,
    )
    cues = [{"start_ms": round(x.start*1000), "end_ms": round(x.end*1000), "text": x.text.strip()}
            for x in segments if x.text.strip()]
    Path(request["output"]).write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")

def reply(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def error_reply(exc, request):
    from .engine_policy import MemoryUnavailable, MEMORY_GIB
    from .resources import memory_available
    value = {"error": str(exc)}
    memory_error = isinstance(exc, (MemoryError, MemoryUnavailable)) or any(
        term in str(exc).lower() for term in ("defaultcpuallocator", "not enough memory", "out of memory", "std::bad_alloc")
    )
    if memory_error:
        value.update(kind="memory", required=getattr(exc, "required", MEMORY_GIB[(request["engine"], request.get("dtype", "float32"))]), available=getattr(exc, "available", memory_available()/1024**3))
    reply(value)

def main():
    from onnxruntime import disable_telemetry_events
    disable_telemetry_events()
    serving = sys.argv[1] == "--serve"
    request = json.loads(Path(sys.argv[2] if serving else sys.argv[1]).read_text(encoding="utf-8"))
    if request["engine"].startswith("qwen-"):
        try:
            with contextlib.redirect_stdout(sys.stderr):
                engine = QwenEngine(request)
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            if not serving:
                raise
            error_reply(exc, request)
            return
        if not serving:
            engine.generate(request)
            return
        reply({"ready": True})
        for line in sys.stdin:
            try:
                item = json.loads(line)
                with contextlib.redirect_stdout(sys.stderr):
                    engine.generate(item)
                reply({"ok": True})
            except Exception as exc:
                import traceback
                traceback.print_exc(file=sys.stderr)
                error_reply(exc, request)
                return
    elif request["engine"].startswith("whisper-") and not serving:
        transcribe(request)
    else:
        raise ValueError("Motor não implementado.")

if __name__ == "__main__":
    main()
