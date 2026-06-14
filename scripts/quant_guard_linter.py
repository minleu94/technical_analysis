"""量化防禦一鍵式合規檢查工具 (量化精度與未來函數審查)。"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

def run_script(script_name: str) -> int:
    script_path = REPO_ROOT / "scripts" / script_name
    print(f"=== 執行 {script_name} ===")
    try:
        res = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        if res.stdout:
            print(res.stdout.strip())
        if res.stderr:
            print(res.stderr.strip(), file=sys.stderr)
        
        if res.returncode == 0:
            print(f"✅ {script_name} 通過！無違規項。")
            return 0
        else:
            print(f"❌ {script_name} 偵測到違規項！")
            return res.returncode
    except Exception as e:
        print(f"💥 執行 {script_name} 發生異常: {e}", file=sys.stderr)
        return 1

def main() -> int:
    if hasattr(sys.stdout, "reconfigure") and str(getattr(sys.stdout, "encoding", "")).lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("🔍 開始執行量化合規檢查...")
    float_code = run_script("check_financial_float_boundaries.py")
    print()
    lookahead_code = run_script("check_look_ahead_bias.py")
    
    print("\n======================================")
    if float_code == 0 and lookahead_code == 0:
        print("🎉 恭喜！所有量化防禦檢查（精度與未來函數）皆順利通過！")
        return 0
    else:
        print("⚠️ 警告：部分量化防禦檢查未通過，請修正上述違規項！")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
