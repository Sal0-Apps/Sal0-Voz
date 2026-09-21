"""Strict, lossless VoiceScript subset and subtitle formats."""
import re


def split_text(text, maximum=350):
    # Prefer sentence/word boundaries, retaining every character (including spaces).
    while len(text) > maximum:
        candidates = list(re.finditer(r"[.!?;]\s+|\s+", text[:maximum + 1]))
        cut = candidates[-1].end() if candidates else maximum
        yield text[:cut]
        text = text[cut:]
    if text:
        yield text


def compile_script(source, language="pt-BR", character_id=None, rate=1.0):
    state = {"language": language, "character_id": character_id, "rate": rate, "volume": 0.0}
    stack = []
    segments = []
    text = []

    def flush():
        if text:
            for part in split_text("".join(text)):
                if part.strip():
                    segments.append({"text": part, **state})
            text.clear()

    i = 0
    while i < len(source):
        if source[i:i+2] in (r"\[", r"\]", r"\\"):
            text.append(source[i+1]); i += 2; continue
        if source[i] != "[":
            text.append(source[i]); i += 1; continue
        end = source.find("]", i)
        if end < 0:
            raise ValueError(f"Tag sem fechamento na posição {i + 1}.")
        tag = source[i+1:end]
        flush()
        if tag.startswith("/"):
            if not stack or stack[-1][0] != tag[1:]:
                raise ValueError(f"Fechamento incompatível [{tag}], posição {i + 1}.")
            _, key, previous = stack.pop()
            state[key] = previous
        elif "=" in tag:
            name, val = tag.split("=", 1)
            if name == "pausa":
                if not re.fullmatch(r"\d+(?:ms|s)", val):
                    raise ValueError("Pausa: use [pausa=450ms] ou [pausa=2s].")
                ms = int(val[:-2]) if val.endswith("ms") else int(val[:-1]) * 1000
                segments.append({"text": "", "pause_ms": ms, **state})
            elif name in ("personagem", "idioma"):
                key = "character_id" if name == "personagem" else "language"
                if name == "idioma" and val not in ("pt-BR", "en-US"):
                    raise ValueError("Idioma: pt-BR ou en-US.")
                state[key] = val
            elif name in ("ritmo", "volume"):
                key = "rate" if name == "ritmo" else "volume"
                number = float(val.replace(",", "."))
                low, high = (0.8, 1.2) if key == "rate" else (-24, 6)
                if not low <= number <= high:
                    raise ValueError(f"{name}: intervalo {low} a {high}.")
                stack.append((name, key, state[key])); state[key] = number
            else:
                raise ValueError(f"Controle [{name}] indisponível nos motores desta versão (posição {i + 1}). Remova-o explicitamente; ele não será falado.")
        else:
            raise ValueError(f"Tag desconhecida [{tag}], posição {i + 1}.")
        i = end + 1
    flush()
    if stack:
        raise ValueError(f"Falta fechar [/{stack[-1][0]}].")
    if not any(x["text"].strip() for x in segments):
        raise ValueError("O roteiro não contém fala.")
    return segments


def timestamp(ms, sep=","):
    ms = round(ms)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{sep}{ms:03}"


def validate_cues(cues):
    previous = -1
    for cue in cues:
        start, end = int(cue["start_ms"]), int(cue["end_ms"])
        if start < 0 or end <= start or start < previous or not cue["text"].strip():
            raise ValueError("Legendas exigem texto, início crescente e fim maior que início.")
        previous = start
    return cues


def subtitles(cues, vtt=False):
    validate_cues(cues)
    sep = "." if vtt else ","
    return ("WEBVTT\n\n" if vtt else "") + "\n\n".join(
        f"{i+1}\n{timestamp(c['start_ms'], sep)} --> {timestamp(c['end_ms'], sep)}\n{c['text']}"
        for i, c in enumerate(cues)) + "\n"


def parse_srt(source):
    cues = []
    for block in re.split(r"\n\s*\n", source.replace("\r", "").lstrip("\ufeff").strip()):
        lines = block.splitlines()
        if not lines:
            continue
        if lines[0].strip().isdigit():
            lines.pop(0)
        match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3}) --> (\d+):(\d{2}):(\d{2})[,.](\d{3})", lines[0].strip())
        if not match or len(lines) < 2:
            raise ValueError("SRT inválido: confira os tempos e o texto de cada bloco.")
        n = list(map(int, match.groups()))
        if any(n[k] >= 60 for k in (1, 2, 5, 6)):
            raise ValueError("Minutos ou segundos inválidos no SRT.")
        start = ((n[0]*60+n[1])*60+n[2])*1000+n[3]
        end = ((n[4]*60+n[5])*60+n[6])*1000+n[7]
        cues.append({"start_ms": start, "end_ms": end, "text": "\n".join(lines[1:])})
    if not cues:
        raise ValueError("SRT vazio.")
    return validate_cues(cues)
