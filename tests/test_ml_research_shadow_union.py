from __future__ import annotations

from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from data_module.ml_research_shadow_union import (
    PUBLICATION_SCHEMA_VERSION,
    RESEARCH_DATASET_ID,
    RESEARCH_TRAINING_MANIFEST_SCHEMA_VERSION,
    _CurrentValue,
    _CORPORATE_MICROSTRUCTURE_FEATURE_IDS,
    _FeatureDefinition,
    _RULE_PORTFOLIO_HEALTH_FEATURE_IDS,
    _ResearchTeacherCandidate,
    _blocked_corporate_microstructure_features,
    _causal_portfolio_state_features,
    _feature_pack_dispositions,
    _load_official_corporate_event_timeline,
    _official_corporate_microstructure_features,
    _research_target_for_decision,
    _research_teacher_policy_payload,
    _shadow_feature_snapshot,
    lock_research_training_manifest,
    validate_research_training_publication,
)
from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
)
from scripts.run_daily_ml_allocation_orchestration import (
    _load_frozen_release,
)


TAIPEI = ZoneInfo("Asia/Taipei")
ZERO_HASH = "sha256:" + ("0" * 64)


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _file_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _definition() -> _FeatureDefinition:
    return _FeatureDefinition(
        feature_id="fundamental_monthly_revenues.revenue",
        base_feature_id="fundamental_monthly_revenues.revenue",
        family_id="fundamental_growth_quality",
        source_id="sqlite.fundamental_monthly_revenues",
        source_table="fundamental_monthly_revenues",
        scale=10_000,
        stale_after_days=62,
        eligibility_status="research_shadow",
        record_hash=ZERO_HASH,
    )


def test_shadow_snapshot_is_missing_before_first_seen_and_never_zero_filled() -> None:
    decision = datetime(2020, 1, 2, 8, 30, tzinfo=TAIPEI).isoformat()
    features, missing_families, stats = _shadow_feature_snapshot(
        decision_at=decision,
        definitions=(_definition(),),
        current={},
    )

    feature = next(
        item
        for item in features
        if item["feature_id"] == "fundamental_monthly_revenues.revenue"
    )
    assert feature["observed"] is False
    assert feature["value_int"] is None
    assert feature["quality"] == "missing"
    assert feature["revision_id"] == "missing:not_observed_as_of_decision"
    assert missing_families == {"fundamental_growth_quality"}
    assert stats["observed"] == 0
    assert stats["missing"] == 1
    assert next(
        item
        for item in features
        if item["feature_id"]
        == "data_quality.fundamental_growth_quality.coverage_bp"
    )["value_int"] == 0


def test_shadow_snapshot_uses_only_available_nonstale_nonblocked_integer() -> None:
    definition = _definition()
    current = _CurrentValue(
        value_int=123_456,
        scale=10_000,
        event_at="2026-05-31T14:30:00+08:00",
        available_at="2026-06-17T13:41:50+08:00",
        revision_id="first-seen-v1",
        quality="observed",
        content_hash=ZERO_HASH,
        stale_after_days=62,
        missing_mask=False,
        quality_blocked_mask=False,
    )
    features, missing_families, stats = _shadow_feature_snapshot(
        decision_at="2026-06-18T08:30:00+08:00",
        definitions=(definition,),
        current={definition.feature_id: current},
    )
    feature = next(
        item for item in features if item["feature_id"] == definition.feature_id
    )
    assert feature["observed"] is True
    assert feature["value_int"] == 123_456
    assert missing_families == set()
    assert stats["observed"] == 1

    blocked = _CurrentValue(
        **{
            **current.__dict__,
            "quality_blocked_mask": True,
        }
    )
    blocked_features, blocked_families, blocked_stats = (
        _shadow_feature_snapshot(
            decision_at="2026-06-18T08:30:00+08:00",
            definitions=(definition,),
            current={definition.feature_id: blocked},
        )
    )
    blocked_feature = next(
        item
        for item in blocked_features
        if item["feature_id"] == definition.feature_id
    )
    assert blocked_feature["observed"] is False
    assert blocked_feature["value_int"] is None
    assert blocked_feature["revision_id"] == "missing:quality_blocked"
    assert blocked_families == {"fundamental_growth_quality"}
    assert blocked_stats["quality_blocked"] == 1


