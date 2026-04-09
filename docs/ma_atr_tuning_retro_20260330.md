# 双均线 + ATR 调优复盘（截至 2026-03-30）

## 1. 目的

这份文档汇总最近几轮围绕“`双均线 + ATR` 作为主交易信号，`LPPL` 降级为辅助或关闭”的测试、结果和结论，作为下一轮调优的起点。

当前结论已经很明确：

- `LPPL` 叠加到主信号上，在现有实现下大概率是负贡献。
- `双均线 + ATR` 单独作为主信号是可行的，但长区间下需要独立风险层。
- 新增的长期趋势过滤和回撤停机，显著改善了 `2012-2025` 长区间回撤。
- 当前主要瓶颈已经从“收益/回撤”转为“`turnover_rate` / `whipsaw_rate` 的统计或定义问题”。

## 2. 当前代码状态

核心文件：

- 策略与回测：[src/investment/backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py)
- 参数解析：[src/config/optimal_params.py](/home/james/Documents/Project/lppl/src/config/optimal_params.py)
- 纯双均线+ATR 调优脚本：[scripts/tune_ma_atr_only.py](/home/james/Documents/Project/lppl/scripts/tune_ma_atr_only.py)

当前 `signal_model` 相关能力：

- `ma_cross_atr_v1`
  - 纯双均线 + ATR
  - 不执行 LPPL 扫描
- `ma_cross_atr_lppl_v1`
  - 双均线 + ATR 主交易
  - LPPL 顶部状态机辅助减仓/清仓

当前新增风险层参数：

- `regime_filter_ma`
- `regime_filter_buffer`
- `regime_filter_reduce_enabled`
- `risk_drawdown_stop_threshold`
- `risk_drawdown_lookback`
- `min_hold_bars`

## 3. 并行执行优化

已完成的并行优化：

- `30` 个并行 worker，使用 `ProcessPoolExecutor`
- 每个 worker 限制底层数值库线程为 `1`
  - `OMP_NUM_THREADS=1`
  - `OPENBLAS_NUM_THREADS=1`
  - `MKL_NUM_THREADS=1`
  - `NUMEXPR_NUM_THREADS=1`
- `executor.map(..., chunksize=...)`
  - 降低进程调度开销

相关位置：

- [scripts/tune_ma_atr_only.py](/home/james/Documents/Project/lppl/scripts/tune_ma_atr_only.py)

## 4. 已完成实验

### 4.1 纯 MA20/MA60 + ATR vs LPPL 叠加

目的：

- 验证 `LPPL` 是否拖累主信号效果。

输出：

- 纯主信号汇总：
  [ma20_ma60_atr_only_effectiveness_round1_summary.csv](/home/james/Documents/Project/lppl/output/ma20_ma60_atr_only_effectiveness_round1/summary/ma20_ma60_atr_only_effectiveness_round1_summary.csv)
- 对比差分：
  [ma20_ma60_atr_only_vs_lppl_overlay_round1.csv](/home/james/Documents/Project/lppl/output/ma20_ma60_atr_only_effectiveness_round1/summary/ma20_ma60_atr_only_vs_lppl_overlay_round1.csv)

结论：

- 纯主信号：`eligible = 2 / 8`
- 带 LPPL overlay：`eligible = 0 / 8`
- 说明当前 LPPL 叠加逻辑大概率是负贡献。

关键通过指数：

- `000001.SH`
- `000905.SH`

### 4.2 多双均线组合 + ATR，短区间基线（2020-01-01 到 2026-03-27）

目的：

- 在 `MA5/10/20/30/60/120` 中搜索最佳双均线组合。

输出：

- [ma_atr_stage2_best_20260330_094827.csv](/home/james/Documents/Project/lppl/output/ma_atr_tuning_round1_w30/summary/ma_atr_stage2_best_20260330_094827.csv)
- [ma_atr_tuning_report_20260330_094827.md](/home/james/Documents/Project/lppl/output/ma_atr_tuning_round1_w30/reports/ma_atr_tuning_report_20260330_094827.md)

结论：

