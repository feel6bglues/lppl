# LPPL 参数总表与状态实验复盘

日期：2026-03-29

## 1. 当前参数源

当前项目里有 3 层参数源：

1. 代码默认值
2. `config/optimal_params.yaml` 的默认项和逐指数覆盖项
3. 实验轮次中的临时覆盖项

这三层里，真正参与运行时的优先级是：

`实验覆盖 > symbol YAML > defaults YAML > 代码默认值`

## 2. 代码默认参数

### 2.1 LPPLConfig 默认参数
来源：[src/lppl_engine.py](/home/james/Documents/Project/lppl/src/lppl_engine.py:34)

| 参数 | 当前默认值 | 说明 |
| --- | --- | --- |
| `window_range` | `range(40, 100, 20)` | 默认窗口集合 |
| `optimizer` | `de` | LPPL 优化器 |
| `maxiter` | `100` | 差分进化迭代数 |
| `popsize` | `15` | 差分进化种群 |
| `tol` | `0.05` | 优化容忍度 |
| `m_bounds` | `(0.1, 0.9)` | LPPL `m` 参数边界 |
| `w_bounds` | `(6, 13)` | LPPL `w` 参数边界 |
| `tc_bound` | `(1, 100)` | 临界时间搜索边界 |
| `r2_threshold` | `0.5` | 顶部主阈值 |
| `danger_r2_offset` | `0.0` | `danger` 相对 `r2_threshold` 的偏移 |
| `danger_days` | `5` | 顶部危险窗口 |
| `warning_days` | `12` | 顶部预警窗口 |
| `watch_days` | `25` | 顶部观察窗口 |
| `consensus_threshold` | `0.15` | ensemble 共识阈值 |
| `n_workers` | `-1` | 自动并行 |

当前顶部状态机阈值：
- `danger`: `days_left < danger_days` 且 `r2 >= r2_threshold + danger_r2_offset`
- `warning`: `days_left < warning_days` 且 `r2 >= r2_threshold - 0.05`
- `watch`: `days_left < watch_days` 且 `r2 >= r2_threshold - 0.15`

来源：[src/lppl_engine.py](/home/james/Documents/Project/lppl/src/lppl_engine.py:81)

### 2.2 InvestmentSignalConfig 默认参数
来源：[src/investment/backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py:20)

| 参数 | 当前默认值 | 说明 |
| --- | --- | --- |
| `signal_model` | `multi_factor_v1` | 信号模型 |
| `initial_position` | `0.0` | 初始仓位 |
| `full_position` | `1.0` | 满仓 |
| `flat_position` | `0.0` | 空仓 |
| `half_position` | `0.5` | 半仓 |
| `strong_buy_days` | `20` | 强底部买入窗口 |
| `buy_days` | `40` | 底部买入窗口 |
| `strong_sell_days` | `20` | 强顶部卖出窗口 |
| `reduce_days` | `60` | 顶部减仓窗口 |
| `watch_days` | `25` | 观察窗口 |
| `warning_days` | `12` | 预警窗口 |
| `danger_r2_offset` | `0.0` | `danger` 的 R2 放宽偏移 |
| `warning_trade_enabled` | `True` | warning 是否允许直接参与交易 |
| `positive_consensus_threshold` | `0.25` | 顶部置信阈值 |
| `negative_consensus_threshold` | `0.20` | 底部置信阈值 |
| `danger_days` | `5` | 危险窗口 |
| `rebound_days` | `15` | 底部反弹窗口 |
| `trend_fast_ma` | `20` | 快均线 |
| `trend_slow_ma` | `120` | 慢均线 |
| `trend_slope_window` | `10` | 均线斜率窗口 |
| `atr_period` | `14` | ATR 窗口 |
| `atr_ma_window` | `60` | ATR 均值窗口 |
| `vol_breakout_mult` | `1.05` | 顶部波动率放大阈值 |
| `buy_volatility_cap` | `1.05` | 底部买入波动阈值 |
| `high_volatility_mult` | `1.15` | 高波动判定阈值 |
| `high_volatility_position_cap` | `0.5` | 高波动买入仓位上限 |
| `drawdown_confirm_threshold` | `0.05` | 顶部回撤确认 |
| `buy_reentry_drawdown_threshold` | `0.08` | 底部再入场回撤要求 |
| `buy_reentry_lookback` | `20` | 再入场回看窗口 |
| `buy_trend_slow_buffer` | `0.98` | 买入时对慢均线缓冲 |
| `buy_vote_threshold` | `3` | 买入票数阈值 |
| `sell_vote_threshold` | `3` | 卖出票数阈值 |
| `buy_confirm_days` | `2` | 买入确认天数 |
| `sell_confirm_days` | `2` | 卖出确认天数 |
| `cooldown_days` | `15` | 冷却期 |
| `post_sell_reentry_cooldown_days` | `10` | 卖后再入场阻断期 |
| `min_hold_bars` | `0` | 最少持有期 |
| `allow_top_risk_override_min_hold` | `True` | 顶部高危覆盖最少持有 |
| `enable_regime_hysteresis` | `True` | regime 滞后控制 |
| `require_trend_recovery_for_buy` | `True` | 买入需要趋势修复 |

