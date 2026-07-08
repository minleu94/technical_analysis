"""Read-only V3.0 effectiveness dashboard disclosure service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app_module.v3_effectiveness_dtos import V3EffectivenessReport


FORBIDDEN_DISCLOSURE_TERMS = ("買進", "賣出", "保證", "勝率保證")


@dataclass(frozen=True)
class V3EffectivenessDashboardRow:
    slice_id: str
    event_family: str
    event_type: str
    sample_count: int
    sample_sufficiency_label: str
    confidence_label: str
    gap_classification_summary: str
    disclosure: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "event_family": self.event_family,
            "event_type": self.event_type,
            "sample_count": self.sample_count,
            "sample_sufficiency_label": self.sample_sufficiency_label,
            "confidence_label": self.confidence_label,
            "gap_classification_summary": self.gap_classification_summary,
            "disclosure": self.disclosure,
        }


@dataclass(frozen=True)
class V3EffectivenessDashboardDTO:
    boundary_banner: str
    summary_cards: Mapping[str, int | str]
    rows: tuple[V3EffectivenessDashboardRow, ...]
    access_boundary: Mapping[str, bool | str]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary_banner": self.boundary_banner,
            "summary_cards": dict(self.summary_cards),
            "rows": [row.to_dict() for row in self.rows],
            "access_boundary": dict(self.access_boundary),
            "warnings": list(self.warnings),
        }


class V3EffectivenessDashboardService:
    def build_dashboard(
        self, report: V3EffectivenessReport
    ) -> V3EffectivenessDashboardDTO:
        rows = tuple(self._build_row(item) for item in report.slices)
        summary_cards: dict[str, int | str] = {
            "total_slice_count": len(rows),
            "insufficient_sample_count": sum(
                1
                for item in report.slices
                if item.sample_sufficiency_label == "insufficient_sample"
            ),
            "review_ready_count": sum(
                1
                for item in report.slices
                if item.sample_sufficiency_label == "review_ready"
            ),
            "manual_validation_status": report.manual_validation_status,
        }
        return V3EffectivenessDashboardDTO(
            boundary_banner=(
                "V3 effectiveness dashboard 是唯讀揭露，不是交易建議，"
                "不宣稱投資有效性，也不啟用 production scheduler。"
            ),
            summary_cards=summary_cards,
            rows=rows,
            access_boundary=report.access_boundary,
            warnings=report.warnings,
        )

    def _build_row(self, item: Any) -> V3EffectivenessDashboardRow:
        gap_summary = ", ".join(
            sorted({gap.classification for gap in item.gap_classifications})
        ) or "none"
        disclosure = self._disclosure_text(
            sample_sufficiency_label=item.sample_sufficiency_label,
            confidence_label=item.confidence_label,
            warnings=item.warnings,
        )
        self._assert_safe_disclosure(disclosure)
        return V3EffectivenessDashboardRow(
            slice_id=item.slice_id,
            event_family=item.event_family,
            event_type=item.event_type,
            sample_count=item.sample_count,
            sample_sufficiency_label=item.sample_sufficiency_label,
            confidence_label=item.confidence_label,
            gap_classification_summary=gap_summary,
            disclosure=disclosure,
        )

    def _disclosure_text(
        self,
        *,
        sample_sufficiency_label: str,
        confidence_label: str,
        warnings: tuple[str, ...],
    ) -> str:
        if sample_sufficiency_label == "insufficient_sample":
            return "樣本不足，只能列為工程觀察；不是交易建議。"
        if sample_sufficiency_label == "needs_manual_validation":
            return "需要人工驗證文案與門檻；不自動套用 lifecycle action。"
        if sample_sufficiency_label == "directional_only":
            return "僅供方向性工程覆盤；缺口與警告仍需揭露。"
        if confidence_label == "medium":
            return "可進入人工 review，但不代表投資有效性。"
        if warnings:
            return "可讀性較高但仍有 warning；需人工覆盤。"
        return "可進入人工 review；不產生任何自動動作。"

    def _assert_safe_disclosure(self, text: str) -> None:
        for term in FORBIDDEN_DISCLOSURE_TERMS:
            if term in text:
                raise ValueError(f"forbidden disclosure term: {term}")
