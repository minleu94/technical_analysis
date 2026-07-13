# Two-Day Evidence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在兩個完整工作日內，建立 replay／殘缺資料／新來源／ML shadow 的統一工程驗證基線與 forward evidence 接手包。

**Architecture:** 新增一個唯讀 rehearsal service 與 CLI，透過 adapters 組合既有 replay、source candidate、paper、health、ML 與 lineage輸出。所有結果分 tier、保留 quality/missing/available-date與 parent lineage；不建立新 registry，不變更正式決策。

**Tech Stack:** Python 3.11、dataclasses、Decimal／integer bp、SQLite working-copy、JSON／Markdown、pytest、mypy。

## Global Constraints

- 不寫 production evidence DB、不修改正式資料根目錄。
- 不啟用 production scheduler、broker、自動 rebalance/exit、source acceptance、pruning、lifecycle action或 ML promotion。
- 核心金融值使用 `Decimal` 或整數 bp/股數/分；analytics float必須隔離並標記。
- 所有 feature/label 必須滿足 `available_date <= decision_date`；immature label不得進訓練或評估。
- fixture/replay輸出只能標為 engineering/replay/shadow tier，不得計入 forward/paper/live maturity。
- 每一 task 完成 RED→GREEN、focused verification、`git diff --check` 後才 commit。

---

## Day 1 — 建立可信 replay 與殘缺資料基線

### Task 1（09:00–10:30）：Scenario Contract 與安全邊界

**Files:**
- Create: `app_module/evidence_rehearsal_dtos.py`
- Create: `tests/test_evidence_rehearsal_dtos.py`
- Modify: `qa/full_app_healthcheck/test_inventory.py`

**Interfaces:**
- Produces: `EvidenceRehearsalScenario`, `CoverageMetric`, `RehearsalArtifact`, `EvidenceRehearsalReport`。
- Tier固定為 `engineering_fixture | historical_replay_candidate | shadow_comparison | forward_handoff_pending`。

- [ ] 寫入失敗測試：拒絕 production-like DB、future available date、負 coverage bp、formal evidence tier及 production action flags。
- [ ] 執行 `\.venv\Scripts\python.exe -m pytest tests/test_evidence_rehearsal_dtos.py -q -o addopts=`；預期 import failure。
- [ ] 實作 frozen dataclasses、`to_dict()` 與 fail-closed `__post_init__`；coverage只允許 `0..10000` integer bp。
- [ ] 重跑 focused test；預期全部 PASS。
- [ ] 將新測試登錄為 `governance-doc-tooling`，更新 inventory count test。
- [ ] Commit：`feat(evidence): define replay rehearsal contract`。

### Task 2（10:30–12:30）：Coverage / Quality / Missingness Projector

**Files:**
- Create: `app_module/evidence_rehearsal_coverage.py`
- Create: `tests/test_evidence_rehearsal_coverage.py`

**Interfaces:**
- Consumes: iterable rows containing source id/version、quality、available/decision date、feature/label presence。
- Produces: total/observed/degraded/missing/future-blocked/immature-label counts與 coverage bp；不回傳補值後資料。

- [ ] 測試 complete-case、missing cohort、future data、immature label、空資料與 deterministic ordering。
- [ ] 先跑 focused test確認 RED。
- [ ] 實作 projector；以整數除法計算 coverage bp，禁止裸 float。
- [ ] 加入 invariant：各 cohort counts合計必須等於母體；future-blocked不得列為 observed。
- [ ] 跑 focused tests與 `scripts/quant_guard_linter.py`。
- [ ] Commit：`feat(evidence): project replay coverage and missingness`。

### Task 3（13:30–15:30）：Historical Replay Adapter 與 PIT Gate

**Files:**
- Create: `app_module/evidence_rehearsal_adapters.py`
- Modify: `app_module/historical_evidence_replay.py`
- Test: `tests/test_evidence_rehearsal_adapters.py`
- Test: `tests/test_historical_evidence_replay.py`

