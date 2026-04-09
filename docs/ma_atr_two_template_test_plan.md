# MA + ATR 双模板测试计划

日期：2026-03-30

本文档面向第一次接触本项目的人。目标是把当前 `MA + ATR` 策略拆成两套可执行模板，并明确：

- 每套模板适合什么类型的指数
- 先测哪些参数
- 基线是什么
- 什么时候算“更好”
- 具体怎么跑、怎么看结果

这份文档不是研究结论本身，而是下一轮测试的操作手册。

## 1. 先看结论

当前策略已经不适合用“一套参数打全市场”。

根据前几轮结果，应该拆成两类模板：

- `模板 A`：几年一个周期的指数，偏大盘、偏宽基
- `模板 B`：高波动指数，偏中小盘、波动更剧烈

核心原因是：

- 大盘指数的趋势更慢，适合更长均线和更重的风险过滤
- 高波动指数的噪声更大，适合更短均线但更严格的波动确认
- 当前结果已经证明，继续只调 `confirm_days`、`cooldown_days`、`min_hold_bars`，很难再显著压低换手

当前最重要的实验基线是：

- 全量基线：`output/ma_atr_tuning_round6_w30_2012_2025_sell_atr_expand`
- 全量补充基线：`output/ma_atr_tuning_full_test`

## 2. 这套策略在测什么

当前纯 `MA + ATR` 策略的含义是：

- 买入：`MA` 金叉 + `ATR` 低波动确认
- 卖出：`MA` 死叉 + `ATR` 持续放大确认
- 风险层：长期趋势过滤 + 回撤停机
- 交易抑制：确认天数、冷却天数、最小持有期

对应实现位置：

- `src/investment/backtest.py`
- `scripts/tune_ma_atr_only.py`
- `src/investment/tuning.py`

## 3. 新人先看这个

如果你完全没接触过这个项目，按下面顺序理解最省时间：

1. `src/investment/backtest.py` 决定每天什么时候买、什么时候卖。
2. `scripts/tune_ma_atr_only.py` 负责批量跑不同参数组合。
3. `src/investment/tuning.py` 负责判断哪些结果可接受，哪些结果要拒绝。
4. `output/` 目录保存每次实验的 CSV 和报告。

你可以把系统理解成：

- 输入：历史行情
- 中间层：均线、ATR、趋势过滤、回撤过滤
- 输出：每日仓位、交易动作、收益、回撤、换手

## 4. 基线是什么

### 4.1 代码基线

当前应该以这些文件为准：

- `src/investment/backtest.py`
- `src/investment/tuning.py`
- `scripts/tune_ma_atr_only.py`
- `config/optimal_params.yaml`

如果这些文件改了，测试计划要跟着改。

### 4.2 结果基线

先用下面两个结果作为对照：

- `round6`：
  - 路径：`output/ma_atr_tuning_round6_w30_2012_2025_sell_atr_expand`
  - 特点：卖出加入“ATR 持续放大”后，收益回来了，但回撤仍偏高
- `full_test`：
  - 路径：`output/ma_atr_tuning_full_test`
  - 特点：是更完整的参数序列汇总，适合做模板拆分前的参考

### 4.3 当前全量基线指标

以 `round6` / `full_test` 的 Stage 4 为当前参考：

- 平均年化超额收益：`+1.3408%`
- 平均最大回撤：`-19.3237%`
- 平均交易次数：`64.875`
- 平均换手率：`65.5281`
- 平均 whipsaw_rate：`0.2224`

这代表当前策略的状态是：

- 收益已经不是最大问题
- 回撤仍然需要继续压
- 换手率仍然偏高
- 高频指数特别容易产生抖动

## 5. 两套模板怎么分

### 5.1 模板 A: 几年一个周期的大盘/宽基

适用指数：

- `000001.SH`
- `399001.SZ`
- `000016.SH`
- `000300.SH`
- `000905.SH`

特征：

