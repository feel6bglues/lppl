# 信号质量修复计划 — P0/P1 技术方案

> 生成日期: 2026-05-13
> 审核范围: `src/wyckoff/engine.py`, `src/wyckoff/rules.py`, `scripts/generate_daily_signals.py`
> 排除了: 前复权数据修复（单独处理）

---

## 问题汇总

| ID | 问题 | 严重级 | 模块 | 当前表现 |
|----|------|:-----:|------|---------|
| SQ-01 | Wyckoff置信度锁定C级 | 🔴 P0 | `_calc_confidence` | 176/176信号全C级，无B/A |
| SQ-02 | Wyckoff目标价缺失+盈亏比NaN | 🔴 P0 | `_step4_risk_reward` | 约70%的信号 `upside_pct` 为None |
| SQ-03 | MA5/20信号无质量过滤 | 🟠 P1 | `generate_daily_signals.py` | 单日896条信号(17.2%) |
| SQ-04 | 市场制度未考虑个股独立性 | 🟠 P1 | `check_wyckoff_signal` | 全部176个信号都在bull regime |
| SQ-05 | 交易成本未计入信号 | 🟠 P1 | `generate_daily_signals.py` | 实盘每笔需扣0.25% |

---

## SQ-01: Wyckoff 置信度锁定C级

### 根因分析

`engine.py: _calc_confidence` 中有两条路径将置信度锁定在C级：

```python
# 路径A (Line ~752): Spring已检测但LPS未验证 → 强制C级
if step3.spring_detected and not spring_lps_verified:
    return ConfidenceResult(level="C", ...)

# 路径B (Line ~764): RR达标但BC未定位 → 强制C级
if rr_qualified and not bc_located:
    return ConfidenceResult(level="C", ...)
```

当不命中上述两条时，走 `rule8_confidence_matrix` (rules.py:164):

```python
# MET COUNT → LEVEL (当前为放宽版本: A=4, B=3, C=2)
if met_count >= 4: level = "A"
elif met_count >= 3: level = "B"
elif met_count >= 2: level = "C"
else: level = "D"
```

对于 MARKUP 阶段信号（占今天176个中的173个）:

| 条件 | 典型值 | 原因 |
|------|:-----:|------|
| ① BC定位 | ❌ False | MARKUP阶段BC已被突破，不在近期视野内 |
| ② Spring/LPS | ❌ False | MARKUP阶段不存在Spring结构 |
| ③ 反事实通过 | ✅ True | 大部分正常通过 |
| ④ RR达标(≥2.5) | ❌ False | 目标价缺失导致RR计算无效 |
| ⑤ 多周期一致 | ❌ False | 单周期分析硬编码为False |

**最多1-2项** → 无论走哪条路径都是C级。

### 修复方案

#### 修复 1.1: 按阶段差异化置信度标准

不同威科夫阶段应有不同的置信度评估标准，而不是统一使用5项条件:

```python
def _calc_confidence(...):
    if step1.phase == WyckoffPhase.MARKUP:
        # MARKUP阶段: 不要求BC定位和Spring验证
        # 替代条件: trend_confirmed(趋势确认) + rr_qualified
        trend_confirmed = (
            step1.short_trend_pct >= 0.03 and
            step1.relative_position >= 0.60
        )
        conditions = [
            trend_confirmed,           # ① 趋势确认
            counterfactual_passed,      # ② 反事实通过
            rr_qualified,              # ③ 盈亏比达标
            not cf.conclusion_overturned,  # ④ 未被推翻
        ]
        met = sum(conditions)
        # MARKUP: B级=3项, C级=2项
        ...
    elif step1.phase == WyckoffPhase.ACCUMULATION:
        # ACCUMULATION阶段: 保留原有Spring/LPS标准
        ...
```

#### 修复 1.2: 增加ATR-based目标价回填

当 `first_target` 缺失或无效时（`first_target <= current_price`），使用ATR替代:

