# 代码实现与使用指南

## 5.1 文件结构

```
src/
  investment/
    factor_combination.py    # 因子组合引擎 (含v1/v2评估)
    signal_models.py         # 原始信号模型 (LPPL/多因子)
    indicators.py            # 技术指标计算
    backtest.py              # 原始回测引擎
    config.py                # 配置类

validate_factor_combinations.py     # 小范围验证 (932000.SH)
validate_large_scale.py             # 大范围验证 (7指数+阈值敏感性)
validate_p1_p2.py                   # P1网格搜索 + P2 Wyckoff增量
validate_costs_walkforward.py       # 交易成本 + Walk-forward

output/
  validate_large_scale/
    costs_walkforward.json    # 成本+Walk-forward结果
    p1_p2_results.json        # 网格搜索+Wyckoff增量结果
    results.json              # 大范围验证结果
  factor_combination_design.md       # 因子组合设计文档
  comprehensive_evaluation.json      # 综合评估
  validate_factor_combinations.json  # 小范围验证结果

docs/new/                     # 本文档目录
```

## 5.2 快速使用

### 环境要求

```bash
# Python 3.10+
pip install numpy pandas akshare matplotlib
```

### 运行完整回测

```bash
# 小范围验证 (单指数)
python3 validate_factor_combinations.py

# 大范围验证 (7指数 + 阈值敏感性)
python3 validate_large_scale.py

# 参数网格搜索 + Wyckoff增量
python3 validate_p1_p2.py

# 交易成本 + Walk-forward
python3 validate_costs_walkforward.py
```

### 核心API使用

```python
from src.investment.factor_combination import FactorCombinationEngine, Regime, Phase, MTFAlignment, Confidence

# 初始化引擎
engine = FactorCombinationEngine()

# 评估单个组合 (v2: 校准版)
result = engine.evaluate_v2(
    regime=Regime.BULL,
    phase=Phase.MARKUP,
    alignment=MTFAlignment.FULLY_ALIGNED,
    confidence=Confidence.D
)

print(f"方向: {result.direction}")     # 做多
print(f"仓位: {result.position_size}") # 0.95
print(f"风险: {result.risk_level}")    # low
```

### 策略实现

```python
def generate_signal(closes):
    """生成策略信号"""
    from src.investment.factor_combination import FactorCombinationEngine, Regime

    engine = FactorCombinationEngine()

    # Step 1: 计算MA60
    ma60 = np.mean(closes[-60:])

    # Step 2: 判断制度
    ratio = closes[-1] / ma60
    if ratio > 1.01:        regime_str = "bull"
    elif ratio < 0.99:      regime_str = "bear"
    else:                   regime_str = "range"

    # Step 3: 计算Wyckoff相位 (简化版)
    phase_str = "unknown"
    # ... (详见 validate_p1_p2.py p2_wyckoff_phase 函数)

    # Step 4: 评估组合
    result = engine.evaluate_v2(
        regime=Regime.from_str(regime_str),
        phase=Phase.from_str(phase_str),
        alignment=MTFAlignment.MIXED,   # 简化: 不计算对齐
        confidence=Confidence.D,
    )

    return result.position_size  # 0.0 ~ 0.95
```

## 5.3 迁移到新数据

```python
import akshare as ak
import pandas as pd
import numpy as np

# 获取数据
df = ak.stock_zh_index_daily(symbol="sh000001")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

# 生成信号 (参考 validate_p1_p2.py)
closes = df["close"].values

# MA60 + 1% bands 策略
ma60 = np.full(len(closes), np.nan)
for i in range(59, len(closes)):
    ma60[i] = np.mean(closes[i-59:i+1])

signals = np.zeros(len(closes))
for i in range(60, len(closes)):
    ratio = closes[i] / ma60[i]
    if ratio > 1.01:         signals[i] = 0.85
    elif ratio < 0.99:       signals[i] = 0.00
    else:                    signals[i] = 0.50

# 回测 (含交易成本)
equity = 1.0; position = 0.0
for i in range(1, len(closes)):
    target = signals[i]
    change = target - position
    cost = 0.0
    if abs(change) > 0.001:
        cost = change * 0.00075 if change > 0 else abs(change) * 0.00175
        position = target
    equity *= (1 + (closes[i]/closes[i-1] - 1) * position - cost)

print(f"总收益: {equity:.4f}")
```
