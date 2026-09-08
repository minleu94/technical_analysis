"""以固定上限批次抓取 MOPS 季度財報 research candidates。

每個 request 都必須明確指定股票、上市市場與公曆期別；driver 逐公司呼叫
既有單公司 fetcher，且每批最多八家公司。輸出只在隔離 research output，
不寫入正式 SQLite、availability mapping 或 D 槽原始資料。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_statement_candidate_adapter import validate_research_output_path
from scripts.build_mops_statement_pit_candidate import (
    _XBRL_ENCODING_REPAIR_C1,
    _file_sha256_reference,
    build_candidate,
)
from scripts.plan_mops_statement_universe import load_universe_plan


_MAX_BATCH_COMPANIES = 8
_DEFAULT_MAX_ATTEMPTS_PER_CHILD = 2
_MAX_ATTEMPTS_PER_CHILD = 5
_DEFAULT_MAX_SOURCE_TRANSPORT_FAILURES = 1
_MAX_SOURCE_TRANSPORT_FAILURES = 5
_BATCH_SCHEMA_VERSION = "mops-statement-pit-batch-manifest.v2"
_CHILD_STATUSES = frozenset({"pending", "running", "succeeded", "failed", "integrity_error"})
_REPORT_BASES = frozenset({"consolidated", "individual"})


def _parse_request(value: str) -> tuple[str, str, int, int]:
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise ValueError("--request must be STOCK:MARKET:YYYY-Qn")
    stock_code, market, period = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("request stock must be a 4-to-6 digit code")
    if market not in {"sii", "otc", "rotc", "pub"}:
        raise ValueError("request market must be sii, otc, rotc, or pub")
    try:
        year_text, quarter_text = period.split("-Q", 1)
        period_year = int(year_text)
        season = int(quarter_text)
    except (ValueError, TypeError) as error:
        raise ValueError("request period must be YYYY-Qn") from error
    if len(year_text) != 4 or period_year < 1900 or not 1 <= season <= 4:
        raise ValueError("request period must be a valid YYYY-Qn")
    return stock_code, market, period_year, season


def _parse_listing_override(value: str) -> tuple[str, Path]:
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--listing-raw must be STOCK=PATH")
    stock_code, path_text = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("listing override stock must be a 4-to-6 digit code")
    if not path_text:
        raise ValueError("listing override path must be non-empty")
    return stock_code, _resolved_path(Path(path_text))


def _parse_listing_evidence_override(value: str) -> tuple[str, Path]:
    """解析與保存 t57 raw 對應的官方 HTTP evidence 路徑。"""
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--listing-evidence must be STOCK=PATH")
    stock_code, path_text = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("listing evidence stock must be a 4-to-6 digit code")
    if not path_text:
        raise ValueError("listing evidence path must be non-empty")
    return stock_code, _resolved_path(Path(path_text))


def _parse_listing_browser_evidence_override(value: str) -> tuple[str, Path]:
    """解析已保存的 t57 瀏覽器 DOM observation evidence 路徑。"""
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--listing-browser-evidence must be STOCK=PATH")
    stock_code, path_text = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("browser listing evidence stock must be a 4-to-6 digit code")
    if not path_text:
        raise ValueError("browser listing evidence path must be non-empty")
    return stock_code, _resolved_path(Path(path_text))


def _parse_ezsearch_availability_override(value: str) -> tuple[str, Path]:
    """解析已保存的官方 EZSearch 公告事件 evidence 路徑。"""
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--ezsearch-availability-evidence must be STOCK=PATH")
    stock_code, path_text = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("EZSearch evidence stock must be a 4-to-6 digit code")
    if not path_text:
        raise ValueError("EZSearch evidence path must be non-empty")
    return stock_code, _resolved_path(Path(path_text))


def _parse_statement_raw_dir_override(value: str) -> tuple[str, Path]:
    """解析已保存的三張 t164 與 XBRL raw 目錄。"""
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--statement-raw-dir must be STOCK=PATH")
    stock_code, path_text = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("statement raw directory stock must be a 4-to-6 digit code")
    if not path_text:
        raise ValueError("statement raw directory path must be non-empty")
    return stock_code, _resolved_path(Path(path_text))


def _parse_xbrl_browser_dom_override(value: str) -> tuple[str, Path]:
    """解析已保存的官方 t164 XBRL 瀏覽器 DOM。"""
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--xbrl-browser-dom must be STOCK=PATH")
    stock_code, path_text = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("XBRL browser DOM stock must be a 4-to-6 digit code")
    if not path_text:
        raise ValueError("XBRL browser DOM path must be non-empty")
    return stock_code, _resolved_path(Path(path_text))


def _parse_xbrl_browser_evidence_override(value: str) -> tuple[str, Path]:
    """解析 t164 XBRL 瀏覽器 DOM 的 identity／hash evidence。"""
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--xbrl-browser-evidence must be STOCK=PATH")
    stock_code, path_text = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("XBRL browser evidence stock must be a 4-to-6 digit code")
    if not path_text:
        raise ValueError("XBRL browser evidence path must be non-empty")
    return stock_code, _resolved_path(Path(path_text))


def _parse_xbrl_encoding_repair_override(value: str) -> tuple[str, str]:
    """解析需明示套用的 XBRL 編碼修復政策。"""
    parts = value.strip().split("=", 1)
    if len(parts) != 2:
        raise ValueError("--xbrl-encoding-repair must be STOCK=POLICY")
    stock_code, policy = (part.strip() for part in parts)
    if not stock_code.isdigit() or not 4 <= len(stock_code) <= 6:
        raise ValueError("XBRL encoding repair stock must be a 4-to-6 digit code")
    if policy != _XBRL_ENCODING_REPAIR_C1:
        raise ValueError(f"unsupported XBRL encoding repair: {policy}")
    return stock_code, policy


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _transport_failure_source(error: BaseException) -> str | None:
    """從例外鏈判斷可歸屬的網路來源，供批次 circuit breaker 使用。"""
    parts: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        cause = current.__cause__
        context = current.__context__
        current = cause if cause is not None else context
    text = " ".join(parts)
    transport_markers = (
        "ConnectionError",
        "ConnectTimeout",
        "NameResolutionError",
        "NewConnectionError",
        "ProxyError",
        "ReadTimeout",
        "Timeout",
        "WinError 10013",
        "Errno 11001",
        "socket.gaierror",
    )
    if not any(marker in text for marker in transport_markers):
        return None
    for host in ("doc.twse.com.tw", "mopsov.twse.com.tw", "mops.twse.com.tw"):
        if host in text:
            return host
    return "network"


def _resolved_path(path: Path) -> Path:
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    return requested.resolve(strict=False)


def _path_identity(path: Path) -> str:
    """以解析後、大小寫不敏感的路徑保存操作身分。"""
    return str(_resolved_path(path)).casefold()


def _raw_directory_hashes(path: Path) -> dict[str, str]:
    """保存 replay raw 目錄內檔案身份，拒絕別名與子目錄。"""
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=False) != path:
        raise ValueError("statement raw directory must be a regular non-alias directory")
    hashes: dict[str, str] = {}
    for child in sorted(path.iterdir()):
        if child.is_symlink() or not child.is_file() or child.resolve(strict=False) != child:
            raise ValueError("statement raw directory contains an alias or non-file")
        hashes[child.name] = _file_sha256_reference(child)
    return hashes


def _expected_child_paths(output_root: Path, run_id: str) -> tuple[Path, Path]:
    child_root = _resolved_path(output_root) / run_id
    return child_root / "statement-pit-candidate.json", child_root / "run-manifest.json"


def _initial_child_rows(
    requests: list[tuple[str, str, int, int]],
    run_ids: list[str],
    output_root: Path,
    report_basis: str = "consolidated",
) -> list[dict[str, Any]]:
    if report_basis not in _REPORT_BASES:
        raise ValueError("report_basis must be consolidated or individual")
    rows: list[dict[str, Any]] = []
    resolved_root = _resolved_path(output_root)
    for (stock_code, market, period_year, season), run_id in zip(requests, run_ids):
        candidate, manifest = _expected_child_paths(resolved_root, run_id)
        row: dict[str, Any] = {
                "stock_code": stock_code,
                "market": market,
                "period": f"{period_year:04d}-Q{season}",
                "run_id": run_id,
                "candidate": str(candidate),
                "manifest": str(manifest),
                "status": "pending",
                "attempts": [],
            }
        if report_basis != "consolidated":
            row["report_basis"] = report_basis
        rows.append(row)
    return rows


def _write_batch_manifest(path: Path, payload: Mapping[str, Any], *, create_only: bool) -> None:
    """以同目錄暫存檔更新進度，避免失敗紀錄截斷既有 manifest。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if create_only:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
        return
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _refresh_batch_summary(payload: dict[str, Any], *, status: str | None = None) -> None:
    rows = payload.get("child_runs")
    if not isinstance(rows, list):
        raise ValueError("batch manifest child_runs must be a list")
    counts = {name: 0 for name in _CHILD_STATUSES}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("status") not in counts:
            raise ValueError("batch manifest contains an invalid child status")
        counts[str(row["status"])] += 1
    payload["succeeded_count"] = counts["succeeded"]
    payload["failed_count"] = counts["failed"] + counts["integrity_error"]
    payload["pending_count"] = counts["pending"] + counts["running"]
    attempts_used = 0
    for row in rows:
        attempts = row.get("attempts") if isinstance(row, Mapping) else None
        if not isinstance(attempts, list):
            raise ValueError("batch manifest child attempts must be a list")
        attempts_used += len(attempts)
    payload["attempts_used"] = attempts_used
    max_attempts = payload.get("max_attempts_per_child")
    if isinstance(max_attempts, int) and max_attempts > 0:
        payload["max_total_attempts"] = len(rows) * max_attempts
        payload["attempts_remaining"] = max(0, len(rows) * max_attempts - attempts_used)
    payload["status"] = status or (
        "completed"
        if counts["succeeded"] == len(rows)
        else "partial"
        if counts["failed"] or counts["integrity_error"]
        else "running"
    )
    payload["updated_at"] = _utc_now()


