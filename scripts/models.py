"""Pinned, verified models for the image and optional persistent downloads."""
import argparse
import json
import os
import shutil
from pathlib import Path
from app import storage as s
from app.catalog import CATALOG

def verify_file(path, expected):
    if expected.get("sha256"):
        return s.digest(path) == expected["sha256"]
    if expected.get("git_sha1"):
        import hashlib
        sha = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                sha.update(block)
        return sha.hexdigest() == expected["git_sha1"]
    return True  # Existing plans remain usable; new plans include upstream hashes.

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["list", "plan", "install", "verify"])
    parser.add_argument("model", nargs="?")
    parser.add_argument("--accept-license", action="store_true")
    args = parser.parse_args()
    s.init()
    if args.action == "list":
        for ident, meta in CATALOG.items():
            print(ident, "—", meta["name"], "—", meta["license"])
        return
    if args.model not in CATALOG or "repo" not in CATALOG[args.model]:
        parser.error("Escolha um modelo baixável do comando list.")
    meta = CATALOG[args.model]
    folder = s.DATA / "models" / args.model
    folder.mkdir(parents=True, exist_ok=True)
    if args.action == "verify":
        manifest = json.loads((folder / "manifest.json").read_text())
        for relative, expected in manifest["files"].items():
            path = (folder / relative).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file() or s.digest(path) != expected:
                raise SystemExit("Arquivo ausente ou inválido: " + relative)
        print("Todos os hashes SHA-256 conferem."); return
    from huggingface_hub import HfApi, snapshot_download
    if args.action == "plan":
        info = HfApi().model_info(meta["repo"], revision=meta["revision"], files_metadata=True)
        files = {x.rfilename: x.size or 0 for x in info.siblings if not x.rfilename.startswith(".")}
        hashes = {x.rfilename: {"sha256": x.lfs.sha256} if x.lfs else {"git_sha1": x.blob_id}
                  for x in info.siblings if x.rfilename in files}
        total = sum(files.values())
        plan = {"repo": meta["repo"], "revision": info.sha, "bytes": total, "license": meta["license"], "files": files, "upstream_hashes": hashes}
        s.atomic_json(folder / "download-plan.json", plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print(f"Download estimado: {total/1024**3:.2f} GiB. Execute install com --accept-license após conferir a licença na fonte.")
        return
    if not args.accept_license:
        parser.error("Leia a licença do modelo e acrescente --accept-license.")
    plan_path = folder / "download-plan.json"
    if not plan_path.exists():
        parser.error("Execute plan primeiro para fixar revisão e tamanho.")
    plan = json.loads(plan_path.read_text())
    if plan["repo"] != meta["repo"] or any(not (folder / name).resolve().is_relative_to(folder.resolve()) for name in plan["files"]):
        raise SystemExit("Plano inválido. Remova download-plan.json e execute plan novamente.")
    existing = sum(min((folder / name).stat().st_size, size) for name, size in plan["files"].items() if (folder / name).is_file())
    if shutil.disk_usage(folder).free < max(0, plan["bytes"] - existing) + 512*1024**2:
        raise SystemExit("Espaço livre insuficiente para o plano.")
    snapshot_download(repo_id=plan["repo"], revision=plan["revision"], local_dir=str(folder), allow_patterns=list(plan["files"]), max_workers=2)
    files = {}
    for relative in plan["files"]:
        path = folder / relative
        if not path.is_file():
            raise SystemExit("Download incompleto: " + relative)
        if path.stat().st_size != plan["files"][relative] or not verify_file(path, plan.get("upstream_hashes", {}).get(relative, {})):
            path.unlink()
            raise SystemExit("Arquivo não confere com a fonte. Retome o download: " + relative)
        files[relative] = s.digest(path)
    s.atomic_json(folder / "manifest.json", {**plan, "file_sizes": plan["files"], "files": files})
    print("Modelo instalado e hashes registrados. Execute verify antes de levar o pacote offline.")

if __name__ == "__main__":
    main()

