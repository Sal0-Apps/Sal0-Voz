"""Consistent portable backup/restore. Stop the app before running."""
import argparse
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from contextlib import closing
from app import storage as s

def backup(destination):
    destination = Path(destination).resolve()
    if destination.is_relative_to(s.DATA):
        raise ValueError("Salve o backup fora do diretório de dados.")
    with tempfile.TemporaryDirectory() as temporary:
        db_path = Path(temporary) / "app.sqlite"
        with s.db() as conn, closing(sqlite3.connect(db_path)) as target:
            conn.backup(target)
        files = {"app.sqlite": s.digest(db_path)}
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.write(db_path, "app.sqlite")
            for folder in ("media", "projects", "jobs", "exports"):
                for path in (s.DATA / folder).rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        relative = path.relative_to(s.DATA).as_posix()
                        files[relative] = s.digest(path); archive.write(path, relative)
            models = {}
            for path in (s.DATA / "models").glob("*/manifest.json"):
                models[path.parent.name] = json.loads(path.read_text())
            archive.writestr("backup-manifest.json", json.dumps({"schema_version": 1, "files": files, "models": models}))
    return destination

def restore(source, destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Restaure em uma pasta nova ou vazia.")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            manifest = json.loads(archive.read("backup-manifest.json"))
            if manifest["schema_version"] != 1:
                raise ValueError("Versão de backup incompatível.")
            expected = set(manifest["files"])
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != expected | {"backup-manifest.json"}:
                raise ValueError("Lista de arquivos inválida.")
            if shutil.disk_usage(staging).free < sum(x.file_size for x in archive.infolist()) + 256*1024**2:
                raise ValueError("Espaço insuficiente para restauração.")
            for name in expected:
                relative = Path(name)
                output = (staging / relative).resolve()
                if relative.is_absolute() or not output.is_relative_to(staging) or ":" in name or "\\" in name:
                    raise ValueError("Caminho inseguro no backup.")
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as inp, output.open("wb") as out:
                    shutil.copyfileobj(inp, out, 1024*1024)
                if s.digest(output) != manifest["files"][name]:
                    raise ValueError("Hash inválido: " + name)
        # Sessions do not survive a restore.
        with closing(sqlite3.connect(staging / "app.sqlite")) as conn:
            conn.execute("DELETE FROM records WHERE kind='session'")
            conn.commit()
        destination.mkdir(exist_ok=True)
        for path in staging.iterdir():
            shutil.move(str(path), str(destination / path.name))
        (destination / "required-models.json").write_text(json.dumps(manifest["models"], indent=2), encoding="utf-8")
    return destination

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("archive")
    parser.add_argument("--destination")
    args = parser.parse_args()
    if args.action == "create":
        s.init(); print(backup(args.archive))
    else:
        if not args.destination: parser.error("--destination é obrigatório")
        print(restore(args.archive, args.destination))