- `eligible = 5 / 8`
- 通过门槛：
  - `000001.SH`
  - `000300.SH`
  - `000905.SH`
  - `000852.SH`
  - `932000.SH`

关键发现：

- 快线大多数收敛到 `MA5`
- 慢线在 `30 / 60 / 120` 三类之间分化
- 固定 `MA20/60` 的策略假设不成立

### 4.3 长区间基线（2012-01-01 到 2025-12-31）

目的：

- 用更长历史验证纯双均线 + ATR 的稳健性。

输出：

- [ma_atr_stage2_best_20260330_095802.csv](/home/james/Documents/Project/lppl/output/ma_atr_tuning_round2_w30_2012_2025/summary/ma_atr_stage2_best_20260330_095802.csv)
- [ma_atr_tuning_report_20260330_095802.md](/home/james/Documents/Project/lppl/output/ma_atr_tuning_round2_w30_2012_2025/reports/ma_atr_tuning_report_20260330_095802.md)

结论：

- `eligible = 0 / 8`
- 原因不是没有正超额，而是长区间下最大回撤全面超线。

关键发现：

- 多数指数的最优结构从短区间的 `MA5/*` 向 `MA10/30` 偏移
- 高弹性指数仍倾向更快的均线
- 长区间下，单靠双均线 + ATR 不能控制大回撤

### 4.4 风险层验证（Stage 3）

目的：

- 保持主买卖逻辑不变，只增加独立风险层：
  - `MA120` 趋势过滤
  - 长回撤停机

输出：

- [ma_atr_stage3_best_20260330_102129.csv](/home/james/Documents/Project/lppl/output/ma_atr_risk_round3_w30_2012_2025/summary/ma_atr_stage3_best_20260330_102129.csv)
- [ma_atr_tuning_report_20260330_102129.md](/home/james/Documents/Project/lppl/output/ma_atr_risk_round3_w30_2012_2025/reports/ma_atr_tuning_report_20260330_102129.md)

结果：

- `eligible = 0 / 8`
- 但收益和回撤大幅改善

相对长区间基线的代表性改善：

- `399001.SZ`
  - `mdd: -55.03% -> -25.85%`
  - `excess: +2.27% -> +3.45%`
- `000016.SH`
  - `mdd: -38.42% -> -15.63%`
  - `excess: +1.83% -> +5.57%`
- `000300.SH`
  - `mdd: -35.11% -> -22.22%`
  - `excess: +1.83% -> +2.88%`
- `932000.SH`
  - `mdd: -48.89% -> -24.80%`
  - `excess: +5.00% -> +6.16%`

Stage 3 最强组合：

- `000016.SH`
  - `MA5/30`, `ATR 10/20`
  - `regime=120@0.98`
  - `dd_stop=0.12/240`
  - `excess=5.57%`
  - `mdd=-15.63%`
- `932000.SH`
  - `MA5/30`, `ATR 14/40`
  - `regime=120@0.98`
  - `dd_stop=0.15/180`
  - `excess=6.16%`
  - `mdd=-24.80%`
- `000300.SH`
  - `MA10/30`, `ATR 10/20`
  - `regime=120@0.98`
  - `dd_stop=0.18/240`
  - `excess=2.88%`
  - `mdd=-22.22%`

Stage 3 未通过的主因：

- `turnover_cap`
- `whipsaw_cap`
- `399006.SZ` 额外还有 `non_positive_excess`

### 4.5 换手抑制验证（Stage 4）

目的：

- 不动主收益/风险框架，只搜索：
  - `confirm_days`
  - `cooldown_days`
  - `min_hold_bars`

输出：

- [ma_atr_stage4_best_20260330_103058.csv](/home/james/Documents/Project/lppl/output/ma_atr_turnover_round4_w30_2012_2025/summary/ma_atr_stage4_best_20260330_103058.csv)
- [ma_atr_tuning_report_20260330_103058.md](/home/james/Documents/Project/lppl/output/ma_atr_turnover_round4_w30_2012_2025/reports/ma_atr_tuning_report_20260330_103058.md)

结果：

- `eligible = 0 / 8`
- Stage 4 对结果没有任何实质变化

统一收敛参数：

