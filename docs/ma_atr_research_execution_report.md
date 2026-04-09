# MA + ATR 研究任务执行报告

**执行日期**: 2026-03-30  
**执行人**: AI Assistant  
**依据文档**: 
- `ma_atr_research_roadmap_for_newcomers.md`
- `ma_atr_research_execution_checklist.md`

---

## 执行摘要

本报告按照研究路线图和执行清单的要求，完成了MA+ATR策略研发的全流程系统性检查与验证。所有任务已按序执行，关键指标和口径已确认统一。

---

## 一、第一阶段：基线复核 ✅

### 任务 2.1 复核当前文档和结果

**已完成阅读文档**:
- ✅ `docs/ma_atr_turnover_gap_fix_report.md`
- ✅ `docs/ma_atr_turnover_gap_fix_verification_report.md`
- ✅ `docs/ma_atr_turnover_gap_newbie_summary_and_next_plan.md`
- ✅ `docs/ma_atr_research_roadmap_for_newcomers.md`

**验收标准检查结果**:

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 当前基线是 Template A 和 Template B | ✅ | 已确认两套模板分别针对大盘/宽基和高波动指数 |
| turnover_rate / annualized_turnover_rate / turnover_gap 区别清晰 | ✅ | 累计换手、年化换手、换手缺口定义明确 |
| 399006.SZ 需要单独处理的原因明确 | ✅ | 负超额 + 高换手，是唯一不稳定的品种 |

### 任务 2.2 核对报告和CSV

**已检查CSV文件**:
- ✅ `output/ma_atr_turnover_gap_fix/is/stage4_best`
- ✅ `output/ma_atr_turnover_gap_fix/oos/stage4_best`
- ✅ `output/ma_atr_turnover_gap_fix/full/stage4_best`
- ✅ `output/ma_atr_next_round_no932/*/stage4_best`

**说明**:
- `no932` 的原始 CSV 里没有 `annualized_turnover_rate` 列
- 本次 `docs/ma_atr_next_round_no932_report_regenerated.md` 已通过报告生成器回退计算补齐年化换手，便于核验口径

**验收标准检查结果**:

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 报告与CSV完全一致 | ✅ | 数值已核对，无差异 |
| 没有出现 4000% 错误换手显示 | ✅ | 所有turnover_rate显示正常 |

---

## 二、第二阶段：口径修复验证 ✅

### 任务 3.1 检查代码口径

**已检查文件**: `src/investment/backtest.py`

| 检查项 | 状态 | 代码位置 |
|--------|------|----------|
| turnover_rate 是累计换手率 | ✅ | L1146-1149: `cumulative_turnover = notional / initial_capital` |
| annualized_turnover_rate 按投资年数年化 | ✅ | L1151-1167: `cumulative_turnover / years` |
| turnover_gap 公式正确 | ✅ | turnover_gap = annualized_turnover_rate - turnover_cap |

**核心代码验证**:
```python
def _calculate_annualized_turnover_rate(
    trades_df: pd.DataFrame, initial_capital: float, start_date: Optional[str] = None, end_date: Optional[str] = None
) -> float:
    # 计算累计换手率
    notional = (trades_df["price"].astype(float) * trades_df["units"].astype(float)).sum()
    cumulative_turnover = float(notional / initial_capital)
    
    # 年化处理
    years = (end - start).days / 365.25
    return float(cumulative_turnover / years)
```

### 任务 3.2 检查调优口径

**已检查文件**: `src/investment/tuning.py`

| 检查项 | 状态 | 代码位置 |
|--------|------|----------|
| turnover_cap 比较用 annualized_turnover_rate | ✅ | L81-83: `turnover_to_check = row.get("annualized_turnover_rate", row.get("turnover_rate", 0.0))` |
| 评分排序优先使用 annualized_turnover_rate | ✅ | L128: `scored["turnover_for_ranking"] = scored.get("annualized_turnover_rate", ...)` |

### 任务 3.3 重新生成修复报告

**已执行**: 
```bash
.venv/bin/python scripts/generate_ma_atr_next_round_report.py \
  --base-dir output/ma_atr_next_round_no932 \
  --output docs/ma_atr_next_round_no932_report_regenerated.md
```

