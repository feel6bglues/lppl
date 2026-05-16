#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
LPPL 多窗口+移动平均趋势预警测试程序

基于lppl.py的现有算法参数，测试不同窗口策略、步长和移动平均的组合

使用方法:
    python test_lppl_ma.py --symbol 000001.SH
    python test_lppl_ma.py --all
"""

import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.optimize import differential_evolution

warnings.filterwarnings("ignore")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# CPU核心数
CPU_CORES = max(1, (os.cpu_count() or 4) - 2)

# ============================================================================
# lppl.py 原有算法参数
# ============================================================================

# 窗口范围 (与lppl.py一致)
WINDOW_RANGE_SHORT = list(range(50, 200, 10))   # 短期: 50-190
WINDOW_RANGE_MEDIUM = list(range(200, 520, 20)) # 中期: 200-500
WINDOW_RANGE_LONG = list(range(600, 1200, 50))  # 长期: 600-1150
WINDOW_RANGE_ALL = WINDOW_RANGE_SHORT + WINDOW_RANGE_MEDIUM + WINDOW_RANGE_LONG

# 已知牛市顶部
PEAKS = {
    '000001.SH': {'2007': '2007-10-16', '2015': '2015-06-12'},
    '399001.SZ': {'2007': '2007-10-31', '2015': '2015-06-12'},
    '399006.SZ': {'2015': '2015-06-03'},
    '000016.SH': {'2007': '2007-10-16', '2015': '2015-06-08'},
    '000300.SH': {'2007': '2007-10-16', '2015': '2015-06-08'},
    '000905.SH': {'2007': '2007-10-09', '2015': '2015-06-12'},
    '000852.SH': {'2007': '2007-09-18', '2015': '2015-06-12'},
}

SYMBOLS = {
    '000001.SH': '上证综指',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
    '000016.SH': '上证50',
    '000300.SH': '沪深300',
    '000905.SH': '中证500',
    '000852.SH': '中证1000',
}


def lppl_func(t, tc, m, w, a, b, c, phi):
    """LPPL模型函数 (与lppl.py一致)"""
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau ** m) + c * (tau ** m) * np.cos(w * np.log(tau) + phi)


def cost_function(params, t, log_prices):
    """成本函数 (与lppl.py一致)"""
    tc, m, w, a, b, c, phi = params
    prediction = lppl_func(t, tc, m, w, a, b, c, phi)
    residuals = prediction - log_prices
    return np.sum(residuals ** 2)


def fit_window_lppl(close_prices, window_size):
    """
    拟合单个窗口 (与lppl.py的fit_window一致)
    
    Args:
        close_prices: 收盘价数组
        window_size: 窗口大小
    
    Returns:
        dict或None
    """
    if len(close_prices) < window_size:
        return None
    
    t_data = np.arange(window_size)
    price_data = close_prices[-window_size:]
    log_price_data = np.log(price_data)
    
    current_t = float(window_size)
    
    # lppl.py原参数
    bounds = [
        (current_t + 1, current_t + 100),
        (0.1, 0.9),
        (6, 13),
        (np.min(log_price_data), np.max(log_price_data) * 1.1),
        (-20, 20),
        (-20, 20),
        (0, 2 * np.pi)
    ]
    
    try:
        result = differential_evolution(
            cost_function, bounds, args=(t_data, log_price_data),
            strategy='best1bin', maxiter=100, popsize=15, tol=0.05, seed=42, workers=1
        )
        
        if not result.success:
            return None
        
        tc, m, w, a, b, c, phi = result.x
        days_to_crash = tc - current_t
        
        fitted_curve = lppl_func(t_data, tc, m, w, a, b, c, phi)
        mse = np.mean((fitted_curve - log_price_data) ** 2)
        rmse = np.sqrt(mse)
        
        # 计算R²
        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - np.mean(log_price_data)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        # lppl.py风险判定
        is_danger = (0.1 < m < 0.9) and (6 < w < 13) and (days_to_crash < 20) and (r_squared > 0.5)
        is_warning = (0.1 < m < 0.9) and (6 < w < 13) and (days_to_crash < 60) and (r_squared > 0.3)
        
        return {
            'window_size': window_size,
            'rmse': rmse,
            'r_squared': r_squared,
            'm': m,
            'w': w,
            'tc': tc,
            'days_to_crash': days_to_crash,
            'is_danger': bool(is_danger),
            'is_warning': bool(is_warning),
        }
    except Exception:
        return None


def scan_single_date(close_prices, idx, window_range):
    """
    对单个日期扫描所有窗口，选择最佳拟合
    
    Args:
        close_prices: 收盘价数组
        idx: 当前索引
        window_range: 窗口范围列表
    
    Returns:
        dict或None
    """
    results = []
    
    for window_size in window_range:
        if idx < window_size:
            continue
        
        subset = close_prices[idx - window_size:idx]
        res = fit_window_lppl(subset, window_size)
        
        if res is not None:
            res['idx'] = idx
            results.append(res)
    
    if not results:
        return None
    
    # 选择RMSE最低的结果
    best = min(results, key=lambda x: x['rmse'])
    return best


def scan_date_range(close_prices, start_idx, end_idx, window_range, step=1):
    """
    扫描日期范围内的所有窗口
    
    Args:
        close_prices: 收盘价数组
        start_idx: 起始索引
        end_idx: 结束索引
        window_range: 窗口范围列表
        step: 步长
    
    Returns:
        list of dict
    """
    indices = list(range(start_idx, end_idx, step))
    
    results = Parallel(n_jobs=CPU_CORES, backend='loky', verbose=0)(
        delayed(scan_single_date)(close_prices, idx, window_range)
        for idx in indices
    )
    
    return [r for r in results if r is not None]


def calculate_trend_scores(daily_results, ma_window=5):
    """
    计算趋势评分
    
    Args:
        daily_results: 每日最佳拟合结果列表
        ma_window: 移动平均窗口
    
    Returns:
        DataFrame
    """
    df = pd.DataFrame(daily_results)
    
    if len(df) == 0:
        return df
    
    df = df.sort_values('idx').reset_index(drop=True)
    
    # R²移动平均
    df['r2_ma'] = df['r_squared'].rolling(window=ma_window, min_periods=1).mean()
    
    # Danger信号计数 (MA窗口内)
    df['danger_count'] = df['is_danger'].rolling(window=ma_window, min_periods=1).sum()
    
    # 趋势得分
    df['trend_score'] = df['r2_ma'] * (df['danger_count'] / ma_window)
    
    # RMSE移动平均
    df['rmse_ma'] = df['rmse'].rolling(window=ma_window, min_periods=1).mean()
    
    return df


def evaluate_warning_performance(df, peak_date, analyze_days=180):
    """
    评估预警效果
    
    Args:
        df: 趋势分析结果
        peak_date: 顶部日期
        analyze_days: 分析天数
    
    Returns:
        dict
    """
    peak_idx = df[df['date'] == peak_date].index
    
    if len(peak_idx) == 0:
        return None
    
    peak_idx = peak_idx[0]
    
    # 获取顶部前的数据
    start_idx = max(0, peak_idx - analyze_days)
    period = df.loc[start_idx:peak_idx].copy()
    
    if len(period) == 0:
        return None
    
    # 首个danger信号
    danger_signals = period[period['is_danger']]
    first_danger = danger_signals.iloc[0] if len(danger_signals) > 0 else None
    
    # 最高趋势得分
    if len(period[period['trend_score'] > 0]) > 0:
        best_trend = period.loc[period['trend_score'].idxmax()]
    else:
        best_trend = period.iloc[-1]
    
    # 最高R²
    best_r2 = period.loc[period['r_squared'].idxmax()]
    
    # 计算预警天数
    days_first_danger = (peak_idx - first_danger.name) if first_danger is not None else None
    days_best_trend = (peak_idx - best_trend.name)
    days_best_r2 = (peak_idx - best_r2.name)
    
    return {
        'first_danger_days': days_first_danger,
        'best_trend_days': days_best_trend,
        'best_r2_days': days_best_r2,
        'best_trend_score': best_trend['trend_score'],
        'best_r2_value': best_r2['r_squared'],
        'danger_count': len(danger_signals),
        'warning_count': len(period[period['is_warning']]),
    }


def run_test(symbol, name, start_date, end_date, window_strategy, step, ma_window, output_dir):
    """
    运行单个测试组合
    
    Args:
        symbol: 指数代码
        name: 指数名称
        start_date: 开始日期
        end_date: 结束日期
        window_strategy: 窗口策略 ('S1', 'S2', 'S3', 'S4', 'S5')
        step: 扫描步长
        ma_window: 移动平均窗口
        output_dir: 输出目录
    
    Returns:
        dict
    """
    from src.data.manager import DataManager
    
    print(f"\n{'='*80}")
    print(f"测试: {name} ({symbol})")
    print(f"窗口策略: {window_strategy}, 步长: {step}, 移动平均: {ma_window}")
    print(f"{'='*80}")
    
    # 获取数据
    dm = DataManager()
    df = dm.get_data(symbol)
    
    if df is None or df.empty:
        print(f"无法获取 {name} 数据")
        return None
    
    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])
    
    # 过滤日期范围
    df = df[(df['date'] >= pd.to_datetime(start_date)) & 
            (df['date'] <= pd.to_datetime(end_date))].reset_index(drop=True)
    
    if len(df) < 100:
        print(f"数据不足: {len(df)} 天")
        return None
    
    close_prices = df['close'].values
    
    # 选择窗口范围
    if window_strategy == 'S1':
        window_range = WINDOW_RANGE_SHORT
    elif window_strategy == 'S2':
        window_range = WINDOW_RANGE_MEDIUM
    elif window_strategy == 'S3':
        window_range = WINDOW_RANGE_LONG
    elif window_strategy == 'S4':
        window_range = WINDOW_RANGE_ALL
    elif window_strategy == 'S5':
        window_range = [50, 100, 150, 200, 300, 500]
    else:
        window_range = WINDOW_RANGE_SHORT
    
    print(f"数据: {len(df)} 天 ({df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')})")
    print(f"窗口范围: {window_range[0]}-{window_range[-1]}天 ({len(window_range)}个)")
    print(f"扫描步长: {step}天")
    
    # 扫描
    start_idx = max(window_range) + 50  # 留出足够的历史数据
    end_idx = len(df) - 1
    
    print(f"扫描范围: 索引 {start_idx} ~ {end_idx}")
    
    start_time = time.time()
    results = scan_date_range(close_prices, start_idx, end_idx, window_range, step)
    elapsed = time.time() - start_time
    
    print(f"扫描完成: {len(results)} 个有效结果, 耗时 {elapsed:.1f}秒")
    
    if len(results) == 0:
        print("无有效结果")
        return None
    
    # 添加日期
    for r in results:
        r['date'] = df.iloc[r['idx']]['date']
        r['price'] = df.iloc[r['idx']]['close']
    
    # 计算趋势得分
    trend_df = calculate_trend_scores(results, ma_window)
    trend_df['date'] = trend_df['idx'].apply(lambda x: df.iloc[x]['date'] if x < len(df) else None)
    trend_df['price'] = trend_df['idx'].apply(lambda x: df.iloc[x]['close'] if x < len(df) else None)
    
    # 保存原始结果
    test_name = f"{symbol}_{window_strategy}_step{step}_ma{ma_window}"
    raw_file = os.path.join(output_dir, f"raw_{test_name}.parquet")
    trend_df.to_parquet(raw_file, index=False)
    print(f"原始结果已保存: {raw_file}")
    
    # 评估预警效果
    evaluation = {}
    if symbol in PEAKS:
        for year, peak_date_str in PEAKS[symbol].items():
            peak_date = pd.to_datetime(peak_date_str)
            if peak_date in trend_df['date'].values:
                perf = evaluate_warning_performance(trend_df, peak_date)
                if perf:
                    evaluation[f"{year}年"] = perf
    
    # 汇总统计
    total_scans = len(trend_df)
    danger_count = trend_df['is_danger'].sum()
    warning_count = trend_df['is_warning'].sum()
    
    result_summary = {
        'symbol': symbol,
        'name': name,
        'window_strategy': window_strategy,
        'step': step,
        'ma_window': ma_window,
        'total_scans': total_scans,
        'danger_count': danger_count,
        'warning_count': warning_count,
        'danger_ratio': danger_count / total_scans * 100 if total_scans > 0 else 0,
        'evaluation': evaluation,
    }
    
    print("\n统计:")
    print(f"  总扫描: {total_scans}")
    print(f"  Danger信号: {danger_count} ({result_summary['danger_ratio']:.1f}%)")
    print(f"  Warning信号: {warning_count}")
    
    for year, perf in evaluation.items():
        print(f"\n{year}顶部预警:")
        print(f"  首个Danger: {perf['first_danger_days']}天前" if perf['first_danger_days'] is not None else "  首个Danger: 无")
        print(f"  最高趋势得分: {perf['best_trend_days']}天前 (得分={perf['best_trend_score']:.4f})")
        print(f"  最高R²: {perf['best_r2_days']}天前 (R²={perf['best_r2_value']:.3f})")
    
    return result_summary


def generate_report(all_results, output_dir):
    """生成对比报告"""
    
    if not all_results:
        print("无结果可生成报告")
        return
    
    report_path = os.path.join(output_dir, "comparison_report.md")
    
    lines = []
    lines.append("# LPPL 多窗口+移动平均趋势预警测试报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 汇总表
    lines.append("## 一、测试结果汇总")
    lines.append("")
    lines.append("| 指数 | 窗口策略 | 步长 | 移动平均 | 总扫描 | Danger | 比例 |")
    lines.append("|:-----|:---------|-----:|--------:|-------:|-------:|-----:|")
    
    for r in all_results:
        lines.append(f"| {r['name']} | {r['window_strategy']} | {r['step']} | {r['ma_window']} | {r['total_scans']} | {r['danger_count']} | {r['danger_ratio']:.1f}% |")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 预警效果评估
    lines.append("## 二、预警效果评估")
    lines.append("")
    
    for r in all_results:
        lines.append(f"### {r['name']} ({r['window_strategy']}, step={r['step']}, MA={r['ma_window']})")
        lines.append("")
        
        if r['evaluation']:
            for year, perf in r['evaluation'].items():
                lines.append(f"**{year}顶部**:")
                lines.append("")
                if perf['first_danger_days'] is not None:
                    lines.append(f"- 首个Danger信号: **{perf['first_danger_days']}天前**")
                else:
                    lines.append("- 首个Danger信号: 无")
                lines.append(f"- 最高趋势得分: **{perf['best_trend_days']}天前** (得分={perf['best_trend_score']:.4f})")
                lines.append(f"- 最高R²: **{perf['best_r2_days']}天前** (R²={perf['best_r2_value']:.3f})")
                lines.append(f"- Danger信号数: {perf['danger_count']}")
                lines.append("")
        else:
            lines.append("无预警数据")
            lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # 最佳参数推荐
    lines.append("## 三、最佳参数推荐")
    lines.append("")
    
    # 按首个Danger信号天数排序
    results_with_danger = [r for r in all_results if any(
        perf.get('first_danger_days') is not None 
        for perf in r['evaluation'].values()
    )]
    
    if results_with_danger:
        # 计算平均预警天数
        for r in results_with_danger:
            danger_days = [perf['first_danger_days'] for perf in r['evaluation'].values() if perf.get('first_danger_days') is not None]
            r['avg_danger_days'] = np.mean(danger_days) if danger_days else float('inf')
        
        best_by_danger = sorted(results_with_danger, key=lambda x: x['avg_danger_days'])
        
        lines.append("### 按最早预警排序")
        lines.append("")
        lines.append("| 排名 | 指数 | 窗口策略 | 步长 | 移动平均 | 平均预警天数 |")
        lines.append("|-----:|:-----|:---------|-----:|--------:|------------:|")
        
        for i, r in enumerate(best_by_danger[:5], 1):
            lines.append(f"| {i} | {r['name']} | {r['window_strategy']} | {r['step']} | {r['ma_window']} | {r['avg_danger_days']:.0f}天 |")
        
        lines.append("")
        
        # 推荐最佳组合
        best = best_by_danger[0]
        lines.append("### 推荐最佳组合")
        lines.append("")
        lines.append(f"- **窗口策略**: {best['window_strategy']}")
        lines.append(f"- **扫描步长**: {best['step']}")
        lines.append(f"- **移动平均窗口**: {best['ma_window']}")
        lines.append(f"- **平均预警天数**: {best['avg_danger_days']:.0f}天")
    else:
        lines.append("无有效预警数据")
    
    # 写入文件
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"\n报告已保存: {report_path}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='LPPL 多窗口+移动平均趋势预警测试')
    parser.add_argument('--symbol', '-s', default=None, help='指数代码')
    parser.add_argument('--all', '-a', action='store_true', help='测试所有指数')
    parser.add_argument('--start', default='2014-01-01', help='开始日期')
    parser.add_argument('--end', default='2016-06-30', help='结束日期')
    parser.add_argument('--output', '-o', default='output/MA', help='输出目录')
    
    args = parser.parse_args()
    
    # 创建输出目录
    os.makedirs(args.output, exist_ok=True)
    
    print("="*80)
    print("LPPL 多窗口+移动平均趋势预警测试")
    print("="*80)
    print(f"日期范围: {args.start} ~ {args.end}")
    print(f"输出目录: {args.output}")
    print(f"CPU核心数: {CPU_CORES}")
    
    # 定义测试组合
    test_configs = [
        ('S4', 5, 3),   # 全窗口, 步长5, MA3
        ('S4', 5, 5),   # 全窗口, 步长5, MA5
        ('S4', 5, 7),   # 全窗口, 步长5, MA7
        ('S4', 10, 5),  # 全窗口, 步长10, MA5
        ('S1', 5, 5),   # 短期窗口, 步长5, MA5
        ('S2', 5, 5),   # 中期窗口, 步长5, MA5
        ('S3', 5, 5),   # 长期窗口, 步长5, MA5
    ]
    
    # 选择测试指数
    if args.all:
        symbols = SYMBOLS
    elif args.symbol:
        symbols = {args.symbol: SYMBOLS.get(args.symbol, args.symbol)}
    else:
        # 默认测试上证综指
        symbols = {'000001.SH': '上证综指'}
    
    all_results = []
    
    for symbol, name in symbols.items():
        print(f"\n{'#'*80}")
        print(f"# 测试指数: {name} ({symbol})")
        print(f"{'#'*80}")
        
        for window_strategy, step, ma_window in test_configs:
            result = run_test(
                symbol, name, args.start, args.end,
                window_strategy, step, ma_window, args.output
            )
            
            if result:
                all_results.append(result)
    
    # 生成对比报告
    generate_report(all_results, args.output)
    
    print("\n" + "="*80)
    print("测试完成!")
    print("="*80)


if __name__ == "__main__":
    main()
