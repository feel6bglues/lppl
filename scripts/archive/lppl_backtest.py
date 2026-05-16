# -*- coding: utf-8 -*-
"""
LPPL 回测分析程序 [LEGACY - 向后兼容]

⚠️ 警告: 此脚本使用独立实现，不依赖 src/ 模块。
新项目请使用 src/cli/ 下的正式入口。

使用方法:
    python lppl_backtest.py --all
    python lppl_backtest.py --symbol sh000001
"""

import warnings

warnings.warn(
    "lppl_backtest.py is deprecated. Use src.cli.lppl_verify_v2 instead.",
    DeprecationWarning,
    stacklevel=2,
)

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use('Agg')
import os
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
from tqdm import tqdm

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CPU_CORES = os.cpu_count() or 4
print(f"检测到 CPU 核心数: {CPU_CORES}, 使用单线程+内部并行 (differential_evolution workers=-1)")

LPPL_CODE_LIST = [
    ("000001.SH", "sh000001", "上证综指"),
    ("399001.SZ", "sz399001", "深证成指"),
    ("399006.SZ", "sz399006", "创业板指"),
    ("000016.SH", "sh000016", "上证50"),
    ("000300.SH", "sh000300", "沪深300"),
    ("000905.SH", "sh000905", "中证500"),
    ("000852.SH", "sh000852", "中证1000"),
    ("932000.SH", "csindex2000", "中证2000"),
]

WINDOW_RANGE = list(range(50, 300, 10))


def run_backtest_parallel(symbol_lppl, symbol_name, start_date="2005-01-01", 
                          window_sizes=None, step=5, n_workers=CPU_CORES):
    """
    使用 joblib 并行回测 - 支持多窗口
    """
    from src.lppl_fit import fit_single_point

    from src.data.manager import DataManager
    
    if window_sizes is None:
        window_sizes = WINDOW_RANGE
    
    print(f"\n{'='*60}")
    print(f"处理: {symbol_name} ({symbol_lppl})")
    print(f"窗口范围: {min(window_sizes)}-{max(window_sizes)}天, 共{len(window_sizes)}个窗口")
    print(f"{'='*60}")
    
    dm = DataManager()
    df = dm.get_data(symbol_lppl)
    
    if df is None or df.empty:
        print(f"无法获取 {symbol_name} 数据")
        return None
    
    df = df[['date', 'close']].copy()
    df = df.sort_values('date').reset_index(drop=True)
    df = df[df['date'] >= pd.to_datetime(start_date)].reset_index(drop=True)
    
    max_window = max(window_sizes)
    if len(df) < max_window:
        print(f"数据不足: {len(df)} < {max_window}")
        return None
    
    print(f"数据: {len(df)} 个交易日, {df['date'].min().date()} ~ {df['date'].max().date()}")
    
    close_prices = df['close'].values
    
    all_data_list = []
    for window_size in window_sizes:
        if len(df) >= window_size:
            indices = list(range(window_size, len(df), step))
            for idx in indices:
                all_data_list.append((idx, close_prices, window_size))
    
    print(f"待拟合: {len(all_data_list)} 个点 ({len(window_sizes)}窗口 x ~{len(all_data_list)//len(window_sizes)}点), 使用 {n_workers} 线程")
    
    from joblib import Parallel, delayed
    results = Parallel(n_jobs=n_workers, backend='loky', verbose=0)(
        delayed(fit_single_point)(data) for data in tqdm(all_data_list, desc=f"{symbol_name[:4]}")
    )
    
    results = [r for r in results if r is not None]
    
    if results:
        result_df = pd.DataFrame(results)
        result_df['date'] = result_df['idx'].apply(lambda x: df.iloc[x]['date'])
        result_df['price'] = result_df['idx'].apply(lambda x: df.iloc[x]['close'])
        result_df = result_df.drop(columns=['idx'])
        result_df = result_df.sort_values('date').reset_index(drop=True)
        return result_df
    
    return None


def run_all_backtests(start_date="2005-01-01", window_sizes=None, step=5):
    """运行所有指数的回测"""
    if window_sizes is None:
        window_sizes = WINDOW_RANGE
    
    all_results = {}
    
    for symbol_lppl, symbol_tdx, symbol_name in LPPL_CODE_LIST:
        result = run_backtest_parallel(symbol_lppl, symbol_name, start_date, window_sizes, step, CPU_CORES)
        if result is not None:
            all_results[symbol_name] = result
            print(f"  完成: {len(result)} 条结果")
    
    return all_results