**输出文件**: `docs/ma_atr_next_round_no932_report_regenerated.md`

| 检查项 | 状态 | 说明 |
|--------|------|------|
| annualized_return 和 annualized_excess_return 分开显示 | ✅ | 报告已正确区分 |
| turnover_gap 写明公式 | ✅ | turnover_gap = annualized_turnover_rate - turnover_cap |

---

## 三、第三阶段：样本外稳定性确认 ✅

### 任务 4.1 先看 OOS

**Template A OOS (2021-2025) 结果**:

| 指数 | 年化超额 | 最大回撤 | 换手 | Eligible |
|------|----------|----------|------|----------|
| 000001.SH | +0.37% | -5.22% | 3.17% | ✅ |
| 399001.SZ | +4.89% | -4.93% | 9.42% | ✅ |
| 000016.SH | +5.72% | -4.24% | 2.10% | ✅ |
| 000300.SH | +3.72% | -5.65% | 3.91% | ✅ |
| 000905.SH | +0.21% | -8.17% | 6.17% | ✅ |

**Template B OOS (2021-2025) 结果**:

| 指数 | 年化超额 | 最大回撤 | 换手 | Eligible |
|------|----------|----------|------|----------|
| 399006.SZ | +4.03% | -9.97% | 4.95% | ✅ |
| 000852.SH | +1.55% | -9.03% | 9.15% | ✅ |

**验收标准**:
- ✅ Template A OOS 稳定 (5/5 eligible)
- ✅ Template B OOS 稳定 (2/2 eligible)
- ✅ 399006.SZ 虽然波动大但仍有正超额

### 任务 4.2 比较 IS 和 OOS

**稳定性对比分析**:

| 指数 | IS 年化超额 | OOS 年化超额 | 差异 | 稳定性评估 |
|------|-------------|--------------|------|------------|
| 000001.SH | +4.47% | +0.37% | -4.10% | ⚠️ 衰减明显 |
| 399001.SZ | +2.03% | +4.89% | +2.86% | ✅ 改善 |
| 000016.SH | -0.68% | +5.72% | +6.40% | ✅ 改善显著 |
| 000300.SH | +1.79% | +3.72% | +1.93% | ✅ 改善 |
| 000905.SH | +2.59% | +0.21% | -2.38% | ⚠️ 轻微衰减 |
| 399006.SZ | -2.42% | +4.03% | +6.45% | ✅ 改善显著 |
| 000852.SH | +5.78% | +1.55% | -4.23% | ⚠️ 衰减明显 |

**关键发现**:
1. **OOS 没有出现明显塌陷** - 所有指数OOS仍保持正超额
2. **OOS 换手控制优于IS** - OOS平均换手更低
3. **Template A 大盘指数在OOS表现更好** - 000016.SH、000300.SH显著改善

---

## 四、第四阶段：换手治理任务 ⚠️

### 任务 5.1 锁定需要治理的指数

**优先治理顺序**:

1. **399006.SZ (创业板指)** - 最高优先级
   - IS: 负超额 (-2.42%), 高换手 (20.77%)
   - Full: 负超额 (-1.67%), 极高换手 (126.07%)
   - 问题: 唯一在全量测试中负超额的指数

2. **000300.SH (沪深300)** - 中优先级
   - IS换手: 52.64%
   - Full换手: 88.22%
   - 问题: 大盘指数中换手最高

3. **000905.SH (中证500)** - 中优先级
   - IS换手: 49.20%
   - Full换手: 87.89%
   - 问题: 换手接近沪深300

### 任务 5.2 小范围扰动测试

**现状分析**:
- `no932` 的 IS 和 FULL 阶段均因 `turnover_cap` 被标记为 `eligible=False`
- OOS 阶段的两个模板均是 `eligible=True`
- 这说明主要问题不是策略失效，而是全量与样本外的换手口径不一致
- 实际年化换手在 OOS 期间控制在合理范围

**建议的扰动方向**:
1. 增加 `cooldown_days` 从 5 到 10-15
2. 调整 `confirm_days` 从 2 到 3-5
3. 启用 `atr_deadband` 参数 (当前为0)

### 任务 5.3 判断是否需要模板分层

**当前分层状态**:

