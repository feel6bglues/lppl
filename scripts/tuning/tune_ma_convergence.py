# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

for env_name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(env_name, "1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.lppl_verify_v2 import SYMBOLS
from src.data.manager import DataManager
from src.investment import (
    BacktestConfig,
    InvestmentSignalConfig,
    generate_investment_signals,
    run_strategy_backtest,
    score_signal_tuning_results,
)
from src.lppl_engine import LPPLConfig

HIGH_BETA_SYMBOLS = {"399006.SZ", "000852.SH", "932000.SH"}
_WORKER_DF: pd.DataFrame | None = None
_WORKER_SYMBOL: str | None = None
_WORKER_START_DATE: str | None = None
_WORKER_END_DATE: str | None = None


def _build_signal_config(
    bb_period: int = 20,
    bb_std: float = 2.0,
    bb_width_cap: float = 0.03,
    atr_period: int = 14,
    atr_ma_window: int = 40,
    atr_low_percentile: float = 0.20,
    atr_high_percentile: float = 0.80,
    atr_percentile_window: int = 126,
    ma_short: int = 10,
    ma_mid: int = 30,
    ma_long: int = 60,
    regime_filter_ma: int = 120,
    regime_filter_buffer: float = 1.0,
    risk_drawdown_stop_threshold: float = 0.15,
    risk_drawdown_lookback: int = 120,
    confirm_days: int = 1,
    cooldown_days: int = 10,
    min_hold_bars: int = 0,
) -> InvestmentSignalConfig:
    return InvestmentSignalConfig(
        signal_model="ma_convergence_atr_v1",
        initial_position=0.0,
        bb_period=bb_period,
        bb_std=bb_std,
        bb_width_cap=bb_width_cap,
        atr_period=atr_period,
        atr_ma_window=atr_ma_window,
        atr_low_percentile=atr_low_percentile,
        atr_high_percentile=atr_high_percentile,
        atr_percentile_window=atr_percentile_window,
        ma_short=ma_short,
        ma_mid=ma_mid,
        ma_long=ma_long,
        regime_filter_ma=regime_filter_ma,
        regime_filter_buffer=regime_filter_buffer,
        regime_filter_reduce_enabled=True,
        risk_drawdown_stop_threshold=risk_drawdown_stop_threshold,
        risk_drawdown_lookback=risk_drawdown_lookback,
        buy_confirm_days=confirm_days,
        sell_confirm_days=confirm_days,
        cooldown_days=cooldown_days,
        min_hold_bars=min_hold_bars,
    )


def _run_candidate(
    df: pd.DataFrame,
    symbol: str,
    signal_config: InvestmentSignalConfig,
    start_date: str,
    end_date: str,
) -> Dict[str, object]:
    signal_df = generate_investment_signals(
        df=df,
        symbol=symbol,
        signal_config=signal_config,
        lppl_config=LPPLConfig(window_range=[20], n_workers=1),
        use_ensemble=False,
        start_date=start_date,
        end_date=end_date,
        scan_step=1,
    )
    _, _, summary = run_strategy_backtest(
        signal_df,
        BacktestConfig(
            initial_capital=1_000_000.0,
            buy_fee=0.0003,
            sell_fee=0.0003,
            slippage=0.0005,
            start_date=start_date,
            end_date=end_date,
        ),
    )
    return summary


def _init_worker(df_payload: Dict[str, List[object]], symbol: str, start_date: str, end_date: str) -> None:
    global _WORKER_DF, _WORKER_SYMBOL, _WORKER_START_DATE, _WORKER_END_DATE
    for env_name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[env_name] = "1"
    _WORKER_DF = pd.DataFrame(df_payload)
    _WORKER_SYMBOL = symbol
    _WORKER_START_DATE = start_date
    _WORKER_END_DATE = end_date


def _evaluate_candidate_worker(
    params: Tuple[int, float, float, int, int, float, float, int, int, int, int, int, float, int, int, int, int],
) -> Dict[str, object]:
    if _WORKER_DF is None or _WORKER_SYMBOL is None or _WORKER_START_DATE is None or _WORKER_END_DATE is None:
        raise RuntimeError("worker 未初始化")

    (
        bb_period,
        bb_std,
        bb_width_cap,
        atr_period,
        atr_ma_window,
        atr_low_percentile,
        atr_high_percentile,
        atr_percentile_window,
        ma_short,
        ma_mid,
        ma_long,
        regime_filter_ma,
        regime_filter_buffer,
        risk_drawdown_stop_threshold,
        risk_drawdown_lookback,
        confirm_days,
        cooldown_days,
        min_hold_bars,
    ) = params
    signal_config = _build_signal_config(
        bb_period=bb_period,
        bb_std=bb_std,
        bb_width_cap=bb_width_cap,
        atr_period=atr_period,
        atr_ma_window=atr_ma_window,
        atr_low_percentile=atr_low_percentile,
        atr_high_percentile=atr_high_percentile,
        atr_percentile_window=atr_percentile_window,
        ma_short=ma_short,
        ma_mid=ma_mid,
        ma_long=ma_long,
        regime_filter_ma=regime_filter_ma,
        regime_filter_buffer=regime_filter_buffer,
        risk_drawdown_stop_threshold=risk_drawdown_stop_threshold,
        risk_drawdown_lookback=risk_drawdown_lookback,
        confirm_days=confirm_days,
        cooldown_days=cooldown_days,
        min_hold_bars=min_hold_bars,
    )
    summary = _run_candidate(
        _WORKER_DF,
        _WORKER_SYMBOL,
        signal_config,
        _WORKER_START_DATE,
        _WORKER_END_DATE,
    )
    return {
        "bb_period": bb_period,
        "bb_std": bb_std,
        "bb_width_cap": bb_width_cap,
        "atr_period": atr_period,
        "atr_ma_window": atr_ma_window,
        "atr_low_percentile": atr_low_percentile,
        "atr_high_percentile": atr_high_percentile,
        "atr_percentile_window": atr_percentile_window,
        "ma_short": ma_short,
        "ma_mid": ma_mid,
        "ma_long": ma_long,
        "regime_filter_ma": regime_filter_ma,
        "regime_filter_buffer": regime_filter_buffer,
        "risk_drawdown_stop_threshold": risk_drawdown_stop_threshold,
        "risk_drawdown_lookback": risk_drawdown_lookback,
        "confirm_days": confirm_days,
        "cooldown_days": cooldown_days,
        "min_hold_bars": min_hold_bars,
        **summary,
    }


def _score_symbol_results(results_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    max_dd_cap = -0.40 if symbol in HIGH_BETA_SYMBOLS else -0.35
    return score_signal_tuning_results(
        results_df,
        min_trade_count=3,
        max_drawdown_cap=max_dd_cap,
        turnover_cap=12.0,
        whipsaw_cap=0.50,
        scoring_profile="balanced",
        hard_reject=True,
    )


def _map_chunksize(candidate_count: int, workers: int) -> int:
    if workers <= 1:
        return 1
    return max(1, candidate_count // (workers * 2))


def _effective_workers(requested_workers: int, candidate_count: int) -> int:
    cpu_limit = max(1, (os.cpu_count() or 1) - 2)
    return max(1, min(int(requested_workers), cpu_limit, candidate_count))


def _run_candidate_grid(
    candidate_params: List[Tuple],
    df: pd.DataFrame,
    symbol: str,
    start_date: str,
    end_date: str,
    requested_workers: int,
) -> Tuple[List[Dict[str, object]], int]:
    workers = _effective_workers(requested_workers, len(candidate_params))
    df_payload = df.to_dict(orient="list")

    if workers <= 1:
        _init_worker(df_payload, symbol, start_date, end_date)
        return ([_evaluate_candidate_worker(params) for params in candidate_params], 1)

    current_workers = workers
    while current_workers > 1:
        try:
            with ProcessPoolExecutor(
                max_workers=current_workers,
                initializer=_init_worker,
                initargs=(df_payload, symbol, start_date, end_date),
            ) as executor:
                raw_rows = list(
                    executor.map(
                        _evaluate_candidate_worker,
                        candidate_params,
                        chunksize=_map_chunksize(len(candidate_params), current_workers),
                    )
                )
            return raw_rows, current_workers
        except Exception as exc:
            next_workers = max(1, current_workers // 2)
            print(
                f"[POOL-RETRY] {symbol} workers={current_workers} failed={type(exc).__name__}: {exc}; retry={next_workers}",
                flush=True,
            )
            current_workers = next_workers

    _init_worker(df_payload, symbol, start_date, end_date)
    return ([_evaluate_candidate_worker(params) for params in candidate_params], 1)


def _stage1(
    symbol: str,
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    workers: int,
) -> Tuple[pd.DataFrame, Tuple[Tuple[int, float, float], ...]]:
    """Stage 1: Bollinger Band parameter screening."""
    candidate_params = [
        (bb_period, bb_std, bb_width_cap, 14, 40, 0.20, 0.80, 126, 10, 30, 60, 120, 1.0, 0.15, 120, 1, 10, 0)
        for bb_period, bb_std, bb_width_cap in product(
            [20, 30],
            [1.5, 2.0, 2.5],
            [0.02, 0.03, 0.05],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [
        {
            "symbol": symbol,
            "name": SYMBOLS[symbol],
            "stage": "stage1_bb_params",
            **row,
        }
        for row in raw_rows
    ]
    scored = _score_symbol_results(pd.DataFrame(rows), symbol)
    print(f"[STAGE1-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    top_seeds = scored[["bb_period", "bb_std", "bb_width_cap"]].drop_duplicates().head(2)
    return scored, tuple(top_seeds.itertuples(index=False, name=None))


def _stage2(
    symbol: str,
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    top_seeds: Tuple[Tuple[int, float, float], ...],
    workers: int,
) -> Tuple[pd.DataFrame, Tuple[Tuple[int, int, float, float, int], ...]]:
    """Stage 2: ATR dynamic percentile validation."""
    candidate_params = [
        (bb_period, bb_std, bb_width_cap, atr_period, atr_ma_window, atr_low, atr_high, atr_win, 10, 30, 60, 120, 1.0, 0.15, 120, 1, 10, 0)
        for bb_period, bb_std, bb_width_cap in top_seeds
        for atr_period, atr_ma_window, atr_low, atr_high, atr_win in product(
            [14, 20],
            [20, 40, 60],
            [0.15, 0.20, 0.25],
            [0.75, 0.80, 0.85],
            [126, 252],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [
        {
            "symbol": symbol,
            "name": SYMBOLS[symbol],
            "stage": "stage2_atr_percentile",
            **row,
        }
        for row in raw_rows
    ]
    scored = _score_symbol_results(pd.DataFrame(rows), symbol)
    print(f"[STAGE2-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    top_seeds2 = scored[["bb_period", "bb_std", "bb_width_cap", "atr_period", "atr_ma_window", "atr_low_percentile", "atr_high_percentile", "atr_percentile_window"]].drop_duplicates().head(2)
    return scored, tuple(top_seeds2.itertuples(index=False, name=None))


def _stage3(
    symbol: str,
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    top_seeds: Tuple[Tuple[int, float, float, int, int, float, float, int], ...],
    workers: int,
) -> pd.DataFrame:
    """Stage 3: MA combination testing."""
    candidate_params = [
        (bb_period, bb_std, bb_width_cap, atr_period, atr_ma_window, atr_low, atr_high, atr_win, ma_s, ma_m, ma_l, 120, 1.0, 0.15, 120, 1, 10, 0)
        for bb_period, bb_std, bb_width_cap, atr_period, atr_ma_window, atr_low, atr_high, atr_win in top_seeds
        for ma_s, ma_m, ma_l in product(
            [5, 10, 20],
            [20, 30, 60],
            [60, 120, 250],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [
        {
            "symbol": symbol,
            "name": SYMBOLS[symbol],
            "stage": "stage3_ma_combos",
            **row,
        }
        for row in raw_rows
    ]
    print(f"[STAGE3-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    return _score_symbol_results(pd.DataFrame(rows), symbol)


def _stage4(
    symbol: str,
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    stage3_df: pd.DataFrame,
    workers: int,
) -> pd.DataFrame:
    """Stage 4: Risk layer parameter tuning."""
    seeds = stage3_df[
        ["bb_period", "bb_std", "bb_width_cap", "atr_period", "atr_ma_window",
         "atr_low_percentile", "atr_high_percentile", "atr_percentile_window",
         "ma_short", "ma_mid", "ma_long"]
    ].drop_duplicates().head(2)

    candidate_params = [
        (int(s.bb_period), float(s.bb_std), float(s.bb_width_cap),
         int(s.atr_period), int(s.atr_ma_window),
         float(s.atr_low_percentile), float(s.atr_high_percentile), int(s.atr_percentile_window),
         int(s.ma_short), int(s.ma_mid), int(s.ma_long),
         rf_ma, rf_buf, dd_stop, dd_lb, 1, 10, 0)
        for s in seeds.itertuples(index=False)
        for rf_ma, rf_buf, dd_stop, dd_lb in product(
            [120, 180, 240],
            [0.98, 1.00, 1.02],
            [0.12, 0.15, 0.18],
            [120, 180, 240],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [
        {
            "symbol": symbol,
            "name": SYMBOLS[symbol],
            "stage": "stage4_risk_layer",
            **row,
        }
        for row in raw_rows
    ]
    print(f"[STAGE4-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    return _score_symbol_results(pd.DataFrame(rows), symbol)


def _stage5(
    symbol: str,
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    stage4_df: pd.DataFrame,
    workers: int,
) -> pd.DataFrame:
    """Stage 5: Trading suppression (cooldown, min_hold)."""
    seeds = stage4_df[
        ["bb_period", "bb_std", "bb_width_cap", "atr_period", "atr_ma_window",
         "atr_low_percentile", "atr_high_percentile", "atr_percentile_window",
         "ma_short", "ma_mid", "ma_long",
         "regime_filter_ma", "regime_filter_buffer",
         "risk_drawdown_stop_threshold", "risk_drawdown_lookback"]
    ].drop_duplicates().head(2)

    candidate_params = [
        (int(s.bb_period), float(s.bb_std), float(s.bb_width_cap),
         int(s.atr_period), int(s.atr_ma_window),
         float(s.atr_low_percentile), float(s.atr_high_percentile), int(s.atr_percentile_window),
         int(s.ma_short), int(s.ma_mid), int(s.ma_long),
         int(s.regime_filter_ma), float(s.regime_filter_buffer),
         float(s.risk_drawdown_stop_threshold), int(s.risk_drawdown_lookback),
         confirm, cooldown, min_hold)
        for s in seeds.itertuples(index=False)
        for confirm, cooldown, min_hold in product(
            [1, 2, 3],
            [5, 10, 15],
            [0, 3, 5],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [
        {
            "symbol": symbol,
            "name": SYMBOLS[symbol],
            "stage": "stage5_trading_suppress",
            **row,
        }
        for row in raw_rows
    ]
    print(f"[STAGE5-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    return _score_symbol_results(pd.DataFrame(rows), symbol)


def main() -> None:
    parser = argparse.ArgumentParser(description="MA收敛 + ATR波动率策略参数调优")
    parser.add_argument("--symbols", default="000001.SH,399001.SZ,399006.SZ,000016.SH,000300.SH,000905.SH,000852.SH")
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--output", default="output/ma_convergence_tuning")
    parser.add_argument("--workers", type=int, default=30)
    args = parser.parse_args()

    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    unknown = [symbol for symbol in symbols if symbol not in SYMBOLS]
    if unknown:
        raise SystemExit(f"未知指数代码: {unknown}")

    out_dir = Path(args.output)
    summary_dir = out_dir / "summary"
    reports_dir = out_dir / "reports"
    summary_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    manager = DataManager()
    stage1_best_rows: List[Dict[str, object]] = []
    stage2_best_rows: List[Dict[str, object]] = []
    stage3_best_rows: List[Dict[str, object]] = []
    stage4_best_rows: List[Dict[str, object]] = []
    stage5_best_rows: List[Dict[str, object]] = []
    stage1_frames: List[pd.DataFrame] = []
    stage2_frames: List[pd.DataFrame] = []
    stage3_frames: List[pd.DataFrame] = []
    stage4_frames: List[pd.DataFrame] = []
    stage5_frames: List[pd.DataFrame] = []

    for symbol in symbols:
        print(f"[STAGE1] {symbol}", flush=True)
        df = manager.get_data(symbol)
        if df is None or df.empty:
            print(f"SKIP {symbol}: empty data", flush=True)
            continue

        stage1_df, top_seeds1 = _stage1(symbol, df, args.start_date, args.end_date, max(1, int(args.workers)))
        stage1_frames.append(stage1_df)
        stage1_best_rows.append(stage1_df.iloc[0].to_dict())
        best_stage1 = stage1_df.iloc[0]
        print(
            f"[STAGE1-BEST] {symbol} BB{int(best_stage1['bb_period'])} "
            f"std={float(best_stage1['bb_std']):.1f} cap={float(best_stage1['bb_width_cap']):.3f} "
            f"excess={float(best_stage1['annualized_excess_return']):.4f} "
            f"mdd={float(best_stage1['max_drawdown']):.4f}",
            flush=True,
        )

        print(f"[STAGE2] {symbol} top_seeds={top_seeds1}", flush=True)
        stage2_df, top_seeds2 = _stage2(symbol, df, args.start_date, args.end_date, top_seeds1, max(1, int(args.workers)))
        stage2_frames.append(stage2_df)
        stage2_best_rows.append(stage2_df.iloc[0].to_dict())
        best_stage2 = stage2_df.iloc[0]
        print(
            f"[STAGE2-BEST] {symbol} ATR{int(best_stage2['atr_period'])}/{int(best_stage2['atr_ma_window'])} "
            f"low={float(best_stage2['atr_low_percentile']):.2f} high={float(best_stage2['atr_high_percentile']):.2f} "
            f"excess={float(best_stage2['annualized_excess_return']):.4f} "
            f"mdd={float(best_stage2['max_drawdown']):.4f} eligible={bool(best_stage2['eligible'])}",
            flush=True,
        )

        print(f"[STAGE3] {symbol} MA combos", flush=True)
        stage3_df = _stage3(symbol, df, args.start_date, args.end_date, top_seeds2, max(1, int(args.workers)))
        stage3_frames.append(stage3_df)
        stage3_best_rows.append(stage3_df.iloc[0].to_dict())
        best_stage3 = stage3_df.iloc[0]
        print(
            f"[STAGE3-BEST] {symbol} MA{int(best_stage3['ma_short'])}/{int(best_stage3['ma_mid'])}/{int(best_stage3['ma_long'])} "
            f"excess={float(best_stage3['annualized_excess_return']):.4f} "
            f"mdd={float(best_stage3['max_drawdown']):.4f} eligible={bool(best_stage3['eligible'])}",
            flush=True,
        )

        print(f"[STAGE4] {symbol} risk layer", flush=True)
        stage4_df = _stage4(symbol, df, args.start_date, args.end_date, stage3_df, max(1, int(args.workers)))
        stage4_frames.append(stage4_df)
        stage4_best_rows.append(stage4_df.iloc[0].to_dict())
        best_stage4 = stage4_df.iloc[0]
        print(
            f"[STAGE4-BEST] {symbol} regime={int(best_stage4['regime_filter_ma'])}@{float(best_stage4['regime_filter_buffer']):.2f} "
            f"dd_stop={float(best_stage4['risk_drawdown_stop_threshold']):.2f} "
            f"excess={float(best_stage4['annualized_excess_return']):.4f} "
            f"mdd={float(best_stage4['max_drawdown']):.4f} eligible={bool(best_stage4['eligible'])}",
            flush=True,
        )

        print(f"[STAGE5] {symbol} trading suppress", flush=True)
        stage5_df = _stage5(symbol, df, args.start_date, args.end_date, stage4_df, max(1, int(args.workers)))
        stage5_frames.append(stage5_df)
        stage5_best_rows.append(stage5_df.iloc[0].to_dict())
        best_stage5 = stage5_df.iloc[0]
        print(
            f"[STAGE5-BEST] {symbol} confirm={int(best_stage5['confirm_days'])} cooldown={int(best_stage5['cooldown_days'])} "
            f"min_hold={int(best_stage5['min_hold_bars'])} "
            f"excess={float(best_stage5['annualized_excess_return']):.4f} "
            f"mdd={float(best_stage5['max_drawdown']):.4f} trades={int(best_stage5['trade_count'])} "
            f"eligible={bool(best_stage5['eligible'])}",
            flush=True,
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stage1_full = pd.concat(stage1_frames, ignore_index=True) if stage1_frames else pd.DataFrame()
    stage2_full = pd.concat(stage2_frames, ignore_index=True) if stage2_frames else pd.DataFrame()
    stage3_full = pd.concat(stage3_frames, ignore_index=True) if stage3_frames else pd.DataFrame()
    stage4_full = pd.concat(stage4_frames, ignore_index=True) if stage4_frames else pd.DataFrame()
    stage5_full = pd.concat(stage5_frames, ignore_index=True) if stage5_frames else pd.DataFrame()
    stage1_best = pd.DataFrame(stage1_best_rows)
    stage2_best = pd.DataFrame(stage2_best_rows)
    stage3_best = pd.DataFrame(stage3_best_rows)
    stage4_best = pd.DataFrame(stage4_best_rows)
    stage5_best = pd.DataFrame(stage5_best_rows)

    stage1_full_path = summary_dir / f"ma_convergence_stage1_full_{stamp}.csv"
    stage1_best_path = summary_dir / f"ma_convergence_stage1_best_{stamp}.csv"
    stage2_full_path = summary_dir / f"ma_convergence_stage2_full_{stamp}.csv"
    stage2_best_path = summary_dir / f"ma_convergence_stage2_best_{stamp}.csv"
    stage3_full_path = summary_dir / f"ma_convergence_stage3_full_{stamp}.csv"
    stage3_best_path = summary_dir / f"ma_convergence_stage3_best_{stamp}.csv"
    stage4_full_path = summary_dir / f"ma_convergence_stage4_full_{stamp}.csv"
    stage4_best_path = summary_dir / f"ma_convergence_stage4_best_{stamp}.csv"
    stage5_full_path = summary_dir / f"ma_convergence_stage5_full_{stamp}.csv"
    stage5_best_path = summary_dir / f"ma_convergence_stage5_best_{stamp}.csv"
    stage1_full.to_csv(stage1_full_path, index=False)
    stage1_best.to_csv(stage1_best_path, index=False)
    stage2_full.to_csv(stage2_full_path, index=False)
    stage2_best.to_csv(stage2_best_path, index=False)
    stage3_full.to_csv(stage3_full_path, index=False)
    stage3_best.to_csv(stage3_best_path, index=False)
    stage4_full.to_csv(stage4_full_path, index=False)
    stage4_best.to_csv(stage4_best_path, index=False)
    stage5_full.to_csv(stage5_full_path, index=False)
    stage5_best.to_csv(stage5_best_path, index=False)

    report_lines = [
        "# MA收敛 + ATR波动率策略参数调优",
        "",
        f"- 测试区间: {args.start_date} 到 {args.end_date}",
        f"- 指数数量: {len(stage5_best)}",
        "",
        "## Stage 5 Best",
        "",
    ]
    for row in stage5_best.sort_values("objective_score", ascending=False).to_dict("records"):
        report_lines.extend(
            [
                f"### {row['symbol']} {row['name']}",
                f"- objective_score: {float(row['objective_score']):.4f}",
                f"- BB: period={int(row['bb_period'])} std={float(row['bb_std']):.1f} cap={float(row['bb_width_cap']):.3f}",
                f"- ATR: period={int(row['atr_period'])} window={int(row['atr_ma_window'])} low={float(row['atr_low_percentile']):.2f} high={float(row['atr_high_percentile']):.2f}",
                f"- MA: {int(row['ma_short'])}/{int(row['ma_mid'])}/{int(row['ma_long'])}",
                f"- regime: {int(row['regime_filter_ma'])} buffer={float(row['regime_filter_buffer']):.2f}",
                f"- risk: dd_stop={float(row['risk_drawdown_stop_threshold']):.2f} lookback={int(row['risk_drawdown_lookback'])}",
                f"- trading: confirm={int(row['confirm_days'])} cooldown={int(row['cooldown_days'])} min_hold={int(row['min_hold_bars'])}",
                f"- annualized_excess_return: {float(row['annualized_excess_return']):.4%}",
                f"- max_drawdown: {float(row['max_drawdown']):.4%}",
                f"- trade_count: {int(row['trade_count'])}",
                f"- whipsaw_rate: {float(row.get('whipsaw_rate', 0)):.4f}",
                f"- eligible: {bool(row['eligible'])}",
                "",
            ]
        )
    report_path = reports_dir / f"ma_convergence_tuning_report_{stamp}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print(f"SAVED {stage1_full_path}")
    print(f"SAVED {stage1_best_path}")
    print(f"SAVED {stage2_full_path}")
    print(f"SAVED {stage2_best_path}")
    print(f"SAVED {stage3_full_path}")
    print(f"SAVED {stage3_best_path}")
    print(f"SAVED {stage4_full_path}")
    print(f"SAVED {stage4_best_path}")
    print(f"SAVED {stage5_full_path}")
    print(f"SAVED {stage5_best_path}")
    print(f"SAVED {report_path}")


if __name__ == "__main__":
    main()
