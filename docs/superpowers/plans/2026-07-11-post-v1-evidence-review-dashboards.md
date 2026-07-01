# Post-V1 Evidence Review Dashboards Read-only UI Pack 實作計畫

## 1. Preflight

- 確認 Round 1-10 evidence pipeline、Forward Evidence UI、Live Gap、Signal Decay 與 Decision Quality service 邊界。
- 確認 Research Lab result panel 是最小侵入 UI placement。
- 確認新 UI 不直接 import repository / SQLite / scoring / portfolio mutation / scheduler。

## 2. Dashboard Service / DTO

- 新增 Decision Quality dashboard DTO / service。
- 新增 Signal Decay dashboard DTO / service。
- 新增 Live vs Research Gap dashboard DTO / service。
- 新增 DecisionQualityService read-only `list_items` passthrough。
- 保持 dashboard service read-only，只做 filter、row mapping、summary card 與 empty state。

## 3. Qt Model / View

- 新增三個 table model，保留 bp raw numeric value，display 才轉百分比。
- 新增三個 dashboard view，支援 filter panel、summary cards、main table、detail panel、empty / degraded state。
- 新增 `EvidenceBoundaryBanner`。
- 新增 `EvidenceReviewView` 容器，把 Forward Evidence、Live vs Research Gap、Signal Decay、Decision Quality 放入同一 evidence review tab set。

## 4. Research Lab Integration

- 修改 `ui_qt/views/backtest/result_panel.py`，將既有 Forward Evidence 掛載改為 Evidence Review 容器。
- 不新增頂層 workspace，不改 MainWindow navigation。

## 5. Tests

- 新增 dashboard service tests。
- 新增 Qt view / table model tests。
- 新增 forbidden language / forbidden UI import / no write call boundary tests。
- 跑既有 Decision Quality、Signal Decay、Live Gap 與 Forward Performance dashboard service 回歸。

## 6. Documentation / QA

- 新增 QA 文件。
- 更新 Project Snapshot、6M Roadmap、Vision、Architecture、Manual 與 Documentation Index。
- 明確保留 production scheduler 未啟用、alpha 未證明、dashboard 只是 inspection layer。
