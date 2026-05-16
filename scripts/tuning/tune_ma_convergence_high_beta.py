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

_WORKER_DF: pd.DataFrame | None = None
_WORKER_SYMBOL: str | None = None
_WORKER_START_DATE: str | None = None
_WORKER_END_DATE: str | None = None


def _build_signal_config(params: Dict[str, object]) -> InvestmentSignalConfig:
    return InvestmentSignalConfig(
        signal_model="ma_convergence_atr_v1",
        initial_position=0.0,
        bb_period=int(params["bb_period"]),
        bb_std=float(params["bb_std"]),
        bb_width_cap=float(params["bb_width_cap"]),
        atr_period=int(params["atr_period"]),
        atr_ma_window=int(params["atr_ma_window"]),
        atr_low_percentile=float(params["atr_low_percentile"]),
        atr_high_percentile=float(params["atr_high_percentile"]),
        atr_percentile_window=int(params["atr_percentile_window"]),
        ma_short=int(params["ma_short"]),
        ma_mid=int(params["ma_mid"]),
        ma_long=int(params["ma_long"]),
        regime_filter_ma=int(params["regime_filter_ma"]),
        regime_filter_buffer=float(params["regime_filter_buffer"]),
        regime_filter_reduce_enabled=True,
        risk_drawdown_stop_threshold=float(params["risk_drawdown_stop_threshold"]),
        risk_drawdown_lookback=int(params["risk_drawdown_lookback"]),
        buy_confirm_days=int(params["confirm_days"]),
        sell_confirm_days=int(params["confirm_days"]),
        cooldown_days=int(params["cooldown_days"]),
        min_hold_bars=int(params["min_hold_bars"]),
    )


def _init_worker(df_payload: Dict[str, List[object]], symbol: str, start_date: str, end_date: str) -> None:
    global _WORKER_DF, _WORKER_SYMBOL, _WORKER_START_DATE, _WORKER_END_DATE
    for env_name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[env_name] = "1"
    _WORKER_DF = pd.DataFrame(df_payload)
    _WORKER_SYMBOL = symbol
    _WORKER_START_DATE = start_date
    _WORKER_END_DATE = end_date


def _evaluate_candidate_worker(params: Dict[str, object]) -> Dict[str, object]:
    if _WORKER_DF is None or _WORKER_SYMBOL is None or _WORKER_START_DATE is None or _WORKER_END_DATE is None:
        raise RuntimeError("worker 未初始化")
    signal_config = _build_signal_config(params)
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
    return {**params, **summary}


def _effective_workers(requested_workers: int, candidate_count: int) -> int:
    cpu_limit = max(1, (os.cpu_count() or 1) - 2)
    return max(1, min(int(requested_workers), cpu_limit, candidate_count))


