# 修复后策略重跑对比 - 2026-04-01

## 口径

- 指数集合: `000300.SH`, `000905.SH`, `399006.SZ`
- 区间: `2012-01-01` 到 `2025-12-31`
- 并发: `CPU-2` 上限, 当前机器为 `30`
- 公共回测层已统一为优化后的 `backtest.py`

## 修复内容

1. 公共回测热点优化
   - `generate_investment_signals()` 从 `iterrows()` 改为 `itertuples()`
   - `run_strategy_backtest()` 去掉 `to_dict("records")`
   - `_whipsaw_rate()` 改为向量化统计
2. 脚本层并发统一
   - `tune_ma_atr_only.py`
   - `tune_ma_convergence.py`
   - `tune_ma_convergence_v2.py`
   - `tune_multi_factor_adaptive.py`
   - `tune_optimized_strategy.py`
3. 并发规则统一
   - 实际 worker = `min(用户指定, CPU-2, 候选数)`
   - 进程池失败时自动降并发重试

## 各策略最佳结果

| 策略 | 000300.SH | 000905.SH | 399006.SZ | 结论 |
|---|---:|---:|---:|---|
| `ma_convergence` | `+5.81%` / `True` | `+4.50%` / `True` | `-11.85%` / `False` | 修复后恢复有效, 当前最值得继续 |
| `optimized_strategy_v3` | `+2.25%` / `False` | `+0.97%` / `False` | `+1.43%` / `False` | 有超额, 但交易过多, 筛选不通过 |
| `ma_atr_only` | `-1.00%` / `False` | `-3.45%` / `False` | `-7.66%` / `False` | 当前 smoke 下无效 |
| `ma_atr_long_hold` | `-1.33%` / `False` | `-2.70%` / `False` | `-4.55%` / `False` | 能跑通, 但明显弱于其他路线 |
| `ma_convergence_v2` | `-2.01%` / `False` | `-6.50%` / `False` | `-7.37%` / `False` | 程序已修复, 但策略本身较差 |
| `multi_factor_adaptive` | `-5.33%` / `False` | `-6.50%` / `False` | `-11.85%` / `False` | 基本不交易, 当前设计无效 |

## 综合排名

按“策略有效性 + 可继续研究价值”排序:

1. `ma_convergence`
2. `optimized_strategy_v3`
3. `ma_atr_only`
4. `ma_atr_long_hold`
5. `ma_convergence_v2`
6. `multi_factor_adaptive`

## 判断

### 1. `ma_convergence`

- 这条线已经证明之前存在程序问题
- 修复后在 `000300.SH` 和 `000905.SH` 上达到 `eligible=True`
- 当前最应继续做 OOS 和参数收缩

证据:
- `output/retest_20260401/ma_convergence_retry/summary/ma_convergence_stage5_best_20260401_163821.csv`
- `output/retest_20260401/ma_convergence_retry/reports/ma_convergence_tuning_report_20260401_163821.md`

### 2. `optimized_strategy_v3`

- 修复后可稳定利用 30 进程重跑
- 三个指数都有正年化超额
- 但交易次数极高, 无法通过筛选标准

证据:
- `output/retest_20260401/optimized_strategy_smoke_retry3/summary/optimized_v3_stage2_best_20260401_162342.csv`
- `output/retest_20260401/optimized_strategy_smoke_retry3/reports/optimized_v3_tuning_report_20260401_162342.md`

### 3. `ma_atr_only`

- 并发与回测层都已修正
- 结果仍然整体为负
- 说明当前问题主要不在程序, 而在策略或参数网格

证据:
- `output/retest_20260401/ma_atr_only_retry/summary/ma_atr_stage4_best_20260401_163535.csv`
- `output/retest_20260401/ma_atr_only_retry/reports/ma_atr_tuning_report_20260401_163535.md`

### 4. `ma_atr_long_hold`

- 之前确有程序问题, 已修复
- 修复后可以快速稳定产出结果
- 但当前长持仓参数在 3 个指数上全部负超额, 回撤也偏大

证据:
- `output/retest_20260401/ma_atr_long_hold_retry/long_hold_combined_20260401_164221.csv`

### 5. `ma_convergence_v2`

- 现在可以正常跑
- 但修复后仍普遍为负超额
- 说明主要是策略设计不佳, 不是脚本问题

证据:
- `output/retest_20260401/ma_convergence_v2_retry/summary/ma_convergence_v2_stage5_best_20260401_163915.csv`
- `output/retest_20260401/ma_convergence_v2_retry/reports/ma_convergence_v2_tuning_report_20260401_163915.md`

### 6. `multi_factor_adaptive`

- 程序链路已打通
- 但几乎不交易, 或退化为全程空仓
- 当前版本不建议继续扩参

证据:
- `output/retest_20260401/multi_factor_adaptive_retry/summary/multi_factor_stage5_best_20260401_164212.csv`
- `output/retest_20260401/multi_factor_adaptive_retry/reports/multi_factor_tuning_report_20260401_164212.md`

## 下一步建议

1. 继续 `ma_convergence`
   - 做 OOS 重跑
   - 再做全指数扩展
2. 收缩 `optimized_strategy_v3`
   - 重点压交易次数与换手
   - 暂不扩全量
3. 暂停以下路线的大规模继续实验
   - `ma_atr_only`
   - `ma_atr_long_hold`
   - `ma_convergence_v2`
   - `multi_factor_adaptive`
