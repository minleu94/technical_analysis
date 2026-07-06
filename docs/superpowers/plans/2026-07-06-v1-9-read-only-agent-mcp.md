# V1.9 Read-only Agent MCP Evidence Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 V1.9 Read-only Agent / MCP Evidence Access，提供 evidence / research run / portfolio review saved evidence 查詢與 AI report template，並完成分段 commit。

**Architecture:** 新增 app-layer service 作為唯一業務入口；MCP server 只包裝 service，不直接寫 DB。Evidence event 使用既有 read-only repository；research run / portfolio review saved evidence 使用 SQLite `mode=ro` 與 `PRAGMA query_only=ON`。

**Tech Stack:** Python dataclasses / sqlite3 / pytest / FastMCP fallback wrapper / 現有 TWStockConfig。

---

## File Structure

- Create: `app_module/agent_evidence_access_service.py`
- Create: `mcp_servers/evidence_access_server.py`
- Create: `tests/test_v1_9_agent_evidence_access.py`
- Modify: `mcp_servers/README.md`
- Modify active docs: Snapshot、Roadmap Hub、6M Roadmap、Version Roadmap、External Reference Blueprint、Architecture、Manual、Documentation Index、Skills Registry。
- Add QA closeout: `docs/06_qa/V1_9_READ_ONLY_AGENT_MCP_CLOSEOUT_2026_07_06.md`

## Task 1: Design Commit

- [x] Write design doc at `docs/superpowers/specs/2026-07-06-v1-9-read-only-agent-mcp-design.md`.
- [x] Write implementation plan at `docs/superpowers/plans/2026-07-06-v1-9-read-only-agent-mcp.md`.
- [ ] Commit design and plan.

## Task 2: TDD Guardrails

- [ ] Write failing tests in `tests/test_v1_9_agent_evidence_access.py`:

```python
def test_permission_model_is_read_only_and_denies_trading_actions():
    model = build_agent_permission_model()
    assert model["access_mode"] == "read_only"
    assert "write_database" in model["denied_actions"]
    assert "place_order" in model["denied_actions"]
```

```python
def test_evidence_query_returns_events_outcomes_and_source_trace(tmp_path):
    # Arrange test DB with EvidenceEventRepository.
    # Act through AgentEvidenceAccessService.
    # Assert event rows, outcomes, data quality and source trace are present.
```

```python
def test_missing_research_db_returns_diagnostics_without_creating_file(tmp_path):
    service = AgentEvidenceAccessService(config, research_db_path=tmp_path / "missing.sqlite")
    payload = service.query_research_runs(limit=5)
    assert payload["diagnostics"]
    assert not (tmp_path / "missing.sqlite").exists()
```

```python
def test_portfolio_review_query_reads_saved_gap_and_lifecycle_evidence(tmp_path):
    # Arrange persisted live_research_gap_observations and strategy_lifecycle_evidence.
    # Act through AgentEvidenceAccessService.query_portfolio_review_evidence.
    # Assert both evidence collections are returned and marked saved-evidence-only.
```

- [ ] Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v1_9_agent_evidence_access.py -q -o addopts=
```

Expected: fails with missing module/classes.

## Task 3: App-layer Read-only Service

- [ ] Implement `build_agent_permission_model()`.
- [ ] Implement `build_ai_report_template()`.
- [ ] Implement `AgentEvidenceAccessService.query_evidence_events(...)`.
- [ ] Implement `AgentEvidenceAccessService.summarize_forward_evidence(...)`.
- [ ] Implement `AgentEvidenceAccessService.query_research_runs(...)`.
- [ ] Implement `AgentEvidenceAccessService.query_portfolio_review_evidence(...)`.
- [ ] Run focused pytest until GREEN.

Commit:

```powershell
git add app_module/agent_evidence_access_service.py tests/test_v1_9_agent_evidence_access.py
git commit -m "feat: add v1.9 read-only evidence access service"
```

## Task 4: MCP Tool Surface

- [ ] Implement `mcp_servers/evidence_access_server.py` with FastMCP tools:
  - `get_agent_permission_model`
  - `get_ai_report_template`
  - `query_evidence_events`
  - `summarize_forward_evidence`
  - `query_research_runs`
  - `query_portfolio_review_evidence`
- [ ] Add a smoke import test or include MCP module in `py_compile`.

Commit:

```powershell
git add mcp_servers/evidence_access_server.py
git commit -m "feat: expose v1.9 evidence access mcp server"
```

## Task 5: Documentation / QA Closeout

- [ ] Update active docs listed in File Structure.
- [ ] Add QA closeout with commands and results.
- [ ] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v1_9_agent_evidence_access.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module/agent_evidence_access_service.py mcp_servers/evidence_access_server.py
.\.venv\Scripts\python.exe scripts/quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

- [ ] Commit docs:

```powershell
git add mcp_servers/README.md docs/00_core docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md docs/agents/skills_registry.md docs/06_qa/V1_9_READ_ONLY_AGENT_MCP_CLOSEOUT_2026_07_06.md
git commit -m "docs: close out v1.9 read-only agent mcp"
```
