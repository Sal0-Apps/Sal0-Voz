"""Observe Chatterbox's native limits without changing sampling or model quality."""
from contextlib import contextmanager
from .resources import TextCapacityExceeded


@contextmanager
def qwen_capacity(talker):
    original = talker.generate

    def checked(*args, **kwargs):
        result = original(*args, **kwargs)
        maximum, eos = kwargs.get("max_new_tokens"), kwargs.get("eos_token_id")
        if maximum and result.sequences.shape[-1] >= maximum:
            endings = eos if isinstance(eos, (list, tuple)) else [eos]
            if result.sequences[0, -1].item() not in endings:
                raise TextCapacityExceeded("O Qwen atingiu o limite nativo antes de terminar a fala.")
        return result

    talker.generate = checked
    try:
        yield
    finally:
        talker.generate = original


@contextmanager
def chatterbox_capacity(model):
    t3 = getattr(model, "t3", None)
    if t3 is None:
        yield
        return
    original = t3.inference

    def checked(*args, **kwargs):
        # Inspect the backend's normalized, padded tokens rather than estimating
        # capacity from characters. The position table includes two delimiters.
        tokens = kwargs.get("text_tokens")
        if tokens is not None and t3.hp.input_pos_emb == "learned" and tokens.shape[-1] > t3.hp.max_text_tokens+2:
            raise TextCapacityExceeded("O texto ultrapassa o contexto nativo do Chatterbox.")
        result = original(*args, **kwargs)
        maximum = kwargs.get("max_new_tokens")
        if maximum and result.shape[-1] >= maximum and result[0, -1].item() != t3.hp.stop_speech_token:
            # Do not decode, checkpoint, or present a capped utterance as complete.
            raise TextCapacityExceeded("O Chatterbox atingiu o limite nativo antes de terminar a fala.")
        return result

    t3.inference = checked
    try:
        yield
    finally:
        t3.inference = original
