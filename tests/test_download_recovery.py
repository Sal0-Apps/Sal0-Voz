"""Real local HTTP/cache recovery with substitute bytes; no model weights."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from app import storage as s
from app.catalog import CATALOG
from app.model_manager import DownloadFailure, ModelManager
from scripts.models import transient_error


def test_hub_http_interruption_resumes_existing_partial_and_verifies(data):
    # Large enough to expose multiple 256 KiB blocks, still under 1 MiB.
    content = bytes(range(256)) * 3072
    sha = hashlib.sha256(content).hexdigest()
    ident = "qwen-0.6b"
    meta = CATALOG[ident]
    transfers = []
    expected_path = f"/{meta['repo']}/resolve/{meta['revision']}/substitute.bin"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def headers_for(self, status=200, offset=0):
            self.send_response(status)
            self.send_header("Content-Length", str(len(content) - offset))
            self.send_header("ETag", '"' + sha + '"')
            self.send_header("X-Repo-Commit", meta["revision"])
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {offset}-{len(content)-1}/{len(content)}")
            self.end_headers()

        def do_HEAD(self):
            assert self.path == expected_path
            self.headers_for()

        def do_GET(self):
            assert self.path == expected_path
            offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
            transfers.append(offset)
            self.headers_for(206 if offset else 200, offset)
            if len(transfers) == 1:
                self.wfile.write(content[:256 * 1024])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                self.close_connection = True
            else:
                self.wfile.write(content[offset:])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    folder = data / "models" / ident
    folder.mkdir()
    plan = {"repo": meta["repo"], "revision": meta["revision"], "license": meta["license"],
            "bytes": len(content), "files": {"substitute.bin": len(content)},
            "sources": [{"repo": meta["repo"], "revision": meta["revision"], "files": ["substitute.bin"]}],
            "upstream_hashes": {"substitute.bin": {"sha256": sha}}}
    s.atomic_json(folder / "download-plan.json", plan)
    env = {**os.environ, "SAL0_DATA": str(data), "HF_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
           "HF_HUB_OFFLINE": "0", "HF_HUB_DISABLE_XET": "1", "HF_HUB_DOWNLOAD_TIMEOUT": "2",
           "HF_HUB_DISABLE_PROGRESS_BARS": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
    command = [sys.executable, "-m", "scripts.models", "install", ident, "--accept-license"]
    try:
        failed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
        assert failed.returncode == 75, failed.stdout + failed.stderr
        partial = list(folder.rglob("*.incomplete"))
        assert len(partial) == 1 and partial[0].stat().st_size == 256 * 1024
        manager = ModelManager()
        manager._record(ident, status="downloading")
        manager._progress(ident)
        assert manager.status(ident)["downloaded_bytes"] == 256 * 1024
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert transfers == [0, 256 * 1024]
        assert (folder / "substitute.bin").read_bytes() == content
        manifest = json.loads((folder / "manifest.json").read_text())
        assert manifest["files"] == {"substitute.bin": sha}
        # A complete verified file is reused without even issuing HTTP HEAD.
        again = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
        assert again.returncode == 0, again.stdout + again.stderr
        assert transfers == [0, 256 * 1024]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stalled_process_is_stopped_but_partial_and_plan_are_preserved(data, monkeypatch):
    import app.model_manager as module
    manager = ModelManager()
    ident = "voxcpm2"
    folder = data / "models" / ident
    folder.mkdir()
    (folder / "transfer.incomplete").write_bytes(b"partial data")
    s.atomic_json(folder / "download-plan.json", {"bytes": 100, "files": {"weights": 100}})
    manager._record(ident, status="downloading")
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("SAL0_DOWNLOAD_STALL_SECONDS", "30")
    monkeypatch.setattr(manager.stop_event, "wait", lambda _: clock.__setitem__(0, clock[0] + 10))

    class Process:
        returncode = None
        terminated = False
        def poll(self): return self.returncode
        def terminate(self): self.terminated = True; self.returncode = -15
        def wait(self, timeout=None): return self.returncode
    process = Process()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_, **__: process)
    with pytest.raises(DownloadFailure, match="sem avanço") as error:
        manager._run(ident, ["python", "-m", "scripts.models", "install", ident], folder / "download.log")
    assert error.value.transient and process.terminated
    assert (folder / "transfer.incomplete").read_bytes() == b"partial data"
    assert (folder / "download-plan.json").is_file() and not manager.processes


def test_verification_heartbeat_prevents_false_stall(data, monkeypatch):
    import app.model_manager as module
    manager = ModelManager()
    ident = "omnivoice"
    folder = data / "models" / ident
    folder.mkdir()
    manager._record(ident, status="downloading")
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(manager.stop_event, "wait", lambda _: clock.__setitem__(0, clock[0] + 60))
    monkeypatch.setattr(manager, "_progress", lambda _: (100, "verifying", "file", clock[0], clock[0]))

    class Process:
        def poll(self): return 0 if clock[0] >= 600 else None
        def terminate(self): pytest.fail("Hash verification is advancing")
        def wait(self, timeout=None): return 0
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_, **__: Process())
    manager._run(ident, ["python", "-m", "scripts.models", "install", ident], folder / "download.log")


def test_progress_failure_cannot_leave_an_orphan_download(data, monkeypatch):
    import app.model_manager as module
    manager = ModelManager()
    ident = "voxcpm2"
    folder = data / "models" / ident
    folder.mkdir()
    manager._record(ident, status="downloading")
    class Process:
        returncode = None
        def poll(self): return self.returncode
        def terminate(self): self.returncode = -15
        def wait(self, timeout=None): return self.returncode
    process = Process()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_, **__: process)
    def error(_): raise RuntimeError("Monitoring interrupted")
    monkeypatch.setattr(manager, "_progress", error)
    with pytest.raises(RuntimeError, match="Monitoring interrupted"):
        manager._run(ident, ["python", "-m", "scripts.models", "install", ident], folder / "download.log")
    assert process.returncode == -15 and not manager.processes


def test_manual_download_gets_automatic_network_retry_and_pause_cancels_it(data, monkeypatch):
    manager = ModelManager()
    ident = "voxcpm2"
    manager.request(ident, accept_license=True)
    def fail(_):
        manager._record(ident, status="downloading", attempt=10)
        raise DownloadFailure("Temporary network interruption", transient=True)
    monkeypatch.setattr(manager, "_download", fail)
    monkeypatch.setattr(manager.wake, "wait", lambda _: manager.stop_event.set())
    manager.loop()
    state = manager.status(ident)
    assert state["status"] == "failed" and state["retry_at"] is not None
    assert state["retry_at"] <= time.time() + 301
    manager.cancel(ident)
    state = manager.status(ident)
    assert state["status"] == "cancelled" and state["retry_at"] is None


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError(), requests.exceptions.ChunkedEncodingError()])
def test_network_error_classification(error):
    assert transient_error(error)
    assert not transient_error(ValueError("Corrupt hash"))
    assert not transient_error(PermissionError("Read-only data folder"))


def test_corrupt_model_manifest_cannot_break_api_or_download_queue(owner, data):
    folder = data / "models" / "omnivoice"
    folder.mkdir()
    (folder / "manifest.json").write_text("[]")
    response = owner.get("/api/models")
    assert response.status_code == 200
    assert not next(m for m in response.json() if m["id"] == "omnivoice")["available"]
    assert owner.get("/api/jobs").status_code == 200
    assert owner.post("/api/models/omnivoice/download", json={"accept_license": True}).status_code == 200


def test_legacy_event_stream_is_finite_and_uses_small_job_snapshot(owner):
    job = s.put("job", {"status": "queued", "snapshot": {"text": "private snapshot"}, "owner_username": "admin"})
    response = owner.get("/api/events/stream")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.text.startswith("retry: 5000\ndata: ")
    assert response.text.endswith("\n\n")
    jobs = json.loads(response.text.split("data: ", 1)[1].strip())
    assert jobs[0]["id"] == job["id"] and "snapshot" not in jobs[0]


def test_slow_session_lookup_does_not_block_healthcheck(owner, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = s.get
    def slow(kind, ident):
        if kind == "session":
            started.set()
            assert release.wait(3)
        return original(kind, ident)
    monkeypatch.setattr(s, "get", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        protected = pool.submit(owner.get, "/api/jobs")
        assert started.wait(1)
        try:
            health = pool.submit(owner.get, "/health")
            assert health.result(timeout=1).status_code == 200
        finally:
            release.set()
        assert protected.result(timeout=2).status_code == 200
