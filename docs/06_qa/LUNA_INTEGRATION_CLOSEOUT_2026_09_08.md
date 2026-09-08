# LUNA 三線整合驗收（2026-09-08）

狀態：**工程整合驗收通過；正式 ML 仍維持 fail-closed。** 使用者已授權完整整併、commit、推送 origin 及僅保留 main／dev 與主 checkout。

## 回滾清單（動作前保存）

| 範圍 | 動作 | 回復 | 風險 |
|---|---|---|---|
| 67個既有dirty檔案（精確清單見baseline_changes.json） | 保存A／B及前次整理，後續只修驗收缺陷 | 逐檔從output/qa/luna_integration_20260908/backup還原，比對SHA；新檔與刪除依manifest處理 | 不可覆寫之後他人修改 |
| codex/luna-c-uiux=7868a517、dev=71500ef6、main=4e1641c4 | 測試通過後fast-forward整併 | refs_before.txt及pre_integration.bundle保存完整refs | 已推送後用新增revert，不force push |
| query_current_repo_context=f64f4db8 | 確認祖先已整併且乾淨後移除worktree與branch | git branch query_current_repo_context f64f4db8；依worktrees_before.txt重建 | ignored產物須先盤點保存 |
| 本文件及整合缺陷修補 | 新增／修改 | 新檔移除，修改檔依逐檔backup回復 | 最後完整重驗 |

正式D原始資料、既有模型與排程不在變更範圍。三線工程完成不等同ML來源、正式OOS或投資有效性完成。

## 三線交付判定

- **A：工程修補可整併，真實來源／正式 ML 目標未完成。** ML release 以中立 loader registry 解開跨層引用，CLI 在 composition root 註冊 App adapter；未註冊時拒絕載入。OOC trainer 在建立輸出、容量預檢及 fit 之前拒絕無效 teacher。中央 200 GiB 安全保留沒有降低，本輪沒有執行新的 fit、promotion 或正式資料更新。
- **B：架構與清冊交付納入，補完整合測試隔離後驗收。** 欄位 resolver 與 SignalCombiner 共用流程收斂，保留 facade 與不同金融政策；移走共用 ML fixture，拆開 runtime／dev requirements。7 份失效診斷腳本、其 README 與已合併的重複欄位測試共 9 個舊檔刪除，原始資料不在清理範圍。
- **C：UI 工程交付可整併。** 原始提交為 `7868a5176ab51886059438c751cd0f25c0b94e16`；研究 context、來源診斷、比較假設及持倉 scope 與 Manual 一起收錄。offscreen 驗證不代表所有原生 DPI、真實資料與長文字版面均已完成體驗驗收。

### 整合時發現並處理的缺陷

1. 合成資料測試仍讀取真實 C 槽容量，C 槽低於正式 200 GiB reserve 時在 fixture 建立階段失敗。只在明確的合成測試／module fixture 注入可控容量；專用容量不足、跨磁碟與拒寫測試仍使用自己的 oracle。
2. 兩個 builder CLI 在子程序不繼承 pytest patch，改由受限測試 wrapper 啟動原 CLI；只准兩個既有 fixture builder 路徑，新增不支援入口的拒絕測試。產品 CLI 沒有新增測試環境變數後門。
3. B 先前完整測試將 TEMP 放在 repository 內，觸發輸出路徑保護與 Windows 路徑問題。本次保留系統 TEMP，僅將 DATA_ROOT／OUTPUT_ROOT 指向隔離 QA 目錄，不放寬正式路徑防護。已同步修正共同規劃及 A／C Prompt 的 TEMP 指示，避免後續照舊指示再現衝突。
4. PROJECT_NAVIGATION 與 DOCUMENTATION_INDEX 的 27 個機器絕對連結改成有效相對連結。
5. C 新增研究橫幅更新後，既有 task-loop 測試的 SimpleNamespace 替身缺少對應方法。補上替身並驗證橫幅收到清空後的 result ID；沒有刪除舊保存／清除行為的斷言。

## 驗證紀錄

