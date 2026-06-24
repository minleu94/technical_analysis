import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from contextlib import contextmanager
from app_module.broker_branch_update_service import BrokerBranchUpdateService
from bs4 import BeautifulSoup

class DummyConfig:
    def __init__(self, tmp_path):
        self.data_root = tmp_path
        self.meta_data_dir = tmp_path / "meta_data"
        self.broker_branch_registry_file = self.meta_data_dir / "broker_branch_registry.csv"
        self.broker_flow_dir = tmp_path / "broker_flow"

def test_decode_unicode_hex(tmp_path):
    config = DummyConfig(tmp_path)
    service = BrokerBranchUpdateService(config)

    # 測試正常解密
    assert service._decode_unicode_hex("0039004100390069") == "9A9i"
    assert service._decode_unicode_hex("003800380038004b") == "888K"

    # 測試自動補零解密 (長度 12 到 15 之間)
    # "003800380038004b" 少前置 00 為 "3800380038004b" (14碼)
    assert service._decode_unicode_hex("3800380038004b") == "888K"

    # 測試非 hex 字串
    assert service._decode_unicode_hex("not_hex_string_1") == "not_hex_string_1"

    # 測試短字串
    assert service._decode_unicode_hex("short") == "short"

    # 測試空值
    assert service._decode_unicode_hex("") == ""
    assert service._decode_unicode_hex(None) is None


def test_build_branch_url_uses_explicit_moneydj_metric(tmp_path):
    service = BrokerBranchUpdateService(DummyConfig(tmp_path))
    branch = {"branch_system_key": "8450_845B", "url_param_a": "8450", "url_param_b": "0038003400350042"}

    lots_url = service._build_branch_url(branch, "2026-06-10", "2026-06-11", metric="lots")
    amount_url = service._build_branch_url(branch, "2026-06-10", "2026-06-11", metric="amount")

    assert "c=E" in lots_url
    assert "c=B" in amount_url


def test_merge_metric_records_keeps_lots_and_amount_separate(tmp_path):
    service = BrokerBranchUpdateService(DummyConfig(tmp_path))
    common = {
        "date": "2026-06-11",
        "trade_type": "買超",
        "branch_system_key": "8450_845B",
        "branch_broker_code": "8450",
        "branch_code": "845B",
        "branch_display_name": "康和-永和",
        "counterparty_broker_code": "00631L",
        "counterparty_broker_name": "元大台灣50正2",
    }

    merged = service._merge_metric_records(
        [{**common, "buy_lots": 160, "sell_lots": 20, "net_lots": 140, "metric_rank": 3}],
        [{
            **common,
            "buy_amount_k_twd": 5291,
            "sell_amount_k_twd": 653,
            "net_amount_k_twd": 4638,
            "metric_rank": 7,
        }],
    )

    assert merged == [{
        **common,
        "buy_lots": 160,
        "sell_lots": 20,
        "net_lots": 140,
        "buy_amount_k_twd": 5291,
        "sell_amount_k_twd": 653,
        "net_amount_k_twd": 4638,
        "lots_observed": True,
        "amount_observed": True,
        "lots_rank": 3,
        "amount_rank": 7,
    }]


@pytest.mark.parametrize(
    ("metric", "header", "expected"),
    [
        ("lots", "買進張數", {"buy_lots": 160, "sell_lots": 20, "net_lots": 140}),
        (
            "amount",
            "買進金額",
            {"buy_amount_k_twd": 5291, "sell_amount_k_twd": 653, "net_amount_k_twd": 4638},
        ),
    ],
)
def test_parse_metric_tables_uses_headers_instead_of_fixed_indexes(tmp_path, metric, header, expected):
    service = BrokerBranchUpdateService(DummyConfig(tmp_path))
    html = f"""
    <html><body>
      <table><tr><td>layout</td></tr></table>
      <table>
        <tr><th>股票</th><th>{header}</th><th>賣出</th><th>差額</th></tr>
        <tr><td>00631L元大台灣50正2</td><td>{expected[next(iter(expected))]:,}</td><td>{list(expected.values())[1]:,}</td><td>{list(expected.values())[2]:,}</td></tr>
      </table>
    </body></html>
    """
    branch = {
        "branch_system_key": "8450_845B",
        "branch_broker_code": "8450",
        "branch_code": "845B",
        "branch_display_name": "康和-永和",
    }

    records = service._parse_metric_tables(
        BeautifulSoup(html, "html.parser").find_all("table"),
        branch,
        "2026-06-11",
        metric,
    )

    assert len(records) == 1
    for key, value in expected.items():
        assert records[0][key] == value


