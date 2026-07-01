from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
from typing import Any

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    DecisionDeskSnapshot,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertAttribution,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)
from app_module.research_run_dtos import canonical_json


SnapshotJson = dict[str, Any]


def _date_text(value: date | datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any) -> date | None:
    text = _date_text(value)
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return datetime.utcnow().replace(microsecond=0)
    return datetime.fromisoformat(text)


def _quality(value: Any) -> DecisionDeskQuality:
    raw = value.value if hasattr(value, "value") else value
    try:
        return DecisionDeskQuality(str(raw))
    except ValueError:
        return DecisionDeskQuality.MISSING


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _warnings(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _list(value) if str(item).strip())


def _section_quality(payload: SnapshotJson) -> str:
    return str(payload.get("quality") or DecisionDeskQuality.MISSING.value)


def _snapshot_hash_payload(
    *,
    decision_date: str,
    as_of_date: str,
    source_version: str,
    builder_version: str,
    data_quality: str,
    warnings_json: list[Any],
    market_regime_json: SnapshotJson,
    market_breadth_json: SnapshotJson,
    sector_rotation_json: SnapshotJson,
    relative_strength_liquidity_json: SnapshotJson,
    watchlist_trigger_json: SnapshotJson,
    portfolio_alert_json: SnapshotJson,
    risk_prompt_json: SnapshotJson,
    fundamental_diagnostics_json: SnapshotJson,
    metadata_json: SnapshotJson,
) -> SnapshotJson:
    return {
        "decision_date": decision_date,
        "as_of_date": as_of_date,
        "source_version": source_version,
        "builder_version": builder_version,
        "data_quality": data_quality,
        "warnings_json": warnings_json,
        "market_regime_json": market_regime_json,
        "market_breadth_json": market_breadth_json,
        "sector_rotation_json": sector_rotation_json,
        "relative_strength_liquidity_json": relative_strength_liquidity_json,
        "watchlist_trigger_json": watchlist_trigger_json,
        "portfolio_alert_json": portfolio_alert_json,
        "risk_prompt_json": risk_prompt_json,
        "fundamental_diagnostics_json": fundamental_diagnostics_json,
        "metadata_json": metadata_json,
    }


@dataclass(frozen=True)
class StoredDecisionDeskSnapshot:
    snapshot_id: str
    snapshot_hash: str
    decision_date: str
    as_of_date: str
    source_version: str
    builder_version: str
    data_quality: str
    warnings_json: list[Any] = field(default_factory=list)
    market_regime_json: SnapshotJson = field(default_factory=dict)
    market_breadth_json: SnapshotJson = field(default_factory=dict)
    sector_rotation_json: SnapshotJson = field(default_factory=dict)
    relative_strength_liquidity_json: SnapshotJson = field(default_factory=dict)
    watchlist_trigger_json: SnapshotJson = field(default_factory=dict)
    portfolio_alert_json: SnapshotJson = field(default_factory=dict)
    risk_prompt_json: SnapshotJson = field(default_factory=dict)
    fundamental_diagnostics_json: SnapshotJson = field(default_factory=dict)
    metadata_json: SnapshotJson = field(default_factory=dict)
    snapshot_status: str = "active"
    created_at: str = ""

    def hash_payload(self) -> SnapshotJson:
        return _snapshot_hash_payload(
            decision_date=self.decision_date,
            as_of_date=self.as_of_date,
            source_version=self.source_version,
            builder_version=self.builder_version,
            data_quality=self.data_quality,
            warnings_json=list(self.warnings_json),
            market_regime_json=dict(self.market_regime_json),
            market_breadth_json=dict(self.market_breadth_json),
            sector_rotation_json=dict(self.sector_rotation_json),
            relative_strength_liquidity_json=dict(self.relative_strength_liquidity_json),
            watchlist_trigger_json=dict(self.watchlist_trigger_json),
            portfolio_alert_json=dict(self.portfolio_alert_json),
            risk_prompt_json=dict(self.risk_prompt_json),
            fundamental_diagnostics_json=dict(self.fundamental_diagnostics_json),
            metadata_json=dict(self.metadata_json),
        )

    def to_decision_desk_snapshot(self) -> DecisionDeskSnapshot:
        generated_at = _parse_datetime(self.metadata_json.get("generated_at") or self.created_at)
        return DecisionDeskSnapshot(
            as_of_date=date.fromisoformat(self.as_of_date),
            generated_at=generated_at,
            schema_version=int(self.metadata_json.get("schema_version") or 1),
            overall_quality=_quality(self.data_quality),
            market_regime=_market_regime(self.market_regime_json),
            market_breadth=_market_breadth(self.market_breadth_json),
            sector_rotation=_sector_rotation(self.sector_rotation_json),
            relative_strength_liquidity=_relative_strength_liquidity(self.relative_strength_liquidity_json),
            watchlist_triggers=_watchlist_trigger(self.watchlist_trigger_json),
            portfolio_alerts=_portfolio_alert(self.portfolio_alert_json),
            risk_prompts=_risk_prompt(self.risk_prompt_json),
            warnings=_warnings(self.warnings_json),
        )


