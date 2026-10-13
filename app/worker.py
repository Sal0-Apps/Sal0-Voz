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
from .catalog import CATALOG, runtime, require, model_files, models_needed, DEFAULT_ASR_MODEL, is_clone, needs_reference_text
from .engine_session import EngineSession
from .engine_policy import choose_profile, MemoryUnavailable
from .engine_policy import MEMORY_GIB
from .resources import cgroup_memory, memory_available, release_temporary_memory, ProcessInterrupted, stop_process_tree, is_memory_error
from .audio_files import audio_valid, checkpoint_audio
from .model_manager import manager as model_manager
from .media import ffargs, probe, input_args
from .script import subtitles
from .reactions import caption, synthesis_text, render_policy
from .telegram import notify_job

class Interrupted(Exception):
    pass

class Worker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.clone_session = None
        self.active_job_id = None
        self.processing_engine = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        for ident in s.job_ids("running"):
            self.update(ident, status="queued", stage="Retomando após reinício", retry_at=None)
        # Upgrade older RAM/interruption failures to the same automatic Resume.
        # A manual pause/cancel and invalid inputs remain under user control.
        for status in ("failed", "paused"):
            for ident in s.job_ids(status):
                saved = s.get("job", ident)
                detail = (str(saved.get("error") or "") + " " + str(saved.get("stage") or "")).lower()
                terms = ("out of memory", "defaultcpuallocator", "not enough memory", "std::bad_alloc",
                         "aguardando ram", "memória livre insuficiente", "memória do container próxima",
                         "pouca memória disponível", "modelo de voz foi interrompido",
                         "motor de voz encerrou a conexão", "o sistema encerrou o processo")
                if (is_memory_error(detail) or any(term in detail for term in terms)) and "instrução incompatível" not in detail and (status != "paused" or saved.get("stage") != "Pausado"):
                    self.update(ident, status="queued", stage="Retomando automaticamente dos trechos salvos", error=None, retry_at=None, consecutive_retries=0)
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
        state = s.job_state(ident)
        if state["status"] != "running":
            raise Interrupted()
        minimum = int(os.getenv("SAL0_MIN_FREE_MB", "512")) * 1024**2
        if shutil.disk_usage(s.DATA).free < minimum:
            self.update(ident, status="paused", stage="Libere espaço em disco e retome")
            raise Interrupted()
        memory = psutil.virtual_memory()
        usage = cgroup_memory(Path("/sys/fs/cgroup"))
        if usage and usage[1] > usage[0]*0.94:
            cloning = state["mode"] != "asr" and not (self.processing_engine or "").startswith("whisper-")
            needed = MEMORY_GIB.get((state["engine"], state["dtype"]), 0.5) if cloning else 0.5
            raise MemoryUnavailable(needed, max(0, usage[0]-usage[1])/1024**3)
        if memory.available < 256*1024**2:
            raise MemoryUnavailable(0.5, memory.available/1024**3)

    def run(self, ident, args, cwd=None):
        self.check(ident)
        log = s.DATA / "jobs" / ident / "process.log"
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", PYANNOTE_METRICS_ENABLED="0", GRADIO_ANALYTICS_ENABLED="False", DO_NOT_TRACK="1")
        with log.open("ab") as output:
            log_start = log.stat().st_size
            process = subprocess.Popen(args, cwd=cwd, env=env, stdout=output, stderr=output, start_new_session=os.name == "posix")
            try:
                while process.poll() is None:
                    self.check(ident)
                    self.stop_event.wait(0.4)
                if process.returncode:
                    with log.open("rb") as stream:
                        stream.seek(max(log_start, log.stat().st_size - 4000))
                        detail = stream.read().decode("utf-8", errors="replace").strip()
                    reason = {-9: "O sistema encerrou o processo; verifique memória e limites do container.",
                              -4: "O motor encontrou uma instrução incompatível com esta CPU."}.get(process.returncode, "O motor não conseguiu concluir o processamento.")
                    if is_memory_error(detail):
                        state = s.job_state(ident)
                        needed = MEMORY_GIB.get((state["engine"], state["dtype"]), 0.5) if is_clone(self.processing_engine) else 0.5
                        raise MemoryUnavailable(needed, memory_available()/1024**3)
                    if process.returncode < 0 and process.returncode != -4:
                        raise ProcessInterrupted(f"{reason} Código {process.returncode}. {detail[-1200:]}")
                    raise ValueError(f"{reason} Código {process.returncode}. {detail[-1200:]}")
            finally:
                stop_process_tree(process)

    @staticmethod
    def speech_started(project, folder):
        return any(segment.get("pause_ms") is None and (not segment.get("reaction") or
                   (folder / f"render-{index:06d}.json").is_file()) and
                   any((folder / f"{prefix}-{index:06d}.json").is_file() for prefix in ("segment", "raw"))
                   for index, segment in enumerate(project.get("segments", [])))

    def close_clone(self):
        session, self.clone_session = self.clone_session, None
        if session:
            session.close()
            release_temporary_memory()

    def retry(self, ident, exc, project=None, waiting_memory=None):
        """Automatic equivalent of Resume, respecting manual pause/cancel."""
        self.close_clone()
        release_temporary_memory()
        with self.lock:
            job = s.get("job", ident)
            if job["status"] != "running":
                return
            project = project or job["snapshot"]
            folder = s.DATA / "jobs" / ident
            saved = sum(any((folder / f"{prefix}-{index:06d}.json").is_file() for prefix in ("segment", "raw"))
                        for index in range(len(project.get("segments", []))))
            previous = job.get("consecutive_retries", 0) if saved <= job.get("retry_checkpoint_count", -1) else 0
            consecutive = previous + 1
            delay = min(300, 5 * 2**min(consecutive-1, 6))
            stage = f"Retomada automática em {delay}s · {saved} trechos salvos"
            if waiting_memory:
                stage = "Liberando RAM. " + stage
            self.update(ident, status="queued", snapshot=project, stage=stage, error=None,
                        waiting_memory=waiting_memory, retry_at=time.time()+delay,
                        automatic_retries=job.get("automatic_retries", 0)+1,
                        consecutive_retries=consecutive, retry_checkpoint_count=saved,
                        last_recovery_error=str(exc)[-2000:])

    def loop(self):
        while not self.stop_event.is_set():
            with self.lock:
                job = None
                for candidate_id in s.job_ids("queued"):
                    candidate = s.get("job", candidate_id)
                    if candidate.get("retry_at") and candidate["retry_at"] > time.time():
                        continue
                    try:
                        project = candidate["snapshot"]
                        folder = s.DATA / "jobs" / candidate["id"]
                        locked = self.speech_started(project, folder)
                        profile = choose_profile(project, locked=locked)
                        if profile:
                            project.setdefault("requested_engine", project["engine"])
                            project.update(engine=profile["engine"], dtype=profile["dtype"])
                            self.update(candidate["id"], snapshot=project, profile=profile, waiting_memory=None)
                        needed = models_needed(project)
                        waiting = []
                        models = {}
                        for engine in needed:
                            try:
                                models[engine] = require(engine, "asr" if engine.startswith("whisper-") else "tts")
                            except ValueError:
                                if engine == "diagnostic":
                                    raise
                                download = model_manager.status(engine) or {}
                                if download.get("status") == "completed" and model_files(engine)[0] is not None:
                                    raise ValueError("Os arquivos chegaram, mas o ambiente do modelo não está pronto. Atualize a imagem do aplicativo.")
                                if download.get("status") not in {"queued", "downloading", "failed", "cancelled"}:
                                    model_manager.request(engine, accept_license=True, automatic=True)
                                waiting.append(engine)
                        if waiting:
                            stage = "Preparando os modelos; seu trabalho começará automaticamente"
                            if any((model_manager.status(x) or {}).get("status") in {"failed", "cancelled"} for x in waiting):
                                stage = "Aguardando o modelo. Use Retomar preparação para continuar este trabalho."
                            old = s.get("job", candidate["id"])
                            if old.get("stage") != stage or old.get("waiting_models") != waiting:
                                self.update(candidate["id"], stage=stage, waiting_models=waiting)
                            continue
                        if needed:
                            project["model"] = models[needed[0]]
                        self.update(candidate["id"], snapshot=project)
                        job = candidate
                        break
                    except MemoryUnavailable as exc:
                        self.update(candidate["id"], stage=str(exc), waiting_memory={"required_gib": exc.required, "available_gib": round(exc.available, 1)})
                    except Exception as exc:
                        self.update(candidate["id"], status="failed", stage="Não foi possível preparar este trabalho: " + str(exc), error=str(exc))
                if job:
                    self.update(job["id"], status="running", stage="Preparando", waiting_models=[], retry_at=None, started=time.time())
                    self.active_job_id = job["id"]
            if not job:
                self.wake.wait(2); self.wake.clear(); continue
            ident = job["id"]
            started = time.monotonic()
            try:
                self.execute(job)
                with self.lock:
                    self.check(ident)
                    finished = self.update(ident, status="completed", stage="Concluído — revise o resultado", progress=100, consecutive_retries=0, retry_at=None, waiting_memory=None, elapsed_seconds=round(time.monotonic()-started, 2))
                notify_job(finished)
            except Interrupted:
                if self.stop_event.is_set() and s.get("job", ident)["status"] == "running":
                    self.update(ident, status="queued", stage="Interrompido com segurança; aguardando reinício")
            except MemoryUnavailable as exc:
                project = s.get("job", ident)["snapshot"]
                folder = s.DATA / "jobs" / ident
                locked = self.speech_started(project, folder)
                if not locked and exc.required == MEMORY_GIB.get((project.get("engine"), project.get("dtype", "float32"))) and project.get("adaptive_memory", True):
                    failed = project.setdefault("memory_failed_profiles", [])
                    key = project["engine"] + "/" + project.get("dtype", "float32")
                    if key not in failed:
                        failed.append(key)
                self.retry(ident, exc, project, {"required_gib": exc.required, "available_gib": round(exc.available, 1)})
            except ProcessInterrupted as exc:
                self.retry(ident, exc)
            except Exception as exc:
                failed = self.update(ident, status="failed", stage=str(exc), error=str(exc))
                notify_job(failed)
            finally:
                with self.lock:
                    self.active_job_id = None
                release_temporary_memory()

    def engine(self, ident, request, folder):
        previous, self.processing_engine = self.processing_engine, request["engine"]
        try:
            return self._engine(ident, request, folder)
        finally:
            self.processing_engine = previous

    def _engine(self, ident, request, folder):
        if request["engine"].startswith("whisper-"):
            self.close_clone()
            request["work_dir"] = str(folder / "asr-work")
        if is_clone(request["engine"]):
            request["dtype"] = s.get("job", ident)["snapshot"].get("dtype", CATALOG[request["engine"]].get("dtype", "float32"))
        path = folder / "request.json"
        model, manifest, _ = model_files(request["engine"])
        request["model_path"] = str(model or (s.DATA / "models" / request["engine"]))
        request["model_revision"] = manifest.get("revision")
        s.atomic_json(path, request)
        if is_clone(request["engine"]):
            if self.clone_session is None:
                stage = s.get("job", ident)["stage"]
                self.clone_session = EngineSession(self, ident, request, folder)
                self.update(ident, stage=stage)
            self.clone_session.generate(request)
        else:
            try:
                self.run(ident, [runtime(request["engine"]), "-m", "app.engine_runner", str(path)])
            finally:
                shutil.rmtree(folder / "asr-work", ignore_errors=True)
                release_temporary_memory()

    def execute(self, job):
        self.clone_session = None
        try:
            self._execute(job)
        finally:
            self.close_clone()

    def prepare_references(self, ident, project, folder):
        # ASR exits before cloning; Chatterbox does not need a transcript.
        reference_seconds = CATALOG[project["engine"]].get("reference_seconds", 30)
        reference_hz = CATALOG[project["engine"]].get("reference_hz", 24000)
        source_hashes = {}
        for segment in project["segments"]:
            if segment.get("pause_ms") is not None:
                continue
            needs_text = needs_reference_text(project["engine"], project.get("voice_style", "natural"), bool(segment.get("reaction")))
            character = segment.get("character")
            if not character or not character.get("reference"):
                raise ValueError("Escolha uma voz com gravação de referência para gerar a fala e as reações.")
            source = s.safe_path(character["reference"]["path"])
            transcript = character.get("reference_text", "").strip()
            language = character.get("language", project["language"])
            asr_revision = require(DEFAULT_ASR_MODEL, "asr").get("revision") if needs_text and not transcript else None
            if source not in source_hashes:
                source_hashes[source] = s.digest(source)
            key = json.dumps([source_hashes[source], language, transcript,
                              [DEFAULT_ASR_MODEL, asr_revision] if needs_text and not transcript else None,
                              "reference-v2" if needs_text else "reference-audio-v1"])
            if reference_seconds != 30 or reference_hz != 24000:
                key += json.dumps([reference_seconds, reference_hz])
            import hashlib
            cache = s.DATA / "cache" / "voice-reference" / hashlib.sha256(key.encode()).hexdigest()
            cache.mkdir(parents=True, exist_ok=True)
            audio, meta_file = cache / "reference.wav", cache / "prepared.json"
            try:
                prepared = json.loads(meta_file.read_text())
                valid = audio.is_file() and prepared["sha256"] == s.digest(audio) and (not needs_text or bool(prepared["text"].strip()))
            except (OSError, ValueError, KeyError):
                valid = False
            if not valid:
                self.update(ident, stage="Preparando a gravação da sua voz")
                duration = probe(source)["duration"]
                if needs_text and transcript and duration > reference_seconds + 0.1:
                    raise ValueError(f"Com transcrição manual, use uma referência de até {reference_seconds} segundos. Deixe a transcrição vazia para preparar um trecho automaticamente.")
                temporary = cache / "reference.partial.wav"
                self.run(ident, ffargs(*input_args(source), "-map", "0:a:0", "-t", str(reference_seconds), "-vn", "-ac", "1", "-ar", str(reference_hz), "-c:a", "pcm_s16le", temporary))
                with wave.open(str(temporary)) as wav:
                    seconds = wav.getnframes() / wav.getframerate()
                if seconds < 3:
                    raise ValueError(f"Use uma gravação com pelo menos 3 segundos de fala clara e até {reference_seconds} segundos, com uma pessoa e sem música.")
                os.replace(temporary, audio)
                if needs_text and not transcript:
                    self.update(ident, stage="Transcrevendo sua gravação automaticamente na CPU")
                    cues_file = cache / "transcript.json"
                    self.engine(ident, {"engine": DEFAULT_ASR_MODEL, "language": language,
                                       "source": str(audio), "output": str(cues_file)}, folder)
                    transcript = " ".join(c["text"] for c in json.loads(cues_file.read_text())).strip()
                    if not transcript:
                        raise ValueError("Não encontrei fala na gravação. Envie uma amostra mais clara ou informe a transcrição nas opções da voz.")
                prepared = {"text": transcript, "sha256": s.digest(audio), "seconds": seconds,
                            "automatic": not bool(character.get("reference_text", "").strip())}
                s.atomic_json(meta_file, prepared)
            character["prepared_reference"] = audio.relative_to(s.DATA).as_posix()
            character["prepared_reference_text"] = prepared["text"]
            if needs_text and character.get("reference_id") and segment.get("character_id"):
                s.put("reference_preparation", {"id": segment["character_id"]+"-"+str(character["number"]),
                       "owner_username": project.get("owner_username"), "text": prepared["text"],
                       "seconds": prepared["seconds"], "automatic": prepared["automatic"]})
        self.update(ident, snapshot=project)

    def _execute(self, job):
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
        if project.get("automatic_dub") and not project["segments"]:
            self.prepare_dubbing(ident, project, folder)
        if is_clone(project["engine"]):
            self.prepare_references(ident, project, folder)
        parts = []
        sample_rate = project.get("output_sample_rate", CATALOG[project["engine"]].get("sample_rate", 24000))
        cues = []
        cursor = 0
        timed_groups = {}
        segments = project["segments"]
        last_speech = max((i for i, segment in enumerate(segments)
                           if segment.get("pause_ms") is None), default=-1)
        for index, segment in enumerate(segments):
            self.check(ident)
            self.update(ident, progress=round(index/len(segments)*85), stage=f"Gerando trecho {index+1} de {len(segments)}")
            policy = render_policy(project, segment)
            if policy is not None:
                marker = folder / f"render-{index:06d}.json"
                try:
                    current = json.loads(marker.read_text()) == policy
                except (OSError, ValueError):
                    current = False
                if not current:
                    for prefix in ("raw", "segment"):
                        for suffix in ("wav", "json"):
                            (folder / f"{prefix}-{index:06d}.{suffix}").unlink(missing_ok=True)
                    # Save before rendering, so an interrupted confirmation
                    # still reuses a new raw checkpoint on the next attempt.
                    s.atomic_json(marker, policy)
            target = folder / f"segment-{index:06d}.wav"
            valid = audio_valid(target)
            if valid and index == last_speech:
                self.close_clone()
            if not valid:
                tmp = folder / f"temporary-{index}.wav"
                if segment.get("pause_ms") is not None:
                    with wave.open(str(tmp), "wb") as wav:
                        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(sample_rate)
                        frames = round(segment["pause_ms"]*sample_rate/1000)
                        while frames:
                            self.check(ident)
                            chunk = min(frames, sample_rate)
                            wav.writeframesraw(b"\0\0"*chunk); frames -= chunk
                else:
                    raw = folder / f"raw-{index:06d}.wav"
                    character = segment.get("character")
                    if not audio_valid(raw):
                        text = synthesis_text(segment["reaction"], project["engine"], segment["language"]) if segment.get("reaction") else segment["text"]
                        if project["engine"] == "diagnostic":
                            text_file = folder / "spoken.txt"
                            text_file.write_text(text, encoding="utf-8")
                            self.run(ident, [shutil.which("espeak-ng") or shutil.which("espeak"), "-v", "pt-br" if segment["language"]=="pt-BR" else "en-us", "-f", str(text_file), "-w", str(raw)])
                        else:
                            self.engine(ident, {"engine": project["engine"], "language": segment["language"], "text": text, "reaction": segment.get("reaction"), "reference": str(s.safe_path(character["prepared_reference"])), "reference_text": character["prepared_reference_text"], "expressiveness": project.get("expressiveness", 0.7), "voice_style": project.get("voice_style", "natural"), "output": str(raw), "checkpoint": True}, folder)
                        if not audio_valid(raw):
                            checkpoint_audio(raw)
                    if index == last_speech:
                        self.close_clone()
                    filters = []
                    if segment["rate"] != 1:
                        filters.append(f"atempo={segment['rate']}")
                    if segment["volume"] != 0:
                        filters.append(f"volume={segment['volume']}dB")
                    self.run(ident, ffargs("-i", raw, *( ["-af", ",".join(filters)] if filters else [] ), "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le", tmp))
                os.replace(tmp, target)
                checkpoint_audio(target)
            with wave.open(str(target), "rb") as wav:
                duration_ms = round(wav.getnframes()*1000/wav.getframerate())
            if project["mode"] == "dub":
                key = segment.get("cue_index", index)
                group = timed_groups.setdefault(key, {"start_ms": segment["start_ms"], "end_ms": segment["end_ms"], "paths": [], "text": []})
                group["paths"].append(target)
                if caption(segment):
                    group["text"].append(caption(segment))
            else:
                parts.append(target)
                if caption(segment):
                    cues.append({"start_ms": cursor, "end_ms": cursor+duration_ms, "text": caption(segment)})
                cursor += duration_ms
        self.close_clone()
        self.update(ident, progress=90, stage="Montando exportação")
        joined = folder / "joined.wav"
        if project["mode"] == "dub":
            for index, group in enumerate(timed_groups.values()):
                target = folder / f"cue-{index:06d}.wav"
                self.concatenate(group["paths"], target, ident, sample_rate)
                with wave.open(str(target), "rb") as wav:
                    duration_ms = wav.getnframes()*1000/wav.getframerate()
                window = group["end_ms"]-group["start_ms"]
                ratio = duration_ms/window
                if ratio > 1.1 and not project.get("automatic_dub"):
                    raise ValueError(f"Trecho {index+1} excede a janela em mais de 10%. Edite o texto ou os tempos e gere uma nova versão; nenhuma palavra foi cortada.")
                if ratio > 1:
                    # FFmpeg may add a few samples during tempo adjustment.
                    # Measure the result so contiguous cues never drift later.
                    for attempt in range(3):
                        fitted = folder / f"fitted-{index}-{attempt}.wav"
                        factor = ratio*1.01
                        factors = []
                        while factor > 2:
                            factors.append("atempo=2"); factor /= 2
                        factors.append(f"atempo={factor}")
                        self.run(ident, ffargs("-i", target, "-af", ",".join(factors), "-c:a", "pcm_s16le", fitted))
                        target = fitted
                        with wave.open(str(target), "rb") as wav:
                            ratio = wav.getnframes()*1000/wav.getframerate()/window
                        if ratio <= 1:
                            break
                    else:
                        raise ValueError(f"Trecho {index+1} não coube no intervalo. Revise os tempos; nenhuma palavra foi cortada.")
                parts.append((target, group["start_ms"]))
                cues.append({"start_ms": group["start_ms"], "end_ms": group["end_ms"], "text": " ".join(group["text"])})
            self.timeline(parts, joined, round(project["media"]["duration"]*sample_rate), ident, sample_rate)
        else:
            self.concatenate(parts, joined, ident, sample_rate)
        extension = "mp4" if project["mode"] == "dub" else project.get("format", "wav")
        output = s.DATA / "exports" / f"{ident}.{extension}"
        temporary = output.with_name(ident + ".partial." + extension)
        if project["mode"] == "dub":
            source = s.safe_path(project["media"]["path"])
            has_video = project["media"].get("video")
            args = ffargs("-i", source, "-i", joined) if has_video else ffargs("-f", "lavfi", "-i", "color=c=0x0b1521:s=1280x720:r=25", "-i", joined)
            if project.get("background"):
                args += ["-i", str(s.safe_path(project["background"]["path"])), "-filter_complex", "[1:a]volume=1[v];[2:a]volume=0.7[b];[v][b]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v:0", "-map", "[a]"]
            else:
                args += ["-map", "0:v:0", "-map", "1:a:0"]
            video = next((x for x in project["media"].get("streams", []) if x["type"] == "video"), {})
            if video.get("codec") == "h264" and video.get("pixel_format") == "yuv420p":
                args += ["-c:v", "copy"]
            else:
                args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-threads", os.getenv("SAL0_THREADS", "4")]
            args += ["-c:a", "aac", "-t", str(project["media"]["duration"]), "-movflags", "+faststart", str(temporary)]
        else:
            codec = {"wav": "pcm_s24le", "flac": "flac", "mp3": "libmp3lame", "opus": "libopus"}[extension]
            args = ffargs("-i", joined, "-c:a", codec, temporary)
        self.run(ident, args)
        os.replace(temporary, output)
        self.finish_subtitles(ident, cues, [{"path": output.relative_to(s.DATA).as_posix(), "name": f"{project.get('output_name', project['name'])}.{extension}", "type": "video" if extension=="mp4" else "audio"}])

    def prepare_dubbing(self, ident, project, folder):
        """Transcribe the source once and freeze timed speech before cloning."""
        from .script import compile_script
        output = folder / "video-transcript.json"
        if not output.is_file():
            self.update(ident, stage="Transcrevendo a fala original para dublagem automática")
            temporary = folder / "video-transcript.partial.json"
            self.engine(ident, {"engine": project.get("asr_engine", DEFAULT_ASR_MODEL), "language": project["language"], "source": str(s.safe_path(project["media"]["path"])), "output": str(temporary)}, folder)
            os.replace(temporary, output)
        cues = json.loads(output.read_text(encoding="utf-8"))
        if not cues:
            raise ValueError("Não encontrei fala no vídeo. Confira o áudio e o idioma escolhido.")
        segments, previous_end = [], 0
        for cue_index, cue in enumerate(cues):
            start = max(previous_end, int(cue["start_ms"]))
            end = min(round(project["media"]["duration"]*1000), int(cue["end_ms"]))
            if not cue["text"].strip():
                continue
            if end <= start:
                raise ValueError("A transcrição contém fala sem intervalo utilizável. Revise os tempos das legendas antes de dublar.")
            # Transcribed brackets are literal speech, never script controls.
            source = cue["text"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            parsed = compile_script(source, project["language"], project.get("character_id"), project.get("rate", 1))
            for item in parsed:
                segment = {**item, "cue_index": cue_index, "start_ms": start, "end_ms": end}
                if project.get("default_character"):
                    segment["character"] = dict(project["default_character"])
                segments.append(segment)
            previous_end = end
        if not segments:
            raise ValueError("Não encontrei trechos de fala utilizáveis no vídeo.")
        project["segments"] = segments
        project["cues"] = cues
        self.update(ident, snapshot=project, cues=cues)

    def concatenate(self, paths, output, ident, sample_rate=24000):
        with wave.open(str(output), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(sample_rate)
            for path in paths:
                self.check(ident)
                with wave.open(str(path), "rb") as inp:
                    while block := inp.readframes(sample_rate):
                        out.writeframesraw(block)

    def timeline(self, parts, output, frames, ident, sample_rate=24000):
        # Disk-based timeline, constant memory. Overlap is rejected during submission.
        with wave.open(str(output), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(sample_rate)
            cursor = 0
            for path, start in parts:
                self.check(ident)
                gap = round(start*sample_rate/1000)-cursor
                while gap > 0:
                    self.check(ident)
                    n = min(gap, sample_rate); out.writeframesraw(b"\0\0"*n); gap -= n; cursor += n
                with wave.open(str(path), "rb") as inp:
                    while block := inp.readframes(sample_rate):
                        out.writeframesraw(block); cursor += len(block)//2
            while cursor < frames:
                self.check(ident)
                n = min(frames-cursor, sample_rate); out.writeframesraw(b"\0\0"*n); cursor += n

    def finish_subtitles(self, ident, cues, outputs=None):
        outputs = outputs or []
        project = s.get("job", ident).get("snapshot", {})
        name = project.get("output_name", "legendas")
        for extension in ("srt", "vtt"):
            path = s.DATA / "exports" / f"{ident}.{extension}"
            path.write_text(subtitles(cues, vtt=extension=="vtt"), encoding="utf-8")
            outputs.append({"path": path.relative_to(s.DATA).as_posix(), "name": f"{name}.{extension}", "type": "subtitle"})
        self.update(ident, outputs=outputs, cues=cues, subtitle_alignment="Tempos por trecho; revisão humana necessária.")

