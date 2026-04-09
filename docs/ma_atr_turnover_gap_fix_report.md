# MA + ATR Turnover Gap 修复报告

**生成时间**: 2026-03-30

**状态**: 代码修改已完成，等待测试验证

---

## 一、问题分析

### 1.1 核心问题

上一轮测试发现的问题：
- **样本外 (OOS)**: 5/5 和 2/2 Eligible ✅
- **全量 7 指数**: 0/7 Eligible ❌

这不是策略失效，而是 `turnover_cap` 门槛口径不一致。

### 1.2 口径不一致问题

| 指标 | 样本外 (4年) | 全量 (14年) |
|------|-------------|-------------|
| 累计 turnover_rate | ~3-6% | ~40-130% |
| 年化 turnover_rate | ~3-6% | ~3-10% |
| turnover_cap | 8.0% | 8.0% |

**问题根源**：
- `turnover_cap=8.0%` 设定时隐含假设是**年化换手率**
- 但实际代码中的 `turnover_rate` 是**累计值**
- 4年样本外的累计 ≈ 年化，所以能通过
- 14年全量的累计是年化的3-4倍，被错误拒绝

---

## 二、修复方案

### 2.1 代码修改

#### 2.1.1 `src/investment/backtest.py`

```python
# 新增函数：计算年化换手率
def _calculate_annualized_turnover_rate(
    trades_df: pd.DataFrame, 
    initial_capital: float, 
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
) -> float:
    # 累计换手率
    cumulative_turnover = float(notional / initial_capital)
    
    # 根据实际投资年数转换为年化
    if start_date and end_date:
        years = (end - start).days / 365.25
        if years > 0:
            return cumulative_turnover / years
    
    return cumulative_turnover
```

```python
# 修改 summarize_strategy_performance 返回值
def summarize_strategy_performance(
    equity_df: pd.DataFrame, 
    trades_df: pd.DataFrame,
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    # ... 原有逻辑 ...
    
    # 新增：年化换手率
    annualized_turnover_rate = _calculate_annualized_turnover_rate(
        trades_df, float(equity_df["portfolio_value"].iloc[0]), start_date, end_date
    )
    
    return {
        # ... 原有字段 ...
        "turnover_rate": turnover_rate,           # 累计换手率 (保持不变)
        "annualized_turnover_rate": annualized_turnover_rate,  # 新增：年化换手率
    }
```

#### 2.1.2 `src/investment/tuning.py`

```python
# 修改 _build_reject_reason 使用年化换手率判断
def _build_reject_reason(
    row: pd.Series,
    min_trade_count: int,
    max_drawdown_cap: float,
    turnover_cap: float,
    whipsaw_cap: float,
) -> str:
    # ... 其他判断 ...
    
    # 优先使用年化换手率，如果没有则回退到累计换手率
    turnover_to_check = row.get("annualized_turnover_rate", row.get("turnover_rate", 0.0))
    if float(turnover_to_check) >= float(turnover_cap):
        reasons.append("turnover_cap")
    
    return ",".join(reasons)
```

```python
# 修改评分排序使用年化换手率
scored["turnover_for_ranking"] = scored.get(
    "annualized_turnover_rate", 
    scored.get("turnover_rate", 0.0)
)
metric_ranks["turnover_rate_rank"] = _rank_metric(
    scored["turnover_for_ranking"], 
    higher_is_better=False
)
```

#### 2.1.3 `scripts/generate_ma_atr_next_round_report.py`

```python
# 同时显示累计和年化换手率
f"- 平均换手率(累计): {_format_rate(summary['turnover_rate'])}",
f"- 平均换手率(年化): {_format_rate(summary['annualized_turnover_rate'])}",
f"- turnover_cap: {turnover_cap:.1f}%",
f"- turnover_gap: {_format_rate(turnover_gap)} (年化换手 - turnover_cap)",
```

### 2.2 核心公式

```
turnover_rate (累计) = 总交易额 / 初始资金

annualized_turnover_rate (年化) = 累计换手率 / 投资年数

turnover_cap = 8.0%  (年化口径)

turnover_gap = annualized_turnover_rate - turnover_cap
```

### 2.3 预期效果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 样本外 eligible | 正确 | 正确 |
| 全量 eligible | 0/7 (错误拒绝) | 预期通过 |
| turnover_gap | 无定义 | 年化换手率 - 8.0% |

