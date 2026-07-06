from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_pipeline_runner import EvidencePipelineRunner
from app_module.evidence_pipeline_runner_dtos import EvidencePipelineRunRequest
from app_module.forward_performance_service import ForwardPerformanceService
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig


REPLAY_MODE_HISTORICAL = "historical_replay"
SOURCE_LABEL_SIMULATED_SCHEDULER = "simulated_scheduler"


@dataclass(frozen=True)
class HistoricalEvidenceReplayRequest:
    start_date: str
    end_date: str
    source_db_path: str | Path
    replay_db_path: str | Path
    sources: tuple[str, ...] = ("all",)
    windows: tuple[int, ...] = (5, 10, 20, 60)
    group_by: str = "event_type"
    window: int = 20
    min_sample_size: int = 10
    limit: int | None = None
    confirm: bool = False
    overwrite_replay_db: bool = False
    replay_mode: str = REPLAY_MODE_HISTORICAL
    source_label: str = SOURCE_LABEL_SIMULATED_SCHEDULER
    replay_run_id: str = field(default_factory=lambda: f"hre_{uuid4().hex[:12]}")


@dataclass(frozen=True)
class HistoricalEvidenceReplayDay:
    decision_date: str
    selected_recommendation_result_id: str | None
    sources: tuple[str, ...]
    events_seen: int
    events_inserted: int
    outcomes_created: int
    outcomes_updated: int
    outcomes_pending: int
    blocking_gaps: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sources"] = list(self.sources)
        payload["blocking_gaps"] = list(self.blocking_gaps)
        payload["diagnostics"] = list(self.diagnostics)
        return payload


@dataclass(frozen=True)
class HistoricalEvidenceReplayReport:
    replay_run_id: str
    replay_mode: str
    source_label: str
    start_date: str
    end_date: str
    source_db_path: str
    replay_db_path: str
    dry_run: bool
    confirm: bool
    days: tuple[HistoricalEvidenceReplayDay, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_run_id": self.replay_run_id,
            "replay_mode": self.replay_mode,
            "source_label": self.source_label,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "source_db_path": self.source_db_path,
            "replay_db_path": self.replay_db_path,
            "dry_run": self.dry_run,
            "confirm": self.confirm,
            "days": [day.to_dict() for day in self.days],
            "limitations": list(self.limitations),
            "totals": {
                "days": len(self.days),
                "events_seen": sum(day.events_seen for day in self.days),
                "events_inserted": sum(day.events_inserted for day in self.days),
                "outcomes_created": sum(day.outcomes_created for day in self.days),
                "outcomes_pending": sum(day.outcomes_pending for day in self.days),
            },
        }