## 3. YAML 当前生效参数
来源：[config/optimal_params.yaml](/home/james/Documents/Project/lppl/config/optimal_params.yaml:1)

### 3.1 defaults 段

| 参数 | 当前值 |
| --- | --- |
| `optimizer` | `lbfgsb` |
| `lookahead_days` | `60` |
| `drop_threshold` | `0.10` |
| `ma_window` | `5` |
| `max_peaks` | `10` |
| `signal_model` | `multi_factor_v1` |
| `initial_position` | `0.0` |
| `positive_consensus_threshold` | `0.25` |
| `negative_consensus_threshold` | `0.20` |
| `rebound_days` | `15` |
| `trend_fast_ma` | `20` |
| `trend_slow_ma` | `120` |
| `trend_slope_window` | `10` |
| `atr_period` | `14` |
| `atr_ma_window` | `60` |
| `vol_breakout_mult` | `1.05` |
| `buy_volatility_cap` | `1.05` |
| `drawdown_confirm_threshold` | `0.05` |
| `buy_vote_threshold` | `3` |
| `sell_vote_threshold` | `3` |
| `buy_confirm_days` | `2` |
| `sell_confirm_days` | `2` |
| `cooldown_days` | `15` |
| `require_trend_recovery_for_buy` | `true` |

### 3.2 当前 symbol 覆盖值

| 指数 | step | window_set | r2 | consensus | danger_days | pos_th | neg_th | sell_votes | buy_votes | sell_confirm | buy_confirm | cooldown | 其他 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `000001.SH` | 120 | `narrow_40_120` | 0.50 | 0.20 | 20 | 0.25 | 0.20 | 3 | 3 | 2 | 2 | 20 | - |
| `399001.SZ` | 120 | `wide_30_180` | 0.50 | 0.30 | 20 | 0.25 | 0.20 | 2 | 3 | 2 | 2 | 15 | `vol_breakout_mult=1.03` |
| `399006.SZ` | 60 | `wide_30_180` | 0.50 | 0.30 | 20 | 0.20 | 0.20 | 2 | 3 | 1 | 2 | 10 | `vol_breakout_mult=1.02`, `drawdown_confirm_threshold=0.08` |
| `000016.SH` | 60 | `wide_30_180` | 0.50 | 0.20 | 20 | 0.25 | 0.20 | 2 | 3 | 2 | 2 | 15 | `vol_breakout_mult=1.00`, `buy_volatility_cap=1.00`, `drawdown_confirm_threshold=0.08` |
| `000300.SH` | 120 | `narrow_40_120` | 0.50 | 0.25 | 20 | 0.30 | 0.20 | 2 | 3 | 2 | 2 | 10 | `vol_breakout_mult=1.00`, `buy_volatility_cap=1.00`, `drawdown_confirm_threshold=0.08` |
| `000905.SH` | 120 | `narrow_40_120` | 0.50 | 0.20 | 20 | 0.20 | 0.20 | 2 | 3 | 2 | 2 | 15 | `vol_breakout_mult=1.03` |
| `000852.SH` | 120 | `narrow_40_120` | 0.50 | 0.20 | 20 | 0.20 | 0.20 | 2 | 3 | 1 | 2 | 10 | `vol_breakout_mult=1.02`, `drawdown_confirm_threshold=0.08` |
| `932000.SH` | 20 | `narrow_40_120` | 0.50 | 0.25 | 20 | 0.20 | 0.20 | 2 | 3 | 1 | 2 | 10 | `vol_breakout_mult=1.02`, `drawdown_confirm_threshold=0.08` |

