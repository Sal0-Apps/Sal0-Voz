"""Explicit model preparation; never called by the offline inference service."""
import argparse
import json
import os
import shutil
from pathlib import Path
from app import storage as s
from app.catalog import CATALOG

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
        info = HfApi().model_info(meta["repo"], files_metadata=True)
        files = {x.rfilename: x.size or 0 for x in info.siblings if not x.rfilename.startswith(".")}
        total = sum(files.values())
        plan = {"repo": meta["repo"], "revision": info.sha, "bytes": total, "license": meta["license"], "files": files}
        s.atomic_json(folder / "download-plan.json", plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print(f"Download estimado: {total/1024**3:.2f} GiB. Execute install com --accept-license após conferir a licença na fonte.")
        return
    if not args.accept_license:
        parser.error("Leia a licença do modelo e acrescente --accept-license.")
    plan_path = folder / "download-plan.json"
    if not plan_path.exists():
        parser.error("Execute plan primeiro para fixar revisão e tamanho.")
    if (folder / "manifest.json").exists():
        raise SystemExit("Modelo já instalado. Preserve esta revisão; remova a instalação explicitamente antes de trocar os pesos.")
    plan = json.loads(plan_path.read_text())
    if shutil.disk_usage(folder).free < plan["bytes"] + 512*1024**2:
        raise SystemExit("Espaço livre insuficiente para o plano.")
    snapshot_download(repo_id=plan["repo"], revision=plan["revision"], local_dir=str(folder), allow_patterns=list(plan["files"]))
    files = {}
    for relative in plan["files"]:
        path = folder / relative
        if not path.is_file():
            raise SystemExit("Download incompleto: " + relative)
        files[relative] = s.digest(path)
    s.atomic_json(folder / "manifest.json", {**plan, "files": files})
    print("Modelo instalado e hashes registrados. Execute verify antes de levar o pacote offline.")

if __name__ == "__main__":
    main()

