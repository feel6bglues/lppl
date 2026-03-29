#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LPPL算法有效性验证程序

查找8个指数历年日线最高点，对每个最高点前后运行LPPL拟合，验证算法预警效果
"""

import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.optimize import differential_evolution

warnings.filterwarnings("ignore")
CPU_CORES = max(1, (os.cpu_count() or 4) - 2)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# LPPL模型函数
def lppl_func(t, tc, m, w, a, b, c, phi):
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau ** m) + c * (tau ** m) * np.cos(w * np.log(tau) + phi)

def cost_function(params, t, log_prices):
    tc, m, w, a, b, c, phi = params
    prediction = lppl_func(t, tc, m, w, a, b, c, phi)
    residuals = prediction - log_prices
    return np.sum(residuals ** 2)

def fit_window_lppl(close_prices, window_size):
    """使用lppl.py原参数拟合单个窗口"""
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
        
        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - np.mean(log_price_data)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        # Danger信号条件
        is_danger = (0.1 < m < 0.9) and (6 < w < 13) and (days_to_crash < 20) and (r_squared > 0.5)
        
        return {
            'window_size': window_size,
            'rmse': rmse,
            'r_squared': r_squared,
            'm': m,
            'w': w,
            'days_to_crash': days_to_crash,
            'is_danger': bool(is_danger),
        }
    except Exception:
        return None

def scan_single_date(close_prices, idx, window_range):
    """扫描单个日期的所有窗口"""
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
    return min(results, key=lambda x: x['rmse'])

def find_local_highs(df, min_gap=60, min_drop_pct=0.05):
    """
    查找局部最高点
    
    Args:
        df: 包含date和close的DataFrame
        min_gap: 两个高点之间的最小间隔天数
        min_drop_pct: 高点后最小跌幅百分比
    
    Returns:
        list of dict: 高点信息
    """
    highs = []
    close = df['close'].values
    dates = df['date'].values
    
    # 使用滑动窗口找局部最高点
    window = 20  # 20天窗口
    
    for i in range(window, len(close) - window):
        # 检查是否是局部最高点
        local_max = np.max(close[i-window:i+window+1])
        if close[i] == local_max:
            # 检查后续是否下跌
            future_window = min(60, len(close) - i - 1)
            if future_window > 0:
                future_min = np.min(close[i+1:i+1+future_window])
                drop_pct = (close[i] - future_min) / close[i]
                
                if drop_pct >= min_drop_pct:
                    # 检查与已有高点的距离
                    too_close = False
                    for h in highs:
                        if abs(i - h['idx']) < min_gap:
                            too_close = True
                            break
                    
                    if not too_close:
                        highs.append({
                            'idx': i,
                            'date': dates[i],
                            'price': close[i],
                            'drop_pct': drop_pct
                        })
    
    return highs

def analyze_peak(df, peak_idx, window_range, scan_step=2, ma_window=5):
    """
    分析单个高点前后的LPPL信号
    
    Args:
        df: DataFrame with date and close
        peak_idx: 高点索引
        window_range: LPPL窗口范围
        scan_step: 扫描步长
        ma_window: 移动平均窗口
    
    Returns:
        dict: 分析结果
    """
    close_prices = df['close'].values
    
    # 扫描范围: 高点前120天到高点
    start_idx = max(max(window_range) + 5, peak_idx - 120)
    end_idx = peak_idx
    
    if start_idx >= end_idx:
        return None
    
    indices = list(range(start_idx, end_idx + 1, scan_step))
    
    results = Parallel(n_jobs=CPU_CORES, backend='loky', verbose=0)(
        delayed(scan_single_date)(close_prices, idx, window_range)
        for idx in indices
    )
    results = [r for r in results if r is not None]
    
    if len(results) == 0:
        return None
    
    for r in results:
        r['date'] = df.iloc[r['idx']]['date']
        r['price'] = df.iloc[r['idx']]['close']
        r['days_to_peak'] = r['idx'] - peak_idx
    
    trend_df = pd.DataFrame(results)
    trend_df = trend_df.sort_values('idx').reset_index(drop=True)
    
    # 计算趋势得分
    trend_df['r2_ma'] = trend_df['r_squared'].rolling(window=ma_window, min_periods=1).mean()
    trend_df['danger_count'] = trend_df['is_danger'].rolling(window=ma_window, min_periods=1).sum()
    trend_df['trend_score'] = trend_df['r2_ma'] * (trend_df['danger_count'] / ma_window)
    
    # 分析危险信号
    danger_signals = trend_df[trend_df['is_danger']]
    danger_before_peak = danger_signals[danger_signals['days_to_peak'] <= 0]
    
    first_danger = danger_before_peak.sort_values('date').iloc[0] if len(danger_before_peak) > 0 else None
    
    # 最高趋势得分
    before_peak = trend_df[trend_df['days_to_peak'] <= 0]
    if len(before_peak) > 0 and len(before_peak[before_peak['trend_score'] > 0]) > 0:
        best_trend = before_peak.loc[before_peak['trend_score'].idxmax()]
    else:
        best_trend = None
    
    peak_date = df.iloc[peak_idx]['date']
    peak_price = df.iloc[peak_idx]['close']
    
    return {
        'peak_idx': peak_idx,
        'peak_date': peak_date if isinstance(peak_date, str) else peak_date.strftime('%Y-%m-%d'),
        'peak_price': peak_price,
        'total_scans': len(results),
        'danger_count': len(danger_signals),
        'danger_before_peak': len(danger_before_peak),
        'first_danger_days': first_danger['days_to_peak'] if first_danger is not None else None,
        'first_danger_r2': first_danger['r_squared'] if first_danger is not None else None,
        'first_danger_m': first_danger['m'] if first_danger is not None else None,
        'first_danger_w': first_danger['w'] if first_danger is not None else None,
        'best_trend_days': best_trend['days_to_peak'] if best_trend is not None else None,
        'best_trend_score': best_trend['trend_score'] if best_trend is not None else None,
        'best_trend_r2': best_trend['r_squared'] if best_trend is not None else None,
        'detected': len(danger_before_peak) > 0,
    }

def main():
    from src.data.manager import DataManager
    
    # 配置
    WINDOW_RANGE = list(range(40, 100, 20))  # 40,60,80天 - 减少窗口数量
    SCAN_STEP = 5
    MA_WINDOW = 5
    MIN_PEAK_DROP = 0.10  # 高点后至少下跌10%才算有效高点
    MIN_PEAK_GAP = 120    # 两个高点之间至少间隔120天
    
    SYMBOLS = {
        '000001.SH': '上证综指',
        '399001.SZ': '深证成指',
        '399006.SZ': '创业板指',
        '000016.SH': '上证50',
        '000300.SH': '沪深300',
        '000905.SH': '中证500',
        '000852.SH': '中证1000',
        '932000.SH': '中证2000',
    }
    
    dm = DataManager()
    os.makedirs('output/MA', exist_ok=True)
    
    print("="*100)
    print("LPPL算法有效性验证")
    print("="*100)
    print("参数配置:")
    print(f"  窗口范围: {WINDOW_RANGE[0]}-{WINDOW_RANGE[-1]}天")
    print(f"  扫描步长: {SCAN_STEP}天")
    print(f"  移动平均: {MA_WINDOW}天")
    print(f"  最小跌幅: {MIN_PEAK_DROP*100:.0f}%")
    print(f"  最小间隔: {MIN_PEAK_GAP}天")
    
    all_results = []
    
    for symbol, name in SYMBOLS.items():
        print(f"\n{'='*80}")
        print(f"{name} ({symbol})")
        print(f"{'='*80}")
        
        df = dm.get_data(symbol)
        if df is None or df.empty:
            print("  无数据")
            continue
        
        df = df.sort_values('date').reset_index(drop=True)
        df['date'] = pd.to_datetime(df['date'])
        
        print(f"  数据: {len(df)}天 ({df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')})")
        
        # 查找局部最高点
        highs = find_local_highs(df, min_gap=MIN_PEAK_GAP, min_drop_pct=MIN_PEAK_DROP)
        
        print(f"  找到 {len(highs)} 个有效高点:")
        for h in highs:
            h['date'] = pd.to_datetime(h['date'])
            print(f"    {h['date'].strftime('%Y-%m-%d')}: {h['price']:.2f} (下跌{h['drop_pct']*100:.1f}%)")
        
        # 限制分析数量，只分析跌幅最大的前10个高点
        highs_sorted = sorted(highs, key=lambda x: x['drop_pct'], reverse=True)[:10]
        print(f"\n  分析跌幅最大的 {len(highs_sorted)} 个高点:")
        
        # 分析每个高点
        for peak in highs_sorted:
            print(f"\n  分析高点: {peak['date'].strftime('%Y-%m-%d')} ({peak['price']:.2f})")
            
            result = analyze_peak(df, peak['idx'], WINDOW_RANGE, SCAN_STEP, MA_WINDOW)
            
            if result is not None:
                result['symbol'] = symbol
                result['name'] = name
                result['drop_pct'] = peak['drop_pct']
                all_results.append(result)
                
                if result['detected']:
                    print(f"    ✅ 检测到预警: {result['first_danger_days']}天前, R²={result['first_danger_r2']:.3f}")
                else:
                    print("    ❌ 未检测到预警")
            else:
                print("    ⚠️ 分析失败")
    
    # 保存结果
    if all_results:
        results_df = pd.DataFrame(all_results)
        results_df.to_csv('output/MA/peak_verification.csv', index=False)
        
        print("\n" + "="*100)
        print("验证结果汇总")
        print("="*100)
        
        total = len(results_df)
        detected = results_df['detected'].sum()
        detection_rate = detected / total * 100 if total > 0 else 0
        
        print(f"\n总高点数: {total}")
        print(f"检测到预警: {detected} ({detection_rate:.1f}%)")
        
        # 按指数统计
        print(f"\n{'指数':<10} {'高点数':>6} {'检测数':>6} {'检测率':>8} {'平均天数':>10}")
        print("-"*50)
        
        for name in results_df['name'].unique():
            idx_data = results_df[results_df['name'] == name]
            idx_total = len(idx_data)
            idx_detected = idx_data['detected'].sum()
            idx_rate = idx_detected / idx_total * 100 if idx_total > 0 else 0
            
            detected_data = idx_data[idx_data['detected']]
            avg_days = detected_data['first_danger_days'].mean() if len(detected_data) > 0 else np.nan
            
            days_str = f"{avg_days:.0f}d" if pd.notna(avg_days) else "N/A"
            print(f"{name:<10} {idx_total:>6} {idx_detected:>6} {idx_rate:>7.1f}% {days_str:>10}")
        
        # 高置信度案例
        high_conf = results_df[(results_df['detected']) & (results_df['first_danger_r2'] > 0.8)]
        print(f"\n高置信度案例 (R²>0.8): {len(high_conf)}个")
        
        if len(high_conf) > 0:
            print(f"\n{'指数':<10} {'高点日期':<12} {'高点价格':>10} {'预警天数':>10} {'R²':>6} {'m':>6} {'w':>6}")
            print("-"*70)
            for _, row in high_conf.sort_values('first_danger_r2', ascending=False).iterrows():
                print(f"{row['name']:<10} {row['peak_date']:<12} {row['peak_price']:>10.2f} {row['first_danger_days']:>10.0f} {row['first_danger_r2']:>6.3f} {row['first_danger_m']:>6.3f} {row['first_danger_w']:>6.3f}")
        
        print("\n结果已保存到 output/MA/peak_verification.csv")

if __name__ == "__main__":
    main()
