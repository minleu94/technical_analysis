# Month 2 Parameter & Run Storage Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成指標參數、推薦權重、統一 Research Run Registry、Cross-run Comparison 與 Registry-based Promote Gate，使每一次研究 run 可保存、可比較、可重播、可追溯。

**Architecture:** Month 2 拆為 M2-A、M2-B、M2-C 三個不可平行開工的增量。M2-A 在 decision/analysis 邊界建立 fail-closed 參數與整數 bp 權重契約；M2-B 由 `ResearchRunService` 作為唯一保存 owner，協調 SQLite metadata 與 Parquet 詳細資料；M2-C 在既有 Research Lab 增加比較子頁，並以補償交易整合 JSON Strategy Version 與 Registry promotion。

**Tech Stack:** Python 3、Decimal、pandas、TA-Lib、SQLite、Parquet、PySide6、pytest、mypy、現有 DTO / Repository / StrategyVersionService。

---

## 0. 計畫狀態與執行規則

### 目前狀態（2026-06-14）

- [x] Month 2 Roadmap、Legacy Carryover 與 Research Run Registry schema 規格已建立。
- [x] M2-A 第一版程式與單元測試已產出。
- [x] M2-A Blocker 修復版 2 已產出：Decimal 評分、最大餘額法、治理例外傳播、跨欄位驗證與 Prefix-Invariance 測試均已接入。
- [x] M2-A 契約層級阻斷問題已修復，完整驗證與文件 Coverage 已通過。
- [x] M2-A Gate 已由使用者於 2026-06-14 核准，允許開始 M2-B。
- [x] M2-B 開始。
- [ ] M2-B Gate 通過並取得使用者核准。
- [ ] M2-C 開始。
- [ ] Month 2 最終 Gate 通過。

### M2-A 第一輪阻斷修復狀態（2026-06-14 第二輪驗收）

已驗證完成：

1. `ScoringEngine.calculate_total_score()` 的 `TotalScore` / `FinalScore` 已改用 `Decimal`，不再使用 `/ 10000.0`。
2. Regime 權重已改用 Decimal 倍率與 Largest Remainder Method，採 floor、餘額降序及 key 字母順序穩定分配。
3. `generate_recommendations()` 已有非法 RSI `timeperiod=1` 的端到端測試，治理例外可向外傳播。
4. Registry 已加入 MACD `fastperiod < slowperiod`、SAR `acceleration <= maximum`、MA windows 不重複與 bool 元素拒絕。
5. Recommendation Weight Contract 已拒絕 bool 權重。
6. Prefix-Invariance 已逐日比對 RSI、SlowK、SlowD 中間指標。
7. `config_schema_version` 已收緊為只接受非 bool、非負的原生 `int`。
8. MA windows 已逐元素拒絕 bool、float 與 string，不再執行 `int(x)` 隱式轉換。
9. LegacyWeightMigrationAdapter 已要求精確三鍵集合，不再補缺漏 key 或忽略額外 key。
10. disabled 測試已改走 `configure_technical_indicators()` 正式路徑，逐一覆蓋 RSI、MACD、KD、Bollinger、SAR、ATR、TSF、ADX、MA；Bollinger / SAR 停用時不再產生空欄位。
11. `TotalScore` / `FinalScore` 已依既有 score basis-point 契約，以 `Decimal('0.01')` 與 `ROUND_HALF_UP` 統一量化。
12. `StrategyConfigurator` 已在任何指標 section 執行前驗證 `config_schema_version`，即使全部指標停用也不能繞過版本 Fail-Closed。

目前程式契約阻斷已清除。M2-A 仍需完成完整驗證、文件 Coverage、Review Gate 與使用者核准，才可標示 Gate 通過並開始 M2-B。

### 最終驗證證據（2026-06-14）

```text
focused pytest: 36 passed in 1.12s
full pytest: 405 passed, 7 warnings in 15.92s
mypy: Success: no issues found in 148 source files
financial float boundary scanner: exit 0
financial float boundary tests: 37 passed in 0.10s
changed-files py_compile: exit 0
```

結論：M2-A 程式、測試、數值防線、Look-ahead Gate、文件 Coverage 與 review 已完成；目前只等待使用者明確核准，核准後才能開始 M2-B。

### 強制順序

1. M2-A Gate 未通過，不得開始 M2-B。
2. M2-B Gate 未通過，不得開始 M2-C。
3. 每個增量先寫失敗測試，再做最小實作。
4. 每個增量完成後先 review，再由使用者核准是否進入下一增量。
5. 不重建、不刪除、不修改正式 raw data。
6. 金融核心計算不得新增裸 `float`。
7. 策略、回測、推薦與 benchmark 變更必須做 Look-ahead 自查。
8. 不覆寫目前 working tree 內使用者或其他 agent 的未提交變更。

