# RESEARCH ONLY — not production code
"""共用配置：TDX数据路径"""
import os
from pathlib import Path

TDX_BASE = Path(os.environ.get("TDX_DATA_PATH", "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"))
TDX_SH_DIR = TDX_BASE / "sh" / "lday"
TDX_SZ_DIR = TDX_BASE / "sz" / "lday"
CSI300_PATH = TDX_SH_DIR / "sh000300.day"