```python
if first_target <= current_price:
    atr = calc_atr(df, 20) or current_price * 0.02
    first_target = current_price + 2.0 * atr  # ATR-based目标
    first_target_source = "atr_derived"
```

这能修复条件④ RR达标。

#### 修复 1.3: 多周期条件默认值调整

单周期分析时，条件⑤不应硬编码为False:

```python
# 修复前: multiframe_aligned = multiframe (永远False)
# 修复后: 如果未提供多周期，该条件视为"已满足"（不扣分）
multiframe_aligned = multiframe or True  # 不降级
```

但需要在报告中明确声明"缺乏多周期确认"。

### 预期效果

- MARKUP阶段B级信号占比：从0%提升至 **15-25%**
- C级信号数量不变，但盈亏比有值
- D级信号下降

---

## SQ-02: Wyckoff 目标价缺失 + 盈亏比NaN

### 根因分析

`engine.py: _step4_risk_reward`:

```python
first_target = step1.boundary_upper  # 默认: TR上沿
# 尝试大阴线起跌点(< current_price则不采纳)
# 尝试缺口下沿(< current_price则不采纳)

reward = first_target - current_price
if risk > 0: rr_ratio = reward / risk

gain_pct = (first_target - current_price) / current_price * 100
```

对于MARKUP阶段的股票，当前价格可能已经高于TR上沿:
- `boundary_upper <= current_price` → `reward <= 0` → `rr_ratio = 0`
- 大阴线/缺口条件更严格，通常也不命中
- 结果: `rr.rr_ratio = 0`, `gain_pct <= 0`

### 修复方案

#### 修复 2.1: ATR-based 目标价回填

```python
def _step4_risk_reward(self, df, step1, step3, rule0):
    current_price = float(df.iloc[-1]["close"])
    key_low = ...
    stop_loss_result = self.rules.rule10_stop_loss(key_low)
    stop_loss = stop_loss_result.stop_loss_price

    # 尝试结构化目标位
    first_target = step1.boundary_upper
    first_target_source = "tr_upper"

    # 尝试大阴线起跌点
    for i in range(len(recent_20) - 1, 0, -1):
        ...
        if bearish_target > current_price and bearish_target < first_target:
            first_target = bearish_target
            break

    # 尝试缺口下沿
    ...

    # ==== 新增: ATR-based回填 ====
    if first_target <= current_price:
        # 计算ATR
        tr_vals = []
        for i in range(1, min(21, len(df))):
            hi, lo, pc = float(df.iloc[-i]["high"]), float(df.iloc[-i]["low"]), float(df.iloc[-i-1]["close"])
            tr_vals.append(max(hi-lo, abs(hi-pc), abs(lo-pc)))
        atr = float(np.mean(tr_vals[-20:])) if len(tr_vals) >= 20 else current_price * 0.02

        first_target = current_price + 2.0 * atr
        first_target_source = "atr_derived"
    # ============================

    reward = first_target - current_price
    ...
```

#### 修复 2.2: 盈亏比阈值差异化

不同阶段的盈亏比要求不同:

```python
# MARKUP阶段: 动态目标(ATR-based), 盈亏比要求可放宽至1.5
if step1.phase == WyckoffPhase.MARKUP:
    rr_threshold_good = 1.5  # 而非2.5
    rr_threshold_excellent = 2.0
elif step1.phase == WyckoffPhase.ACCUMULATION:
    rr_threshold_good = 2.0  # 结构性信号需要更高置信度
    rr_threshold_excellent = 2.5
```

### 预期效果

- 目标价缺失率：**从~70%降至~5%**
- 盈亏比有值的信号：从 **~10%提升至~95%**
- ATR-based目标虽然是估算，但提供了可操作的价格参考

---

## SQ-03: MA5/20 信号无质量过滤

### 根因分析

`generate_daily_signals.py: check_ma_signal`:

