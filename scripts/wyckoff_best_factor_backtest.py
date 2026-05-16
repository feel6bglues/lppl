#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff 最佳因子验证回测脚本

基于 T+1 + 只能做多约束下的因子分析结果:
- 唯一做多信号: wy_direction == "观察等待" (等价于 accumulation + spring)
- 明确回避信号: wy_direction == "持有观察" (等价于 markup)
- 其余: 空仓观望 (不操作)

验证目标:
1. 做多信号的超额收益、正收益率、回撤控制
2. 回避信号的避险效果
3. 因子在不同市场环境下的鲁棒性

用法:
    python scripts/wyckoff_best_factor_backtest.py
    python scripts/wyckoff_best_factor_backtest.py --limit 200 --seed 42
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff.engine import WyckoffEngine

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ============================================================================
# 配置
# ============================================================================

TIME_WINDOWS: List[Dict[str, Any]] = [
    # ===== 2017 (6 windows) =====
    {"id": 1,  "date": "2017-01-16", "label": "2017年初回调",           "market_env": "structural_low"},
    {"id": 2,  "date": "2017-05-11", "label": "2017白马行情",           "market_env": "bull_start"},
    {"id": 3,  "date": "2017-07-17", "label": "2017年中回调",           "market_env": "structural_low"},
    {"id": 4,  "date": "2017-08-11", "label": "2017供给侧行情",         "market_env": "bull_start"},
    {"id": 5,  "date": "2017-11-14", "label": "2017年末回调",           "market_env": "structural_low"},
    {"id": 6,  "date": "2017-12-18", "label": "2017年末底",             "market_env": "bear_bottom"},
    # ===== 2018 (7 windows) =====
    {"id": 7,  "date": "2018-02-09", "label": "2018年初闪崩",           "market_env": "crash_bottom"},
    {"id": 8,  "date": "2018-03-23", "label": "2018贸易战启动",         "market_env": "event_bottom"},
    {"id": 9,  "date": "2018-06-19", "label": "2018年中贸易战",         "market_env": "event_bottom"},
    {"id": 10, "date": "2018-08-20", "label": "2018秋季低迷",           "market_env": "bear_bottom"},
    {"id": 11, "date": "2018-10-19", "label": "2018熊底",               "market_env": "bear_bottom"},
    {"id": 12, "date": "2018-11-02", "label": "2018政策底",             "market_env": "bear_bottom"},
    {"id": 13, "date": "2018-12-28", "label": "2018年末",               "market_env": "bear_bottom"},
    # ===== 2019 (6 windows) =====
    {"id": 14, "date": "2019-01-04", "label": "2019春季反弹",           "market_env": "rebound_start"},
    {"id": 15, "date": "2019-04-08", "label": "2019春季顶",             "market_env": "bull_start"},
    {"id": 16, "date": "2019-05-06", "label": "2019加关税回调",         "market_env": "event_bottom"},
    {"id": 17, "date": "2019-08-06", "label": "2019贸易摩擦底",         "market_env": "bear_bottom"},
    {"id": 18, "date": "2019-10-14", "label": "2019秋季反弹",           "market_env": "rebound_start"},
    {"id": 19, "date": "2019-12-03", "label": "2019年末",               "market_env": "bull_start"},
    # ===== 2020 (6 windows) =====
    {"id": 20, "date": "2020-02-04", "label": "2020疫情首跌",           "market_env": "event_bottom"},
    {"id": 21, "date": "2020-03-23", "label": "2020疫情底",             "market_env": "event_bottom"},
    {"id": 22, "date": "2020-07-01", "label": "2020牛市启动",           "market_env": "bull_start"},
    {"id": 23, "date": "2020-09-09", "label": "2020年中回调",           "market_env": "structural_low"},
    {"id": 24, "date": "2020-10-30", "label": "2020秋季底",             "market_env": "structural_low"},
    {"id": 25, "date": "2020-11-02", "label": "2020年末牛市",           "market_env": "bull_start"},
    # ===== 2021 (6 windows) =====
    {"id": 26, "date": "2021-03-09", "label": "2021抱团回调",           "market_env": "structural_low"},
    {"id": 27, "date": "2021-05-11", "label": "2021周期行情",           "market_env": "bull_start"},
    {"id": 28, "date": "2021-07-28", "label": "2021教育双减底",         "market_env": "structural_low"},
    {"id": 29, "date": "2021-09-14", "label": "2021限电回调",           "market_env": "structural_low"},
    {"id": 30, "date": "2021-11-10", "label": "2021年末反弹",           "market_env": "rebound_start"},
    {"id": 31, "date": "2021-12-13", "label": "2021年末回调",           "market_env": "structural_low"},
    # ===== 2022 (6 windows) =====
    {"id": 32, "date": "2022-01-28", "label": "2022年初杀跌",           "market_env": "crash_bottom"},
    {"id": 33, "date": "2022-04-27", "label": "2022上海封控底",         "market_env": "event_bottom"},
    {"id": 34, "date": "2022-07-05", "label": "2022年中反弹顶",         "market_env": "bull_start"},
    {"id": 35, "date": "2022-10-31", "label": "2022熊底",               "market_env": "bear_bottom"},
    {"id": 36, "date": "2022-11-28", "label": "2022地产三支箭",         "market_env": "rebound_start"},
    {"id": 37, "date": "2022-12-23", "label": "2022年末反弹",           "market_env": "rebound_start"},
    # ===== 2023 (5 windows) =====
    {"id": 38, "date": "2023-03-16", "label": "2023春季回调",           "market_env": "structural_low"},
    {"id": 39, "date": "2023-05-25", "label": "2023年中回调",           "market_env": "structural_low"},
    {"id": 40, "date": "2023-08-25", "label": "2023政策底",             "market_env": "bear_bottom"},
    {"id": 41, "date": "2023-10-23", "label": "2023年底部",             "market_env": "bear_bottom"},
    {"id": 42, "date": "2023-12-21", "label": "2023年末",               "market_env": "bear_bottom"},
    # ===== 2024 (5 windows) =====
    {"id": 43, "date": "2024-02-05", "label": "2024年初恐慌底",         "market_env": "crash_bottom"},
    {"id": 44, "date": "2024-04-12", "label": "2024国九条",             "market_env": "structural_low"},
    {"id": 45, "date": "2024-05-20", "label": "2024地产反弹顶",         "market_env": "bull_start"},
    {"id": 46, "date": "2024-09-13", "label": "2024极度低迷",           "market_env": "bear_bottom"},
    {"id": 47, "date": "2024-10-08", "label": "2024政策牛回调",         "market_env": "crash_bottom"},
    # ===== 2025 (3 windows) =====
    {"id": 48, "date": "2025-01-13", "label": "2025年初回调",           "market_env": "structural_low"},
    {"id": 49, "date": "2025-03-04", "label": "2025两会行情",           "market_env": "bull_start"},
    {"id": 50, "date": "2025-04-07", "label": "2025关税冲击",           "market_env": "event_bottom"},
]

