"""執行 derived allocation release 的自然日研究 shadow。

這個入口只把現有 ``run_daily_ml_allocation_orchestration`` 接到一個
immutable derived release。來源 SQLite 與 Paper ledger 都以唯讀方式交給
既有 service；輸出固定留在 repository ``output`` 下，並以 256 MiB 的
持久／暫存上限做執行前與執行後檢查。

``research_latest_asof`` 允許在 release 今日才發布時，留下最近可得的
真實 as-of 研究推論，但會保存發布時間、capture 時間與
``available_before_decision=false``，所以不會被誤讀成 forward capture。
``forward_natural_date`` 只有在 release 檔案在決策鐘前已可得時才執行。
兩種模式都固定 alpha=0、formal OOS=false、broker=false。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, time
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping, cast
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_module.allocation_release_adapter import (  # noqa: E402
    LoadedAllocationRelease,
    AllocationReleaseAdapter,
)
from data_module.ml_storage_capacity import (  # noqa: E402
    CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
    MLStorageCapacityBudget,
    StorageCapacityError,
    acquire_heavy_chain_reservation,
    directory_size_bytes,
    release_heavy_chain_reservation,
    preflight_capacity,
    resolve_heavy_chain_lock_path,
)
from data_module.official_trading_calendar import (  # noqa: E402
    OfficialTradingCalendar,
)
from scripts import run_daily_ml_allocation_orchestration as daily  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_TIME = time(hour=8, minute=30)
SCHEMA_VERSION = "ml-allocation-natural-date-shadow.v1"
RESEARCH_MODE = "research_latest_asof"
FORWARD_MODE = "forward_natural_date"
MAX_PERSISTENT_NEW_BYTES = 256 * 1024**2
MAX_TEMPORARY_PEAK_BYTES = 256 * 1024**2
# 既有 daily task 固定 08:30；forward capture 只接受短暫的排程抖動，
# 逾時即留下 blocked state，不把盤後回溯執行算成 forward。
MAX_FORWARD_CAPTURE_DELAY = timedelta(minutes=5)
# Raw exporter checkpoints receive a small allowance for the wrapper's
# immutable record and daily orchestration metadata.
RAW_PERSISTENT_NEW_BYTES = MAX_PERSISTENT_NEW_BYTES - 8 * 1024**2
# 與既有 heavy-chain 雙碟政策一致；這不是本次輸出配額，不能因為
# shadow 輕量就把安全保留空間降回舊版 20 GiB。
DEFAULT_SAFETY_RESERVE_BYTES = CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES
DEFAULT_RAW_LOOKBACK_DAYS = daily.DEFAULT_RAW_LOOKBACK_DAYS
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "v4_ml_daily_derived_shadow"
DEFAULT_RELEASE_ROOT = REPO_ROOT / "output" / "v4_ml_derived_h5_20260907_real"
DEFAULT_DATA_ROOT = Path(
    os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")
)
DEFAULT_DATABASE = DEFAULT_DATA_ROOT / "sqlite" / "twstock.db"
DEFAULT_PAPER_STATE_DB = (
    DEFAULT_DATA_ROOT / "output" / "paper_portfolio" / "paper_portfolio.sqlite"
)


def _default_heavy_chain_lock_path(database_path: Path) -> Path:
    """由真實 DATA_ROOT 指向既有 release_v4 共用 lock。"""

    database_parent = database_path.resolve().parent
    data_root = (
        database_parent.parent
        if database_parent.name.casefold() == "sqlite"
        else database_parent
    )
    return data_root / "output" / "release_v4" / ".ml_heavy_chain.lock"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _atomic_create_json(path: Path, payload: Mapping[str, object]) -> None:
    """只建立 immutable record；同名不同內容一律拒絕覆寫。"""

    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"immutable shadow record collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # O_EXCL 語意避免兩個 producer 同時建立時互相覆蓋；既有同 hash
        # record 仍允許冪等重跑，但內容不同必須 fail closed。
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ValueError(f"immutable shadow record collision: {path}")


def _create_json_if_absent(path: Path, payload: Mapping[str, object]) -> None:
    """建立 create-only receipt；既有內容交由呼叫端驗證，不覆寫。"""

    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return


def _write_immutable_record(
    *,
    output_root: Path,
    payload: Mapping[str, object],
) -> tuple[Path, str, str]:
    body = dict(payload)
    body.pop("record_hash", None)
    record_hash = _payload_hash(body)
    record = {**body, "record_hash": record_hash}
    path = (
        output_root
        / "natural_date_shadow"
        / "records"
        / f"{record_hash[7:]}.json"
    )
    _atomic_create_json(path, record)
    return path.resolve(), record_hash, _file_hash(path)


def _immutable_record_encoded_size(payload: Mapping[str, object]) -> int:
    """計算含 record_hash 的 immutable JSON bytes，用於容量閉合估算。"""

    body = dict(payload)
    body.pop("record_hash", None)
    record = {**body, "record_hash": _payload_hash(body)}
    return len(
        (
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
    )


def _aware_now(value: datetime | None) -> datetime:
    current = value or daily._taipei_now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must contain a timezone")
    return current.astimezone(TAIPEI)


def _parse_aware_timestamp(value: object, *, field_name: str) -> datetime:
    """解析帶 offset 的時間；所有 availability 判斷都用 datetime。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must contain a timezone")
    return parsed.astimezone(TAIPEI)


def _stat_evidence(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"path": str(path.resolve()), "exists": False}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _stat_unchanged(before: Mapping[str, object], path: Path) -> bool:
    after = _stat_evidence(path)
    return (
        before.get("exists") is True
        and after.get("exists") is True
        and before.get("size_bytes") == after.get("size_bytes")
        and before.get("mtime_ns") == after.get("mtime_ns")
    )


