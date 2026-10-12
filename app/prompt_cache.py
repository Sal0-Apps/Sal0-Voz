"""Only the current voice prompt stays in RAM; full prompts persist per job."""
import hashlib
import json
import os
import pickle
from pathlib import Path
from . import storage as s
from .resources import release_temporary_memory


class PromptCache:
    def __init__(self, directory, engine, dtype, revision=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.profile = (engine, dtype, revision)
        self.key = None
        self.items = None

    def get(self, reference, transcript, build, item_type, torch):
        key = hashlib.sha256(json.dumps([self.profile, reference, transcript], ensure_ascii=False).encode()).hexdigest()
        if self.key == key:
            return self.items
        self.items = None
        self.key = None
        release_temporary_memory()
        path = self.directory / f"{key}.pt"
        meta = path.with_suffix(".json")
        try:
            if json.loads(meta.read_text())["sha256"] != s.digest(path):
                raise ValueError("Cache incompleto")
            records = torch.load(path, map_location="cpu", weights_only=True)
            items = [item_type(**record) for record in records]
        except (OSError, ValueError, KeyError, TypeError, EOFError, RuntimeError, pickle.UnpicklingError) as exc:
            if any(term in str(exc).lower() for term in ("out of memory", "not enough memory", "defaultcpuallocator", "std::bad_alloc")):
                raise
            items = build()
            # Clone the small logical tensors so a view never serializes unused
            # backing storage. Keep reference text, codec, embedding and modes.
            records = [{"ref_code": item.ref_code.detach().clone() if item.ref_code is not None else None,
                        "ref_spk_embedding": item.ref_spk_embedding.detach().clone(),
                        "x_vector_only_mode": item.x_vector_only_mode, "icl_mode": item.icl_mode,
                        "ref_text": item.ref_text} for item in items]
            temporary = path.with_suffix(".partial.pt")
            try:
                torch.save(records, temporary)
                with temporary.open("rb") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                s.atomic_json(meta, {"sha256": s.digest(path)})
            finally:
                temporary.unlink(missing_ok=True)
            del records
        self.key, self.items = key, items
        return items
