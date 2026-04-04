# 新手继续执行手册

日期：2026-03-30

适用范围：

1. 你刚接手这个 LPPL 指数项目
2. 你要继续做策略测试，而不是从头理解全部代码
3. 你希望知道"下一步该跑什么、看什么结果、如何判断对错"

这份文档不是研究笔记。它是执行手册。

## 1. 先看结论

当前项目已经做过几类测试，结论可以直接记成 4 句话：

1. 只靠 LPPL 过早预警，会把很多有效收益提前让掉。
2. 只靠放宽 LPPL，会把交易放大成高换手、低质量信号。
3. 只靠双均线 + ATR，能产生交易，但还没稳定打出 8 指数的合格结果。
4. **当前策略转向：移除 LPPL 状态机，纯 MA 均线交叉 + ATR 波动率测试。**

当前 8 指数有效性测试结果（MA20/60 + ATR + LPPL 版）：

- `eligible = 0/8`
- 最接近通过的指数：
  - `000016.SH`
  - `000300.SH`
  - `000905.SH`

---

## 2. 当前已经完成了什么

### 2.1 已经实现的功能

项目当前具备这些能力：

1. 指数日线数据读取
2. LPPL 检测
3. 指数投资分析
4. 净值曲线和回撤曲线输出
5. 日 K 线叠加信号图
6. 单元测试和集成测试
7. 多轮参数调优

### 2.2 当前有效的策略模型

当前已经加进代码里的新模型是：

- `ma_cross_atr_lppl_v1`

它的含义是：

1. `MA20 / MA60` 负责主买卖
2. `ATR` 负责波动确认和风险过滤
3. `LPPL` 只负责顶部疯狂状态机
4. 只有 `LPPL danger <= 3 天` 才允许清仓

### 2.3 当前可以直接复用的文档

1. [双均线 + ATR + LPPL 疯狂状态机测试计划](../TEST_PLAN_MA20_MA60_ATR_LPPL.md)
2. [LPPL 参数总表与状态实验复盘](./lppl_signal_experiment_retro_20260329.md)

---

## 3. 新测试方向：纯 MA 交叉 + ATR（移除 LPPL）

### 3.1 为什么移除 LPPL

1. LPPL 过早预警会牺牲收益
2. LPPL 参数调优空间有限
3. 纯技术指标更稳定、更易解释

### 3.2 策略定义

**模型名称**：`ma_cross_atr_v1`

**核心逻辑**：

1. 快线上穿慢线（金叉）+ ATR 低波动 → 买入
2. 快线下穿慢线（死叉）+ ATR 高波动 → 卖出
3. ATR 用于过滤假突破和控制仓位

### 3.3 MA 常量设置

| 快线候选 | 慢线候选 |
|----------|----------|
| MA5 | MA30 |
| MA10 | MA120 |
| MA20 | MA250 |
| MA30 | - |

**交叉组合矩阵**（快线 < 慢线）：

| 快线 \ 慢线 | MA30 | MA120 | MA250 |
|-------------|------|-------|-------|
| MA5 | 5/30 | 5/120 | 5/250 |
| MA10 | 10/30 | 10/120 | 10/250 |
| MA20 | 20/30 | 20/120 | 20/250 |
| MA30 | - | 30/120 | 30/250 |

**共 11 组合**需测试。

### 3.4 ATR 波动率分层

| 层级 | 条件 | 交易含义 |
|------|------|----------|
| 低波动 | `atr_ratio <= 1.05` | 允许买入 |
| 中波动 | `1.05 < atr_ratio < 1.15` | 观察 |
| 高波动 | `atr_ratio >= 1.15` | 卖出确认 |

**参数定义**：

- `atr_period`：ATR 计算窗口（默认 14）
- `atr_ma_window`：ATR 均值窗口（默认 40）
- `atr_ratio` = `ATR / ATR_MA`
- `buy_volatility_cap`：买入时 ATR 上限（默认 1.05）
- `vol_breakout_mult`：卖出时 ATR 触发（默认 1.15）