```python
# 唯一条件: MA5上穿MA20
if not (prev_ma5 <= prev_ma20 and ma5 > ma20):
    return None
# 直接返回信号，无任何质量检查
```

没有任何过滤，导致所有金叉（无论多弱）都产生信号。

### 修复方案

#### 修复 3.1: ATR过滤器 — 排除窄幅震荡假金叉

```python
# 计算ATR(20): 衡量近期波动幅度
tr_vals = []
for i in range(1, min(21, len(h))):
    hi, lo, pc = float(h.iloc[-i]["high"]), float(h.iloc[-i]["low"]), float(h.iloc[-i-1]["close"])
    tr_vals.append(max(hi-lo, abs(hi-pc), abs(lo-pc)))
atr = float(np.mean(tr_vals)) if tr_vals else close_now * 0.02
atr_ratio = atr / close_now

# ATR < 1.5%: 窄幅震荡，金叉可靠性低
if atr_ratio < 0.015:
    return None  # 排除假金叉
```

#### 修复 3.2: 均线斜率过滤器

```python
# 计算MA5的斜率: 5日均线的方向
ma5_slope = (ma5 - float(h.tail(10)["close"].mean())) / float(h.tail(10)["close"].mean())
# MA5需要明显上行 > 0.5%
if ma5_slope < 0.005:
    return None
```

#### 修复 3.3: 成交额确认

```python
# 金叉日的成交额应高于近期均值
if "amount" in h.columns:
    avg_amount = float(h.tail(20)["amount"].mean())
    curr_amount = float(h.iloc[-1]["amount"])
    if curr_amount < avg_amount * 0.8:  # 缩量金叉不可靠
        return None  # 或降级为C级
```

#### 修复 3.4: 信号置信度分级

```python
# 根据过滤器命中数量分级
filter_score = 0
if atr_ratio >= 0.015: filter_score += 1  # 波动率合格
if ma5_slope >= 0.005: filter_score += 1  # 斜率合格
if curr_amount >= avg_amount * 0.8: filter_score += 1  # 量能合格

confidence = "B" if filter_score >= 2 else "C"
```

### 预期效果

- 信号数量: 从 **896降至200-350条** (正常水平)
- 假信号率显著下降
- 年化换手率下降，交易成本降低

---

## SQ-04: 市场制度未考虑个股独立性

### 根因分析

`check_wyckoff_signal`:

```python
regime = get_regime(csi, as_of_date)  # 只看CSI300
if regime == "bear":
    return None  # 全市场统一过滤
```

CSI300为bull时，所有176只股票全部标记为bull。但实际上，每只股票有自己的市场环境。

### 修复方案

#### 修复 4.1: 增加个股制度判断

```python
def get_stock_regime(df, as_of_date):
    """判断个股自身的市场制度"""
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a]
    if len(h) < 120:
        return "unknown"

    c = float(h.iloc[-1]["close"])
    # 使用MA120作为个股牛熊分界线
    ma120 = float(h.tail(120)["close"].mean())
    ma60 = float(h.tail(60)["close"].mean())

    if c > ma120 * 1.03 and ma60 > ma120:
        return "bull"
    if c < ma120 * 0.97:
        return "bear"
    return "range"
```

#### 修复 4.2: 双级制度过滤

```python
def check_wyckoff_signal(df, symbol, as_of_date, csi):
    # 宏观过滤: 全市场系统性风险
    macro_regime = get_regime(csi, as_of_date)
    if macro_regime == "bear" and symbol not in ["回避"]:
        return None  # 宏观熊市不做多

    # 个股过滤: 不影响Wyckoff分析，仅用于仓位建议
    stock_regime = get_stock_regime(df, as_of_date)

    # 分析结果中的regime使用个股制度
    ...
    return {
        ...
        "regime": stock_regime,  # 使用个股制度而非宏观制度
        "macro_regime": macro_regime,  # 保留宏观制度用于参考
    }
```

### 预期效果

