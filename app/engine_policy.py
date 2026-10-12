"""Choose a complete CPU clone profile according to currently available RAM."""
from .resources import memory_available, cgroup_memory
from .catalog import is_clone

MEMORY_GIB = {
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
        x.get("pause_ms") is None and not x.get("reaction") for x in project["segments"]
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
        options = [(requested, "float32")]
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
            name = "Chatterbox V3 pt-BR" if engine == "chatterbox-pt-br" else "Qwen 1.7B" if engine == "qwen-1.7b" else "Qwen 0.6B"
            name += " · econômico" if dtype == "bfloat16" else " · float32"
            return {"engine": engine, "dtype": dtype, "memory_gib": required,
                    "name": name, "adapted": engine != requested or dtype != "float32"}
    raise MemoryUnavailable(MEMORY_GIB[options[-1]] + 0.25, available_gib)
