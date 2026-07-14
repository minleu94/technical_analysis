# Terra Development Dataset V0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立獨立、唯讀、development-only 的 Terra V0 dataset generator，讓 2025 可作 development、2026 僅作 evaluation，且絕不寫正式路徑或改變 Rule-only path。

**Architecture:** `development_module` 將 source read、universe policy、generation 和 artifact writer 分離；既有 `ml_module` registry／feature／label contracts 僅作唯讀依賴。CLI 是唯一 composition root，先拒絕不安全輸出根與 non-core source，再產生 append-only generation。

**Tech Stack:** Python 3、stdlib `sqlite3`／`Decimal`／`hashlib`、既有 `ml_module` causal contracts、pytest、mypy。

## Global Constraints

- 固定目前 `dev` working tree；不得建立／切換 branch 或 worktree，且不得 reset、stash、pull。
- 不讀取 EV3 sealed payload／return／metric／ranking／report body；不改 `locked_oos`、formal verifier、ScoringEngine、Recommendation、Portfolio、Exit、scheduler。
- 只讀 `daily_prices`、`technical_indicators`、`market_indices`、`industry_indices`；fundamental／broker 一律排除。
- 所有量化持久化值使用 `Decimal` 或整數 bp/count；不得在核心計算新增裸 `float`。
- 全部 artifacts 僅寫明確 `DEVELOPMENT_OUTPUT_ROOT`／TEMP，且 generation ID 不可覆寫。
- 2025 是 `development_fit_eligible`；2026 的 matured labels 是 `evaluation_only`，永不進 fit。
- `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`formal_rule_only_path_unchanged=true`、`zero_formal_write=true` 必須由 contracts 和 CLI 同時保證。

---

### Task 1: Contracts、輸出安全閘與 RED 測試

**Files:**
- Create: `tests/test_terra_development_dataset_v0.py`
- Create: `development_module/__init__.py`
- Create: `development_module/contracts.py`
- Create: `development_module/output_guard.py`

**Interfaces:**
- Produces: `DevelopmentGenerationRequest`, `DevelopmentDatasetManifest`, `GenerationWriteResult`, `validate_development_output_root()`。
- Consumes: only `pathlib.Path`、frozen standard-library dataclasses。

- [ ] **Step 1: 寫入失敗測試**

```python
def test_output_root_rejects_data_root_and_accepts_explicit_external_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    with pytest.raises(ValueError, match="development_output_root"):
        validate_development_output_root(data_root, data_root=data_root, formal_db=data_root / "sqlite" / "twstock.db")
    assert validate_development_output_root(tmp_path / "development", data_root=data_root, formal_db=data_root / "sqlite" / "twstock.db") == (tmp_path / "development").resolve()

def test_manifest_rejects_nonzero_production_alpha_or_formal_oos() -> None:
    with pytest.raises(ValueError, match="formal_oos_allowed"):
        DevelopmentDatasetManifest.minimal(formal_oos_allowed=True)
    with pytest.raises(ValueError, match="production_blend_alpha_bp"):
        DevelopmentDatasetManifest.minimal(production_blend_alpha_bp=1)
```

- [ ] **Step 2: 執行 RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terra_development_dataset_v0.py -q -o addopts=`

Expected: FAIL，因 module／interface 尚不存在。

- [ ] **Step 3: 寫入最小 contract 與 guard**

```python
@dataclass(frozen=True)
class DevelopmentGenerationRequest:
    generation_id: str
    decision_date_start: str
    decision_date_end: str
    training_as_of: str
    evaluation_as_of: str
    minimum_observed_history_days: int = 252

@dataclass(frozen=True)
class DevelopmentDatasetManifest:
    dataset_status: Literal["research_only_degraded"]
    formal_oos_allowed: Literal[False] = False
    production_blend_alpha_bp: Literal[0] = 0
    formal_rule_only_path_unchanged: Literal[True] = True
    zero_formal_write: Literal[True] = True

def validate_development_output_root(root: Path, *, data_root: Path, formal_db: Path) -> Path: ...
```

