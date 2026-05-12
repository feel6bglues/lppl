# -*- coding: utf-8 -*-
"""
Investment strategy module.

唯一生产入口: src.investment.backtest
- backtest_engine.py 已弃用 (deprecated)，所有生产代码和测试均走 backtest.py。

Provides:
- Configuration dataclasses for signal generation and backtesting
- Technical indicator computation
- Signal evaluation models (LPPL, multi-factor)
- Backtesting engine
- Tuning and scoring utilities
"""
from .backtest import (
    BacktestConfig,
    InvestmentSignalConfig,
    calculate_drawdown,
    generate_investment_signals,
    run_strategy_backtest,
    summarize_strategy_performance,
)
from .config import BacktestConfig as BacktestConfigBase
from .config import InvestmentSignalConfig as InvestmentSignalConfigBase
from .indicators import compute_indicators, normalize_price_frame
from .signal_models import (
    evaluate_multi_factor_adaptive,
    map_ensemble_signal,
    map_single_window_signal,
    resolve_action,
)
from .tuning import score_signal_tuning_results

__all__ = [
    # Configs (from backtest.py for backward compatibility)
    "BacktestConfig",
    "InvestmentSignalConfig",
    # Configs (from config module)
    "BacktestConfigBase",
    "InvestmentSignalConfigBase",
    # Indicators
    "normalize_price_frame",
    "compute_indicators",
    # Signal models
    "resolve_action",
    "evaluate_multi_factor_adaptive",
    "map_single_window_signal",
    "map_ensemble_signal",
    # Backtest engine
    "calculate_drawdown",
    "generate_investment_signals",
    "run_strategy_backtest",
    "summarize_strategy_performance",
    # Tuning
    "score_signal_tuning_results",
]
