"""TASK-LOOP-02 市場閉環的應用層 DTO。

這個模組只負責把市場服務的結果包成可跨頁傳遞、可序列化的邊界物件。
資料來源、日期降級與品質判斷仍由服務層決定；UI 不應從 DTO 之外重新查詢或
重算排名。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping


def _date_value(value: object) -> date | None:
    """將已知日期表示正規化；無法辨識時回傳 None，不猜測日期。"""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _quality_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _warnings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item for item in value.split("|") if item)
    if isinstance(value, (tuple, list, set)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if value.__class__.__module__.startswith("numpy") and hasattr(value, "item"):
        return _json_value(value.item())
    return value


@dataclass(frozen=True)
class MarketRegimeDTO:
    """市場狀態結果，保留決策日與實際資料日。"""

    decision_date: date | None
    effective_date: date | None
    regime: str | None
    regime_name_cn: str | None
    match_score_bp: int | None
    quality: str
    warnings: tuple[str, ...] = ()
    source_id: str = "market_regime_detector"
    source_version: str = "legacy-regime-service"
    details: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_date", _date_value(self.decision_date))
        object.__setattr__(self, "effective_date", _date_value(self.effective_date))
        object.__setattr__(self, "match_score_bp", None if self.match_score_bp is None else int(self.match_score_bp))
        object.__setattr__(self, "quality", _quality_value(self.quality))
        object.__setattr__(self, "warnings", _warnings(self.warnings))
        object.__setattr__(self, "details", _mapping(self.details))

    @classmethod
    def from_legacy(
        cls,
        result: object,
        *,
        decision_date: date | None = None,
        effective_date: date | None = None,
        quality: str = "observed",
        warnings: tuple[str, ...] = (),
        source_id: str = "market_regime_detector",
    ) -> "MarketRegimeDTO":
        regime = getattr(result, "regime", None)
        regime_name_cn = getattr(result, "regime_name_cn", None)
        raw_confidence = getattr(result, "confidence", None)
        score_bp: int | None = None
        if raw_confidence is not None:
            try:
                # Regime 信心僅以整數基點跨層傳遞；相容舊 DTO 時不在金融核心
                # 以二進位浮點重新計算。
                score_bp = int(
                    (Decimal(str(raw_confidence)) * Decimal("10000")).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )
            except (TypeError, ValueError, ArithmeticError):
                score_bp = None
        details = getattr(result, "details", {})
        return cls(
            decision_date=decision_date,
            effective_date=effective_date,
            regime=None if regime is None else str(regime),
            regime_name_cn=None if regime_name_cn is None else str(regime_name_cn),
            match_score_bp=score_bp,
            quality=quality,
            warnings=warnings,
            source_id=source_id,
            details=details,
        )

    def to_legacy(self) -> Any:
        """只在舊 UI 相容邊界建立舊 DTO，不讓它成為服務間契約。"""

        from app_module.dtos import RegimeResultDTO

        confidence: Any = self.match_score_bp
        if confidence is not None:
            confidence = Decimal(confidence) / Decimal("10000")
        else:
            confidence = Decimal("0")
        return RegimeResultDTO(
            regime=self.regime or "Unknown",
            confidence=confidence,
            details=dict(self.details or {}),
            regime_name_cn=self.regime_name_cn or (self.regime or "未知"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "regime": self.regime,
            "regime_name_cn": self.regime_name_cn,
            "match_score_bp": self.match_score_bp,
            "quality": self.quality,
            "warnings": list(self.warnings),
            "source_id": self.source_id,
            "source_version": self.source_version,
            "details": _json_value(self.details or {}),
        }


@dataclass(frozen=True)
class MarketBreadthDTO:
    decision_date: date | None
    effective_date: date | None
    quality: str
    advancing: int | None = None
    declining: int | None = None
    unchanged: int | None = None
    breadth_ratio_bp: int | None = None
    warnings: tuple[str, ...] = ()
    source_id: str = "market_breadth_service"
    source_version: str = "market-breadth-v1"
    meta: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_date", _date_value(self.decision_date))
        object.__setattr__(self, "effective_date", _date_value(self.effective_date))
        object.__setattr__(self, "quality", _quality_value(self.quality))
        object.__setattr__(self, "warnings", _warnings(self.warnings))
        object.__setattr__(self, "meta", _mapping(self.meta))
        for field_name in ("advancing", "declining", "unchanged", "breadth_ratio_bp"):
            raw = getattr(self, field_name)
            object.__setattr__(self, field_name, None if raw is None else int(raw))

    @classmethod
    def from_summary(cls, summary: object, *, decision_date: date | None = None) -> "MarketBreadthDTO":
        meta = getattr(summary, "meta", None) or {}
        return cls(
            decision_date=decision_date,
            effective_date=getattr(summary, "as_of_date", None),
            quality=getattr(summary, "quality", "missing"),
            advancing=getattr(summary, "advancing", None),
            declining=getattr(summary, "declining", None),
            unchanged=getattr(summary, "unchanged", None),
            breadth_ratio_bp=getattr(summary, "breadth_ratio_bp", None),
            warnings=getattr(summary, "warnings", ()),
            source_id=str(meta.get("source") or "market_breadth_service"),
            meta=meta,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "quality": self.quality,
            "advancing": self.advancing,
            "declining": self.declining,
            "unchanged": self.unchanged,
            "breadth_ratio_bp": self.breadth_ratio_bp,
            "warnings": list(self.warnings),
            "source_id": self.source_id,
            "source_version": self.source_version,
            "meta": _json_value(self.meta or {}),
        }


@dataclass(frozen=True)
class SectorRotationDTO:
    decision_date: date | None
    effective_date: date | None
    quality: str
    leading_sector: str | None = None
    trailing_sector: str | None = None
    rotation_intensity_bp: int | None = None
    ranking: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    source_id: str = "sector_rotation_service"
    source_version: str = "sector-rotation-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_date", _date_value(self.decision_date))
        object.__setattr__(self, "effective_date", _date_value(self.effective_date))
        object.__setattr__(self, "quality", _quality_value(self.quality))
        object.__setattr__(self, "warnings", _warnings(self.warnings))
        object.__setattr__(self, "rotation_intensity_bp", None if self.rotation_intensity_bp is None else int(self.rotation_intensity_bp))
        object.__setattr__(self, "ranking", tuple(_mapping(item) for item in self.ranking))

    @classmethod
    def from_summary(cls, summary: object, *, decision_date: date | None = None) -> "SectorRotationDTO":
        meta = getattr(summary, "meta", None) or {}
        ranking = meta.get("sector_ranking", meta.get("ranking", ())) if isinstance(meta, Mapping) else ()
        return cls(
            decision_date=decision_date,
            effective_date=getattr(summary, "as_of_date", None),
            quality=getattr(summary, "quality", "missing"),
            leading_sector=getattr(summary, "leading_sector", None),
            trailing_sector=getattr(summary, "trailing_sector", None),
            rotation_intensity_bp=getattr(summary, "rotation_intensity_bp", None),
            ranking=tuple(ranking) if isinstance(ranking, (tuple, list)) else (),
            warnings=getattr(summary, "warnings", ()),
            source_id=str(meta.get("source") or "sector_rotation_service") if isinstance(meta, Mapping) else "sector_rotation_service",
            source_version="sector-rotation-v1",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "quality": self.quality,
            "leading_sector": self.leading_sector,
            "trailing_sector": self.trailing_sector,
            "rotation_intensity_bp": self.rotation_intensity_bp,
            "ranking": _json_value(self.ranking),
            "warnings": list(self.warnings),
            "source_id": self.source_id,
            "source_version": self.source_version,
        }


@dataclass(frozen=True)
class RelativeStrengthLiquidityDTO:
    decision_date: date | None
    effective_date: date | None
    quality: str
    top_strength_codes: tuple[str, ...] = ()
    weak_strength_codes: tuple[str, ...] = ()
    low_liquidity_codes: tuple[str, ...] = ()
    ranking: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    source_id: str = "relative_strength_liquidity_service"
    source_version: str = "relative-strength-liquidity-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_date", _date_value(self.decision_date))
        object.__setattr__(self, "effective_date", _date_value(self.effective_date))
        object.__setattr__(self, "quality", _quality_value(self.quality))
        object.__setattr__(self, "warnings", _warnings(self.warnings))
        object.__setattr__(self, "top_strength_codes", tuple(str(item) for item in self.top_strength_codes))
        object.__setattr__(self, "weak_strength_codes", tuple(str(item) for item in self.weak_strength_codes))
        object.__setattr__(self, "low_liquidity_codes", tuple(str(item) for item in self.low_liquidity_codes))
        object.__setattr__(self, "ranking", tuple(_mapping(item) for item in self.ranking))

    @classmethod
    def from_summary(cls, summary: object, *, decision_date: date | None = None) -> "RelativeStrengthLiquidityDTO":
        meta = getattr(summary, "meta", None) or {}
        ranking = meta.get("ranking", ()) if isinstance(meta, Mapping) else ()
        return cls(
            decision_date=decision_date,
            effective_date=getattr(summary, "as_of_date", None),
            quality=getattr(summary, "quality", "missing"),
            top_strength_codes=getattr(summary, "top_strength_codes", ()),
            weak_strength_codes=getattr(summary, "weak_strength_codes", ()),
            low_liquidity_codes=getattr(summary, "low_liquidity_codes", ()),
            ranking=tuple(ranking) if isinstance(ranking, (tuple, list)) else (),
            warnings=getattr(summary, "warnings", ()),
            source_id=str(meta.get("source") or "relative_strength_liquidity_service") if isinstance(meta, Mapping) else "relative_strength_liquidity_service",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "quality": self.quality,
            "top_strength_codes": list(self.top_strength_codes),
            "weak_strength_codes": list(self.weak_strength_codes),
            "low_liquidity_codes": list(self.low_liquidity_codes),
            "ranking": _json_value(self.ranking),
            "warnings": list(self.warnings),
            "source_id": self.source_id,
            "source_version": self.source_version,
        }


@dataclass(frozen=True)
class ScreeningResultDTO:
    """強弱排名結果；rows 是跨 UI 邊界的唯讀快照。"""

    result_kind: str
    direction: str
    period: str
    decision_date: date | None
    effective_date: date | None
    quality: str
    eligible_universe_size: int
    rows: tuple[Mapping[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    source_id: str = "screening_service"
    source_version: str = "screening-v1"
    ranking_method: str = "legacy-stock-screener"

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_kind", str(self.result_kind))
        object.__setattr__(self, "direction", str(self.direction))
        object.__setattr__(self, "period", str(self.period))
        object.__setattr__(self, "decision_date", _date_value(self.decision_date))
        object.__setattr__(self, "effective_date", _date_value(self.effective_date))
        object.__setattr__(self, "quality", _quality_value(self.quality))
        object.__setattr__(self, "eligible_universe_size", max(0, int(self.eligible_universe_size)))
        object.__setattr__(self, "rows", tuple(_mapping(row) for row in self.rows))
        object.__setattr__(self, "warnings", _warnings(self.warnings))

    @classmethod
    def from_legacy(
        cls,
        result: object,
        *,
        direction: str,
        period: str,
        decision_date: date | None = None,
        effective_date: date | None = None,
        quality: str = "observed",
        warnings: tuple[str, ...] = (),
        source_id: str = "screening_service",
        result_kind: str = "stocks",
        ranking_method: str = "legacy-stock-screener",
        eligible_universe_size: int | None = None,
    ) -> "ScreeningResultDTO":
        frame = result[0] if isinstance(result, tuple) and len(result) == 2 else result
        universe = result[1] if isinstance(result, tuple) and len(result) == 2 else None
        rows: tuple[Mapping[str, Any], ...] = ()
        row_count = 0
        if hasattr(frame, "to_dict") and hasattr(frame, "columns"):
            records = frame.to_dict(orient="records")
            rows = tuple(_mapping(record) for record in records)
            row_count = len(records)
        try:
            eligible = (
                int(eligible_universe_size)
                if eligible_universe_size is not None
                else int(universe) if universe is not None else row_count
            )
        except (TypeError, ValueError):
            eligible = row_count
        return cls(
            result_kind=result_kind,
            direction=direction,
            period=period,
            decision_date=decision_date,
            effective_date=effective_date,
            quality=quality,
            eligible_universe_size=eligible,
            rows=rows,
            warnings=warnings,
            source_id=source_id,
            ranking_method=ranking_method,
        )

    def to_dataframe(self) -> Any:
        import pandas as pd

        return pd.DataFrame([dict(row) for row in self.rows])

    def to_legacy(self) -> Any:
        frame = self.to_dataframe()
        if self.result_kind == "stocks":
            return frame, self.eligible_universe_size
        return frame

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_kind": self.result_kind,
            "direction": self.direction,
            "period": self.period,
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "quality": self.quality,
            "eligible_universe_size": self.eligible_universe_size,
            "rows": _json_value(self.rows),
            "warnings": list(self.warnings),
            "source_id": self.source_id,
            "source_version": self.source_version,
            "ranking_method": self.ranking_method,
        }


# 明確命名的相容別名，避免各呼叫端自行建立第二套 DTO。
MarketRegimeResultDTO = MarketRegimeDTO
MarketBreadthResultDTO = MarketBreadthDTO
SectorRotationResultDTO = SectorRotationDTO
RelativeStrengthLiquidityResultDTO = RelativeStrengthLiquidityDTO
RankingResultDTO = ScreeningResultDTO
