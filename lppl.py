# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution
from datetime import timedelta, datetime
import logging
import time
import os
from tabulate import tabulate
from colorama import Fore, Style, init

init(autoreset=True)

INDICES = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
}

WINDOW_RANGE = list(range(50, 300, 10)) + list(range(300, 600, 20)) + list(range(600, 1200, 50)) 

def lppl_func(t, tc, m, w, a, b, c, phi):
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau ** m) + c * (tau ** m) * np.cos(w * np.log(tau) + phi)

def cost_function(params, t, log_prices):
    tc, m, w, a, b, c, phi = params
    prediction = lppl_func(t, tc, m, w, a, b, c, phi)
    residuals = prediction - log_prices
    return np.sum(residuals ** 2)

class LPPLScanner:
    def __init__(self, data_dir="data/daily"):
        self.data_dir = data_dir

    def fetch_data(self, symbol):
        try:
            file_path = os.path.join(self.data_dir, f"{symbol}.parquet")
            
            if not os.path.exists(file_path):
                print(f"{Fore.RED}数据文件不存在: {file_path}{Style.RESET_ALL}")
                return None
            
            df = pd.read_parquet(file_path)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            
            print(f"{Fore.GREEN}成功加载数据 (最新日期: {df['date'].iloc[-1].date()}, 数据长度: {len(df)}, 路径: {file_path}){Style.RESET_ALL}")
            return df
        except Exception as e:
            print(f"{Fore.RED}失败: {e}{Style.RESET_ALL}")
            return None

    def fit_window(self, df_window):
        t_data = np.arange(len(df_window))
        price_data = df_window['close'].values
        log_price_data = np.log(price_data)
        
        current_t = len(df_window)
        
        bounds = [
            (current_t + 1, current_t + 100),
            (0.1, 0.9),
            (6, 13),
            (np.min(log_price_data), np.max(log_price_data) * 1.1),
            (-20, 20),
            (-20, 20),
            (0, 2 * np.pi)
        ]

        result = differential_evolution(
            cost_function, bounds, args=(t_data, log_price_data),
            strategy='best1bin', maxiter=100, popsize=15, tol=0.05, seed=42, workers=1
        )

        if not result.success:
            return None

        fitted_curve = lppl_func(t_data, *result.x)
        mse = np.mean((fitted_curve - log_price_data) ** 2)
        rmse = np.sqrt(mse)
        
        return {
            "params": result.x,
            "rmse": rmse,
            "last_date": df_window['date'].iloc[-1]
        }

    def scan_index(self, symbol, name, full_df):
        results = {
            "short": {"window": 0, "result": None, "rmse": float('inf')},
            "medium": {"window": 0, "result": None, "rmse": float('inf')},
            "long": {"window": 0, "result": None, "rmse": float('inf')}
        }
        
        print(f"  > 开始扫描 {name} ({symbol}): ", end="", flush=True)

        for window in WINDOW_RANGE:
            if len(full_df) < window:
                continue
                
            df_subset = full_df.tail(window).copy().reset_index(drop=True)
            
            res = self.fit_window(df_subset)
            
            if res:
                print(".", end="", flush=True)
                
                if window < 200:
                    if res["rmse"] < results["short"]["rmse"]:
                        results["short"]["window"] = window
                        results["short"]["result"] = res
                        results["short"]["rmse"] = res["rmse"]
                elif 200 <= window <= 500:
                    if res["rmse"] < results["medium"]["rmse"]:
                        results["medium"]["window"] = window
                        results["medium"]["result"] = res
                        results["medium"]["rmse"] = res["rmse"]
                else:
                    if res["rmse"] < results["long"]["rmse"]:
                        results["long"]["window"] = window
                        results["long"]["result"] = res
                        results["long"]["rmse"] = res["rmse"]
            else:
                print("x", end="", flush=True)

        print(f" 完成")
        
        output_results = []
        if results["short"]["result"]:
            output_results.append(self._format_output(symbol, name, results["short"]["window"], results["short"]["result"], "短期"))
        if results["medium"]["result"]:
            output_results.append(self._format_output(symbol, name, results["medium"]["window"], results["medium"]["result"], "中期"))
        if results["long"]["result"]:
            output_results.append(self._format_output(symbol, name, results["long"]["window"], results["long"]["result"], "长期"))
        
        return output_results

    def _format_output(self, symbol, name, window, res, time_span=""):
        tc, m, w, a, b, c, phi = res["params"]
        
        days_left = tc - window
        crash_date = res["last_date"] + timedelta(days=int(days_left))
        
        risk = "低"
        if 0.1 < m < 0.9 and 6 < w < 13:
            if days_left < 20: risk = "极高 (Danger)"
            elif days_left < 60: risk = "高 (Warning)"
            else: risk = "中 (Watch)"
        else:
            risk = "无效模型 (假信号)"

        return [
            name,
            symbol,
            time_span,
            window,
            f"{res['rmse']:.5f}",
            f"{m:.3f}",
            f"{w:.3f}",
            f"{days_left:.1f} 天",
            crash_date.strftime('%Y-%m-%d'),
            risk
        ]

def main():
    print(f"{Fore.CYAN}{'='*60}")
    print(f"   LPPL 中国主要指数全市场扫描系统")
    print(f"   扫描窗口范围: {list(WINDOW_RANGE)} 天")
    print(f"{'='*60}{Style.RESET_ALL}\n")
    
    scanner = LPPLScanner()
    report_data = []
    
    for symbol, name in INDICES.items():
        df = scanner.fetch_data(symbol)
        if df is None or df.empty:
            continue
            
        results = scanner.scan_index(symbol, name, df)
        if results:
            report_data.extend(results)
        
        print("-" * 30)

    headers = ["指数名称", "代码", "时间跨度", "最佳窗口(天)", "拟合误差(RMSE)", "m (加速)", "w (震荡)", "距离崩盘", "预测崩盘日", "风险等级"]
    
    print(f"\n{Fore.YELLOW}>>> 扫描结果汇总 (按照 RMSE 从小到大排序){Style.RESET_ALL}")
    print(tabulate(report_data, headers=headers, tablefmt="grid"))
    
    print(f"\n{Fore.CYAN}结果说明:{Style.RESET_ALL}")
    print("1. [最佳窗口]: 指该指数在过去多少天的数据上拟合 LPPL 模型效果最好。")
    print("2. [拟合误差]: 值越小说明模型预测曲线和实际 K 线越吻合，结果越可靠。")
    print("3. [m]: 取值在 0.1-0.9 之间，越接近 0.5 效果越好。")
    print("4. [w]: 取值在 6-13 之间，越接近 8 效果越好。")

if __name__ == "__main__":
    main()
