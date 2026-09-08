"""獨立核對 bounded confirmatory comparison 的 equity、source 與共同 pool。

本檔只讀 comparison JSON、exposure receipt 與其綁定的 parent/store manifest，
不呼叫 comparison consumer，也不會開啟或改寫任何 model/source artifact。
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


_INITIAL_CAPITAL_MINOR = 50_000_000
_SHA256_PREFIX = "sha256:"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _round_bp(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


def _total_return_bp(equities: Sequence[int], initial: int) -> int:
    if initial <= 0:
        raise ValueError("initial equity must be positive")
    if not equities:
        return 0
    return _round_bp(
        (Decimal(equities[-1]) / Decimal(initial) - Decimal(1))
        * Decimal(10_000)
    )


def _maximum_drawdown_bp(equities: Sequence[int], initial: int) -> int:
    if initial <= 0:
        raise ValueError("initial equity must be positive")
    peak = initial
    maximum = Decimal(0)
    for equity in equities:
        if equity < 0:
            raise ValueError("closing equity must not be negative")
        peak = max(peak, equity)
        if peak <= 0:
            continue
        maximum = max(
            maximum,
            Decimal(peak - equity) / Decimal(peak) * Decimal(10_000),
        )
    return _round_bp(maximum)


def _close_return_bp(previous: int, current: int) -> int:
    if previous <= 0 or current < 0:
        raise ValueError("close equity must be non-negative with positive base")
    return _round_bp(
        (Decimal(current) / Decimal(previous) - Decimal(1)) * Decimal(10_000)
    )


def _verify_manifest(path: Path, expected_hash: str) -> dict[str, Any]:
    manifest = _read_object(path)
    actual_hash = manifest.get("manifest_hash")
    if not isinstance(actual_hash, str) or actual_hash != expected_hash:
        raise ValueError(f"manifest logical hash mismatch: {path}")
    body = deepcopy(manifest)
    body.pop("manifest_hash", None)
    if _payload_hash(body) != expected_hash:
        raise ValueError(f"manifest payload hash mismatch: {path}")
    return manifest


def _verify_exposure(
    path: Path,
    binding: Mapping[str, Any],
    *,
    expected_run_id: str,
) -> dict[str, Any]:
    exposure = _read_object(path)
    for field_name in (
        "schema_version",
        "run_id",
        "fold_id",
        "comparison_hash",
        "method_freeze_hash",
        "request_hash",
        "request_binding_hash",
        "runner_file_hash",
        "status",
        "source_read_attempted",
        "source_read_completed",
        "price_data_read",
        "label_data_read",
        "result_data_read",
        "formal_oos_allowed",
        "production_alpha_bp",
        "broker_order_allowed",
        "research_only",
        "source_readonly",
    ):
        if field_name not in exposure:
            raise ValueError(f"exposure field missing: {field_name}")
    if exposure["schema_version"] != (
        "allocation-base-expert-confirmatory-exposure.v1"
    ):
        raise ValueError("exposure schema mismatch")
    if exposure["run_id"] != expected_run_id:
        raise ValueError("exposure run identity mismatch")
    if exposure["fold_id"] != binding.get("fold_id"):
        raise ValueError("exposure fold identity mismatch")
    if exposure["comparison_hash"] != binding.get("comparison_hash"):
        raise ValueError("exposure comparison identity mismatch")
    if exposure["method_freeze_hash"] != binding.get("method_freeze_hash"):
        raise ValueError("exposure method identity mismatch")
    if exposure["request_hash"] != binding.get("request_hash"):
        raise ValueError("exposure request identity mismatch")
    if exposure["request_binding_hash"] != binding.get("binding_hash"):
        raise ValueError("exposure binding identity mismatch")
    if exposure["runner_file_hash"] != binding.get("runner_file_hash"):
        raise ValueError("exposure runner identity mismatch")
    if exposure["status"] != "source_read_completed_published":
        raise ValueError("confirmatory exposure did not publish")
    if exposure["source_read_attempted"] is not True or exposure[
        "source_read_completed"
    ] is not True:
        raise ValueError("confirmatory exposure source phase is incomplete")
    if any(
        exposure[field_name] is not True
        for field_name in (
            "price_data_read",
            "label_data_read",
            "result_data_read",
        )
    ):
        raise ValueError("confirmatory exposure source flags are incomplete")
    if (
        exposure["formal_oos_allowed"] is not False
        or exposure["production_alpha_bp"] != 0
        or exposure["broker_order_allowed"] is not False
        or exposure["research_only"] is not True
        or exposure["source_readonly"] is not True
    ):
        raise ValueError("confirmatory exposure safety flags changed")
    return exposure


def _execution_bar_missing_audit(
    comparison: Mapping[str, Any],
    *,
    store_manifest_path: Path,
) -> dict[str, Any]:
    occurrences: dict[tuple[str, str], list[str]] = {}
    daily = comparison.get("daily")
    if not isinstance(daily, list):
        raise TypeError("comparison daily rows are required")
    for day in daily:
        if not isinstance(day, Mapping):
            raise TypeError("daily row must be an object")
        decision_date = str(day["decision_date"])
        day_lanes = day.get("lanes")
        if not isinstance(day_lanes, Mapping):
            raise TypeError("daily lanes are required")
        for lane_id, lane in day_lanes.items():
            if not isinstance(lane, Mapping):
                raise TypeError("daily lane must be an object")
            lot_execution = lane.get("complete_lot_execution")
            if not isinstance(lot_execution, Mapping):
                continue
            symbols = lot_execution.get("symbols")
            if not isinstance(symbols, list):
                continue
            for symbol_record in symbols:
                if not isinstance(symbol_record, Mapping):
                    continue
                reasons = symbol_record.get("reasons")
                if not isinstance(reasons, list) or not any(
                    "execution_bar_missing" in str(reason)
                    for reason in reasons
                ):
                    continue
                key = (decision_date, str(symbol_record["symbol"]))
                occurrences.setdefault(key, []).append(str(lane_id))

    entries: list[dict[str, Any]] = []
    for (decision_date, symbol), lane_ids in sorted(occurrences.items()):
        year = decision_date[:4]
        source_path = store_manifest_path.parent / f"year={year}" / "replay_source.sqlite"
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        connection = sqlite3.connect(
            f"file:{source_path.as_posix()}?mode=ro",
            uri=True,
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            row = connection.execute(
                "SELECT decision_at, decision_date, symbol, sector_id, "
                "price_event_at, price_available_at, open_int, open_scale, "
                "close_int, close_scale, volume_shares, "
                "median_volume_20d_shares, source_values_hash "
                "FROM replay_source WHERE decision_date=? AND symbol=?",
                (decision_date, symbol),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError(
                f"missing execution bar row is absent from source: {decision_date}/{symbol}"
            )
        (
            source_decision_at,
            source_decision_date,
            source_symbol,
            sector_id,
            price_event_at,
            price_available_at,
            open_int,
            open_scale,
            close_int,
            close_scale,
            volume_shares,
            median_volume,
            source_values_hash,
        ) = row
        if source_decision_date != decision_date or source_symbol != symbol:
            raise ValueError("execution bar source identity mismatch")
        missing_components = [
            field_name
            for field_name, value in (
                ("open_int", open_int),
                ("open_scale", open_scale),
                ("close_int", close_int),
                ("close_scale", close_scale),
            )
            if value is None
        ]
        entries.append(
            {
                "decision_date": decision_date,
                "decision_at": source_decision_at,
                "symbol": symbol,
                "affected_lane_count": len(lane_ids),
                "affected_lane_ids": sorted(lane_ids),
                "source_sqlite_path": str(source_path),
                "source_sqlite_sha256": _file_hash(source_path),
                "source_contract": "replay_source.open_close_integer_components",
                "missing_bar_components": missing_components,
                "source_row": {
                    "decision_at": source_decision_at,
                    "decision_date": source_decision_date,
                    "symbol": source_symbol,
                    "sector_id": sector_id,
                    "price_event_at": price_event_at,
                    "price_available_at": price_available_at,
                    "open_int": open_int,
                    "open_scale": open_scale,
                    "close_int": close_int,
                    "close_scale": close_scale,
                    "volume_shares": volume_shares,
                    "median_volume_20d_shares": median_volume,
                    "source_values_hash": source_values_hash,
                },
            }
        )
    return {
        "occurrence_count": sum(len(item) for item in occurrences.values()),
        "distinct_date_symbol_count": len(entries),
        "entries": entries,
        "status": "source_components_identified" if entries else "none",
    }


def audit_result(
    comparison_path: Path,
    *,
    stable_exposure_path: Path,
) -> dict[str, Any]:
    comparison_path = comparison_path.resolve()
    comparison = _read_object(comparison_path)
    comparison_hash = comparison.get("comparison_hash")
    if not isinstance(comparison_hash, str):
        raise ValueError("comparison hash is missing")
    body = deepcopy(comparison)
    body.pop("comparison_hash", None)
    logical_hash = _payload_hash(body)
    if logical_hash != comparison_hash:
        raise ValueError("comparison logical hash mismatch")

    binding = comparison.get("confirmatory_binding")
    if not isinstance(binding, Mapping):
        raise TypeError("confirmatory binding is missing")
    scope = comparison.get("confirmatory_scope")
    if not isinstance(scope, Mapping):
        raise TypeError("confirmatory scope is missing")
    if (
        comparison.get("schema_version")
        != "allocation-base-expert-confirmatory-comparison.v1"
        or comparison.get("status") != "complete_confirmatory_research"
        or comparison.get("fold_id") != "fold-005"
        or comparison.get("horizon") != 5
        or comparison.get("algorithms") != ["ridge_logistic"]
    ):
        raise ValueError("confirmatory comparison identity is invalid")
    if any(
        scope.get(field_name) is not True
        for field_name in ("price_data_read", "label_data_read", "result_data_read")
    ):
        raise ValueError("comparison source read flags are incomplete")
    if (
        comparison.get("formal_oos_allowed") is not False
        or comparison.get("production_alpha_bp") != 0
        or comparison.get("broker_order_allowed") is not False
        or comparison.get("research_only") is not True
        or comparison.get("source_readonly") is not True
        or comparison.get("future_confirmatory_scopes") != []
    ):
        raise ValueError("comparison safety flags changed")

    parent_path = Path(str(binding["parent_training_manifest_path"]))
    store_path = Path(str(binding["parent_store_manifest_path"]))
    parent = _verify_manifest(parent_path, str(binding["parent_training_manifest_hash"]))
    store = _verify_manifest(store_path, str(binding["parent_store_manifest_hash"]))
    store_file_hash = _file_hash(store_path)
    if store_file_hash != binding["parent_store_manifest_file_hash"]:
        raise ValueError("parent store file hash mismatch")
    if parent.get("store_manifest_hash") != binding["parent_store_manifest_hash"]:
        raise ValueError("parent/store lineage mismatch")
    if parent.get("store_manifest_file_hash") != store_file_hash:
        raise ValueError("parent/store file lineage mismatch")
    execution_bar_missing = _execution_bar_missing_audit(
        comparison,
        store_manifest_path=store_path,
    )

    daily = comparison.get("daily")
    lanes = comparison.get("lanes")
    if not isinstance(daily, list) or not isinstance(lanes, list):
        raise TypeError("comparison daily/lanes must be arrays")
    lane_ids = [str(item["lane_id"]) for item in lanes if isinstance(item, Mapping)]
    if len(lane_ids) != len(lanes) or len(set(lane_ids)) != len(lane_ids):
        raise ValueError("lane summaries are not unique")
    if not daily:
        raise ValueError("comparison has no daily rows")
    dates = [str(item["decision_date"]) for item in daily]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("daily decision dates are not ordered and unique")

    pool_by_date: dict[str, tuple[str, ...]] = {}
    for day in daily:
        if not isinstance(day, Mapping):
            raise TypeError("daily row must be an object")
        date_key = str(day["decision_date"])
        pool = day.get("liquidity_pool")
        day_lanes = day.get("lanes")
        if not isinstance(pool, Mapping) or not isinstance(day_lanes, Mapping):
            raise TypeError("daily pool/lanes must be objects")
        selected = pool.get("selected")
        if not isinstance(selected, list):
            raise TypeError("daily selected pool must be an array")
        pool_symbols = tuple(str(item["symbol"]) for item in selected)
        if _required_int(pool.get("selected_count"), "selected_count") != len(
            pool_symbols
        ):
            raise ValueError("daily pool selected count mismatch")
        pool_by_date[date_key] = pool_symbols
        if set(day_lanes) != set(lane_ids):
            raise ValueError("daily lane scope differs from lane summaries")
        for lane_id in lane_ids:
            lane_day = day_lanes[lane_id]
            if not isinstance(lane_day, Mapping):
                raise TypeError("daily lane must be an object")
            if tuple(lane_day.get("investment_pool_symbols", ())) != pool_symbols:
                raise ValueError("lane investment pool differs on a decision date")

    universe = comparison.get("universe")
    if not isinstance(universe, Mapping):
        raise TypeError("universe is missing")
    if universe.get("all_lanes_same_investment_pool") is not True or universe.get(
        "all_lanes_same_scope"
    ) is not True:
        raise ValueError("universe does not bind one pool for all lanes")
    if universe.get("liquidity_pool_nonempty_decision_date_count") != len(daily):
        raise ValueError("nonempty pool day count mismatch")
    if universe.get("liquidity_pool_empty_decision_date_count") != 0:
        raise ValueError("unexpected empty pool day")
    if universe.get("liquidity_pool_selected_row_count") != sum(
        len(symbols) for symbols in pool_by_date.values()
    ):
        raise ValueError("selected pool row count mismatch")
    pool_hash = universe.get("investment_pool_scope_hash")
    if not isinstance(pool_hash, str):
        raise ValueError("investment pool scope hash is missing")

    lane_audits: list[dict[str, Any]] = []
    for summary in lanes:
        if not isinstance(summary, Mapping):
            raise TypeError("lane summary must be an object")
        lane_id = str(summary["lane_id"])
        records = [
            day["lanes"][lane_id]  # type: ignore[index]
            for day in daily
        ]
        net_equities = [
            _required_int(record["net_closing_equity_minor"], "net equity")
            for record in records
        ]
        gross_equities = [
            _required_int(
                record["gross_closing_equity_cost_addback_estimate_minor"],
                "gross equity",
            )
            for record in records
        ]
        costs = [
            _required_int(record["transaction_cost_minor"], "transaction cost")
            for record in records
        ]
        if any(
            gross != net + sum(costs[: index + 1])
            for index, (gross, net) in enumerate(zip(gross_equities, net_equities))
        ):
            raise ValueError(f"gross/net cost addback mismatch: {lane_id}")
        previous_net = _INITIAL_CAPITAL_MINOR
        previous_gross = _INITIAL_CAPITAL_MINOR
        for record, net, gross in zip(records, net_equities, gross_equities):
            if record["net_return_bp"] != _close_return_bp(previous_net, net):
                raise ValueError(f"daily net return mismatch: {lane_id}")
            if record["gross_return_bp"] != _close_return_bp(previous_gross, gross):
                raise ValueError(f"daily gross return mismatch: {lane_id}")
            previous_net = net
            previous_gross = gross

        sums = {
            "requested_order_count": sum(
                _required_int(record["requested_order_count"], "requested orders")
                for record in records
            ),
            "executed_trade_count": sum(
                _required_int(record["executed_trade_count"], "executed trades")
                for record in records
            ),
            "unfilled_order_count": sum(
                _required_int(record["unfilled_order_count"], "unfilled orders")
                for record in records
            ),
            "blocked_order_count": sum(
                _required_int(record["blocked_order_count"], "blocked orders")
                for record in records
            ),
            "transaction_cost_minor_total": sum(costs),
            "turnover_total_bp": sum(
                _required_int(record["turnover_bp"], "turnover") for record in records
            ),
        }
        for field_name, value in sums.items():
            if summary.get(field_name) != value:
                raise ValueError(f"lane aggregate mismatch: {lane_id}/{field_name}")
        expected = {
            "daily_sample_count": len(net_equities),
            "final_net_closing_equity_minor": net_equities[-1],
            "final_gross_closing_equity_cost_addback_estimate_minor": gross_equities[-1],
            "net_total_return_bp": _total_return_bp(net_equities, _INITIAL_CAPITAL_MINOR),
            "gross_total_return_bp": _total_return_bp(gross_equities, _INITIAL_CAPITAL_MINOR),
            "net_max_drawdown_bp": _maximum_drawdown_bp(net_equities, _INITIAL_CAPITAL_MINOR),
            "gross_max_drawdown_bp": _maximum_drawdown_bp(gross_equities, _INITIAL_CAPITAL_MINOR),
            "investment_pool_scope_hash": pool_hash,
        }
        mismatches = {
            field_name: {"reported": summary.get(field_name), "expected": value}
            for field_name, value in expected.items()
            if summary.get(field_name) != value
        }
        if mismatches:
            raise ValueError(f"lane performance mismatch: {lane_id}: {mismatches}")
        lane_audits.append(
            {
                "lane_id": lane_id,
                "scenario": summary.get("scenario"),
                "execution_status": summary.get("execution_status"),
                "execution_status_reason": summary.get("execution_status_reason"),
                "decision_date_count": len(daily),
                "executed_trade_count": sums["executed_trade_count"],
                "requested_order_count": sums["requested_order_count"],
                "unfilled_order_count": sums["unfilled_order_count"],
                "transaction_cost_minor_total": sums["transaction_cost_minor_total"],
                "turnover_total_bp": sums["turnover_total_bp"],
                "net_total_return_bp": expected["net_total_return_bp"],
                "net_max_drawdown_bp": expected["net_max_drawdown_bp"],
                "gross_total_return_bp": expected["gross_total_return_bp"],
                "gross_max_drawdown_bp": expected["gross_max_drawdown_bp"],
                "final_net_closing_equity_minor": expected[
                    "final_net_closing_equity_minor"
                ],
                "common_pool_verified": True,
            }
        )

    output_run_dir = comparison_path.parent
    exposure_paths = [
        output_run_dir / "confirmatory_exposure_outcome.json",
        stable_exposure_path.resolve(),
    ]
    expected_run_id = str(comparison["run_id"])
    exposures = [
        _verify_exposure(
            path,
            binding,
            expected_run_id=expected_run_id,
        )
        for path in exposure_paths
    ]
    if exposures[0] != exposures[1]:
        raise ValueError("local/stable exposure receipts differ")

    return {
        "schema_version": "allocation-base-expert-confirmatory-independent-audit.v1",
        "status": "independent_audit_passed",
        "comparison_path": str(comparison_path),
        "comparison_file_bytes": comparison_path.stat().st_size,
        "comparison_file_sha256": _file_hash(comparison_path),
        "comparison_logical_hash": logical_hash,
        "run_id": comparison.get("run_id"),
        "fold_id": comparison.get("fold_id"),
        "horizon": comparison.get("horizon"),
        "selected_oof_row_count": comparison.get("selected_oof_row_count"),
        "decision_dates": {
            "count": len(daily),
            "start": dates[0],
            "end": dates[-1],
        },
        "initial_capital_minor": _INITIAL_CAPITAL_MINOR,
        "currency": comparison.get("performance_capital", {}).get("currency"),
        "source_lineage": {
            "parent_training_manifest_path": str(parent_path),
            "parent_training_manifest_hash": binding.get("parent_training_manifest_hash"),
            "parent_store_manifest_path": str(store_path),
            "parent_store_manifest_hash": binding.get("parent_store_manifest_hash"),
            "parent_store_manifest_file_hash": store_file_hash,
            "dataset_identity_hash": comparison.get("dataset_identity_hash"),
            "source_readonly": comparison.get("source_readonly"),
            "meta_targets_read": comparison.get("meta_targets_read"),
            "teacher_targets_read": comparison.get("teacher_targets_read"),
        },
        "exposure": {
            "status": exposures[0]["status"],
            "started_before_outcome": True,
            "source_read_attempted": exposures[0]["source_read_attempted"],
            "source_read_completed": exposures[0]["source_read_completed"],
            "price_data_read": exposures[0]["price_data_read"],
            "label_data_read": exposures[0]["label_data_read"],
            "result_data_read": exposures[0]["result_data_read"],
            "local_receipt_path": str(exposure_paths[0]),
            "stable_receipt_path": str(exposure_paths[1]),
            "local_receipt_sha256": _file_hash(exposure_paths[0]),
            "stable_receipt_sha256": _file_hash(exposure_paths[1]),
        },
        "pool": {
            "policy_version": universe.get("liquidity_pool_policy_version"),
            "scope_hash": pool_hash,
            "all_lanes_same_investment_pool": True,
            "decision_dates_with_pool": len(pool_by_date),
            "empty_decision_dates": 0,
            "selected_row_count": sum(len(symbols) for symbols in pool_by_date.values()),
            "pool_size_by_date": sorted({len(symbols) for symbols in pool_by_date.values()}),
        },
        "execution_bar_missing": execution_bar_missing,
        "lane_audits": lane_audits,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--stable-exposure", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    audit = audit_result(
        args.comparison,
        stable_exposure_path=args.stable_exposure,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