def build_stored_decision_desk_snapshot(
    snapshot: DecisionDeskSnapshot,
    *,
    decision_date: date | str | None = None,
    source_version: str = "decision_desk_snapshot_v1",
    builder_version: str = "DecisionDeskSnapshotBuilder:v1",
    metadata: SnapshotJson | None = None,
) -> StoredDecisionDeskSnapshot:
    decision_date_text = _date_text(decision_date) or snapshot.as_of_date.isoformat()
    as_of_date_text = snapshot.as_of_date.isoformat()
    metadata_json = dict(metadata or {})
    metadata_json.update(
        {
            "generated_at": snapshot.generated_at.isoformat(),
            "schema_version": snapshot.schema_version,
        }
    )
    hash_metadata_json = {key: value for key, value in metadata_json.items() if key != "generated_at"}
    payload = _snapshot_hash_payload(
        decision_date=decision_date_text,
        as_of_date=as_of_date_text,
        source_version=source_version,
        builder_version=builder_version,
        data_quality=snapshot.overall_quality.value,
        warnings_json=list(snapshot.warnings),
        market_regime_json=snapshot.market_regime.to_dict(),
        market_breadth_json=snapshot.market_breadth.to_dict(),
        sector_rotation_json=snapshot.sector_rotation.to_dict(),
        relative_strength_liquidity_json=snapshot.relative_strength_liquidity.to_dict(),
        watchlist_trigger_json=snapshot.watchlist_triggers.to_dict(),
        portfolio_alert_json=snapshot.portfolio_alerts.to_dict(),
        risk_prompt_json=snapshot.risk_prompts.to_dict(),
        fundamental_diagnostics_json={},
        metadata_json=hash_metadata_json,
    )
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    snapshot_hash = f"sha256:{digest}"
    return StoredDecisionDeskSnapshot(
        snapshot_id=f"dds_{digest[:16]}",
        snapshot_hash=snapshot_hash,
        decision_date=decision_date_text,
        as_of_date=as_of_date_text,
        source_version=source_version,
        builder_version=builder_version,
        data_quality=snapshot.overall_quality.value,
        warnings_json=list(snapshot.warnings),
        market_regime_json=snapshot.market_regime.to_dict(),
        market_breadth_json=snapshot.market_breadth.to_dict(),
        sector_rotation_json=snapshot.sector_rotation.to_dict(),
        relative_strength_liquidity_json=snapshot.relative_strength_liquidity.to_dict(),
        watchlist_trigger_json=snapshot.watchlist_triggers.to_dict(),
        portfolio_alert_json=snapshot.portfolio_alerts.to_dict(),
        risk_prompt_json=snapshot.risk_prompts.to_dict(),
        fundamental_diagnostics_json={},
        metadata_json=metadata_json,
    )


def _market_regime(payload: SnapshotJson) -> MarketRegimeSummary:
    return MarketRegimeSummary(
        as_of_date=_parse_date(payload.get("as_of_date")),
        quality=_quality(payload.get("quality")),
        warnings=_warnings(payload.get("warnings")),
        regime_label=payload.get("regime_label"),
        regime_score=payload.get("regime_score"),
        regime_confidence=payload.get("regime_confidence"),
        meta=payload.get("meta"),
    )


