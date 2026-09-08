from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from app_module.formal_input_owner_packet import build_formal_input_owner_packet
from app_module.program_readiness_projection import (
    PROGRAM_READINESS_SCHEMA,
    load_program_readiness,
)
from data_module.pit_sector_machine_publisher import (
    MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV,
    MACHINE_PIT_PUBLISHER_ID_ENV,
    publish_machine_pit_operational_candidate,
)
from data_module.pit_sector_membership_machine import (
    build_machine_pit_publication,
    write_machine_pit_receipt,
)
from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from data_module.portfolio_ml_dataset_assembler import _FeatureDefinition
from scripts import inspect_ml_formal_input_readiness as readiness
from scripts import inspect_program_readiness as program_readiness
from scripts import build_ml_allocation_post_freeze_shadow_input as post_freeze


CAPTURED_AT = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
DECISION_AT = datetime(2026, 8, 1, 13, 0, tzinfo=timezone.utc)
PUBLISHED_AT = datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc)
FEATURE_DECISION_AT = datetime(2026, 8, 2, 0, 30, tzinfo=timezone.utc)


def _raw_payloads() -> dict[str, bytes]:
    return {
        "twse": _json_bytes(
            [
                {"公司代號": "1101", "產業別": "01", "出表日期": "20260801"},
                {"公司代號": "1102", "產業別": "02", "出表日期": "20260801"},
            ]
        ),
        "tpex": _json_bytes(
            [
                {
                    "SecuritiesCompanyCode": "5501",
                    "SecuritiesIndustryCode": "03",
                    "Date": "2026-08-01",
                },
                {
                    "SecuritiesCompanyCode": "5502",
                    "SecuritiesIndustryCode": "05",
                    "Date": "2026-08-01",
                },
            ]
        ),
    }


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    )


def _operational_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision_at: datetime = DECISION_AT,
    raw_payloads: dict[str, bytes] | None = None,
) -> Path:
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, "test-controlled-key")
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_ID_ENV, "machine-pit-test-store")
    publication_dir = tmp_path / "machine"
    publication_dir.mkdir()
    publication = build_machine_pit_publication(
        raw_payloads=_raw_payloads() if raw_payloads is None else raw_payloads,
        output_dir=publication_dir,
        captured_at=CAPTURED_AT,
        now=datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc),
    )
    receipt_path = tmp_path / "receipt.json"
    write_machine_pit_receipt(
        publication.publication_path,
        receipt_path=receipt_path,
        now=datetime(2026, 8, 1, 10, 30, tzinfo=timezone.utc),
    )
    operational_path = tmp_path / "operational.json"
    publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=operational_path,
        decision_at=decision_at,
        now=datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc),
    )
    return operational_path


