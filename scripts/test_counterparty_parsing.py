"""
測試對手券商名稱解析邏輯
驗證改進後的解析方法是否能正確處理各種格式
"""

import sys
import os
from pathlib import Path

# 設置 UTF-8 編碼（Windows 終端機支援）
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

# 添加項目根目錄到路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from app_module.broker_branch_update_service import BrokerBranchUpdateService


def test_parsing():
    """測試各種格式的解析"""
    config = TWStockConfig()
    service = BrokerBranchUpdateService(config)
    
    # 測試案例
    test_cases = [
        # (輸入, 預期代碼, 預期名稱, 說明)
        # 標準券商格式
        ("1234元大證券", "1234", "元大證券", "標準券商格式"),
        ("9A00永豐證券", "9A00", "永豐證券", "標準券商格式（字母數字）"),
        ("5678富邦證券", "5678", "富邦證券", "標準券商格式"),
        
        # ETF 名稱
        ("元大台灣50", "ETF", "元大台灣50", "ETF 名稱"),
        ("元大高股息", "ETF", "元大高股息", "ETF 名稱"),
        ("富邦科技", "ETF", "富邦科技", "ETF 名稱"),
        ("國泰台灣50", "ETF", "國泰台灣50", "ETF 名稱"),
        
        # 特殊格式
        ("6643M31", "6643", "6643M31", "特殊格式（股票代號+標識）"),
        ("7722LINEPAY", "7722", "7722LINEPAY", "特殊格式（股票代號+標識）"),
        ("2330TSMC", "2330", "2330TSMC", "特殊格式（股票代號+標識）"),
        
        # 純中文（股票名稱）
        ("台積電", "STOCK", "台積電", "純中文股票名稱"),
        ("聯發科", "STOCK", "聯發科", "純中文股票名稱"),
        ("鴻海", "STOCK", "鴻海", "純中文股票名稱"),
        
        # 只有數字（可能是股票代號）
        ("2330", "2330", "2330", "純數字股票代號"),
        ("6643", "6643", "6643", "純數字股票代號"),
        
        # 邊界情況
        ("", "UNKNOWN", "", "空字串"),
        ("   ", "UNKNOWN", "", "空白字串"),
        ("ABC", "UNKNOWN", "ABC", "無法識別的格式"),
    ]
    
    print("="*80)
    print("[測試] 對手券商名稱解析測試")
    print("="*80)
    print(f"{'輸入':<25} {'預期代碼':<15} {'實際代碼':<15} {'預期名稱':<20} {'實際名稱':<20} {'結果':<10}")
    print("-"*80)
    
    passed = 0
    failed = 0
    
    for input_text, expected_code, expected_name, description in test_cases:
        code, name = service._parse_counterparty_broker_name(input_text)
        
        # 檢查結果
        code_match = code == expected_code
        name_match = name == expected_name
        success = code_match and name_match
        
        if success:
            passed += 1
            result = "[PASS]"
        else:
            failed += 1
            result = "[FAIL]"
        
        # 顯示結果
        print(f"{input_text:<25} {expected_code:<15} {code:<15} {expected_name:<20} {name:<20} {result:<10}")
        
        if not success:
            print(f"  [警告] 說明: {description}")
            if not code_match:
                print(f"     代碼不匹配: 預期 '{expected_code}', 實際 '{code}'")
            if not name_match:
                print(f"     名稱不匹配: 預期 '{expected_name}', 實際 '{name}'")
    
    print("="*80)
    print(f"[統計] 測試結果: {passed} 通過, {failed} 失敗 (總共 {len(test_cases)} 個測試)")
    print("="*80)
    
    if failed == 0:
        print("[成功] 所有測試通過！")
        return True
    else:
        print(f"[失敗] 有 {failed} 個測試失敗")
        return False


if __name__ == '__main__':
    success = test_parsing()
    sys.exit(0 if success else 1)

