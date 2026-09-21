import pytest
from app.script import compile_script, split_text, parse_srt, subtitles

def test_long_text_preserves_all_characters():
    text = ("Capítulo um. Olá, mundo! Uma voz em português.\n" * 2500)
    parts = list(split_text(text))
    assert "".join(parts) == text
    assert all(len(x) <= 351 for x in parts)
    assert len(text) > 100000

def test_controls_do_not_become_spoken_text():
    result = compile_script("[personagem=luna][idioma=pt-BR][ritmo=1.05]Olá![/ritmo][pausa=450ms]Fim.")
    assert result[0]["rate"] == 1.05
    assert result[1]["pause_ms"] == 450
    assert result[2]["rate"] == 1
    assert [x["text"] for x in result] == ["Olá!", "", "Fim."]

@pytest.mark.parametrize("text", ["[reacao=riso]Olá", "[tom=sussurro]Oi[/tom]", "[ritmo=3]Oi[/ritmo]", "[ritmo=1.1]Oi", "[/volume]Oi", "[abc", "[idioma=fr-FR]Salut"])
def test_invalid_directions_fail_explicitly(text):
    with pytest.raises(ValueError):
        compile_script(text)

def test_literal_brackets():
    assert compile_script(r"Leia \[isto\].")[0]["text"] == "Leia [isto]."

def test_srt_roundtrip_and_hours():
    cues = [{"start_ms": 3600123, "end_ms": 3602345, "text": "Olá\nTudo bem?"}]
    assert parse_srt(subtitles(cues)) == cues
    assert "01:00:00.123" in subtitles(cues, True)

@pytest.mark.parametrize("source", ["", "1\n00:00:02,000 --> 00:00:01,000\nErro", "1\n00:99:00,000 --> 01:00:00,000\nErro"])
def test_invalid_subtitles(source):
    with pytest.raises(ValueError): parse_srt(source)

