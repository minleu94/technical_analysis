# LUNA B：架構、冗餘與測試治理 handoff

> 整合補註（2026-09-08）：以下保留本線交付當時的數字與 Git 狀態；整合修補、全域測試及 main／dev 收尾以 [三線整合驗收](LUNA_INTEGRATION_CLOSEOUT_2026_09_08.md) 為準。

> 文件標籤：2026-09-07；最後驗證：2026-09-08。這份 handoff 是 B 線交付摘要，不是新的 Snapshot、Roadmap 或產品狀態來源。

## 1. 結論與範圍

B 線已完成可獨立驗收的架構／測試治理包：

- 建立可重跑的 repo map、測試 inventory audit 與文件漂移檢查；所有新 JSON、清冊 sidecar、暫存與 rollback backup 均在 `output/luna_B/`，且不納入 Git。
- 將可證明相同的欄位 resolver 收斂為單一 primitive，保留既有三個 facade 名稱與匯入契約；SignalCombiner 的共同分析流程沿用既有 shared support，可靠性與 backtest 政策仍分開。
- 將 OOC／ML 共用 test builder 與 fixture 移到專用 support module；容量探針只在 synthetic／`tmp_path` 測試範圍 patch，沒有改 production reserve，也沒有跳過真實容量測試。
- 建立 runtime、development／QA 與 Python 3.11 Windows direct constraints 的需求檔關係；沒有在共用 venv 安裝或升級套件。
- 補上 Fubon CLI 的隔離 `DATA_ROOT` 測試、可重現 OHLC fixture、inventory audit 的正／負小型 fixture，以及 type／parse 修復。

本線沒有修改交易帳本、financial core、正式資料、ML fit／promotion、UI 產品服務或 `APPLICATION_MANUAL.md`。C 已另行完成 UI／Manual 交付；A 維持資料／ML fail-closed，詳見第 9 節。

目前 checkout 的 HEAD 是 `7868a517`（C 的 `ui: polish Luna C research workbench flows` 提交），B 沒有建立 commit、沒有 push、沒有 reset／checkout 或整樹清理。這個事實很重要：B 的 uncommitted 檔案與並行工作樹仍應先由 integration owner 依檔案所有權檢查，再決定如何提交。

## 2. Repo map 與 before／after 數量

### 2.1 可核對的基線與目前快照

`docs/06_qa/PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md` 的 baseline 是 `71500ef6`，當時工作樹起點為 clean；以下把那份 baseline 與包含本 handoff 的最終可重跑快照並列。兩者的分類定義已標明，不把 untracked 交付檔假裝成 tracked baseline。

| 維度 | 整併 baseline（tracked，`71500ef6`） | B 完成後快照（visible working tree） | 證據／定義 |
|---|---:|---:|---|
| Git tracked | 2,268 | 2,269 | baseline `inventory_before.json`；final `repo_map.json` |
| Git untracked | 未在 baseline map 分離記錄 | 18 | `git ls-files --others --exclude-standard`；包含本 handoff |
| Git ignored | 未在 baseline map 分離記錄 | 62,702 | `git ls-files --others --ignored --exclude-standard`；包含既有 cache／venv |
| code | 681 | 684 | `_path_kind`：非 `tests/`、`scripts/`、`docs/` 的程式檔 |
| docs | 452 | 464 | `_path_kind`：`docs/` 或 `.md/.rst/.txt`；包含本 handoff |
| tests | 775 | 778 | `tests/` 路徑 |
| scripts | 333 | 334 | `scripts/` 路徑 |
| other | 27 | 27 | 其餘 visible path |
| dirty status lines | 0（baseline review） | 67 | final `git status --short --untracked-files=all`；含 A／C 與既有並行變更 |

Final repo map：[`output/luna_B/repo_map.json`](../../output/luna_B/repo_map.json)。tracked、untracked、ignored 的完整／sidecar 清單在同一個 `output/luna_B/` 目錄；這些是機器證據，不是永久文件清冊。

### 2.2 測試清冊與收集數量

| 維度 | 整併前 | 整併後、B support 尚未新增前 | B 完成快照（C commit 前） | 目前含 C commit |
|---|---:|---:|---:|---:|
| filesystem test Python files | 748 | 740 | 743 | 743 |
| inventory entries | 679 | 740 | 743 | 743 |
| collected test cases | 4,639 | 4,645 | 4,651 | 4,654 |
| support files | 未分離記錄 | 既有 `ml_teacher_fixture` | 4 | 4 |
| default non-collected files | 未分離記錄 | 0 drift | 23 | 23 |

