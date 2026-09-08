from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from data_module.ml_daily_price_overlay_consumer import (
    build_daily_price_overlay_impact,
)
from data_module.ml_daily_price_research_pipeline import (
    DailyPriceResearchReplayError,
    build_research_label_replay_from_overlay,
)
from tests.test_ml_daily_price_overlay_consumer import (
    _DATE,
    _official_overlay,
    _SYMBOLS,
)


def _add_horizon_plus_one_session(database: Path) -> None:
    """讓既有 h20 label spool 看見額外一個 session，驗證完整 horizon。"""

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?)",
            ("20260617", "TAIEX", "1100", "1101"),
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    "20260617",
                    symbol,
                    symbol,
                    "110",
                    "112",
                    "108",
                    "111",
                    5000,
                )
                for symbol in _SYMBOLS
            ),
        )


def test_official_overlay_is_selected_by_existing_label_spool_and_matches_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database, overlay = _official_overlay(tmp_path, monkeypatch)
    _add_horizon_plus_one_session(database)
    reference = build_daily_price_overlay_impact(
        overlay_path=overlay,
        sqlite_path=database,
        output_path=tmp_path / "impact" / "impact.json",
    )
    output = tmp_path / "replay" / "labels.json"
    database_before = database.read_bytes()
    result = build_research_label_replay_from_overlay(
        overlay_path=overlay,
        sqlite_path=database,
        reference_impact_path=reference.output_path,
        output_path=output,
    )

    assert result.row_count == len(_SYMBOLS)
    assert result.reference_rows_matched == len(_SYMBOLS)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["selection"]["existing_pipeline"].endswith(
        "portfolio_ml_dataset_assembler._build_label_spool"
    )
    assert payload["selection"]["same_day_overlay_as_model_feature"] is False
    assert payload["formal_training_allowed"] is False
    assert payload["historical_decision_time_available"] is False
    assert payload["verification"]["reference_original_rows_matched"] == 2
    assert payload["verification"]["reference_corrected_rows_matched"] == 2
    for row in payload["rows"]:
        assert row["decision_at"] == f"{_DATE}T08:30:00+08:00"
        assert row["feature_source"]["source_date"] == "2026-05-19"
        assert row["feature_source"]["source_available_at"] is None
        assert row["feature_source"]["available_before_decision"] is True
        assert row["feature_source"]["availability_timestamp_proven"] is False
        assert row["feature_source"]["selected_values"]["close"]
        assert isinstance(
            row["feature_source"]["selected_values"][
                "close_to_previous_close_bp"
            ],
            int,
        )
        assert row["source_lineage"][
            "official_overlay_used_for_decision_features"
        ] is False
        assert row["labels"]["corrected_source_kind"] == (
            "official_response_bound_overlay"
        )
    assert database.read_bytes() == database_before

    # 同一內容可重播；output 不是可被 research pipeline 改寫的暫存檔。
    before = output.read_bytes()
    repeated = build_research_label_replay_from_overlay(
        overlay_path=overlay,
        sqlite_path=database,
        reference_impact_path=reference.output_path,
        output_path=output,
    )
    assert repeated.replay_hash == result.replay_hash
    assert output.read_bytes() == before


def test_research_replay_rejects_output_inside_read_only_overlay_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database, overlay = _official_overlay(tmp_path, monkeypatch)
    _add_horizon_plus_one_session(database)
    try:
        build_research_label_replay_from_overlay(
            overlay_path=overlay,
            sqlite_path=database,
            output_path=overlay,
        )
    except DailyPriceResearchReplayError as exc:
        assert "overlaps read-only source" in str(exc)
    else:
        raise AssertionError("research replay accepted a source-overlapping output")


def test_research_replay_rejects_capture_time_not_bound_to_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """overlay 宣告的 available time 不能脫離官方 receipt completion。"""

    from data_module.ml_daily_price_overlay import _payload_hash

    database, overlay = _official_overlay(tmp_path, monkeypatch)
    _add_horizon_plus_one_session(database)
    payload = json.loads(overlay.read_text(encoding="utf-8"))
    capture = dict(payload["official_capture"])
    capture["captured_at_utc"] = "2026-09-07T19:24:01+00:00"
    payload["official_capture"] = capture
    payload.pop("overlay_hash", None)
    payload["overlay_hash"] = _payload_hash(payload)
    tampered = tmp_path / "tampered-overlay.json"
    tampered.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    try:
        build_research_label_replay_from_overlay(
            overlay_path=tampered,
            sqlite_path=database,
            output_path=tmp_path / "replay" / "blocked.json",
        )
    except DailyPriceResearchReplayError as exc:
        assert "receipt completion" in str(exc)
    else:
        raise AssertionError("research replay accepted an unbound capture time")