def _teacher_candidate(
    *,
    symbol: str,
    excess_bp: int,
    fill_feasible: bool = True,
    tail_loss_bp: int = 200,
    max_drawdown_bp: int = 300,
) -> _ResearchTeacherCandidate:
    return _ResearchTeacherCandidate(
        symbol=symbol,
        horizon_end_date="2025-02-03",
        available_at="2025-02-03T14:30:00+08:00",
        benchmark_excess_return_bp=excess_bp,
        tail_loss_bp=tail_loss_bp,
        max_drawdown_bp=max_drawdown_bp,
        fill_feasible_observed=fill_feasible,
    )


def test_research_teacher_emits_nonzero_constrained_allocation_targets() -> None:
    target = _research_target_for_decision(
        decision_date="2025-01-02",
        candidates=(
            _teacher_candidate(symbol="2330", excess_bp=500),
            _teacher_candidate(symbol="2317", excess_bp=300),
            _teacher_candidate(symbol="2454", excess_bp=100),
        ),
    )

    assert target["target_weights"] == {
        "positions_bp": [["2317", 500], ["2330", 1_500]],
        "cash_bp": 8_000,
    }
    assert target["delta_weights_bp"] == [
        ["2317", 500],
        ["2330", 1_500],
    ]
    assert target["risk_contributions_bp"] == [
        ["2317", 500],
        ["2330", 1_500],
    ]
    assert target["risky_budget_bp"] == 2_000
    assert target["cash_bp"] == 8_000
    assert target["rebalance_worthwhile"] is True


def test_research_teacher_fail_closed_candidate_filters_and_manifest_flags() -> None:
    target = _research_target_for_decision(
        decision_date="2025-01-02",
        candidates=(
            _teacher_candidate(
                symbol="2330",
                excess_bp=500,
                fill_feasible=False,
            ),
            _teacher_candidate(symbol="2317", excess_bp=-1),
        ),
    )
    policy = _research_teacher_policy_payload()

    assert target["target_weights"] == {
        "positions_bp": [],
        "cash_bp": 10_000,
    }
    assert target["delta_weights_bp"] == []
    assert target["risky_budget_bp"] == 0
    assert target["rebalance_worthwhile"] is False
    assert policy["snapshot_backfill_research_assumption"] is False
    assert (
        policy["unknown_sector_unique_bucket_research_assumption"]
        is True
    )
    assert policy["excluded_from_formal"] is True
    assert policy["formal_oos_allowed"] is False
    assert policy["production_alpha_bp"] == 0
    assert policy["promotion_eligible"] is False
    assert policy["recursive_paper_ledger_available"] is False
    assert policy["rule_portfolio_health_pack_used"] is False
    assert policy["targets_feed_next_state"] is False


def test_all_eight_feature_packs_have_explicit_research_disposition() -> None:
    present = (
        {
            "pack_id": "price_liquidity_technical",
            "feature_ids": ["price.close"],
        },
        {
            "pack_id": "market_sector_cross_section",
            "feature_ids": ["market.close"],
        },
        {
            "pack_id": "fundamental_growth_quality",
            "feature_ids": ["fundamental.revenue"],
        },
        {
            "pack_id": "valuation",
            "feature_ids": ["valuation.pe"],
        },
        {
            "pack_id": "flow_chip",
            "feature_ids": ["flow.foreign"],
        },
        {
            "pack_id": "data_quality",
            "feature_ids": ["quality.coverage"],
        },
        {
            "pack_id": "rule_portfolio_health",
            "feature_ids": list(_RULE_PORTFOLIO_HEALTH_FEATURE_IDS),
        },
        {
            "pack_id": "corporate_microstructure",
            "feature_ids": list(_CORPORATE_MICROSTRUCTURE_FEATURE_IDS),
        },
    )
    dispositions = {
        item["pack_id"]: item
        for item in _feature_pack_dispositions(present)
    }

    assert len(dispositions) == 8
    assert (
        dispositions["corporate_microstructure"]["status"]
        == "schema_registered_blocked_zero_coverage"
    )
    assert dispositions["corporate_microstructure"]["feature_count"] == 4
    assert dispositions["corporate_microstructure"]["declared_coverage_bp"] == 0
    assert (
        dispositions["rule_portfolio_health"]["status"]
        == "present_causal_state_only"
    )
    assert dispositions["rule_portfolio_health"]["feature_count"] == 6
    assert dispositions["rule_portfolio_health"]["declared_coverage_bp"] == 10_000
    assert all(
        item["formal_training_eligible"] is False
        for item in dispositions.values()
    )