## 1. Scope

### Scope In

- Indicator Parameter Registry 與版本化 legacy defaults。
- Recommendation Weight Contract 與 legacy float migration adapter。
- 動態指標參數傳遞與 enabled/disabled 子指標控制。
- ScoringEngine 整數 bp 權重與 Regime 權重重分配。
- Research Run SQLite metadata、Parquet 詳細資料與 hash 稽核。
- 單股、批次、推薦回放與推薦組合的統一 run adapter。
- Research Lab Cross-run Comparison 子頁。
- Comparability Gate 與 benchmark-relative attribution。
- Registry-based promotion、JSON Strategy Version 補償交易與 reconciliation。
- Legacy run 手動 backfill。

### Scope Out

- Factor Layer v1、營收、估值、三大法人與新資料來源。
- 黑箱自動調參。
- 把 quantile 改成預設。
- 新增第八個頂層 UI Tab。
- 自動刪除 archived run 或實體 purge。
- 把 Strategy Version 全面遷移到 SQLite。
- 改寫既有績效公式或在 Registry 重新計算績效。

## 2. 核心契約

### 2.1 指標參數

- `config_schema_version` 只能從完整 config 解析，caller 不得用額外參數覆蓋。
- 缺失版本視為 legacy v0。
- v0 缺少欄位可套用版本化 legacy default，並保存 fallback metadata。
- v1+ 缺少必要參數必須拒絕。
- 所有版本的非法值、錯誤型態、未知欄位都必須拒絕。
- alias canonicalization 必須先處理，再移除 `enabled` 等治理欄位，最後檢查未知欄位。
- disabled 指標不驗證、不計算、不生成欄位。

### 2.2 權重

- 核心權重只接受 `pattern`、`technical`、`volume` 三個完整 key。
- 值必須是非 bool 的整數 bp。
- 三項總和必須嚴格等於 `10000`。
- 不自動 normalize、不四捨五入、不補差額。
- legacy float 只能由 `LegacyWeightMigrationAdapter` 使用 `Decimal(str(value))` 轉換。
- legacy 轉換乘積不是整數 bp，或總和不是 `10000`，必須拒絕。

### 2.3 Research Run

- `ResearchRunService` 是唯一 write owner。
- 執行服務只回傳成功 DTO，不直接落盤。
- 使用者按「保存結果」或明確排程設定後才呼叫 `save_run()`。
- 相同 `run_id` + 相同 payload hash：回傳既有結果。
- 相同 `run_id` + 不同 payload hash：拋出 conflict。
- run 不可覆寫；取消、失敗、未完成結果不可保存。
- `data_fingerprint`、`fingerprint_algorithm`、`data_manifest` 分欄保存。
- 績效、Regime 與 benchmark 結果來自正式結果 DTO，Registry 不重算。

### 2.4 Promotion

- promoted run 不可 archive。
- Registry 保存 `promoted_version_id` 與 promotion reconciliation 狀態。
- Strategy Version 目前是 JSON 檔案，不能宣稱與 SQLite 共用 transaction。
- Promotion 採暫存 JSON、原子 rename、Registry 回填與補償刪除。
- 補償失敗時記錄 reconciliation 狀態，啟動或受控工具可修復。

## 3. 檔案結構

### M2-A 新增

- `decision_module/indicator_parameter_registry.py`
- `decision_module/weight_contract.py`
- `tests/test_indicator_parameter_registry.py`
- `tests/test_weight_contract.py`
- `tests/test_m2_a_integration.py`

### M2-A 修改

- `analysis_module/technical_analysis/technical_indicators.py`
- `analysis_module/technical_analysis/technical_analyzer.py`
- `decision_module/strategy_configurator.py`
- `decision_module/scoring_engine.py`

### M2-B 新增

- `app_module/research_run_dtos.py`
- `app_module/research_run_repository.py`
- `app_module/research_run_service.py`
- `app_module/research_run_legacy_adapter.py`
- `tests/test_research_run_repository.py`
- `tests/test_research_run_service.py`
- `tests/test_research_run_legacy_adapter.py`
- `scripts/backfill_legacy_runs.py`

### M2-B 修改

- `data_module/config.py`
- `app_module/backtest_repository.py`
- `app_module/recommendation_portfolio_run_repository.py`
- `ui_qt/views/backtest_view.py`

### M2-C 新增

- `ui_qt/views/research_lab/run_registry_compare_widget.py`
- `app_module/research_run_comparison_service.py`
- `app_module/promotion_reconciliation_service.py`
- `tests/test_research_run_comparison_service.py`
- `tests/test_promotion_reconciliation.py`
- `tests/test_ui_qt_run_registry_compare.py`

### M2-C 修改

