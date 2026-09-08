from __future__ import annotations

import json
from pathlib import Path

import pytest

import data_module.ml_research_shadow_overlay_integration as integration_module
from data_module.ml_research_shadow_overlay_integration import (
    ResearchShadowIntegrationError,
    _payload_hash,
    build_research_shadow_overlay_direct_readback,
)
from data_module.portfolio_ml_dataset_assembler import (
    build_teacher_source_row_provenance_for_assembly,
)
from data_module.portfolio_ml_target_diagnostics import (
    evaluate_allocation_teacher_eligibility,
)
from tests.test_teacher_input_source_producer import (
    _decision_rows,
    _diagnostics,
    _source_fixture,
    _target_summary,
)


_OVERLAY = Path(
    "output/v4_ml_daily_price_source_quality_20260907/"
    "canonical_overlay_20260520_official_v1.json"
)
_REPLAY = Path(
    "output/v4_ml_daily_price_overlay_impact_20260907/"
    "research_label_replay_20260520_h20_v3.json"
)
_UNION = Path(
    r"D:/Min/Python/Project/FA_Data/output/release_v4/"
    r"ml_research_shadow_union_full_v4_official_events/runs/"
    r"research-union-c385b17c541f2a132d05efa6/manifest.json"
)
_PIT_MANIFEST = Path(
    "output/v4_ml_shared_pit_consumer_20260907/publication/runs/"
    "pit-shared-14127774a7ded93cd564fdcf/manifest.json"
)
_PIT_STORE = Path("output/v4_ml_shared_pit_consumer_20260907/registry")
_DIRECT_MANIFEST = Path(
    "output/v4_ml_direct_shared_consumer_20260907_bounded/runs/"
    "direct-ooc-415dba364b4dacbe583b9284/manifest.json"
)
_BOUNDED_UNION = Path(
    "output/v4_ml_research_shadow_union_bounded_20260907_v2/union/runs/"
    "research-union-8521935985bcf1c60a1a049b/manifest.json"
)
_BOUNDED_PIT_MANIFEST = Path(
    "output/v4_ml_research_shadow_union_bounded_20260907_v2/"
    "shared_pit_publication/runs/"
    "pit-shared-4392435e587e2b895e07f5fe/manifest.json"
)
_BOUNDED_PIT_STORE = Path(
    "output/v4_ml_research_shadow_union_bounded_20260907_v2/"
    "shared_pit_store"
)


def test_synthetic_teacher_source_to_assembler_gate_is_explicitly_research_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合成來源可驗證 producer→assembler→gate，但不可冒充正式 custody。"""

    monkeypatch.setenv(
        "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY",
        "teacher-source-test-key",
    )
    monkeypatch.setenv(
        "RULE_CHAMPION_CONTROLLED_STORE_ID",
        "teacher-source-test-store",
    )
    sources = _source_fixture(tmp_path / "synthetic-sources")
    provenance = build_teacher_source_row_provenance_for_assembly(
        source_paths=sources,
        output_root=tmp_path / "synthetic-provenance",
        decision_dates=("2020-01-02",),
        decision_cutoffs={"2020-01-02": "2020-01-02T08:30:00+08:00"},
        decision_rows=_decision_rows(),
    )
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(),
        teacher_target_diagnostics=_diagnostics(),
        teacher_input_provenance=provenance,
    )
    assert provenance["source_rows_are_artifact_rebuilt"] is True
    assert provenance["source_availability_proven"] is True
    assert gate["allowed"] is True
    assert gate["formal_oos_allowed"] is False
    assert gate["broker_order_allowed"] is False
    assert gate["production_alpha_bp"] == 0
    # source_nature 是 QA 文件的外層標記；producer provenance 本身只保存
    # 可驗證來源契約，不能靠一個自述欄位把合成資料升格為正式 custody。
    assert all(
        str(path).startswith(str(tmp_path.resolve()))
        for path in sources.values()
    )


@pytest.mark.skipif(
    not all(path.exists() for path in (_OVERLAY, _REPLAY)),
    reason="accepted overlay/replay artifacts are not present",
)
def test_official_comparison_content_hash_is_verified_against_overlay_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只改官方 comparison 內容即使保留 overlay 宣告也必須拒絕。"""

    from data_module.twse_historical_daily_capture import load_twse_capture

    overlay_payload = json.loads(_OVERLAY.read_text(encoding="utf-8"))
    comparison_path = Path(
        str(overlay_payload["official_capture"]["comparison_path"])
    )
    receipt, comparison = load_twse_capture(comparison_path.parent)
    tampered_comparison = dict(comparison)
    tampered_comparison["rows"] = []
    # 保留原 overlay 的 comparison_hash，模擬 nested source 被改寫而
    # 外層 metadata 未同步；深層 verifier 應在讀取任何下游資料前拒絕。
    tampered_comparison["comparison_hash"] = overlay_payload[
        "official_capture"
    ]["comparison_hash"]
    monkeypatch.setattr(
        integration_module,
        "load_twse_capture",
        lambda _capture_directory: (receipt, tampered_comparison),
    )
    with pytest.raises(
        ResearchShadowIntegrationError,
        match="official capture comparison.comparison_hash mismatch",
    ):
        integration_module._load_overlay_and_replay(
            overlay_path=_OVERLAY,
            label_replay_path=_REPLAY,
        )


