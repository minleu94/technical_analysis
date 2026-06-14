"""SQLite 查詢計劃分析與索引健全度診斷工具。"""

from __future__ import annotations

import sys
from pathlib import Path

# 將專案根目錄加入 sys.path 以防 ModuleNotFoundError
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import sqlite3
from data_module.config import TWStockConfig

def main() -> int:
    if hasattr(sys.stdout, "reconfigure") and str(getattr(sys.stdout, "encoding", "")).lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    config = TWStockConfig()
    db_path = config.db_file
    print(f"📦 資料庫路徑: {db_path}")
    if not db_path.exists():
        print("❌ 錯誤: 資料庫檔案不存在！請先執行資料更新或初始化。")
        return 1

    queries = {
        "1. 個股日收盤價查詢 (Backtest 載入價格)": 
            "SELECT * FROM daily_prices WHERE 證券代號 = '2330' AND 日期 >= '2026-01-01' ORDER BY 日期 ASC;",
        "2. 個股技術指標查詢 (Backtest 載入指標)": 
            "SELECT * FROM technical_indicators WHERE 證券代號 = '2330' AND 日期 >= '2026-01-01' ORDER BY 日期 ASC;",
        "3. 單日市場指數查詢 (Regime Detector 載入)": 
            "SELECT * FROM market_indices WHERE 指數名稱 = '發行量加權股價指數' AND 日期 = '2026-06-12';",
        "4. 籌碼流向分點排行查詢 (Smart Money 載入)": 
            "SELECT * FROM broker_flows WHERE 證券代號 = '2330' AND 日期 = '2026-06-12' ORDER BY lots_rank ASC;"
    }

    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    
    print("\n=== 開始 SQLite 查詢計劃審查 (EXPLAIN QUERY PLAN) ===")
    has_bottleneck = False
    
    try:
        for name, sql in queries.items():
            print(f"\n📋 查詢類型: {name}")
            print(f"   SQL: {sql}")
            
            explain_sql = f"EXPLAIN QUERY PLAN {sql}"
            cursor = conn.execute(explain_sql)
            plans = cursor.fetchall()
            
            uses_index = False
            for plan in plans:
                detail = plan['detail']
                print(f"   💡 執行計劃: {detail}")
                if (
                    "USING INDEX" in detail
                    or "USING COVERING INDEX" in detail
                    or "USING PRIMARY KEY" in detail
                ):
                    uses_index = True
                if detail.startswith("SCAN ") and "USING " not in detail:
                    print("   ⚠️ 警告: 偵測到全表掃描，若資料量大可能造成延遲。")
                    has_bottleneck = True
                if "USE TEMP B-TREE" in detail:
                    print("   ℹ️ 注意: 排序使用暫存 B-Tree；目前保留為觀察項，不代表查詢失敗。")
            
            if uses_index:
                print("   ✅ 檢查通過: 已安全使用索引進行檢索。")
            else:
                print("   ❌ 檢查未通過: 未能使用任何索引！")
                has_bottleneck = True
                
        # 檢查資料庫併發設定 WAL 模式
        cursor = conn.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0]
        print(f"\n📊 資料庫日誌模式 (journal_mode): {journal_mode.upper()}")
        if journal_mode.lower() == "wal":
            print("   ✅ 檢查通過: 已啟用 WAL 模式，可降低讀寫互相阻塞。")
            print("   ℹ️ 限制: WAL 不保證完全不會發生鎖競爭，仍需控制交易時間與寫入者數量。")
        else:
            print("   ⚠️ 警告: 未啟用 WAL 模式，可能在高併發回測時遇到 database is locked 鎖定錯誤。")
            has_bottleneck = True
            
    except Exception as e:
        print(f"💥 診斷過程中發生異常: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print("\n======================================")
    if not has_bottleneck:
        print("✅ 受檢核心查詢均使用索引，且目前為 WAL 模式。")
        return 0
    else:
        print("⚠️ 警告：SQLite 檢查發現潛在效能瓶頸或併發隱患，請參閱上述報告進行優化！")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