def test_parse_metric_tables_reads_genlink2stk_script_rows(tmp_path):
    service = BrokerBranchUpdateService(DummyConfig(tmp_path))
    html = """
    <table>
      <tbody>
        <tr><td colspan="4">買超</td></tr>
        <tr><td>券商名稱</td><td>買進張數</td><td>賣出張數</td><td>差額</td></tr>
        <tr>
          <td><script>GenLink2stk('AS3296','勝德');</script></td>
          <td>163</td><td>0</td><td>163</td>
        </tr>
      </tbody>
    </table>
    """
    branch = {
        "branch_system_key": "8450_845B",
        "branch_broker_code": "8450",
        "branch_code": "845B",
        "branch_display_name": "康和-永和",
    }

    records = service._parse_metric_tables(
        BeautifulSoup(html, "html.parser").find_all("table"),
        branch,
        "2026-06-11",
        "lots",
    )

    assert records[0]["counterparty_broker_code"] == "3296"
    assert records[0]["counterparty_broker_name"] == "勝德"
    assert records[0]["net_lots"] == 163
    assert records[0]["metric_source"] == "lots"
    assert records[0]["metric_rank"] == 1


def test_fetch_metric_records_http_decodes_moneydj_big5_and_parses_rows(tmp_path, monkeypatch):
    service = BrokerBranchUpdateService(DummyConfig(tmp_path))
    branch = {
        "branch_system_key": "8450_845B",
        "branch_broker_code": "8450",
        "branch_code": "845B",
        "branch_display_name": "康和-永和",
        "url_param_a": "8450",
        "url_param_b": "845B",
    }
    html = """
    <html><body>
      <table>
        <tbody>
          <tr><td colspan="4">買超</td></tr>
          <tr><td>股票</td><td>買進張數</td><td>賣出張數</td><td>差額</td></tr>
          <tr><td><script>GenLink2stk('AS3296','勝德');</script></td><td>163</td><td>0</td><td>163</td></tr>
        </tbody>
      </table>
    </body></html>
    """

    class FakeResponse:
        status_code = 200
        content = html.encode("big5")

        def raise_for_status(self):
            return None

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr("app_module.broker_branch_update_service.requests.get", fake_get)

    records = service._fetch_metric_records_http(branch, "2026-06-11", "lots", retries=1)

    assert "c=E" in captured["url"]
    assert captured["kwargs"]["timeout"] == 30
    assert len(records) == 1
    assert records[0]["counterparty_broker_code"] == "3296"
    assert records[0]["net_lots"] == 163


def test_fetch_metric_records_http_marks_valid_empty_moneydj_page_as_no_data(tmp_path, monkeypatch):
    service = BrokerBranchUpdateService(DummyConfig(tmp_path))
    branch = {
        "branch_system_key": "8450_845B",
        "branch_broker_code": "8450",
        "branch_code": "845B",
        "branch_display_name": "康和-永和",
        "url_param_a": "8450",
        "url_param_b": "845B",
    }
    html = """
    <html><body>
      <table><tr><td>券商進出排行</td></tr></table>
      <table><tr><td>資料日期：</td></tr></table>
    </body></html>
    """

    class FakeResponse:
        status_code = 200
        content = html.encode("big5")

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "app_module.broker_branch_update_service.requests.get",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(RuntimeError, match="MoneyDJ lots 頁面未解析到交易資料"):
        service._fetch_metric_records_http(branch, "2026-04-06", "lots", retries=1)


