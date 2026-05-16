#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff + LPPL 融合因子全市场验证回测

在所有市场环境下验证融合方法 vs 纯Wyckoff方法:
- 纯Wyckoff: BUY=观察等待, AVOID=持有观察, HOLD=空仓观望
- 融合: Wyckoff信号 × LPPL过滤（markdown阶段+LPPL warning/watch增强）

关键改进:
1. 按历史日期正确检测市场regime（而非仅用最新数据）
2. 覆盖所有市场环境（bear/bull/crash/event/structural）
3. 对比纯Wyckoff vs 融合 vs LPPL单一因子

用法:
    python scripts/wyckoff_lppl_fusion_full_market.py --limit 1000 --workers 6
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.lppl_engine import LPPLConfig, fit_single_window
from src.wyckoff.engine import WyckoffEngine

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ============================================================================
# 配置
# ============================================================================

TIME_WINDOWS: List[Dict[str, Any]] = [
    {"id": 1,  "date": "2017-05-11", "label": "2017白马行情",       "market_env": "bull_start"},
    {"id": 2,  "date": "2018-02-09", "label": "2018年初闪崩",       "market_env": "crash_bottom"},
    {"id": 3,  "date": "2018-10-19", "label": "2018熊底",           "market_env": "bear_bottom"},
    {"id": 4,  "date": "2019-01-04", "label": "2019春季反弹",       "market_env": "rebound_start"},
    {"id": 5,  "date": "2019-08-06", "label": "2019贸易摩擦底",     "market_env": "bear_bottom"},
    {"id": 6,  "date": "2020-03-23", "label": "2020疫情底",         "market_env": "event_bottom"},
    {"id": 7,  "date": "2020-07-01", "label": "2020牛市启动",       "market_env": "bull_start"},
    {"id": 8,  "date": "2021-07-28", "label": "2021教育双减底",     "market_env": "structural_low"},
    {"id": 9,  "date": "2021-11-10", "label": "2021年末反弹",       "market_env": "rebound_start"},
    {"id": 10, "date": "2022-04-27", "label": "2022上海封控底",     "market_env": "event_bottom"},
    {"id": 11, "date": "2022-10-31", "label": "2022熊底",           "market_env": "bear_bottom"},
    {"id": 12, "date": "2023-05-25", "label": "2023年中回调",       "market_env": "structural_low"},
    {"id": 13, "date": "2023-10-23", "label": "2023年底部",         "market_env": "bear_bottom"},
    {"id": 14, "date": "2024-02-05", "label": "2024年初恐慌底",     "market_env": "crash_bottom"},
    {"id": 15, "date": "2024-05-20", "label": "2024地产反弹顶",     "market_env": "bull_start"},
    {"id": 16, "date": "2024-09-13", "label": "2024极度低迷",       "market_env": "bear_bottom"},
    {"id": 17, "date": "2025-01-13", "label": "2025年初回调",       "market_env": "structural_low"},
    {"id": 18, "date": "2025-03-04", "label": "2025两会行情",       "market_env": "bull_start"},
    {"id": 19, "date": "2025-04-07", "label": "2025关税冲击",       "market_env": "event_bottom"},
    {"id": 20, "date": "2025-04-18", "label": "2025反弹中",         "market_env": "rebound_start"},
]

WYCKOFF_LOOKBACK = 300
FORWARD_DAYS = 90
BENCHMARK = "000300.SH"
LPPL_WINDOW = 130
LPPL_RMSE_TH = 0.025


# ============================================================================
# LPPL 三层拟合
# ============================================================================

