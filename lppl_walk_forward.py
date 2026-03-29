# -*- coding: utf-8 -*-
import argparse
import os

import pandas as pd

from lppl_verify_v2 import SYMBOLS, create_config
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
    args = parser.parse_args()

    if args.symbol not in SYMBOLS:
        raise SystemExit(f"未知指数代码: {args.symbol}")

    os.makedirs(args.output, exist_ok=True)

    dm = DataManager()
    df = dm.get_data(args.symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据")

    config = create_config(args.ensemble)
    records_df, summary = run_walk_forward(
        df=df,
        symbol=args.symbol,
        window_range=config.window_range,
        config=config,
        scan_step=args.step,
        lookahead_days=args.lookahead,
        drop_threshold=args.drop_threshold,
        use_ensemble=args.ensemble,
    )

    mode_slug = "ensemble" if args.ensemble else "single_window"
    records_path = os.path.join(args.output, f"walk_forward_{args.symbol.replace('.', '_')}_{mode_slug}.csv")
    summary_path = os.path.join(args.output, f"walk_forward_{args.symbol.replace('.', '_')}_{mode_slug}_summary.csv")

    records_df.to_csv(records_path, index=False)
    pd.DataFrame([summary]).to_csv(summary_path, index=False)

    print(f"逐日记录已保存: {records_path}")
    print(f"汇总统计已保存: {summary_path}")


if __name__ == "__main__":
    main()
