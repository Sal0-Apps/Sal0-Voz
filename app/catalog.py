import json
import os
import shutil
import sys
from pathlib import Path
from . import storage as s

DEFAULT_CLONE_MODEL = "qwen-1.7b"
DEFAULT_ASR_MODEL = "whisper-large-v3-turbo"
DEFAULT_MODELS = (DEFAULT_CLONE_MODEL, "qwen-0.6b", DEFAULT_ASR_MODEL)

CATALOG = {
    "diagnostic": {"name": "Voz de diagnóstico", "kind": "tts", "clone": False, "license": "GPL-3.0 (eSpeak NG)", "notice": "Voz sintética simples para testar o app; não representa a qualidade final."},
    "qwen-1.7b": {"name": "Maior fidelidade · Qwen 1.7B", "kind": "tts", "clone": True, "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "revision": "fd4b254389122332181a7c3db7f27e918eec64e3", "runtime": "qwen", "license": "Apache-2.0", "memory_gib": 9.5, "notice": "Prioriza fidelidade em CPU, com pesos em float32. Mais lento e exige cerca de 9,5 GiB livres; a qualidade depende da gravação."},
    "qwen-0.6b": {"name": "Mais leve · Qwen 0.6B", "kind": "tts", "clone": True, "repo": "Qwen/Qwen3-TTS-12Hz-0.6B-Base", "revision": "5d83992436eae1d760afd27aff78a71d676296fc", "runtime": "qwen", "license": "Apache-2.0", "memory_gib": 5.5, "notice": "Incluído na imagem. Clonagem completa em float32 ou modo econômico bfloat16, escolhido automaticamente quando há pouca RAM livre. O modo econômico pode ser mais lento em CPUs antigas."},
    "whisper-large-v3-turbo": {"name": "Faster-Whisper large-v3-turbo · INT8", "kind": "asr", "repo": "dropbox-dash/faster-whisper-large-v3-turbo", "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf", "runtime": "whisper", "license": "MIT", "notice": "Incluído na imagem. Transcreve sua gravação automaticamente e gera legendas em CPU, com INT8 e quatro threads."},
    "whisper-medium": {"name": "Whisper medium · INT8", "kind": "asr", "repo": "Systran/faster-whisper-medium", "revision": "08e178d48790749d25932bbc082711ddcfdfbc4f", "runtime": "whisper", "license": "MIT", "notice": "Modelo opcional mantido para projetos existentes. Novas transcrições usam large-v3-turbo."},
    "whisper-large-v3": {"name": "Whisper large-v3 · INT8", "kind": "asr", "repo": "Systran/faster-whisper-large-v3", "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478", "runtime": "whisper", "license": "MIT", "notice": "Transcrição opcional com maior custo em CPU e memória. Revise os resultados."},
}

def model_files(ident):
    """Prefer a complete persistent model; volumes never hide the image's models."""
    roots = [(s.DATA / "models", "downloaded"),
             (Path(os.getenv("SAL0_BUNDLED_MODELS", "/opt/sal0-models/models")), "bundled")]
    for root, source in roots:
        folder = root / ident
        try:
            saved = json.loads((folder / "manifest.json").read_text())
            if (not isinstance(saved.get("revision"), str) or not saved["revision"]
                    or not isinstance(saved["files"], dict) or not saved["files"]):
                continue
            sizes = saved.get("file_sizes", {})
            complete = True
            for relative in saved["files"]:
                path = (folder / relative).resolve()
                if (not path.is_relative_to(folder.resolve()) or not path.is_file()
                        or (relative in sizes and path.stat().st_size != sizes[relative])):
                    complete = False
                    break
            if complete:
                return folder, saved, source
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None, {}, "missing"

def models_needed(project):
    if project["mode"] == "asr":
        return [project.get("asr_engine", DEFAULT_ASR_MODEL)]
    engine = project.get("engine", DEFAULT_CLONE_MODEL)
    if "segments" in project and not project.get("automatic_dub") and not any(x.get("pause_ms") is None and not x.get("reaction") for x in project["segments"]):
        return []
    result = [engine]
    if project.get("automatic_dub"):
        result.append(project.get("asr_engine", DEFAULT_ASR_MODEL))
    if engine.startswith("qwen-") and any(
        not segment.get("reaction") and segment.get("character", {}).get("reference")
        and not segment["character"].get("reference_text", "").strip()
        for segment in project.get("segments", []) + ([{"character": project["default_character"]}] if project.get("default_character") else [])
    ):
        result.append(DEFAULT_ASR_MODEL)
    return list(dict.fromkeys(result))

def runtime(engine):
    family = CATALOG[engine].get("runtime")
    if not family:
        return sys.executable
    root = Path(os.getenv("SAL0_ENGINES", "/opt/engines"))
    path = root / family / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(path)

def installed():
    out = []
    for ident, meta in CATALOG.items():
        item = {"id": ident, **meta}
        if ident == "diagnostic":
            item["available"] = bool(shutil.which("espeak-ng") or shutil.which("espeak"))
        else:
            folder, saved, source = model_files(ident)
            item["available"] = folder is not None and Path(runtime(ident)).is_file()
            item["source"] = source
            if saved:
                item["revision"] = saved["revision"]
        item["validation"] = "Não avaliado no A10"
        out.append(item)
    return out

def require(ident, kind):
    item = next((x for x in installed() if x["id"] == ident), None)
    if not item or item["kind"] != kind:
        raise ValueError("Motor incompatível com esta operação.")
    if not item["available"]:
        raise ValueError(f"Modelo ou ambiente {item['name']} não instalado. Consulte Ajustes.")
    return item