前兩欄來自整併 evidence；B 完成欄由 B 的 `audit_test_inventory.py` 與 `pytest --collect-only` 重新計算。C commit 後再 collect 為 4,654，增加的 3 個測項來自 C 已提交的既有 UI test 檔，並非 B inventory drift；B 新增的三個 support／QA helper 檔已登錄，沒有用手改數字消除 drift。

### 2.3 B 批次的精確行數（不含本 handoff）

這些數字以每批開始前保存的 `output/luna_B/backup/*-before/` 與目前檔案逐檔比較；排除 C／A 的產品路徑、既有 SignalCombiner mixin 未提交變更、以及 B 開始前已存在的 legacy deletion。新增的 output JSON／manifest 不列入 source LOC。

| 批次 | 可核對內容 | 新增 | 刪除 | 淨變化 |
|---|---|---:|---:|---:|
| B1 | repo-map scanner 394 行；核心導航／inventory 逐檔增補 | 401 | 2 | +399 |
| B2 | tracked 測試／fixture 調整；另新增 OOC support 239、ML support 216、support regression 23 行 | 559 | 395 | +164 |
| B3 | 25 行 canonical resolver、三個 facade、9 行 parity test | 44 | 27 | +17 |
| B4 | runtime/dev/constraints 75 行、environment guide 56 行、requirements／index 更新 | 135 | 23 | +112 |
| B5 | inventory audit、正／負 fixture、分類摘要 refresh | 207 | 5 | +202 |
| **B 合計** | **B-owned batch，暫不含本 handoff** | **1,346** | **452** | **+894** |

B2 的主要搬移可直接核對：`tests/test_portfolio_ml_out_of_core_pipeline.py` 移出本地 builder／fixture 160 行、`tests/test_ml_allocation_training_service.py` 移出共用 helper 194 行；這些刪除是移動到 support module，不是刪除測試 oracle。整併 baseline 中另有 7 份 legacy diagnostic script 加 1 份 README 的 deletion；那批變更在 B 開始前已存在，B 只在 repo map 與 healthcheck 中核對其狀態，沒有把它重算成 B 的刪除量。

## 3. 冗餘判斷、邊界與引用證據

repo map 以 SHA／AST、callers、tests、docs、dynamic import marker 與 path presence 產生候選資料；沒有用「`rg` 找不到」單獨宣稱 unused。Final map 分類數為：package markers 33、compatibility facades 5、manual scripts 21、formal tests 23、QA evidence 140、dynamic import hits 30；既有 `graphify-out/graph.json` 存在且未重建。

| 候選 | 判定 | 處置與理由 |
|---|---|---|
| SignalCombiner shared analysis flow | merge／沿用 | `analysis_module/signal_combiner_support.py` 提供共同組合／volume／合成流程；兩個入口仍保留，保留既有測試與 facade。 |
| analysis column resolver | merge | `analysis_module/column_support.py` 的 lookup order 成為 canonical；`pattern_column_support.py`、`technical_column_support.py`、`ml_column_support.py` 只保留 typed facade，沒有破壞公開名稱。 |
| SignalCombiner reliability／backtest | keep | `_evaluate_signal_reliability`、`backtest_strategy` 含不同同日成交、可靠性與輸出政策；沒有足夠 oracle 證明可默默互換。 |
| legacy manual diagnostics | remove（已存在於 baseline 變更） | 固定正式路徑／失效 runner；只核對 7 scripts + README 的現有 deletion，不擴大清理其他歷史 manual。 |
| `technical_indicators.clean_price_series` nested duplicates | defer | AST 顯示同檔重複，但隸屬不同指標流程；先補 missing／NaN parity oracle 才能考慮共用。 |

B3 的量測結果：分析 AST exact duplicate groups 由 6 組（含相同 `__init__`）降為 5 組；排除 `__init__` 則由 5 組降為 4 組；相同函式定義數由 14 降為 12。沒有改變訊號日期、策略、交易、回測、金融計算或 look-ahead policy。

## 4. B2 測試隔離與容量政策

### 4.1 Support module 與 fixture

