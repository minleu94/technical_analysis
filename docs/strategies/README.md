# 策略說明文件目錄

> **最後整理**：2026-07-06
> **定位**：本目錄保存給使用者與開發者閱讀的策略說明。策略程式碼、版本註冊與執行邏輯不放在這裡。

## 文件列表

| 文件 | 用途 |
|---|---|
| `momentum_aggressive_v1.md` | 暴衝策略的目的、適用情境與風險說明。 |
| `stable_conservative_v1.md` | 穩健策略的目的、適用情境與風險說明。 |

## 維護規則

- 新增策略說明時，需同步更新 `../00_core/DOCUMENTATION_INDEX.md`。
- 策略實作與 registry 狀態以 `app_module/strategy_registry.py`、`app_module/strategies/` 與 `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md` 為準。
- 策略說明不得宣稱投資績效或保證收益；若提及驗證結果，必須連到對應 QA 或 Research Run evidence。
