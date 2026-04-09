#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LPPL 算法验证程序 V2 (专业修正版)

修正内容：
1. 删除了重复定义的 print_summary 函数
2. 重构了 Ensemble 模式的窗口矩阵 (从 3 个窗口扩大到 12 个窗口)
3. 强制使用差分进化算法(DE)作为全局优化器

Ensemble 模式参数 (对齐 target.md):
- 窗口范围: 40-150天 (共12个窗口)
- 共识阈值: 25% (12窗口中至少3个达成共识)
- 强制使用 DE 优化器

使用方法:
    python lppl_verify_v2.py --all
    python lppl_verify_v2.py --symbol 000001.SH
    python lppl_verify_v2.py --symbol 000001.SH --ensemble
"""

import argparse
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# 添加项目根路径（兼容直接运行 src/cli/*.py）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 导入引擎模块
from src.config import load_optimal_config, resolve_symbol_params
from src.constants import (
    PLOTS_OUTPUT_DIR,
    RAW_OUTPUT_DIR,
    REPORTS_OUTPUT_DIR,
    SUMMARY_OUTPUT_DIR,
    VERIFY_OUTPUT_DIR,
)
from src.lppl_engine import (
    LPPLConfig,
    analyze_peak,
    analyze_peak_ensemble,
    find_local_highs,
)
from src.reporting import PlotGenerator, VerificationReportGenerator

# CPU核心数
CPU_CORES = max(1, (os.cpu_count() or 4) - 2)

# 指数配置 (与verify_lppl.py一致)
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


def get_mode_metadata(use_ensemble: bool) -> dict:
    if use_ensemble:
        return {
            "mode_slug": "ensemble",
            "mode_label": "Ensemble 多窗口共识",
            "window_label": "40-150天 (12窗口)",
            "report_title": "LPPL 算法验证报告 V2 - Ensemble 模式",
            "results_filename": "peak_verification_v2_ensemble.csv",
            "report_filename": "verification_report_v2_ensemble.md",
        }

    return {
        "mode_slug": "single_window",
        "mode_label": "单窗口独立",
        "window_label": "40-80天 (3窗口)",
        "report_title": "LPPL 算法验证报告 V2 - 单窗口模式",
        "results_filename": "peak_verification_v2_single_window.csv",
        "report_filename": "verification_report_v2_single_window.md",
    }


def resolve_output_dirs(base_output_dir: str = None) -> dict:
    if base_output_dir:
        verify_dir = base_output_dir
        return {
            "base": verify_dir,
            "raw": os.path.join(verify_dir, "raw"),
            "plots": os.path.join(verify_dir, "plots"),
            "reports": os.path.join(verify_dir, "reports"),
            "summary": os.path.join(verify_dir, "summary"),
        }

    return {
        "base": VERIFY_OUTPUT_DIR,
        "raw": RAW_OUTPUT_DIR,
        "plots": PLOTS_OUTPUT_DIR,
        "reports": REPORTS_OUTPUT_DIR,
        "summary": SUMMARY_OUTPUT_DIR,
    }


def ensure_output_dirs(output_dirs: dict) -> None:
    for path in output_dirs.values():
        os.makedirs(path, exist_ok=True)


def create_config(use_ensemble: bool = False) -> LPPLConfig:
    """
    创建 LPPL 配置 - 对齐 target.md 参数
    
    真正的 Ensemble 需要足够的样本量。
    使用 40 到 150 天，步长 10 天，共计 12 个观察窗口。
    
    Args:
        use_ensemble: 是否使用 Ensemble 模式
    
    Returns:
        LPPLConfig 对象
    """
    # 12个窗口: 40,50,60,70,80,90,100,110,120,130,140,150
    w_range = list(range(40, 160, 10)) if use_ensemble else list(range(40, 100, 20))

    return LPPLConfig(
        window_range=w_range,
        optimizer='de',  # 强制使用差分进化算法(DE)
        maxiter=100,     # 增加迭代次数
        popsize=15,     # 保持足够种群
        tol=0.05,       # 适度容忍
        m_bounds=(0.1, 0.9),
        w_bounds=(6.0, 13.0),
        tc_bound=(1, 60),
        r2_threshold=0.6 if use_ensemble else 0.5,
        danger_r2_offset=0.0,
        danger_days=20,
        warning_days=60,
        # 12个窗口中，至少需要3个(25%)达成共识，才能触发信号
        consensus_threshold=0.25 if use_ensemble else 0.0,
        n_workers=CPU_CORES,
    )


def run_verification(symbol: str, name: str,
                    use_ensemble: bool = False,
                    scan_step: int = 5,
                    ma_window: int = 5,
                    min_peak_drop: float = 0.10,
                    min_peak_gap: int = 120,
                    max_peaks: int = 10,
                    config_override: dict = None,
                    param_source: str = "default_cli"):
    """
    运行单个指数的验证
    
    Args:
        symbol: 指数代码
        name: 指数名称
        use_ensemble: 是否使用 Ensemble 模式 (12窗口多窗口共识)
        scan_step: 扫描步长
        ma_window: 移动平均窗口
        min_peak_drop: 最小跌幅
        min_peak_gap: 最小间隔
        max_peaks: 最多分析的高点数
    
    Returns:
        list of dict: 验证结果
    """
    from src.data.manager import DataManager
    mode_meta = get_mode_metadata(use_ensemble)

    print(f"\n{'='*80}")
    print(f"{name} ({symbol}) | 模式: {mode_meta['mode_label']}")
    print(f"{'='*80}")

    # 获取数据
    dm = DataManager()
    df = dm.get_data(symbol)

    if df is None or df.empty:
        print("  无数据")
        return []

    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])

    date_range = f"{df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}"
    print(f"  数据: {len(df)}天 ({date_range})")

    # 查找局部最高点
    highs = find_local_highs(df, min_gap=min_peak_gap, min_drop_pct=min_peak_drop)

    print(f"  找到 {len(highs)} 个有效高点:")
    for h in highs:
        h['date'] = pd.to_datetime(h['date'])
        print(f"    {h['date'].strftime('%Y-%m-%d')}: {h['price']:.2f} (下跌{h['drop_pct']*100:.1f}%)")

    # 限制分析数量
    highs_sorted = sorted(highs, key=lambda x: x['drop_pct'], reverse=True)[:max_peaks]
    print(f"\n  分析跌幅最大的 {len(highs_sorted)} 个高点:")

    # 创建配置
    config = create_config(use_ensemble)
    if config_override:
        config.window_range = list(config_override.get("window_range", config.window_range))
        config.optimizer = str(config_override.get("optimizer", config.optimizer))
        config.r2_threshold = float(config_override.get("r2_threshold", config.r2_threshold))
        config.danger_r2_offset = float(config_override.get("danger_r2_offset", config.danger_r2_offset))
        config.consensus_threshold = float(
            config_override.get("consensus_threshold", config.consensus_threshold)
        )
        config.danger_days = int(config_override.get("danger_days", config.danger_days))
        config.warning_days = int(config_override.get("warning_days", config.warning_days))
        config.watch_days = int(config_override.get("watch_days", config.watch_days))
        scan_step = int(config_override.get("step", scan_step))
        ma_window = int(config_override.get("ma_window", ma_window))
        max_peaks = int(config_override.get("max_peaks", max_peaks))

    print(
        "  生效参数: "
        f"source={param_source}, step={scan_step}, ma={ma_window}, max_peaks={max_peaks}, "
        f"windows={config.window_range[0]}-{config.window_range[-1]} ({len(config.window_range)}), "
        f"optimizer={config.optimizer}, r2={config.r2_threshold:.2f}, "
        f"consensus={config.consensus_threshold:.2f}, danger_days={config.danger_days}"
    )

    # 分析每个高点
    results = []
    for peak in highs_sorted:
        print(f"\n  分析高点: {peak['date'].strftime('%Y-%m-%d')} ({peak['price']:.2f})")

        analyze_func = analyze_peak_ensemble if use_ensemble else analyze_peak
        result = analyze_func(
            df,
            peak['idx'],
            config.window_range,
            scan_step=scan_step,
            ma_window=ma_window,
            config=config
        )

        if result is not None:
            result['symbol'] = symbol
            result['name'] = name
            result['drop_pct'] = peak['drop_pct']
            result["param_source"] = param_source
            result["step"] = scan_step
            result["ma_window"] = ma_window
            result["optimizer"] = config.optimizer
            result["window_count"] = len(config.window_range)
            result["window_min"] = min(config.window_range)
            result["window_max"] = max(config.window_range)
            result["r2_threshold"] = config.r2_threshold
            result["consensus_threshold"] = config.consensus_threshold
            result["danger_days"] = config.danger_days
            results.append(result)

            if result['detected']:
                print(f"    ✅ 检测到预警: {result['first_danger_days']}天前, R²={result['first_danger_r2']:.3f}")
            else:
                print("    ❌ 未检测到预警")
        else:
            print("    ⚠️ 分析失败")

    return results


def print_summary(results_df: pd.DataFrame):
    """打印验证结果汇总"""
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
            m_val = row['first_danger_m'] if pd.notna(row['first_danger_m']) else 0
            w_val = row['first_danger_w'] if pd.notna(row['first_danger_w']) else 0
            print(f"{row['name']:<10} {row['peak_date']:<12} {row['peak_price']:>10.2f} {row['first_danger_days']:>10.0f} {row['first_danger_r2']:>6.3f} {m_val:>6.3f} {w_val:>6.3f}")


def save_results(all_results: list, output_dir: str = "output/MA",
                 use_ensemble: bool = False) -> pd.DataFrame:
    """保存结果到CSV"""
    if not all_results:
        return None

    output_dirs = resolve_output_dirs(output_dir)
    ensure_output_dirs(output_dirs)

    results_df = pd.DataFrame(all_results)
    mode_meta = get_mode_metadata(use_ensemble)

    for result in all_results:
        timeline = result.get("timeline")
        if not timeline:
            continue

        raw_filename = (
            f"raw_{result['symbol'].replace('.', '_')}_"
            f"{mode_meta['mode_slug']}_{result['peak_date']}.parquet"
        )
        raw_path = os.path.join(output_dirs["raw"], raw_filename)
        pd.DataFrame(timeline).to_parquet(raw_path, index=False)

    # 保存原始结果
    output_path = os.path.join(output_dirs["summary"], mode_meta["results_filename"])
    summary_df = results_df.drop(columns=["timeline"], errors="ignore")
    summary_df.to_csv(output_path, index=False)
    print(f"\n结果已保存到 {output_path}")

    return summary_df


def generate_verification_artifacts(
    all_results: list,
    output_dir: str = "output/MA",
    use_ensemble: bool = False,
) -> dict:
    if not all_results:
        return {}

    mode_meta = get_mode_metadata(use_ensemble)
    output_dirs = resolve_output_dirs(output_dir)
    ensure_output_dirs(output_dirs)

    summary_df = save_results(all_results, output_dir, use_ensemble)
    plot_generator = PlotGenerator(output_dirs["plots"])
    report_generator = VerificationReportGenerator(output_dirs["reports"])

    plot_paths = {
        "案例价格时间线图": [],
        "案例 Ensemble 共识图": [],
        "案例预测时间离散图": [],
        "汇总统计图": [],
    }

    for result in all_results:
        timeline = result.get("timeline")
        if not timeline:
            continue

        timeline_df = pd.DataFrame(timeline)
        metadata = {
            "symbol": result["symbol"],
            "name": result["name"],
            "peak_date": result["peak_date"],
            "mode": result.get("mode", mode_meta["mode_slug"]),
            "first_danger_days": result.get("first_danger_days"),
        }

        timeline_plot = plot_generator.generate_price_timeline_plot(timeline_df, metadata)
        plot_paths["案例价格时间线图"].append(timeline_plot)

        if use_ensemble and "consensus_rate" in timeline_df.columns:
            consensus_plot = plot_generator.generate_consensus_plot(
                timeline_df,
                metadata,
                consensus_threshold=create_config(True).consensus_threshold,
            )
            plot_paths["案例 Ensemble 共识图"].append(consensus_plot)

        if use_ensemble and {"predicted_crash_days", "tc_std"}.issubset(timeline_df.columns):
            dispersion_plot = plot_generator.generate_crash_dispersion_plot(timeline_df, metadata)
            plot_paths["案例预测时间离散图"].append(dispersion_plot)

    summary_plot = plot_generator.generate_summary_statistics_plot(summary_df)
    plot_paths["汇总统计图"].append(summary_plot)

    markdown_path = report_generator.generate_markdown_report(
        summary_df=summary_df,
        use_ensemble=use_ensemble,
        plot_paths=plot_paths,
        filename=mode_meta["report_filename"],
    )
    html_filename = mode_meta["report_filename"].replace(".md", ".html")
    html_path = report_generator.generate_html_report(
        summary_df=summary_df,
        use_ensemble=use_ensemble,
        plot_paths=plot_paths,
        filename=html_filename,
    )

    return {
        "summary_df": summary_df,
        "plot_paths": plot_paths,
        "markdown_path": markdown_path,
        "html_path": html_path,
        "output_dirs": output_dirs,
    }


def generate_report(results_df: pd.DataFrame, output_path: str, use_ensemble: bool):
    """生成 Markdown 报告"""
    mode_meta = get_mode_metadata(use_ensemble)
    lines = []
    lines.append(f"# {mode_meta['report_title']}")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**模式**: {mode_meta['mode_label']}")
    lines.append("**优化器**: Differential Evolution (DE)")
    lines.append("")
    lines.append("**参数**:")
    lines.append(f"- 窗口范围: {mode_meta['window_label']}")
    lines.append("- 扫描步长: 5 天")
    lines.append("- 移动平均: 5 天")
    lines.append("- 风险判定: (0.1 < m < 0.9) AND (6 < w < 13) AND (days < 20) AND (R² > 0.5)")
    if use_ensemble:
        lines.append("- 共识阈值: 25% (12窗口中至少3个)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 汇总统计
    total = len(results_df)
    detected = results_df['detected'].sum()
    detection_rate = detected / total * 100 if total > 0 else 0

    lines.append("## 一、验证结果汇总")
    lines.append("")
    lines.append(f"- **总高点数**: {total}")
    lines.append(f"- **检测到预警**: {detected} ({detection_rate:.1f}%)")
    lines.append("")

    # 按指数统计表
    lines.append("| 指数 | 高点数 | 检测数 | 检测率 |")
    lines.append("|:-----|-------:|-------:|-------:|")

    for name in results_df['name'].unique():
        idx_data = results_df[results_df['name'] == name]
        idx_total = len(idx_data)
        idx_detected = idx_data['detected'].sum()
        idx_rate = idx_detected / idx_total * 100 if idx_total > 0 else 0
        lines.append(f"| {name} | {idx_total} | {idx_detected} | {idx_rate:.1f}% |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 高置信度案例
    high_conf = results_df[(results_df['detected']) & (results_df['first_danger_r2'] > 0.8)]
    lines.append("## 二、高置信度案例 (R²>0.8)")
    lines.append("")

    if len(high_conf) > 0:
        lines.append("| 指数 | 高点日期 | 高点价格 | 预警天数 | R² | m | w |")
        lines.append("|:-----|:---------|---------:|---------:|----:|----:|----:|")

        for _, row in high_conf.sort_values('first_danger_r2', ascending=False).iterrows():
            m_val = f"{row['first_danger_m']:.3f}" if pd.notna(row['first_danger_m']) else "N/A"
            w_val = f"{row['first_danger_w']:.3f}" if pd.notna(row['first_danger_w']) else "N/A"
            lines.append(f"| {row['name']} | {row['peak_date']} | {row['peak_price']:.2f} | {row['first_danger_days']:.0f} | {row['first_danger_r2']:.3f} | {m_val} | {w_val} |")
    else:
        lines.append("无高置信度案例")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 三、结论")
    lines.append("")
    lines.append(f"本次验证共分析 {total} 个历史高点，")
    lines.append(f"检测到预警信号 {detected} 个，")
    lines.append(f"整体检测率为 {detection_rate:.1f}%。")

    if len(high_conf) > 0:
        high_conf_rate = len(high_conf) / detected * 100 if detected > 0 else 0
        lines.append(f"其中高置信度案例 (R²>0.8) {len(high_conf)} 个，")
        lines.append(f"占检测到信号的 {high_conf_rate:.1f}%。")

    # 写入文件
    content = "\n".join(lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"报告已保存到 {output_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='LPPL 算法验证程序 V2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python lppl_verify_v2.py --all
  python lppl_verify_v2.py --symbol 000001.SH
  python lppl_verify_v2.py --symbol 000001.SH --ensemble
        """
    )

    parser.add_argument('--symbol', '-s', default=None,
                        help='指数代码 (如 000001.SH)')
    parser.add_argument('--all', '-a', action='store_true',
                        help='验证所有8个指数')
    parser.add_argument('--ensemble', '-e', action='store_true',
                        help='使用 Ensemble 模式 (12窗口多窗口共识)')
    parser.add_argument('--max-peaks', '-m', type=int, default=10,
                        help='每个指数最多分析的高点数 (默认10)')
    parser.add_argument('--step', type=int, default=5,
                        help='扫描步长 (默认: 5)')
    parser.add_argument('--ma', type=int, default=5,
                        help='移动平均窗口 (默认: 5)')
    parser.add_argument('--output', '-o', default='output/MA',
                        help='输出目录 (默认 output/MA)')
    parser.add_argument(
        "--use-optimal-config",
        action="store_true",
        help="按指数从YAML读取最优参数（缺失配置会回退默认值）",
    )
    parser.add_argument(
        "--optimal-config-path",
        default="config/optimal_params.yaml",
        help="最优参数YAML路径",
    )

    args = parser.parse_args()
    mode_meta = get_mode_metadata(args.ensemble)

    # 参数显示
    print(f"\n{'='*60}")
    print("LPPL 算法验证程序 V2")
    print(f"{'='*60}")
    print("参数配置:")
    print(f"  窗口范围: {mode_meta['window_label']}")
    print(f"  扫描步长: {args.step}天")
    print(f"  移动平均: {args.ma}天")
    print("  最小跌幅: 10%")
    print("  最小间隔: 120天")
    print(f"  模式: {mode_meta['mode_label']}")
    print("  优化器: Differential Evolution (DE)")
    print(f"{'='*60}\n")

    # 选择要验证的指数
    if args.all:
        symbols_to_verify = SYMBOLS
    elif args.symbol:
        if args.symbol not in SYMBOLS:
            print(f"未知的指数代码: {args.symbol}")
            print(f"可用指数: {', '.join(SYMBOLS.keys())}")
            return
        symbols_to_verify = {args.symbol: SYMBOLS[args.symbol]}
    else:
        # 默认测试上证综指
        symbols_to_verify = {'000001.SH': '上证综指'}

    # 运行验证
    all_results = []
    optimal_data = None
    if args.use_optimal_config:
        try:
            optimal_data = load_optimal_config(args.optimal_config_path)
            print(f"已加载最优参数配置: {args.optimal_config_path}")
        except Exception as e:
            print(f"⚠️ 最优参数加载失败，整体回退默认参数: {e}")

    for symbol, name in symbols_to_verify.items():
        config_override = None
        param_source = "default_cli"
        if args.use_optimal_config and optimal_data is not None:
            base_config = create_config(args.ensemble)
            fallback = {
                "step": args.step,
                "window_range": list(base_config.window_range),
                "r2_threshold": base_config.r2_threshold,
                "consensus_threshold": base_config.consensus_threshold,
                "danger_days": base_config.danger_days,
                "warning_days": base_config.warning_days,
                "optimizer": base_config.optimizer,
                "lookahead_days": 60,
                "drop_threshold": 0.10,
                "ma_window": args.ma,
                "max_peaks": args.max_peaks,
            }
            config_override, warnings = resolve_symbol_params(optimal_data, symbol, fallback)
            for msg in warnings:
                print(f"⚠️ {msg}")
            param_source = config_override.get("param_source", "default_fallback")

        results = run_verification(
            symbol, name,
            use_ensemble=args.ensemble,
            scan_step=args.step,
            ma_window=args.ma,
            max_peaks=args.max_peaks,
            config_override=config_override,
            param_source=param_source,
        )
        all_results.extend(results)

    # 打印汇总
    if all_results:
        results_df = pd.DataFrame(all_results)
        print_summary(results_df)

        artifacts = generate_verification_artifacts(all_results, args.output, args.ensemble)
        if artifacts:
            print(f"\nMarkdown 报告已生成: {artifacts['markdown_path']}")
            print(f"HTML 报告已生成: {artifacts['html_path']}")
    else:
        print("\n无验证结果")


if __name__ == "__main__":
    main()
