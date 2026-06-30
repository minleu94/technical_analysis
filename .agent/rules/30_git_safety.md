# Antigravity Rule 30 - Git Safety

## Git 前置檢查

Stage 或 commit 前必須先讀：

- `docs/agents/git_exclusions.md`

並執行：

```powershell
git status --short
```

## 不得 stage 的常見項目

- `.superpowers/`
- `docs/.tmp.driveupload/`
- `.pytest_cache/`
- `.coverage`
- `htmlcov/`
- `output/`
- `output/qa/`
- `test.parquet`

除非任務明確要求保存可分享的 QA 結論，否則 raw QA output 不得 stage；需要留存時整理到 `docs/06_qa/`。

## 多 Agent 協作

- 不要為了讓 working tree 乾淨而 revert、刪除或覆寫其他 Agent / 使用者留下的未提交變更。
- 若同一檔案已有不屬於本任務的變更，先讀懂差異再決定如何疊加。
- 高風險操作包含資料重建、分支清理、刪除檔案、批次移動，必須先取得明確確認。
