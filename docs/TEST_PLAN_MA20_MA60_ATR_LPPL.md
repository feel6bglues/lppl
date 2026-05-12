# 双均线 + ATR + LPPL 疯狂状态机测试计划

日期：2026-03-29

## 1. 目标

本测试计划用于约束下一版指数投资策略的实现与验收。

策略目标固定为：

1. `MA20 / MA60` 作为主要趋势买卖框架
2. `ATR` 作为波动率确认与风险过滤
3. `LPPL` 作为核心“疯狂状态机”
4. 只有当 LPPL 进入`距离危险期 3 天内`时，策略才允许`清仓`

这意味着：

- 买入和卖出信号都必须由`双均线 + ATR`直接给出
- LPPL 不再负责日常买卖触发
- LPPL 负责识别顶部疯狂阶段，并在危险临近时提升风控级别
- `warning/watch` 不能直接等价为清仓

## 2. 策略定义

### 2.1 主信号层

主信号层由趋势和波动率共同决定：

- `MA20 > MA60` 且短均线斜率向上：多头环境
- `MA20 < MA60` 且短均线斜率向下：空头环境
- `ATR` 用于确认突破是否有效，以及控制高波动时期的目标仓位

### 2.2 LPPL 状态机层

LPPL 只做状态机，不直接主导日常买卖。

状态定义：

- `none`
- `watch`
- `warning`
- `danger`

交易含义：

- `watch`：只记录顶部疯狂观察状态，不改变主信号
- `warning`：允许收紧仓位上限，但不允许清仓
- `danger`：若 `days_left > 3`，最多只允许减仓
- `danger` 且 `days_left <= 3`：才允许清仓

这条规则是硬约束。

## 3. 参数范围

### 3.1 主信号参数

需要进入首轮优化的参数：

| 参数 | 候选范围 | 说明 |
| --- | --- | --- |
| `fast_ma` | `20` 固定 | 主策略要求固定 MA20 |
| `slow_ma` | `60` 固定 | 主策略要求固定 MA60 |
| `ma_slope_window` | `3, 5, 10` | 判断均线斜率 |
| `atr_period` | `10, 14, 20` | ATR 窗口 |
| `atr_filter_mode` | `absolute, relative` | 绝对 ATR 或 ATR/ATR_MA |
| `atr_ma_window` | `20, 40, 60` | ATR 相对过滤窗口 |
| `buy_atr_cap` | `1.00, 1.05, 1.10, 1.15` | 波动率过高是否延迟买入 |
| `sell_atr_trigger` | `1.00, 1.05, 1.10` | 高波动确认卖出 |
| `cross_confirm_days` | `1, 2, 3` | 均线交叉确认期 |
| `cooldown_days` | `3, 5, 8, 10` | 交易冷却期 |

### 3.2 LPPL 状态机参数

首轮优化只保留状态机相关参数，不让 LPPL 重新回到主信号层。

| 参数 | 候选范围 | 说明 |
| --- | --- | --- |
| `window_family` | `narrow, standard, macro` | LPPL 观察窗口家族 |
| `step` | `5, 10, 20` | 扫描频率 |
| `r2_threshold` | `0.40, 0.45, 0.50` | 主拟合阈值 |
| `danger_r2_offset` | `0.00, -0.02, -0.05` | danger 放宽量 |
| `watch_days` | `10, 15, 20, 25` | 顶部观察期 |
| `warning_days` | `5, 8, 10, 12` | 顶部预警期 |
| `danger_days` | `3, 5, 7` | 顶部危险期 |
| `full_exit_days` | `3` 固定 | 只有 3 天内允许清仓 |

约束条件：

- `watch_days > warning_days > danger_days > full_exit_days`
- `full_exit_days` 固定为 `3`

### 3.3 仓位参数

建议固定为阶梯仓位：

- `0.0`
- `0.5`
- `1.0`

规则：

- 主买入信号成立：`0.0 -> 0.5 -> 1.0`
- 主卖出信号成立：`1.0 -> 0.5 -> 0.0`
- LPPL `warning` 只允许把满仓压到半仓，不允许直接清零
- LPPL `danger` 且 `days_left <= 3` 才允许 `0.5 -> 0.0` 或 `1.0 -> 0.0`

## 4. 信号逻辑测试

### 4.1 买入逻辑

必须验证：

1. `MA20` 上穿 `MA60` 后，若 ATR 未超限，能生成 `buy`
2. 若 ATR 超出 `buy_atr_cap`，则交叉成立但不买入
3. 若 `cross_confirm_days > 1`，交叉未持续足够天数不得买入
4. 若当前已持有半仓，再次满足买入条件只允许 `add`
5. LPPL 处于 `watch/warning` 时，不能阻断正常底部趋势买入，除非仓位上限被显式压缩

### 4.2 卖出逻辑

必须验证：

1. `MA20` 下穿 `MA60` 后，若 ATR 达到卖出确认，能生成 `reduce/sell`
2. 若交叉成立但 ATR 未确认，卖出信号不应过早触发
3. 当前满仓时首次卖出只允许 `reduce`
4. 再次卖出确认后才允许 `sell`
5. LPPL `warning` 可收缩仓位上限，但不能直接清仓
6. LPPL `danger` 但 `days_left > 3` 时，不能清仓
7. LPPL `danger` 且 `days_left <= 3` 时，允许清仓覆盖主策略

### 4.3 LPPL 状态机逻辑

必须验证：

1. `watch` 不会直接触发交易
2. `warning` 不会直接触发清仓
3. `danger` 不会在 `days_left > 3` 时触发清仓
4. `danger` 在 `days_left <= 3` 时可触发清仓
5. 若 LPPL 状态消失，仓位控制恢复到主信号层
6. 同一顶部 regime 内不允许重复清仓

