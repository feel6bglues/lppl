#!/usr/bin/env python3
# RESEARCH ONLY — not production code
"""
Thin compat layer — all logic migrated to src.strategies (Sprint 9)
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
_src_path = str(PROJECT_ROOT.parent)
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from src.strategies.backtest import (
    run_backtest, MC_SIMS, COST_BUY, COST_SELL,
    process_stock, compute_stats, ann_sharpe,
    load_stocks, load_csi300, gen_windows,
)
from src.strategies.registry import STRATEGY_MAP
from src.strategies.indicators import calc_atr
from src.strategies.regime import get_regime
from src.strategies.wyckoff import trade_wyckoff, REGIME_PARAMS
from src.strategies.ma_cross import trade_ma
from src.strategies.str_reversal import trade_str_reversal
