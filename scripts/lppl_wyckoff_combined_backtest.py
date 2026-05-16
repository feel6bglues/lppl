#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
LPPL + Wyckoff 综合回测脚本

根据 LPPL_Wyckoff_Combined_Analysis.md 文档制定:
- 使用 LPPL 调优参数（基于 lppl_params_20260327.json 最佳配置）
- 使用 Wyckoff 调优参数（300天窗口、B级置信度）
- 从 stock_list.csv 提取 200 只股票
- 选择 2012-2023 年 10 个时间窗口
- 拟合随后真实 90 天日线数据
- 以沪深300 为基准分析收益率和因子有效性
- 多线程并行（CPU核数 - 2）

用法:
    python scripts/lppl_wyckoff_combined_backtest.py
    python scripts/lppl_wyckoff_combined_backtest.py --limit 200 --workers 6
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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.lppl_engine import LPPLConfig, fit_single_window
from src.wyckoff.engine import WyckoffEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================================
# 配置常量 (来自 LPPL_Wyckoff_Combined_Analysis.md)
# ============================================================================

# 10 个时间窗口 (2012-2023, 选取市场关键转折点)
TIME_WINDOWS: List[Dict[str, Any]] = [
    {"id": 1,  "date": "2012-12-04", "label": "2012熊底",         "market_env": "bear_bottom"},
    {"id": 2,  "date": "2013-06-25", "label": "2013钱荒底",       "market_env": "bear_bottom"},
    {"id": 3,  "date": "2014-07-22", "label": "2014牛市启动",     "market_env": "bull_start"},
    {"id": 4,  "date": "2015-08-26", "label": "2015股灾底",       "market_env": "crash_bottom"},
    {"id": 5,  "date": "2016-01-27", "label": "2016熔断底",       "market_env": "crash_bottom"},
    {"id": 6,  "date": "2018-10-19", "label": "2018熊底",         "market_env": "bear_bottom"},
    {"id": 7,  "date": "2019-01-04", "label": "2019春季反弹启动", "market_env": "rebound_start"},
    {"id": 8,  "date": "2020-03-23", "label": "2020疫情底",       "market_env": "event_bottom"},
    {"id": 9,  "date": "2021-07-28", "label": "2021结构底",       "market_env": "structural_low"},
    {"id": 10, "date": "2022-10-31", "label": "2022熊底",         "market_env": "bear_bottom"},
]

# LPPL 最佳参数配置 (来自分析文档)
LPPL_CONFIG = {"window": 130, "rmse_threshold": 0.025, "m_upper": 0.35}

# Wyckoff 调优参数 (来自分析文档, 仅 300 天窗口)
WYCKOFF_LOOKBACK_DAYS = 300

# 回测参数
FORWARD_DAYS = 90  # 前瞻 90 个交易日
BENCHMARK_SYMBOL = "000300.SH"  # 沪深300


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class LPPLSignal:
    m: float = 0.0
    w: float = 0.0
    rmse: float = 1.0
    r_squared: float = 0.0
    days_to_crash: float = 0.0
    is_valid: bool = False
    is_bottom: bool = False
    is_top: bool = False


@dataclass
class WyckoffSignal:
    phase: str = "unknown"
    direction: str = "空仓观望"
    confidence: str = "D"
    signal_type: str = "no_signal"
    bc_found: bool = False
    spring_detected: bool = False
    rr_ratio: float = 0.0


# ============================================================================
# 工具函数
# ============================================================================

