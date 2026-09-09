"""Review and explicitly apply a TDCC ready-import CSV to one SQLite DB.

The default is read-only dry-run.  ``--apply`` requires both an explicit
confirmation token and a pre-apply backup path.  This command is intentionally
separate from capture/normalization so a root owner can review the raw hash,
quarantine, and exact target before any database write.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


CONFIRM_TOKEN = "apply-tdcc-shareholding-candidate"
REQUIRED_CANDIDATE_FIELDS = {
    "stock_code", "decision_date", "source_version", "publication_at", "first_observed_at",
    "observed_at", "available_at", "available_date", "quality", "shareholding_tiers",
    "large_holder_ratio_bp", "retail_holder_ratio_bp", "dispersion_index_bp",
}
BASE_TARGET_FIELDS = {
    "stock_code", "decision_date", "available_date", "source_version", "quality",
    "shareholding_tiers", "large_holder_ratio_bp", "retail_holder_ratio_bp", "dispersion_index_bp",
}


@dataclass(frozen=True)
class ApplyReport:
    candidate_rows: int
    added: int
    unchanged: int
    conflicts: int
    target_db: str
    dry_run: bool
    backup_path: str | None
    schema_added: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_rows": self.candidate_rows,
            "added": self.added,
            "unchanged": self.unchanged,
            "conflicts": self.conflicts,
            "target_db": self.target_db,
            "dry_run": self.dry_run,
            "backup_path": self.backup_path,
            "formal_db_written": not self.dry_run,
            "schema_added": list(self.schema_added),
        }


def _read_candidate(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = sorted(REQUIRED_CANDIDATE_FIELDS - fields)
        if missing:
            raise ValueError(f"candidate 缺少欄位: {','.join(missing)}")
        rows = [{str(k): str(v or "") for k, v in row.items()} for row in reader]
    if not rows:
        raise ValueError("candidate 沒有資料列")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        identity = (row["stock_code"].strip(), row["decision_date"].strip())
        if not identity[0] or not identity[1]:
            raise ValueError("candidate stock_code/decision_date 不可為空")
        if identity in seen:
            raise ValueError(f"candidate 重複 identity: {identity}")
        seen.add(identity)
        if row.get("publication_at"):
            raise ValueError("TDCC candidate 不得自行填 publication_at")
        try:
            tiers = json.loads(row["shareholding_tiers"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"shareholding_tiers JSON 無法解析: {identity}") from exc
        if not isinstance(tiers, list) or len(tiers) != 17:
            raise ValueError(f"shareholding_tiers 必須保留 17 級: {identity}")
    return rows


def _row_content(row: dict[str, Any], fields: set[str]) -> str:
    payload = {field: str(row.get(field, "")) for field in sorted(fields)}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _target_columns(conn: sqlite3.Connection) -> set[str]:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tdcc_shareholding)")}
    if not BASE_TARGET_FIELDS.issubset(columns):
        missing = sorted(BASE_TARGET_FIELDS - columns)
        raise ValueError(f"target tdcc_shareholding 缺少欄位: {','.join(missing)}")
    return columns


def _compare_fields(target_columns: set[str]) -> tuple[str, ...]:
    # A repeated capture may have a new observation timestamp while retaining
    # the same report-date content.  Preserve the first custody timestamps;
    # source/values changes still conflict and fail closed.
    return tuple(field for field in (
        "stock_code", "decision_date", "source_version", "quality",
        "shareholding_tiers", "large_holder_ratio_bp", "retail_holder_ratio_bp", "dispersion_index_bp",
    ) if field in target_columns)


def _verified_sqlite_backup(source: Path, destination: Path) -> None:
    """Take a consistent SQLite online backup, including WAL-visible rows."""

    if destination.exists():
        raise FileExistsError(f"backup 已存在，避免覆寫既有證據: {destination}")
    source_conn = sqlite3.connect(source)
    backup_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(backup_conn)
        result = backup_conn.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise ValueError(f"backup quick_check 失敗: {result}")
        backup_conn.commit()
    finally:
        backup_conn.close()
        source_conn.close()


def _verify_manifest(candidate: Path, manifest_path: Path | None) -> None:
    if manifest_path is None:
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest 無法讀取: {manifest_path}") from exc
    expected_name = str(manifest.get("ready_import_file", ""))
    if expected_name and candidate.name != expected_name:
        raise ValueError(f"candidate 與 manifest ready_import_file 不一致: {candidate.name}")
    expected_hash = str(manifest.get("artifact_hashes", {}).get(candidate.name, ""))
    actual_hash = sha256(candidate.read_bytes()).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("candidate bytes 與 manifest artifact hash 不一致")


def review_or_apply(
    candidate: Path,
    target_db: Path,
    *,
    apply: bool = False,
    confirm: str | None = None,
    backup_db: Path | None = None,
    manifest: Path | None = None,
) -> ApplyReport:
    _verify_manifest(candidate, manifest)
    rows = _read_candidate(candidate)
    if apply:
        if confirm != CONFIRM_TOKEN:
            raise PermissionError(f"apply 必須提供 --confirm {CONFIRM_TOKEN}")
        if backup_db is None:
            raise ValueError("apply 必須提供 --backup-db；先保存正式 DB backup")
        if target_db.resolve() == backup_db.resolve():
            raise ValueError("target-db 與 backup-db 不可相同")
        if not target_db.is_file():
            raise FileNotFoundError(f"target-db 不存在: {target_db}")
        backup_db.parent.mkdir(parents=True, exist_ok=True)
        _verified_sqlite_backup(target_db, backup_db)

    conn = sqlite3.connect(target_db)
    try:
        target_columns = _target_columns(conn)
        schema_added: list[str] = []
        if apply:
            conn.execute("BEGIN IMMEDIATE")
            if "observed_at" not in target_columns:
                conn.execute("ALTER TABLE tdcc_shareholding ADD COLUMN observed_at TEXT")
                target_columns.add("observed_at")
                schema_added.append("observed_at")
        compare_fields = _compare_fields(target_columns)
        added = unchanged = conflicts = 0
        insert_fields = tuple(field for field in (
            "stock_code", "decision_date", "available_date", "source_version", "quality",
            "shareholding_tiers", "large_holder_ratio_bp", "retail_holder_ratio_bp", "dispersion_index_bp",
            "observed_at", "publication_at", "first_observed_at", "available_at",
        ) if field in target_columns)
        existing_sql = f"SELECT {','.join(insert_fields)} FROM tdcc_shareholding WHERE stock_code=? AND decision_date=?"
        for row in rows:
            existing = conn.execute(existing_sql, (row["stock_code"], row["decision_date"])).fetchone()
            if existing is not None:
                existing_dict = dict(zip(insert_fields, existing))
                if _row_content(existing_dict, set(compare_fields)) == _row_content(row, set(compare_fields)):
                    unchanged += 1
                else:
                    conflicts += 1
                continue
            if apply:
                values = [row.get(field, "") or None for field in insert_fields]
                placeholders = ",".join("?" for _ in insert_fields)
                conn.execute(
                    f"INSERT INTO tdcc_shareholding ({','.join(insert_fields)}) VALUES ({placeholders})",
                    values,
                )
            added += 1
        if conflicts:
            if apply:
                conn.rollback()
            raise ValueError(f"candidate 與 target 已有內容衝突: {conflicts} rows")
        if apply:
            conn.commit()
        return ApplyReport(
            candidate_rows=len(rows),
            added=added,
            unchanged=unchanged,
            conflicts=conflicts,
            target_db=str(target_db),
            dry_run=not apply,
            backup_path=str(backup_db) if backup_db else None,
            schema_added=tuple(schema_added),
        )
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review/apply TDCC ready candidate; default is read-only")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--target-db", type=Path, required=True)
    parser.add_argument("--backup-db", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None, help="capture manifest；核對 ready CSV bytes/hash")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None)
    args = parser.parse_args(argv)
    report = review_or_apply(
        args.candidate.expanduser().resolve(),
        args.target_db.expanduser().resolve(),
        apply=args.apply,
        confirm=args.confirm,
        backup_db=args.backup_db.expanduser().resolve() if args.backup_db else None,
        manifest=args.manifest.expanduser().resolve() if args.manifest else None,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
