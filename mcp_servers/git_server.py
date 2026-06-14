from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT_CHARS = 200_000


def _validate_git_args(args: list[str]) -> None:
    if args[:2] == ["log", "-n"]:
        try:
            count = int(args[2])
        except (IndexError, ValueError) as exc:
            raise ValueError("git log 筆數必須是 1 到 100 的整數。") from exc
        if not 1 <= count <= 100:
            raise ValueError("git log 筆數必須是 1 到 100。")


def _truncate_output(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return (
        output[:MAX_OUTPUT_CHARS]
        + f"\n\n[輸出已截斷：超過 {MAX_OUTPUT_CHARS} 個字元]"
    )

def run_git_command(args: list[str]) -> str:
    """在專案根目錄下安全地執行 Git 指令。"""
    _validate_git_args(args)
    try:
        res = subprocess.run(
            ["git", "--no-pager"] + args,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if res.returncode == 0:
            return _truncate_output(res.stdout.strip())
        raise RuntimeError(
            f"Git 指令失敗（exit {res.returncode}）：{res.stderr.strip()}"
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"無法執行 Git 指令：{exc}") from exc

def create_git_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("twstock-git-assistant")

    @mcp.tool()
    def git_status() -> str:
        """獲取目前專案的 Git 狀態簡短摘要 (git status --short)。"""
        return run_git_command(["status", "--short"])

    @mcp.tool()
    def git_diff(cached: bool = False) -> str:
        """獲取目前 Working Tree 或暫存區 (cached) 的 Git Diff 差異內容。"""
        args = ["diff", "--no-ext-diff", "--no-textconv"]
        if cached:
            args.append("--cached")
        return run_git_command(args)

    @mcp.tool()
    def git_log(n: int = 5) -> str:
        """獲取最近 n 筆 Commit 紀錄歷史。"""
        return run_git_command(["log", "-n", str(n), "--oneline"])

    return mcp

if __name__ == "__main__":
    create_git_mcp_server().run(show_banner=False)