- 趋势更慢
- 更容易持有较长周期
- 不适合过短均线

### 5.2 模板 B: 高波动指数

适用指数：

- `399006.SZ`
- `000852.SH`
- `932000.SH`

特征：

- 波动更大
- 假突破和假跌破更多
- 需要更严格的波动确认和更保守的风控

## 6. 模板参数建议

下面的参数不是最终答案，而是建议的测试起点。

### 6.1 模板 A 建议

#### 均线

- `fast_ma`: `10, 20, 30`
- `slow_ma`: `60, 120`

推荐优先测试：

- `10/60`
- `10/120`
- `20/120`
- `30/120`

#### ATR

- `atr_period`: `14, 20`
- `atr_ma_window`: `40, 60`
- `buy_volatility_cap`: `1.00, 1.03, 1.05`
- `vol_breakout_mult`: `1.00, 1.03, 1.05`

#### 交易节奏

- `confirm_days`: `2, 3`
- `cooldown_days`: `8, 10, 15`
- `min_hold_bars`: `5, 8`

#### 风险层

- `regime_filter_ma`: `180, 240`
- `regime_filter_buffer`: `0.98, 1.00`
- `risk_drawdown_stop_threshold`: `0.12, 0.15`
- `risk_drawdown_lookback`: `180, 240`

#### 额外压频建议

- `atr_deadband`: `0.02, 0.05`
- `slope_threshold`: `0.01, 0.02`

#### 模板 A 的预期

理想情况下应该看到：

- 换手率下降
- whipsaw_rate 下降
- 收益不明显退化
- 最大回撤继续向 `-20%` 以内靠近

### 6.2 模板 B 建议

#### 均线

- `fast_ma`: `5, 10`
- `slow_ma`: `30, 60`

推荐优先测试：

- `5/30`
- `10/30`
- `5/60`
- `10/60`

#### ATR

- `atr_period`: `10, 14`
- `atr_ma_window`: `40`
- `buy_volatility_cap`: `1.00, 1.05`
- `vol_breakout_mult`: `1.05`

#### 交易节奏

- `confirm_days`: `1, 2`
- `cooldown_days`: `5, 8`
- `min_hold_bars`: `3`

#### 风险层

- `regime_filter_ma`: `120, 180, 240`
- `regime_filter_buffer`: `0.98`
- `risk_drawdown_stop_threshold`: `0.15, 0.18`
- `risk_drawdown_lookback`: `180, 240`

#### 额外压频建议

- `atr_confirm_enabled`: `true`
- `atr_deadband`: `0.03, 0.05`
- `slope_threshold`: `0.01`

#### 模板 B 的预期

理想情况下应该看到：

- 假信号减少
- 交易次数下降
- whipsaw_rate 下降
- 收益不掉到负值太多

## 7. 测试顺序

不要直接全量大网格。建议按下面顺序来。

### 7.1 第一轮：单元测试

先确认代码行为没坏。

推荐命令：

```bash
.venv/bin/python -m unittest tests.unit.test_investment_backtest
```

必须通过的点：

- 金叉买入逻辑
- 死叉卖出逻辑
- ATR 过滤逻辑
- 回撤停机逻辑
- 冷却期和最小持有期逻辑

### 7.2 第二轮：模板 A 烟雾测试

先只跑这些指数：

- `000001.SH`
- `000300.SH`
- `000905.SH`

原因：

- 它们代表典型的大盘/宽基行为
- 能最快看出参数是不是过慢或过快

推荐命令：

```bash
.venv/bin/python scripts/tune_ma_atr_only.py \
  --symbols 000001.SH,000300.SH,000905.SH \
  --start-date 2012-01-01 \
  --end-date 2025-12-31 \
  --workers 30 \
  --output output/ma_atr_template_a_smoke
```

### 7.3 第三轮：模板 B 烟雾测试

先只跑这些指数：

- `399006.SZ`
- `000852.SH`
- `932000.SH`

