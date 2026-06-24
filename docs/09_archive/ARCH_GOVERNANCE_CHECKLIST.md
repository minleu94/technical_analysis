# Architecture Governance Checklist
> 用途：在新增模組/功能前完成自檢，避免跨層依賴與 Legacy 擴散。

## A) 新增模組 / 新增檔案
- [ ] 已定義唯一責任（One Responsibility）一句話  
- [ ] 模組歸屬層級清楚（UI / Service / Domain / Analysis / Backtest / Data / Tool / Legacy）  
- [ ] 依賴方向符合規範（UI → Service → Domain/Analysis/Backtest/Data）  
- [ ] 未引入反向依賴（Domain 依賴 UI/Service 等）  
- [ ] 未將業務邏輯放入 UI 或 scripts  
- [ ] 若為 Legacy/Experimental，已明確標示「僅維持、不擴張」  

**常見違規情境（必檢）**  
- [ ] UI 直接 import decision_module / analysis_module / backtest_module  
- [ ] Service 接收 UI 元件/Qt 物件  
- [ ] Legacy 模組被新功能引用  

---

## B) 新增 UI 功能
- [ ] UI 僅負責收參數、呼叫 Service、顯示 DTO  
- [ ] UI 未直接讀寫資料檔（CSV/DB）  
- [ ] UI 未直接計算指標 / 回測 / 分析  
- [ ] 新功能入口從 `app_module` 取得服務  
- [ ] 如需共享狀態，放在 Service 或 UI 共享層，而非 Domain  

**常見違規情境（必檢）**  
- [ ] UI 直接調用 decision_module  
- [ ] UI 在 View 層寫推薦理由、打分、回測邏輯  

---

## C) 新增 Service
- [ ] Service 只有 orchestrate，不含 UI/視覺邏輯  
- [ ] Service 依賴方向正確（可依賴 Domain/Analysis/Backtest/Data）  
- [ ] Service 不依賴 UI 物件（Qt/Tk）  
- [ ] Service 輸入/輸出使用 DTO 或純資料結構  
- [ ] 新 Service 有明確的使用場景（由 UI / scripts 呼叫）  

**常見違規情境（必檢）**  
- [ ] Service 引用 UI 模組  
- [ ] Service 內操作 UI state  

---

## D) 新增 Script / QA 工具
- [ ] Script 只調用 app_module（不碰 UI）  
- [ ] Script 不直接調用 Domain 作為入口  
- [ ] Script 目的明確（更新/修復/驗證/QA）  
- [ ] 若是一次性/實驗性，標示為非正式入口  

**常見違規情境（必檢）**  
- [ ] Script 直接操作 UI  
- [ ] Script 混入業務邏輯  
