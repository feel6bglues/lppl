#!/usr/bin/env python3
"""
统一回测入口 — 替代 run_tristrat_v6*.py / run_dual_strat*.py

用法:
  python scripts/run_backtest.py --strategies wyckoff,ma_cross --windows 30 --min-year 2020 --max-year 2026 --name dual_2020_30w

  python scripts/run_backtest.py --strategies wyckoff,ma_cross,str_reversal --windows 20 --min-year 2016 --max-year 2026 --name tri_full

  python scripts/run_backtest.py --strategies wyckoff,ma_cross --windows 20 --min-year 2020 --max-year 2025 --costs --name dual_with_costs
"""

import argparse, json, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.backtest_core import run_backtest

VALID_STRATEGIES = {"wyckoff", "ma_cross", "str_reversal"}


def validate_args(strategies: list[str], windows: int, min_year: int,
                  max_year: int, limit: int, name: str) -> list[str]:
    """参数校验纯函数。返回错误信息列表，空列表 = 合法。"""
    errors = []
    unknown = [s for s in strategies if s not in VALID_STRATEGIES]
    if unknown:
        errors.append(f"未知策略: {', '.join(unknown)} (可选: {', '.join(sorted(VALID_STRATEGIES))})")
    if windows < 1:
        errors.append("--windows 必须 >= 1")
    if min_year > max_year:
        errors.append(f"--min-year {min_year} > --max-year {max_year}")
    if limit < 1:
        errors.append("--limit 必须 >= 1")
    if not name:
        errors.append("--name 不能为空")
    return errors


def main():
    parser = argparse.ArgumentParser(description="统一回测框架")
    parser.add_argument("--strategies", default="wyckoff,ma_cross",
                        help="策略列表, 逗号分隔, 可选: wyckoff,ma_cross,str_reversal")
    parser.add_argument("--windows", type=int, default=20, help="随机窗口数量")
    parser.add_argument("--min-year", type=int, default=2020, help="最早采样年份")
    parser.add_argument("--max-year", type=int, default=2026, help="最晚采样年份")
    parser.add_argument("--costs", action="store_true", help="扣除交易成本")
    parser.add_argument("--name", default="backtest", help="输出目录名")
    parser.add_argument("--limit", type=int, default=99999, help="股票数量限制")
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",")]
    errs = validate_args(strategies, args.windows, args.min_year,
                         args.max_year, args.limit, args.name)
    if errs:
        parser.error("; ".join(errs))

    output_dir = PROJECT_ROOT / "output" / args.name

    print(f"strategy={args.strategies} windows={args.windows} period={args.min_year}-{args.max_year}")
    print(f"costs={args.costs} limit={args.limit}")

    t0 = time.time()
    result = run_backtest(
        strategies=strategies,
        n_windows=args.windows,
        min_year=args.min_year,
        max_year=args.max_year,
        with_costs=args.costs,
        output_dir=str(output_dir),
        n_stocks_limit=args.limit,
    )
    elapsed = time.time() - t0

    if not result.get("strategies"):
        print("无交易")
        return

    # 输出
    print(f"\n{'=' * 70}")
    print("策略表现:")
    header = f"{'策略':15s} {'样本':>8s} {'收益均':>8s} {'中位':>8s} {'标准差':>8s} {'胜率':>6s} {'持有':>6s} {'夏普':>8s}"
    print(header)
    print("-" * 70)
    for sn, st in result["strategies"].items():
        print(f"  {sn:13s} {st['n']:>8d} {st['mean_ret']:>7.2f}% {st['median_ret']:>7.2f}% "
              f"{st['std']:>7.2f}% {st['win_rate']:>5.1f}% {st['avg_days']:>5.1f}d {st['sharpe']:>7.3f}")

    p = result["portfolio"]
    print(f"\n组合夏普: {p['multi_strat_sharpe']:.3f} ({p['method']})")

    print(f"\n蒙特卡洛:")
    for sn, m in result.get("monte_carlo", {}).items():
        print(f"  {sn:13s}: 均值={m['mean']:.3f} 90%CI=[{m['ci_5']:.3f},{m['ci_95']:.3f}] 正值={m['p_pos']:.1f}%")

    # 保存
    output_dir.mkdir(parents=True, exist_ok=True)
    jp = output_dir / "results.json"
    with jp.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {jp} (耗时 {elapsed:.1f}s)")


if __name__ == "__main__":
    main()
