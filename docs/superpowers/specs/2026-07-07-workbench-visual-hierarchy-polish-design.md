# Workbench Visual Hierarchy Polish Design

## Goal

修正左側主導覽 icon 可辨識性不足、Workbench 總覽第一眼難讀，以及總覽標題 / 摘要區貼齊左上角造成的不平衡。

## Decisions

- 左側主導覽採自製一致線條 SVG icon，不再以兩個大寫英文字母作為主要 icon。
- 每個 icon 以 20x20 viewBox、2px stroke、round cap / join 呈現，使用現有 Midnight Analyst token 著色，不新增外部 icon 套件。
- Expanded 狀態顯示 icon + label + badge；collapsed 狀態只顯示 icon，tooltip 保留完整 label。
- Workbench 總覽採「指揮台摘要列」：今日待判讀、人工待處理、等待真實時間、Warnings 四個 summary block。
- Workbench title / summary 區與 tab pane 之間保留一致 gutter，左側、上方與摘要 panel 內距一致，避免內容貼齊邊界。

## Non-goals

- 不啟用 scheduler。
- 不寫 DB。
- 不執行 replay。
- 不補 Phase gate。
- 不產生買賣建議。
- 不重算 scoring、portfolio、backtest、recommendation 或 evidence domain 邏輯。

## Formal Data Gate

本次只改善 UI 可讀性。Phase 0 weekly history `0/3`、multi-day dry-run `1/3`、manual review note rhythm、action item rhythm 與 Phase 5 scheduler approval 仍需正式資料與真實時間紀錄才能標示完成。
