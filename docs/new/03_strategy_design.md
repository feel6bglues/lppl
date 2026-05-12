# 策略设计与规则

## 3.1 最终策略架构

```
输入: OHLCV数据
  │
  ▼
┌─────────────────────────────────────┐
│ Layer 1: 市场制度分类               │
│   close / MA60 > 1.03  →  Bull     │
│   close / MA60 < 0.97  →  Bear     │
│   其余                   →  Range   │
└─────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────┐
│ Layer 2: 基础仓位 (纯制度策略)       │
│   Bull  →  85%                      │
│   Range →  50%                      │
│   Bear  →  0%                       │
└─────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────┐
│ Layer 3: Wyckoff相位微调 (增量)     │
│   Markup  +  Bull → +10% (max 95%) │
│   Markdown + 任意 → 0%              │
│   Accum + Range → +10% (to 60%)     │
│   Distrib + Range → -20% (to 30%)  │
└─────────────────────────────────────┘
  │
  ▼
输出: 仓位信号 (0% ~ 95%)
```

## 3.2 纯制度策略 (核心, 25.6%年化)

### 规则

```python
def regime_signal(closes, ma_period=60, threshold=0.01):
    """纯制度策略: 3行规则"""
    ma = MA(closes, ma_period)          # MA60
    ratio = closes[-1] / ma[-1]
    
    if   ratio > 1 + threshold:  return 0.85   # Bull → 85%
    elif ratio < 1 - threshold:  return 0.00   # Bear → 0% (空仓)
    else:                        return 0.50   # Range → 50%
```

### 逻辑解释

- **牛市 (Bull)**: 价格超过MA60的1%以上 → 市场处于上升趋势, 85%仓位
- **熊市 (Bear)**: 价格低于MA60的1%以上 → 市场处于下降趋势, 空仓
- **盘整 (Range)**: 价格在MA60附近 ±1% → 市场方向不明, 半仓

## 3.3 Wyckoff相位增强 (增量+3.3%)

### 相位分类规则 (基于原始analyzer.py:810-903)

```python
def wyckoff_phase(closes, ma5, ma20, short_trend, rel_pos):
    """
    从 src/wyckoff/analyzer.py 提取的核心规则
    
    Parameters:
        closes: 收盘价序列
        ma5: MA5序列
        ma20: MA20序列
        short_trend: 近20日涨跌幅
        rel_pos: 近60日价格位置 (0~1)
    """
    # 1. TR (Trading Range) 检测
    lo60 = min(closes[-60:])
    hi60 = max(closes[-60:])
    total_range = (hi60 - lo60) / lo60
    in_tr = total_range <= 0.30 and 0.25 <= rel_pos <= 0.75
    
    if in_tr:
        # TR内: 看TR前趋势
        prior = prices[-60] / prices[-100] - 1
        if prior < -0.10:     return "accumulation"
        elif prior > 0.10:    return "distribution"
        elif rel_pos <= 0.40: return "accumulation"
        else:                 return "unknown"
    else:
        # 非TR: 看短期趋势
        if short_trend >= 0.03 and close > ma20 and ma5 >= ma20:
            return "markup"
        elif short_trend >= 0.03 and close > ma5 and rel_pos >= 0.50:
            return "markup"
        elif short_trend <= -0.03 and close < ma20:
            return "markdown"
        elif short_trend <= -0.04 and rel_pos <= 0.20:
            return "markdown"
        else:
            return "unknown"
```

### 相位→仓位调整规则

| 制度 | 相位 | 调整 | 最终仓位 | 逻辑 |
|------|------|------|---------|------|
| Bull | markup | +10% | 95% | 趋势确认, 加仓 |
| Bull | markdown | -85% | 0% | 趋势反转, 空仓 |
| Bull | unknown | 0% | 85% | 无确认, 维持 |
| Range | accumulation | +10% | 60% | 吸筹信号, 加仓 |
| Range | distribution | -20% | 30% | 派发信号, 减仓 |
| Range | else | 0% | 50% | 无信号, 维持 |
| Bear | markdown | 0% | 0% | 维持空仓 |
| Bear | markup | 0% | 0% | 禁止做多 |
| Bear | accumulation | +50% | 50% | 吸筹信号, 轻仓 |

## 3.4 完整信号合成函数

```python
def combined_signal(closes, ma_period=60, threshold=0.01):
    """
    最终策略: 纯制度 + Wyckoff相位微调
    
    Returns:
        signal: 仓位信号 (0.0 ~ 0.95)
    """
    # Step 1: Base regime signal
    ma = MA(closes, ma_period)
    ratio = closes[-1] / ma[-1]
    
    if ratio > 1 + threshold:
        base = 0.85
        regime = "bull"
    elif ratio < 1 - threshold:
        base = 0.00
        regime = "bear"
    else:
        base = 0.50
        regime = "range"
    
    # Step 2: Wyckoff phase adjustment
    phase = wyckoff_phase(closes, ...)
    
    adjustments = {
        ("bull", "markup"):       0.10,
        ("bull", "markdown"):    -0.85,
        ("bull", "unknown"):      0.00,
        ("range", "accumulation"): 0.10,
        ("range", "distribution"):-0.20,
        ("range", "unknown"):     0.00,
        ("bear", "accumulation"): 0.50,
        ("bear", "markdown"):     0.00,
        ("bear", "markup"):       0.00,
    }
    
    adjustment = adjustments.get((regime, phase), 0.0)
    signal = max(0.0, min(0.95, base + adjustment))
    
    return signal
```

## 3.5 回测执行逻辑

```python
def backtest(closes, signals, cost_buy=0.00075, cost_sell=0.00175):
    """
    含交易成本的回测
    
    成本模型:
    - 买入: 佣金万2.5 + 滑点万5 = 0.075%
    - 卖出: 印花税千1 + 佣金万2.5 + 滑点万5 = 0.175%
    """
    equity = 1.0
    position = 0.0
    
    for i in range(1, len(closes)):
        target = min(max(signals[i], 0.0), 1.0)
        change = target - position
        
        cost = 0.0
        if abs(change) > 0.001:
            if change > 0:
                cost = change * cost_buy
            else:
                cost = abs(change) * cost_sell
            position = target
        
        daily_ret = closes[i] / closes[i-1] - 1
        equity *= (1 + daily_ret * position - cost)
    
    return equity
```
