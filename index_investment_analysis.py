#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import warnings
warnings.warn(
    "This entry point is deprecated. Use 'python main.py <subcommand>' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from src.cli.index_investment_analysis import main

if __name__ == "__main__":
    main()