**Interfaces:**
- Consumes: existing historical replay summary、score effectiveness rows、benchmark diagnostics。
- Produces: canonical `RehearsalArtifact`；parent指向 source/recommendation/evidence ids。

- [ ] 測試 adapter不重算既有結果，只投影 replay id、decision/as-of/available dates、source version、quality、missing與content hash。
- [ ] 測試缺 screening matrix、benchmark、industry benchmark時保留 immutable diagnostics，不回補舊 payload。
- [ ] 測試 `available_date > decision_date` 進 `future_blocked`，不進 effectiveness denominator。
- [ ] 實作最小 adapter與穩定 SHA-256 canonical JSON hash。
- [ ] 跑 replay、score effectiveness、look-ahead focused tests。
- [ ] Commit：`feat(evidence): adapt historical replay into rehearsal artifacts`。

### Task 4（15:30–17:30）：跨域 Rehearsal Service

**Files:**
- Create: `app_module/evidence_rehearsal_service.py`
- Create: `tests/test_evidence_rehearsal_service.py`
- Reuse: `app_module/artifact_lineage_verifier.py`

**Interfaces:**
- Consumes: scenario + replay/source/paper/health/ML adapter outputs。
- Produces: ordered report、blockers、diagnostics、artifact DAG、formal/product flags固定 false。

- [ ] 測試完整 fixture鏈：data→market→recommendation→advice→paper→health→evidence→outcome→weekly→signal→ML。
- [ ] 測試同 scenario repeat=2 hash/id/count完全相同。
- [ ] 測試 missing-day、source outage、future data、cycle與缺 parent均 fail-closed/degraded。
- [ ] 實作 orchestration；不直接 import UI、不建立 SQLite schema。
- [ ] 跑 service + lineage tests。
- [ ] Commit：`feat(evidence): orchestrate cross-domain rehearsal`。

### Day 1 Closeout（17:30–18:30）

- [ ] 執行 Day 1 focused suite：rehearsal、historical replay、lineage、source readiness、paper、health、ML available-date。
- [ ] 執行 mypy於所有 Day 1新增/修改模組。
- [ ] 執行 py_compile、quant guard、ML boundary、`git diff --check`。
- [ ] 產出 temp JSON report；確認 `formal_product_closeout=false`、`production_actions_allowed=false`。
- [ ] 若任一 Gate失敗，當日只修復根因，不提前進 Day 2。

---

## Day 2 — 新來源／ML shadow比較與運作接手

### Task 5（09:00–11:00）：P0 Source Shadow Comparison

**Files:**
- Create: `app_module/evidence_rehearsal_source_comparison.py`
- Create: `tests/test_evidence_rehearsal_source_comparison.py`
- Reuse: `data_module/p0_*_shadow_adapter.py`, `source_candidate_readiness.py`

**Interfaces:**
- Produces: per-source baseline/shadow coverage、quality、future-blocked、missing/outage與eligibility delta；eligibility固定不高於 human review。

- [ ] 測試13個P0 contract逐來源都有列，即使完全未 ingestion仍顯示 missing而非消失。
- [ ] 測試 candidate observed row不會改成 accepted或進 Scoring/Advice。
- [ ] 測試 outage/schema missing/future date產生明確 blocker與retry/quarantine提示。
- [ ] 實作 comparison projector，不修改現有 adapters。
- [ ] 跑所有 `test_p0_*`、source readiness、acceptance verifier tests。
- [ ] Commit：`feat(data): compare P0 source shadows in rehearsal`。

### Task 6（11:00–13:00）：ML Dataset / Challenger Shadow Baseline

**Files:**
- Create: `app_module/evidence_rehearsal_ml_comparison.py`
- Create: `tests/test_evidence_rehearsal_ml_comparison.py`
- Reuse: `ml_module/dataset_manifest.py`, `available_date_boundary.py`, `model_prediction_registries.py`, `drift_champion_comparison.py`

