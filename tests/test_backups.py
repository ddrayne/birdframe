import os
import sqlite3
from datetime import datetime

from birdframe.backups import (
    backup_status, create_daily_backup, create_manual_backup, prune_backups,
)
from birdframe.store import Detection, Store


def test_daily_backup_is_consistent_and_idempotent(tmp_path):
    store = Store(tmp_path / "live.sqlite")
    store.add_detection(Detection(
        datetime(2026, 7, 13, 6), "Erithacus rubecula", "European Robin", .9))
    backup_dir = tmp_path / "backups"

    path, created = create_daily_backup(
        store, backup_dir, datetime(2026, 7, 13, 12), keep_days=30)
    assert created is True
    assert path.name == "birdframe-2026-07-13.sqlite"
    assert not list(backup_dir.glob("*.partial"))
    with sqlite3.connect(path) as copied:
        assert copied.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert copied.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 1

    # Later detections do not rewrite the day's restore point.
    store.add_detection(Detection(
        datetime(2026, 7, 13, 7), "Turdus merula", "Eurasian Blackbird", .9))
    same, created_again = create_daily_backup(
        store, backup_dir, datetime(2026, 7, 13, 18), keep_days=30)
    assert same == path and created_again is False
    with sqlite3.connect(path) as copied:
        assert copied.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 1


def test_manual_backup_and_status(tmp_path):
    store = Store(tmp_path / "live.sqlite")
    path = create_manual_backup(store, tmp_path / "backups",
                                datetime(2026, 7, 13, 14, 30, 5))
    status = backup_status(tmp_path / "backups")
    assert path.name == "birdframe-2026-07-13-143005.sqlite"
    assert status.count == 1 and status.latest == path.name
    assert status.bytes == path.stat().st_size


def test_retention_removes_only_old_completed_snapshots(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old = backup_dir / "birdframe-2026-05-01.sqlite"
    recent = backup_dir / "birdframe-2026-07-12.sqlite"
    unrelated = backup_dir / "notes.txt"
    for path in (old, recent, unrelated):
        path.write_bytes(b"x")
    old_time = (datetime(2026, 5, 1) - datetime(1970, 1, 1)).total_seconds()
    recent_time = (datetime(2026, 7, 12) - datetime(1970, 1, 1)).total_seconds()
    os.utime(old, (old_time, old_time))
    os.utime(recent, (recent_time, recent_time))

    assert prune_backups(backup_dir, 30, datetime(2026, 7, 13)) == 1
    assert not old.exists()
    assert recent.exists() and unrelated.exists()
    # Zero retention means keep forever.
    assert prune_backups(backup_dir, 0, datetime(2027, 7, 13)) == 0
