#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
合併與去重券商分點註冊表 (broker_branch_registry.csv)
"""

import sys
from pathlib import Path
import pandas as pd

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from data_module.config import TWStockConfig

# 設置 UTF-8 輸出
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 用戶提供的新 37 個分點資料
NEW_BRANCH_DATA = [
    {"branch_system_key": "8440_8440", "branch_broker_code": "8440", "branch_code": "8440", "branch_display_name": "摩根大通", "url_param_a": "8440", "url_param_b": "8440"},
    {"branch_system_key": "9A00_9A9i", "branch_broker_code": "9A00", "branch_code": "9A9i", "branch_display_name": "永豐金-新店", "url_param_a": "9A00", "url_param_b": "0039004100390069"},
    {"branch_system_key": "8880_8888", "branch_broker_code": "8880", "branch_code": "8888", "branch_display_name": "國泰-敦南", "url_param_a": "8880", "url_param_b": "8888"},
    {"branch_system_key": "1030_1030", "branch_broker_code": "1030", "branch_code": "1030", "branch_display_name": "土銀", "url_param_a": "1030", "url_param_b": "1030"},
    {"branch_system_key": "8890_8890", "branch_broker_code": "8890", "branch_code": "8890", "branch_display_name": "大和國泰", "url_param_a": "8890", "url_param_b": "8890"},
    {"branch_system_key": "8880_8882", "branch_broker_code": "8880", "branch_code": "8882", "branch_display_name": "國泰-台中", "url_param_a": "8880", "url_param_b": "8882"},
    {"branch_system_key": "8880_888K", "branch_broker_code": "8880", "branch_code": "888K", "branch_display_name": "國泰-板橋", "url_param_a": "8880", "url_param_b": "003800380038004b"},
    {"branch_system_key": "7790_779c", "branch_broker_code": "7790", "branch_code": "779c", "branch_display_name": "國票-敦北法人", "url_param_a": "7790", "url_param_b": "0037003700390063"},
    {"branch_system_key": "8880_888A", "branch_broker_code": "8880", "branch_code": "888A", "branch_display_name": "國泰-館前", "url_param_a": "8880", "url_param_b": "0038003800380041"},
    {"branch_system_key": "8880_8881", "branch_broker_code": "8880", "branch_code": "8881", "branch_display_name": "國泰-高雄", "url_param_a": "8880", "url_param_b": "8881"},
    {"branch_system_key": "9200_9217", "branch_broker_code": "9200", "branch_code": "9217", "branch_display_name": "凱基-松山", "url_param_a": "9200", "url_param_b": "9217"},
    {"branch_system_key": "8880_8885", "branch_broker_code": "8880", "branch_code": "8885", "branch_display_name": "國泰-桃園", "url_param_a": "8880", "url_param_b": "8885"},
    {"branch_system_key": "9600_9604", "branch_broker_code": "9600", "branch_code": "9604", "branch_display_name": "富邦-陽明", "url_param_a": "9600", "url_param_b": "9604"},
    {"branch_system_key": "8840_8842", "branch_broker_code": "8840", "branch_code": "8842", "branch_display_name": "玉山-新莊", "url_param_a": "8840", "url_param_b": "8842"},
    {"branch_system_key": "8450_8450", "branch_broker_code": "8450", "branch_code": "8450", "branch_display_name": "康和", "url_param_a": "8450", "url_param_b": "8450"},
    {"branch_system_key": "9600_9655", "branch_broker_code": "9600", "branch_code": "9655", "branch_display_name": "富邦-板橋", "url_param_a": "9600", "url_param_b": "9655"},
    {"branch_system_key": "9600_9647", "branch_broker_code": "9600", "branch_code": "9647", "branch_display_name": "富邦-新竹", "url_param_a": "9600", "url_param_b": "9647"},
    {"branch_system_key": "9800_989G", "branch_broker_code": "9800", "branch_code": "989G", "branch_display_name": "元大-大同", "url_param_a": "9800", "url_param_b": "0039003800390047"},
    {"branch_system_key": "8880_8886", "branch_broker_code": "8880", "branch_code": "8886", "branch_display_name": "國泰-新莊", "url_param_a": "8880", "url_param_b": "8886"},
    {"branch_system_key": "9A00_9A9J", "branch_broker_code": "9A00", "branch_code": "9A9J", "branch_display_name": "永豐金-板新", "url_param_a": "9A00", "url_param_b": "003900410039004a"},
    {"branch_system_key": "8880_8884", "branch_broker_code": "8880", "branch_code": "8884", "branch_display_name": "國泰-台南", "url_param_a": "8880", "url_param_b": "8884"},
    {"branch_system_key": "8840_8843", "branch_broker_code": "8840", "branch_code": "8843", "branch_display_name": "玉山-高雄", "url_param_a": "8840", "url_param_b": "8843"},
    {"branch_system_key": "9200_9268", "branch_broker_code": "9200", "branch_code": "9268", "branch_display_name": "凱基-台北", "url_param_a": "9200", "url_param_b": "9268"},
    {"branch_system_key": "9800_9800", "branch_broker_code": "9800", "branch_code": "9800", "branch_display_name": "元大證券", "url_param_a": "9800", "url_param_b": "9800"},
    {"branch_system_key": "1590_1590", "branch_broker_code": "1590", "branch_code": "1590", "branch_display_name": "花旗環球", "url_param_a": "1590", "url_param_b": "1590"},
    {"branch_system_key": "9600_9600", "branch_broker_code": "9600", "branch_code": "9600", "branch_display_name": "富邦證券", "url_param_a": "9600", "url_param_b": "9600"},
    {"branch_system_key": "1440_1440", "branch_broker_code": "1440", "branch_code": "1440", "branch_display_name": "美林", "url_param_a": "1440", "url_param_b": "1440"},
    {"branch_system_key": "9A00_9A00", "branch_broker_code": "9A00", "branch_code": "9A00", "branch_display_name": "永豐金證券", "url_param_a": "9A00", "url_param_b": "0039004100300030"},
    {"branch_system_key": "1470_1470", "branch_broker_code": "1470", "branch_code": "1470", "branch_display_name": "台灣摩根士丹利", "url_param_a": "1470", "url_param_b": "1470"},
    {"branch_system_key": "1650_1650", "branch_broker_code": "1650", "branch_code": "1650", "branch_display_name": "新加坡商瑞銀", "url_param_a": "1650", "url_param_b": "1650"},
    {"branch_system_key": "9B00_9B20", "branch_broker_code": "9B00", "branch_code": "9B20", "branch_display_name": "台新-台北", "url_param_a": "9B00", "url_param_b": "0039004200320030"},
    {"branch_system_key": "9200_9200", "branch_broker_code": "9200", "branch_code": "9200", "branch_display_name": "凱基", "url_param_a": "9200", "url_param_b": "9200"},
    {"branch_system_key": "1360_1360", "branch_broker_code": "1360", "branch_code": "1360", "branch_display_name": "港商麥格理", "url_param_a": "1360", "url_param_b": "1360"},
    {"branch_system_key": "1560_1560", "branch_broker_code": "1560", "branch_code": "1560", "branch_display_name": "港商野村", "url_param_a": "1560", "url_param_b": "1560"},
    {"branch_system_key": "8960_8960", "branch_broker_code": "8960", "branch_code": "8960", "branch_display_name": "香港上海匯豐", "url_param_a": "8960", "url_param_b": "8960"},
    {"branch_system_key": "9200_9216", "branch_broker_code": "9200", "branch_code": "9216", "branch_display_name": "凱基-信義", "url_param_a": "9200", "url_param_b": "9216"},
    {"branch_system_key": "1480_1480", "branch_broker_code": "1480", "branch_code": "1480", "branch_display_name": "美商高盛", "url_param_a": "1480", "url_param_b": "1480"},
]

def merge_registries():
    config = TWStockConfig()
    registry_file = config.broker_branch_registry_file
    
    print(f"分點註冊表目標路徑: {registry_file}")
    
    # 讀取既有分點
    existing_branches = []
    has_existing = False
    if registry_file.exists():
        has_existing = True
        try:
            dtype_dict = {
                'url_param_a': str,
                'url_param_b': str,
                'branch_system_key': str,
                'branch_broker_code': str,
                'branch_code': str,
                'branch_display_name': str
            }
            df_existing = pd.read_csv(registry_file, encoding='utf-8-sig', dtype=dtype_dict)
            existing_branches = df_existing.to_dict('records')
            print(f"讀取到原本既有分點數: {len(existing_branches)}")
        except Exception as e:
            print(f"讀取既有 CSV 失敗: {str(e)}，將直接覆寫/建立新表。")
    
    # 合併去重邏輯
    # 以 branch_system_key 為 key
    merged_map = {}
    
    # 1. 先將既有分點存入
    for branch in existing_branches:
        key = branch.get('branch_system_key')
        if key:
            # 確保 url_param_b 為字串格式
            if 'url_param_b' in branch:
                branch['url_param_b'] = str(branch['url_param_b'])
            # 確保 is_active 預設為 True
            if 'is_active' not in branch:
                branch['is_active'] = True
            merged_map[key] = branch
            
    # 2. 合併新分點，如果已存在，進行屬性覆蓋，但保留 `is_active` 等舊自訂屬性
    added_count = 0
    updated_count = 0
    for new_branch in NEW_BRANCH_DATA:
        key = new_branch['branch_system_key']
        if key in merged_map:
            # 已存在，更新屬性 (url_param_b 可能是長碼，我們使用新提供的以確保它被寫入)
            old_branch = merged_map[key]
            old_branch.update(new_branch)
            updated_count += 1
        else:
            # 不存在，追加，預設 is_active 為 True
            new_branch['is_active'] = True
            merged_map[key] = new_branch
            added_count += 1
            
    # 轉回 DataFrame 並保存
    merged_list = list(merged_map.values())
    df_merged = pd.DataFrame(merged_list)
    
    # 排序（以 branch_system_key）
    df_merged = df_merged.sort_values(by='branch_system_key')
    
    # 確保 columns 順序一致
    col_order = ['branch_system_key', 'branch_broker_code', 'branch_code', 
                 'branch_display_name', 'url_param_a', 'url_param_b', 'is_active']
    # 保留可能存在的額外 columns
    for col in df_merged.columns:
        if col not in col_order:
            col_order.append(col)
            
    df_merged = df_merged[col_order]
    
    # 建立備份
    if has_existing:
        try:
            config.create_backup(registry_file)
            print("已成功備份原 Registry 檔案")
        except Exception as backup_err:
            print(f"備份失敗: {str(backup_err)}")
            
    # 寫回 CSV (使用 utf-8-sig)
    df_merged.to_csv(registry_file, index=False, encoding='utf-8-sig')
    print(f"合併成功！目前分點總數: {len(df_merged)}")
    print(f"  - 新增: {added_count} 個")
    print(f"  - 更新: {updated_count} 個")
    
    # 印出所有分點簡介
    print("\n=== 目前註冊表中所有分點 ===")
    for idx, row in df_merged.iterrows():
        print(f"  {row['branch_system_key']}: {row['branch_display_name']} (active={row.get('is_active', True)})")

if __name__ == '__main__':
    merge_registries()
