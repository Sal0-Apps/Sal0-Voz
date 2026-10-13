"""Generate nonverbal cues with the selected voice; no recording fallback."""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / "assets" / "reactions"

# Only documented native symbols are sent to the matching model. Other cues
# use short vocalizations, never the display name or an invented English tag.
VOCALIZATIONS = {
    "risada": "Ha, ha, ha!", "risada_curta": "Ha!", "gargalhada": "Ha, ha, ha, ha!",
    "grito": "Aaaah!", "dor": "Ah!", "dor_forte": "Aaah!",
    "gemido": "Ah... mmh...", "gemido_longo": "Aah... mmh... aah...",
    "grunhido": "Ugh!", "esforco": "Hnn... ah!", "esforco_curto": "Hnn!",
    "espanto": "Oh!", "surpresa": "Oh!", "resmungo": "Hmm...",
    "duvida": "Hum?", "susto": "Ah!", "choro": "Ah... ah...",
    "respiracao": "Haa...", "respiracao_leve": "Hah...",
    "respiracao_ofegante": "Hah, hah, hah...", "respiracao_medo": "Ah... hah...",
    "suspiro": "Ah...", "suspiro_longo": "Haa...",
    "bocejo": "Aaah...", "bocejo_longo": "Aaaah...",
    "tosse": "Cof!", "tosse_forte": "Cof, cof!", "fungada": "Hmm...",
    "shh": "Shhh...", "assobio": "Fiu, fiu!", "ronco": "Hrrr...",
    "arroto": "Uurp...", "espirro": "Atchim!",
}
OMNIVOICE_TAGS = {
    "risada": "[laughter]", "risada_curta": "[laughter]", "gargalhada": "[laughter]",
    "suspiro": "[sigh]", "suspiro_longo": "[sigh]", "duvida": "[question-en]",
    "espanto": "[surprise-ah]", "surpresa": "[surprise-oh]", "susto": "[surprise-ah]",
    "resmungo": "[dissatisfaction-hnn]",
}
VOXCPM_TAGS = {
    "risada": "[laughing]", "risada_curta": "[laughing]", "gargalhada": "[laughing]",
    "suspiro": "[sigh]", "suspiro_longo": "[sigh]", "duvida": "[uhm]",
    "surpresa": "[surprise-wa]", "espanto": "[surprise-yo]",
    "resmungo": "[dissatisfaction-hnn]", "shh": "[shh]",
}
NATIVE_TAGS = {"omnivoice": OMNIVOICE_TAGS, "voxcpm2": VOXCPM_TAGS}

def native_models(ident):
    return [engine for engine, tags in NATIVE_TAGS.items() if ident in tags]

@lru_cache(maxsize=1)
def catalog():
    old = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    return [{"id": item["id"], "name": item["name"], "category": item["category"],
             "native_models": native_models(item["id"]), "generation": "selected_voice"}
            for item in old]

def reaction(ident):
    found = next((item for item in catalog() if item["id"] == ident), None)
    if found is None:
        raise ValueError(f"Reação desconhecida: {ident}. Escolha uma opção do editor Detalhado.")
    return found

def synthesis_text(ident, engine, language="pt-BR"):
    reaction(ident)
    tag = NATIVE_TAGS.get(engine, {}).get(ident)
    if tag:
        return tag
    text = VOCALIZATIONS[ident]
    if language == "en-US":
        text = {"duvida": "Hmm?", "tosse": "Ahem!", "tosse_forte": "Ahem, ahem!",
                "espirro": "Achoo!"}.get(ident, text)
    return text

def render_policy(project, segment):
    # A retry must not reuse a reaction recorded by another speaker, or a
    # VoxCPM continuation that has already spoken a style instruction.
    if segment.get("reaction") or (project["engine"] == "voxcpm2" and
                                    project.get("voice_style", "natural") != "natural"):
        return {"version": 1, "engine": project["engine"], "reaction": segment.get("reaction"),
                "style": project.get("voice_style", "natural")}
    return None

def caption(segment):
    return "[" + reaction(segment["reaction"])["name"].lower() + "]" if segment.get("reaction") else segment["text"].strip()