def lppl_multifit(close_prices: np.ndarray, idx: int) -> Dict:
    """
    LPPL 多窗口拟合（简化版）

    在当前索引处对多个窗口进行拟合，返回综合评分
    """
    windows = [50, 80, 130, 180]
    results = []

    for w in windows:
        if idx < w + 10:
            continue
        subset = close_prices[idx - w:idx]
        config = LPPLConfig(window_range=[w], maxiter=60, popsize=10, tol=0.05)
        res = fit_single_window(subset, w, config)
        if res is not None:
            results.append(res)

    if not results:
        return {"score": 0.0, "level": "none", "n_valid": 0, "avg_rmse": 1.0, "avg_m": 0.0}

    valid = [r for r in results if 0.1 < r["m"] < 0.9 and 6 < r["w"] < 13 and r["rmse"] < 0.05]

    n_valid = len(valid)
    n_total = len(results)

    if n_valid == 0:
        return {"score": 0.0, "level": "none", "n_valid": 0, "avg_rmse": 1.0, "avg_m": 0.0}

    avg_rmse = np.mean([r["rmse"] for r in valid])
    avg_m = np.mean([r["m"] for r in valid])
    avg_r2 = np.mean([r["r_squared"] for r in valid])

    # 综合评分: 有效窗口比例 × 平均R2 × (1 - 平均RMSE)
    score = (n_valid / n_total) * avg_r2 * (1.0 - min(avg_rmse / 0.05, 1.0))

    # 分级
    if score >= 0.5:
        level = "strong"
    elif score >= 0.3:
        level = "warning"
    elif score >= 0.15:
        level = "watch"
    elif n_valid > 0:
        level = "danger"
    else:
        level = "none"

    return {
        "score": round(score, 4),
        "level": level,
        "n_valid": n_valid,
        "n_total": n_total,
        "avg_rmse": round(avg_rmse, 6),
        "avg_m": round(avg_m, 4),
        "avg_r2": round(avg_r2, 4),
    }


# ============================================================================
# 工具函数
# ============================================================================

def load_stock_symbols(csv_path: Path, limit: int = 0, random_seed: int = 42) -> List[Dict[str, str]]:
    all_valid = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            valid_prefixes = ("600","601","603","605","688","689","000","001","002","003","300","301","302")
            if not code.startswith(valid_prefixes):
                continue
            all_valid.append({"symbol": f"{code}.{market}", "code": code, "market": market, "name": name})
    if limit > 0 and len(all_valid) > limit:
        all_valid = random.Random(random_seed).sample(all_valid, limit)
    return all_valid


def calc_fwd_return(df: pd.DataFrame, signal_date: str, days: int = FORWARD_DAYS) -> Optional[Dict]:
    ts = pd.Timestamp(signal_date)
    before = df[df["date"] <= ts]
    if before.empty:
        return None
    entry_idx = before.index[-1]
    entry_price = float(before.iloc[-1]["close"])
    future = df.loc[entry_idx + 1:].head(days)
    if len(future) < int(days * 0.75):
        return None
    ret = (float(future.iloc[-1]["close"]) - entry_price) / entry_price * 100
    gain = (float(future["high"].max()) - entry_price) / entry_price * 100
    dd = (entry_price - float(future["low"].min())) / entry_price * 100
    return {"return_pct": round(ret, 2), "max_gain_pct": round(gain, 2), "max_drawdown_pct": round(dd, 2)}


def _to_native(obj):
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


# ============================================================================
# 单股票处理
# ============================================================================

