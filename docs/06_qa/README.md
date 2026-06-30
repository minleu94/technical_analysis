# QA 相關文檔目錄

> **QA 驗證和問題文檔**

本目錄包含所有 QA 相關的文檔。

## 📄 文檔列表

### 推薦分析 Tab QA
- `QA_RECOMMENDATION_TAB_ISSUES.md` - QA 問題
- `QA_RECOMMENDATION_TAB_SUMMARY.md` - QA 總結

### 數據更新 Tab QA
- `QA_UPDATE_TAB_ISSUES.md` - QA 問題
- `QA_UPDATE_TAB_SUMMARY.md` - QA 總結

### 全程式人工 Health Check 與測試路由
- `V1_RELEASE_CHECKLIST_2026_06_30.md` - v1.0.0-rc.1 / v1.0.0 發布前 release readiness gate，涵蓋乾淨 main、全新 clone、非破壞 healthcheck、MainWindow UI smoke 與人工 UI 驗證。
- `FULL_APP_HEALTHCHECK_2026_06_16.md` - 主 UI 人工 smoke test 母檔，包含數據更新、SQLite 檢視、TPEX 日價、券商分點、每日決策與跨工作區流程
- `FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md` - Testing / QA Agent + Full App Healthcheck Runner A-E 完成後的收束報告、可用邊界與下一階段選項。
- `TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md` - `tests/` 全量測試分類，定義哪些測試可直接橋接到非破壞式 release healthcheck runner、哪些只能作 oracle、哪些需保留 manual / dry-run。
- `FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md` - Testing QA Agent 使用的 feature-to-test 測試路由與決策矩陣（測試知識庫），不包含 Agent 角色定義。

### UI Qt Roadmap Audit
- `UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md` - UI Qt 對照 development roadmap 的完成度稽核報告

### 文件與工具稽核
- `DOCUMENT_ENCODING_AUDIT_2026_06_16.md` - repo 文件 UTF-8 / mojibake 掃描報告

## 🔗 相關目錄

- `../02_features/` - 功能文檔
- `../03_data/` - 數據相關文檔
