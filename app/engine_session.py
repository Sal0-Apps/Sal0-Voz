"""One cancellable clone process per job, with bounded line-based responses."""
import json
import os
import queue
import subprocess
import threading
from . import storage as s
from .catalog import runtime
from .engine_policy import MemoryUnavailable, MEMORY_GIB
from .resources import oom_kills, memory_available, ProcessInterrupted, stop_process_tree, TextCapacityExceeded

class EngineSession:
    def __init__(self, worker, ident, request, folder):
        self.worker, self.ident = worker, ident
        self.log = folder / "process.log"
        self.output = self.log.open("ab")
        self.process = None
        self.responses = queue.Queue()
        self.profile = (request["engine"], request.get("dtype", "float32"))
        self.oom_before = oom_kills()
        path = folder / "engine-session.json"
        s.atomic_json(path, request)
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", GRADIO_ANALYTICS_ENABLED="False", DO_NOT_TRACK="1")
        try:
            self.process = subprocess.Popen(
                [runtime(request["engine"]), "-m", "app.engine_runner", "--serve", str(path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.output,
                text=True, encoding="utf-8", env=env, bufsize=1, start_new_session=os.name == "posix",
            )
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.worker.engine_progress(ident, {"phase": "loading"})
            if not self.wait().get("ready"):
                raise ValueError("O modelo não ficou pronto.")
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                self.responses.put(line)
        finally:
            self.responses.put(None)

    def wait(self):
        while True:
            self.worker.check(self.ident)
            try:
                line = self.responses.get(timeout=0.4)
            except queue.Empty:
                continue
            if line is None:
                try:
                    code = self.process.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    raise ProcessInterrupted("O motor encerrou a comunicação antes de concluir. O trabalho será retomado.") from exc
                if oom_kills() > self.oom_before or code == -9:
                    raise MemoryUnavailable(MEMORY_GIB[self.profile], memory_available()/1024**3)
                with self.log.open("rb") as stream:
                    stream.seek(max(0, self.log.stat().st_size - 2000))
                    detail = stream.read().decode("utf-8", errors="replace").strip()
                if code == -4:
                    raise ValueError("O motor encontrou uma instrução incompatível com esta CPU. " + detail)
                raise ProcessInterrupted("O modelo de voz foi interrompido. " + detail)
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if not isinstance(value, dict):
                continue
            if value.get("event") == "progress":
                self.worker.engine_progress(self.ident, value)
                continue
            if value.get("error"):
                if value.get("kind") == "memory":
                    raise MemoryUnavailable(value["required"], value["available"])
                if value.get("kind") == "interrupted":
                    raise ProcessInterrupted(value["error"])
                if value.get("kind") == "text_capacity":
                    raise TextCapacityExceeded(value["error"])
                raise ValueError(value["error"])
            if value.get("ready") or value.get("ok"):
                return value

    def generate(self, request):
        self.worker.check(self.ident)
        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ProcessInterrupted("O motor de voz encerrou a conexão. O trabalho continuará dos trechos salvos.") from exc
        if not self.wait().get("ok"):
            raise ValueError("O motor não confirmou a geração do trecho.")

    def close(self):
        process = self.process
        if process:
            stop_process_tree(process)
            if hasattr(self, "reader"):
                self.reader.join(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass  # Do not mask the recoverable broken-pipe error.
            self.process = None
        self.output.close()
