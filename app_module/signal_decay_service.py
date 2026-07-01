from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from app_module.evidence_event_dtos import EvidenceEvent, EvidenceOutcome, EvidenceOutcomeStatus
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.live_research_gap_repository import LiveResearchGapRepository
from app_module.live_research_gap_service import is_production_like_db
from app_module.research_run_dtos import canonical_json
from app_module.signal_decay_dtos import (
    DECAY_STATUS_DECAYING,
    DECAY_STATUS_INSUFFICIENT_SAMPLE,
    DECAY_STATUS_NO_DATA,
    DECAY_STATUS_SEVERE_DECAY,
    DECAY_STATUS_STABLE,
    DECAY_STATUS_WATCH,
    SUGGESTION_DEMOTE_CANDIDATE,
    SUGGESTION_HOLD,
    SUGGESTION_NONE,
    SUGGESTION_RETIRE_CANDIDATE,
    SUGGESTION_WATCH,
    SignalDecayObservation,
    SignalDecaySaveResult,
)
from app_module.signal_decay_repository import SignalDecayRepository


SUPPORTED_SIGNAL_DECAY_SCOPES = ("event_type", "event_family", "strategy_version", "profile")


class SignalDecayLifecycleEvidenceAdapter:
    """Builds proposed lifecycle evidence payloads without applying actions."""

    def build_payload(self, observation: SignalDecayObservation) -> dict[str, Any]:
        return {
            "source": "signal_decay_monitor_v1",
            "status": "proposed",
            "apply_action": False,
            "decay_id": observation.decay_id,
            "decay_hash": observation.decay_hash,
            "observation_date": observation.observation_date,
            "signal_scope_type": observation.signal_scope_type,
            "signal_scope_id": observation.signal_scope_id,
            "suggested_lifecycle_action": observation.suggested_lifecycle_action,
            "confidence": observation.confidence,
            "quality": observation.quality,
            "warnings": list(observation.warnings_json),
            "diagnostics": list(observation.diagnostics_json),
            "metrics": {
                "decay_score_bp": observation.decay_score_bp,
                "forward_excess_short_bp": observation.forward_excess_short_bp,
                "forward_excess_long_bp": observation.forward_excess_long_bp,
                "win_rate_short_bp": observation.win_rate_short_bp,
                "win_rate_long_bp": observation.win_rate_long_bp,
                "mae_short_bp": observation.mae_short_bp,
                "mae_long_bp": observation.mae_long_bp,
                "live_gap_short_bp": observation.live_gap_short_bp,
                "live_gap_long_bp": observation.live_gap_long_bp,
                "sample_size_short": observation.sample_size_short,
                "sample_size_long": observation.sample_size_long,
            },
        }