@pytest.mark.skipif(
    not all(path.exists() for path in (_OVERLAY, _REPLAY)),
    reason="accepted overlay/replay artifacts are not present",
)
def test_official_receipt_content_hash_is_verified_before_downstream_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """receipt 的宣告日期被改寫時，不能只因外層 hash 格式正確而通過。"""

    from data_module.twse_historical_daily_capture import load_twse_capture

    overlay_payload = json.loads(_OVERLAY.read_text(encoding="utf-8"))
    comparison_path = Path(
        str(overlay_payload["official_capture"]["comparison_path"])
    )
    receipt, comparison = load_twse_capture(comparison_path.parent)
    tampered_receipt = dict(receipt)
    tampered_receipt["date"] = "2026-05-21"
    # 保留 overlay 宣告的 digest；實際內容 verifier 應先拒絕 receipt。
    tampered_receipt["receipt_hash"] = overlay_payload["official_capture"][
        "receipt_hash"
    ]
    monkeypatch.setattr(
        integration_module,
        "load_twse_capture",
        lambda _capture_directory: (tampered_receipt, comparison),
    )
    with pytest.raises(
        ResearchShadowIntegrationError,
        match="official capture receipt.receipt_hash mismatch",
    ):
        integration_module._load_overlay_and_replay(
            overlay_path=_OVERLAY,
            label_replay_path=_REPLAY,
        )