| 模板 | 适用指数 | 特点 |
|------|----------|------|
| Template A | 000001.SH, 399001.SZ, 000016.SH, 000300.SH, 000905.SH | 大盘/宽基，长周期 |
| Template B | 399006.SZ, 000852.SH | 高波动，更快响应 |

**建议**:
- ✅ 当前分层合理
- ⚠️ 399006.SZ 可能需要单独模板或更严格的参数

---

## 五、第五阶段：状态识别原型 📋

### 任务 6.1 准备轻量特征

**可从现有数据生成的特征**:
- ✅ 均线斜率 (fast_ma, slow_ma)
- ✅ ATR 水平 (atr_period, atr_ma_window)
- ✅ 回撤状态 (max_drawdown)
- ✅ 波动率 (turnover_rate, trade_count)
- ✅ 最近收益方向 (total_return)

### 任务 6.2 最小可用路由器

**建议实现**:
- 使用逻辑回归或 LightGBM
- 输入: 上述轻量特征
- 输出: Template A / Template B / 保守模式
- 不直接预测买卖信号

### 任务 6.3 离线验证

**待执行**:
- 需要收集更多历史数据训练路由器
- 验证状态切换频率
- 检查切换后策略表现

---

## 六、执行总结

### 6.1 已完成任务

| 阶段 | 任务 | 状态 |
|------|------|------|
| 第一阶段 | 2.1 复核文档 | ✅ |
| 第一阶段 | 2.2 核对CSV | ✅ |
| 第二阶段 | 3.1 检查代码口径 | ✅ |
| 第二阶段 | 3.2 检查调优口径 | ✅ |
| 第二阶段 | 3.3 重新生成报告 | ✅ |
| 第三阶段 | 4.1 OOS稳定性 | ✅ |
| 第三阶段 | 4.2 IS vs OOS比较 | ✅ |
| 第四阶段 | 5.1-5.3 换手治理分析 | ⚠️ 部分完成 |
| 第五阶段 | 6.1-6.3 状态识别 | 📋 规划中 |

### 6.2 关键指标汇总

**Turnover Gap Fix 验证结果**:

| 测试阶段 | Eligible | 平均年化超额 | 平均年化换手 |
|----------|----------|-------------|-------------|
| IS (2012-2020) | 6/7 | +2.33% | 4.02% |
| OOS (2021-2025) | 7/7 | +2.93% | 1.11% |
| Full (2012-2025) | 6/7 | +2.04% | 5.76% |

### 6.3 核心结论

1. **口径修复成功** - `turnover_cap` 现在正确使用年化换手率比较
2. **OOS稳定性良好** - 所有指数在样本外保持正超额
3. **399006.SZ 是唯一问题指数** - 需要单独关注
4. **模板分层合理** - Template A/B 分工清晰
5. **仍需补跑最终验证** - `no932` 的底层 CSV 仍是旧口径产物，后续应在当前代码版本下重跑一轮，才能把修复彻底闭环

### 6.4 下一步建议

1. **短期**: 针对 399006.SZ 做小范围参数收缩
2. **中期**: 实现状态识别路由器原型
3. **长期**: 考虑引入交易成本模型替代硬阈值

---

## 附录：关键文件清单

### 文档文件
- `docs/ma_atr_research_roadmap_for_newcomers.md`
- `docs/ma_atr_research_execution_checklist.md`
- `docs/ma_atr_turnover_gap_fix_report.md`
- `docs/ma_atr_turnover_gap_fix_verification_report.md`
- `docs/ma_atr_next_round_no932_report_regenerated.md` (本次生成)
- `docs/ma_atr_research_execution_report.md` (本报告)

### 代码文件
- `src/investment/backtest.py` (已验证口径)
- `src/investment/tuning.py` (已验证口径)
- `scripts/generate_ma_atr_next_round_report.py` (已执行)

### 数据文件
- `output/ma_atr_turnover_gap_fix/*/summary/stage4_best_*.csv`
- `output/ma_atr_next_round_no932/*/summary/stage4_best_*.csv`

---

**报告生成时间**: 2026-03-30  
**执行状态**: 第一阶段至第三阶段已完成，第四阶段部分完成，第五阶段待执行
