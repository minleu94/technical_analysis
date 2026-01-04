#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""驗證券商分點資料格式"""

import sys
import io
from pathlib import Path

# 設置 UTF-8 編碼
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
import pandas as pd

config = TWStockConfig()
test_date = '2025-12-22'
branch = '9A00_9A9P'

file_path = config.broker_flow_dir / branch / 'daily' / f'{test_date}.csv'

print(f"Checking file: {file_path}")
print(f"Exists: {file_path.exists()}")

if file_path.exists():
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    print(f"\nColumns: {list(df.columns)}")
    print(f"\nTotal records: {len(df)}")
    print(f"\nFirst 3 rows:")
    print(df.head(3).to_string())
    print(f"\nData types:")
    print(df.dtypes)
else:
    print("File not found!")

