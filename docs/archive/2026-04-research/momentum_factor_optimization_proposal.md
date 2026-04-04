# 互联网动量因子策略深度研究与优化建议

日期：2026-03-31

适用范围：

1. 需要对现有 MA+ATR+LPPL 策略进行动量因子增强
2. 希望引入学术研究中的经典动量因子
3. 想要提升 8 指数合格率和策略稳健性

---

## 1. 执行摘要

本项目当前已实现的 MA+ATR+LPPL 三层架构整体稳健，但缺少**价格动量**这一核心alpha因子。本方案建议引入五大动量增强模块，预期可将 8 指数合格数从 3/8 提升至 5-6/8，年化超额收益从约 3% 提升至 5-7%，最大回撤从 -25% 降至 -18% 左右。

**推荐实施顺序**：
1. **P0** 动态波动率缩放（1-2天，复用 ATR 框架）
2. **P1** 动量共振因子（3-5天）
3. **P1** 市场状态分层（3-5天）
4. **P2** 52周高点效应（1天，简单计算）
5. **P2** 跨指数轮动（1-2周，需新增组合逻辑）

---

## 2. 当前因子架构诊断

### 2.1 现有因子覆盖度

| 因子类别 | 状态 | 实现位置 | 问题分析 |
|---------|------|---------|---------|
| LPPL 泡沫检测 | ✅ | `lppl_core.py` | 过度依赖单一因子，信号稀疏 |
| MA 趋势跟踪 | ✅ | `backtest.py:201` | 周期选择简单（仅20/120），未利用不同时间框架的动量 |
| ATR 波动率 | ✅ | `backtest.py:216` | 仅用于过滤，无动态仓位调整 |
| 回撤控制 | ✅ | `backtest.py:229` | 仅作为卖出信号，未用于预防性减仓 |
| **价格动量** | ❌ 缺失 | - | **核心因子缺失** - 未引入20日/60日/120日收益率 |
| **52周高点效应** | ❌ 缺失 | - | **动量锚点缺失** - 未利用George & Hwang (2004)发现 |
| **动量时间序列** | ❌ 缺失 | - | 动量持续性未捕捉（加速度/减速） |
| **波动率调整动量** | ❌ 缺失 | - | 未做风险调整（Harvey et al. 2018） |
| **多周期动量** | ❌ 缺失 | - | 仅单一时间框架（MA20/120），缺少5/10/250日 |
| **行业轮动** | ❌ 缺失 | - | 跨资产配置缺失（仅在单指数内交易） |

### 2.2 与学术研究的差距

根据 Jegadeesh & Titman (1993)、George & Hwang (2004)、Moskowitz & Grinblatt (1999) 等经典研究，价格动量是股票市场最持久的 alpha 来源之一。当前项目仅使用了趋势（MA）和波动率（ATR），未直接使用价格收益率作为信号，这是提升空间最大的领域。

---

## 3. 动量因子学术回顾

### 3.1 经典动量因子

**Jegadeesh & Titman (1993) 12-个月动量**
- 买入过去 12 个月收益高的股票，卖出收益低的
- **关键发现**：动量在除1月份外持续有效
- **A股适配**：需改为过去20/60/120日收益率

**52周高点效应 (George & Hwang, 2004)**
- 接近52周高点的股票后续表现更好
- **机制**：心理锚点效应，突破阻力后有持续动力
- **修正因子**：距离高点百分比 + 突破时长

**动量崩溃风险 (Daniel & Moskowitz, 2016)**
- 在高波动市场，动量策略回撤可达 -50%+
- **解决方案**：波动率缩放、下行波动率惩罚

### 3.2 动量增强变体

| 因子名称 | 来源 | 计算方式 | A股适配性 |
|---------|------|---------|---------|
| **VIX动量** | 恐慌指数 | VIX变化率与指数收益关联 | ⭐⭐⭐ 适用（可用50ETF期权隐含波动率） |
| **资金流动量** | 聪明钱跟踪 | ETF资金流向 + 北向资金 | ⭐⭐⭐ 适用（公募/北向资金数据可得） |
| **行为动量** | 情绪代理 | 搜索量 + 社交媒体情绪 | ⭐⭐ 部分适用 |
| **波动率期限结构** | 风险预期 | VIX期货曲线斜率 | ⭐⭐ 可用期权数据有限 |
| **分析师动量** | 基本面 | 盈利预测修正趋势 | ⭐⭐ 季度数据频率较低 |

---

## 4. 五大优化建议

