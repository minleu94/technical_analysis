"""從保存的官方公司 registry 建立可重跑的 MOPS 季報 universe plan。

這個入口只讀取已保存的 companies.csv，不啟動網路請求，也不寫入 DATA_ROOT。
計畫會保存來源檔案 hash、完整 eligible 分母、排除原因、已處理鍵與明確選取
的公司／市場／期別；後續 batch driver 以 plan hash 綁定同一批次 identity。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.mops_statement_candidate_adapter import validate_research_output_path


PLAN_SCHEMA_VERSION = "mops-statement-universe-plan.v1"
_STOCK_CODE_RE = re.compile(r"^\d{4}$")
_PERIOD_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_REGISTRY_MARKET_TO_BATCH_MARKET = {"twse": "sii", "tpex": "otc"}
_SUPPORTED_REGISTRY_MARKETS = frozenset(_REGISTRY_MARKET_TO_BATCH_MARKET)
_ETF_NAME_MARKERS = ("ETF", "ETN", "指數股票型", "槓桿型", "反向型")
_BATCH_MARKET_TO_REGISTRY_MARKET = {
    value: key for key, value in _REGISTRY_MARKET_TO_BATCH_MARKET.items()
}
_PROFILES = frozenset({"representative_initial", "continuation"})
_MAX_BATCH_COMPANIES = 8
_SUPERSESSION_SCHEMA_VERSION = "mops-statement-artifact-correction.v1"


def _sha256_reference(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_json(value: object) -> str:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _parse_period(value: str) -> tuple[int, int]:
    match = _PERIOD_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError("period must be YYYY-Q1 through YYYY-Q4")
    year, season = int(match.group(1)), int(match.group(2))
    if year < 1900:
        raise ValueError("period year must be at least 1900")
    return year, season


def _parse_key(value: str, *, option: str) -> tuple[str, str]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"{option} must be STOCK:twse or STOCK:tpex")
    stock_code, market = (part.strip() for part in parts)
    if not _STOCK_CODE_RE.fullmatch(stock_code):
        raise ValueError(f"{option} stock must be a four-digit code")
    if market not in _SUPPORTED_REGISTRY_MARKETS:
        raise ValueError(f"{option} market must be twse or tpex")
    return stock_code, market


def _normalize_row(row: Mapping[str, object], *, row_number: int) -> dict[str, str]:
    required = (
        "industry_category",
        "stock_id",
        "stock_name",
        "type",
        "date",
        "download_time",
    )
    values = {key: str(row.get(key, "") or "").strip() for key in required}
    if any(not values[key] for key in required):
        raise ValueError(f"company registry row {row_number} is missing a required field")
    return values


def _is_etf_like(row: Mapping[str, str]) -> bool:
    name = row["stock_name"].upper()
    code = row["stock_id"]
    return code.startswith(("00", "01")) or any(
        marker in name for marker in _ETF_NAME_MARKERS
    )


def _load_registry(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError("registry path must be a regular file")
    with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        required = (
            "industry_category",
            "stock_id",
            "stock_name",
            "type",
            "date",
            "download_time",
        )
        if fields != required:
            raise ValueError(
                "company registry columns do not match the saved official registry contract"
            )
        rows = [
            _normalize_row(row, row_number=index)
            for index, row in enumerate(reader, start=2)
        ]
    if not rows:
        raise ValueError("company registry contains no rows")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["stock_id"], row["type"])
        if key in seen:
            raise ValueError(f"company registry contains duplicate key: {key[0]}:{key[1]}")
        seen.add(key)
    dates = [
        row["date"]
        for row in rows
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"])
    ]
    download_times = sorted({row["download_time"] for row in rows})
    source = {
        "path": str(resolved),
        "sha256": _sha256_reference(resolved),
        "byte_count": resolved.stat().st_size,
        "row_count": len(rows),
        "columns": list(fields),
        "registry_snapshot_date": max(dates) if dates else None,
        "registry_download_times": download_times,
        "source_kind": "persisted_registry_derived_from_official_t187ap03_L_O",
        "capture_time_basis": (
            "companies.csv download_time field; raw HTTP response timestamp is not present in this file"
        ),
    }
    return rows, source


def _classify_exclusion(row: Mapping[str, str]) -> str | None:
    if row["type"] not in _SUPPORTED_REGISTRY_MARKETS:
        return "unsupported_registry_market"
    if not _STOCK_CODE_RE.fullmatch(row["stock_id"]):
        return "non_four_digit_or_depository_receipt"
    if row["industry_category"] == "存託憑證":
        return "depository_receipt"
    if _is_etf_like(row):
        return "etf_or_etn_pattern"
    return None


def _verify_child_artifacts(
    candidate_path: Path,
    manifest_path: Path,
    *,
    expected_period: str,
) -> dict[str, str]:
    """驗證已完成 child 的 candidate／manifest／raw hash 後回傳完成鍵。"""
    candidate_path = candidate_path.expanduser().resolve(strict=True)
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    if (
        candidate_path.is_symlink()
        or manifest_path.is_symlink()
        or not candidate_path.is_file()
        or not manifest_path.is_file()
    ):
        raise ValueError("verified artifact must contain regular candidate and manifest files")
    try:
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("verified artifact JSON is unreadable") from error
    if not isinstance(candidate, Mapping) or not isinstance(manifest, Mapping):
        raise ValueError("verified artifact JSON must be objects")
    if (
        manifest.get("schema_version")
        not in {"mops-statement-pit-run-manifest.v1", "mops-statement-pit-run-manifest.v2"}
        or manifest.get("research_only") is not True
        or manifest.get("formal_oos_allowed") is not False
    ):
        raise ValueError("verified child manifest is not a research-only v1 manifest")
    if manifest.get("run_id") and not isinstance(manifest.get("run_id"), str):
        raise ValueError("verified child run_id is malformed")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or "run-manifest.json" in files:
        raise ValueError("verified child manifest files are missing or self-referential")
    root = manifest_path.parent
    raw_root = root / "raw"
    legacy_names = {
        "candidate": "statement-pit-candidate.json",
        "statement_sources": "statement-sources.json",
        "availability_source": "availability-source.json",
    }
    for name, expected_hash in files.items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("verified child manifest contains an unsafe file name")
        path = raw_root / name.removeprefix("raw_") if name.startswith("raw_") else root / legacy_names.get(name, name)
        if not isinstance(expected_hash, str) or not path.is_file() or path.resolve(strict=False) != path:
            raise ValueError(f"verified child file is missing or aliased: {name}")
        if _sha256_reference(path) != expected_hash:
            raise ValueError(f"verified child hash mismatch: {name}")
    raw_files = manifest.get("raw_files")
    if raw_files is not None:
        if not isinstance(raw_files, Mapping):
            raise ValueError("verified child raw_files is malformed")
        for name, expected_hash in raw_files.items():
            path = raw_root / str(name)
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or not path.is_file()
                or path.resolve(strict=False) != path
                or not isinstance(expected_hash, str)
                or _sha256_reference(path) != expected_hash
            ):
                raise ValueError(f"verified child raw hash mismatch: {name}")
    if candidate.get("research_only") is not True or candidate.get("formal_oos_allowed") is not False:
        raise ValueError("verified candidate must remain research-only")
    rows = candidate.get("rows")
    summary = candidate.get("pit_coverage_summary")
    if not isinstance(rows, list) or not rows or not isinstance(summary, Mapping):
        raise ValueError("verified candidate has no rows or coverage summary")
    stock_code = summary.get("stock_code")
    batch_market = summary.get("market_request")
    period = summary.get("period")
    if (
        not isinstance(stock_code, str)
        or not isinstance(batch_market, str)
        or batch_market not in _BATCH_MARKET_TO_REGISTRY_MARKET
        or period != expected_period
    ):
        raise ValueError("verified child identity does not match the plan period")
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or row.get("stock_code") != stock_code
            or row.get("market") != batch_market
            or row.get("period") != period
        ):
            raise ValueError("verified candidate contains a mismatched row identity")
    return {
        "stock_code": stock_code,
        "registry_market": _BATCH_MARKET_TO_REGISTRY_MARKET[batch_market],
        "batch_market": batch_market,
        "period": str(period),
        "candidate_path": str(candidate_path),
        "candidate_sha256": _sha256_reference(candidate_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_reference(manifest_path),
        "candidate_row_count": str(len(rows)),
    }


def _load_supersession_records(
    paths: Sequence[Path],
    *,
    expected_period: str,
) -> list[dict[str, Any]]:
    """驗證 immutable child 的 replacement 關係，不覆寫任一舊 artifact。"""

    records: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for requested in paths:
        path = Path(requested).expanduser().resolve(strict=True)
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("supersession record must be a regular file")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("supersession record is unreadable") from error
        if not isinstance(payload, Mapping):
            raise ValueError("supersession record must be an object")
        if payload.get("schema_version") != _SUPERSESSION_SCHEMA_VERSION:
            raise ValueError("supersession record schema is unsupported")
        if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
            raise ValueError("supersession record must remain research-only")
        if payload.get("status") != "accepted_replacement":
            raise ValueError("supersession record status is not accepted_replacement")
        target = payload.get("target")
        superseded = payload.get("superseded")
        replacement = payload.get("replacement")
        if not isinstance(target, Mapping) or not isinstance(superseded, Mapping) or not isinstance(replacement, Mapping):
            raise ValueError("supersession record target and artifacts are incomplete")
        stock_code = target.get("stock_code")
        registry_market = target.get("registry_market")
        period = target.get("period")
        if (
            not isinstance(stock_code, str)
            or not _STOCK_CODE_RE.fullmatch(stock_code)
            or registry_market not in _SUPPORTED_REGISTRY_MARKETS
            or period != expected_period
        ):
            raise ValueError("supersession record target identity is invalid")

        def _verify_reference(
            reference: Mapping[str, object],
            *,
            label: str,
        ) -> dict[str, str]:
            candidate_value = reference.get("candidate_path")
            manifest_value = reference.get("manifest_path")
            candidate_hash = reference.get("candidate_sha256")
            manifest_hash = reference.get("manifest_sha256")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (
                    candidate_value,
                    manifest_value,
                    candidate_hash,
                    manifest_hash,
                )
            ):
                raise ValueError(f"supersession {label} artifact reference is incomplete")
            details = _verify_child_artifacts(
                Path(str(candidate_value)),
                Path(str(manifest_value)),
                expected_period=expected_period,
            )
            if details["candidate_sha256"] != candidate_hash or details["manifest_sha256"] != manifest_hash:
                raise ValueError(f"supersession {label} artifact hash mismatch")
            if (
                details["stock_code"] != stock_code
                or details["registry_market"] != registry_market
            ):
                raise ValueError(f"supersession {label} artifact identity mismatch")
            return details

        old_details = _verify_reference(superseded, label="superseded")
        new_details = _verify_reference(replacement, label="replacement")
        if old_details["candidate_sha256"] == new_details["candidate_sha256"]:
            raise ValueError("supersession replacement must have a new candidate hash")
        if (
            old_details["candidate_path"] == new_details["candidate_path"]
            or old_details["manifest_path"] == new_details["manifest_path"]
        ):
            raise ValueError("supersession replacement must use a new immutable child")
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("supersession record reason is required")
        records.append(
            {
                "record_path": str(path),
                "record_sha256": _sha256_reference(path),
                "stock_code": stock_code,
                "registry_market": registry_market,
                "batch_market": new_details["batch_market"],
                "period": expected_period,
                "reason": reason,
                "superseded": old_details,
                "replacement": new_details,
            }
        )
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = (
            str(record["stock_code"]),
            str(record["registry_market"]),
            str(record["period"]),
        )
        previous = by_key.get(key)
        if previous is not None and previous["record_sha256"] != record["record_sha256"]:
            raise ValueError("multiple supersession records target the same company period")
        by_key[key] = record
    return [by_key[key] for key in sorted(by_key)]


def _load_verified_artifacts(
    paths: Sequence[Path],
    *,
    expected_period: str,
    supersession_records: Sequence[Path] = (),
) -> tuple[dict[tuple[str, str], dict[str, str]], list[dict[str, str]]]:
    """從 batch manifest 或 child manifest 取得已完成鍵，不信任 caller 自填狀態。"""
    completed: dict[tuple[str, str], dict[str, str]] = {}
    references: list[dict[str, str]] = []
    correction_paths = [Path(path) for path in supersession_records]
    for requested in paths:
        path = Path(requested).expanduser().resolve(strict=True)
        if path.is_symlink() or not path.is_file():
            raise ValueError("verified artifact path must be a regular file")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("verified artifact manifest is unreadable") from error
        if not isinstance(payload, Mapping):
            raise ValueError("verified artifact manifest must be an object")
        if payload.get("schema_version") == _SUPERSESSION_SCHEMA_VERSION:
            correction_paths.append(path)
            continue
        pairs: list[tuple[Path, Path, str]] = []
        if payload.get("schema_version") == "mops-statement-pit-batch-manifest.v2":
            if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
                raise ValueError("verified batch manifest must remain research-only")
            child_runs = payload.get("child_runs")
            if not isinstance(child_runs, list):
                raise ValueError("verified batch manifest child_runs is malformed")
            for child in child_runs:
                if not isinstance(child, Mapping) or child.get("status") != "succeeded":
                    continue
                candidate = child.get("candidate")
                manifest = child.get("manifest")
                if not isinstance(candidate, str) or not isinstance(manifest, str):
                    raise ValueError("verified batch child paths are incomplete")
                pairs.append((Path(candidate), Path(manifest), "batch_manifest"))
        elif payload.get("schema_version") in {
            "mops-statement-pit-run-manifest.v1",
            "mops-statement-pit-run-manifest.v2",
        }:
            pairs.append((path.parent / "statement-pit-candidate.json", path, "child_manifest"))
        else:
            raise ValueError("verified artifact must be a v1 child or v2 batch manifest")
        for candidate_path, manifest_path, artifact_kind in pairs:
            verified = _verify_child_artifacts(
                candidate_path,
                manifest_path,
                expected_period=expected_period,
            )
            key = (verified["stock_code"], verified["registry_market"])
            previous = completed.get(key)
            if previous is not None and previous["candidate_sha256"] != verified["candidate_sha256"]:
                raise ValueError(
                    "verified completion has conflicting candidate revisions: "
                    f"{key[0]}:{key[1]}"
                )
            completed[key] = verified
            references.append(
                {
                    "artifact_kind": artifact_kind,
                    "artifact_path": str(path),
                    "artifact_sha256": _sha256_reference(path),
                    "stock_code": verified["stock_code"],
                    "registry_market": verified["registry_market"],
                    "batch_market": verified["batch_market"],
                    "period": verified["period"],
                    "candidate_sha256": verified["candidate_sha256"],
                    "manifest_sha256": verified["manifest_sha256"],
                }
            )
    corrections = _load_supersession_records(
        correction_paths,
        expected_period=expected_period,
    )
    for correction in corrections:
        key = (str(correction["stock_code"]), str(correction["registry_market"]))
        old_hash = str(correction["superseded"]["candidate_sha256"])
        replacement = dict(correction["replacement"])
        previous = completed.get(key)
        if previous is not None:
            if previous["candidate_sha256"] == old_hash:
                completed[key] = replacement
            elif previous["candidate_sha256"] != replacement["candidate_sha256"]:
                raise ValueError(
                    "supersession replacement conflicts with an existing completion: "
                    f"{key[0]}:{key[1]}"
                )
        else:
            completed[key] = replacement
        references = [
            reference
            for reference in references
            if not (
                reference["stock_code"] == key[0]
                and reference["registry_market"] == key[1]
                and reference["candidate_sha256"] == old_hash
            )
        ]
        references.append(
            {
                "artifact_kind": "supersession_record",
                "artifact_path": correction["record_path"],
                "artifact_sha256": correction["record_sha256"],
                "stock_code": correction["stock_code"],
                "registry_market": correction["registry_market"],
                "batch_market": correction["batch_market"],
                "period": correction["period"],
                "candidate_sha256": replacement["candidate_sha256"],
                "manifest_sha256": replacement["manifest_sha256"],
                "supersedes_candidate_sha256": old_hash,
                "supersedes_manifest_sha256": correction["superseded"]["manifest_sha256"],
                "reason": correction["reason"],
            }
        )
    unique_references = {
        (
            item["artifact_path"],
            item["stock_code"],
            item["registry_market"],
        ): item
        for item in references
    }
    return completed, [
        unique_references[key]
        for key in sorted(unique_references)
    ]


def build_universe_plan(
    *,
    registry_path: Path,
    period: str,
    selected: Sequence[tuple[str, str]] = (),
    profile: str = "continuation",
    verified_completed: Sequence[tuple[str, str]] = (),
    verified_artifacts: Sequence[Path] = (),
    supersession_records: Sequence[Path] = (),
    caller_excluded: Sequence[tuple[str, str]] = (),
    processed: Sequence[tuple[str, str]] = (),
    minimum_distinct_industries: int = 4,
    max_selected_companies: int = 8,
) -> dict[str, Any]:
    """建立可重跑的 bounded universe plan；不進行網路或資料庫操作。

    ``verified_completed`` 是供程式內呼叫者傳入、已由外部證據驗證的完成鍵；
    CLI 應使用 ``verified_artifacts``，由本模組重新驗證 child／batch manifest
    的候選、raw 與 hash。``processed`` 僅為舊介面的 caller exclusion 別名，
    不會被算作已完成。續跑 profile 未指定 ``selected`` 時，依 registry 的
    穩定排序自動選下一批可取公司，因此尾批可以只有單一市場。
    """
    period_year, season = _parse_period(period)
    canonical_period = f"{period_year:04d}-Q{season}"
    if profile not in _PROFILES:
        raise ValueError(f"unsupported universe profile: {profile}")
    if not 1 <= minimum_distinct_industries <= 8:
        raise ValueError("minimum_distinct_industries must be between 1 and 8")
    if not 1 <= max_selected_companies <= _MAX_BATCH_COMPANIES:
        raise ValueError("max_selected_companies must be between 1 and 8")

    def _validate_key_sequence(
        values: Sequence[tuple[str, str]],
        *,
        label: str,
    ) -> tuple[tuple[str, str], ...]:
        normalized: list[tuple[str, str]] = []
        for value in values:
            if not isinstance(value, (tuple, list)) or len(value) != 2:
                raise ValueError(f"{label} keys must be STOCK:twse or STOCK:tpex tuples")
            stock_code, market = (str(part).strip() for part in value)
            if _STOCK_CODE_RE.fullmatch(stock_code) is None:
                raise ValueError(f"{label} stock must be a four-digit code")
            if market not in _SUPPORTED_REGISTRY_MARKETS:
                raise ValueError(f"{label} market must be twse or tpex")
            normalized.append((stock_code, market))
        result = tuple(normalized)
        if len(set(result)) != len(result):
            raise ValueError(f"{label} universe keys must be unique")
        return result

    selected_keys = _validate_key_sequence(selected, label="selected")
    direct_verified_keys = _validate_key_sequence(
        verified_completed, label="verified_completed"
    )
    caller_excluded_keys = _validate_key_sequence(
        (*caller_excluded, *processed), label="caller_excluded"
    )
    rows, source = _load_registry(registry_path)
    eligible: dict[tuple[str, str], dict[str, str]] = {}
    exclusion_counts: dict[str, int] = {}
    exclusion_samples: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        reason = _classify_exclusion(row)
        if reason is not None:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            sample = exclusion_samples.setdefault(reason, [])
            if len(sample) < 10:
                sample.append(
                    {
                        "stock_code": row["stock_id"],
                        "market": row["type"],
                        "stock_name": row["stock_name"],
                    }
                )
            continue
        eligible[(row["stock_id"], row["type"])] = row
    if not eligible:
        raise ValueError("eligible universe is empty")
    artifact_completed, artifact_references = _load_verified_artifacts(
        verified_artifacts,
        expected_period=canonical_period,
        supersession_records=supersession_records,
    )
    artifact_completed_keys = tuple(sorted(artifact_completed))
    if set(direct_verified_keys) & set(artifact_completed_keys):
        raise ValueError("verified completion keys must not be supplied twice")
    verified_keys = tuple(sorted((*direct_verified_keys, *artifact_completed_keys)))
    verified_set = set(verified_keys)
    caller_excluded_set = set(caller_excluded_keys)
    if verified_set & caller_excluded_set:
        overlap = sorted(verified_set & caller_excluded_set)
        raise ValueError(
            "a key cannot be both verified_completed and caller_excluded: "
            + ", ".join(f"{stock}:{market}" for stock, market in overlap)
        )
    if set(verified_keys) - set(eligible):
        unknown = sorted(set(verified_keys) - set(eligible))
        raise ValueError(
            "verified_completed key is not in eligible universe: "
            + ", ".join(f"{stock}:{market}" for stock, market in unknown)
        )
    if caller_excluded_set - set(eligible):
        unknown = sorted(caller_excluded_set - set(eligible))
        raise ValueError(
            "caller_excluded key is not in eligible universe: "
            + ", ".join(f"{stock}:{market}" for stock, market in unknown)
        )
    unknown_selected = sorted(set(selected_keys) - set(eligible))
    if unknown_selected:
        raise ValueError(
            "selected key is not in eligible universe: "
            + ", ".join(f"{stock}:{market}" for stock, market in unknown_selected)
        )
    overlap = sorted(set(selected_keys) & (verified_set | caller_excluded_set))
    if overlap:
        raise ValueError(
            "selected company is already completed or caller-excluded: "
            + ", ".join(f"{stock}:{market}" for stock, market in overlap)
        )

    selectable_keys = [
        key
        for key in sorted(eligible, key=lambda item: (item[1], item[0]))
        if key not in verified_set and key not in caller_excluded_set
    ]
    if not selected_keys:
        if profile == "representative_initial":
            raise ValueError(
                "representative_initial profile requires explicit --select entries"
            )
        selected_keys = tuple(selectable_keys[:max_selected_companies])
    if len(selected_keys) > max_selected_companies:
        raise ValueError(
            f"selected universe exceeds the {max_selected_companies}-company batch limit"
        )
    selected_rows = [eligible[key] for key in selected_keys]
    industries = {row["industry_category"] for row in selected_rows}
    if profile == "representative_initial":
        if {row["type"] for row in selected_rows} != set(_SUPPORTED_REGISTRY_MARKETS):
            raise ValueError("representative_initial universe must contain both TWSE and TPEx")
        if len(industries) < minimum_distinct_industries:
            raise ValueError(
                "representative_initial universe does not cover enough distinct industries"
            )
        finance_rows = [
            row
            for row in selected_rows
            if row["stock_id"] == "2881" and row["industry_category"] == "金融保險"
        ]
        if not finance_rows:
            raise ValueError(
                "representative_initial universe must include verified 2881 金融保險"
            )

    def _coverage_bp(numerator: int, denominator: int) -> int:
        return (numerator * 10_000) // denominator if denominator else 0

    unprocessed_count = len(eligible) - len(verified_set)
    remaining_selectable_count = len(eligible) - len(verified_set | caller_excluded_set)
    selected_records = [
        {
            "stock_code": row["stock_id"],
            "registry_market": row["type"],
            "batch_market": _REGISTRY_MARKET_TO_BATCH_MARKET[row["type"]],
            "stock_name": row["stock_name"],
            "industry_category": row["industry_category"],
            "registry_date": row["date"],
            "period": canonical_period,
            "request": (
                f"{row['stock_id']}:{_REGISTRY_MARKET_TO_BATCH_MARKET[row['type']]}:"
                f"{canonical_period}"
            ),
            "selection_reason": (
                "explicit representative_initial coverage"
                if profile == "representative_initial"
                else "stable next selectable eligible company"
            ),
        }
        for row in selected_rows
    ]
    eligible_rows = [
        {
            "stock_code": row["stock_id"],
            "registry_market": row["type"],
            "batch_market": _REGISTRY_MARKET_TO_BATCH_MARKET[row["type"]],
            "stock_name": row["stock_name"],
            "industry_category": row["industry_category"],
            "registry_date": row["date"],
            "verified_completed": (row["stock_id"], row["type"]) in verified_set,
            "caller_excluded": (row["stock_id"], row["type"]) in caller_excluded_set,
            "selectable": (row["stock_id"], row["type"])
            not in verified_set
            and (row["stock_id"], row["type"]) not in caller_excluded_set,
        }
        for row in sorted(eligible.values(), key=lambda item: (item["type"], item["stock_id"]))
    ]
    selected_registry_markets = sorted({row["registry_market"] for row in selected_records})
    selected_batch_markets = sorted({row["batch_market"] for row in selected_records})
    scope = {
        "period": canonical_period,
        "markets": selected_batch_markets,
        "registry_markets": selected_registry_markets,
        "eligible_company_count": len(eligible),
        "verified_completed_company_count": len(verified_set),
        "caller_excluded_company_count": len(caller_excluded_set),
        "processed_company_count": len(caller_excluded_set),
        "unprocessed_eligible_company_count": unprocessed_count,
        "remaining_selectable_company_count": remaining_selectable_count,
        # caller_excluded 只表示本輪明確 deferred／unresolved；仍保留在
        # unfinished 分母中，供後續來源恢復重新選取與追蹤。
        "deferred_unresolved_company_count": len(caller_excluded_set),
        "total_unfinished_company_count": unprocessed_count,
        "selected_company_count": len(selected_records),
        "coverage_selected_over_eligible_bp": _coverage_bp(len(selected_records), len(eligible)),
        "coverage_selected_over_unprocessed_bp": _coverage_bp(
            len(selected_records), unprocessed_count
        ),
        "coverage_verified_over_eligible_bp": _coverage_bp(len(verified_set), len(eligible)),
        "selected_industry_count": len(industries),
    }
    body: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "research_only": True,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "source": source,
        "selection_policy": {
            "profile": profile,
            "supported_registry_markets": sorted(_SUPPORTED_REGISTRY_MARKETS),
            "batch_market_mapping": dict(_REGISTRY_MARKET_TO_BATCH_MARKET),
            "stock_code_pattern": _STOCK_CODE_RE.pattern,
            "exclude_rules": [
                "registry type outside twse/tpex",
                "stock code is not exactly four digits or industry is 存託憑證",
                "stock code starts 00/01 or name contains ETF/ETN/index-fund marker",
            ],
            "minimum_distinct_industries": minimum_distinct_industries,
            "max_selected_companies": max_selected_companies,
            "auto_selection_order": ["registry_market", "stock_code"],
            "representative_requirements": (
                {
                    "both_registry_markets": True,
                    "stock_code": "2881",
                    "industry_category": "金融保險",
                    "minimum_distinct_industries": minimum_distinct_industries,
                }
                if profile == "representative_initial"
                else None
            ),
        },
        "scope": scope,
        "verified_completed_keys": [
            f"{stock}:{market}" for stock, market in sorted(verified_set)
        ],
        "caller_excluded_keys": [
            f"{stock}:{market}" for stock, market in sorted(caller_excluded_set)
        ],
        "processed_keys": [
            f"{stock}:{market}" for stock, market in sorted(caller_excluded_set)
        ],
        "verified_completed_artifacts": artifact_references,
        "supersession_records": [
            reference
            for reference in artifact_references
            if reference.get("artifact_kind") == "supersession_record"
        ],
        "selected_companies": selected_records,
        "requests": [record["request"] for record in selected_records],
        "eligible_rows": eligible_rows,
        "excluded": {"counts": exclusion_counts, "samples": exclusion_samples},
    }
    body["eligible_rows_sha256"] = _sha256_json(eligible_rows)
    body["content_sha256"] = _sha256_json(body)
    body["plan_id"] = (
        f"mops-statement-universe-{period_year:04d}q{season}-"
        f"{body['content_sha256'][7:23]}"
    )
    return body


def validate_universe_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    """驗證計畫自身 hash 與 bounded scope，供 batch resume 前使用。"""
    if payload.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("universe plan schema version is unsupported")
    if (
        payload.get("research_only") is not True
        or payload.get("formal_oos_allowed") is not False
    ):
        raise ValueError("universe plan must remain research-only")
    stored_hash = payload.get("content_sha256")
    if not isinstance(stored_hash, str) or not stored_hash.startswith("sha256:"):
        raise ValueError("universe plan content hash is missing")
    body = dict(payload)
    body.pop("content_sha256", None)
    body.pop("plan_id", None)
    if _sha256_json(body) != stored_hash:
        raise ValueError("universe plan content hash mismatch")
    source = payload.get("source")
    scope = payload.get("scope")
    policy = payload.get("selection_policy")
    selected = payload.get("selected_companies")
    requests = payload.get("requests")
    eligible_rows = payload.get("eligible_rows")
    profile = payload.get("selection_policy", {}).get("profile") if isinstance(payload.get("selection_policy"), Mapping) else None
    if (
        not isinstance(source, Mapping)
        or not isinstance(scope, Mapping)
        or not isinstance(policy, Mapping)
        or profile not in _PROFILES
    ):
        raise ValueError("universe plan source, scope, or profile is missing")
    if (
        not isinstance(selected, list)
        or not isinstance(requests, list)
        or not isinstance(eligible_rows, list)
    ):
        raise ValueError("universe plan rows are malformed")
    period = scope.get("period")
    if not isinstance(period, str):
        raise ValueError("universe plan scope period is missing")
    _parse_period(period)

    supersession_values = payload.get("supersession_records", [])
    if not isinstance(supersession_values, list):
        raise ValueError("universe plan supersession records are malformed")
    supersession_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for value in supersession_values:
        if not isinstance(value, Mapping):
            raise ValueError("universe plan supersession record is malformed")
        record_path = value.get("artifact_path")
        record_hash = value.get("artifact_sha256")
        if not isinstance(record_path, str) or not isinstance(record_hash, str):
            raise ValueError("universe plan supersession record identity is incomplete")
        records = _load_supersession_records(
            [Path(record_path)],
            expected_period=period,
        )
        if len(records) != 1 or records[0]["record_sha256"] != record_hash:
            raise ValueError("universe plan supersession record hash mismatch")
        record = records[0]
        key = (str(record["stock_code"]), str(record["registry_market"]))
        if key in supersession_by_key:
            raise ValueError("universe plan supersession targets are duplicated")
        replacement = record["replacement"]
        if value.get("candidate_sha256") != replacement["candidate_sha256"]:
            raise ValueError("universe plan supersession replacement hash mismatch")
        supersession_by_key[key] = record

    def _key_from_text(value: object, *, label: str) -> tuple[str, str]:
        if not isinstance(value, str):
            raise ValueError(f"universe plan {label} key is malformed")
        try:
            return _parse_key(value, option=label)
        except ValueError as error:
            raise ValueError(f"universe plan {label} key is malformed") from error

    def _count(name: str) -> int:
        value = scope.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"universe plan scope {name} is invalid")
        return value

    eligible_count = _count("eligible_company_count")
    verified_count = _count("verified_completed_company_count")
    caller_excluded_count = _count("caller_excluded_company_count")
    unprocessed_count = _count("unprocessed_eligible_company_count")
    selectable_count = _count("remaining_selectable_company_count")
    selected_count = _count("selected_company_count")
    if verified_count > eligible_count or unprocessed_count != eligible_count - verified_count:
        raise ValueError("universe plan verified completion denominator mismatch")
    deferred_count = scope.get("deferred_unresolved_company_count")
    if deferred_count is None:
        deferred_count = caller_excluded_count
    elif isinstance(deferred_count, bool) or not isinstance(deferred_count, int) or deferred_count < 0:
        raise ValueError("universe plan scope deferred unresolved count is invalid")
    unfinished_count = scope.get("total_unfinished_company_count")
    if unfinished_count is None:
        unfinished_count = unprocessed_count
    elif isinstance(unfinished_count, bool) or not isinstance(unfinished_count, int) or unfinished_count < 0:
        raise ValueError("universe plan scope total unfinished count is invalid")
    if (
        deferred_count != caller_excluded_count
        or unfinished_count != unprocessed_count
        or unfinished_count != deferred_count + selectable_count
    ):
        raise ValueError("universe plan unfinished/deferred/selectable denominator mismatch")
    verified_values = payload.get("verified_completed_keys", [])
    excluded_values = payload.get("caller_excluded_keys", [])
    if not isinstance(verified_values, list) or not isinstance(excluded_values, list):
        raise ValueError("universe plan completion/exclusion keys are malformed")
    verified_keys = {_key_from_text(value, label="verified_completed") for value in verified_values}
    excluded_keys = {_key_from_text(value, label="caller_excluded") for value in excluded_values}
    if len(verified_keys) != len(verified_values) or len(excluded_keys) != len(excluded_values):
        raise ValueError("universe plan completion/exclusion keys are duplicated")
    if verified_keys & excluded_keys:
        raise ValueError("universe plan completion/exclusion keys overlap")
    if verified_count != len(verified_keys) or caller_excluded_count != len(excluded_keys):
        raise ValueError("universe plan completion/exclusion counts mismatch")
    artifact_references = payload.get("verified_completed_artifacts", [])
    if not isinstance(artifact_references, list):
        raise ValueError("universe plan verified artifact references are malformed")
    old_hashes = {
        str(record["superseded"]["candidate_sha256"])
        for record in supersession_by_key.values()
    }
    replacement_hashes = {
        str(record["replacement"]["candidate_sha256"])
        for record in supersession_by_key.values()
    }
    if any(
        isinstance(reference, Mapping)
        and reference.get("candidate_sha256") in old_hashes
        for reference in artifact_references
    ):
        raise ValueError("universe plan still counts a superseded candidate")
    if not replacement_hashes <= {
        str(reference.get("candidate_sha256"))
        for reference in artifact_references
        if isinstance(reference, Mapping)
    }:
        raise ValueError("universe plan omits a supersession replacement")
    if selectable_count != eligible_count - len(verified_keys | excluded_keys):
        raise ValueError("universe plan selectable denominator mismatch")
    legacy_processed = payload.get("processed_keys")
    if legacy_processed is not None and legacy_processed != excluded_values:
        raise ValueError("universe plan legacy processed keys must equal caller exclusions")

    eligible_keys: set[tuple[str, str]] = set()
    eligible_flags: dict[tuple[str, str], tuple[bool, bool, bool]] = {}
    for row in eligible_rows:
        if not isinstance(row, Mapping):
            raise ValueError("universe plan eligible row is malformed")
        stock_code = row.get("stock_code")
        registry_market = row.get("registry_market")
        key = _key_from_text(
            f"{stock_code}:{registry_market}", label="eligible"
        )
        if key in eligible_keys:
            raise ValueError("universe plan eligible rows contain duplicate keys")
        batch_market = row.get("batch_market")
        if batch_market != _REGISTRY_MARKET_TO_BATCH_MARKET[key[1]]:
            raise ValueError("universe plan eligible market mapping mismatch")
        flags = tuple(row.get(name) for name in ("verified_completed", "caller_excluded", "selectable"))
        if not all(isinstance(value, bool) for value in flags):
            raise ValueError("universe plan eligible row flags are malformed")
        expected_flags = (key in verified_keys, key in excluded_keys, key not in verified_keys | excluded_keys)
        if flags != expected_flags:
            raise ValueError("universe plan eligible row flags do not match completion state")
        eligible_keys.add(key)
        eligible_flags[key] = (bool(flags[0]), bool(flags[1]), bool(flags[2]))
    if eligible_count != len(eligible_keys) or not verified_keys <= eligible_keys or not excluded_keys <= eligible_keys:
        raise ValueError("universe plan eligible denominator or state mismatch")
    if scope.get("selected_company_count") != len(selected) or len(requests) != len(selected):
        raise ValueError("universe plan selected count mismatch")
    if payload.get("eligible_rows_sha256") != _sha256_json(eligible_rows):
        raise ValueError("universe plan eligible rows hash mismatch")
    max_selected = policy.get("max_selected_companies", _MAX_BATCH_COMPANIES)
    if isinstance(max_selected, bool) or not isinstance(max_selected, int) or not 1 <= max_selected <= _MAX_BATCH_COMPANIES:
        raise ValueError("universe plan max selected company limit is invalid")
    if len(selected) > max_selected:
        raise ValueError("universe plan exceeds the eight-company batch limit")
    selected_keys: set[tuple[str, str]] = set()
    for request, record in zip(requests, selected):
        if (
            not isinstance(request, str)
            or not isinstance(record, Mapping)
            or request != record.get("request")
        ):
            raise ValueError("universe plan request identity mismatch")
        request_parts = request.split(":")
        if len(request_parts) != 3:
            raise ValueError("universe plan request format is invalid")
        request_key = _key_from_text(
            f"{request_parts[0]}:{_BATCH_MARKET_TO_REGISTRY_MARKET.get(request_parts[1], '')}",
            label="request",
        )
        if request_parts[2] != period or request_key in selected_keys or request_key not in eligible_keys:
            raise ValueError("universe plan request period or key mismatch")
        if request_key in verified_keys | excluded_keys:
            raise ValueError("universe plan requests contain completed or excluded keys")
        if record.get("stock_code") != request_key[0] or record.get("registry_market") != request_key[1]:
            raise ValueError("universe plan selected company identity mismatch")
        if record.get("batch_market") != request_parts[1] or record.get("period") != period:
            raise ValueError("universe plan selected market or period mismatch")
        selected_keys.add(request_key)
    if selected_count != len(selected_keys):
        raise ValueError("universe plan selected key count mismatch")
    actual_selected_registry_markets = sorted({key[1] for key in selected_keys})
    actual_selected_batch_markets = sorted({_REGISTRY_MARKET_TO_BATCH_MARKET[key[1]] for key in selected_keys})
    if scope.get("registry_markets") != actual_selected_registry_markets or scope.get("markets") != actual_selected_batch_markets:
        raise ValueError("universe plan selected market scope mismatch")
    if profile == "representative_initial":
        if set(actual_selected_registry_markets) != set(_SUPPORTED_REGISTRY_MARKETS):
            raise ValueError("representative_initial plan must contain both markets")
        selected_industries = {
            row.get("industry_category")
            for row in selected
            if isinstance(row.get("industry_category"), str)
        }
        minimum_industries = policy.get("minimum_distinct_industries")
        if isinstance(minimum_industries, bool) or not isinstance(minimum_industries, int) or len(selected_industries) < minimum_industries:
            raise ValueError("representative_initial plan industry coverage is invalid")
        if not any(
            row.get("stock_code") == "2881" and row.get("registry_market") == "twse" and row.get("industry_category") == "金融保險"
            for row in selected
        ):
            raise ValueError("representative_initial plan must include 2881 金融保險")
    return dict(payload)


def load_universe_plan(path: Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve(strict=True)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("universe plan is unreadable") from error
    if not isinstance(payload, Mapping):
        raise ValueError("universe plan must be a JSON object")
    return validate_universe_plan(payload)


def write_universe_plan(path: Path, payload: Mapping[str, Any]) -> Path:
    resolved = validate_research_output_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        required=True,
        help="保存的官方 TWSE/TPEx companies.csv",
    )
    parser.add_argument("--period", required=True, help="YYYY-Qn")
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="STOCK:twse|tpex",
        help="明確選取公司；continuation 未指定時依 registry 自動選下一批",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(_PROFILES),
        default="continuation",
        help="代表性首批或可持續續跑 profile",
    )
    parser.add_argument(
        "--verified-artifact",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="已驗證的 v1 child 或 v2 batch manifest；可重複指定",
    )
    parser.add_argument(
        "--supersession-record",
        action="append",
        default=[],
        type=Path,
        metavar="PATH",
        help="immutable child replacement record；可重複指定",
    )
    parser.add_argument(
        "--caller-excluded",
        action="append",
        default=[],
        metavar="STOCK:twse|tpex",
        help="本次 caller 暫不取數的鍵；不計作 verified completed",
    )
    parser.add_argument(
        "--processed",
        action="append",
        default=[],
        metavar="STOCK:twse|tpex",
        help="舊介面別名，視為 caller exclusion，不代表已完成",
    )
    parser.add_argument("--minimum-distinct-industries", type=int, default=4)
    parser.add_argument("--max-selected-companies", type=int, default=_MAX_BATCH_COMPANIES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    selected = [_parse_key(value, option="--select") for value in args.select]
    caller_excluded = [
        _parse_key(value, option="--caller-excluded") for value in args.caller_excluded
    ]
    processed = [_parse_key(value, option="--processed") for value in args.processed]
    payload = build_universe_plan(
        registry_path=args.registry,
        period=args.period,
        selected=selected,
        profile=args.profile,
        verified_artifacts=args.verified_artifact,
        supersession_records=args.supersession_record,
        caller_excluded=caller_excluded,
        processed=processed,
        minimum_distinct_industries=args.minimum_distinct_industries,
        max_selected_companies=args.max_selected_companies,
    )
    output = write_universe_plan(args.output, payload)
    print(
        json.dumps(
            {
                "status": "completed",
                "output": str(output),
                "plan_id": payload["plan_id"],
                "scope": payload["scope"],
                "source": payload["source"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
