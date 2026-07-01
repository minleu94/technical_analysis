from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Protocol

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskRiskPromptSummary,
    PortfolioAlertSummary,
    WatchlistTriggerSummary,
)
from app_module.evidence_event_dtos import EvidenceDataQuality, EvidenceEventType
from app_module.evidence_event_importer_dtos import (
    EvidenceCaptureRequest,
    EvidenceImportDiagnostic,
    EvidenceImportResult,
)


class EvidenceImporter(Protocol):
    source_name: str

    def collect(self, request: EvidenceCaptureRequest) -> EvidenceImportResult: ...


def _quality(value: Any) -> EvidenceDataQuality:
    raw = value.value if hasattr(value, "value") else value
    if raw == DecisionDeskQuality.OBSERVED.value:
        return EvidenceDataQuality.OBSERVED
    if raw == DecisionDeskQuality.ESTIMATED.value:
        return EvidenceDataQuality.ESTIMATED
    if raw == DecisionDeskQuality.DEGRADED.value:
        return EvidenceDataQuality.DEGRADED
    return EvidenceDataQuality.MISSING


def _date_text(value: Any, fallback: str | None = None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return fallback or date.today().isoformat()
    text = str(value).strip()
    if not text:
        return fallback or date.today().isoformat()
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return text[:10]


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        if ";" in value:
            return tuple(item.strip() for item in value.split(";") if item.strip())
        return (value.strip(),) if value.strip() else ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _score_bp(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return int((score * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class UnsupportedEvidenceImporter:
    def __init__(self, source_name: str, reason: str = "source provider is not configured") -> None:
        self.source_name = source_name
        self.reason = reason

    def collect(self, request: EvidenceCaptureRequest) -> EvidenceImportResult:
        return EvidenceImportResult(
            source_name=self.source_name,
            decision_date=request.decision_date_text,
            diagnostics=(
                EvidenceImportDiagnostic(
                    code="source_unsupported",
                    message=self.reason,
                    source_name=self.source_name,
                    severity="warning",
                ),
            ),
        )


class RecommendationEvidenceImporter:
    source_name = "recommendation"

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def collect(self, request: EvidenceCaptureRequest) -> EvidenceImportResult:
        result = self._load_result(request)
        if result is None:
            return EvidenceImportResult(
                source_name=self.source_name,
                decision_date=request.decision_date_text,
                diagnostics=(
                    EvidenceImportDiagnostic(
                        code="source_missing",
                        message="recommendation result not found",
                        source_name=self.source_name,
                    ),
                ),
            )

        decision_date = request.decision_date_text or _date_text(getattr(result, "created_at", None))
        config = dict(getattr(result, "config", {}) or {})
        profile_id = str(config.get("profile_id") or config.get("selected_profile") or "")
        profile_version = str(config.get("profile_version") or "")
        payloads: list[dict[str, Any]] = []
        diagnostics = [
            EvidenceImportDiagnostic(
                code="source_missing_exclusion_payload",
                message="RecommendationResultDTO does not persist why-not/liquidity exclusion payloads",
                source_name=self.source_name,
            )
        ]

        for index, rec in enumerate(getattr(result, "recommendations", ())):
            symbol = str(getattr(rec, "stock_code", "")).strip()
            if request.symbol and symbol != str(request.symbol).strip():
                continue
            if not symbol:
                diagnostics.append(
                    EvidenceImportDiagnostic(
                        code="event_invalid_symbol",
                        message="recommendation row has empty stock_code",
                        source_name=self.source_name,
                    )
                )
                continue

            warnings = []
            percentile = getattr(rec, "score_percentile_bp", None)
            if percentile is None:
                warnings.append("score_percentile_missing")
            payloads.append(
                {
                    "event_date": decision_date,
                    "decision_date": decision_date,
                    "symbol": symbol,
                    "event_type": EvidenceEventType.RECOMMENDATION_INCLUDED,
                    "event_family": "recommendation",
                    "source_type": "recommendation_result",
                    "source_id": str(getattr(result, "result_id", "")),
                    "source_snapshot_id": str(getattr(result, "result_id", "")),
                    "profile_id": profile_id,
                    "reason_codes": _tuple(getattr(rec, "recommendation_reasons", "")),
                    "risk_codes": (),
                    "score_bp": _score_bp(getattr(rec, "total_score", None)),
                    "score_percentile_bp": percentile,
                    "regime": getattr(result, "regime", None),
                    "sector": getattr(rec, "industry", None),
                    "data_quality": EvidenceDataQuality.OBSERVED,
                    "warnings": tuple(warnings),
                    "as_of_date": decision_date,
                    "available_date": decision_date,
                    "source_version": "recommendation_importer_v1",
                    "metadata": {
                        "result_name": str(getattr(result, "result_name", "")),
                        "profile_version": profile_version,
                        "stock_name": str(getattr(rec, "stock_name", "")),
                        "threshold_mode": str(getattr(rec, "threshold_mode", "")),
                        "eligible_universe_size": getattr(rec, "eligible_universe_size", None),
                        "eligible_universe_date": getattr(rec, "eligible_universe_date", None),
                        "ranking_method": getattr(rec, "ranking_method", None),
                        "recommendation_rank": index + 1,
                        "source_created_at": getattr(result, "created_at", None),
                    },
                }
            )
            if request.limit is not None and len(payloads) >= request.limit:
                break

        return EvidenceImportResult(
            source_name=self.source_name,
            decision_date=decision_date,
            event_payloads=tuple(payloads),
            diagnostics=tuple(diagnostics),
        )

    def _load_result(self, request: EvidenceCaptureRequest) -> Any | None:
        if request.result_id:
            return self.repository.load_result(request.result_id)
        results = self.repository.list_results()
        if not results:
            return None
        latest = sorted(results, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]
        return self.repository.load_result(str(latest.get("result_id") or ""))


class WatchlistTriggerEvidenceImporter:
    source_name = "watchlist-trigger"

    def __init__(self, snapshot_provider: Any | None = None) -> None:
        self.snapshot_provider = snapshot_provider

    def collect(self, request: EvidenceCaptureRequest) -> EvidenceImportResult:
        if self.snapshot_provider is None:
            return UnsupportedEvidenceImporter(self.source_name).collect(request)
        decision_date = request.decision_date_text or date.today().isoformat()
        summary: WatchlistTriggerSummary = self.snapshot_provider.build_snapshot(datetime.fromisoformat(decision_date).date())
        as_of = _date_text(summary.as_of_date, decision_date)
        signal_types = self._parse_top_signal(summary.top_signal)
        payloads: list[dict[str, Any]] = []
        for code in summary.triggered_codes:
            event_type = signal_types.get(code, EvidenceEventType.WATCHLIST_TRIGGER_ADDED)
            payloads.append(self._payload(summary, code, event_type, decision_date, as_of, fallback=code not in signal_types))
        for warning in summary.warnings:
            prefix = "watchlist_trigger_risk_alert:"
            if warning.startswith(prefix):
                code = warning.removeprefix(prefix).strip()
                if code:
                    payloads.append(self._payload(summary, code, EvidenceEventType.WATCHLIST_TRIGGER_RISK_ALERT, decision_date, as_of))
        return EvidenceImportResult(self.source_name, decision_date, tuple(payloads))

    def _payload(
        self,
        summary: WatchlistTriggerSummary,
        code: str,
        event_type: EvidenceEventType,
        decision_date: str,
        as_of: str,
        *,
        fallback: bool = False,
    ) -> dict[str, Any]:
        return {
            "event_date": as_of,
            "decision_date": decision_date,
            "symbol": str(code),
            "event_type": event_type,
            "event_family": "watchlist",
            "source_type": "daily_decision_desk_watchlist_trigger",
            "source_id": f"watchlist-trigger:{as_of}",
            "source_snapshot_id": f"watchlist-trigger:{as_of}",
            "reason_codes": (event_type.value,),
            "risk_codes": ("watchlist_risk_alert",) if event_type == EvidenceEventType.WATCHLIST_TRIGGER_RISK_ALERT else (),
            "data_quality": _quality(summary.quality),
            "warnings": tuple(summary.warnings),
            "as_of_date": as_of,
            "available_date": decision_date,
            "source_version": "watchlist_trigger_importer_v1",
            "metadata": {
                "top_signal": summary.top_signal,
                "trigger_count": summary.trigger_count,
                "fallback_signal_type": fallback,
            },
        }

    def _parse_top_signal(self, top_signal: str | None) -> dict[str, EvidenceEventType]:
        mapping: dict[str, EvidenceEventType] = {}
        if not top_signal:
            return mapping
        type_by_key = {
            "new": EvidenceEventType.WATCHLIST_TRIGGER_ADDED,
            "added": EvidenceEventType.WATCHLIST_TRIGGER_ADDED,
            "removed": EvidenceEventType.WATCHLIST_TRIGGER_REMOVED,
            "up": EvidenceEventType.WATCHLIST_TRIGGER_STRENGTH_UP,
            "down": EvidenceEventType.WATCHLIST_TRIGGER_STRENGTH_DOWN,
        }
        for part in top_signal.split(";"):
            key, sep, raw_codes = part.partition("=")
            if not sep:
                continue
            event_type = type_by_key.get(key.strip().lower())
            if event_type is None:
                continue
            for code in raw_codes.split(","):
                clean = code.strip()
                if clean:
                    mapping[clean] = event_type
        return mapping


class PortfolioAlertEvidenceImporter:
    source_name = "portfolio-alert"

    def __init__(self, snapshot_provider: Any | None = None) -> None:
        self.snapshot_provider = snapshot_provider

    def collect(self, request: EvidenceCaptureRequest) -> EvidenceImportResult:
        if self.snapshot_provider is None:
            return UnsupportedEvidenceImporter(self.source_name).collect(request)
        decision_date = request.decision_date_text or date.today().isoformat()
        summary: PortfolioAlertSummary = self.snapshot_provider.build_snapshot(datetime.fromisoformat(decision_date).date())
        as_of = _date_text(summary.as_of_date, decision_date)
        payloads = [
            self._payload(summary, attribution, decision_date, as_of)
            for attribution in summary.attributions
            if not request.symbol or str(attribution.stock_code) == str(request.symbol)
        ]
        return EvidenceImportResult(self.source_name, decision_date, tuple(payloads))

    def _payload(self, summary: PortfolioAlertSummary, attribution: Any, decision_date: str, as_of: str) -> dict[str, Any]:
        event_type = self._event_type(attribution)
        return {
            "event_date": as_of,
            "decision_date": decision_date,
            "symbol": str(attribution.stock_code),
            "event_type": event_type,
            "event_family": "portfolio",
            "source_type": "daily_decision_desk_portfolio_alert",
            "source_id": f"portfolio-alert:{as_of}",
            "source_snapshot_id": f"portfolio-alert:{as_of}",
            "reason_codes": tuple(attribution.reasons),
            "risk_codes": (event_type.value,),
            "data_quality": _quality(summary.quality),
            "warnings": tuple(summary.warnings),
            "as_of_date": as_of,
            "available_date": decision_date,
            "source_version": "portfolio_alert_importer_v1",
            "metadata": {
                "source_label": attribution.source_label,
                "condition_status": attribution.condition_status,
                "chip_risk_level": attribution.chip_risk_level,
                "severity": attribution.severity,
                "data_quality_flags": list(attribution.data_quality_flags),
                "alert_level": summary.alert_level,
            },
        }

    def _event_type(self, attribution: Any) -> EvidenceEventType:
        if str(attribution.condition_status).lower() == "invalid":
            return EvidenceEventType.PORTFOLIO_ALERT_CONDITION_INVALID
        if str(attribution.condition_status).lower() == "warning":
            return EvidenceEventType.PORTFOLIO_ALERT_CONDITION_WARNING
        if str(attribution.chip_risk_level).lower() in {"bearish", "extreme", "risk", "error"}:
            return EvidenceEventType.PORTFOLIO_ALERT_CHIP_RISK
        return EvidenceEventType.PORTFOLIO_ALERT_DATA_QUALITY


class RiskPromptEvidenceImporter:
    source_name = "risk-prompt"

    def __init__(self, snapshot_provider: Any | None = None) -> None:
        self.snapshot_provider = snapshot_provider

    def collect(self, request: EvidenceCaptureRequest) -> EvidenceImportResult:
        if self.snapshot_provider is None:
            return UnsupportedEvidenceImporter(self.source_name).collect(request)
        decision_date = request.decision_date_text or date.today().isoformat()
        summary: DecisionDeskRiskPromptSummary = self.snapshot_provider.build_snapshot(datetime.fromisoformat(decision_date).date())
        as_of = _date_text(summary.as_of_date, decision_date)
        payloads = []
        for prompt in summary.prompts:
            symbol = str(prompt.code or "").strip() or "MARKET"
            if request.symbol and symbol != str(request.symbol):
                continue
            payloads.append(
                {
                    "event_date": as_of,
                    "decision_date": decision_date,
                    "symbol": symbol,
                    "event_type": self._event_type(prompt.category),
                    "event_family": "risk_prompt",
                    "source_type": "daily_decision_desk_risk_prompt",
                    "source_id": f"risk-prompt:{as_of}",
                    "source_snapshot_id": f"risk-prompt:{as_of}",
                    "reason_codes": (prompt.category, prompt.source),
                    "risk_codes": (prompt.severity,),
                    "data_quality": _quality(summary.quality),
                    "warnings": tuple(summary.warnings),
                    "as_of_date": as_of,
                    "available_date": decision_date,
                    "source_version": "risk_prompt_importer_v1",
                    "metadata": {
                        "title": prompt.title,
                        "reason": prompt.reason,
                        "action_hint": prompt.action_hint,
                        "source": prompt.source,
                        "category": prompt.category,
                    },
                }
            )
        return EvidenceImportResult(self.source_name, decision_date, tuple(payloads))

    def _event_type(self, category: str) -> EvidenceEventType:
        if category == "liquidity":
            return EvidenceEventType.RISK_PROMPT_LOW_LIQUIDITY
        if category == "weakness":
            return EvidenceEventType.RISK_PROMPT_RELATIVE_WEAKNESS
        if category == "fundamental_diagnostic":
            return EvidenceEventType.RISK_PROMPT_FUNDAMENTAL_DIAGNOSTIC
        return EvidenceEventType.RISK_PROMPT_DATA_QUALITY

