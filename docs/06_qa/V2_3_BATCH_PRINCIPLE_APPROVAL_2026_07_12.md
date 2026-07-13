# V2.3 P0 Sources Batch Principle Approval

> 日期：2026-07-12
> 決策人：使用者（release / data-governance owner）
> 決策：**全部 P0 source 原則核准導入方向；維持 `downstream eligibility=none`。**

## 決策範圍

本次核准涵蓋 `V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md` 的所有 13 個 P0 source。這是導入方向與補證工作授權，不是已完成的 source acceptance，也不授權正式 ingestion、`ScoringEngine` 接線、Advice、Portfolio、scheduler、broker 或交易。

## 維持的安全狀態

- 台帳各列的 `human decision` 仍為 `requires_human_acceptance`，直到逐列證據完成後才可改為 `accepted` / `limited` / `rejected` / `deferred`。
- 所有 `downstream eligibility` 維持 `none`。
- 缺 source version、license、as-of / available date、coverage、missing / outage、quarantine / retry 或 rollback evidence 時必須 fail-closed。
- 不得以本文件推定任何資料已可用、授權已完成或不存在 look-ahead bias。

## 已授權的後續工作

1. 由工程補齊 registry / manifest / metadata / source coverage / evidence links。
2. 對可公開驗證的官方來源蒐集版本、取得時間、rate limit、公告或 available-date 語意。
3. 對無正式 contract 的來源建立缺口與 fail-closed evidence，不以 sample、replay 或猜測補值。
4. 完成後再逐列向使用者提出可真正選擇 `accepted` / `limited` / `rejected` / `deferred` 的決策卡。

## 不包含的人工確認

- 商業授權、再散布、付費資料合約或帳號權限。
- 未登錄 corporate action、停牌 / 復牌與 PIT 季度財報的正式來源選擇。
- 任何 production ingestion、正式資料庫 schema write、scheduler write-mode 或投資決策啟用。
