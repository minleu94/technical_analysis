# V2.2 Simulated Phase Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only `simulated_phase_progress` inspector that labels historical replay and scheduled dry-run evidence from Phase 0 through simulated Phase 5 without changing official lifecycle or scheduler gates.

**Architecture:** Add a focused application service that consumes existing JSON/Markdown evidence artifacts and Pre-V2 readiness data, then returns immutable DTOs with explicit replay-only tags. Add a CLI wrapper that emits JSON or Markdown and never runs replay, scheduler, or DB writes. Keep the official Pre-V2 readiness service unchanged.

**Tech Stack:** Python dataclasses, argparse CLI, pathlib/json/sqlite read-only dependencies through existing services, pytest subprocess CLI tests.

## Global Constraints

- 回覆與文件使用繁體中文。
- 保持 read-only：不啟用 scheduler、不寫 formal DB、不跑 replay、不用 fixture/manual edit 補 official gate。
- 所有 replay-derived evidence 必須標註 `official_gate_credit=false` 與 `requires_real_world_validation=true`。
- simulated Phase 5 可為 `simulated_ready`，但 official Phase 5 必須保持 `blocked` 或 `official_gate_not_satisfied`。
- Runtime output 不得輸出 `official_ready`、`phase_complete`、`scheduler_approved`、`production_ready`。
- 不產生買賣、倉位、策略有效性或投資建議。
- 不 stage 或修改既有非本任務 dirty files：`app_module/update_service.py`、`tests/test_update_service_status.py`、`ui_qt/main.py`。

---

## File Structure

- Create `app_module/simulated_phase_progress_service.py`: DTOs, JSON/Markdown artifact readers, phase classification, replay/dry-run tag generation, Markdown renderer.
- Create `scripts/inspect_simulated_phase_progress.py`: read-only CLI for JSON/Markdown output.
- Create `tests/test_simulated_phase_progress_service.py`: service behavior, official gate isolation, replay tag assertions.
- Create `tests/test_simulated_phase_progress_cli.py`: subprocess CLI behavior and no-write checks.
- Modify `docs/00_core/DOCUMENTATION_INDEX.md`: add the new QA note.
- Create `docs/06_qa/V2_2_SIMULATED_PHASE_PROGRESS_QA_2026_07_07.md`: closeout, replay labels, true-data validation checklist.

## Task 1: Service DTOs And Phase Report

**Files:**
- Create: `tests/test_simulated_phase_progress_service.py`
- Create: `app_module/simulated_phase_progress_service.py`

**Interfaces:**
- Consumes: `PreV2ReadinessService.inspect(...) -> PreV2ReadinessReport`
- Produces: `SimulatedPhaseProgressService.build_report(...) -> SimulatedPhaseProgressReport`
- Produces: `render_simulated_phase_progress_markdown(report: SimulatedPhaseProgressReport) -> str`

- [ ] **Step 1: Write failing service tests**

```python
def test_simulated_phase_report_marks_replay_and_keeps_official_gate_blocked(tmp_path: Path) -> None:
    config = _config(tmp_path)
    replay_summary = tmp_path / "replay.json"
    _write_replay_summary(replay_summary, days=3, events_seen=12, outcomes_created=4)
    scheduled_root = tmp_path / "output" / "scheduled" / "evidence_pipeline_dry_run"
    _write_scheduled_status(scheduled_root, decision_date="2026-07-07")
    record_path = tmp_path / "multi-day.md"
    _write_multi_day_record(record_path, rows=1)

    report = SimulatedPhaseProgressService(config, evidence_db_path=tmp_path / "missing.db").build_report(
        decision_date="2026-07-07",
        replay_summary_path=replay_summary,
        scheduled_output_root=scheduled_root,
        multi_day_record_path=record_path,
    )

    assert report.production_scheduler_allowed is False
    assert report.official_phase_5_status == "blocked"
    assert report.replay_tags.official_gate_credit is False
    assert report.replay_tags.requires_real_world_validation is True
    assert report.replay_tags.replay_mode == "historical_replay"
    assert report.replay_tags.source_label == "simulated_scheduler"
    assert {item.phase_id for item in report.items} == {"phase_0", "phase_1", "phase_2", "phase_3", "phase_4", "phase_5"}
    assert report.items[-1].simulated_status == "simulated_ready"
    assert report.items[-1].official_status == "official_gate_not_satisfied"
```

- [ ] **Step 2: Run service test to verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_simulated_phase_progress_service.py -q -o addopts=`

Expected: FAIL with `ModuleNotFoundError` or import error for `app_module.simulated_phase_progress_service`.

- [ ] **Step 3: Implement minimal service**

Create immutable dataclasses:

```python
@dataclass(frozen=True)
class ReplayEvidenceTagSummary:
    replay_mode: str
    source_label: str
    replay_run_id: str | None
    replay_decision_dates: tuple[str, ...]
    replay_data_as_of_dates: tuple[str, ...]
    official_gate_credit: bool = False
    requires_real_world_validation: bool = True
```

Create `SimulatedPhaseProgressItem`, `RealWorldValidationPlan`, `SimulatedPhaseProgressReport`, `_load_json`, `_summarize_replay`, `_summarize_scheduled_status`, `_official_status_from_pre_v2`, `_phase_items`, and `render_simulated_phase_progress_markdown`.

- [ ] **Step 4: Run service test to verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_simulated_phase_progress_service.py -q -o addopts=`

