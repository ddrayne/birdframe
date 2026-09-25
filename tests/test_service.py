import plistlib
import sys
from pathlib import Path

import pytest

from birdframe import service


def test_plist_dict_is_wellformed():
    d = service._plist_dict()
    assert d["Label"] == "com.birdframe"
    assert d["ProgramArguments"][1:] == ["run", "birdframe"]
    assert d["RunAtLoad"] is True and d["KeepAlive"] is True
    assert d["StandardOutPath"].endswith("birdframe.log")


@pytest.mark.skipif(sys.platform != "darwin", reason="compiles a macOS launcher with clang")
def test_make_app_creates_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "APP_PATH", tmp_path / "Birdframe.app")
    monkeypatch.setattr(service, "_write_icns", lambda dest: False)  # skip iconutil in tests

    # A previous implementation wrote into an existing Safari web-app bundle,
    # leaving its signature and resources behind.
    stale = tmp_path / "Birdframe.app" / "Contents"
    (stale / "_CodeSignature").mkdir(parents=True)
    (stale / "_CodeSignature" / "CodeResources").write_text("stale")
    (stale / "Resources").mkdir()
    (stale / "Resources" / "ApplicationIcon.icns").write_text("stale")

    msg = service.make_app()
    app = tmp_path / "Birdframe.app"
    assert (app / "Contents" / "Info.plist").exists()
    launcher = app / "Contents" / "MacOS" / "birdframe"
    assert launcher.exists()
    # Thin and fat Mach-O magic values, in either byte order.
    assert launcher.read_bytes()[:4] in {
        b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
    }
    assert (launcher.stat().st_mode & 0o111)  # executable
    with open(app / "Contents" / "Info.plist", "rb") as fh:
        assert plistlib.load(fh)["CFBundleIdentifier"] == "com.birdframe.launcher"
    assert not (app / "Contents" / "Resources" / "ApplicationIcon.icns").exists()
    assert (app / "Contents" / "_CodeSignature" / "CodeResources").exists()
    assert (app / "Contents" / "_CodeSignature" / "CodeResources").read_text() != "stale"
    assert "Birdframe.app" in msg


def test_install_builds_app_before_bootstrapping(tmp_path, monkeypatch):
    plist = tmp_path / "LaunchAgents" / "com.birdframe.plist"
    log = tmp_path / "Logs" / "birdframe.log"
    events = []
    monkeypatch.setattr(service, "PLIST_PATH", plist)
    monkeypatch.setattr(service, "LOG_PATH", log)
    monkeypatch.setattr(service, "make_app", lambda: events.append("make-app"))
    monkeypatch.setattr(
        service,
        "_launchctl",
        lambda *args, **kwargs: events.append(args),
    )

    service.install()

    assert events == [
        "make-app",
        ("bootout", service._job()),
        ("bootstrap", service._domain(), str(plist)),
        ("enable", service._job()),
    ]
    with open(plist, "rb") as fh:
        installed = plistlib.load(fh)
    assert installed["ProgramArguments"][1:] == ["run", "birdframe"]