- `tests/fixtures/portfolio_ml_ooc_support.py`：OOC 的 synthetic source、bounded builder、isolated capacity fixture。
- `tests/fixtures/ml_allocation_training_support.py`：ML inference／CLI 需要的小型 training fixture；不再從完整 training test module import。
- `tests/test_portfolio_ml_test_support.py`：確認 patch 生效且 fixture 結束後 `storage_capacity.filesystem_usage` 恢復原 callable。
- `tests/conftest.py` 的 `pytest_plugins` 只指向上面兩個專用 support module；沒有再把完整測試檔當 plugin 載入。sample market／stock／index fixture 改成 deterministic 且滿足 OHLC 關係，沒有改 production reserve。
- `tests/test_inspect_fubon_shadow_decision_cli.py` 使用明確 `tmp_path` `DATA_ROOT`；另以 configured formal root 驗證 `validate_output_root` 仍拒絕 output 落在 formal data root 內。

### 4.2 200 GiB proof

先保留了修復前 RED evidence：OOC pipeline 在中央容量政策擋下時為 `12 passed、10 errors、1 failed`；代表性 preflight 要求 `216,895,848,448` bytes，而當時 C 槽只有約 `189,196,177,408` bytes（約 176.22 GiB），所以不能把小型 fixture 當作真實足夠空間。

B 的 synthetic fixture 只在明確測試 scope 中 patch `filesystem_usage`，使用 1,024 GiB synthetic total／512 GiB synthetic free 的回傳值，並由 restoration test 證明離開 scope 後恢復。production 的中央 200 GiB reserve、persistent／temp default 1 GiB、跨磁碟／並行承諾／watchdog／no-write 規則均未改。真實容量測試仍執行：`25 passed、1 skipped`。

## 5. B3 分析合併與 parity

新增 canonical resolver 的查找順序與原三份 resolver 一致；三個舊入口仍可匯入，parity test 驗證 identity／結果一致。SignalCombiner 的共同流程沿用既有 shared support；可靠性與 backtest 的差異刻意保留，避免用一個研究 helper 覆蓋另一個正式／歷史 oracle。這批沒有新增金融核心的裸 `float`，也沒有新增策略／推薦／回測邏輯，因此不引入新的 look-ahead surface。

## 6. B4 依賴與環境

需求檔關係：`requirements-runtime.txt` 是 direct runtime；`requirements-dev.txt` 是 runtime + `pytest`／`pytest-qt`／`mypy`；`requirements.txt` 保留向後相容 all-in-one 入口；`requirements-py311-windows.constraints.txt` 是現有環境驗證過的 direct constraints，不是假稱完整 transitive lock。

已驗證環境：Windows x64、Python `3.11.9`、`.venv\Scripts\python.exe`；pandas `2.3.3`、numpy `2.3.5`、scikit-learn `1.8.0`、TA-Lib `0.6.8`、fallback `ta 0.5.25`、PySide6 `6.10.1`、pyarrow `22.0.0`、pytest `9.0.2`、mypy `2.1.0`。本 venv 缺 `pytest-qt`，所以 Qt plugin 不是 B 的已驗證安裝結果；C 的 UI handoff 有其自身 offscreen／healthcheck evidence。

重建計畫與平台邊界詳見 [`LUNA_B_ENVIRONMENT_2026_09_07.md`](../07_guides/LUNA_B_ENVIRONMENT_2026_09_07.md)。B 沒有下載套件、沒有共用 venv install／upgrade，也沒有把 private `fubon_neo` wheel 或 Codex tooling 放入正式 runtime manifest。

## 7. QA 命令、exit code 與結果

以下是本線實際執行的命令。`-o addopts=` 用來排除 repository 預設外掛選項的干擾；`.pytest_cache` 的 permission warning 不影響下列 exit code。

