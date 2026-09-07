from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
)
from app_module.score_effectiveness_dtos import ScoreEffectivenessReport
from app_module.score_effectiveness_read_model import ScoreEffectivenessReadModel
from app_module.threshold_robustness_read_model import (
    ThresholdRobustnessReadModel,
    ThresholdRobustnessReport,
    sample_threshold_robustness_observations,
)


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="唯讀檢查 TotalScore 分數區間的 forward outcome 研究證據。")
    parser.add_argument("--sample", action="store_true", help="使用內建樣本，不讀取正式資料。")
    parser.add_argument("--db-path", type=Path, help="既有 evidence SQLite DB；會以唯讀模式開啟。")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="輸出格式。")
    parser.add_argument("--output", type=Path, help="選填輸出檔案路徑。")
    parser.add_argument("--min-sample-size", type=int, default=1, help="每個 bucket 的最小觀察樣本數。")
    parser.add_argument("--include-threshold-robustness", action="store_true", help="同時輸出唯讀固定門檻穩健性矩陣。")
    args = parser.parse_args(argv)

    if args.sample:
        events, outcomes = _sample_rows()
        source_mode = "sample_only"
    else:
        if args.db_path is None:
            parser.error("除非使用 --sample，否則必須提供 --db-path。")
        events, outcomes = _load_rows_from_db(args.db_path)
        source_mode = "read_only_sqlite"

    report = ScoreEffectivenessReadModel(
        events=events,
        outcomes=outcomes,
        source_mode=source_mode,
    ).build_report(min_sample_size=args.min_sample_size)
    threshold_report = None
    if args.include_threshold_robustness:
        threshold_report = ThresholdRobustnessReadModel(
            observations=sample_threshold_robustness_observations() if args.sample else (),
            min_sample_size=args.min_sample_size,
            source_mode=source_mode,
        ).build_report()
    rendered = (
        json.dumps(_build_payload(report, threshold_report), ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_score_effectiveness_markdown(report, threshold_report=threshold_report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def _build_payload(report: ScoreEffectivenessReport, threshold_report: ThresholdRobustnessReport | None) -> dict[str, Any]:
    payload = report.to_dict()
    if threshold_report is not None:
        payload["threshold_robustness"] = threshold_report.to_dict()
    return payload


def render_score_effectiveness_markdown(
    report: ScoreEffectivenessReport,
    *,
    threshold_report: ThresholdRobustnessReport | None = None,
) -> str:
    payload = report.to_dict()
    lines = [
        "# 分數有效性稽核",
        "",
        f"- 來源模式：`{payload['source_mode']}`",
        f"- 產生時間：`{payload['generated_at']}`",
        f"- 允許寫入：`{str(payload['access_boundary']['writes_allowed']).lower()}`",
        f"- 允許啟用正式排程：`{str(payload['access_boundary']['production_scheduler_allowed']).lower()}`",
        f"- 宣稱投資有效性：`{str(payload['access_boundary']['investment_effectiveness_claim']).lower()}`",
        "",
        "此報告僅為分數有效性研究證據，不是交易建議，也不代表任何策略已被證明有效。",
        "",
        "| 分數區間 | 樣本數 | 已成熟結果 | 等待中結果 | 缺失結果 | 前瞻報酬 bp | 大盤超額 bp | 成本後超額 bp | 95% 區間 | 勝率 bp | 限制 |",
        "|---|---:|---:|---:|---:|---|---|---|---|---|---|",
    ]
    for bucket in payload["buckets"]:
        lines.append(
            "| {bucket} | {sample_count} | {ready_outcome_count} | {pending_outcome_count} | "
            "{missing_outcome_count} | {forward_return_bp_by_horizon} | "
            "{benchmark_excess_bp_by_horizon} | {cost_adjusted_excess_bp_by_horizon} | "
            "{benchmark_excess_ci95_bp_by_horizon} | {win_rate_bp_by_horizon} | {limitations} |".format(
                bucket=bucket["bucket"],
                sample_count=bucket["sample_count"],
                ready_outcome_count=bucket["ready_outcome_count"],
                pending_outcome_count=bucket["pending_outcome_count"],
                missing_outcome_count=bucket["missing_outcome_count"],
                forward_return_bp_by_horizon=_format_horizon_map(bucket["forward_return_bp_by_horizon"]),
                benchmark_excess_bp_by_horizon=_format_horizon_map(bucket["benchmark_excess_bp_by_horizon"]),
                cost_adjusted_excess_bp_by_horizon=_format_horizon_map(bucket["cost_adjusted_excess_bp_by_horizon"]),
                benchmark_excess_ci95_bp_by_horizon=_format_ci_map(bucket["benchmark_excess_ci95_bp_by_horizon"]),
                win_rate_bp_by_horizon=_format_horizon_map(bucket["win_rate_bp_by_horizon"]),
                limitations="；".join(bucket["limitations"]) if bucket["limitations"] else "",
            )
        )
    lines.extend(["", "## 限制", ""])
    lines.extend(f"- {limitation}" for limitation in payload["limitations"])
    if payload["diagnostics"]:
        lines.extend(["", "## 診斷", ""])
        lines.extend(f"- {diagnostic}" for diagnostic in payload["diagnostics"])
    if threshold_report is not None:
        lines.extend(["", "## 固定門檻穩健性矩陣", ""])
        lines.extend(
            [
                "- 此矩陣僅供唯讀研究檢查，不 promote threshold，也不改推薦預設參數。",
                "",
                "| Buy | Sell | Confirm | Cooldown | Label | Ready | Benchmark excess bp |",
                "|---:|---:|---:|---:|---|---:|---:|",
            ]
        )
        for row in threshold_report.rows:
            benchmark_excess_bp = "" if row.benchmark_excess_bp is None else str(row.benchmark_excess_bp)
            lines.append(
                f"| {row.buy_score} | {row.sell_score} | {row.confirmation_days} | "
                f"{row.cooldown_days} | {row.label} | {row.ready_outcome_count} | {benchmark_excess_bp} |"
            )
    return "\n".join(lines)


def _format_horizon_map(values: dict[str, int]) -> str:
    if not values:
        return ""
    return "；".join(f"{horizon}日={value}" for horizon, value in values.items())


def _format_ci_map(values: dict[str, dict[str, int]]) -> str:
    if not values:
        return ""
    return "；".join(
        f"{horizon}日=[{item['lower_bp']},{item['upper_bp']}] (n={item['sample_count']})"
        for horizon, item in values.items()
    )


def _load_rows_from_db(db_path: Path) -> tuple[tuple[EvidenceEvent, ...], tuple[EvidenceOutcome, ...]]:
    if not db_path.exists():
        raise FileNotFoundError(f"找不到 evidence DB：{db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        events = tuple(_row_to_event(dict(row)) for row in conn.execute("SELECT * FROM evidence_events"))
        outcomes = tuple(_row_to_outcome(dict(row)) for row in conn.execute("SELECT * FROM evidence_outcomes"))
    return events, outcomes


def _row_to_event(row: dict[str, Any]) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=str(row["event_id"]),
        event_hash=str(row["event_hash"]),
        event_date=str(row["event_date"]),
        decision_date=str(row["decision_date"]),
        symbol=row["symbol"],
        event_type=str(row["event_type"]),
        event_family=str(row["event_family"]),
        source_type=str(row["source_type"]),
        source_id=str(row.get("source_id") or ""),
        source_snapshot_id=str(row.get("source_snapshot_id") or ""),
        strategy_version_id=str(row.get("strategy_version_id") or ""),
        profile_id=str(row.get("profile_id") or ""),
        run_id=str(row.get("run_id") or ""),
        reason_codes=tuple(json.loads(row.get("reason_codes_json") or "[]")),
        why_not_codes=tuple(json.loads(row.get("why_not_codes_json") or "[]")),
        risk_codes=tuple(json.loads(row.get("risk_codes_json") or "[]")),
        score_bp=row.get("score_bp"),
        score_percentile_bp=row.get("score_percentile_bp"),
        regime=row.get("regime"),
        sector=row.get("sector"),
        concept_basket=row.get("concept_basket"),
        liquidity_state=row.get("liquidity_state"),
        data_quality=str(row.get("data_quality") or EvidenceDataQuality.MISSING.value),
        warnings=tuple(json.loads(row.get("warnings_json") or "[]")),
        as_of_date=str(row.get("as_of_date") or ""),
        available_date=str(row.get("available_date") or ""),
        source_version=str(row.get("source_version") or ""),
        cost_model_id=str(row.get("cost_model_id") or ""),
        benchmark_id=row.get("benchmark_id"),
        industry_benchmark_id=row.get("industry_benchmark_id"),
        metadata=json.loads(row.get("metadata_json") or "{}"),
        created_at=str(row.get("created_at") or ""),
    )


def _row_to_outcome(row: dict[str, Any]) -> EvidenceOutcome:
    return EvidenceOutcome(
        outcome_id=str(row["outcome_id"]),
        event_id=str(row["event_id"]),
        window_days=int(row["window_days"]),
        window_type=str(row.get("window_type") or "trading_days"),
        return_basis=str(row.get("return_basis") or "close_to_close_event_date"),
        event_price_date=row.get("event_price_date"),
        event_close=row.get("event_close"),
        outcome_price_date=row.get("outcome_price_date"),
        outcome_close=row.get("outcome_close"),
        forward_return_bp=row.get("forward_return_bp"),
        benchmark_return_bp=row.get("benchmark_return_bp"),
        benchmark_excess_bp=row.get("benchmark_excess_bp"),
        industry_return_bp=row.get("industry_return_bp"),
        industry_excess_bp=row.get("industry_excess_bp"),
        max_adverse_excursion_bp=row.get("max_adverse_excursion_bp"),
        max_favorable_excursion_bp=row.get("max_favorable_excursion_bp"),
        outcome_status=str(row.get("outcome_status") or EvidenceOutcomeStatus.PENDING.value),
        data_quality=str(row.get("data_quality") or EvidenceDataQuality.MISSING.value),
        warnings=tuple(json.loads(row.get("warnings_json") or "[]")),
        calculated_at=str(row.get("calculated_at") or ""),
        data_as_of_date=row.get("data_as_of_date"),
        metadata=json.loads(row.get("metadata_json") or "{}"),
    )


def _sample_rows() -> tuple[tuple[EvidenceEvent, ...], tuple[EvidenceOutcome, ...]]:
    events = (
        _sample_event("sample-low", "1101", 3500),
        _sample_event("sample-neutral", "2330", 5550),
        _sample_event("sample-high", "2454", 8250),
    )
    outcomes = (
        _sample_outcome("sample-low", 5, EvidenceOutcomeStatus.READY, -120, -80, None, -220),
        _sample_outcome("sample-neutral", 5, EvidenceOutcomeStatus.READY, 60, 30, None, -50),
        _sample_outcome("sample-high", 5, EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA, None, None, None, None),
        _sample_outcome("sample-high", 10, EvidenceOutcomeStatus.MISSING_PRICE, None, None, None, None),
    )
    return events, outcomes


def _sample_event(event_id: str, symbol: str, score_bp: int) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        event_hash=f"hash-{event_id}",
        event_date="2026-01-02",
        decision_date="2026-01-02",
        symbol=symbol,
        event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
        event_family="recommendation",
        source_type="sample",
        score_bp=score_bp,
        data_quality=EvidenceDataQuality.OBSERVED,
        as_of_date="2026-01-02",
        available_date="2026-01-02",
    )


def _sample_outcome(
    event_id: str,
    horizon: int,
    status: EvidenceOutcomeStatus,
    forward_return_bp: int | None,
    benchmark_excess_bp: int | None,
    industry_excess_bp: int | None,
    max_adverse_excursion_bp: int | None,
) -> EvidenceOutcome:
    return EvidenceOutcome(
        outcome_id=f"out-{event_id}-{horizon}",
        event_id=event_id,
        window_days=horizon,
        forward_return_bp=forward_return_bp,
        benchmark_excess_bp=benchmark_excess_bp,
        industry_excess_bp=industry_excess_bp,
        max_adverse_excursion_bp=max_adverse_excursion_bp,
        outcome_status=status,
        data_quality=EvidenceDataQuality.OBSERVED,
    )


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
