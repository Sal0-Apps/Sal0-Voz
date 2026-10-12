"""Pinned, verified models for the image and optional persistent downloads."""
import argparse
import json
import os
import shutil
from pathlib import Path
from app import storage as s
from app.catalog import CATALOG

def download_plan(meta, api):
    """Download only the chosen weights, including pinned companion assets."""
    specifications = [meta, *meta.get("companions", [])]
    files, hashes, sources = {}, {}, []
    for spec in specifications:
        info = api.model_info(spec["repo"], revision=spec["revision"], files_metadata=True)
        selected = {x.rfilename: x for x in info.siblings if not x.rfilename.startswith(".")}
        if "files" in spec:
            missing = set(spec["files"]) - selected.keys()
            if missing:
                raise ValueError("Arquivos ausentes na fonte: " + ", ".join(sorted(missing)))
            selected = {name: selected[name] for name in spec["files"]}
        if files.keys() & selected.keys():
            raise ValueError("As fontes do modelo contêm arquivos duplicados.")
        sources.append({"repo": spec["repo"], "revision": info.sha, "files": list(selected)})
        for name, item in selected.items():
            files[name] = item.size or 0
            hashes[name] = {"sha256": item.lfs.sha256} if item.lfs else {"git_sha1": item.blob_id}
    return {"repo": meta["repo"], "revision": sources[0]["revision"], "sources": sources,
            "bytes": sum(files.values()), "license": meta["license"], "files": files, "upstream_hashes": hashes}

def validate_plan(plan, meta, folder):
    if plan["repo"] != meta["repo"] or any(not (folder / name).resolve().is_relative_to(folder.resolve()) for name in plan["files"]):
        raise ValueError("Plano inválido. Remova download-plan.json e execute plan novamente.")
    if "companions" in meta:
        specifications = [meta, *meta["companions"]]
        expected = [(item["repo"], item["revision"], set(item["files"])) for item in specifications]
        actual = [(item["repo"], item["revision"], set(item["files"])) for item in plan.get("sources", [])]
        if expected != actual or set(plan["files"]) != set().union(*(item[2] for item in expected)):
            raise ValueError("Plano incompleto ou de outra revisão. Remova download-plan.json e execute plan novamente.")

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
        plan = download_plan(meta, HfApi())
        s.atomic_json(folder / "download-plan.json", plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print(f"Download estimado: {plan['bytes']/1024**3:.2f} GiB. Execute install com --accept-license após conferir a licença na fonte.")
        return
    if not args.accept_license:
        parser.error("Leia a licença do modelo e acrescente --accept-license.")
    plan_path = folder / "download-plan.json"
    if not plan_path.exists():
        parser.error("Execute plan primeiro para fixar revisão e tamanho.")
    plan = json.loads(plan_path.read_text())
    validate_plan(plan, meta, folder)
    existing = sum(min((folder / name).stat().st_size, size) for name, size in plan["files"].items() if (folder / name).is_file())
    if shutil.disk_usage(folder).free < max(0, plan["bytes"] - existing) + 512*1024**2:
        raise SystemExit("Espaço livre insuficiente para o plano.")
    for source in plan.get("sources", [{"repo": plan["repo"], "revision": plan["revision"], "files": list(plan["files"])}]):
        snapshot_download(repo_id=source["repo"], revision=source["revision"], local_dir=str(folder), allow_patterns=source["files"], max_workers=2)
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

