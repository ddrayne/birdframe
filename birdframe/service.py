"""Manage birdframe as a macOS background service (LaunchAgent), and build a
double-clickable app — so running it forever is one command, not launchctl
incantations.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

LABEL = "com.birdframe"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "birdframe.log"
REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = Path.home() / "Applications" / "Birdframe.app"
DASHBOARD_URL = "http://localhost:8355"


def _uv() -> str:
    return shutil.which("uv") or "/opt/homebrew/bin/uv"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _plist_dict() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [_uv(), "run", "birdframe"],
        "WorkingDirectory": str(REPO_ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    }


def install() -> str:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "wb") as fh:
        plistlib.dump(_plist_dict(), fh)
    _launchctl("bootout", str(PLIST_PATH), check=False)  # in case it's already loaded
    _launchctl("bootstrap", _domain(), str(PLIST_PATH), check=False)
    _launchctl("enable", f"{_domain()}/{LABEL}", check=False)
    return f"Installed and started. Logs: {LOG_PATH}\nDashboard: {DASHBOARD_URL}"


def uninstall() -> str:
    _launchctl("bootout", str(PLIST_PATH), check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return "birdframe service removed (your data and settings are untouched)."


def start() -> str:
    if not PLIST_PATH.exists():
        return install()
    _launchctl("bootstrap", _domain(), str(PLIST_PATH), check=False)
    return "Started."


def stop() -> str:
    _launchctl("bootout", str(PLIST_PATH), check=False)
    return "Stopped."


def restart() -> str:
    _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}", check=False)
    return "Restarted."


def is_running() -> bool:
    out = _launchctl("list", capture=True) or ""
    return LABEL in out


def status() -> str:
    installed = PLIST_PATH.exists()
    running = is_running()
    lines = [
        f"  service installed : {'yes' if installed else 'no'}",
        f"  running           : {'yes' if running else 'no'}",
        f"  dashboard         : {DASHBOARD_URL}",
        f"  logs              : {LOG_PATH}",
    ]
    if not installed:
        lines.append("\n  run 'birdframe install' to run it in the background at login")
    return "birdframe service\n" + "\n".join(lines)


def _launchctl(*args, check=True, capture=False):
    try:
        r = subprocess.run(["launchctl", *args], check=check, capture_output=True, text=True)
        return r.stdout if capture else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Double-clickable app bundle
# --------------------------------------------------------------------------
def make_app() -> str:
    """Create ~/Applications/Birdframe.app — opening it ensures the service is
    running and opens the dashboard. A friendly, Spotlight-able launcher."""
    contents = APP_PATH / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    for d in (macos, resources):
        d.mkdir(parents=True, exist_ok=True)

    launcher = macos / "birdframe"
    launcher.write_text(
        "#!/bin/bash\n"
        f'cd "{REPO_ROOT}"\n'
        f'"{_uv()}" run birdframe start >/dev/null 2>&1\n'
        f'sleep 1\n'
        f'open "{DASHBOARD_URL}"\n'
    )
    launcher.chmod(0o755)

    info = {
        "CFBundleName": "Birdframe",
        "CFBundleDisplayName": "Birdframe",
        "CFBundleIdentifier": "com.birdframe.launcher",
        "CFBundleVersion": "1.0",
        "CFBundleExecutable": "birdframe",
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "birdframe",
        "LSUIElement": False,
    }
    with open(contents / "Info.plist", "wb") as fh:
        plistlib.dump(info, fh)

    icon_ok = _write_icns(resources / "birdframe.icns")
    note = "" if icon_ok else " (default icon — iconutil unavailable)"
    return f"Created {APP_PATH}{note}\nFind it in Spotlight or ~/Applications."


def _write_icns(dest: Path) -> bool:
    """Render the birdframe icon into a macOS .icns via iconutil."""
    try:
        from birdframe.icon import render_icon
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "birdframe.iconset"
            iconset.mkdir()
            for size in (16, 32, 64, 128, 256, 512):
                (iconset / f"icon_{size}x{size}.png").write_bytes(render_icon(size))
                (iconset / f"icon_{size}x{size}@2x.png").write_bytes(render_icon(size * 2))
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)],
                           check=True, capture_output=True)
        return True
    except Exception:
        return False
