from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import gzip
import hashlib
import json
import sqlite3

import pytest

from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.official_trading_calendar_cache import (
    build_twse_calendar_cache,
    write_twse_calendar_cache,
)

from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
    post_freeze_shadow_decision_scope,
)
from ml_module.allocation_feature_contract import (
    DERIVED_MARKET_SOURCE_ID,
    build_market_repair_contract,
    derived_source_manifest_hash,
)
from scripts.build_ml_allocation_post_freeze_feature_repair import (
    _OfficialClose,
    _derive_market_values,
    _input_payload,
    _load_calendar_evidence,
    _legacy_rejection_for_bytes,
    _repair_rows,
    _select_close_pair,
    load_repaired_input,
)


DECISION_AT = datetime.fromisoformat("2026-09-07T18:00:00+08:00")
PRICE_DATE = "2026-09-04"
PARENT_REGISTRY_HASH = "sha256:" + "a" * 64
PARENT_DATASET_HASH = "sha256:" + "b" * 64


def _write_calendar_cache(
    path: Path,
    *,
    calendar_year: int,
) -> None:
    captured_at = datetime.now().astimezone()
    roc_year = calendar_year - 1911
    raw = json.dumps(
        [
            {
                "Name": "中華民國開國紀念日",
                "Date": f"{roc_year:03d}0101",
                "Weekday": "四",
                "Description": "依規定放假1日。",
            },
            {
                "Name": "國曆新年開始交易日",
                "Date": f"{roc_year:03d}0102",
                "Weekday": "五",
                "Description": "國曆新年開始交易。",
            },
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    cache = build_twse_calendar_cache(
        calendar_year=calendar_year,
        raw_response=raw,
        requested_at=captured_at - timedelta(seconds=1),
        captured_at=captured_at,
        response_status=200,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_twse_calendar_cache(path, cache, allowed_root=path.parents[1])


def _close(
    event_date: str,
    value_int: int,
    *,
    available_at: str | None = None,
) -> _OfficialClose:
    return _OfficialClose(
        event_date=event_date,
        event_at=f"{event_date}T14:30:00+08:00",
        available_at=available_at or f"{event_date}T14:30:00+08:00",
        value_int=value_int,
        scale=10_000,
        source_row_hash="sha256:" + "0" * 56 + event_date.replace("-", ""),
        source_value_hash="sha256:" + "1" * 56 + event_date.replace("-", ""),
    )


def _parent_rows() -> tuple[PortfolioMLDatasetRow, ...]:
    feature_specs = (
        (
            "market_indices.漲跌百分比",
            "market_sector_cross_section",
        ),
        (
            "market_indices.漲跌點數",
            "market_sector_cross_section",
        ),
        ("technical_indicators.涨跌", "price_liquidity_technical"),
        (
            "technical_indicators.漲跌(+/-)",
            "price_liquidity_technical",
        ),
        ("technical_indicators.RSI", "price_liquidity_technical"),
    )
    features = tuple(
        PITFeatureValue(
            feature_id=feature_id,
            family_id=family_id,
            source_id=(
                "sqlite.market_indices"
                if feature_id.startswith("market_indices.")
                else "sqlite.technical_indicators"
            ),
            value_int=(1 if feature_id == "technical_indicators.RSI" else None),
            scale=10_000,
            event_at=PRICE_DATE,
            available_at=DECISION_AT.isoformat(),
            revision_id=(
                "sha256:" + "9" * 64
                if feature_id == "technical_indicators.RSI"
                else "missing:not_observed_as_of_decision"
            ),
            quality=(
                "observed"
                if feature_id == "technical_indicators.RSI"
                else "missing"
            ),
            content_hash="sha256:" + "c" * 64,
            observed=feature_id == "technical_indicators.RSI",
        )
        for feature_id, family_id in feature_specs
    )
    quality_features = tuple(
        PITFeatureValue(
            feature_id=f"data_quality.{family_id}.{metric}",
            family_id="data_quality",
            source_id="derived:feature_quality",
            value_int=1,
            scale=1,
            event_at=DECISION_AT.isoformat(),
            available_at=DECISION_AT.isoformat(),
            revision_id="derived:data-quality-v1",
            quality="observed",
            content_hash="sha256:" + "8" * 64,
            observed=True,
        )
        for family_id in (
            "market_sector_cross_section",
            "price_liquidity_technical",
        )
        for metric in (
            "coverage_bp",
            "missing_count",
            "stale_count",
            "quality_blocked_count",
            "max_available_lag_days",
        )
    )
    features = features + quality_features
    state = CausalPortfolioState.create(
        as_of_date=PRICE_DATE,
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )
    with post_freeze_shadow_decision_scope():
        return (
            PortfolioMLDatasetRow(
                row_id="row:post-freeze-shadow:2026-09-07:2330",
                decision_at=DECISION_AT.isoformat(),
                symbol="2330",
                features=features,
                missing_family_ids=(
                    "market_sector_cross_section",
                    "price_liquidity_technical",
                ),
                portfolio_state=state,
                dataset_identity_hash=PARENT_DATASET_HASH,
                feature_registry_hash=PARENT_REGISTRY_HASH,
                source_manifest_hashes=(
                    (
                        "derived:feature_quality",
                        "sha256:" + "d" * 64,
                    ),
                    (
                        "sqlite.market_indices",
                        "sha256:" + "e" * 64,
                    ),
                    (
                        "sqlite.technical_indicators",
                        "sha256:" + "f" * 64,
                    ),
                ),
                targets=None,
            ),
        )


def test_decimal_market_repair_uses_official_consecutive_dates() -> None:
    current = _close("2026-09-04", 465_511_300)
    previous = _close("2026-09-03", 458_576_600)
    contract = build_market_repair_contract(
        parent_feature_registry_hash=PARENT_REGISTRY_HASH,
        feature_ids=(
            "market_indices.漲跌百分比",
            "market_indices.漲跌點數",
            "technical_indicators.涨跌",
            "technical_indicators.漲跌(+/-)",
        ),
    )

    derived = _derive_market_values(
        contract=contract,
        current=current,
        previous=previous,
        decision_at=DECISION_AT,
        expected_price_date=PRICE_DATE,
    )

    assert derived["market_indices.漲跌點數"]["value_int"] == 6_934_700
    assert derived["market_indices.漲跌百分比"]["value_int"] == 15_122
    assert all(
        proof["previous_event_date"] == "2026-09-03"
        and proof["current_source_row_hash"].startswith("sha256:")
        and proof["previous_source_value_hash"].startswith("sha256:")
        for proof in (item["proof"] for item in derived.values())
    )


def test_repair_projection_excludes_classification_and_binds_new_source() -> None:
    parent_rows = _parent_rows()
    contract = build_market_repair_contract(
        parent_feature_registry_hash=PARENT_REGISTRY_HASH,
        feature_ids=tuple(feature.feature_id for feature in parent_rows[0].features),
    )
    derived = _derive_market_values(
        contract=contract,
        current=_close("2026-09-04", 465_511_300),
        previous=_close("2026-09-03", 458_576_600),
        decision_at=DECISION_AT,
        expected_price_date=PRICE_DATE,
    )
    derived_manifest = derived_source_manifest_hash(
        contract=contract,
        input_source_manifest_hash="sha256:" + "e" * 64,
    )

    repaired = _repair_rows(
        parent_rows=parent_rows,
        contract=contract,
        derived_manifest_hash=derived_manifest,
        derived_values=derived,
        parent_dataset_hash=PARENT_DATASET_HASH,
        parent_input_hash="sha256:" + "1" * 64,
        raw_dataset_hash="sha256:" + "2" * 64,
    )
    ids = {feature.feature_id for feature in repaired[0].features}
    assert ids == set(contract.included_feature_ids)
    assert "technical_indicators.涨跌" not in ids
    assert "technical_indicators.漲跌(+/-)" not in ids
    assert all(
        feature.source_id == DERIVED_MARKET_SOURCE_ID
        and feature.observed
        for feature in repaired[0].features
        if feature.feature_id in contract.derived_feature_ids
    )
    quality = {
        feature.feature_id: feature
        for feature in repaired[0].features
        if feature.family_id == "data_quality"
    }
    assert quality[
        "data_quality.market_sector_cross_section.coverage_bp"
    ].value_int == 10_000
    assert quality[
        "data_quality.market_sector_cross_section.missing_count"
    ].value_int == 0
    assert quality[
        "data_quality.price_liquidity_technical.coverage_bp"
    ].value_int == 10_000
    assert all(
        feature.source_id.startswith("derived:feature_quality.effective_contract")
        and feature.revision_id.startswith("derived:data-quality-effective-v1:")
        for feature in quality.values()
    )
    assert repaired[0].feature_registry_hash == contract.contract_hash
    assert DERIVED_MARKET_SOURCE_ID in dict(repaired[0].source_manifest_hashes)
    assert repaired[0].missing_family_ids == ()


def test_repair_consumer_rejects_rehashed_dq_tamper_and_contract_and_legacy_parser_rejects_v3(
    tmp_path: Path,
) -> None:
    parent_rows = _parent_rows()
    contract = build_market_repair_contract(
        parent_feature_registry_hash=PARENT_REGISTRY_HASH,
        feature_ids=tuple(feature.feature_id for feature in parent_rows[0].features),
    )
    derived = _derive_market_values(
        contract=contract,
        current=_close("2026-09-04", 465_511_300),
        previous=_close("2026-09-03", 458_576_600),
        decision_at=DECISION_AT,
        expected_price_date=PRICE_DATE,
    )
    repaired = _repair_rows(
        parent_rows=parent_rows,
        contract=contract,
        derived_manifest_hash=derived_source_manifest_hash(
            contract=contract,
            input_source_manifest_hash="sha256:" + "e" * 64,
        ),
        derived_values=derived,
        parent_dataset_hash=PARENT_DATASET_HASH,
        parent_input_hash="sha256:" + "1" * 64,
        raw_dataset_hash="sha256:" + "2" * 64,
    )
    payload = _input_payload(
        rows=repaired,
        contract=contract,
        parent_input_hash="sha256:" + "1" * 64,
    )
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    path = tmp_path / "post_freeze_shadow_feature_repair.json.gz"
    path.write_bytes(gzip.compress(raw, mtime=0))
    assert len(load_repaired_input(path, expected_contract_hash=contract.contract_hash)) == 1
    assert "unsupported input field: feature_contract" in _legacy_rejection_for_bytes(
        path.read_bytes()
    )

    tampered_quality = json.loads(raw.decode("utf-8"))
    quality_row = tampered_quality["rows"][0]
    quality_feature = next(
        feature
        for feature in quality_row["features"]
        if feature["feature_id"]
        == "data_quality.market_sector_cross_section.coverage_bp"
    )
    quality_feature["value_int"] = 9_999
    # Recompute the child hash and re-envelope the gzip bytes.  The loader
    # must still reject this: a validly formatted self-attestation does not
    # override the effective DQ value recomputed from the actual features.
    quality_feature["content_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            {
                "feature_id": quality_feature["feature_id"],
                "value_int": quality_feature["value_int"],
                "content_hash": quality_feature["content_hash"],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    tampered_quality_raw = (
        json.dumps(tampered_quality, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(gzip.compress(tampered_quality_raw, mtime=0))
    with pytest.raises(ValueError, match="effective data quality feature mismatch"):
        load_repaired_input(path, expected_contract_hash=contract.contract_hash)

    tampered = json.loads(raw.decode("utf-8"))
    tampered["feature_contract"]["derivation_method"] = "guess"
    tampered_raw = (
        json.dumps(tampered, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(gzip.compress(tampered_raw, mtime=0))
    with pytest.raises(ValueError, match="feature contract payload mismatch"):
        load_repaired_input(path, expected_contract_hash=contract.contract_hash)


def test_market_repair_rejects_future_availability_and_missing_prior_date() -> None:
    contract = build_market_repair_contract(
        parent_feature_registry_hash=PARENT_REGISTRY_HASH,
        feature_ids=(
            "market_indices.漲跌百分比",
            "market_indices.漲跌點數",
            "technical_indicators.涨跌",
            "technical_indicators.漲跌(+/-)",
        ),
    )
    with pytest.raises(ValueError, match="after decision_at"):
        _derive_market_values(
            contract=contract,
            current=_close(
                "2026-09-04",
                465_511_300,
                available_at="2099-01-01T00:00:00+00:00",
            ),
            previous=_close("2026-09-03", 458_576_600),
            decision_at=DECISION_AT,
            expected_price_date=PRICE_DATE,
        )
    with pytest.raises(ValueError, match="official prior trading date close missing"):
        _select_close_pair(
            {PRICE_DATE: _close(PRICE_DATE, 465_511_300)},
            expected_price_date=PRICE_DATE,
            calendar_previous_date="2026-09-03",
        )


def test_close_pair_rejects_missing_middle_official_trading_day() -> None:
    closes = {
        "2026-09-02": _close("2026-09-02", 461_647_200),
        PRICE_DATE: _close(PRICE_DATE, 465_511_300),
    }
    with pytest.raises(
        ValueError,
        match="official prior trading date close missing: 2026-09-03",
    ):
        _select_close_pair(
            closes,
            expected_price_date=PRICE_DATE,
            calendar_previous_date="2026-09-03",
        )


def test_calendar_provider_can_skip_a_proven_official_holiday(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_database = tmp_path / "calendar.sqlite"
    sqlite3.connect(calendar_database).close()

    def fake_days(
        _provider: object,
        start_date: date,
        end_date: date,
        *,
        allow_online_probe: bool,
    ) -> list[dict[str, object]]:
        assert allow_online_probe is False
        days: list[dict[str, object]] = []
        current = start_date
        while current <= end_date:
            days.append(
                {
                    "date": current,
                    "date_str": current.isoformat(),
                    "is_trading_day": (
                        False
                        if current == date(2026, 9, 3)
                        else True
                    ),
                    "reason_code": (
                        "twse_holiday_schedule_closed"
                        if current == date(2026, 9, 3)
                        else "twse_holiday_schedule_open"
                    ),
                }
            )
            current += timedelta(days=1)
        return days

    monkeypatch.setattr(
        "scripts.build_ml_allocation_post_freeze_feature_repair."
        "OfficialTradingCalendar.get_trading_days_in_range",
        fake_days,
    )
    previous_date, evidence = _load_calendar_evidence(
        calendar_database=calendar_database,
        expected_price_date=PRICE_DATE,
    )
    assert previous_date == "2026-09-02"
    assert evidence["selected_previous_trading_date"] == "2026-09-02"
    assert evidence["evidence_hash"].startswith("sha256:")

    current, previous = _select_close_pair(
        {
            "2026-09-02": _close("2026-09-02", 461_647_200),
            PRICE_DATE: _close(PRICE_DATE, 465_511_300),
        },
        expected_price_date=PRICE_DATE,
        calendar_previous_date=previous_date,
    )
    assert current.event_date == PRICE_DATE
    assert previous.event_date == "2026-09-02"


def test_calendar_provider_unknown_weekday_blocks(tmp_path: Path) -> None:
    calendar_database = tmp_path / "calendar.sqlite"
    sqlite3.connect(calendar_database).close()
    with pytest.raises(
        ValueError,
        match="official calendar does not prove expected price date is trading",
    ):
        _load_calendar_evidence(
            calendar_database=calendar_database,
            expected_price_date=PRICE_DATE,
        )


def test_calendar_cache_cross_year_missing_prior_cache_blocks_db_fallback(
    tmp_path: Path,
) -> None:
    calendar_database = tmp_path / "calendar.sqlite"
    sqlite3.connect(calendar_database).close()
    cache_root = tmp_path / "calendar-cache"
    _write_calendar_cache(
        cache_root / "twse_holiday_schedule_2026_january.json",
        calendar_year=2026,
    )

    with pytest.raises(
        ValueError,
        match="official calendar cache is unavailable or invalid: 2025",
    ):
        _load_calendar_evidence(
            calendar_database=calendar_database,
            expected_price_date="2026-01-02",
            calendar_cache_path=cache_root,
        )


def test_calendar_cache_cross_year_requires_and_binds_both_annual_caches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_database = tmp_path / "calendar.sqlite"
    sqlite3.connect(calendar_database).close()
    cache_root = tmp_path / "calendar-cache"
    _write_calendar_cache(
        cache_root / "twse_holiday_schedule_2025_december.json",
        calendar_year=2025,
    )
    _write_calendar_cache(
        cache_root / "twse_holiday_schedule_2026_january.json",
        calendar_year=2026,
    )

    def fail_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cross-year cache proof must not use the network")

    monkeypatch.setattr(
        "data_module.official_trading_calendar.safe_request",
        fail_network,
    )
    previous_date, evidence = _load_calendar_evidence(
        calendar_database=calendar_database,
        expected_price_date="2026-01-02",
        calendar_cache_path=cache_root,
    )

    assert previous_date == "2025-12-31"
    assert evidence["source"] == "hash_bound_official_calendar_cache"
    assert evidence["calendar_custody"]["calendar_years"] == [2025, 2026]  # type: ignore[index]
    selected = evidence["selected_calendar_evidence"]
    assert selected["previous"]["mode"] == "hash_bound_official_calendar_cache"  # type: ignore[index]
    assert selected["expected"]["mode"] == "hash_bound_official_calendar_cache"  # type: ignore[index]
    assert selected["previous"]["target_date"] == "2025-12-31"  # type: ignore[index]
    assert selected["expected"]["target_date"] == "2026-01-02"  # type: ignore[index]


def test_calendar_cache_mid_read_tamper_is_rejected_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar_database = tmp_path / "calendar.sqlite"
    sqlite3.connect(calendar_database).close()
    cache_path = tmp_path / "calendar-cache" / "twse_holiday_schedule_2026.json"
    _write_calendar_cache(cache_path, calendar_year=2026)

    original = OfficialTradingCalendar.is_official_trading_day
    calls = 0

    def tamper_after_schedule_read(
        provider: OfficialTradingCalendar,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        nonlocal calls
        result = original(
            provider,
            target_date,
            allow_online_probe=allow_online_probe,
        )
        calls += 1
        if calls == 3:
            cache_path.write_bytes(cache_path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(
        "scripts.build_ml_allocation_post_freeze_feature_repair."
        "OfficialTradingCalendar.is_official_trading_day",
        tamper_after_schedule_read,
    )
    with pytest.raises(
        ValueError,
        match="official calendar custody changed during bounded read",
    ):
        _load_calendar_evidence(
            calendar_database=calendar_database,
            expected_price_date=PRICE_DATE,
            calendar_cache_path=cache_path,
        )
    assert calls >= 3
