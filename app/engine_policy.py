"""Choose a complete CPU clone profile according to currently available RAM."""
from .resources import memory_available, cgroup_memory
from .catalog import CATALOG, is_clone

MEMORY_GIB = {
    ("pocket-pt", "float32"): 3.5,
    ("drama3", "q4-bf16"): 8.0,
    ("omnivoice", "float32"): 5.5,
    ("voxcpm2", "float16"): 7.5,
    ("chatterbox-pt-br", "float32"): 6.5,
    ("qwen-1.7b", "float32"): 9.5,
    ("qwen-1.7b", "bfloat16"): 6.0,
    ("qwen-0.6b", "float32"): 5.5,
    ("qwen-0.6b", "bfloat16"): 3.25,
}

class MemoryUnavailable(ValueError):
    def __init__(self, required, available):
        self.required, self.available = required, available
        super().__init__(f"Aguardando RAM livre: {available:.1f} GiB disponíveis; "
                         f"este perfil precisa de cerca de {required:.2f} GiB. "
                         "Libere memória de outras tarefas. O trabalho continuará automaticamente.")

def choose_profile(project, available=None, locked=False, memory_limit=None):
    if project.get("mode") == "asr" or ("segments" in project and not project.get("automatic_dub") and not any(
        x.get("pause_ms") is None for x in project["segments"]
    )):
        return None
    requested = project.get("requested_engine", project.get("engine", "qwen-1.7b"))
    if not is_clone(requested):
        return None
    if available is None and memory_limit is None:
        usage = cgroup_memory()
        memory_limit = usage[0] if usage else None
    available_gib = (memory_available() if available is None else available) / 1024**3
    if locked:
        options = [(project["engine"], project.get("dtype", "float32"))]
    else:
        options = [(requested, CATALOG[requested].get("dtype", "float32"))]
        if project.get("adaptive_memory", True) and (requested, "bfloat16") in MEMORY_GIB:
            options.append((requested, "bfloat16"))
    for index, (engine, dtype) in enumerate(options):
        if not locked and index < len(options)-1 and f"{engine}/{dtype}" in project.get("memory_failed_profiles", []):
            continue
        if (engine, dtype) not in MEMORY_GIB:
            raise ValueError("Perfil de voz incompatível com CPU.")
        required = MEMORY_GIB[engine, dtype]
        # Do not begin an adaptive profile that already consumes nearly the
        # whole container. Leave room for decoding and longer utterances.
        if not locked and project.get("adaptive_memory", True) and memory_limit and required + 0.25 > memory_limit/1024**3 * 0.90:
            continue
        if available_gib >= required + 0.25:
            name = {"pocket-pt": "Pocket PT 24 camadas · 5 passos", "drama3": "Drama 3 experimental · Q4/BF16 · especialistas em disco", "omnivoice": "OmniVoice 0.6B", "voxcpm2": "VoxCPM2 2B", "chatterbox-pt-br": "Chatterbox V3 pt-BR", "qwen-1.7b": "Qwen 1.7B", "qwen-0.6b": "Qwen 0.6B"}[engine]
            if dtype != "q4-bf16":
                name += " · econômico" if dtype == "bfloat16" else " · F16 GGML" if dtype == "float16" else " · float32"
            return {"engine": engine, "dtype": dtype, "memory_gib": required,
                    "name": name, "adapted": engine != requested or dtype != CATALOG[requested].get("dtype", "float32")}
    raise MemoryUnavailable(MEMORY_GIB[options[-1]] + 0.25, available_gib)