- `confirm_days = 2`
- `cooldown_days = 5`
- `min_hold_bars = 3`

但相对 Stage 3：

- `excess_delta = 0`
- `mdd_delta = 0`
- `trade_delta = 0`

结论：

- `confirm/cooldown/min_hold` 不是当前瓶颈。
- 继续在这条线上调参，预期收益很低。

## 5. 当前最可靠判断

### 5.1 已确认成立

- `LPPL` 当前实现方式会干扰主交易信号，不应优先叠加。
- `双均线 + ATR` 作为主交易信号是成立的。
- 长期趋势过滤 + 长回撤停机是有效风险层。
- 快线和慢线必须逐指数或分组调，不存在统一最优。

### 5.2 已确认不值得继续调

- 继续微调 `LPPL` 叠加顺序
- 继续只调 `confirm_days / cooldown_days / min_hold_bars`
- 继续使用固定 `MA20/60`

### 5.3 当前真正瓶颈

最关键的问题已经从“收益/回撤”切换为：

- `turnover_rate`
- `whipsaw_rate`

而且 Stage 4 的“零变化”说明：

- 要么这两个指标的计算口径和当前策略不匹配
- 要么当前统计的是某种非信号级的交易特征
- 要么当前最佳结果的 rejected reason 过于严格，不适合这类日频趋势策略

## 6. 下一轮调优建议

优先级按顺序执行：

### A. 先查指标定义

必须先检查：

- `turnover_rate` 的计算方式
- `whipsaw_rate` 的计算方式
- 是否与当前 `trade_count` / `action` 序列一致
- 是否仍然有“非信号驱动的持仓再计算”污染指标

建议优先核查文件：

- [src/investment/tuning.py](/home/james/Documents/Project/lppl/src/investment/tuning.py)
- [src/investment/backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py)

### B. 用 Stage 3 作为下一轮起点

下一轮不要从 Stage 1 重新扫起，直接以 Stage 3 最优参数为初始候选。

建议优先保留的结构：

- `000016.SH`: `MA5/30 + ATR 10/20 + regime 120@0.98 + dd_stop 0.12/240`
- `000300.SH`: `MA10/30 + ATR 10/20 + regime 120@0.98 + dd_stop 0.18/240`
- `000905.SH`: `MA5/60 + ATR 14/20 + regime 120@0.98 + dd_stop 0.18/240`
- `932000.SH`: `MA5/30 + ATR 14/40 + regime 120@0.98 + dd_stop 0.15/180`

### C. 若指标定义无误，再做结构性抑制

如果核查后发现 `turnover/whipsaw` 指标本身没有问题，下一轮不要再调 `confirm/cooldown`，而是改信号结构：

- 买入只允许在“首次金叉”触发，不允许持续多日重复 buy candidate
- 卖出只允许在“首次死叉”触发，不允许长期死叉状态反复记为 whipsaw
- 对快线增加去抖动：
  - 用 `MA slope` 门槛
  - 或 `ATR deadband`
  - 或 `cross persistence`

## 7. 可直接复用的结果文件

作为下一轮起点，优先使用：

- Stage 3 最优表：
  [ma_atr_stage3_best_20260330_102129.csv](/home/james/Documents/Project/lppl/output/ma_atr_risk_round3_w30_2012_2025/summary/ma_atr_stage3_best_20260330_102129.csv)
- Stage 4 最优表：
  [ma_atr_stage4_best_20260330_103058.csv](/home/james/Documents/Project/lppl/output/ma_atr_turnover_round4_w30_2012_2025/summary/ma_atr_stage4_best_20260330_103058.csv)
- 长区间纯主信号基线：
  [ma_atr_stage2_best_20260330_095802.csv](/home/james/Documents/Project/lppl/output/ma_atr_tuning_round2_w30_2012_2025/summary/ma_atr_stage2_best_20260330_095802.csv)

## 8. 一句话结论

下一轮调优的正确起点不是再改参数，而是：

`以 Stage 3 的“主信号 + 风险层”最优组合作为基线，先核查 turnover/whipsaw 的统计定义，再决定是否需要改信号去抖动结构。`