- `ui_qt/views/backtest_view.py`
- `ui_qt/views/backtest/config_panel.py`
- `app_module/promotion_service.py`
- `app_module/recommendation_portfolio_promotion_service.py`
- `app_module/strategy_version_service.py`

### 文件

- `docs/02_features/RESEARCH_RUN_REGISTRY_SPEC.md`
- `docs/02_features/BACKTEST_LAB_FEATURES.md`
- `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
- `docs/02_features/USER_GUIDE.md`
- `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`
- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/01_architecture/system_architecture.md`
- `PROJECT_NAVIGATION.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`

---

## M2-A：參數與權重契約

## Task A1: 收緊 Indicator Parameter Registry

**Files:**
- Modify: `decision_module/indicator_parameter_registry.py`
- Modify: `tests/test_indicator_parameter_registry.py`

- [x] **Step 1: 寫入嚴格型態與未知欄位失敗測試**

測試至少包含：

```python
@pytest.mark.parametrize(
    "value",
    ["20", 20.0, True, None],
)
def test_v1_rsi_rejects_non_integer_timeperiod(value):
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize(
            "rsi",
            {"timeperiod": value},
            {"config_schema_version": 1},
        )
```

```python
def test_unknown_parameter_is_rejected_after_alias_normalization():
    with pytest.raises(InvalidParameterError, match="未知參數"):
        IndicatorParameterRegistry.validate_and_sanitize(
            "rsi",
            {"period": 14, "timeperoid": 20},
            {"config_schema_version": 1},
        )
```

```python
@pytest.mark.parametrize("version", [True, 1.0, -1, "abc"])
def test_invalid_config_schema_version_is_controlled(version):
    with pytest.raises(InvalidParameterError, match="config_schema_version"):
        IndicatorParameterRegistry.validate_and_sanitize(
            "rsi",
            {"timeperiod": 14},
            {"config_schema_version": version},
        )
```

- [x] **Step 2: 執行測試並確認失敗**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_indicator_parameter_registry.py -q -o addopts=
```

Expected: 新增 strict-contract cases FAIL。

- [x] **Step 3: 實作 canonicalization 與 strict validation**

順序必須固定：

```text
parse full config version
-> copy input
-> pop governance keys such as enabled
-> canonicalize aliases
-> reject remaining unknown keys
-> reject missing required values according to version
-> exact type validation
-> range/cross-field validation
```

版本解析不得使用裸 `int(value)` 接受 bool/float：

```python
raw_version = full_config.get("config_schema_version", 0)
if isinstance(raw_version, bool) or not isinstance(raw_version, int):
    raise InvalidParameterError("Invalid config_schema_version format")
if raw_version < 0:
    raise InvalidParameterError("config_schema_version must be non-negative")
```

- [x] **Step 4: 加入跨欄位限制**

- MACD：`fastperiod < slowperiod`。
- SAR：`acceleration <= maximum`。
- MA windows：非空、非 bool 整數、範圍 `2..500`、不得重複。
- Bollinger：`nbdevup` / `nbdevdn` 只在 TA-Lib 邊界轉 float。

第二輪驗收後修復：MACD、SAR、重複值、bool 與 MA windows 精確型態契約均已完成。

- [x] **Step 5: 執行 Registry 測試**

Expected: PASS。

## Task A2: 鎖定整數 bp 權重與 legacy migration

**Files:**
- Modify: `decision_module/weight_contract.py`
- Modify: `tests/test_weight_contract.py`

- [x] **Step 1: 寫入 key completeness 測試**

```python
@pytest.mark.parametrize(
    "weights",
    [
        {"pattern": 3000, "technical": 7000},
        {"pattern": 3000, "technical": 5000, "volume": 2000, "other": 0},
    ],
)
def test_weight_contract_rejects_missing_or_extra_keys(weights):
    with pytest.raises(InvalidWeightError):
        RecommendationWeightContract(weights)
```

- [x] **Step 2: 寫入 bool 與 migration 精度測試**

```python
def test_weight_contract_rejects_bool():
    with pytest.raises(InvalidWeightError):
        RecommendationWeightContract(
            {"pattern": True, "technical": 7999, "volume": 2000}
        )
```

保留 `Decimal(str(value))`，乘積不是整數或總和不是 10000 時拒絕。

- [x] **Step 3: 實作並執行測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_weight_contract.py -q -o addopts=
```

Expected: PASS。

第二輪驗收後修復：正式 Contract 與 LegacyWeightMigrationAdapter 均已拒絕缺少 / 額外 key，正式 Contract 同時拒絕 bool。

## Task A3: 正確處理 enabled/disabled 指標

**Files:**
- Modify: `analysis_module/technical_analysis/technical_analyzer.py`
- Modify: `analysis_module/technical_analysis/technical_indicators.py`
- Modify: `tests/test_m2_a_integration.py`
- Modify: `tests/test_analysis/test_technical_analysis.py`

