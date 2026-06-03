# Phase 2A：盤點讀取來源報告（Data Sources Audit Report）

> **建立日期**：2026-06-03  
> **系統定位**：自 CSV-first 邁向 DB-first 的過渡期盤點  
> **當前狀態**：已完成 SQLite 儲存庫建置、大盤及指標全量遷移。本報告旨在識別並列出所有**仍在主讀 CSV 數據**的代碼區塊，並設計 Phase 2B 的改造優先順序。

---

## 📌 讀取來源盤點總覽

目前系統已具備高性能的 SQLite 資料庫（由 [db_manager.py](file:///c:/Projects/PythonProjects/technical_analysis/data_module/db_manager.py) 管理），支持包括 `daily_prices`、`technical_indicators`、`market_indices`、`industry_indices` 與 `broker_flows` 在內的五張核心數據表。

然而，系統的數個模組仍維持 CSV 優先的讀取邏輯。以下是完整盤點與「CSV-first / DB-first / Fallback」狀態表：

### 📊 數據讀取來源狀態表

| 範圍 | 目標檔案/資料庫表 | 讀取模式 | 核心代碼位置 | 當前行為描述與性能瓶頸 | DB-first 改造難度與方案 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 📊 **Update 狀態** | 1. `daily_prices`<br>2. `market_indices`<br>3. `industry_indices`<br>4. `broker_flows`<br>5. `technical_indicators`<br>6. `broker_branch_registry.csv` | **Fallback**<br>(SQLite 優先；CSV 為備用)<br><br>但分點註冊表為 **CSV-first** | - [update_service.py:check_data_status](file:///c:/Projects/PythonProjects/technical_analysis/app_module/update_service.py#L874)<br>- [update_service.py:_overview_broker_branch_status](file:///c:/Projects/PythonProjects/technical_analysis/app_module/update_service.py#L1243) | **已實作部分 DB-first**：若啟用 SQLite，UI數據更新工作台的 overview 與 detail 會直接使用 SQL 聚合統計，實現毫秒級「秒開」。但券商註冊表等中繼資訊仍強制讀取 CSV。 | **低**：<br>保持現行 `use_sqlite` 狀態機，將 `broker_branch_registry.csv` 映射引入 SQLite 表（或維持輕量 CSV 讀取，因其僅含數十行註冊資訊）。 |
| 📈 **技術指標** | 1. `technical_indicators`<br>2. `{stock_id}_indicators.csv` | **CSV-first**<br>(選股篩選器)<br><br>**Fallback**<br>(回測服務) | - [stock_screener.py:get_strong_stocks](file:///c:/Projects/PythonProjects/technical_analysis/decision_module/stock_screener.py#L95)<br>- [backtest_service.py:_load_indicator_data](file:///c:/Projects/PythonProjects/technical_analysis/app_module/backtest_service.py#L503) | **嚴重瓶頸**：選股器（`StockScreener`）在計算強勢股/弱勢股評分時，**仍在硬碟上逐一 read_csv 讀取上千個個股指標檔**，導致 UI 卡頓。而回測服務已完成 DB-first 提速。 | **中**：<br>重構 `StockScreener`，在啟動 SQLite 時，將 `pd.read_csv` 遍歷改為單次 SQL 查詢或按需 batch 查詢 `technical_indicators` 表，可消除 99% 磁碟 I/O。 |
| 💡 **Recommendation** | 1. `all_stocks_data.csv`<br>2. `stock_data_whole.csv` | **CSV-first** | - [recommendation_service.py:run_recommendation](file:///c:/Projects/PythonProjects/technical_analysis/app_module/recommendation_service.py#L117) | 推薦分析引擎執行時，直接讀取整個合併的 `all_stocks_data.csv`，未支持從 SQLite `daily_prices` 載入，消耗大量記憶體與時間。 | **中**：<br>改為優先從 SQLite 查詢特定日期範圍（通常是最新60天）的個股價格。如果 SQLite 沒啟用，再 fallback 到讀取合併 CSV。 |
| 🔍 **Market Watch** | 1. `market_index.csv`<br>2. `industry_index.csv`<br>3. `companies.csv` | **CSV-first** | - [market_regime_detector.py:detect_regime](file:///c:/Projects/PythonProjects/technical_analysis/decision_module/market_regime_detector.py#L302)<br>- [industry_mapper.py:_load_companies](file:///c:/Projects/PythonProjects/technical_analysis/decision_module/industry_mapper.py#L36)<br>- [industry_mapper.py:_load_industry_index](file:///c:/Projects/PythonProjects/technical_analysis/decision_module/industry_mapper.py#L59) | 1. 大盤狀態偵測器（`MarketRegimeDetector`）強制 read_csv 大盤指數。<br>2. 產業映射器（`IndustryMapper`）強制 read_csv 產業指數與公司清單。 | **低**：<br>1. 改為自 `market_indices` 查詢大盤指數。<br>2. 改為自 `industry_indices` 查詢產業指數。<br>3. `companies.csv` 可維持 CSV（基本映射表，不易變動）或建立 `companies` 庫表。 |
| 🧪 **Backtest** | 1. `daily_prices`<br>2. `technical_indicators`<br>3. `stock_data_whole.csv` | **Fallback**<br>(SQLite 優先；CSV 為備用) | - [backtest_service.py:_load_price_data](file:///c:/Projects/PythonProjects/technical_analysis/app_module/backtest_service.py#L371)<br>- [backtest_service.py:_load_indicator_data](file:///c:/Projects/PythonProjects/technical_analysis/app_module/backtest_service.py#L503) | **已實作 DB-first**：先使用複合索引快速查詢 SQLite。若無資料或查詢出錯，再降級讀取大 CSV 或指標 CSV。回測性能因此提升 322 倍。 | **已完成**：<br>結構已穩定，後續僅需在 Phase 2B 改造其他模組時維持接口的一致性。 |

---

## 🔄 數據讀取流向對比

```mermaid
graph TD
    subgraph ⚠️ 改造前: CSV-First (現狀)
        A[UI 觸發操作] --> B1[Update: 讀取 status_manifest.json]
        A --> B2[Market Watch: 讀取 market_index.csv / industry_index.csv]
        A --> B3[Recommendation: 讀取 all_stocks_data.csv / companies.csv]
        A --> B4[StockScreener: 遍歷讀取上千個 stock_indicators.csv]
        A --> B5[Backtest: 優先讀取 SQLite, 失敗 fallback CSV]
    end

    subgraph 🚀 改造後: DB-First (目標)
        C[UI 觸發操作] --> D1[Update: 讀取 SQLite db]
        C --> D2[Market Watch: 讀取 SQLite market_indices / industry_indices]
        C --> D3[Recommendation: 讀取 SQLite daily_prices]
        C --> D4[StockScreener: 單次 SQL 讀取 technical_indicators]
        C --> D5[Backtest: 優先讀取 SQLite, 失敗 fallback CSV]
    end
    
    style B4 fill:#ffcccc,stroke:#333,stroke-width:2px
    style B3 fill:#ffcccc,stroke:#333,stroke-width:1px
    style B2 fill:#ffcccc,stroke:#333,stroke-width:1px
    style D4 fill:#ccffcc,stroke:#333,stroke-width:2px
```

---

## 📈 Phase 2B：DB-first 改造順序與規劃

為了平穩重構，建議依**影響層級**與**性能回報**將改造切分為三波，遵循「SQLite 優先；SQLite 不存在、表空、查詢失敗才 fallback CSV」的核心防禦規則。

### 第一波：技術指標與 Update 狀態（核心提速）
1. **重構 `StockScreener` (`decision_module/stock_screener.py`)**：
   - **現狀瓶頸**：磁碟 I/O 毒瘤。
   - **改造方案**：引入 `use_sqlite` 判斷。若是 SQLite 模式，直接利用 SQL 做 `SELECT ... FROM technical_indicators WHERE 日期 >= ?` 的 batch 查詢，替代 `glob` 與遍歷 `read_csv`。
   - **預期效果**：強勢股/弱勢股打分加載從數秒縮減至 **100 毫秒**以內。
2. **優化 `UpdateService` 的券商狀態與指標 overview 邏輯**：
   - 移除不必要的 CSV 尾端掃描。

### 第二波：市場觀察 (Market Watch) 與大盤狀態（穩定性優化）
1. **重構 `MarketRegimeDetector` (`decision_module/market_regime_detector.py`)**：
   - 將 `detect_regime` 中的大盤指數加載對接 SQLite 的 `market_indices` 表。
2. **重構 `IndustryMapper` (`decision_module/industry_mapper.py`)**：
   - 將產業指數加載對接 SQLite 的 `industry_indices` 表。

### 第三波：推薦系統 (Recommendation) 與回測優化（完整閉環）
1. **重構 `RecommendationService` (`app_module/recommendation_service.py`)**：
   - 將推薦分析的原始數據載入（`pd.read_csv(all_stocks_data.csv)`）對接為 SQLite 的 `daily_prices` 的特定日期區間查詢。

---

## 🛡️ 未來函數與股票/量化防禦自查

在將數據讀取改為 DB-first 時，必須注意以下防禦條款：
1. **隔離浮點數**：自 SQLite 讀取數值（如價格、成交量、指標等）時，必須在資料邊界將其標準化（例如將 NaN 統一處理、價格欄位維持 `Decimal` 或在運算邊界內做好隔離），不可引入裸 `float` 的不確定性。
2. **時間旅行防護（Look-ahead Bias）**：
   - 在 DB-first 查詢時，必須嚴格限定 `日期 <= 決策基準日`。
   - **特別警告**：在 SQLite 查詢時若忘記加上日期過濾條件，會直接查到最新日期數據，造成嚴重的未來函數滲漏。因此，所有 SQL 查詢必須顯式傳入當前決策的 `base_date` 或是 `end_date`。

---

## 🔄 更新記錄

- 2026-06-03：初始建立 Phase 2A 盤點報告，列出所有 CSV-first 讀取點，並規劃 DB-first 改造路徑。