def _child_expected_identity(
    row: Mapping[str, Any],
    *,
    output_root: Path,
) -> tuple[str, str, str, Path, Path]:
    values = (row.get("stock_code"), row.get("market"), row.get("period"), row.get("run_id"))
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("batch manifest child identity is incomplete")
    stock_code, market, period, run_id = (str(value) for value in values)
    candidate, manifest = _expected_child_paths(output_root, run_id)
    stored_candidate = row.get("candidate")
    stored_manifest = row.get("manifest")
    if not isinstance(stored_candidate, str) or _path_identity(Path(stored_candidate)) != _path_identity(candidate):
        raise ValueError(f"batch child candidate path does not match run_id: {run_id}")
    if not isinstance(stored_manifest, str) or _path_identity(Path(stored_manifest)) != _path_identity(manifest):
        raise ValueError(f"batch child manifest path does not match run_id: {run_id}")
    return stock_code, market, period, candidate, manifest


def _partial_replay_raw_dir(
    row: Mapping[str, Any],
    *,
    output_root: Path,
) -> Path | None:
    """驗證可重用的失敗 staging；不把 partial 直接算成 completed child。"""
    if row.get("partial_replay_ready") is not True:
        return None
    partial_value = row.get("partial_staging")
    run_id = row.get("run_id")
    if not isinstance(partial_value, str) or not isinstance(run_id, str):
        raise ValueError("partial staging identity is incomplete")
    expected_root = _resolved_path(output_root) / "_partial" / run_id
    partial_root = _resolved_path(Path(partial_value))
    if partial_root != expected_root or partial_root.is_symlink() or not partial_root.is_dir():
        raise ValueError("partial staging path does not match the batch child")
    failure_path = partial_root / "partial-failure.json"
    if (
        failure_path.is_symlink()
        or not failure_path.is_file()
        or failure_path.resolve(strict=False) != failure_path
    ):
        raise ValueError("partial staging failure receipt is missing or aliased")
    expected_failure_hash = row.get("partial_failure_sha256")
    actual_failure_hash = _file_sha256_reference(failure_path)
    if expected_failure_hash != actual_failure_hash:
        raise ValueError("partial staging failure receipt hash changed")
    try:
        receipt = json.loads(failure_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("partial staging failure receipt is unreadable") from error
    if not isinstance(receipt, Mapping):
        raise ValueError("partial staging failure receipt must be an object")
    if (
        receipt.get("schema_version") != "mops-statement-pit-partial.v1"
        or receipt.get("run_id") != run_id
        or receipt.get("stock_code") != row.get("stock_code")
        or receipt.get("market") != row.get("market")
        or receipt.get("period") != row.get("period")
        or receipt.get("report_basis", "consolidated") != row.get("report_basis", "consolidated")
        or receipt.get("replay_ready") is not True
    ):
        raise ValueError("partial staging receipt identity or replay state is invalid")
    raw_dir = partial_root / "raw"
    if raw_dir.is_symlink() or not raw_dir.is_dir() or raw_dir.resolve(strict=False) != raw_dir:
        raise ValueError("partial staging raw directory is missing or aliased")
    listed = receipt.get("raw_files")
    if not isinstance(listed, list):
        raise ValueError("partial staging raw file list is missing")
    expected_files: dict[str, tuple[str, int]] = {}
    for item in listed:
        if not isinstance(item, Mapping):
            raise ValueError("partial staging raw file entry is malformed")
        name = item.get("basename")
        digest = item.get("sha256")
        byte_count = item.get("byte_count")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(digest, str)
            or not isinstance(byte_count, int)
        ):
            raise ValueError("partial staging raw file identity is malformed")
        expected_files[name] = (digest, byte_count)
    actual_files = _raw_directory_hashes(raw_dir)
    if set(actual_files) != set(expected_files):
        raise ValueError("partial staging raw file set changed")
    for name, (digest, byte_count) in expected_files.items():
        path = raw_dir / name
        if actual_files[name] != digest or path.stat().st_size != byte_count:
            raise ValueError(f"partial staging raw file changed: {name}")
    return raw_dir