def test_fixed_pack_features_use_causal_state_and_explicit_missing() -> None:
    weights = AllocationWeightContract(
        positions_bp=(("2330", 1_200),),
        cash_bp=8_800,
    )
    state = CausalPortfolioState.create(
        as_of_date="2025-01-01",
        weights=weights,
        weekly_turnover_used_bp=300,
    )
    row = {
        "portfolio_state": {
            "as_of_date": state.as_of_date,
            "weights": {
                "positions_bp": [["2330", 1_200]],
                "cash_bp": 8_800,
            },
            "weekly_turnover_used_bp": 300,
            "state_hash": state.state_hash,
        }
    }
    state_features = _causal_portfolio_state_features(
        row=row,
        decision_at="2025-01-02T08:30:00+08:00",
        symbol="2330",
    )
    values = {
        str(feature["feature_id"]): feature["value_int"]
        for feature in state_features
    }
    corporate = _blocked_corporate_microstructure_features(
        decision_at="2025-01-02T08:30:00+08:00"
    )

    assert values == {
        "rule_portfolio_health.cash_bp": 8_800,
        "rule_portfolio_health.current_symbol_weight_bp": 1_200,
        "rule_portfolio_health.invested_bp": 1_200,
        "rule_portfolio_health.position_count": 1,
        "rule_portfolio_health.state_complete_flag": 1,
        "rule_portfolio_health.weekly_turnover_used_bp": 300,
    }
    assert all(feature["observed"] is True for feature in state_features)
    assert len(corporate) == 4
    assert all(feature["observed"] is False for feature in corporate)
    assert all(feature["value_int"] is None for feature in corporate)
    assert all(feature["quality"] == "missing" for feature in corporate)
    assert all(
        feature["revision_id"]
        == "missing:official_event_manifest_not_delivered"
        for feature in corporate
    )


def _write_official_event_manifest(root: Path) -> Path:
    canonical = root / "canonical" / "events.jsonl"
    canonical.parent.mkdir(parents=True)
    common = {
        "schema_version": "official-market-event.v1",
        "source_id": "twse.halt",
        "symbol": "2330",
        "result_only": False,
        "formal_decision_feature_allowed": False,
        "formal_trading_restriction_allowed": True,
        "revision_availability_ambiguous": False,
    }
    rows = [
        {
            **common,
            "event_type": "trading_halt",
            "event_at": "2025-01-02T08:00:00+08:00",
            "available_at": "2025-01-02T08:00:00+08:00",
            "event_id": f"sha256:{'1' * 64}",
            "revision_id": f"sha256:{'2' * 64}",
            "source_record_hash": f"sha256:{'3' * 64}",
        },
        {
            **common,
            "event_type": "trading_resume",
            "event_at": "2025-01-03T08:00:00+08:00",
            "available_at": "2025-01-03T08:00:00+08:00",
            "event_id": f"sha256:{'4' * 64}",
            "revision_id": f"sha256:{'5' * 64}",
            "source_record_hash": f"sha256:{'6' * 64}",
        },
        {
            **common,
            "event_type": "trading_halt",
            "event_at": "2025-02-01T08:00:00+08:00",
            "available_at": "2025-02-01T08:00:00+08:00",
            "event_id": f"sha256:{'7' * 64}",
            "revision_id": f"sha256:{'8' * 64}",
            "source_record_hash": f"sha256:{'9' * 64}",
        },
        {
            "schema_version": "official-market-event.v1",
            "source_id": "twse.result",
            "symbol": "2330",
            "result_only": True,
            "formal_decision_feature_allowed": False,
            "formal_trading_restriction_allowed": False,
            "revision_availability_ambiguous": False,
            "event_type": "ex_right_dividend_result",
            "event_at": "2025-01-02T00:00:00+08:00",
            "available_at": "2025-01-02T23:59:59+08:00",
            "event_id": f"sha256:{'a' * 64}",
            "revision_id": f"sha256:{'b' * 64}",
            "source_record_hash": f"sha256:{'c' * 64}",
        },
    ]
    canonical.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    manifest: dict[str, object] = {
        "schema_version": "official-market-event-publication.v1",
        "status": "formal_source_publication",
        "canonical_events": {
            "schema_version": "official-market-event.v1",
            "path": "canonical/events.jsonl",
            "file_hash": _file_hash(canonical),
            "event_count": len(rows),
        },
        "coverage": [
            {
                "source_id": "twse.halt",
                "result_only": False,
                "complete_year_coverage": True,
                "requested_start_year": 2025,
                "requested_end_year": 2025,
            }
        ],
        "source_registry": {
            "sources": [
                {
                    "source_id": "twse.halt",
                    "result_only": False,
                    "allowed_uses": [
                        "formal_trading_restriction_timeline"
                    ],
                },
                {
                    "source_id": "twse.result",
                    "result_only": True,
                    "allowed_uses": ["formal_label", "formal_ledger"],
                },
            ]
        },
        "safety": {
            "append_only_canonical_events": True,
            "available_at_effective_at_separated": True,
            "formal_source_publication": True,
            "result_tables_label_ledger_only": True,
            "result_tables_decision_feature_allowed": False,
        },
    }
    manifest["manifest_hash"] = _sha256_json(manifest)
    path = root / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_official_halt_resume_is_causal_and_result_only_events_are_excluded(
    tmp_path: Path,
) -> None:
    timeline = _load_official_corporate_event_timeline(
        _write_official_event_manifest(tmp_path)
    )

    before = _official_corporate_microstructure_features(
        decision_at="2025-01-01T08:30:00+08:00",
        symbol="2330",
        timeline=timeline,
    )
    halted = _official_corporate_microstructure_features(
        decision_at="2025-01-02T08:30:00+08:00",
        symbol="2330",
        timeline=timeline,
    )
    resumed = _official_corporate_microstructure_features(
        decision_at="2025-01-03T08:30:00+08:00",
        symbol="2330",
        timeline=timeline,
    )

    def values(features: list[dict[str, object]]) -> dict[str, object]:
        return {
            str(feature["feature_id"]): feature["value_int"]
            for feature in features
        }

    assert timeline.result_only_event_count == 1
    assert timeline.decision_feature_event_count == 3
    assert values(before)["corporate_microstructure.suspension_flag"] == 0
    assert values(halted)["corporate_microstructure.suspension_flag"] == 1
    assert values(resumed)["corporate_microstructure.suspension_flag"] == 0
    assert (
        values(halted)[
            "corporate_microstructure.trading_restriction_flag"
        ]
        == 1
    )
    assert (
        values(halted)["corporate_microstructure.corporate_action_flag"]
        is None
    )
    assert (
        values(halted)["corporate_microstructure.limit_lock_flag"]
        is None
    )
    assert all(
        feature["available_at"] <= "2025-01-02T08:30:00+08:00"
        for feature in halted
    )


