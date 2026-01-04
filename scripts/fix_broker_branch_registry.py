#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修正 broker_branch_registry.csv 的中文亂碼問題
"""

import sys
from pathlib import Path

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from data_module.config import TWStockConfig
import pandas as pd
from datetime import datetime

def fix_registry():
    """重新建立 registry 檔案，確保中文正確"""
    config = TWStockConfig()
    registry_file = config.broker_branch_registry_file
    
    # 確保目錄存在
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 正確的中文資料
    registry_data = [
        {
            'branch_system_key': '9A00_9A9P',
            'branch_broker_code': '9A00',
            'branch_code': '9A9P',
            'branch_display_name': '永豐竹北',
            'url_param_a': '9A00',
            'url_param_b': '0039004100390050',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        },
        {
            'branch_system_key': '9200_9268',
            'branch_broker_code': '9200',
            'branch_code': '9268',
            'branch_display_name': '凱基台北',
            'url_param_a': '9200',
            'url_param_b': '9268',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        },
        {
            'branch_system_key': '9200_9216',
            'branch_broker_code': '9200',
            'branch_code': '9216',
            'branch_display_name': '凱基信義',
            'url_param_a': '9200',
            'url_param_b': '9216',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        },
        {
            'branch_system_key': '9200_9217',
            'branch_broker_code': '9200',
            'branch_code': '9217',
            'branch_display_name': '凱基松山',
            'url_param_a': '9200',
            'url_param_b': '9217',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        },
        {
            'branch_system_key': '9100_9131',
            'branch_broker_code': '9100',
            'branch_code': '9131',
            'branch_display_name': '群益民權',
            'url_param_a': '9100',
            'url_param_b': '9131',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        },
        {
            'branch_system_key': '8450_845B',
            'branch_broker_code': '8450',
            'branch_code': '845B',
            'branch_display_name': '康和永和',
            'url_param_a': '8450',
            'url_param_b': '0038003400350042',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
    ]
    
    # 備份現有檔案（如果存在）
    if registry_file.exists():
        config.create_backup(registry_file)
        print(f"Backup created: {registry_file}")
    
    # 建立 DataFrame 並寫入（使用 utf-8-sig）
    df = pd.DataFrame(registry_data)
    df.to_csv(registry_file, index=False, encoding='utf-8-sig')
    print(f"Registry recreated: {registry_file}")
    
    # 驗證讀取
    df_read = pd.read_csv(registry_file, encoding='utf-8-sig')
    print("\nVerifying Registry content:")
    for idx, row in df_read.iterrows():
        key = row['branch_system_key']
        name = row['branch_display_name']
        print(f"  {key}: {name}")
    
    # 檢查是否有 mojibake
    has_mojibake = False
    for idx, row in df_read.iterrows():
        display_name = row['branch_display_name']
        if 'æ' in display_name or 'Ã' in display_name:
            has_mojibake = True
            print(f"  WARNING: {row['branch_system_key']} still has mojibake: {display_name}")
    
    if not has_mojibake:
        print("\nAll Chinese characters display correctly, no mojibake")
    
    return True

if __name__ == "__main__":
    try:
        # 設置 UTF-8 輸出
        import io
        import sys
        if sys.platform == 'win32':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        
        fix_registry()
        print("\nRegistry fix completed successfully")
    except Exception as e:
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