说明：
- `000016.SH` 与 `000300.SH` 的参数已经按 round2 写回 YAML。
- `000905.SH` 虽然在 round4 首次达到 `eligible=True`，但还没有写回 YAML。

## 4. 已完成实验轮次复盘

### 4.1 Round2 原子化调优
来源：[optimal8_signal_tuning_round2_summary_20260329.csv](/home/james/Documents/Project/lppl/output/signal_tuning_round2_complete/summary/optimal8_signal_tuning_round2_summary_20260329.csv)

结论：
- `000016.SH` 可升级：`annualized_excess_return=3.08%`, `max_drawdown=-28.09%`
- `000300.SH` 可升级：`annualized_excess_return=2.96%`, `max_drawdown=-17.09%`
- 其余 6 只不达标

失败分型：
- 低信号：`000001.SH`, `399001.SZ`, `000905.SH`
- 高风险：`399006.SZ`, `000852.SH`, `932000.SH`

### 4.2 Round3 放宽 LPPL
来源：[remaining6_signal_tuning_round3_summary_20260329.csv](/home/james/Documents/Project/lppl/output/signal_tuning_round3_relaxed/combined/summary/remaining6_signal_tuning_round3_summary_20260329.csv)

结论：
- 没有新增可升级指数
- `000001.SH`、`399001.SZ` 仍然信号稀缺
- `399006.SZ`、`000905.SH`、`000852.SH` 放宽后质量恶化
- `932000.SH` 风险仍然过深

### 4.3 Round4 定向结构调优
来源：[round4_targeted_best_20260329.csv](/home/james/Documents/Project/lppl/output/signal_tuning_round4_targeted/summary/round4_targeted_best_20260329.csv)

结论：
- `000905.SH` 首次达到 `eligible=True`
- 最优参数：
  - `family=macro`
  - `step=40`
  - `r2_threshold=0.40`
  - `warning_days=80`
  - `danger_days=25`
  - `positive_consensus_threshold=0.15`
  - `negative_consensus_threshold=0.15`
  - `buy_vote_threshold=2`
  - `buy_confirm_days=1`
  - `sell_vote_threshold=2`
  - `sell_confirm_days=2`
  - `cooldown_days=8`
- 结果：`annualized_excess_return=0.88%`, `max_drawdown=-31.57%`, `trade_count=10`

说明：
- 这个结果说明 `000905.SH` 的问题主要是 LPPL 结构层过于保守。
- 但因为回撤仍偏大，尚未写回生产参数。

### 4.4 短 warning 首轮验证
来源：[short_warning_validation_8_summary_20260329.csv](/home/james/Documents/Project/lppl/output/backtest/short_warning/short_warning_validation/summary/short_warning_validation_8_summary_20260329.csv)

实验设定：
- 大盘：`watch=25`, `warning=12`, `danger=5`
- 宽基：`watch=20`, `warning=10`, `danger=4`
- 高弹性：`watch=15`, `warning=8`, `danger=3`
- 保持原始 `step=60/120` 不变

结论：
- `8/8` 全部失败
- `bubble_risk_count=0` 几乎全灭
- 直接证明：短 `warning/danger` 不能脱离扫描频率单独使用

### 4.5 短 warning + 固定 step=5
来源：[short_warning_validation_step5_8_summary_20260329.csv](/home/james/Documents/Project/lppl/output/backtest/short_warning/short_warning_validation_step5/summary/short_warning_validation_step5_8_summary_20260329.csv)

结论：
- `8/8` 仍全部失败
- 但 `000001.SH` 已经能打出 `bubble_risk_count=5`
- 说明之前确实有一部分问题来自 `step` 过粗
- 但 7/8 的 `bubble_risk_count` 仍为 0，说明 `danger` 仍过严

