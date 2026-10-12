"""Interpretation instructions supported by VoxCPM2 cloning."""
STYLES = {
    "natural": ("Natural · seguir a gravação", ""),
    "happy": ("Alegre", "cheerful, joyful tone"),
    "sad": ("Triste", "sad, subdued tone"),
    "angry": ("Com raiva", "angry, forceful tone"),
    "afraid": ("Com medo", "afraid, tense tone"),
    "surprised": ("Surpreso", "surprised, astonished tone"),
    "calm": ("Calmo", "calm, relaxed tone"),
    "excited": ("Entusiasmado", "excited, enthusiastic tone"),
    "affectionate": ("Carinhoso", "warm, affectionate tone"),
    "serious": ("Sério", "serious, firm tone"),
    "whisper": ("Sussurrando", "soft whispered delivery"),
    "shouting": ("Gritando", "loud, shouted delivery"),
}

def instruction(ident):
    try:
        return STYLES[ident][1]
    except KeyError:
        raise ValueError("Escolha uma interpretação disponível.") from None