def _validate_child_artifacts(
    row: Mapping[str, Any],
    *,
    output_root: Path,
) -> dict[str, Any]:
    """驗證既有 child 的內部 hash 與候選身分，供新建及 resume 共用。"""
    stock_code, market, period, candidate_path, manifest_path = _child_expected_identity(
        row, output_root=output_root
    )
    if (
        candidate_path.is_symlink()
        or manifest_path.is_symlink()
        or candidate_path.resolve(strict=False) != candidate_path
        or manifest_path.resolve(strict=False) != manifest_path
    ):
        raise ValueError(f"completed child files must not use an alias: {row.get('run_id')}")
    if not candidate_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"completed child files are missing: {row.get('run_id')}")
    try:
        child_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"completed child artifact is unreadable: {row.get('run_id')}") from error
    if not isinstance(child_manifest, Mapping) or not isinstance(candidate, Mapping):
        raise ValueError("completed child artifacts must be JSON objects")
    if child_manifest.get("run_id") != row.get("run_id"):
        raise ValueError("completed child manifest run_id does not match batch identity")
    if child_manifest.get("research_only") is not True or child_manifest.get("formal_oos_allowed") is not False:
        raise ValueError("completed child must remain research_only and formal_oos disallowed")
    files = child_manifest.get("files")
    if not isinstance(files, Mapping) or "run-manifest.json" in files:
        raise ValueError("completed child manifest files are missing or self-referential")
    root = manifest_path.parent.resolve()
    raw_root = (root / "raw").resolve()
    raw_count = 0
    legacy_file_names = {
        "candidate": "statement-pit-candidate.json",
        "statement_sources": "statement-sources.json",
        "availability_source": "availability-source.json",
    }
    for name, expected_hash in files.items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("completed child manifest contains an unsafe path")
        if not isinstance(expected_hash, str):
            raise ValueError("completed child manifest hash must be text")
        if name.startswith("raw_"):
            path = raw_root / name.removeprefix("raw_")
            raw_count += 1
        else:
            path = root / legacy_file_names.get(name, name)
        allowed_root = raw_root if name.startswith("raw_") else root
        resolved_path = path.resolve(strict=False)
        try:
            resolved_path.relative_to(allowed_root)
        except ValueError as error:
            raise ValueError("completed child manifest path escapes its run directory") from error
        if resolved_path != path:
            raise ValueError("completed child manifest path must not use an alias")
        if not path.is_file() or _file_sha256_reference(path) != expected_hash:
            raise ValueError(f"completed child hash mismatch: {name}")
    raw_files = child_manifest.get("raw_files")
    if raw_files is not None:
        if not isinstance(raw_files, Mapping):
            raise ValueError("completed child raw_files must be a mapping")
        for name, expected_hash in raw_files.items():
            if not isinstance(name, str) or Path(name).name != name:
                raise ValueError("completed child raw manifest contains an unsafe path")
            path = raw_root / name
            if not isinstance(expected_hash, str) or not path.is_file() or _file_sha256_reference(path) != expected_hash:
                raise ValueError(f"completed child raw hash mismatch: {name}")
            raw_count += 1

    if candidate.get("research_only") is not True or candidate.get("formal_oos_allowed") is not False:
        raise ValueError("completed child candidate must remain research_only and formal OOS disallowed")
    source_version = candidate.get("source_version")
    requested_report_basis = str(row.get("report_basis", "consolidated"))
    candidate_report_basis = str(candidate.get("report_basis", "consolidated"))
    if requested_report_basis not in _REPORT_BASES:
        raise ValueError("batch child report basis is unsupported")
    if candidate_report_basis != requested_report_basis:
        raise ValueError("completed child candidate report basis does not match the batch request")
    rows = candidate.get("rows")
    summary = candidate.get("pit_coverage_summary")
    if not isinstance(source_version, str) or not source_version.strip() or not isinstance(rows, list) or not rows:
        raise ValueError("completed child candidate has no source version or numeric rows")
    if not isinstance(summary, Mapping) or summary.get("stock_code") != stock_code or summary.get("market_request") != market or summary.get("period") != period:
        raise ValueError("completed child candidate identity does not match the batch request")
    for candidate_row in rows:
        if not isinstance(candidate_row, Mapping) or candidate_row.get("stock_code") != stock_code or candidate_row.get("market") != market or candidate_row.get("period") != period:
            raise ValueError("completed child candidate contains a mismatched row identity")

    candidate_hash = _file_sha256_reference(candidate_path)
    manifest_hash = _file_sha256_reference(manifest_path)
    stored_candidate_hash = row.get("candidate_sha256")
    stored_manifest_hash = row.get("manifest_sha256")
    if stored_candidate_hash is not None and stored_candidate_hash != candidate_hash:
        raise ValueError(f"completed child candidate hash changed: {row.get('run_id')}")
    if stored_manifest_hash is not None and stored_manifest_hash != manifest_hash:
        raise ValueError(f"completed child manifest hash changed: {row.get('run_id')}")
    return {
        "candidate": str(candidate_path),
        "manifest": str(manifest_path),
        "candidate_sha256": candidate_hash,
        "manifest_sha256": manifest_hash,
        "candidate_row_count": len(rows),
        "raw_file_count": raw_count,
        "source_version": source_version,
        "report_basis": candidate_report_basis,
        "verified_at": _utc_now(),
    }


