"""TASK-05 雙根離線驗收；只建立隔離 fixture，不修改正式 Registry 或信用。"""
from __future__ import annotations

from dataclasses import asdict, replace
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import mkdtemp
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.research_run_comparison_service import ComparabilityStatus, ResearchRunComparisonService
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_repository import ResearchRunConflictError
from app_module.research_run_service import InjectedResearchRunFailure, ResearchRunIntegrityError, ResearchRunService
from data_module.config import TWStockConfig


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    task_root = (ROOT / "output/master_goal/TASK-LOOP-05").resolve()
    roots: dict[str, Path] = {}
    for variable, expected in (("DATA_ROOT", "data"), ("OUTPUT_ROOT", "artifacts")):
        value = os.environ.get(variable, "")
        if not value or Path(value).resolve() != task_root / expected:
            raise RuntimeError(f"{variable} 必須明確設為 TASK-LOOP-05/{expected}")
        roots[variable] = Path(value).resolve()
        roots[variable].mkdir(parents=True, exist_ok=True)
    if os.environ.get("PROFILE") != "test":
        raise RuntimeError("PROFILE 必須為 test")
    results: list[dict[str, Any]] = []
    # 保留本輪隔離 fixture 供覆盤；不遞迴刪除仍可能持有 logger 的目錄。
    with nullcontext(mkdtemp(prefix="registry_fixture_", dir=roots["DATA_ROOT"])) as data_dir, \
         nullcontext(mkdtemp(prefix="registry_fixture_", dir=roots["OUTPUT_ROOT"])) as output_dir:
        config = TWStockConfig(data_root=Path(data_dir), output_root=Path(output_dir))
        assert config.db_file.resolve().is_relative_to(roots["DATA_ROOT"])
        assert config.research_run_db_file.resolve().is_relative_to(roots["OUTPUT_ROOT"])
        service = ResearchRunService(config)
        equity = pd.DataFrame({"date": ["2026-01-02", "2026-01-05"], "portfolio_value": [100000, 100500]})
        trades = pd.DataFrame({"date": ["2026-01-05"], "shares": [1000], "price_cents": [10000]})
        base = ResearchRunMetadataDTO("qa", "隔離 Registry QA", "single_backtest", payload_hash="sha256:fixture",
                                      execution_price="next-session-open.v2", created_at="2026-01-06T12:00:00")
        stages = ("after_staging_row", "after_temp_write", "after_hash", "after_first_rename", "after_second_rename", "before_final_commit")
        for stage in stages:
            run = replace(base, run_id=stage)
            try:
                service.save_run(run, equity, trades, fail_at=stage)
            except InjectedResearchRunFailure:
                pass
            else:
                raise AssertionError(f"missing injected failure: {stage}")
            before = digest(config.research_run_db_file)
            query = ResearchRunService(config)
            assert stage not in {item.run_id for item in query.list_runs()}
            try:
                query.load_run_data(stage)
            except ResearchRunIntegrityError:
                pass
            else:
                raise AssertionError("半成品被載入")
            assert digest(config.research_run_db_file) == before
            query.reconcile_incomplete_saves()
            state = query.repository.get_raw_metadata_row(stage)["storage_state"]
            assert state == ("failed" if stage in stages[:2] else "committed")
            if state == "committed":
                assert query.load_run_data(stage).equity.equals(equity)
            results.append({"check": stage, "passed": True, "recovery_state": state, "query_read_only": True})
        saved = service.save_run(base, equity, trades)
        assert service.save_run(base, equity, trades) == saved
        try:
            service.save_run(replace(base, payload_hash="sha256:different"), equity, trades)
        except ResearchRunConflictError:
            pass
        else:
            raise AssertionError("異 hash 未拒絕")
        compare = ResearchRunComparisonService().evaluate_comparability([
            saved, replace(saved, execution_price="legacy-same-day-close.v1",
                           data_manifest={"execution_contract": "legacy-same-day-close.v1"})])
        assert compare.status == ComparabilityStatus.INCOMPATIBLE
        results.append({"check": "idempotency_and_version_isolation", "passed": True})
        evidence = EvidenceEventService(EvidenceEventRepository(config))
        event = evidence.record_event(event_date="2026-01-02", decision_date="2026-01-02", symbol="2330",
            event_type="recommendation_included", event_family="recommendation", source_type="fixture",
            run_id="qa", source_snapshot_id="fixture-recommendation", as_of_date="2026-01-02",
            available_date="2026-01-02", evidence_tier="replay")
        before = digest(config.db_file)
        proposal = evidence.build_review_proposal("qa")
        assert proposal.evidence[0]["event_id"] == event.event_id
        assert not proposal.formal_credit_granted and not proposal.promotion_allowed
        assert digest(config.db_file) == before
        results.append({"check": "review_lineage_without_credit", "passed": True,
                        "proposal": asdict(proposal)})
        Path(saved.trades_path).write_bytes(b"isolated corruption")
        try:
            service.load_run_data("qa")
        except ResearchRunIntegrityError:
            pass
        else:
            raise AssertionError("損毀未拒絕")
        results.append({"check": "corruption_rejected", "passed": True})
    output = roots["OUTPUT_ROOT"] / "_test/qa/research_registry_loop/VALIDATION_REPORT.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"task": "TASK-LOOP-05", "fixture_only": True, "formal_credit_granted": False,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "qa_source_sha256": digest(Path(__file__)),
              "contract_source_sha256": digest(ROOT / "tests/test_task_loop_05_contract.py"),
              "data_root": str(roots["DATA_ROOT"]), "output_root": str(roots["OUTPUT_ROOT"]),
              "fixture_data_root": data_dir, "fixture_output_root": output_dir,
              "passed": len(results), "failed": 0, "checks": results}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TASK-LOOP-05: {len(results)} passed / 0 failed; {output}; sha256={digest(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