def process_stock(sym_info: Dict, bench_returns: Dict[int, float]) -> Tuple[List[Dict], str]:
    symbol = sym_info["symbol"]
    name = sym_info["name"]
    results = []
    err = ""
    try:
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty or len(df) < 200:
            return results, f"{symbol}: 数据不足"
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        close_prices = df["close"].values.astype(float)

        for tw in TIME_WINDOWS:
            signal_date = tw["date"]
            available = df[df["date"] <= pd.Timestamp(signal_date)]
            if len(available) < 150:
                continue

            # Wyckoff 分析
            try:
                engine = WyckoffEngine(lookback_days=WYCKOFF_LOOKBACK)
                report = engine.analyze(available, symbol=symbol, period="日线", multi_timeframe=False)
            except Exception:
                continue

            phase = report.structure.phase.value if report.structure and report.structure.phase else "unknown"
            direction = report.trading_plan.direction if report.trading_plan else "空仓观望"
            confidence = report.trading_plan.confidence.value if report.trading_plan and report.trading_plan.confidence else "D"
            signal_type = report.signal.signal_type if report.signal else "no_signal"
            bc = report.structure.bc_point is not None if report.structure else False
            spring = signal_type == "spring"

            # LPPL 多窗口拟合
            idx = len(available) - 1
            lppl = lppl_multifit(close_prices, idx)

            # 纯Wyckoff信号
            if direction == "观察等待":
                wy_signal = "BUY"
            elif direction == "持有观察":
                wy_signal = "AVOID"
            else:
                wy_signal = "HOLD"

            # 融合信号: Wyckoff × LPPL
            if wy_signal == "BUY" and lppl["level"] in ("strong", "warning", "watch"):
                fusion_signal = "BUY_LPPL"
            elif wy_signal == "BUY" and lppl["level"] in ("none", "danger"):
                fusion_signal = "BUY_NO_LPPL"
            elif wy_signal == "AVOID" and lppl["level"] in ("danger", "none"):
                fusion_signal = "AVOID_LPPL_DANGER"
            elif wy_signal == "AVOID":
                fusion_signal = "AVOID_OTHER"
            elif phase == "markdown" and lppl["level"] in ("warning", "watch"):
                fusion_signal = "MD_LPPL"
            elif phase == "markdown":
                fusion_signal = "MD_NO_LPPL"
            else:
                fusion_signal = "OTHER"

            # 前瞻收益
            fwd = calc_fwd_return(df, signal_date, FORWARD_DAYS)
            if fwd is None:
                continue

            bench_ret = bench_returns.get(tw["id"], 0.0)

            results.append({
                "symbol": symbol,
                "name": name,
                "window_id": tw["id"],
                "signal_date": signal_date,
                "market_env": tw["market_env"],
                "wy_phase": phase,
                "wy_direction": direction,
                "wy_confidence": confidence,
                "wy_signal_type": signal_type,
                "wy_bc": bc,
                "wy_spring": spring,
                "wy_signal": wy_signal,
                "lppl_score": lppl["score"],
                "lppl_level": lppl["level"],
                "lppl_n_valid": lppl["n_valid"],
                "lppl_avg_rmse": lppl["avg_rmse"],
                "lppl_avg_m": lppl["avg_m"],
                "fusion_signal": fusion_signal,
                "fwd_return": fwd["return_pct"],
                "fwd_max_gain": fwd["max_gain_pct"],
                "fwd_max_dd": fwd["max_drawdown_pct"],
                "bench_return": round(bench_ret, 2),
                "excess_return": round(fwd["return_pct"] - bench_ret, 2),
            })
    except Exception as e:
        err = f"{symbol}: {type(e).__name__}: {e}"
    return results, err


# ============================================================================
# 基准
# ============================================================================

def precompute_bench(dm: DataManager) -> Dict[int, float]:
    df = dm.get_data(BENCHMARK)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    returns = {}
    for tw in TIME_WINDOWS:
        fwd = calc_fwd_return(df, tw["date"], FORWARD_DAYS)
        returns[tw["id"]] = fwd["return_pct"] if fwd else 0.0
    return returns


# ============================================================================
# 分析
# ============================================================================

