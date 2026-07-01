from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from app_module.dtos.portfolio_dtos import PositionDTO
from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
    normalize_data_quality,
    normalize_event_type,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.live_research_gap_dtos import (
    LiveResearchGapAttribution,
    LiveResearchGapObservation,
    LiveResearchGapSaveResult,
)
from app_module.live_research_gap_repository import LiveResearchGapRepository
from app_module.portfolio_service import PortfolioService
from app_module.research_run_dtos import canonical_json


class PortfolioPositionProvider(Protocol):
    def list_positions(self, portfolio_id: str = "default") -> Sequence[PositionDTO]: ...


class LiveResearchGapService:
    """Build research_gap_observation records without mutating portfolio or strategy state."""

    def __init__(
        self,
        config: Any,
        *,
        repository: LiveResearchGapRepository | None = None,
        evidence_repository: EvidenceEventRepository | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or LiveResearchGapRepository(config)
        self.evidence_repository = evidence_repository or EvidenceEventRepository(config)

    def build_gap_for_position(
        self,
        position: PositionDTO,
        *,
        observation_date: str,
        condition_result: Any | None = None,
        chip_risk_level: str = "",
    ) -> LiveResearchGapObservation:
        source_summary = dict(position.source_summary or {})
        trace = self._source_trace(position, source_summary)
        event, outcome, match_metadata, match_warnings = self._match_evidence(position, trace, observation_date)
        current_price = self._decimal(position.current_price)
        entry_price = self._decimal(position.average_cost)
        portfolio_return_bp = self._return_bp(entry_price, current_price)
        expected_return_bp = self._first_int(
            source_summary,
            "research_expected_return_bp",
            "expected_return_bp",
            "return_bp",
            "total_return_bp",
        )
        forward_return_bp = outcome.forward_return_bp if outcome is not None else None
        benchmark_excess_bp = outcome.benchmark_excess_bp if outcome is not None else None
        industry_excess_bp = outcome.industry_excess_bp if outcome is not None else None
        entry_regime = self._entry_regime(source_summary, event, condition_result)
        current_regime = self._current_regime(source_summary, condition_result)
        warnings = list(match_warnings)
        data_quality = self._data_quality(event, outcome, source_summary, warnings)
        attributions = self._attributions(
            position=position,
            source_summary=source_summary,
            event=event,
            outcome=outcome,
            portfolio_return_bp=portfolio_return_bp,
            expected_return_bp=expected_return_bp,
            forward_return_bp=forward_return_bp,
            benchmark_excess_bp=benchmark_excess_bp,
            entry_regime=entry_regime,
            current_regime=current_regime,
            data_quality=data_quality,
            match_metadata=match_metadata,
        )
        warnings.extend(self._warnings_from_attributions(attributions))
        observation_payload: dict[str, Any] = {
            "observation_date": observation_date,
            "position_id": position.position_id,
            "symbol": position.stock_code,
            "portfolio_mode": self._portfolio_mode(source_summary),
            "source_type": position.source_type,
            "source_id": position.source_id,
            "research_run_id": trace["research_run_id"],
            "strategy_version_id": trace["strategy_version_id"],
            "recommendation_result_id": trace["recommendation_result_id"],
            "evidence_event_id": event.event_id if event is not None and match_metadata["match_confidence"] == "high" else "",
            "evidence_outcome_id": outcome.outcome_id if outcome is not None and match_metadata["match_confidence"] == "high" else "",
            "entry_date": position.opened_at,
            "entry_price": self._format_decimal(entry_price),
            "current_price_date": observation_date if current_price is not None else "",
            "current_price": self._format_decimal(current_price),
            "holding_days": self._holding_days(position.opened_at, observation_date),
            "portfolio_return_bp": portfolio_return_bp,
            "research_expected_return_bp": expected_return_bp,
            "forward_evidence_return_bp": forward_return_bp if match_metadata["match_confidence"] == "high" else None,
            "benchmark_excess_bp": benchmark_excess_bp if match_metadata["match_confidence"] == "high" else None,
            "industry_excess_bp": industry_excess_bp if match_metadata["match_confidence"] == "high" else None,
            "gap_vs_research_bp": self._diff(portfolio_return_bp, expected_return_bp),
            "gap_vs_forward_evidence_bp": self._diff(portfolio_return_bp, forward_return_bp)
            if match_metadata["match_confidence"] == "high"
            else None,
            "gap_vs_benchmark_bp": self._diff(portfolio_return_bp, benchmark_excess_bp)
            if match_metadata["match_confidence"] == "high"
            else None,
            "condition_status": str(getattr(condition_result, "status", "") or ""),
            "chip_risk_level": chip_risk_level or str(source_summary.get("chip_risk_level") or ""),
            "regime_at_entry": entry_regime,
            "regime_current": current_regime,
            "data_quality": data_quality,
            "warnings_json": sorted(set(str(item) for item in warnings if item)),
            "attribution_json": [item.to_dict() for item in attributions],
            "metadata_json": {
                **match_metadata,
                "event_type": normalize_event_type(event.event_type).value if event is not None else "",
                "return_basis": outcome.return_basis if outcome is not None else "",
                "research_gap_observation": True,
            },
        }
        gap_hash = self.build_gap_hash(observation_payload)
        return LiveResearchGapObservation(
            gap_id=f"gap_{gap_hash.split(':', 1)[1][:16]}",
            gap_hash=gap_hash,
            **observation_payload,
        )

    def build_gaps_for_portfolio(
        self,
        *,
        observation_date: str,
        portfolio_id: str = "default",
        portfolio_provider: PortfolioPositionProvider | None = None,
        symbol: str | None = None,
        strategy_version_id: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
    ) -> list[LiveResearchGapObservation]:
        provider = portfolio_provider or PortfolioService(self.config)
        positions = list(provider.list_positions(portfolio_id))
        if symbol:
            positions = [position for position in positions if position.stock_code == symbol]
        if strategy_version_id:
            positions = [
                position
                for position in positions
                if str(position.source_summary.get("strategy_version_id") or "") == strategy_version_id
            ]
        if source_type:
            positions = [position for position in positions if position.source_type == source_type]
        if limit is not None:
            positions = positions[: int(limit)]
        return [
            self.build_gap_for_position(position, observation_date=observation_date)
            for position in positions
        ]

    def save_gap_observation(
        self,
        observation: LiveResearchGapObservation,
        *,
        confirm: bool,
    ) -> LiveResearchGapSaveResult:
        if not confirm:
            return LiveResearchGapSaveResult(observation=observation, saved=False)
        existing = self.repository.get_by_hash(observation.gap_hash)
        saved = self.repository.save_observation(observation)
        return LiveResearchGapSaveResult(
            observation=saved,
            saved=existing is None,
            skipped_duplicate=existing is not None,
        )

    def list_gap_observations(self, **filters: Any) -> list[LiveResearchGapObservation]:
        return self.repository.list_observations(**filters)

    def summarize_gaps(self, *, group_by: str = "source_type", min_sample_size: int = 1):
        return self.repository.summarize_live_research_gaps(group_by=group_by, min_sample_size=min_sample_size)

    def capture_gaps(
        self,
        *,
        observation_date: str,
        confirm: bool,
        portfolio_id: str = "default",
        symbol: str | None = None,
        strategy_version_id: str | None = None,
        source_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        observations = self.build_gaps_for_portfolio(
            observation_date=observation_date,
            portfolio_id=portfolio_id,
            symbol=symbol,
            strategy_version_id=strategy_version_id,
            source_type=source_type,
            limit=limit,
        )
        results = [self.save_gap_observation(item, confirm=confirm) for item in observations]
        return self._capture_summary(observations, results, confirm=confirm)

    def build_gap_hash(self, payload: Mapping[str, Any]) -> str:
        digest = hashlib.sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _source_trace(self, position: PositionDTO, source_summary: Mapping[str, Any]) -> dict[str, str]:
        source_type = str(position.source_type or "")
        source_id = str(position.source_id or "")
        research_run_id = str(source_summary.get("research_run_id") or source_summary.get("run_id") or "")
        recommendation_result_id = str(
            source_summary.get("recommendation_result_id") or source_summary.get("result_id") or ""
        )
        if source_type in {"research_run", "backtest_run"} and source_id:
            research_run_id = research_run_id or source_id
        if source_type in {"recommendation", "recommendation_result"} and source_id:
            recommendation_result_id = recommendation_result_id or source_id
        return {
            "source_type": source_type,
            "source_id": source_id,
            "research_run_id": research_run_id,
            "strategy_version_id": str(source_summary.get("strategy_version_id") or source_summary.get("strategy_version") or ""),
            "recommendation_result_id": recommendation_result_id,
            "evidence_event_id": str(source_summary.get("evidence_event_id") or source_summary.get("event_id") or ""),
            "evidence_outcome_id": str(source_summary.get("evidence_outcome_id") or source_summary.get("outcome_id") or ""),
        }

    def _match_evidence(
        self,
        position: PositionDTO,
        trace: Mapping[str, str],
        observation_date: str,
    ) -> tuple[EvidenceEvent | None, EvidenceOutcome | None, dict[str, Any], list[str]]:
        warnings: list[str] = []
        if trace["evidence_event_id"]:
            event = self.evidence_repository.get_event(trace["evidence_event_id"])
            if event is not None:
                return event, self._matched_outcome(event, trace["evidence_outcome_id"]), {
                    "match_confidence": "high",
                    "match_policy": "explicit_evidence_event_id",
                    "candidate_evidence_event_ids": [],
                }, warnings

        events = self.evidence_repository.list_events(symbol=position.stock_code, end_date=observation_date)
        exact = [
            event
            for event in events
            if trace["source_id"]
            and event.source_id == trace["source_id"]
            and (not trace["source_type"] or event.source_type == trace["source_type"])
        ]
        if exact:
            event = exact[-1]
            return event, self._matched_outcome(event, trace["evidence_outcome_id"]), {
                "match_confidence": "high",
                "match_policy": "explicit_source_trace",
                "candidate_evidence_event_ids": [],
            }, warnings

        candidates = [
            event.event_id
            for event in events
            if event.symbol == position.stock_code and event.event_date == position.opened_at
        ]
        if candidates:
            warnings.append("fuzzy_match_candidate_only")
        return None, None, {
            "match_confidence": "low" if candidates else "none",
            "match_policy": "symbol_date_candidate_only" if candidates else "no_match",
            "candidate_evidence_event_ids": candidates,
        }, warnings

    def _matched_outcome(self, event: EvidenceEvent, preferred_outcome_id: str = "") -> EvidenceOutcome | None:
        outcomes = self.evidence_repository.list_outcomes(event_id=event.event_id)
        if preferred_outcome_id:
            for outcome in outcomes:
                if outcome.outcome_id == preferred_outcome_id:
                    return outcome
        ready = [outcome for outcome in outcomes if outcome.outcome_status == EvidenceOutcomeStatus.READY]
        return sorted(ready or outcomes, key=lambda item: item.window_days)[0] if outcomes else None

    def _attributions(
        self,
        *,
        position: PositionDTO,
        source_summary: Mapping[str, Any],
        event: EvidenceEvent | None,
        outcome: EvidenceOutcome | None,
        portfolio_return_bp: int | None,
        expected_return_bp: int | None,
        forward_return_bp: int | None,
        benchmark_excess_bp: int | None,
        entry_regime: str,
        current_regime: str,
        data_quality: str,
        match_metadata: Mapping[str, Any],
    ) -> list[LiveResearchGapAttribution]:
        items: list[LiveResearchGapAttribution] = []
        if not position.source_type or not position.source_id:
            items.append(LiveResearchGapAttribution("source_trace_gap", "medium", "position source trace is incomplete"))
        if outcome is None or match_metadata.get("match_confidence") != "high":
            items.append(LiveResearchGapAttribution("insufficient_evidence", "medium", "confirmed evidence outcome is unavailable"))
        if entry_regime and current_regime and entry_regime != current_regime:
            items.append(
                LiveResearchGapAttribution(
                    "market_regime_gap",
                    "medium",
                    "current regime differs from entry regime",
                    {"entry_regime": entry_regime, "current_regime": current_regime},
                )
            )
        liquidity_state = str((event.liquidity_state if event else "") or source_summary.get("liquidity_state") or "").lower()
        if liquidity_state in {"low", "degraded", "illiquid", "missing"}:
            items.append(LiveResearchGapAttribution("liquidity_gap", "medium", "liquidity state requires review"))
        if data_quality in {"missing", "degraded"}:
            items.append(LiveResearchGapAttribution("data_quality_gap", "medium", "data quality is not fully observed"))
        expected_price = self._first_decimal(source_summary, "price", "close_price", "entry_price")
        average_cost = self._decimal(position.average_cost)
        entry_gap = self._return_bp(expected_price, average_cost)
        if entry_gap is not None and entry_gap != 0:
            items.append(
                LiveResearchGapAttribution(
                    "execution_gap",
                    "medium",
                    "entry price differs from research source price",
                    {"entry_price_gap_bp": entry_gap},
                )
            )
        if (
            portfolio_return_bp is not None
            and (
                (forward_return_bp is not None and portfolio_return_bp < forward_return_bp)
                or (benchmark_excess_bp is not None and portfolio_return_bp < benchmark_excess_bp)
                or (expected_return_bp is not None and portfolio_return_bp < expected_return_bp)
            )
        ):
            items.append(LiveResearchGapAttribution("signal_gap", "low", "portfolio return is below one saved reference"))
        return items or [LiveResearchGapAttribution("insufficient_evidence", "low", "no strong attribution available")]

    def _data_quality(
        self,
        event: EvidenceEvent | None,
        outcome: EvidenceOutcome | None,
        source_summary: Mapping[str, Any],
        warnings: list[str],
    ) -> str:
        quality_values = [
            str(source_summary.get("data_quality") or source_summary.get("quality") or "").lower(),
            normalize_data_quality(event.data_quality).value if event is not None else "",
            normalize_data_quality(outcome.data_quality).value if outcome is not None else "",
        ]
        if any(value == EvidenceDataQuality.MISSING.value for value in quality_values) or not event or not outcome:
            return "missing"
        if warnings or any(value in {"degraded", "estimated", "unavailable"} for value in quality_values):
            return "degraded"
        return "observed"

    def _warnings_from_attributions(self, attributions: Sequence[LiveResearchGapAttribution]) -> list[str]:
        mapping = {
            "source_trace_gap": "source_trace_missing",
            "insufficient_evidence": "evidence_outcome_missing",
            "data_quality_gap": "data_quality_degraded",
            "liquidity_gap": "liquidity_state_degraded",
        }
        return [mapping[item.category] for item in attributions if item.category in mapping]

    def _portfolio_mode(self, source_summary: Mapping[str, Any]) -> str:
        mode = str(source_summary.get("portfolio_mode") or source_summary.get("account_mode") or "").lower()
        if mode in {"real", "real_if_recorded"} and source_summary.get("real_trade_recorded"):
            return "real"
        if mode in {"simulated", "paper"}:
            return "simulated"
        return "unknown"

    def _entry_regime(self, source_summary: Mapping[str, Any], event: EvidenceEvent | None, condition_result: Any | None) -> str:
        return str(
            source_summary.get("entry_regime")
            or source_summary.get("regime")
            or getattr(condition_result, "entry_regime", "")
            or (event.regime if event is not None else "")
            or ""
        )

    def _current_regime(self, source_summary: Mapping[str, Any], condition_result: Any | None) -> str:
        return str(source_summary.get("current_regime") or getattr(condition_result, "current_regime", "") or "")

    def _capture_summary(
        self,
        observations: Sequence[LiveResearchGapObservation],
        results: Sequence[LiveResearchGapSaveResult],
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        attribution_counts: Counter[str] = Counter()
        quality_counts = Counter(row.data_quality for row in observations)
        mode_counts = Counter(row.portfolio_mode for row in observations)
        warnings_count = 0
        for row in observations:
            warnings_count += len(row.warnings_json)
            attribution_counts.update(
                str(item.get("category"))
                for item in row.attribution_json
                if isinstance(item, dict) and item.get("category")
            )
        return {
            "positions_seen": len(observations),
            "positions_linked": sum(1 for row in observations if row.evidence_event_id),
            "gap_observations_created": sum(1 for result in results if result.saved),
            "gap_observations_skipped_duplicate": sum(1 for result in results if result.skipped_duplicate),
            "missing_source_trace": sum(1 for row in observations if not row.source_type or not row.source_id),
            "missing_research_run": sum(1 for row in observations if not row.research_run_id),
            "missing_evidence_event": sum(1 for row in observations if not row.evidence_event_id),
            "missing_evidence_outcome": sum(1 for row in observations if not row.evidence_outcome_id),
            "portfolio_mode_counts": dict(sorted(mode_counts.items())),
            "attribution_counts": dict(sorted(attribution_counts.items())),
            "data_quality_counts": dict(sorted(quality_counts.items())),
            "warnings_count": warnings_count,
            "dry_run": not confirm,
        }

    def _first_int(self, source: Mapping[str, Any], *keys: str) -> int | None:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                try:
                    return int(Decimal(str(value)).to_integral_value())
                except (InvalidOperation, ValueError):
                    continue
        return None

    def _first_decimal(self, source: Mapping[str, Any], *keys: str) -> Decimal | None:
        for key in keys:
            parsed = self._decimal(source.get(key))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _format_decimal(value: Decimal | None) -> str:
        if value is None:
            return ""
        return format(value.quantize(Decimal("0.01")), "f")

    @staticmethod
    def _return_bp(start: Decimal | None, end: Decimal | None) -> int | None:
        if start is None or end is None or start <= 0:
            return None
        return int(((end - start) / start * Decimal("10000")).to_integral_value())

    @staticmethod
    def _diff(left: int | None, right: int | None) -> int | None:
        if left is None or right is None:
            return None
        return int(left) - int(right)

    @staticmethod
    def _holding_days(entry_date: str, observation_date: str) -> int | None:
        try:
            return (date.fromisoformat(observation_date) - date.fromisoformat(entry_date)).days
        except ValueError:
            return None

    @staticmethod
    def to_jsonable_observations(observations: Iterable[LiveResearchGapObservation]) -> list[dict[str, Any]]:
        return [asdict(item) for item in observations]


def is_production_like_db(config: Any, db_path: str | Path | None) -> bool:
    if db_path is None:
        return True
    candidate = Path(db_path).resolve()
    configured = Path(config.db_file).resolve()
    return candidate == configured and "pytest" not in str(candidate).lower() and "tmp" not in str(candidate).lower()
