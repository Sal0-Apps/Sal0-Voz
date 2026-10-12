"""Remove selected library items without breaking saved voices or resumable jobs."""
import json
import logging
import re
import shutil
import time
from pathlib import Path

from fastapi import HTTPException
from . import storage as s

KINDS = {"media": "media", "characters": "character", "results": "job"}


def media_ids(value):
    found = set()
    if isinstance(value, dict):
        if value.get("path") and value.get("id"):
            found.add(value["id"])
        for key in ("media_id", "background_id", "reference_id"):
            if value.get(key):
                found.add(value[key])
        found.update(value.get("reactions", {}).values())
        for item in value.values():
            found.update(media_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(media_ids(item))
    return found


def removal_path(relative):
    """Only canonical uploaded, exported and job files can be removed."""
    parts = Path(relative).parts
    if len(parts) != 2 or parts[0] not in {"media", "exports", "jobs"} or not re.fullmatch(r"[a-f0-9]{32}(?:\.[a-z0-9.]+)?", parts[1]):
        raise ValueError("Caminho de arquivo inválido para exclusão.")
    return s.DATA / relative


def recover_removals():
    """Restore a staged deletion if SQLite did not commit before a restart."""
    root = s.DATA / "trash"
    if not root.exists():
        return
    for folder in root.iterdir():
        if not folder.is_dir() or folder.is_symlink():
            continue
        try:
            manifest = json.loads((folder / "manifest.json").read_text())
            for move in manifest["moves"]:
                staged = folder / move["target"]
                if not re.fullmatch(r"move-\d+", move["target"]):
                    raise ValueError("Registro de limpeza inválido.")
                try:
                    s.get(manifest["kind"], move["id"])
                except KeyError:
                    continue
                original = removal_path(move["source"])
                if staged.exists() and not original.exists():
                    staged.rename(original)
            shutil.rmtree(folder)
        except (OSError, ValueError, KeyError):
            logging.getLogger(__name__).warning("Não foi possível concluir a limpeza pendente de arquivos", exc_info=True)


def remove_items(kind, identifiers, owner, worker):
    if kind not in KINDS:
        raise ValueError("Tipo de item inválido.")
    ids = list(dict.fromkeys(identifiers))
    if not ids or len(ids) > 100 or any(not re.fullmatch(r"[a-f0-9]{32}", ident) for ident in ids):
        raise ValueError("Selecione de 1 a 100 itens válidos por vez.")
    record_kind = KINDS[kind]
    deleted, blocked, missing, moves = [], [], [], []
    folder = None
    with worker.lock:
        with s.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            records = {}
            for entry_kind, ident, body in conn.execute("SELECT kind,id,body FROM records WHERE kind IN ('media','character','job','project')"):
                records.setdefault(entry_kind, {})[ident] = json.loads(body)
            targets = records.get(record_kind, {})
            # Check the entire request before making any filesystem changes.
            for ident in ids:
                if ident in targets and owner.get("role") != "admin" and targets[ident].get("owner_username") != owner["username"]:
                    raise HTTPException(403, "Um dos itens pertence a outro usuário.")
            for ident in ids:
                item = targets.get(ident)
                if item is None:
                    missing.append(ident)
                    continue
                reason = None
                if kind == "results" and (item.get("status") in {"queued", "running"} or worker.active_job_id == ident):
                    reason = "Este trabalho ainda está em execução. Cancele-o e aguarde encerrar antes de excluir."
                if kind == "media":
                    for voice in records.get("character", {}).values():
                        if ident in media_ids({"reference_id": voice.get("reference_id"), "reactions": voice.get("reactions", {})}):
                            name = voice["name"] if owner.get("role") == "admin" or voice.get("owner_username") == owner["username"] else "uma voz salva"
                            reason = f"Usado por {name}. Altere a referência ou exclua essa voz primeiro."
                            break
                    if not reason:
                        for job in records.get("job", {}).values():
                            if (job.get("status") != "completed" or worker.active_job_id == job["id"]) and ident in media_ids(job.get("snapshot", {})):
                                name = job["name"] if owner.get("role") == "admin" or job.get("owner_username") == owner["username"] else "um trabalho"
                                reason = f"Usado por {name}. Conclua ou exclua esse trabalho em Resultados primeiro."
                                break
                if reason:
                    blocked.append({"id": ident, "name": item["name"], "reason": reason})
                    continue
                deleted.append(ident)
                paths = []
                if kind == "media":
                    path = removal_path(item["path"])
                    if path.parent != s.DATA / "media" or not path.name.startswith(ident + "."):
                        raise ValueError("O arquivo não corresponde ao item selecionado.")
                    paths.append(path)
                elif kind == "results":
                    paths = [s.DATA / "jobs" / ident, *sorted((s.DATA / "exports").glob(ident + ".*"))]
                for path in paths:
                    if path.exists() or path.is_symlink():
                        moves.append({"id": ident, "source": path.relative_to(s.DATA).as_posix(), "target": f"move-{len(moves)}"})
            try:
                if moves:
                    folder = s.DATA / "trash" / s.uid()
                    folder.mkdir(parents=True)
                    s.atomic_json(folder / "manifest.json", {"kind": record_kind, "moves": moves})
                    for move in moves:
                        removal_path(move["source"]).rename(folder / move["target"])
                for ident in deleted:
                    conn.execute("DELETE FROM records WHERE kind=? AND id=?", (record_kind, ident))
                    if kind == "characters":
                        conn.execute("DELETE FROM records WHERE kind='reference_preparation' AND id LIKE ?", (ident + "-%",))
                # Keep the saved text and project, clear only removed selections.
                for project in records.get("project", {}).values():
                    old = dict(project)
                    changed = False
                    fields = ("media_id", "background_id") if kind == "media" else ("character_id",) if kind == "characters" else ()
                    for key in fields:
                        if project.get(key) in deleted:
                            project[key] = None
                            changed = True
                    if kind == "characters":
                        cues = [dict(cue) for cue in project.get("cues", [])]
                        for cue in cues:
                            if cue.get("character_id") in deleted:
                                cue["character_id"] = None
                                changed = True
                        project["cues"] = cues
                    if changed:
                        old["id"] += "-" + str(old["revision"])
                        project["revision"] += 1
                        for entry_kind, value in (("project_revision", old), ("project", project)):
                            value["updated"] = time.time()
                            conn.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?)", (entry_kind, value["id"], json.dumps(value, ensure_ascii=False), value["updated"]))
                conn.commit()
            except BaseException:
                for move in reversed(moves):
                    staged = folder / move["target"] if folder else None
                    if staged and (staged.exists() or staged.is_symlink()):
                        staged.rename(removal_path(move["source"]))
                if folder:
                    shutil.rmtree(folder)
                raise
    pending = False
    if folder:
        try:
            shutil.rmtree(folder)
        except OSError:
            pending = True
    return {"deleted": deleted, "blocked": blocked, "missing": missing, "cleanup_pending": pending}
