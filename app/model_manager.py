"""Server-side model download manager with persistent status records."""
import json
import os
import subprocess
import sys
import threading
import time
from . import storage as s
from .catalog import CATALOG, installed
DEFAULT_AUTO_MODELS = ("qwen-0.6b", "whisper-medium")
class ModelManager:
    def __init__(self):
        self.stop_event=threading.Event(); self.wake=threading.Event(); self.lock=threading.RLock(); self.thread=None; self.processes={}
    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear()
        for row in s.listing("model_download", limit=-1):
            if row.get("status") == "downloading":
                self._record(row["id"], status="queued", stage="Retomando download interrompido")
        if os.getenv("SAL0_AUTO_DOWNLOAD_MODELS","1").lower() not in {"0","false","no"}:
            for ident in (x.strip() for x in os.getenv("SAL0_AUTO_MODELS",",".join(DEFAULT_AUTO_MODELS)).split(",")):
                if ident and ident in CATALOG and "repo" in CATALOG[ident]:
                    current = self.status(ident)
                    if not current or current.get("status") != "cancelled":
                        self.request(ident,accept_license=True,automatic=True)
        self.thread=threading.Thread(target=self.loop,name="sal0-models",daemon=True); self.thread.start()
    def stop(self):
        self.stop_event.set(); self.wake.set()
        for process in list(self.processes.values()):
            if process.poll() is None: process.terminate()
        if self.thread: self.thread.join(timeout=10)
    def _record(self,ident,**fields):
        with self.lock:
            try: current=s.get("model_download",ident)
            except KeyError: current={}
            current.update({"id":ident,**fields,"updated":time.time()}); return s.put("model_download",current)

    def status(self,ident):
        try: return s.get("model_download",ident)
        except KeyError: return None
    def request(self,ident,accept_license=False,automatic=False):
        with self.lock:
            if ident not in CATALOG or "repo" not in CATALOG[ident]: raise ValueError("Escolha um modelo baixável.")
            if any(item["id"]==ident and item["available"] for item in installed()):
                return {"id":ident,"status":"completed","stage":"Instalado","progress":100}
            current=self.status(ident)
            if current and current.get("status") in {"queued","downloading"}: return current
            if not accept_license: raise ValueError("Confirme a licença do modelo antes de iniciar o download.")
            result=self._record(ident,status="queued",stage="Aguardando download no servidor",progress=0,error=None,automatic=automatic,started=None,finished=None)
            self.wake.set(); return result

    def cancel(self,ident):
        with self.lock:
            current=self.status(ident)
            if not current or current.get("status") not in {"queued","downloading"}: return current or {"id":ident,"status":"idle"}
            result = self._record(ident,status="cancelled",stage="Cancelado",error=None,finished=time.time())
            process=self.processes.get(ident)
            if process and process.poll() is None: process.terminate()
            return result

    def _run(self,ident,args,log_path):
        env=os.environ.copy(); env.update(SAL0_DATA=str(s.DATA), HF_HUB_OFFLINE="0",TRANSFORMERS_OFFLINE="0",HF_HUB_DISABLE_TELEMETRY="1")
        log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open("ab") as stream:
            process=subprocess.Popen(args,stdout=stream,stderr=subprocess.STDOUT,env=env); self.processes[ident]=process
            while process.poll() is None and not self.stop_event.is_set():
                if self.status(ident).get("status") == "cancelled":
                    process.terminate()
                    break
                self._progress(ident)
                self.stop_event.wait(1)
            if process.poll() is None: process.terminate()
            try:
                code=process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); code=process.wait()
            self.processes.pop(ident,None)
        self._check(ident)
        if code:
            with log_path.open("rb") as stream:
                stream.seek(max(0, log_path.stat().st_size-4000))
                detail = stream.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail or "O processo de download falhou.")
    def _progress(self, ident):
        folder = s.DATA / "models" / ident
        try:
            plan = json.loads((folder / "download-plan.json").read_text())
            total = plan["bytes"]
            downloaded = sum((folder / f).stat().st_size for f in plan["files"] if (folder / f).is_file())
            downloaded += sum(f.stat().st_size for f in folder.rglob("*.incomplete"))
            with self.lock:
                if self.status(ident).get("status") == "downloading":
                    self._record(ident, downloaded_bytes=downloaded, total_bytes=total,
                                 progress=min(99, round(downloaded / max(1,total)*100)),
                                 stage="Baixando e verificando arquivos no servidor")
        except (OSError, ValueError, KeyError):
            pass

    def _check(self, ident):
        if self.stop_event.is_set() or self.status(ident).get("status") == "cancelled":
            raise InterruptedError("Download interrompido")

    def _download(self,ident):
        folder=s.DATA/"models"/ident; folder.mkdir(parents=True,exist_ok=True); log=folder/"download.log"; plan=folder/"download-plan.json"
        with self.lock:
            self._check(ident)
            self._record(ident,status="downloading",stage="Consultando revisão e tamanho",progress=0,started=time.time(),error=None)
        if not plan.exists(): self._run(ident,[sys.executable,"-m","scripts.models","plan",ident],log)
        self._check(ident)
        self._record(ident,stage="Baixando pesos para o servidor",progress=0)
        self._run(ident,[sys.executable,"-m","scripts.models","install",ident,"--accept-license"],log)
        self._check(ident)
        if not (folder/"manifest.json").is_file(): raise RuntimeError("Download terminou sem manifesto de hashes.")
        with self.lock:
            self._check(ident)
            self._record(ident,status="completed",stage="Instalado no servidor",progress=100,finished=time.time(),error=None)
    def loop(self):
        while not self.stop_event.is_set():
            queued=[x for x in s.listing("model_download",limit=-1) if x.get("status")=="queued"]
            if not queued: self.wake.wait(2); self.wake.clear(); continue
            ident=sorted(queued,key=lambda x:x.get("updated",0))[0]["id"]
            try: self._download(ident)
            except InterruptedError:
                if self.stop_event.is_set() and self.status(ident).get("status") != "cancelled":
                    self._record(ident, status="queued", stage="Aguardando reinício")
            except Exception as exc:
                if self.status(ident) and self.status(ident).get("status")!="cancelled": self._record(ident,status="failed",stage="Falha no download",error=str(exc)[-4000:],finished=time.time())
    def snapshot(self):
        result=[]
        for item in installed():
            download=self.status(item["id"])
            if download: item["download"]=download
            result.append(item)
        return result
manager=ModelManager()
