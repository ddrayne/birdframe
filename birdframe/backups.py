"""Consistent, atomic SQLite backups with simple retention."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from birdframe.store import Store


@dataclass(frozen=True)
class BackupStatus:
    count: int
    latest: str | None
    bytes: int


def _finish_backup(store: Store, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    try:
        if temporary.exists():
            temporary.unlink()
        store.backup_to(temporary)
        temporary.replace(target)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return target


def prune_backups(backup_dir: Path, keep_days: int, now: datetime) -> int:
    """Delete completed snapshots older than the configured retention."""
    if keep_days <= 0:
        return 0
    cutoff = now - timedelta(days=keep_days)
    removed = 0
    for path in Path(backup_dir).glob("birdframe-*.sqlite"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def create_daily_backup(store: Store, backup_dir: Path, when: datetime,
                        keep_days: int = 30) -> tuple[Path, bool]:
    """Ensure today's restore-ready snapshot exists.

    Returns the path and whether it was newly created. Existing daily snapshots
    are never rewritten, which keeps the 30-second runtime tick cheap.
    """
    target = Path(backup_dir) / f"birdframe-{when:%Y-%m-%d}.sqlite"
    created = False
    if not target.exists():
        _finish_backup(store, target)
        created = True
    prune_backups(Path(backup_dir), keep_days, when)
    return target, created


def create_manual_backup(store: Store, backup_dir: Path,
                         when: datetime) -> Path:
    """Create a separately named on-demand snapshot."""
    target = Path(backup_dir) / f"birdframe-{when:%Y-%m-%d-%H%M%S}.sqlite"
    return _finish_backup(store, target)


def backup_status(backup_dir: Path) -> BackupStatus:
    files = list(Path(backup_dir).glob("birdframe-*.sqlite"))
    files.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0,
               reverse=True)
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return BackupStatus(
        count=len(files),
        latest=files[0].name if files else None,
        bytes=total,
    )
