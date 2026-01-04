"""
分析券商分點資料中的 UNKNOWN 對手券商模式
用於改進解析邏輯
"""

import sys
import os
from pathlib import Path
import pandas as pd
from collections import Counter
import re

# 設置 UTF-8 編碼（Windows 終端機支援）
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

# 添加項目根目錄到路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig


def analyze_unknown_counterparties():
    """分析所有 CSV 檔案中的 UNKNOWN 對手券商"""
    config = TWStockConfig()
    broker_flow_dir = config.broker_flow_dir
    
    if not broker_flow_dir.exists():
        print(f"❌ 目錄不存在: {broker_flow_dir}")
        print("請先執行資料下載")
        return
    
    # 收集所有 UNKNOWN 對手券商
    unknown_patterns = []
    all_counterparties = []
    
    # 遍歷所有分點目錄
    for branch_dir in broker_flow_dir.iterdir():
        if not branch_dir.is_dir():
            continue
        
        branch_key = branch_dir.name
        daily_dir = branch_dir / 'daily'
        
        if not daily_dir.exists():
            continue
        
        print(f"📂 分析分點: {branch_key}")
        
        # 遍歷所有 CSV 檔案
        for csv_file in daily_dir.glob('*.csv'):
            try:
                df = pd.read_csv(csv_file, encoding='utf-8-sig')
                
                if 'counterparty_broker_code' not in df.columns:
                    continue
                
                # 找出 UNKNOWN 的記錄
                unknown_df = df[df['counterparty_broker_code'] == 'UNKNOWN']
                
                if len(unknown_df) > 0:
                    for _, row in unknown_df.iterrows():
                        counterparty_name = row.get('counterparty_broker_name', '')
                        if counterparty_name:
                            unknown_patterns.append({
                                'branch_key': branch_key,
                                'date': csv_file.stem,
                                'counterparty_name': counterparty_name,
                                'buy_qty': row.get('buy_qty', 0),
                                'sell_qty': row.get('sell_qty', 0)
                            })
                
                # 收集所有對手券商名稱（用於統計）
                if 'counterparty_broker_name' in df.columns:
                    all_counterparties.extend(df['counterparty_broker_name'].dropna().tolist())
                    
            except Exception as e:
                print(f"  ⚠️  讀取檔案失敗: {csv_file.name} - {str(e)}")
    
    # 分析結果
    print("\n" + "="*80)
    print("[分析] 分析結果")
    print("="*80)
    
    if not unknown_patterns:
        print("[成功] 沒有發現 UNKNOWN 對手券商")
        return
    
    print(f"\n[統計] 總共發現 {len(unknown_patterns)} 筆 UNKNOWN 記錄")
    
    # 統計 UNKNOWN 對手券商名稱
    unknown_names = [p['counterparty_name'] for p in unknown_patterns]
    name_counter = Counter(unknown_names)
    
    print(f"\n[統計] UNKNOWN 對手券商名稱統計（前 20 名）:")
    print("-" * 80)
    for name, count in name_counter.most_common(20):
        print(f"  {count:4d} 次: {name}")
    
    # 分類分析
    print("\n" + "="*80)
    print("[分析] 模式分類分析")
    print("="*80)
    
    # 1. ETF 名稱模式（純中文，可能包含數字）
    etf_patterns = []
    # 2. 特殊格式（數字+字母組合，但不符合標準格式）
    special_patterns = []
    # 3. 純中文（可能是股票名稱）
    chinese_only = []
    # 4. 其他
    other_patterns = []
    
    for pattern in unknown_patterns:
        name = pattern['counterparty_name']
        
        # 檢查是否為 ETF（常見 ETF 關鍵詞）
        etf_keywords = ['元大', '富邦', '國泰', '中信', '台新', '永豐', '第一', '兆豐', 
                       '台灣50', '高股息', '科技', '金融', '中小', '電子', '傳產']
        if any(keyword in name for keyword in etf_keywords):
            etf_patterns.append(pattern)
        # 檢查是否為純中文（無數字、無英文）
        elif re.match(r'^[\u4e00-\u9fff]+$', name):
            chinese_only.append(pattern)
        # 檢查是否為特殊格式（數字+字母，但不符合標準券商格式）
        elif re.match(r'^[\dA-Za-z]+$', name) and not re.match(r'^[\dA-Z]+[\u4e00-\u9fff]', name):
            special_patterns.append(pattern)
        else:
            other_patterns.append(pattern)
    
    print(f"\n1️⃣  ETF 名稱模式: {len(etf_patterns)} 筆")
    if etf_patterns:
        etf_names = Counter([p['counterparty_name'] for p in etf_patterns])
        print("   範例:")
        for name, count in etf_names.most_common(10):
            print(f"     - {name} ({count} 次)")
    
    print(f"\n2️⃣  特殊格式（數字+字母）: {len(special_patterns)} 筆")
    if special_patterns:
        special_names = Counter([p['counterparty_name'] for p in special_patterns])
        print("   範例:")
        for name, count in special_names.most_common(10):
            print(f"     - {name} ({count} 次)")
    
    print(f"\n3️⃣  純中文（可能是股票名稱）: {len(chinese_only)} 筆")
    if chinese_only:
        chinese_names = Counter([p['counterparty_name'] for p in chinese_only])
        print("   範例:")
        for name, count in chinese_names.most_common(10):
            print(f"     - {name} ({count} 次)")
    
    print(f"\n4️⃣  其他格式: {len(other_patterns)} 筆")
    if other_patterns:
        other_names = Counter([p['counterparty_name'] for p in other_patterns])
        print("   範例:")
        for name, count in other_names.most_common(10):
            print(f"     - {name} ({count} 次)")
    
    # 輸出詳細報告
    print("\n" + "="*80)
    print("[報告] 詳細報告（前 50 筆）")
    print("="*80)
    print(f"{'分點':<15} {'日期':<12} {'對手券商名稱':<30} {'買進':<12} {'賣出':<12}")
    print("-" * 80)
    for pattern in unknown_patterns[:50]:
        print(f"{pattern['branch_key']:<15} {pattern['date']:<12} {pattern['counterparty_name']:<30} "
              f"{pattern['buy_qty']:<12} {pattern['sell_qty']:<12}")
    
    # 保存報告
    report_file = project_root / 'output' / 'qa' / 'unknown_counterparties_analysis.csv'
    report_file.parent.mkdir(parents=True, exist_ok=True)
    
    report_df = pd.DataFrame(unknown_patterns)
    report_df.to_csv(report_file, index=False, encoding='utf-8-sig')
    print(f"\n[保存] 詳細報告已保存至: {report_file}")
    
    return {
        'total_unknown': len(unknown_patterns),
        'etf_patterns': len(etf_patterns),
        'special_patterns': len(special_patterns),
        'chinese_only': len(chinese_only),
        'other_patterns': len(other_patterns),
        'name_counter': name_counter
    }


if __name__ == '__main__':
    result = analyze_unknown_counterparties()

