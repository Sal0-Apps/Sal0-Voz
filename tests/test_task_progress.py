"""Native progress observation and IPC, with substitutes; no neural weights."""
import io
import json
import queue
import sys
from types import SimpleNamespace

import pytest

from app import storage as s
from app.engine_progress import omnivoice_progress, progress_to, report
from app.engine_session import EngineSession
from app.worker import Worker


@pytest.mark.parametrize("fail", [False, True])
def test_steps_confirm_sampling_not_just_forward_and_restore_after_failure(monkeypatch, fail):
    import app.engine_progress as module
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    class Model:
        def __init__(self): self.hooks = []; self.sampled = 0
        def register_forward_pre_hook(self, callback):
            self.hooks.append(callback)
            return SimpleNamespace(remove=lambda: self.hooks.remove(callback))
        def forward(self):
            for callback in self.hooks: callback(self, ())
            clock[0] += 4
        def _generate_iterative(self, task, config):
            clock[0] += 100  # Input preparation must not distort the step ETA.
            for index in range(config.num_step):
                self.forward()
                if fail and index == 1: raise RuntimeError("sampling failed")
                clock[0] += 1
                self.sampled += 1
            return ["same tokens"]
        def _decode_and_post_process(self, tokens):
            self.forward()  # Outside iterative decoding: never count this.
            return tokens
    model = Model()
    original, decoder = model._generate_iterative, model._decode_and_post_process
    events, observations = [], []
    def collect(event):
        events.append(event)
        if event["phase"] == "sampling": observations.append((event["completed"], model.sampled))
    with progress_to(collect), omnivoice_progress(model):
        model.forward()  # Reference encoding is not a generation step either.
        if fail:
            with pytest.raises(RuntimeError, match="sampling failed"):
                model._generate_iterative(SimpleNamespace(texts=["Fala inteira"]), SimpleNamespace(num_step=4))
        else:
            tokens = model._generate_iterative(SimpleNamespace(texts=["Fala inteira"]), SimpleNamespace(num_step=4))
            assert model._decode_and_post_process(tokens) == ["same tokens"]
    assert observations == [(i, i) for i in range(2 if fail else 5)]
    assert not model.hooks and model._generate_iterative == original and model._decode_and_post_process == decoder
    if not fail:
        steps = [event for event in events if event["phase"] == "sampling"]
        assert [event["elapsed_seconds"] for event in steps] == [0, 5, 10, 15, 20]
        assert [event["fraction"] for event in steps] == [0, .25, .5, .75, 1]
        assert events[-1]["phase"] == "decoding"
    before = len(events)
    report("writing")  # The reporter is scoped, too.
    assert len(events) == before


def test_backend_chunks_keep_accumulated_fraction_and_individual_step_counts():
    class Model:
        def register_forward_pre_hook(self, callback):
            self.callback = callback
            return SimpleNamespace(remove=lambda: setattr(self, "callback", None))
        def _generate_iterative(self, task, config):
            for _ in range(config.num_step): self.callback(self, ())
            return task.texts
        def _generate_chunked(self, task, config):
            return [self._generate_iterative(SimpleNamespace(texts=[text]), config) for text in ("abc", "abcdef")]
    model = Model(); events = []
    with progress_to(events.append), omnivoice_progress(model):
        result = model._generate_chunked(SimpleNamespace(texts=["abcdefghi"]), SimpleNamespace(num_step=2))
    assert result == [["abc"], ["abcdef"]]
    assert [e["completed"] for e in events] == [0, 1, 2, 0, 1, 2]
    assert [e["chunk"] for e in events] == [1, 1, 1, 2, 2, 2]
    assert [e["fraction"] for e in events] == pytest.approx([0, 1/6, 1/3, 1/3, 2/3, 1])