- [x] **Step 1: 寫入混合配置失敗測試**

至少逐一覆蓋 RSI、MACD、KD、Bollinger、SAR、ATR、TSF、ADX、MA：

```python
def test_disabled_rsi_and_kd_are_not_calculated_but_macd_is():
    result = StrategyConfigurator().configure_technical_indicators(
        price_data,
        {
            "momentum": {
                "enabled": True,
                "rsi": {"enabled": False},
                "macd": {
                    "enabled": True,
                    "fastperiod": 12,
                    "slowperiod": 26,
                    "signalperiod": 9,
                },
                "kd": {"enabled": False},
            }
        },
        full_config={"config_schema_version": 1},
    )
    assert "MACD" in result.columns
    assert "RSI" not in result.columns
    assert "SlowK" not in result.columns
```

- [x] **Step 2: 定義 legacy 與 v1 預設**

- direct calculator 呼叫且 `full_config is None`：視為 legacy，`None` 可轉 `{}` 使用舊預設。
- v0 analyzer 未提供子指標：沿用舊版預設計算。
- v1 analyzer 未提供或 `enabled=False`：跳過該子指標。
- v1 `enabled=True` 但缺少必要參數：Registry fail-closed。

- [x] **Step 3: 實作最小跳過邏輯**

Calculator 不得用「所有參數都是 None」猜測單一指標是否停用；由 analyzer 明確決定是否呼叫各 calculator。

第二輪驗收：實作路徑已存在，但 `test_single_indicator_disabled` 沒有呼叫 analyzer / configurator，Step 1 與 Step 4 仍不得標成完成。

- [x] **Step 4: 執行分析與整合測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_analysis\test_technical_analysis.py tests\test_m2_a_integration.py -q -o addopts=
```

Expected: PASS。

## Task A4: 將 bp 權重接入 ScoringEngine

**Files:**
- Modify: `decision_module/scoring_engine.py`
- Modify: `tests/test_m2_a_integration.py`

- [x] **Step 1: 寫入正式路徑 migration / 失敗測試**

測試不能只呼叫 Contract，必須呼叫 `ScoringEngine.calculate_total_score()`。可無損轉換的 legacy float 應經 adapter 成功；非整數 bp 或總和不合規時必須拒絕：

```python
def test_scoring_engine_uses_controlled_legacy_weight_migration(scoring_frame):
    valid = {"weights": {"pattern": 0.3, "technical": 0.5, "volume": 0.2}}
    result = ScoringEngine().calculate_total_score(scoring_frame, valid)
    assert isinstance(result.iloc[-1]["TotalScore"], Decimal)

    invalid = {
        "weights": {
            "pattern": 0.33333,
            "technical": 0.5,
            "volume": 0.16667,
        }
    }
    with pytest.raises(WeightMigrationError):
        ScoringEngine().calculate_total_score(scoring_frame, invalid)
```

- [x] **Step 2: 定義總分公式**

核心計算使用 Decimal：

```text
weighted_numerator =
    pattern_score * pattern_bp
  + technical_score * technical_bp
  + volume_score * volume_bp

total_score = weighted_numerator / 10000
```

最終 rounding 採 `ROUND_HALF_UP` 至既有分數 contract 所需精度；只有 DataFrame analytics/UI 邊界才轉 float。

第二輪驗收後修復：Decimal 加權公式已完成，並依 score basis-point 契約量化至 `0.01` 分。

- [x] **Step 3: 實作 Regime 權重重分配**

Regime 倍率使用 Decimal 字串：

```python
REGIME_MULTIPLIERS = {
    "Trend": {
        "pattern": Decimal("0.8"),
        "technical": Decimal("1.2"),
        "volume": Decimal("1.0"),
    },
}
```

`_normalize_to_10000_bp()` 必須：

1. 計算 Decimal raw weights。
2. 取 floor bp。
3. 依 fractional remainder、固定 key 順序分配剩餘 bp。
4. 建立 `RecommendationWeightContract` 再驗證。

- [x] **Step 4: 移除舊 float normalize**

移除或停止呼叫：

- `_normalize_weights()` 裸 float 除法。
- `_get_regime_weights()` 裸 float 乘法。
- 缺少權重時靜默退回 float defaults。

Legacy config 必須先經 `LegacyWeightMigrationAdapter`。

- [x] **Step 5: 執行測試**

Expected:

- base bp 總和為 10000。
- 每個 Regime 重分配後總和為 10000。
- 同輸入重複執行結果一致。
- 非 bp config 不會繞過 migration。

## Task A5: Fail-Closed 傳播與 Look-ahead Gate

**Files:**
- Modify: `decision_module/strategy_configurator.py`
- Modify: `tests/test_m2_a_integration.py`

- [x] **Step 1: 寫入治理例外傳播測試**

```python
def test_generate_recommendations_propagates_invalid_parameter(price_data):
    config = valid_v1_config()
    config["technical"]["momentum"]["rsi"]["timeperiod"] = 1
    with pytest.raises(InvalidParameterError):
        StrategyConfigurator().generate_recommendations(price_data, config)
