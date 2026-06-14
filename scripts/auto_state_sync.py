"""自動同步 Git 工作區狀態至 active_task.yaml 並檢查 dirty exclusions 檔案。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_TASK_PATH = REPO_ROOT / "docs" / "agents" / "shared_state" / "active_task.yaml"

# 常見不應提交的排除規則 (對應 git_exclusions.md)
EXCLUSION_PATTERNS = [
    r"^\.superpowers/",
    r"(^|/)\.tmp\.driveupload/",
    r"^docs/agents/shared_state/(active_task\.yaml|handoff_log\.md)$",
    r"(^|/)\.pytest_cache/",
    r"(^|/)\.coverage$",
    r"(^|/)htmlcov/",
    r"(^|/)\.tox/",
    r"(^|/)\.cache/",
    r"\.log$",
    r"^logs/",
    r"^(venv|env|ENV)/",
    r"^\.env",
    r"^downloads/",
    r"^temp_downloads/",
    r"^(tmp|temp)/",
    r"^output/qa/update_tab/RUN_LOG\.txt$",
    r"^output/qa/update_tab/VALIDATION_REPORT\.md$",
    r"\.db$",
    r"\.sqlite",
]

def run_git_status() -> list[str]:
    """獲取 Git status 輸出的檔案清單。"""
    try:
        res = subprocess.run(
            ["git", "status", "--short", "-z", "--untracked-files=all"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Git status 執行失敗: {res.stderr.strip()}")
        entries = res.stdout.split("\0")
        files: list[str] = []
        index = 0
        while index < len(entries) and entries[index]:
            entry = entries[index]
            status = entry[:2]
            path = entry[3:]
            files.append(path)
            index += 1
            if "R" in status or "C" in status:
                index += 1
        return files
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"無法執行 Git status: {exc}") from exc

def check_exclusions(files: list[str]) -> list[str]:
    """比對排除清單，檢查是否有不應被 stage 的檔案被變更或新增。"""
    warnings = []
    for file in files:
        for pattern in EXCLUSION_PATTERNS:
            if re.search(pattern, file):
                warnings.append(file)
                break
    return warnings

def build_active_task_content(
    content: str,
    files: list[str],
    warnings: list[str],
) -> str:
    """建立新的 active_task.yaml 內容，保留 git_status 後方區塊。"""
    block_lines = [
        "git_status:",
        f"  clean: {'true' if not files else 'false'}",
    ]
    if files:
        block_lines.append("  modified_files:")
        block_lines.extend(
            f"    - {json.dumps(file, ensure_ascii=False)}" for file in files
        )
    if warnings:
        block_lines.append("  warnings:")
        block_lines.extend(
            "    - "
            + json.dumps(
                f"不應 stage 的排除檔案已修改: {warning}",
                ensure_ascii=False,
            )
            for warning in warnings
        )
    else:
        block_lines.append("  warnings: []")
    new_block = "\n".join(block_lines) + "\n"

    pattern = re.compile(
        r"^git_status:\r?\n(?:^[ \t][^\r\n]*(?:\r?\n|$))*",
        re.MULTILINE,
    )
    if pattern.search(content):
        return pattern.sub(new_block, content, count=1)
    return content.rstrip() + "\n\n" + new_block


def update_active_task(files: list[str], warnings: list[str]) -> None:
    """以原子替換更新 active_task.yaml 的 git_status 區塊。"""
    if not ACTIVE_TASK_PATH.exists():
        raise FileNotFoundError(f"active_task.yaml 不存在: {ACTIVE_TASK_PATH}")

    try:
        content = ACTIVE_TASK_PATH.read_text(encoding="utf-8")
        new_content = build_active_task_content(content, files, warnings)
        temp_path = ACTIVE_TASK_PATH.with_suffix(".yaml.tmp")
        temp_path.write_text(new_content, encoding="utf-8")
        os.replace(temp_path, ACTIVE_TASK_PATH)
        print(f"✅ 成功將 Git 狀態與警告寫入 active_task.yaml！")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"無法更新 active_task.yaml: {exc}") from exc

def main() -> int:
    if hasattr(sys.stdout, "reconfigure") and str(getattr(sys.stdout, "encoding", "")).lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("🔍 檢查 Git 工作區狀態與 exclusions...")
    try:
        files = run_git_status()
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    warnings = check_exclusions(files)
    
    if files:
        print(f"   發現已修改/新增的檔案 ({len(files)} 個)：")
        for file in files:
            prefix = "🔴 [警告/不應提交]" if file in warnings else "📝 [合規變更]"
            print(f"     {prefix} {file}")
    else:
        print("   ✅ Git 工作區乾淨，無未提交變更。")

    if warnings:
        print(f"\n⚠️ 警告：發現 {len(warnings)} 個不應提交的暫存/日誌/資料檔案被修改！")
        print("   請參考 docs/agents/git_exclusions.md 處理，不要將它們 stage！")
    
    try:
        update_active_task(files, warnings)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    return 1 if warnings else 0

if __name__ == "__main__":
    raise SystemExit(main())
