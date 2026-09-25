"""Mac-versus-Linux differences outside audio: log location, keep-awake, notices."""
import logging

from birdframe import host


def test_linux_log_follows_xdg_state(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "IS_MAC", False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert host.log_path() == tmp_path / "birdframe" / "birdframe.log"
    monkeypatch.delenv("XDG_STATE_HOME")
    assert host.log_path().parts[-4:] == (".local", "state", "birdframe", "birdframe.log")


def test_mac_log_is_in_library_logs(monkeypatch):
    monkeypatch.setattr(host, "IS_MAC", True)
    assert host.log_path().parts[-3:] == ("Library", "Logs", "birdframe.log")


def test_headless_notices_are_log_lines(monkeypatch, caplog):
    monkeypatch.setattr(host, "IS_MAC", False)
    ran = []
    monkeypatch.setattr(host.subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(host.subprocess, "Popen", lambda *a, **k: ran.append(a))
    with caplog.at_level(logging.INFO, logger="birdframe"):
        host.notify("New bird", "First time hearing a Waxwing.")
        host.keep_awake()
    assert ran == []  # no osascript, no caffeinate
    assert "New bird: First time hearing a Waxwing." in caplog.text


def test_mac_notification_quotes_safely(monkeypatch):
    monkeypatch.setattr(host, "IS_MAC", True)
    ran = []
    monkeypatch.setattr(host.subprocess, "run", lambda args, **k: ran.append(args))
    host.notify('Say "hi"', 'back\\slash')
    script = ran[0][2]
    assert 'with title "Say \\"hi\\""' in script
    assert '"back\\\\slash"' in script