```

同步測試 `InvalidWeightError`。

- [x] **Step 2: 定義 catch policy**

- `InvalidParameterError`、`InvalidWeightError`、`WeightMigrationError`：一律向外傳播。
- 既有資料品質或非契約例外是否降級：沿用既有行為，但必須 logger 記錄。
- 文件不得宣稱「所有 Exception 都向外拋出」，只宣稱治理例外 fail-closed。

- [x] **Step 3: 實作 prefix-invariance**

```python
def test_indicator_and_score_prefix_are_invariant_to_future_rows():
    prefix = price_data.iloc[:80].copy()
    extended = price_data.iloc[:100].copy()

    prefix_result = run_analysis(prefix)
    extended_result = run_analysis(extended).iloc[:80]

    pd.testing.assert_frame_equal(
        prefix_result[CHECKED_COLUMNS],
        extended_result[CHECKED_COLUMNS],
        check_exact=False,
        rtol=0,
        atol=0,
    )
```

若指標暖機產生 NaN，使用相同 index/columns 比較，不得用填值掩蓋差異。

- [x] **Step 4: 執行 M2-A focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_indicator_parameter_registry.py tests\test_weight_contract.py tests\test_m2_a_integration.py tests\test_analysis\test_technical_analysis.py -q -o addopts=
```

Expected: PASS。

## Task A6: M2-A 文件與完整驗證

**Files:**
- Modify only after Coverage Pass confirms exact set.

- [x] **Step 1: 執行 Documentation Coverage Pass**

至少檢查：

- `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`
- `docs/02_features/BACKTEST_LAB_FEATURES.md`
- `docs/02_features/USER_GUIDE.md`
- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/01_architecture/system_architecture.md`
- `PROJECT_NAVIGATION.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`

Coverage 已同步 Strategy Design、Score Explanation、User Guide、Backtest Lab、Application Manual、Architecture、Navigation、Snapshot、Index 與本計畫。

- [x] **Step 2: 執行完整 pytest**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

- [x] **Step 3: 執行 mypy**

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

- [x] **Step 4: 執行金融邊界 Gate**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m pytest tests\test_financial_float_boundary_checker.py -q -o addopts=
```

- [x] **Step 5: 執行 changed-files py_compile**

```powershell
.\.venv\Scripts\python.exe -m py_compile decision_module\indicator_parameter_registry.py decision_module\weight_contract.py decision_module\scoring_engine.py decision_module\strategy_configurator.py analysis_module\technical_analysis\technical_indicators.py analysis_module\technical_analysis\technical_analyzer.py
```

- [x] **Step 6: M2-A Review Gate**

必須確認：

- Contract 已接入正式執行路徑，不只是孤立 class。
- enabled/disabled 混合配置正確。
- 治理例外不被轉成空結果。
- Prefix-invariance 通過。
- 文件不得提前宣稱 M2-B/C 完成。

- [ ] **Step 7: 取得使用者核准**

使用者明確核准後，才將本計畫的 M2-A 狀態標成完成並開始 M2-B。

---

## M2-B：Research Run Registry

## Task B1: 建立 Research Run DTO 與 schema migration

**Files:**
- Create: `app_module/research_run_dtos.py`
- Create: `app_module/research_run_repository.py`
- Modify: `data_module/config.py`
- Test: `tests/test_research_run_repository.py`

- [x] **Step 1: 寫入 schema 與路徑失敗測試**

`TWStockConfig` 新增：

```python
research_run_db_file: Path
research_run_parquet_dir: Path
research_run_staging_dir: Path
```

路徑由 `output_root` 衍生，測試必須使用 `tmp_path`。

- [x] **Step 2: 定義 ResearchRunMetadataDTO**

必要欄位：

```text
run_id
run_name
run_type
strategy_id
strategy_version
parameter_contract_version
original_input
normalized_params
fallback_reason
universe
start_date
end_date
data_cutoff_date
data_fingerprint
fingerprint_algorithm
data_manifest
capital_cents
fee_bp_x100
slippage_bp_x100
stop_loss_bp
take_profit_bp
execution_price
sizing_mode
metrics
regime_breakdown
benchmark_results
payload_hash
equity_path
equity_parquet_hash
trades_path
trades_parquet_hash
is_archived
promoted_version_id
promotion_reconciliation_status
created_at
```

- [x] **Step 3: 建立 versioned migration**

