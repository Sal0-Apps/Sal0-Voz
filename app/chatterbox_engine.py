"""Pinned Brazilian Portuguese Chatterbox V3; CPU only, one reference in RAM."""
import hashlib
import json
import os
import pickle
from pathlib import Path

from .audio_files import checkpoint_audio
from . import storage as s
from .resources import memory_available, release_temporary_memory, is_memory_error
from .engine_policy import MEMORY_GIB, MemoryUnavailable


def load_model(folder, torch):
    # The official pt-BR model includes the V3 decoder. Do not silently load
    # the generic multilingual/English checkpoint or the older S3 decoder.
    from safetensors.torch import load_file
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.t3_config import T3Config
    from chatterbox.models.s3gen import S3Gen
    from chatterbox.models.tokenizers import MTLTokenizer
    from chatterbox.models.voice_encoder import VoiceEncoder
    from tokenizers import Tokenizer

    class PortugueseTokenizer(MTLTokenizer):
        def __init__(self, path):
            # Keep upstream Portuguese encoding unchanged, without loading
            # Chinese segmentation or looking for an unrelated HF dictionary.
            self.tokenizer = Tokenizer.from_file(str(path))
            self.cangjie_converter = None
            self.check_vocabset_sot_eot()

    def weights(model, name):
        # assign avoids copying a full second state dictionary into parameters.
        # safetensors uses CPU mappings; weights are never converted to FP16.
        state = load_file(str(folder / name), device="cpu")
        # These deterministic mel/window buffers are omitted by the official
        # V3 safetensors export. Preserve the upstream constructor's values;
        # all learned weights must still pass strict loading.
        for key in getattr(model, "ignore_state_dict_missing", ()):
            if key not in state:
                state[key] = model.get_buffer(key)
        model.load_state_dict(state, strict=True, assign=True)
        del state
        release_temporary_memory()
        return model.to("cpu").eval()

    ve = weights(VoiceEncoder(), "ve.safetensors")
    t3 = weights(T3(T3Config.multilingual()), "t3_pt_br.safetensors")
    s3gen = weights(S3Gen(), "s3gen_v3.safetensors")
    tokenizer = PortugueseTokenizer(folder / "grapheme_mtl_merged_expanded_v1.json")
    return ChatterboxMultilingualTTS(t3, s3gen, ve, tokenizer, "cpu", conds=None)


class ChatterboxEngine:
    def __init__(self, request):
        if request.get("dtype", "float32") != "float32":
            raise ValueError("Chatterbox pt-BR usa float32 em CPU.")
        required = MEMORY_GIB["chatterbox-pt-br", "float32"]
        available = memory_available() / 1024**3
        if available < required:
            raise MemoryUnavailable(required, available)
        import torch
        torch.backends.nnpack.set_flags(False)
        torch.set_num_threads(max(1, int(os.getenv("SAL0_THREADS", "4"))))
        torch.set_num_interop_threads(1)
        self.model = load_model(Path(request["model_path"]), torch)
        self.cache = Path(request["output"]).parent / "chatterbox-prompts"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.revision = request.get("model_revision")
        self.current_reference = None

    def prepare_reference(self, reference, expression):
        from chatterbox.mtl_tts import Conditionals
        key = hashlib.sha256(json.dumps([s.digest(Path(reference)), self.revision,
                                       "chatterbox-pt-br-v3-1"]).encode()).hexdigest()
        if self.current_reference == key:
            return
        self.current_reference = None
        self.model.conds = None
        release_temporary_memory()
        path, meta = self.cache / (key + ".pt"), self.cache / (key + ".json")
        try:
            saved = json.loads(meta.read_text())
            if s.digest(path) != saved["sha256"]:
                raise ValueError("Cache incompleto")
            self.model.conds = Conditionals.load(path, map_location="cpu")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, EOFError, pickle.UnpicklingError) as exc:
            if is_memory_error(exc):
                raise
            self.model.prepare_conditionals(reference, exaggeration=expression)
            temporary = path.with_suffix(".partial.pt")
            try:
                self.model.conds.save(temporary)
                with temporary.open("rb") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                s.atomic_json(meta, {"sha256": s.digest(path)})
            finally:
                temporary.unlink(missing_ok=True)
        self.current_reference = key

    def generate(self, request):
        if request["language"] != "pt-BR":
            raise ValueError("Escolha Português brasileiro para usar o Chatterbox pt-BR.")
        expression = float(request.get("expressiveness", 0.7))
        if not 0.25 <= expression <= 1.2:
            raise ValueError("Expressividade: escolha um valor entre 0,25 e 1,20.")
        import torch
        import soundfile as sf
        with torch.inference_mode():
            self.prepare_reference(request["reference"], expression)
            wav = self.model.generate(request["text"], language_id="pt", audio_prompt_path=None,
                                      exaggeration=expression, cfg_weight=0.3,
                                      temperature=0.8, repetition_penalty=1.2, min_p=0.05, top_p=1.0)
        audio = wav.squeeze(0).detach().cpu().numpy()
        if not len(audio):
            raise ValueError("O modelo não gerou áudio. Confira sua referência.")
        output = Path(request["output"])
        temporary = output.with_name(output.stem + ".partial.wav")
        sf.write(temporary, audio, self.model.sr)
        os.replace(temporary, output)
        if request.get("checkpoint"):
            checkpoint_audio(output)
