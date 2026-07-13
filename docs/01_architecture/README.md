# 架構文檔目錄

> **系統架構相關文檔**

本目錄包含系統的架構設計和技術文檔。

## 📄 文檔列表

- **`system_architecture.md`**
  - 系統的技術架構說明
  - 模組結構、數據流程、技術細節

- **`target_system_architecture.md`**
  - Current → Transitional → Target 的理想架構與治理邊界
  - 不代表 target-only package 或能力目前已實作

- **`system_vision_specification.md`**
  - North Star、Bounded Advice、Evidence Requirements、Success Levels 與 Non-goals

- **`system_flow_end_to_end.md`**
  - 系統端到端流程說明
  - 從環境初始化到 UI 應用的完整流程

- **`data_collection_architecture.md`**
  - 數據收集系統的架構
  - API 端點、數據更新流程、數據存儲結構

- **`runtime_observatory_rules.md`**
  - Runtime Subsystem、DTO、UI bridge 與依賴方向治理規範

- **`ui_design_system_midnight_analyst.md`**
  - PySide6 UI theme tokens、共用元件、QSS 與效能限制

歷史遷移與已完成安全重構報告已移至 `../09_archive/`；QA closeout 與移除稽核位於 `../06_qa/`。

## 🔗 相關目錄

- `../00_core/` - 核心文檔
- `../03_data/` - 數據相關文檔
- `../06_qa/` - QA、驗證與 closeout 證據
- `../09_archive/` - 歷史遷移與已完成計畫