不得只在 constructor 中散落多個 `ALTER TABLE`。建立 `schema_version` 表或等價 migration runner，migration 必須可重複執行。

- [x] **Step 4: 測試 schema round-trip**

Expected: 所有 JSON 欄位 canonical serialization 後可還原。

驗證證據（2026-06-14）：`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_repository.py -q -o addopts=` -> 4 passed in 1.22s；`.\.venv\Scripts\python.exe -m py_compile data_module\config.py app_module\research_run_dtos.py app_module\research_run_repository.py tests\test_research_run_repository.py` -> exit 0；`.\.venv\Scripts\python.exe -m mypy app_module\research_run_dtos.py app_module\research_run_repository.py data_module\config.py` -> Success: no issues found in 3 source files；`git diff --check` -> exit 0（僅 CRLF 提示）。

## Task B2: 實作 immutable save 與跨媒介 crash recovery

**Files:**
- Modify: `app_module/research_run_repository.py`
- Create: `app_module/research_run_service.py`
- Test: `tests/test_research_run_service.py`

- [x] **Step 1: 寫入 idempotency 測試**

- 同 run ID、同 payload hash：回傳 existing。
- 同 run ID、不同 payload hash：`ResearchRunConflictError`。
- archived/promoted run 不可覆寫。

- [x] **Step 2: 寫入 crash point 測試**

注入 failure：

1. temp parquet 寫入前。
2. temp parquet 寫入後。
3. hash 後。
4. SQLite staging row 後。
5. rename 第一個 parquet 後。
6. rename 第二個 parquet 後。
7. final SQLite update 前。

- [x] **Step 3: 實作 staging state machine**

建議狀態：

```text
staging
files_ready
committed
failed
```

儲存流程：

```text
canonical payload + payload hash
-> insert staging row
-> write temp parquet
-> hash temp parquet
-> atomic rename
-> verify final hashes
-> update row committed
```

SQLite 無法與 filesystem 真正同 transaction；不得宣稱完全原子。啟動時執行 reconciliation：

- staging row + temp files：清理或續作。
- staging row + final files：驗 hash 後 commit。
- final files 無 row：移至 quarantine，不直接刪除。
- committed row 缺檔：標記 integrity failure。

- [x] **Step 4: 實作 load hash verification**

hash 不符時拋出 `ResearchRunIntegrityError`，不得載入部分資料冒充完整 run。

驗證證據（2026-06-14）：`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_repository.py tests\test_research_run_service.py -q -o addopts=` -> 13 passed in 1.66s；`.\.venv\Scripts\python.exe -m py_compile app_module\research_run_dtos.py app_module\research_run_repository.py app_module\research_run_service.py tests\test_research_run_repository.py tests\test_research_run_service.py` -> exit 0；`.\.venv\Scripts\python.exe -m mypy app_module\research_run_dtos.py app_module\research_run_repository.py app_module\research_run_service.py data_module\config.py` -> Success: no issues found in 4 source files。

## Task B3: 軟刪除與 promoted 保護

**Files:**
- Modify: `app_module/research_run_service.py`
- Test: `tests/test_research_run_service.py`

- [x] **Step 1: 寫入 archive 測試**

- 一般 run：`is_archived=1`，檔案保留。
- promoted run：拒絕 archive。
- list 預設排除 archived，可明確 include。

- [x] **Step 2: 實作**

本增量不實作 purge。Retention/purge 留待獨立治理任務。

驗證證據（2026-06-14）：`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_repository.py tests\test_research_run_service.py -q -o addopts=` -> 15 passed in 1.55s；`.\.venv\Scripts\python.exe -m py_compile app_module\research_run_repository.py app_module\research_run_service.py tests\test_research_run_service.py` -> exit 0；`.\.venv\Scripts\python.exe -m mypy app_module\research_run_dtos.py app_module\research_run_repository.py app_module\research_run_service.py data_module\config.py` -> Success: no issues found in 4 source files。

## Task B4: 舊 Repository adapter 與 backfill

**Files:**
- Create: `app_module/research_run_legacy_adapter.py`
- Create: `scripts/backfill_legacy_runs.py`
- Modify: `app_module/backtest_repository.py`
- Modify: `app_module/recommendation_portfolio_run_repository.py`
- Test: `tests/test_research_run_legacy_adapter.py`

- [x] **Step 1: 寫入 legacy mapping tests**

舊 run 缺 metadata 時：

- 不偽造版本。
- 缺值保存為空或 explicit unknown。
- 原始 legacy run ID 保存於 source metadata。
- backfill 重跑不重複寫入。

- [x] **Step 2: 實作 dry-run 與 explicit apply**

```powershell
.\.venv\Scripts\python.exe scripts\backfill_legacy_runs.py --dry-run
.\.venv\Scripts\python.exe scripts\backfill_legacy_runs.py --apply
```