---

## 4. 测试方案

### 4.1 轮次一：单指数 Smoke Test

**目的**：验证代码链路能跑通。

**测试指数**：`000300.SH`

**测试组合**：`MA20 / MA60`

**测试参数**：

```python
{
    'signal_model': 'ma_cross_atr_v1',
    'trend_fast_ma': 20,
    'trend_slow_ma': 60,
    'atr_period': 14,
    'atr_ma_window': 40,
    'buy_volatility_cap': 1.05,
    'vol_breakout_mult': 1.15,
    'buy_confirm_days': 1,
    'sell_confirm_days': 1,
    'cooldown_days': 5,
    'initial_position': 0.0,
}
```

**运行命令**：

```bash
.venv/bin/python index_investment_analysis.py \
  --symbol 000300.SH \
  --start-date 2020-01-01 \
  --end-date 2026-03-27 \
  --step 5 \
  --signal-model ma_cross_atr_v1 \
  --fast-ma 20 \
  --slow-ma 60 \
  --output output/ma_cross_atr_smoke
```

**判断标准**：

1. 目录能生成
2. CSV 能打开
3. 报告能生成
4. 结果里有交易，不是全程空仓

### 4.2 轮次二：全 MA 组合扫描

**目的**：找到最优 MA 交叉组合。

**测试指数**：`000300.SH`

**测试组合**：全部 11 个 MA 组合

**固定参数**：

```python
{
    'signal_model': 'ma_cross_atr_v1',
    'atr_period': 14,
    'atr_ma_window': 40,
    'buy_volatility_cap': 1.05,
    'vol_breakout_mult': 1.15,
    'buy_confirm_days': 1,
    'sell_confirm_days': 1,
    'cooldown_days': 5,
    'initial_position': 0.0,
}
```

**扫描参数**：

| 快线 | 慢线 |
|------|------|
| 5, 10, 20, 30 | 30, 120, 250 |

**运行脚本**：

```bash
.venv/bin/python - <<'PY'
from src.data.manager import DataManager
from src.investment import InvestmentSignalConfig, BacktestConfig, generate_investment_signals, run_strategy_backtest
import pandas as pd
import itertools

symbol = '000300.SH'
fast_mas = [5, 10, 20, 30]
slow_mas = [30, 120, 250]
manager = DataManager()
df = manager.get_data(symbol)

results = []
for fast_ma, slow_ma in itertools.product(fast_mas, slow_mas):
    if fast_ma >= slow_ma:
        continue
    
    signal_cfg = InvestmentSignalConfig.from_mapping(symbol, {
        'signal_model': 'ma_cross_atr_v1',
        'trend_fast_ma': fast_ma,
        'trend_slow_ma': slow_ma,
        'atr_period': 14,
        'atr_ma_window': 40,
        'buy_volatility_cap': 1.05,
        'vol_breakout_mult': 1.15,
        'buy_confirm_days': 1,
        'sell_confirm_days': 1,
        'cooldown_days': 5,
    })
    
    signal_df = generate_investment_signals(
        df=df,
        symbol=symbol,
        signal_config=signal_cfg,
        lppl_config=None,  # 无 LPPL
        use_ensemble=False,
        start_date='2020-01-01',
        end_date='2026-03-27',
        scan_step=5,
    )
    
    equity_df, trades_df, summary = run_strategy_backtest(
        signal_df,
        BacktestConfig(
            initial_capital=1_000_000.0,
            buy_fee=0.0003,
            sell_fee=0.0003,
            slippage=0.0005,
            start_date='2020-01-01',
            end_date='2026-03-27',
        ),
    )
    
    results.append({
        'fast_ma': fast_ma,
        'slow_ma': slow_ma,
        'annualized_excess_return': summary['annualized_excess_return'],
        'max_drawdown': summary['max_drawdown'],
        'trade_count': summary['trade_count'],
        'eligible': summary.get('eligible', False),
    })
    print(f"MA{fast_ma}/MA{slow_ma}: excess={summary['annualized_excess_return']:.2%}, drawdown={summary['max_drawdown']:.2%}, trades={summary['trade_count']}")

results_df = pd.DataFrame(results)
results_df.to_csv('output/ma_cross_atr_smoke/ma_combination_scan.csv', index=False)
print("\n最优组合:")
print(results_df.sort_values('annualized_excess_return', ascending=False).head(5))
PY
```