Expected: PASS.

- [ ] **Step 5: Commit service**

```powershell
git add app_module/simulated_phase_progress_service.py tests/test_simulated_phase_progress_service.py
git diff --cached --check
git commit -m "feat: add simulated phase progress service"
```

## Task 2: CLI JSON And Markdown

**Files:**
- Create: `tests/test_simulated_phase_progress_cli.py`
- Create: `scripts/inspect_simulated_phase_progress.py`

**Interfaces:**
- Consumes: `SimulatedPhaseProgressService.build_report(...)`
- Produces CLI args: `--replay-summary-path`, `--scheduled-output-root`, `--db-path`, `--decision-date`, `--multi-day-record-path`, `--json-output`, `--markdown`, `--report-output`, `--data-root`, `--output-root`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_simulated_phase_progress_cli_emits_json_without_creating_missing_db(tmp_path: Path) -> None:
    replay_summary = tmp_path / "replay.json"
    _write_replay_summary(replay_summary)
    scheduled_root = tmp_path / "output" / "scheduled" / "evidence_pipeline_dry_run"
    _write_scheduled_status(scheduled_root)
    missing_db = tmp_path / "missing" / "evidence.db"

    result = _run_cli(
        tmp_path,
        "--db-path", str(missing_db),
        "--replay-summary-path", str(replay_summary),
        "--scheduled-output-root", str(scheduled_root),
        "--decision-date", "2026-07-07",
        "--json-output",
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["production_scheduler_allowed"] is False
    assert payload["official_phase_5_status"] == "blocked"
    assert payload["replay_tags"]["official_gate_credit"] is False
    assert not missing_db.exists()
```

- [ ] **Step 2: Run CLI test to verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_simulated_phase_progress_cli.py -q -o addopts=`

Expected: FAIL because `scripts/inspect_simulated_phase_progress.py` does not exist.

- [ ] **Step 3: Implement CLI**

Implement `build_parser()`, `_config_from_args()`, `main(argv=None)`, UTF-8 stdout/stderr reconfigure, JSON output through `report.to_dict()`, Markdown output through `render_simulated_phase_progress_markdown(report)`, and optional `--report-output` file writing only when explicit.

- [ ] **Step 4: Run CLI tests to verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_simulated_phase_progress_cli.py tests\test_simulated_phase_progress_service.py -q -o addopts=`

Expected: PASS.

- [ ] **Step 5: Commit CLI**

```powershell
git add scripts/inspect_simulated_phase_progress.py tests/test_simulated_phase_progress_cli.py
git diff --cached --check
git commit -m "feat: add simulated phase progress cli"
```

## Task 3: Documentation And QA Closeout

**Files:**
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Create: `docs/06_qa/V2_2_SIMULATED_PHASE_PROGRESS_QA_2026_07_07.md`

**Interfaces:**
- Consumes: CLI output and service report semantics.
- Produces: Durable note explaining replay labels and real-data validation steps.

- [ ] **Step 1: Write QA note**

The QA note must include:

```markdown
# V2.2 Simulated Phase Progress QA - 2026-07-07

## 結論

- historical replay 可用於 simulated Phase 0-5 演練。
- official Phase 0 weekly history 與 multi-day dry-run gate 不因 replay 改變。
- production_scheduler_allowed=false。

## Replay 標註

| 標註 | 值 | 意義 |
|---|---|---|
| replay_mode | historical_replay | 歷史重放，不是真實排程 |
| source_label | simulated_scheduler | 模擬 scheduler，不是 production scheduler |
| official_gate_credit | false | 不計入正式 gate |
| requires_real_world_validation | true | 後續需要真實時間資料補強 |
```

- [ ] **Step 2: Update documentation index**

Add the QA note under V2.2 / QA evidence references without changing lifecycle status.

- [ ] **Step 3: Run docs and focused QA**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_simulated_phase_progress_service.py tests\test_simulated_phase_progress_cli.py tests\test_pre_v2_readiness_service.py tests\test_pre_v2_readiness_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\simulated_phase_progress_service.py scripts\inspect_simulated_phase_progress.py
git diff --check
```

Expected: PASS and clean diff check for staged task files.

- [ ] **Step 4: Commit docs**

```powershell
git add docs/00_core/DOCUMENTATION_INDEX.md docs/06_qa/V2_2_SIMULATED_PHASE_PROGRESS_QA_2026_07_07.md
git diff --cached --check
git commit -m "docs: document simulated phase progress validation"
```

## Task 4: Final Verification

**Files:**
- No new files.

**Interfaces:**
- Consumes all prior commits.
- Produces final command evidence and user-facing summary.

- [ ] **Step 1: Run focused final QA**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_simulated_phase_progress_service.py tests\test_simulated_phase_progress_cli.py tests\test_pre_v2_readiness_service.py tests\test_pre_v2_readiness_cli.py tests\test_replay_historical_evidence_pipeline_cli.py tests\test_historical_evidence_replay.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\simulated_phase_progress_service.py scripts\inspect_simulated_phase_progress.py
git show --check --stat --oneline HEAD
git status --short
```

Expected: pytest PASS, py_compile PASS, latest commit has no whitespace errors, and only pre-existing unrelated dirty files remain outside this task.

- [ ] **Step 2: Summarize commits and next real-data validation**

Final response must list each commit, describe replay labels, explain that official Phase 5 is still blocked until real weekly/multi-day/manual gates pass, and provide the next real-data checklist.