| 類型 | 命令 | 結果 |
|---|---|---|
| 修復前 RED | `pytest tests/test_portfolio_ml_out_of_core_pipeline.py -q -o addopts=` | exit 1；12 passed、10 errors、1 failed（capacity preflight） |
| B focused integration | B audit／inventory、fixture、Fubon、四個 analysis parity、OOC、OOC related、ML support／adapter／CLI 共 18 個 test files | exit 0；125 passed、2 warnings、163.04 秒 |
| 真實容量 policy | `pytest tests/test_ml_storage_capacity.py -q -o addopts=` | exit 0；25 passed、1 skipped、1 warning、12.36 秒 |
| inventory audit | `python scripts/audit_test_inventory.py --output-json output/luna_B/test_inventory_audit.json --skip-pytest-collection` | exit 0；filesystem／inventory 743／743；missing、stale、collection errors、count drift、link errors、duplicate current sections、formal refs、blockers 全為 0／空 |
| repo map | `python scripts/audit_luna_b_repo_map.py --output-json output/luna_B/repo_map.json` | exit 0；final counts 見第 2 節 |
| collection | `python -m pytest --collect-only -q -o addopts=` | exit 0；B snapshot 4,651 collected；C commit 後目前 working tree 4,654 collected |
| runtime import | `python -c "import sys, pandas, numpy, talib, ta, PySide6, pyarrow, joblib, psutil, requests; print(sys.version); print('runtime imports OK')"` | exit 0 |
| dependency consistency | `python -m pip check` | exit 0；No broken requirements found |
| quant guard | `python scripts/quant_guard_linter.py` | exit 0；float boundary／look-ahead checks pass |
| B changed Python parse | `PYTHONPYCACHEPREFIX=output/luna_B/pycache python -m py_compile ...`（B 變更 Python 清單） | exit 0；初次使用 repository cache 曾因 `.pytest_cache` permission exit 1，改用隔離 cache 後通過 |
| B mypy | `python -m mypy --explicit-package-bases --cache-dir output/luna_B/mypy_all_cache ...`（B 變更／support／audit Python 清單） | exit 0；28 source files，Success: no issues found |
| full pytest，隔離 DATA／OUTPUT／TEMP | `DATA_ROOT=output/luna_B/runtime_data OUTPUT_ROOT=output/luna_B/runtime_output TEMP=output/luna_B/temp TMP=output/luna_B/temp python -m pytest -q -o addopts=` | exit 1；4,561 passed、65 failed、25 errors、3 skipped、29 warnings，487.58 秒 |

完整 suite 的 log 在 [`output/luna_B/pytest_full.log`](../../output/luna_B/pytest_full.log)。該 suite 是在同一組 C UI dirty changes 已存在、但 C commit 尚未成為 HEAD 的 shared working tree 中執行；C 的 3 個新增測項已另外以 collection 驗證，未把它們回算成 B focused 結果。失敗不是被 B focused regression 證明：同一 B OOC／ML／capacity 集合在未覆寫 `TEMP` 的正常 pytest 暫存策略下已通過；full suite 的代表性錯誤包含 Windows `os.replace` file lock、其他 A-owned mature／replay 路徑仍遵守 200 GiB reserve 而被隔離 C 槽擋下，以及正式資料／外部環境 fixture 假設。沒有用 xfail、刪 assertion 或放寬 production guard 來換綠燈。完整 suite 仍應標為 fail-closed，不能宣稱整 repo passed。

Inventory audit 的 JSON 目前有 27 筆既有 nonportable absolute Markdown link warning（主要在 `PROJECT_NAVIGATION.md` 與歷史 `DOCUMENTATION_INDEX.md`）；它們不是 missing link blocker。B 將其保留為 residual debt，避免在共享導航文件中做與本線無關的大範圍重寫。

## 8. 已修復、保留與待拆 seam

### 已修復

- 完整 test module plugin coupling、跨測試 import builder、全域容量 mock 與固定 D formal root 假設。
- deterministic OHLC fixture、inventory audit 的 local link／duplicate current／formal entry checks。
- duplicated column resolver 的語意歧義；public facade 與 parity oracle 保留。
- requirements 的 direct／dev／constraints 邊界與 Windows／TA-Lib／PySide6 的未驗證狀態揭露。

### 刻意保留

- SignalCombiner reliability、backtest、同日成交與輸出政策的雙入口 oracle。
- 真實容量 policy tests 與 production 200 GiB reserve。
- `tests/manual`、`tests/scripts` 的手動／高風險資料寫入邊界；不因檔名相似就全部收進預設 pytest。
- A 的正式 teacher gate、PIT／formal data readiness 與 C 的 UI／Manual 契約。

### 下一個可拆 seam

1. `analysis_module/technical_analysis/technical_indicators.py` 的兩個 nested `clean_price_series`：先建立 missing／NaN／empty-series oracle，再抽出 typed policy interface；風險是不同指標對清理順序的依賴。
2. OOC／ML product service 的大檔拆分：以 `capacity preflight → source eligibility → artifact materialization → fit／replay` 四個 seam 先定 protocol，再以 existing freeze／storage／causal tests 作 oracle；B 本輪只拆 test support，沒有碰 production service。
3. 共享導航文件的 absolute link：先建立相對連結遷移表，再逐檔修復並重跑 link audit；不要在 A／C 仍有 dirty path 時整份替換。