**Interfaces:**
- Produces: dataset coverage、excluded rows、mature labels、purged folds、calibration/drift diagnostics、rule-vs-challenger comparison；永遠 shadow-only。

- [ ] 測試缺值保留missingness indicator與excluded count，不靜默補值。
- [ ] 測試未成熟label與future feature不進fit/evaluation。
- [ ] 測試樣本不足時輸出 `insufficient_sample`，不訓練假模型或產生promotion建議。
- [ ] 測試 prediction registry固定 `production_action_allowed=false`。
- [ ] 實作 read-only comparison adapter；僅使用既有 ML module計算結果。
- [ ] 跑完整 `tests/test_ml_*`與boundary guard。
- [ ] Commit：`feat(ml): expose replay shadow comparison baseline`。

### Task 7（14:00–15:30）：CLI、故障注入與 Forward Handoff Package

**Files:**
- Create: `scripts/run_evidence_rehearsal.py`
- Create: `tests/test_evidence_rehearsal_cli.py`
- Create: `docs/07_guides/EVIDENCE_REHEARSAL_RUNBOOK.md`

**Interfaces:**
- CLI: `--scenario`, `--source-db`, `--working-copy-db`, `--replay-summary`, `--output-root`, `--inject-failure`。
- Failure choices: `missing_day | source_outage | future_available_date | schema_missing | immature_label`。

- [ ] 測試預設 dry/read-only、source與working-copy同路徑拒絕、production-like target拒絕。
- [ ] 測試每種 failure injection都有deterministic status/blocker，且不建立production DB或scheduler task。
- [ ] 實作CLI，輸出 `rehearsal-report.json`、`rehearsal-report.md`、`forward-handoff.json`。
- [ ] Runbook逐欄記錄 command/input/output/owner/safety/failure/rollback/completion/prohibited。
- [ ] 跑CLI subprocess tests與兩次temp working-copy smoke。
- [ ] Commit：`feat(evidence): add controlled rehearsal CLI and handoff`。

### Task 8（15:30–17:00）：Workbench / Control Center 可見性（只讀）

**Files:**
- Modify: `app_module/engineering_closure_dashboard_service.py`
- Modify: `ui_qt/views/workbench_view.py`
- Test: `tests/test_engineering_closure_dashboard_service.py`
- Test: `tests/test_ui_qt_workbench_view.py`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

**Interfaces:**
- 顯示 rehearsal tier、coverage、blockers、shadow comparison與forward pending；不提供apply/promote按鈕。

- [ ] 寫UI/service RED tests：清楚標示「工程/Replay/Shadow，不是forward evidence」。
- [ ] 實作read-only DTO projection與最小Workbench區塊。
- [ ] 驗證missing/outage/insufficient sample在UI不顯示clean/ready。
- [ ] 跑強制UI pytest、`qa_validate_update_tab.py`與全模組mypy。
- [ ] 同步Manual入口、操作、參數、結果判讀、安全、排錯。
- [ ] Commit：`feat(workbench): expose evidence rehearsal status`。

### Task 9（17:00–19:00）：文件治理與完整 Closeout