def _batch_identity(
    *,
    output_root: Path,
    run_id_prefix: str,
    requests: list[tuple[str, str, int, int]],
    run_ids: list[str],
    canonical_manifest: Path,
    canonical_dataset: Path,
    listing_overrides: Mapping[str, Path],
    listing_evidence_overrides: Mapping[str, Path],
    listing_browser_evidence_overrides: Mapping[str, Path],
    ezsearch_availability_overrides: Mapping[str, Path],
    statement_raw_dirs: Mapping[str, Path],
    xbrl_browser_dom_overrides: Mapping[str, Path],
    xbrl_browser_evidence_overrides: Mapping[str, Path],
    xbrl_encoding_repairs: Mapping[str, str],
    universe_plan: Path | None,
    max_source_transport_failures: int,
    report_basis: str = "consolidated",
) -> dict[str, Any]:
    if report_basis not in _REPORT_BASES:
        raise ValueError("report_basis must be consolidated or individual")
    if not canonical_manifest.is_file() or not canonical_dataset.is_file():
        raise ValueError("canonical manifest and dataset must both exist")
    identity: dict[str, Any] = {
        "output_root": str(_resolved_path(output_root)),
        "run_id_prefix": run_id_prefix.strip().lower(),
        "max_source_transport_failures": max_source_transport_failures,
        "requests": [
            {
                "stock_code": stock_code,
                "market": market,
                "period": f"{period_year:04d}-Q{season}",
                "run_id": run_id,
            }
            for (stock_code, market, period_year, season), run_id in zip(requests, run_ids)
        ],
        "canonical_manifest": {
            "path": str(_resolved_path(canonical_manifest)),
            "sha256": _file_sha256_reference(canonical_manifest),
        },
        "canonical_dataset": {
            "path": str(_resolved_path(canonical_dataset)),
            "sha256": _file_sha256_reference(canonical_dataset),
        },
        "listing_overrides": {
            stock_code: {
                "path": str(_resolved_path(path)),
                "sha256": _file_sha256_reference(path),
            }
            for stock_code, path in sorted(listing_overrides.items())
        },
    }
    # 舊版 consolidated manifest 沒有這個欄位，保留其 resume 相容性；個別
    # 報表則必須把範圍寫入操作身分，避免把合併與個別 child 混在同一批。
    if report_basis != "consolidated":
        identity["report_basis"] = report_basis
    if listing_evidence_overrides:
        identity["listing_evidence_overrides"] = {
            stock_code: {
                "path": str(_resolved_path(path)),
                "sha256": _file_sha256_reference(path),
            }
            for stock_code, path in sorted(listing_evidence_overrides.items())
        }
    if listing_browser_evidence_overrides:
        identity["listing_browser_evidence_overrides"] = {
            stock_code: {
                "path": str(_resolved_path(path)),
                "sha256": _file_sha256_reference(path),
            }
            for stock_code, path in sorted(listing_browser_evidence_overrides.items())
        }
    if ezsearch_availability_overrides:
        identity["ezsearch_availability_overrides"] = {
            stock_code: {
                "path": str(_resolved_path(path)),
                "sha256": _file_sha256_reference(path),
            }
            for stock_code, path in sorted(ezsearch_availability_overrides.items())
        }
    if statement_raw_dirs:
        identity["statement_raw_dirs"] = {
            stock_code: {
                "path": str(_resolved_path(path)),
                "files": _raw_directory_hashes(path),
            }
            for stock_code, path in sorted(statement_raw_dirs.items())
        }
    if xbrl_browser_dom_overrides:
        identity["xbrl_browser_dom_overrides"] = {
            stock_code: {
                "path": str(_resolved_path(path)),
                "sha256": _file_sha256_reference(path),
            }
            for stock_code, path in sorted(xbrl_browser_dom_overrides.items())
        }
    if xbrl_browser_evidence_overrides:
        identity["xbrl_browser_evidence_overrides"] = {
            stock_code: {
                "path": str(_resolved_path(path)),
                "sha256": _file_sha256_reference(path),
            }
            for stock_code, path in sorted(xbrl_browser_evidence_overrides.items())
        }
    if xbrl_encoding_repairs:
        identity["xbrl_encoding_repairs"] = {
            stock_code: policy
            for stock_code, policy in sorted(xbrl_encoding_repairs.items())
        }
    if universe_plan is not None:
        identity["universe_plan"] = {
            "path": str(_resolved_path(universe_plan)),
            "sha256": _file_sha256_reference(universe_plan),
        }
    return identity


def _new_batch_manifest(
    *,
    identity: dict[str, Any],
    child_runs: list[dict[str, Any]],
    max_companies: int,
    max_attempts_per_child: int,
    max_source_transport_failures: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": _BATCH_SCHEMA_VERSION,
        "operation_id": f"{identity['run_id_prefix']}:{_file_sha256_reference(Path(identity['canonical_manifest']['path']))[:24]}",
        "captured_at": _utc_now(),
        "request_count": len(child_runs),
        "max_batch_companies": max_companies,
        "max_attempts_per_child": max_attempts_per_child,
        "max_source_transport_failures": max_source_transport_failures,
        "source_failure_counts": {},
        "source_circuit_breakers": {},
        "source_failure_events": [],
        "max_total_attempts": len(child_runs) * max_attempts_per_child,
        "attempts_used": 0,
        "attempts_remaining": len(child_runs) * max_attempts_per_child,
        "batch_identity": identity,
        "child_runs": child_runs,
        "research_only": True,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
    }
    _refresh_batch_summary(payload, status="running")
    return payload