WYCKOFF_LOOKBACK = 300
FORWARD_DAYS = 90
BENCHMARK = "000300.SH"


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class FactorSignal:
    """因子信号"""
    symbol: str
    name: str
    window_id: int
    signal_date: str
    market_env: str

    # Wyckoff原始信号
    wy_phase: str
    wy_direction: str
    wy_confidence: str
    wy_signal_type: str
    wy_bc: bool
    wy_spring: bool

    # 因子分类
    factor_signal: str  # "BUY" / "AVOID" / "HOLD"

    # 前瞻收益
    fwd_return: float
    fwd_max_gain: float
    fwd_max_dd: float
    bench_return: float
    excess_return: float


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


def classify_signal(wy_direction: str, wy_phase: str, wy_spring: bool) -> str:
    """
    T+1 + 只能做多约束下的信号分类

    BUY:   观察等待 (等价于 accumulation + spring, 总是共现)
    AVOID: 持有观察 (等价于 markup, 总是共现)
    HOLD:  其余全部 (空仓观望)
    """
    if wy_direction == "观察等待":
        return "BUY"
    if wy_direction == "持有观察":
        return "AVOID"
    return "HOLD"


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

            # 因子分类
            factor = classify_signal(direction, phase, spring)

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
                "factor_signal": factor,
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

    # 总体
    a["overall"] = {
        "total_records": len(df),
        "unique_stocks": df["symbol"].nunique(),
        "signal_distribution": df["factor_signal"].value_counts().to_dict(),
    }

    # 各信号类型
    sig_stats = {}
    for sig in ["BUY", "AVOID", "HOLD"]:
        sub = df[df["factor_signal"] == sig]
        if len(sub) == 0:
            continue
        sig_stats[sig] = {
            "count": len(sub),
            "avg_return": round(sub["fwd_return"].mean(), 2),
            "median_return": round(sub["fwd_return"].median(), 2),
            "avg_excess": round(sub["excess_return"].mean(), 2),
            "median_excess": round(sub["excess_return"].median(), 2),
            "positive_return_rate": round((sub["fwd_return"] > 0).mean() * 100, 1),
            "beat_benchmark_rate": round((sub["excess_return"] > 0).mean() * 100, 1),
            "avg_max_dd": round(sub["fwd_max_dd"].mean(), 2),
            "dd_under_10_rate": round((sub["fwd_max_dd"] < 10).mean() * 100, 1),
            "ir": round(sub["excess_return"].mean() / sub["excess_return"].std(), 4) if sub["excess_return"].std() > 0 else 0,
        }
    a["signal_stats"] = sig_stats

    # BUY vs AVOID 效应量
    buy = df[df["factor_signal"] == "BUY"]["excess_return"]
    avoid = df[df["factor_signal"] == "AVOID"]["excess_return"]
    if len(buy) > 0 and len(avoid) > 0:
        pooled_std = np.sqrt(((len(buy)-1)*buy.var() + (len(avoid)-1)*avoid.var()) / (len(buy)+len(avoid)-2))
        d = (buy.mean() - avoid.mean()) / pooled_std if pooled_std > 0 else 0
        a["buy_vs_avoid"] = {
            "buy_avg_excess": round(buy.mean(), 2),
            "avoid_avg_excess": round(avoid.mean(), 2),
            "difference": round(buy.mean() - avoid.mean(), 2),
            "cohens_d": round(d, 3),
        }

    # 市场环境 × 信号
    env_sig = {}
    for env in df["market_env"].unique():
        env_df = df[df["market_env"] == env]
        env_sig[env] = {}
        for sig in ["BUY", "AVOID", "HOLD"]:
            sub = env_df[env_df["factor_signal"] == sig]
            if len(sub) > 0:
                env_sig[env][sig] = {
                    "count": len(sub),
                    "avg_excess": round(sub["excess_return"].mean(), 2),
                    "positive_rate": round((sub["fwd_return"] > 0).mean() * 100, 1),
                    "avg_dd": round(sub["fwd_max_dd"].mean(), 2),
                }
    a["market_env_signal"] = env_sig

    # 各窗口表现
    win_stats = {}
    for wid in sorted(df["window_id"].unique()):
        w_df = df[df["window_id"] == wid]
        win_stats[str(wid)] = {
            "date": w_df["signal_date"].iloc[0],
            "label": w_df["market_env"].iloc[0],
            "total": len(w_df),
            "buy_count": (w_df["factor_signal"] == "BUY").sum(),
            "avoid_count": (w_df["factor_signal"] == "AVOID").sum(),
        }
        for sig in ["BUY", "AVOID", "HOLD"]:
            sub = w_df[w_df["factor_signal"] == sig]
            if len(sub) > 0:
                win_stats[str(wid)][f"{sig}_excess"] = round(sub["excess_return"].mean(), 2)
                win_stats[str(wid)][f"{sig}_positive_rate"] = round((sub["fwd_return"] > 0).mean() * 100, 1)
    a["by_window"] = win_stats

    # 回撤分布
    dd_dist = {}
    for sig in ["BUY", "AVOID"]:
        sub = df[df["factor_signal"] == sig]
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
        dd_dist[sig] = dist.to_dict("index")
    a["drawdown_distribution"] = dd_dist

    return a