def _map_chunksize(candidate_count: int, workers: int) -> int:
    if workers <= 1:
        return 1
    return max(1, candidate_count // (workers * 2))


def _score(df: pd.DataFrame) -> pd.DataFrame:
    return score_signal_tuning_results(
        df,
        min_trade_count=3,
        max_drawdown_cap=-0.45,
        turnover_cap=12.0,
        whipsaw_cap=0.55,
        scoring_profile="balanced",
        hard_reject=True,
    )


def _grid() -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    base_params = {
        "bb_period": 20,
        "bb_std": 1.5,
        "bb_width_cap": 0.02,
        "atr_period": 14,
        "atr_ma_window": 20,
        "atr_low_percentile": 0.15,
        "atr_high_percentile": 0.75,
        "atr_percentile_window": 126,
        "ma_short": 5,
        "ma_mid": 20,
        "ma_long": 60,
        "regime_filter_ma": 120,
        "regime_filter_buffer": 0.98,
        "risk_drawdown_stop_threshold": 0.12,
        "risk_drawdown_lookback": 120,
        "confirm_days": 1,
        "cooldown_days": 5,
        "min_hold_bars": 0,
    }
    for bb_period, bb_std, bb_width_cap in product([20, 30], [1.5, 2.0], [0.02, 0.03, 0.05, 0.08]):
        for atr_period, atr_ma_window, atr_low, atr_high, atr_window in product(
            [14, 20],
            [20, 40],
            [0.15, 0.20, 0.25, 0.30],
            [0.60, 0.65, 0.70, 0.75],
            [126],
        ):
            for ma_short, ma_mid, ma_long in product([5, 10], [20, 30], [60, 120]):
                if not (ma_short < ma_mid < ma_long):
                    continue
                for regime_filter_ma, regime_filter_buffer, dd_stop, dd_lb in product(
                    [60, 120],
                    [0.95, 0.98, 1.00],
                    [0.12, 0.15],
                    [120, 180],
                ):
                    for confirm_days, cooldown_days, min_hold_bars in product([1, 2], [3, 5], [0, 3]):
                        params = {
                            "bb_period": bb_period,
                            "bb_std": bb_std,
                            "bb_width_cap": bb_width_cap,
                            "atr_period": atr_period,
                            "atr_ma_window": atr_ma_window,
                            "atr_low_percentile": atr_low,
                            "atr_high_percentile": atr_high,
                            "atr_percentile_window": atr_window,
                            "ma_short": ma_short,
                            "ma_mid": ma_mid,
                            "ma_long": ma_long,
                            "regime_filter_ma": regime_filter_ma,
                            "regime_filter_buffer": regime_filter_buffer,
                            "risk_drawdown_stop_threshold": dd_stop,
                            "risk_drawdown_lookback": dd_lb,
                            "confirm_days": confirm_days,
                            "cooldown_days": cooldown_days,
                            "min_hold_bars": min_hold_bars,
                        }
                        diff_count = sum(1 for key, value in params.items() if base_params[key] != value)
                        if diff_count <= 3:
                            rows.append(params)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="399006.SZ 高波动适配 MA Convergence 搜索")
    parser.add_argument("--symbol", default="399006.SZ")
    parser.add_argument("--start-date", default="2012-01-01")
    parser.add_argument("--end-date", default="2020-12-31")
    parser.add_argument("--output", default="output/retest_20260401/ma_convergence_high_beta")
    parser.add_argument("--workers", type=int, default=30)
    args = parser.parse_args()

    out_dir = Path(args.output)
    summary_dir = out_dir / "summary"
    reports_dir = out_dir / "reports"
    summary_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    manager = DataManager()
    df = manager.get_data(args.symbol)
    if df is None or df.empty:
        raise SystemExit(f"empty data: {args.symbol}")

    candidates = _grid()
    effective_workers = _effective_workers(args.workers, len(candidates))
    df_payload = df.to_dict(orient="list")
    print(f"[HIGH-BETA] {args.symbol} requested={args.workers} effective={effective_workers} candidates={len(candidates)}", flush=True)

    if effective_workers <= 1:
        _init_worker(df_payload, args.symbol, args.start_date, args.end_date)
        raw_rows = [_evaluate_candidate_worker(item) for item in candidates]
    else:
        with ProcessPoolExecutor(
            max_workers=effective_workers,
            initializer=_init_worker,
            initargs=(df_payload, args.symbol, args.start_date, args.end_date),
        ) as executor:
            raw_rows = list(
                executor.map(
                    _evaluate_candidate_worker,
                    candidates,
                    chunksize=_map_chunksize(len(candidates), effective_workers),
                )
            )

    frame = pd.DataFrame([{"symbol": args.symbol, "name": SYMBOLS[args.symbol], "stage": "high_beta_search", **row} for row in raw_rows])
    scored = _score(frame).sort_values(["eligible", "annualized_excess_return", "trade_count"], ascending=[False, False, True])
    best_df = scored.head(20)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    full_path = summary_dir / f"ma_convergence_high_beta_full_{stamp}.csv"
    best_path = summary_dir / f"ma_convergence_high_beta_best_{stamp}.csv"
    scored.to_csv(full_path, index=False)
    best_df.to_csv(best_path, index=False)

    report_lines = [
        "# 399006.SZ 高波动适配 MA Convergence 搜索",
        "",
        f"- 区间: {args.start_date} 到 {args.end_date}",
        f"- 候选数: {len(candidates)}",
        "",
    ]
    for row in best_df.to_dict("records"):
        report_lines.extend(
            [
                f"## excess={float(row['annualized_excess_return']):.4%} eligible={bool(row['eligible'])}",
                f"- bb: {int(row['bb_period'])}/{float(row['bb_std']):.1f}/{float(row['bb_width_cap']):.2f}",
                f"- atr: {int(row['atr_period'])}/{int(row['atr_ma_window'])} low={float(row['atr_low_percentile']):.2f} high={float(row['atr_high_percentile']):.2f} win={int(row['atr_percentile_window'])}",
                f"- ma: {int(row['ma_short'])}/{int(row['ma_mid'])}/{int(row['ma_long'])}",
                f"- regime: {int(row['regime_filter_ma'])}@{float(row['regime_filter_buffer']):.2f}",
                f"- risk: {float(row['risk_drawdown_stop_threshold']):.2f}/{int(row['risk_drawdown_lookback'])}",
                f"- trade: confirm={int(row['confirm_days'])} cooldown={int(row['cooldown_days'])} min_hold={int(row['min_hold_bars'])}",
                f"- mdd: {float(row['max_drawdown']):.4%}",
                f"- trades: {int(row['trade_count'])}",
                "",
            ]
        )
    report_path = reports_dir / f"ma_convergence_high_beta_report_{stamp}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"SAVED {full_path}")
    print(f"SAVED {best_path}")
    print(f"SAVED {report_path}")


if __name__ == "__main__":
    main()
