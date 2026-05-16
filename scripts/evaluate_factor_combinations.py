#!/usr/bin/env python3
# RESEARCH ONLY — not production code
"""
有效因子组合评估与验证脚本

直接加载因子组合模块，跳过 __init__.py 的依赖链。
基于49866样本的交叉分析数据，执行:
1. 全组合扫描排序
2. 最优组合详情输出
3. 分层策略性能汇总
4. 持有期与置信度敏感性分析
"""
import importlib
import importlib.machinery
import sys
import types

_mod_name = "src.investment.factor_combination"
_mod_path = "/home/james/Documents/Project/lppl/src/investment/factor_combination.py"
loader = importlib.machinery.SourceFileLoader(_mod_name, _mod_path)
mod = types.ModuleType(loader.name)
mod.__file__ = _mod_path
mod.__package__ = "src.investment"
sys.modules[_mod_name] = mod
loader.exec_module(mod)

FactorCombinationEngine = mod.FactorCombinationEngine
Regime = mod.Regime
Phase = mod.Phase
MTFAlignment = mod.MTFAlignment
Confidence = mod.Confidence


def print_header(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_section(subtitle: str):
    print(f"\n{'-'*50}")
    print(f"  {subtitle}")
    print(f"{'-'*50}")


def main():
    engine = FactorCombinationEngine()

    # === 1. 全组合扫描 ===
    print_header("有效因子组合全景扫描 (Top 30)")
    print(f"{'排名':>4} | {'组合':<48} | {'评分':>4} | {'60d收益':>7} | {'胜率':>5} | {'样本':>5} | {'风险':>6} | {'方向':<10} | {'仓位':>4}")
    print("-"*115)

    top = engine.scan_all(min_score=0)
    for i, combo in enumerate(top[:30]):
        ret = f"{combo['return_60d']:>5.1f}%" if combo['return_60d'] else "  N/A"
        wr = f"{combo['win_rate']:>4.1f}%" if combo['win_rate'] else " N/A"
        ns = str(combo['sample_size']) if combo['sample_size'] else "N/A"
        pos = f"{combo['position']:.0%}" if combo['position'] else "N/A"
        print(f"{i+1:>4} | {combo['combo']:<48} | {combo['score']:>4} | {ret:>7} | {wr:>5} | {ns:>5} | {combo['risk']:>6} | {combo['direction']:<10} | {pos:>4}")

    # === 2. 最优大样本组合 ===
    print_header("最优大样本组合 (n >= 2000)")
    print_section("熊市做多 - 最可靠的大样本信号")
    for alignment in [MTFAlignment.HIGHER_TF, MTFAlignment.FULLY_ALIGNED, MTFAlignment.WEEKLY_DAILY]:
        res = engine.evaluate(Regime.BEAR, Phase.MARKDOWN, alignment, Confidence.D, 120)
        d = res.to_dict()
        ret = f"{d['return_60d']}" if d['return_60d'] else "N/A"
        wr = f"{d['win_rate']}%" if d['win_rate'] else "N/A"
        ns = d['sample_size']
        print(f"  {d['combo']:<50} 收益:{ret:>8} | 胜率:{wr:>6} | 样本:{ns:>5} | 仓位:{d['position']:.0%}")

    print_section("高胜率稀有信号 (n < 500)")
    rare_combos = [
        (Regime.BEAR, Phase.ACCUMULATION, MTFAlignment.HIGHER_TF, "熊市吸筹抄底"),
        (Regime.BULL, Phase.DISTRIBUTION, MTFAlignment.HIGHER_TF, "牛市派发做空"),
        (Regime.BULL, Phase.UNKNOWN, MTFAlignment.WEEKLY_DAILY, "牛市未知相位做多"),
        (Regime.BULL, Phase.MARKUP, MTFAlignment.WEEKLY_DAILY, "牛市回调反转"),
    ]
    for regime, phase, alignment, label in rare_combos:
        res = engine.evaluate(regime, phase, alignment, Confidence.B, 120)
        d = res.to_dict()
        ret = f"{d['return_60d']}" if d['return_60d'] else "N/A"
        wr = f"{d['win_rate']}%" if d['win_rate'] else "N/A"
        print(f"  {label:<20} | {d['combo']:<48} 收益:{ret:>8} | 胜率:{wr:>6} | 样本:{d['sample_size']:>5} | 仓位:{d['position']:.0%}")

    # === 3. 必须排除的组合 ===
    print_section("必须排除的负收益组合 (Hard Exclusion)")
    exclude_combos = [
        (Regime.BEAR, Phase.MARKUP, MTFAlignment.FULLY_ALIGNED, "熊市+markup+fully_aligned"),
        (Regime.BEAR, Phase.UNKNOWN, MTFAlignment.HIGHER_TF, "熊市+unknown+higher_tf"),
    ]
    for regime, phase, alignment, label in exclude_combos:
        res = engine.evaluate(regime, phase, alignment, Confidence.D, 60)
        d = res.to_dict()
        if d['return_60d']:
            print(f"  {label:<35} 收益:{d['return_60d']:>6.1f}% | 胜率:{d['win_rate']}% | 样本:{d['sample_size']}")

    # === 4. 持有期衰减分析 ===
    print_header("持有期衰减分析")
    print(f"{'持有期':>8} | {'熊市价值':>8} | {'牛市动量':>8} | {'反转':>8} | {'衰减乘数':>8}")
    print("-"*60)
    ref = engine.evaluate(Regime.BEAR, Phase.MARKDOWN, MTFAlignment.HIGHER_TF, Confidence.D, 60)
    ref_ret = ref.expected_return_60d or 1.0
    for days in [30, 60, 90, 120, 150, 180]:
        r1 = engine.evaluate(Regime.BEAR, Phase.MARKDOWN, MTFAlignment.HIGHER_TF, Confidence.D, days)
        r2 = engine.evaluate(Regime.BULL, Phase.UNKNOWN, MTFAlignment.WEEKLY_DAILY, Confidence.D, days)
        r3 = engine.evaluate(Regime.BULL, Phase.MARKUP, MTFAlignment.WEEKLY_DAILY, Confidence.D, days)
        ret1 = f"{r1.expected_return_60d:>5.1f}%" if r1.expected_return_60d else "  N/A"
        ret2 = f"{r2.expected_return_60d:>5.1f}%" if r2.expected_return_60d else "  N/A"
        ret3 = f"{r3.expected_return_60d:>5.1f}%" if r3.expected_return_60d else "  N/A"
        mult = engine.DECAY_MULTIPLIER.get(days, 1.0)
        print(f"  {days:>4}d    | {ret1:>8} | {ret2:>8} | {ret3:>8} | {mult:>7.2f}x")

    # === 5. 分层策略汇总 ===
    print_header("分层策略汇总")
    strategies = [
        ("熊市价值 (核心)", [
            (Regime.BEAR, Phase.MARKDOWN, MTFAlignment.HIGHER_TF, Confidence.D, 120)]),
        ("牛市动量 (增长)", [
            (Regime.BULL, Phase.UNKNOWN, MTFAlignment.WEEKLY_DAILY, Confidence.D, 90),
            (Regime.BULL, Phase.MARKDOWN, MTFAlignment.MIXED, Confidence.D, 90)]),
        ("反转捕捉 (机会)", [
            (Regime.BULL, Phase.MARKUP, MTFAlignment.WEEKLY_DAILY, Confidence.D, 60)]),
        ("吸筹抄底 (低频)", [
            (Regime.BEAR, Phase.ACCUMULATION, MTFAlignment.HIGHER_TF, Confidence.B, 180)]),
        ("风险防御 (保本)", [
            (Regime.BEAR, Phase.MARKUP, MTFAlignment.FULLY_ALIGNED, Confidence.D, 60),
            (Regime.BEAR, Phase.UNKNOWN, MTFAlignment.HIGHER_TF, Confidence.D, 60)]),
    ]
    for name, combos in strategies:
        print_section(name)
        for r, p, a, c, h in combos:
            res = engine.evaluate(r, p, a, c, h)
            d = res.to_dict()
            ret = f"{d['return_60d']:>5.1f}%" if d['return_60d'] else "  N/A"
            wr = f"{d['win_rate']:>4.1f}%" if d['win_rate'] else " N/A"
            risk_flag = "⚠️ " if d['risk'] == "excluded" else "✅ "
            print(f"  {risk_flag} {d['combo']:<50} 收益:{ret} | 胜率:{wr} | 仓位:{d['position']:.0%}")

    # === 6. 决策树验证 ===
    print_header("决策树: 全Regime+Phase×Alignment矩阵 (60d收益%)")
    print(f"{'制度':>6} | {'相位':<14}", end="")
    for a_label in ["mixed", "fully", "wk_dly", "hi_tf"]:
        print(f" | {a_label:>6}", end="")
    print(f" | {'最佳':>10}")
    print("-"*85)

    for r in [Regime.BULL, Regime.BEAR, Regime.RANGE]:
        for p in [Phase.MARKDOWN, Phase.MARKUP, Phase.UNKNOWN, Phase.ACCUMULATION, Phase.DISTRIBUTION]:
            scores = {}
            for a in [MTFAlignment.MIXED, MTFAlignment.FULLY_ALIGNED, MTFAlignment.WEEKLY_DAILY, MTFAlignment.HIGHER_TF]:
                res = engine.evaluate(r, p, a, Confidence.D, 120)
                k = a.value.replace("_aligned", "").replace("higher_tf", "hi_tf").replace("weekly_daily", "wk_dly")
                scores[k] = f"{res.expected_return_60d:.1f}" if res.expected_return_60d else "N/A"
            best = max(scores, key=lambda k: float(scores[k]) if scores[k] != "N/A" else -999)
            print(f"  {r.value:>6} | {p.value:<14}", end="")
            for k in ["mixed", "fully", "wk_dly", "hi_tf"]:
                print(f" | {scores.get(k, 'N/A'):>6}", end="")
            print(f" | {best:>10}")

    print()
    print("="*70)
    print("  总结: 最优核心信号 = bear + markdown + higher_tf (收益6.83, 胜率56.9%, n=3667)")
    print("        RANGE制度全部排除 | 最小持有期60d | 置信度B为全仓,D为75%")
    print("        决策树驱动的仓位管理: 制度(35%) + 相位(30%) + 对齐(20%) + 置信度(15%)")
    print("="*70)


if __name__ == "__main__":
    main()
