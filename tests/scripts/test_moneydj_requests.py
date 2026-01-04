#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
測試使用 requests 抓取 MoneyDJ 券商分點資料
"""

import re
import time
import pandas as pd
import requests
from bs4 import BeautifulSoup

URLS = [
    "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=9A00&b=0039004100390050",
    "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=9200&b=9268",
    "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=9200&b=9216",
    "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=9200&b=9217",
    "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=9100&b=9131",
    "https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=8450&b=0038003400350042",
]

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
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()

    # MoneyDJ 常見有 Big5/UTF-8 混雜；用 requests 的 apparent_encoding 來最大化成功率
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"

    return r.text

def parse_branch_names(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")

    # 目標：抓「券商/分點」那一欄（通常在表格第一欄）
    # 這邊採用比較保守的策略：
    # 1) 找所有表格 row
    # 2) 每列取第一個 td 的文字
    # 3) 過濾掉 header/空值/明顯不是分點的行
    rows = soup.find_all("tr")
    candidates = []
    for tr in rows:
        tds = tr.find_all("td")
        if not tds:
            continue
        name = tds[0].get_text(strip=True)
        if not name:
            continue

        # 排除常見非資料行
        bad_patterns = [
            r"券商", r"分點", r"買超", r"賣超", r"合計", r"排行", r"商品", r"日期",
            r"金額", r"張數", r"小計", r"總計"
        ]
        if any(re.search(p, name) for p in bad_patterns):
            continue

        # 通常分點名稱含有券商名（如：凱基、元大、富邦、永豐等）
        # 但為了泛用，不強制，只是再濾掉太短的雜訊
        if len(name) < 2:
            continue

        candidates.append(name)

    # 去重保持順序
    seen = set()
    result = []
    for x in candidates:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result

def main():
    out_rows = []
    for url in URLS:
        print(f"Fetching: {url}")
        try:
            html = fetch_html(url)
            names = parse_branch_names(html)

            # 若解析結果太少，給你提示：表示頁面結構可能不同或被擋
            if len(names) == 0:
                print("  [WARNING] No branch names parsed. Might be blocked or structure changed.")
            else:
                print(f"  [OK] Parsed {len(names)} names")

            for n in names:
                out_rows.append({"url": url, "branch_name": n})

            time.sleep(1.0)  # 禮貌延遲
        except Exception as e:
            print(f"  [ERROR] Error: {str(e)}")

    df = pd.DataFrame(out_rows)
    output_file = "moneydj_branches.csv"
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\nSaved: {output_file}")

    # 也印出每個 url 對應的清單
    for url, g in df.groupby("url"):
        print("\n" + "=" * 80)
        print(url)
        for n in g["branch_name"].tolist():
            try:
                print(" -", n)
            except UnicodeEncodeError:
                # Windows 終端機編碼問題，跳過無法顯示的字符
                print(f" - [Branch name with special characters]")

if __name__ == "__main__":
    main()

