from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app_module.evidence_event_dtos import EvidenceEvent


READ_ONLY_COMPONENT_ACCESS_BOUNDARY = {
    "writes_allowed": False,
    "backfill_allowed": False,
    "recompute_legacy_recommendations_allowed": False,
    "production_decision_allowed": False,
    "production_scheduler_allowed": False,
}

COMPONENT_REPORT_LIMITATIONS = (
    "Component ablation 只能使用決策當下已保存的 component score metadata。",
    "舊 evidence 若缺 component payload，僅輸出缺口診斷，不回補、不重算舊推薦。",
    "本報告只供 shadow/read-only readiness 判讀，不改 ScoringEngine 或推薦權重。",
)


@dataclass(frozen=True)
class ComponentSetDefinition:
    component_set_id: str
    label: str
    components: tuple[str, ...]


COMPONENT_SETS = (
    ComponentSetDefinition("technical_only", "technical only", ("technical",)),
    ComponentSetDefinition("pattern_only", "pattern only", ("pattern",)),
    ComponentSetDefinition("volume_only", "volume only", ("volume",)),
    ComponentSetDefinition("technical_pattern", "technical + pattern", ("technical", "pattern")),
    ComponentSetDefinition("technical_volume", "technical + volume", ("technical", "volume")),
    ComponentSetDefinition("pattern_volume", "pattern + volume", ("pattern", "volume")),
    ComponentSetDefinition(
        "technical_pattern_volume",
        "technical + pattern + volume",
        ("technical", "pattern", "volume"),
    ),
)


@dataclass(frozen=True)
class ComponentAblationReadinessRow:
    component_set_id: str
    label: str
    components: tuple[str, ...]
    status: str
    available_event_count: int
    missing_event_count: int
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["components"] = list(self.components)
        payload["diagnostics"] = list(self.diagnostics)
        return payload


@dataclass(frozen=True)
class ComponentAblationReadinessReport:
    generated_at: str
    source_mode: str
    component_sets: tuple[ComponentAblationReadinessRow, ...]
    access_boundary: dict[str, bool]
    limitations: tuple[str, ...]
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "source_mode": self.source_mode,
            "component_sets": [row.to_dict() for row in self.component_sets],
            "access_boundary": dict(self.access_boundary),
            "limitations": list(self.limitations),
            "diagnostics": list(self.diagnostics),
        }


class ComponentAblationReadinessService:
    """Inspect whether saved evidence can support component ablation."""

    def __init__(self, *, events: Iterable[EvidenceEvent], source_mode: str = "in_memory") -> None:
        self.events = tuple(events)
        self.source_mode = source_mode

    def build_report(self) -> ComponentAblationReadinessReport:
        rows = []
        report_diagnostics: set[str] = set()
        for component_set in COMPONENT_SETS:
            available = sum(1 for event in self.events if _has_components(event, component_set.components))
            missing = len(self.events) - available
            diagnostics: list[str] = []
            if missing:
                diagnostics.extend(["component_payload_missing", "new_evidence_metadata_required"])
                report_diagnostics.update(diagnostics)
            status = "ready_for_shadow_ablation" if self.events and missing == 0 else "component_payload_missing"
            rows.append(
                ComponentAblationReadinessRow(
                    component_set_id=component_set.component_set_id,
                    label=component_set.label,
                    components=component_set.components,
                    status=status,
                    available_event_count=available,
                    missing_event_count=missing,
                    diagnostics=tuple(sorted(set(diagnostics))),
                )
            )
        return ComponentAblationReadinessReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_mode=self.source_mode,
            component_sets=tuple(rows),
            access_boundary=dict(READ_ONLY_COMPONENT_ACCESS_BOUNDARY),
            limitations=COMPONENT_REPORT_LIMITATIONS,
            diagnostics=tuple(sorted(report_diagnostics)),
        )


def _has_components(event: EvidenceEvent, components: tuple[str, ...]) -> bool:
    metadata = event.metadata
    scores = metadata.get("component_scores_bp")
    if isinstance(scores, dict):
        return all(_has_int_score(scores.get(component)) for component in components)
    legacy_aliases = {
        "technical": ("technical_score_bp", "indicator_score_bp"),
        "pattern": ("pattern_score_bp",),
        "volume": ("volume_score_bp",),
    }
    return all(
        any(_has_int_score(metadata.get(alias)) for alias in legacy_aliases[component])
        for component in components
    )


def _has_int_score(value: object) -> bool:
    return isinstance(value, int) and 0 <= value <= 10000
