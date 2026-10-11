"""One cancellable Qwen process per job, with bounded line-based responses."""
import json
import os
import queue
import subprocess
import threading
import psutil
from . import storage as s
from .catalog import runtime

class EngineSession:
    def __init__(self, worker, ident, request, folder):
        self.worker, self.ident = worker, ident
        self.log = folder / "process.log"
        self.output = self.log.open("ab")
        self.process = None
        self.responses = queue.Queue()
        path = folder / "engine-session.json"
        s.atomic_json(path, request)
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", GRADIO_ANALYTICS_ENABLED="False", DO_NOT_TRACK="1")
        try:
            self.process = subprocess.Popen(
                [runtime(request["engine"]), "-m", "app.engine_runner", "--serve", str(path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.output,
                text=True, encoding="utf-8", env=env, bufsize=1,
            )
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.worker.update(ident, stage="Carregando o modelo de voz na CPU; uma vez por trabalho")
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
                with self.log.open("rb") as stream:
                    stream.seek(max(0, self.log.stat().st_size - 2000))
                    detail = stream.read().decode("utf-8", errors="replace").strip()
                raise ValueError("O modelo de voz foi interrompido. " + detail)
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get("error"):
                raise ValueError(value["error"])
            return value

    def generate(self, request):
        self.worker.check(self.ident)
        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ValueError("O motor de voz encerrou a conexão. Consulte o diagnóstico do trabalho.") from exc
        if not self.wait().get("ok"):
            raise ValueError("O motor não confirmou a geração do trecho.")

    def close(self):
        process = self.process
        if process:
            if process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.terminate()
                    process.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
            if hasattr(self, "reader"):
                self.reader.join(timeout=1)
        self.output.close()
