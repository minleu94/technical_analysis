# Architecture Violation Response Policy

## A) 可暫時容忍的情況
- 既有跨層依賴，且無資源立即修正  
- Legacy 模組仍被舊流程使用，但已明確標示  
- UI 主入口中既存共享初始化（不擴散）  

**條件**  
- 必須標記為「例外但不得擴散」  
- 必須記錄到 Architecture Audit Record  

---

## B) 必須立即阻止的情況
- 新增 UI → Domain 直接依賴  
- Service 引入 UI 物件  
- 新功能引用 Legacy 模組  
- 新增反向依賴（Domain 依賴 Service/UI）  

---

## C) 記錄規則（Architecture Audit Record）
每次違規必須新增一筆記錄，至少包含：  
- 違規內容  
- 觸發場景  
- 風險描述  
- 是否為臨時例外  
- 未來處理建議（Phase C）  

---

## D) 例外標示規範
- 例外標示必須明確列出：  
  - 理由  
  - 範圍  
  - 期限或清理條件  
- 例外不得作為新功能參考  