def analyze(all_results: List[Dict]) -> Dict:
    if not all_results:
        return {"error": "No results"}
    df = pd.DataFrame(all_results)
    a = {}

    a["overall"] = {
        "total_records": len(df),
        "unique_stocks": df["symbol"].nunique(),
        "signal_distribution": df["fusion_signal"].value_counts().to_dict(),
    }

    # 1. 纯Wyckoff信号
    wy_stats = {}
    for sig in ["BUY", "AVOID", "HOLD"]:
        sub = df[df["wy_signal"] == sig]
        if len(sub) == 0:
            continue
        wy_stats[sig] = _sig_stats(sub)
    a["pure_wyckoff"] = wy_stats

    # 2. 融合信号
    fusion_stats = {}
    for sig in sorted(df["fusion_signal"].unique()):
        sub = df[df["fusion_signal"] == sig]
        if len(sub) < 5:
            continue
        fusion_stats[sig] = _sig_stats(sub)
    a["fusion"] = fusion_stats

    # 3. LPPL level in markdown
    md = df[df["wy_phase"] == "markdown"]
    lppl_in_md = {}
    for level in ["strong", "warning", "watch", "danger", "none"]:
        sub = md[md["lppl_level"] == level]
        if len(sub) < 5:
            continue
        lppl_in_md[level] = _sig_stats(sub)
    a["lppl_in_markdown"] = lppl_in_md

    # 4. 市场环境 × 信号
    env_sig = {}
    for env in sorted(df["market_env"].unique()):
        env_df = df[df["market_env"] == env]
        env_sig[env] = {}
        for sig_type in ["pure_wyckoff", "fusion"]:
            if sig_type == "pure_wyckoff":
                for sig in ["BUY", "AVOID"]:
                    sub = env_df[env_df["wy_signal"] == sig]
                    if len(sub) > 0:
                        env_sig[env][f"wy_{sig}"] = _sig_stats(sub)
            else:
                for sig in ["BUY_LPPL", "AVOID_LPPL_DANGER", "MD_LPPL"]:
                    sub = env_df[env_df["fusion_signal"] == sig]
                    if len(sub) > 0:
                        env_sig[env][f"fusion_{sig}"] = _sig_stats(sub)
    a["market_env_signal"] = env_sig

    # 5. 回撤分布
    dd_dist = {}
    for sig_name, mask_expr in [
        ("wy_BUY", df["wy_signal"] == "BUY"),
        ("wy_AVOID", df["wy_signal"] == "AVOID"),
        ("fusion_BUY_LPPL", df["fusion_signal"] == "BUY_LPPL"),
        ("fusion_MD_LPPL", df["fusion_signal"] == "MD_LPPL"),
    ]:
        sub = df[mask_expr]
        if len(sub) == 0:
            continue
        bins = [0, 5, 10, 15, 20, 30, 50, 100]
        labels = ["<5%", "5-10%", "10-15%", "15-20%", "20-30%", "30-50%", ">50%"]
        sub_copy = sub.copy()
        sub_copy["dd_bin"] = pd.cut(sub_copy["fwd_max_dd"], bins=bins, labels=labels)
        dist = sub_copy.groupby("dd_bin", observed=True).agg(
            count=("excess_return", "count"),
            avg_excess=("excess_return", "mean"),
            positive_rate=("fwd_return", lambda x: (x > 0).mean() * 100),
        ).round(2)
        dd_dist[sig_name] = dist.to_dict("index")
    a["drawdown_distribution"] = dd_dist

    # 6. BUY vs AVOID 效应量
    buy = df[df["wy_signal"] == "BUY"]["excess_return"]
    avoid = df[df["wy_signal"] == "AVOID"]["excess_return"]
    if len(buy) > 0 and len(avoid) > 0:
        pooled = np.sqrt(((len(buy)-1)*buy.var() + (len(avoid)-1)*avoid.var()) / (len(buy)+len(avoid)-2))
        d = (buy.mean() - avoid.mean()) / pooled if pooled > 0 else 0
        a["buy_vs_avoid"] = {
            "buy_avg_excess": round(buy.mean(), 2),
            "avoid_avg_excess": round(avoid.mean(), 2),
            "difference": round(buy.mean() - avoid.mean(), 2),
            "cohens_d": round(d, 3),
        }

    # fusion BUY_LPPL vs wy BUY
    f_buy = df[df["fusion_signal"] == "BUY_LPPL"]["excess_return"]
    w_buy = df[df["wy_signal"] == "BUY"]["excess_return"]
    if len(f_buy) > 5 and len(w_buy) > 0:
        pooled2 = np.sqrt(((len(f_buy)-1)*f_buy.var() + (len(w_buy)-1)*w_buy.var()) / (len(f_buy)+len(w_buy)-2))
        d2 = (f_buy.mean() - w_buy.mean()) / pooled2 if pooled2 > 0 else 0
        a["fusion_buy_vs_wy_buy"] = {
            "fusion_avg_excess": round(f_buy.mean(), 2),
            "wy_avg_excess": round(w_buy.mean(), 2),
            "difference": round(f_buy.mean() - w_buy.mean(), 2),
            "cohens_d": round(d2, 3),
        }

    return a


