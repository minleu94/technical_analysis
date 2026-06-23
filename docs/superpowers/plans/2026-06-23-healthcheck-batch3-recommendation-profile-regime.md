# Healthcheck Batch 3 Recommendation Profile / Regime 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:executing-plans 依序執行本計畫。每完成一個 task 後必須跑該 task 的 verification，並在發現偏離時停止修正。

**Goal:** 完成推薦分析 Profile / Regime lifecycle 修復，處理 `RECOMMEND-ISSUE-001`、`RECOMMEND-ISSUE-002`、`RECOMMEND-ISSUE-003`、`RECOMMEND-ISSUE-004`、`RECOMMEND-ISSUE-008`，讓推薦分析能清楚區分內建 Profile、自訂 Profile、通過 gate 的策略版本 Profile，並揭露目前 Regime、Profile 適用 Regime、match / mismatch 與分數排序影響。

**Architecture:** 新增薄型 `RecommendationProfileService` 作為 Profile lifecycle 與 JSON round-trip 邊界；`RecommendationView` 只負責呈現、套用與保存使用者可見設定；既有 `StrategyVersionService` 維持歷史策略版本資料，不刪停用版本，只在 Profile 清單做 active / gate filter；既有 `RecommendationService` 與 `ScoringEngine` 不新增交易建議或自動持倉動作。

**Tech Stack:** Python 3、PySide6、pytest、Decimal / integer basis point numeric contract、repo 既有 `TWStockConfig.resolve_output_path()` 儲存路徑。

---

## Base Branch / Commit 判斷依據

- 已執行 `git fetch --all --prune`、`git status --short --branch`、`git branch -vv`、`git log --oneline --decorate --graph --all --max-count=30`。
- `origin/main` 目前為 `298d613 docs: add non-destructive healthcheck runner plan`，包含使用者最新 push 的 runner plan，但 `938ad47` 不是 `origin/main` 的 ancestor。
- `origin/codex/healthcheck-batch1-direct-fixes` 目前為 `938ad47 feat: add healthcheck batch 2 dashboard semantics`，包含 Batch 1 commit `0e9a29a` 與 Batch 2 commit `938ad47`，但不含 `origin/main` 的 runner plan。
- 目前沒有單一已 push 分支同時包含 Batch 1 / Batch 2 與使用者最新 runner plan。Batch 3 以 `origin/codex/healthcheck-batch1-direct-fixes` 的 `938ad47` 作為 code base，並把 `origin/main` 的 `docs/superpowers/plans/2026-06-23-non-destructive-release-healthcheck-runner.md` 帶入新分支。
- 已建立工作分支 `codex/healthcheck-batch3-recommendation-profile-regime`；目前未 commit、未 push。

## Scope Boundary

### In Scope

- 推薦分析 Profile 下拉選單支援三種來源：
  - 內建 Profile：現有三個 UI 預設 Profile，顯示為內建來源。
  - 自訂 Profile：由目前 UI 設定保存到 repo 既有 config / output root 下的推薦 Profile 儲存區，顯示 `自訂，未經回測驗證`。
  - 策略版本 Profile：只列出 Research Lab / Strategy Registry 已通過 gate 的策略版本；停用版本不出現在下拉，但不得刪除歷史 JSON。
- Profile lifecycle service：
  - list / save custom / load custom / filter strategy version profiles。
  - JSON round-trip 保留 Decimal 字串與 integer basis point 權重，不把金融核心數值寫成不受控 naked float。
- Regime 呈現：
  - 顯示目前 Regime code / 中文名稱 / confidence / source 或 as-of 資訊。
  - 顯示 Profile 適用 Regime、目前 match / mismatch / neutral、以及既有評分語意中的 bonus / no bonus / penalty 等價說明。
  - mismatch 不排除推薦結果，只作解釋、排序或分數揭露。
- UI copy：
  - 將目前「策略傾向」若仍是摘要，命名為「目前策略傾向摘要」。
  - 增加新手 Profile 對應進階設定的可讀描述。
- 文件同步：
  - `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/01_architecture/system_architecture.md`（若新增 service 邊界）
  - `docs/00_core/DOCUMENTATION_INDEX.md`

### Out of Scope

- 不新增交易建議、自動下單、自動持倉調整。
- 不改推薦核心買賣策略語意，不改回測績效規則。
- 不刪除策略版本歷史資料；停用只影響清單可見性。
- 不做資料重建、SQLite migration 或 destructive cleanup。

## Look-ahead / Numeric Self-check

