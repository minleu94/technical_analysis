#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""檢查券商分點檔案是否存在"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig

config = TWStockConfig()
test_date = '2025-12-22'
branches = ['9A00_9A9P', '9200_9268', '9200_9216', '9200_9217', '9100_9131', '8450_845B']

print(f"Checking files for date: {test_date}")
print("=" * 60)

for branch in branches:
    file_path = config.broker_flow_dir / branch / 'daily' / f'{test_date}.csv'
    exists = file_path.exists()
    status = "OK" if exists else "MISSING"
    print(f"{branch}: {status}")
    
    if exists:
        import pandas as pd
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            print(f"  Records: {len(df)}")
        except Exception as e:
            print(f"  Error reading: {str(e)}")

print("=" * 60)