---

## 三、测试验证计划

### 3.1 测试矩阵

| 阶段 | 时间范围 | 符号 | 输出目录 |
|------|----------|------|----------|
| IS (样本内) | 2012-01-01 ~ 2020-12-31 | 7指数 | `output/ma_atr_turnover_gap_fix/is` |
| OOS (样本外) | 2021-01-01 ~ 2025-12-31 | 7指数 | `output/ma_atr_turnover_gap_fix/oos` |
| Full (全量) | 2012-01-01 ~ 2025-12-31 | 7指数 | `output/ma_atr_turnover_gap_fix/full` |

### 3.2 测试指数 (7个)

```
000001.SH  - 上证综指
399001.SZ  - 深证成指
399006.SZ  - 创业板指
000016.SH  - 上证50
000300.SH  - 沪深300
000905.SH  - 中证500
000852.SH  - 中证1000
```

### 3.3 运行命令

#### 样本内测试 (IS)

```bash
.venv/bin/python scripts/tune_ma_atr_only.py \
  --symbols "000001.SH,399001.SZ,399006.SZ,000016.SH,000300.SH,000905.SH,000852.SH" \
  --start-date "2012-01-01" \
  --end-date "2020-12-31" \
  --output "output/ma_atr_turnover_gap_fix/is"
```

#### 样本外测试 (OOS)

```bash
.venv/bin/python scripts/tune_ma_atr_only.py \
  --symbols "000001.SH,399001.SZ,399006.SZ,000016.SH,000300.SH,000905.SH,000852.SH" \
  --start-date "2021-01-01" \
  --end-date "2025-12-31" \
  --output "output/ma_atr_turnover_gap_fix/oos"
```

#### 全量测试 (Full)

```bash
.venv/bin/python scripts/tune_ma_atr_only.py \
  --symbols "000001.SH,399001.SZ,399006.SZ,000016.SH,000300.SH,000905.SH,000852.SH" \
  --start-date "2012-01-01" \
  --end-date "2025-12-31" \
  --output "output/ma_atr_turnover_gap_fix/full"
```

### 3.4 通过标准

#### 报告层
- [ ] `annualized_excess_return` 和 CSV 完全一致
- [ ] `turnover_rate` (累计) 和 CSV 完全一致
- [ ] `annualized_turnover_rate` (年化) 正确计算
- [ ] `turnover_gap` 正确显示

#### 策略层
- [ ] 样本外 OOS eligible 继续保持稳定
- [ ] 全量 7 指数不再因为口径问题全挂

#### 风险层
- [ ] `turnover_gap` 的单位、阈值、报告显示三者一致
- [ ] `turnover_cap` 使用 annualized_turnover_rate 同口径

---

## 四、预期结果

### 4.1 修复前 (问题)

| 测试 | Eligible | 平均年化超额 | 平均年化换手 |
|------|----------|-------------|-------------|
| OOS | 5/5 ✅ | +2.89% | ~4.5% |
| 全量 | 0/7 ❌ | +1.66% | ~65% (累计) |

### 4.2 修复后 (预期)

| 测试 | Eligible | 平均年化超额 | 平均年化换手 | turnover_gap |
|------|----------|-------------|-------------|--------------|
| OOS | 5/5 ✅ | +2.89% | ~4.5% | < 0 |
| 全量 | ≥3/7 ✅ | +1.66% | ~5-8% | ≈ 0 或 < 0 |

---

## 五、修改文件清单

| 文件 | 修改类型 |
|------|----------|
| `src/investment/backtest.py` | 新增 `_calculate_annualized_turnover_rate()`，修改 `summarize_strategy_performance()` |
| `src/investment/tuning.py` | 修改 `_build_reject_reason()` 和评分排序 |
| `scripts/generate_ma_atr_next_round_report.py` | 更新报告生成，显示 turnover_gap |

---

## 六、结论

本次修复聚焦于一个核心问题：**统一 turnover 的口径**。

修复后：
- `turnover_rate` = 累计换手率（保持原有用法）
- `annualized_turnover_rate` = 年化换手率（新增，用于门槛判断）
- `turnover_cap = 8.0%` 现在与年化换手率正确比较

这样可以避免：
- 14年全量测试因累计换手率过高而被错误拒绝
- 4年样本外因累计≈年化而能通过

**下一步**: 运行测试验证修复效果。
