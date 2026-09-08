"""由 immutable replay source 重建跨年 causal volume window 的研究 sidecar。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence


CAUSAL_VOLUME_SIDECAR_POLICY_VERSION = "causal-volume20-cross-year-carry.v1"
_SHA256_PREFIX = "sha256:"
_WINDOW_SIZE = 20


@dataclass(frozen=True)
class CausalVolumeTarget:
    """待重建的 selected row identity；只包含決策時已知的 row 欄位。"""

    year_ordinal: int
    local_row_index: int
    symbol: str
    decision_at: datetime
    stored_median_volume_20d_shares: int | None


@dataclass(frozen=True)
class CausalVolumeValue:
    """單一 selected row 的 sidecar median 與 parity 證據。"""

    derived_median_volume_20d_shares: int | None
    observation_count: int
    stored_median_volume_20d_shares: int | None
    same_year_stored_median_matches: bool | None
    recovered_from_missing_stored_median: bool


@dataclass(frozen=True)
class CausalVolumeSidecarResult:
    values: Mapping[tuple[int, int], CausalVolumeValue]
    evidence: Mapping[str, Any]


def reconstruct_causal_volume20(
    *,
    source_paths: Sequence[tuple[int, Path]],
    targets: Sequence[CausalVolumeTarget],
    require_same_year_parity: bool = True,
) -> CausalVolumeSidecarResult:
    """重建每個 symbol 的最近 20 個 distinct price events median。

    source 年份可跨年提供；每一筆 observation 只會在其自身
    decision_at 已到達後加入該 symbol window，且 volume 必須存在且非負、
    price_event_at 可解析且不晚於決策時間。因此不需要改寫 Direct parent，
    也不會用未來資料填補當時的 median。stored median 存在時會逐 row 做
    parity；若 parity 不一致，預設 fail closed。price_available_at 缺值時
    沿用已存在的 event-time 可得性契約，以 price_event_at 作為 fallback。
    """

    if not source_paths:
        raise ValueError("causal volume sidecar requires source paths")
    if not targets:
        return CausalVolumeSidecarResult(
            values={},
            evidence=_empty_evidence(),
        )
    target_by_key = {
        (item.year_ordinal, item.local_row_index): item for item in targets
    }
    if len(target_by_key) != len(targets):
        raise ValueError("causal volume sidecar target keys are duplicated")
    symbols = tuple(sorted({item.symbol for item in targets}))
    max_decision_at = max(item.decision_at for item in targets)
    histories: dict[str, deque[int]] = {}
    seen_events: dict[str, set[str]] = {}
    values: dict[tuple[int, int], CausalVolumeValue] = {}
    source_hasher = hashlib.sha256()
    rows_read = 0
    rows_eligible = 0
    skipped_invalid_datetime = 0
    source_years: list[int] = []

    for year_ordinal, source_path in sorted(source_paths):
        path = source_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        source_years.append(int(year_ordinal))
        connection = _readonly_sqlite(path)
        try:
            placeholders = ",".join("?" for _ in symbols)
            cursor = connection.execute(
                f"""
                SELECT local_row_index, decision_at, decision_date, symbol,
                       price_event_at, price_available_at, volume_shares,
                       median_volume_20d_shares, source_values_hash
                FROM replay_source
                WHERE symbol IN ({placeholders})
                  AND decision_date <= ?
                """,
                (*symbols, max_decision_at.date().isoformat()),
            )
            source_rows: list[tuple[Any, ...]] = [
                tuple(row) for row in cursor.fetchall()
            ]
        finally:
            connection.close()
        source_rows.sort(
            key=lambda row: (
                _parse_datetime_or_max(row[1]),
                int(year_ordinal),
                int(row[0]),
            )
        )
        for row in source_rows:
            rows_read += 1
            (
                local_row_index,
                decision_at_text,
                _decision_date_text,
                symbol,
                price_event_at_text,
                price_available_at_text,
                volume_shares,
                stored_median,
                source_values_hash,
            ) = row
            if not isinstance(symbol, str) or symbol not in symbols:
                continue
            decision_at = _parse_datetime_or_none(decision_at_text)
            if decision_at is None:
                skipped_invalid_datetime += 1
                continue
            key = (int(year_ordinal), int(local_row_index))
            target = target_by_key.get(key)
            if target is not None and (
                target.symbol != symbol or target.decision_at != decision_at
            ):
                raise ValueError(
                    "causal volume sidecar target identity mismatch: "
                    f"{key}"
                )
            if decision_at > max_decision_at:
                continue
            event_at = _parse_datetime_or_none(price_event_at_text)
            if event_at is None or event_at >= decision_at:
                continue
            available_at = _parse_datetime_or_none(price_available_at_text)
            if available_at is not None and available_at >= decision_at:
                continue
            try:
                volume = int(volume_shares)
            except (TypeError, ValueError):
                continue
            if volume < 0:
                continue
            event_key = str(price_event_at_text)
            symbol_history = histories.setdefault(symbol, deque(maxlen=_WINDOW_SIZE))
            symbol_events = seen_events.setdefault(symbol, set())
            is_new_event = event_key not in symbol_events
            if is_new_event:
                symbol_events.add(event_key)
                symbol_history.append(volume)
                rows_eligible += 1
                source_hasher.update(
                    _canonical_json(
                        {
                            "year_ordinal": int(year_ordinal),
                            "local_row_index": int(local_row_index),
                            "symbol": symbol,
                            "decision_at": decision_at.isoformat(),
                            "price_event_at": event_key,
                            "volume_shares": volume,
                            "source_values_hash": source_values_hash,
                        }
                    ).encode("utf-8")
                )
            if target is None:
                continue
            median = _median_lower_pair(symbol_history)
            stored_value = _optional_nonnegative_int(stored_median)
            parity = (
                None
                if stored_value is None or median is None
                else stored_value == median
            )
            values[key] = CausalVolumeValue(
                derived_median_volume_20d_shares=median,
                observation_count=len(symbol_history),
                stored_median_volume_20d_shares=stored_value,
                same_year_stored_median_matches=parity,
                recovered_from_missing_stored_median=(
                    stored_value is None and median is not None
                ),
            )

    # Selected rows with no valid source observation remain explicitly missing;
    # this is a data-quality outcome, never an implicit zero or fallback.
    for key, target in target_by_key.items():
        if key in values:
            continue
        stored_value = _optional_nonnegative_int(
            target.stored_median_volume_20d_shares
        )
        values[key] = CausalVolumeValue(
            derived_median_volume_20d_shares=None,
            observation_count=0,
            stored_median_volume_20d_shares=stored_value,
            same_year_stored_median_matches=(
                None if stored_value is None else False
            ),
            recovered_from_missing_stored_median=False,
        )

    parity_values = [
        item.same_year_stored_median_matches
        for item in values.values()
        if item.stored_median_volume_20d_shares is not None
    ]
    parity_mismatches = sum(value is False for value in parity_values)
    if require_same_year_parity and parity_mismatches:
        raise ValueError(
            "causal volume sidecar stored median parity mismatch: "
            f"{parity_mismatches} selected rows"
        )
    evidence = {
        "policy_version": CAUSAL_VOLUME_SIDECAR_POLICY_VERSION,
        "window_size_distinct_price_events": _WINDOW_SIZE,
        "algorithm": (
            "source rows sorted by decision_at; per symbol distinct "
            "price_event_at; append nonnegative volume then lower-pair median"
        ),
        "price_available_at_missing_policy": (
            "use_price_event_at_as_available_time"
        ),
        "source_year_ordinals": source_years,
        "source_scope_hash": _SHA256_PREFIX + source_hasher.hexdigest(),
        "source_rows_read": rows_read,
        "eligible_distinct_event_rows": rows_eligible,
        "skipped_invalid_decision_at_rows": skipped_invalid_datetime,
        "selected_row_count": len(targets),
        "derived_observed_row_count": sum(
            item.derived_median_volume_20d_shares is not None
            for item in values.values()
        ),
        "derived_missing_row_count": sum(
            item.derived_median_volume_20d_shares is None
            for item in values.values()
        ),
        "stored_median_observed_row_count": sum(
            item.stored_median_volume_20d_shares is not None
            for item in values.values()
        ),
        "same_year_parity_checked_row_count": len(parity_values),
        "same_year_parity_match_row_count": sum(
            value is True for value in parity_values
        ),
        "same_year_parity_mismatch_row_count": parity_mismatches,
        "cross_year_recovered_row_count": sum(
            item.recovered_from_missing_stored_median
            for item in values.values()
        ),
        "max_decision_at": max_decision_at.isoformat(),
        "read_only": True,
    }
    return CausalVolumeSidecarResult(values=values, evidence=evidence)


def _empty_evidence() -> dict[str, Any]:
    return {
        "policy_version": CAUSAL_VOLUME_SIDECAR_POLICY_VERSION,
        "window_size_distinct_price_events": _WINDOW_SIZE,
        "selected_row_count": 0,
        "derived_observed_row_count": 0,
        "derived_missing_row_count": 0,
        "stored_median_observed_row_count": 0,
        "same_year_parity_checked_row_count": 0,
        "same_year_parity_match_row_count": 0,
        "same_year_parity_mismatch_row_count": 0,
        "cross_year_recovered_row_count": 0,
        "source_scope_hash": _SHA256_PREFIX + hashlib.sha256(b"").hexdigest(),
        "read_only": True,
    }


def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _parse_datetime_or_none(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        return None
    return result


def _parse_datetime_or_max(value: object) -> datetime:
    parsed = _parse_datetime_or_none(value)
    if parsed is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    return parsed


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        try:
            result = int(value)
        except ValueError:
            return None
    else:
        return None
    return result if result >= 0 else None


def _median_lower_pair(history: Iterable[int]) -> int | None:
    values = sorted(int(value) for value in history if int(value) >= 0)
    if len(values) < _WINDOW_SIZE:
        return None
    return (values[9] + values[10]) // 2


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "CAUSAL_VOLUME_SIDECAR_POLICY_VERSION",
    "CausalVolumeSidecarResult",
    "CausalVolumeTarget",
    "CausalVolumeValue",
    "reconstruct_causal_volume20",
]
