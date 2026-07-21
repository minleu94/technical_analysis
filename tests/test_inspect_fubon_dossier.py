# -*- coding: utf-8 -*-
"""富邦行情來源接受封包 (Source Acceptance Dossier) 唯讀盤點 CLI 工具與邏輯的單元與整合測試。

所有註解、docstring 及測試名稱均使用繁體中文。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from data_module.source_acceptance_governance import (
    SourceAcceptanceDossier,
    SourceAcceptanceGovernance,
    SourceAcceptanceDiagnosis,
)
from scripts.inspect_fubon_dossier import main, is_path_safe


def _建立候選封包(**修改參數: object) -> SourceAcceptanceDossier:
    """建立測試用的資料源接受封包基礎範例。"""
    基礎數值: dict[str, object] = {
        "source_id": "fubon.marketdata",
        "source_owner_role": "Data Source Owner",
        "license_owner_role": "License/Legal Owner",
        "license_status": "requires_review",
        "license_scope": "not_decided",
        "redistribution_policy": "not_decided",
        "source_status": "candidate",
        "publication_time_policy": "daily publication window unverified",
        "timezone": "Asia/Taipei",
        "available_date_policy": "first_observed_only_not_official_announcement",
        "revision_policy": "not_evidenced",
        "pit_coverage_window": "not_evidenced",
        "coverage_numerator": 0,
        "coverage_denominator": 36,
        "missing_policy": "degrade_preflight_and_warn",
        "row_conservation_counts": {"raw": 36, "accepted_candidate": 36},
        "quarantine_policy": "unverified",
        "quality_thresholds": {"minimum_coverage_bp": 0},
        "downstream_use_cases": ("research",),
        "disable_conditions": ("license_not_accepted", "source_acceptance_owner_review_required"),
        "rollback_reference": "decision:future-disable-revision",
        "evidence_artifact_ids": ("http:200", "parser:passed"),
        "reviewer_role": "Data Governance Owner",
        "decision_timestamp": "2026-07-21T11:28:52+08:00",
    }
    基礎數值.update(修改參數)
    return SourceAcceptanceDossier(**基礎數值)


def test_dossier_盤點缺失證據且未核准() -> None:
    """測試當封包缺少必要證據時，盤點系統能正確識別缺失，且未通過審查準備度。"""
    封包 = _建立候選封包()
    治理 = SourceAcceptanceGovernance()
    診斷 = 治理.diagnose_dossier(封包)

    assert 診斷.checklist_complete is False
    assert "license_status" in 診斷.missing_authority_evidence
    assert "coverage_bp" in 診斷.missing_programmatic_evidence
    assert "quarantine_policy" in 診斷.missing_programmatic_evidence
    assert "rollback_reference" in 診斷.missing_authority_evidence


def test_dossier_當證據齊備時通過審查準備度() -> None:
    """測試當封包補齊所有證據且無無效關鍵字時，準備度為 True。"""
    封包 = _建立候選封包(
        source_owner_role="Data Source Owner",
        license_owner_role="License/Legal Owner",
        license_status="approved",
        license_scope="research",
        redistribution_policy="internal only",
        publication_time_policy="daily publication verified",
        timezone="Asia/Taipei",
        available_date_policy="explicit available dates verified",
        revision_policy="immutable revision audit trail",
        pit_coverage_window="verified_pit_window",
        coverage_numerator=36,
        coverage_denominator=36,
        quarantine_policy="isolated to errors directory",
        quality_thresholds={"minimum_coverage_bp": 1000},
        row_conservation_counts={"raw": 36, "accepted_candidate": 36},
        downstream_eligibility="research_only",
        rollback_reference="decision:prior-approved-revision",
    )
    治理 = SourceAcceptanceGovernance()
    診斷 = 治理.diagnose_dossier(封包)

    assert 診斷.checklist_complete is True
    assert 診斷.missing_programmatic_evidence == ()
    assert 診斷.missing_authority_evidence == ()
    assert 診斷.active_blockers == ()


def test_cli_檔案不存在時回傳錯誤() -> None:
    """測試當輸入的 dossier 檔案路徑不存在時，CLI 回傳 exit code 1。"""
    結束碼 = main(["--dossier", "non_existent_file_path.json"])
    assert 結束碼 == 1


def test_cli_在合法外部shadow_root寫出範本(tmp_path: Path, capsys) -> None:
    """測試在合法且允許寫入的外部 shadow root 下成功產生範本。"""
    dossier_檔 = tmp_path / "fubon_dossier_test.json"
    template_檔 = tmp_path / "review_template_test.md"

    封包 = _建立候選封包()
    dossier_檔.write_text(json.dumps(封包.to_dict(), indent=2), encoding="utf-8")

    # template_檔 的 parent 為 tmp_path，屬於允許的外部臨時目錄
    結束碼 = main([
        "--dossier", str(dossier_檔),
        "--output-template", str(template_檔),
        "--shadow-root", str(tmp_path)
    ])

    assert 結束碼 == 0
    assert template_檔.exists()

    內容 = template_檔.read_text(encoding="utf-8")
    assert "來源接受擁有者審查範本" in 內容
    assert "證據接受檢核清單" in 內容

    # 驗證 stdout 包含正確的 Fail-Closed 狀態
    輸出 = capsys.readouterr().out
    assert "是否準備好供擁有者進行審查: False" in 輸出
    assert "status: deferred" in 輸出
    assert "downstream_eligibility: none" in 輸出


def test_cli_路徑拒絕矩陣(tmp_path: Path) -> None:
    """測試各種非法路徑的拒絕安全性檢查，確保正式目錄與不合規路徑均被阻擋。"""
    dossier_檔 = tmp_path / "fubon_dossier_test.json"
    封包 = _建立候選封包()
    dossier_檔.write_text(json.dumps(封包.to_dict(), indent=2), encoding="utf-8")

    # 模擬 DATA_ROOT
    DATA_ROOT = os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")

    # A. 拒絕僅提供 --output-template 但未提供 --shadow-root 的情況
    結束碼 = main([
        "--dossier", str(dossier_檔),
        "--output-template", str(tmp_path / "template.md")
    ])
    assert 結束碼 == 1

    # B. 拒絕 DATA_ROOT 與其子路徑
    結束碼 = main([
        "--dossier", str(dossier_檔),
        "--output-template", f"{DATA_ROOT}/template.md",
        "--shadow-root", DATA_ROOT
    ])
    assert 結束碼 == 1

    # C. 拒絕 repo 根目錄與其子路徑
    repo_root = Path(__file__).resolve().parents[1]
    結束碼 = main([
        "--dossier", str(dossier_檔),
        "--output-template", f"{repo_root}/template.md",
        "--shadow-root", str(repo_root)
    ])
    assert 結束碼 == 1

    # D. 拒絕相對路徑
    結束碼 = main([
        "--dossier", str(dossier_檔),
        "--output-template", "relative_dir/template.md",
        "--shadow-root", str(tmp_path)
    ])
    assert 結束碼 == 1

    # E. 拒絕不在 shadow_root 內的 nonexistent parent
    外部不存在路徑 = Path("C:/InvalidNonexistentPath/template.md")
    結束碼 = main([
        "--dossier", str(dossier_檔),
        "--output-template", str(外部不存在路徑),
        "--shadow-root", str(tmp_path)
    ])
    assert 結束碼 == 1


def test_fubon_投影檔等價_fixture_驗證與斷言() -> None:
    """使用真正的 Fubon dossier projection 等價 fixture 測試，驗證檢核與阻擋器完全一致。"""
    等價_fixture = _建立候選封包(
        available_date_policy="first_observed_only_not_official_announcement",
        coverage_denominator=36,
        coverage_numerator=0,
        license_status="requires_review",
        license_scope="not_decided",
        pit_coverage_window="not_evidenced",
        publication_time_policy="daily publication window unverified",
        quarantine_policy="unverified",
        redistribution_policy="not_decided",
        revision_policy="not_evidenced",
        rollback_reference="decision:future-disable-revision",
        timezone="Asia/Taipei"
    )

    治理 = SourceAcceptanceGovernance()
    診斷 = 治理.diagnose_dossier(等價_fixture)

    # 驗證指定 5 個欄位皆為 FAIL (非 verified)
    檢核結果 = {item["name"]: item["status"] for item in 診斷.checklist}
    assert 檢核結果["publication_time_policy"] != "verified"
    assert 檢核結果["available_date_policy"] != "verified"
    assert 檢核結果["pit_coverage_window"] != "verified"
    assert 檢核結果["revision_policy"] != "verified"
    assert 檢核結果["quarantine_policy"] != "verified"

    # 斷言其對應的 blockers 均完整出現在 active_blockers
    assert "missing_publication_time_policy" in 診斷.active_blockers
    assert "missing_available_date_policy" in 診斷.active_blockers
    assert "missing_revision_policy" in 診斷.active_blockers
    assert "missing_pit_coverage" in 診斷.active_blockers
    assert "missing_quarantine_policy" in 診斷.active_blockers

    # 同時驗證詳細資訊中包含明確的缺失原因
    詳細欄位 = {item["name"]: item["detail"] for item in 診斷.checklist}
    assert "缺失原因: 包含未驗證/無效關鍵字" in 詳細欄位["publication_time_policy"]
    assert "缺失原因: 包含 first_observed_only 或 not_official_announcement" in 詳細欄位["available_date_policy"]
    assert "缺失原因: 未能證明 PIT 覆蓋" in 詳細欄位["pit_coverage_window"]
    assert "缺失原因: 未能證明修訂機制" in 詳細欄位["revision_policy"]
    assert "缺失原因: 未驗證隔離機制" in 詳細欄位["quarantine_policy"]


def test_coverage_數值極端邊界安全() -> None:
    """測試覆蓋率計算之極端情況：分母為 0、分子為負、分子大於分母、門檻非整數或負數。"""
    治理 = SourceAcceptanceGovernance()

    # A. 分母為 0
    封包_分母0 = _建立候選封包(coverage_numerator=10, coverage_denominator=0)
    診斷 = 治理.diagnose_dossier(封包_分母0)
    檢核結果 = {item["name"]: item for item in 診斷.checklist}
    assert 檢核結果["coverage_bp"]["status"] != "verified"
    assert "分母必須大於 0" in 檢核結果["coverage_bp"]["detail"]
    assert "missing_coverage_bp" in 診斷.active_blockers

    # B. 分子為負數
    封包_分子負 = _建立候選封包(coverage_numerator=-5, coverage_denominator=36)
    診斷 = 治理.diagnose_dossier(封包_分子負)
    檢核結果 = {item["name"]: item for item in 診斷.checklist}
    assert 檢核結果["coverage_bp"]["status"] != "verified"
    assert "分子不得為負數" in 檢核結果["coverage_bp"]["detail"]
    assert "missing_coverage_bp" in 診斷.active_blockers

    # C. 分子大於分母
    封包_分子大 = _建立候選封包(coverage_numerator=40, coverage_denominator=36)
    診斷 = 治理.diagnose_dossier(封包_分子大)
    檢核結果 = {item["name"]: item for item in 診斷.checklist}
    assert 檢核結果["coverage_bp"]["status"] != "verified"
    assert "分子不得大於分母" in 檢核結果["coverage_bp"]["detail"]
    assert "missing_coverage_bp" in 診斷.active_blockers

    # D. 品質門檻為負數
    封包_門檻負 = _建立候選封包(
        coverage_numerator=36, coverage_denominator=36,
        quality_thresholds={"minimum_coverage_bp": -100}
    )
    診斷 = 治理.diagnose_dossier(封包_門檻負)
    檢核結果 = {item["name"]: item for item in 診斷.checklist}
    assert 檢核結果["coverage_bp"]["status"] != "verified"
    assert "品質門檻最低覆蓋基點必須為非負整數" in 檢核結果["coverage_bp"]["detail"]
    assert "missing_coverage_bp" in 診斷.active_blockers

    # E. 品質門檻非整數
    封包_門檻非整數 = _建立候選封包(
        coverage_numerator=36, coverage_denominator=36,
        quality_thresholds={"minimum_coverage_bp": "not_an_int"}
    )
    診斷 = 治理.diagnose_dossier(封包_門檻非整數)
    檢核結果 = {item["name"]: item for item in 診斷.checklist}
    assert 檢核結果["coverage_bp"]["status"] != "verified"
    assert "品質門檻最低覆蓋基點必須為非負整數" in 檢核結果["coverage_bp"]["detail"]
    assert "missing_coverage_bp" in 診斷.active_blockers


def test_不變量之完全安全防禦() -> None:
    """測試不變量：即便所有欄位看似完美且完全驗證，診斷與評估結果依然為 deferred、eligibility none。"""
    完全封包 = _建立候選封包(
        source_owner_role="Data Source Owner",
        license_owner_role="License/Legal Owner",
        license_status="approved",
        license_scope="research",
        redistribution_policy="internal only",
        publication_time_policy="daily publication verified",
        timezone="Asia/Taipei",
        available_date_policy="explicit available dates verified",
        revision_policy="immutable revision audit trail",
        pit_coverage_window="verified_pit_window",
        coverage_numerator=36,
        coverage_denominator=36,
        quarantine_policy="isolated to errors directory",
        quality_thresholds={"minimum_coverage_bp": 1000},
        row_conservation_counts={"raw": 36, "accepted_candidate": 36},
        downstream_eligibility="research_only",
        rollback_reference="decision:prior-approved-revision",
    )
    治理 = SourceAcceptanceGovernance()
    診斷 = 治理.diagnose_dossier(完全封包)

    # 即使 checklist 完整 (checklist_complete 為 True)
    assert 診斷.checklist_complete is True

    # 輸出狀態與下游權限依然被鎖死
    assert 診斷.status == "deferred"
    assert 診斷.allowed_use_cases == ()
    assert 診斷.downstream_eligibility == "none"

    # evaluate 方法同樣被 source_acceptance_not_authorized 鎖定
    評估決議 = 治理.evaluate(完全封包)
    assert 評估決議.status == "deferred"
    assert 評估決議.allowed_use_cases == ()
    assert "source_acceptance_not_authorized" in 評估決議.blockers