**输出文件**：

- `output/ma_cross_atr_smoke/ma_combination_scan.csv`
- 终端打印最优 5 组合

### 4.3 轮次三：8 指数全量测试

**目的**：验证最优组合在全指数上的稳定性。

**测试指数**：全部 8 个

**测试组合**：轮次二选出的前 3 个最优组合

**运行脚本**：

```bash
.venv/bin/python - <<'PY'
from src.data.manager import DataManager
from src.investment import InvestmentSignalConfig, BacktestConfig, generate_investment_signals, run_strategy_backtest
import pandas as pd

symbols = ['000001.SH','399001.SZ','399006.SZ','000016.SH','000300.SH','000905.SH','000852.SH','932000.SH']
manager = DataManager()

# 从轮次二结果读取最优组合
best_combos = [
    {'fast_ma': 20, 'slow_ma': 60},  # 示例，需替换为实际最优
    {'fast_ma': 10, 'slow_ma': 30},
    {'fast_ma': 5, 'slow_ma': 120},
]

for combo in best_combos:
    fast_ma = combo['fast_ma']
    slow_ma = combo['slow_ma']
    print(f"\n{'='*60}")
    print(f"测试组合: MA{fast_ma}/MA{slow_ma}")
    print(f"{'='*60}")
    
    results = []
    for symbol in symbols:
        df = manager.get_data(symbol)
        if df is None or df.empty:
            print(f"{symbol}: 数据缺失")
            continue
        
        signal_cfg = InvestmentSignalConfig.from_mapping(symbol, {
            'signal_model': 'ma_cross_atr_v1',
            'trend_fast_ma': fast_ma,
            'trend_slow_ma': slow_ma,
            'atr_period': 14,
            'atr_ma_window': 40,
            'buy_volatility_cap': 1.05,
            'vol_breakout_mult': 1.15,
            'buy_confirm_days': 1,
            'sell_confirm_days': 1,
            'cooldown_days': 5,
        })
        
        signal_df = generate_investment_signals(
            df=df,
            symbol=symbol,
            signal_config=signal_cfg,
            lppl_config=None,
            use_ensemble=False,
            start_date='2020-01-01',
            end_date='2026-03-27',
            scan_step=5,
        )
        
        equity_df, trades_df, summary = run_strategy_backtest(
            signal_df,
            BacktestConfig(
                initial_capital=1_000_000.0,
                buy_fee=0.0003,
                sell_fee=0.0003,
                slippage=0.0005,
                start_date='2020-01-01',
                end_date='2026-03-27',
            ),
        )
        
        results.append({
            'symbol': symbol,
            'fast_ma': fast_ma,
            'slow_ma': slow_ma,
            'annualized_excess_return': summary['annualized_excess_return'],
            'max_drawdown': summary['max_drawdown'],
            'trade_count': summary['trade_count'],
            'eligible': summary.get('eligible', False),
        })
        print(f"{symbol}: excess={summary['annualized_excess_return']:.2%}, drawdown={summary['max_drawdown']:.2%}, trades={summary['trade_count']}")
    
    results_df = pd.DataFrame(results)
    results_df.to_csv(f'output/ma_cross_atr_fulltest/ma{fast_ma}_ma{slow_ma}_fulltest.csv', index=False)
    print(f"\neligible: {results_df['eligible'].sum()}/8")
PY
```

### 4.4 轮次四：ATR 波动率参数优化

**目的**：找到最优 ATR 阈值。

**测试指数**：`000300.SH`

**测试组合**：轮次二最优组合

