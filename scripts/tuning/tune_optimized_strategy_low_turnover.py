# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Dict, List

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


def _build_signal_config(params: Dict[str, object]) -> InvestmentSignalConfig:
    return InvestmentSignalConfig(
        signal_model="multi_factor_adaptive_v1",
        initial_position=0.0,
        ma_short=int(params["ma_short"]),
        ma_mid=int(params["ma_mid"]),
        ma_long=int(params["ma_long"]),
        atr_period=int(params["atr_period"]),
        atr_ma_window=int(params["atr_ma_window"]),
        atr_low_threshold=float(params["atr_low_threshold"]),
        atr_high_threshold=float(params["atr_high_threshold"]),
        bb_period=int(params["bb_period"]),
        bb_std=float(params["bb_std"]),
        bb_narrow_threshold=float(params["bb_narrow_threshold"]),
        bb_wide_threshold=float(params["bb_wide_threshold"]),
        regime_filter_ma=int(params["regime_filter_ma"]),
        regime_filter_buffer=float(params["regime_filter_buffer"]),
        regime_filter_reduce_enabled=True,
        risk_drawdown_stop_threshold=float(params["risk_drawdown_stop_threshold"]),
        risk_drawdown_lookback=int(params["risk_drawdown_lookback"]),
        buy_confirm_days=int(params["confirm_days"]),
        sell_confirm_days=int(params["confirm_days"]),
        cooldown_days=int(params["cooldown_days"]),
        min_hold_bars=int(params["min_hold_bars"]),
        buy_score_threshold=float(params["buy_score_threshold"]),
        sell_score_threshold=float(params["sell_score_threshold"]),
        trend_weight=0.35,
        volatility_weight=0.30,
        market_state_weight=0.25,
        momentum_weight=0.10,
    )


def _init_worker(df_payload: Dict[str, List[object]], symbol: str, start_date: str, end_date: str) -> None:
    global _WORKER_DF, _WORKER_SYMBOL, _WORKER_START_DATE, _WORKER_END_DATE
    for env_name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[env_name] = "1"
    _WORKER_DF = pd.DataFrame(df_payload)
    _WORKER_SYMBOL = symbol
    _WORKER_START_DATE = start_date
    _WORKER_END_DATE = end_date


def _run_candidate(signal_config: InvestmentSignalConfig) -> Dict[str, object]:
    if _WORKER_DF is None or _WORKER_SYMBOL is None or _WORKER_START_DATE is None or _WORKER_END_DATE is None:
        raise RuntimeError("worker 未初始化")
    signal_df = generate_investment_signals(
        df=_WORKER_DF,
        symbol=_WORKER_SYMBOL,
        signal_config=signal_config,
        lppl_config=LPPLConfig(window_range=[20], n_workers=1),
        use_ensemble=False,
        start_date=_WORKER_START_DATE,
        end_date=_WORKER_END_DATE,
        scan_step=1,
    )
    _, _, summary = run_strategy_backtest(
        signal_df,
        BacktestConfig(
            initial_capital=1_000_000.0,
            buy_fee=0.0003,
            sell_fee=0.0003,
            slippage=0.0005,
            start_date=_WORKER_START_DATE,
            end_date=_WORKER_END_DATE,
        ),
    )
    return summary


def _evaluate_candidate_worker(params: Dict[str, object]) -> Dict[str, object]:
    signal_config = _build_signal_config(params)
    return {**params, **_run_candidate(signal_config)}


def _effective_workers(requested_workers: int, candidate_count: int) -> int:
    cpu_limit = max(1, (os.cpu_count() or 1) - 2)
    return max(1, min(int(requested_workers), cpu_limit, candidate_count))


