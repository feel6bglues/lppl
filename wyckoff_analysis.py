#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff Analysis Entry Point
威科夫 A 股实战分析入口
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.wyckoff_analysis import main

if __name__ == "__main__":
    main()
