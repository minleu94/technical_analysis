import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock
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
        [{**common, "buy_lots": 160, "sell_lots": 20, "net_lots": 140}],
        [{**common, "buy_amount_k_twd": 5291, "sell_amount_k_twd": 653, "net_amount_k_twd": 4638}],
    )

    assert merged == [{
        **common,
        "buy_lots": 160,
        "sell_lots": 20,
        "net_lots": 140,
        "buy_amount_k_twd": 5291,
        "sell_amount_k_twd": 653,
        "net_amount_k_twd": 4638,
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