**Files:**
- Create: `docs/06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md`
- Modify: `docs/06_qa/V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `PROJECT_NAVIGATION.md`

**Interfaces:**
- Closeout只允許 `engineering_rehearsal_complete`；external register狀態不自動改成complete。

- [ ] Coverage Pass確認Snapshot/Roadmap/Architecture/Index/Manual/QA/navigation全部覆蓋。
- [ ] Patch Pass同步四層tier、實際coverage、已知missing與forward handoff。
- [ ] 執行全量：`pytest -q -o addopts=`。
- [ ] 執行全模組mypy、encoding、relative links、active index、quant guard、ML boundary、Gate 2–7 verifier、py_compile、`git diff --check`。
- [ ] 核對工作樹只含本計畫變更，所有output/DB/log/cache未stage。
- [ ] Commit：`docs(evidence): close two-day rehearsal foundation`。
- [ ] 不push，除非使用者明確要求。

## 最終交付判定

- [ ] Replay／殘缺資料能產生可重跑coverage、quality、missingness與lineage report。
- [ ] 13個P0來源即使未 ingestion也全部可見，且不會被誤標accepted。
- [ ] ML可產生dataset/readiness/shadow comparison；樣本不足時誠實defer。
- [ ] 五種故障情境均可重跑，正式來源與production boundary未被寫入。
- [ ] Workbench可看見但不能apply任何replay/shadow結果。
- [ ] Forward handoff明確列出真實時間、license與人工Gate。
- [ ] 全量驗證通過並依功能切片建立可回滾commits。

## Exact Interface / RED Test Blueprint

下列介面名稱是計畫契約，實作者不得自行改名；若既有型別衝突，先修訂本計畫再實作。

### Task 1 contract

```python
EvidenceTier = Literal[
    "engineering_fixture",
    "historical_replay_candidate",
    "shadow_comparison",
    "forward_handoff_pending",
]

@dataclass(frozen=True)
class EvidenceRehearsalScenario:
    scenario_id: str
    decision_date: str
    source_db_path: str
    working_copy_db_path: str
    tier: EvidenceTier
    production_actions_allowed: bool = False

@dataclass(frozen=True)
class CoverageMetric:
    source_id: str
    total_count: int
    observed_count: int
    degraded_count: int
    missing_count: int
    future_blocked_count: int
    immature_label_count: int
    coverage_bp: int
```

```python
def test_scenario_rejects_formal_tier_and_production_action() -> None:
    with pytest.raises(ValueError):
        EvidenceRehearsalScenario("s", "2026-07-13", "source.db", "copy.db", "forward")
    with pytest.raises(ValueError):
        EvidenceRehearsalScenario(
            "s", "2026-07-13", "source.db", "copy.db", "engineering_fixture", True
        )
```

### Task 2 contract

```python
@dataclass(frozen=True)
class CoverageObservation:
    row_id: str
    source_id: str
    source_version: str
    decision_date: str
    available_date: str | None
    quality: str
    feature_present: bool
    label_maturity_date: str | None

class EvidenceRehearsalCoverageProjector:
    def project(
        self, rows: Iterable[CoverageObservation], *, decision_date: str
    ) -> tuple[CoverageMetric, ...]: ...
```

```python
def test_future_and_immature_rows_are_not_observed() -> None:
    result = EvidenceRehearsalCoverageProjector().project(rows, decision_date="2026-07-13")[0]
    assert result.total_count == 3
    assert result.observed_count == 1
    assert result.future_blocked_count == 1
    assert result.immature_label_count == 1
    assert result.coverage_bp == 3333
```

### Task 3 contract

```python
class HistoricalReplayRehearsalAdapter:
    def project(
        self,
        replay_summary: Mapping[str, object],
        *,
        decision_date: str,
        rollback_reference: str,
    ) -> tuple[RehearsalArtifact, ...]: ...

def canonical_payload_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

```python
def test_adapter_preserves_old_payload_gaps() -> None:
    artifacts = HistoricalReplayRehearsalAdapter().project(
        {"result_id": "r1", "diagnostics": ["source_missing_screening_matrix"]},
        decision_date="2026-07-13",
        rollback_reference="commit:abc",
    )
    assert "source_missing_screening_matrix" in artifacts[0].diagnostics
    assert artifacts[0].tier == "historical_replay_candidate"
```

### Task 4 contract

```python
class EvidenceRehearsalService:
    def build(
        self,
        scenario: EvidenceRehearsalScenario,
        *,
        artifacts: Iterable[RehearsalArtifact],
        coverage: Iterable[CoverageMetric],
    ) -> EvidenceRehearsalReport: ...
```

