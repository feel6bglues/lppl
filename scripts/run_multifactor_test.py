#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff 多因子合成策略验证 (P2)
=================================
因子:
  1. Wyckoff (v2+执行逻辑)        权重: 0.5  (核心信号)
  2. MA/ATR趋势过滤                 权重: 0.3  (个股趋势确认)
  3. LPPL泡沫过滤                   权重: 0.2  (市场级风险控制)

执行流程:
  NTZ过滤 → 因子加权评分 → 达标交易 → v2+三阶段执行
"""

import csv
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.parallel import get_optimal_workers, worker_init
from src.wyckoff.engine import WyckoffEngine

# === 配置 ===
N_STOCKS = 99999
N_WINDOWS = 20
MAX_HOLD = 180
SEED = 42
N_BOOTSTRAP = 2000
CSI300_TDX_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")
OUTPUT_DIR = PROJECT_ROOT / "output" / "wyckoff_multifactor_test"

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "time_stop_days": 45, "max_hold_days": 90},
    "bear":  {"atr_mult": 2.5, "time_stop_days": 90, "max_hold_days": 180},
    "bull":  {"atr_mult": 3.0, "time_stop_days": 60, "max_hold_days": 120},
    "unknown": {"atr_mult": 2.0, "time_stop_days": 60, "max_hold_days": 120},
}

# 因子权重
W_WYCKOFF = 0.6
W_MAATR = 0.4
W_LPPL = 0.0  # LPPL数据陈旧,暂不启用
SCORE_THRESHOLD = 0.35  # 综合评分>0.35才交易

# LPPL参数缓存
_lppl_cache = {}
_lppl_loaded = False


def load_lppl_params() -> Dict:
    """加载所有LPPL参数文件"""
    if _lppl_cache:
        return _lppl_cache
    params_dir = PROJECT_ROOT / "output" / "lppl" / "params"
    lppl_data = {}
    if params_dir.exists():
        for f in sorted(params_dir.glob("lppl_params_*.json")):
            try:
                data = json.load(f.open())
                params_list = data.get("parameters", [])
                for entry in params_list:
                    idx = entry.get("symbol", "")
                    params = entry.get("params", [])
                    rmse = entry.get("rmse", 1)
                    # LPPL置信度 = 1/rmse 归一化到0-1
                    conf = min(100, max(0, (1.0 / max(rmse, 0.01)) * 10))
                    omega = abs(params[2]) if len(params) > 2 else 0
                    lppl_data[idx] = {"confidence": round(conf), "rmse": rmse, "omega": omega}
            except Exception:
                pass
    _lppl_cache.update(lppl_data)
    return lppl_data


def get_lppl_score(index_symbol: str = "000001.SH") -> float:
    """
    LPPL泡沫评分: 0=无泡沫, 1=严重泡沫
    当LPPL置信度>70%且omega在合理范围时判定为泡沫
    """
    lp = load_lppl_params()
    idx_data = lp.get(index_symbol)
    if not idx_data:
        return 0.0
    conf = idx_data["confidence"]
    rmse = idx_data.get("rmse", 1)
    # 置信度高 + 拟合质量好 + omega在泡沫范围
    if conf > 70 and rmse < 0.1:
        return min(1.0, conf / 100)
    return 0.0


def get_maatr_score(df: pd.DataFrame, as_of_date: str) -> float:
    """
    MA/ATR趋势评分: 0=强下降趋势, 1=强上升趋势
    基于MA20/MA60交叉和价格位置
    """
    as_of = pd.Timestamp(as_of_date)
    hist = df[df["date"] <= as_of].tail(100)
    if len(hist) < 60:
        return 0.5

    close = float(hist.iloc[-1]["close"])
    ma20 = float(hist.tail(20)["close"].mean())
    ma60 = float(hist.tail(60)["close"].mean())

    # 趋势方向: MA20 > MA60 = 上升, 否则下降
    trend_score = 0.5 + 0.5 * ((ma20 - ma60) / ma60)  # 0-1范围
    trend_score = max(0, min(1, trend_score))

    # 价格位置: 当前价格在近期区间的百分比位置
    recent_high = float(hist.tail(60)["high"].max())
    recent_low = float(hist.tail(60)["low"].min())
    price_range = recent_high - recent_low
    if price_range > 0:
        pos_score = (close - recent_low) / price_range
    else:
        pos_score = 0.5

    return 0.6 * trend_score + 0.4 * pos_score


def load_stocks(csv_path: Path, limit: int = N_STOCKS) -> List[Dict[str, str]]:
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            if code.startswith(("600", "601", "603", "605", "688", "689",
                               "000", "001", "002", "003", "300", "301", "302")):
                symbols.append({"symbol": f"{code}.{market}", "code": code, "market": market, "name": name})
            if len(symbols) >= limit:
                break
    return symbols


def load_csi300() -> Optional[pd.DataFrame]:
    if CSI300_TDX_PATH.exists():
        df = load_tdx_data(str(CSI300_TDX_PATH))
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
    return None


def generate_windows(csi300_df: pd.DataFrame, n: int = N_WINDOWS) -> List[str]:
    if csi300_df is None or len(csi300_df) < 200:
        return []
    trading_dates = csi300_df["date"].dt.strftime("%Y-%m-%d").tolist()
    available = trading_dates[:len(trading_dates) - MAX_HOLD]
    random.seed(SEED)
    return sorted(random.sample(available, min(n, len(available))))


def classify_market_regime(index_data: pd.DataFrame, as_of_date: str) -> str:
    as_of = pd.Timestamp(as_of_date)
    hist = index_data[index_data["date"] <= as_of]
    if len(hist) < 120:
        return "unknown"
    close = float(hist.iloc[-1]["close"])
    ma120 = float(hist.tail(120)["close"].mean())
    ma60 = float(hist.tail(60)["close"].mean())
    if close > ma120 * 1.02 and ma60 > ma120:
        return "bull"
    elif close < ma120 * 0.98:
        return "bear"
    else:
        return "range"


def calc_atr(df_slice: pd.DataFrame, period: int = 20) -> float:
    n = len(df_slice)
    if n < period + 1:
        return 0.0
    high = df_slice["high"].values[-period:]
    low = df_slice["low"].values[-period:]
    close = df_slice["close"].values[-period:]
    tr = [high[i]-low[i]]
    for i in range(min(period, len(df_slice)-1)):
        tr.append(max(high[i]-low[i], abs(high[i]-df_slice['close'].iloc[-i-2]), abs(low[i]-df_slice['close'].iloc[-i-2])))
    return float(np.mean(tr[-period:]))


def calc_v2plus_return(df, as_of_date, wyckoff_entry=None, stop_loss=None, first_target=None, regime="unknown"):
    params = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_mult = params["atr_mult"]
    time_stop = params["time_stop_days"]
    max_hold = params["max_hold_days"]

    as_of = pd.Timestamp(as_of_date)
    future = df[df["date"] > as_of].head(max_hold)
    if len(future) < max_hold * 0.5:
        return None

    current_close = float(df[df["date"] <= as_of].iloc[-1]["close"])
    use_we = (wyckoff_entry is not None and wyckoff_entry > 0
              and abs(wyckoff_entry - current_close) / current_close > 0.001)
    entry = wyckoff_entry if use_we else current_close
    if use_we:
        early = future.head(10)
        if len(early) > 0 and wyckoff_entry < float(early["low"].min()):
            return None

    hist = df[df["date"] <= as_of].tail(60)
    atr_20 = calc_atr(pd.concat([hist, future.head(20)]), 20) if len(future) >= 20 else entry * 0.02
    if atr_20 <= 0:
        atr_20 = entry * 0.02
    struct_stop = stop_loss if (stop_loss is not None and stop_loss > 0) else (entry * 0.93)
    et = first_target if (first_target is not None and first_target > 0) else None
    atr_target = entry + 2.0 * atr_20
    effective_target = max(et, atr_target) if (et and et > entry) else (atr_target if atr_target > entry else None)

    peak = entry
    trailing_stop = None
    half_exited = False
    stage2 = False
    exit_price = None
    exit_reason = "max_hold"
    hit_stop = False
    hit_target = False

    for i, (_, row) in enumerate(future.iterrows()):
        d = i + 1
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        peak = max(peak, high)
        if low <= struct_stop:
            exit_price = struct_stop; exit_reason = "stop_loss"; hit_stop = True; break
        if d <= 30 and not half_exited and effective_target is not None:
            if high >= effective_target:
                half_exited = True; stage1_price = effective_target
                stage2 = True; trailing_stop = peak - atr_mult * atr_20; hit_target = True; continue
            if d == 30:
                stage2 = True; trailing_stop = peak - atr_mult * atr_20
        if stage2:
            ts = peak - atr_mult * atr_20
            trailing_stop = max(trailing_stop, ts) if trailing_stop else ts
            if low <= trailing_stop:
                exit_price = trailing_stop; exit_reason = "trailing_stop"; break
            if d > time_stop and not half_exited:
                exit_price = close; exit_reason = "time_stop"; break
        exit_price = close

    if not hit_stop and d >= max_hold:
        exit_price = float(future.iloc[-1]["close"]); exit_reason = "max_hold"

    if half_exited and hit_target:
        r1 = (stage1_price - entry) / entry * 100
        r2 = (exit_price - entry) / entry * 100
        total_ret = 0.5 * r1 + 0.5 * r2
        er = f"target_50pct+{exit_reason}"
    else:
        total_ret = (exit_price - entry) / entry * 100
        er = exit_reason

    fh, fl = float(future["high"].max()), float(future["low"].min())
    return {"entry_price": round(entry, 3), "total_return": round(total_ret, 2), "exit_reason": er,
            "hit_target": hit_target, "hit_stop": hit_stop, "half_exited": half_exited,
            "max_gain_pct": round((fh-entry)/entry*100, 2), "max_drawdown_pct": round((entry-fl)/entry*100, 2),
            "days_in_trade": d, "regime": regime}


def process_stock(args) -> List[Dict]:
    si, windows, csi300_df = args
    symbol = si["symbol"]
    name = si["name"]
    results = []
    try:
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty or len(df) < 300:
            return results
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        engine = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)

        for as_of_date in windows:
            as_of = pd.Timestamp(as_of_date)
            avail = df[df["date"] <= as_of]
            if len(avail) < 100:
                continue

            report = engine.analyze(avail, symbol=symbol, period="日线", multi_timeframe=True)
            rr = report.risk_reward
            wyckoff_entry = rr.entry_price if (rr and rr.entry_price and rr.entry_price > 0) else None
            stop_loss = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss > 0) else None
            first_target = rr.first_target if (rr and rr.first_target and rr.first_target > 0) else None
            sig = report.signal.signal_type
            phase = report.structure.phase.value
            direction = report.trading_plan.direction

            # NTZ过滤
            if sig == "no_signal" or direction == "空仓观望":
                continue

            market_regime = classify_market_regime(csi300_df, as_of_date) if csi300_df is not None else "unknown"

            # ---- 因子计算 ----
            # 因子1: Wyckoff基础评分 (基于phase)
            wyckoff_scores = {"markdown": 0.7, "accumulation": 0.5, "distribution": 0.3, "markup": 0.3}
            s_wyckoff = wyckoff_scores.get(phase, 0.3)

            # 因子2: MA/ATR趋势评分
            s_maatr = get_maatr_score(df, as_of_date)

            score = W_WYCKOFF * s_wyckoff + W_MAATR * s_maatr
            if score < SCORE_THRESHOLD:
                continue

            ret = calc_v2plus_return(df, as_of_date,
                                     wyckoff_entry=wyckoff_entry, stop_loss=stop_loss,
                                     first_target=first_target, regime=market_regime)
            if ret is None:
                continue

            bm_ret = None
            if csi300_df is not None:
                bm_f = csi300_df[csi300_df["date"] > as_of].head(90)
                if len(bm_f) >= 72:
                    be = float(csi300_df[csi300_df["date"] <= as_of].iloc[-1]["close"])
                    bx = float(bm_f.iloc[-1]["close"])
                    bm_ret = round((bx - be) / be * 100, 2)

            results.append({
                "symbol": symbol, "name": name, "as_of": as_of_date,
                "phase": phase, "market_regime": market_regime,
                "score_wyckoff": round(s_wyckoff, 3), "score_maatr": round(s_maatr, 3),
                "score_lppl": round(s_lppl, 3), "total_score": round(score, 3),
                "total_return": ret["total_return"], "exit_reason": ret["exit_reason"],
                "hit_target": ret["hit_target"], "hit_stop": ret["hit_stop"],
                "half_exited": ret["half_exited"], "days_in_trade": ret["days_in_trade"],
                "max_gain_pct": ret["max_gain_pct"], "max_drawdown_pct": ret["max_drawdown_pct"],
                "benchmark_return": bm_ret,
                "excess_return": round(ret["total_return"] - bm_ret, 2) if bm_ret is not None else None,
            })
    except Exception:
        pass
    return results


def bootstrap_ci(data: np.ndarray, n=N_BOOTSTRAP, confidence=0.95):
    if len(data) < 10:
        return np.nan, np.nan, np.nan
    means = [np.mean(np.random.choice(data, size=len(data), replace=True)) for _ in range(n)]
    return np.mean(means), np.percentile(means, (1 - confidence) / 2 * 100), np.percentile(means, (1 + confidence) / 2 * 100)


def run():
    print("=" * 70)
    print("Wyckoff 多因子合成策略验证 (P2)")
    print(f"  因子权重: Wyckoff={W_WYCKOFF} MA/ATR={W_MAATR} LPPL={W_LPPL}")
    print(f"  全量A股 | 窗口:{N_WINDOWS}")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    stocks = load_stocks(csv_path, N_STOCKS)
    print(f"\n加载 {len(stocks)} 只股票")

    csi300 = load_csi300()
    print(f"沪深300: {len(csi300) if csi300 is not None else 0}行")
    windows = generate_windows(csi300, N_WINDOWS)
    print(f"时间窗口: {len(windows)}个")

    all_results = []
    max_workers = get_optimal_workers()
    batch_size = max_workers * 4
    args_list = [(s, windows, csi300) for s in stocks]

    with ProcessPoolExecutor(max_workers=max_workers, initializer=worker_init) as executor:
        for batch_start in range(0, len(args_list), batch_size):
            batch = args_list[batch_start:batch_start + batch_size]
            futures = {executor.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for future in as_completed(futures):
                try:
                    r = future.result(timeout=300)
                    all_results.extend(r)
                except Exception:
                    pass
            p = min(batch_start + batch_size, len(args_list))
            print(f"  进度: {p}/{len(stocks)} 股票, {len(all_results)} 样本")

    print(f"\n总样本: {len(all_results)}")
    if not all_results:
        print("无样本, 退出"); return

    df = pd.DataFrame(all_results)
    returns = df["total_return"].values
    mr, cl, ch = bootstrap_ci(returns)

    analysis = {
        "config": {"version": "multifactor", "w_wyckoff": W_WYCKOFF, "w_maatr": W_MAATR, "w_lppl": W_LPPL},
        "overall": {
            "n_samples": len(df), "mean_return": round(mr, 2),
            "ci_lower": round(cl, 2), "ci_upper": round(ch, 2),
            "median_return": round(np.median(returns), 2),
            "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
            "std_return": round(np.std(returns), 2),
            "sharpe": round(mr / np.std(returns) * (252 / 90)**0.5, 3) if np.std(returns) > 0 else 0,
        },
        "exit_reason": {}, "benchmark": {},
    }

    for r in df["exit_reason"].unique():
        v = df[df["exit_reason"] == r]["total_return"].values
        if len(v) >= 3:
            analysis["exit_reason"][r] = {
                "n": len(v), "mean": round(np.mean(v), 2), "win": round(sum(v > 0) / len(v) * 100, 1),
                "pct": round(len(v) / len(df) * 100, 1),
            }

    if df["excess_return"].notna().sum() >= 10:
        ex = df["excess_return"].dropna().values
        analysis["benchmark"] = {
            "strategy": round(np.mean(returns), 2),
            "benchmark": round(np.mean(df["benchmark_return"].dropna()), 2),
            "excess_mean": round(np.mean(ex), 2),
            "excess_win": round(sum(ex > 0) / len(ex) * 100, 1),
        }

    jp = OUTPUT_DIR / "multifactor_results.json"
    with jp.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {jp}")

    o = analysis["overall"]
    print(f"\n{'='*70}")
    print("多因子策略测试摘要")
    print(f"  总样本: {o['n_samples']}")
    print(f"  平均收益: {o['mean_return']:.2f}%")
    print(f"  95%CI: [{o['ci_lower']:.2f}, {o['ci_upper']:.2f}]")
    print(f"  中位收益: {o['median_return']:.2f}%")
    print(f"  胜率: {o['win_rate']:.1f}%")
    print(f"  标准差: {o['std_return']:.2f}%")
    print(f"  夏普: {o['sharpe']:.3f}")
    bc = analysis.get("benchmark", {})
    if bc:
        print(f"  策略: {bc['strategy']:.2f}% vs 基准: {bc['benchmark']:.2f}%")
        print(f"  超额: {bc['excess_mean']:.2f}%  超额胜率: {bc['excess_win']:.1f}%")

    print("\n  退出原因:")
    for r, s in sorted(analysis["exit_reason"].items(), key=lambda x: -x[1]["pct"], reverse=True):
        print(f"    {r:35s}: {s['pct']:5.1f}%  ret={s['mean']:6.2f}%  win={s['win']:5.1f}%")

    print("\n  vs v2+对比:")
    print("    v2+:      收益=+1.69%  夏普=0.168  超额=+5.52%")
    print(f"    多因子:   收益={o['mean_return']:+.2f}%  夏普={o['sharpe']:.3f}  超额={bc.get('excess_mean',0):+.2f}%")

    print(f"\n{'='*70}")
    print("完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    run()