def plot_all_results(all_results, output_dir="output"):
    """绘制所有指数的回测结果"""
    os.makedirs(output_dir, exist_ok=True)
    
    n_indices = len(all_results)
    if n_indices == 0:
        print("没有可绘制的数据")
        return
    
    fig, axes = plt.subplots(n_indices + 1, 1, figsize=(16, 4 * (n_indices + 1)))
    if n_indices == 0:
        axes = [axes]
    elif n_indices == 1:
        axes = [axes[0], axes[1]]
    
    colors = plt.cm.tab10(np.linspace(0, 1, n_indices))
    
    for idx, (name, df) in enumerate(all_results.items()):
        ax = axes[idx]
        ax.plot(df['date'], df['price'], color='black', lw=0.8, label='Price')
        
        danger = df[df['is_danger']]
        if not danger.empty:
            ax.scatter(danger['date'], danger['price'], color='red', s=10, 
                      label=f'Danger ({len(danger)})', zorder=5)
        
        ax.set_title(f"{name}", fontsize=12, fontweight='bold')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_ylabel('Price')
        
        for date in ['2007-10-16', '2015-06-12']:
            try:
                ax.axvline(pd.Timestamp(date), color='orange', linestyle=':', alpha=0.5)
            except Exception:
                pass
    
    ax_summary = axes[-1]
    for idx, (name, df) in enumerate(all_results.items()):
        danger = df[df['is_danger']]
        if not danger.empty:
            ax_summary.scatter(danger['date'], [idx] * len(danger), 
                             color=colors[idx], s=20, alpha=0.7, label=name)
        ax_summary.plot(df['date'], [idx] * len(df), color=colors[idx], lw=0.5, alpha=0.3)
    
    ax_summary.set_yticks(range(len(all_results)))
    ax_summary.set_yticklabels(list(all_results.keys()))
    ax_summary.set_title("危险信号时间线对比", fontsize=12)
    ax_summary.grid(True, alpha=0.3, axis='x')
    ax_summary.set_xlabel('Date')
    
    for date in ['2007-10-16', '2015-06-12', '2024-03-01']:
        try:
            ax_summary.axvline(pd.Timestamp(date), color='orange', linestyle=':', alpha=0.5)
        except Exception:
            pass
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, "lppl_backtest_all.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n图表已保存: {output_path}")
    plt.close()


def print_statistics(all_results):
    """打印统计信息"""
    print(f"\n{'='*80}")
    print("回测统计汇总")
    print(f"{'='*80}")
    
    summary_data = []
    
    for name, df in all_results.items():
        danger = df[df['is_danger']]
        total = len(df)
        danger_count = len(danger)
        ratio = danger_count / total * 100 if total > 0 else 0
        
        summary_data.append({
            '指数': name,
            '总扫描': total,
            '危险信号': danger_count,
            '比例(%)': f"{ratio:.1f}%"
        })
        
        print(f"\n{name}:")
        print(f"  总扫描: {total}, 危险信号: {danger_count} ({ratio:.1f}%)")
        
        if not danger.empty:
            danger_copy = danger.copy()
            danger_copy['year'] = pd.to_datetime(danger_copy['date']).dt.year
            yearly = danger_copy.groupby('year').size()
            print(f"  按年分布: {dict(yearly)}")
    
    summary_df = pd.DataFrame(summary_data)
    print(f"\n{'='*80}")
    print("汇总表:")
    print(summary_df.to_string(index=False))
    print(f"{'='*80}")
    
    return summary_df


