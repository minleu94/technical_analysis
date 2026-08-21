from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path

import pytest

from data_module.prospective_formal_clock import (
    build_clock_manifest,
    load_clock_manifest,
    payload_hash,
)
from data_module.prospective_official_pit_source import (
    ProspectiveOfficialPITSourceError,
    build_official_first_seen_capture,
)
from data_module.prospective_pit_sector_membership import (
    capture_prospective_pit_sector_membership,
    validate_prospective_pit_sector_membership,
)


_PREFLIGHT_NOW = datetime.fromisoformat("2026-08-21T06:30:00+08:00")
_CAPTURE_NOW = datetime.fromisoformat("2026-08-25T08:31:00+08:00")
_AVAILABLE_AT = datetime.fromisoformat("2026-08-21T05:30:00+08:00")
_PUBLICATION_AT = datetime.fromisoformat("2026-08-20T00:00:00+08:00")
_EFFECTIVE_FROM = date(2026, 8, 25)


def _clock(tmp_path: Path):
    seed = {"kind": "cash", "cash_bp": 10_000, "position_count": 0}
    seed["state_hash"] = payload_hash(seed)
    calendar = {
        "schema_version": "official-trading-calendar-evidence.v1",
        "date": "2026-08-25",
        "is_trading_day": True,
        "reason_code": "twse_holiday_schedule_explicit_open",
        "source": "TWSE holidaySchedule + TPEX mktCalendar",
        "source_hash": "sha256:" + "1" * 64,
    }
    body: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": "clock:prospective:20260825:rule-only-test",
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-direction:prospective-formal-restart:20260819:v1",
        "owner_decision_timestamp": "2026-08-20T12:00:00+08:00",
        "activation_trading_day": "2026-08-25",
        "decision_timezone": "Asia/Taipei",
        "decision_time": "08:30:00",
        "activation_calendar_evidence": calendar,
        "seed_state": seed,
        "virtual_notional_minor_units": 50_000_000,
        "strategy_version": "manual-rule-only-daily-rank-v1",
        "policy_version": "foreground-owner-bound-v1",
        "policy_hash": "sha256:" + "2" * 64,
        "universe_hash": "sha256:" + "5" * 64,
        "source_policy_hash": "sha256:" + "6" * 64,
        "candidate_model_hash": "sha256:" + "7" * 64,
        "candidate_feature_manifest_hash": "sha256:" + "8" * 64,
        "candidate_training_cutoff": "2026-08-20T08:30:00+08:00",
        "calibration_policy_hash": "sha256:" + "9" * 64,
        "evaluation_policy_hash": "sha256:" + "a" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    path = tmp_path / "clock.json"
    path.write_text(
        json.dumps(build_clock_manifest(body), ensure_ascii=False),
        encoding="utf-8",
    )
    return load_clock_manifest(path, now=_PREFLIGHT_NOW)


