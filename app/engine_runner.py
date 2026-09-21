"""Isolated process: heavyweight imports never enter the API process."""
import json
import os
import sys
from pathlib import Path

def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    threads = int(os.getenv("SAL0_THREADS", "2"))
    engine = request["engine"]
    if engine.startswith("qwen-"):
        import torch
        import soundfile as sf
        from qwen_tts import Qwen3TTSModel
        torch.set_num_threads(threads)
        model = Qwen3TTSModel.from_pretrained(request["model_path"], device_map="cpu", dtype=torch.float32, attn_implementation="eager", local_files_only=True)
        wavs, sr = model.generate_voice_clone(
            text=request["text"], language={"pt-BR": "Portuguese", "en-US": "English"}[request["language"]],
            ref_audio=request["reference"], ref_text=request["reference_text"],
            x_vector_only_mode=False, max_new_tokens=4096,
        )
        sf.write(request["output"], wavs[0], sr)
    elif engine.startswith("whisper-"):
        from faster_whisper import WhisperModel
        model = WhisperModel(request["model_path"], device="cpu", compute_type="int8", cpu_threads=threads, num_workers=1, local_files_only=True)
        segments, info = model.transcribe(request["source"], language=request["language"].split("-")[0], beam_size=5, vad_filter=True, word_timestamps=True)
        cues = [{"start_ms": round(x.start*1000), "end_ms": round(x.end*1000), "text": x.text.strip()} for x in segments if x.text.strip()]
        Path(request["output"]).write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
    else:
        raise ValueError("Motor não implementado.")

if __name__ == "__main__":
    main()