| 檢查 | 結果 | 本機證據 |
|---|---|---|
| 合成容量／CLI／真實容量第一批 | 42 passed、1 skipped | `isolation_targeted.log` |
| 其餘 module fixture／UI 契約修補 | 43 passed | `remaining_fixture_after.log` |
| 全量 pytest 第一次整合驗證 | 4,639 passed、3 skipped、1 failed、12 errors；缺陷已修補，非最終通過證據 | `pytest_full_1.log` |
| 測試與受檢文件清冊 | 743 檔／743 entries；4,655 測項；missing／stale／count drift、失效及不可攜連結皆無 | `inventory_final.json` |
| UpdateView 強制回歸 | 81 passed | `update_ui.log` |
| 更新頁 QA | 25 passed、0 failed、4 skipped；skip 不算功能已執行 | `update_qa.log` |
| 全模組 mypy | 565 個 source files，沒有錯誤 | `mypy.log` |
| Quant guard | financial float 與 look-ahead 檢查通過 | `quant_guard.log` |
| ML import boundary | 459 檔受檢、0 violations | `ml_boundary.log` |
| 改動 Python 編譯 | 50 檔通過 | `py_compile.json` |
| 真 MainWindow offscreen smoke | 8／8 tabs；1366×768、390×844 requested＝actual；取消沒有觸發寫入 | `ui_smoke/` |
| Git 工作副本 diff check | exit 0（使用專案既有換行設定） | `diff_check.log` |
| 最終空白整理／文件同步後 | 分析與清冊回歸 25 passed；文件 audit 通過、受檢連結無缺漏 | `closeout_targeted.log`、`inventory_post_docs.json` |

**最終完整 pytest：4,652 passed、3 skipped、67 warnings，586.11 秒，exit 0。** 4,655 個測項沒有失敗或初始化錯誤；證據為 `pytest_full_final.log`。3 個 skip 均是平台不允許建立 symlink 的案例，既有 pandas dtype／日期頻率等依賴警告仍保留，不宣稱零警告。完整測試後只清除共用 SignalCombiner 複製程式的行尾空白並做定向回歸，再同步結論文件。上述 QA 檔案均位於本輪 ignored output 目錄。

## 獨立證據與限制

- A manifest 指向的 9 個來源／比較產物，逐檔 SHA-256 讀回一致；既有 fold-004 v7 的 12 組 equity 路徑以 Decimal 獨立重算淨報酬與最大回撤一致。這證明讀回及計算一致，不能推論 ML alpha 或正式 OOS 合格；沒有讀取 fold-005 樣本。
- A 當輪 parent 診斷為 3,347,662 rows、全現金 teacher；Snapshot 舊 3,353,096 rows 屬另一個 parent，不混用分母。真實因果成交帳本、歷史 Rule Champion、PIT 產業成分仍缺，正式輸入維持 0/3。
- D 槽本輪先前觀測約 310.74 GiB 可用；這是時間點觀測。既有 reserve／持久新增／暫存峰值預檢及執行中 guard 持續有效，不能用一次檢查保證其他程序之後不佔空間。
- requirements constraints 是已觀測的直接依賴版本，不是全套 transitive lock；未在全新環境安裝驗證。UI 截圖為 offscreen、DPR 1.0；窄版仍有長文字截斷的後續改善空間。

原始 QA、回滾副本、Git bundle 與截圖位於 ignored 的 `output/qa/luna_integration_20260908/`；本文件保存可提交的結論，未將模型、資料庫、快取或 raw output 納入 Git。

## Git 收尾

- `query_current_repo_context` 的獨有 commit 數為 0；最後再次確認乾淨、無 untracked／ignored 檔後，已移除舊 worktree 與該分支。完整 refs／Git bundle 已保存並驗證。
- A／B 與前次整併的未提交內容已完整提交為 `bfa6a0f0a696d26df480b18c58e8e84cffac2bf0`（82 檔、2,766 行新增／1,704 行刪除，包含新增文件與搬移支援模組）；C 原提交保留在其歷史中。main／dev 已以 fast-forward 同步，`codex/luna-c-uiux` 已用 `git branch -d` 移除。
- `git push --atomic origin main dev` 成功；獨立 `git ls-remote --heads origin` 讀回只有 main／dev，兩者均為上述整合提交。沒有 force push、reset 或清除其他 refs／tags。
- 本機 `git branch` 只有 main／dev，`git worktree list` 只有 `C:/Projects/PythonProjects/technical_analysis` 主 checkout，停留在 dev；整合推送後 `git status --short` 為空。本紀錄的後續純文件提交沿用同一程式驗證基線，並同步推送兩個保留分支。
