"""由正式 outer-fold OOF 與 causal execution source 建立 OOS replay input。

本模組不讀 ``targets.i32`` 或 ``labels.i32``。配置只能來自 Rule baseline
與 outer-fold meta OOF；報酬只能來自決策後實際交易日的 open/close。任何
price-event、availability、sector、流動性或 custody 缺口都 fail closed。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN
from bisect import bisect_left
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ml_module import allocation_oos_portfolio_replay as replay


BUILD_SCHEMA_VERSION = "allocation-ooc-replay-input-build.v1"
REPLAY_SOURCE_SCHEMA_VERSION = "portfolio-ml-replay-source.v1"
INITIAL_CAPITAL = Decimal("500000.00")
_TAIPEI = timezone(timedelta(hours=8))
_CASH = "CASH"
_ALLOWED_TRADABLE = frozenset({"officially_tradable", "formal_tradable"})


@dataclass(frozen=True)
class AllocationOOSReplayInputBuildRequest:
    training_manifest_path: Path


@dataclass(frozen=True)
class AllocationOOSReplayInputBuildResult:
    status: str
    blockers: tuple[str, ...]
    status_path: Path
    manifest_path: Path | None
    row_count: int
    manifest_hash: str | None


@dataclass(frozen=True)
class _Candidate:
    fold_id: str
    decision_date: date
    decision_at: datetime
    symbol: str
    sector_id: str | None
    price_event_at: datetime | None
    price_available_at: datetime | None
    median_volume_20d_shares: int | None
    rule_score_bp: int | None
    trade_restriction_status: str
    source_values_hash: str
    ml_target_weight_bp: int | None


@dataclass(frozen=True)
class _Bar:
    symbol: str
    event_date: date
    available_at: datetime
    open_price: Decimal
    close_price: Decimal
    open_int: int
    open_scale: int
    close_int: int
    close_scale: int
    volume_shares: int
    source_values_hash: str


@dataclass
class _LaneState:
    cash: Decimal = INITIAL_CAPITAL
    shares: dict[str, int] = field(default_factory=dict)
    last_close: dict[str, Decimal] = field(default_factory=dict)
    sectors: dict[str, str | None] = field(default_factory=dict)
    last_trade_session: dict[str, int] = field(default_factory=dict)
    weekly_turnover: dict[tuple[int, int], int] = field(default_factory=dict)
    previous_state_hash: str = "sha256:" + "0" * 64
    prior_close_equity: Decimal | None = None


def build_allocation_oos_replay_inputs(
    request: AllocationOOSReplayInputBuildRequest,
) -> AllocationOOSReplayInputBuildResult:
    training_path = request.training_manifest_path.resolve()
    input_root = (
        training_path.parent
        / "artifacts"
        / "oos_portfolio_replay_inputs"
    )
    status_path = input_root / "build_status.json"
    manifest_path = input_root / "manifest.json"
    try:
        custody = replay._load_formal_custody(training_path)
        sources = _load_replay_sources(
            custody,
            retro_output_root=input_root / "replay_sources",
        )
        records = _build_records(custody, sources)
        if not records:
            raise ValueError("formal_oos_replay_input_has_no_daily_records")
        input_root.mkdir(parents=True, exist_ok=True)
        rows_path = input_root / "rows.jsonl"
        record_hashes = [str(item["record_hash"]) for item in records]
        _atomic_write_text(
            rows_path,
            "".join(_canonical_json(item) + "\n" for item in records),
        )
        source_hash = replay._payload_hash(
            [item["manifest_file_hash"] for item in sources.values()]
        )
        rule_policy_hash = replay._payload_hash(
            {
                "method": "causal_t_minus_one_ma20_equal_risk_budget",
                "initial_capital": str(INITIAL_CAPITAL),
                "policy": replay._REPLAY_POLICY,
                "teacher_targets_used": False,
            }
        )
        cost_policy_hash = replay._payload_hash(
            {
                "buy_cost_bp": replay._REPLAY_POLICY["buy_cost_bp"],
                "sell_cost_bp": replay._REPLAY_POLICY["sell_cost_bp"],
                "lot_size_shares": replay._REPLAY_POLICY["lot_size_shares"],
            }
        )
        ledger_hash = replay._payload_hash(
            {
                "dataset_replay_source_hash": (
                    custody.dataset_replay_source_hash
                ),
                "replay_source_manifest_set_hash": source_hash,
                "rule_policy_hash": rule_policy_hash,
                "cost_policy_hash": cost_policy_hash,
            }
        )
        rebound = [
            _rebind_record_hashes(
                item,
                rule_policy_hash=rule_policy_hash,
                cost_policy_hash=cost_policy_hash,
                ledger_hash=ledger_hash,
            )
            for item in records
        ]
        record_hashes = [str(item["record_hash"]) for item in rebound]
        _atomic_write_text(
            rows_path,
            "".join(_canonical_json(item) + "\n" for item in rebound),
        )
        body: dict[str, object] = {
            "schema_version": replay.REPLAY_INPUT_SCHEMA_VERSION,
            "status": "complete",
            "formal_source_only": True,
            "research_shadow_included": False,
            "research_only": False,
            "input_custody": dict(custody.input_custody),
            "dataset_replay_source_hash": custody.dataset_replay_source_hash,
            "outer_fold_ids": list(custody.outer_fold_ids),
            "alpha_lanes_bp": list(replay.ALPHA_LANES),
            "policy": dict(replay._REPLAY_POLICY),
            "execution_safety": dict(replay._REQUIRED_EXECUTION_SAFETY),
            "execution_component_contract": dict(
                replay._EXECUTION_COMPONENT_CONTRACT
            ),
            "rule_policy_hash": rule_policy_hash,
            "cost_policy_hash": cost_policy_hash,
            "causal_portfolio_ledger_hash": ledger_hash,
            "fold_bindings": replay._expected_fold_bindings(custody),
            "replay_source_manifest_set_hash": source_hash,
            "replay_source_artifacts": [
                {
                    "year": year,
                    "path": str(
                        Path(
                            replay._required_text(
                                item.get("path"),
                                "replay_source.path",
                            )
                        ).resolve()
                    ),
                    "file_sha256": item["manifest_file_hash"],
                    "row_count": item["row_count"],
                    "source_mode": item["source_mode"],
                    "lineage": item["lineage"],
                }
                for year, item in sorted(sources.items())
            ],
            "teacher_targets_or_horizon_labels_read": False,
            "rows": {
                "path": rows_path.name,
                "row_count": len(rebound),
                "byte_count": rows_path.stat().st_size,
                "file_sha256": replay._file_hash(rows_path),
                "record_hashes_hash": replay._payload_hash(record_hashes),
            },
        }
        manifest = replay._with_logical_hash(body, "manifest_hash")
        _atomic_write_json(manifest_path, manifest)
        _atomic_write_json(
            status_path,
            {
                "schema_version": BUILD_SCHEMA_VERSION,
                "status": "complete",
                "manifest_path": str(manifest_path),
                "manifest_hash": manifest["manifest_hash"],
                "row_count": len(rebound),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
        )
        return AllocationOOSReplayInputBuildResult(
            status="complete",
            blockers=(),
            status_path=status_path,
            manifest_path=manifest_path,
            row_count=len(rebound),
            manifest_hash=str(manifest["manifest_hash"]),
        )
    except (replay._ReplayBlocked, OSError, KeyError, TypeError, ValueError) as exc:
        blockers = (
            exc.blockers
            if isinstance(exc, replay._ReplayBlocked)
            else (f"{type(exc).__name__}:{_safe_reason(exc)}",)
        )
        normalized = tuple(sorted(set(blockers)))
        _atomic_write_json(
            status_path,
            {
                "schema_version": BUILD_SCHEMA_VERSION,
                "status": "blocked",
                "blockers": list(normalized),
                "blocker_set_hash": replay._payload_hash(list(normalized)),
                "teacher_targets_or_horizon_labels_read": False,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
        )
        return AllocationOOSReplayInputBuildResult(
            status="blocked",
            blockers=normalized,
            status_path=status_path,
            manifest_path=None,
            row_count=0,
            manifest_hash=None,
        )


def _load_replay_sources(
    custody: replay._FormalCustody,
    *,
    retro_output_root: Path,
) -> dict[int, dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    missing_embedded = False
    raw_identity = _direct_raw_identity(custody)
    for year_item in replay._mapping_sequence(
        custody.dataset.get("years"),
        "dataset.years",
    ):
        year = replay._required_int(year_item.get("year"), "year.year")
        raw_source = year_item.get("replay_source")
        if raw_source is None:
            missing_embedded = True
            continue
        source = replay._required_mapping(raw_source, "year.replay_source")
        if source.get("schema_version") != REPLAY_SOURCE_SCHEMA_VERSION:
            raise ValueError(
                f"formal_oos_replay_source_schema_missing:{year}"
            )
        path = (
            custody.dataset_path.parent
            / f"year={year:04d}"
            / replay._required_text(source.get("path"), "replay_source.path")
        ).resolve()
        if not path.is_relative_to(custody.dataset_path.parent.resolve()):
            raise ValueError("formal_oos_replay_source_path_escapes_store")
        if not path.is_file():
            raise ValueError(
                f"formal_oos_replay_source_file_missing:{year}"
            )
        artifact = next(
            (
                item
                for item in replay._mapping_sequence(
                    year_item.get("artifacts"),
                    "year.artifacts",
                )
                if Path(
                    replay._required_text(item.get("path"), "artifact.path")
                ).name
                == path.name
            ),
            None,
        )
        if artifact is None:
            raise ValueError(
                f"formal_oos_replay_source_not_hash_bound:{year}"
            )
        expected = replay._required_sha256(
            artifact.get("file_sha256"),
            "replay_source.file_sha256",
        )
        if replay._file_hash(path) != expected:
            raise ValueError(
                f"formal_oos_replay_source_hash_mismatch:{year}"
            )
        result[year] = {
            "path": path,
            "manifest_file_hash": expected,
            "row_count": replay._required_int(
                source.get("row_count"),
                "replay_source.row_count",
            ),
            "source_mode": "embedded_direct_numeric",
            "lineage": {
                "schema_version": "allocation-replay-source-lineage.v1",
                "derivation_manifest_path": str(custody.dataset_path),
                "derivation_manifest_hash": custody.dataset["manifest_hash"],
                "derivation_manifest_file_hash": replay._file_hash(
                    custody.dataset_path
                ),
                "database_file_hash": expected,
                "training_manifest_hash": custody.training["manifest_hash"],
                "training_manifest_file_hash": replay._file_hash(
                    custody.training_path
                ),
                "store_manifest_hash": custody.dataset["manifest_hash"],
                "store_manifest_file_hash": replay._file_hash(
                    custody.dataset_path
                ),
                **raw_identity,
            },
        }
    if missing_embedded:
        if result:
            raise ValueError("formal_oos_replay_sources_partially_embedded")
        result = _retro_build_replay_sources(
            custody,
            output_root=retro_output_root,
        )
    if not result:
        raise ValueError("formal_oos_replay_sources_missing")
    return result


def _direct_raw_identity(
    custody: replay._FormalCustody,
) -> dict[str, str]:
    store_identity = replay._required_mapping(
        custody.dataset.get("store_identity"),
        "dataset.store_identity",
    )
    direct_identity = replay._required_mapping(
        store_identity.get("direct_identity"),
        "dataset.store_identity.direct_identity",
    )
    return {
        "raw_manifest_hash": replay._required_sha256(
            direct_identity.get("raw_manifest_hash"),
            "direct_identity.raw_manifest_hash",
        ),
        "raw_manifest_file_hash": replay._required_sha256(
            direct_identity.get("raw_manifest_file_hash"),
            "direct_identity.raw_manifest_file_hash",
        ),
    }


def _retro_build_replay_sources(
    custody: replay._FormalCustody,
    *,
    output_root: Path,
) -> dict[int, dict[str, object]]:
    """舊 direct store 沒有 replay sidecar 時，從其 hash-bound raw PIT 回補。

    回補只搬運 T-1 價量與因果衍生的 20 日量中位數／momentum；不讀 teacher
    target/label，也不修改 frozen store。
    """

    raw_manifest_path, raw_manifest = _discover_raw_manifest(custody)
    raw_shards = {
        replay._required_int(item.get("year"), "raw_shard.year"): item
        for item in replay._mapping_sequence(
            raw_manifest.get("shards"),
            "raw_manifest.shards",
        )
    }
    result: dict[int, dict[str, object]] = {}
    output_root.mkdir(parents=True, exist_ok=True)
    for year_item in replay._mapping_sequence(
        custody.dataset.get("years"),
        "dataset.years",
    ):
        year = replay._required_int(year_item.get("year"), "year.year")
        final_path = output_root / f"year={year:04d}.sqlite"
        manifest_path = output_root / f"year={year:04d}.manifest.json"
        if final_path.is_file() and manifest_path.is_file():
            manifest = _read_mapping(manifest_path)
            _verify_retro_manifest(
                manifest,
                database_path=final_path,
                custody=custody,
                raw_manifest=raw_manifest,
                raw_manifest_path=raw_manifest_path,
                year=year,
            )
        else:
            manifest = _build_retro_year(
                custody,
                raw_manifest_path=raw_manifest_path,
                raw_manifest=raw_manifest,
                raw_shards=raw_shards,
                year=year,
                final_path=final_path,
                manifest_path=manifest_path,
            )
        result[year] = {
            "path": final_path,
            "manifest_file_hash": replay._file_hash(final_path),
            "row_count": replay._required_int(
                manifest.get("row_count"),
                "retro.row_count",
            ),
            "source_mode": "retro_hash_bound_raw_pit",
            "lineage": {
                "schema_version": "allocation-replay-source-lineage.v1",
                "derivation_manifest_path": str(manifest_path.resolve()),
                "derivation_manifest_hash": manifest["manifest_hash"],
                "derivation_manifest_file_hash": replay._file_hash(
                    manifest_path
                ),
                "database_file_hash": replay._file_hash(final_path),
                "training_manifest_hash": custody.training["manifest_hash"],
                "training_manifest_file_hash": replay._file_hash(
                    custody.training_path
                ),
                "store_manifest_hash": custody.dataset["manifest_hash"],
                "store_manifest_file_hash": replay._file_hash(
                    custody.dataset_path
                ),
                "raw_manifest_hash": raw_manifest["manifest_hash"],
                "raw_manifest_file_hash": replay._file_hash(
                    raw_manifest_path
                ),
            },
        }
    return result


def _discover_raw_manifest(
    custody: replay._FormalCustody,
) -> tuple[Path, Mapping[str, object]]:
    store_identity = replay._required_mapping(
        custody.dataset.get("store_identity"),
        "dataset.store_identity",
    )
    direct_identity = replay._required_mapping(
        store_identity.get("direct_identity"),
        "dataset.store_identity.direct_identity",
    )
    expected_file_hash = replay._required_sha256(
        direct_identity.get("raw_manifest_file_hash"),
        "direct_identity.raw_manifest_file_hash",
    )
    expected_manifest_hash = replay._required_sha256(
        direct_identity.get("raw_manifest_hash"),
        "direct_identity.raw_manifest_hash",
    )
    candidates: list[Path] = []
    for ancestor in custody.dataset_path.parents:
        root = ancestor / "ml_pit_year_shards" / "runs"
        if root.is_dir():
            candidates.extend(
                root.glob("*/all_field_enriched/manifest.json")
            )
            candidates.extend(root.glob("*/core_long_history/manifest.json"))
            break
    matches: list[tuple[Path, Mapping[str, object]]] = []
    for path in sorted(set(item.resolve() for item in candidates)):
        if replay._file_hash(path) != expected_file_hash:
            continue
        payload = _read_mapping(path)
        if payload.get("manifest_hash") == expected_manifest_hash:
            matches.append((path, payload))
    if len(matches) != 1:
        raise ValueError(
            "formal_oos_replay_raw_manifest_discovery_not_unique:"
            f"{len(matches)}"
        )
    return matches[0]


def _build_retro_year(
    custody: replay._FormalCustody,
    *,
    raw_manifest_path: Path,
    raw_manifest: Mapping[str, object],
    raw_shards: Mapping[int, Mapping[str, object]],
    year: int,
    final_path: Path,
    manifest_path: Path,
) -> Mapping[str, object]:
    year_item = next(
        item
        for item in replay._mapping_sequence(
            custody.dataset.get("years"),
            "dataset.years",
        )
        if replay._required_int(item.get("year"), "year.year") == year
    )
    rows_path = custody.dataset_path.parent / f"year={year:04d}" / "rows.sqlite"
    if not rows_path.is_file():
        raise ValueError(f"retro_store_rows_missing:{year}")
    rows_by_symbol: dict[str, list[tuple[int, str, str]]] = {}
    rows_connection = sqlite3.connect(
        f"file:{rows_path.as_posix()}?mode=ro",
        uri=True,
    )
    for local_index, decision_at, decision_date, symbol in rows_connection.execute(
        """
        SELECT local_row_index, decision_at, decision_date, symbol
        FROM rows
        ORDER BY symbol, decision_date, local_row_index
        """
    ):
        rows_by_symbol.setdefault(str(symbol), []).append(
            (int(local_index), str(decision_at), str(decision_date))
        )
    rows_connection.close()
    bars_by_symbol: dict[str, list[dict[str, object]]] = {}
    used_shards: list[dict[str, object]] = []
    for source_year in (year - 1, year):
        shard = raw_shards.get(source_year)
        if shard is None:
            continue
        used_shards.append(
            _load_raw_price_shard(
                raw_manifest_path,
                raw_manifest=raw_manifest,
                shard=shard,
                bars_by_symbol=bars_by_symbol,
            )
        )
    staging = final_path.with_suffix(".sqlite.partial")
    staging.unlink(missing_ok=True)
    connection = sqlite3.connect(staging)
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        CREATE TABLE replay_source (
            local_row_index INTEGER PRIMARY KEY,
            decision_at TEXT NOT NULL,
            decision_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            sector_id TEXT,
            price_event_at TEXT,
            price_available_at TEXT,
            open_int INTEGER,
            open_scale INTEGER,
            close_int INTEGER,
            close_scale INTEGER,
            volume_shares INTEGER,
            median_volume_20d_shares INTEGER,
            rule_score_bp INTEGER,
            trade_restriction_status TEXT NOT NULL,
            source_values_hash TEXT NOT NULL
        );
        CREATE INDEX idx_replay_source_decision
            ON replay_source(decision_date, local_row_index);
        CREATE INDEX idx_replay_source_price_event
            ON replay_source(price_event_at, symbol);
        """
    )
    batch: list[tuple[object, ...]] = []
    emitted = 0
    for symbol in sorted(rows_by_symbol):
        bars = sorted(
            bars_by_symbol.get(symbol, ()),
            key=lambda item: str(item["event_at"]),
        )
        bar_dates = [str(item["event_at"])[:10] for item in bars]
        for local_index, decision_at, decision_date in rows_by_symbol[symbol]:
            position = bisect_left(bar_dates, decision_date) - 1
            bar = bars[position] if position >= 0 else None
            median_volume: int | None = None
            rule_score: int | None = None
            if bar is not None:
                volume_history = [
                    replay._required_int(
                        item.get("volume_shares"),
                        "bar.volume_shares",
                    )
                    for item in bars[max(0, position - 19) : position + 1]
                    if item.get("volume_shares") is not None
                ]
                if len(volume_history) == 20:
                    ordered = sorted(volume_history)
                    median_volume = (ordered[9] + ordered[10]) // 2
                if position >= 20:
                    prior_close = _bar_price(bars[position - 20], "close")
                    current_close = _bar_price(bar, "close")
                    if prior_close is not None and current_close is not None:
                        rule_score = int(
                            (
                                (
                                    current_close / prior_close
                                    - Decimal(1)
                                )
                                * Decimal(10_000)
                            ).quantize(
                                Decimal("1"),
                                rounding=ROUND_HALF_EVEN,
                            )
                        )
            batch.append(
                (
                    local_index,
                    decision_at,
                    decision_date,
                    symbol,
                    None,
                    None if bar is None else bar["event_at"],
                    None if bar is None else bar["available_at"],
                    None if bar is None else bar["open_int"],
                    None if bar is None else bar["open_scale"],
                    None if bar is None else bar["close_int"],
                    None if bar is None else bar["close_scale"],
                    None if bar is None else bar["volume_shares"],
                    median_volume,
                    rule_score,
                    "unknown_no_official_restriction_timeline",
                    (
                        replay._payload_hash([])
                        if bar is None
                        else bar["source_values_hash"]
                    ),
                )
            )
            emitted += 1
            if len(batch) >= 8_192:
                _insert_retro_rows(connection, batch)
                batch.clear()
    if batch:
        _insert_retro_rows(connection, batch)
    connection.commit()
    connection.close()
    expected_rows = replay._required_int(
        year_item.get("row_count"),
        "year.row_count",
    )
    if emitted != expected_rows:
        staging.unlink(missing_ok=True)
        raise ValueError(
            f"retro_replay_source_row_count_mismatch:{year}:"
            f"{emitted}/{expected_rows}"
        )
    os.replace(staging, final_path)
    body: dict[str, object] = {
        "schema_version": REPLAY_SOURCE_SCHEMA_VERSION,
        "source_mode": "retro_hash_bound_raw_pit",
        "year": year,
        "row_count": emitted,
        "database_path": final_path.name,
        "database_file_hash": replay._file_hash(final_path),
        "training_manifest_hash": custody.training["manifest_hash"],
        "training_manifest_file_hash": replay._file_hash(
            custody.training_path
        ),
        "store_manifest_hash": custody.dataset["manifest_hash"],
        "store_manifest_file_hash": replay._file_hash(custody.dataset_path),
        "raw_manifest_hash": raw_manifest["manifest_hash"],
        "raw_manifest_file_hash": replay._file_hash(raw_manifest_path),
        "raw_shards": used_shards,
        "teacher_targets_or_horizon_labels_read": False,
        "sector_unknown_no_new_position": True,
        "trade_restriction_unknown_no_new_position": True,
    }
    manifest = replay._with_logical_hash(body, "manifest_hash")
    _atomic_write_json(manifest_path, manifest)
    return manifest