**扫描参数**：

| 参数 | 候选值 |
|------|--------|
| `atr_period` | 10, 14, 20 |
| `atr_ma_window` | 20, 40, 60 |
| `buy_volatility_cap` | 1.00, 1.05, 1.10 |
| `vol_breakout_mult` | 1.05, 1.10, 1.15 |

---

## 5. 评价指标

### 5.1 核心指标

| 指标 | 含义 | 门槛 |
|------|------|------|
| `annualized_excess_return` | 年化超额收益 | > 0% |
| `max_drawdown` | 最大回撤 | > -35% |
| `trade_count` | 交易次数 | >= 3 |
| `eligible` | 是否达标 | True |

### 5.2 辅助指标

| 指标 | 含义 |
|------|------|
| `turnover_rate` | 换手率 |
| `whipsaw_rate` | 震荡率 |
| `calmar_ratio` | 超额/回撤比 |

### 5.3 分组评价标准

| 指数组 | 代表指数 | 超额门槛 | 回撤门槛 |
|--------|----------|----------|----------|
| 大盘权重 | 000001.SH, 000016.SH, 000300.SH | > 0% | > -35% |
| 宽基平衡 | 399001.SZ, 000905.SH | > 0% | > -35% |
| 高弹性 | 399006.SZ, 000852.SH, 932000.SH | > 0% | > -40% |

### 5.4 合格标准

- `eligible = True` 当且仅当：
  - `annualized_excess_return > 0`
  - `max_drawdown > -35%`（高弹性组 > -40%）
  - `trade_count >= 3`

---

## 6. 每一轮测试看什么

### 6.1 功能测试

只看这 4 个点：

1. 是否能成功生成 CSV
2. 是否能成功生成报告
3. 是否有交易记录
4. 是否没有报错

### 6.2 策略有效性测试

必须看这 6 个指标：

1. `annualized_excess_return`
2. `max_drawdown`
3. `trade_count`
4. `turnover_rate`
5. `whipsaw_rate`
6. `eligible`

### 6.3 组合扫描测试

必须看：

1. 哪个组合 `eligible` 最多
2. 哪个组合 `annualized_excess_return` 最高
3. 哪个组合 `max_drawdown` 最小
4. 交易次数是否稳定（不是极端值）

---

## 7. 你现在应该怎么继续

按这个顺序做：

1. 先跑单指数 smoke test（轮次一）
2. 跑全 MA 组合扫描（轮次二）
3. 选前 3 组合跑 8 指数（轮次三）
4. 选最优组合跑 ATR 参数优化（轮次四）
5. 检查 `output/` 下的 CSV 和报告
6. 只看 `annualized_excess_return / max_drawdown / trade_count / eligible`

---

## 8. 结果判断规则

### 8.1 可以继续的情况

满足任意一条，就可以继续优化：

1. 某只指数出现正超额，但回撤仍不合格
2. 某只指数回撤明显改善，但超额收益还没转正
3. 交易次数稳定，不是全程空仓

### 8.2 暂停的情况

满足任意一条，就先暂停看模型：

1. 交易次数暴增，但超额收益恶化
2. 回撤改善主要来自空仓，而不是信号质量
3. 所有组合 `eligible = 0/8`
4. 报告无法生成

---

## 9. 已经写回生产参数的指数

当前写回 `config/optimal_params.yaml` 的只有：

- `000016.SH`
- `000300.SH`

`000905.SH` 还没有写回。

---

## 10. 复用建议

如果以后还要继续做实验，建议直接复用这 3 份文档：

1. [新手继续执行手册](./beginner_execution_runbook.md)
2. [双均线 + ATR + LPPL 疯狂状态机测试计划](../TEST_PLAN_MA20_MA60_ATR_LPPL.md)
3. [LPPL 参数总表与状态实验复盘](./lppl_signal_experiment_retro_20260329.md)

这三份文档分别回答：

1. 现在怎么做
2. 应该做什么
3. 为什么这么做