class SignalDecayService:
    """Read-only signal decay evaluator over forward evidence and gap observations."""

    def __init__(
        self,
        config: Any,
        *,
        db_path: str | Path | None = None,
        evidence_repository: EvidenceEventRepository | None = None,
        gap_repository: LiveResearchGapRepository | None = None,
        decay_repository: SignalDecayRepository | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.evidence_repository = evidence_repository or EvidenceEventRepository(config, db_path=self.db_path)
        self.gap_repository = gap_repository or LiveResearchGapRepository(config, db_path=self.db_path)
        self.decay_repository = decay_repository or SignalDecayRepository(config, db_path=self.db_path)
        self.lifecycle_adapter = SignalDecayLifecycleEvidenceAdapter()

    def evaluate_signal_scope(
        self,
        *,
        observation_date: str,
        signal_scope_type: str,
        signal_scope_id: str,
        short_window_events: int = 30,
        long_window_events: int = 120,
        short_window_days: int = 60,
        long_window_days: int = 240,
        min_sample_size: int = 10,
    ) -> SignalDecayObservation:
        normalized_scope = self._normalize_scope(signal_scope_type)
        diagnostics: list[dict[str, Any]] = []
        warnings: list[str] = []
        events = [
            event
            for event in self.evidence_repository.list_events(end_date=observation_date)
            if self._event_matches_scope(event, normalized_scope, signal_scope_id)
        ]
        rows = self._ready_rows(events)
        rows = sorted(rows, key=lambda row: (row[0].decision_date, row[0].event_id))
        long_rows = rows[-int(long_window_events):]
        short_rows = long_rows[-int(short_window_events):]
        gap_rows = self._gap_rows(normalized_scope, signal_scope_id, observation_date)
        long_gaps = gap_rows[-int(long_window_events):]
        short_gaps = long_gaps[-int(short_window_events):]

        if not events:
            diagnostics.append({"code": "scope_no_events", "severity": "warning"})
            return self._build_observation(
                observation_date=observation_date,
                signal_scope_type=normalized_scope,
                signal_scope_id=signal_scope_id,
                events=[],
                short_rows=[],
                long_rows=[],
                short_gaps=[],
                long_gaps=[],
                short_window_events=short_window_events,
                long_window_events=long_window_events,
                short_window_days=short_window_days,
                long_window_days=long_window_days,
                status=DECAY_STATUS_NO_DATA,
                suggestion=SUGGESTION_NONE,
                confidence="low",
                score=0,
                warnings=warnings,
                diagnostics=diagnostics,
            )

        short_metrics = self._metrics(short_rows, short_gaps)
        long_metrics = self._metrics(long_rows, long_gaps)
        if len(short_rows) < min_sample_size or len(long_rows) < min_sample_size:
            diagnostics.append(
                {
                    "code": "insufficient_sample",
                    "severity": "warning",
                    "metadata": {"min_sample_size": int(min_sample_size)},
                }
            )
            return self._build_observation(
                observation_date=observation_date,
                signal_scope_type=normalized_scope,
                signal_scope_id=signal_scope_id,
                events=events,
                short_rows=short_rows,
                long_rows=long_rows,
                short_gaps=short_gaps,
                long_gaps=long_gaps,
                short_window_events=short_window_events,
                long_window_events=long_window_events,
                short_window_days=short_window_days,
                long_window_days=long_window_days,
                status=DECAY_STATUS_INSUFFICIENT_SAMPLE,
                suggestion=SUGGESTION_NONE,
                confidence="low",
                score=0,
                warnings=warnings,
                diagnostics=diagnostics,
            )

        benchmark_present = short_metrics["mean_benchmark_excess_bp"] is not None and long_metrics["mean_benchmark_excess_bp"] is not None
        live_gap_present = short_metrics["mean_live_gap_vs_forward_bp"] is not None and long_metrics["mean_live_gap_vs_forward_bp"] is not None
        industry_present = short_metrics["mean_industry_excess_bp"] is not None and long_metrics["mean_industry_excess_bp"] is not None
        if not benchmark_present:
            diagnostics.append({"code": "missing_benchmark_evidence", "severity": "warning"})
            warnings.append("missing_benchmark_evidence")
        if not live_gap_present:
            diagnostics.append({"code": "missing_live_gap_evidence", "severity": "warning"})
            warnings.append("missing_live_gap_evidence")
        if not industry_present:
            diagnostics.append({"code": "missing_industry_evidence", "severity": "info"})

        score = self._decay_score(short_metrics, long_metrics, live_gap_present)
        confidence = self._confidence(
            benchmark_present=benchmark_present,
            live_gap_present=live_gap_present,
            industry_present=industry_present,
            short_quality_ratio=short_metrics["quality_degraded_ratio_bp"],
        )
        status, suggestion = self._status_and_suggestion(
            score=score,
            short_metrics=short_metrics,
            long_metrics=long_metrics,
            benchmark_present=benchmark_present,
            live_gap_present=live_gap_present,
        )
        if score >= 2500:
            diagnostics.append({"code": "short_window_weaker", "severity": "info", "metadata": {"decay_score_bp": score}})

        return self._build_observation(
            observation_date=observation_date,
            signal_scope_type=normalized_scope,
            signal_scope_id=signal_scope_id,
            events=events,
            short_rows=short_rows,
            long_rows=long_rows,
            short_gaps=short_gaps,
            long_gaps=long_gaps,
            short_window_events=short_window_events,
            long_window_events=long_window_events,
            short_window_days=short_window_days,
            long_window_days=long_window_days,
            status=status,
            suggestion=suggestion,
            confidence=confidence,
            score=score,
            warnings=warnings,
            diagnostics=diagnostics,
        )

    def evaluate_all_scopes(
        self,
        *,
        observation_date: str,
        scope: str = "all",
        scope_id: str | None = None,
        short_window_events: int = 30,
        long_window_events: int = 120,
        short_window_days: int = 60,
        long_window_days: int = 240,
        min_sample_size: int = 10,
    ) -> list[SignalDecayObservation]:
        scopes = self._discover_scopes(scope=scope, scope_id=scope_id, observation_date=observation_date)
        return [
            self.evaluate_signal_scope(
                observation_date=observation_date,
                signal_scope_type=scope_type,
                signal_scope_id=scope_value,
                short_window_events=short_window_events,
                long_window_events=long_window_events,
                short_window_days=short_window_days,
                long_window_days=long_window_days,
                min_sample_size=min_sample_size,
            )
            for scope_type, scope_value in scopes
        ]

    def save_decay_observation(
        self,
        observation: SignalDecayObservation,
        *,
        confirm: bool = False,
    ) -> SignalDecaySaveResult:
        if not confirm:
            return SignalDecaySaveResult(observation=observation, saved=False)
        existing = self.decay_repository.get_by_hash(observation.decay_hash)
        if existing is not None:
            return SignalDecaySaveResult(observation=existing, saved=False, skipped_duplicate=True)
        saved = self.decay_repository.save_observation(observation)
        return SignalDecaySaveResult(observation=saved, saved=True)

    def list_decay_observations(self, **filters: Any) -> list[SignalDecayObservation]:
        return self.decay_repository.list_observations(**filters)

    def summarize_decay(self, *, observation_date: str | None = None):
        return self.decay_repository.summarize_decay(observation_date=observation_date)

    def build_lifecycle_proposed_evidence_payload(self, observation: SignalDecayObservation) -> dict[str, Any]:
        return self.lifecycle_adapter.build_payload(observation)

    def capture_decay(
        self,
        *,
        observation_date: str,
        scope: str = "all",
        scope_id: str | None = None,
        short_window_events: int = 30,
        long_window_events: int = 120,
        short_window_days: int = 60,
        long_window_days: int = 240,
        min_sample_size: int = 10,
        confirm: bool = False,
    ) -> dict[str, Any]:
        observations = self.evaluate_all_scopes(
            observation_date=observation_date,
            scope=scope,
            scope_id=scope_id,
            short_window_events=short_window_events,
            long_window_events=long_window_events,
            short_window_days=short_window_days,
            long_window_days=long_window_days,
            min_sample_size=min_sample_size,
        )
        save_results = [self.save_decay_observation(observation, confirm=confirm) for observation in observations]
        status_counts = Counter(observation.decay_status for observation in observations)
        suggestion_counts = Counter(observation.suggested_lifecycle_action for observation in observations)
        confidence_counts = Counter(observation.confidence for observation in observations)
        return {
            "dry_run": not confirm,
            "observation_date": observation_date,
            "scopes_seen": len(self._discover_scopes(scope=scope, scope_id=scope_id, observation_date=observation_date)),
            "scopes_evaluated": len(observations),
            "observations_created": sum(1 for result in save_results if result.saved),
            "observations_skipped_duplicate": sum(1 for result in save_results if result.skipped_duplicate),
            "insufficient_sample_count": status_counts.get(DECAY_STATUS_INSUFFICIENT_SAMPLE, 0),
            "stable_count": status_counts.get(DECAY_STATUS_STABLE, 0),
            "watch_count": status_counts.get(DECAY_STATUS_WATCH, 0),
            "decaying_count": status_counts.get(DECAY_STATUS_DECAYING, 0),
            "severe_decay_count": status_counts.get(DECAY_STATUS_SEVERE_DECAY, 0),
            "demote_candidate_count": suggestion_counts.get(SUGGESTION_DEMOTE_CANDIDATE, 0),
            "retire_candidate_count": suggestion_counts.get(SUGGESTION_RETIRE_CANDIDATE, 0),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "warnings_count": sum(len(observation.warnings_json) for observation in observations),
            "observations": [observation.to_dict() for observation in observations],
        }

    def _discover_scopes(
        self,
        *,
        scope: str,
        scope_id: str | None,
        observation_date: str,
    ) -> list[tuple[str, str]]:
        if scope != "all":
            normalized = self._normalize_scope(scope)
            if scope_id:
                return [(normalized, scope_id)]
        else:
            normalized = ""
        events = self.evidence_repository.list_events(end_date=observation_date)
        scope_types = SUPPORTED_SIGNAL_DECAY_SCOPES if scope == "all" else (normalized,)
        discovered: set[tuple[str, str]] = set()
        for event in events:
            for scope_type in scope_types:
                value = self._scope_value(event, scope_type)
                if value:
                    discovered.add((scope_type, value))
        return sorted(discovered)

    def _ready_rows(self, events: list[EvidenceEvent]) -> list[tuple[EvidenceEvent, EvidenceOutcome]]:
        event_by_id = {event.event_id: event for event in events}
        rows: list[tuple[EvidenceEvent, EvidenceOutcome]] = []
        for outcome in self.evidence_repository.list_outcomes():
            event = event_by_id.get(outcome.event_id)
            if event is not None and outcome.outcome_status == EvidenceOutcomeStatus.READY:
                rows.append((event, outcome))
        return rows

    def _gap_rows(self, scope_type: str, scope_id: str, observation_date: str):
        rows = [
            row
            for row in self.gap_repository.list_observations()
            if row.observation_date <= observation_date and self._gap_matches_scope(row, scope_type, scope_id)
        ]
        return sorted(rows, key=lambda row: (row.observation_date, row.gap_id))

    @staticmethod
    def _metrics(rows: list[tuple[EvidenceEvent, EvidenceOutcome]], gaps: list[Any]) -> dict[str, int | None]:
        benchmark_values = [outcome.benchmark_excess_bp for _, outcome in rows if outcome.benchmark_excess_bp is not None]
        industry_values = [outcome.industry_excess_bp for _, outcome in rows if outcome.industry_excess_bp is not None]
        mae_values = [outcome.max_adverse_excursion_bp for _, outcome in rows if outcome.max_adverse_excursion_bp is not None]
        live_forward_values = [row.gap_vs_forward_evidence_bp for row in gaps if row.gap_vs_forward_evidence_bp is not None]
        live_benchmark_values = [row.gap_vs_benchmark_bp for row in gaps if row.gap_vs_benchmark_bp is not None]
        degraded_count = 0
        for event, outcome in rows:
            if event.data_quality.value in {"missing", "degraded"} or outcome.data_quality.value in {"missing", "degraded"}:
                degraded_count += 1
        return {
            "mean_benchmark_excess_bp": _mean_int(benchmark_values),
            "median_benchmark_excess_bp": _median_int(benchmark_values),
            "win_vs_benchmark_rate_bp": _rate_bp(sum(1 for value in benchmark_values if value > 0), len(benchmark_values)),
            "mean_industry_excess_bp": _mean_int(industry_values),
            "mean_mae_bp": _mean_int(mae_values),
            "mean_live_gap_vs_forward_bp": _mean_int(live_forward_values),
            "mean_live_gap_vs_benchmark_bp": _mean_int(live_benchmark_values),
            "quality_degraded_ratio_bp": _rate_bp(degraded_count, len(rows)),
        }

    @staticmethod
    def _decay_score(short_metrics: dict[str, int | None], long_metrics: dict[str, int | None], live_gap_present: bool) -> int:
        score = 0
        if _worse_by(short_metrics["mean_benchmark_excess_bp"], long_metrics["mean_benchmark_excess_bp"], 300):
            score += 3000
        if _worse_by(short_metrics["win_vs_benchmark_rate_bp"], long_metrics["win_vs_benchmark_rate_bp"], 1000):
            score += 2000
        if _worse_by(short_metrics["mean_mae_bp"], long_metrics["mean_mae_bp"], 300):
            score += 1500
        if live_gap_present and _worse_by(short_metrics["mean_live_gap_vs_forward_bp"], long_metrics["mean_live_gap_vs_forward_bp"], 300):
            score += 2000
        short_quality = short_metrics["quality_degraded_ratio_bp"]
        long_quality = long_metrics["quality_degraded_ratio_bp"]
        if short_quality is not None and long_quality is not None and short_quality > long_quality + 1000:
            score += 1000
        return min(score, 10000)

    @staticmethod
    def _confidence(
        *,
        benchmark_present: bool,
        live_gap_present: bool,
        industry_present: bool,
        short_quality_ratio: int | None,
    ) -> str:
        if not benchmark_present or not live_gap_present:
            return "low"
        if not industry_present or (short_quality_ratio is not None and short_quality_ratio > 0):
            return "medium"
        return "high"

    @staticmethod
    def _status_and_suggestion(
        *,
        score: int,
        short_metrics: dict[str, int | None],
        long_metrics: dict[str, int | None],
        benchmark_present: bool,
        live_gap_present: bool,
    ) -> tuple[str, str]:
        if score < 2500:
            return DECAY_STATUS_STABLE, SUGGESTION_HOLD
        if score < 5000:
            return DECAY_STATUS_WATCH, SUGGESTION_WATCH
        if score < 5000:
            return DECAY_STATUS_DECAYING, SUGGESTION_DEMOTE_CANDIDATE if benchmark_present else SUGGESTION_WATCH
        if not benchmark_present or not live_gap_present:
            return DECAY_STATUS_SEVERE_DECAY, SUGGESTION_DEMOTE_CANDIDATE if benchmark_present else SUGGESTION_WATCH
        short_excess = short_metrics["mean_benchmark_excess_bp"]
        long_excess = long_metrics["mean_benchmark_excess_bp"]
        short_gap = short_metrics["mean_live_gap_vs_forward_bp"]
        long_gap = long_metrics["mean_live_gap_vs_forward_bp"]
        both_weak = (
            short_excess is not None
            and long_excess is not None
            and short_gap is not None
            and long_gap is not None
            and short_excess < 0
            and long_excess <= 0
            and short_gap < 0
            and long_gap <= 0
        )
        return DECAY_STATUS_SEVERE_DECAY, SUGGESTION_RETIRE_CANDIDATE if both_weak else SUGGESTION_DEMOTE_CANDIDATE

    def _build_observation(
        self,
        *,
        observation_date: str,
        signal_scope_type: str,
        signal_scope_id: str,
        events: list[EvidenceEvent],
        short_rows: list[tuple[EvidenceEvent, EvidenceOutcome]],
        long_rows: list[tuple[EvidenceEvent, EvidenceOutcome]],
        short_gaps: list[Any],
        long_gaps: list[Any],
        short_window_events: int,
        long_window_events: int,
        short_window_days: int,
        long_window_days: int,
        status: str,
        suggestion: str,
        confidence: str,
        score: int,
        warnings: list[str],
        diagnostics: list[dict[str, Any]],
    ) -> SignalDecayObservation:
        short_metrics = self._metrics(short_rows, short_gaps)
        long_metrics = self._metrics(long_rows, long_gaps)
        metadata = {
            "window_policy": "event_count_primary",
            "short_window_days": int(short_window_days),
            "long_window_days": int(long_window_days),
            "lifecycle_policy": "payload_only",
            "return_basis": "close_to_close_research_evidence",
        }
        scope_metadata = self._scope_metadata(signal_scope_type, signal_scope_id)
        quality = self._quality(status, warnings, short_metrics["quality_degraded_ratio_bp"])
        decay_hash_payload = {
            "observation_date": observation_date,
            "signal_scope_type": signal_scope_type,
            "signal_scope_id": signal_scope_id,
            "window_short": int(short_window_events),
            "window_long": int(long_window_events),
            "metrics": {
                "short": short_metrics,
                "long": long_metrics,
                "score": int(score),
                "status": status,
                "suggestion": suggestion,
            },
        }
        decay_hash = f"sha256:{uuid5(NAMESPACE_URL, canonical_json(decay_hash_payload)).hex}"
        decay_id = f"decay_{uuid5(NAMESPACE_URL, decay_hash).hex}"
        return SignalDecayObservation(
            decay_id=decay_id,
            decay_hash=decay_hash,
            observation_date=observation_date,
            signal_scope_type=signal_scope_type,
            signal_scope_id=signal_scope_id,
            strategy_version_id=scope_metadata["strategy_version_id"],
            profile_id=scope_metadata["profile_id"],
            event_type=scope_metadata["event_type"],
            event_family=scope_metadata["event_family"],
            factor_name=scope_metadata["factor_name"],
            window_short=int(short_window_events),
            window_long=int(long_window_events),
            sample_size_short=len(short_rows),
            sample_size_long=len(long_rows),
            forward_excess_short_bp=short_metrics["mean_benchmark_excess_bp"],
            forward_excess_long_bp=long_metrics["mean_benchmark_excess_bp"],
            win_rate_short_bp=short_metrics["win_vs_benchmark_rate_bp"],
            win_rate_long_bp=long_metrics["win_vs_benchmark_rate_bp"],
            mae_short_bp=short_metrics["mean_mae_bp"],
            mae_long_bp=long_metrics["mean_mae_bp"],
            live_gap_short_bp=short_metrics["mean_live_gap_vs_forward_bp"],
            live_gap_long_bp=long_metrics["mean_live_gap_vs_forward_bp"],
            decay_score_bp=score,
            decay_status=status,
            suggested_lifecycle_action=suggestion,
            confidence=confidence,
            evidence_event_count=len(events),
            gap_observation_count=len(long_gaps),
            quality=quality,
            warnings_json=sorted(set(warnings)),
            diagnostics_json=diagnostics,
            metadata_json=metadata,
        )

    @staticmethod
    def _quality(status: str, warnings: list[str], short_quality_ratio: int | None) -> str:
        if status in {DECAY_STATUS_NO_DATA, DECAY_STATUS_INSUFFICIENT_SAMPLE}:
            return "missing"
        if warnings or (short_quality_ratio is not None and short_quality_ratio > 0):
            return "degraded"
        return "observed"

    @staticmethod
    def _scope_metadata(scope_type: str, scope_id: str) -> dict[str, str]:
        return {
            "strategy_version_id": scope_id if scope_type == "strategy_version" else "",
            "profile_id": scope_id if scope_type == "profile" else "",
            "event_type": scope_id if scope_type == "event_type" else "",
            "event_family": scope_id if scope_type == "event_family" else "",
            "factor_name": scope_id if scope_type == "factor_name" else "",
        }

    @staticmethod
    def _normalize_scope(scope: str) -> str:
        aliases = {
            "strategy_version_id": "strategy_version",
            "profile_id": "profile",
        }
        normalized = aliases.get(scope, scope)
        if normalized not in SUPPORTED_SIGNAL_DECAY_SCOPES:
            raise ValueError(f"unsupported signal decay scope: {scope}")
        return normalized

    @staticmethod
    def _scope_value(event: EvidenceEvent, scope_type: str) -> str:
        if scope_type == "event_type":
            return event.event_type.value
        if scope_type == "event_family":
            return event.event_family
        if scope_type == "strategy_version":
            return event.strategy_version_id
        if scope_type == "profile":
            return event.profile_id
        return ""

    def _event_matches_scope(self, event: EvidenceEvent, scope_type: str, scope_id: str) -> bool:
        return self._scope_value(event, scope_type) == scope_id

    @staticmethod
    def _gap_matches_scope(row: Any, scope_type: str, scope_id: str) -> bool:
        if scope_type == "event_type":
            return str(row.metadata_json.get("event_type") or "") == scope_id
        if scope_type == "strategy_version":
            return row.strategy_version_id == scope_id
        return False


def _rounded_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator >= 0:
        return (numerator + denominator // 2) // denominator
    return -((-numerator + denominator // 2) // denominator)


def _mean_int(values: list[int | None]) -> int | None:
    clean = [int(value) for value in values if value is not None]
    if not clean:
        return None
    return _rounded_div(sum(clean), len(clean))


def _median_int(values: list[int | None]) -> int | None:
    clean = sorted(int(value) for value in values if value is not None)
    if not clean:
        return None
    middle = len(clean) // 2
    if len(clean) % 2 == 1:
        return clean[middle]
    return _rounded_div(clean[middle - 1] + clean[middle], 2)


def _rate_bp(success_count: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    return _rounded_div(int(success_count) * 10000, int(denominator))


def _worse_by(short_value: int | None, long_value: int | None, threshold_bp: int) -> bool:
    if short_value is None or long_value is None:
        return False
    return int(short_value) < int(long_value) - int(threshold_bp)


__all__ = [
    "SignalDecayLifecycleEvidenceAdapter",
    "SignalDecayService",
    "SUPPORTED_SIGNAL_DECAY_SCOPES",
    "is_production_like_db",
]