## 9. A／C 整合狀態與可執行步驟

已閱讀：[`LUNA_A_HANDOFF_2026_09_07.md`](LUNA_A_HANDOFF_2026_09_07.md) 與 [`LUNA_C_HANDOFF_2026_09_07.md`](LUNA_C_HANDOFF_2026_09_07.md)。

- A：`incomplete / fail-closed`；沒有正式資料寫入、fit、promotion 或 broker 啟用。仍缺 formal causal non-cash ledger、同日 Rule Champion history、PIT sector membership 與符合 reserve 的新 OOC fit。
- C：UI／UX、Workbench source projection、Manual、offscreen 兩 viewport 與 mandatory Update QA 已由 C handoff 報告；其程式與 handoff 已在目前 HEAD 的 C commit 中。C 也明示 native Windows DPI／字型、真實 populated result 與 live source 不在其隔離驗收範圍。
- B：已完成自己的 inventory／architecture／test／environment 交付；沒有把 A 的 data/ML 或 C 的 UI 行為寫入 B 的假設。

整合 owner 下一步應依序執行：

1. 先保存現況 `git status --short --untracked-files=all`，確認 A／B／C 的 ownership；不可對整個 checkout 使用 `reset --hard`、`checkout --` 或 broad clean。
2. 以 `qa/full_app_healthcheck/test_inventory.py`、`tests/conftest.py`、`PROJECT_INVENTORY.md`、`PROJECT_NAVIGATION.md`、`docs/00_core/DOCUMENTATION_INDEX.md` 為共享檔逐段合併：保留三線新增條目與 B 的重新計算，不能直接選整份 ours／theirs。
3. 重新跑 `scripts/audit_test_inventory.py` 與 `scripts/audit_luna_b_repo_map.py`，確認 C handoff 的 UI 測試條目與 A 的 ML／data 條目都在聯集 inventory；27 筆 absolute-link warning 要另立修復 task，不可吞掉。
4. 依 C handoff 再驗證 `tests/test_ui_qt_update_view_workbench.py`、`scripts/qa_validate_update_tab.py`、C focused UI／workflow、full app smoke；依 A handoff 只在 source gate 與容量允許時執行 data／ML evidence，不能因 B focused pass 解除 formal block。
5. 最後在獨立 `DATA_ROOT`／`OUTPUT_ROOT`／`TEMP`／`TMP` 下重新跑 full pytest；若仍有 Windows file lock 或 reserve failure，保留新的 log、分類與 exit code，不改 B fixture 去掩蓋。

## 10. Rollback

每批變更在動手前已保存精確 backup；可用下表做檔案級 rollback。執行前必須再次 `git status`，只對仍與該 backup 對應、且沒有被 A／C 後續改寫的路徑操作。

| 批次 | backup | 回復範圍 |
|---|---|---|
| B1 | `output/luna_B/backup/b1-before/` | `PROJECT_INVENTORY.md`、`PROJECT_NAVIGATION.md`；repo-map scanner 是新增檔，移除前先確認沒有被 integration owner 採用 |
| B2 | `output/luna_B/backup/b2-before/`、`b2-second-before/`、`b2-third-before/` | `tests/conftest.py`、OOC／ML／adapter／CLI／fixture／inventory 測試；新增 `tests/fixtures/*support.py` 與 support regression test 逐檔處理 |
| B3 | `output/luna_B/backup/b3-before/` | 三個 column facade；canonical `analysis_module/column_support.py` 與 parity test 需一併確認 import contract |
| B4 | `output/luna_B/backup/b4-before/` | `requirements.txt`、`DOCUMENTATION_INDEX.md`；新 runtime/dev/constraints 與 environment guide 逐檔移除或保留，不能 broad clean |
| B5 | `output/luna_B/backup/b5-before/` | `scripts/audit_test_inventory.py`、其測試與分類摘要；先確認 handoff／C 新文件的連結不被回復動作打斷 |

`output/luna_B/` 下的 JSON、log、mypy／pycache、backup 是可重新生成的 ignored QA output；可在確認無人需要後清除該線 output，但不得刪除 `D:/Min/Python/Project/FA_Data` 或其他 agent 的 `output/luna_A`／`output/luna_C`。

**B handoff 判定：** B 範圍已交付、focused evidence 通過；完整 suite 維持 fail-closed，等待 integration owner 依 A／C handoff 完成共享清冊聯集與最後 UI／full-suite 重驗證。
