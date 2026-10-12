"""Safe download names and atomic numbering across jobs and server restarts."""
import re
from . import storage as s

def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', " ", value)
    value = " ".join(value.split()).strip(" .")[:160].rstrip(" .")
    value = re.sub(r"\.(wav|flac|mp3|opus|mp4|srt|vtt)$", "", value, flags=re.I).rstrip(" .")
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])", value):
        value = "Áudio " + value
    return value

def output_name(project, username):
    supplied = safe_name(project.get("audio_name", ""))
    if supplied:
        return supplied
    character = project.get("default_character") or next((x.get("character") for x in project.get("segments", []) if x.get("character")), None)
    voice = safe_name(character["name"]) if character else ("Legendas" if project["mode"] == "asr" else "Voz simples" if project["engine"] == "diagnostic" else "Reações")
    voice = voice or "Voz"
    key = "audio-sequence:" + username + ":" + str(project.get("character_id") or voice)
    with s.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        number = int(row[0]) + 1 if row else 1
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(number)))
    return f"{voice} {number}"
