# V1.1 Decision Workflow Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 V1.1 的每日決策到推薦策略驗證 workflow bridge，補齊 Profile Replay Comparison 的服務邊界與可見 Profile 差異。

**Architecture:** 新增一個 application service 聚合多個 Recommendation Profile 的推薦回放結果，UI 只讀 DTO 與摘要。V1.1 不套用自動 demote / retire；只提供人工覆盤候選與導引。

**Tech Stack:** Python、PySide6、pytest、mypy、既有 `app_module` service / DTO / repository pattern。

---

## File Map

- Create: `app_module/profile_replay_comparison_dtos.py`
  - 定義 Profile comparison request / row / result DTO。
- Create: `app_module/profile_replay_comparison_service.py`
  - 對多個 Profile 執行共同 replay runner，產生 comparison result。
- Modify: `ui_qt/views/recommendation_view.py`
  - 強化 Profile 摘要，讓權重、指標、型態與主要 filter 可見。
- Test: `tests/test_profile_replay_comparison_service.py`
  - 服務層 TDD tests。
- Test: `tests/test_ui_qt_recommendation_profiles.py`
  - Profile 摘要 UI tests。
- Later checkpoint docs only after V1.1 complete:
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`

---

## Task 1: Profile Replay Comparison DTOs and Service

**Files:**
- Create: `app_module/profile_replay_comparison_dtos.py`
- Create: `app_module/profile_replay_comparison_service.py`
- Test: `tests/test_profile_replay_comparison_service.py`

- [ ] **Step 1: Write failing tests**

Add tests that use fake profiles and a fake replay runner. The fake runner returns deterministic metrics per profile. Tests must cover:

```python
def test_compare_profiles_ranks_rows_and_marks_promote_candidate():
    ...

def test_compare_profiles_marks_insufficient_evidence_when_trade_count_low():
    ...

def test_compare_profiles_marks_demote_candidate_for_negative_excess_and_large_drawdown():
    ...
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_profile_replay_comparison_service.py -q -o addopts=
```

Expected: import failure for missing `app_module.profile_replay_comparison_service`.

- [ ] **Step 3: Implement DTOs**

Create dataclasses:

```python
@dataclass(frozen=True)
class ProfileReplayComparisonRequest:
    start_date: str
    end_date: str
    rebalance_frequency: str = "weekly"
    holding_days: int = 20
    top_n: int = 10
    benchmark_id: str = "taiex"

@dataclass(frozen=True)
class ProfileReplayComparisonRow:
    profile_id: str
    profile_name: str
    profile_version: str
    applicable_regimes: tuple[str, ...]
    total_return_bp: int | None
    benchmark_excess_bp: int | None
    max_drawdown_bp: int | None
    trade_count: int
    quality: str
    warnings: tuple[str, ...]
    lifecycle_candidate: str
```

- [ ] **Step 4: Implement service**

`ProfileReplayComparisonService` accepts `profile_service` and `replay_runner`. It calls `profile_service.list_profiles()`, passes each profile to the runner, normalizes metrics using integer basis points, and assigns lifecycle candidates:

- `insufficient_evidence` when `trade_count < min_trades` or benchmark excess is missing.
- `promote_candidate` when excess return >= 0, drawdown <= max promote drawdown, quality is not missing/degraded.
- `demote_candidate` when excess return < 0 or drawdown exceeds demote threshold.
- `retire_candidate` when excess return <= -1000 bp and drawdown exceeds retire threshold.
- otherwise `hold`.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_profile_replay_comparison_service.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add app_module/profile_replay_comparison_dtos.py app_module/profile_replay_comparison_service.py tests/test_profile_replay_comparison_service.py
git commit -m "feat: add profile replay comparison service"
git push origin dev
```

---

## Task 2: Recommendation Profile Details Visibility

**Files:**
- Modify: `ui_qt/views/recommendation_view.py`
- Test: `tests/test_ui_qt_recommendation_profiles.py`

- [ ] **Step 1: Write failing UI test**

Add a test selecting built-in `momentum` and asserting the description text includes:

- `型態`
- `技術`
- `量能`
- `主要篩選`
- `漲幅`
- `量能`
- at least one selected pattern name

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_profiles.py -q -o addopts=
```

Expected: fails because current summary does not include the richer filter / pattern text.

- [ ] **Step 3: Implement richer summary**

Update `_profile_advanced_summary()` to include:

- normalized weight text, displaying `2500bp` style when values are integers and `%` style when legacy floats are present.
- technical categories.
- selected pattern names up to 5 items plus count.
- filters: `price_change_min`, `price_change_max`, `volume_ratio_min`, and `industry` when present.

- [ ] **Step 4: Run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_profiles.py -q -o addopts=
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add ui_qt/views/recommendation_view.py tests/test_ui_qt_recommendation_profiles.py
git commit -m "feat: show recommendation profile details"
git push origin dev
```

---

## Task 3: Workflow Bridge QA and Documentation Checkpoint

**Files:**
- Modify after implementation checkpoint only:
  - `docs/07_guides/APPLICATION_MANUAL.md`
  - `docs/00_core/PROJECT_SNAPSHOT.md`
  - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`

- [ ] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_profile_replay_comparison_service.py tests\test_ui_qt_recommendation_profiles.py -q -o addopts=
```

- [ ] **Step 2: Run UI required tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

- [ ] **Step 3: Run type and syntax checks**

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe -m py_compile app_module\profile_replay_comparison_dtos.py app_module\profile_replay_comparison_service.py ui_qt\views\recommendation_view.py
```

- [ ] **Step 4: Update checkpoint docs**

Only after the implementation and QA evidence exist, update Manual / Snapshot / Roadmap / Version Roadmap with the V1.1 completed status and limitations.

- [ ] **Step 5: Commit and push V1.1 checkpoint**

```powershell
git add docs/07_guides/APPLICATION_MANUAL.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md
git commit -m "docs: record v1.1 workflow checkpoint"
git push origin dev
```

---

## Self-Review

- Spec coverage: covers V1.1 workflow bridge, Profile visibility, Profile Replay Comparison, evidence-only lifecycle candidate language, and documentation checkpoint timing.
- Placeholder scan: no `TBD` or open-ended implementation placeholders remain.
- Type consistency: DTO and service names are consistent across tasks.
- Scope check: automatic demote / retire, production scheduler, V2.0 unified workbench, and ScoringEngine expansion remain outside V1.1.
