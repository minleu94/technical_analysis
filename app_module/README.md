# Application Service Layer

`app_module/` 是 UI、domain、資料存取與研究引擎之間的應用服務層。主要 UI `ui_qt/` 應透過 service 與 DTO 使用系統能力，不直接實作業務規則。

## 目前架構

```text
ui_qt
  -> app_module services / repositories / DTOs
      -> decision_module
      -> backtest_module
      -> portfolio_module
      -> data_module
      -> runtime
```

早期由 service 包裝 `ui_app` 業務邏輯的過渡方案已結束。核心決策邏輯目前位於 `decision_module/`，回測位於 `backtest_module/`，持倉 domain 位於 `portfolio_module/`。

## 主要責任

### 市場與推薦

- `recommendation_service.py`
- `screening_service.py`
- `regime_service.py`
- `broker_flow_service.py`
- `portfolio_chip_service.py`

負責組合決策元件、資料來源與 DTO，提供 UI 可使用的推薦、篩選、Regime 與籌碼結果。

### 資料更新

- `update_service.py`
- `broker_branch_update_service.py`
- `sqlite_inspector_service.py`

負責下載、合併、SQLite 同步、技術指標更新、資料狀態與唯讀檢視。

### 回測與研究

- `backtest_service.py`
- `batch_backtest_service.py`
- `walkforward_service.py`
- `optimization_service.py`
- `recommendation_portfolio_backtest_service.py`
- `recommendation_replay_service.py`

負責一般回測、批次回測、最佳化、Walk-forward、推薦回放與研究結果組裝。

### 保存與治理

- `backtest_repository.py`
- `recommendation_repository.py`
- `recommendation_portfolio_run_repository.py`
- `result_store.py`
- `strategy_version_service.py`
- `preset_service.py`
- `universe_service.py`

負責研究結果、推薦結果、策略版本、Preset 與 Universe 的保存及追溯。

### Portfolio

- `portfolio_service.py`
- `portfolio_condition_monitor.py`
- `portfolio_source_adapter.py`

負責交易記錄、持倉投影、來源 metadata 與條件監控。核心金額規則仍由 `portfolio_module/` domain 負責。

### Runtime

- `runtime_services/`
- `dtos/runtime_dtos.py`

負責 Runtime controller、健康快照與 UI DTO。

## DTO 原則

`app_module/dtos.py` 與子 DTO 模組是 UI contract。新增或修改欄位時必須：

1. 保持歷史資料 round-trip 相容，或提供 migration。
2. 明確標示資料日期、品質與來源。
3. 金融核心值遵守 Decimal、整數股數/基點與 numeric boundary 規範。
4. 同步更新 UI、測試與使用文件。

## 研究與金融防線

- 回測與推薦不得使用決策日之後的資料。
- quantile 回測門檻只能使用 T-1 以前歷史。
- 推薦百分位必須先固定 eligible universe。
- 核心金額、PnL、成本與倉位不得新增裸 `float` 計算。
- Factor 擴充必須走 Factor Contract，不直接耦合新資料表到 ScoringEngine。

## 使用方式

UI 層通常由 `ui_qt/main.py` 建立 service 並注入 view。獨立腳本應先建立 `TWStockConfig`：

```python
from data_module.config import TWStockConfig
from app_module.regime_service import RegimeService

config = TWStockConfig()
service = RegimeService(config)
result = service.detect_regime()
```

具體方法簽名以服務程式碼與測試為準，不在 README 複製可能快速過期的完整 API 清單。

## 近期工程方向

以 [ROADMAP_6M_ENGINEERING.md](../docs/00_core/ROADMAP_6M_ENGINEERING.md) 為準：

- 全 UI 健檢與 release healthcheck runner 收斂。
- Month 6.1 Strategy Lifecycle QA、manual approval workflow、Review Dashboard 與 Evidence Explainability。
- Portfolio feedback attribution 與 lifecycle review workflow 的證據保存、可解釋性與操作風險提示深化。
- PDF 研究報告輸出仍屬後續 backlog；Excel 規格化匯出已完成。

