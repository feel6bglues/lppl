#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import os
import sys
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Dict, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.lppl_engine import LPPLConfig
from src.verification.walk_forward import run_walk_forward

WINDOW_SETS: Dict[str, List[int]] = {
    "narrow_40_120": list(range(40, 130, 10)),
    "default_40_150": list(range(40, 160, 10)),
    "wide_30_180": list(range(30, 190, 10)),
}


def parse_float_list(value: str) -> List[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def parse_int_list(value: str) -> List[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def objective(summary: Dict[str, float]) -> float:
    precision = float(summary["precision"])
    recall = float(summary["recall"])
    fpr = float(summary["false_positive_rate"])
    return (0.60 * recall) + (0.30 * precision) - (0.10 * fpr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensemble 参数网格搜索")
    parser.add_argument("--symbol", default="000001.SH", help="指数代码")
    parser.add_argument("--step", type=int, default=120, help="walk-forward 扫描步长")
    parser.add_argument("--lookahead", type=int, default=60, help="未来观察天数")
    parser.add_argument("--drop-threshold", type=float, default=0.10, help="未来跌幅阈值")
    parser.add_argument("--optimizer", default="lbfgsb", choices=["lbfgsb", "de"], help="拟合优化器")
    parser.add_argument("--r2-grid", default="0.45,0.50,0.55,0.60", help="R² 阈值列表")
    parser.add_argument("--consensus-grid", default="0.15,0.20,0.25,0.30,0.35", help="共识阈值列表")
    parser.add_argument("--danger-grid", default="15,20,25", help="danger_days 列表")
    parser.add_argument(
        "--window-sets",
        default="narrow_40_120,default_40_150,wide_30_180",
        help=f"窗口集合名称，逗号分隔，可选: {','.join(WINDOW_SETS.keys())}",
    )
    parser.add_argument("--n-workers", type=int, default=1, help="LPPL 拟合并行数")
    parser.add_argument("--output", default="output/MA/summary", help="输出目录")
    args = parser.parse_args()

    r2_grid = parse_float_list(args.r2_grid)
    consensus_grid = parse_float_list(args.consensus_grid)
    danger_grid = parse_int_list(args.danger_grid)
    window_set_names = [x.strip() for x in args.window_sets.split(",") if x.strip()]

    unknown = [w for w in window_set_names if w not in WINDOW_SETS]
    if unknown:
        raise SystemExit(f"未知窗口集: {unknown}")

    os.makedirs(args.output, exist_ok=True)

    dm = DataManager()
    df = dm.get_data(args.symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据")

    grid = list(product(window_set_names, r2_grid, consensus_grid, danger_grid))
    print(f"开始网格搜索: symbol={args.symbol}, 组合数={len(grid)}")

    rows: List[Dict] = []
    for idx, (window_name, r2_threshold, consensus_threshold, danger_days) in enumerate(grid, start=1):
        window_range = WINDOW_SETS[window_name]
        config = LPPLConfig(
            window_range=window_range,
            optimizer=args.optimizer,
            r2_threshold=r2_threshold,
            consensus_threshold=consensus_threshold,
            danger_days=danger_days,
            warning_days=60,
            n_workers=args.n_workers,
        )

        _, summary = run_walk_forward(
            df=df,
            symbol=args.symbol,
            window_range=config.window_range,
            config=config,
            scan_step=args.step,
            lookahead_days=args.lookahead,
            drop_threshold=args.drop_threshold,
            use_ensemble=True,
        )

        score = objective(summary)
        row = {
            "run_id": idx,
            "symbol": args.symbol,
            "optimizer": args.optimizer,
            "window_set": window_name,
            "window_count": len(window_range),
            "window_min": min(window_range),
            "window_max": max(window_range),
            "r2_threshold": r2_threshold,
            "consensus_threshold": consensus_threshold,
            "danger_days": danger_days,
            "step": args.step,
            "lookahead_days": args.lookahead,
            "drop_threshold": args.drop_threshold,
            "objective_score": score,
        }
        row.update(summary)
        rows.append(row)

        print(
            f"[{idx}/{len(grid)}] window={window_name}, r2={r2_threshold:.2f}, "
            f"consensus={consensus_threshold:.2f}, danger={danger_days} | "
            f"precision={summary['precision']:.3f}, recall={summary['recall']:.3f}, "
            f"fpr={summary['false_positive_rate']:.3f}, score={score:.4f}"
        )

    result_df = pd.DataFrame(rows).sort_values(
        ["objective_score", "recall", "precision"], ascending=False
    ).reset_index(drop=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.output, f"ensemble_grid_search_{args.symbol.replace('.', '_')}_{ts}.csv")
    md_path = os.path.join(args.output, f"ensemble_grid_search_{args.symbol.replace('.', '_')}_{ts}.md")
    result_df.to_csv(csv_path, index=False)

    top_n = min(20, len(result_df))
    md_lines = [
        "# Ensemble 参数网格搜索结果",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 标的: {args.symbol}",
        f"- 组合数: {len(result_df)}",
        f"- 优化器: {args.optimizer}",
        f"- step/lookahead/drop: {args.step}/{args.lookahead}/{args.drop_threshold}",
        "",
        f"## Top {top_n}",
        "",
    ]
    top_cols = [
        "window_set",
        "r2_threshold",
        "consensus_threshold",
        "danger_days",
        "precision",
        "recall",
        "false_positive_rate",
        "signal_density",
        "objective_score",
        "signal_count",
        "true_positive",
        "false_positive",
        "false_negative",
    ]
    md_lines.append(result_df[top_cols].head(top_n).to_markdown(index=False))
    md_lines.append("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print("")
    print(f"搜索完成，结果CSV: {csv_path}")
    print(f"搜索完成，结果MD : {md_path}")
    if not result_df.empty:
        best = result_df.iloc[0]
        print(
            "最佳参数: "
            f"window_set={best['window_set']}, r2={best['r2_threshold']}, "
            f"consensus={best['consensus_threshold']}, danger_days={best['danger_days']}, "
            f"precision={best['precision']:.3f}, recall={best['recall']:.3f}, "
            f"fpr={best['false_positive_rate']:.3f}, score={best['objective_score']:.4f}"
        )


if __name__ == "__main__":
    main()