def _twse_payload() -> bytes:
    return json.dumps(
        [
            {"出表日期": "1150820", "公司代號": "1101", "產業別": "01", "公司名稱": "甲"},
            {"出表日期": "1150820", "公司代號": "2330", "產業別": "24", "公司名稱": "乙"},
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _tpex_payload() -> bytes:
    return json.dumps(
        [
            {
                "Date": "115/08/20",
                "SecuritiesCompanyCode": "2317",
                "SecuritiesIndustryCode": "28",
                "CompanyName": "丙",
            },
            {
                "Date": "115/08/20",
                "SecuritiesCompanyCode": "6505",
                "SecuritiesIndustryCode": "20",
                "CompanyName": "丁",
            },
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _base_kwargs() -> dict[str, object]:
    return {
        "raw_payloads": {"twse": _twse_payload(), "tpex": _tpex_payload()},
        "license_ids": {
            "twse": "twse-open-data-license-v1",
            "tpex": "tpex-open-data-license-v1",
        },
        "license_urls": {
            "twse": "https://openapi.twse.com.tw/",
            "tpex": "https://www.tpex.org.tw/openapi/",
        },
        "publication_at": {"twse": _PUBLICATION_AT, "tpex": _PUBLICATION_AT},
        "expected_symbols": ("1101", "2317", "2330", "6505"),
        "clock_id": "clock:prospective:20260825:rule-only-test",
        "clock_manifest_hash": "sha256:" + "3" * 64,
        "universe_hash": "sha256:" + "5" * 64,
        "available_at": _AVAILABLE_AT,
        "effective_from": _EFFECTIVE_FROM,
        "now": _PREFLIGHT_NOW,
    }


def test_official_capture_builds_rows_and_complete_lineage() -> None:
    capture = build_official_first_seen_capture(**_base_kwargs())

    assert capture.expected_symbols == ("1101", "2317", "2330", "6505")
    assert [row["symbol"] for row in capture.rows] == ["1101", "2317", "2330", "6505"]
    assert [row["sector_id"] for row in capture.rows] == ["01", "28", "24", "20"]
    assert [item["market"] for item in capture.source_registry] == [
        "tpex_otc",
        "twse_listed",
    ]
    for source in capture.source_registry:
        assert source["source_hash"] == source["raw_hash"]
        assert str(source["canonical_rows_hash"]).startswith("sha256:")
        assert source["clock_id"] == "clock:prospective:20260825:rule-only-test"
        assert source["universe_hash"] == "sha256:" + "5" * 64
        assert source["publication_date"] == "2026-08-20"
        assert source["effective_from"] == "2026-08-25"
        assert source["source_registry_hash"].startswith("sha256:")
    assert capture.to_dict()["secret_values_emitted"] is False


def test_official_capture_is_accepted_by_existing_pit_sidecar_contract(
    tmp_path: Path,
) -> None:
    clock = _clock(tmp_path)
    kwargs = _base_kwargs()
    kwargs["clock_manifest_hash"] = clock.manifest_hash
    kwargs["universe_hash"] = str(clock.payload["universe_hash"])
    capture = build_official_first_seen_capture(**kwargs)

    output = tmp_path / "official-pit.json"
    result = capture_prospective_pit_sector_membership(
        clock=clock,
        output_path=output,
        decision_timestamp="2026-08-25T08:30:00+08:00",
        now=_CAPTURE_NOW,
        rows=capture.rows,
        source_registry=capture.source_registry,
        expected_symbols=capture.expected_symbols,
    )
    validated = validate_prospective_pit_sector_membership(
        sidecar_path=output,
        clock=clock,
        decision_timestamp="2026-08-25T08:30:00+08:00",
        now=_CAPTURE_NOW,
        expected_symbols=capture.expected_symbols,
    )
    assert result.row_count == 4
    assert validated.canonical_hash == result.canonical_hash
    assert validated.source_ids == (
        "official:tpex:t187ap03_O",
        "official:twse:t187ap03_L",
    )


def test_unknown_industry_code_fails_closed() -> None:
    payload = json.loads(_twse_payload().decode("utf-8"))
    payload[0]["產業別"] = "99"
    kwargs = _base_kwargs()
    kwargs["raw_payloads"] = {
        "twse": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "tpex": _tpex_payload(),
    }
    with pytest.raises(ProspectiveOfficialPITSourceError, match="industry code"):
        build_official_first_seen_capture(**kwargs)


def test_missing_symbol_and_publication_mismatch_fail_closed() -> None:
    kwargs = _base_kwargs()
    kwargs["expected_symbols"] = ("1101", "2317", "2330", "6505", "9999")
    with pytest.raises(ProspectiveOfficialPITSourceError, match="missing expected"):
        build_official_first_seen_capture(**kwargs)

    kwargs = _base_kwargs()
    kwargs["publication_at"] = {
        "twse": datetime.fromisoformat("2026-08-19T23:00:00+08:00"),
        "tpex": _PUBLICATION_AT,
    }
    with pytest.raises(ProspectiveOfficialPITSourceError, match="publication_at"):
        build_official_first_seen_capture(**kwargs)


def test_emerging_source_is_conditional_on_clock_universe() -> None:
    emerging_payload = json.dumps(
        [
            {
                "Date": "115/08/20",
                "SecuritiesCompanyCode": "7000",
                "SecuritiesIndustryCode": "20",
            }
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    kwargs = _base_kwargs()
    kwargs["raw_payloads"] = {
        "twse": _twse_payload(),
        "tpex": _tpex_payload(),
        "emerging": emerging_payload,
    }
    with pytest.raises(ProspectiveOfficialPITSourceError, match="t187ap03_R"):
        build_official_first_seen_capture(**kwargs)

    kwargs["raw_payloads"] = {"twse": _twse_payload(), "emerging": emerging_payload}
    kwargs["expected_symbols"] = ("1101", "2330", "7000")
    kwargs["license_ids"] = {
        "twse": "twse-open-data-license-v1",
        "emerging": "tpex-open-data-license-v1",
    }
    kwargs["license_urls"] = {
        "twse": "https://openapi.twse.com.tw/",
        "emerging": "https://www.tpex.org.tw/openapi/",
    }
    kwargs["publication_at"] = {"twse": _PUBLICATION_AT, "emerging": _PUBLICATION_AT}
    capture = build_official_first_seen_capture(**kwargs)
    assert [item["dataset_id"] for item in capture.source_registry] == [
        "t187ap03_R",
        "t187ap03_L",
    ]


def test_preactivation_effective_date_and_unlicensed_source_fail_closed() -> None:
    kwargs = _base_kwargs()
    kwargs["effective_from"] = date(2026, 8, 20)
    with pytest.raises(ProspectiveOfficialPITSourceError, match="effective_from"):
        build_official_first_seen_capture(**kwargs)

    kwargs = _base_kwargs()
    kwargs["license_ids"] = {
        "twse": "unknown",
        "tpex": "tpex-open-data-license-v1",
    }
    with pytest.raises(ProspectiveOfficialPITSourceError, match="license_id"):
        build_official_first_seen_capture(**kwargs)


def test_official_fixture_cli_writes_only_the_requested_sidecar(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.capture_prospective_official_pit_sector import main

    _clock(tmp_path)
    twse_path = tmp_path / "twse.json"
    tpex_path = tmp_path / "tpex.json"
    twse_path.write_bytes(_twse_payload())
    tpex_path.write_bytes(_tpex_payload())
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "twse": {
                    "license_id": "twse-open-data-license-v1",
                    "license_url": "https://openapi.twse.com.tw/",
                    "publication_at": _PUBLICATION_AT.isoformat(),
                },
                "tpex": {
                    "license_id": "tpex-open-data-license-v1",
                    "license_url": "https://www.tpex.org.tw/openapi/",
                    "publication_at": _PUBLICATION_AT.isoformat(),
                },
            }
        ),
        encoding="utf-8",
    )
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(
        json.dumps(["1101", "2317", "2330", "6505"]),
        encoding="utf-8",
    )
    output = tmp_path / "official-pit.jsonl.gz"

    exit_code = main(
        [
            "--fixture-only",
            "--clock-manifest",
            str(tmp_path / "clock.json"),
            "--now",
            _CAPTURE_NOW.isoformat(),
            "--decision-timestamp",
            "2026-08-25T08:30:00+08:00",
            "--available-at",
            _AVAILABLE_AT.isoformat(),
            "--effective-from",
            "2026-08-25",
            "--symbols-json",
            str(symbols_path),
            "--source-metadata-json",
            str(metadata_path),
            "--twse-raw-json",
            str(twse_path),
            "--tpex-raw-json",
            str(tpex_path),
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.is_file()
    assert '"status": "accepted"' in captured.out
    assert '"secret_values_emitted": false' in captured.out
    assert captured.err == ""
