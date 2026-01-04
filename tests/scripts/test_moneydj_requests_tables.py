#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
測試使用 requests 抓取 MoneyDJ 券商分點買超/賣超表格
"""

import re
import time
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=9A00&b=0039004100390050&c=E&e=2025-12-22&f=2025-12-22"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://5850web.moneydj.com/",
}

def fetch_html(url: str) -> str:
    """抓取 HTML"""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()

    # MoneyDJ 常見有 Big5/UTF-8 混雜；用 requests 的 apparent_encoding 來最大化成功率
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"

    return r.text

def parse_tables(html: str):
    """解析買超/賣超表格"""
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    
    print(f"Found {len(tables)} tables")
    
    if len(tables) < 15:
        print(f"[WARNING] Not enough tables (need at least 15, got {len(tables)})")
        return None, None
    
    # 處理買超資料（表格索引 13）
    buy_table = tables[13]
    buy_rows = buy_table.find_all('tr')[2:]  # 跳過前兩行標題
    buy_data = []
    
    for row in buy_rows:
        cols = row.find_all('td')
        if len(cols) == 4:
            buy_data.append({
                'counterparty_name': cols[0].get_text(strip=True),
                'buy_qty': cols[1].get_text(strip=True).replace(',', ''),
                'sell_qty': cols[2].get_text(strip=True).replace(',', ''),
                'net_qty': cols[3].get_text(strip=True).replace(',', '')
            })
    
    # 處理賣超資料（表格索引 14）
    sell_table = tables[14]
    sell_rows = sell_table.find_all('tr')[2:]  # 跳過前兩行標題
    sell_data = []
    
    for row in sell_rows:
        cols = row.find_all('td')
        if len(cols) == 4:
            sell_data.append({
                'counterparty_name': cols[0].get_text(strip=True),
                'buy_qty': cols[1].get_text(strip=True).replace(',', ''),
                'sell_qty': cols[2].get_text(strip=True).replace(',', ''),
                'net_qty': cols[3].get_text(strip=True).replace(',', '')
            })
    
    buy_df = pd.DataFrame(buy_data)
    sell_df = pd.DataFrame(sell_data)
    
    return buy_df, sell_df

def main():
    print(f"Testing URL: {URL}")
    print("=" * 80)
    
    try:
        html = fetch_html(URL)
        print(f"[OK] HTML fetched successfully, length: {len(html)} characters")
        
        buy_df, sell_df = parse_tables(html)
        
        if buy_df is not None and sell_df is not None:
            print(f"\n[OK] Buy data: {len(buy_df)} records")
            print(buy_df.head(10).to_string())
            
            print(f"\n[OK] Sell data: {len(sell_df)} records")
            print(sell_df.head(10).to_string())
            
            # Save test results
            buy_df['trade_type'] = 'buy'
            sell_df['trade_type'] = 'sell'
            combined_df = pd.concat([buy_df, sell_df], ignore_index=True)
            combined_df.to_csv('test_buy_sell_tables.csv', index=False, encoding='utf-8-sig')
            print(f"\n[OK] Test results saved to: test_buy_sell_tables.csv")
        else:
            print("[ERROR] Failed to parse tables")
            
    except Exception as e:
        print(f"[ERROR] Error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

