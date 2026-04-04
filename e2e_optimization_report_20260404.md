# LPPL 因子计算模组 E2E 优化结论文档

**更新日期**: 2026-04-04  
**结论状态**: 已完成修复、复验通过、文档已校正  
**最终验证结果**: `110 passed in 8.58s`，`ruff check` 全部通过

---

## 一、执行摘要

本轮 E2E 优化对系统产生了**明确且可验证的正优化**，主要体现在四个方面：

1. **核心计算口径更一致**
   - `src/lppl_core.py` 与 `src/lppl_engine.py` 对 `tc_bound`、风险阈值、极端数值处理的口径已对齐。
   - `src/lppl_engine.calculate_risk_level()` 已改为尊重调用方传入的 `LPPLConfig`，不再被 `DEFAULT_CONFIG` 硬绑定。

2. **交易与回测行为更正确**
   - 修复了 `bubble_watch` 场景下 MA 死叉意外减仓。
   - 修复了 `sell_votes` 被压成布尔值的问题。
   - 修复了 `daily_return` 首日始终为 `0.0` 的口径偏差。
   - 修复了 `indicator_warmup` 未考虑 `atr_period` 的问题。

3. **指标统计更可信**
   - Calmar 改为基于 `annualized_excess_return`。
   - `positive_consensus_rate` / `negative_consensus_rate` 改为以 `valid_n` 为分母。
   - ATR 除零保护与 Numba 非有限值保护增强了数值稳定性。

4. **工程闭环完成度更高**
   - 残留的 CLI 配置不一致、全局 warnings 吞掉、lint 未清问题已补齐。
   - 测试从原来的 `103` 项增加到 `110` 项，新增用例覆盖了本轮审计发现的残余问题。

---

## 二、最终修复清单

### A. 已确认的业务/算法修复

| 类别 | 文件 | 修复项 | 结论 |
|---|---|---|---|
| 核心拟合 | `src/lppl_core.py` | `tc_bound` 从 `100` 提升到 `150`，与引擎默认配置统一 | 正优化 |
| 风险判定 | `src/lppl_core.py` | `calculate_risk_level` 阈值改为 `5/12/25` 口径 | 正优化 |
| 风险判定 | `src/lppl_engine.py` | `calculate_risk_level(..., config=...)` 改为尊重外部配置 | 正优化 |
| 共识统计 | `src/lppl_engine.py` | `positive_consensus_rate` / `negative_consensus_rate` 分母改为 `valid_n` | 正优化 |
| 稳定性 | `src/lppl_engine.py` | `valid_n == 0` 时提前返回，避免空数组统计 | 正优化 |
| 警告策略 | `src/lppl_engine.py` | 全局 `ignore` 改为仅忽略 `RuntimeWarning` 和 `OptimizeWarning` | 正优化 |
| 交易逻辑 | `src/investment/backtest.py` | `bubble_watch` 时清除 `sell_candidate`，避免意外减仓 | 正优化 |
| 交易逻辑 | `src/investment/backtest.py` | `sell_votes` 改为真实计数 | 正优化 |
| 回测预热 | `src/investment/backtest.py` | `indicator_warmup` 纳入 `atr_period + atr_ma_window - 1` | 正优化 |
| 指标统计 | `src/investment/backtest.py` | Calmar 使用 `annualized_excess_return` | 正优化 |
| 指标统计 | `src/investment/backtest.py` | 首日 `daily_return` 改为实际值 | 正优化 |
| 数值稳定 | `src/investment/backtest.py` | ATR 除零保护改为 `clip(lower=1e-10)` | 正优化 |
| 调优评分 | `src/investment/tuning.py` | `_risk_band` 删除不可达分支 | 正优化 |
| 数值稳定 | `src/lppl_core.py` | 底部信号得分增加 `max(0.0, ...)` 下界保护 | 正优化 |
| 数值稳定 | `src/lppl_core.py` | Numba 结果非有限值时回退 `np.inf` | 正优化 |

### B. 本轮补掉的残余问题

| 残余问题 | 文件 | 修复内容 | 状态 |
|---|---|---|---|
| `calculate_risk_level` 仍走默认配置 | `src/lppl_engine.py` | 新增 `config` 参数并使用 `active_config` | 已修复 |
| CLI 默认阈值仍为旧口径 | `src/cli/lppl_verify_v2.py` | `tc_bound/danger_days/warning_days/watch_days` 统一到核心口径 | 已修复 |
| CLI 仍全局吞掉 warnings | `src/cli/lppl_verify_v2.py` | 改为定向过滤 `RuntimeWarning` / `OptimizeWarning` | 已修复 |
| import 排序未通过 lint | `src/lppl_engine.py`, `src/investment/__init__.py` | 已整理 | 已修复 |

---

## 三、测试补强

本轮额外新增并通过的关键测试包括：

- `tests/unit/test_lppl_engine_ensemble.py`
  - 校验 `positive_consensus_rate` / `negative_consensus_rate` 使用 `valid_n`
  - 校验 `calculate_risk_level` 尊重调用方传入配置

- `tests/unit/test_lppl_verify_outputs.py`
  - 校验 `lppl_verify_v2.create_config()` 与核心阈值口径一致
  - 校验 CLI 不再注册 broad `ignore all warnings`

- `tests/unit/test_investment_backtest.py`
  - 校验首日 `daily_return` 使用真实费用影响

测试总数由之前的 `103` 项提升到 **110** 项。

---

## 四、最终验证结果

### 1. 单元/集成测试

```text
PYTHONPATH=. .venv/bin/pytest -q
110 passed in 8.58s
```

### 2. 静态检查

```text
.venv/bin/ruff check src tests *.py
All checks passed!
```

---

## 五、对“是否产生正优化”的最终判断

### 结论

本次修改对系统产生了**实质性正优化**，不是文档层面的“表面优化”。

### 判断依据

1. **正确性提升**
   - 风险阈值与交易行为更符合配置语义。
   - 回测输出字段和统计指标更接近真实交易结果。

2. **稳定性提升**
   - 空数组、ATR 除零、Numba 非有限值等边界情况处理更稳健。

3. **一致性提升**
   - 核心模块与 CLI 默认口径已经统一，不再存在先前审计发现的明显分裂配置。

4. **可验证性提升**
   - 新增 5 项测试，完整回归通过，`ruff` 全绿。

### 风险等级

当前状态可判定为：

- **功能正确性**: 良好
- **数值稳定性**: 良好
- **工程一致性**: 良好
- **可回归验证性**: 良好

未发现本轮修复后新增的阻断性问题。

---

## 六、仍需保留的客观说明

虽然当前结论为正优化，但仍应保持以下工程口径：

1. `ma_cross_atr_lppl_v1` 仍是简化模型，不具备 `multi_factor_v1` 的完整状态机能力。
2. Calmar 与相关报表口径已经变化，历史导出的旧报告不应与新结果直接横向比较。
3. 短周期样本的年化收益仍然仅供参考，这属于指标解释边界，不是本轮缺陷。

这些属于**模型设计边界**，不属于本轮残留 bug。

---

## 七、最终结论

截至 2026-04-04，本次 E2E 优化已经完成以下闭环：

- 问题识别
- 代码修复
- 残余问题补齐
- 测试补强
- 全量回归
- 静态检查
- 文档校正

**最终结论**：

> 本轮修改已对 LPPL 因子计算、交易信号生成、回测统计与 CLI 配置一致性产生明确正优化；  
> 当前代码状态通过 110 项测试和静态检查，可视为“本轮优化目标已达成，系统进入可继续迭代的稳定状态”。  
