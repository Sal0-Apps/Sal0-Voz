import json
import zipfile
import pytest
from app import storage as s
from scripts.backup import backup, restore

def test_roundtrip(data, tmp_path):
    media = data / "media" / "sample.txt"; media.write_text("reference")
    s.put("character", {"id":"luna","name":"Luna","version":1})
    s.put("session", {"id":"session","expires":99999999999})
    archive = backup(tmp_path / "backup.zip")
    destination = tmp_path / "restored"
    restore(archive, destination)
    assert (destination / "media/sample.txt").read_text() == "reference"
    import sqlite3
    with sqlite3.connect(destination / "app.sqlite") as conn:
        assert conn.execute("select count(*) from records where kind='character'").fetchone()[0] == 1
        assert conn.execute("select count(*) from records where kind='session'").fetchone()[0] == 0

def test_reject_zip_traversal(data, tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", "bad")
        z.writestr("backup-manifest.json", json.dumps({"schema_version":1,"files":{"../escape":"bad"},"models":{}}))
    with pytest.raises(ValueError): restore(archive, tmp_path / "restored")
    assert not (tmp_path / "escape").exists()

def test_safe_path(data):
    with pytest.raises(ValueError): s.safe_path("../escape")