## 5. 单元测试计划

### 5.1 指标计算

新增或重构后必须覆盖：

- `MA20`
- `MA60`
- 均线交叉方向
- ATR
- ATR/ATR_MA
- LPPL `watch/warning/danger`
- `danger <= 3天` 判定

### 5.2 信号函数

需要新增单元测试：

1. `golden_cross + ATR pass -> buy`
2. `golden_cross + ATR fail -> hold`
3. `death_cross + ATR pass -> reduce`
4. `death_cross + ATR fail -> hold`
5. `LPPL watch -> hold`
6. `LPPL warning -> reduce only`
7. `LPPL danger but >3 days -> reduce only`
8. `LPPL danger and <=3 days -> sell`
9. `cooldown` 生效
10. `confirm_days` 生效
11. `flat/half/full` 仓位阶梯正确

### 5.3 回测执行

必须验证：

1. `hold` 日不再交易
2. 只有 `target_position` 变化时才交易
3. 手续费与滑点计入正确
4. 空仓不能卖出
5. 已满仓不能重复买入
6. LPPL 清仓优先级高于普通 `reduce`

## 6. 集成测试计划

### 6.1 单指数最小链路

每只指数都要打通：

`行情 -> 指标 -> LPPL状态 -> 主信号 -> 仓位 -> 回测 -> CSV输出`

至少验证：

- `000300.SH`
- `000905.SH`
- `399006.SZ`

原因：

- `000300.SH` 代表大盘权重
- `000905.SH` 代表宽基中盘
- `399006.SZ` 代表高弹性成长

### 6.2 八指数全量链路

需要跑全量 8 指数：

- `000001.SH`
- `399001.SZ`
- `399006.SZ`
- `000016.SH`
- `000300.SH`
- `000905.SH`
- `000852.SH`
- `932000.SH`

输出要求：

- 每指数单独 summary
- 合并 summary
- 净值曲线
- 回撤曲线
- 交易明细
- LPPL 状态分布统计

## 7. 参数优化测试计划

### 7.1 优化阶段拆分

参数优化分 3 阶段，不允许一次性全参数混搜。

#### 阶段 A：主信号层

只优化：

- `atr_period`
- `atr_ma_window`
- `buy_atr_cap`
- `sell_atr_trigger`
- `cross_confirm_days`
- `cooldown_days`

LPPL 固定为保守状态机模板。

目标：

- 找到双均线 + ATR 本身是否能形成正向 alpha

#### 阶段 B：LPPL 状态机层

固定阶段 A 最优主信号参数，只优化：

- `window_family`
- `step`
- `r2_threshold`
- `danger_r2_offset`
- `watch_days`
- `warning_days`
- `danger_days`

目标：

- 找到 LPPL 对顶部风险控制的最优补充方式

#### 阶段 C：仓位层

固定前两阶段，只优化：

- `warning` 是否 `reduce`
- `warning` 的仓位上限
- `danger > 3天` 的仓位上限
- `danger <= 3天` 的清仓规则

目标：

- 把 LPPL 状态机转成最优仓位映射

### 7.2 优化评分指标

最终评分必须同时看：

- `annualized_excess_return`
- `max_drawdown`
- `calmar_ratio`
- `trade_count`
- `turnover_rate`
- `whipsaw_rate`

推荐硬门槛：

- `annualized_excess_return > 0`
- `trade_count >= 3`
- `max_drawdown > -0.35`

高弹性指数允许适度放宽：

- `max_drawdown > -0.40`

### 7.3 稳定性检查

每个候选参数都必须验证：

1. 不同时间子样本是否稳定
2. 不同指数风格下是否过拟合
3. 最优解是否只是尖峰点
4. 改善是否来自极少数交易

## 8. 回测口径

回测口径固定：

1. 日频
2. 第 `t` 日信号，第 `t+1` 日执行
3. `hold` 日不再平衡
4. 手续费和滑点固定计入
5. 不能使用未来函数

## 9. 验收标准

### 9.1 逻辑验收

必须满足：

1. 买卖信号由 `MA20/MA60 + ATR` 直接生成
2. LPPL 仅作为状态机，不负责日常买入
3. 只有 `danger <= 3天` 才允许清仓

### 9.2 结果验收

至少满足以下之一，才进入下一步生产候选：

1. `000300.SH` 或 `000016.SH` 保持正超额且回撤不劣化
2. `000905.SH` 保持正超额且回撤收敛
3. 高弹性组至少 1 只出现“超额改善且回撤不恶化”

### 9.3 失败标准

若出现以下任一情况，则判定该版本失败：

1. `warning` 重新变成事实上的提前清仓
2. 交易次数暴增但超额收益不改善
3. 回撤下降只是因为长期空仓
4. LPPL 状态机重新变成主交易引擎

## 10. 建议实现顺序

1. 抽离 `MA20/MA60 cross` 主信号函数
2. 抽离 `ATR buy/sell filter` 函数
3. 抽离 `LPPL state machine overlay`
4. 单元测试先落地
5. 跑 3 指数集成测试
6. 跑 8 指数全量回测
7. 再做参数优化

## 11. 计划输出物

下一步实现后，主目录和 `output/` 至少应生成：

- 策略说明文档
- 参数搜索结果 CSV
- 八指数汇总 CSV
- 净值图
- 回撤图
- LPPL 状态分布表
- 可读复盘报告

这份文档是下一轮实现和测试的唯一验收基线。
EOF","workdir":"/home/james/Documents/Project/lppl","yield_time_ms":1000,"max_output_tokens":4000} บาคาร่ to=functions.exec_command մեկնաբանություն code 0: Success? Actually exec output not shown yet?
