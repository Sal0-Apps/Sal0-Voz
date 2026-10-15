"""Small, optional progress events; no model imports or changes to sampling."""
from contextlib import contextmanager
from contextvars import ContextVar
import time


_reporter = ContextVar("engine_progress", default=None)


@contextmanager
def progress_to(callback):
    token = _reporter.set(callback)
    try:
        yield
    finally:
        _reporter.reset(token)


def report(phase, **fields):
    callback = _reporter.get()
    if callback is not None:
        callback({"phase": phase, **fields})


@contextmanager
def omnivoice_progress(model):
    """Observe completed native steps, including the sampling after each forward.

    A pre-hook on the *next* forward confirms the previous full step. The last
    step is confirmed only when the iterative decoder returns successfully.
    Reference encoding and waveform decoding never enter this counter.
    """
    iterative = getattr(model, "_generate_iterative", None)
    if iterative is None or not hasattr(model, "register_forward_pre_hook"):
        yield
        return
    decode = getattr(model, "_decode_and_post_process", None)
    chunked = getattr(model, "_generate_chunked", None)
    state = {"chunk": 0, "total_chars": None, "done_chars": 0}

    def chunks(task, gen_config):
        state["total_chars"] = sum(len(text) for text in task.texts)
        return chunked(task, gen_config)

    def observe(task, gen_config):
        state["chunk"] += 1
        chars = sum(len(text) for text in task.texts)
        total_chars = state["total_chars"] or max(1, chars)
        total = gen_config.num_step
        calls = 0
        started = None

        def emit(completed):
            elapsed = time.monotonic() - started if started is not None else 0
            report("sampling", completed=completed, total=total, unit="steps",
                   chunk=state["chunk"], elapsed_seconds=elapsed,
                   fraction=min(1, (state["done_chars"] + chars*completed/total)/total_chars))

        def before_forward(_module, _args):
            nonlocal calls, started
            if started is None:
                started = time.monotonic()
            if calls:
                emit(calls)
            calls += 1

        emit(0)
        handle = model.register_forward_pre_hook(before_forward)
        try:
            result = iterative(task, gen_config)
            if calls == total:
                emit(total)
            state["done_chars"] += chars
            return result
        finally:
            handle.remove()

    def decoding(*args, **kwargs):
        report("decoding")
        return decode(*args, **kwargs)

    model._generate_iterative = observe
    if chunked is not None:
        model._generate_chunked = chunks
    if decode is not None:
        model._decode_and_post_process = decoding
    try:
        yield
    finally:
        model._generate_iterative = iterative
        if chunked is not None:
            model._generate_chunked = chunked
        if decode is not None:
            model._decode_and_post_process = decode
