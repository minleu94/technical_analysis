#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
驗證 broker_branch_registry.csv 的中文顯示
"""

import sys
from pathlib import Path

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from data_module.config import TWStockConfig
from app_module.broker_branch_update_service import BrokerBranchUpdateService
import pandas as pd

# 設置 UTF-8 輸出
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def verify_registry():
    """驗證 registry 檔案"""
    config = TWStockConfig()
    registry_file = config.broker_branch_registry_file
    
    print(f"Registry 檔案路徑: {registry_file}")
    print(f"檔案是否存在: {registry_file.exists()}\n")
    
    if not registry_file.exists():
        print("ERROR: Registry 檔案不存在")
        return False
    
    # 方法 1: 直接讀取 CSV
    print("=== 方法 1: 直接讀取 CSV ===")
    df = pd.read_csv(registry_file, encoding='utf-8-sig')
    for idx, row in df.iterrows():
        key = row['branch_system_key']
        name = row['branch_display_name']
        print(f"  {key}: {name}")
    
    # 檢查 mojibake
    has_mojibake = False
    for idx, row in df.iterrows():
        name = row['branch_display_name']
        if 'æ' in name or 'Ã' in name:
            has_mojibake = True
            print(f"  WARNING: {row['branch_system_key']} has mojibake: {name}")
    
    if not has_mojibake:
        print("  OK: 無亂碼\n")
    else:
        print("  ERROR: 仍有亂碼\n")
    
    # 方法 2: 透過 Service 載入
    print("=== 方法 2: 透過 Service 載入 ===")
    service = BrokerBranchUpdateService(config)
    branches = service._load_branch_registry()
    
    for branch in branches:
        key = branch['branch_system_key']
        name = branch['branch_display_name']
        print(f"  {key}: {name}")
    
    # 預期的正確名稱
    expected_names = {
        '9A00_9A9P': '永豐竹北',
        '9200_9268': '凱基台北',
        '9200_9216': '凱基信義',
        '9200_9217': '凱基松山',
        '9100_9131': '群益民權',
        '8450_845B': '康和永和'
    }
    
    print("\n=== 驗證預期名稱 ===")
    all_correct = True
    for branch in branches:
        key = branch['branch_system_key']
        actual = branch['branch_display_name']
        expected = expected_names.get(key, '')
        if actual == expected:
            print(f"  OK: {key} = {actual}")
        else:
            print(f"  ERROR: {key} = {actual} (預期: {expected})")
            all_correct = False
    
    if all_correct:
        print("\n所有驗證通過！")
        return True
    else:
        print("\n驗證失敗！")
        return False

if __name__ == "__main__":
    try:
        success = verify_registry()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

