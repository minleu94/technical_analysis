from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
from statistics import median
from typing import Any, Iterable

from app_module.live_research_gap_dtos import LiveResearchGapObservation, LiveResearchGapSummary
from app_module.research_run_dtos import canonical_json


SUPPORTED_LIVE_GAP_GROUP_BY = (
    "source_type",
    "strategy_version_id",
    "event_type",
    "regime_at_entry",
    "regime_current",
    "portfolio_mode",
    "attribution_category",
    "data_quality",
)


class LiveResearchGapRepository:
    """Append-only/idempotent repository for research gap observations."""

    def __init__(self, config: Any, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS live_research_gap_observations (
                    gap_id TEXT PRIMARY KEY,
                    gap_hash TEXT NOT NULL UNIQUE,
                    observation_date TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    portfolio_mode TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    research_run_id TEXT NOT NULL DEFAULT '',
                    strategy_version_id TEXT NOT NULL DEFAULT '',
                    recommendation_result_id TEXT NOT NULL DEFAULT '',
                    evidence_event_id TEXT NOT NULL DEFAULT '',
                    evidence_outcome_id TEXT NOT NULL DEFAULT '',
                    entry_date TEXT NOT NULL DEFAULT '',
                    entry_price TEXT NOT NULL DEFAULT '',
                    current_price_date TEXT NOT NULL DEFAULT '',
                    current_price TEXT NOT NULL DEFAULT '',
                    holding_days INTEGER,
                    portfolio_return_bp INTEGER,
                    research_expected_return_bp INTEGER,
                    forward_evidence_return_bp INTEGER,
                    benchmark_excess_bp INTEGER,
                    industry_excess_bp INTEGER,
                    gap_vs_research_bp INTEGER,
                    gap_vs_forward_evidence_bp INTEGER,
                    gap_vs_benchmark_bp INTEGER,
                    condition_status TEXT NOT NULL DEFAULT '',
                    chip_risk_level TEXT NOT NULL DEFAULT '',
                    regime_at_entry TEXT NOT NULL DEFAULT '',
                    regime_current TEXT NOT NULL DEFAULT '',
                    data_quality TEXT NOT NULL DEFAULT 'missing',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    attribution_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_gap_observation_date
                ON live_research_gap_observations(observation_date, symbol)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_live_gap_source
                ON live_research_gap_observations(source_type, source_id)
                """
            )

    def save_observation(self, observation: LiveResearchGapObservation) -> LiveResearchGapObservation:
        existing = self.get_by_hash(observation.gap_hash)
        if existing is not None:
            return existing
        row = self._observation_to_row(observation)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO live_research_gap_observations ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        saved = self.get_observation(observation.gap_id)
        if saved is None:
            raise RuntimeError(f"live research gap observation not found after insert: {observation.gap_id}")
        return saved

    def get_observation(self, gap_id: str) -> LiveResearchGapObservation | None:
        return self._fetch_one("gap_id = ?", (gap_id,))

    def get_by_hash(self, gap_hash: str) -> LiveResearchGapObservation | None:
        return self._fetch_one("gap_hash = ?", (gap_hash,))

    def list_observations(
        self,
        *,
        observation_date: str | None = None,
        symbol: str | None = None,
        source_type: str | None = None,
        strategy_version_id: str | None = None,
        limit: int | None = None,
    ) -> list[LiveResearchGapObservation]:
        where: list[str] = []
        params: list[Any] = []
        if observation_date:
            where.append("observation_date = ?")
            params.append(observation_date)
        if symbol:
            where.append("symbol = ?")
            params.append(symbol)
        if source_type:
            where.append("source_type = ?")
            params.append(source_type)
        if strategy_version_id:
            where.append("strategy_version_id = ?")
            params.append(strategy_version_id)
        sql = "SELECT * FROM live_research_gap_observations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY observation_date ASC, gap_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return self._fetch_many(sql, tuple(params))

    def summarize_live_research_gaps(
        self,
        *,
        group_by: str = "source_type",
        min_sample_size: int = 1,
    ) -> list[LiveResearchGapSummary]:
        if group_by not in SUPPORTED_LIVE_GAP_GROUP_BY:
            raise ValueError(f"unsupported group_by: {group_by}")
        observations = self.list_observations()
        grouped: dict[str, list[LiveResearchGapObservation]] = defaultdict(list)
        for observation in observations:
            for key in self._group_keys(observation, group_by):
                grouped[key].append(observation)
        return [
            self._build_summary(group_by, key, rows, min_sample_size)
            for key, rows in sorted(grouped.items())
        ]

    def _fetch_one(self, where: str, params: tuple[Any, ...]) -> LiveResearchGapObservation | None:
        rows = self._fetch_many(f"SELECT * FROM live_research_gap_observations WHERE {where} LIMIT 1", params)
        return rows[0] if rows else None

    def _fetch_many(self, sql: str, params: tuple[Any, ...]) -> list[LiveResearchGapObservation]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_observation(dict(row)) for row in rows]

    def _observation_to_row(self, observation: LiveResearchGapObservation) -> dict[str, Any]:
        row = observation.to_dict()
        row["warnings_json"] = canonical_json(observation.warnings_json)
        row["attribution_json"] = canonical_json(observation.attribution_json)
        row["metadata_json"] = canonical_json(observation.metadata_json)
        if not row["created_at"]:
            row.pop("created_at")
        return row

    def _row_to_observation(self, row: dict[str, Any]) -> LiveResearchGapObservation:
        return LiveResearchGapObservation(
            gap_id=str(row["gap_id"]),
            gap_hash=str(row["gap_hash"]),
            observation_date=str(row["observation_date"]),
            position_id=str(row["position_id"]),
            symbol=str(row["symbol"]),
            portfolio_mode=str(row["portfolio_mode"]),
            source_type=str(row["source_type"]),
            source_id=str(row["source_id"]),
            research_run_id=str(row["research_run_id"]),
            strategy_version_id=str(row["strategy_version_id"]),
            recommendation_result_id=str(row["recommendation_result_id"]),
            evidence_event_id=str(row["evidence_event_id"]),
            evidence_outcome_id=str(row["evidence_outcome_id"]),
            entry_date=str(row["entry_date"]),
            entry_price=str(row["entry_price"]),
            current_price_date=str(row["current_price_date"]),
            current_price=str(row["current_price"]),
            holding_days=row["holding_days"],
            portfolio_return_bp=row["portfolio_return_bp"],
            research_expected_return_bp=row["research_expected_return_bp"],
            forward_evidence_return_bp=row["forward_evidence_return_bp"],
            benchmark_excess_bp=row["benchmark_excess_bp"],
            industry_excess_bp=row["industry_excess_bp"],
            gap_vs_research_bp=row["gap_vs_research_bp"],
            gap_vs_forward_evidence_bp=row["gap_vs_forward_evidence_bp"],
            gap_vs_benchmark_bp=row["gap_vs_benchmark_bp"],
            condition_status=str(row["condition_status"]),
            chip_risk_level=str(row["chip_risk_level"]),
            regime_at_entry=str(row["regime_at_entry"]),
            regime_current=str(row["regime_current"]),
            data_quality=str(row["data_quality"]),
            warnings_json=json.loads(row["warnings_json"] or "[]"),
            attribution_json=json.loads(row["attribution_json"] or "[]"),
            metadata_json=json.loads(row["metadata_json"] or "{}"),
            created_at=str(row["created_at"]),
        )

    def _build_summary(
        self,
        group_by: str,
        key: str,
        rows: list[LiveResearchGapObservation],
        min_sample_size: int,
    ) -> LiveResearchGapSummary:
        warning_counts: Counter[str] = Counter()
        quality_counts = Counter(row.data_quality for row in rows)
        for row in rows:
            warning_counts.update(str(item) for item in row.warnings_json)
        missing_source = sum(1 for row in rows if not row.source_id or not row.source_type)
        missing_evidence = sum(1 for row in rows if not row.evidence_event_id or not row.evidence_outcome_id)
        gap_forward_values = [row.gap_vs_forward_evidence_bp for row in rows if row.gap_vs_forward_evidence_bp is not None]
        status = self._summary_status(rows, min_sample_size, missing_source, missing_evidence)
        return LiveResearchGapSummary(
            group_by=group_by,
            group_key=key,
            sample_size=len(rows),
            mean_portfolio_return_bp=self._mean(row.portfolio_return_bp for row in rows),
            median_portfolio_return_bp=self._median(row.portfolio_return_bp for row in rows),
            mean_gap_vs_research_bp=self._mean(row.gap_vs_research_bp for row in rows),
            mean_gap_vs_forward_evidence_bp=self._mean(gap_forward_values),
            mean_gap_vs_benchmark_bp=self._mean(row.gap_vs_benchmark_bp for row in rows),
            positive_gap_rate_bp=self._rate(sum(1 for value in gap_forward_values if value and value > 0), len(gap_forward_values)),
            negative_gap_rate_bp=self._rate(sum(1 for value in gap_forward_values if value and value < 0), len(gap_forward_values)),
            missing_source_trace_count=missing_source,
            missing_evidence_count=missing_evidence,
            quality_counts=dict(sorted(quality_counts.items())),
            warning_counts=dict(sorted(warning_counts.items())),
            summary_status=status,
        )

    def _group_keys(self, observation: LiveResearchGapObservation, group_by: str) -> list[str]:
        if group_by == "attribution_category":
            categories = [
                str(item.get("category"))
                for item in observation.attribution_json
                if isinstance(item, dict) and item.get("category")
            ]
            return categories or ["missing"]
        if group_by == "event_type":
            return [str(observation.metadata_json.get("event_type") or "missing")]
        value = getattr(observation, group_by)
        return [str(value) if value not in (None, "") else "missing"]

    @staticmethod
    def _summary_status(
        rows: list[LiveResearchGapObservation],
        min_sample_size: int,
        missing_source: int,
        missing_evidence: int,
    ) -> str:
        if len(rows) < min_sample_size:
            return "INSUFFICIENT_SAMPLE"
        if missing_source:
            return "MISSING_SOURCE_TRACE"
        if missing_evidence:
            return "MISSING_EVIDENCE"
        if any(row.data_quality in {"missing", "degraded"} or row.warnings_json for row in rows):
            return "DEGRADED"
        return "READY"

    @staticmethod
    def _mean(values: Iterable[int | None]) -> int | None:
        clean = [int(value) for value in values if value is not None]
        if not clean:
            return None
        return int(round(sum(clean) / len(clean)))

    @staticmethod
    def _median(values: Iterable[int | None]) -> int | None:
        clean = [int(value) for value in values if value is not None]
        if not clean:
            return None
        return int(round(median(clean)))

    @staticmethod
    def _rate(success: int, total: int) -> int | None:
        if total <= 0:
            return None
        return int(round(success * 10000 / total))
