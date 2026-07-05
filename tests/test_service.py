from pathlib import Path

from birdframe import service


def test_plist_dict_is_wellformed():
    d = service._plist_dict()
    assert d["Label"] == "com.birdframe"
    assert d["ProgramArguments"][1:] == ["run", "birdframe"]
    assert d["RunAtLoad"] is True and d["KeepAlive"] is True
    assert d["StandardOutPath"].endswith("birdframe.log")


def test_make_app_creates_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "APP_PATH", tmp_path / "Birdframe.app")
    monkeypatch.setattr(service, "_write_icns", lambda dest: False)  # skip iconutil in tests
    msg = service.make_app()
    app = tmp_path / "Birdframe.app"
    assert (app / "Contents" / "Info.plist").exists()
    launcher = app / "Contents" / "MacOS" / "birdframe"
    assert launcher.exists()
    body = launcher.read_text()
    assert "run birdframe start" in body and "open" in body
    assert (launcher.stat().st_mode & 0o111)  # executable
    assert "Birdframe.app" in msg
