# 下一步策略实施计划

日期：2026-04-01

## 1. 当前结论

基于最近两轮实验，当前策略状态已经比较明确：

1. `MA20/250` 不是全市场统一最优主组合，但它适合作为**大盘组**当前主模板。
2. 大盘组（`000001.SH`、`000016.SH`、`000300.SH`）已经找到可落地参数：
   - `signal_model = ma_cross_atr_v1`
   - `trend_fast_ma = 20`
   - `trend_slow_ma = 250`
   - `atr_period = 14`
   - `atr_ma_window = 20`
   - `buy_volatility_cap = 1.05`
   - `vol_breakout_mult = 1.15`
   - `enable_volatility_scaling = true`
   - `target_volatility = 0.12`
3. 平衡组（`399001.SZ`、`000905.SH`）在 `MA20/250` 下仍为 `0 eligible`。
4. 高弹性组（`399006.SZ`、`000852.SH`、`932000.SH`）在 `MA20/250` 下仍为 `0 eligible`。
5. 因此，下一阶段不再继续全市场统一调 ATR，而是进入**分组主组合重扫**。

当前分组优化结果来源：

- [group_summary.csv](/home/james/Documents/Project/lppl/output/grouped_ma_atr_optimization/group_summary.csv)
- [yaml_suggestions.yaml](/home/james/Documents/Project/lppl/output/grouped_ma_atr_optimization/yaml_suggestions.yaml)

## 2. 下一阶段目标

下一阶段只做两件事：

1. 将大盘组候选参数整理为可写回生产的 YAML 草案。
2. 对平衡组和高弹性组重新扫描 **MA 主组合**，找到比 `MA20/250` 更匹配的趋势节奏。

目标不是追求一次性 `8/8 eligible`，而是先把结构正确：

- 大盘组先稳定落地
- 平衡组找到正超额候选
- 高弹性组找到回撤不过度恶化的候选

## 3. 分组执行路线

### 3.1 第一部分：大盘组写回草案

执行内容：

1. 以当前最优分组结果为基础，生成 `config/optimal_params.yaml` 草案。
2. 仅覆盖以下三只指数：
   - `000001.SH`
   - `000016.SH`
   - `000300.SH`
3. 不覆盖平衡组和高弹性组现有配置。

写回候选参数：

```yaml
signal_model: ma_cross_atr_v1
trend_fast_ma: 20
trend_slow_ma: 250
atr_period: 14
atr_ma_window: 20
buy_volatility_cap: 1.05
vol_breakout_mult: 1.15
enable_volatility_scaling: true
target_volatility: 0.12
```

验证要求：

1. 单指数 CLI 可正常读取并显示 `param_source=optimal_yaml`
2. 回测 summary 不劣于当前分组实验结果
3. 输出报告正常生成

### 3.2 第二部分：平衡组主组合重扫

适用指数：

- `399001.SZ`
- `000905.SH`

当前问题：

1. `MA20/250` 交易频率偏低
2. 结构上未形成正超额
3. ATR 与 target volatility 微调没有解决核心问题

下一轮扫描重点：

优先测试这些 MA 主组合：

- `20/120`
- `30/120`
- `30/250`
- `10/120`
- `5/250`

固定参数建议：

- `atr_period = 14`
- `atr_ma_window = 20, 40, 60`
- `buy_volatility_cap = 1.00, 1.05`
- `vol_breakout_mult = 1.05, 1.10, 1.15`
- `enable_volatility_scaling = false, true`
- `target_volatility = 0.15, 0.18`

筛选目标：

1. `annualized_excess_return > 0`
2. `max_drawdown > -35%`
3. `trade_count >= 3`
4. `turnover_rate < 8`
5. `whipsaw_rate <= 0.35`

### 3.3 第三部分：高弹性组主组合重扫

适用指数：

- `399006.SZ`
- `000852.SH`
- `932000.SH`

当前问题：

1. `MA20/250` 节奏过慢
2. 虽然部分候选能改善回撤，但超额仍显著为负
3. 高弹性组需要更快的趋势切换和更积极的波动容忍度

下一轮扫描重点：

优先测试这些 MA 主组合：

- `5/250`
- `10/250`
- `20/120`
- `5/120`
- `30/250`

固定参数建议：

- `atr_period = 14, 20`
- `atr_ma_window = 20, 40, 60`
- `buy_volatility_cap = 1.00, 1.05`
- `vol_breakout_mult = 1.05, 1.10, 1.15`
- `enable_volatility_scaling = true`
- `target_volatility = 0.18, 0.20`

筛选目标：

1. `annualized_excess_return > 0` 为第一目标
2. 若暂时无法转正，则优先保留：
   - 回撤明显收敛
   - 交易次数恢复到 `>= 3`
   - 平均持仓不极端
3. 高弹性组最大回撤门槛放宽到 `-40%`

## 4. 具体执行顺序

按这个顺序推进：

1. 先把大盘组 YAML 草案写出来，但先不立即覆盖所有 defaults
2. 单独写一个“平衡组 MA 重扫脚本”
3. 单独写一个“高弹性组 MA 重扫脚本”
4. 每组先做 MA 主组合筛选，再做 ATR + volatility scaling 小网格
5. 汇总结果后，再决定是否写回 `optimal_params.yaml`

## 5. 输出物要求

下一轮实验必须产出以下文件：

1. `output/grouped_ma_rescan_balanced/summary.csv`
2. `output/grouped_ma_rescan_high_beta/summary.csv`
3. `output/grouped_ma_rescan_balanced/report.md`
4. `output/grouped_ma_rescan_high_beta/report.md`
5. `output/grouped_ma_rescan_candidate_yaml.yaml`

## 6. 通过标准

下一阶段视为通过，至少满足以下条件之一：

1. 大盘组参数成功写回草案，并能通过 CLI 正常读取。
2. 平衡组找到至少 `1/2 eligible` 的 MA 主组合。
3. 高弹性组找到至少 `1/3 eligible` 的 MA 主组合。
4. 至少有一组新的候选参数比当前 `MA20/250` 主模板更优。

## 7. 暂不做的事情

这一轮明确不做：

1. 不重新回到 LPPL 主导逻辑
2. 不引入动量因子二期 (`enable_momentum_factor`)
3. 不引入 52 周高点因子
4. 不做跨指数轮动
5. 不追求一次性统一 8 指数参数

原因很简单：当前真正的瓶颈还是**平衡组和高弹性组的趋势主组合不匹配**，不是增强因子缺失。

## 8. 下一步直接执行项

从现在开始，下一步直接做：

1. 生成大盘组三只指数的 YAML 写回草案
2. 编写平衡组 MA 主组合重扫脚本
3. 编写高弹性组 MA 主组合重扫脚本

一句话总结：

> 先把大盘组落地，再把平衡组和高弹性组从 “ATR 微调问题” 转回 “主组合重扫问题”。
