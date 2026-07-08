# Workbench Overview Density Redesign

## 背景

2026-07-07 主 UI「決策工作台 > 總覽」已能揭露 freshness、scheduled evidence dry-run、manual recommendation fallback、replay diagnostics 與 read-only boundary，但背景證據流與其他總覽區塊把完整 diagnostics / source trace 直接放進表格欄位，造成資訊密度過高、水平捲動與判讀負擔。

## 目標

- 總覽第一屏先回答「今天要看什麼、是否安全、哪裡降級」。
- 表格改為掃描用途，只顯示短欄位；完整 source trace / degraded reason / diagnostics 放進右側詳情檢視。
- 次要區塊改為可收合，預設降低畫面高度與捲動量。
- 保留所有 read-only 邊界：不寫 DB、不啟用 scheduler、不重跑 replay、不補 Phase gate、不改 DTO 資料來源。

## 設計

1. 頂部四張摘要卡維持，但提高可讀性與第一屏權重。
2. 在摘要卡上方新增「今日重點」色帶，集中顯示待判讀、人工處理、等待真實時間與 warnings。
3. 導入語意色：綠色代表 ready / observed / passed，藍色代表資訊或 manual observed，橘色代表 warning / degraded / waiting / manual required，紅色代表 missing / blocked / critical。
4. 表格 row 依 status / severity 回傳 foreground / background / bold font role，讓重要事件在列表掃描時直接浮出。
5. Inspector 改為狀態徽章與三個分區：「重點摘要」、「來源與邊界」、「診斷訊號」。
6. 主內容改成雙欄：
   - 左欄：今日待判讀、背景證據流、只讀 Action Items 的緊湊清單。
   - 右欄：詳情檢視 / Inspector，點選任一清單列後顯示完整 item id、status、summary、source trace、degraded reason、diagnostics、drilldown target 與 read-only 提醒。
7. 背景證據流表格只保留 `label / status / summary`；`source_trace / degraded_reason / diagnostics` 保留於 raw DTO 與 Inspector。
8. 操作節奏、Evidence mode、Daily Checklist、Warnings 改成可收合區塊；預設收合次要資訊，避免使用者一進頁面就被長文淹沒。
9. Drill-down 維持既有舊頁導向 contract，雙擊列或按 Inspector 下鑽按鈕才切頁。

## 驗收

- 測試確認 evidence feed model 不再把 diagnostics 顯示為表格欄位，但 `row_at()` 仍可取回完整 diagnostics。
- 測試確認 table model 針對 degraded / warning row 回傳語意 foreground / background / bold font role。
- 測試確認點選 evidence feed row 後，Inspector 會顯示 source trace、degraded reason 與 diagnostics。
- 測試確認 Inspector 顯示狀態徽章與「重點摘要 / 來源與邊界 / 診斷訊號」三個分區。
- 測試確認總覽有高對比今日重點帶，摘要卡依狀態呈現非白色語意色。
- 測試確認次要區塊可收合。
- UI 修改後執行 Workbench view tests、UpdateView required tests、QA script、py_compile 與 mypy。
