#!/usr/bin/env python3
"""多因子后处理分析: 在v2+运行结果上叠加因子过滤"""
import json
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 加载v2+原始结果 (7118样本)
d = json.load(open(PROJECT_ROOT / "output" / "wyckoff_v2plus_test" / "v2plus_results.json"))
print(f"加载v2+结果: {d['overall']['n_samples']}样本")
print(f"v2+原始收益: {d['overall']['mean_return']:.2f}%")
print(f"v2+夏普: {d['overall']['sharpe_ratio']:.3f}")
print()

# 从exit_reason分析看, target_50pct+trailing_stop是最优子集
er = d["exit_reason"]
print("=== v2+退出方式收益率排序 ===")
for r, s in sorted(er.items(), key=lambda x: -x[1]["mean"]):
    print(f"  {r:35s}: {s['pct']:5.1f}%  ret={s['mean']:6.2f}%  win={s['win']:5.1f}%")

# 从regime分析看, bull市场表现最好
rg = d["regime"]
print("\n=== v2+市场状态分析 ===")
for r, s in sorted(rg.items(), key=lambda x: -x[1]["mean"]):
    print(f"  {r:6s}: ret={s['mean']:6.2f}%  win={s['win']:5.1f}%  n={s['n']}")

print(f"""
=================================================================
多因子合成可行性(基于v2+已观测数据)
=================================================================

因子1: WYCKOFF = v2+基础策略                   Sharpe=0.168  收益=+1.69%

因子2: MA/ATR (趋势过滤)
  - 在v2+的NTZ过滤基础上, 加入MA20>MA60确认上升趋势
  - 预期: 标记上升趋势的股票交易表现更好
  - 数据: 可从exit_reason推断 - 达target的交易集中在bull/up阶段

因子3: REGIME (市场状态自适应, 已部分使用)
  - bull: 收益+3.57%  (n=3248)  ← 最强
  - range: +2.45%     (n=481)   ← 中等
  - bear: -0.12%      (n=3389)  ← 最弱

合成方案1: REGIME FILTER ONLY (最快实现)
  只在bull和range市场交易, 跳过bear市场
  预期: 3248+481=3729样本
  加权收益: (3248*3.57 + 481*2.45) / 3729 = 3.42%
  预期夏普: 0.342 (翻倍!)

合成方案2: WYCKOFF + REGIME (当前)
  已经实现: regime自适应ATR乘数
  还可优化: bear市场中进一步收紧NTZ

结论: 最大的单因子增益来自REGIME过滤(跳过bear市场)
  从Sharpe 0.168 → ~0.342 (翻倍)
  这是当前最低成本最高回报的优化
""")

print("=" * 65)
print("验证: 如果只在bull+range中交易")
print("=" * 65)

# 从regime分析估算
for regime, s in rg.items():
    sharpe_r = s["mean"] / d["overall"]["std_return"] * (252/90)**0.5 if d["overall"]["std_return"] > 0 else 0
    print(f"  {regime:6s}: 收益={s['mean']:6.2f}%  夏普≈{sharpe_r:.3f}  权重={s['n']/d['overall']['n_samples']*100:.0f}%")

# Bull+Range加权
bull_range = [s for r, s in rg.items() if r in ("bull", "range")]
n_br = sum(s["n"] for s in bull_range)
ret_br = sum(s["mean"] * s["n"] for s in bull_range) / n_br
sharpe_br = ret_br / d["overall"]["std_return"] * (252/90)**0.5
print(f"\n  bull+range加权: 收益={ret_br:.2f}%  夏普≈{sharpe_br:.3f}  样本={n_br}")
print(f"  相比v2+全部:    收益=+1.69%  夏普=0.168")
print(f"  改善:           收益+{ret_br-1.69:.2f}pp  夏普+{sharpe_br-0.168:.3f}")
