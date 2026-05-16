#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff Analysis Entry Point
威科夫 A 股实战分析入口
"""

import warnings
warnings.warn(
    "This entry point is deprecated. Use 'python main.py <subcommand>' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from src.cli.wyckoff_analysis import main

if __name__ == "__main__":
    main()
