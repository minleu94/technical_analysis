from __future__ import annotations

from datetime import date

import pytest

from data_module import official_phase3c_fetcher as fetcher


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class _CsvResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = "utf-8"


def _install_responses(monkeypatch, *payloads: dict[str, object]) -> None:
    responses = iter(_JsonResponse(payload) for payload in payloads)
    monkeypatch.setattr(fetcher, "safe_request", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(fetcher.time, "sleep", lambda _seconds: None)


def test_institutional_fetcher_supports_current_tpex_tables_shape(monkeypatch) -> None:
    twse_fields = [
        "證券代號",
        "證券名稱",
        "外陸資買進股數(不含外資自營商)",
        "外陸資賣出股數(不含外資自營商)",
        "外陸資買賣超股數(不含外資自營商)",
        "外資自營商買進股數",
        "外資自營商賣出股數",
        "外資自營商買賣超股數",
        "投信買進股數",
        "投信賣出股數",
        "投信買賣超股數",
        "自營商買進股數(自行買賣)",
        "自營商賣出股數(自行買賣)",
        "自營商買賣超股數(自行買賣)",
        "自營商買進股數(避險)",
        "自營商賣出股數(避險)",
        "自營商買賣超股數(避險)",
    ]
    twse_row = [
        "2330", "台積電", "100", "80", "20", "3", "2", "1",
        "10", "5", "5", "7", "4", "3", "2", "1", "1",
    ]
    tpex_row = [
        "6488", "環球晶",
        "90", "70", "20", "2", "1", "1", "92", "71", "21",
        "8", "3", "5", "6", "4", "2", "3", "1", "2",
        "9", "5", "4", "30",
    ]
    _install_responses(
        monkeypatch,
        {"stat": "OK", "date": "20260813", "fields": twse_fields, "data": [twse_row]},
        {
            "stat": "ok",
            "date": "20260813",
            "tables": [{"fields": ["代號"] + [f"欄{i}" for i in range(1, 24)], "data": [tpex_row]}],
        },
    )

    frame = fetcher.fetch_institutional_flows(date(2026, 8, 13))

    assert len(frame) == 2
    assert set(frame["source_version"]) == {
        "twse-official-T86",
        "tpex-official-3itrade",
    }
    twse = frame.loc[frame["stock_code"] == "2330"].iloc[0]
    assert int(twse["foreign_investor_buy"]) == 103
    assert int(twse["dealer_net"]) == 4
    tpex = frame.loc[frame["stock_code"] == "6488"].iloc[0]
    assert int(tpex["foreign_investor_net"]) == 21
    assert int(tpex["investment_trust_net"]) == 5
    assert int(tpex["dealer_net"]) == 4
    assert frame["available_date"].isna().all()


def test_credit_fetcher_supports_current_repeated_field_tables_shape(monkeypatch) -> None:
    twse_row = [
        "2330", "台積電", "100", "40", "5", "900", "955", "2000",
        "20", "30", "2", "110", "118", "500", "10", "",
    ]
    tpex_row = [
        "6488", "環球晶", "500", "70", "20", "5", "545", "1000",
        "80", "10", "15", "3", "2", "1", "12", "0", "0", "0", "0", "",
    ]
    _install_responses(
        monkeypatch,
        {
            "stat": "OK",
            "date": "20260813",
            "tables": [
                {"fields": ["項目", "買進", "賣出", "現金償還", "前日餘額", "今日餘額"], "data": [["融資", "1", "1", "0", "1", "1"]]},
                {"fields": ["代號"] + [f"欄{i}" for i in range(1, 16)], "data": [twse_row]},
            ],
        },
        {
            "stat": "ok",
            "date": "20260813",
            "tables": [{"fields": ["代號"] + [f"欄{i}" for i in range(1, 20)], "data": [tpex_row]}],
        },
    )

    frame = fetcher.fetch_credit_transactions(date(2026, 8, 13))

    assert len(frame) == 2
    twse = frame.loc[frame["stock_code"] == "2330"].iloc[0]
    assert int(twse["margin_purchase"]) == 100
    assert int(twse["margin_balance"]) == 955
    assert int(twse["short_sale"]) == 30
    assert int(twse["short_balance"]) == 118
    tpex = frame.loc[frame["stock_code"] == "6488"].iloc[0]
    assert int(tpex["margin_purchase"]) == 70
    assert int(tpex["margin_balance"]) == 545
    assert int(tpex["short_sale"]) == 3
    assert int(tpex["short_balance"]) == 12


def test_fetcher_fails_whole_date_when_official_response_date_drifts(monkeypatch) -> None:
    _install_responses(
        monkeypatch,
        {"stat": "OK", "date": "20260812", "fields": ["證券代號"], "data": [["2330"]]},
        {
            "stat": "ok",
            "date": "20260813",
            "tables": [{"fields": ["代號"] + [f"欄{i}" for i in range(1, 17)], "data": [["6488"] + ["0"] * 16]}],
        },
    )

    with pytest.raises(RuntimeError, match="官方回應日期不符"):
        fetcher.fetch_institutional_flows(date(2026, 8, 13))


def test_latest_tdcc_fetcher_uses_payload_week_date(monkeypatch) -> None:
    csv_text = (
        "資料日期,證券代號,持股分級,占集保庫存數比例%\n"
        "20260807,2330,15,60.50\n"
        "20260807,2330,5,10.25\n"
    )
    monkeypatch.setattr(
        fetcher,
        "safe_request",
        lambda *_args, **_kwargs: _CsvResponse(csv_text),
    )

    frame = fetcher.fetch_latest_tdcc_shareholding()

    assert len(frame) == 1
    assert frame.iloc[0]["decision_date"] == "2026-08-07"
    assert int(frame.iloc[0]["large_holder_ratio_bp"]) == 6050
    assert int(frame.iloc[0]["retail_holder_ratio_bp"]) == 1025
    assert int(frame.iloc[0]["dispersion_index_bp"]) == -5025
    assert fetcher.fetch_tdcc_shareholding(date(2026, 8, 13)).empty


def test_latest_tdcc_fetcher_rejects_ambiguous_payload_dates(monkeypatch) -> None:
    csv_text = (
        "資料日期,證券代號,持股分級,占集保庫存數比例%\n"
        "20260807,2330,15,60.50\n"
        "20260808,2317,15,50.00\n"
    )
    monkeypatch.setattr(
        fetcher,
        "safe_request",
        lambda *_args, **_kwargs: _CsvResponse(csv_text),
    )

    assert fetcher.fetch_latest_tdcc_shareholding().empty