def test_update_broker_branch_data_uses_http_fast_path_without_driver(tmp_path, monkeypatch):
    config = DummyConfig(tmp_path)
    config.meta_data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "branch_system_key": ["8450_845B"],
        "branch_broker_code": ["8450"],
        "branch_code": ["845B"],
        "branch_display_name": ["康和-永和"],
        "url_param_a": ["8450"],
        "url_param_b": ["0038003400350042"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")

    service = BrokerBranchUpdateService(config)

    def fake_http(branch_info, date_str, metric, retries=3, timeout=30):
        common = {
            "date": date_str,
            "trade_type": "買超",
            "branch_system_key": branch_info["branch_system_key"],
            "branch_broker_code": branch_info["branch_broker_code"],
            "branch_code": branch_info["branch_code"],
            "branch_display_name": branch_info["branch_display_name"],
            "counterparty_broker_code": "2330",
            "counterparty_broker_name": "台積電",
            "metric_rank": 1,
        }
        if metric == "lots":
            return [{**common, "metric_source": "lots", "buy_lots": 10, "sell_lots": 2, "net_lots": 8}]
        return [{
            **common,
            "metric_source": "amount",
            "buy_amount_k_twd": 1000,
            "sell_amount_k_twd": 200,
            "net_amount_k_twd": 800,
        }]

    monkeypatch.setattr(service, "_fetch_metric_records_http", fake_http)

    def fail_driver():
        raise AssertionError("HTTP fast path should not create Selenium driver")

    monkeypatch.setattr(service, "_get_driver", fail_driver)

    result = service.update_broker_branch_data("2026-06-11", "2026-06-11", delay_seconds=0)

    assert result["success"] is True
    assert result["total_records"] == 1
    daily_file = config.broker_flow_dir / "8450_845B" / "daily" / "2026-06-11.csv"
    saved = pd.read_csv(daily_file, encoding="utf-8-sig")
    assert saved.loc[0, "buy_lots"] == 10
    assert saved.loc[0, "buy_amount_k_twd"] == 1000
    assert bool(saved.loc[0, "lots_observed"]) is True
    assert bool(saved.loc[0, "amount_observed"]) is True


def test_update_broker_branch_data_skips_dates_without_daily_price_evidence(tmp_path, monkeypatch):
    config = DummyConfig(tmp_path)
    config.daily_price_dir = tmp_path / "daily_price"
    config.tpex_daily_price_dir = tmp_path / "daily_price_tpex"
    config.db_file = tmp_path / "stock_data.db"
    config.use_sqlite = False
    config.meta_data_dir.mkdir(parents=True, exist_ok=True)
    config.daily_price_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "branch_system_key": ["8450_845B"],
        "branch_broker_code": ["8450"],
        "branch_code": ["845B"],
        "branch_display_name": ["康和-永和"],
        "url_param_a": ["8450"],
        "url_param_b": ["0038003400350042"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")
    pd.DataFrame([{"日期": "20260407", "證券代號": "2330"}]).to_csv(
        config.daily_price_dir / "20260407.csv",
        index=False,
        encoding="utf-8-sig",
    )

    service = BrokerBranchUpdateService(config)
    requested_dates = []

    def fake_http(branch_info, date_str, metric, retries=3, timeout=30):
        requested_dates.append((date_str, metric))
        common = {
            "date": date_str,
            "trade_type": "買超",
            "branch_system_key": branch_info["branch_system_key"],
            "branch_broker_code": branch_info["branch_broker_code"],
            "branch_code": branch_info["branch_code"],
            "branch_display_name": branch_info["branch_display_name"],
            "counterparty_broker_code": "2330",
            "counterparty_broker_name": "台積電",
            "metric_rank": 1,
        }
        if metric == "lots":
            return [{**common, "metric_source": "lots", "buy_lots": 10, "sell_lots": 2, "net_lots": 8}]
        return [{
            **common,
            "metric_source": "amount",
            "buy_amount_k_twd": 1000,
            "sell_amount_k_twd": 200,
            "net_amount_k_twd": 800,
        }]

    monkeypatch.setattr(service, "_fetch_metric_records_http", fake_http)
    monkeypatch.setattr(
        service,
        "_get_driver",
        lambda: (_ for _ in ()).throw(AssertionError("非交易日不應進入 Selenium fallback")),
    )

    result = service.update_broker_branch_data(
        "2026-04-06",
        "2026-04-07",
        delay_seconds=0,
        force_all=True,
    )

    assert result["success"] is True
    assert result["non_trading_dates"] == ["2026-04-06"]
    assert requested_dates == [("2026-04-07", "lots"), ("2026-04-07", "amount")]
    assert not (config.broker_flow_dir / "8450_845B" / "daily" / "2026-04-06.csv").exists()
    assert (config.broker_flow_dir / "8450_845B" / "daily" / "2026-04-07.csv").exists()


def test_update_broker_branch_data_returns_success_when_all_dates_are_non_trading(tmp_path, monkeypatch):
    config = DummyConfig(tmp_path)
    config.daily_price_dir = tmp_path / "daily_price"
    config.tpex_daily_price_dir = tmp_path / "daily_price_tpex"
    config.db_file = tmp_path / "stock_data.db"
    config.use_sqlite = False
    config.meta_data_dir.mkdir(parents=True, exist_ok=True)
    config.daily_price_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "branch_system_key": ["8450_845B"],
        "branch_broker_code": ["8450"],
        "branch_code": ["845B"],
        "branch_display_name": ["康和-永和"],
        "url_param_a": ["8450"],
        "url_param_b": ["0038003400350042"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")
    pd.DataFrame([{"日期": "20260407", "證券代號": "2330"}]).to_csv(
        config.daily_price_dir / "20260407.csv",
        index=False,
        encoding="utf-8-sig",
    )

    service = BrokerBranchUpdateService(config)
    monkeypatch.setattr(
        service,
        "_fetch_metric_records_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("非交易日不應抓 MoneyDJ")),
    )

    result = service.update_broker_branch_data(
        "2026-04-06",
        "2026-04-06",
        delay_seconds=0,
        force_all=True,
    )

    assert result["success"] is True
    assert result["message"] == "券商分點更新完成：目標日期皆無交易日行情，已跳過 MoneyDJ 抓取"
    assert result["non_trading_dates"] == ["2026-04-06"]
    assert result["total_processed"] == 0


def test_infer_metric_ranks_for_legacy_daily_rows(tmp_path):
    service = BrokerBranchUpdateService(DummyConfig(tmp_path))
    df = pd.DataFrame([
        {
            "date": "2026-06-11",
            "trade_type": "買超",
            "branch_system_key": "8450_845B",
            "net_lots": 100,
            "net_amount_k_twd": 1000,
            "lots_observed": True,
            "amount_observed": True,
        },
        {
            "date": "2026-06-11",
            "trade_type": "買超",
            "branch_system_key": "8450_845B",
            "net_lots": 200,
            "net_amount_k_twd": 500,
            "lots_observed": True,
            "amount_observed": True,
        },
    ])

    ranked = service._infer_metric_ranks(df)

    assert ranked["lots_rank"].tolist() == [2, 1]
    assert ranked["amount_rank"].tolist() == [1, 2]

def test_headquarters_detection_and_decoding(tmp_path):
    config = DummyConfig(tmp_path)
    config.meta_data_dir.mkdir(parents=True, exist_ok=True)

    # 建立測試用的 registry CSV
    df = pd.DataFrame({
        "branch_system_key": ["9200_9200", "9200_9201", "1110_1110", "1110_111A", "0039_0039"],
        "branch_broker_code": ["9200", "9200", "1110", "1110", "0039"],
        "branch_code": ["9200", "", "1110", "111A", ""],
        "branch_display_name": ["凱基證券", "凱基證券-台北分公司", "土銀", "土銀新竹分行", "測試分點"],
        "url_param_a": ["9200", "9200", "1110", "1110", "0039"],
        # url_param_b 為 Unicode Hex 表示, "0039004100390069" = "9A9i"
        "url_param_b": ["0039003200300030", "0039003200300031", "0031003100310030", "0031003100310041", "0039004100390069"],
        "is_active": [True, True, True, True, True]
    })

    df.to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")

    service = BrokerBranchUpdateService(config)
    branches = service._load_branch_registry(active_only=True)

    assert len(branches) == 5

    # 9200_9200: branch_broker_code == branch_code ("9200" == "9200"), is_headquarters 應為 True
    b1 = next(b for b in branches if b["branch_system_key"] == "9200_9200")
    assert b1["is_headquarters"] is True

    # 9200_9201: display_name 包含 "-台北分公司", is_headquarters 應為 False
    b2 = next(b for b in branches if b["branch_system_key"] == "9200_9201")
    assert b2["is_headquarters"] is False

    # 1110_1110: branch_broker_code == branch_code,且 display_name 是 "土銀", is_headquarters 應為 True
    b3 = next(b for b in branches if b["branch_system_key"] == "1110_1110")
    assert b3["is_headquarters"] is True

    # 1110_111A: display_name 包含 "分行", is_headquarters 應為 False
    b4 = next(b for b in branches if b["branch_system_key"] == "1110_111A")
    assert b4["is_headquarters"] is False

    # 0039_0039: url_param_b 是 "0039004100390069"，解密後為 "9A9i"，應自動覆蓋至 branch_code
    b5 = next(b for b in branches if b["branch_system_key"] == "0039_0039")
    assert b5["branch_code"] == "9A9i"
    # 總部判定不成立（因為 broker_code '0039' != branch_code '9A9i'，且名稱無總公司關鍵字）
    assert b5["is_headquarters"] is False


def test_update_broker_branch_data_skips_existing_sqlite_rows_by_display_name(tmp_path, monkeypatch):
    import sqlite3

    config = DummyConfig(tmp_path)
    config.meta_data_dir.mkdir(parents=True, exist_ok=True)
    config.use_sqlite = True
    config.db_file = tmp_path / "sqlite" / "twstock.db"
    config.db_file.parent.mkdir(parents=True)

    pd.DataFrame({
        "branch_system_key": ["8450_845B"],
        "branch_broker_code": ["8450"],
        "branch_code": ["845B"],
        "branch_display_name": ["康和-永和"],
        "url_param_a": ["8450"],
        "url_param_b": ["0038003400350042"],
        "is_active": [True],
    }).to_csv(config.broker_branch_registry_file, index=False, encoding="utf-8-sig")

    with sqlite3.connect(config.db_file) as conn:
        conn.execute(
            """
            CREATE TABLE broker_flows (
                日期 TEXT,
                分點名稱 TEXT,
                證券代號 TEXT,
                買進股數 INTEGER,
                買進金額千元 INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO broker_flows (日期, 分點名稱, 證券代號, 買進股數, 買進金額千元) VALUES (?, ?, ?, ?, ?)",
            ("20260616", "康和-永和", "2330", 1000, 500),
        )

    service = BrokerBranchUpdateService(config)
    driver = MagicMock()

    @contextmanager
    def fake_driver():
        yield driver

    monkeypatch.setattr(service, "_get_driver", fake_driver)
    result = service.update_broker_branch_data(
        "2026-06-16",
        "2026-06-16",
        delay_seconds=0,
    )

    assert result["success"] is True
    assert result["skipped_dates"] == ["2026-06-16"]
    driver.get.assert_not_called()