Guard 必須 resolve path、拒絕 `DATA_ROOT` 本身／其子孫、正式 DB 或既有 generation directory，並且不可建立任何 formal path。

- [ ] **Step 4: 執行 GREEN**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terra_development_dataset_v0.py -q -o addopts=`

Expected: PASS。

### Task 2: 唯讀 core-source adapter 與 conservative universe

**Files:**
- Modify: `tests/test_terra_development_dataset_v0.py`
- Create: `development_module/source_adapter.py`
- Create: `development_module/universe.py`

**Interfaces:**
- Produces: `CoreSourceSnapshot`, `CoreSourceAdapter.load()`, `ConservativeObservedHistoryUniverse.select()`。
- Consumes: four allowed SQLite source tables only；輸入／輸出 observations 均保留 `Decimal` 或 int。

- [ ] **Step 1: 寫入失敗測試**

```python
def test_source_adapter_is_query_only_and_fingerprints_each_core_source(sqlite_fixture: Path) -> None:
    snapshot = CoreSourceAdapter(sqlite_fixture).load("2025-01-01", "2026-12-31")
    assert snapshot.source_tables == ("daily_prices", "technical_indicators", "market_indices", "industry_indices")
    assert set(snapshot.source_fingerprints) == set(snapshot.source_tables)
    assert snapshot.query_only is True

def test_conservative_universe_requires_252_prior_observed_days_and_reports_gaps() -> None:
    selected, diagnostics = ConservativeObservedHistoryUniverse(252).select(observations)
    assert selected == ("2330",)
    assert diagnostics["listing_date_unavailable"] > 0
    assert diagnostics["insufficient_observed_history"] > 0
```

- [ ] **Step 2: 執行 RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terra_development_dataset_v0.py -q -o addopts=`

Expected: FAIL，因 adapter 與 policy 尚不存在。

- [ ] **Step 3: 寫入最小 read-only source 與 universe 實作**

```python
class CoreSourceAdapter:
    ALLOWED_TABLES = ("daily_prices", "technical_indicators", "market_indices", "industry_indices")
    def load(self, start: str, end: str) -> CoreSourceSnapshot: ...

class ConservativeObservedHistoryUniverse:
    def __init__(self, minimum_observed_history_days: int = 252) -> None: ...
    def select(self, prices: tuple[HistoricalPriceObservation, ...], decision_date: str) -> tuple[tuple[str, ...], dict[str, int]]: ...
```

SQLite 必須 URI `mode=ro` 及 `PRAGMA query_only=ON`；每個 table 的 canonical schema、range、row count 與內容列 hash 各自 SHA-256。universe 只計 decision 前 observations，標記未提供 listing／delisting metadata 的 diagnostics，絕不可改用 survivor list。

- [ ] **Step 4: 執行 GREEN**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terra_development_dataset_v0.py -q -o addopts=`

Expected: PASS，且 fixture DB 的 size／mtime 不變。

### Task 3: T-1 generation、2025／2026 label policy、artifact writer 與 CLI

**Files:**
- Modify: `tests/test_terra_development_dataset_v0.py`
- Create: `development_module/generation.py`
- Create: `development_module/writer.py`
- Create: `scripts/build_terra_development_dataset_v0.py`

**Interfaces:**
- Produces: `TerraDevelopmentDatasetGenerator.generate(request)`, `DevelopmentArtifactWriter.write(result, output_root)`, CLI exit 0/2。
- Consumes: Task 1 request/manifest、Task 2 snapshot/universe、既有 feature／label registry and builders。

- [ ] **Step 1: 寫入失敗測試**

```python
def test_generation_uses_t_minus_1_and_keeps_2025_fit_separate_from_2026_evaluation(snapshot: CoreSourceSnapshot) -> None:
    result = TerraDevelopmentDatasetGenerator(snapshot).generate(request)
    assert all(row.feature.feature_as_of_date < row.feature.decision_date for row in result.fit_rows)
    assert {row.feature.decision_date[:4] for row in result.fit_rows} == {"2025"}
    assert {row.feature.decision_date[:4] for row in result.evaluation_rows} == {"2026"}
    assert result.manifest.dataset_status == "research_only_degraded"

