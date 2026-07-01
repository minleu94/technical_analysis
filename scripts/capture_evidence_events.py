from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_capture_service import EvidenceCaptureService
from app_module.evidence_event_importer_dtos import EvidenceCaptureRequest
from app_module.evidence_event_importers import (
    MissingSnapshotEvidenceImporter,
    PortfolioAlertEvidenceImporter,
    RecommendationEvidenceImporter,
    RiskPromptEvidenceImporter,
    WatchlistTriggerEvidenceImporter,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture evidence events from persisted or DTO sources.")
    parser.add_argument(
        "--source",
        choices=("recommendation", "watchlist-trigger", "portfolio-alert", "risk-prompt", "all"),
        required=True,
    )
    parser.add_argument("--decision-date")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--result-id")
    parser.add_argument("--symbol")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run. This is also the default.")
    parser.add_argument("--confirm", action="store_true", help="Write events. Without this flag no DB write occurs.")
    parser.add_argument("--db-path")
    parser.add_argument("--json-output", action="store_true", help="Emit JSON summary. JSON is the default output.")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    if args.db_path:
        config.db_file = Path(args.db_path)
        config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


class _DecisionDeskSnapshotSectionProvider:
    def __init__(self, stored_snapshot, section_name: str) -> None:
        self.stored_snapshot = stored_snapshot
        self.section_name = section_name
        self.snapshot_id = stored_snapshot.snapshot_id
        self.metadata = {
            "decision_desk_snapshot_id": stored_snapshot.snapshot_id,
            "decision_desk_snapshot_hash": stored_snapshot.snapshot_hash,
            "decision_desk_snapshot_source": "durable_snapshot",
        }

    def build_snapshot(self, as_of_date):
        snapshot = self.stored_snapshot.to_decision_desk_snapshot()
        if self.section_name == "watchlist-trigger":
            return snapshot.watchlist_triggers
        if self.section_name == "portfolio-alert":
            return snapshot.portfolio_alerts
        if self.section_name == "risk-prompt":
            return snapshot.risk_prompts
        raise ValueError(f"unsupported decision desk snapshot section: {self.section_name}")


def _decision_date_for_snapshot(args: argparse.Namespace) -> str:
    if args.decision_date:
        return str(args.decision_date)[:10]
    return date.today().isoformat()


def _decision_desk_importers(config: TWStockConfig, decision_date: str):
    repository = DecisionDeskSnapshotRepository(config)
    stored = repository.latest_before_or_on(decision_date) if decision_date else None
    if stored is None:
        reason = "durable decision desk snapshot not found; run capture_decision_desk_snapshot.py first"
        return {
            "watchlist-trigger": MissingSnapshotEvidenceImporter("watchlist-trigger", reason),
            "portfolio-alert": MissingSnapshotEvidenceImporter("portfolio-alert", reason),
            "risk-prompt": MissingSnapshotEvidenceImporter("risk-prompt", reason),
        }
    return {
        "watchlist-trigger": WatchlistTriggerEvidenceImporter(
            _DecisionDeskSnapshotSectionProvider(stored, "watchlist-trigger")
        ),
        "portfolio-alert": PortfolioAlertEvidenceImporter(
            _DecisionDeskSnapshotSectionProvider(stored, "portfolio-alert")
        ),
        "risk-prompt": RiskPromptEvidenceImporter(
            _DecisionDeskSnapshotSectionProvider(stored, "risk-prompt")
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)

    repository = EvidenceEventRepository(config)
    event_service = EvidenceEventService(repository)
    recommendation_repository = RecommendationRepository(config)
    ddd_importers = _decision_desk_importers(config, _decision_date_for_snapshot(args))
    capture_service = EvidenceCaptureService(
        event_service,
        {
            "recommendation": RecommendationEvidenceImporter(recommendation_repository),
            **ddd_importers,
        },
    )
    request = EvidenceCaptureRequest(
        source=args.source,
        decision_date=args.decision_date,
        start_date=args.start_date,
        end_date=args.end_date,
        result_id=args.result_id,
        symbol=args.symbol,
        limit=args.limit,
        dry_run=(args.dry_run or not args.confirm),
        confirm=bool(args.confirm),
    )
    summary = capture_service.capture(request)
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
