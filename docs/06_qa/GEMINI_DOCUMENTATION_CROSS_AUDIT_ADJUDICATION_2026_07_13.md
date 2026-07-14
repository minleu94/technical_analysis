# Gemini Repository 文件交叉稽核裁決

> 裁決日期：2026-07-13
>
> 稽核基線：`dev` / `7c173b0`（修補前），並追溯 `4f72766`、`4b7169e`、`873fb61` 與 `74c2eac`
>
> 裁決權威：Scoped SSOT、Git history、source code、測試與 QA artifacts；Gemini 報告只作待驗證輸入
>
> 安全結論：未改 External Gate revision；`formal_oos_allowed=false`；`production_blend_alpha_bp=0`；未重做 A～G

## 1. 計數口徑

- Gemini 有 11 個 A～K 稽核項目，以及 4 個 P0～P3 優先項目，共 15 個列項。
- P0 是 F 的同一主張，因此去重後為 14 個 assertions。
- Gemini 明確列為「問題／後續裁決」的是 4 項 P0～P3；逐項核實後，0 項以原結論成立。
- 本次獨立稽核另發現 6 組可執行文件缺口，已全部修正；另外建立 3 份使用者指定的執行交付物。

## 2. A～K 裁決

| ID | 裁決 | Repository 證據與處置 |
|---|---|---|
| A | `confirmed` | Snapshot、Product／6M Roadmap 的 scoped authority 大致一致；但 Gemini 未發現 Roadmap Hub 與非權威導航仍留有 weekly `0/3` 的舊目前值。本次只把「目前值」校正為已有 QA 證據的 `1/3 waiting_for_time`，未改 Gate 狀態。 |
| B | `scoped-not-conflict` | 6M 是六個月工程順序，Target Architecture 是目標領域邊界；差異屬 scope。`target_system_architecture.md` 並未要求 Event-driven PoC，因此不能由此推導 P2 stub。 |
| C | `confirmed` | Snapshot 與 Version Roadmap 目前段落都維持 ML shadow-only、alpha 0、formal OOS blocked。版本文件中的 dated update log 是歷史紀錄，不用來覆寫 current truth。 |
| D | `historical-only` | Legacy Carryover 只管理舊工作移交；目前 UI 入口與 active module 由 current architecture、Manual 與 source code決定。Gemini 對 legacy 的描述可作歷史摘要，不是目前完成狀態來源。 |
| E | `false positive` | 「無嚴重衝突」過度樂觀：Index 仍把已核准的 V2.1 寫成 awaiting、核心 reading order 不以 Snapshot 開始，且 Navigation／current architecture 有舊 UI 入口。本次以最小修補消除。 |
| F | `false positive` | `4b7169e` 同一提交明確寫成 A～F committed handoff；Snapshot、Roadmap Hub、`SystemExecutionBlueprintAdapter` 與 closeout 都把 G 定義為跨流 composition／verifier。將 Manual 改成「A～G committed handoff」會製造錯誤。 |
| G | `confirmed` | Snapshot、Manual、ML runbooks 與 source contract 均為 `historical_ml_shadow=continue_shadow`；不影響正式 ranking、Score 或 downstream action。 |
| H | `confirmed` | `formal_oos_allowed=false`、forward evidence pending、production blend alpha 0 在 SSOT、Manual、source verifier 與 Master Plan 一致。 |
| I | `confirmed` | source acceptance 與 production automation 均 pending；scheduler／broker／auto action 禁止條款一致。 |
| J | `confirmed` | Manual 對目前 8 個工作區、Daily Decision 唯一實例與 Workbench 導覽契約正確；本次只校正 Gate 進度引用，不修改 UI 行為。 |
| K | `confirmed` | Git exclusions、shared context 與精確 stage 規則存在且互相一致；本任務不提交 ignored state、output 或 raw QA。 |

## 3. P0～P3 裁決

| Priority | 裁決 | 結論 |
|---|---|---|
| P0 DOC-SYNC | `false positive` | 保留 Manual 的「A～F committed handoff」。G 是 verifier／integration owner，不是第七個同質 handoff。 |
| P1 QA-GATE | `false positive` | Register 已初始化為外部待辦矩陣；registry repository 與 CLI 是 append-only。`tests/test_engineering_gate_registry.py` + CLI tests 實跑 `7 passed`，duplicate revision 會拒絕且 history 保留。無需改程式或 Gate state。 |
| P2 ARCH-PREP | `false positive` | Current／Target 沒有要求 Event-driven PoC，且該 stub 不影響現有導航、Gate 或執行。依使用者規則不加入 6M Roadmap。 |
| P3 DOC-OPTIMIZATION | `needs-human-decision` | 定期排程屬 owner、頻率與自動化政策決策；不是目前文件缺陷。本次不新增無價值的月底文字或 automation。 |

## 4. 獨立發現並修正的 6 組問題

1. `DOCUMENTATION_INDEX.md` 的 reading order 未以 Snapshot/current truth 開始。
2. Index 對 V2.1 仍寫 `awaiting_release_owner_confirmation`，但 `74c2eac` 與 formal closeout artifact 已是 `formal_closeout_complete`。
3. `PROJECT_NAVIGATION.md` 與 current architecture 仍把 Daily Decision 說成頂層入口，未反映唯一實例位於「市場探索 > 市場總覽」。
4. Roadmap Hub、current architecture、Manual 與 Navigation 的 current weekly history 仍有 `0/3`；既有 Week 1 artifact 與 Snapshot 已證明目前為 `1/3 waiting_for_time`。
5. External Evidence Master Plan 要求執行 HEAD 等於 A～G 工程錨點 `4f72766`，但 Plan 本身已在其後提交；照原文會讓 Terra 永遠 preflight 失敗。現改為保留 immutable engineering anchor，並在授權當下動態封存 clean、同步且為其後代的 execution baseline。
6. External Evidence design／Master Plan／External Register 缺少對 OOS Audit plan、Preregistration template 與 Terra handoff 的單一執行導航；已建立 companion 並互相連結，不改任何 Gate。

## 5. 必須由人類決定

- 2025 OOS exposure declaration 的簽署者、access evidence 完整性與 influence dimensions；缺任一項維持 `indeterminate`。
- Experiment V1 的 `minimum_material_effect_bp` 與 `downside_noninferiority_margin_bp`；Agent 不得代填。
- P0-13 與 Broker 的 license／declared-use decisions；工程成功不等於 accepted。
- paper policy、promotion／release、production scheduler 與 formal adapter proposal 的 owner decision。
- 是否建立週期性 Snapshot review automation；本次沒有自行建立。

## 6. 本次未改變的真相

- Snapshot=current；Product Roadmap=產品方向；6M Roadmap=六個月工程；current／target architecture 分離；Vision=北極星；Manual=操作；archive=歷史。
- A～G engineering integration 只維持 historical engineering verified，不升級 formal product closeout。
- External Validation Register 的每一個 item 狀態保持原樣。
- `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、forward/source/automation/promotion pending。