def _inventory(path: Path) -> None:
    payload = {
        "schema_version": "ml-formal-input-candidate-inventory.v1",
        "candidate_root": str(path.parent / "candidates"),
        "manifest_count": 0,
        "skipped_count": 0,
        "truncated": False,
        "lane_counts": {},
        "candidate_input_counts": {
            "causal_non_cash_portfolio_ledger": 0,
            "formal_rule_champion_snapshot_history": 0,
            "pit_sector_membership": 0,
        },
        "formal_ready_input_count": 0,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "promotion_eligible": False,
        "candidates": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_owner_packet_consumes_signed_operational_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operational_path = _operational_publication(
        tmp_path,
        monkeypatch,
        decision_at=PUBLISHED_AT,
    )
    inventory_path = tmp_path / "inventory.json"
    (tmp_path / "candidates").mkdir()
    _inventory(inventory_path)

    packet = build_formal_input_owner_packet(
        inventory_path,
        pit_machine_publication_path=operational_path,
        pit_machine_decision_at=DECISION_AT,
    )

    record = next(
        item for item in packet["review_records"] if item["input"] == "pit_sector_membership"
    )
    assert packet["packet_status"] == "needs_input_evidence"
    assert packet["machine_verified_input_count"] == 1
    assert packet["machine_candidate_input_count"] == 1
    assert packet["formal_ready_input_count"] == 0
    assert packet["owner_reviewer_required"] is False
    assert packet["human_review_required"] is False
    assert record["evidence_state"] == "missing"
    assert record["owner_decision"] == "machine_candidate"
    assert record["machine_review_required"] is False
    assert record["machine_verification"]["publisher_id"] == "machine-pit-test-store"
    assert record["machine_verification"]["formal_consumer_compatible"] is False


def test_readiness_and_program_projection_keep_machine_candidate_out_of_formal_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operational_path = _operational_publication(tmp_path, monkeypatch)
    output_root = tmp_path / "output"
    output_root.mkdir()
    for name in (
        readiness.PORTFOLIO_LEDGER_ENV,
        readiness.RULE_HISTORY_ENV,
        readiness.SECTOR_MEMBERSHIP_ENV,
        readiness.PIT_MACHINE_RECEIPT_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(readiness.PIT_MACHINE_PUBLICATION_ENV, str(operational_path))
    monkeypatch.setattr(readiness, "_refresh_controlled_runtime_environment", lambda: ())
    monkeypatch.setattr(
        readiness,
        "discover_valid_sector_membership",
        lambda **_: None,
    )

    report = readiness.build_readiness_report(
        output_root=output_root,
        training_as_of="2026-08-01T13:00:00+00:00",
    )
    assert report["status"] == "waiting_for_formal_inputs"
    assert report["ready_input_count"] == 0
    assert report["machine_verified_input_count"] == 1
    assert report["inputs"][2]["state"] == "machine_verified"
    assert report["inputs"][2]["formal_ready"] is False
    assert report["inputs"][2]["candidate_only"] is True

    lane = program_readiness._inspect_formal_ml_lane(
        output_root,
        training_as_of="2026-08-01T13:00:00+00:00",
    )
    assert lane["blockers"] == [
        "formal_input_source_missing:causal_non_cash_portfolio_ledger",
        "formal_input_source_missing:formal_rule_champion_snapshot_history",
        "formal_input_machine_candidate:pit_sector_membership",
        "formal_oos_disabled",
    ]

    program_path = tmp_path / "program-readiness.json"
    program_path.write_text(
        json.dumps(
            {
                "schema_version": PROGRAM_READINESS_SCHEMA,
                "status": "action_required",
                "workstreams": {
                    "formal_ml": {
                        "status": "action_required",
                        "blockers": [
                            "formal_input_machine_candidate:pit_sector_membership"
                        ],
                        "next_actions": ["publish formal inputs"],
                        "external_input_required": True,
                        "details": {"readiness": report},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    projected = load_program_readiness(program_path)
    assert projected["workstreams"]["formal_ml"]["metrics"] == {
        "ready_input_count": 0,
        "machine_verified_input_count": 1,
        "machine_candidate_input_count": 1,
        "formal_consumer_compatible_count": 0,
        "missing_input_count": 2,
        "unknown_input_count": 0,
        "invalid_input_count": 0,
        "input_count": 3,
        "ready_input_ratio": "0/3",
        "readiness_status": "waiting_for_formal_inputs",
    }


def test_operational_membership_reduces_industry_feature_missing_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operational_path = _operational_publication(
        tmp_path,
        monkeypatch,
        decision_at=PUBLISHED_AT,
    )
    definitions = (
        _FeatureDefinition(
            feature_id="daily_prices.收盤價",
            base_feature_id="daily_prices.收盤價",
            table_name="daily_prices",
            family_id="price_liquidity_technical",
            source_id="sqlite.daily_prices",
            scale=100,
            stale_after_days=1,
            record_hash="sha256:" + "1" * 64,
            scope="stock",
        ),
        _FeatureDefinition(
            feature_id="market_indices.收盤指數",
            base_feature_id="market_indices.收盤指數",
            table_name="market_indices",
            family_id="market_sector_cross_section",
            source_id="sqlite.market_indices",
            scale=100,
            stale_after_days=1,
            record_hash="sha256:" + "2" * 64,
            scope="market",
        ),
        _FeatureDefinition(
            feature_id="industry_indices.收盤指數",
            base_feature_id="industry_indices.收盤指數",
            table_name="industry_indices",
            family_id="market_sector_cross_section",
            source_id="sqlite.industry_indices",
            scale=100,
            stale_after_days=1,
            record_hash="sha256:" + "3" * 64,
            scope="industry",
        ),
    )

    def build(machine_path: Path | None) -> dict[str, object]:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            dataset_assembler._initialize_spool(connection)
            common_observations = [
                (
                    "stock",
                    "1101",
                    "daily_prices.收盤價",
                    "daily_prices",
                    "2026-08-01T14:30:00+08:00",
                    "2026-08-01T14:30:00+08:00",
                    "stock-1",
                    "accepted",
                    "sha256:" + "4" * 64,
                    "sha256:" + "5" * 64,
                    101,
                    100,
                    1,
                    1,
                    0,
                    0,
                ),
                (
                    "market",
                    "TAIEX",
                    "market_indices.收盤指數",
                    "market_indices",
                    "2026-08-01T14:30:00+08:00",
                    "2026-08-01T14:30:00+08:00",
                    "market-1",
                    "accepted",
                    "sha256:" + "6" * 64,
                    "sha256:" + "7" * 64,
                    20_000,
                    100,
                    1,
                    1,
                    0,
                    0,
                ),
                (
                    "industry",
                    "水泥類指數",
                    "industry_indices.收盤指數",
                    "industry_indices",
                    "2026-08-01T14:30:00+08:00",
                    "2026-08-01T20:00:00+08:00",
                    "industry-1",
                    "accepted",
                    "sha256:" + "8" * 64,
                    "sha256:" + "9" * 64,
                    30_000,
                    100,
                    1,
                    1,
                    0,
                    0,
                ),
            ]
            connection.executemany(
                """
                INSERT INTO observations(
                    scope, entity_key, feature_id, source_table,
                    event_at, available_at, revision_id, quality,
                    source_row_hash, source_value_hash, value_int, scale,
                    stale_after_days, formal_training_eligible, missing_mask,
                    quality_blocked_mask
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                common_observations,
            )
            dataset_assembler._insert_prices(
                connection,
                [
                    (
                        "stock",
                        "1101",
                        "2026-08-01",
                        "2026-08-01T14:30:00+08:00",
                        100,
                        100,
                        102,
                        100,
                        99,
                        100,
                        101,
                        100,
                        "sha256:" + "a" * 64,
                    ),
                    (
                        "market",
                        "TAIEX",
                        "2026-08-01",
                        "2026-08-01T14:30:00+08:00",
                        20_000,
                        100,
                        20_200,
                        100,
                        19_900,
                        100,
                        20_100,
                        100,
                        "sha256:" + "b" * 64,
                    ),
                ],
            )
            connection.commit()
            _, _, counts = post_freeze._assemble_shadow_rows(
                connection=connection,
                definitions=definitions,
                symbols=("1101",),
                decision_at=FEATURE_DECISION_AT,
                expected_price_date=datetime(
                    2026, 8, 1, tzinfo=timezone.utc
                ).date(),
                dataset_identity_hash="sha256:" + "c" * 64,
                feature_registry_hash="sha256:" + "d" * 64,
                source_manifest_hashes=(
                    ("derived:feature_quality", "sha256:" + "e" * 64),
                    ("sqlite.daily_prices", "sha256:" + "f" * 64),
                    ("sqlite.industry_indices", "sha256:" + "0" * 64),
                    ("sqlite.market_indices", "sha256:" + "1" * 64),
                ),
                batch_size=32,
                machine_operational_path=machine_path,
                machine_now=(
                    datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
                    if machine_path is not None
                    else None
                ),
            )
            return dict(counts)
        finally:
            connection.close()

    baseline = build(None)
    machine = build(operational_path)
    assert baseline["machine_sector_row_count"] == 0
    assert baseline["industry_feature_observed_count"] == 0
    assert baseline["industry_feature_missing_count"] == 1
    assert machine["machine_sector_row_count"] == 4
    assert machine["machine_sector_mapped_symbol_count"] == 4
    assert machine["industry_entity_lineage"]["01"] == "水泥類指數"
    assert machine["industry_index_kind"] == "price_index"
    assert machine["industry_index_market_scope"] == "TWSE"
    assert machine["industry_index_source_id"] == "sqlite.industry_indices"
    assert all(
        entity is None or "報酬" not in entity
        for entity in machine["industry_entity_lineage"].values()
    )
    assert machine["industry_feature_observed_count"] == 1
    assert machine["industry_feature_missing_count"] == 0


def test_industry_index_kind_unknown_keeps_membership_feature_missing() -> None:
    assert post_freeze._industry_index_kind(
        ("industry_indices.收盤指數",)
    ) == "price_index"
    assert post_freeze._industry_index_kind(
        ("industry_indices.報酬指數",)
    ) is None
    assert post_freeze._industry_entity_candidates(
        "01",
        index_kind=None,
    ) == ()
    assert all(
        "報酬" not in entity
        for entity in post_freeze._industry_entity_candidates(
            "01",
            index_kind="price_index",
        )
    )


def test_tpex_membership_same_sector_keeps_twse_industry_feature_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operational_path = _operational_publication(
        tmp_path,
        monkeypatch,
        raw_payloads={
            "twse": _json_bytes(
                [{"公司代號": "1101", "產業別": "01", "出表日期": "20260801"}]
            ),
            "tpex": _json_bytes(
                [
                    {
                        "SecuritiesCompanyCode": "5501",
                        "SecuritiesIndustryCode": "01",
                        "Date": "2026-08-01",
                    }
                ]
            ),
        },
    )
    definitions = (
        _FeatureDefinition(
            feature_id="daily_prices.收盤價",
            base_feature_id="daily_prices.收盤價",
            table_name="daily_prices",
            family_id="price_liquidity_technical",
            source_id="sqlite.daily_prices",
            scale=100,
            stale_after_days=1,
            record_hash="sha256:" + "1" * 64,
            scope="stock",
        ),
        _FeatureDefinition(
            feature_id="market_indices.收盤指數",
            base_feature_id="market_indices.收盤指數",
            table_name="market_indices",
            family_id="market_sector_cross_section",
            source_id="sqlite.market_indices",
            scale=100,
            stale_after_days=1,
            record_hash="sha256:" + "2" * 64,
            scope="market",
        ),
        _FeatureDefinition(
            feature_id="industry_indices.收盤指數",
            base_feature_id="industry_indices.收盤指數",
            table_name="industry_indices",
            family_id="market_sector_cross_section",
            source_id="sqlite.industry_indices",
            scale=100,
            stale_after_days=1,
            record_hash="sha256:" + "3" * 64,
            scope="industry",
        ),
    )
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        dataset_assembler._initialize_spool(connection)
        observations = []
        for symbol, value, source_hash in (
            ("1101", 101, "4"),
            ("5501", 201, "5"),
        ):
            observations.append(
                (
                    "stock",
                    symbol,
                    "daily_prices.收盤價",
                    "daily_prices",
                    "2026-08-01T14:30:00+08:00",
                    "2026-08-01T14:30:00+08:00",
                    f"stock-{symbol}",
                    "accepted",
                    "sha256:" + source_hash * 64,
                    "sha256:" + (source_hash + "a") * 32,
                    value,
                    100,
                    1,
                    1,
                    0,
                    0,
                )
            )
        observations.extend(
            [
                (
                    "market",
                    "TAIEX",
                    "market_indices.收盤指數",
                    "market_indices",
                    "2026-08-01T14:30:00+08:00",
                    "2026-08-01T14:30:00+08:00",
                    "market-1",
                    "accepted",
                    "sha256:" + "6" * 64,
                    "sha256:" + "7" * 64,
                    20_000,
                    100,
                    1,
                    1,
                    0,
                    0,
                ),
                (
                    "industry",
                    "水泥類指數",
                    "industry_indices.收盤指數",
                    "industry_indices",
                    "2026-08-01T14:30:00+08:00",
                    "2026-08-01T14:30:00+08:00",
                    "industry-1",
                    "accepted",
                    "sha256:" + "8" * 64,
                    "sha256:" + "9" * 64,
                    30_000,
                    100,
                    1,
                    1,
                    0,
                    0,
                ),
            ]
        )
        connection.executemany(
            """
            INSERT INTO observations(
                scope, entity_key, feature_id, source_table,
                event_at, available_at, revision_id, quality,
                source_row_hash, source_value_hash, value_int, scale,
                stale_after_days, formal_training_eligible, missing_mask,
                quality_blocked_mask
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            observations,
        )
        prices = []
        for symbol, value, source_hash in (
            ("1101", 101, "a"),
            ("5501", 201, "b"),
        ):
            prices.append(
                (
                    "stock",
                    symbol,
                    "2026-08-01",
                    "2026-08-01T14:30:00+08:00",
                    value,
                    100,
                    value + 2,
                    100,
                    value - 1,
                    100,
                    value + 1,
                    100,
                    "sha256:" + source_hash * 64,
                )
            )
        prices.append(
            (
                "market",
                "TAIEX",
                "2026-08-01",
                "2026-08-01T14:30:00+08:00",
                20_000,
                100,
                20_200,
                100,
                19_900,
                100,
                20_100,
                100,
                "sha256:" + "c" * 64,
            )
        )
        dataset_assembler._insert_prices(connection, prices)
        connection.commit()
        rows, _, counts = post_freeze._assemble_shadow_rows(
            connection=connection,
            definitions=definitions,
            symbols=("1101", "5501"),
            decision_at=FEATURE_DECISION_AT,
            expected_price_date=datetime(2026, 8, 1, tzinfo=timezone.utc).date(),
            dataset_identity_hash="sha256:" + "c" * 64,
            feature_registry_hash="sha256:" + "d" * 64,
            source_manifest_hashes=(
                ("derived:feature_quality", "sha256:" + "e" * 64),
                ("sqlite.daily_prices", "sha256:" + "f" * 64),
                ("sqlite.industry_indices", "sha256:" + "0" * 64),
                ("sqlite.market_indices", "sha256:" + "1" * 64),
            ),
            batch_size=32,
            machine_operational_path=operational_path,
            machine_now=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
        )
    finally:
        connection.close()

    by_symbol = {row.symbol: row for row in rows}
    twse_feature = next(
        feature
        for feature in by_symbol["1101"].features
        if feature.feature_id == "industry_indices.收盤指數"
    )
    tpex_feature = next(
        feature
        for feature in by_symbol["5501"].features
        if feature.feature_id == "industry_indices.收盤指數"
    )
    assert counts["machine_symbol_markets"] == {
        "1101": "TWSE",
        "5501": "TPEx",
    }
    assert counts["industry_feature_observed_count"] == 1
    assert counts["industry_feature_missing_count"] == 1
    assert counts["industry_scope_mismatch_symbols"] == ["5501"]
    assert twse_feature.observed is True
    assert tpex_feature.observed is False
    assert "industry_scope_mismatch" in tpex_feature.revision_id
