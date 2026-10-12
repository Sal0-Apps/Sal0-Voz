"""Bundled, licensed nonverbal recordings; never send reaction labels to TTS."""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / "assets" / "reactions"

@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))

def reaction(ident):
    found = next((item for item in catalog() if item["id"] == ident), None)
    if found is None:
        raise ValueError(f"Reação desconhecida: {ident}. Escolha uma opção do editor Detalhado.")
    return found

def reaction_file(ident):
    return ROOT / reaction(ident)["file"]

def caption(segment):
    return "[" + reaction(segment["reaction"])["name"].lower() + "]" if segment.get("reaction") else segment["text"].strip()