- Strategy version Profile 只能從已存在、已通過 gate 的版本產生；不得用未來回測結果即時提高當下推薦分數。
- Regime 顯示使用 `RegimeService.detect_regime()` 的當下結果或既有 snapshot；文件需標示來源與日期 / as-of，避免把未來 regime 視為決策當下可見。
- 自訂 Profile JSON 儲存時：
  - `Decimal` 以字串保存。
  - weights 優先保存為整數 bp（例如 `5500`），避免 `0.55` 這類裸 float 成為權威資料。
  - runtime UI 邊界若需轉為 `float` 給 Qt spinbox，必須限縮在呈現/套用邊界，不作金融核心計算權威。
- 執行 `scripts/check_financial_float_boundaries.py`，若新增檔案觸發掃描需補上合規註記或改用 Decimal / int。

## File Map

- 新增：`app_module/recommendation_profile_service.py`
  - Profile dataclass / DTO。
  - 自訂 Profile JSON repository。
  - Strategy version gate / disabled filter。
  - Regime compatibility explanation。
- 修改：`ui_qt/views/recommendation_view.py`
  - Profile dropdown source labels。
  - 保存自訂 Profile 行為。
  - Regime / Profile compatibility 顯示。
  - 策略傾向摘要命名與 copy。
- 可能修改：`ui_qt/main.py`
  - 若需要由 MainWindow 注入 profile service，優先保持可選參數以降低 blast radius。
- 新增 / 修改測試：
  - `tests/test_recommendation_profile_service.py`
  - `tests/test_ui_qt_recommendation_profiles.py` 或既有推薦 UI focused tests。
- 文件：
  - `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/01_architecture/system_architecture.md`
  - `docs/00_core/DOCUMENTATION_INDEX.md`

## Rollback List

- 刪除 `app_module/recommendation_profile_service.py`。
- 還原 `ui_qt/views/recommendation_view.py` Profile dropdown、save custom、Regime explanation、copy 變更。
- 還原新增 / 修改的 Batch 3 tests。
- 還原 Batch 3 文件段落與 `DOCUMENTATION_INDEX.md` 索引項目。
- 保留使用者最新 runner plan 檔案除非使用者要求，因該檔來自 `origin/main` 最新 push 且不是 Batch 3 實作副作用。

## TDD Steps

1. Profile service failing tests
   - 驗證內建 / 自訂 / 策略版本 Profile 會產生帶來源的 option labels。
   - 驗證自訂 Profile 保存後再讀回，`Decimal` 與 integer bp weights 不變成裸 float。
   - 驗證策略版本只列出 gate-passed 且未停用版本；停用 / pending / rejected 版本不顯示但 JSON 仍存在。
   - 驗證 Regime match / mismatch / neutral explanation 不回傳排除語意。

2. UI focused failing tests
   - 驗證推薦分析 Profile combo 含 `內建｜`、`自訂｜`、`策略版本｜` 三種來源。
   - 驗證選擇 Profile 後描述區顯示目前 Regime、適用 Regime、match 狀態與分數影響。
   - 驗證自訂 Profile 保存後標示 `自訂，未經回測驗證`。
   - 驗證策略傾向區塊標題為「目前策略傾向摘要」。

3. Service implementation
   - 實作 profile dataclass、JSON sanitizer / loader、custom save、strategy version filter、regime compatibility。
   - 保持與既有 `StrategyVersionService` 相容，不要求 schema migration。

4. UI implementation
   - 將現有內建 Profile 透過 service normalize。
   - 加入自訂保存按鈕與 refresh flow。
   - 更新 `_collect_config()`、`_on_profile_selected()`、snapshot / portfolio metadata 使用新的 profile lookup。
   - 更新 Regime 與 Profile 說明 copy。

5. Docs implementation
   - 更新 healthcheck issue 狀態與 Batch 3 註記。
   - 更新 Manual 的推薦分析操作、Profile lifecycle、Regime mismatch 判讀與安全限制。
   - 若 service 邊界新增，更新 architecture。

## Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_profile_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_profiles.py tests\test_ui_qt_research_workflow.py tests\test_recommendation_ranking_service.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_profile_service.py ui_qt\views\recommendation_view.py
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

## Docs Update Checklist

- [x] `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`：標示 Batch 3 對應 issues 與處理結果。
- [x] `docs/07_guides/APPLICATION_MANUAL.md`：補 Profile 類型、自訂保存、策略版本 gate、Regime mismatch 判讀、安全限制與排錯。
- [x] `docs/01_architecture/system_architecture.md`：補 `RecommendationProfileService` 邊界與資料流。
- [x] `docs/00_core/DOCUMENTATION_INDEX.md`：加入 Batch 3 plan 與最新 runner plan。
- [x] 依 `DOC_COVERAGE_MAP.md` 檢查 UI / service / recommendation core 相關文件是否需額外同步。
