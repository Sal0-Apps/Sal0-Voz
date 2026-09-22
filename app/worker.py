import json
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import psutil
from . import storage as s
from .catalog import runtime, require
from .model_manager import manager as model_manager
from .media import ffargs
from .script import subtitles
from .telegram import notify_job

class Interrupted(Exception):
    pass

class Worker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.RLock()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        for job in s.listing("job", limit=-1):
            if job["status"] == "running":
                job.update(status="queued", stage="Retomando após reinício")
                s.put("job", job)
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=20)

    def update(self, ident, **fields):
        with self.lock:
            job = s.get("job", ident)
            job.update(fields)
            return s.put("job", job)

    def check(self, ident):
        if self.stop_event.is_set():
            raise Interrupted()
        if s.get("job", ident)["status"] != "running":
            raise Interrupted()
        minimum = int(os.getenv("SAL0_MIN_FREE_MB", "512")) * 1024**2
        if shutil.disk_usage(s.DATA).free < minimum:
            self.update(ident, status="paused", stage="Libere espaço em disco e retome")
            raise Interrupted()
        memory = psutil.virtual_memory()
        cgroup = Path("/sys/fs/cgroup")
        try:
            limit = (cgroup / "memory.max").read_text().strip()
            used = int((cgroup / "memory.current").read_text())
            memory_stats = dict(line.split() for line in (cgroup / "memory.stat").read_text().splitlines())
            working_set = max(0, used - int(memory_stats.get("inactive_file", 0)))
            if limit != "max" and working_set > int(limit)*0.94:
                self.update(ident, status="paused", stage="Memória do container próxima do limite")
                raise Interrupted()
        except (OSError, ValueError):
            pass
        if memory.available < 256*1024**2:
            self.update(ident, status="paused", stage="Pouca memória disponível")
            raise Interrupted()

    def run(self, ident, args, cwd=None):
        self.check(ident)
        log = s.DATA / "jobs" / ident / "process.log"
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", PYANNOTE_METRICS_ENABLED="0")
        with log.open("ab") as output:
            process = subprocess.Popen(args, cwd=cwd, env=env, stdout=output, stderr=output)
            try:
                while process.poll() is None:
                    self.check(ident)
                    self.stop_event.wait(0.4)
                if process.returncode:
                    with log.open("rb") as stream:
                        stream.seek(max(0, log.stat().st_size - 4000))
                        detail = stream.read().decode("utf-8", errors="replace").strip()
                    reason = {-9: "O sistema encerrou o processo; verifique memória e limites do container.",
                              -4: "O motor encontrou uma instrução incompatível com esta CPU."}.get(process.returncode, "O motor não conseguiu concluir o processamento.")
                    raise ValueError(f"{reason} Código {process.returncode}. {detail[-1200:]}")
            finally:
                if process.poll() is None:
                    try:
                        parent = psutil.Process(process.pid)
                        children = parent.children(recursive=True)
                        for child in children:
                            child.kill()
                        parent.kill()
                        psutil.wait_procs(children + [parent], timeout=5)
                    except psutil.NoSuchProcess:
                        pass
                    process.wait()

    def loop(self):
        while not self.stop_event.is_set():
            with self.lock:
                jobs = [x for x in reversed(s.listing("job", limit=-1)) if x["status"] == "queued"]
                job = None
                for candidate in jobs:
                    try:
                        project = candidate["snapshot"]
                        engine = project["asr_engine"] if project["mode"] == "asr" else project["engine"]
                        try:
                            model = require(engine, "asr" if project["mode"] == "asr" else "tts")
                        except ValueError as exc:
                            if engine == "diagnostic":
                                raise
                            download = model_manager.status(engine) or {}
                            if download.get("status") in {"failed", "cancelled"}:
                                raise ValueError("Download do modelo interrompido. Retome em Ajustes e retome este trabalho. " + (download.get("error") or ""))
                            if download.get("status") not in {"queued", "downloading"}:
                                model_manager.request(engine, accept_license=True, automatic=True)
                            self.update(candidate["id"], stage="Aguardando download do modelo no servidor")
                            continue
                        project["model"] = model
                        self.update(candidate["id"], snapshot=project)
                        job = candidate
                        break
                    except Exception as exc:
                        self.update(candidate["id"], status="failed", stage="Não foi possível preparar este trabalho: " + str(exc), error=str(exc))
                if job:
                    self.update(job["id"], status="running", stage="Preparando")
            if not job:
                self.wake.wait(2); self.wake.clear(); continue
            ident = job["id"]
            started = time.monotonic()
            try:
                self.execute(job)
                with self.lock:
                    self.check(ident)
                    finished = self.update(ident, status="completed", stage="Concluído — revise o resultado", progress=100, elapsed_seconds=round(time.monotonic()-started, 2))
                notify_job(finished)
            except Interrupted:
                if self.stop_event.is_set() and s.get("job", ident)["status"] == "running":
                    self.update(ident, status="queued", stage="Interrompido com segurança; aguardando reinício")
            except Exception as exc:
                failed = self.update(ident, status="failed", stage=str(exc), error=str(exc))
                notify_job(failed)

    def engine(self, ident, request, folder):
        path = folder / "request.json"
        request["model_path"] = str(s.DATA / "models" / request["engine"])
        s.atomic_json(path, request)
        self.run(ident, [runtime(request["engine"]), "-m", "app.engine_runner", str(path)])

    def execute(self, job):
        ident = job["id"]
        project = job["snapshot"]
        folder = s.DATA / "jobs" / ident
        folder.mkdir(parents=True, exist_ok=True)
        if project["mode"] == "asr":
            output = folder / "cues.json"
            self.engine(ident, {"engine": project["asr_engine"], "language": project["language"], "source": str(s.safe_path(project["media"]["path"])), "output": str(output)}, folder)
            cues = json.loads(output.read_text(encoding="utf-8"))
            if not cues:
                raise ValueError("Nenhuma fala detectada. Confira o áudio e o idioma.")
            self.finish_subtitles(ident, cues)
            return
        parts = []
        cues = []
        cursor = 0
        segments = project["segments"]
        for index, segment in enumerate(segments):
            self.check(ident)
            self.update(ident, progress=round(index/len(segments)*85), stage=f"Gerando trecho {index+1} de {len(segments)}")
            target = folder / f"segment-{index:06d}.wav"
            checkpoint = target.with_suffix(".json")
            valid = False
            if target.exists() and checkpoint.exists():
                meta = json.loads(checkpoint.read_text())
                valid = meta.get("sha256") == s.digest(target)
            if not valid:
                tmp = folder / f"temporary-{index}.wav"
                if segment.get("pause_ms") is not None:
                    with wave.open(str(tmp), "wb") as wav:
                        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                        frames = round(segment["pause_ms"]*24)
                        while frames:
                            self.check(ident)
                            chunk = min(frames, 24000)
                            wav.writeframesraw(b"\0\0"*chunk); frames -= chunk
                else:
                    raw = folder / f"raw-{index}.wav"
                    character = segment.get("character")
                    if project["engine"] == "diagnostic":
                        text_file = folder / "spoken.txt"
                        text_file.write_text(segment["text"], encoding="utf-8")
                        self.run(ident, [shutil.which("espeak-ng") or shutil.which("espeak"), "-v", "pt-br" if segment["language"]=="pt-BR" else "en-us", "-f", str(text_file), "-w", str(raw)])
                    else:
                        self.engine(ident, {"engine": project["engine"], "language": segment["language"], "text": segment["text"], "reference": str(s.safe_path(character["reference"]["path"])), "reference_text": character.get("reference_text", ""), "output": str(raw)}, folder)
                    self.run(ident, ffargs("-i", raw, "-af", f"atempo={segment['rate']},volume={segment['volume']}dB", "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", tmp))
                with wave.open(str(tmp), "rb") as wav:
                    duration = wav.getnframes()/wav.getframerate()
                    if not duration:
                        raise ValueError("Motor produziu áudio vazio.")
                os.replace(tmp, target)
                s.atomic_json(checkpoint, {"sha256": s.digest(target), "duration": duration})
            with wave.open(str(target), "rb") as wav:
                duration_ms = round(wav.getnframes()*1000/wav.getframerate())
            if project["mode"] == "dub":
                start, end = segment["start_ms"], segment["end_ms"]
                window = end-start
                ratio = duration_ms/window
                if ratio > 1.1:
                    raise ValueError(f"Trecho {index+1} excede a janela em mais de 10%. Edite o texto ou os tempos e gere uma nova versão; nenhuma palavra foi cortada.")
                if duration_ms > window:
                    fitted = folder / f"fitted-{index}.wav"
                    self.run(ident, ffargs("-i", target, "-af", f"atempo={ratio}", "-c:a", "pcm_s16le", fitted))
                    target = fitted
                cues.append({"start_ms": start, "end_ms": end, "text": segment["text"]})
                parts.append((target, start))
            else:
                parts.append(target)
                if segment["text"].strip():
                    cues.append({"start_ms": cursor, "end_ms": cursor+duration_ms, "text": segment["text"].strip()})
                cursor += duration_ms
        self.update(ident, progress=90, stage="Montando exportação")
        joined = folder / "joined.wav"
        if project["mode"] == "dub":
            self.timeline(parts, joined, round(project["media"]["duration"]*24000), ident)
        else:
            with wave.open(str(joined), "wb") as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
                for path in parts:
                    self.check(ident)
                    with wave.open(str(path), "rb") as inp:
                        while block := inp.readframes(24000):
                            out.writeframesraw(block)
        extension = "mp4" if project["mode"] == "dub" else project.get("format", "wav")
        output = s.DATA / "exports" / f"{ident}.{extension}"
        temporary = output.with_name(ident + ".partial." + extension)
        if project["mode"] == "dub":
            source = s.safe_path(project["media"]["path"])
            args = ffargs("-i", source, "-i", joined)
            if project.get("background"):
                args += ["-i", str(s.safe_path(project["background"]["path"])), "-filter_complex", "[1:a]volume=1[v];[2:a]volume=0.7[b];[v][b]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v:0", "-map", "[a]"]
            else:
                args += ["-map", "0:v:0", "-map", "1:a:0"]
            args += ["-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", str(temporary)]
        else:
            codec = {"wav": "pcm_s24le", "flac": "flac", "mp3": "libmp3lame", "opus": "libopus"}[extension]
            args = ffargs("-i", joined, "-c:a", codec, temporary)
        self.run(ident, args)
        os.replace(temporary, output)
        self.finish_subtitles(ident, cues, [{"path": output.relative_to(s.DATA).as_posix(), "name": f"{project['name']}.{extension}", "type": "video" if extension=="mp4" else "audio"}])

    def timeline(self, parts, output, frames, ident):
        # Disk-based timeline, constant memory. Overlap is rejected during submission.
        with wave.open(str(output), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
            cursor = 0
            for path, start in parts:
                self.check(ident)
                gap = round(start*24)-cursor
                while gap > 0:
                    self.check(ident)
                    n = min(gap, 24000); out.writeframesraw(b"\0\0"*n); gap -= n; cursor += n
                with wave.open(str(path), "rb") as inp:
                    while block := inp.readframes(24000):
                        out.writeframesraw(block); cursor += len(block)//2
            while cursor < frames:
                self.check(ident)
                n = min(frames-cursor, 24000); out.writeframesraw(b"\0\0"*n); cursor += n

    def finish_subtitles(self, ident, cues, outputs=None):
        outputs = outputs or []
        for extension in ("srt", "vtt"):
            path = s.DATA / "exports" / f"{ident}.{extension}"
            path.write_text(subtitles(cues, vtt=extension=="vtt"), encoding="utf-8")
            outputs.append({"path": path.relative_to(s.DATA).as_posix(), "name": f"legendas.{extension}", "type": "subtitle"})
        self.update(ident, outputs=outputs, cues=cues, subtitle_alignment="Tempos por trecho; revisão humana necessária.")