### 4.6 step=5 + relaxed danger
来源：[short_warning_validation_step5_relaxed_danger_8_summary_20260329.csv](/home/james/Documents/Project/lppl/output/backtest/short_warning/short_warning_validation_step5_relaxed_danger/summary/short_warning_validation_step5_relaxed_danger_8_summary_20260329.csv)

实验设定：
- 固定 `step=5`
- `danger_days` 放宽：
  - 大盘 `7`
  - 宽基 `6`
  - 高弹性 `5`
- `danger_r2_offset=-0.02`

结果：
- `eligible=0/8`
- `annualized_excess_return` 改善：`0/8`
- `max_drawdown` 改善：`0/8`
- `bubble_risk_count` 增加：`6/8`

结论：
- `danger` 判定之前确实偏严
- 但 `danger` 不是收益问题的主瓶颈
- 新增的 `bubble_risk` 大多没有改变真实交易路径

### 4.7 step=5 + relaxed danger + warning observe only
来源：[short_warning_validation_step5_warning_observe_only_8_summary_20260329.csv](/home/james/Documents/Project/lppl/output/backtest/short_warning/short_warning_validation_step5_warning_observe_only/summary/short_warning_validation_step5_warning_observe_only_8_summary_20260329.csv)

实验设定：
- 保持上一轮所有参数不变
- 唯一新增：`warning_trade_enabled=False`

结果：
- `eligible=0/8`
- 相比上一轮：
  - 超额收益改善：`5/8`
  - 回撤改善：`3/8`
  - 交易次数下降：`7/8`

逐类结论：
- 高弹性组改善更明显：`932000.SH`, `399006.SZ`, `000852.SH`
- 大盘/宽基并不适合完全关闭 warning：`000016.SH`, `000905.SH`, `000001.SH`
- `399001.SZ` 基本无变化，说明问题不在 warning 交易层

## 5. 当前最可信的结论

### 5.1 已经明确成立的结论

1. `warning_days` 不应像旧模型那样过长
2. 短 `warning/danger` 必须配合更密的扫描频率
3. `danger` 之前确实过严，但放宽 `danger` 本身不能改善收益
4. `warning` 过早交易，确实会吃掉一部分泡沫后段收益
5. 但 `warning` 完全不交易，也会让部分指数回撤重新放大

### 5.2 当前最合理的顶部状态机方向

下一步最值得验证的不是继续改 LPPL 检测层，而是交易映射层：

- `watch`: 只观察，不动仓
- `warning`: 只允许 `reduce`
- `danger`: 才允许 `sell`

原因：
- “warning 直接交易”太早
- “warning 完全不交易”又太晚
- 介于两者之间的轻减仓路径，目前最符合数据

## 6. 当前可复用参数模板

### 6.1 大盘权重组模板
适用：`000001.SH`, `000016.SH`, `000300.SH`

- `watch_days=25`
- `warning_days=12`
- `danger_days=7`
- `danger_r2_offset=-0.02`
- `step=5` 仅适合实验，不建议直接生产
- `warning_trade_enabled=False` 不适合作为最终生产形态

### 6.2 宽基平衡组模板
适用：`399001.SZ`, `000905.SH`

- `watch_days=20`
- `warning_days=10`
- `danger_days=6`
- `danger_r2_offset=-0.02`
- `399001.SZ` 问题不在 warning 交易，优先回到 LPPL 结构层
- `000905.SH` 结构调优比状态机调优更有效

### 6.3 高弹性组模板
适用：`399006.SZ`, `000852.SH`, `932000.SH`

- `watch_days=15`
- `warning_days=8`
- `danger_days=5`
- `danger_r2_offset=-0.02`
- warning 观察化对收益修复更敏感
- 但仍需要保留某种提前减仓能力

## 7. 当前建议的下一实验

最优先建议：

1. 保持 `step=5`
2. 保持 `danger_r2_offset=-0.02`
3. 保持当前 `watch/warning/danger` 窗口
4. 改成：
   - `watch -> hold`
   - `warning -> reduce only`
   - `danger -> sell`
5. 再跑 8 指数对照验证

这是目前最有信息增益的一轮实验。