- 信号中的regime分布更真实地反映个股状态
- 不会全部集中在bull regime
- 可能出现 range 和 bear regime但有结构信号的个股

---

## SQ-05: 交易成本未计入

### 根因分析

`generate_daily_signals.py` 中毫无交易成本处理。

### 修复方案

#### 修复 5.1: 信号生成中加入成本预估

```python
COST_BUY = 0.00075   # 佣金万2.5 + 滑点万5
COST_SELL = 0.00175  # 印花税千1 + 佣金万2.5 + 滑点万5
COST_ROUND_TRIP = COST_BUY + COST_SELL  # 0.25%
```

在目标价和止损价中反应成本:

```python
# 实际入场价 = 信号价 × (1 + 买入成本)
# 实际出场价 = 信号价 × (1 - 卖出成本)
# 只是为了信号展示，不需要修改入场价，只需要在盈亏比中体现

# 修正后的盈亏比计算:
effective_entry = entry_price * (1 + COST_BUY)
effective_target = take_profit * (1 - COST_SELL) if take_profit else None
net_return = (effective_target - effective_entry) / effective_entry * 100 if effective_target else None
```

#### 修复 5.2: 信号中加入成本预警

```python
signal = {
    ...
    "entry_cost_pct": COST_BUY * 100,       # 0.075%
    "exit_cost_pct": COST_SELL * 100,       # 0.175%
    "round_trip_cost": COST_ROUND_TRIP * 100,  # 0.250%
    "net_upside_pct": net_return if take_profit else None,  # 扣除成本后的净收益
}
```

---

## 执行计划

### Phase 1: Core Fixes (1天)

| 优先级 | 任务 | 文件 | 工时 |
|:-----:|------|------|:---:|
| P0 | SQ-01: 置信度差异化标准 | `engine.py:_calc_confidence` | 2h |
| P0 | SQ-02: ATR目标价回填 | `engine.py:_step4_risk_reward` | 1h |
| P0 | SQ-02: 盈亏比阈值差异化 | `engine.py:_step4_risk_reward` | 0.5h |

### Phase 2: Quality Filters (1天)

| 优先级 | 任务 | 文件 | 工时 |
|:-----:|------|------|:---:|
| P1 | SQ-03: MA5/20 ATR+斜率+量能过滤 | `generate_daily_signals.py` | 1.5h |
| P1 | SQ-03: MA5/20置信度分级 | `generate_daily_signals.py` | 0.5h |
| P1 | SQ-04: 个股制度判断 | `generate_daily_signals.py` | 1h |

### Phase 3: Cost & Polish (0.5天)

| 优先级 | 任务 | 文件 | 工时 |
|:-----:|------|------|:---:|
| P1 | SQ-05: 交易成本模型 | `generate_daily_signals.py` | 1h |

### 总工时估算

| Phase | 工时 | 覆盖问题 |
|-------|:---:|---------|
| Phase 1 | 3.5h | SQ-01, SQ-02 |
| Phase 2 | 3h | SQ-03, SQ-04 |
| Phase 3 | 1h | SQ-05 |
| **Total** | **7.5h** | **5个问题** |

---

## 修复后预期效果

| 指标 | 修复前 | 修复后预期 |
|------|:-----:|:---------:|
| Wyckoff B级信号占比 | 0% | **15-25%** |
| Wyckoff目标价缺失率 | ~70% | **<5%** |
| MA5/20信号数量 | 896条/日 | **200-350条/日** |
| 交易成本提示 | 无 | **每笔含净收益** |
| 市场制度区分度 | 全部bull | **bull/range/bear混合** |

---

## 不动项

以下内容不在本计划范围内:
1. **前复权数据** — 单独处理，涉及数据层改造
2. **Wyckoff核心逻辑重构** — 引擎结构不动，只修置信度/目标价
3. **回测脚本改动** — `run_dual_strat_wyckoff_ma.py` 不改
4. **数据库存储层** — `storage/database.py` 不改
