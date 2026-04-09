# -*- coding: utf-8 -*-
"""多因子动态自适应趋势跟踪策略参数调优"""
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
    ma_short: int = 10,
    ma_mid: int = 30,
    ma_long: int = 120,
    htf_ma: int = 180,
    atr_period: int = 14,
    atr_ma_window: int = 40,
    atr_low_threshold: float = 0.95,
    atr_high_threshold: float = 1.15,
    bb_period: int = 20,
    bb_std: float = 2.0,
    bb_narrow_threshold: float = 0.05,
    bb_wide_threshold: float = 0.10,
    buy_score_threshold: float = 2.0,
    sell_score_threshold: float = -1.5,
    reduce_score_threshold: float = -1.0,
    atr_stop_mult: float = 2.5,
    regime_filter_ma: int = 120,
    regime_filter_buffer: float = 1.0,
    risk_drawdown_stop_threshold: float = 0.15,
    risk_drawdown_lookback: int = 120,
    confirm_days: int = 2,
    cooldown_days: int = 10,
    min_hold_bars: int = 0,
) -> InvestmentSignalConfig:
    return InvestmentSignalConfig(
        signal_model="multi_factor_adaptive_v1",
        initial_position=0.0,
        ma_short=ma_short,
        ma_mid=ma_mid,
        ma_long=ma_long,
        htf_ma=htf_ma,
        atr_period=atr_period,
        atr_ma_window=atr_ma_window,
        atr_low_threshold=atr_low_threshold,
        atr_high_threshold=atr_high_threshold,
        bb_period=bb_period,
        bb_std=bb_std,
        bb_narrow_threshold=bb_narrow_threshold,
        bb_wide_threshold=bb_wide_threshold,
        buy_score_threshold=buy_score_threshold,
        sell_score_threshold=sell_score_threshold,
        reduce_score_threshold=reduce_score_threshold,
        atr_stop_mult=atr_stop_mult,
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


def _evaluate_candidate_worker(params: Tuple) -> Dict[str, object]:
    if _WORKER_DF is None or _WORKER_SYMBOL is None or _WORKER_START_DATE is None or _WORKER_END_DATE is None:
        raise RuntimeError("worker 未初始化")

    (
        ma_short, ma_mid, ma_long, htf_ma,
        atr_period, atr_ma_window, atr_low_threshold, atr_high_threshold,
        bb_period, bb_std, bb_narrow_threshold, bb_wide_threshold,
        buy_score_threshold, sell_score_threshold, reduce_score_threshold,
        atr_stop_mult, regime_filter_ma, regime_filter_buffer,
        risk_drawdown_stop_threshold, risk_drawdown_lookback,
        confirm_days, cooldown_days, min_hold_bars,
    ) = params
    signal_config = _build_signal_config(
        ma_short=ma_short, ma_mid=ma_mid, ma_long=ma_long, htf_ma=htf_ma,
        atr_period=atr_period, atr_ma_window=atr_ma_window,
        atr_low_threshold=atr_low_threshold, atr_high_threshold=atr_high_threshold,
        bb_period=bb_period, bb_std=bb_std,
        bb_narrow_threshold=bb_narrow_threshold, bb_wide_threshold=bb_wide_threshold,
        buy_score_threshold=buy_score_threshold, sell_score_threshold=sell_score_threshold,
        reduce_score_threshold=reduce_score_threshold, atr_stop_mult=atr_stop_mult,
        regime_filter_ma=regime_filter_ma, regime_filter_buffer=regime_filter_buffer,
        risk_drawdown_stop_threshold=risk_drawdown_stop_threshold,
        risk_drawdown_lookback=risk_drawdown_lookback,
        confirm_days=confirm_days, cooldown_days=cooldown_days,
        min_hold_bars=min_hold_bars,
    )
    summary = _run_candidate(_WORKER_DF, _WORKER_SYMBOL, signal_config, _WORKER_START_DATE, _WORKER_END_DATE)
    return {
        "ma_short": ma_short, "ma_mid": ma_mid, "ma_long": ma_long, "htf_ma": htf_ma,
        "atr_period": atr_period, "atr_ma_window": atr_ma_window,
        "atr_low_threshold": atr_low_threshold, "atr_high_threshold": atr_high_threshold,
        "bb_period": bb_period, "bb_std": bb_std,
        "bb_narrow_threshold": bb_narrow_threshold, "bb_wide_threshold": bb_wide_threshold,
        "buy_score_threshold": buy_score_threshold, "sell_score_threshold": sell_score_threshold,
        "reduce_score_threshold": reduce_score_threshold, "atr_stop_mult": atr_stop_mult,
        "regime_filter_ma": regime_filter_ma, "regime_filter_buffer": regime_filter_buffer,
        "risk_drawdown_stop_threshold": risk_drawdown_stop_threshold,
        "risk_drawdown_lookback": risk_drawdown_lookback,
        "confirm_days": confirm_days, "cooldown_days": cooldown_days,
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


def _stage1(symbol: str, df: pd.DataFrame, start_date: str, end_date: str, workers: int) -> Tuple[pd.DataFrame, Tuple]:
    """Stage 1: MA + HTF trend combination screening."""
    candidate_params = [
        (ma_s, ma_m, ma_l, htf_ma, 14, 40, 0.95, 1.15, 20, 2.0, 0.05, 0.10, 2.0, -1.5, -1.0, 2.5, 120, 1.0, 0.15, 120, 2, 10, 0)
        for ma_s, ma_m, ma_l, htf_ma in product(
            [5, 10, 20],
            [20, 30, 60],
            [60, 120, 250],
            [120, 180, 240],
        )
        if ma_s < ma_m < ma_l <= htf_ma
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [{"symbol": symbol, "name": SYMBOLS[symbol], "stage": "stage1_ma_htf", **row} for row in raw_rows]
    scored = _score_symbol_results(pd.DataFrame(rows), symbol)
    print(f"[STAGE1-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    top_seeds = scored[["ma_short", "ma_mid", "ma_long", "htf_ma"]].drop_duplicates().head(3)
    return scored, tuple(top_seeds.itertuples(index=False, name=None))


def _stage2(symbol: str, df: pd.DataFrame, start_date: str, end_date: str, top_seeds: Tuple, workers: int) -> Tuple[pd.DataFrame, Tuple]:
    """Stage 2: ATR volatility factor."""
    candidate_params = [
        (ma_s, ma_m, ma_l, htf_ma, atr_p, atr_w, atr_low, atr_high, 20, 2.0, 0.05, 0.10, 2.0, -1.5, -1.0, 2.5, 120, 1.0, 0.15, 120, 2, 10, 0)
        for ma_s, ma_m, ma_l, htf_ma in top_seeds
        for atr_p, atr_w, atr_low, atr_high in product(
            [14, 20],
            [20, 40, 60],
            [0.90, 0.95, 1.00],
            [1.10, 1.15, 1.20],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [{"symbol": symbol, "name": SYMBOLS[symbol], "stage": "stage2_atr", **row} for row in raw_rows]
    scored = _score_symbol_results(pd.DataFrame(rows), symbol)
    print(f"[STAGE2-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    top_seeds2 = scored[["ma_short", "ma_mid", "ma_long", "htf_ma", "atr_period", "atr_ma_window", "atr_low_threshold", "atr_high_threshold"]].drop_duplicates().head(2)
    return scored, tuple(top_seeds2.itertuples(index=False, name=None))


def _stage3(symbol: str, df: pd.DataFrame, start_date: str, end_date: str, top_seeds: Tuple, workers: int) -> pd.DataFrame:
    """Stage 3: BB market state factor."""
    candidate_params = [
        (ma_s, ma_m, ma_l, htf_ma, atr_p, atr_w, atr_low, atr_high, bb_p, bb_s, bb_n, bb_w, 2.0, -1.5, -1.0, 2.5, 120, 1.0, 0.15, 120, 2, 10, 0)
        for ma_s, ma_m, ma_l, htf_ma, atr_p, atr_w, atr_low, atr_high in top_seeds
        for bb_p, bb_s, bb_n, bb_w in product(
            [20, 30],
            [1.5, 2.0, 2.5],
            [0.04, 0.05, 0.06],
            [0.08, 0.10, 0.12],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [{"symbol": symbol, "name": SYMBOLS[symbol], "stage": "stage3_bb", **row} for row in raw_rows]
    print(f"[STAGE3-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    return _score_symbol_results(pd.DataFrame(rows), symbol)


def _stage4(symbol: str, df: pd.DataFrame, start_date: str, end_date: str, stage3_df: pd.DataFrame, workers: int) -> pd.DataFrame:
    """Stage 4: Score thresholds."""
    seeds = stage3_df[
        ["ma_short", "ma_mid", "ma_long", "htf_ma", "atr_period", "atr_ma_window",
         "atr_low_threshold", "atr_high_threshold", "bb_period", "bb_std",
         "bb_narrow_threshold", "bb_wide_threshold"]
    ].drop_duplicates().head(2)

    candidate_params = [
        (int(s.ma_short), int(s.ma_mid), int(s.ma_long), int(s.htf_ma),
         int(s.atr_period), int(s.atr_ma_window), float(s.atr_low_threshold), float(s.atr_high_threshold),
         int(s.bb_period), float(s.bb_std), float(s.bb_narrow_threshold), float(s.bb_wide_threshold),
         buy_t, sell_t, reduce_t, 2.5, 120, 1.0, 0.15, 120, 2, 10, 0)
        for s in seeds.itertuples(index=False)
        for buy_t, sell_t, reduce_t in product(
            [1.5, 2.0, 2.5],
            [-1.5, -2.0, -2.5],
            [-1.0, -1.5],
        )
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [{"symbol": symbol, "name": SYMBOLS[symbol], "stage": "stage4_scores", **row} for row in raw_rows]
    print(f"[STAGE4-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    return _score_symbol_results(pd.DataFrame(rows), symbol)


def _stage5(symbol: str, df: pd.DataFrame, start_date: str, end_date: str, stage4_df: pd.DataFrame, workers: int) -> pd.DataFrame:
    """Stage 5: Risk and trading parameters."""
    seeds = stage4_df[
        ["ma_short", "ma_mid", "ma_long", "htf_ma", "atr_period", "atr_ma_window",
         "atr_low_threshold", "atr_high_threshold", "bb_period", "bb_std",
         "bb_narrow_threshold", "bb_wide_threshold", "buy_score_threshold",
         "sell_score_threshold", "reduce_score_threshold"]
    ].drop_duplicates().head(2)

    candidate_params = [
        (int(s.ma_short), int(s.ma_mid), int(s.ma_long), int(s.htf_ma),
         int(s.atr_period), int(s.atr_ma_window), float(s.atr_low_threshold), float(s.atr_high_threshold),
         int(s.bb_period), float(s.bb_std), float(s.bb_narrow_threshold), float(s.bb_wide_threshold),
         float(s.buy_score_threshold), float(s.sell_score_threshold), float(s.reduce_score_threshold),
         atr_stop, rf_ma, rf_buf, dd_stop, dd_lb, confirm, cooldown, min_hold)
        for s in seeds.itertuples(index=False)
        for atr_stop, rf_ma, rf_buf, dd_stop, dd_lb in product(
            [2.0, 2.5, 3.0],
            [120, 180, 240],
            [0.98, 1.00, 1.02],
            [0.12, 0.15, 0.18],
            [120, 180, 240],
        )
        for confirm, cooldown, min_hold in product([1, 2], [5, 10], [0, 3])
    ]
    raw_rows, effective_workers = _run_candidate_grid(candidate_params, df, symbol, start_date, end_date, workers)
    rows = [{"symbol": symbol, "name": SYMBOLS[symbol], "stage": "stage5_risk", **row} for row in raw_rows]
    print(f"[STAGE5-WORKERS] {symbol} requested={workers} effective={effective_workers} candidates={len(candidate_params)}", flush=True)
    return _score_symbol_results(pd.DataFrame(rows), symbol)


def main() -> None:
    parser = argparse.ArgumentParser(description="多因子动态自适应趋势跟踪策略参数调优")
    parser.add_argument("--symbols", default="000001.SH,399001.SZ,399006.SZ,000016.SH,000300.SH,000905.SH,000852.SH")
    parser.add_argument("--start-date", default="2012-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--output", default="output/multi_factor_adaptive_tuning")
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
    all_stage5_rows: List[Dict[str, object]] = []
    stage_frames: Dict[str, List[pd.DataFrame]] = {f"stage{i}": [] for i in range(1, 6)}

    for symbol in symbols:
        print(f"[STAGE1] {symbol}", flush=True)
        df = manager.get_data(symbol)
        if df is None or df.empty:
            print(f"SKIP {symbol}: empty data", flush=True)
            continue

        stage1_df, top_seeds1 = _stage1(symbol, df, args.start_date, args.end_date, max(1, int(args.workers)))
        stage_frames["stage1"].append(stage1_df)
        best1 = stage1_df.iloc[0]
        print(f"[STAGE1-BEST] {symbol} MA{int(best1['ma_short'])}/{int(best1['ma_mid'])}/{int(best1['ma_long'])} HTF{int(best1['htf_ma'])} excess={float(best1['annualized_excess_return']):.4f} mdd={float(best1['max_drawdown']):.4f}", flush=True)

        print(f"[STAGE2] {symbol}", flush=True)
        stage2_df, top_seeds2 = _stage2(symbol, df, args.start_date, args.end_date, top_seeds1, max(1, int(args.workers)))
        stage_frames["stage2"].append(stage2_df)
        best2 = stage2_df.iloc[0]
        print(f"[STAGE2-BEST] {symbol} ATR{int(best2['atr_period'])}/{int(best2['atr_ma_window'])} low={float(best2['atr_low_threshold']):.2f} high={float(best2['atr_high_threshold']):.2f} excess={float(best2['annualized_excess_return']):.4f} eligible={bool(best2['eligible'])}", flush=True)

        print(f"[STAGE3] {symbol}", flush=True)
        stage3_df = _stage3(symbol, df, args.start_date, args.end_date, top_seeds2, max(1, int(args.workers)))
        stage_frames["stage3"].append(stage3_df)
        best3 = stage3_df.iloc[0]
        print(f"[STAGE3-BEST] {symbol} BB{int(best3['bb_period'])} narrow={float(best3['bb_narrow_threshold']):.3f} wide={float(best3['bb_wide_threshold']):.3f} excess={float(best3['annualized_excess_return']):.4f} eligible={bool(best3['eligible'])}", flush=True)

        print(f"[STAGE4] {symbol}", flush=True)
        stage4_df = _stage4(symbol, df, args.start_date, args.end_date, stage3_df, max(1, int(args.workers)))
        stage_frames["stage4"].append(stage4_df)
        best4 = stage4_df.iloc[0]
        print(f"[STAGE4-BEST] {symbol} buy={float(best4['buy_score_threshold']):.1f} sell={float(best4['sell_score_threshold']):.1f} excess={float(best4['annualized_excess_return']):.4f} eligible={bool(best4['eligible'])}", flush=True)

        print(f"[STAGE5] {symbol}", flush=True)
        stage5_df = _stage5(symbol, df, args.start_date, args.end_date, stage4_df, max(1, int(args.workers)))
        stage_frames["stage5"].append(stage5_df)
        all_stage5_rows.append(stage5_df.iloc[0].to_dict())
        best5 = stage5_df.iloc[0]
        print(f"[STAGE5-BEST] {symbol} confirm={int(best5['confirm_days'])} cooldown={int(best5['cooldown_days'])} excess={float(best5['annualized_excess_return']):.4f} mdd={float(best5['max_drawdown']):.4f} trades={int(best5['trade_count'])} eligible={bool(best5['eligible'])}", flush=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for i in range(1, 6):
        key = f"stage{i}"
        full_df = pd.concat(stage_frames[key], ignore_index=True) if stage_frames[key] else pd.DataFrame()
        full_df.to_csv(summary_dir / f"multi_factor_stage{i}_full_{stamp}.csv", index=False)

    stage5_best = pd.DataFrame(all_stage5_rows)
    stage5_best.to_csv(summary_dir / f"multi_factor_stage5_best_{stamp}.csv", index=False)

    report_lines = [
        "# 多因子动态自适应趋势跟踪策略参数调优",
        "",
        f"- 测试区间: {args.start_date} 到 {args.end_date}",
        f"- 指数数量: {len(stage5_best)}",
        "",
        "## Stage 5 Best",
        "",
    ]
    for row in stage5_best.sort_values("objective_score", ascending=False).to_dict("records"):
        report_lines.extend([
            f"### {row['symbol']} {row['name']}",
            f"- objective_score: {float(row['objective_score']):.4f}",
            f"- MA: {int(row['ma_short'])}/{int(row['ma_mid'])}/{int(row['ma_long'])} HTF={int(row['htf_ma'])}",
            f"- ATR: period={int(row['atr_period'])} window={int(row['atr_ma_window'])} low={float(row['atr_low_threshold']):.2f} high={float(row['atr_high_threshold']):.2f}",
            f"- BB: period={int(row['bb_period'])} std={float(row['bb_std']):.1f} narrow={float(row['bb_narrow_threshold']):.3f} wide={float(row['bb_wide_threshold']):.3f}",
            f"- Score: buy={float(row['buy_score_threshold']):.1f} sell={float(row['sell_score_threshold']):.1f} reduce={float(row['reduce_score_threshold']):.1f}",
            f"- annualized_excess_return: {float(row['annualized_excess_return']):.4%}",
            f"- max_drawdown: {float(row['max_drawdown']):.4%}",
            f"- trade_count: {int(row['trade_count'])}",
            f"- whipsaw_rate: {float(row.get('whipsaw_rate', 0)):.4f}",
            f"- eligible: {bool(row['eligible'])}",
            "",
        ])
    report_path = reports_dir / f"multi_factor_tuning_report_{stamp}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"SAVED {report_path}")


if __name__ == "__main__":
    main()