def _write_research_publication(root: Path) -> Path:
    root.mkdir(parents=True)
    shard_path = root / "year=2025.jsonl.gz"
    content = b'{"record_type":"header"}\n'
    with shard_path.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=1,
            fileobj=raw,
            mtime=0,
        ) as stream:
            stream.write(content)
    manifest: dict[str, object] = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "dataset_id": RESEARCH_DATASET_ID,
        "research_only": True,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "formal_consumer_compatible": False,
        "shards": [
            {
                "path": shard_path.name,
                "compressed_sha256": _file_hash(shard_path),
            }
        ],
    }
    manifest["manifest_hash"] = _sha256_json(manifest)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def test_research_publication_is_hash_bound_and_promotion_ineligible(
    tmp_path: Path,
) -> None:
    manifest_path = _write_research_publication(tmp_path / "union")
    shard_path = manifest_path.parent / "year=2025.jsonl.gz"
    payload = validate_research_training_publication(
        manifest_path, (shard_path,)
    )
    assert payload["research_only"] is True
    assert payload["formal_oos_allowed"] is False
    assert payload["production_alpha_bp"] == 0
    assert payload["promotion_eligible"] is False

    tampered = dict(payload)
    tampered["formal_oos_allowed"] = True
    tampered["manifest_hash"] = _sha256_json(
        {key: value for key, value in tampered.items() if key != "manifest_hash"}
    )
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="formal_oos_allowed"):
        validate_research_training_publication(manifest_path, (shard_path,))


def test_research_training_manifest_schema_is_rejected_by_formal_loader(
    tmp_path: Path,
) -> None:
    union_manifest = _write_research_publication(tmp_path / "union")
    generic_manifest = tmp_path / "training_manifest_research_v1.json"
    generic_manifest.write_text(
        json.dumps(
            {
                "schema_version": "allocation-training-manifest-v2",
                "dataset_id": RESEARCH_DATASET_ID,
                "production_alpha_bp": 0,
                "production_action_allowed": False,
                "formal_oos_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    locked = lock_research_training_manifest(
        generic_manifest_path=generic_manifest,
        union_manifest_path=union_manifest,
    )
    assert (
        locked["schema_version"]
        == RESEARCH_TRAINING_MANIFEST_SCHEMA_VERSION
    )
    assert locked["research_only"] is True
    assert locked["promotion_eligible"] is False
    assert locked["formal_consumer_compatible"] is False

    formal_root = tmp_path / "formal-release"
    formal_root.mkdir()
    (formal_root / "training_manifest_v2.json").write_text(
        generic_manifest.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported training manifest schema"):
        _load_frozen_release(formal_root)