def save_report_to_markdown(all_results, output_path="lppl_backtest_report.md", window=5000, step=5):
    """保存回测报告到Markdown文件"""
    from datetime import datetime
    
    lines = []
    lines.append("# LPPL 回测分析报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**分析窗口**: {window}天")
    lines.append(f"**扫描步长**: {step}天")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    lines.append("## 一、汇总统计")
    lines.append("")
    lines.append("| 指数 | 总扫描 | 危险信号 | 比例 |")
    lines.append("|:-----|-------:|--------:|-----:|")
    
    summary_data = []
    for name, df in all_results.items():
        danger = df[df['is_danger']]
        total = len(df)
        danger_count = len(danger)
        ratio = danger_count / total * 100 if total > 0 else 0
        summary_data.append({
            '指数': name,
            '总扫描': total,
            '危险信号': danger_count,
            '比例': f"{ratio:.1f}%"
        })
        lines.append(f"| {name} | {total} | {danger_count} | {ratio:.1f}% |")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、各指数详细分析")
    lines.append("")
    
    for name, df in all_results.items():
        danger = df[df['is_danger']]
        total = len(df)
        danger_count = len(danger)
        ratio = danger_count / total * 100 if total > 0 else 0
        
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- **总扫描次数**: {total}")
        lines.append(f"- **危险信号次数**: {danger_count}")
        lines.append(f"- **信号比例**: {ratio:.1f}%")
        lines.append("")
        
        if not danger.empty:
            danger_copy = danger.copy()
            danger_copy['year'] = pd.to_datetime(danger_copy['date']).dt.year
            yearly = danger_copy.groupby('year').size().sort_index()
            
            lines.append("**按年分布**:")
            lines.append("")
            lines.append("| 年份 | 信号数 |")
            lines.append("|:----:|-------:|")
            for year, count in yearly.items():
                lines.append(f"| {year} | {count} |")
            
            lines.append("")
            lines.append("**最近危险信号** (前10条):")
            lines.append("")
            lines.append("| 日期 | 收盘价 | 预测崩盘天数 | m | w |")
            lines.append("|:-----|-------:|------------:|---:|---:|")
            
            danger_sorted = danger.sort_values('date', ascending=False).head(10)
            for _, row in danger_sorted.iterrows():
                date_str = pd.to_datetime(row['date']).strftime('%Y-%m-%d')
                days = row['days_to_crash'] if pd.notna(row['days_to_crash']) else 'N/A'
                lines.append(f"| {date_str} | {row['price']:.2f} | {days} | {row['m']:.3f} | {row['w']:.3f} |")
        
        lines.append("")
        lines.append("---")
        lines.append("")
    
    lines.append("## 三、关键时间节点分析")
    lines.append("")
    lines.append("### 2007年大牛市顶部 (2007-10-16)")
    lines.append("")
    
    for name, df in all_results.items():
        danger = df[df['is_danger']]
        if not danger.empty:
            danger_2007 = danger[(pd.to_datetime(danger['date']) >= '2007-09-01') & 
                                   (pd.to_datetime(danger['date']) <= '2007-12-31')]
            if len(danger_2007) > 0:
                lines.append(f"- **{name}**: {len(danger_2007)} 次信号")
    
    lines.append("")
    lines.append("### 2015年大牛市顶部 (2015-06-12)")
    lines.append("")
    
    for name, df in all_results.items():
        danger = df[df['is_danger']]
        if not danger.empty:
            danger_2015 = danger[(pd.to_datetime(danger['date']) >= '2015-05-01') & 
                                   (pd.to_datetime(danger['date']) <= '2015-08-31')]
            if len(danger_2015) > 0:
                lines.append(f"- **{name}**: {len(danger_2015)} 次信号")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 四、AI Agent Context Block")
    lines.append("")
    lines.append("```markdown")
    lines.append("# LPPL Backtest Summary")
    lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("| Index | Total Scans | Danger Signals | Ratio |")
    lines.append("|:------|------------:|---------------:|:-----:|")
    
    for item in summary_data:
        lines.append(f"| {item['指数']} | {item['总扫描']} | {item['危险信号']} | {item['比例']} |")
    
    lines.append("```")
    
    content = "\n".join(lines)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n报告已保存: {output_path}")
    return output_path


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='LPPL 回测分析 (多线程版)')
    parser.add_argument('--symbol', '-s', default=None,
                        help='LPPL指数代码，如 000001.SH')
    parser.add_argument('--start', '-d', default='2005-01-01',
                        help='回测开始日期')
    parser.add_argument('--window', '-w', type=int, default=None,
                        help='单个窗口大小 (默认使用50-290短期窗口)')
    parser.add_argument('--windows', '-wlist', type=str, default=None,
                        help='窗口列表，格式: 50,60,70 或 50-290-10')
    parser.add_argument('--step', type=int, default=5,
                        help='步长')
    parser.add_argument('--workers', type=int, default=CPU_CORES,
                        help=f'线程数 (默认: {CPU_CORES})')
    parser.add_argument('--all', '-a', action='store_true',
                        help='回测所有8个指数')
    parser.add_argument('--output', '-o', default='output',
                        help='输出目录')
    
    args = parser.parse_args()
    
    window_sizes = None
    if args.windows:
        if '-' in args.windows:
            parts = args.windows.split('-')
            if len(parts) == 3:
                start, end, step = int(parts[0]), int(parts[1]), int(parts[2])
                window_sizes = list(range(start, end + 1, step))
        else:
            window_sizes = [int(w) for w in args.windows.split(',')]
    elif args.window:
        window_sizes = [args.window]
    else:
        window_sizes = WINDOW_RANGE
    
    print(f"\n{'='*60}")
    print("LPPL 回测分析程序")
    print(f"{'='*60}")
    print(f"开始日期: {args.start}")
    print(f"窗口范围: {min(window_sizes)}-{max(window_sizes)}天, 共{len(window_sizes)}个窗口")
    print(f"步长: {args.step} 天")
    print(f"线程数: {args.workers}")
    print(f"{'='*60}\n")
    
    if args.all or args.symbol is None:
        print("回测所有8个指数...")
        all_results = run_all_backtests(args.start, window_sizes, args.step)
        plot_all_results(all_results, args.output)
        print_statistics(all_results)
        save_report_to_markdown(all_results, "lppl_backtest_report.md", f"{min(window_sizes)}-{max(window_sizes)}", args.step)
    else:
        symbol_lppl = args.symbol
        symbol_name = None
        
        for lp, _, name in LPPL_CODE_LIST:
            if lp == symbol_lppl:
                symbol_lppl = lp
                symbol_name = name
                break
        
        if symbol_name is None:
            print(f"未找到指数: {args.symbol}")
            return
        
        result = run_backtest_parallel(symbol_lppl, symbol_name, args.start, window_sizes, args.step, args.workers)
        
        if result is not None:
            os.makedirs(args.output, exist_ok=True)
            plot_all_results({symbol_name: result}, args.output)
            
            danger = result[result['is_danger']]
            print(f"\n统计: {len(result)} 次扫描, {len(danger)} 次危险信号 ({len(danger)/len(result)*100:.1f}%)")
            
            if not danger.empty:
                print("\n危险信号详情 (前10条):")
                print(danger[['date', 'price', 'days_to_crash', 'm', 'w']].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