腳本不得自動執行，不得刪除舊 repository。

驗證證據（2026-06-14）：`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_repository.py tests\test_research_run_service.py tests\test_research_run_legacy_adapter.py -q -o addopts=` -> 17 passed in 1.67s；`.\.venv\Scripts\python.exe -m py_compile app_module\research_run_legacy_adapter.py app_module\research_run_service.py scripts\backfill_legacy_runs.py tests\test_research_run_legacy_adapter.py` -> exit 0；`.\.venv\Scripts\python.exe -m mypy app_module\research_run_dtos.py app_module\research_run_repository.py app_module\research_run_service.py app_module\research_run_legacy_adapter.py data_module\config.py scripts\backfill_legacy_runs.py` -> Success: no issues found in 6 source files。

## Task B5: UI 保存入口改用 ResearchRunService

**Files:**
- Modify: `ui_qt/views/backtest_view.py`
- Test: relevant Research Lab UI tests

- [x] **Step 1: 鎖定 save owner**

Backtest/replay services 只回傳 DTO。現有「保存結果」入口呼叫 `ResearchRunService.save_run()`。

- [x] **Step 2: 防止失敗或 stale DTO 保存**

保存前檢查：

- result status success。
- run ID 存在。
- snapshot 已建立。
- UI 新一輪執行已開始時，不可保存舊 pending result。

驗證證據（2026-06-14）：`.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_run_save.py -q -o addopts=` -> 3 passed in 1.85s；`.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_run_save.py tests\test_ui_qt_research_workflow.py tests\test_ui_qt_report_export.py -q -o addopts=` -> 19 passed in 2.55s；`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_repository.py tests\test_research_run_service.py tests\test_research_run_legacy_adapter.py -q -o addopts=` -> 17 passed in 1.78s；`.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=` -> 13 passed in 1.50s；`.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py` -> passed 21 / failed 0 / skipped 4；`.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` -> Success: no issues found in 152 source files；changed-files py_compile -> exit 0。

## Task B6: M2-B 文件與驗證

- [x] Repository/service focused tests。
- [x] Crash-recovery injection tests。
- [x] Legacy dry-run 使用隔離測試資料。
- [x] 完整 pytest、mypy、float gate、py_compile。
- [x] 更新 Registry spec、Architecture、Navigation、Manual 與相關功能文件。
- [ ] 使用者核准後才開始 M2-C。

驗證證據（2026-06-14）：`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_repository.py tests\test_research_run_service.py tests\test_research_run_legacy_adapter.py tests\test_ui_qt_research_run_save.py -q -o addopts=` -> 20 passed in 2.63s；`.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py` -> exit 0；changed-files py_compile -> exit 0；`.\.venv\Scripts\python.exe -m pytest -q -o addopts=` -> 425 passed, 7 warnings in 17.08s；`.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` -> Success: no issues found in 152 source files；`.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py` -> passed 21 / failed 0 / skipped 4。文件同步涵蓋 Registry spec / Architecture / Navigation / Manual / UI features / Backtest Lab / User Guide / Snapshot / Roadmap Hub / 6M Roadmap / Documentation Index。

---

## M2-C：Cross-run Comparison 與 Promote Gate

## Task C1: Comparability Service

**Files:**
- Create: `app_module/research_run_comparison_service.py`
- Test: `tests/test_research_run_comparison_service.py`

- [x] **Step 1: 定義三態**

```text
Comparable
Caution
Incompatible
```

- `Comparable`：fingerprint、期間、Universe、成本、execution、sizing 相同。
- `Caution`：Universe、期間或成本不同，只顯示並列，不產生優劣排名。
- `Incompatible`：資料 fingerprint、execution 或 sizing mode 不同，禁用直接績效比較。

- [x] **Step 2: 定義曲線比較**

- 各 run 以起始值正規化為 100。
- 只比較明確日期交集。
- 缺值不 forward-fill 跨越 run 不存在期間。
- UI 顯示使用的日期交集與排除原因。

- [x] **Step 3: benchmark-relative attribution**

只使用 run 已保存的 benchmark results，不在比較時重新抓取目前資料。

驗證證據（2026-06-14）：`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_comparison_service.py -q -o addopts=` 先 RED：缺少 `app_module.research_run_comparison_service`；實作後 -> 5 passed in 1.11s。`.\.venv\Scripts\python.exe -m pytest tests\test_research_run_comparison_service.py tests\test_research_run_repository.py tests\test_research_run_service.py -q -o addopts=` -> 20 passed in 1.66s；changed-files py_compile -> exit 0；`.\.venv\Scripts\python.exe -m mypy app_module\research_run_comparison_service.py app_module\research_run_dtos.py tests\test_research_run_comparison_service.py` -> Success: no issues found in 3 source files。