def _release_evidence(
    *,
    release_root: Path,
    release: LoadedAllocationRelease,
    output_root: Path,
    capture_at: datetime,
) -> dict[str, object]:
    training_manifest_path = release_root / "training_manifest_v2.json"
    training_manifest = json.loads(training_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(training_manifest, dict):
        raise TypeError("training manifest must be an object")
    required_files = (
        release.manifest_path,
        release_root / "training_manifest_v2.json",
        release_root / release.manifest.artifact_file,
        release_root / release.manifest.preprocessor.artifact_file,
        release_root / release.manifest.calibration.artifact_file,
    )
    files: list[dict[str, object]] = []
    for path in dict.fromkeys(item.resolve() for item in required_files):
        evidence = _stat_evidence(path)
        if evidence.get("exists") is True:
            evidence["sha256"] = _file_hash(path)
        files.append(evidence)
    if any(item.get("exists") is not True for item in files):
        raise FileNotFoundError("derived release required file is missing")
    # mtime 只作診斷，不能當發布時間（copy2／還原會保留舊 mtime）。
    # 可供 future decision 使用的時間只能來自本 producer 的 create-only
    # first-observed receipt；本次第一次觀察若在決策鐘後，必須保持 research。
    receipt_path = (
        output_root
        / "natural_date_shadow"
        / "release_receipts"
        / f"{release.manifest.release_identity_hash[7:]}.json"
    )
    receipt_body = {
        "schema_version": "ml-allocation-release-observation-receipt.v1",
        "release_identity_hash": release.manifest.release_identity_hash,
        "release_manifest_file_hash": release.release_manifest_file_hash,
        "artifact_hash": release.artifact_hash,
        "observed_at": capture_at.isoformat(timespec="microseconds"),
        "required_file_hashes": [
            {
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for item in files
        ],
    }
    # Receipt 是 release identity／內容 hash 的 first-observed 證據。若
    # 同一 release 已有 receipt，保留首次真實 clock，不因重跑時間改寫。
    _create_json_if_absent(receipt_path, receipt_body)
    observed = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(observed, dict):
        raise TypeError("release observation receipt must be an object")
    if (
        observed.get("schema_version")
        != receipt_body["schema_version"]
        or observed.get("release_identity_hash")
        != release.manifest.release_identity_hash
        or observed.get("release_manifest_file_hash")
        != release.release_manifest_file_hash
        or observed.get("artifact_hash") != release.artifact_hash
        or observed.get("required_file_hashes")
        != receipt_body["required_file_hashes"]
    ):
        raise ValueError("release observation receipt identity mismatch")
    observed_dt = _parse_aware_timestamp(
        observed.get("observed_at"),
        field_name="release observation receipt observed_at",
    )
    if observed_dt > capture_at:
        raise ValueError("release observation receipt is from the future")
    return {
        "release_root": str(release_root.resolve()),
        "release_id": release.release_id,
        "release_manifest_file_hash": release.release_manifest_file_hash,
        "release_identity_hash": release.manifest.release_identity_hash,
        "model_id": release.model_id,
        "dataset_id": release.dataset_id,
        "artifact_hash": release.artifact_hash,
        "training_as_of": training_manifest.get("training_as_of"),
        "observed_at": observed_dt.isoformat(
            timespec="microseconds"
        ),
        "first_observed_at": observed_dt.isoformat(timespec="microseconds"),
        "observation_receipt_path": str(receipt_path.resolve()),
        "observation_receipt_file_hash": _file_hash(receipt_path),
        "published_at": None,
        "published_time_basis": (
            "not_inferred_from_mtime; use_first_observed_receipt_only"
        ),
        "required_file_mtime_diagnostics": [
            {
                "path": item["path"],
                "mtime_ns": item.get("mtime_ns"),
            }
            for item in files
        ],
        "required_files": files,
    }


def _source_date_evidence(
    *,
    database_path: Path,
    symbols: tuple[str, ...],
    strict_t_minus_one: str | None,
) -> dict[str, object]:
    """讀取真實 DB 日期／symbol 證據；連線固定唯讀。"""

    if not database_path.is_file():
        return {
            "status": "missing",
            "database_path": str(database_path.resolve()),
            "source_database_mode": "ro",
            "query_only": True,
        }
    tables = (
        "daily_prices",
        "technical_indicators",
        "market_indices",
        "industry_indices",
    )
    result: dict[str, object] = {
        "status": "completed",
        "database_path": str(database_path.resolve()),
        "source_database_mode": "ro",
        "query_only": True,
        "latest_date_by_table": {},
        "symbol_latest_date": {},
        "strict_t_minus_one_rows_by_symbol": {},
    }
    try:
        uri = database_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA query_only").fetchone() != (1,):
                raise RuntimeError("source SQLite query_only could not be enabled")
            latest = result["latest_date_by_table"]
            symbol_latest = result["symbol_latest_date"]
            strict_rows = result["strict_t_minus_one_rows_by_symbol"]
            assert isinstance(latest, dict)
            assert isinstance(symbol_latest, dict)
            assert isinstance(strict_rows, dict)
            for table in tables:
                row = connection.execute(
                    f'SELECT MAX("日期") FROM "{table}"'
                ).fetchone()
                latest[table] = row[0] if row else None
            placeholders = ",".join("?" for _ in symbols)
            rows = connection.execute(
                f'''SELECT "證券代號", MAX("日期") FROM "daily_prices"
                    WHERE "證券代號" IN ({placeholders}) GROUP BY "證券代號"''',
                symbols,
            ).fetchall()
            symbol_latest.update({str(symbol): value for symbol, value in rows})
            if strict_t_minus_one is not None:
                rows = connection.execute(
                    f'''SELECT "證券代號", COUNT(*) FROM "daily_prices"
                        WHERE "日期" = ? AND "證券代號" IN ({placeholders})
                        GROUP BY "證券代號"''',
                    (strict_t_minus_one.replace("-", ""), *symbols),
                ).fetchall()
                strict_rows.update({str(symbol): int(count) for symbol, count in rows})
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        result["status"] = "failed"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    return result


def _select_natural_decision(
    *,
    calendar: object,
    now: datetime,
    requested_decision_at: str | None,
) -> dict[str, object]:
    local_now = _aware_now(now)
    if requested_decision_at is None:
        if local_now.timetz().replace(tzinfo=None) < DECISION_TIME:
            return {
                "status": "waiting_for_decision_clock",
                "reason": "taipei_08:30_not_reached",
                "now": local_now.isoformat(timespec="seconds"),
            }
        decision_at = datetime.combine(
            local_now.date(),
            DECISION_TIME,
            tzinfo=TAIPEI,
        )
        selection_mode = "natural_current_date"
    else:
        try:
            decision_at = daily._parse_decision_at(requested_decision_at)
        except (TypeError, ValueError) as exc:
            return {
                "status": "blocked_invalid_decision_at",
                "reason": str(exc),
                "error_type": type(exc).__name__,
                "now": local_now.isoformat(timespec="seconds"),
            }
        local_decision_at = decision_at.astimezone(TAIPEI)
        if local_decision_at.timetz().replace(tzinfo=None) != DECISION_TIME:
            return {
                "status": "blocked_invalid_decision_clock",
                "reason": "decision_at_must_equal_taipei_08:30",
                "decision_at": local_decision_at.isoformat(
                    timespec="seconds"
                ),
                "now": local_now.isoformat(timespec="seconds"),
            }
        decision_at = local_decision_at
        if decision_at.date() != local_now.date():
            return {
                "status": "blocked_stale_or_future_decision",
                "reason": "explicit_decision_date_must_equal_current_taipei_date",
                "decision_at": decision_at.isoformat(timespec="seconds"),
                "now": local_now.isoformat(timespec="seconds"),
            }
        if decision_at > local_now:
            return {
                "status": "waiting_for_decision_clock",
                "reason": "explicit_decision_at_is_in_the_future",
                "decision_at": decision_at.isoformat(timespec="seconds"),
                "now": local_now.isoformat(timespec="seconds"),
            }
        selection_mode = "requested_current_date"

    is_open, reason = daily._calendar_day_state(
        cast(Any, calendar),
        decision_at.date(),
    )
    if is_open is None:
        return {
            "status": "blocked_calendar_unknown",
            "reason": f"{decision_at.date().isoformat()}:{reason}",
            "decision_at": decision_at.isoformat(timespec="seconds"),
            "calendar_reason": reason,
        }
    if is_open is False:
        return {
            "status": "skipped_non_trading_day",
            "reason": reason,
            "decision_at": decision_at.isoformat(timespec="seconds"),
            "calendar_reason": reason,
        }
    return {
        "status": "selected",
        "decision_at": decision_at.isoformat(timespec="seconds"),
        "calendar_reason": reason,
        "selection_mode": selection_mode,
        "now": local_now.isoformat(timespec="seconds"),
    }


def _forward_clock_evidence(
    *,
    mode: str,
    capture_at: datetime,
    selection: Mapping[str, object],
) -> dict[str, object]:
    """記錄 capture 是否落在正式 08:30 forward 窗口。"""

    decision_value = selection.get("decision_at")
    if not isinstance(decision_value, str):
        return {
            "status": "not_selected",
            "mode": mode,
            "capture_at": capture_at.isoformat(timespec="microseconds"),
            "within_forward_window": False,
        }
    decision_at = _parse_aware_timestamp(
        decision_value,
        field_name="selection.decision_at",
    )
    window_end = decision_at + MAX_FORWARD_CAPTURE_DELAY
    within_window = decision_at <= capture_at <= window_end
    return {
        "status": "within_window" if within_window else "outside_window",
        "mode": mode,
        "decision_at": decision_at.isoformat(timespec="microseconds"),
        "capture_at": capture_at.isoformat(timespec="microseconds"),
        "window_end": window_end.isoformat(timespec="microseconds"),
        "within_forward_window": within_window,
        "research_late_capture": (
            mode == RESEARCH_MODE and capture_at > window_end
        ),
    }


def _release_files_unchanged(
    required_files: object,
) -> bool:
    """比對 release 每個 frozen 檔案的 stat 與 hash。"""

    if not isinstance(required_files, list):
        return False
    for expected in required_files:
        if not isinstance(expected, dict):
            return False
        path_value = expected.get("path")
        expected_hash = expected.get("sha256")
        if not isinstance(path_value, str) or not isinstance(
            expected_hash, str
        ):
            return False
        path = Path(path_value)
        actual = _stat_evidence(path)
        if (
            actual.get("exists") is not True
            or actual.get("size_bytes") != expected.get("size_bytes")
            or actual.get("mtime_ns") != expected.get("mtime_ns")
        ):
            return False
        if _file_hash(path) != expected_hash:
            return False
    return True


def _load_observation_lanes(status: Mapping[str, object]) -> dict[str, object]:
    observation_value = status.get("shadow_observation_path")
    if not isinstance(observation_value, str) or not observation_value:
        return {
            "status": "missing",
            "reason": "shadow_observation_path_missing",
        }
    path = Path(observation_value)
    if not path.is_file():
        return {"status": "missing", "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "status": "failed",
            "path": str(path),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    if not isinstance(raw, dict) or not isinstance(raw.get("lanes"), list):
        return {"status": "failed", "path": str(path), "reason": "lanes_missing"}
    lanes: list[dict[str, object]] = []
    for item in raw["lanes"]:
        if not isinstance(item, dict):
            continue
        lanes.append(
            {
                "alpha_bp": item.get("alpha_bp"),
                "lane_hash": item.get("lane_hash"),
                "estimated_cost": item.get("estimated_cost"),
                "turnover_bp": item.get("turnover_bp"),
                "constraint_violation_count": item.get("constraint_violation_count"),
                "research_only": item.get("research_only"),
            }
        )
    rule = next((lane for lane in lanes if lane.get("alpha_bp") == 0), None)
    return {
        "status": "completed" if rule is not None else "failed",
        "path": str(path.resolve()),
        "record_hash": raw.get("record_hash"),
        "rule_lane": rule,
        "shadow_lanes": [lane for lane in lanes if lane is not rule],
        "all_lanes_count": len(lanes),
    }


def _cost_performance_state(status: Mapping[str, object]) -> dict[str, object]:
    lanes = _load_observation_lanes(status)
    return {
        "status": "waiting_for_mature_labels",
        "forward_effectiveness_claim": False,
        "rule_comparison": lanes,
        "equal_weight_comparison": {
            "status": "deferred",
            "reason": (
                "正式 Rule/EW PIT snapshot 與同成本模型尚未接入；"
                "不以目前 Paper ledger 合成 expected baseline。"
            ),
        },
        "cost_unit": "existing_projector_decimal_money_and_integer_bp_turnover",
        "label_maturity": "not_available_for_current_capture",
    }


def _raw_exporter_temporary_capacity(
    status: Mapping[str, object],
) -> tuple[int | None, dict[str, object]]:
    """取出 raw exporter 真正量測的 staging peak；缺資料保持 unknown。"""

    stages_value = status.get("stage_results")
    if not isinstance(stages_value, dict):
        return None, {
            "status": "unknown",
            "reason": "daily_stage_results_missing",
            "scope": "raw_pit_exporter_staging_only",
        }
    raw_value = stages_value.get("raw_pit_publication")
    if not isinstance(raw_value, dict):
        return None, {
            "status": "unknown",
            "reason": "raw_exporter_capacity_evidence_missing",
            "scope": "raw_pit_exporter_staging_only",
        }
    peak = raw_value.get("temporary_peak_bytes_observed")
    if isinstance(peak, bool) or not isinstance(peak, int) or peak < 0:
        return None, {
            "status": "unknown",
            "reason": "raw_exporter_temporary_peak_unknown",
            "scope": "raw_pit_exporter_staging_only",
            "capacity_checkpoint_count": raw_value.get(
                "capacity_checkpoint_count"
            ),
            "capacity_last_stage": raw_value.get("capacity_last_stage"),
        }
    return peak, {
        "status": "observed",
        "scope": "raw_pit_exporter_staging_only",
        "temporary_peak_bytes_observed": peak,
        "temporary_peak_bytes_budget": MAX_TEMPORARY_PEAK_BYTES,
        "within_temporary_budget": peak <= MAX_TEMPORARY_PEAK_BYTES,
        "capacity_checkpoint_count": raw_value.get(
            "capacity_checkpoint_count"
        ),
        "capacity_last_stage": raw_value.get("capacity_last_stage"),
        "complete_for_full_run": False,
    }


def _post_run_capacity_check(
    *,
    probe_path: Path,
    budget: MLStorageCapacityBudget,
    stage: str,
    persistent_new_bytes_estimate: int,
    temporary_peak_bytes_observed: int | None,
) -> dict[str, object]:
    """重查執行後磁碟 headroom；unknown telemetry 不被假稱通過。"""

    try:
        return preflight_capacity(
            probe_path=probe_path,
            budget=budget,
            stage=stage,
            persistent_new_bytes_estimate=persistent_new_bytes_estimate,
            temporary_peak_bytes_observed=temporary_peak_bytes_observed,
        ).as_dict()
    except StorageCapacityError as exc:
        return {
            **dict(exc.preflight),
            "status": "blocked_or_unknown",
        }


def _base_record(
    *,
    output_root: Path,
    mode: str,
    capture_at: datetime,
    selection: Mapping[str, object],
    release_evidence: Mapping[str, object] | None,
    database_evidence: Mapping[str, object],
    paper_state_evidence: Mapping[str, object],
    missing_inputs: list[str],
    capacity: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "research_only": True,
        "capture_at": capture_at.isoformat(timespec="microseconds"),
        "selection": dict(selection),
        "release": dict(release_evidence) if release_evidence is not None else None,
        "source": {
            "database": dict(database_evidence),
            "paper_state_db": dict(paper_state_evidence),
            "database_read_only_required": True,
            "release_read_only_required": True,
        },
        "missing_inputs": list(missing_inputs),
        "capacity": dict(capacity),
        "production_boundaries": {
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
            "broker_execution": False,
        },
        "cost_performance": {
            "status": "waiting_for_mature_labels",
            "forward_effectiveness_claim": False,
        },
        "writes_source_database": False,
        "changes_portfolio_state": False,
        "output_root": str(output_root.resolve()),
    }


def _run_unlocked(
    *,
    database_path: Path,
    output_root: Path,
    release_root: Path,
    paper_state_db_path: Path,
    mode: str = RESEARCH_MODE,
    decision_at: str | None = None,
    now: datetime | None = None,
    raw_lookback_days: int = DEFAULT_RAW_LOOKBACK_DAYS,
    batch_size: int = 2_048,
    compression_level: int = 6,
    calendar: object | None = None,
    heavy_lock_path: Path | None = None,
    pit_machine_operational_path: Path | None = None,
    pit_machine_operational_publication_file_hash: str | None = None,
    pit_machine_archive_root: Path | None = None,
    pit_machine_archive_manifest: Path | None = None,
    pit_machine_archive_manifest_file_hash: str | None = None,
    natural_forward_deadline_at: datetime | None = None,
) -> dict[str, object]:
    if mode not in {RESEARCH_MODE, FORWARD_MODE}:
        raise ValueError(f"unsupported mode: {mode}")
    capture_at = _aware_now(now)
    output_root = output_root.resolve()
    database_path = database_path.resolve()
    release_root = release_root.resolve()
    paper_state_db_path = paper_state_db_path.resolve()
    if pit_machine_operational_path is not None:
        pit_machine_operational_path = (
            pit_machine_operational_path.expanduser().resolve()
        )
    if pit_machine_archive_root is not None:
        pit_machine_archive_root = pit_machine_archive_root.expanduser().resolve()
    if pit_machine_archive_manifest is not None:
        pit_machine_archive_manifest = (
            pit_machine_archive_manifest.expanduser().resolve()
        )
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=MAX_PERSISTENT_NEW_BYTES,
        temporary_peak_bytes_budget=MAX_TEMPORARY_PEAK_BYTES,
        safety_reserve_bytes=DEFAULT_SAFETY_RESERVE_BYTES,
    )
    reservation_evidence = {
        "state": "held_for_entire_run",
        "lock_path": (
            str(heavy_lock_path.resolve())
            if heavy_lock_path is not None
            else None
        ),
        "scope": "source_raw_release_daily_shadow",
    }
    baseline_bytes = directory_size_bytes(output_root)
    preflight: dict[str, object] = {}
    try:
        output_preflight = preflight_capacity(
            probe_path=output_root,
            budget=budget,
            stage="natural_shadow_before_run",
            persistent_new_bytes_estimate=0,
            temporary_peak_bytes_observed=0,
        )
        source_preflight = preflight_capacity(
            probe_path=database_path.parent,
            budget=budget,
            stage="natural_shadow_source_drive_before_run",
            persistent_new_bytes_estimate=0,
            temporary_peak_bytes_observed=0,
        )
        preflight = {
            "output": output_preflight.as_dict(),
            "source_drive": source_preflight.as_dict(),
            "budget": budget.as_dict(),
        }
    except StorageCapacityError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked_capacity_preflight",
            "mode": mode,
            "research_only": True,
            "capture_at": capture_at.isoformat(timespec="microseconds"),
            "capacity": dict(exc.preflight),
            "heavy_chain_reservation": reservation_evidence,
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
            "writes_source_database": False,
            "record_path": None,
        }

    source_before = _stat_evidence(database_path)
    paper_before = _stat_evidence(paper_state_db_path)
    missing_inputs = [
        label
        for label, evidence in (
            ("database", source_before),
            ("paper_state_db", paper_before),
        )
        if evidence.get("exists") is not True
    ]

    release: LoadedAllocationRelease | None = None
    release_evidence: dict[str, object] | None = None
    try:
        release = AllocationReleaseAdapter().load(release_root)
        release_evidence = _release_evidence(
            release_root=release_root,
            release=release,
            output_root=output_root,
            capture_at=capture_at,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        missing_inputs.append(f"release:{type(exc).__name__}:{exc}")

    calendar_service = calendar or OfficialTradingCalendar(database_path)
    selection = _select_natural_decision(
        calendar=calendar_service,
        now=capture_at,
        requested_decision_at=decision_at,
    )
    decision_clock = _forward_clock_evidence(
        mode=mode,
        capture_at=capture_at,
        selection=selection,
    )
    selected_decision_at = selection.get("decision_at")
    if isinstance(release_evidence, dict) and isinstance(
        selected_decision_at, str
    ):
        observed_at = _parse_aware_timestamp(
            release_evidence.get("first_observed_at"),
            field_name="release.first_observed_at",
        )
        selected_decision = _parse_aware_timestamp(
            selected_decision_at,
            field_name="selection.decision_at",
        )
        available_before_decision = observed_at <= selected_decision
        release_evidence["available_before_decision"] = available_before_decision
        release_evidence["availability_blocker"] = (
            None
            if available_before_decision
            else "release_first_observed_after_decision"
        )
    else:
        release_evidence = (
            dict(release_evidence) if release_evidence is not None else None
        )

    capacity_payload = {
        "preflight": preflight,
        "persistent_new_bytes_budget": MAX_PERSISTENT_NEW_BYTES,
        "temporary_peak_bytes_budget": MAX_TEMPORARY_PEAK_BYTES,
        "persistent_existing_bytes_before_run": baseline_bytes,
        "persistent_new_bytes_before_run": 0,
        "temporary_peak_enforced_by_raw_exporter": True,
        "heavy_chain_reservation": reservation_evidence,
    }
    record = _base_record(
        output_root=output_root,
        mode=mode,
        capture_at=capture_at,
        selection=selection,
        release_evidence=release_evidence,
        database_evidence=source_before,
        paper_state_evidence=paper_before,
        missing_inputs=missing_inputs,
        capacity=capacity_payload,
    )
    record["decision_clock"] = decision_clock

    if (
        selection.get("status") == "selected"
        and mode == FORWARD_MODE
        and decision_clock.get("within_forward_window") is not True
    ):
        record["status"] = "blocked_forward_decision_window"
        record["blocked_reason"] = (
            "capture_must_fall_within_taipei_08:30_forward_window"
        )
        record["cost_performance"] = _cost_performance_state({})
        path, record_hash, file_hash = _write_immutable_record(
            output_root=output_root,
            payload=record,
        )
        return {
            **record,
            "record_path": str(path),
            "record_hash": record_hash,
            "record_file_hash": file_hash,
        }

    if selection.get("status") != "selected":
        record["status"] = selection.get("status", "blocked")
        record["cost_performance"] = _cost_performance_state({})
        path, record_hash, file_hash = _write_immutable_record(
            output_root=output_root,
            payload=record,
        )
        return {
            **record,
            "record_path": str(path),
            "record_hash": record_hash,
            "record_file_hash": file_hash,
        }
    if release is None:
        record["status"] = "blocked_missing_release"
        record["cost_performance"] = _cost_performance_state({})
        path, record_hash, file_hash = _write_immutable_record(
            output_root=output_root,
            payload=record,
        )
        return {
            **record,
            "record_path": str(path),
            "record_hash": record_hash,
            "record_file_hash": file_hash,
        }
    if mode == FORWARD_MODE and release_evidence is not None:
        if release_evidence.get("available_before_decision") is not True:
            record["status"] = "blocked_release_not_available_at_decision"
            record["cost_performance"] = _cost_performance_state({})
            path, record_hash, file_hash = _write_immutable_record(
                output_root=output_root,
                payload=record,
            )
            return {
                **record,
                "record_path": str(path),
                "record_hash": record_hash,
                "record_file_hash": file_hash,
            }

    if missing_inputs:
        record["status"] = "blocked_missing_input"
        record["cost_performance"] = _cost_performance_state({})
        path, record_hash, file_hash = _write_immutable_record(
            output_root=output_root,
            payload=record,
        )
        return {
            **record,
            "record_path": str(path),
            "record_hash": record_hash,
            "record_file_hash": file_hash,
        }

    assert isinstance(selected_decision_at, str)
    if natural_forward_deadline_at is not None and (
        natural_forward_deadline_at.tzinfo is None
        or natural_forward_deadline_at.utcoffset() is None
    ):
        raise ValueError("natural_forward_deadline_at must contain a timezone")
    policy_hash = release.manifest.missing_policy.policy_hash
    policy_id = release.manifest.missing_policy.policy_id
    # exporter 的唯讀 filesystem preflight 需要 probe path 已存在；只預建
    # repository output 目錄，不碰 D: source 或既有 release。
    daily_output_root = (
        output_root / "scheduled" / "ml_allocation_copilot" / "raw_pit_publications"
    )
    daily_output_root.mkdir(parents=True, exist_ok=True)
    release_manifest_before = _stat_evidence(release.manifest_path)
    expected_natural_forward_deadline_at = (
        _parse_aware_timestamp(
            selected_decision_at,
            field_name="selection.decision_at",
        )
        + MAX_FORWARD_CAPTURE_DELAY
        if mode == FORWARD_MODE
        else None
    )
    if natural_forward_deadline_at is not None:
        if mode != FORWARD_MODE:
            raise ValueError(
                "natural_forward_deadline_at is only valid in forward mode"
            )
        if expected_natural_forward_deadline_at is None:
            raise ValueError("forward deadline could not be derived")
        if natural_forward_deadline_at.astimezone(TAIPEI) != (
            expected_natural_forward_deadline_at.astimezone(TAIPEI)
        ):
            raise ValueError(
                "natural_forward_deadline_at must equal decision_at plus 5 minutes"
            )
    elif mode == FORWARD_MODE:
        natural_forward_deadline_at = expected_natural_forward_deadline_at
    daily_status = daily.run(
        database_path=database_path,
        output_root=output_root,
        release_root=release_root,
        paper_state_db_path=paper_state_db_path,
        decision_at=daily._parse_decision_at(selected_decision_at),
        decision_selection_mode=str(selection.get("selection_mode", mode)),
        requested_decision_at=daily._parse_decision_at(selected_decision_at),
        decision_selection_reason=(
            "research_latest_asof_release_published_after_decision"
            if mode == RESEARCH_MODE
            and release_evidence is not None
            and release_evidence.get("available_before_decision") is not True
            else "natural_date_release_available_before_decision"
        ),
        symbols=daily.DEFAULT_SYMBOLS,
        policy_hash=policy_hash,
        raw_lookback_days=raw_lookback_days,
        batch_size=batch_size,
        compression_level=compression_level,
        capacity_budget=MLStorageCapacityBudget(
            persistent_new_bytes_budget=RAW_PERSISTENT_NEW_BYTES,
            temporary_peak_bytes_budget=MAX_TEMPORARY_PEAK_BYTES,
            safety_reserve_bytes=DEFAULT_SAFETY_RESERVE_BYTES,
        ),
        model_id=release.model_id,
        universe_id=daily.DEFAULT_UNIVERSE_ID,
        policy_id=policy_id,
        pit_machine_operational_path=pit_machine_operational_path,
        pit_machine_operational_publication_file_hash=(
            pit_machine_operational_publication_file_hash
        ),
        pit_machine_archive_root=pit_machine_archive_root,
        pit_machine_archive_manifest=pit_machine_archive_manifest,
        pit_machine_archive_manifest_file_hash=(
            pit_machine_archive_manifest_file_hash
        ),
        natural_forward_deadline_at=natural_forward_deadline_at,
        # Release reference / authority are intentionally absent in this
        # research shadow.  Promotion therefore remains machine fail-closed.
        promotion_reference_pointer_path=None,
        promotion_authority_pointer_path=None,
        trusted_issuer_keys={},
        trusted_custody_roots=(),
        trusted_custody_id=None,
    )
    source_after = _stat_evidence(database_path)
    paper_after = _stat_evidence(paper_state_db_path)
    release_manifest_after = _stat_evidence(release.manifest_path)
    source_unchanged = _stat_unchanged(source_before, database_path)
    paper_unchanged = _stat_unchanged(paper_before, paper_state_db_path)
    release_unchanged = (
        _stat_unchanged(release_manifest_before, release.manifest_path)
        and _release_files_unchanged(
            release_evidence.get("required_files")
            if release_evidence is not None
            else None
        )
    )
    actual_new_bytes = max(0, directory_size_bytes(output_root) - baseline_bytes)
    # 先保存不含本筆 immutable record 的 delta；最後的固定點會把
    # record 自身納入，讓寫入後目錄 delta 與報告值完全相等。
    capacity_payload["persistent_new_bytes_observed_before_record"] = (
        actual_new_bytes
    )
    capacity_payload["persistent_new_bytes_observed"] = actual_new_bytes
    capacity_payload["within_persistent_budget"] = (
        actual_new_bytes <= MAX_PERSISTENT_NEW_BYTES
    )
    temporary_peak_bytes, temporary_evidence = _raw_exporter_temporary_capacity(
        daily_status
    )
    capacity_payload["temporary_peak_bytes_observed"] = temporary_peak_bytes
    capacity_payload["temporary_peak_evidence"] = temporary_evidence
    capacity_payload["within_temporary_budget"] = (
        None
        if temporary_peak_bytes is None
        else temporary_peak_bytes <= MAX_TEMPORARY_PEAK_BYTES
    )
    capacity_payload["temporary_budget_full_run_status"] = "unknown"
    if actual_new_bytes > MAX_PERSISTENT_NEW_BYTES:
        daily_status = {
            **daily_status,
            "status": "passed_rule_only",
            "operation_mode": "rule_only",
            "failed_stage": "natural_shadow_capacity_post_run",
            "failed_reasons": [
                "persistent_new_bytes_budget_exceeded",
            ],
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
        }
    # _base_record 建立的是淺層 snapshot；post-run bytes 必須再寫回
    # immutable record，否則 QA 只會看到 preflight 而遺失實際成本。
    record["capacity"] = dict(capacity_payload)
    observation_summary = _cost_performance_state(daily_status)
    status_text = str(daily_status.get("status", "failed"))
    orchestration_completed = (
        daily_status.get("orchestration_status") == "completed"
        and daily_status.get("shadow_observation_recorded") is True
    )
    natural_pruning_exit_code = daily_status.get(
        "natural_shadow_pruning_evidence_exit_code",
        0,
    )
    natural_pruning_integrity_blocked = natural_pruning_exit_code != 0
    if actual_new_bytes > MAX_PERSISTENT_NEW_BYTES:
        wrapper_status = "blocked_capacity_post_run"
    elif natural_pruning_integrity_blocked:
        # Preserve the inner Rule-only status and its non-zero scheduler
        # signal.  A derived shadow wrapper must not turn an integrity-failed
        # natural maturity readback into a completed candidate.
        wrapper_status = "blocked_natural_shadow_pruning_evidence"
    elif orchestration_completed:
        wrapper_status = "completed"
    elif status_text.startswith("passed_"):
        wrapper_status = "blocked_daily_orchestration"
    else:
        wrapper_status = status_text
    record.update(
        {
            "status": wrapper_status,
            "daily_orchestration": daily_status,
            "cost_performance": observation_summary,
            "source": {
                "database": {
                    **source_before,
                    "after": source_after,
                    "unchanged": source_unchanged,
                },
                "paper_state_db": {
                    **paper_before,
                    "after": paper_after,
                    "unchanged": paper_unchanged,
                },
                "release_manifest": {
                    "before": release_manifest_before,
                    **release_manifest_after,
                    "unchanged": release_unchanged,
                    "required_files_unchanged": release_unchanged,
                },
                "database_read_only_required": True,
                "release_read_only_required": True,
            },
        }
    )
    completion_clock = daily_status.get("natural_forward_completion_clock")
    if isinstance(completion_clock, Mapping):
        record["natural_forward_completion_clock"] = dict(completion_clock)
    record["source_date_evidence"] = _source_date_evidence(
        database_path=database_path,
        symbols=daily.DEFAULT_SYMBOLS,
        strict_t_minus_one=(
            str(daily_status.get("strict_t_minus_one"))
            if daily_status.get("strict_t_minus_one") is not None
            else None
        ),
    )
    if not (source_unchanged and paper_unchanged and release_unchanged):
        record["status"] = "failed_read_only_integrity"
        boundaries_value = record.get("production_boundaries")
        boundaries = (
            dict(boundaries_value)
            if isinstance(boundaries_value, dict)
            else {}
        )
        record["production_boundaries"] = {
            **boundaries,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
            "broker_execution": False,
        }
    # post-run output/source recheck 會把 ``observed_total`` 寫入檢查請求，
    # 而檢查結果又會影響 record 大小；因此所有最終欄位與 status 都在同一
    # 個固定點迴圈內收斂，避免先算 record bytes、後補 capacity 欄位而少算。
    observed_total = actual_new_bytes
    capacity_adjusted_daily_status = False
    for _ in range(8):
        capacity_payload["persistent_new_bytes_observed"] = observed_total
        capacity_payload["within_persistent_budget"] = (
            observed_total <= MAX_PERSISTENT_NEW_BYTES
        )
        capacity_payload["post_run_output_drive"] = _post_run_capacity_check(
            probe_path=output_root,
            budget=budget,
            stage="natural_shadow_output_drive_after_run",
            persistent_new_bytes_estimate=observed_total,
            temporary_peak_bytes_observed=temporary_peak_bytes,
        )
        capacity_payload["post_run_source_drive"] = _post_run_capacity_check(
            probe_path=database_path.parent,
            budget=budget,
            stage="natural_shadow_source_drive_after_run",
            persistent_new_bytes_estimate=0,
            temporary_peak_bytes_observed=temporary_peak_bytes,
        )
        post_run_blockers: list[str] = []
        for key in ("post_run_output_drive", "post_run_source_drive"):
            value = capacity_payload.get(key)
            if isinstance(value, dict):
                blockers = value.get("blockers")
                if isinstance(blockers, list):
                    post_run_blockers.extend(
                        str(item)
                        for item in blockers
                        if str(item) != "temporary_peak_bytes_estimate_unknown"
                    )
        capacity_blocked = bool(post_run_blockers) or (
            observed_total > MAX_PERSISTENT_NEW_BYTES
        )
        if capacity_blocked:
            candidate_status = "blocked_capacity_post_run"
            if (
                observed_total > MAX_PERSISTENT_NEW_BYTES
                and not capacity_adjusted_daily_status
            ):
                daily_status = {
                    **daily_status,
                    "status": "passed_rule_only",
                    "operation_mode": "rule_only",
                    "failed_stage": "natural_shadow_capacity_post_run",
                    "failed_reasons": [
                        "persistent_new_bytes_budget_exceeded",
                    ],
                    "production_blend_alpha_bp": 0,
                    "formal_oos_allowed": False,
                    "broker_order_allowed": False,
                }
                observation_summary = _cost_performance_state(daily_status)
                record["daily_orchestration"] = daily_status
                record["cost_performance"] = observation_summary
                capacity_adjusted_daily_status = True
        else:
            candidate_status = wrapper_status
        if not (source_unchanged and paper_unchanged and release_unchanged):
            candidate_status = "failed_read_only_integrity"
        record["status"] = candidate_status
        record["capacity"] = dict(capacity_payload)
        next_total = actual_new_bytes + _immutable_record_encoded_size(record)
        if next_total == observed_total:
            break
        observed_total = next_total
    # Keep the reported value synchronized with the exact payload that will be
    # written.  This final assignment is followed by no further record fields.
    capacity_payload["persistent_new_bytes_observed"] = observed_total
    capacity_payload["within_persistent_budget"] = (
        observed_total <= MAX_PERSISTENT_NEW_BYTES
    )
    record["capacity"] = dict(capacity_payload)
    path, record_hash, file_hash = _write_immutable_record(
        output_root=output_root,
        payload=record,
    )
    return {
        **record,
        "record_path": str(path),
        "record_hash": record_hash,
        "record_file_hash": file_hash,
    }


def run(
    *,
    database_path: Path,
    output_root: Path,
    release_root: Path,
    paper_state_db_path: Path,
    mode: str = RESEARCH_MODE,
    decision_at: str | None = None,
    now: datetime | None = None,
    raw_lookback_days: int = DEFAULT_RAW_LOOKBACK_DAYS,
    batch_size: int = 2_048,
    compression_level: int = 6,
    calendar: object | None = None,
    lock_path: Path | None = None,
    pit_machine_operational_path: Path | None = None,
    pit_machine_operational_publication_file_hash: str | None = None,
    pit_machine_archive_root: Path | None = None,
    pit_machine_archive_manifest: Path | None = None,
    pit_machine_archive_manifest_file_hash: str | None = None,
    natural_forward_deadline_at: datetime | None = None,
) -> dict[str, object]:
    """持有真實 parent release_v4 lock 後執行整段 shadow chain。"""

    resolved_database = database_path.resolve()
    canonical_lock = _default_heavy_chain_lock_path(resolved_database)
    resolved_lock: Path
    if lock_path is not None and resolved_database.parent.name.casefold() != "sqlite":
        # A caller supplied lock remains useful for isolated fixtures whose
        # database is not under the production ``sqlite`` directory.
        resolved_lock = lock_path.resolve()
    else:
        # The daily shadow output is intentionally separate from release_v4,
        # so resolve the explicit path against the canonical release root
        # rather than inferring a lock from the shadow output directory.  This
        # keeps a production caller from creating a second lock.
        candidate_lock = resolve_heavy_chain_lock_path(
            canonical_lock.parent,
            explicit_path=lock_path,
        )
        resolved_lock = (
            canonical_lock if candidate_lock is None else candidate_lock
        )
    try:
        reservation = acquire_heavy_chain_reservation(resolved_lock)
    except StorageCapacityError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked_shared_heavy_chain_lock",
            "research_only": True,
            "heavy_chain_reservation": {
                "state": "error",
                "lock_path": str(resolved_lock),
                "scope": "source_raw_release_daily_shadow",
            },
            "error_type": type(exc).__name__,
            "error": str(exc),
            "capacity": dict(exc.preflight),
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
            "writes_source_database": False,
            "record_path": None,
        }
    if reservation is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked_shared_heavy_chain_lock",
            "research_only": True,
            "heavy_chain_reservation": {
                "state": "unavailable",
                "lock_path": str(resolved_lock),
                "scope": "source_raw_release_daily_shadow",
            },
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
            "writes_source_database": False,
            "record_path": None,
        }
    try:
        return _run_unlocked(
            database_path=resolved_database,
            output_root=output_root,
            release_root=release_root,
            paper_state_db_path=paper_state_db_path,
            mode=mode,
            decision_at=decision_at,
            now=now,
            raw_lookback_days=raw_lookback_days,
            batch_size=batch_size,
            compression_level=compression_level,
            calendar=calendar,
            heavy_lock_path=resolved_lock,
            pit_machine_operational_path=pit_machine_operational_path,
            pit_machine_operational_publication_file_hash=(
                pit_machine_operational_publication_file_hash
            ),
            pit_machine_archive_root=pit_machine_archive_root,
            pit_machine_archive_manifest=pit_machine_archive_manifest,
            pit_machine_archive_manifest_file_hash=(
                pit_machine_archive_manifest_file_hash
            ),
            natural_forward_deadline_at=natural_forward_deadline_at,
        )
    finally:
        release_heavy_chain_reservation(reservation)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--paper-state-db", type=Path, default=DEFAULT_PAPER_STATE_DB)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument(
        "--mode",
        choices=(RESEARCH_MODE, FORWARD_MODE),
        default=RESEARCH_MODE,
    )
    parser.add_argument(
        "--decision-at",
        help="可選；只接受當日台北 08:30，過期／未到鐘一律留 blocked state。",
    )
    parser.add_argument(
        "--pit-machine-operational-publication",
        type=Path,
        help=(
            "可選的受控自然日 PIT operational publication；可由前一日"
            "收盤後或盤前 producer 完成，但必須在模型日台北 08:30 前"
            "可見，consumer 會重驗 receipt、available_at、effective_from 與 HMAC。"
        ),
    )
    parser.add_argument(
        "--pit-machine-operational-publication-file-hash",
        help="operational publication bytes 的 frozen sha256:<64 hex>",
    )
    parser.add_argument(
        "--natural-forward-deadline-at",
        help=(
            "forward mode 的明確 emission deadline；必須嚴格等於"
            " decision_at 後 5 分鐘"
        ),
    )
    parser.add_argument(
        "--pit-machine-archive-root",
        type=Path,
        help=(
            "可選的受控 Formal pit_candidate_archive root；必須同時提供 "
            "exact archive manifest 與其 frozen file hash"
        ),
    )
    parser.add_argument(
        "--pit-machine-archive-manifest",
        type=Path,
        help="已選定且凍結 hash 的 exact archive_manifest.json",
    )
    parser.add_argument(
        "--pit-machine-archive-manifest-file-hash",
        help="archive_manifest.json bytes 的 sha256:<64 hex>",
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        help="可選；預設使用 DATA_ROOT/output/release_v4/.ml_heavy_chain.lock。",
    )
    parser.add_argument("--raw-lookback-days", type=int, default=DEFAULT_RAW_LOOKBACK_DAYS)
    parser.add_argument("--batch-size", type=int, default=2_048)
    parser.add_argument("--compression-level", type=int, choices=range(10), default=6)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run(
            database_path=args.database,
            output_root=args.output_root,
            release_root=args.release_root,
            paper_state_db_path=args.paper_state_db,
            mode=args.mode,
            decision_at=args.decision_at,
            lock_path=args.lock_path,
            raw_lookback_days=args.raw_lookback_days,
            batch_size=args.batch_size,
            compression_level=args.compression_level,
            pit_machine_operational_path=args.pit_machine_operational_publication,
            pit_machine_operational_publication_file_hash=(
                args.pit_machine_operational_publication_file_hash
            ),
            pit_machine_archive_root=args.pit_machine_archive_root,
            pit_machine_archive_manifest=args.pit_machine_archive_manifest,
            pit_machine_archive_manifest_file_hash=(
                args.pit_machine_archive_manifest_file_hash
            ),
            natural_forward_deadline_at=(
                _parse_aware_timestamp(
                    args.natural_forward_deadline_at,
                    field_name="natural_forward_deadline_at",
                )
                if args.natural_forward_deadline_at is not None
                else None
            ),
        )
    except (OSError, TypeError, ValueError, KeyError, sqlite3.Error) as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "failed_startup",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "research_only": True,
            "production_blend_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
            "writes_source_database": False,
            "record_path": None,
        }
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    # Keep the complete derived wrapper on stdout.  Its outer status includes
    # post-run capacity and read-only integrity gates; an inner completed
    # orchestration must never hide an outer blocked result.
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if str(payload.get("status", "")).startswith(
        ("completed", "skipped", "waiting")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FORWARD_MODE",
    "MAX_FORWARD_CAPTURE_DELAY",
    "MAX_PERSISTENT_NEW_BYTES",
    "MAX_TEMPORARY_PEAK_BYTES",
    "RESEARCH_MODE",
    "SCHEMA_VERSION",
    "build_parser",
    "run",
]