def _load_raw_price_shard(
    raw_manifest_path: Path,
    *,
    raw_manifest: Mapping[str, object],
    shard: Mapping[str, object],
    bars_by_symbol: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    publication_root = raw_manifest_path.parent.parent.resolve()
    path = (
        publication_root
        / replay._required_text(shard.get("path"), "raw_shard.path")
    ).resolve()
    if not path.is_relative_to(publication_root):
        raise ValueError("retro_raw_shard_path_escapes_publication")
    expected_file_hash = replay._required_sha256(
        shard.get("compressed_sha256"),
        "raw_shard.compressed_sha256",
    )
    if replay._file_hash(path) != expected_file_hash:
        raise ValueError("retro_raw_shard_file_hash_mismatch")
    digest = hashlib.sha256()
    row_count = 0
    value_count = 0
    with gzip.open(path, "rb") as stream:
        for raw_line in stream:
            if not raw_line.strip():
                continue
            digest.update(raw_line)
            payload = json.loads(raw_line.decode("utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("retro raw observation must be object")
            if (
                payload.get("schema_version") != "ml-pit-observation.v1"
                or payload.get("dataset_id") != raw_manifest.get("dataset_id")
                or payload.get("pit_status") != "eligible_as_of_decision"
            ):
                raise ValueError("retro raw observation custody mismatch")
            expected_row_hash = replay._required_sha256(
                payload.get("source_row_hash"),
                "raw.source_row_hash",
            )
            body = dict(payload)
            body.pop("source_row_hash", None)
            if replay._payload_hash(body) != expected_row_hash:
                raise ValueError("retro raw observation row hash mismatch")
            values = replay._mapping_sequence(
                payload.get("values"),
                "raw.values",
            )
            row_count += 1
            value_count += len(values)
            if (
                payload.get("source_table") != "daily_prices"
                or payload.get("source_id") != "sqlite.daily_prices"
            ):
                continue
            by_id = {
                replay._required_text(item.get("feature_id"), "feature_id"): item
                for item in values
            }
            open_value = by_id.get("daily_prices.開盤價")
            close_value = by_id.get("daily_prices.收盤價")
            volume_value = by_id.get("daily_prices.成交股數")
            if open_value is None or close_value is None or volume_value is None:
                continue
            open_int = _formal_raw_int(open_value)
            close_int = _formal_raw_int(close_value)
            volume_int = _formal_raw_int(volume_value)
            if (
                open_int is None
                or close_int is None
                or volume_int is None
                or open_int <= 0
                or close_int <= 0
                or volume_int <= 0
            ):
                continue
            source_hashes = [
                replay._required_sha256(
                    item.get("source_value_hash"),
                    "source_value_hash",
                )
                for item in (open_value, close_value, volume_value)
            ]
            symbol = replay._required_text(
                payload.get("entity_id"),
                "raw.entity_id",
            )
            bars_by_symbol.setdefault(symbol, []).append(
                {
                    "event_at": replay._required_text(
                        payload.get("event_at"),
                        "raw.event_at",
                    ),
                    "available_at": replay._required_text(
                        payload.get("available_at"),
                        "raw.available_at",
                    ),
                    "open_int": open_int,
                    "open_scale": replay._required_int(
                        open_value.get("scale"),
                        "open.scale",
                    ),
                    "close_int": close_int,
                    "close_scale": replay._required_int(
                        close_value.get("scale"),
                        "close.scale",
                    ),
                    "volume_shares": volume_int,
                    "source_values_hash": replay._payload_hash(
                        sorted(source_hashes)
                    ),
                }
            )
    if "sha256:" + digest.hexdigest() != replay._required_sha256(
        shard.get("content_sha256"),
        "raw_shard.content_sha256",
    ):
        raise ValueError("retro_raw_shard_content_hash_mismatch")
    if row_count != replay._required_int(
        shard.get("row_count"),
        "raw_shard.row_count",
    ):
        raise ValueError("retro_raw_shard_row_count_mismatch")
    if value_count != replay._required_int(
        shard.get("feature_value_count"),
        "raw_shard.feature_value_count",
    ):
        raise ValueError("retro_raw_shard_value_count_mismatch")
    return {
        "year": replay._required_int(shard.get("year"), "raw_shard.year"),
        "path": str(path),
        "compressed_sha256": expected_file_hash,
        "content_sha256": shard["content_sha256"],
    }


def _formal_raw_int(value: Mapping[str, object]) -> int | None:
    for field_name in (
        "formal_training_eligible",
        "missing_mask",
        "quality_blocked_mask",
    ):
        raw = value.get(field_name)
        if not isinstance(raw, bool):
            raise TypeError(f"raw {field_name} must be bool")
    if (
        value["formal_training_eligible"] is not True
        or value["missing_mask"] is True
        or value["quality_blocked_mask"] is True
    ):
        return None
    return _optional_int(value.get("value_int"))


def _bar_price(
    bar: Mapping[str, object],
    prefix: str,
) -> Decimal | None:
    return _scaled_price(
        bar.get(f"{prefix}_int"),
        bar.get(f"{prefix}_scale"),
    )


def _insert_retro_rows(
    connection: sqlite3.Connection,
    rows: Sequence[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT INTO replay_source(
            local_row_index, decision_at, decision_date, symbol,
            sector_id, price_event_at, price_available_at,
            open_int, open_scale, close_int, close_scale,
            volume_shares, median_volume_20d_shares, rule_score_bp,
            trade_restriction_status, source_values_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _verify_retro_manifest(
    manifest: Mapping[str, object],
    *,
    database_path: Path,
    custody: replay._FormalCustody,
    raw_manifest: Mapping[str, object],
    raw_manifest_path: Path,
    year: int,
) -> None:
    if (
        manifest.get("schema_version") != REPLAY_SOURCE_SCHEMA_VERSION
        or manifest.get("source_mode") != "retro_hash_bound_raw_pit"
        or manifest.get("year") != year
        or manifest.get("training_manifest_hash")
        != custody.training.get("manifest_hash")
        or manifest.get("store_manifest_hash")
        != custody.dataset.get("manifest_hash")
        or manifest.get("raw_manifest_hash")
        != raw_manifest.get("manifest_hash")
        or manifest.get("training_manifest_file_hash")
        != replay._file_hash(custody.training_path)
        or manifest.get("store_manifest_file_hash")
        != replay._file_hash(custody.dataset_path)
        or manifest.get("raw_manifest_file_hash")
        != replay._file_hash(raw_manifest_path)
        or manifest.get("database_path") != database_path.name
    ):
        raise ValueError(f"retro_replay_source_custody_mismatch:{year}")
    replay._verify_logical_hash(
        manifest,
        "manifest_hash",
        f"retro_replay_source_manifest_hash_mismatch:{year}",
    )
    if (
        replay._file_hash(database_path)
        != manifest.get("database_file_hash")
    ):
        raise ValueError(f"retro_replay_source_database_hash_mismatch:{year}")


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain object")
    return value


def _build_records(
    custody: replay._FormalCustody,
    sources: Mapping[int, Mapping[str, object]],
) -> list[dict[str, object]]:
    meta_paths = _meta_oof_paths(custody)
    result: list[dict[str, object]] = []
    for fold_index, fold_id in enumerate(custody.outer_fold_ids):
        fold = custody.folds_by_id[fold_id]
        refs = _open_test_refs(custody, fold)
        meta_path = meta_paths.get(fold_id)
        meta = (
            None
            if meta_path is None
            else np.memmap(
                meta_path,
                dtype="<i4",
                mode="r",
                shape=(len(refs), 6),
            )
        )
        groups = _fold_candidates(
            custody,
            sources=sources,
            fold_id=fold_id,
            refs=refs,
            meta=meta,
        )
        rule_state = _LaneState()
        lane_states = {
            alpha: _LaneState() for alpha in replay.ALPHA_LANES if alpha
        }
        for session_index, (decision_day, candidates) in enumerate(groups):
            symbols = {
                candidate.symbol for candidate in candidates
            } | set(rule_state.shares)
            for state in lane_states.values():
                symbols.update(state.shares)
            bars = _bars_for_date(
                sources,
                event_date=decision_day,
                symbols=symbols,
            )
            _require_daily_bars(
                bars,
                fold_id=fold_id,
                decision_day=decision_day,
            )
            rule_weights = _rule_weights(candidates)
            ml_weights = _ml_weights(candidates)
            rule_metrics, rule_transition = _execute_day(
                state=rule_state,
                decision_day=decision_day,
                session_index=session_index,
                candidates=candidates,
                bars=bars,
                requested=rule_weights,
            )
            lanes: list[dict[str, object]] = [
                {"alpha_bp": 0, **rule_metrics}
            ]
            lane_calculations: list[dict[str, object]] = [
                {
                    "alpha_bp": 0,
                    **replay._required_mapping(
                        rule_transition.get("calculation"),
                        "rule_transition.calculation",
                    ),
                }
            ]
            meta_entry = custody.meta_oof_by_fold.get(fold_id)
            for alpha in replay.ALPHA_LANES[1:]:
                if meta_entry is None:
                    lane_states[alpha] = _clone_state(rule_state)
                    metrics = dict(rule_metrics)
                    transition = dict(rule_transition)
                else:
                    requested = _blend(rule_weights, ml_weights, alpha)
                    metrics, transition = _execute_day(
                        state=lane_states[alpha],
                        decision_day=decision_day,
                        session_index=session_index,
                        candidates=candidates,
                        bars=bars,
                        requested=requested,
                    )
                lanes.append({"alpha_bp": alpha, **metrics})
                lane_calculations.append(
                    {
                        "alpha_bp": alpha,
                        **replay._required_mapping(
                            transition.get("calculation"),
                            "lane_transition.calculation",
                        ),
                    }
                )
            outcome_at = max(bar.available_at for bar in bars.values())
            price_components = [
                {
                    "symbol": bar.symbol,
                    "event_date": bar.event_date.isoformat(),
                    "available_at": bar.available_at.isoformat(
                        timespec="seconds"
                    ),
                    "open_int": bar.open_int,
                    "open_scale": bar.open_scale,
                    "close_int": bar.close_int,
                    "close_scale": bar.close_scale,
                    "volume_shares": bar.volume_shares,
                    "source_values_hash": bar.source_values_hash,
                }
                for bar in sorted(bars.values(), key=lambda item: item.symbol)
            ]
            body: dict[str, object] = {
                "schema_version": replay.REPLAY_ROW_SCHEMA_VERSION,
                "fold_id": fold_id,
                "decision_date": decision_day.isoformat(),
                "decision_at": datetime.combine(
                    decision_day,
                    time(8, 30),
                    tzinfo=_TAIPEI,
                ).isoformat(timespec="seconds"),
                "outcome_available_at": outcome_at.isoformat(
                    timespec="seconds"
                ),
                "allocation_source": (
                    "rule_fallback"
                    if meta_entry is None
                    else "meta_oof"
                ),
                "source_meta_oof_file_hash": (
                    None
                    if meta_entry is None
                    else meta_entry["oof_file_hash"]
                ),
                "rule_policy_hash": "sha256:" + "0" * 64,
                "cost_policy_hash": "sha256:" + "0" * 64,
                "causal_portfolio_ledger_hash": "sha256:" + "0" * 64,
                "causal_t_minus_one_state_hash": rule_transition[
                    "previous_state_hash"
                ],
                "causal_post_close_state_hash": rule_transition[
                    "post_close_state_hash"
                ],
                "candidate_count": len(candidates),
                "teacher_targets_or_horizon_labels_read": False,
                "calculation_verification": {
                    "price_components": price_components,
                    "price_source_set_hash": replay._payload_hash(
                        price_components
                    ),
                    "rule": rule_transition["calculation"],
                    "lanes": lane_calculations,
                },
                "rule": rule_metrics,
                "lanes": lanes,
            }
            result.append(replay._with_logical_hash(body, "record_hash"))
        del refs
        if meta is not None:
            del meta
    return result


def _meta_oof_paths(
    custody: replay._FormalCustody,
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in replay._mapping_sequence(
        custody.training.get("meta_folds"),
        "training.meta_folds",
    ):
        fold_id = replay._required_text(item.get("fold_id"), "meta.fold_id")
        directory = (
            custody.training_path.parent
            / replay._required_text(
                item.get("artifact_path"),
                "meta.artifact_path",
            )
        ).resolve()
        path = directory / "oof.i32"
        if not path.is_file():
            raise ValueError(f"meta_oof_file_missing:{fold_id}")
        result[fold_id] = path
    return result


def _open_test_refs(
    custody: replay._FormalCustody,
    fold: Mapping[str, object],
) -> np.memmap:
    item = replay._required_mapping(fold.get("test"), "fold.test")
    path = (
        custody.dataset_path.parent
        / "folds"
        / replay._required_text(item.get("path"), "fold.test.path")
    )
    row_count = replay._required_int(
        item.get("row_count"),
        "fold.test.row_count",
    )
    return np.memmap(path, dtype="<i8", mode="r", shape=(row_count, 2))


def _fold_candidates(
    custody: replay._FormalCustody,
    *,
    sources: Mapping[int, Mapping[str, object]],
    fold_id: str,
    refs: np.memmap,
    meta: np.memmap | None,
) -> list[tuple[date, tuple[_Candidate, ...]]]:
    years = replay._mapping_sequence(custody.dataset.get("years"), "years")
    grouped: dict[date, list[_Candidate]] = {}
    for ordinal_value in np.unique(refs[:, 0]):
        ordinal = int(ordinal_value)
        year_item = years[ordinal]
        year = replay._required_int(year_item.get("year"), "year.year")
        source = sources.get(year)
        if source is None:
            raise ValueError(f"replay_source_year_missing:{year}")
        positions = np.flatnonzero(refs[:, 0] == ordinal_value)
        locals_ = np.asarray(refs[positions, 1], dtype=np.int64)
        connection = sqlite3.connect(
            "file:"
            f"{Path(replay._required_text(source.get('path'), 'source.path')).as_posix()}"
            "?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            "SELECT * FROM replay_source ORDER BY local_row_index"
        )
        target = 0
        for row in cursor:
            if target >= len(locals_):
                break
            local = int(row["local_row_index"])
            expected = int(locals_[target])
            if local < expected:
                continue
            if local > expected:
                connection.close()
                raise ValueError("replay_source_ref_missing")
            global_position = int(positions[target])
            decision_at = _parse_datetime(str(row["decision_at"]))
            candidate = _Candidate(
                fold_id=fold_id,
                decision_date=date.fromisoformat(str(row["decision_date"])),
                decision_at=decision_at,
                symbol=str(row["symbol"]),
                sector_id=(
                    None
                    if row["sector_id"] in (None, "")
                    else str(row["sector_id"])
                ),
                price_event_at=_optional_datetime(row["price_event_at"]),
                price_available_at=_optional_datetime(
                    row["price_available_at"]
                ),
                median_volume_20d_shares=_optional_int(
                    row["median_volume_20d_shares"]
                ),
                rule_score_bp=_optional_int(row["rule_score_bp"]),
                trade_restriction_status=str(
                    row["trade_restriction_status"]
                ),
                source_values_hash=replay._required_sha256(
                    row["source_values_hash"],
                    "source_values_hash",
                ),
                ml_target_weight_bp=(
                    None
                    if meta is None
                    else int(meta[global_position, 0])
                ),
            )
            if (
                candidate.price_available_at is not None
                and candidate.price_available_at > candidate.decision_at
            ):
                connection.close()
                raise ValueError("replay_source_future_prefix_violation")
            grouped.setdefault(candidate.decision_date, []).append(candidate)
            target += 1
        connection.close()
        if target != len(locals_):
            raise ValueError("replay_source_ref_coverage_incomplete")
    return [
        (day, tuple(sorted(values, key=lambda item: item.symbol)))
        for day, values in sorted(grouped.items())
    ]


def _bars_for_date(
    sources: Mapping[int, Mapping[str, object]],
    *,
    event_date: date,
    symbols: Iterable[str],
) -> dict[str, _Bar]:
    remaining = set(symbols)
    result: dict[str, _Bar] = {}
    start = event_date.isoformat() + "T00:00:00"
    stop = event_date.isoformat() + "T23:59:59.999999"
    for year in (event_date.year, event_date.year + 1):
        source = sources.get(year)
        if source is None or not remaining:
            continue
        connection = sqlite3.connect(
            "file:"
            f"{Path(replay._required_text(source.get('path'), 'source.path')).as_posix()}"
            "?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in remaining)
        query = (
            "SELECT * FROM replay_source "
            "WHERE price_event_at BETWEEN ? AND ? "
            f"AND symbol IN ({placeholders}) "
            "ORDER BY decision_date, local_row_index"
        )
        for row in connection.execute(
            query,
            (start, stop, *sorted(remaining)),
        ):
            symbol = str(row["symbol"])
            if symbol in result:
                continue
            open_int = _optional_int(row["open_int"])
            open_scale = _optional_int(row["open_scale"])
            close_int = _optional_int(row["close_int"])
            close_scale = _optional_int(row["close_scale"])
            open_price = _scaled_price(open_int, open_scale)
            close_price = _scaled_price(close_int, close_scale)
            volume = _optional_int(row["volume_shares"])
            available_at = _optional_datetime(row["price_available_at"])
            if (
                open_price is None
                or close_price is None
                or volume is None
                or volume <= 0
                or available_at is None
            ):
                continue
            result[symbol] = _Bar(
                symbol=symbol,
                event_date=event_date,
                available_at=available_at,
                open_price=open_price,
                close_price=close_price,
                open_int=replay._required_int(open_int, "bar.open_int"),
                open_scale=replay._required_int(
                    open_scale,
                    "bar.open_scale",
                ),
                close_int=replay._required_int(close_int, "bar.close_int"),
                close_scale=replay._required_int(
                    close_scale,
                    "bar.close_scale",
                ),
                volume_shares=volume,
                source_values_hash=replay._required_sha256(
                    row["source_values_hash"],
                    "bar.source_values_hash",
                ),
            )
            remaining.discard(symbol)
        connection.close()
    return result


def _require_daily_bars(
    bars: Mapping[str, _Bar],
    *,
    fold_id: str,
    decision_day: date,
) -> None:
    if not bars:
        raise ValueError(
            "formal_oos_replay_outcome_bar_missing:"
            f"{fold_id}:{decision_day.isoformat()}"
        )


def _rule_weights(
    candidates: Sequence[_Candidate],
) -> dict[str, int]:
    eligible = [
        item
        for item in candidates
        if _eligible_for_new_position(item)
        and item.rule_score_bp is not None
        and item.rule_score_bp > 0
    ]
    ranked = sorted(
        eligible,
        key=lambda item: (-int(item.rule_score_bp or 0), item.symbol),
    )[: replay._REPLAY_POLICY["maximum_positions"]]
    return _capped_weights(
        [(item.symbol, 1, item.sector_id) for item in ranked]
    )


def _ml_weights(
    candidates: Sequence[_Candidate],
) -> dict[str, int]:
    eligible = [
        item
        for item in candidates
        if _eligible_for_new_position(item)
        and item.ml_target_weight_bp is not None
        and item.ml_target_weight_bp > 0
    ]
    ranked = sorted(
        eligible,
        key=lambda item: (
            -int(item.ml_target_weight_bp or 0),
            item.symbol,
        ),
    )[: replay._REPLAY_POLICY["maximum_positions"]]
    return _capped_weights(
        [
            (
                item.symbol,
                int(item.ml_target_weight_bp or 0),
                item.sector_id,
            )
            for item in ranked
        ]
    )


def _eligible_for_new_position(candidate: _Candidate) -> bool:
    return bool(
        candidate.sector_id
        and candidate.price_event_at is not None
        and candidate.price_event_at < candidate.decision_at
        and candidate.median_volume_20d_shares
        and candidate.median_volume_20d_shares > 0
        and candidate.trade_restriction_status in _ALLOWED_TRADABLE
    )


def _capped_weights(
    values: Sequence[tuple[str, int, str | None]],
) -> dict[str, int]:
    if not values:
        return {_CASH: 10_000}
    risky = 10_000 - replay._REPLAY_POLICY["minimum_cash_bp"]
    total = sum(item[1] for item in values)
    raw = {
        symbol: min(
            replay._REPLAY_POLICY["maximum_symbol_weight_bp"],
            risky * score // total,
        )
        for symbol, score, _ in values
    }
    sectors = {symbol: sector for symbol, _, sector in values}
    for sector in sorted({item for item in sectors.values() if item}):
        names = sorted(
            symbol for symbol, value in sectors.items() if value == sector
        )
        sector_total = sum(raw[name] for name in names)
        cap = replay._REPLAY_POLICY["maximum_sector_weight_bp"]
        if sector_total > cap:
            for name in names:
                raw[name] = raw[name] * cap // sector_total
    raw[_CASH] = 10_000 - sum(raw.values())
    return raw


def _blend(
    rule_weights: Mapping[str, int],
    ml_weights: Mapping[str, int],
    alpha: int,
) -> dict[str, int]:
    keys = sorted(set(rule_weights) | set(ml_weights))
    floors: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    for key in keys:
        numerator = (
            (10_000 - alpha) * int(rule_weights.get(key, 0))
            + alpha * int(ml_weights.get(key, 0))
        )
        floors[key], remainder = divmod(numerator, 10_000)
        remainders.append((remainder, key))
    for _, key in sorted(
        remainders,
        key=lambda item: (-item[0], item[1]),
    )[: 10_000 - sum(floors.values())]:
        floors[key] += 1
    return floors


def _execute_day(
    *,
    state: _LaneState,
    decision_day: date,
    session_index: int,
    candidates: Sequence[_Candidate],
    bars: Mapping[str, _Bar],
    requested: Mapping[str, int],
) -> tuple[dict[str, int], dict[str, object]]:
    candidate_by_symbol = {item.symbol: item for item in candidates}
    opening_cash = state.cash
    opening_shares = dict(state.shares)
    symbols = sorted(set(state.shares) | (set(requested) - {_CASH}))
    open_value = state.cash
    open_prices: dict[str, Decimal] = {}
    for symbol in symbols:
        if state.shares.get(symbol, 0) > 0 and symbol not in bars:
            raise ValueError(f"held_symbol_bar_missing:{symbol}")
        price = bars[symbol].open_price if symbol in bars else None
        if price is None:
            continue
        open_prices[symbol] = price
        open_value += Decimal(state.shares.get(symbol, 0)) * price
    if open_value <= 0:
        raise ValueError("replay_lane_open_value_not_positive")
    previous_hash = state.previous_state_hash
    current_weights = _weights_from_holdings(
        state,
        prices=open_prices,
        total=open_value,
    )
    target = {
        symbol: int(requested.get(symbol, 0))
        for symbol in symbols
    }
    for symbol in symbols:
        current = current_weights.get(symbol, 0)
        candidate = candidate_by_symbol.get(symbol)
        if target[symbol] > current and (
            candidate is None or not _eligible_for_new_position(candidate)
        ):
            target[symbol] = current
        if (
            candidate is not None
            and candidate.trade_restriction_status == "officially_blocked"
        ):
            target[symbol] = 0
    _enforce_target_caps(target, state.sectors, candidate_by_symbol)
    week = decision_day.isocalendar()
    week_key = (week.year, week.week)
    used_turnover = state.weekly_turnover.get(week_key, 0)
    theoretical = _turnover_bp(current_weights, target)
    if used_turnover + theoretical > replay._REPLAY_POLICY[
        "maximum_weekly_turnover_bp"
    ]:
        target = dict(current_weights)
    for symbol in symbols:
        gap = target.get(symbol, 0) - current_weights.get(symbol, 0)
        if (
            abs(gap) <= replay._REPLAY_POLICY["rebalance_band_bp"]
            or abs(gap) < replay._REPLAY_POLICY["minimum_trade_bp"]
            or session_index - state.last_trade_session.get(symbol, -10_000)
            < replay._REPLAY_POLICY["cooldown_trading_days"]
        ):
            target[symbol] = current_weights.get(symbol, 0)
    before_trade = dict(current_weights)
    costs = Decimal(0)
    lot = replay._REPLAY_POLICY["lot_size_shares"]
    for symbol in sorted(symbols):
        if symbol not in open_prices:
            continue
        current_shares = state.shares.get(symbol, 0)
        desired = int(
            (
                open_value
                * Decimal(target.get(symbol, 0))
                / Decimal(10_000)
                / open_prices[symbol]
            ).to_integral_value(rounding=ROUND_DOWN)
        )
        desired = desired // lot * lot
        if desired >= current_shares:
            continue
        sell = current_shares - desired
        notional = Decimal(sell) * open_prices[symbol]
        cost = _cost(notional, replay._REPLAY_POLICY["sell_cost_bp"])
        state.cash += notional - cost
        costs += cost
        state.shares[symbol] = desired
        state.last_trade_session[symbol] = session_index
    reserve = open_value * Decimal(
        replay._REPLAY_POLICY["minimum_cash_bp"]
    ) / Decimal(10_000)
    for symbol in sorted(
        symbols,
        key=lambda item: (
            -(target.get(item, 0) - before_trade.get(item, 0)),
            item,
        ),
    ):
        if symbol not in open_prices:
            continue
        current_shares = state.shares.get(symbol, 0)
        desired = int(
            (
                open_value
                * Decimal(target.get(symbol, 0))
                / Decimal(10_000)
                / open_prices[symbol]
            ).to_integral_value(rounding=ROUND_DOWN)
        )
        desired = desired // lot * lot
        if desired <= current_shares:
            continue
        candidate = candidate_by_symbol.get(symbol)
        if candidate is None or not _eligible_for_new_position(candidate):
            continue
        volume_cap = (
            int(candidate.median_volume_20d_shares or 0)
            * replay._REPLAY_POLICY[
                "maximum_t_minus_1_median_volume_participation_bp"
            ]
            // 10_000
        )
        volume_cap = volume_cap // lot * lot
        buy = min(desired - current_shares, volume_cap)
        per_lot_notional = Decimal(lot) * open_prices[symbol]
        per_lot_cost = _cost(
            per_lot_notional,
            replay._REPLAY_POLICY["buy_cost_bp"],
        )
        available = max(Decimal(0), state.cash - reserve)
        affordable_lots = int(
            (available / (per_lot_notional + per_lot_cost))
            .to_integral_value(rounding=ROUND_DOWN)
        )
        buy = min(buy, affordable_lots * lot)
        if buy <= 0:
            continue
        notional = Decimal(buy) * open_prices[symbol]
        cost = _cost(notional, replay._REPLAY_POLICY["buy_cost_bp"])
        state.cash -= notional + cost
        costs += cost
        state.shares[symbol] = current_shares + buy
        state.last_trade_session[symbol] = session_index
        state.sectors[symbol] = candidate.sector_id
    after_trade_value = state.cash + sum(
        (
            Decimal(shares) * open_prices[symbol]
            for symbol, shares in state.shares.items()
            if shares > 0 and symbol in open_prices
        ),
        Decimal(0),
    )
    after_trade_weights = _weights_from_holdings(
        state,
        prices=open_prices,
        total=after_trade_value,
    )
    turnover = _turnover_bp(before_trade, after_trade_weights)
    close_value = state.cash
    for symbol, shares in list(state.shares.items()):
        if shares <= 0:
            state.shares.pop(symbol, None)
            continue
        if symbol not in bars:
            raise ValueError(f"held_symbol_bar_missing:{symbol}")
        close_price = bars[symbol].close_price
        if close_price is None:
            raise ValueError(f"held_symbol_close_missing:{symbol}")
        state.last_close[symbol] = close_price
        close_value += Decimal(shares) * close_price
    performance_open_value = (
        open_value
        if state.prior_close_equity is None
        else state.prior_close_equity
    )
    opening_minor = _money_minor(performance_open_value)
    closing_minor = _money_minor(close_value)
    return_bp = int(
        (
            (
                Decimal(closing_minor) / Decimal(opening_minor)
                - Decimal(1)
            )
            * Decimal(10_000)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    )
    after_weights = _weights_from_holdings(
        state,
        prices={
            symbol: state.last_close[symbol]
            for symbol in state.shares
        },
        total=close_value,
    )
    state.weekly_turnover[week_key] = used_turnover + turnover
    state_hash = replay._payload_hash(
        {
            "decision_date": decision_day.isoformat(),
            "cash": str(state.cash.quantize(Decimal("0.01"))),
            "shares": sorted(state.shares.items()),
            "last_close": sorted(
                (key, str(value)) for key, value in state.last_close.items()
            ),
            "post_close_equity": str(
                close_value.quantize(Decimal("0.01"))
            ),
            "previous_state_hash": previous_hash,
        }
    )
    state.previous_state_hash = state_hash
    state.prior_close_equity = close_value
    core_coverage, enriched_coverage = _coverage(candidates)
    requested_symbols = {
        key for key, value in requested.items() if key != _CASH and value > 0
    }
    feasible = (
        10_000
        if not requested_symbols
        else (
            10_000
            * sum(symbol in bars for symbol in requested_symbols)
            // len(requested_symbols)
        )
    )
    violations = _constraint_violations(
        after_weights,
        sectors=state.sectors,
        weekly_turnover=state.weekly_turnover[week_key],
    )
    metrics = {
        "after_cost_return_bp": return_bp,
        "turnover_bp": turnover,
        "core_coverage_bp": core_coverage,
        "enriched_coverage_bp": enriched_coverage,
        "feasible_fill_coverage_bp": feasible,
        "pit_violation_count": 0,
        "future_prefix_violation_count": 0,
        "constraint_violation_count": len(violations),
    }
    return metrics, {
        "previous_state_hash": previous_hash,
        "post_close_state_hash": state_hash,
        "transaction_cost": str(costs.quantize(Decimal("0.01"))),
        "calculation": {
            "opening_value_minor": opening_minor,
            "closing_value_minor": closing_minor,
            "transaction_cost_minor": _money_minor(costs),
            "opening_cash_minor": _money_minor(opening_cash),
            "closing_cash_minor": _money_minor(state.cash),
            "holdings": [
                {
                    "symbol": symbol,
                    "opening_shares": opening_shares.get(symbol, 0),
                    "post_trade_shares": state.shares.get(symbol, 0),
                }
                for symbol in sorted(
                    set(opening_shares) | set(state.shares)
                )
            ],
            "before_weights": _weight_rows(before_trade),
            "after_trade_weights": _weight_rows(after_trade_weights),
        },
    }


def _weights_from_holdings(
    state: _LaneState,
    *,
    prices: Mapping[str, Decimal],
    total: Decimal,
) -> dict[str, int]:
    result = {
        symbol: int(
            (
                Decimal(shares)
                * prices[symbol]
                * Decimal(10_000)
                / total
            ).to_integral_value(rounding=ROUND_DOWN)
        )
        for symbol, shares in state.shares.items()
        if shares > 0 and symbol in prices
    }
    result[_CASH] = 10_000 - sum(result.values())
    return result


def _enforce_target_caps(
    target: dict[str, int],
    prior_sectors: Mapping[str, str | None],
    candidates: Mapping[str, _Candidate],
) -> None:
    cap = replay._REPLAY_POLICY["maximum_symbol_weight_bp"]
    for symbol in target:
        target[symbol] = min(cap, max(0, target[symbol]))
    positive = sorted(
        (symbol for symbol, value in target.items() if value > 0),
        key=lambda symbol: (-target[symbol], symbol),
    )
    for symbol in positive[replay._REPLAY_POLICY["maximum_positions"] :]:
        target[symbol] = 0
    by_sector: dict[str, list[str]] = {}
    for symbol, value in target.items():
        if value <= 0:
            continue
        sector = (
            candidates[symbol].sector_id
            if symbol in candidates
            else prior_sectors.get(symbol)
        )
        if sector is None:
            target[symbol] = 0
            continue
        by_sector.setdefault(sector, []).append(symbol)
    for names in by_sector.values():
        total = sum(target[name] for name in names)
        cap_value = replay._REPLAY_POLICY["maximum_sector_weight_bp"]
        if total > cap_value:
            for name in names:
                target[name] = target[name] * cap_value // total
    invested = sum(target.values())
    maximum = 10_000 - replay._REPLAY_POLICY["minimum_cash_bp"]
    if invested > maximum:
        for symbol in target:
            target[symbol] = target[symbol] * maximum // invested


def _turnover_bp(
    current: Mapping[str, int],
    target: Mapping[str, int],
) -> int:
    keys = set(current) | set(target) | {_CASH}
    current_cash = int(current.get(_CASH, 10_000 - sum(
        value for key, value in current.items() if key != _CASH
    )))
    target_cash = int(target.get(_CASH, 10_000 - sum(
        value for key, value in target.items() if key != _CASH
    )))
    total = sum(
        abs(
            (current_cash if key == _CASH else int(current.get(key, 0)))
            - (target_cash if key == _CASH else int(target.get(key, 0)))
        )
        for key in keys
    )
    return total // 2


def _coverage(candidates: Sequence[_Candidate]) -> tuple[int, int]:
    if not candidates:
        return 0, 0
    core = sum(
        item.price_event_at is not None and item.rule_score_bp is not None
        for item in candidates
    )
    enriched = sum(_eligible_for_new_position(item) for item in candidates)
    return (
        core * 10_000 // len(candidates),
        enriched * 10_000 // len(candidates),
    )


def _constraint_violations(
    weights: Mapping[str, int],
    *,
    sectors: Mapping[str, str | None],
    weekly_turnover: int,
) -> tuple[str, ...]:
    positions = {
        key: value for key, value in weights.items() if key != _CASH and value
    }
    violations: list[str] = []
    if weights.get(_CASH, 0) < replay._REPLAY_POLICY["minimum_cash_bp"]:
        violations.append("cash_floor")
    if len(positions) > replay._REPLAY_POLICY["maximum_positions"]:
        violations.append("position_count")
    if any(
        value > replay._REPLAY_POLICY["maximum_symbol_weight_bp"]
        for value in positions.values()
    ):
        violations.append("symbol_cap")
    sector_weights: dict[str, int] = {}
    for symbol, value in positions.items():
        sector = sectors.get(symbol)
        if sector is None:
            violations.append("sector_unknown")
            continue
        sector_weights[sector] = sector_weights.get(sector, 0) + value
    if any(
        value > replay._REPLAY_POLICY["maximum_sector_weight_bp"]
        for value in sector_weights.values()
    ):
        violations.append("sector_cap")
    if weekly_turnover > replay._REPLAY_POLICY["maximum_weekly_turnover_bp"]:
        violations.append("weekly_turnover")
    return tuple(sorted(set(violations)))


def _clone_state(state: _LaneState) -> _LaneState:
    return _LaneState(
        cash=state.cash,
        shares=dict(state.shares),
        last_close=dict(state.last_close),
        sectors=dict(state.sectors),
        last_trade_session=dict(state.last_trade_session),
        weekly_turnover=dict(state.weekly_turnover),
        previous_state_hash=state.previous_state_hash,
        prior_close_equity=state.prior_close_equity,
    )


def _rebind_record_hashes(
    value: Mapping[str, object],
    *,
    rule_policy_hash: str,
    cost_policy_hash: str,
    ledger_hash: str,
) -> dict[str, object]:
    body = dict(value)
    body.pop("record_hash", None)
    body["rule_policy_hash"] = rule_policy_hash
    body["cost_policy_hash"] = cost_policy_hash
    body["causal_portfolio_ledger_hash"] = ledger_hash
    return replay._with_logical_hash(body, "record_hash")


def _cost(notional: Decimal, bp: int) -> Decimal:
    return (
        notional * Decimal(bp) / Decimal(10_000)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _money_minor(value: Decimal) -> int:
    return int(
        (value * Decimal(100)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _weight_rows(weights: Mapping[str, int]) -> list[dict[str, object]]:
    canonical = {
        key: int(value) for key, value in weights.items() if int(value) > 0
    }
    if _CASH not in canonical:
        canonical[_CASH] = 10_000 - sum(
            value for key, value in canonical.items() if key != _CASH
        )
    return [
        {"key": key, "weight_bp": canonical[key]}
        for key in sorted(canonical)
    ]


def _scaled_price(raw: object, scale: object) -> Decimal | None:
    value = _optional_int(raw)
    denominator = _optional_int(scale)
    if value is None or denominator is None or value <= 0 or denominator <= 0:
        return None
    return Decimal(value) / Decimal(denominator)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("replay integer field must be integer or null")
    return value


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("replay datetime must be timezone-aware")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise TypeError("replay datetime must be text or null")
    return _parse_datetime(value)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: object) -> None:
    _atomic_write_text(path, json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n")


def _safe_reason(exc: BaseException) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ")[:500]


__all__ = [
    "AllocationOOSReplayInputBuildRequest",
    "AllocationOOSReplayInputBuildResult",
    "build_allocation_oos_replay_inputs",
]
