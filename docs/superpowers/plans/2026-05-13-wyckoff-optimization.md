# Wyckoff 策略优化实施计划

> **For agentic workers:** Use `executing-plans` to implement this plan task-by-task. Each task produces testable output before moving to the next.

**Goal:** P0参数优化(+1.06%收益) + P2多策略合成(Sharpe倍增)

**Architecture:** 两步走——先改执行参数(1个脚本函数),再合成多信号(因子加权)

**Tech Stack:** Python/pandas/numpy, existing `scripts/run_v2plus_final_test.py`

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `scripts/run_v2plus_final_test.py` | 被修改: `calc_v2plus_return`函数 (P0优化) |
| `src/wyckoff/trading.py` | 被修改: 新增 `calc_v2plus_return_v2` (P0优化后版本) |
| `scripts/run_multifactor_test.py` | 新建: 多策略合成验证 (P2) |
| `output/wyckoff_v2plus_test/v2plus_results.json` | P0验证基准数据 |
| `output/wyckoff_multifactor_test/` | P2验证输出 |

---

## Step 1 (P0): 参数优化

### Task 1.1: ATR乘数差异化——未达目标交易放宽止损

**设计:**
- 如果交易在30天内未达第一目标 → 使用更宽的ATR乘数 (原乘数 + 1.0)
- 如果交易已达第一目标 → 使用原乘数
- 逻辑嵌入 `calc_v2plus_return` 函数

**验证方法:** 修改后运行全量测试, 对比 trailing_stop 组的损失变化

### Task 1.2: 叠加-15%硬止损

**设计:**
- 在结构止损 `struct_stop` 之外, 再加一道硬止损 `hard_stop = entry * 0.85`
- 取两者中的较高者(更早触发): `effective_stop = max(struct_stop, hard_stop)`
- 如果结构止损已经在 -7% 以内 → 硬止损不生效
- 如果结构止损在 -25% → 硬止损在 -15% 更早触发

**验证方法:** 修改后运行全量测试, 对比 stop_loss 组的平均损失变化

---

## Step 2 (P2): 多策略合成

### Task 2.1: 识别可用因子

从已有系统中可提取的因子:
1. Wyckoff Phase (当前使用)
2. Market Regime (120d MA)
3. MTF Alignment (多周期对齐)
4. LPPL泡沫指数 (已有因子分析报告)
5. MA/ATR信号 (已有策略验证)
6. 置信度等级 (engine confidence)
7. 退出机制本身作为因子

### Task 2.2: 构建因子组合策略

**设计:**
- 每个因子独立评分(0-1)
- 加权综合评分 = Σ(wi × score_i)
- 权重通过历史数据优化
- 只有综合评分 > 阈值时才交易

**验证方法:** 与v2+对比夏普比

---

## 自检清单

- [ ] Task 1.1: ATR乘数差异化实现正确
- [ ] Task 1.1: 验证 trailing_stop 损失从 -5.28% 降低
- [ ] Task 1.2: 硬止损在结构止损之前触发
- [ ] Task 1.2: 验证 stop_loss 损失从 -20.93% 降低
- [ ] P0综合: 收益从 +1.69% 提升
- [ ] Task 2.1: 识别了至少3个可用因子
- [ ] Task 2.2: 合成策略夏普高于单策略