```python
def test_repeat_build_is_deterministic() -> None:
    first = service.build(scenario, artifacts=artifacts, coverage=coverage)
    second = service.build(scenario, artifacts=artifacts, coverage=coverage)
    assert first.to_dict() == second.to_dict()
    assert first.formal_product_closeout is False
    assert first.production_actions_allowed is False
```

### Task 5 contract

```python
@dataclass(frozen=True)
class SourceShadowComparison:
    source_id: str
    contract_status: str
    baseline_coverage_bp: int
    shadow_coverage_bp: int
    missing_count: int
    future_blocked_count: int
    downstream_eligibility: str = "none"

class P0SourceShadowComparisonService:
    def compare(
        self,
        contracts: Iterable[P0SourceContract],
        observations: Iterable[P0ShadowObservation],
    ) -> tuple[SourceShadowComparison, ...]: ...
```

```python
def test_every_contract_remains_visible_without_observations() -> None:
    rows = P0SourceShadowComparisonService().compare(all_13_contracts, ())
    assert len(rows) == 13
    assert {row.downstream_eligibility for row in rows} == {"none"}
    assert all(row.missing_count >= 1 for row in rows)
```

### Task 6 contract

```python
@dataclass(frozen=True)
class MLShadowComparison:
    dataset_id: str
    total_rows: int
    accepted_rows: int
    future_blocked_rows: int
    immature_label_rows: int
    status: str
    shadow_only: bool = True
    production_action_allowed: bool = False

class MLRehearsalComparisonService:
    def compare(
        self,
        manifest: MLDatasetManifest,
        boundary_report: MLBoundaryFilterResult,
        predictions: Iterable[MLShadowPredictionRecord],
    ) -> MLShadowComparison: ...
```

```python
def test_insufficient_samples_defer_instead_of_promote() -> None:
    result = service.compare(manifest, insufficient_boundary_report, ())
    assert result.status == "insufficient_sample"
    assert result.shadow_only is True
    assert result.production_action_allowed is False
```

### Task 7 CLI contract

```python
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--working-copy-db", type=Path, required=True)
    parser.add_argument("--replay-summary", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--inject-failure",
        choices=("missing_day", "source_outage", "future_available_date", "schema_missing", "immature_label"),
    )
```

```python
def test_cli_rejects_same_source_and_working_copy(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_evidence_rehearsal.py", "--source-db", str(tmp_path / "x.db"),
         "--working-copy-db", str(tmp_path / "x.db"), "--scenario", str(scenario),
         "--replay-summary", str(summary), "--output-root", str(tmp_path / "out")],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "working-copy DB must differ" in completed.stderr
```

### Task 8 projection contract

```python
@dataclass(frozen=True)
class EvidenceRehearsalDashboard:
    tier: str
    status: str
    coverage: tuple[CoverageMetric, ...]
    blockers: tuple[str, ...]
    disclosure: str = "工程／Replay／Shadow；不是 forward evidence"
    write_intent: bool = False
```

```python
def test_dashboard_never_exposes_apply_intent() -> None:
    dashboard = service.compose(rehearsal_report)
    assert dashboard.write_intent is False
    assert "不是 forward evidence" in dashboard.disclosure
```

## Exact verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts/qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime ml_module
$closeout = Join-Path $env:TEMP "two-day-closeout.json"
$control = Join-Path $env:TEMP "two-day-control.sqlite3"
.\.venv\Scripts\python.exe scripts/verify_gate_2_to_7_closeout.py --output $closeout --gate-db $control
.\.venv\Scripts\python.exe scripts/audit_document_encoding.py
.\.venv\Scripts\python.exe scripts/quant_guard_linter.py
.\.venv\Scripts\python.exe scripts/check_ml_shadow_boundary.py
git diff --check
git status --short
```
