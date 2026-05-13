#!/usr/bin/env python3
"""
源码质量验证脚本

用法: python scripts/verify_src_quality.py

依次执行:
  1. compileall -q src    (语法检查)
  2. ruff check src       (lint)
  3. pytest tests/unit -q (单元测试)

退出码: 全部通过返回 0，任一失败返回非 0
"""

import subprocess
import sys
from pathlib import Path

VENV_PYTHON = str(Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python")

STEPS = [
    ("compileall -q src", [VENV_PYTHON, "-m", "compileall", "-q", "src"]),
    ("ruff check src", [VENV_PYTHON, "-m", "ruff", "check", "src"]),
    ("pytest tests/unit -q", [VENV_PYTHON, "-m", "pytest", "tests/unit", "-q"]),
]


def main() -> None:
    failed = []
    for label, cmd in STEPS:
        print(f"\n>>> {label}")
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            failed.append(label)

    if failed:
        print(f"\n❌ 以下步骤失败: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("\n✅ 全部验证通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