def _sig_stats(sub):
    return {
        "count": len(sub),
        "avg_return": round(sub["fwd_return"].mean(), 2),
        "avg_excess": round(sub["excess_return"].mean(), 2),
        "median_excess": round(sub["excess_return"].median(), 2),
        "positive_rate": round((sub["fwd_return"] > 0).mean() * 100, 1),
        "beat_bench_rate": round((sub["excess_return"] > 0).mean() * 100, 1),
        "avg_dd": round(sub["fwd_max_dd"].mean(), 2),
        "dd_under_10": round((sub["fwd_max_dd"] < 10).mean() * 100, 1),
        "ir": round(sub["excess_return"].mean() / sub["excess_return"].std(), 4) if sub["excess_return"].std() > 0 else 0,
    }


# ============================================================================
# 报告
# ============================================================================

def save_report(all_results: List[Dict], analysis: Dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_results).to_csv(output_dir / "fusion_full_detail.csv", index=False, encoding="utf-8-sig")
    with open(output_dir / "fusion_full_analysis.json", "w", encoding="utf-8") as f:
        json.dump(_to_native(analysis), f, ensure_ascii=False, indent=2)

    lines = [
        "# Wyckoff + LPPL 融合因子全市场验证报告",
        "",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 基准: 沪深300, 前瞻: {FORWARD_DAYS}天",
        f"> Wyckoff: {WYCKOFF_LOOKBACK}天",
        "> LPPL: 多窗口拟合 [50,80,130,180]",
        "> 约束: T+1 + 只能做多",
        "",
    ]

    ov = analysis.get("overall", {})
    lines.extend(["## 一、总体", "",
        f"- 总记录: **{ov.get('total_records', 0)}**",
        f"- 股票: **{ov.get('unique_stocks', 0)}**",
        f"- 信号分布: {ov.get('signal_distribution', {})}",
        "",
    ])

    # 纯Wyckoff
    lines.extend(["## 二、纯Wyckoff 信号", "",
        "| 信号 | 样本 | 平均收益 | 平均超额 | 正收益率 | >基准率 | 平均回撤 | 回撤<10% | IR |",
        "|------|------|---------|---------|---------|---------|---------|---------|-----|"])
    for sig, stats in analysis.get("pure_wyckoff", {}).items():
        lines.append(f"| **{sig}** | {stats['count']} | {stats['avg_return']:+.2f}% | {stats['avg_excess']:+.2f}% | {stats['positive_rate']:.1f}% | {stats['beat_bench_rate']:.1f}% | {stats['avg_dd']:.2f}% | {stats['dd_under_10']:.1f}% | {stats['ir']:+.4f} |")
    lines.append("")

    # 融合信号
    lines.extend(["## 三、融合信号", "",
        "| 信号 | 样本 | 平均收益 | 平均超额 | 正收益率 | >基准率 | 平均回撤 | 回撤<10% | IR |",
        "|------|------|---------|---------|---------|---------|---------|---------|-----|"])
    for sig, stats in analysis.get("fusion", {}).items():
        lines.append(f"| **{sig}** | {stats['count']} | {stats['avg_return']:+.2f}% | {stats['avg_excess']:+.2f}% | {stats['positive_rate']:.1f}% | {stats['beat_bench_rate']:.1f}% | {stats['avg_dd']:.2f}% | {stats['dd_under_10']:.1f}% | {stats['ir']:+.4f} |")
    lines.append("")

    # LPPL in markdown
    lines.extend(["## 四、LPPL 过滤在 markdown 阶段的效果", "",
        "| LPPL Level | 样本 | 平均收益 | 平均超额 | 正收益率 | 平均回撤 |",
        "|------------|------|---------|---------|---------|---------|"])
    for level, stats in analysis.get("lppl_in_markdown", {}).items():
        lines.append(f"| {level:10s} | {stats['count']:5d} | {stats['avg_return']:+6.2f}% | {stats['avg_excess']:+6.2f}% | {stats['positive_rate']:5.1f}% | {stats['avg_dd']:6.2f}% |")
    lines.append("")

    # 市场环境
    lines.extend(["## 五、市场环境 × 信号", "",
        "| 环境 | 信号 | 样本 | 平均超额 | 正收益率 | 平均回撤 |",
        "|------|------|------|---------|---------|---------|"])
    for env, sigs in sorted(analysis.get("market_env_signal", {}).items()):
        for sig_name, stats in sorted(sigs.items()):
            lines.append(f"| {env:18s} | {sig_name:20s} | {stats['count']:5d} | {stats['avg_excess']:+6.2f}% | {stats['positive_rate']:5.1f}% | {stats['avg_dd']:6.2f}% |")
    lines.append("")

    # 效应量
    bv = analysis.get("buy_vs_avoid", {})
    fbv = analysis.get("fusion_buy_vs_wy_buy", {})
    if bv or fbv:
        lines.extend(["## 六、效应量对比", ""])
        if bv:
            lines.extend([
                "### 纯Wyckoff BUY vs AVOID",
                f"- BUY 超额: **{bv['buy_avg_excess']:+.2f}%**",
                f"- AVOID 超额: **{bv['avoid_avg_excess']:+.2f}%**",
                f"- 差值: **{bv['difference']:+.2f}%**, Cohen's d: **{bv['cohens_d']:+.3f}**",
                "",
            ])
        if fbv:
            lines.extend([
                "### 融合 BUY_LPPL vs 纯Wyckoff BUY",
                f"- 融合超额: **{fbv['fusion_avg_excess']:+.2f}%**",
                f"- 纯Wy超额: **{fbv['wy_avg_excess']:+.2f}%**",
                f"- 差值: **{fbv['difference']:+.2f}%**, Cohen's d: **{fbv['cohens_d']:+.3f}**",
                "",
            ])

    # 回撤分布
    lines.extend(["## 七、回撤分布", ""])
    for sig_name, dist in analysis.get("drawdown_distribution", {}).items():
        lines.extend([f"### {sig_name}", "",
            "| 回撤 | 样本 | 超额 | 正收益率 |",
            "|------|------|------|---------|"])
        for dd_bin, dd_stats in dist.items():
            lines.append(f"| {dd_bin:8s} | {dd_stats['count']:5d} | {dd_stats['avg_excess']:+6.2f}% | {dd_stats['positive_rate']:5.1f}% |")
        lines.append("")

    (output_dir / "fusion_full_report.md").write_text("\n".join(lines), encoding="utf-8")


# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Wyckoff+LPPL 融合全市场验证")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default="output/wyckoff_lppl_fusion_full_market")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Wyckoff + LPPL 融合因子全市场验证")
    print("=" * 70)
    print(f"股票: {args.limit} (种子={args.seed})")
    print(f"窗口: {len(TIME_WINDOWS)}个 (2017-2025, 覆盖全市场环境)")
    print(f"前瞻: {FORWARD_DAYS}天 | 基准: {BENCHMARK}")
    print(f"Wyckoff: {WYCKOFF_LOOKBACK}天 | LPPL: 多窗口[50,80,130,180]")
    print(f"线程: {args.workers}")
    print("=" * 70)

    stock_path = PROJECT_ROOT / "data" / "stock_list.csv"
    if not stock_path.exists():
        stock_path = PROJECT_ROOT / "stock_list.csv"
    symbols = load_stock_symbols(stock_path, limit=args.limit, random_seed=args.seed)
    print(f"\n加载: {len(symbols)}只")

    dm = DataManager()
    bench_returns = precompute_bench(dm)
    print("\n基准收益:")
    for tw in TIME_WINDOWS:
        print(f"  {tw['date']} ({tw['label']}): {bench_returns[tw['id']]:+.2f}%")

    print(f"\n开始回测 ({len(symbols)} x {len(TIME_WINDOWS)})...")
    t0 = time.time()
    all_results = []
    errors = []
    lock = threading.Lock()
    counter = {"n": 0}

    def on_done(fut):
        with lock:
            counter["n"] += 1
            if counter["n"] % 50 == 0 or counter["n"] == len(symbols):
                elapsed = time.time() - t0
                speed = counter["n"] / elapsed if elapsed > 0 else 0
                eta = (len(symbols) - counter["n"]) / speed if speed > 0 else 0
                print(f"  {counter['n']}/{len(symbols)} | 结果:{len(all_results)} | {elapsed:.0f}s | ETA:{eta:.0f}s")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futs = []
        for sym in symbols:
            f = executor.submit(process_stock, sym, bench_returns)
            f.add_done_callback(on_done)
            futs.append(f)
        for f in futs:
            try:
                res, err = f.result()
                all_results.extend(res)
                if err:
                    errors.append(err)
            except Exception as e:
                errors.append(str(e))

    elapsed = time.time() - t0
    print(f"\n完成: {len(all_results)}条, {len(errors)}错误, {elapsed:.1f}s")

    print("分析中...")
    analysis = analyze(all_results)

    save_report(all_results, analysis, output_dir)
    print(f"输出: {output_dir}/")

    # 打印关键结论
    print("\n" + "=" * 70)
    print("关键结论")
    print("=" * 70)

    print("\n--- 纯Wyckoff ---")
    for sig, stats in analysis.get("pure_wyckoff", {}).items():
        print(f"  {sig:5s}: n={stats['count']:6d} | 超额={stats['avg_excess']:+6.2f}% | 正收益率={stats['positive_rate']:5.1f}% | 回撤={stats['avg_dd']:6.2f}% | IR={stats['ir']:+.4f}")

    print("\n--- 融合信号 ---")
    for sig, stats in sorted(analysis.get("fusion", {}).items()):
        print(f"  {sig:20s}: n={stats['count']:6d} | 超额={stats['avg_excess']:+6.2f}% | 正收益率={stats['positive_rate']:5.1f}% | 回撤={stats['avg_dd']:6.2f}% | IR={stats['ir']:+.4f}")

    print("\n--- LPPL过滤 in markdown ---")
    for level, stats in analysis.get("lppl_in_markdown", {}).items():
        print(f"  {level:10s}: n={stats['count']:5d} | 收益={stats['avg_return']:+6.2f}% | 正收益率={stats['positive_rate']:5.1f}% | 回撤={stats['avg_dd']:6.2f}%")

    bv = analysis.get("buy_vs_avoid", {})
    if bv:
        print("\n--- 纯Wyckoff BUY vs AVOID ---")
        print(f"  超额差: {bv['difference']:+.2f}% | Cohen's d: {bv['cohens_d']:+.3f}")

    fbv = analysis.get("fusion_buy_vs_wy_buy", {})
    if fbv:
        print("\n--- 融合BUY_LPPL vs 纯Wyckoff BUY ---")
        print(f"  超额差: {fbv['difference']:+.2f}% | Cohen's d: {fbv['cohens_d']:+.3f}")

    print("\n完成!")


if __name__ == "__main__":
    main()
