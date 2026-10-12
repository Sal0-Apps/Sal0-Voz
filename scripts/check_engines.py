"""Image runtime check: import packages/help only; never load model weights."""
import os
import json
import subprocess
from app.catalog import runtime, runtime_binary


def main():
    # A clone job may fail in the earlier ASR subprocess. Validate the shared
    # runner under every interpreter before checking individual backend packages.
    seen = set()
    for engine in ("whisper-large-v3-turbo", "qwen-1.7b", "chatterbox-pt-br", "omnivoice", "voxcpm2"):
        executable = runtime(engine)
        if executable in seen:
            continue
        seen.add(executable)
        result = subprocess.run([executable, "-m", "app.engine_runner", "--check-imports"],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"O ambiente {engine} não consegue iniciar o executor:\n{result.stderr}")
        assert json.loads(result.stdout) == {"ok": True, "check": "imports"}, result.stdout
        print(f"Executor imports ({engine}): PASS (no weights)")
    subprocess.run([runtime("whisper-large-v3-turbo"), "-c",
                    "import psutil; from faster_whisper import WhisperModel; "
                    "from app.asr_memory import DiskFeatures; print('Whisper CPU imports: PASS (no weights)')"], check=True)
    subprocess.run([runtime("omnivoice"), "-c",
                    "import torch; from omnivoice import OmniVoice, VoiceClonePrompt; "
                    "assert torch.version.cuda is None; print('OmniVoice CPU imports: PASS')"], check=True)
    binary = runtime_binary("voxcpm2")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(binary.parent)
    env["GGML_BACKEND_PATH"] = str(binary.parent)
    help_result = subprocess.run([str(binary), "--help"], capture_output=True, text=True, env=env, check=False)
    assert help_result.returncode in (0, 1), help_result.stderr
    assert "--cpu" in help_result.stderr and "--prompt-text" in help_result.stderr, help_result.stderr
    print("VoxCPM2 CPU/continuation CLI: PASS (no weights)")


if __name__ == "__main__":
    main()