原因：

- 它们代表高波动测试场景
- 最容易暴露换手、whipsaw 和回撤问题

推荐命令：

```bash
.venv/bin/python scripts/tune_ma_atr_only.py \
  --symbols 399006.SZ,000852.SH,932000.SH \
  --start-date 2012-01-01 \
  --end-date 2025-12-31 \
  --workers 30 \
  --output output/ma_atr_template_b_smoke
```

### 7.4 第四轮：全量测试

最后再跑 8 个指数全量：

- `000001.SH`
- `399001.SZ`
- `399006.SZ`
- `000016.SH`
- `000300.SH`
- `000905.SH`
- `000852.SH`
- `932000.SH`

推荐命令：

```bash
.venv/bin/python scripts/tune_ma_atr_only.py \
  --start-date 2012-01-01 \
  --end-date 2025-12-31 \
  --workers 30 \
  --output output/ma_atr_template_full
```

## 8. 怎么判断结果好坏

### 8.1 模板 A 通过标准

大盘/宽基模板更看重“稳”：

- 年化超额收益不低于当前基线
- 最大回撤不要明显恶化
- `turnover_rate` 和 `whipsaw_rate` 要比当前基线更低
- `trade_count` 不能太高

建议目标：

- `turnover_rate` 尽量往 `50%` 以下压
- `whipsaw_rate` 尽量往 `20%` 以下压
- `max_drawdown` 尽量靠近 `-15% ~ -20%`

### 8.2 模板 B 通过标准

高波动模板更看重“少犯错”：

- `trade_count` 明显低于当前高波指数基线
- `whipsaw_rate` 明显下降
- 收益不要因为过度保守而长期转负
- 回撤至少比当前高波基线更容易控制

建议目标：

- `turnover_rate` 比当前版本下降一档
- `whipsaw_rate` 比当前版本下降一档
- `max_drawdown` 不要比基线显著更差

## 9. 当前已知问题

测试时要特别注意这几个风险。

### 9.1 `turnover_cap` 仍然是主要卡点

当前结果里，`eligible` 大部分还是被 `turnover_cap` 拦住。

这通常说明：

- 换手率的统计口径和门槛定义还没统一
- 或者门槛本身太严格

所以测试结果里，`eligible=0` 不应该直接当成失败。

### 9.2 高波动指数天然难看

`399006.SZ`、`000852.SH`、`932000.SH` 往往比宽基更难稳定。

这不是坏消息，但意味着：

- 它们要单独设参
- 不要强求和大盘同一套参数

### 9.3 只调确认期不够

`round6` 和 `full_test` 已经说明：

- `confirm_days=2`
- `cooldown_days=5`
- `min_hold_bars=3`

这类参数已经接近收敛。

如果还想继续压频次，下一步应该测试：

- `atr_deadband`
- `atr_confirm_enabled`
- `slope_threshold`

这些参数更接近“信号层抑噪”，比单纯拉长冷却期更有效。

## 10. 建议的输出目录

后续每轮建议按下面命名：

- `output/ma_atr_template_a_smoke`
- `output/ma_atr_template_b_smoke`
- `output/ma_atr_template_full`

每次都保留：

- `summary/`
- `reports/`
- `plots/`

这样新旧对照会非常清楚。

## 11. 最后给新人的执行清单

1. 先跑单测。
2. 再跑模板 A 烟雾测试。
3. 再跑模板 B 烟雾测试。
4. 再跑全量 8 指数。
5. 每轮都对比 `round6` 基线。
6. 如果 `turnover_rate` 还是很高，优先启用 `atr_deadband`、`slope_threshold` 和 `atr_confirm_enabled`，不要只继续拉长 `cooldown_days`。

## 12. 结论

这份测试计划的核心目标只有一个：

- 把大盘/宽基和高波动指数分开测试
- 让每套模板都在自己的波动环境里收敛
- 以降低换手和 whipsaw 为主，但不能把收益打没

