#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫多模态分析系统 - 根目录 Wrapper

使用方法:
    python wyckoff_multimodal_analysis.py --symbol 000300.SH
    python wyckoff_multimodal_analysis.py --symbol 600519.SH --chart-dir output/MA/plots
    python wyckoff_multimodal_analysis.py --chart-dir output/MA/plots
"""
import warnings
warnings.warn(
    "This entry point is deprecated. Use 'python main.py <subcommand>' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from src.cli.wyckoff_multimodal_analysis import main

if __name__ == "__main__":
    main()
