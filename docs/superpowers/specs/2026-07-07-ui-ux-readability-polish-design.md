# UI UX Readability Polish Design

## Goal

修補左側主導覽後第一輪真實使用發現的可讀性與空間浪費問題，讓主工作台更容易掃描，並避免市場弱勢資料用錯視覺語意。

## Scope

In scope：

- Runtime Observatory 上方大留白改為薄型 scope banner，主要區塊往上顯示。
- 左側主導覽加入一致的文字圖示與收合模式；收合時只顯示 icon，完整名稱保留在 tooltip。
- Workbench 總覽加強資訊層級：summary card / section guide / status color，而不是全部用同一種文字堆疊。
- Workbench 的 `Evidence`、`持倉追蹤`、`操作節奏` 子頁明確標示為「摘要 / 下鑽入口 / future detail lane」，避免被誤解成空白或壞掉。
- 市場探索的弱勢個股與弱勢產業 `跌幅%` 顯示為紅色，數值顯示正數百分比，不帶負號。

Out of scope：

- 不改 scoring / recommendation / backtest / portfolio 核心計算。
- 不改 schedule / report output。
- 不改 evidence DB / scheduler / lifecycle。
- 不把 Workbench placeholder 子頁宣稱為完整功能。

## UX Decisions

1. Runtime 採「compact operational console」：標題、scope note、splitter 三段垂直貼齊；說明只做邊界提醒，不佔內容主視覺。
2. Left nav 採 low-risk text-symbol icons：避免新增外部 icon dependency；用 `◎` / `↗` / `◇` 等單字元輔助掃描，並保留 tooltip。收合寬度約 58 px，展開寬度 184 px。
3. Workbench 第一版不重做整個 dashboard，只補「讀法」：在總覽頂部加一組 summary cards，並在 placeholder 子頁用清楚文案說明目前是預留深挖 lane。
4. 弱勢市場資料遵守語意色彩：跌幅永遠是紅色；弱勢頁的 `跌幅%` 值使用絕對值顯示，避免負號與欄名重複表意。

## Safety Boundary

所有變更只在 PySide6 UI / tests / docs。不得新增 DB write path、不得啟用 scheduler、不得執行 replay、不得改正式資料。