def _map_chunksize(candidate_count: int, workers: int) -> int:
    if workers <= 1:
        return 1
    return max(1, candidate_count // (workers * 2))


def _score(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    max_dd_cap = -0.40 if symbol in HIGH_BETA_SYMBOLS else -0.35
    return score_signal_tuning_results(
        df,
        min_trade_count=3,
        max_drawdown_cap=max_dd_cap,
        turnover_cap=6.0,
        whipsaw_cap=0.35,
        scoring_profile="balanced",
        hard_reject=True,
    )


def _candidate_grid(seed: pd.Series) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for confirm_days, cooldown_days, min_hold_bars, buy_score_threshold, sell_score_threshold, regime_filter_buffer, risk_dd in product(
        [2, 3, 4, 5],
        [10, 15, 20, 30],
        [5, 10, 15, 20],
        [0.45, 0.55, 0.65, 0.75],
        [-0.45, -0.55, -0.65, -0.75],
        [1.00, 1.01, 1.02],
        [0.12, 0.15, 0.18],
    ):
        rows.append(
            {
                "ma_short": int(seed["ma_short"]),
                "ma_mid": int(seed["ma_mid"]),
                "ma_long": int(seed["ma_long"]),
                "atr_period": int(seed["atr_period"]),
                "atr_ma_window": int(seed["atr_ma_window"]),
                "atr_low_threshold": float(seed["atr_low_threshold"]),
                "atr_high_threshold": float(seed["atr_high_threshold"]),
                "bb_period": int(seed["bb_period"]),
                "bb_std": float(seed["bb_std"]),
                "bb_narrow_threshold": float(seed["bb_narrow_threshold"]),
                "bb_wide_threshold": float(seed["bb_wide_threshold"]),
                "confirm_days": confirm_days,
                "cooldown_days": cooldown_days,
                "min_hold_bars": min_hold_bars,
                "buy_score_threshold": buy_score_threshold,
                "sell_score_threshold": sell_score_threshold,
                "regime_filter_ma": int(seed["regime_filter_ma"]),
                "regime_filter_buffer": regime_filter_buffer,
                "risk_drawdown_stop_threshold": risk_dd,
                "risk_drawdown_lookback": int(seed["risk_drawdown_lookback"]),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="optimized_strategy_v3 降频收缩测试")
    parser.add_argument(
        "--seed-csv",
        default="output/retest_20260401/optimized_strategy_smoke_retry3/summary/optimized_v3_stage2_best_20260401_162342.csv",
    )
    parser.add_argument("--start-date", default="2012-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--output", default="output/retest_20260401/optimized_strategy_low_turnover")
    parser.add_argument("--workers", type=int, default=30)
    args = parser.parse_args()

    seed_df = pd.read_csv(args.seed_csv)
    out_dir = Path(args.output)
    summary_dir = out_dir / "summary"
    reports_dir = out_dir / "reports"
    summary_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    manager = DataManager()
    best_rows: List[Dict[str, object]] = []
    all_frames: List[pd.DataFrame] = []

    for _, seed in seed_df.iterrows():
        symbol = str(seed["symbol"])
        print(f"[LOW-TURNOVER] {symbol}", flush=True)
        df = manager.get_data(symbol)
        if df is None or df.empty:
            print(f"SKIP {symbol}: empty data", flush=True)
            continue

        candidates = _candidate_grid(seed)
        effective_workers = _effective_workers(args.workers, len(candidates))
        df_payload = df.to_dict(orient="list")
        print(
            f"[LOW-TURNOVER-WORKERS] {symbol} requested={args.workers} effective={effective_workers} candidates={len(candidates)}",
            flush=True,
        )

        if effective_workers <= 1:
            _init_worker(df_payload, symbol, args.start_date, args.end_date)
            raw_rows = [_evaluate_candidate_worker(item) for item in candidates]
        else:
            with ProcessPoolExecutor(
                max_workers=effective_workers,
                initializer=_init_worker,
                initargs=(df_payload, symbol, args.start_date, args.end_date),
            ) as executor:
                raw_rows = list(
                    executor.map(
                        _evaluate_candidate_worker,
                        candidates,
                        chunksize=_map_chunksize(len(candidates), effective_workers),
                    )
                )

        frame = pd.DataFrame(
            [{"symbol": symbol, "name": SYMBOLS[symbol], "stage": "low_turnover_refine", **row} for row in raw_rows]
        )
        scored = _score(frame, symbol).sort_values(
            ["eligible", "annualized_excess_return", "annualized_turnover_rate", "trade_count"],
            ascending=[False, False, True, True],
        )
        all_frames.append(scored)
        best = scored.iloc[0].to_dict()
        best_rows.append(best)
        print(
            f"[LOW-TURNOVER-BEST] {symbol} excess={float(best['annualized_excess_return']):.4f} "
            f"mdd={float(best['max_drawdown']):.4f} trades={int(best['trade_count'])} "
            f"turnover={float(best.get('annualized_turnover_rate', 0.0)):.4f} eligible={bool(best['eligible'])}",
            flush=True,
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    full_df = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    best_df = pd.DataFrame(best_rows)
    full_path = summary_dir / f"optimized_v3_low_turnover_full_{stamp}.csv"
    best_path = summary_dir / f"optimized_v3_low_turnover_best_{stamp}.csv"
    full_df.to_csv(full_path, index=False)
    best_df.to_csv(best_path, index=False)

    report_lines = [
        "# optimized_strategy_v3 降频收缩测试",
        "",
        f"- 种子来源: `{args.seed_csv}`",
        f"- 测试区间: {args.start_date} 到 {args.end_date}",
        f"- 指数数量: {len(best_df)}",
        "",
    ]
    for row in best_df.sort_values("annualized_excess_return", ascending=False).to_dict("records"):
        report_lines.extend(
            [
                f"## {row['symbol']} {row['name']}",
                f"- annualized_excess_return: {float(row['annualized_excess_return']):.4%}",
                f"- max_drawdown: {float(row['max_drawdown']):.4%}",
                f"- trade_count: {int(row['trade_count'])}",
                f"- annualized_turnover_rate: {float(row.get('annualized_turnover_rate', 0.0)):.4f}",
                f"- whipsaw_rate: {float(row.get('whipsaw_rate', 0.0)):.4f}",
                f"- confirm/cooldown/min_hold: {int(row['confirm_days'])}/{int(row['cooldown_days'])}/{int(row['min_hold_bars'])}",
                f"- buy/sell score: {float(row['buy_score_threshold']):.2f}/{float(row['sell_score_threshold']):.2f}",
                f"- eligible: {bool(row['eligible'])}",
                "",
            ]
        )
    report_path = reports_dir / f"optimized_v3_low_turnover_report_{stamp}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"SAVED {full_path}")
    print(f"SAVED {best_path}")
    print(f"SAVED {report_path}")


if __name__ == "__main__":
    main()
