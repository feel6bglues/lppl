# -*- coding: utf-8 -*-
import argparse
import os

import pandas as pd

from src.cli.lppl_verify_v2 import SYMBOLS, create_config
from src.config import load_optimal_config, resolve_symbol_params
from src.constants import SUMMARY_OUTPUT_DIR
from src.data.manager import DataManager
from src.verification import run_walk_forward


def main() -> None:
    parser = argparse.ArgumentParser(description="LPPL Walk-Forward 盲测")
    parser.add_argument("--symbol", "-s", default="000001.SH", help="指数代码")
    parser.add_argument("--ensemble", "-e", action="store_true", help="使用 Ensemble 模式")
    parser.add_argument("--step", type=int, default=5, help="扫描步长")
    parser.add_argument("--lookahead", type=int, default=60, help="未来观察天数")
    parser.add_argument("--drop-threshold", type=float, default=0.10, help="未来跌幅阈值")
    parser.add_argument("--output", "-o", default=SUMMARY_OUTPUT_DIR, help="输出目录")
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

    if args.symbol not in SYMBOLS:
        raise SystemExit(f"未知指数代码: {args.symbol}")

    os.makedirs(args.output, exist_ok=True)

    dm = DataManager()
    df = dm.get_data(args.symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据")

    config = create_config(args.ensemble)
    scan_step = args.step
    lookahead_days = args.lookahead
    drop_threshold = args.drop_threshold
    param_source = "default_cli"

    if args.use_optimal_config:
        fallback = {
            "step": args.step,
            "window_range": list(config.window_range),
            "r2_threshold": config.r2_threshold,
            "danger_r2_offset": config.danger_r2_offset,
            "consensus_threshold": config.consensus_threshold,
            "danger_days": config.danger_days,
            "warning_days": config.warning_days,
            "watch_days": config.watch_days,
            "optimizer": config.optimizer,
            "lookahead_days": args.lookahead,
            "drop_threshold": args.drop_threshold,
            "ma_window": 5,
            "max_peaks": 10,
        }
        try:
            optimal_data = load_optimal_config(args.optimal_config_path)
            resolved, warnings = resolve_symbol_params(optimal_data, args.symbol, fallback)
            for msg in warnings:
                print(f"⚠️ {msg}")

            config.window_range = list(resolved["window_range"])
            config.optimizer = resolved["optimizer"]
            config.r2_threshold = resolved["r2_threshold"]
            config.danger_r2_offset = resolved["danger_r2_offset"]
            config.consensus_threshold = resolved["consensus_threshold"]
            config.danger_days = resolved["danger_days"]
            config.warning_days = resolved["warning_days"]
            config.watch_days = resolved["watch_days"]
            scan_step = resolved["step"]
            lookahead_days = resolved["lookahead_days"]
            drop_threshold = resolved["drop_threshold"]
            param_source = resolved["param_source"]
        except Exception as e:
            print(f"⚠️ 最优参数文件加载失败，使用默认参数: {e}")
            param_source = "default_fallback"

    print(
        "生效参数: "
        f"source={param_source}, step={scan_step}, windows={config.window_range[0]}-{config.window_range[-1]} "
        f"({len(config.window_range)}), optimizer={config.optimizer}, r2={config.r2_threshold:.2f}, "
        f"consensus={config.consensus_threshold:.2f}, danger_days={config.danger_days}, "
        f"lookahead={lookahead_days}, drop={drop_threshold:.2f}"
    )

    records_df, summary = run_walk_forward(
        df=df,
        symbol=args.symbol,
        window_range=config.window_range,
        config=config,
        scan_step=scan_step,
        lookahead_days=lookahead_days,
        drop_threshold=drop_threshold,
        use_ensemble=args.ensemble,
    )
    records_df["param_source"] = param_source

    mode_slug = "ensemble" if args.ensemble else "single_window"
    records_path = os.path.join(args.output, f"walk_forward_{args.symbol.replace('.', '_')}_{mode_slug}.csv")
    summary_path = os.path.join(args.output, f"walk_forward_{args.symbol.replace('.', '_')}_{mode_slug}_summary.csv")
    summary["param_source"] = param_source
    summary["step"] = scan_step
    summary["window_min"] = min(config.window_range)
    summary["window_max"] = max(config.window_range)
    summary["window_count"] = len(config.window_range)
    summary["optimizer"] = config.optimizer
    summary["r2_threshold"] = config.r2_threshold
    summary["consensus_threshold"] = config.consensus_threshold
    summary["danger_days"] = config.danger_days

    records_df.to_csv(records_path, index=False)
    pd.DataFrame([summary]).to_csv(summary_path, index=False)

    print(f"逐日记录已保存: {records_path}")
    print(f"汇总统计已保存: {summary_path}")


if __name__ == "__main__":
    main()