def load_stock_symbols(csv_path: Path, limit: int = 0, random_seed: int = 42) -> List[Dict[str, str]]:
    """
    从 stock_list.csv 加载 A 股股票代码，随机抽取指定数量
    
    严格过滤规则（仅保留股票，剔除指数/ETF/基金）:
    - 上海主板: 600/601/603/605 开头
    - 科创板: 688/689 开头
    - 深圳主板: 000/001 开头
    - 中小板: 002/003 开头
    - 创业板: 300/301/302 开头
    - 市场必须是 SH 或 SZ
    
    排除: 15/51/56/58 开头的ETF, 以及所有指数代码
    """
    all_valid = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            
            # 基础校验: 6位数字 + SH/SZ市场
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            
            # 仅保留股票代码前缀
            valid_prefixes = (
                "600", "601", "603", "605",  # 上海主板
                "688", "689",                  # 科创板
                "000", "001",                  # 深圳主板
                "002", "003",                  # 中小板
                "300", "301", "302",           # 创业板
            )
            if not code.startswith(valid_prefixes):
                continue
            
            all_valid.append({
                "symbol": f"{code}.{market}",
                "code": code,
                "market": market,
                "name": name,
            })
    
    # 随机抽取
    if limit > 0 and len(all_valid) > limit:
        rng = random.Random(random_seed)
        all_valid = rng.sample(all_valid, limit)
    
    return all_valid