### 4.1 建议一：引入动态动量共振因子 ⭐ P1

**核心思想**：价格动量必须与趋势、波动率、成交量形成共振才有效。

**理论基础**：Moskowitz & Grinblatt (1999) 发现行业动量与价格动量相关；Asness (1997) 发现价值+动量比单一因子更稳健。

**具体实现**：

```python
@dataclass
class MomentumConfig:
    momentum_windows: List[int] = field(default_factory=lambda: [20, 60, 120])
    volatility_scale: bool = True  # 是否波动率调整
    regime_filter: bool = True  # 是否市场状态过滤
    proximity_weight: float = 0.3  # 52周高点临近权重

    def calculate_momentum_score(self, df, signal_config):
        """
        动量共振评分 = 价格动量 + 成交量确认 + 52周高点临近 + 趋势对齐
        """
        momentum_score = (
            self.price_momentum(df, self.momentum_windows) * 0.40 +
            self.volume_momentum(df) * 0.25 +
            self.proximity_52w_high(df) * 0.30 +
            self.trend_alignment(df) * 0.05
        ) * self.volatility_multiplier(df)  # 波动率缩放调整
        return momentum_score

    def volatility_multiplier(self, df):
        """
        Harvey et al. (2018) 动态波动率缩放
        """
        realized_vol = df["returns"].rolling(20).std() * np.sqrt(252)
        target_vol = self.target_volatility  # 默认 15%
        return target_vol / max(realized_vol, 0.05)
```

**预期效果**：
- 减少假突破交易（成交量确认）
- 提高信号质量（多维度共振）
- 降低交易频率（52周高点作为锚点）

**与既有代码的整合点**：
- 在 `_compute_indicators` 中新增动量指标计算
- 在 `evaluate_ma_cross_atr` 中新增动量确认条件
- 与现有 `signal_model` 体系兼容，可新增 `momentum_ma_atr_v1`

---

### 4.2 建议二：构建市场状态感知的分层动量模型 ⭐ P1

**理论基础**：动量因子有效性依赖于市场状态（牛市/熊市/震荡）。Daniel & Moskowitz (2016) 发现动量在熊市表现最差。

**市场状态判定**：

| 市场状态 | ADX | 价格位置 | 动量策略调整 |
|---------|-----|---------|------------|
| **趋势市** | > 25 | MA斜率一致 | 标准动量，持有期延长，允许追涨 |
| **震荡市** | < 20 | 价格在MA±1σ内 | 反向均值回归，降低动量权重 |
| **崩盘市** | > 30 | LPPL高危 + ATR>2σ | 降低仓位，现金为主，动量失效 |
| **复苏市** | 快速上升 | 底部信号+成交量激增 | 增加动量敞口，加速建仓 |

**实现建议**：

```python
# 在 InvestmentSignalConfig 中新增
market_state_detector: str = "adx_plus_lppl"  # ADX + LPPL 联合判定

momentum_regime_config = {
    "trending": {
        "lookback": 60,
        "momentum_weight": 1.0,      # 标准权重
        "stop_loss_multiplier": 1.0
    },
    "ranging": {
        "lookback": 20,
        "momentum_weight": -0.5,     # 反向（均值回归）
        "stop_loss_multiplier": 0.5  # 收紧止损
    },
    "crashing": {
        "lookback": 10,
        "momentum_weight": 0.0,     # 禁用动量
        "max_position": 0.25        # 限制仓位
    },
    "recovering": {
        "lookback": 40,
        "momentum_weight": 1.5,      # 加速建仓
        "entry_threshold": 0.5       # 降低入场门槛
    }
}
```

**与既有代码的整合点**：
- 复用 `enable_regime_hysteresis` 逻辑框架
- 在 `_evaluate_multi_factor` 中新增状态机分支
- 与现有 `signal_model` 兼容

---

### 4.3 建议三：跨指数动量轮动 ⭐ P2

**核心逻辑**：在不同指数之间动态调配，始终持有最强动量指数。

**理论基础**：Moskowitz & Grinblatt (1999) 行业动量效应；相对动量比绝对动量更稳健。

**基于现有 8 指数架构**：

```python
def calculate_cross_index_rotation(symbols, lookback=60):
    """
    每日计算各指数动量评分，选择前N个最强动量指数
    """
    momentum_scores = {}
    for symbol in symbols:
        df = DataManager().get_data(symbol)
        momentum_scores[symbol] = calculate_momentum_score(df, lookback)

    # 选择前3个最强动量指数
    selected = top_n(momentum_scores, n=3)

    # 按动量比例分配权重（归一化）
    weights = normalize({k: momentum_scores[k] for k in selected})

    return selected, weights

# 组合构建
portfolio = {
    "symbols": selected,
    "weights": weights,
    "rebalance_frequency": 5,  # 每5天再平衡
    "turnover_limit": 0.3      # 每次最大换仓30%
}
```

