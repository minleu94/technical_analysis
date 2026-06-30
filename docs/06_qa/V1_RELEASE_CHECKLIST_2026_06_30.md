# v1.0.0 Release Checklist

> **建立日期**：2026-06-30
> **目標版本**：`v1.0.0-rc.1` -> `v1.0.0`
> **目前執行分支**：先在 `dev` 驗證；只有通過本清單的 release-critical gate 後，才 cherry-pick / merge 必要內容到 `main`。
> **定位**：本文件是 v1 release readiness gate，不是新功能 roadmap。它只判定目前系統是否足夠乾淨、可啟動、可驗證、可人工操作，能否標記為正式 v1。

---

## 1. 版本判定規則

### 可標 `v1.0.0-rc.1`

- [ ] `main` 可乾淨 clone、安裝、啟動。
- [ ] `dev` 的 release-critical healthcheck / UI smoke 內容已判斷是否需要合入 `main`。
- [ ] 自動化驗證與非破壞式 healthcheck 通過，或失敗項已歸類為 non-blocking 並有明確原因。
- [ ] 人工 UI smoke 完成，且沒有阻擋使用者完成主要工作流的 P0 / P1 問題。
- [ ] README、Application Manual、Snapshot、Roadmap、Vision 對 v1 邊界沒有互相矛盾。

### 可標正式 `v1.0.0`

- [ ] `v1.0.0-rc.1` 的 blocking issue 全部關閉。
- [ ] 使用者可依 `README.md` 完成第一次啟動。
- [ ] 8 個頂層工作區人工檢查完成。
- [ ] 高風險資料寫入、migration、backfill apply、真實資料重建沒有在 release gate 中被誤觸發。
- [ ] 若保留已知限制，已在 Manual / README / release note 清楚揭露。

---

## 2. Release-critical Gate

| Gate | 狀態 | Blocking 條件 | 驗證方式 |
|---|---|---|---|
| Git 狀態 | 進行中 | 有未提交變更、local 與 remote 不一致 | `git status --short --branch` |
| 乾淨 main | dev 初驗通過；main 待複驗 | `main` 追蹤 `output/`、暫存、DB、raw QA artifact | `git ls-files output test.parquet` |
| 文件編碼 | 通過 | 文件編碼測試失敗或 mojibake 實際存在於檔案內容 | `pytest tests/test_audit_document_encoding.py` |
| 文件 whitespace | 通過 | `git diff --check` 報錯 | `git diff --check` |
| Quick healthcheck | 通過 | quick mode 失敗且無已知 non-blocking 解釋 | `scripts/run_full_app_healthcheck.py --mode quick` |
| Tab full bridge | 通過 | direct bridge 分頁失敗且屬 release-critical flow | 逐 tab `--mode full --tab <tab>` |
| MainWindow UI smoke | 通過 | 主視窗無法啟動、8 個頂層 tab 無法切換、cancel-only dialog 無法安全關閉 | opt-in `--ui-smoke` |
| 人工 UI smoke | 通過 | 使用者無法完成核心工作流，或 UI 有明顯阻斷操作的錯誤 | 本文件第 5 節 |
| 文件一致性 | 待人工 review | README / Manual / Snapshot / Roadmap / Vision 對 v1 邊界互相矛盾 | 人工 review |
| Tag 前確認 | 待 main release review | `main` 未包含 release-critical 修正或仍需回滾 | release lead review |

---

## 3. 自動化驗證命令

### 3.1 安全基礎檢查

```powershell
git status --short --branch
git diff --check
git ls-files output test.parquet
.\.venv\Scripts\python.exe -m pytest tests\test_audit_document_encoding.py -q -o addopts=
```