class HistoricalEvidenceReplayService:
    """歷史 evidence replay；只面向 working-copy / replay DB。"""

    def __init__(self, config: TWStockConfig) -> None:
        self.config = config

    def run(self, request: HistoricalEvidenceReplayRequest) -> HistoricalEvidenceReplayReport:
        source_db = Path(request.source_db_path)
        replay_db = Path(request.replay_db_path)
        self._validate_paths(source_db, replay_db)
        self._prepare_replay_db(source_db, replay_db, overwrite=request.overwrite_replay_db)
        replay_config = self._replay_config(replay_db)
        trading_dates = self.discover_trading_dates(
            source_db_path=source_db,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        dry_run = not request.confirm
        days: list[HistoricalEvidenceReplayDay] = []
        for decision_date in trading_dates:
            selected_result_id = self._select_recommendation_result_id(decision_date)
            sources, diagnostics = self._sources_for_day(request.sources, selected_result_id)
            runner_summary = EvidencePipelineRunner(replay_config, db_path=replay_db).run(
                EvidencePipelineRunRequest(
                    decision_date=decision_date,
                    start_date=request.start_date,
                    end_date=decision_date,
                    db_path=str(replay_db),
                    sources=sources,
                    result_id=selected_result_id,
                    windows=request.windows,
                    group_by=request.group_by,
                    window=request.window,
                    min_sample_size=request.min_sample_size,
                    limit=request.limit,
                    dry_run=dry_run,
                    confirm=request.confirm,
                    skip_outcomes=True,
                    replay_context={
                        "replay_mode": request.replay_mode,
                        "source_label": request.source_label,
                        "replay_run_id": request.replay_run_id,
                        "replay_decision_date": decision_date,
                        "replay_data_as_of_date": decision_date,
                    },
                )
            )
            outcome_summary = ForwardPerformanceService(
                replay_config,
                EvidenceEventRepository(replay_config, db_path=replay_db),
            ).calculate(
                windows=request.windows,
                dry_run=dry_run,
                start_date=request.start_date,
                end_date=decision_date,
                limit=request.limit,
                data_as_of_date=decision_date,
            )
            days.append(
                HistoricalEvidenceReplayDay(
                    decision_date=decision_date,
                    selected_recommendation_result_id=selected_result_id,
                    sources=sources,
                    events_seen=runner_summary.events_seen,
                    events_inserted=runner_summary.events_inserted,
                    outcomes_created=outcome_summary.outcomes_created if request.confirm else 0,
                    outcomes_updated=outcome_summary.outcomes_updated if request.confirm else 0,
                    outcomes_pending=outcome_summary.pending_insufficient_future_data,
                    blocking_gaps=tuple(runner_summary.blocking_gaps),
                    diagnostics=tuple(
                        dict.fromkeys(
                            [
                                *diagnostics,
                                *runner_summary.diagnostic_codes,
                            ]
                        )
                    ),
                )
            )

        return HistoricalEvidenceReplayReport(
            replay_run_id=request.replay_run_id,
            replay_mode=request.replay_mode,
            source_label=request.source_label,
            start_date=_iso_date(request.start_date),
            end_date=_iso_date(request.end_date),
            source_db_path=str(source_db),
            replay_db_path=str(replay_db),
            dry_run=dry_run,
            confirm=request.confirm,
            days=tuple(days),
            limitations=(
                "Historical replay is research evidence only and does not replace real weekly or multi-day scheduler gates.",
                "Recommendation source uses only persisted results with created_at date not after the replay decision date.",
                "Forward outcomes are capped by replay_data_as_of_date so future prices are not visible early.",
                "Production scheduler remains separate and is not enabled by this replay.",
            ),
        )

    def discover_trading_dates(
        self,
        *,
        source_db_path: str | Path,
        start_date: str,
        end_date: str,
    ) -> tuple[str, ...]:
        source_db = Path(source_db_path)
        if not source_db.exists():
            raise FileNotFoundError(str(source_db))
        start_key = _date_key(start_date)
        end_key = _date_key(end_date)
        with sqlite3.connect(source_db) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT 日期
                FROM daily_prices
                WHERE REPLACE(REPLACE(日期, '-', ''), '/', '') >= ?
                  AND REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') ASC
                """,
                (start_key, end_key),
            ).fetchall()
        return tuple(_iso_date(row[0]) for row in rows)

    def _validate_paths(self, source_db: Path, replay_db: Path) -> None:
        if source_db.resolve() == replay_db.resolve():
            raise ValueError("replay DB must be separate from source DB")
        if not source_db.exists():
            raise FileNotFoundError(str(source_db))

    def _prepare_replay_db(self, source_db: Path, replay_db: Path, *, overwrite: bool) -> None:
        replay_db.parent.mkdir(parents=True, exist_ok=True)
        if replay_db.exists() and overwrite:
            replay_db.unlink()
        if not replay_db.exists():
            shutil.copy2(source_db, replay_db)

    def _replay_config(self, replay_db: Path) -> TWStockConfig:
        replay_config = TWStockConfig(data_root=self.config.data_root, output_root=self.config.output_root)
        replay_config.db_file = replay_db
        replay_config.sqlite_dir = replay_db.parent
        return replay_config

    def _select_recommendation_result_id(self, decision_date: str) -> str | None:
        decision_key = _date_key(decision_date)
        repository = RecommendationRepository(self.config)
        eligible: list[dict[str, Any]] = []
        for row in repository.list_results():
            created_at = str(row.get("created_at") or "")
            created_key = _date_key(created_at[:10])
            if created_key and created_key <= decision_key:
                eligible.append(row)
        if not eligible:
            return None
        latest = sorted(eligible, key=lambda row: str(row.get("created_at") or ""), reverse=True)[0]
        return str(latest.get("result_id") or "") or None

    def _sources_for_day(
        self,
        requested_sources: Iterable[str],
        selected_result_id: str | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        requested = tuple(source.strip() for source in requested_sources if str(source).strip())
        if not requested or "all" in requested:
            if selected_result_id:
                return (("all",), ())
            return (
                ("watchlist-trigger", "portfolio-alert", "risk-prompt"),
                ("recommendation_asof_result_missing",),
            )

        diagnostics: list[str] = []
        filtered: list[str] = []
        recommendation_sources = {"recommendation", "why-not", "liquidity-gate"}
        for source in requested:
            if source in recommendation_sources and not selected_result_id:
                diagnostics.append("recommendation_asof_result_missing")
                continue
            filtered.append(source)
        if not filtered:
            filtered = ["__no_capture_source__"]
        return (tuple(dict.fromkeys(filtered)), tuple(dict.fromkeys(diagnostics)))


def _date_key(value: Any) -> str:
    return str(value).strip()[:10].replace("-", "").replace("/", "")


def _iso_date(value: Any) -> str:
    key = _date_key(value)
    if len(key) == 8 and key.isdigit():
        return f"{key[:4]}-{key[4:6]}-{key[6:]}"
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return str(value)