def test_writer_is_append_only_and_content_hash_is_deterministic(tmp_path: Path, result: DevelopmentGenerationResult) -> None:
    first = DevelopmentArtifactWriter(tmp_path).write(result)
    with pytest.raises(FileExistsError):
        DevelopmentArtifactWriter(tmp_path).write(result)
    assert first.manifest["content_hash"] == result.manifest.content_hash
```

- [ ] **Step 2: 執行 RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terra_development_dataset_v0.py -q -o addopts=`

Expected: FAIL，因 generator／writer／CLI 尚不存在。

- [ ] **Step 3: 寫入最小 generator、writer 與 CLI**

```python
class TerraDevelopmentDatasetGenerator:
    def generate(self, request: DevelopmentGenerationRequest) -> DevelopmentGenerationResult: ...

class DevelopmentArtifactWriter:
    def write(self, result: DevelopmentGenerationResult) -> GenerationWriteResult: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

Generator 對每個 decision date 僅從前一交易日的 source observation 建 feature；以全新當次 price snapshot 建 20-trading-day labels。沒有 corporate coverage source 時一律 `research_only_degraded`，保留 blockers。fit rows 必須只由 2025 ready labels 形成；所有 2026 ready labels 只寫 evaluation artifact。Writer 必須 canonical JSON，寫入 `generations/{generation_id}/`，包含 dataset／generation ID、registry hash、source fingerprints、cutoffs、date range、row counts、diagnostics、content hash 與安全旗標。CLI 在任何 source read 之前驗證 output root，且永不接受 payload／formal OOS 參數。

- [ ] **Step 4: 執行 GREEN**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terra_development_dataset_v0.py -q -o addopts=`

Expected: PASS。

### Task 4: 文件、靜態與 bounded real-data 驗證

**Files:**
- Modify: `docs/07_guides/HISTORICAL_ML_SHADOW_RUNBOOK.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`

**Interfaces:**
- Consumes: CLI actual flags and manifest schema from Task 3.
- Produces: 可重複的 operator guidance；不產生 formal data 寫入。

- [ ] **Step 1: 文件明確列出 V0 的 output root、2025 seen_oos、2026 evaluation-only、252 日 universe、corporate degraded、排除 family、CLI 操作與安全限制。**

- [ ] **Step 2: 跑 focused checks**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_terra_development_dataset_v0.py tests/test_ml_available_date_boundary.py tests/test_ml_historical_snapshot_provider.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 3: 跑靜態／邊界 checks**

Run: `\.venv\Scripts\python.exe -m mypy development_module scripts\build_terra_development_dataset_v0.py`

Run: `\.venv\Scripts\python.exe -m py_compile development_module\*.py scripts\build_terra_development_dataset_v0.py`

Run: `\.venv\Scripts\python.exe scripts\quant_guard_linter.py development_module`

Run: `\.venv\Scripts\python.exe scripts\check_look_ahead_bias.py development_module`

Expected: PASS；若 boundary scripts 不支援 target argument，依其既有全專案 invocation 跑完並保留結果。

- [ ] **Step 4: 跑一次 bounded real-data smoke**

Run: `\.venv\Scripts\python.exe scripts\build_terra_development_dataset_v0.py --database D:\Min\Python\Project\FA_Data\sqlite\twstock.db --development-output-root C:\Temp\technical_analysis_development_output --generation-id terra-v0-smoke-20260713 --decision-date-start 2025-01-02 --decision-date-end 2026-01-31 --training-as-of 2025-12-31 --evaluation-as-of 2026-12-31 --max-decision-dates 5`

Expected: exit 0、artifact 僅在 output root／TEMP、manifest safety flags 固定、正式 DB 的 SHA-256／mtime 前後相同。

- [ ] **Step 5: 精確 stage、commit、push**

先檢查 `git status --short`，只 stage Task 1–4 source、tests、文件；不 stage output root、TEMP、DB、cache 或其他 agent 檔案。全部 QA 成功後，唯一 Coordinator 以明確檔案清單 stage，commit，再 push 目前 `dev`。