**与既有代码的整合点**：
- 新增 `src/investment/rotation.py` 模块
- 在 `index_investment_analysis.py` 中增加 `rotation_mode`
- 需要新增组合级回撤计算（加权平均）

**所需新增能力**：
- 指数间相关性矩阵
- 组合波动率计算
- 再平衡摩擦成本

---

### 4.4 建议四：引入动态波动率缩放 ⭐ P0

**学术研究**：Harvey et al. (2018) 证明波动率调整后的动量更稳定。

**核心公式**：

```python
def volatility_scale_position(
    target_position: float,
    realized_volatility: float,  # 21日年化波动率
    target_volatility: float = 0.15  # 目标 15%
) -> float:
    """
    当市场波动 > 目标，降低仓位；波动 < 目标，增加仓位
    最大2倍杠杆
    """
    scale_factor = target_volatility / max(realized_volatility, 0.05)
    return target_position * min(scale_factor, 2.0)
```

**与既有 ATR 框架的整合**：

```python
# 在 _compute_indicators 中新增
enriched["realized_vol_21"] = (
    enriched["returns"].rolling(21, min_periods=1).std() * np.sqrt(252)
)

# 在 evaluate 函数中
vol_position_cap = volatility_scale_position(
    full_position,
    realized_vol=row["realized_vol_21"],
    target_vol=signal_config.target_volatility
)

# 最终仓位取最小值（风险叠加）
position_cap = min(lppl_cap, atr_cap, vol_scale_cap)
```

**预期效果**：
- 在高波动期间自动降低仓位
- 避免动量崩溃时的尾部风险
- 提升Calmar比率

---

### 4.5 建议五：52周高点效应增强 ⭐ P2

**理论基础**：George & Hwang (2004) 发现52周高点是最强的心理锚点，比单纯收益率预测能力更强。

**因子定义**：

```python
def calculate_52w_high_factor(df, window=252):
    """
    52周高点因子 = 当前价格 / 过去252日最高价
    """
    rolling_high = df["close"].rolling(window, min_periods=1).max()
    proximity = df["close"] / rolling_high

    # 分值：1.0 = 新高，0.5 = 腰斩
    # 买入信号：突破前高 或 回踩前高不破
    # 卖出信号：跌破前低 20%
    return {
        "proximity": proximity,
        "is_breakout": proximity > 0.99,  # 接近或突破新高
        "is_support_test": (proximity > 0.95) & (proximity < 1.0),  # 测试支撑
        "time_since_high": (df["close"] == rolling_high).rolling(60).sum()  # 多久没创新高
    }
```

**交易规则**：

| 条件 | 52W高点因子 | 信号 |
|------|-----------|------|
| 突破前高 | > 0.99 | 强烈买入（动量确认） |
| 测试支撑 | 0.95-0.99 | 观察/轻量买入 |
| 回踩买入 | 从高点跌<5%后反弹 | 加仓信号 |
| 跌破趋势 | < 0.80（跌破20%） | 清仓信号 |

**与既有体系的整合**：
- 可作为独立 `signal_model`（`52w_high_atr_v1`）
- 也可与 MA+ATR 结合（`ma_52w_atr_v1`）
- 与 LPPL 不冲突（LPPL 专注顶部疯狂状态）

---

## 5. 具体代码实施建议

### 5.1 第一步：在 `InvestmentSignalConfig` 中扩展动量配置

```python
# src/investment/backtest.py

@dataclass
class InvestmentSignalConfig:
    # ===== 现有配置（保留） =====
    signal_model: str = "multi_factor_v1"
    initial_position: float = 0.0
    # ... existing fields ...

    # ===== 新增动量配置 =====
    # P0: 动态波动率缩放
    enable_volatility_scaling: bool = False
    target_volatility: float = 0.15  # 目标年化波动率 15%

    # P1: 动量共振因子
    enable_momentum_factor: bool = False
    momentum_windows: List[int] = field(default_factory=lambda: [20, 60])
    momentum_weight: float = 0.35  # 动量在评分中的权重

    # P2: 52周高点效应
    enable_52w_high_factor: bool = False
    proximity_52w_threshold: float = 0.95  # 95%以上算有效
    breakout_weight: float = 0.25

    # P1: 市场状态分层
    enable_market_state: bool = False
    adx_threshold_trending: float = 25.0
    adx_threshold_ranging: float = 20.0

    # 各状态动量权重（覆盖默认 momentum_weight）
    momentum_regime_weight: Dict[str, float] = field(default_factory=lambda: {
        "trending": 1.0,
        "ranging": -0.3,
        "crashing": 0.0,
        "recovering": 1.2
    })
```

