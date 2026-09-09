"""驗證／備份後增量匯入 MOPS 現況快照，不冒充歷史公告日。"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_module.current_fundamental_snapshots import insert_observations, monthly_snapshot_rows
from data_module.ml_storage_capacity import acquire_heavy_chain_reservation, release_heavy_chain_reservation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--db-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--lock-path", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = monthly_snapshot_rows(args.snapshot)
    result: dict[str, object] = {
        "status": "preview", "rows": len(records), "snapshot": str(args.snapshot.resolve()),
        "snapshot_sha256": sha256(args.snapshot.read_bytes()).hexdigest(),
        "coverage": dict(Counter(f"{r['period']}/{r['market']}" for r in records)),
        "contract": "current-observed-only; no historical announcement evidence",
    }
    if args.apply:
        if not args.db_file.is_file():
            raise ValueError("existing database required")
        if shutil.disk_usage(args.db_file.parent).free < 200 * 1024**3:
            raise ValueError("data disk reserve below 200 GiB")
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(args.backup_dir).free < args.db_file.stat().st_size * 2:
            raise ValueError("insufficient backup space")
        reservation = acquire_heavy_chain_reservation(args.lock_path)
        if reservation is None:
            raise RuntimeError("heavy chain active; no write attempted")
        try:
            backup = args.backup_dir / ("before_monthly_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".db")
            with sqlite3.connect(args.db_file.resolve().as_uri() + "?mode=ro", uri=True) as source:
                with sqlite3.connect(backup) as target:
                    source.backup(target, pages=256)
                    if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("backup integrity failed")
            with sqlite3.connect(args.db_file) as connection:
                connection.execute("BEGIN IMMEDIATE")
                added = insert_observations(connection, records)
            result.update(status="applied", inserted=added, backup=str(backup.resolve()))
        finally:
            release_heavy_chain_reservation(reservation)
    args.evidence_file.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
