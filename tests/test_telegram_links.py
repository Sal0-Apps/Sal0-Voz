"""Telegram transport is replaced; these tests never contact a bot or chat."""
import pytest
from app import storage as s
from app import telegram


def test_completed_job_only_sends_one_authenticated_link_without_reading_files(data, monkeypatch):
    telegram.save_config({"username":"admin"}, "fake-token-12345", "fake-chat", "https://voz.example/voz/")
    messages=[]
    monkeypatch.setattr(telegram, "send_message", lambda cfg,text:messages.append((cfg,text)))
    monkeypatch.setattr(s, "safe_path", lambda *_:pytest.fail("Output files must never be opened for Telegram"))
    telegram.notify_job({"id":"abc", "owner_username":"admin", "name":"Voz & teste", "status":"completed", "stage":"Concluído",
        "outputs":[{"path":"exports/large.mp4", "name":"large.mp4"},{"path":"exports/voice.wav"}], "elapsed_seconds":30})
    assert len(messages)==1
    assert 'href="https://voz.example/voz/?job=abc"' in messages[0][1]
    assert "Voz &amp; teste" in messages[0][1] and "Abrir resultados" in messages[0][1]


def test_existing_config_preserves_token_and_new_jobs_use_the_app_address(data, monkeypatch):
    telegram.save_config({"username":"admin"}, "fake-token-12345", "fake-chat")
    cfg=telegram.masked({"username":"admin"})
    telegram.save_config({"username":"admin"}, cfg["telegram_token"], "fake-chat", "")
    assert telegram.load_config({"username":"admin"})["telegram_token"]=="fake-token-12345"
    messages=[]; monkeypatch.setattr(telegram,"send_message",lambda cfg,text:messages.append(text))
    telegram.notify_job({"id":"abc", "name":"Voz", "status":"queued", "app_url":"http://voz.server:7886"})
    assert 'href="http://voz.server:7886/?job=abc"' in messages[0]


@pytest.mark.parametrize("url", ["javascript:alert(1)","https://user:password@host", "https://host/?token=secret", "https://host/#x","http://host:bad"])
def test_telegram_address_requires_a_clean_http_address(url):
    with pytest.raises(ValueError): telegram.normalize_url(url)


def test_telegram_settings_and_job_links_keep_login_and_ownership(owner):
    response=owner.put("/api/telegram",json={"telegram_token":"fake-token-12345","telegram_chat_id":"fake-chat","telegram_base_url":"http://voz.server:7886"})
    assert response.status_code==200
    assert "***" in response.json()["telegram_token"]
    assert response.json()["telegram_base_url"]=="http://voz.server:7886"
    assert owner.put("/api/telegram",json={"telegram_base_url":"javascript:bad"}).status_code==400
    owner.post("/api/users",json={"username":"alice","password":"test-password-123","role":"user"})
    owner.post("/api/auth/logout")
    assert owner.post("/api/auth/login",json={"username":"alice","password":"test-password-123"}).status_code==200
    own=s.put("job",{"owner_username":"alice","status":"completed","snapshot":{"text":"private"}})
    other=s.put("job",{"owner_username":"other","status":"completed"})
    response=owner.get("/api/jobs/"+own["id"])
    assert response.status_code==200 and "snapshot" not in response.json()
    assert owner.get("/api/jobs/"+other["id"]).status_code==403
    owner.post("/api/auth/logout")
    assert owner.get("/api/jobs/"+own["id"]).status_code==401
