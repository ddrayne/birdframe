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
    monkeypatch.setattr(service, "IS_MAC", True)
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


def _linux(monkeypatch, tmp_path, calls, linger=True):
    monkeypatch.setattr(service, "IS_MAC", False)
    monkeypatch.setattr(service, "UNIT_PATH", tmp_path / "systemd" / "user" / "birdframe.service")
    monkeypatch.setattr(service, "LOG_PATH", tmp_path / "state" / "birdframe.log")
    monkeypatch.setattr(service, "_lingering", lambda: linger)

    def systemctl(*args, capture=False):
        calls.append(args)
        return "active\n" if capture else ""
    monkeypatch.setattr(service, "_systemctl", systemctl)


def test_systemd_unit_restarts_forever_and_logs_like_launchd(monkeypatch):
    monkeypatch.setattr(service, "_uv", lambda: "/home/pi/.local/bin/uv")
    unit = service._unit_text()
    assert 'ExecStart="/home/pi/.local/bin/uv" run birdframe' in unit
    assert f"WorkingDirectory={service.REPO_ROOT}" in unit
    assert "Restart=always" in unit and "StartLimitIntervalSec=0" in unit
    assert f"StandardOutput=append:{service.LOG_PATH}" in unit
    assert f"StandardError=append:{service.LOG_PATH}" in unit
    assert "WantedBy=default.target" in unit


def test_unit_values_are_escaped():
    assert service._unit_quote("/a b/100%") == '"/a b/100%%"'
    assert service._unit_quote('say "hi"') == '"say \\"hi\\""'
    assert service._unit_quote("/opt/$x/uv", command=True) == '"/opt/$$x/uv"'
    assert service._unit_quote("PATH=/opt/$x") == '"PATH=/opt/$x"'  # no expansion there


def test_systemd_install_writes_the_unit_and_starts_it(tmp_path, monkeypatch):
    calls = []
    _linux(monkeypatch, tmp_path, calls)
    message = service.install()
    assert service.UNIT_PATH.read_text() == service._unit_text()
    assert service.LOG_PATH.parent.is_dir()
    assert calls == [("daemon-reload",), ("enable", "birdframe.service"),
                     ("restart", "birdframe.service")]
    assert "Installed and started" in message
    assert "enable-linger" not in message


def test_systemd_install_says_how_to_start_at_boot(tmp_path, monkeypatch):
    calls = []
    _linux(monkeypatch, tmp_path, calls, linger=False)
    monkeypatch.setattr(service.subprocess, "run", lambda *a, **k: None)
    assert "sudo loginctl enable-linger" in service.install()


def test_systemd_install_reports_a_failure(tmp_path, monkeypatch):
    _linux(monkeypatch, tmp_path, [])
    monkeypatch.setattr(service, "_systemctl",
                        lambda *args, capture=False: "Failed to connect to bus")
    message = service.install()
    assert "could not start it: Failed to connect to bus" in message


def test_systemd_status_and_uninstall(tmp_path, monkeypatch):
    calls = []
    _linux(monkeypatch, tmp_path, calls)
    service.install()
    assert service.is_running()
    report = service.status()
    assert "service installed : yes" in report and "running           : yes" in report
    assert ".local:8355" in report
    service.uninstall()
    assert not service.UNIT_PATH.exists()
    assert ("disable", "--now", "birdframe.service") in calls


def test_make_app_is_mac_only(monkeypatch):
    monkeypatch.setattr(service, "IS_MAC", False)
    assert "macOS" in service.make_app()
