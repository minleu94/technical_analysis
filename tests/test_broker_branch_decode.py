import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from app_module.broker_branch_update_service import BrokerBranchUpdateService

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
