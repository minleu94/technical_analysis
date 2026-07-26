"""Fubon Shadow Feature Mapping & Computability Contract.

Provides provable, symbol-isolated, PIT-safe, research-only Fubon feature mapping,
lineage hashing, and per-component computability evaluation for Score, Recommendation,
Portfolio, and Exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Sequence

from data_module.fubon_pit_validator import FubonPITObservation


@dataclass(frozen=True)
class FubonFeatureMappingItem:
    """Single provable feature mapping definition from Fubon raw payload to downstream consumer."""

    raw_field: str
    normalized_field: str
    source_id: str
    source_version: str
    value_type: str
    unit: str
    symbol: str
    available_at: str
    decision_timestamp: str
    revision_id: str
    pit_rule: str
    intended_consumer: str
    consumer_reads_field: bool
    existing_authoritative_policy: str
    computability_status: str
    missing_evidence_or_blocker: str | None
    fallback_behavior: str
    quarantine_behavior: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_field": self.raw_field,
            "normalized_field": self.normalized_field,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "value_type": self.value_type,
            "unit": self.unit,
            "symbol": self.symbol,
            "available_at": self.available_at,
            "decision_timestamp": self.decision_timestamp,
            "revision_id": self.revision_id,
            "pit_rule": self.pit_rule,
            "intended_consumer": self.intended_consumer,
            "consumer_reads_field": self.consumer_reads_field,
            "existing_authoritative_policy": self.existing_authoritative_policy,
            "computability_status": self.computability_status,
            "missing_evidence_or_blocker": self.missing_evidence_or_blocker,
            "fallback_behavior": self.fallback_behavior,
            "quarantine_behavior": self.quarantine_behavior,
        }


@dataclass(frozen=True)
class ComponentComputabilityResult:
    """Per-component computability result for Score, Recommendation, Portfolio, and Exit."""

    component_name: str
    status: str  # "computed", "degraded", "not_computable", "quarantined"
    mapping_revision: str
    consumed_observation_ids: tuple[str, ...]
    consumed_fields: tuple[str, ...]
    decision_timestamp: str
    source_versions: tuple[str, ...]
    pit_validation_status: str
    calculation_lineage_hash: str
    blockers: tuple[str, ...]
    safety_flags: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "status": self.status,
            "mapping_revision": self.mapping_revision,
            "consumed_observation_ids": list(self.consumed_observation_ids),
            "consumed_fields": list(self.consumed_fields),
            "decision_timestamp": self.decision_timestamp,
            "source_versions": list(self.source_versions),
            "pit_validation_status": self.pit_validation_status,
            "calculation_lineage_hash": self.calculation_lineage_hash,
            "blockers": list(self.blockers),
            "safety_flags": dict(self.safety_flags),
        }


@dataclass(frozen=True)
class FubonShadowFeatureMappingResult:
    """Overall result of Fubon shadow feature mapping evaluation."""

    mapping_revision: str
    mapping_content_hash: str
    mapping_items: tuple[FubonFeatureMappingItem, ...]
    symbol_features_map: dict[str, dict[str, int]]
    consumed_fields: tuple[str, ...]
    unused_field_diagnostics: tuple[str, ...]
    component_results: dict[str, ComponentComputabilityResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_revision": self.mapping_revision,
            "mapping_content_hash": self.mapping_content_hash,
            "mapping_items": [item.to_dict() for item in self.mapping_items],
            "symbol_features_map": self.symbol_features_map,
            "consumed_fields": list(self.consumed_fields),
            "unused_field_diagnostics": list(self.unused_field_diagnostics),
            "component_results": {k: v.to_dict() for k, v in self.component_results.items()},
        }


# 已知的 Fubon 正規化欄位候選。這些欄位名稱尚未出現在既有 consumer 的
# 讀取契約中，因此只能作為 research-only 診斷，不能宣稱可計算。
PROVEN_FEATURE_REGISTRY: dict[str, dict[str, Any]] = {
    "is_disposition": {
        "normalized_field": "fubon_is_disposition",
        "value_type": "int",
        "unit": "binary_flag",
        "intended_consumer": "decision_module.strategy_configurator",
        "existing_authoritative_policy": "disposition_stock_risk_filter_and_penalty",
    },
    "matching_interval_seconds": {
        "normalized_field": "fubon_matching_interval",
        "value_type": "int",
        "unit": "seconds",
        "intended_consumer": "decision_module.strategy_configurator",
        "existing_authoritative_policy": "call_auction_interval_liquidity_penalty",
    },
    "is_suspended": {
        "normalized_field": "fubon_is_suspended",
        "value_type": "int",
        "unit": "binary_flag",
        "intended_consumer": "app_module.position_health_service",
        "existing_authoritative_policy": "suspended_halt_exit_risk_flag",
    },
    "limit_up_locked": {
        "normalized_field": "fubon_limit_up_locked",
        "value_type": "int",
        "unit": "binary_flag",
        "intended_consumer": "decision_module.strategy_configurator",
        "existing_authoritative_policy": "limit_up_momentum_boost",
    },
    "limit_down_locked": {
        "normalized_field": "fubon_limit_down_locked",
        "value_type": "int",
        "unit": "binary_flag",
        "intended_consumer": "app_module.position_health_service",
        "existing_authoritative_policy": "limit_down_exit_risk_flag",
    },
}


class FubonShadowFeatureMapping:
    """Builds symbol-isolated, PIT-safe feature mappings and component computability contracts."""

    def __init__(self, revision_id: str = "fubon-feature-mapping.v1") -> None:
        self.revision_id = revision_id

    def build_mapping(
        self,
        *,
        observations: Sequence[FubonPITObservation],
        decision_timestamp: str,
        position_context_supplied: bool = False,
        portfolio_requested: bool = False,
    ) -> FubonShadowFeatureMappingResult:
        """Map observations to symbol features and evaluate component computability."""
        mapping_items: list[FubonFeatureMappingItem] = []
        symbol_features_map: dict[str, dict[str, int]] = {}
        consumed_fields: set[str] = set()
        unused_diagnostics: list[str] = []
        consumed_obs_ids: list[str] = []
        source_versions: set[str] = set()

        has_quarantined = False

        for obs in observations:
            source_versions.add(obs.source_version)
            obs_id = f"{obs.source_id}:{obs.symbol}:{obs.available_at}"

            if obs.quarantine_status == "quarantined":
                has_quarantined = True
                unused_diagnostics.append(f"fubon_quarantined_observation_isolated:{obs.symbol}:{obs.source_id}")
                continue

            symbol = str(obs.symbol).strip()
            if symbol not in symbol_features_map:
                symbol_features_map[symbol] = {}

            consumed_obs_ids.append(obs_id)

            for raw_k, raw_v in obs.quantities.items():
                if raw_k in PROVEN_FEATURE_REGISTRY:
                    reg = PROVEN_FEATURE_REGISTRY[raw_k]
                    norm_field = reg["normalized_field"]
                    val_int = int(raw_v)

                    symbol_features_map[symbol][norm_field] = val_int
                    consumed_fields.add(norm_field)

                    mapping_items.append(
                        FubonFeatureMappingItem(
                            raw_field=raw_k,
                            normalized_field=norm_field,
                            source_id=obs.source_id,
                            source_version=obs.source_version,
                            value_type=reg["value_type"],
                            unit=reg["unit"],
                            symbol=symbol,
                            available_at=obs.available_at,
                            decision_timestamp=decision_timestamp,
                            revision_id=obs.revision_id,
                            pit_rule="available_at <= decision_timestamp",
                            intended_consumer=reg["intended_consumer"],
                            consumer_reads_field=False,
                            existing_authoritative_policy=reg["existing_authoritative_policy"],
                            computability_status="not_computable",
                            missing_evidence_or_blocker="authoritative_consumer_does_not_read_fubon_feature",
                            fallback_behavior="omit_feature_row_unchanged",
                            quarantine_behavior="quarantine_row_isolated",
                        )
                    )
                else:
                    unused_diagnostics.append(f"fubon_unmapped_quantity:{obs.symbol}:{raw_k}")

        mapping_json = json.dumps(
            [item.to_dict() for item in mapping_items],
            ensure_ascii=False,
            sort_keys=True,
        )
        content_hash = sha256(mapping_json.encode("utf-8")).hexdigest()

        # Evaluate component computability
        safety_flags = {
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_blend_alpha_bp": 0,
            "formal_rule_only_path_unchanged": True,
        }

        component_results: dict[str, ComponentComputabilityResult] = {}

        # 既有 Score／Recommendation／Portfolio／Exit consumer 均未讀取這些
        # shadow 欄位；不可將欄位附加到 DataFrame 後把不變的 baseline 當作
        # Fubon candidate。所有 component 因此 fail closed。
        consumer_blocker = "authoritative_consumer_does_not_read_fubon_feature"

        # 1. Score
        score_blockers: list[str] = [consumer_blocker]
        if has_quarantined and not mapping_items:
            score_status = "not_computable"
            score_blockers.append("pit_validation_blocked_or_quarantined")
        elif not mapping_items:
            score_blockers.append("no_proven_fubon_feature_mapped")
        score_status = "not_computable"

        score_lineage_hash = sha256(f"score:{content_hash}:{decision_timestamp}".encode()).hexdigest()
        component_results["score"] = ComponentComputabilityResult(
            component_name="score",
            status=score_status,
            mapping_revision=self.revision_id,
            consumed_observation_ids=tuple(consumed_obs_ids),
            consumed_fields=tuple(sorted(list(consumed_fields))),
            decision_timestamp=decision_timestamp,
            source_versions=tuple(sorted(list(source_versions))),
            pit_validation_status="blocked" if has_quarantined and not mapping_items else "passed",
            calculation_lineage_hash=score_lineage_hash,
            blockers=tuple(score_blockers),
            safety_flags=safety_flags,
        )

        # 2. Recommendation
        rec_blockers: list[str] = []
        rec_status = "not_computable"
        rec_blockers.extend(("score_candidate_not_computable", consumer_blocker))

        rec_lineage_hash = sha256(f"rec:{score_lineage_hash}".encode()).hexdigest()
        component_results["recommendation"] = ComponentComputabilityResult(
            component_name="recommendation",
            status=rec_status,
            mapping_revision=self.revision_id,
            consumed_observation_ids=tuple(consumed_obs_ids),
            consumed_fields=tuple(sorted(list(consumed_fields))),
            decision_timestamp=decision_timestamp,
            source_versions=tuple(sorted(list(source_versions))),
            pit_validation_status=component_results["score"].pit_validation_status,
            calculation_lineage_hash=rec_lineage_hash,
            blockers=tuple(rec_blockers),
            safety_flags=safety_flags,
        )

        # 3. Portfolio
        port_blockers: list[str] = []
        port_status = "not_computable"
        port_blockers.extend(("recommendation_candidate_not_computable", consumer_blocker))
        if not portfolio_requested:
            port_blockers.append("portfolio_request_not_supplied")

        port_lineage_hash = sha256(f"port:{rec_lineage_hash}".encode()).hexdigest()
        component_results["portfolio"] = ComponentComputabilityResult(
            component_name="portfolio",
            status=port_status,
            mapping_revision=self.revision_id,
            consumed_observation_ids=tuple(consumed_obs_ids),
            consumed_fields=tuple(sorted(list(consumed_fields))),
            decision_timestamp=decision_timestamp,
            source_versions=tuple(sorted(list(source_versions))),
            pit_validation_status=component_results["score"].pit_validation_status,
            calculation_lineage_hash=port_lineage_hash,
            blockers=tuple(port_blockers),
            safety_flags=safety_flags,
        )

        # 4. Exit
        exit_blockers: list[str] = []
        exit_status = "not_computable"
        exit_blockers.append(consumer_blocker)
        if not position_context_supplied:
            exit_blockers.append("position_health_context_not_supplied")
        elif score_status != "computed":
            exit_blockers.append("microstructure_signals_not_computable")

        exit_lineage_hash = sha256(f"exit:{content_hash}:{position_context_supplied}".encode()).hexdigest()
        component_results["exit"] = ComponentComputabilityResult(
            component_name="exit",
            status=exit_status,
            mapping_revision=self.revision_id,
            consumed_observation_ids=tuple(consumed_obs_ids),
            consumed_fields=tuple(sorted(list(consumed_fields))),
            decision_timestamp=decision_timestamp,
            source_versions=tuple(sorted(list(source_versions))),
            pit_validation_status=component_results["score"].pit_validation_status,
            calculation_lineage_hash=exit_lineage_hash,
            blockers=tuple(exit_blockers),
            safety_flags=safety_flags,
        )

        return FubonShadowFeatureMappingResult(
            mapping_revision=self.revision_id,
            mapping_content_hash=content_hash,
            mapping_items=tuple(mapping_items),
            symbol_features_map=symbol_features_map,
            consumed_fields=tuple(sorted(list(consumed_fields))),
            unused_field_diagnostics=tuple(sorted(list(set(unused_diagnostics)))),
            component_results=component_results,
        )

    def get_symbol_features(
        self, result: FubonShadowFeatureMappingResult, symbol: str
    ) -> dict[str, int]:
        """Retrieve provable mapped features for a specific stock code."""
        return result.symbol_features_map.get(str(symbol).strip(), {})
