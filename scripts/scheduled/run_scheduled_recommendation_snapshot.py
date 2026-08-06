from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_module.dtos import RecommendationResultDTO
from app_module.recommendation_repository import RecommendationRepository
from app_module.recommendation_service import RecommendationService
from data_module.config import TWStockConfig
from scripts.scheduled.scheduled_clock import scheduled_now


TASK_NAME = "baldr-recommendation-snapshot-daily"


def _scheduled_default_config() -> dict[str, Any]:
    return {
        "technical": {
            "momentum": {
                "enabled": True,
                "rsi": {"enabled": True, "period": 14},
                "macd": {"enabled": True, "fast": 12, "slow": 26, "signal": 9},
                "kd": {"enabled": False},
            },
            "volatility": {
                "enabled": False,
                "bollinger": {"enabled": False, "window": 20, "std": 2},
                "atr": {"enabled": True, "period": 14},
            },
            "trend": {
                "enabled": True,
                "adx": {"enabled": True, "period": 14},
                "ma": {"enabled": True, "windows": [5, 10, 20, 60]},
            },
        },
        "patterns": {"selected": ["旗形", "三角形", "矩形", "V形反轉"]},
        "signals": {
            "technical_indicators": ["momentum", "trend"],
            "volume_conditions": ["increasing", "spike"],
            "weights": {"pattern": "0.25", "technical": "0.55", "volume": "0.20"},
        },
        "filters": {
            "price_change_min": "2.0",
            "price_change_max": "100.0",
            "volume_ratio_min": "1.5",
            "rsi_min": 0,
            "rsi_max": 100,
            "industry": "全部",
        },
        "recommendation_ranking": {"threshold_mode": "fixed"},
        "regime": None,
    }


def _runtime_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _runtime_config(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_runtime_config(child) for child in value]
    if isinstance(value, str):
        try:
            return float(Decimal(value))
        except Exception:  # noqa: BLE001
            return value
    return value


def _build_result_id(now: datetime) -> str:
    return f"scheduled_rec_{now.strftime('%Y%m%d_%H%M%S')}"


def _with_fixed_threshold_metadata(recommendations: list[Any]) -> list[Any]:
    return [
        replace(item, threshold_mode="fixed", ranking_method="fixed_threshold")
        for item in recommendations
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scheduled research-only recommendation snapshot wrapper.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--max-stocks", type=int, default=200)
    parser.add_argument("--top-n", type=int, default=50)
    return parser


def _payload_base(
    *,
    output_root: Path,
    decision_date: str,
    status_path: Path,
    log_path: Path,
    checked_at: str,
) -> dict[str, Any]:
    return {
        "task": TASK_NAME,
        "status": "running",
        "decision_date": decision_date,
        "checked_at": checked_at,
        "status_path": str(status_path),
        "log_path": str(log_path),
        "output_root": str(output_root),
        "confirm": False,
        "writes_recommendation_result": False,
        "writes_evidence_db": False,
        "auto_trading": False,
        "lifecycle_action": False,
    }


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root)
    run_root = output_root / "scheduled" / "recommendation_snapshot"
    run_root.mkdir(parents=True, exist_ok=True)

    now = scheduled_now()
    decision_date = now.date().isoformat()
    today_key = decision_date.replace("-", "")
    status_path = run_root / "latest_status.json"
    log_path = run_root / f"{today_key}_recommendation_snapshot.log"
    checked_at = now.isoformat(timespec="seconds")

    payload = _payload_base(
        output_root=output_root,
        decision_date=decision_date,
        status_path=status_path,
        log_path=log_path,
        checked_at=checked_at,
    )

    try:
        config = TWStockConfig(data_root=Path(args.data_root), output_root=output_root)
        recommendation_config = _scheduled_default_config()
        runtime_config = _runtime_config(recommendation_config)
        service = RecommendationService(config)
        recommendations = _with_fixed_threshold_metadata(service.run_recommendation(
            config=runtime_config,
            max_stocks=args.max_stocks,
            top_n=args.top_n,
        ))

        result_config = deepcopy(recommendation_config)
        result_config.update(
            {
                "scheduled_snapshot": True,
                "research_only": True,
                "decision_date": decision_date,
                "max_stocks": args.max_stocks,
                "top_n": args.top_n,
                "profile_id": "scheduled_daily_research_default_v1",
                "profile_name": "Scheduled daily research default v1",
                "look_ahead_check": "uses latest available data at scheduled run time only",
                "safety_boundary": {
                    "confirm": False,
                    "writes_evidence_db": False,
                    "auto_trading": False,
                    "lifecycle_action": False,
                },
            }
        )

        result = RecommendationResultDTO(
            result_id=_build_result_id(now),
            result_name=f"Scheduled recommendation snapshot {decision_date}",
            config=result_config,
            recommendations=recommendations,
            regime=str(runtime_config.get("regime") or ""),
            created_at=checked_at,
            notes="Research-only scheduled snapshot; not trading advice.",
            excluded_candidates_json=list(getattr(service, "last_excluded_candidates_json", [])),
            screening_matrix_json=list(getattr(service, "last_screening_matrix", [])),
            why_not_payload_json=list(getattr(service, "last_why_not_payload_json", [])),
            liquidity_gate_payload_json=list(getattr(service, "last_liquidity_gate_payload_json", [])),
            exclusion_quality=str(getattr(service, "last_exclusion_quality", "observed")),
            exclusion_warnings_json=list(getattr(service, "last_exclusion_warnings_json", [])),
        )

        repository = RecommendationRepository(config)
        result_id = repository.save_result(result)
        warnings = []
        if not recommendations:
            warnings.append("no_recommendations_returned")

        payload.update(
            {
                "status": "passed",
                "result_id": result_id,
                "result_name": result.result_name,
                "recommendations_count": len(recommendations),
                "screening_matrix_rows": len(result.screening_matrix_json),
                "excluded_candidates_rows": len(result.excluded_candidates_json),
                "why_not_payload_rows": len(result.why_not_payload_json),
                "liquidity_gate_payload_rows": len(result.liquidity_gate_payload_json),
                "exclusion_quality": result.exclusion_quality,
                "exclusion_warnings": list(result.exclusion_warnings_json),
                "warnings": warnings,
                "db_path": str(repository.db_path),
                "runs_dir": str(repository.runs_dir),
                "writes_recommendation_result": True,
                "writes_evidence_db": False,
                "auto_trading": False,
                "lifecycle_action": False,
                "confirm": False,
            }
        )
        log_path.write_text(
            "\n".join(
                [
                    f"status=passed",
                    f"decision_date={decision_date}",
                    f"result_id={result_id}",
                    f"recommendations_count={len(recommendations)}",
                    f"screening_matrix_rows={len(result.screening_matrix_json)}",
                    "writes_evidence_db=false",
                    "auto_trading=false",
                    "lifecycle_action=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        _write_status(status_path, payload)
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        payload.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "writes_recommendation_result": False,
                "writes_evidence_db": False,
                "auto_trading": False,
                "lifecycle_action": False,
                "confirm": False,
            }
        )
        log_path.write_text(f"status=failed\nerror_type={type(exc).__name__}\nerror={exc}\n", encoding="utf-8")
        _write_status(status_path, payload)
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
