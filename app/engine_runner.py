"""CPU engines run in isolated processes; one clone model per active job."""
import contextlib
import json
import io
import os
import sys
import tempfile
from pathlib import Path
from .asr_memory import decode_audio, DiskFeatures
from .prompt_cache import PromptCache
from .resources import release_temporary_memory, is_memory_error
from .audio_files import checkpoint_audio

LANGUAGES = {"pt-BR": "Portuguese", "en-US": "English"}

# Set before importing any model runtime, including Gradio's optional analytics.
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["DO_NOT_TRACK"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

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
        self.prompts = PromptCache(Path(request["output"]).parent / "clone-prompts", request["engine"], self.dtype, request.get("model_revision"))

    def generate(self, request):
        import torch
        import soundfile as sf
        from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem
        transcript = (request.get("reference_text") or "").strip()
        if not transcript:
            raise ValueError("A gravação precisa ser transcrita antes da clonagem. Confira a preparação da referência.")
        with torch.inference_mode(), torch.autocast(device_type="cpu", dtype=torch.bfloat16, enabled=self.dtype == "bfloat16"):
            prompt = self.prompts.get(request["reference"], transcript,
                                     lambda: self.model.create_voice_clone_prompt(
                                         ref_audio=request["reference"], ref_text=transcript, x_vector_only_mode=False),
                                     VoiceClonePromptItem, torch)
            wavs, sr = self.model.generate_voice_clone(
                text=request["text"], language=LANGUAGES[request["language"]],
                voice_clone_prompt=prompt, non_streaming_mode=True, max_new_tokens=4096,
            )
        if not wavs or not len(wavs[0]):
            raise ValueError("O modelo não gerou áudio. Confira sua referência.")
        output = Path(request["output"])
        temporary = output.with_name(output.stem + ".partial.wav")
        sf.write(temporary, wavs[0], sr)
        os.replace(temporary, output)
        if request.get("checkpoint"):
            checkpoint_audio(output)

def transcribe(request):
    from faster_whisper import WhisperModel
    threads = max(1, int(os.getenv("SAL0_THREADS", "4")))
    root = Path(request.get("work_dir", Path(request["output"]).parent / "asr-work"))
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="whisper-", dir=root) as directory:
        with decode_audio(request["source"], directory) as audio:
            model = WhisperModel(request["model_path"], device="cpu", compute_type="int8",
                                 cpu_threads=threads, num_workers=1, local_files_only=True)
            features = DiskFeatures(model.feature_extractor, directory)
            model.feature_extractor = features
            segments = None
            try:
                segments, _ = model.transcribe(
                    audio, language=request["language"].split("-")[0],
                    beam_size=5, vad_filter=True, word_timestamps=True, condition_on_previous_text=False,
                )
                cues = [{"start_ms": round(x.start*1000), "end_ms": round(x.end*1000), "text": x.text.strip()}
                        for x in segments if x.text.strip()]
                from .storage import atomic_json
                atomic_json(request["output"], cues)
            finally:
                segments = None
                model = None
                features.close()
    release_temporary_memory()

def reply(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def error_reply(exc, request, retryable=False):
    from .engine_policy import MemoryUnavailable, MEMORY_GIB
    from .resources import memory_available
    value = {"error": str(exc)}
    memory_error = isinstance(exc, MemoryUnavailable) or is_memory_error(exc)
    if memory_error:
        value.update(kind="memory", required=getattr(exc, "required", MEMORY_GIB[(request["engine"], request.get("dtype", "float32"))]), available=getattr(exc, "available", memory_available()/1024**3))
    elif retryable and isinstance(exc, (RuntimeError, InterruptedError, TimeoutError)):
        value["kind"] = "interrupted"
    reply(value)

def main():
    try:
        from onnxruntime import disable_telemetry_events
        disable_telemetry_events()
    except ImportError:
        pass
    serving = sys.argv[1] == "--serve"
    request = json.loads(Path(sys.argv[2] if serving else sys.argv[1]).read_text(encoding="utf-8"))
    from .catalog import is_clone
    if is_clone(request["engine"]):
        try:
            with contextlib.redirect_stdout(sys.stderr):
                if request["engine"] == "chatterbox-pt-br":
                    from .chatterbox_engine import ChatterboxEngine
                    engine = ChatterboxEngine(request)
                else:
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
                release_temporary_memory()
                reply({"ok": True})
            except Exception as exc:
                import traceback
                traceback.print_exc(file=sys.stderr)
                error_reply(exc, request, retryable=True)
                return
    elif request["engine"].startswith("whisper-") and not serving:
        transcribe(request)
    else:
        raise ValueError("Motor não implementado.")

if __name__ == "__main__":
    main()