def _load_and_validate_resume(
    path: Path,
    *,
    identity: dict[str, Any],
    output_root: Path,
    max_attempts_per_child: int,
    max_source_transport_failures: int,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("batch resume manifest is unreadable") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != _BATCH_SCHEMA_VERSION:
        raise ValueError("batch resume requires a v2 batch manifest created by this driver")
    stored_max_attempts = payload.get("max_attempts_per_child")
    if stored_max_attempts is None:
        payload["max_attempts_per_child"] = max_attempts_per_child
    elif stored_max_attempts != max_attempts_per_child:
        raise ValueError("batch resume max-attempts-per-child does not match the existing operation")
    stored_source_budget = payload.get("max_source_transport_failures")
    if stored_source_budget is None:
        payload["max_source_transport_failures"] = max_source_transport_failures
    elif stored_source_budget != max_source_transport_failures:
        raise ValueError(
            "batch resume max-source-transport-failures does not match the existing operation"
        )
    if not isinstance(payload.get("source_failure_events"), list):
        payload["source_failure_events"] = []
    # 每次 resume 都是新的受控 transport 嘗試週期；歷史事件仍保留在 manifest。
    payload["source_failure_counts"] = {}
    payload["source_circuit_breakers"] = {}
    payload["source_circuit_reset_at"] = _utc_now()
    stored_identity = payload.get("batch_identity")
    if isinstance(stored_identity, dict) and "max_source_transport_failures" not in stored_identity:
        # 舊版 v2 manifest 沒有來源級預算；以目前預設值補入，保持 resume 可驗證。
        stored_identity = dict(stored_identity)
        stored_identity["max_source_transport_failures"] = max_source_transport_failures
        payload["batch_identity"] = stored_identity
    if stored_identity != identity:
        raise ValueError("batch resume inputs do not match the existing operation identity")
    child_runs = payload.get("child_runs")
    if not isinstance(child_runs, list) or len(child_runs) != len(identity["requests"]):
        raise ValueError("batch resume child_runs do not match the request list")
    expected_rows = identity["requests"]
    for row, expected in zip(child_runs, expected_rows):
        if not isinstance(row, dict) or any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("batch resume child identity does not match the request list")
        if row.get("status") not in _CHILD_STATUSES:
            raise ValueError("batch resume contains an unknown child status")
        attempts = row.get("attempts")
        if not isinstance(attempts, list):
            raise ValueError("batch resume child attempts must be a list")
        if row.get("status") == "running":
            row["status"] = "pending"
            if attempts and isinstance(attempts[-1], dict) and attempts[-1].get("status") == "running":
                attempts[-1]["status"] = "interrupted"
                attempts[-1]["finished_at"] = _utc_now()
                attempts[-1]["error_type"] = "BatchProcessInterrupted"
                attempts[-1]["error"] = "batch process ended before recording child completion"
    _refresh_batch_summary(payload)
    _write_batch_manifest(path, payload, create_only=False)
    return payload


def _record_attempt_failure(
    row: dict[str, Any],
    error: Exception,
    *,
    started_at: str,
    failure_source: str | None = None,
) -> None:
    attempts = row.setdefault("attempts", [])
    if not isinstance(attempts, list):
        raise ValueError("batch child attempts must be a list")
    attempt = attempts[-1] if attempts and isinstance(attempts[-1], dict) else None
    if attempt is None or attempt.get("status") != "running":
        attempt = {"attempt": len(attempts) + 1, "started_at": started_at}
        attempts.append(attempt)
    attempt.update(
        {
            "status": "failed",
            "finished_at": _utc_now(),
            "error_type": type(error).__name__,
            "error": str(error),
        }
    )
    if failure_source is not None:
        attempt["failure_source"] = failure_source
    row["status"] = "failed"


def _record_attempt_success(
    row: dict[str, Any],
    child_details: Mapping[str, Any],
    *,
    started_at: str,
    recovered: bool = False,
) -> None:
    attempts = row.setdefault("attempts", [])
    if not isinstance(attempts, list):
        raise ValueError("batch child attempts must be a list")
    attempt = attempts[-1] if attempts and isinstance(attempts[-1], dict) and attempts[-1].get("status") == "running" else None
    if attempt is None:
        attempt = {"attempt": len(attempts) + 1, "started_at": started_at}
        attempts.append(attempt)
    attempt.update({"status": "succeeded", "finished_at": _utc_now()})
    if recovered:
        attempt["recovered_existing_child"] = True
    row.update(child_details)
    row["status"] = "succeeded"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    request_source = parser.add_mutually_exclusive_group(required=True)
    request_source.add_argument(
        "--request",
        action="append",
        help="明確的 STOCK:MARKET:YYYY-Qn，可重複指定，單批最多八家公司",
    )
    request_source.add_argument(
        "--universe-plan",
        type=Path,
        help="已驗證的 mops-statement-universe-plan.v1；其 requests 會固定本批次範圍",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--run-id-prefix", default="v4-quarterly-batch")
    parser.add_argument(
        "--report-basis",
        choices=sorted(_REPORT_BASES),
        default="consolidated",
        help="報表範圍；individual 會要求 t164 A／個別報表身分",
    )
    parser.add_argument("--max-companies", type=int, default=_MAX_BATCH_COMPANIES)
    parser.add_argument(
        "--max-attempts-per-child",
        type=int,
        default=_DEFAULT_MAX_ATTEMPTS_PER_CHILD,
        help="每家公司最多嘗試次數；上限會寫入 checkpoint 並在 resume 固定",
    )
    parser.add_argument(
        "--max-source-transport-failures",
        type=int,
        default=_DEFAULT_MAX_SOURCE_TRANSPORT_FAILURES,
        help="同一批次同一官方來源的 transport 失敗上限；達上限即暫停後續公司",
    )
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument(
        "--listing-raw",
        action="append",
        default=[],
        metavar="STOCK=PATH",
        help="使用已保存的官方 t57 raw，僅供對應公司；可重複指定",
    )
    parser.add_argument(
        "--listing-evidence",
        action="append",
        default=[],
        metavar="STOCK=PATH",
        help="驗證已保存 t57 raw 的官方 HTTP evidence JSON；可重複指定",
    )
    parser.add_argument(
        "--listing-browser-evidence",
        action="append",
        default=[],
        metavar="STOCK=PATH",
        help="驗證已保存 t57 raw 的瀏覽器 DOM observation evidence JSON；可重複指定",
    )
    parser.add_argument(
        "--ezsearch-availability-evidence",
        action="append",
        default=[],
        metavar="STOCK=PATH",
        help="使用已保存官方 EZSearch 公告事件 evidence；可重複指定",
    )
    parser.add_argument(
        "--statement-raw-dir",
        action="append",
        default=[],
        metavar="STOCK=PATH",
        help="重用已保存的三張 t164 與 XBRL raw 目錄；可重複指定",
    )
    parser.add_argument(
        "--xbrl-browser-dom",
        action="append",
        default=[],
        metavar="STOCK=PATH",
        help="使用已保存官方 t164 XBRL 瀏覽器 DOM；可重複指定",
    )
    parser.add_argument(
        "--xbrl-browser-evidence",
        action="append",
        default=[],
        metavar="STOCK=PATH",
        help="驗證 t164 XBRL 瀏覽器 DOM identity／hash evidence；可重複指定",
    )
    parser.add_argument(
        "--xbrl-encoding-repair",
        action="append",
        default=[],
        metavar="STOCK=POLICY",
        help="明示套用已核對的 XBRL 編碼修復政策；可重複指定",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="驗證既有批次 manifest 的成功 child，只重試 pending／failed child",
    )
    args = parser.parse_args(argv)

    if not 1 <= args.max_companies <= _MAX_BATCH_COMPANIES:
        raise ValueError(f"--max-companies must be between 1 and {_MAX_BATCH_COMPANIES}")
    if not 1 <= args.max_attempts_per_child <= _MAX_ATTEMPTS_PER_CHILD:
        raise ValueError(
            "max-attempts-per-child must be between 1 and "
            f"{_MAX_ATTEMPTS_PER_CHILD}"
        )
    if not 1 <= args.max_source_transport_failures <= _MAX_SOURCE_TRANSPORT_FAILURES:
        raise ValueError(
            "max-source-transport-failures must be between 1 and "
            f"{_MAX_SOURCE_TRANSPORT_FAILURES}"
        )
    universe_plan_path: Path | None = None
    universe_plan: dict[str, Any] | None = None
    if args.universe_plan is not None:
        universe_plan_path = _resolved_path(args.universe_plan)
        if (
            universe_plan_path.is_symlink()
            or not universe_plan_path.is_file()
            or universe_plan_path.resolve(strict=False) != universe_plan_path
        ):
            raise ValueError("universe plan must be a regular non-alias file")
        universe_plan = load_universe_plan(universe_plan_path)
        plan_requests = universe_plan.get("requests")
        if not isinstance(plan_requests, list) or not all(
            isinstance(value, str) for value in plan_requests
        ):
            raise ValueError("universe plan requests are malformed")
        raw_requests = [str(value) for value in plan_requests]
    else:
        raw_requests = list(args.request or [])
    if len(raw_requests) > args.max_companies:
        raise ValueError("request count exceeds the explicit batch limit")
    requests: list[tuple[str, str, int, int]] = [_parse_request(value) for value in raw_requests]
    if not requests:
        raise ValueError("at least one --request or --universe-plan request is required")
    if len(set(requests)) != len(requests):
        raise ValueError("duplicate company/market/period request")
    if not isinstance(args.run_id_prefix, str) or not args.run_id_prefix.strip():
        raise ValueError("--run-id-prefix must be non-empty")

    listing_overrides: dict[str, Path] = {}
    for value in args.listing_raw:
        stock_code, path = _parse_listing_override(value)
        if stock_code in listing_overrides:
            raise ValueError("duplicate listing override stock")
        listing_overrides[stock_code] = path
    listing_evidence_overrides: dict[str, Path] = {}
    for value in args.listing_evidence:
        stock_code, path = _parse_listing_evidence_override(value)
        if stock_code in listing_evidence_overrides:
            raise ValueError("duplicate listing evidence stock")
        listing_evidence_overrides[stock_code] = path
    listing_browser_evidence_overrides: dict[str, Path] = {}
    for value in args.listing_browser_evidence:
        stock_code, path = _parse_listing_browser_evidence_override(value)
        if stock_code in listing_browser_evidence_overrides:
            raise ValueError("duplicate browser listing evidence stock")
        listing_browser_evidence_overrides[stock_code] = path
    ezsearch_availability_overrides: dict[str, Path] = {}
    for value in args.ezsearch_availability_evidence:
        stock_code, path = _parse_ezsearch_availability_override(value)
        if stock_code in ezsearch_availability_overrides:
            raise ValueError("duplicate EZSearch availability evidence stock")
        ezsearch_availability_overrides[stock_code] = path
    statement_raw_dirs: dict[str, Path] = {}
    for value in args.statement_raw_dir:
        stock_code, path = _parse_statement_raw_dir_override(value)
        if stock_code in statement_raw_dirs:
            raise ValueError("duplicate statement raw directory stock")
        statement_raw_dirs[stock_code] = path
    xbrl_browser_dom_overrides: dict[str, Path] = {}
    for value in args.xbrl_browser_dom:
        stock_code, path = _parse_xbrl_browser_dom_override(value)
        if stock_code in xbrl_browser_dom_overrides:
            raise ValueError("duplicate XBRL browser DOM stock")
        xbrl_browser_dom_overrides[stock_code] = path
    xbrl_browser_evidence_overrides: dict[str, Path] = {}
    for value in args.xbrl_browser_evidence:
        stock_code, path = _parse_xbrl_browser_evidence_override(value)
        if stock_code in xbrl_browser_evidence_overrides:
            raise ValueError("duplicate XBRL browser evidence stock")
        xbrl_browser_evidence_overrides[stock_code] = path
    xbrl_encoding_repairs: dict[str, str] = {}
    for value in args.xbrl_encoding_repair:
        stock_code, policy = _parse_xbrl_encoding_repair_override(value)
        if stock_code in xbrl_encoding_repairs:
            raise ValueError("duplicate XBRL encoding repair stock")
        xbrl_encoding_repairs[stock_code] = policy
    requested_stocks = {request[0] for request in requests}
    if not set(listing_overrides).issubset(requested_stocks):
        raise ValueError("listing override stock must be included in --request")
    if not set(listing_evidence_overrides).issubset(requested_stocks):
        raise ValueError("listing evidence stock must be included in --request")
    if not set(listing_browser_evidence_overrides).issubset(requested_stocks):
        raise ValueError("browser listing evidence stock must be included in --request")
    if not set(ezsearch_availability_overrides).issubset(requested_stocks):
        raise ValueError("EZSearch availability evidence stock must be included in --request")
    if not set(listing_evidence_overrides).issubset(listing_overrides):
        raise ValueError("listing evidence requires a matching --listing-raw")
    if not set(listing_browser_evidence_overrides).issubset(listing_overrides):
        raise ValueError("browser listing evidence requires a matching --listing-raw")
    if set(listing_evidence_overrides) & set(listing_browser_evidence_overrides):
        raise ValueError("HTTP and browser listing evidence are mutually exclusive")
    if ezsearch_availability_overrides and (
        listing_overrides or listing_evidence_overrides or listing_browser_evidence_overrides
    ):
        raise ValueError("EZSearch availability evidence is mutually exclusive with t57 listing inputs")
    if not set(statement_raw_dirs).issubset(requested_stocks):
        raise ValueError("statement raw directory stock must be included in --request")
    if not set(xbrl_browser_dom_overrides).issubset(requested_stocks):
        raise ValueError("XBRL browser DOM stock must be included in --request")
    if not set(xbrl_browser_evidence_overrides).issubset(requested_stocks):
        raise ValueError("XBRL browser evidence stock must be included in --request")
    if not set(xbrl_encoding_repairs).issubset(requested_stocks):
        raise ValueError("XBRL encoding repair stock must be included in --request")
    if set(xbrl_browser_dom_overrides) != set(xbrl_browser_evidence_overrides):
        raise ValueError("XBRL browser DOM and evidence overrides must match")
    if len(set(statement_raw_dirs.values())) != len(statement_raw_dirs):
        raise ValueError("statement raw directory paths must be distinct")
    if len(set(xbrl_browser_dom_overrides.values())) != len(xbrl_browser_dom_overrides):
        raise ValueError("XBRL browser DOM paths must be distinct")
    if len(set(xbrl_browser_evidence_overrides.values())) != len(xbrl_browser_evidence_overrides):
        raise ValueError("XBRL browser evidence paths must be distinct")
    if len(set(listing_overrides.values())) != len(listing_overrides):
        raise ValueError("listing override paths must be distinct")
    if len(set(listing_browser_evidence_overrides.values())) != len(listing_browser_evidence_overrides):
        raise ValueError("browser listing evidence paths must be distinct")
    if len(set(ezsearch_availability_overrides.values())) != len(ezsearch_availability_overrides):
        raise ValueError("EZSearch availability evidence paths must be distinct")

    run_ids = [
        (
            f"{args.run_id_prefix.strip().lower()}-"
            f"{market}-{stock_code}-{period_year}q{season}"
        )
        for stock_code, market, period_year, season in requests
    ]
    if any(re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,80}", run_id) is None for run_id in run_ids):
        raise ValueError("generated child run id is not safe")
    output_root = _resolved_path(args.output_root)
    predicted_conflicts = tuple(
        output_root / run_id / filename
        for run_id in run_ids
        for filename in ("statement-pit-candidate.json", "run-manifest.json")
    )
    manifest_path = validate_research_output_path(
        args.batch_manifest,
        conflicts=predicted_conflicts,
        allow_existing=args.resume,
    )
    if universe_plan_path is not None:
        validated_plan_path = validate_research_output_path(
            universe_plan_path,
            conflicts=(*predicted_conflicts, manifest_path),
            allow_existing=True,
        )
        if validated_plan_path != universe_plan_path:
            raise ValueError("universe plan path must be resolved before use")
    for path in listing_overrides.values():
        if not path.is_file():
            raise FileNotFoundError(path)
        listing_conflicts = (
            *predicted_conflicts,
            manifest_path,
            *(other for other in listing_overrides.values() if other != path),
        )
        validated_listing_path = validate_research_output_path(
            path,
            conflicts=listing_conflicts,
            allow_existing=True,
        )
        if validated_listing_path != path:
            raise ValueError("listing override path must be resolved before use")
    for path in listing_evidence_overrides.values():
        if not path.is_file():
            raise FileNotFoundError(path)
        evidence_conflicts = (
            *predicted_conflicts,
            manifest_path,
            *listing_overrides.values(),
            *(other for other in listing_evidence_overrides.values() if other != path),
        )
        validated_evidence_path = validate_research_output_path(
            path,
            conflicts=evidence_conflicts,
            allow_existing=True,
        )
        if validated_evidence_path != path:
            raise ValueError("listing evidence path must be resolved before use")
    for path in listing_browser_evidence_overrides.values():
        if not path.is_file():
            raise FileNotFoundError(path)
        browser_evidence_conflicts = (
            *predicted_conflicts,
            manifest_path,
            *listing_overrides.values(),
            *listing_evidence_overrides.values(),
            *(other for other in listing_browser_evidence_overrides.values() if other != path),
        )
        validated_browser_evidence_path = validate_research_output_path(
            path,
            conflicts=browser_evidence_conflicts,
            allow_existing=True,
        )
        if validated_browser_evidence_path != path:
            raise ValueError("browser listing evidence path must be resolved before use")
    for path in ezsearch_availability_overrides.values():
        if not path.is_file():
            raise FileNotFoundError(path)
        ezsearch_conflicts = (
            *predicted_conflicts,
            manifest_path,
            *listing_overrides.values(),
            *listing_evidence_overrides.values(),
            *listing_browser_evidence_overrides.values(),
            *(other for other in ezsearch_availability_overrides.values() if other != path),
        )
        validated_ezsearch_path = validate_research_output_path(
            path,
            conflicts=ezsearch_conflicts,
            allow_existing=True,
        )
        if validated_ezsearch_path != path:
            raise ValueError("EZSearch availability evidence path must be resolved before use")
    for path in statement_raw_dirs.values():
        _raw_directory_hashes(path)
    for path in xbrl_browser_dom_overrides.values():
        if not path.is_file():
            raise FileNotFoundError(path)
        browser_dom_conflicts = (
            *predicted_conflicts,
            manifest_path,
            *listing_overrides.values(),
            *listing_evidence_overrides.values(),
            *listing_browser_evidence_overrides.values(),
            *ezsearch_availability_overrides.values(),
            *xbrl_browser_evidence_overrides.values(),
            *(other for other in xbrl_browser_dom_overrides.values() if other != path),
        )
        validated_dom_path = validate_research_output_path(
            path,
            conflicts=browser_dom_conflicts,
            allow_existing=True,
        )
        if validated_dom_path != path:
            raise ValueError("XBRL browser DOM path must be resolved before use")
    for path in xbrl_browser_evidence_overrides.values():
        if not path.is_file():
            raise FileNotFoundError(path)
        browser_evidence_conflicts = (
            *predicted_conflicts,
            manifest_path,
            *listing_overrides.values(),
            *listing_evidence_overrides.values(),
            *listing_browser_evidence_overrides.values(),
            *ezsearch_availability_overrides.values(),
            *xbrl_browser_dom_overrides.values(),
            *(other for other in xbrl_browser_evidence_overrides.values() if other != path),
        )
        validated_evidence_path = validate_research_output_path(
            path,
            conflicts=browser_evidence_conflicts,
            allow_existing=True,
        )
        if validated_evidence_path != path:
            raise ValueError("XBRL browser evidence path must be resolved before use")
    identity = _batch_identity(
        output_root=output_root,
        run_id_prefix=args.run_id_prefix,
        requests=requests,
        run_ids=run_ids,
        canonical_manifest=args.canonical_manifest,
        canonical_dataset=args.canonical_dataset,
        listing_overrides=listing_overrides,
        listing_evidence_overrides=listing_evidence_overrides,
        listing_browser_evidence_overrides=listing_browser_evidence_overrides,
        ezsearch_availability_overrides=ezsearch_availability_overrides,
        statement_raw_dirs=statement_raw_dirs,
        xbrl_browser_dom_overrides=xbrl_browser_dom_overrides,
        xbrl_browser_evidence_overrides=xbrl_browser_evidence_overrides,
        xbrl_encoding_repairs=xbrl_encoding_repairs,
        universe_plan=universe_plan_path,
        max_source_transport_failures=args.max_source_transport_failures,
        report_basis=args.report_basis,
    )
    if args.resume:
        if not manifest_path.is_file():
            raise ValueError("--resume requires an existing batch manifest")
        manifest = _load_and_validate_resume(
            manifest_path,
            identity=identity,
            output_root=output_root,
            max_attempts_per_child=args.max_attempts_per_child,
            max_source_transport_failures=args.max_source_transport_failures,
        )
    else:
        if manifest_path.exists():
            raise ValueError("batch manifest already exists; use --resume to continue it")
        manifest = _new_batch_manifest(
            identity=identity,
            child_runs=_initial_child_rows(
                requests,
                run_ids,
                output_root,
                report_basis=args.report_basis,
            ),
            max_companies=args.max_companies,
            max_attempts_per_child=args.max_attempts_per_child,
            max_source_transport_failures=args.max_source_transport_failures,
        )
        _write_batch_manifest(manifest_path, manifest, create_only=True)

    child_runs = manifest.get("child_runs")
    if not isinstance(child_runs, list):
        raise ValueError("batch manifest child_runs must be a list")
    max_attempts_per_child = manifest.get("max_attempts_per_child")
    if not isinstance(max_attempts_per_child, int) or not (
        1 <= max_attempts_per_child <= _MAX_ATTEMPTS_PER_CHILD
    ):
        raise ValueError("batch manifest max-attempts-per-child is invalid")
    max_source_transport_failures = manifest.get("max_source_transport_failures")
    if not isinstance(max_source_transport_failures, int) or not (
        1 <= max_source_transport_failures <= _MAX_SOURCE_TRANSPORT_FAILURES
    ):
        raise ValueError("batch manifest max-source-transport-failures is invalid")
    source_failure_counts = manifest.setdefault("source_failure_counts", {})
    source_circuit_breakers = manifest.setdefault("source_circuit_breakers", {})
    source_failure_events = manifest.setdefault("source_failure_events", [])
    if not isinstance(source_failure_counts, dict) or not isinstance(source_circuit_breakers, dict):
        raise ValueError("batch manifest source circuit state is invalid")
    if not isinstance(source_failure_events, list):
        raise ValueError("batch manifest source failure events are invalid")
    for row in child_runs:
        if not isinstance(row, dict):
            raise ValueError("batch manifest child run must be an object")
        status = row.get("status")
        if status == "succeeded":
            _validate_child_artifacts(row, output_root=output_root)
            attempts = row.get("attempts")
            if isinstance(attempts, list):
                row["remaining_attempts"] = max(0, max_attempts_per_child - len(attempts))
            row["last_verified_at"] = _utc_now()
            continue
        if status == "integrity_error":
            raise ValueError(
                f"batch child is marked integrity_error and cannot be retried: {row.get('run_id')}"
            )
        # 若程序在 child replace 後、寫入成功紀錄前中止，先驗證現有 immutable child。
        child_candidate, child_manifest = _expected_child_paths(output_root, str(row["run_id"]))
        if child_candidate.exists() or child_manifest.exists():
            try:
                recovered = _validate_child_artifacts(row, output_root=output_root)
            except Exception as error:
                row["status"] = "integrity_error"
                _record_attempt_failure(row, error, started_at=_utc_now())
                row["status"] = "integrity_error"
                _refresh_batch_summary(manifest)
                _write_batch_manifest(manifest_path, manifest, create_only=False)
                raise
            _record_attempt_success(
                row,
                recovered,
                started_at=_utc_now(),
                recovered=True,
            )
            _refresh_batch_summary(manifest)
            _write_batch_manifest(manifest_path, manifest, create_only=False)
            continue

        if source_circuit_breakers:
            # 來源仍在本次執行的熔斷狀態時只保留 pending，不再重送同一來源。
            row["deferred_reason"] = "source_transport_circuit_open"
            _refresh_batch_summary(manifest)
            _write_batch_manifest(manifest_path, manifest, create_only=False)
            continue

        attempts = row.setdefault("attempts", [])
        if not isinstance(attempts, list):
            raise ValueError("batch child attempts must be a list")
        if len(attempts) >= max_attempts_per_child:
            row["status"] = "failed"
            row["attempt_budget_exhausted"] = True
            row["remaining_attempts"] = 0
            if "budget_exhausted_at" not in row:
                row["budget_exhausted_at"] = _utc_now()
            _refresh_batch_summary(manifest)
            _write_batch_manifest(manifest_path, manifest, create_only=False)
            continue
        row["remaining_attempts"] = max_attempts_per_child - len(attempts)
        started_at = _utc_now()
        attempts.append(
            {
                "attempt": len(attempts) + 1,
                "started_at": started_at,
                "status": "running",
            }
        )
        row["status"] = "running"
        _refresh_batch_summary(manifest)
        _write_batch_manifest(manifest_path, manifest, create_only=False)
        try:
            stock_code = str(row["stock_code"])
            market = str(row["market"])
            period = str(row["period"])
            period_year, season_text = period.split("-Q", 1)
            statement_replay_dir = statement_raw_dirs.get(stock_code)
            if statement_replay_dir is None:
                statement_replay_dir = _partial_replay_raw_dir(
                    row,
                    output_root=output_root,
                )
            paths = build_candidate(
                stock_code=stock_code,
                roc_year=int(period_year) - 1911,
                season=int(season_text),
                market=market,
                output_root=output_root,
                run_id=str(row["run_id"]),
                canonical_manifest=args.canonical_manifest,
                canonical_dataset=args.canonical_dataset,
                timeout_seconds=args.timeout_seconds,
                listing_response_path=listing_overrides.get(stock_code),
                listing_evidence_path=listing_evidence_overrides.get(stock_code),
                listing_browser_evidence_path=listing_browser_evidence_overrides.get(stock_code),
                ezsearch_availability_evidence_path=ezsearch_availability_overrides.get(stock_code),
                statement_raw_dir=statement_replay_dir,
                xbrl_browser_dom_path=xbrl_browser_dom_overrides.get(stock_code),
                xbrl_browser_evidence_path=xbrl_browser_evidence_overrides.get(stock_code),
                xbrl_encoding_repair=xbrl_encoding_repairs.get(stock_code),
                report_basis=str(row.get("report_basis", "consolidated")),
                partial_output_root=output_root / "_partial",
            )
            expected_candidate, expected_manifest = _expected_child_paths(
                output_root, str(row["run_id"])
            )
            if _path_identity(Path(paths["candidate"])) != _path_identity(expected_candidate) or _path_identity(Path(paths["manifest"])) != _path_identity(expected_manifest):
                raise ValueError("single-stock fetcher returned a child outside the requested immutable run")
            details = _validate_child_artifacts(row, output_root=output_root)
            _record_attempt_success(row, details, started_at=started_at)
        except Exception as error:
            # 完成一家公司不依賴其他公司的網路／資料狀態；保留錯誤後繼續下一列。
            try:
                partial_root = _resolved_path(output_root) / "_partial" / str(row.get("run_id", ""))
                partial_failure = partial_root / "partial-failure.json"
                if partial_failure.is_file() and partial_failure.resolve(strict=False) == partial_failure:
                    receipt = json.loads(partial_failure.read_text(encoding="utf-8"))
                    if isinstance(receipt, Mapping):
                        row["partial_staging"] = str(partial_root)
                        row["partial_failure_sha256"] = _file_sha256_reference(partial_failure)
                        row["partial_phase"] = str(receipt.get("phase", "unknown"))
                        row["partial_replay_ready"] = receipt.get("replay_ready") is True
            except Exception:
                # partial receipt 是輔助恢復資訊，不能遮蔽原始失敗原因。
                pass
            failure_source = _transport_failure_source(error)
            _record_attempt_failure(
                row,
                error,
                started_at=started_at,
                failure_source=failure_source,
            )
            if failure_source is not None:
                failure_count = int(source_failure_counts.get(failure_source, 0)) + 1
                source_failure_counts[failure_source] = failure_count
                source_failure_events.append(
                    {
                        "source": failure_source,
                        "stock_code": str(row.get("stock_code", "")),
                        "run_id": str(row.get("run_id", "")),
                        "attempt": len(attempts),
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "observed_at": _utc_now(),
                    }
                )
                if failure_count >= max_source_transport_failures:
                    source_circuit_breakers[failure_source] = {
                        "opened_at": _utc_now(),
                        "failure_count": failure_count,
                        "last_error": str(error),
                    }
            if child_candidate.exists() or child_manifest.exists():
                row["status"] = "integrity_error"
        row["remaining_attempts"] = max(0, max_attempts_per_child - len(attempts))
        if row["status"] == "failed" and row["remaining_attempts"] == 0:
            row["attempt_budget_exhausted"] = True
        _refresh_batch_summary(manifest)
        _write_batch_manifest(manifest_path, manifest, create_only=False)

    _refresh_batch_summary(manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
