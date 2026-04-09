# MA + ATR 下一阶段优化执行计划：turnover_gap 修复

日期：2026-03-30

本文档面向第一次接触本项目的人。它不是新的参数搜索计划，而是下一阶段的修复与验证计划。

这轮的目标非常明确：

- 不再扩 `atr_deadband / slope_threshold / atr_confirm_enabled`
- 不再继续追更大的 MA 网格
- 先把 `turnover_gap` 的计算和报告口径修正
- 再用修正后的口径重跑 7 指数，确认结果是否一致

## 1. 为什么要先修 `turnover_gap`

上一轮剔除 `932000.SH` 后，样本外结果已经很好：

- `Template A` 样本外：`5/5 eligible`
- `Template B` 样本外：`2/2 eligible`

但全量 7 指数复核仍然是：

- `0/7 eligible`

这不是策略突然失效，而是 `turnover_cap` 的门槛仍然在按“总周期累计换手”硬截断，导致长周期全量回测和样本外验证不在同一口径里。

结论很直接：

- 策略本身已经有可用候选
- 现在卡住的是 `turnover_gap` 的定义和门槛口径

## 2. 当前可用基线

以最新的 7 指数结果作为基线：

- `Template A` 样本外
  - 平均年化超额收益：`+2.98%`
  - 平均最大回撤：`-5.64%`
  - 平均交易次数：`9.80`
  - 平均换手率：`4.95%`
  - `Eligible: 5/5`

- `Template B` 样本外
  - 平均年化超额收益：`+2.79%`
  - 平均最大回撤：`-9.50%`
  - 平均交易次数：`14.00`
  - 平均换手率：`7.05%`
  - `Eligible: 2/2`

- 全量 7 指数
  - 平均年化超额收益：`+1.66%`
  - 平均最大回撤：`-20.20%`
  - 平均交易次数：`64.57`
  - 平均换手率：`64.77%`
  - `Eligible: 0/7`

这组结果说明：

- OOS 已经证明策略可用
- 全量被拒绝，主要是 `turnover_cap` 的门槛问题

## 3. `turnover_gap` 到底是什么

这里先把概念讲清楚。

### 3.1 现有 `turnover_rate`

当前回测里，`turnover_rate` 是：

- 交易名义金额 / 初始资金

也就是说，它是累计口径，不是“每年换手率”。

### 3.2 `turnover_gap` 的定义

本阶段建议把 `turnover_gap` 定义成：

- `turnover_gap = normalized_turnover_rate - turnover_cap`

其中 `normalized_turnover_rate` 必须和 `turnover_cap` 使用同一口径。

推荐做法：

- 保留原始累计 `turnover_rate`
- 额外输出 `annualized_turnover_rate`
- 用 `annualized_turnover_rate` 去和 `turnover_cap` 比较

这样才不会出现“5 年 OOS 可过、14 年全量全挂死”的口径失真。

## 4. 修复方案

### 4.1 先修计算口径

修改位置：

- `src/investment/backtest.py`
- `src/investment/tuning.py`
- `scripts/generate_ma_atr_next_round_report.py`

要做的事：

- 在回测摘要里同时保留 `turnover_rate` 和 `annualized_turnover_rate`
- 在调优评分里明确使用和 `turnover_cap` 同单位的指标
- 在报告里同时展示：
  - 原始累计换手
  - 年化换手
  - `turnover_cap`
  - `turnover_gap`

### 4.2 再修硬门槛

修复后再决定是否继续使用硬拒绝：

- 如果 `turnover_gap` 仍然明显为正，继续保留硬拒绝
- 如果只是全量周期过长导致累计换手偏大，就把 `turnover_cap` 改成年化口径
- 如果不同模板差异很大，就按模板单独设置阈值

### 4.3 再修报告

报告必须满足：

- `annualized_excess_return` 和 `annualized_return` 分开写
- `turnover_rate` 不能再被重复乘 100
- `turnover_gap` 必须写明计算方式
- 报告中的数值必须和 `summary/*.csv` 完全一致

## 5. 新人执行顺序

### 5.1 Stage 0：先看代码和单位

先确认这几个地方的单位一致：

- `src/investment/backtest.py`
- `src/investment/tuning.py`
- `scripts/generate_ma_atr_next_round_report.py`

检查重点：

- `turnover_rate` 是累计值还是年化值
- `turnover_cap` 是按什么单位设的
- 报告有没有把累计值当成年化值显示

### 5.2 Stage 1：只做口径修复，不动参数

先不要改 MA 参数，也不要加新过滤器。

只修：

- `turnover_rate` 计算
- `turnover_gap` 输出
- 报告显示口径

### 5.3 Stage 2：重跑 7 指数

仍然使用当前已经验证过的 7 指数范围：

- `000001.SH`
- `399001.SZ`
- `399006.SZ`
- `000016.SH`
- `000300.SH`
- `000905.SH`
- `000852.SH`

分三段跑：

- `2012-01-01` 到 `2020-12-31`：样本内
- `2021-01-01` 到 `2025-12-31`：样本外
- `2012-01-01` 到 `2025-12-31`：全量复核

### 5.4 Stage 3：核验结果

重点看三件事：

- 报告和 CSV 是否一致
- `turnover_gap` 是否按预期收敛
- 全量 `eligible` 是否不再被口径问题一刀切成 0

## 6. 通过标准

### 6.1 报告层

通过标准：

- 报告里的 `annualized_excess_return` 和 CSV 完全一致
- 报告里的 `turnover_rate` 和 CSV 完全一致
- 报告不再出现 4000% 这类换手假值

### 6.2 策略层

通过标准：

- `Template A` 样本外继续保持稳定
- `Template B` 样本外继续保持稳定
- 全量 7 指数不再因为口径问题全挂

### 6.3 风险层

通过标准：

- `turnover_gap` 的单位、阈值、报告显示三者一致
- `turnover_cap` 如果继续使用，必须和 `annualized_turnover_rate` 同口径

## 7. 输出目录建议

建议这轮输出单独放一组新目录，避免和上一轮混淆：

- `output/ma_atr_turnover_gap_fix/a_is`
- `output/ma_atr_turnover_gap_fix/b_is`
- `output/ma_atr_turnover_gap_fix/a_oos`
- `output/ma_atr_turnover_gap_fix/b_oos`
- `output/ma_atr_turnover_gap_fix/full`

## 8. 最终结论

这一阶段不追新 alpha，不扩参数，只做一件事：

- 把 `turnover_gap` 修正确认

只要这个问题修好，后面的策略判断才有意义。