# ============================================================================
# 报告
# ============================================================================

def _to_native(obj):
    """Convert numpy types to native Python for JSON serialization"""
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def save_report(all_results: List[Dict], analysis: Dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(all_results).to_csv(output_dir / "factor_detail.csv", index=False, encoding="utf-8-sig")

    with open(output_dir / "factor_analysis.json", "w", encoding="utf-8") as f:
        json.dump(_to_native(analysis), f, ensure_ascii=False, indent=2)

    lines = [
        "# Wyckoff 最佳因子验证报告",
        "",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 基准: 沪深300, 前瞻窗口: {FORWARD_DAYS} 个交易日",
        f"> Wyckoff窗口: {WYCKOFF_LOOKBACK}天",
        "> 约束: T+1 + 只能做多",
        "",
    ]

    ov = analysis.get("overall", {})
    lines.extend(["## 一、总体", "",
        f"- 总记录数: **{ov.get('total_records', 0)}**",
        f"- 覆盖股票: **{ov.get('unique_stocks', 0)}**",
        f"- 信号分布: {ov.get('signal_distribution', {})}",
        "",
    ])

    lines.extend(["## 二、各信号表现", "",
        "| 信号 | 样本 | 平均收益 | 平均超额 | 中位数超额 | 正收益率 | >基准率 | 平均回撤 | 回撤<10% | 信息比率 |",
        "|------|------|---------|---------|-----------|---------|---------|---------|---------|---------|"])
    for sig, stats in analysis.get("signal_stats", {}).items():
        lines.append(
            f"| **{sig}** | {stats['count']} | {stats['avg_return']:+.2f}% | "
            f"{stats['avg_excess']:+.2f}% | {stats['median_excess']:+.2f}% | "
            f"{stats['positive_return_rate']:.1f}% | {stats['beat_benchmark_rate']:.1f}% | "
            f"{stats['avg_max_dd']:.2f}% | {stats['dd_under_10_rate']:.1f}% | {stats['ir']:+.4f} |"
        )
    lines.append("")

    bv = analysis.get("buy_vs_avoid", {})
    if bv:
        lines.extend(["## 三、BUY vs AVOID 效应量", "",
            f"- BUY 平均超额: **{bv['buy_avg_excess']:+.2f}%**",
            f"- AVOID 平均超额: **{bv['avoid_avg_excess']:+.2f}%**",
            f"- 差值: **{bv['difference']:+.2f}%**",
            f"- Cohen's d: **{bv['cohens_d']:+.3f}**",
            "",
        ])

    lines.extend(["## 四、市场环境 × 信号", "",
        "| 环境 | 信号 | 样本 | 平均超额 | 正收益率 | 平均回撤 |",
        "|------|------|------|---------|---------|---------|"])
    for env, sigs in sorted(analysis.get("market_env_signal", {}).items()):
        for sig, stats in sorted(sigs.items()):
            lines.append(
                f"| {env:18s} | {sig:5s} | {stats['count']:4d} | "
                f"{stats['avg_excess']:+6.2f}% | {stats['positive_rate']:5.1f}% | {stats['avg_dd']:6.2f}% |"
            )
    lines.append("")

    lines.extend(["## 五、各窗口表现", "",
        "| 窗口 | 日期 | 环境 | 总样本 | BUY数 | AVOID数 | BUY超额 | BUY正收益率 | AVOID超额 | AVOID正收益率 |",
        "|------|------|------|--------|-------|---------|---------|------------|----------|------------|"])
    for wid, stats in sorted(analysis.get("by_window", {}).items()):
        buy_ex = stats.get("BUY_excess", "-")
        buy_pr = stats.get("BUY_positive_rate", "-")
        avoid_ex = stats.get("AVOID_excess", "-")
        avoid_pr = stats.get("AVOID_positive_rate", "-")
        buy_ex_str = f"{buy_ex:+.1f}%" if isinstance(buy_ex, (int, float)) else buy_ex
        buy_pr_str = f"{buy_pr:.1f}%" if isinstance(buy_pr, (int, float)) else buy_pr
        avoid_ex_str = f"{avoid_ex:+.1f}%" if isinstance(avoid_ex, (int, float)) else avoid_ex
        avoid_pr_str = f"{avoid_pr:.1f}%" if isinstance(avoid_pr, (int, float)) else avoid_pr
        lines.append(
            f"| {wid:>2s} | {stats['date']} | {stats['label']:18s} | {stats['total']:4d} | "
            f"{stats['buy_count']:5d} | {stats['avoid_count']:5d} | {buy_ex_str:8s} | {buy_pr_str:10s} | {avoid_ex_str:8s} | {avoid_pr_str:10s} |"
        )
    lines.append("")

    lines.extend(["## 六、回撤分布", ""])
    for sig, dist in analysis.get("drawdown_distribution", {}).items():
        lines.extend([f"### {sig} 信号回撤分布", "",
            "| 回撤区间 | 样本 | 平均超额 | 正收益率 |",
            "|----------|------|---------|---------|"])
        for dd_bin, dd_stats in dist.items():
            lines.append(f"| {dd_bin:8s} | {dd_stats['count']:4d} | {dd_stats['avg_excess']:+6.2f}% | {dd_stats['positive_rate']:5.1f}% |")
        lines.append("")

    (output_dir / "factor_report.md").write_text("\n".join(lines), encoding="utf-8")


# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Wyckoff 最佳因子验证")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default="output/wyckoff_best_factor_full_50win")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Wyckoff 最佳因子验证回测")
    print("=" * 70)
    print("约束: T+1 + 只能做多")
    print(f"股票: {args.limit}只随机 (种子={args.seed})")
    print(f"窗口: {len(TIME_WINDOWS)}个 (2012-2023)")
    print(f"前瞻: {FORWARD_DAYS}天")
    print(f"基准: {BENCHMARK}")
    print(f"Wyckoff: {WYCKOFF_LOOKBACK}天")
    print(f"线程: {args.workers}")
    print("信号规则:")
    print("  BUY   = 观察等待 (accumulation + spring)")
    print("  AVOID = 持有观察 (markup)")
    print("  HOLD  = 空仓观望 (其余)")
    print("=" * 70)

    # 股票列表
    stock_path = PROJECT_ROOT / "data" / "stock_list.csv"
    if not stock_path.exists():
        stock_path = PROJECT_ROOT / "stock_list.csv"
    symbols = load_stock_symbols(stock_path, limit=args.limit, random_seed=args.seed)
    print(f"\n加载: {len(symbols)}只")

    # 基准
    dm = DataManager()
    bench_returns = precompute_bench(dm)
    print("\n基准收益:")
    for tw in TIME_WINDOWS:
        print(f"  {tw['date']} ({tw['label']}): {bench_returns[tw['id']]:+.2f}%")

    # 并行
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

    # 分析
    print("分析中...")
    analysis = analyze(all_results)

    # 保存
    save_report(all_results, analysis, output_dir)
    print(f"输出: {output_dir}/")

    # 打印关键结论
    print("\n" + "=" * 70)
    print("关键结论")
    print("=" * 70)

    for sig, stats in analysis.get("signal_stats", {}).items():
        print(f"\n【{sig}】 n={stats['count']}")
        print(f"  平均收益: {stats['avg_return']:+.2f}%")
        print(f"  平均超额: {stats['avg_excess']:+.2f}%")
        print(f"  正收益率: {stats['positive_return_rate']:.1f}%")
        print(f"  >基准率: {stats['beat_benchmark_rate']:.1f}%")
        print(f"  平均回撤: {stats['avg_max_dd']:.2f}%")
        print(f"  回撤<10%: {stats['dd_under_10_rate']:.1f}%")
        print(f"  信息比率: {stats['ir']:+.4f}")

    bv = analysis.get("buy_vs_avoid", {})
    if bv:
        print("\n【BUY vs AVOID】")
        print(f"  超额差: {bv['difference']:+.2f}%")
        print(f"  Cohen's d: {bv['cohens_d']:+.3f}")

    print("\n完成!")


if __name__ == "__main__":
    main()
