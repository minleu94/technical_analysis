"""Capture and normalize one official TDCC 1-5 weekly candidate snapshot.

Default mode is candidate-only: it writes raw/normalized artifacts beneath
the explicit repo ``output`` directory and never opens a SQLite database.
Applying to any formal or candidate DB is intentionally a separate owner
operation after review of the generated manifest and quarantine.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data_module.tdcc_shareholding_candidate import (
    TDCC_SOURCE_VERSION,
    TDCC_URL,
    normalize_tdcc_payload,
    parse_observed_at,
    p0_shadow_row,
    write_csv,
    write_json,
)


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "data_completion_20260909" / "tdcc"


def _repo_output(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"TDCC candidate output 必須位於 repo 內: {resolved}")
    if "output" not in resolved.parts:
        raise ValueError(f"TDCC candidate output 必須位於 repo output/: {resolved}")
    return resolved


def _capture(url: str, output_dir: Path, timeout: int) -> tuple[Path, dict[str, object]]:
    request = Request(url, headers={"User-Agent": "technical-analysis/tdcc-candidate-capture"})
    observed_at = datetime.now(timezone.utc)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official URL/explicit CLI URL
        payload = response.read()
        status = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("Content-Type", ""))
    source_hash = sha256(payload).hexdigest()
    stamp = observed_at.strftime("%Y%m%dT%H%M%SZ")
    raw_path = output_dir / f"tdcc_1-5_raw_{stamp}.csv"
    if raw_path.exists() and sha256(raw_path.read_bytes()).hexdigest() != source_hash:
        raise ValueError(f"capture 目標已存在且 bytes 不同: {raw_path}")
    if not raw_path.exists():
        raw_path.write_bytes(payload)
    metadata = {
        "url": url,
        "http_status": status,
        "content_type": content_type,
        "captured_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
        "sha256": source_hash,
        "content_length": len(payload),
        "raw_file": raw_path.name,
    }
    write_json(raw_path.with_name(raw_path.name + ".meta.json"), metadata)
    return raw_path, metadata


def build_artifacts(raw_path: Path, output_dir: Path, observed_at: datetime, metadata: dict[str, object] | None = None) -> dict[str, object]:
    payload = raw_path.read_bytes()
    parsed = normalize_tdcc_payload(payload, observed_at=observed_at)
    prefix = f"tdcc_1-5_{parsed.report_date.replace('-', '')}"
    tier_fields = (
        "symbol", "report_date", "tier", "holder_count", "shares", "holding_ratio_bp", "tier_role",
        "source_payload_sha256", "raw_row_sha256", "first_observed_at", "observed_at", "available_at", "available_date", "quality",
        "availability_evidence", "source_version",
    )
    aggregate_fields = tuple(parsed.aggregate_rows[0].keys())
    ready = tuple(row for row in parsed.aggregate_rows if row["candidate_status"] == "shadow_ready")
    import_fields = (
        "stock_code", "decision_date", "source_version", "publication_at", "first_observed_at", "observed_at", "available_at", "available_date",
        "quality", "shareholding_tiers", "large_holder_ratio_bp", "retail_holder_ratio_bp",
        "dispersion_index_bp",
    )
    import_rows = [
        {field: row[field] for field in import_fields}
        for row in ready
    ]
    write_csv(output_dir / f"{prefix}_tiers.csv", parsed.tier_rows, fieldnames=tier_fields)
    write_csv(output_dir / f"{prefix}_aggregate.csv", parsed.aggregate_rows, fieldnames=aggregate_fields)
    write_csv(output_dir / f"{prefix}_ready_import.csv", import_rows, fieldnames=import_fields)
    write_csv(output_dir / f"{prefix}_quarantine.csv", parsed.quarantine_rows, fieldnames=(
        "symbol", "report_date", "source_distribution_total_bp", "official_total_ratio_bp",
        "source_distribution_residual_bp", "reason", "source_payload_sha256",
    ))
    shadow_rows = [p0_shadow_row(row) for row in parsed.aggregate_rows]
    write_json(output_dir / f"{prefix}_p0_shadow.json", {"rows": shadow_rows})
    artifact_names = (
        f"{prefix}_tiers.csv", f"{prefix}_aggregate.csv", f"{prefix}_ready_import.csv",
        f"{prefix}_quarantine.csv", f"{prefix}_p0_shadow.json",
    )
    artifact_hashes = {
        name: sha256((output_dir / name).read_bytes()).hexdigest()
        for name in artifact_names
    }
    manifest: dict[str, object] = {
        "source_id": "tdcc_shareholding",
        "source_version": TDCC_SOURCE_VERSION,
        "endpoint": TDCC_URL,
        "raw_file": str(raw_path),
        "source_payload_sha256": parsed.source_payload_sha256,
        "report_date": parsed.report_date,
        "first_observed_at": parsed.observed_at,
        "observed_at": parsed.observed_at,
        "safe_available_date": parsed.aggregate_rows[0]["available_date"] if parsed.aggregate_rows else None,
        "publication_at": None,
        "availability_policy": "first_observed_only",
        "quality": "degraded",
        "candidate_only": True,
        "formal_db_written": False,
        "downstream_eligibility": "none",
        "counts": parsed.manifest_counts(),
        "ready_import_file": f"{prefix}_ready_import.csv",
        "full_tier_file": f"{prefix}_tiers.csv",
        "quarantine_file": f"{prefix}_quarantine.csv",
        "p0_shadow_file": f"{prefix}_p0_shadow.json",
        "artifact_hashes": artifact_hashes,
        "capture_metadata": metadata or {},
        "notes": [
            "資料日期是 TDCC report/period date，不是 publication timestamp。",
            "available_date 使用觀測時間轉台北後的翌日，避免日期型 reader 在同日早盤誤讀中午才完成的 capture。",
            "第 17 級保留為官方總計列；彙總只使用第 1..16 級。",
            "ready_import 只包含 source distribution mismatch 以外的 shadow_ready rows；quarantine 仍保留完整級距。",
        ],
    }
    write_json(output_dir / f"{prefix}_manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture/normalize official TDCC 1-5 candidate; never writes DB")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--raw-file", type=Path, help="既有官方 raw bytes；不重新下載")
    source.add_argument("--url", default=TDCC_URL, help="官方 TDCC endpoint；只有未給 --raw-file 時下載")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--observed-at", help="含 timezone ISO timestamp；raw-file 未給時讀 metadata")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    output_dir = _repo_output(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, object] = {}
    if args.raw_file:
        raw_path = args.raw_file.expanduser().resolve()
        if not raw_path.is_file():
            raise SystemExit(f"raw file 不存在: {raw_path}")
        meta_path = raw_path.with_name(raw_path.name + ".meta.json")
        if meta_path.exists():
            metadata = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        raw_hash = sha256(raw_path.read_bytes()).hexdigest()
        declared_hash = str(metadata.get("sha256", ""))
        if declared_hash and raw_hash != declared_hash:
            raise SystemExit("raw bytes 與 metadata sha256 不一致，拒絕重建 candidate")
        metadata_observed = str(metadata.get("captured_at_utc", ""))
        if args.observed_at and metadata_observed and args.observed_at != metadata_observed:
            raise SystemExit("不可用 --observed-at 覆寫既有 capture metadata；避免偽造可得時間")
        observed_text = metadata_observed or args.observed_at or ""
        if not observed_text:
            raise SystemExit("--raw-file 必須搭配 --observed-at 或同名 .meta.json captured_at_utc")
        observed_at = parse_observed_at(observed_text)
    else:
        raw_path, metadata = _capture(args.url, output_dir, args.timeout)
        observed_at = parse_observed_at(str(metadata["captured_at_utc"]))
    manifest = build_artifacts(raw_path, output_dir, observed_at, metadata)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    print("APPLY_CLI=由 owner 審核 ready_import 後，使用既有 Phase 3C candidate apply；本 CLI 不寫任何 SQLite。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
