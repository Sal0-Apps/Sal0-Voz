import json
import os
import shutil
import sys
from pathlib import Path
from . import storage as s

DEFAULT_CLONE_MODEL = "qwen-1.7b"
DEFAULT_ASR_MODEL = "whisper-large-v3-turbo"
DEFAULT_MODELS = (DEFAULT_CLONE_MODEL, DEFAULT_ASR_MODEL)

CATALOG = {
    "diagnostic": {"name": "Voz de diagnóstico", "kind": "tts", "clone": False, "license": "GPL-3.0 (eSpeak NG)", "notice": "Voz sintética simples para testar o app; não representa a qualidade final."},
    "pocket-pt": {
        "name": "Qualidade em CPU · Pocket TTS PT 24 camadas", "kind": "tts", "clone": True,
        "reference_text": False, "reference_seconds": 30, "runtime": "omnivoice",
        "languages": ["pt-BR"], "sample_rate": 24000, "fixed_precision": True,
        "repo": "kyutai/pocket-tts", "revision": "2dd944b099d06bb9edbd221fef138685711d9bf0",
        "files": ["README.md", "languages/portuguese_24l/model.safetensors", "languages/portuguese_24l/tokenizer.json"],
        "license": "CC-BY-4.0 (pesos); MIT (código)", "memory_gib": 3.5, "download_gib": 0.63,
        "gated": True, "access_url": "https://huggingface.co/kyutai/pocket-tts",
        "notice": "Português, 24 camadas, CPU FP32 sem quantização, cinco passos de amostragem e saída de 24 bits. Usa a gravação para clonar a voz, sem exigir transcrição. Tenta a fala inteira e mantém o perfil na retomada. Para baixar os pesos com clonagem, aceite o acesso na página do Pocket TTS no Hugging Face e salve um token de leitura nos ajustes abaixo. Qualidade e velocidade precisam ser avaliadas com sua voz.",
    },
    "drama3": {
        "name": "Fidelidade experimental · Drama 3 CPU Q4", "kind": "tts", "clone": True,
        "reference_text": True, "reference_seconds": 30, "reference_hz": 44100,
        "runtime": "omnivoice", "runtime_binary": "drama3/bin/audiocpp_cli", "dtype": "q4-bf16",
        "sample_rate": 44100, "fixed_precision": True, "experimental": True,
        "repo": "Jmica/Drama-3-GGUF", "revision": "17a5b40c5dc2c2be986f5371a7e650108b828e29",
        "files": ["README.md", "LICENSE", "NOTICE", "drama-3-backbone-8bit-F32-routers-BF16-embed-head-experts-Q4_K_S.gguf"],
        "license": "Fish Audio Community License v1.0 (pesos); Apache-2.0 (motor)", "memory_gib": 8.0, "download_gib": 23.88,
        "notice": "Experimental para CPU: modelo completo de 35B com especialistas Q4, roteadores FP32, embedding/cabeça BF16 e áudio F16. Não é o checkpoint original sem conversão. O motor lê especialistas pelo disco com cache de oito por camada; exige cerca de 24 GiB em disco e pode ser extremamente lento, especialmente em HD. Saída de 24 bits. Mantém o limite de RAM e aguarda memória se necessário; não há garantia de caber em toda fala nem de igualar a fidelidade do original. Nenhuma troca automática para outro modelo.",
    },
    "drama3-original": {
        "name": "Drama 3 original · pesos para GPU", "kind": "weights", "clone": False,
        "runtime": "base", "download_only": True,
        "repo": "fishaudio/drama-3", "revision": "dd64a85cd82e9521f7202610ede97b367fc83946",
        "license": "Fish Audio Community License v1.0", "download_gib": 38.66,
        "notice": "Download opcional do checkpoint oficial FP8/BF16, sem a quantização GGUF de CPU, para comparar fidelidade em um servidor com GPU compatível. Cerca de 39 GiB em disco; somente os pesos do motor ocupam aproximadamente 37 GB na GPU. Este pacote não aparece como motor de geração neste servidor de 10 GiB. O Drama 3 CPU experimental acima é um download separado e identificado como Q4.",
    },
    "omnivoice": {
        "name": "Fidelidade e expressão · OmniVoice 0.6B", "kind": "tts", "clone": True,
        "reference_text": True, "reference_seconds": 10, "runtime": "omnivoice",
        "repo": "k2-fsa/OmniVoice", "revision": "c5fdb5ccb189668d56333f77ba2629f4cd7535f4",
        "files": ["README.md", "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "audio_tokenizer/LICENSE", "audio_tokenizer/README.md", "audio_tokenizer/config.json", "audio_tokenizer/model.safetensors", "audio_tokenizer/preprocessor_config.json"],
        "license": "CC-BY-NC (pesos); Apache-2.0 (código)", "memory_gib": 5.5, "download_gib": 3.1,
        "notice": "Download opcional de cerca de 3,1 GiB. Qualidade máxima: CPU float32, 64 passos e áudio de 24 bits. Preserva as pausas e tenta a fala inteira; divide somente por sobrecarga ou limite do modelo. Leva mais tempo que o perfil anterior. Os pesos permitem uso não comercial. Qualidade, tempo e RAM real precisam ser avaliados no seu servidor.",
    },
    "voxcpm2": {
        "name": "Clonagem e emoções · VoxCPM2 2B", "kind": "tts", "clone": True,
        "reference_text": True, "reference_hz": 16000, "runtime": "base",
        "runtime_binary": "voxcpm/bin/voxcpm2-cli", "dtype": "float16", "style_control": True, "sample_rate": 48000,
        "repo": "DennisHuang648/VoxCPM2-GGUF", "revision": "169f64d8b98bbaab1761e4ca3a83e6af653456cc",
        "files": ["README.md", "VoxCPM2-BaseLM-F16.gguf", "VoxCPM2-Acoustic-F16.gguf"],
        "license": "Apache-2.0 (pesos); MIT (motor)", "memory_gib": 7.5, "download_gib": 4.8,
        "notice": "Download opcional de cerca de 4,8 GiB. Pesos F16 completos, sem quantização de 4/8 bits. Motor GGML em CPU, clonagem com áudio e transcrição e orientação de emoção/estilo. Dez passos de difusão e saída de 48 kHz. Pode ser lento; qualidade e consumo real precisam ser avaliados no seu servidor.",
    },
    "chatterbox-pt-br": {
        "name": "Expressiva · Chatterbox V3 pt-BR", "kind": "tts", "clone": True,
        "reference_text": False, "languages": ["pt-BR"], "expressiveness": True,
        "repo": "ResembleAI/Chatterbox-Multilingual-pt-br",
        "revision": "b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d",
        "files": ["README.md", "t3_pt_br.safetensors", "s3gen_v3.safetensors", "grapheme_mtl_merged_expanded_v1.json"],
        "companions": [{"repo": "ResembleAI/chatterbox", "revision": "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18", "files": ["ve.safetensors"]}],
        "runtime": "chatterbox", "license": "MIT", "memory_gib": 6.5, "download_gib": 3.0,
        "notice": "Download opcional de cerca de 3 GiB. Especializado em português brasileiro, com clonagem e ajuste de expressividade. CPU float32; reserva inicial de 6,5 GiB, sujeita ao consumo real. Dispensa a transcrição da referência. A qualidade e o tempo precisam ser avaliados no seu servidor.",
    },
    "qwen-1.7b": {"name": "Maior fidelidade · Qwen 1.7B", "kind": "tts", "clone": True, "reference_text": True, "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "revision": "fd4b254389122332181a7c3db7f27e918eec64e3", "runtime": "qwen", "license": "Apache-2.0", "memory_gib": 9.5, "notice": "Prioriza fidelidade em CPU, com pesos em float32. Mais lento e exige cerca de 9,5 GiB livres; a qualidade depende da gravação."},
    "qwen-0.6b": {"name": "Mais leve · Qwen 0.6B", "kind": "tts", "clone": True, "reference_text": True, "repo": "Qwen/Qwen3-TTS-12Hz-0.6B-Base", "revision": "5d83992436eae1d760afd27aff78a71d676296fc", "runtime": "qwen", "license": "Apache-2.0", "memory_gib": 5.5, "notice": "Download opcional no servidor, salvo na pasta de dados. Clonagem completa em float32 ou modo econômico bfloat16, usando o modo econômico do mesmo modelo quando há pouca RAM livre. O modo econômico pode ser mais lento em CPUs antigas."},
    "whisper-large-v3-turbo": {"name": "Faster-Whisper large-v3-turbo · INT8", "kind": "asr", "repo": "dropbox-dash/faster-whisper-large-v3-turbo", "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf", "runtime": "whisper", "license": "MIT", "notice": "Preparado automaticamente após iniciar o aplicativo e salvo na pasta de dados. Transcreve sua gravação e gera legendas em CPU, com INT8 e quatro threads."},
    "whisper-medium": {"name": "Whisper medium · INT8", "kind": "asr", "repo": "Systran/faster-whisper-medium", "revision": "08e178d48790749d25932bbc082711ddcfdfbc4f", "runtime": "whisper", "license": "MIT", "notice": "Modelo opcional mantido para projetos existentes. Novas transcrições usam large-v3-turbo."},
    "whisper-large-v3": {"name": "Whisper large-v3 · INT8", "kind": "asr", "repo": "Systran/faster-whisper-large-v3", "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478", "runtime": "whisper", "license": "MIT", "notice": "Transcrição opcional com maior custo em CPU e memória. Revise os resultados."},
}

def is_clone(ident):
    return bool(CATALOG.get(ident, {}).get("clone"))

def needs_reference_text(ident, voice_style="natural", reaction=False):
    if ident == "voxcpm2" and (voice_style != "natural" or reaction):
        return False
    return bool(CATALOG.get(ident, {}).get("reference_text"))

def model_files(ident):
    """Use persistent downloads, retaining support for older custom model bundles."""
    roots = [(s.DATA / "models", "downloaded"),
             (Path(os.getenv("SAL0_BUNDLED_MODELS", "/opt/sal0-models/models")), "bundled")]
    for root, source in roots:
        folder = root / ident
        try:
            saved = json.loads((folder / "manifest.json").read_text())
            if (not isinstance(saved, dict) or not isinstance(saved.get("revision"), str) or not saved["revision"]
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
    if "segments" in project and not project.get("automatic_dub") and not any(x.get("pause_ms") is None for x in project["segments"]):
        return []
    result = [engine]
    if project.get("automatic_dub"):
        result.append(project.get("asr_engine", DEFAULT_ASR_MODEL))
    if any(
        segment.get("pause_ms") is None and needs_reference_text(engine, project.get("voice_style", "natural"), bool(segment.get("reaction")))
        and segment.get("character", {}).get("reference")
        and not segment["character"].get("reference_text", "").strip()
        for segment in project.get("segments", []) + ([{"character": project["default_character"]}] if project.get("default_character") else [])
    ):
        result.append(DEFAULT_ASR_MODEL)
    return list(dict.fromkeys(result))

def runtime(engine):
    family = CATALOG[engine].get("runtime")
    if not family or family == "base":
        return sys.executable
    root = Path(os.getenv("SAL0_ENGINES", "/opt/engines"))
    path = root / family / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(path)

def runtime_binary(engine):
    relative = CATALOG[engine].get("runtime_binary")
    return Path(os.getenv("SAL0_ENGINES", "/opt/engines")) / relative if relative else None

def installed():
    out = []
    for ident, meta in CATALOG.items():
        item = {"id": ident, **meta}
        if ident == "diagnostic":
            item["available"] = bool(shutil.which("espeak-ng") or shutil.which("espeak"))
        else:
            folder, saved, source = model_files(ident)
            item["available"] = folder is not None and Path(runtime(ident)).is_file()
            binary = runtime_binary(ident)
            if binary is not None:
                item["available"] = item["available"] and binary.is_file() and os.access(binary, os.X_OK)
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

