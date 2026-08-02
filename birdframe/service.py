"""Manage birdframe as a macOS background service (LaunchAgent), and build a
double-clickable app — so running it forever is one command, not launchctl
incantations.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tempfile
import uuid
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


def _job() -> str:
    return f"{_domain()}/{LABEL}"


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
    # Keep the friendly launcher in sync with the installed service.
    make_app()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "wb") as fh:
        plistlib.dump(_plist_dict(), fh)
    _launchctl("bootout", _job(), check=False)  # in case it's already loaded
    _launchctl("bootstrap", _domain(), str(PLIST_PATH), check=False)
    _launchctl("enable", f"{_domain()}/{LABEL}", check=False)
    return f"Installed and started. Logs: {LOG_PATH}\nDashboard: {DASHBOARD_URL}"


def uninstall() -> str:
    _launchctl("bootout", _job(), check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return "birdframe service removed (your data and settings are untouched)."


def start() -> str:
    if not PLIST_PATH.exists():
        return install()
    _launchctl("bootstrap", _domain(), str(PLIST_PATH), check=False)
    return "Started."


def stop() -> str:
    _launchctl("bootout", _job(), check=False)
    return "Stopped."


def restart() -> str:
    _launchctl("kickstart", "-k", _job(), check=False)
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
def _c_string(value: str) -> str:
    """Encode arbitrary UTF-8 text as adjacent C string literals."""
    return "".join(f'"\\x{byte:02x}"' for byte in value.encode("utf-8")) or '""'


def _launcher_source() -> str:
    """A native launcher keeps LaunchServices from mistaking a script-only
    app bundle for an unsupported Intel application.
    """
    uv = _c_string(_uv())
    repo_root = _c_string(str(REPO_ROOT))
    dashboard_url = _c_string(DASHBOARD_URL)
    return f"""\
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static int run(const char *path, char *const argv[]) {{
    posix_spawn_file_actions_t actions;
    if (posix_spawn_file_actions_init(&actions) != 0) return 1;
    if (posix_spawn_file_actions_addopen(
            &actions, STDOUT_FILENO, "/dev/null", O_WRONLY, 0) != 0 ||
        posix_spawn_file_actions_addopen(
            &actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0) != 0) {{
        posix_spawn_file_actions_destroy(&actions);
        return 1;
    }}

    pid_t pid;
    int error = posix_spawn(&pid, path, &actions, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&actions);
    if (error != 0) return error;

    int status;
    while (waitpid(pid, &status, 0) == -1) {{
        if (errno != EINTR) return 1;
    }}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}}

int main(void) {{
    static const char uv[] = {uv};
    static const char repo_root[] = {repo_root};
    static const char dashboard_url[] = {dashboard_url};

    if (chdir(repo_root) != 0) return 1;

    char *start_argv[] = {{
        (char *)uv, "run", "birdframe", "start", NULL
    }};
    int status = run(uv, start_argv);
    if (status != 0) return status;

    sleep(1);
    char *open_argv[] = {{
        "/usr/bin/open", (char *)dashboard_url, NULL
    }};
    return run("/usr/bin/open", open_argv);
}}
"""


def _compile_launcher(dest: Path) -> None:
    compiler = shutil.which("clang") or "/usr/bin/clang"
    source = dest.with_suffix(".c")
    source.write_text(_launcher_source())
    try:
        subprocess.run(
            [compiler, "-std=c11", "-Os", "-Wall", "-Wextra", "-Werror",
             "-mmacosx-version-min=11.0", "-o", str(dest), str(source)],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise RuntimeError(f"could not build the native app launcher: {detail}") from exc
    finally:
        source.unlink(missing_ok=True)


def _replace_bundle(built_app: Path) -> None:
    """Replace APP_PATH atomically, rolling back if the final rename fails."""
    backup: Path | None = None
    if APP_PATH.exists() or APP_PATH.is_symlink():
        backup = APP_PATH.parent / f".{APP_PATH.name}.backup-{uuid.uuid4().hex}"
        APP_PATH.rename(backup)
    try:
        built_app.rename(APP_PATH)
    except Exception:
        if backup is not None:
            backup.rename(APP_PATH)
        raise
    if backup is not None:
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup)
        else:
            backup.unlink()


def make_app() -> str:
    """Create ~/Applications/Birdframe.app — opening it ensures the service is
    running and opens the dashboard. A friendly, Spotlight-able launcher."""
    APP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix=".birdframe-build-", dir=APP_PATH.parent) as tmp:
        built_app = Path(tmp) / APP_PATH.name
        contents = built_app / "Contents"
        macos = contents / "MacOS"
        resources = contents / "Resources"
        for directory in (macos, resources):
            directory.mkdir(parents=True)

        launcher = macos / "birdframe"
        _compile_launcher(launcher)

        info = {
            "CFBundleName": "Birdframe",
            "CFBundleDisplayName": "Birdframe",
            "CFBundleIdentifier": "com.birdframe.launcher",
            "CFBundleVersion": "1.0",
            "CFBundleExecutable": "birdframe",
            "CFBundlePackageType": "APPL",
            "CFBundleIconFile": "birdframe",
            "LSMinimumSystemVersion": "11.0",
            "LSUIElement": False,
        }
        with open(contents / "Info.plist", "wb") as fh:
            plistlib.dump(info, fh)

        icon_ok = _write_icns(resources / "birdframe.icns")
        subprocess.run(
            ["codesign", "--force", "--sign", "-", "--identifier",
             "com.birdframe.launcher", str(built_app)],
            check=True, capture_output=True, text=True,
        )
        _replace_bundle(built_app)

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