### 5.2 第二步：在 `_compute_indicators` 中新增动量指标

```python
def _compute_indicators(df: pd.DataFrame, signal_config: InvestmentSignalConfig) -> pd.DataFrame:
    enriched = df.copy()

    # ===== 现有计算（保留） =====
    # MA 计算
    enriched["ma_fast"] = enriched["close"].rolling(signal_config.trend_fast_ma, min_periods=1).mean()
    enriched["ma_slow"] = enriched["close"].rolling(signal_config.trend_slow_ma, min_periods=1).mean()
    # ... ATR 计算 ...

    # ===== 新增动量指标 =====

    # 1. 收益率计算
    enriched["returns"] = enriched["close"].pct_change()

    # 2. 已实现波动率（P0）
    enriched["realized_vol_21"] = (
        enriched["returns"].rolling(21, min_periods=1).std() * np.sqrt(252)
    )

    # 3. 多周期动量（P1）
    if signal_config.enable_momentum_factor:
        for window in signal_config.momentum_windows:
            enriched[f"momentum_{window}"] = (
                enriched["close"] / enriched["close"].shift(window) - 1
            )
        # 动量加权合成
        momentum_cols = [f"momentum_{w}" for w in signal_config.momentum_windows]
        enriched["momentum_composite"] = enriched[momentum_cols].mean(axis=1)

    # 4. 52周高点临近度（P2）
    if signal_config.enable_52w_high_factor:
        rolling_52w_high = enriched["close"].rolling(252, min_periods=1).max()
        enriched["proximity_52w_high"] = enriched["close"] / rolling_52w_high
        enriched["is_near_52w_high"] = enriched["proximity_52w_high"] >= signal_config.proximity_52w_threshold

    # 5. ADX 市场状态（P1）
    if signal_config.enable_market_state:
        enriched["adx"] = calculate_adx(enriched, period=14)
        enriched["market_state"] = enriched.apply(
            lambda row: (
                "trending" if row["adx"] > signal_config.adx_threshold_trending
                else "ranging" if row["adx"] < signal_config.adx_threshold_ranging
                else "neutral"
            ),
            axis=1
        )

    return enriched
```

### 5.3 第三步：创建新的信号模型 `momentum_lppl_atr_v1`

```python
def _evaluate_momentum_lppl_atr(
    row: pd.Series,
    momentum_state: MomentumState,
    lppl_state: ActiveLPPLState,
    signal_config: InvestmentSignalConfig,
    current_position: float
) -> Dict[str, Any]:
    """
    动量 + LPPL + ATR 融合模型

    核心逻辑：
    - 动量评分决定买入意愿强度
    - LPPL 状态机限制最大仓位（风险控制）
    - ATR 波动率调整实际仓位
    - 已实现波动率做动态仓位缩放
    """

    # 1. 基础动量信号
    momentum_score = momentum_state.score
    momentum_direction = 1 if momentum_score > 0 else -1

    # 2. LPPL 状态机风险上限
    position_cap = signal_config.full_position
    if lppl_state.positive_signal_name == "bubble_warning":
        position_cap = signal_config.half_position
    elif lppl_state.positive_signal_name == "bubble_risk":
        if lppl_state.effective_positive_days() <= 3:
            position_cap = signal_config.flat_position  # 清仓
        else:
            position_cap = signal_config.half_position

    # 3. ATR 波动率过滤
    atr_ratio = row["atr_ratio"]
    if atr_ratio > signal_config.vol_breakout_mult:
        position_cap = min(position_cap, signal_config.full_position * 0.5)

    # 4. 动态波动率缩放（P0）
    if signal_config.enable_volatility_scaling:
        realized_vol = row["realized_vol_21"]
        vol_scale = signal_config.target_volatility / max(realized_vol, 0.05)
        position_cap = min(position_cap, signal_config.full_position * min(vol_scale, 2.0))

    # 5. 市场状态调整动量权重（P1）
    if signal_config.enable_market_state:
        market_state = row.get("market_state", "neutral")
        regime_weight = signal_config.momentum_regime_weight.get(market_state, 1.0)
        adjusted_momentum = momentum_score * regime_weight
    else:
        adjusted_momentum = momentum_score

    # 6. 52周高点突破奖励（P2）
    if signal_config.enable_52w_high_factor and row.get("is_near_52w_high"):
        adjusted_momentum *= (1 + signal_config.breakout_weight)

    # 7. 综合决策
    if adjusted_momentum > 0 and current_position < position_cap:
        next_position = min(position_cap, current_position + signal_config.position_step)
        reason = f"动量买入(得分={adjusted_momentum:.2f})"
    elif adjusted_momentum < 0 and current_position > 0:
        next_position = max(0, current_position - signal_config.position_step)
        reason = f"动量卖出(得分={adjusted_momentum:.2f})"
    else:
        next_position = current_position
        reason = "持有"

    return {
        "next_position": next_position,
        "reason": reason,
        "momentum_score": momentum_score,
        "adjusted_momentum": adjusted_momentum,
        "lppl_signal": lppl_state.positive_signal_name,
        "atr_ratio": atr_ratio,
        "position_cap": position_cap
    }
```

