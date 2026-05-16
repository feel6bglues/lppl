import csv
import math
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.constants import TDX_DATA_DIR
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.parallel import get_optimal_workers, worker_init
from src.strategies.registry import STRATEGY_MAP

MC_SIMS = 10000
COST_BUY = 0.00075
COST_SELL = 0.00175

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STOCK_LIST_PATH = PROJECT_ROOT / "data" / "stock_list.csv"


def load_stocks(csv_path: Path, limit: int = 99999) -> List[Dict]:
    syms = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            c = row.get("code", "").strip()
            m = row.get("market", "").strip().upper()
            n = row.get("name", "").replace("\x00", "").strip()
            if not (c.isdigit() and len(c) == 6 and m in {"SH", "SZ"}):
                continue
            if c.startswith(("600", "601", "603", "605", "688", "689",
                             "000", "001", "002", "003", "300", "301", "302")):
                syms.append({"symbol": f"{c}.{m}", "code": c, "market": m, "name": n})
                if len(syms) >= limit:
                    break
    return syms


def load_csi300() -> Optional[pd.DataFrame]:
    if not TDX_DATA_DIR:
        return None
    p = Path(TDX_DATA_DIR) / "sh" / "lday" / "sh000300.day"
    if not p.exists():
        return None
    df = load_tdx_data(str(p))
    if df is not None and not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    return None


def gen_windows(csi: pd.DataFrame, n: int = 20, min_year: int = 0, max_year: int = 9999,
                seed: int = 42) -> List[str]:
    if csi is None or len(csi) < 200:
        return []
    d = csi["date"].dt.strftime("%Y-%m-%d").tolist()
    d = [x for x in d if int(x[:4]) >= min_year and int(x[:4]) <= max_year]
    if len(d) < n + 200:
        return []
    random.seed(seed)
    return sorted(random.sample(d[:len(d) - 200], min(n, len(d) - 200)))


def ann_sharpe(rets: np.ndarray, avg_days: float) -> float:
    if len(rets) < 5 or np.std(rets) == 0 or avg_days <= 0:
        return 0.0
    return float(np.mean(rets) / np.std(rets) * math.sqrt(252.0 / avg_days))


def compute_stats(sub_df: pd.DataFrame) -> Dict:
    rets = sub_df["ret"].values
    ad = float(np.mean(sub_df["days"]))
    return {
        "n": len(sub_df),
        "mean_ret": round(float(np.mean(rets)), 2),
        "median_ret": round(float(np.median(rets)), 2),
        "std": round(float(np.std(rets)), 2),
        "win_rate": round(float(sum(rets > 0) / len(rets) * 100), 1),
        "avg_days": round(ad, 1),
        "sharpe": round(ann_sharpe(rets, ad), 3),
    }


def process_stock(args: Tuple) -> List[Dict]:
    si, windows, csi, strategies, cost_buy, cost_sell = args
    sym = si["symbol"]
    trades = []
    try:
        dm = DataManager()
        df = dm.get_data(sym)
        if df is None or df.empty or len(df) < 300:
            return trades
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for w in windows:
            for s_name in strategies:
                func = STRATEGY_MAP.get(s_name)
                if func is None:
                    continue
                try:
                    kwargs = {"cost_buy": cost_buy, "cost_sell": cost_sell}
                    r = func(df, w, csi, **kwargs) if s_name == "wyckoff" else func(df, w, **kwargs)
                    if r:
                        trades.append({"strategy": s_name, "symbol": sym, "window": w, **r})
                except Exception:
                    continue
    except Exception:
        pass
    return trades