def test_progress_messages_never_acknowledge_a_request_or_end_a_wait():
    events = []
    session = EngineSession.__new__(EngineSession)
    session.profile = ("omnivoice", "float32")
    session.worker = SimpleNamespace(check=lambda _: None, engine_progress=lambda ident, event: events.append(event))
    session.ident = "test"; session.responses = queue.Queue()
    for value in [{"event": "progress", "phase": "loading"}, [], {"log": "ignored"}, {"ready": True},
                  {"event": "progress", "phase": "sampling", "completed": 2, "total": 64}, {"ok": True}]:
        session.responses.put(json.dumps(value))
    assert session.wait() == {"ready": True}
    assert len(events) == 1
    assert session.wait() == {"ok": True}
    assert len(events) == 2 and events[-1]["completed"] == 2


def test_runner_keeps_control_events_out_of_backend_logs(tmp_path, monkeypatch, capsys):
    import app.engine_runner as runner
    class Engine:
        def __init__(self, request): print("model loading log")
        def generate(self, request):
            print("backend generation log")
            report("sampling", completed=1, total=64, unit="steps")
    monkeypatch.setitem(sys.modules, "app.omnivoice_engine", SimpleNamespace(OmniVoiceEngine=Engine))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(disable_telemetry_events=lambda: None))
    monkeypatch.setattr(runner, "release_temporary_memory", lambda: None)
    request = tmp_path/"request.json"; request.write_text(json.dumps({"engine": "omnivoice"}))
    monkeypatch.setattr(sys, "argv", ["engine_runner", "--serve", str(request)])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"engine":"omnivoice"}\n'))
    runner.main()
    output = capsys.readouterr()
    messages = [json.loads(line) for line in output.out.splitlines()]
    assert messages == [{"event": "progress", "phase": "loading"}, {"ready": True},
                        {"event": "progress", "phase": "sampling", "completed": 1, "total": 64, "unit": "steps"}, {"ok": True}]
    assert "model loading log" in output.err and "backend generation log" in output.err


def test_worker_exposes_measured_eta_and_never_finishes_on_last_step(data):
    job = s.put("job", {"status": "running", "snapshot": {}, "progress": 0})
    worker = Worker(); ident = job["id"]
    worker.begin_progress(ident, 20, 40, "Trecho 2 de 3 · parte 1 de 2")
    worker.engine_progress(ident, {"phase": "sampling", "completed": 1, "total": 64, "unit": "steps", "elapsed_seconds": 150})
    assert "eta_seconds" not in s.get("job", ident)["progress_detail"]
    worker.engine_progress(ident, {"phase": "sampling", "completed": 24, "total": 64, "unit": "steps", "elapsed_seconds": 3600})
    current = s.get("job", ident)
    assert current["progress"] == 34.1 and "passo 25 de 64" in current["stage"]
    assert current["progress_detail"]["eta_seconds"] == 6000
    worker.engine_progress(ident, {"phase": "sampling", "completed": 64, "total": 64, "unit": "steps", "elapsed_seconds": 9600})
    current = s.get("job", ident)
    assert current["status"] == "running" and current["progress"] < 60
    assert "eta_seconds" not in current["progress_detail"]
    worker.engine_progress(ident, {"phase": "decoding"})
    assert s.get("job", ident)["progress_detail"]["phase"] == "decoding"
    worker.update(ident, status="paused", stage="Pausado")
    worker.engine_progress(ident, {"phase": "writing"})
    assert s.get("job", ident)["stage"] == "Pausado" and s.get("job", ident)["progress_detail"] is None


def test_fast_one_shot_reports_progress_before_process_exit_is_consumed(data):
    job = s.put("job", {"status": "running", "snapshot": {"mode": "asr"}, "progress": 0})
    folder = data/"jobs"/job["id"]; folder.mkdir()
    path = folder/"progress.json"
    worker = Worker(); worker.begin_progress(job["id"], 0, 95, "Transcrição")
    event = {"phase": "transcribing", "completed": 10, "total": 20, "unit": "seconds"}
    worker.run(job["id"], [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])", str(path), json.dumps(event)], progress_file=path)
    saved = s.get("job", job["id"])
    assert saved["progress"] == 46.6 and saved["progress_detail"]["completed"] == 10