### 5.4 第四步：在 `optimal_params.yaml` 中按指数配置

```yaml
# config/optimal_params.yaml

version: 2  # 版本升级

defaults:
  # 基础模型
  signal_model: momentum_lppl_atr_v1

  # P0: 波动率缩放（默认开启）
  enable_volatility_scaling: true
  target_volatility: 0.15

  # P1: 动量因子（默认开启）
  enable_momentum_factor: true
  momentum_windows: [20, 60]
  momentum_weight: 0.35

  # P2: 52周高点（默认关闭，可选开启）
  enable_52w_high_factor: false
  proximity_52w_threshold: 0.95
  breakout_weight: 0.25

  # P1: 市场状态（默认开启）
  enable_market_state: true

# 各指数特化配置
symbols:
  "000300.SH":  # 沪深300 - 稳健大盘股
    signal_model: momentum_lppl_atr_v1
    enable_volatility_scaling: true
    target_volatility: 0.12  # 更保守
    momentum_weight: 0.30    # 降低动量权重
    momentum_regime_weight:
      trending: 1.0
      ranging: 0.0           # 震荡市不做反向
      crashing: 0.0

  "399006.SZ":  # 创业板指 - 高波动
    signal_model: momentum_lppl_atr_v1
    enable_volatility_scaling: true
    target_volatility: 0.20  # 可承受更高波动
    momentum_weight: 0.45      # 增加动量权重
    momentum_windows: [10, 30, 60]  # 更短周期
    enable_52w_high_factor: true    # 开启突破效应
    breakout_weight: 0.35
```

---

## 6. 与既有文档的对比分析

### 6.1 与《因子交易策略新手指南》的相同点

| 维度 | 新手指南 | 本方案 | 一致性 |
|------|---------|--------|--------|
| **核心架构** | MA20/MA60 + ATR + LPPL 三层 | 复用三层架构，增加动量层 | ✅ 完全继承 |
| **数据层** | 复用 `DataManager`, `constants` | 复用既有数据基础设施 | ✅ 完全一致 |
| **信号生成顺序** | 先算指标 → 再生成信号 → 再回测 | 遵循相同流程 | ✅ 完全一致 |
| **仓位管理** | 阶梯仓位 (0/0.33/0.66/1.0) | 保留阶梯仓位，增加动态调整 | ✅ 增强而非替换 |
| **LPPL角色** | 只做状态机风控，不做买入 | 保持 LPPL 风控定位 | ✅ 完全一致 |
| **交易规则定义** | 金叉买入 + ATR确认 + LPPL风控 | 金叉 + 动量共振 + ATR确认 + LPPL风控 | ✅ 扩展而非替换 |

### 6.2 与《因子交易策略新手指南》的不同点

| 维度 | 新手指南 | 本方案 | 差异说明 |
|------|---------|--------|---------|
| **核心因子** | MA（趋势）+ ATR（波动） | 动量 + MA + ATR + LPPL | **重大补充**：新增价格动量因子 |
| **优化顺序** | 趋势 → 波动 → LPPL | 波动缩放(P0) → 动量(P1) → 状态(P1) → 轮动(P2) | **新增**：动量因子优先于LPPL调优 |
| **信号模型** | `ma_cross_atr_lppl_v1` | `momentum_lppl_atr_v1` | **新增模型**：更完整的四因子融合 |
| **参数维度** | 单指数优化 | 按指数组优化 + 轮动 | **扩展**：跨指数层面优化 |
| **波动率处理** | ATR作为开关阈值 | ATR阈值 + 动态波动率缩放 + 已实现波动率 | **深化**：三维波动率管理 |
| **市场状态** | 被动跟随趋势 | 主动识别状态并调整权重 | **新增**：状态机驱动的策略切换 |
| **52周高点** | 未涉及 | 作为独立因子引入 | **新增**：心理锚点效应 |

