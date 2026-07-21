"""富邦行情來源接受封包 (Source Acceptance Dossier) 唯讀盤點 CLI 工具。

此工具會產生一個 fail-closed 的準備度報告，並生成擁有者審查範本。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.source_acceptance_governance import (
    SourceAcceptanceDossier,
    SourceAcceptanceGovernance,
    SourceAcceptanceDiagnosis,
)


def is_path_safe(path: Path) -> bool:
    """檢查路徑是否與正式數據、正式輸出、正式資料庫或專案庫根路徑重疊。"""
    try:
        resolved = path.resolve()
    except Exception:
        return False

    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    output_root = Path(os.environ.get("OUTPUT_ROOT", "D:/Min/Python/Project/FA_Data/output")).resolve()
    sqlite_dir = data_root / "sqlite"
    repo_root = Path(__file__).resolve().parents[1].resolve()

    for forbidden in (data_root, output_root, sqlite_dir, repo_root):
        if resolved == forbidden or resolved.is_relative_to(forbidden):
            return False
    return True


def validate_paths(output_template: Path | None, shadow_root: Path | None) -> None:
    """驗證輸出路徑與 shadow root 是否符合安全性與白名單規則，拒絕非法路徑。"""
    if output_template is None and shadow_root is None:
        return

    if (output_template is not None) != (shadow_root is not None):
        raise ValueError("安全驗證失敗：必須同時提供 --output-template 與 --shadow-root 才能寫出範本")

    assert output_template is not None
    assert shadow_root is not None

    if not output_template.is_absolute():
        raise ValueError("安全驗證失敗：輸出範本路徑必須是絕對路徑")
    if not shadow_root.is_absolute():
        raise ValueError("安全驗證失敗：Shadow root 路徑必須是絕對路徑")

    try:
        shadow_resolved = shadow_root.resolve()
    except Exception:
        raise ValueError("安全驗證失敗：無法解析指定的 shadow root 絕對路徑")

    if not shadow_resolved.exists():
        raise ValueError("安全驗證失敗：指定的 shadow root 目錄不存在")
    if not shadow_resolved.is_dir():
        raise ValueError("安全驗證失敗：指定的 shadow root 必須為目錄")

    if not is_path_safe(shadow_resolved):
        raise ValueError("安全驗證失敗：指定的 shadow root 位於限制寫入之正式或專案庫目錄下")

    try:
        tpl_resolved = output_template.resolve()
    except Exception:
        raise ValueError("安全驗證失敗：無法解析指定的輸出範本絕對路徑")

    try:
        tpl_resolved.relative_to(shadow_resolved)
    except ValueError:
        raise ValueError("安全驗證失敗：輸出範本路徑必須位於指定的 shadow root 之下")

    if not is_path_safe(tpl_resolved):
        raise ValueError("安全驗證失敗：輸出範本路徑位於限制寫入之正式或專案庫目錄下")

    # 檢查不存在的父路徑是否都在 shadow_resolved 內
    current = tpl_resolved.parent
    while not current.exists():
        parent = current.parent
        if parent == current:
            break
        current = parent

    if current != shadow_resolved and not current.is_relative_to(shadow_resolved):
        raise ValueError("安全驗證失敗：輸出路徑中包含不存在且不在授權 shadow root 範圍內的父目錄")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="盤點富邦來源接受封包 (Source Acceptance Dossier)")
    parser.add_argument("--dossier", required=True, type=Path, help="dossier JSON 檔案的完整路徑")
    parser.add_argument("--output-template", type=Path, help="可選：輸出 Markdown 審查範本的目的地檔案路徑 (需搭配 --shadow-root)")
    parser.add_argument("--shadow-root", type=Path, help="可選：顯式授權允許寫出範本的外部 shadow root 絕對路徑")
    args = parser.parse_args(argv)

    if not args.dossier.exists():
        print(f"錯誤：dossier 檔案不存在於 {args.dossier}")
        return 1

    try:
        raw_payload = json.loads(args.dossier.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print("錯誤：無法讀取或解析 dossier 檔案，操作終止。")
        return 1

    # 相容原始輸入與投影產出的格式
    dossier_data = raw_payload.get("dossier", raw_payload) if isinstance(raw_payload, dict) else raw_payload

    try:
        dossier = SourceAcceptanceDossier.from_dict(dossier_data)
    except (TypeError, ValueError) as exc:
        print("錯誤：dossier 資料結構無效，操作終止。")
        return 1

    # 進行安全路徑檢查，防止寫入限制區域
    try:
        validate_paths(args.output_template, args.shadow_root)
    except Exception as exc:
        # 安全機制：錯誤輸出不得回顯任何機敏資訊或秘密
        print(f"錯誤：路徑安全性檢查未通過 - {exc}")
        return 1

    gov = SourceAcceptanceGovernance()
    diagnostics = gov.diagnose_dossier(dossier)
    template = gov.generate_owner_review_template(dossier, diagnostics)

    print("================================================================================")
    print(f"來源接受封包 (Source Acceptance Dossier) 唯讀評估報告：{dossier.source_id}")
    print("================================================================================")
    print(f"Dossier 內容雜湊值: {dossier.content_hash}")
    print(f"是否準備好供擁有者進行審查: {diagnostics.checklist_complete}")
    print("\n檢核清單摘要：")
    for item in diagnostics.checklist:
        symbol = "[OK]" if item["status"] == "verified" else "[FAIL]"
        print(f"  {symbol} {item['name']}: {item['detail']}")

    print("\n缺失程式可驗證證據 (由系統代碼核對)：")
    if diagnostics.missing_programmatic_evidence:
        for item in diagnostics.missing_programmatic_evidence:
            print(f"  - {item}")
    else:
        print("  - 無")

    print("\n缺失管理權限證據 (須由擁有者/法務/合規部門提供)：")
    if diagnostics.missing_authority_evidence:
        for item in diagnostics.missing_authority_evidence:
            print(f"  - {item}")
    else:
        print("  - 無")

    print("\n作用中阻擋器 (Blockers)：")
    if diagnostics.active_blockers:
        for b in diagnostics.active_blockers:
            print(f"  - {b}")
    else:
        print("  - 無")

    print("\nFail-Closed 狀態投影：")
    print(f"  - status: {diagnostics.status}")
    print(f"  - allowed_use_cases: {diagnostics.allowed_use_cases}")
    print(f"  - downstream_eligibility: {diagnostics.downstream_eligibility}")
    print("================================================================================")

    if args.output_template and args.shadow_root:
        try:
            args.output_template.parent.mkdir(parents=True, exist_ok=True)
            args.output_template.write_text(template, encoding="utf-8")
            print(f"\n已將擁有者審查範本寫入：{args.output_template}")
        except Exception:
            print("錯誤：寫入範本檔案時發生異常。")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