def calculate_forward_return(
    df: pd.DataFrame,
    signal_date: str,
    days: int = FORWARD_DAYS,
) -> Optional[Dict[str, float]]:
    """计算信号日后 N 个交易日的前瞻收益率"""
    signal_ts = pd.Timestamp(signal_date)
    before = df[df["date"] <= signal_ts]
    if before.empty:
        return None
    entry_idx = before.index[-1]
    entry_price = float(before.iloc[-1]["close"])

    future_data = df.loc[entry_idx + 1:].head(days)
    if len(future_data) < int(days * 0.75):
        return None

    future_close = float(future_data.iloc[-1]["close"])
    future_high = float(future_data["high"].max())
    future_low = float(future_data["low"].min())

    return_pct = (future_close - entry_price) / entry_price * 100
    max_gain = (future_high - entry_price) / entry_price * 100
    max_dd = (entry_price - future_low) / entry_price * 100

    return {
        "return_pct": round(return_pct, 2),
        "max_gain_pct": round(max_gain, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "entry_price": round(entry_price, 3),
        "exit_price": round(future_close, 3),
        "data_points": len(future_data),
    }


def run_lppl_fit(close_prices: np.ndarray) -> LPPLSignal:
    """
    LPPL 单窗口拟合
    窗口=130天, RMSE阈值=0.025, m上限=0.35 (来自分析文档)
    """
    window = LPPL_CONFIG["window"]
    rmse_threshold = LPPL_CONFIG["rmse_threshold"]
    m_upper = LPPL_CONFIG["m_upper"]

    if len(close_prices) < window + 10:
        return LPPLSignal()

    config = LPPLConfig(
        window_range=[window],
        maxiter=80,
        popsize=12,
        tol=0.05,
    )

    result = fit_single_window(close_prices, window, config)
    if result is None:
        return LPPLSignal()

    m = result["m"]
    rmse = result["rmse"]
    r2 = result["r_squared"]
    w = result["w"]
    dtc = result["days_to_crash"]

    is_valid = 0.1 < m < 0.9 and 6 < w < 13 and rmse < rmse_threshold * 2
    is_bottom = is_valid and m < m_upper and rmse < rmse_threshold
    is_top = is_valid and m > 0.85 and rmse < rmse_threshold

    return LPPLSignal(
        m=round(m, 4), w=round(w, 4), rmse=round(rmse, 6),
        r_squared=round(r2, 4), days_to_crash=round(dtc, 2),
        is_valid=is_valid, is_bottom=is_bottom, is_top=is_top,
    )


def run_wyckoff_analysis(df: pd.DataFrame, symbol: str) -> WyckoffSignal:
    """Wyckoff 分析 (300天窗口)"""
    try:
        engine = WyckoffEngine(lookback_days=WYCKOFF_LOOKBACK_DAYS)
        report = engine.analyze(df, symbol=symbol, period="日线", multi_timeframe=False)

        bc_found = report.structure.bc_point is not None if report.structure else False
        signal_type = report.signal.signal_type if report.signal else "no_signal"

        return WyckoffSignal(
            phase=report.structure.phase.value if report.structure and report.structure.phase else "unknown",
            direction=report.trading_plan.direction if report.trading_plan else "空仓观望",
            confidence=report.trading_plan.confidence.value if report.trading_plan and report.trading_plan.confidence else "D",
            signal_type=signal_type,
            bc_found=bc_found,
            spring_detected=(signal_type == "spring"),
            rr_ratio=round(report.risk_reward.reward_risk_ratio, 3) if report.risk_reward else 0.0,
        )
    except Exception as e:
        logger.debug(f"Wyckoff分析异常 {symbol}: {e}")
        return WyckoffSignal()


def compute_combined_score(lppl: LPPLSignal, wy: WyckoffSignal) -> Tuple[float, str]:
    """LPPL + Wyckoff 综合评分"""
    score = 0.0

    # LPPL 贡献 (满分 50)
    if lppl.is_valid:
        score += 10
        if lppl.is_bottom:
            score += 25
        if lppl.is_top:
            score -= 15
        if lppl.rmse < 0.015:
            score += 10
        elif lppl.rmse < 0.025:
            score += 5
        if lppl.r_squared > 0.8:
            score += 5

    # Wyckoff 贡献 (满分 50)
    phase_scores = {
        "accumulation": 25, "distribution": 10, "markdown": 15,
        "markup": 5, "unknown": 0, "no_trade_zone": -5,
    }
    score += phase_scores.get(wy.phase, 0)

    conf_bonus = {"B": 0.3, "A": 0.2, "C": 0.0, "D": -0.1}
    score += conf_bonus.get(wy.confidence, 0) * 10

    if wy.spring_detected:
        score += 8
    if wy.signal_type in ("sos_candidate", "spring"):
        score += 5
    if wy.direction in ("做多", "观察等待", "轻仓试探"):
        score += 5

    if score >= 60:
        label = "strong_buy"
    elif score >= 40:
        label = "buy"
    elif score >= 20:
        label = "watch"
    elif score >= 0:
        label = "neutral"
    else:
        label = "avoid"

    return round(score, 1), label


# ============================================================================
# 单股票处理
# ============================================================================

def process_single_stock(
    symbol_info: Dict[str, str],
    benchmark_returns: Dict[int, float],
) -> Tuple[List[Dict], str]:
    """
    处理单只股票的所有时间窗口
    返回 (结果列表, 错误信息)
    """
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    results = []
    error_msg = ""

    try:
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty:
            return results, f"{symbol}: 无数据"
        if len(df) < 200:
            return results, f"{symbol}: 数据不足({len(df)}行)"

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        for tw in TIME_WINDOWS:
            signal_date = tw["date"]
            signal_ts = pd.Timestamp(signal_date)

            # 截取截至信号日的数据
            available = df[df["date"] <= signal_ts]
            if len(available) < 150:
                continue

            avail_close = available["close"].values

            # LPPL 拟合
            lppl = run_lppl_fit(avail_close)

            # Wyckoff 分析
            wy = run_wyckoff_analysis(available, symbol)

            # 综合评分
            score, label = compute_combined_score(lppl, wy)

            # 前瞻收益
            fwd = calculate_forward_return(df, signal_date, FORWARD_DAYS)
            if fwd is None:
                continue

            bench_ret = benchmark_returns.get(tw["id"], 0.0)
            excess = fwd["return_pct"] - bench_ret

            results.append({
                "symbol": symbol,
                "name": name,
                "window_id": tw["id"],
                "signal_date": signal_date,
                "market_env": tw["market_env"],
                "label_desc": tw["label"],
                "lppl_m": lppl.m, "lppl_w": lppl.w, "lppl_rmse": lppl.rmse,
                "lppl_r2": lppl.r_squared, "lppl_dtc": lppl.days_to_crash,
                "lppl_valid": lppl.is_valid, "lppl_bottom": lppl.is_bottom,
                "lppl_top": lppl.is_top,
                "wy_phase": wy.phase, "wy_direction": wy.direction,
                "wy_confidence": wy.confidence, "wy_signal": wy.signal_type,
                "wy_bc": wy.bc_found, "wy_spring": wy.spring_detected,
                "wy_rr": wy.rr_ratio,
                "combined_score": score, "signal_label": label,
                "fwd_return": fwd["return_pct"],
                "fwd_max_gain": fwd["max_gain_pct"],
                "fwd_max_dd": fwd["max_drawdown_pct"],
                "bench_return": round(bench_ret, 2),
                "excess_return": round(excess, 2),
            })

    except Exception as e:
        error_msg = f"{symbol}: {type(e).__name__}: {e}"

    return results, error_msg


# ============================================================================
# 基准收益计算
# ============================================================================

def precompute_benchmark_returns(bench_df: pd.DataFrame) -> Dict[int, float]:
    """预计算沪深300在每个时间窗口的 90 天前瞻收益"""
    returns = {}
    for tw in TIME_WINDOWS:
        fwd = calculate_forward_return(bench_df, tw["date"], FORWARD_DAYS)
        returns[tw["id"]] = fwd["return_pct"] if fwd else 0.0
    return returns


# ============================================================================
# 结果分析
# ============================================================================

def analyze_results(all_results: List[Dict]) -> Dict:
    """分析测试结果, 计算因子有效性"""
    if not all_results:
        return {"error": "No results"}

    df = pd.DataFrame(all_results)
    analysis = {}

    # 总体统计
    analysis["overall"] = {
        "total_signals": len(df),
        "unique_stocks": df["symbol"].nunique(),
        "avg_stock_return": round(df["fwd_return"].mean(), 2),
        "avg_benchmark_return": round(df["bench_return"].mean(), 2),
        "avg_excess_return": round(df["excess_return"].mean(), 2),
        "excess_win_rate": round(len(df[df["excess_return"] > 0]) / len(df) * 100, 1),
        "median_excess": round(df["excess_return"].median(), 2),
    }

    # LPPL 有效性
    lppl_valid = df[df["lppl_valid"]]
    lppl_invalid = df[~df["lppl_valid"]]
    analysis["lppl_effectiveness"] = {
        "valid_count": len(lppl_valid),
        "valid_avg_excess": round(lppl_valid["excess_return"].mean(), 2) if len(lppl_valid) > 0 else 0,
        "valid_win_rate": round(len(lppl_valid[lppl_valid["excess_return"] > 0]) / len(lppl_valid) * 100, 1) if len(lppl_valid) > 0 else 0,
        "invalid_count": len(lppl_invalid),
        "invalid_avg_excess": round(lppl_invalid["excess_return"].mean(), 2) if len(lppl_invalid) > 0 else 0,
        "invalid_win_rate": round(len(lppl_invalid[lppl_invalid["excess_return"] > 0]) / len(lppl_invalid) * 100, 1) if len(lppl_invalid) > 0 else 0,
    }

    # LPPL 底部信号
    lppl_bottom = df[df["lppl_bottom"]]
    analysis["lppl_bottom_signal"] = {
        "count": len(lppl_bottom),
        "avg_excess": round(lppl_bottom["excess_return"].mean(), 2) if len(lppl_bottom) > 0 else 0,
        "win_rate": round(len(lppl_bottom[lppl_bottom["excess_return"] > 0]) / len(lppl_bottom) * 100, 1) if len(lppl_bottom) > 0 else 0,
    }

    # Wyckoff 阶段
    phase_stats = {}
    for phase in df["wy_phase"].unique():
        p_df = df[df["wy_phase"] == phase]
        phase_stats[phase] = {
            "count": len(p_df),
            "avg_return": round(p_df["fwd_return"].mean(), 2),
            "avg_excess": round(p_df["excess_return"].mean(), 2),
            "win_rate": round(len(p_df[p_df["excess_return"] > 0]) / len(p_df) * 100, 1),
            "median_excess": round(p_df["excess_return"].median(), 2),
        }
    analysis["wyckoff_phase"] = phase_stats

    # Wyckoff 置信度
    conf_stats = {}
    for conf in sorted(df["wy_confidence"].unique()):
        c_df = df[df["wy_confidence"] == conf]
        conf_stats[conf] = {
            "count": len(c_df),
            "avg_return": round(c_df["fwd_return"].mean(), 2),
            "avg_excess": round(c_df["excess_return"].mean(), 2),
            "win_rate": round(len(c_df[c_df["excess_return"] > 0]) / len(c_df) * 100, 1),
        }
    analysis["wyckoff_confidence"] = conf_stats

    # 综合信号标签
    label_stats = {}
    for label in ["strong_buy", "buy", "watch", "neutral", "avoid"]:
        l_df = df[df["signal_label"] == label]
        if len(l_df) == 0:
            continue
        label_stats[label] = {
            "count": len(l_df),
            "avg_return": round(l_df["fwd_return"].mean(), 2),
            "avg_excess": round(l_df["excess_return"].mean(), 2),
            "win_rate": round(len(l_df[l_df["excess_return"] > 0]) / len(l_df) * 100, 1),
        }
    analysis["combined_signal"] = label_stats

    # 市场环境分组
    env_stats = {}
    for env in df["market_env"].unique():
        e_df = df[df["market_env"] == env]
        env_stats[env] = {
            "count": len(e_df),
            "avg_return": round(e_df["fwd_return"].mean(), 2),
            "avg_benchmark": round(e_df["bench_return"].mean(), 2),
            "avg_excess": round(e_df["excess_return"].mean(), 2),
            "win_rate": round(len(e_df[e_df["excess_return"] > 0]) / len(e_df) * 100, 1),
        }
    analysis["market_environment"] = env_stats

    # 时间窗口分组
    window_stats = {}
    for wid in sorted(df["window_id"].unique()):
        w_df = df[df["window_id"] == wid]
        window_stats[str(wid)] = {
            "date": w_df["signal_date"].iloc[0],
            "label": w_df["label_desc"].iloc[0],
            "count": len(w_df),
            "avg_return": round(w_df["fwd_return"].mean(), 2),
            "bench_return": round(w_df["bench_return"].iloc[0], 2),
            "avg_excess": round(w_df["excess_return"].mean(), 2),
            "win_rate": round(len(w_df[w_df["excess_return"] > 0]) / len(w_df) * 100, 1),
        }
    analysis["by_window"] = window_stats

    # 联合场景
    scene_a = df[(df["lppl_bottom"]) & (df["wy_phase"] == "accumulation") & (df["wy_confidence"] == "B")]
    scene_b = df[(df["lppl_bottom"]) & (df["wy_spring"])]
    scene_c = df[(df["lppl_valid"]) & (df["wy_confidence"] == "B")]

    def _scene_stats(s_df):
        return {
            "count": len(s_df),
            "avg_excess": round(s_df["excess_return"].mean(), 2) if len(s_df) > 0 else 0,
            "win_rate": round(len(s_df[s_df["excess_return"] > 0]) / len(s_df) * 100, 1) if len(s_df) > 0 else 0,
        }

    analysis["combined_scenarios"] = {
        "scene_a_lppl_bottom_accumulation_b": {**_scene_stats(scene_a), "description": "LPPL底部 + Wyckoff Accumulation + B级"},
        "scene_b_lppl_bottom_spring": {**_scene_stats(scene_b), "description": "LPPL底部 + Wyckoff Spring信号"},
        "scene_c_lppl_valid_b_confidence": {**_scene_stats(scene_c), "description": "LPPL有效 + Wyckoff B级置信度"},
    }

    return analysis


# ============================================================================
# 报告输出
# ============================================================================

def save_results(all_results: List[Dict], analysis: Dict, output_dir: Path):
    """保存结果到文件"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 明细数据 CSV
    detail_path = output_dir / "lppl_wyckoff_combined_detail.csv"
    if all_results:
        pd.DataFrame(all_results).to_csv(detail_path, index=False, encoding="utf-8-sig")
        print(f"  明细数据: {detail_path} ({len(all_results)} 行)")

    # 2. 分析报告 JSON
    analysis_path = output_dir / "lppl_wyckoff_combined_analysis.json"
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"  分析报告: {analysis_path}")

    # 3. 可读报告 MD
    report_path = output_dir / "lppl_wyckoff_combined_report.md"
    _write_readable_report(analysis, report_path)
    print(f"  可读报告: {report_path}")


def _write_readable_report(analysis: Dict, path: Path):
    """生成 Markdown 报告"""
    lines = [
        "# LPPL + Wyckoff 综合回测报告",
        "",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "> 基准: 沪深300 (000300.SH), 前瞻窗口: 90 个交易日",
        "",
    ]

    ov = analysis.get("overall", {})
    lines.extend([
        "## 一、总体统计", "",
        f"- 总信号数: **{ov.get('total_signals', 0)}**",
        f"- 覆盖股票数: **{ov.get('unique_stocks', 0)}**",
        f"- 平均股票收益: **{ov.get('avg_stock_return', 0)}%**",
        f"- 平均基准收益: **{ov.get('avg_benchmark_return', 0)}%**",
        f"- 平均超额收益: **{ov.get('avg_excess_return', 0)}%**",
        f"- 超额胜率: **{ov.get('excess_win_rate', 0)}%**",
        f"- 超额中位数: **{ov.get('median_excess', 0)}%**", "",
    ])

    lp = analysis.get("lppl_effectiveness", {})
    lines.extend([
        "## 二、LPPL 因子有效性", "",
        "| 类别 | 样本数 | 平均超额 | 胜率 |",
        "|------|--------|----------|------|",
        f"| LPPL 有效信号 | {lp.get('valid_count', 0)} | {lp.get('valid_avg_excess', 0)}% | {lp.get('valid_win_rate', 0)}% |",
        f"| LPPL 无效信号 | {lp.get('invalid_count', 0)} | {lp.get('invalid_avg_excess', 0)}% | {lp.get('invalid_win_rate', 0)}% |",
    ])
    lb = analysis.get("lppl_bottom_signal", {})
    lines.append(f"| LPPL 底部信号 | {lb.get('count', 0)} | {lb.get('avg_excess', 0)}% | {lb.get('win_rate', 0)}% |")
    lines.append("")

    lines.extend(["## 三、Wyckoff 阶段有效性", "",
        "| 阶段 | 样本数 | 平均收益 | 平均超额 | 胜率 | 中位数超额 |",
        "|------|--------|----------|----------|------|------------|"])
    for phase, stats in sorted(analysis.get("wyckoff_phase", {}).items()):
        lines.append(f"| {phase} | {stats['count']} | {stats['avg_return']}% | {stats['avg_excess']}% | {stats['win_rate']}% | {stats['median_excess']}% |")
    lines.append("")

    lines.extend(["## 四、Wyckoff 置信度有效性", "",
        "| 置信度 | 样本数 | 平均收益 | 平均超额 | 胜率 |",
        "|--------|--------|----------|----------|------|"])
    for conf, stats in sorted(analysis.get("wyckoff_confidence", {}).items()):
        lines.append(f"| {conf} | {stats['count']} | {stats['avg_return']}% | {stats['avg_excess']}% | {stats['win_rate']}% |")
    lines.append("")

    lines.extend(["## 五、综合信号有效性", "",
        "| 信号标签 | 样本数 | 平均收益 | 平均超额 | 胜率 |",
        "|----------|--------|----------|----------|------|"])
    for label, stats in analysis.get("combined_signal", {}).items():
        lines.append(f"| {label} | {stats['count']} | {stats['avg_return']}% | {stats['avg_excess']}% | {stats['win_rate']}% |")
    lines.append("")

    lines.extend(["## 六、LPPL + Wyckoff 联合场景", "",
        "| 场景 | 样本数 | 平均超额 | 胜率 | 说明 |",
        "|------|--------|----------|------|------|"])
    for stats in analysis.get("combined_scenarios", {}).values():
        lines.append(f"| {stats.get('description', '')} | {stats['count']} | {stats['avg_excess']}% | {stats['win_rate']}% | {stats.get('description', '')} |")
    lines.append("")

    lines.extend(["## 七、市场环境分组", "",
        "| 环境 | 样本数 | 平均收益 | 平均基准 | 平均超额 | 胜率 |",
        "|------|--------|----------|----------|----------|------|"])
    for env, stats in analysis.get("market_environment", {}).items():
        lines.append(f"| {env} | {stats['count']} | {stats['avg_return']}% | {stats['avg_benchmark']}% | {stats['avg_excess']}% | {stats['win_rate']}% |")
    lines.append("")

    lines.extend(["## 八、各时间窗口表现", "",
        "| 窗口 | 日期 | 描述 | 样本数 | 平均收益 | 基准收益 | 平均超额 | 胜率 |",
        "|------|------|------|--------|----------|----------|----------|------|"])
    for wid, stats in analysis.get("by_window", {}).items():
        lines.append(f"| {wid} | {stats['date']} | {stats['label']} | {stats['count']} | {stats['avg_return']}% | {stats['bench_return']}% | {stats['avg_excess']}% | {stats['win_rate']}% |")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="LPPL + Wyckoff 综合回测")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2),
                        help="并行线程数 (默认: CPU核数-2)")
    parser.add_argument("--limit", type=int, default=1000,
                        help="随机抽取股票数量 (默认 1000)")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子 (默认 42)")
    parser.add_argument("--output", type=str, default="output/lppl_wyckoff_combined_1000",
                        help="输出目录")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("LPPL + Wyckoff 综合回测")
    print("=" * 70)
    print(f"股票数量: {args.limit} (随机抽取, 种子={args.seed})")
    print(f"时间窗口: {len(TIME_WINDOWS)} 个 (2012-2023)")
    print(f"前瞻天数: {FORWARD_DAYS} 个交易日")
    print(f"基准: {BENCHMARK_SYMBOL} (沪深300)")
    print(f"LPPL 窗口: {LPPL_CONFIG['window']}天, RMSE<{LPPL_CONFIG['rmse_threshold']}, m<{LPPL_CONFIG['m_upper']}")
    print(f"Wyckoff 窗口: {WYCKOFF_LOOKBACK_DAYS} 天")
    print(f"并行线程: {args.workers} (CPU核数={os.cpu_count()})")
    print("=" * 70)

    # 1. 加载股票列表
    stock_list_path = PROJECT_ROOT / "data" / "stock_list.csv"
    if not stock_list_path.exists():
        stock_list_path = PROJECT_ROOT / "stock_list.csv"
    if not stock_list_path.exists():
        print("错误: 找不到 stock_list.csv")
        sys.exit(1)

    symbols = load_stock_symbols(stock_list_path, limit=args.limit, random_seed=args.seed)
    print(f"\n加载股票: {len(symbols)} 只")

    # 2. 加载基准数据并预计算收益
    print("\n加载沪深300基准数据...")
    dm = DataManager()
    bench_df = dm.get_data(BENCHMARK_SYMBOL)
    if bench_df is None or bench_df.empty:
        print("错误: 无法加载沪深300数据")
        sys.exit(1)
    bench_df["date"] = pd.to_datetime(bench_df["date"])
    bench_df = bench_df.sort_values("date").reset_index(drop=True)

    bench_returns = precompute_benchmark_returns(bench_df)
    print("基准 90 天前瞻收益:")
    for tw in TIME_WINDOWS:
        ret = bench_returns.get(tw["id"], 0.0)
        print(f"  窗口 {tw['id']:2d} ({tw['date']}): {ret:+.2f}%  [{tw['label']}]")

    # 3. 多线程并行处理
    print(f"\n开始回测 ({len(symbols)} 只股票 x {len(TIME_WINDOWS)} 个窗口)...")
    t0 = time.time()

    all_results: List[Dict] = []
    errors: List[str] = []
    progress_lock = threading.Lock()
    progress_counter = {"completed": 0}

    def _on_complete(future):
        with progress_lock:
            progress_counter["completed"] += 1
            done = progress_counter["completed"]
            if done % 50 == 0 or done == len(symbols):
                elapsed = time.time() - t0
                speed = done / elapsed if elapsed > 0 else 0
                eta = (len(symbols) - done) / speed if speed > 0 else 0
                print(f"  进度: {done}/{len(symbols)} ({done/len(symbols)*100:.0f}%) "
                      f"| 累计结果: {len(all_results)} | 耗时: {elapsed:.0f}s | ETA: {eta:.0f}s")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = []
        for sym in symbols:
            fut = executor.submit(process_single_stock, sym, bench_returns)
            fut.add_done_callback(_on_complete)
            futures.append(fut)

        for fut in futures:
            try:
                results, err = fut.result()
                all_results.extend(results)
                if err:
                    errors.append(err)
            except Exception as e:
                errors.append(f"线程异常: {e}")

    elapsed = time.time() - t0
    print(f"\n回测完成: {len(all_results)} 条有效记录, {len(errors)} 条错误, 耗时 {elapsed:.1f}s")

    if errors:
        err_path = output_dir / "errors.log"
        with open(err_path, "w", encoding="utf-8") as f:
            f.write("\n".join(errors))
        print(f"  错误日志: {err_path} (前10条: {errors[:10]})")

    # 4. 分析结果
    print("\n分析因子有效性...")
    analysis = analyze_results(all_results)

    # 5. 保存结果
    print("\n保存结果...")
    save_results(all_results, analysis, output_dir)

    # 6. 打印关键结论
    print("\n" + "=" * 70)
    print("关键结论")
    print("=" * 70)

    ov = analysis.get("overall", {})
    print(f"总信号数: {ov.get('total_signals', 0)}")
    print(f"覆盖股票: {ov.get('unique_stocks', 0)}")
    print(f"平均股票收益: {ov.get('avg_stock_return', 0)}%")
    print(f"平均基准收益: {ov.get('avg_benchmark_return', 0)}%")
    print(f"平均超额收益: {ov.get('avg_excess_return', 0)}%")
    print(f"超额胜率: {ov.get('excess_win_rate', 0)}%")

    print("\n--- LPPL 因子 ---")
    lp = analysis.get("lppl_effectiveness", {})
    print(f"有效信号: {lp.get('valid_count', 0)} (超额 {lp.get('valid_avg_excess', 0)}%, 胜率 {lp.get('valid_win_rate', 0)}%)")
    print(f"无效信号: {lp.get('invalid_count', 0)} (超额 {lp.get('invalid_avg_excess', 0)}%, 胜率 {lp.get('invalid_win_rate', 0)}%)")
    lb = analysis.get("lppl_bottom_signal", {})
    print(f"底部信号: {lb.get('count', 0)} (超额 {lb.get('avg_excess', 0)}%, 胜率 {lb.get('win_rate', 0)}%)")

    print("\n--- Wyckoff 阶段 (按超额排序) ---")
    for phase, stats in sorted(analysis.get("wyckoff_phase", {}).items(), key=lambda x: x[1]["avg_excess"], reverse=True):
        print(f"  {phase:15s}: {stats['count']:5d} 样本, 超额 {stats['avg_excess']:+6.2f}%, 胜率 {stats['win_rate']:5.1f}%")

    print("\n--- Wyckoff 置信度 ---")
    for conf, stats in sorted(analysis.get("wyckoff_confidence", {}).items()):
        print(f"  {conf}: {stats['count']:5d} 样本, 超额 {stats['avg_excess']:+6.2f}%, 胜率 {stats['win_rate']:5.1f}%")

    print("\n--- 综合信号 ---")
    for label, stats in analysis.get("combined_signal", {}).items():
        print(f"  {label:12s}: {stats['count']:5d} 样本, 超额 {stats['avg_excess']:+6.2f}%, 胜率 {stats['win_rate']:5.1f}%")

    print("\n--- 联合场景 ---")
    for stats in analysis.get("combined_scenarios", {}).values():
        print(f"  {stats.get('description', '')}: {stats['count']} 样本, 超额 {stats['avg_excess']:+6.2f}%, 胜率 {stats['win_rate']:5.1f}%")

    print("\n--- 各窗口表现 ---")
    for wid, stats in analysis.get("by_window", {}).items():
        print(f"  窗口{wid:>2s} ({stats['date']}, {stats['label']}): "
              f"平均{stats['avg_return']:+6.2f}% | 基准{stats['bench_return']:+6.2f}% | "
              f"超额{stats['avg_excess']:+6.2f}% | 胜率{stats['win_rate']:5.1f}%")

    print("\n完成!")


if __name__ == "__main__":
    main()
