"""Immutable contracts for Terra Development Dataset V0."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class DevelopmentGenerationRequest:
    """A bounded generation request with an explicit 252-day universe policy."""

    generation_id: str
    decision_date_start: str
    decision_date_end: str
    training_as_of: str
    evaluation_as_of: str
    new_holdout_start: str
    usage_decision_sha256: str
    minimum_observed_history_days: int = 252
    max_decision_dates: int | None = None

    def __post_init__(self) -> None:
        if not self.generation_id.strip():
            raise ValueError("generation_id is required")
        if self.minimum_observed_history_days != 252:
            raise ValueError("minimum_observed_history_days must remain 252")
        if self.max_decision_dates is not None and self.max_decision_dates <= 0:
            raise ValueError("max_decision_dates must be positive when provided")
        if not self.usage_decision_sha256.startswith("sha256:"):
            raise ValueError("usage_decision_sha256 is required")


@dataclass(frozen=True)
class DevelopmentDatasetManifest:
    """Safety flags that cannot describe a formal or production dataset."""

    dataset_status: Literal["research_only_degraded"]
    formal_oos_allowed: Literal[False] = False
    production_blend_alpha_bp: Literal[0] = 0
    formal_rule_only_path_unchanged: Literal[True] = True
    zero_formal_write: Literal[True] = True
    generation_id: str = "unspecified"
    dataset_id: str = "unspecified"
    feature_registry_hash: str = ""
    label_registry_hash: str = ""
    source_fingerprints: tuple[tuple[str, str], ...] = ()
    decision_date_start: str = ""
    decision_date_end: str = ""
    training_as_of: str = ""
    evaluation_as_of: str = ""
    fit_row_count: int = 0
    evaluation_row_count: int = 0
    accepted_diagnostics: tuple[tuple[str, int], ...] = ()
    excluded_diagnostics: tuple[tuple[str, int], ...] = ()
    content_hash: str = ""
    manifest_hash: str = ""
    universe_policy_id: str = "conservative_observed_history"
    minimum_observed_history_days: int = 252
    selected_universe_symbol_count: int = 0
    corporate_action_coverage: Literal["research_only_degraded"] = "research_only_degraded"
    corporate_action_blockers: tuple[str, ...] = ()
    new_holdout_start: str = ""
    usage_decision_sha256: str = ""

    def __post_init__(self) -> None:
        if self.formal_oos_allowed is not False:
            raise ValueError("formal_oos_allowed must remain false")
        if self.production_blend_alpha_bp != 0:
            raise ValueError("production_blend_alpha_bp must remain zero")
        if self.formal_rule_only_path_unchanged is not True:
            raise ValueError("formal_rule_only_path_unchanged must remain true")
        if self.zero_formal_write is not True:
            raise ValueError("zero_formal_write must remain true")
        if self.fit_row_count < 0 or self.evaluation_row_count < 0:
            raise ValueError("row counts must not be negative")
        if self.universe_policy_id != "conservative_observed_history":
            raise ValueError("universe_policy_id must remain conservative_observed_history")
        if self.minimum_observed_history_days != 252:
            raise ValueError("minimum_observed_history_days must remain 252")
        if self.selected_universe_symbol_count < 0:
            raise ValueError("selected_universe_symbol_count must not be negative")
        if self.corporate_action_coverage != "research_only_degraded":
            raise ValueError("corporate_action_coverage must remain research_only_degraded")

    @classmethod
    def minimal(
        cls,
        *,
        formal_oos_allowed: bool = False,
        production_blend_alpha_bp: int = 0,
    ) -> "DevelopmentDatasetManifest":
        return cls(
            dataset_status="research_only_degraded",
            formal_oos_allowed=formal_oos_allowed,  # type: ignore[arg-type]
            production_blend_alpha_bp=production_blend_alpha_bp,  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "terra-development-dataset.v0",
            "generation_id": self.generation_id,
            "dataset_id": self.dataset_id,
            "dataset_status": self.dataset_status,
            "formal_oos_allowed": self.formal_oos_allowed,
            "production_blend_alpha_bp": self.production_blend_alpha_bp,
            "formal_rule_only_path_unchanged": self.formal_rule_only_path_unchanged,
            "zero_formal_write": self.zero_formal_write,
            "feature_registry_hash": self.feature_registry_hash,
            "label_registry_hash": self.label_registry_hash,
            "source_fingerprints": dict(self.source_fingerprints),
            "decision_date_start": self.decision_date_start,
            "decision_date_end": self.decision_date_end,
            "training_as_of": self.training_as_of,
            "evaluation_as_of": self.evaluation_as_of,
            "fit_row_count": self.fit_row_count,
            "evaluation_row_count": self.evaluation_row_count,
            "accepted_diagnostics": dict(self.accepted_diagnostics),
            "excluded_diagnostics": dict(self.excluded_diagnostics),
            "content_hash": self.content_hash,
            "manifest_hash": self.manifest_hash,
            "universe_policy_id": self.universe_policy_id,
            "minimum_observed_history_days": self.minimum_observed_history_days,
            "selected_universe_symbol_count": self.selected_universe_symbol_count,
            "corporate_action_coverage": self.corporate_action_coverage,
            "corporate_action_blockers": list(self.corporate_action_blockers),
            "new_holdout_start": self.new_holdout_start,
            "usage_decision_sha256": self.usage_decision_sha256,
        }

    @staticmethod
    def canonical_sha256(value: object) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class GenerationWriteResult:
    """Append-only output locations for one completed generation."""

    generation_directory: "Path"
    manifest_path: "Path"
    dataset_path: "Path"