def _market_breadth(payload: SnapshotJson) -> MarketBreadthSummary:
    return MarketBreadthSummary(
        as_of_date=_parse_date(payload.get("as_of_date")),
        quality=_quality(payload.get("quality")),
        warnings=_warnings(payload.get("warnings")),
        breadth_ratio_bp=payload.get("breadth_ratio_bp"),
        advancing=payload.get("advancing"),
        declining=payload.get("declining"),
        unchanged=payload.get("unchanged"),
        meta=payload.get("meta"),
    )


def _sector_rotation(payload: SnapshotJson) -> SectorRotationSummary:
    return SectorRotationSummary(
        as_of_date=_parse_date(payload.get("as_of_date")),
        quality=_quality(payload.get("quality")),
        warnings=_warnings(payload.get("warnings")),
        leading_sector=payload.get("leading_sector"),
        trailing_sector=payload.get("trailing_sector"),
        rotation_intensity_bp=payload.get("rotation_intensity_bp"),
        meta=payload.get("meta"),
    )


def _relative_strength_liquidity(payload: SnapshotJson) -> RelativeStrengthLiquiditySummary:
    return RelativeStrengthLiquiditySummary(
        as_of_date=_parse_date(payload.get("as_of_date")),
        quality=_quality(payload.get("quality")),
        warnings=_warnings(payload.get("warnings")),
        top_strength_codes=tuple(str(item) for item in _list(payload.get("top_strength_codes"))),
        weak_strength_codes=tuple(str(item) for item in _list(payload.get("weak_strength_codes"))),
        low_liquidity_codes=tuple(str(item) for item in _list(payload.get("low_liquidity_codes"))),
        meta=payload.get("meta"),
    )


def _watchlist_trigger(payload: SnapshotJson) -> WatchlistTriggerSummary:
    return WatchlistTriggerSummary(
        as_of_date=_parse_date(payload.get("as_of_date")),
        quality=_quality(payload.get("quality")),
        warnings=_warnings(payload.get("warnings")),
        trigger_count=payload.get("trigger_count"),
        triggered_codes=tuple(str(item) for item in _list(payload.get("triggered_codes"))),
        top_signal=payload.get("top_signal"),
    )


def _portfolio_alert(payload: SnapshotJson) -> PortfolioAlertSummary:
    attributions = tuple(
        PortfolioAlertAttribution(
            stock_code=str(item.get("stock_code") or ""),
            source_label=str(item.get("source_label") or ""),
            condition_status=str(item.get("condition_status") or ""),
            chip_risk_level=str(item.get("chip_risk_level") or ""),
            severity=int(item.get("severity") or 0),
            reasons=tuple(str(reason) for reason in _list(item.get("reasons"))),
            data_quality_flags=tuple(str(flag) for flag in _list(item.get("data_quality_flags"))),
        )
        for item in _list(payload.get("attributions"))
        if isinstance(item, dict)
    )
    return PortfolioAlertSummary(
        as_of_date=_parse_date(payload.get("as_of_date")),
        quality=_quality(payload.get("quality")),
        warnings=_warnings(payload.get("warnings")),
        alert_count=payload.get("alert_count"),
        alert_codes=tuple(str(item) for item in _list(payload.get("alert_codes"))),
        alert_level=payload.get("alert_level"),
        attributions=attributions,
    )


def _risk_prompt(payload: SnapshotJson) -> DecisionDeskRiskPromptSummary:
    prompts = tuple(
        DecisionDeskRiskPrompt(
            category=str(item.get("category") or "data_quality"),
            severity=str(item.get("severity") or "warning"),
            source=str(item.get("source") or ""),
            code=None if item.get("code") is None else str(item.get("code")),
            title=str(item.get("title") or ""),
            reason=str(item.get("reason") or ""),
            action_hint=str(item.get("action_hint") or ""),
        )
        for item in _list(payload.get("prompts"))
        if isinstance(item, dict)
    )
    return DecisionDeskRiskPromptSummary(
        as_of_date=_parse_date(payload.get("as_of_date")),
        quality=_quality(payload.get("quality")),
        warnings=_warnings(payload.get("warnings")),
        prompts=prompts,
    )


def section_is_ready(payload: SnapshotJson) -> bool:
    return _section_quality(payload) in {DecisionDeskQuality.OBSERVED.value, DecisionDeskQuality.ESTIMATED.value, DecisionDeskQuality.DEGRADED.value}
