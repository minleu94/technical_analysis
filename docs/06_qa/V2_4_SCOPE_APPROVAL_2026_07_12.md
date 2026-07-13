# V2.4 Portfolio Coach Foundation Scope Approval

> 日期：2026-07-12
> 決策人：使用者（release / product owner）
> 決策：**核准 V2.4 開始工程實作與 paper-only 驗證。**

## 核准範圍

- 以「平衡」風險方向建立 Portfolio Coach Foundation：中等現金緩衝、持倉上限、整數 bp target / current / gap、Equal Weight comparison、rebalance band、minimum trade、turnover 與 cooldown。
- 建立 paper portfolio、execution feasibility、成本 / 滑價 / 部分成交 / 拒單的可追溯研究證據與 decision journal foundation。
- Advice 在資料、可成交性或風險條件不足時必須輸出 `NO_NEW_POSITION` 或受限 diagnostics。

## 不包含

- broker 連線、真實下單、自動配置、自動再平衡、自動平倉。
- 將 paper 結果表述為投資有效性或正式 Portfolio performance。
- 無人工確認下變更實際持倉、風險預算、策略權重或 lifecycle。

## 後續人工 Gate

V2.4 工程完成後，使用者仍須確認實際風險政策數值、Paper Portfolio baseline / cost assumptions、限制情境與 `NO_NEW_POSITION` 行為；本文件是開工核准，不是 formal closeout。
