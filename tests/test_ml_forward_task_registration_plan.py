from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "scripts" / "scheduled" / "ml_forward_task_registration_plan.json"
XML = ROOT / "scripts" / "scheduled" / "ml_forward_task_registration.xml"
NS = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def test_forward_registration_plan_is_registered_and_pinned() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))

    assert plan["status"] == "registered_verified"
    assert plan["task_name"] == "baldr-ml-allocation-forward-daily"
    assert plan["host_timezone"] == "Pacific Standard Time"
    assert plan["schedule"]["pacific_local_time"] == "16:15"
    assert plan["settings"]["multiple_instances"] == "IgnoreNew"
    assert plan["settings"]["execution_time_limit"] == "PT2H"
    assert plan["forward_environment"]["ML_FORWARD_OUTPUT_ROOT"].endswith(
        "v4_ml_daily_derived_shadow_real_v2"
    )
    assert plan["forward_environment"]["ML_FORWARD_PAPER_STATE_DB"].endswith(
        "paper_portfolio.sqlite"
    )
    assert plan["forward_environment"]["BALDR_ML_RELEASE_ROOT"].endswith(
        "v4_ml_derived_h5_20260907_real_v2"
    )
    assert plan["forward_environment"]["BALDR_ML_RELEASE_MANIFEST_FILE_HASH"] == (
        "sha256:c306c1ea53ccef112204a8412a605b575e4d107b4503b2b5be5d6d5ee50910ea"
    )
    registration = plan["registration_evidence"]
    assert registration["task_name"] == "baldr-ml-allocation-forward-daily"
    assert registration["next_run_pacific"] == "2026/9/8 16:15:00"
    assert registration["status"] == "Ready"


def test_forward_registration_xml_matches_plan_without_aggregate_registration() -> None:
    root = ET.fromstring(XML.read_bytes())
    assert root.findtext("task:RegistrationInfo/task:URI", namespaces=NS) == (
        "\\baldr-ml-allocation-forward-daily"
    )
    assert root.findtext(
        "task:Triggers/task:CalendarTrigger/task:StartBoundary", namespaces=NS
    ) == "2026-09-08T16:15:00"
    assert root.findtext(
        "task:Triggers/task:CalendarTrigger/task:ScheduleByDay/task:DaysInterval",
        namespaces=NS,
    ) == "1"
    assert root.findtext(
        "task:Principals/task:Principal/task:LogonType", namespaces=NS
    ) == "InteractiveToken"
    assert root.findtext(
        "task:Settings/task:MultipleInstancesPolicy", namespaces=NS
    ) == "IgnoreNew"
    assert root.findtext(
        "task:Settings/task:ExecutionTimeLimit", namespaces=NS
    ) == "PT2H"
    assert root.findtext(
        "task:Settings/task:StartWhenAvailable", namespaces=NS
    ) == "false"
    assert root.findtext("task:Settings/task:WakeToRun", namespaces=NS) == "false"
    assert root.findtext(
        "task:Actions/task:Exec/task:Command", namespaces=NS
    ) == "cmd.exe"
    arguments = root.findtext(
        "task:Actions/task:Exec/task:Arguments", namespaces=NS
    )
    assert arguments is not None
    assert "run_ml_allocation_forward_daily.cmd" in arguments
    # The imported task definition is intentionally UTF-16LE with BOM.  Parse
    # the XML bytes above instead of assuming a UTF-8 deployment encoding.
    assert "schtasks" not in ET.tostring(root, encoding="unicode").lower()
