from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sqlite3

import pytest

from data_module.institutional_credit_flows_service import (
    APPLY_CONFIRM_TOKEN,
    FlowApplyError,
    HttpResponse,
    apply_flow_manifest,
    capture_recent_flows,
)


SESSION_DATES = {"2026-09-07", "2026-09-08"}


def _date_from_params(params: dict[str, str]) -> str:
    if "date" in params:
        raw = params["date"]
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    raw = params["d"].replace("/", "")
    return f"{int(raw[:3]) + 1911:04d}-{raw[3:5]}-{raw[5:]}"


def _twse_institutional_payload(day: str) -> bytes:
    compact = day.replace("-", "")
    fields = [
        "證券代號", "證券名稱", "外陸資買進股數(不含外資自營商)",
        "外陸資賣出股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)",
        "外資自營商買進股數", "外資自營商賣出股數", "外資自營商買賣超股數",
        "投信買進股數", "投信賣出股數", "投信買賣超股數", "自營商買賣超股數",
        "自營商買進股數(自行買賣)", "自營商賣出股數(自行買賣)",
        "自營商買賣超股數(自行買賣)", "自營商買進股數(避險)",
        "自營商賣出股數(避險)", "自營商買賣超股數(避險)", "三大法人買賣超股數",
    ]
    row = [
        "2330", "台積電", "100", "50", "50", "10", "5", "5", "30", "20",
        "10", "5", "4", "3", "1", "6", "2", "4", "69",
    ]
    payload = {
        "stat": "OK",
        "date": compact,
        "publicationTime": f"{day}T17:30:00+08:00",
        "fields": fields,
        "data": [row],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _twse_credit_payload(day: str) -> bytes:
    compact = day.replace("-", "")
    payload = {
        "stat": "OK",
        "date": compact,
        "tables": [
            {
                "title": "信用交易統計",
                "fields": ["項目", "買進", "賣出", "現金償還", "前日餘額", "今日餘額"],
                "data": [["融資(交易單位)", "1", "1", "0", "2", "2"]],
            },
            {
                "title": "融資融券彙總",
                "fields": [
                    "代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額",
                    "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額",
                    "今日餘額", "次一營業日限額", "資券互抵", "註記",
                ],
                "data": [["2330", "台積電", "12", "3", "0", "100", "109", "999", "2", "1", "0", "20", "21", "999", "0", ""]],
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _tpex_institutional_payload(day: str) -> bytes:
    roc = f"{int(day[:4]) - 1911:03d}/{day[5:7]}/{day[8:]}"
    row = [
        "6547", "高端疫苗", "100", "20", "80", "0", "0", "0", "100", "20", "80",
        "5", "3", "2", "1", "1", "0", "2", "1", "1", "3", "1", "2", "82",
    ]
    payload = {
        "columnNum": 25,
        "tables": [{
            "title": "三大法人買賣明細資訊",
            "date": roc,
            "fields": ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7 + ["三大法人買賣超股數合計"],
            "data": [row],
        }],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _tpex_credit_payload(day: str) -> bytes:
    roc = f"{int(day[:4]) - 1911:03d}/{day[5:7]}/{day[8:]}"
    row = [
        "6547", "高端疫苗", "100", "10", "2", "0", "108", "1", "1.2", "999",
        "20", "2", "0", "0", "22", "0", "0.1", "999", "0", "",
    ]
    payload = {
        "date": day.replace("-", ""),
        "tables": [{
            "title": "上櫃股票融資融券餘額",
            "date": roc,
            "fields": [
                "代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額",
                "資屬證金", "資使用率(%)", "資限額", "前券餘額(張)", "券賣",
                "券買", "券償", "券餘額", "券屬證金", "券使用率(%)", "券限額",
                "資券相抵(張)", "備註",
            ],
            "data": [row],
        }],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _fake_transport(url: str, params: dict[str, str], timeout: int) -> HttpResponse:
    day = _date_from_params(params)
    if "fund/T86" in url:
        payload = _twse_institutional_payload(day) if day in SESSION_DATES else json.dumps({"stat": "No data", "date": day}).encode()
    elif "MI_MARGN" in url:
        payload = _twse_credit_payload(day)
    elif "3itrade_hedge_result" in url:
        payload = _tpex_institutional_payload(day)
    elif "margin_bal_result" in url:
        payload = _tpex_credit_payload(day)
    else:
        raise AssertionError(url)
    return HttpResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        payload=payload,
        url=url,
        attempts=1,
    )


def test_capture_preserves_raw_bytes_and_merges_two_official_markets(tmp_path: Path) -> None:
    result = capture_recent_flows(
        output_root=tmp_path / "flows",
        as_of_date=date(2026, 9, 8),
        sessions=2,
        max_lookback_days=4,
        transport=_fake_transport,
        rate_limit_seconds=0,
    )

    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["candidate_only"] is True
    assert manifest["formal_apply_allowed"] is False
    assert manifest["discovered_sessions"] == ["2026-09-07", "2026-09-08"]
    assert manifest["totals"] == {"institutional_flows": 4, "credit_transactions": 4}
    assert len(manifest["sources"]) == 4
    assert all(len(item["raw_artifacts"]) == 2 for item in manifest["sources"])
    institutional = next(item for item in manifest["sources"] if item["source_id"] == "institutional_flows")
    rows = json.loads((manifest_path.parent / institutional["candidate_rows_path"]).read_text(encoding="utf-8"))
    assert {item["values"]["stock_code"] for item in rows} == {"2330", "6547"}
    assert rows[0]["provenance"]["quantity_unit"] == "shares"
    credit = next(item for item in manifest["sources"] if item["source_id"] == "credit_transactions")
    credit_rows = json.loads((manifest_path.parent / credit["candidate_rows_path"]).read_text(encoding="utf-8"))
    assert {item["provenance"]["quantity_unit"] for item in credit_rows} == {"trading_units", "lots"}
    twse = next(item for item in manifest["sources"] if item["source_id"] == "institutional_flows" and item["decision_date"] == "2026-09-08")
    raw_path = manifest_path.parent / next(artifact["path"] for artifact in twse["raw_artifacts"] if "twse_T86" in artifact["path"])
    assert raw_path.read_bytes() == _twse_institutional_payload("2026-09-08")


def test_apply_requires_explicit_token_and_is_idempotent(tmp_path: Path) -> None:
    result = capture_recent_flows(
        output_root=tmp_path / "flows",
        as_of_date=date(2026, 9, 8),
        sessions=2,
        max_lookback_days=4,
        transport=_fake_transport,
        rate_limit_seconds=0,
    )
    manifest = result["manifest_path"]
    db_path = tmp_path / "formal-copy.sqlite"
    with pytest.raises(FlowApplyError, match="confirm token"):
        apply_flow_manifest(manifest, db_path=db_path, confirm_token="wrong")
    assert not db_path.exists()

    first = apply_flow_manifest(manifest, db_path=db_path, confirm_token=APPLY_CONFIRM_TOKEN)
    assert first["inserted"] == 8
    assert first["duplicates"] == 0
    second = apply_flow_manifest(manifest, db_path=db_path, confirm_token=APPLY_CONFIRM_TOKEN)
    assert second["inserted"] == 0
    assert second["duplicates"] == 8
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("select count(*) from institutional_flows").fetchone()[0] == 4
        assert conn.execute("select count(*) from credit_transactions").fetchone()[0] == 4
        assert conn.execute("select available_date from institutional_flows where stock_code='2330' and decision_date='2026-09-08'").fetchone()[0] == "2026-09-08"
        assert conn.execute("select available_date from institutional_flows where stock_code='6547' and decision_date='2026-09-08'").fetchone()[0] is None


def test_tampered_raw_artifact_is_rejected_before_db_write(tmp_path: Path) -> None:
    result = capture_recent_flows(
        output_root=tmp_path / "flows",
        as_of_date=date(2026, 9, 8),
        sessions=1,
        max_lookback_days=2,
        transport=_fake_transport,
        rate_limit_seconds=0,
    )
    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = manifest_path.parent / manifest["sources"][0]["raw_artifacts"][0]["path"]
    raw.write_bytes(raw.read_bytes() + b"tamper")
    with pytest.raises(FlowApplyError, match="raw artifact hash/path"):
        apply_flow_manifest(manifest_path, db_path=tmp_path / "db.sqlite", confirm_token=APPLY_CONFIRM_TOKEN)


def test_existing_conflicting_row_fails_closed(tmp_path: Path) -> None:
    result = capture_recent_flows(
        output_root=tmp_path / "flows",
        as_of_date=date(2026, 9, 8),
        sessions=1,
        max_lookback_days=2,
        transport=_fake_transport,
        rate_limit_seconds=0,
    )
    db_path = tmp_path / "db.sqlite"
    apply_flow_manifest(result["manifest_path"], db_path=db_path, confirm_token=APPLY_CONFIRM_TOKEN)
    with sqlite3.connect(db_path) as conn:
        conn.execute("update institutional_flows set foreign_investor_net=999 where stock_code='2330'")
        conn.commit()
    with pytest.raises(FlowApplyError, match="既有列內容衝突"):
        apply_flow_manifest(result["manifest_path"], db_path=db_path, confirm_token=APPLY_CONFIRM_TOKEN)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("select foreign_investor_net from institutional_flows where stock_code='2330'").fetchone()[0] == 999
