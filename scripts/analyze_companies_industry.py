"""
分析 companies.csv 和 industry_index.csv 的關聯
"""

import sys
import io
import pandas as pd
from pathlib import Path

# 設置 UTF-8 編碼
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def analyze_companies_industry():
    """分析 companies.csv 和 industry_index.csv"""
    
    # 讀取 companies.csv
    companies_file = Path(r"D:\Min\Python\Project\FA_Data\meta_data\companies.csv")
    industry_file = Path(r"D:\Min\Python\Project\FA_Data\meta_data\industry_index.csv")
    
    print("=" * 80)
    print("companies.csv 分析")
    print("=" * 80)
    
    df_companies = pd.read_csv(companies_file, encoding='utf-8-sig')
    print(f"\n總筆數: {len(df_companies):,}")
    print(f"\n欄位: {list(df_companies.columns)}")
    
    print("\n前10筆樣本:")
    print(df_companies.head(10).to_string())
    
    print("\n\n產業類別統計（前20名）:")
    industry_counts = df_companies['industry_category'].value_counts()
    print(industry_counts.head(20))
    
    print(f"\n\n總共有 {df_companies['industry_category'].nunique()} 個不同的產業類別")
    print(f"總共有 {df_companies['stock_id'].nunique()} 支不同的股票")
    
    # 檢查是否有重複的股票-產業組合
    print(f"\n\n股票-產業組合數: {len(df_companies)}")
    print(f"唯一股票數: {df_companies['stock_id'].nunique()}")
    if len(df_companies) > df_companies['stock_id'].nunique():
        print("⚠️  有些股票屬於多個產業類別")
        # 找出屬於多個產業的股票
        multi_industry = df_companies.groupby('stock_id')['industry_category'].nunique()
        multi_industry = multi_industry[multi_industry > 1].sort_values(ascending=False)
        print(f"\n屬於多個產業的股票（前10名）:")
        for stock_id, count in multi_industry.head(10).items():
            industries = df_companies[df_companies['stock_id'] == stock_id]['industry_category'].unique()
            stock_name = df_companies[df_companies['stock_id'] == stock_id]['stock_name'].iloc[0]
            print(f"  {stock_id} ({stock_name}): {count} 個產業 - {', '.join(industries)}")
    
    print("\n\n" + "=" * 80)
    print("industry_index.csv 分析")
    print("=" * 80)
    
    df_industry = pd.read_csv(industry_file, encoding='utf-8-sig')
    print(f"\n總筆數: {len(df_industry):,}")
    print(f"\n欄位: {list(df_industry.columns)}")
    
    print("\n前10筆樣本:")
    print(df_industry.head(10).to_string())
    
    print("\n\n指數名稱統計（前20名）:")
    index_counts = df_industry['指數名稱'].value_counts()
    print(index_counts.head(20))
    
    print(f"\n\n總共有 {df_industry['指數名稱'].nunique()} 個不同的指數名稱")
    
    # 提取產業類別名稱（去除「類指數」、「類報酬指數」等後綴）
    df_industry['產業類別'] = df_industry['指數名稱'].str.replace('類指數', '').str.replace('類報酬指數', '').str.replace('類', '')
    unique_industries = df_industry['產業類別'].unique()
    
    print(f"\n\n提取的產業類別數: {len(unique_industries)}")
    print("前20個產業類別:")
    for i, industry in enumerate(unique_industries[:20], 1):
        print(f"  {i}. {industry}")
    
    print("\n\n" + "=" * 80)
    print("關聯分析")
    print("=" * 80)
    
    # 找出 companies.csv 中的產業類別
    companies_industries = set(df_companies['industry_category'].unique())
    
    # 找出 industry_index.csv 中的產業類別
    industry_index_industries = set(unique_industries)
    
    print(f"\ncompanies.csv 中的產業類別數: {len(companies_industries)}")
    print(f"industry_index.csv 中的產業類別數: {len(industry_index_industries)}")
    
    # 找出交集
    common_industries = companies_industries & industry_index_industries
    print(f"\n共同的產業類別數: {len(common_industries)}")
    print("共同的產業類別（前20個）:")
    for i, industry in enumerate(sorted(common_industries)[:20], 1):
        print(f"  {i}. {industry}")
    
    # 找出只在 companies.csv 中的產業類別
    only_in_companies = companies_industries - industry_index_industries
    print(f"\n只在 companies.csv 中的產業類別數: {len(only_in_companies)}")
    print("只在 companies.csv 中的產業類別（前20個）:")
    for i, industry in enumerate(sorted(only_in_companies)[:20], 1):
        print(f"  {i}. {industry}")
    
    # 找出只在 industry_index.csv 中的產業類別
    only_in_index = industry_index_industries - companies_industries
    # 過濾掉 NaN 值
    only_in_index = {x for x in only_in_index if pd.notna(x)}
    print(f"\n只在 industry_index.csv 中的產業類別數: {len(only_in_index)}")
    print("只在 industry_index.csv 中的產業類別（前20個）:")
    for i, industry in enumerate(sorted(only_in_index)[:20], 1):
        print(f"  {i}. {industry}")
    
    print("\n\n" + "=" * 80)
    print("使用建議")
    print("=" * 80)
    print("""
1. companies.csv 提供：
   - 每支股票所屬的產業類別
   - 股票基本資訊（代號、名稱、類型）

2. industry_index.csv 提供：
   - 各產業指數的每日數據（收盤指數、漲跌等）

3. 搭配使用方式：
   - 可以通過產業類別名稱將股票與產業指數關聯
   - 例如：找出「半導體類」的所有股票，然後查看「半導體類指數」的表現
   - 可以分析某個產業的股票表現與該產業指數的相關性
   - 可以篩選出特定產業的股票進行分析

4. 注意事項：
   - 產業類別名稱需要進行標準化匹配（去除後綴）
   - 有些股票可能屬於多個產業類別
   - ETF 等特殊類別在 industry_index.csv 中可能沒有對應的指數
    """)

if __name__ == "__main__":
    analyze_companies_industry()

