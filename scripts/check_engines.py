"""Image runtime check: import packages/help only; never load model weights."""
import os
import subprocess
from app.catalog import runtime, runtime_binary


def main():
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