### 6.3 两文档的定位差异

| 维度 | 《因子交易策略新手指南》 | 本优化方案 |
|------|----------------------|-----------|
| **目标读者** | 新手，刚接项目 | 有一定基础，需增强策略 |
| **内容深度** | 执行层、操作步骤 | 研究层、学术支撑 |
| **时间维度** | 短期（跑通链路） | 中期（提升性能） |
| **代码范围** | 复用既有，少量新增 | 结构性新增模块 |
| **风险定位** | 保守（MA稳健但慢） | 平衡（动量+风控） |

---

## 7. 预期效果与验证路径

### 7.1 量化预期

| 指标 | 当前 (MA+ATR) | 预期 (新模型) | 提升 |
|------|--------------|--------------|------|
| 8指数合格数 | 3/8 (37.5%) | 5-6/8 (62-75%) | +67-100% |
| 平均年化超额 | ~3% | ~5-7% | +67-133% |
| 最大回撤 | -25% | -18% | -28% |
| Calmar 比率 | 0.12 | 0.30 | +150% |
| 交易频率 | 高频 | 中频 | 降低噪音 |
| 换手率 | ~400% | ~250% | -37% |

### 7.2 验证路径

```
第一轮（1-2天）：动态波动率缩放
└── 复用现有 ATR 框架
└── 在 000300.SH 上验证回撤控制效果
└── 通过：回撤下降 3%+

第二轮（3-5天）：动量共振因子
└── 在 _compute_indicators 中新增动量计算
└── 新增 `momentum_ma_atr_v1` 信号模型
└── 在 000300.SH / 000016.SH 上验证
└── 通过：年化超额提升 2%+

第三轮（3-5天）：市场状态分层
└── 增加 ADX 计算
└── 实现状态机权重调整
└── 在 399006.SZ（高弹性）上验证
└── 通过：熊市回撤降低 5%+

第四轮（1天）：52周高点效应
└── 新增临近度指标
└── 集成到动量评分中
└── 全量测试
└── 通过：突破交易胜率>60%

第五轮（1-2周）：跨指数轮动
└── 新增 rotation.py 模块
└── 组合级回测
└── 与单指数策略对比
└── 通过：组合夏普比率 > 平均单指数
```

### 7.3 风险控制

每项新增因子都设置了**开关参数**（`enable_XXX: false`），可以随时回滚到原 MA+ATR 策略，保证回测可复现性。

---

## 8. 结论

本方案在充分继承《因子交易策略新手指南》既有架构的基础上，系统性地引入了价格动量这一核心 alpha 因子，并结合学术研究（52周高点效应、波动率缩放、市场状态分层）提出了五大优化方向。

**核心贡献**：
1. **信号完整性**：从趋势+波动二维扩展为动量+趋势+波动+风控四维
2. **学术支撑**：每项建议都有明确的学术文献来源和 A股适配逻辑
3. **渐进实施**：P0-P2 的三级优先级，避免一次性改动过大
4. **可回退性**：每个新增因子都有开关，保证策略可追溯

**与既有文档的关系**：
- 本方案是《因子交易策略新手指南》的**增强版而非替代版**
- 新手应该先看《新手指南》跑通链路，再参考本方案进行因子升级
- 两份文档互补：新手指南回答"怎么做"，本方案回答"为什么这么做及如何提升"

---

## 9. 参考文档

- [因子交易策略新手指南](./因子交易策略新手指南.md) — 基础架构与执行步骤
- [新手继续执行手册](./beginner_execution_runbook.md) — 最新策略方向与测试结果
- [LPPL 参数总表与实验复盘](./lppl_signal_experiment_retro_20260329.md) — 历史实验总结

## 10. 关键代码文件

- `src/investment/backtest.py` — 主回测逻辑，需扩展动量指标计算
- `src/investment/tuning.py` — 参数打分，需扩展动量相关指标
- `src/config/optimal_params.py` — 配置读取，需支持新动量参数
- `config/optimal_params.yaml` — 生产参数，需新增动量配置