### 3.2 非破壞式 quick healthcheck

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\v1_release_candidate\quick --fail-fast
```

### 3.3 分頁 full direct bridge

先逐頁執行，避免一口氣跑完整 full mode 時難以定位：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab update --output-dir output\qa\v1_release_candidate\full_update --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab decision --output-dir output\qa\v1_release_candidate\full_decision --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab research --output-dir output\qa\v1_release_candidate\full_research --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab recommendation --output-dir output\qa\v1_release_candidate\full_recommendation --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab watchlist --output-dir output\qa\v1_release_candidate\full_watchlist --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab portfolio --output-dir output\qa\v1_release_candidate\full_portfolio --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab runtime --output-dir output\qa\v1_release_candidate\full_runtime --fail-fast
```

### 3.4 MainWindow UI smoke

此 gate 會啟動真實 MainWindow，必須是 opt-in。不得自動 confirm 高風險 dialog。

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir output\qa\v1_release_candidate\ui_smoke --fail-fast
```

---

## 4. 全新 clone / install Gate

此 gate 用於確認 `main` 不是只在目前工作目錄可用。

- [ ] 以乾淨目錄 clone repo。
- [ ] checkout `main`。
- [ ] 建立 `.venv`。
- [ ] 安裝 `requirements.txt`。
- [ ] 設定或確認 `DATA_ROOT` / `OUTPUT_ROOT`。
- [ ] 啟動 `ui_qt/main.py`。
- [ ] 確認缺資料時 UI 以 warning / degraded / missing 呈現，而不是崩潰。
- [ ] README quickstart 與實際流程一致。

建議命令：

```powershell
git clone <repo-url> technical_analysis_v1_rc
cd technical_analysis_v1_rc
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe ui_qt\main.py
```

---

## 5. 人工 UI Smoke Checklist

人工驗證只做非破壞操作；所有資料寫入、重建、migration、backfill apply 或高風險 confirm 都要跳過或只測 cancel path。

| 工作區 | 必看項目 | Blocking 條件 | 狀態 |
|---|---|---|---|
| 數據更新 | 主要頁面、資料狀態、SQLite Inspector、危險操作 cancel path | 開頁崩潰、危險操作無 cancel / warning、資料狀態無法判讀 | 通過 |
| 市場觀察 | Regime、強弱股、強弱產業、Smart Money 子頁 | 表格或圖表空白且無 warning、下鑽失效 | 通過 |
| 每日決策 | answer-first dashboard、Market Breadth、Sector Rotation、Watchlist Trigger、Portfolio Alert | 主要摘要不可讀、資料缺口無 quality / warning | 通過 |
| 策略回測 / Research Lab | 單股 / 批次 / 推薦回放入口、Registry / compare / promote 邊界 | 可誤觸高風險 promote、結果頁崩潰、限制未揭露 | 通過 |
| 推薦分析 | Profile、Regime match / mismatch、Why / Why Not、next steps | 推薦結果無資料品質、原因欄位不可讀 | 通過 |
| 觀察清單 | candidate pool、Universe CRUD 的安全操作、Research Lab 輸入 | 候選池無法加入 / 移除，或流程無法銜接 | 通過 |
| 持倉管理 | 持倉、交易歷史、策略與價格監控、生命週期回顧 | lifecycle / gap 判讀不可讀，或誤導為自動交易 | 通過 |
| Runtime Observatory | FSM、治理健康、event stream | 無法開啟、錯誤被包裝成成功 | 通過 |

---

## 6. v1 Release Blocking Policy

### 必須阻擋 v1

- 主程式無法啟動。
- 任一頂層工作區開啟即崩潰。
- README quickstart 無法在乾淨環境重現。
- 高風險資料寫入 / migration / backfill apply 沒有明確 cancel / confirmation。
- 回測、推薦、Portfolio、Daily Decision Desk 任何一處把 v1 訊號描述成保證獲利或交易建議。
- `main` 追蹤本機 raw output、DB、log、暫存或正式資料。

### 可不阻擋 v1，但需揭露

- PDF 報告尚未完成。
- 三大法人、信用交易、處置股完整風險模型尚未完成。
- Forward Performance Dashboard / Live vs Research Gap Dashboard 尚未完成。
- MainWindow smoke 窄 viewport 因最小寬度顯示 constrained，而非真正 responsive mobile layout。
- 某些資料來源缺失，但 UI 有清楚 `MISSING` / `DEGRADED` / warnings。

---

## 7. Dev -> Main 合入判斷

目前 `dev` 相對 `main` 多出的主要內容是 Full App Healthcheck / MainWindow UI smoke、部分 UI 微調、測試與 QA 文件。合入 `main` 前需逐項判斷：

- [ ] Healthcheck runner / MainWindow smoke 是否要作為 v1 release tooling 合入 `main`。
- [ ] UI theme / fonts / update view / backtest view 微調是否已通過人工 smoke。
- [ ] 重新命名或搬移的測試檔是否不影響預設 pytest collection。
- [ ] docs / manual 是否與實際 UI 一致。
- [ ] 所有輸出仍寫入 ignored `output/`，不進 git。

---

## 8. 本次執行紀錄

| 日期 | 分支 | 命令 / Gate | 結果 | 備註 |
|---|---|---|---|---|
| 2026-06-30 | `dev` | 建立 checklist | 通過 | 已新增本文件，並更新 `docs/06_qa/README.md` 與 `docs/00_core/DOCUMENTATION_INDEX.md`。 |
| 2026-06-30 | `dev` | `git diff --check` | 通過 | 僅有 Windows CRLF warning，無 whitespace error。 |
| 2026-06-30 | `dev` | `git ls-files output test.parquet` | 通過 | 無輸出，表示 raw output / 臨時資料未被 Git 追蹤。 |
| 2026-06-30 | `dev` | `pytest tests/test_audit_document_encoding.py -q -o addopts=` | 通過 | `4 passed in 0.08s`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode quick --output-dir output\qa\v1_release_candidate\quick --fail-fast` | 通過 | `Healthcheck passed: 20260630_143912`；輸出位於 ignored `output/`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --tab update --output-dir output\qa\v1_release_candidate\full_update --fail-fast` | 通過 | `Healthcheck passed: 20260630_143935`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --tab decision --output-dir output\qa\v1_release_candidate\full_decision --fail-fast` | 通過 | `Healthcheck passed: 20260630_143946`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --tab runtime --output-dir output\qa\v1_release_candidate\full_runtime --fail-fast` | 通過 | `Healthcheck passed: 20260630_143944`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --tab research --output-dir output\qa\v1_release_candidate\full_research --fail-fast` | 通過 | `Healthcheck passed: 20260630_144016`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --tab recommendation --output-dir output\qa\v1_release_candidate\full_recommendation --fail-fast` | 通過 | `Healthcheck passed: 20260630_144016`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --tab watchlist --output-dir output\qa\v1_release_candidate\full_watchlist --fail-fast` | 通過 | `Healthcheck passed: 20260630_144014`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --tab portfolio --output-dir output\qa\v1_release_candidate\full_portfolio --fail-fast` | 通過 | `Healthcheck passed: 20260630_144014`。 |
| 2026-06-30 | `dev` | `run_full_app_healthcheck.py --mode full --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir output\qa\v1_release_candidate\ui_smoke --fail-fast` | 通過 | `Healthcheck passed: 20260630_151530`；主視窗標題 `baldr`，8 個頂層工作區皆可切換，`update_force_merge_daily_price` dialog 可取消且未呼叫 destructive action。窄 viewport 受最小寬度限制，依第 6 節列為已知 non-blocking 限制。 |
| 2026-06-30 | `dev` | 人工 UI smoke：8 個頂層工作區 | 通過 | 使用者回報數據更新、市場觀察、每日決策、策略回測 / Research Lab、推薦分析、觀察清單、持倉管理、Runtime Observatory 皆 OK；無回報 blocking issue。 |