def run_backtest(strategies: List[str], n_windows: int = 20,
                 min_year: int = 0, max_year: int = 9999,
                 with_costs: bool = True, output_dir: str = "",
                 n_stocks_limit: int = 99999) -> Dict:
    np.random.seed(42)

    effective_buy = COST_BUY if with_costs else 0.0
    effective_sell = COST_SELL if with_costs else 0.0

    stocks = load_stocks(STOCK_LIST_PATH, n_stocks_limit)
    csi = load_csi300()
    windows = gen_windows(csi, n_windows, min_year, max_year)

    all_trades = []
    mw = get_optimal_workers()
    bs = mw * 4
    args_list = [(s, windows, csi, strategies, effective_buy, effective_sell) for s in stocks]

    with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
        for b in range(0, len(args_list), bs):
            batch = args_list[b:b + bs]
            futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for f in as_completed(futures):
                try:
                    all_trades.extend(f.result(timeout=300))
                except Exception:
                    pass

    if not all_trades:
        return {"config": {"strategies": strategies, "n_trades": 0}}

    df = pd.DataFrame(all_trades)

    results = {}
    for sn in strategies:
        sub = df[df["strategy"] == sn]
        if len(sub) >= 5:
            results[sn] = compute_stats(sub)

    corr_data = {}
    strats = list(results.keys())
    for i, t1 in enumerate(strats):
        for t2 in strats[i + 1:]:
            merged = df[df["strategy"] == t1][["window", "symbol", "ret"]].merge(
                df[df["strategy"] == t2][["window", "symbol", "ret"]],
                on=["window", "symbol"], suffixes=("_1", "_2"))
            if len(merged) >= 5:
                corr_data[f"{t1}_vs_{t2}"] = {
                    "corr": round(float(merged["ret_1"].corr(merged["ret_2"])), 3),
                    "n": len(merged)}

    n_strat = len(strats)
    if n_strat >= 2:
        s_vals = [results[s]["sharpe"] for s in strats]
        avg_s = np.mean(s_vals)
        rho_matrix = np.ones((n_strat, n_strat))
        for i in range(n_strat):
            for j in range(n_strat):
                if i < j:
                    k = f"{strats[i]}_vs_{strats[j]}"
                    if k in corr_data:
                        rho_matrix[i][j] = rho_matrix[j][i] = corr_data[k]["corr"]
        avg_rho = (np.sum(rho_matrix) - n_strat) / (n_strat * (n_strat - 1))
        combo = avg_s * math.sqrt(n_strat / (1 + (n_strat - 1) * avg_rho))
    elif n_strat == 1:
        combo = results[strats[0]]["sharpe"]
    else:
        combo = 0

    mc = {}
    for sn in strats:
        sub = df[df["strategy"] == sn]
        if len(sub) < 20:
            continue
        rets = sub["ret"].values
        ad = float(np.mean(sub["days"]))
        sims = [ann_sharpe(np.random.choice(rets, size=len(rets), replace=True), ad)
                for _ in range(MC_SIMS)]
        mc[sn] = {
            "mean": round(float(np.mean(sims)), 3),
            "ci_5": round(float(np.percentile(sims, 5)), 3),
            "ci_95": round(float(np.percentile(sims, 95)), 3),
            "p_pos": round(float(sum(s > 0 for s in sims) / len(sims) * 100), 1),
        }

    sb_warning = "universe is today's stock list, not historical; results may be optimistic"
    return {
        "config": {
            "n_stocks": len(stocks),
            "n_windows": n_windows,
            "min_year": min_year,
            "max_year": max_year,
            "mc_seed": 42,
            "window_seed": 42,
            "with_costs": with_costs,
            "cost_model": {"buy_pct": COST_BUY * 100, "sell_pct": COST_SELL * 100,
                           "round_trip_pct": (COST_BUY + COST_SELL) * 100},
            "strategies_used": strategies,
        },
        "strategies": results,
        "correlations": corr_data,
        "portfolio": {
            "multi_strat_sharpe": round(combo, 3),
            "method": "estimated_from_correlation",
            "formula": "avg(sharpe) * sqrt(n / (1 + (n-1) * avg(corr)))",
            "limitation": "基于各策略独立夏普和平均相关性估算, 非真实组合净值序列",
        },
        "monte_carlo": mc,
        "survivorship_bias_warning": sb_warning,
        "reproducibility": {
            "mc_seeded": True,
            "mc_seed": 42,
            "window_seeded": True,
            "window_seed": 42,
            "windows": windows,
            "universe_size": len(stocks),
            "universe_source": str(STOCK_LIST_PATH),
            "universe_has_delisted_stocks": False,
            "survivorship_bias_note": sb_warning,
        },
    }