@pytest.mark.skipif(
    not all(
        path.exists()
        for path in (
            _OVERLAY,
            _REPLAY,
            _UNION,
            _PIT_MANIFEST,
            _PIT_STORE,
            _DIRECT_MANIFEST,
        )
    ),
    reason="accepted local readback artifacts are not present",
)
def test_public_readback_joins_real_overlay_pit_direct_and_is_idempotent(
    tmp_path: Path,
) -> None:
    output = tmp_path / "readback.json"
    result = build_research_shadow_overlay_direct_readback(
        overlay_path=_OVERLAY,
        label_replay_path=_REPLAY,
        research_union_manifest_path=_UNION,
        pit_manifest_path=_PIT_MANIFEST,
        pit_shared_store_root=_PIT_STORE,
        direct_manifest_path=_DIRECT_MANIFEST,
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    declared_hash = payload.pop("integration_hash")
    assert declared_hash == _payload_hash(payload)
    assert result.overlay_row_count == 33
    assert result.union_overlay_match_count == 0
    assert result.pit_overlay_match_count == 1
    assert result.direct_overlay_match_count == 1
    assert payload["formal_training_allowed"] is False
    assert payload["formal_oos_allowed"] is False
    assert payload["production_alpha_bp"] == 0
    assert payload["decision_scope"]["historical_decision_time_available"] is False
    assert payload["decision_scope"]["decision_cutoff"] == (
        "2026-05-20T08:30:00+08:00"
    )
    assert payload["coverage"]["pit_available_before_decision_row_count"] == 0
    assert payload["label_diff"]["changed_head_count"] == 157
    row_2454 = next(row for row in payload["rows"] if row["symbol"] == "2454")
    assert row_2454["direct"]["status"] == "matched_decision_row"
    assert row_2454["pit"]["matched_row_count"] == 3
    assert row_2454["pit"]["feature_rows_can_be_decision_inputs"] is False
    assert row_2454["source_policy"][
        "same_day_overlay_used_as_decision_features"
    ] is False
    first_bytes = output.read_bytes()
    repeated = build_research_shadow_overlay_direct_readback(
        overlay_path=_OVERLAY,
        label_replay_path=_REPLAY,
        research_union_manifest_path=_UNION,
        pit_manifest_path=_PIT_MANIFEST,
        pit_shared_store_root=_PIT_STORE,
        direct_manifest_path=_DIRECT_MANIFEST,
        output_path=output,
    )
    assert repeated.integration_hash == result.integration_hash
    assert output.read_bytes() == first_bytes


@pytest.mark.skipif(
    not all(
        path.exists()
        for path in (
            _OVERLAY,
            _REPLAY,
            _BOUNDED_UNION,
            _BOUNDED_PIT_MANIFEST,
            _BOUNDED_PIT_STORE,
            _DIRECT_MANIFEST,
        )
    ),
    reason="bounded v2 readback artifacts are not present",
)
def test_bounded_union_nested_sample_records_are_counted_by_public_readback(
    tmp_path: Path,
) -> None:
    """v2 sample envelope 內的 row 也必須正確核對日期與股票池。"""

    result = build_research_shadow_overlay_direct_readback(
        overlay_path=_OVERLAY,
        label_replay_path=_REPLAY,
        research_union_manifest_path=_BOUNDED_UNION,
        pit_manifest_path=_BOUNDED_PIT_MANIFEST,
        pit_shared_store_root=_BOUNDED_PIT_STORE,
        direct_manifest_path=_DIRECT_MANIFEST,
        output_path=tmp_path / "bounded-readback.json",
    )
    assert result.overlay_row_count == 33
    # bounded v2 的 2026-05-20 sample 只有 9 筆；其餘 overlay symbols
    # 沒有在該研究 union 的 sample rows 中，不得被 readback 靜默補齊。
    assert result.union_overlay_match_count == 9


@pytest.mark.skipif(
    not _OVERLAY.exists(),
    reason="accepted overlay artifact is not present",
)
def test_public_readback_rejects_output_overlapping_canonical_source(
    tmp_path: Path,
) -> None:
    """輸出路徑不可指向 overlay 宣告的原始 canonical file。"""

    del tmp_path
    overlay_payload = json.loads(_OVERLAY.read_text(encoding="utf-8"))
    canonical_path = Path(
        str(overlay_payload["rows"][0]["canonical_file"]["path"])
    ).resolve()
    before = canonical_path.read_bytes()
    with pytest.raises(
        ResearchShadowIntegrationError,
        match="overlaps a read-only source",
    ):
        build_research_shadow_overlay_direct_readback(
            overlay_path=_OVERLAY,
            label_replay_path=_REPLAY,
            research_union_manifest_path=_UNION,
            pit_manifest_path=_PIT_MANIFEST,
            pit_shared_store_root=_PIT_STORE,
            direct_manifest_path=_DIRECT_MANIFEST,
            output_path=canonical_path,
        )
    assert canonical_path.read_bytes() == before
