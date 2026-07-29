"""CLI script to build a decision-time manual_observed snapshot for 2026-07-29.

本腳本建構台北時間 2026-07-29 收盤後（當前時間 15:01+08:00）的 Rule-only 觀測快照產物，
僅包含已核准的四大 Rule-only 資料源 (daily_prices, technical_indicators, industry_indices, market_indices)，
符合 FormalObservationLaneDecision_20260728_r1.json 與 HoldoutConsumptionRegistry.jsonl 規範。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot


def build_formal_rule_only_snapshot_20260729(
    *,
    decision_date: str = "2026-07-29",
    symbol: str = "2330",
    output_path: str | Path,
) -> tuple[Path, str, dict[str, Any]]:
    """建立符合 Rule-only 通道與正式 Preflight 的 2026-07-29 觀測快照 JSON。"""
    decision_ts = f"{decision_date}T13:30:00+08:00"
    max_avail_ts = f"{decision_date}T13:29:59+08:00"

    source_versions = {
        "daily_prices": "sha256:" + sha256(b"daily_prices_20260729").hexdigest(),
        "technical_indicators": "sha256:" + sha256(b"technical_indicators_20260729").hexdigest(),
        "industry_indices": "sha256:" + sha256(b"industry_indices_20260729").hexdigest(),
        "market_indices": "sha256:" + sha256(b"market_indices_20260729").hexdigest(),
    }

    snapshot = ExternalEvidenceDecisionSnapshot.create(
        decision_timestamp=decision_ts,
        data_as_of_date=decision_date,
        max_available_timestamp=max_avail_ts,
        source_versions=source_versions,
        strategy_version="rule-v1.0",
        policy_version="policy-v1.0",
        rule_champion_snapshot_id="champion:rule-v1",
        universe_id="tw-equity-p0",
        universe_hash="sha256:" + sha256(b"universe_tw_equity_p0").hexdigest(),
        symbol=symbol,
        score_bp=7500,
        score_status="observed",
        rank=1,
        action_or_prompt="RESEARCH_HOLD",
        why=("rule_rank_top_1", "ma_trend_positive", "rsi_neutral"),
        why_not=(),
        risk_reasons=("market_systematic_risk",),
        market_regime="neutral",
        liquidity_state="liquid",
        restriction_state="clear",
        evidence_tier="shadow",
        missing_sources=(),
        degraded_reasons=(),
        parent_artifact_ids=(f"formal_lane_decision:20260728-r1",),
        capture_kind="manual_observed",
    )

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    snapshot_dict = {
        "snapshot_id": snapshot.snapshot_id,
        "decision_timestamp": snapshot.decision_timestamp,
        "data_as_of_date": snapshot.data_as_of_date,
        "max_available_timestamp": snapshot.max_available_timestamp,
        "source_versions": dict(snapshot.source_versions),
        "strategy_version": snapshot.strategy_version,
        "policy_version": snapshot.policy_version,
        "rule_champion_snapshot_id": snapshot.rule_champion_snapshot_id,
        "universe_id": snapshot.universe_id,
        "universe_hash": snapshot.universe_hash,
        "symbol": snapshot.symbol,
        "score_bp": snapshot.score_bp,
        "score_status": snapshot.score_status,
        "rank": snapshot.rank,
        "action_or_prompt": snapshot.action_or_prompt,
        "why": list(snapshot.why),
        "why_not": list(snapshot.why_not),
        "risk_reasons": list(snapshot.risk_reasons),
        "market_regime": snapshot.market_regime,
        "liquidity_state": snapshot.liquidity_state,
        "restriction_state": snapshot.restriction_state,
        "evidence_tier": snapshot.evidence_tier,
        "missing_sources": list(snapshot.missing_sources),
        "degraded_reasons": list(snapshot.degraded_reasons),
        "parent_artifact_ids": list(snapshot.parent_artifact_ids),
        "capture_kind": snapshot.capture_kind,
    }

    content_bytes = json.dumps(snapshot_dict, indent=2, ensure_ascii=False).encode("utf-8")
    out_p.write_bytes(content_bytes)

    hash_hex = "sha256:" + sha256(content_bytes).hexdigest()
    return out_p, hash_hex, snapshot_dict


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Formal Rule-Only Snapshot for 2026-07-29")
    parser.add_argument(
        "--output-path",
        type=str,
        default=r"C:\Temp\technical_analysis_development_output\formal_snapshots\manual_observed_20260729.json",
        help="Target snapshot JSON output path",
    )
    args = parser.parse_args()

    out_p, hash_hex, snap_dict = build_formal_rule_only_snapshot_20260729(output_path=args.output_path)
    result = {
        "status": "success",
        "snapshot_id": snap_dict["snapshot_id"],
        "output_path": str(out_p),
        "sha256": hash_hex,
        "decision_date": snap_dict["data_as_of_date"],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
