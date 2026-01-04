#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
顯示 broker 每日資料存儲位置
"""

import sys
from pathlib import Path

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from data_module.config import TWStockConfig

# 設置 UTF-8 輸出
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

config = TWStockConfig()

print("=" * 60)
print("Broker 每日資料存儲位置")
print("=" * 60)
print()

print(f"Broker Flow 根目錄:")
print(f"  {config.broker_flow_dir}")
print()

print("目錄結構:")
print(f"  {config.broker_flow_dir}/")
print(f"    ├── 9A00_9A9P/              # 永豐竹北")
print(f"    │   ├── daily/")
print(f"    │   │   ├── 2024-11-08.csv  # 每日原始資料")
print(f"    │   │   ├── 2024-11-11.csv")
print(f"    │   │   └── ...")
print(f"    │   └── meta/")
print(f"    │       └── merged.csv      # 合併後的歷史資料")
print(f"    ├── 9200_9268/              # 凱基台北")
print(f"    │   ├── daily/")
print(f"    │   └── meta/")
print(f"    ├── 9200_9216/              # 凱基信義")
print(f"    ├── 9200_9217/              # 凱基松山")
print(f"    ├── 9100_9131/              # 群益民權")
print(f"    └── 8450_845B/              # 康和永和")
print()

print("檔案命名規則:")
print("  - 每日檔案: {YYYY-MM-DD}.csv (例如: 2024-11-08.csv)")
print("  - 合併檔案: meta/merged.csv")
print("  - 檔名不含中文、不含空白（跨平台安全）")
print()

# 檢查實際目錄
if config.broker_flow_dir.exists():
    print("現有分點目錄:")
    for branch_dir in sorted(config.broker_flow_dir.iterdir()):
        if branch_dir.is_dir():
            daily_dir = branch_dir / 'daily'
            meta_dir = branch_dir / 'meta'
            
            daily_count = len(list(daily_dir.glob('*.csv'))) if daily_dir.exists() else 0
            has_merged = (meta_dir / 'merged.csv').exists() if meta_dir.exists() else False
            
            print(f"  {branch_dir.name}/")
            print(f"    daily/: {daily_count} 個檔案")
            print(f"    meta/merged.csv: {'存在' if has_merged else '不存在'}")
else:
    print("Broker Flow 目錄尚未建立（執行更新後會自動建立）")
print()

print("範例完整路徑:")
branch_key = '9200_9268'
example_date = '2024-11-08'
daily_file = config.broker_flow_dir / branch_key / 'daily' / f'{example_date}.csv'
merged_file = config.broker_flow_dir / branch_key / 'meta' / 'merged.csv'
print(f"  每日檔案: {daily_file}")
print(f"  合併檔案: {merged_file}")