## Task C2: Research Lab 子 Tab

**Files:**
- Create: `ui_qt/views/research_lab/run_registry_compare_widget.py`
- Modify: `ui_qt/views/backtest_view.py`
- Modify: `ui_qt/views/backtest/config_panel.py`
- Test: `tests/test_ui_qt_run_registry_compare.py`

- [ ] **Step 1: 新增子 Tab，不新增頂層 Tab**

功能：

- 分頁 run 列表。
- run type、strategy、tag 篩選。
- 2 至 5 個 run 多選。
- comparability badge。
- 參數差異表。
- normalized equity chart。
- metrics、Regime、benchmark comparison。

- [ ] **Step 2: stale request 防護**

沿用 request ID 模式，舊背景查詢不得覆蓋最新結果。

## Task C3: Registry-based Promotion

**Files:**
- Modify: `app_module/promotion_service.py`
- Modify: `app_module/recommendation_portfolio_promotion_service.py`
- Modify: `app_module/strategy_version_service.py`
- Create: `app_module/promotion_reconciliation_service.py`
- Test: `tests/test_promotion_reconciliation.py`

- [ ] **Step 1: Promotion 只讀 Registry**

新 promotion 必須提供有效 `run_id`，且 run：

- integrity valid。
- not archived。
- not already promoted。
- OOS / validation Gate 通過。
- 參數與權重 contract version 可還原。

- [ ] **Step 2: 實作 JSON 補償交易**

流程：

```text
write strategy version temp JSON
-> fsync if supported
-> atomic rename to final JSON
-> update registry promoted_version_id
-> if registry update fails, delete final JSON
-> if delete fails, mark reconciliation_required
```

不得稱為 SQLite transaction rollback。

- [ ] **Step 3: reconciliation**

掃描：

- JSON 有 source_run_id，但 Registry 未回填。
- Registry 有 promoted_version_id，但 JSON 缺失。
- 雙方 ID 不一致。

只產生受控修復建議或明確 apply 操作，不靜默刪除。

## Task C4: M2-C 文件與最終驗證

- [ ] UI focused pytest。
- [ ] 強制 Update Tab pytest。
- [ ] `scripts/qa_validate_update_tab.py`。
- [ ] 完整 pytest。
- [ ] mypy。
- [ ] financial float boundary。
- [ ] changed-files py_compile。
- [ ] 手動 Cross-run 比較。
- [ ] 手動 Parquet integrity failure。
- [ ] 手動 Promotion compensation failure。
- [ ] Manual、UI docs、Architecture、Navigation、Snapshot、6M Roadmap、Legacy Carryover、Index 同步。

---

## 4. Month 2 Definition of Done

- [ ] 任一研究 run 可追溯資料 fingerprint、manifest、策略版本、參數、權重、成本、成交與 sizing 假設。
- [ ] 任一 v1+ 非法或缺失參數 fail-closed。
- [ ] 舊配置 fallback 有版本與理由，不會污染新配置。
- [ ] ScoringEngine 正式路徑只使用已驗證整數 bp 權重。
- [ ] Look-ahead prefix-invariance 通過。
- [ ] Registry save immutable、idempotent，並具跨 filesystem/SQLite crash reconciliation。
- [ ] archived run 不出現在預設列表，promoted run 不可 archive。
- [ ] 至少可比較 3 個策略版本或參數組合。
- [ ] 不相容 run 不會被 UI 排名成較優/較差。
- [ ] Promote 必須關聯 Registry run，跨 SQLite/JSON 失敗有補償與 reconciliation。
- [ ] Legacy run 可 dry-run backfill，且不破壞原 repository。
- [ ] 完整 pytest、mypy、float boundary、py_compile 與 UI QA 全數通過。
- [ ] 文件與 Scoped SSOT 同步，Month 3 Carryover Gate 可被正式判定。

## 5. 提交策略

- M2-A、M2-B、M2-C 分開提交與 review。
- 每個 Task 先測試、後實作、再 focused verification。
- 不要把目前未提交的其他變更一併 stage。
- Stage 前執行：

```powershell
git status --short
git diff --check
```

- 依 `docs/agents/git_exclusions.md` 排除 shared state、QA output、暫存資料庫、Parquet、報告與測試產物。

## 6. 進度更新規則

每次完成 Task 時：

1. 將對應 checkbox 改為 `[x]`。
2. 在 Task 下方補一行驗證證據：

```text
驗證證據（YYYY-MM-DD）：<command> -> <result>
```

3. Gate 未正式通過前，不更新下一增量為進行中。
4. 功能未驗證完成前，不在 Snapshot、6M Roadmap 或 Legacy Carryover 宣稱完成。
5. 若實作與本計畫契約不同，先更新本 plan 並說明原因，再繼續實作。
