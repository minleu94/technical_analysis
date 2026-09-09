"""Review or apply a current-only quarterly statement snapshot.

The command never writes ``fundamental_statement_items``.  Applying requires
an explicit database path, backup directory, ``--apply`` and the confirmation
token.  A normal invocation is a read-only candidate review for root to audit.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from calendar import monthrange
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.current_fundamental_snapshots import COLUMNS, insert_observations


def load_candidate(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("candidate columns do not match fundamental_current_observations")
        rows = [{column: str(row.get(column) or "") for column in COLUMNS} for row in reader]
    if not rows:
        raise ValueError("candidate has no observations")
    _validate_rows(rows)
    return rows


def review_candidate(candidate: Path, manifest: Path) -> dict[str, Any]:
    rows = load_candidate(candidate)
    metadata = _read_manifest(manifest)
    _validate_manifest(metadata, candidate, rows)
    _validate_observed_at(rows)
    return {
        "status": "review_ready",
        "candidate": str(candidate),
        "manifest": str(manifest),
        "row_count": len(rows),
        "stock_count": len({row["stock_code"] for row in rows}),
        "periods": sorted({row["period"] for row in rows}),
        "markets": sorted({row["market"] for row in rows}),
        "formal_pit_eligible": metadata["source_policy"]["formal_pit_eligible"],
        "formal_credit_authorized": metadata["source_policy"]["formal_credit_authorized"],
        "apply_target": "fundamental_current_observations",
        "database_written": False,
    }


def apply_candidate(
    *,
    candidate: Path,
    manifest: Path,
    db_file: Path,
    backup_dir: Path,
) -> dict[str, Any]:
    rows = load_candidate(candidate)
    metadata = _read_manifest(manifest)
    _validate_manifest(metadata, candidate, rows)
    _validate_observed_at(rows)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not Path(db_file).exists():
        raise FileNotFoundError(db_file)
    backup_path = backup_dir / f"{Path(db_file).stem}.before-current-statement-snapshot.sqlite"
    if backup_path.exists():
        raise FileExistsError(f"refusing to overwrite backup: {backup_path}")
    _sqlite_online_backup(Path(db_file), backup_path)
    connection = sqlite3.connect(db_file)
    try:
        connection.execute("BEGIN IMMEDIATE")
        inserted = insert_observations(connection, rows)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "status": "applied",
        "candidate": str(candidate),
        "database": str(db_file),
        "backup": str(backup_path),
        "row_count": len(rows),
        "inserted_count": inserted,
        "target_table": "fundamental_current_observations",
        "formal_statement_items_written": False,
    }


def _validate_rows(rows: list[dict[str, str]]) -> None:
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        if row["kind"] != "statement_item":
            raise ValueError("candidate kind must be statement_item")
        if not row["item_code"].startswith(("income_statement:", "balance_sheet:")):
            raise ValueError("item_code must include statement type")
        if row["market"] not in {"twse", "tpex"}:
            raise ValueError("unknown market")
        try:
            value = Decimal(row["value"])
        except InvalidOperation as exc:
            raise ValueError("candidate value is not Decimal text") from exc
        if not value.is_finite():
            raise ValueError("candidate value must be finite")
        key = (
            row["stock_code"],
            row["kind"],
            row["period"],
            row["item_code"],
            row["source_version"],
        )
        if key in seen:
            raise ValueError(f"duplicate candidate key: {key}")
        seen.add(key)
        observed = _parse_aware(row["observed_at"])
        year, quarter = map(int, row["period"].split("-Q"))
        if quarter not in (1, 2, 3, 4):
            raise ValueError("invalid quarter")
        period_end = date(year, quarter * 3, monthrange(year, quarter * 3)[1])
        if row["as_of_date"] != period_end.isoformat() or period_end > observed.date():
            raise ValueError("statement period is inconsistent or after observation")


def _validate_observed_at(rows: list[dict[str, str]]) -> None:
    now = datetime.now(timezone.utc)
    if any(_parse_aware(row["observed_at"]) > now for row in rows):
        raise ValueError("candidate contains future observed_at")


def _sqlite_online_backup(source_path: Path, backup_path: Path) -> None:
    """Back up the SQLite logical database, including WAL state."""

    source = sqlite3.connect(source_path)
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
        backup.commit()
        check = str(backup.execute("PRAGMA quick_check").fetchone()[0])
        if check.lower() != "ok":
            raise RuntimeError(f"SQLite backup quick_check failed: {check}")
    finally:
        backup.close()
        source.close()


def _read_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("candidate manifest must be an object")
    return payload


def _validate_manifest(
    metadata: Mapping[str, Any], candidate: Path, rows: list[dict[str, str]]
) -> None:
    policy = metadata.get("source_policy")
    if not isinstance(policy, Mapping):
        raise ValueError("candidate manifest missing source_policy")
    if policy.get("formal_pit_eligible") is not False:
        raise ValueError("only current-only, formal-PIT-ineligible candidates are accepted")
    if policy.get("formal_credit_authorized") is not False:
        raise ValueError("formal credit must remain disabled")
    coverage = metadata.get("coverage")
    if not isinstance(coverage, Mapping) or int(coverage.get("record_count", -1)) != len(rows):
        raise ValueError("candidate manifest record_count mismatch")
    artifacts = metadata.get("artifacts")
    if isinstance(artifacts, Mapping):
        expected_name = artifacts.get("observations_csv")
        if expected_name and Path(candidate).name != expected_name:
            raise ValueError("candidate filename does not match manifest artifact")
        expected_hash = str(artifacts.get("observations_csv_sha256", ""))
        if expected_hash:
            actual_hash = _sha256_file(candidate)
            if actual_hash != expected_hash:
                raise ValueError("candidate bytes do not match manifest hash")
    period = str(metadata.get("period", ""))
    if period and any(row["period"] != period for row in rows):
        raise ValueError("candidate row period mismatch")


def _parse_aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--db-file", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if not args.apply:
        result = review_candidate(args.candidate, args.manifest)
    else:
        if args.confirm != "apply-current-statement-snapshot":
            parser.error("--apply requires --confirm apply-current-statement-snapshot")
        if args.db_file is None or args.backup_dir is None:
            parser.error("--apply requires --db-file and --backup-dir")
        result = apply_candidate(
            candidate=args.candidate,
            manifest=args.manifest,
            db_file=args.db_file,
            backup_dir=args.backup_dir,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
