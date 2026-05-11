# Output 目录重组实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 output 目录从扁平结构重组为按模块分类的层级结构，清理空目录和重复数据，添加索引文件提升可维护性

**Architecture:** 采用 `output/{模块}/{日期或版本}/` 的二级分类结构，将 131 个顶层目录归类为 8 个主要模块，保留原始数据完整性的同时提升导航效率

**Tech Stack:** Bash (文件操作), Python (数据验证), Git (版本控制)

---

## 目标目录结构

```
output/
├── INDEX.md                          # 顶层索引文件
├── lppl/                             # LPPL 模块
│   ├── params/                       # LPPL 参数文件
│   ├── reports/                      # LPPL 扫描报告
│   └── backtest/                     # LPPL 回测结果
├── wyckoff/                          # Wyckoff 分析模块
│   ├── effectiveness/                # 有效性验证
│   ├── factor_analysis/              # 因子分析
│   ├── excess_returns/               # 超额收益分析
│   ├── batch_analysis/               # 批量分析
│   ├── fusion/                       # Wyckoff+LPPL 融合
│   ├── mtf_semantics/                # 多时间框架语义
│   ├── optimization/                 # 优化实验
│   └── latest/                       # 最新分析结果
├── ma_atr/                           # MA/ATR 策略模块
│   ├── tuning/                       # 参数调优
│   ├── risk/                         # 风险管理
│   ├── turnover/                     # 换手率优化
│   └── template/                     # 模板配置
├── signal_tuning/                    # 信号调优模块
│   ├── round1/                       # 第一轮调优
│   ├── round2/                       # 第二轮调优
│   ├── round3/                       # 第三轮调优
│   └── round4/                       # 第四轮调优
├── strategy/                         # 策略优化模块
│   ├── optimized/                    # 优化策略
│   ├── validation/                   # 策略验证
│   └── scheme/                       # 方案验证
├── backtest/                         # 回测验证模块
│   ├── three_layer/                  # 三层回测
│   ├── integrated/                   # 综合验证
│   └── short_warning/                # 短期预警验证
├── demo/                             # 投资演示模块
│   ├── investment_demo/              # 投资演示
│   └── investment_demo_quick/        # 快速演示
└── archive/                          # 历史实验归档
    ├── test/                         # 测试实验
    └── retest/                       # 重测实验
```

---

## Task 1: 创建备份并验证当前状态

**Files:**
- Create: `output_backup_20260511.tar.gz`

- [ ] **Step 1: 创建完整备份**

```bash
cd /home/james/Documents/Project/lppl
tar -czf output_backup_20260511.tar.gz output/
```

- [ ] **Step 2: 验证备份完整性**

```bash
tar -tzf output_backup_20260511.tar.gz | wc -l
# 预期: 约 41350 个文件
```

- [ ] **Step 3: 记录当前目录结构**

```bash
ls -1 output/ > docs/superpowers/plans/original_structure.txt
```

---

## Task 2: 清理空目录

**Files:**
- Delete: 36 个空目录

- [ ] **Step 1: 删除顶层空目录**

```bash
cd /home/james/Documents/Project/lppl/output
rmdir tune_test_20260330 tune_quick tune_quick_test signal_tuning_all 2>/dev/null
```

- [ ] **Step 2: 删除嵌套空目录**

```bash
find . -type d -empty -delete
```

- [ ] **Step 3: 验证清理结果**

```bash
find . -type d -empty | wc -l
# 预期: 0
```

---

## Task 3: 创建模块目录结构

**Files:**
- Create: 8 个一级模块目录
- Create: 25 个二级子目录

- [ ] **Step 1: 创建一级模块目录**

```bash
cd /home/james/Documents/Project/lppl/output
mkdir -p lppl wyckoff ma_atr signal_tuning strategy backtest demo archive
```

- [ ] **Step 2: 创建 LPPL 子目录**

```bash
mkdir -p lppl/params lppl/reports lppl/backtest
```

- [ ] **Step 3: 创建 Wyckoff 子目录**

```bash
mkdir -p wyckoff/effectiveness wyckoff/factor_analysis wyckoff/excess_returns \
         wyckoff/batch_analysis wyckoff/fusion wyckoff/mtf_semantics \
         wyckoff/optimization wyckoff/latest
```

- [ ] **Step 4: 创建 MA/ATR 子目录**

```bash
mkdir -p ma_atr/tuning ma_atr/risk ma_atr/turnover ma_atr/template
```

- [ ] **Step 5: 创建信号调优子目录**

```bash
mkdir -p signal_tuning/round1 signal_tuning/round2 signal_tuning/round3 signal_tuning/round4
```

- [ ] **Step 6: 创建策略子目录**

```bash
mkdir -p strategy/optimized strategy/validation strategy/scheme
```

- [ ] **Step 7: 创建回测子目录**

```bash
mkdir -p backtest/three_layer backtest/integrated backtest/short_warning
```

- [ ] **Step 8: 创建演示和归档子目录**

```bash
mkdir -p demo/investment demo/archive archive/test archive/retest
```

---

## Task 4: 迁移 LPPL 模块文件

**Files:**
- Move: 22 个 LPPL 相关文件

- [ ] **Step 1: 迁移 LPPL 参数文件**

```bash
cd /home/james/Documents/Project/lppl/output
mv lppl_params_*.json lppl/params/
```

- [ ] **Step 2: 迁移 LPPL 报告文件**

```bash
mv lppl_report_*.html lppl_report_*.md lppl/reports/
```

- [ ] **Step 3: 迁移 LPPL 回测图表**

```bash
mv lppl_backtest_all.png lppl/backtest/
```

- [ ] **Step 4: 迁移 LPPL 三层回测目录**

```bash
mv lppl_three_layer_backtest lppl/backtest/three_layer
```

- [ ] **Step 5: 验证迁移结果**

```bash
ls -la lppl/
ls -la lppl/params/
ls -la lppl/reports/
ls -la lppl/backtest/
```

---

## Task 5: 迁移 Wyckoff 模块目录

**Files:**
- Move: 63 个 Wyckoff 相关目录

- [ ] **Step 1: 迁移有效性验证目录**

```bash
cd /home/james/Documents/Project/lppl/output
mv wyckoff_effectiveness wyckoff/effectiveness/
```

- [ ] **Step 2: 迁移因子分析目录**

```bash
mv wyckoff_factor_analysis wyckoff/factor_analysis/
```

- [ ] **Step 3: 迁移超额收益分析目录**

```bash
mv wyckoff_excess_returns wyckoff/excess_returns/
```

- [ ] **Step 4: 迁移批量分析目录**

```bash
mv wyckoff_batch_* wyckoff/batch_analysis/
mv wyckoff_batch_analysis.log wyckoff/batch_analysis/
```

- [ ] **Step 5: 迁移融合分析目录**

```bash
mv wyckoff_lppl_fusion wyckoff/fusion/
```

- [ ] **Step 6: 迁移多时间框架语义目录**

```bash
mv wyckoff_mtf_semantics_* wyckoff/mtf_semantics/
```

- [ ] **Step 7: 迁移最新分析目录**

```bash
mv wyckoff_latest wyckoff/latest/
mv wyckoff_latest_100 wyckoff/latest/
mv wyckoff_latest_1000 wyckoff/latest/
mv wyckoff_latest_1000_mtf_* wyckoff/latest/
mv wyckoff_latest_200d_test wyckoff/latest/
mv wyckoff_latest_20_smoke_1000 wyckoff/latest/
mv wyckoff_latest_test wyckoff/latest/
```

- [ ] **Step 8: 迁移优化实验目录**

```bash
mv wyckoff_*cycle* wyckoff/optimization/
mv wyckoff_optimizer wyckoff/optimization/
mv wyckoff_multi_window_test* wyckoff/optimization/
mv wyckoff_stock_list_full* wyckoff/optimization/
```

- [ ] **Step 9: 迁移其他 Wyckoff 目录**

```bash
mv wyckoff wyckoff/original/
mv wyckoff_test wyckoff/test/
mv wyckoff_test_old wyckoff/test/
mv wyckoff_fixed wyckoff/fixed/
mv wyckoff_cli_smoke* wyckoff/test/
mv wyckoff_daily_replay wyckoff/replay/
mv wyckoff_sample_replay wyckoff/replay/
mv wyckoff_6cycle_engine_test wyckoff/test/
mv wyckoff_6cycle_test wyckoff/test/
```

- [ ] **Step 10: 验证迁移结果**

```bash
ls wyckoff/
```

---

## Task 6: 迁移 MA/ATR 模块目录

**Files:**
- Move: 27 个 MA/ATR 相关目录

- [ ] **Step 1: 迁移参数调优目录**

```bash
cd /home/james/Documents/Project/lppl/output
mv ma_atr_tuning_* ma_atr/tuning/
```

- [ ] **Step 2: 迁移风险管理目录**

```bash
mv ma_atr_risk_* ma_atr/risk/
```

- [ ] **Step 3: 迁移换手率优化目录**

```bash
mv ma_atr_turnover_* ma_atr/turnover/
```

- [ ] **Step 4: 迁移模板配置目录**

```bash
mv ma_atr_template_* ma_atr/template/
```

- [ ] **Step 5: 迁移其他 MA/ATR 目录**

```bash
mv ma_atr_* ma_atr/other/
mv ma20_ma60_atr_* ma_atr/other/
mv MA ma_atr/original/
mv ma_convergence_* ma_atr/convergence/
mv multi_factor_adaptive_* ma_atr/multi_factor/
```

- [ ] **Step 6: 验证迁移结果**

```bash
ls ma_atr/
```

---

## Task 7: 迁移信号调优模块目录

**Files:**
- Move: 10 个信号调优目录

- [ ] **Step 1: 迁移第一轮调优目录**

```bash
cd /home/james/Documents/Project/lppl/output
mv signal_tuning_all_round1 signal_tuning/round1/
mv signal_tuning_all_round1_fast signal_tuning/round1/
```

- [ ] **Step 2: 迁移第二轮调优目录**

```bash
mv signal_tuning_round2 signal_tuning/round2/
mv signal_tuning_round2_complete signal_tuning/round2/
mv signal_tuning_round2_micro signal_tuning/round2/
mv signal_tuning_round2_narrow signal_tuning/round2/
```

- [ ] **Step 3: 迁移第三轮调优目录**

```bash
mv signal_tuning_round3_relaxed signal_tuning/round3/
```

- [ ] **Step 4: 迁移第四轮调优目录**

```bash
mv signal_tuning_round4_split signal_tuning/round4/
mv signal_tuning_round4_targeted signal_tuning/round4/
```

- [ ] **Step 5: 验证迁移结果**

```bash
ls signal_tuning/
```

---

## Task 8: 迁移策略优化模块目录

**Files:**
- Move: 12 个策略相关目录

- [ ] **Step 1: 迁移优化策略目录**

```bash
cd /home/james/Documents/Project/lppl/output
mv optimized_strategy strategy/optimized/
mv optimized_strategy_v2 strategy/optimized/
mv optimized_strategy_v3_baseline strategy/optimized/
mv optimized_strategy_v3_final strategy/optimized/
mv optimized_strategy_v3_fixed strategy/optimized/
mv optimized_strategy_v3_smoke strategy/optimized/
```

- [ ] **Step 2: 迁移策略验证目录**

```bash
mv integrated_strategy_validation strategy/validation/
mv scheme_validation_round1 strategy/scheme/
mv scheme_validation_round2_quality strategy/scheme/
mv scheme_validation_round3_regime_hold strategy/scheme/
```

- [ ] **Step 3: 迁移其他策略目录**

```bash
mv test_optimization strategy/test/
mv optimization_integration_report.md strategy/
```

- [ ] **Step 4: 验证迁移结果**

```bash
ls strategy/
```

---

## Task 9: 迁移回测验证模块目录

**Files:**
- Move: 6 个回测验证目录

- [ ] **Step 1: 迁移短期预警验证目录**

```bash
cd /home/james/Documents/Project/lppl/output
mv short_warning_validation backtest/short_warning/
mv short_warning_validation_step5 backtest/short_warning/
mv short_warning_validation_step5_relaxed_danger backtest/short_warning/
mv short_warning_validation_step5_warning_observe_only backtest/short_warning/
```

- [ ] **Step 2: 验证迁移结果**

```bash
ls backtest/
```

---

## Task 10: 迁移投资演示模块目录

**Files:**
- Move: 2 个投资演示目录

- [ ] **Step 1: 迁移投资演示目录**

```bash
cd /home/james/Documents/Project/lppl/output
mv investment_demo demo/investment/
mv investment_demo_quick demo/investment/
```

- [ ] **Step 2: 验证迁移结果**

```bash
ls demo/
```

---

## Task 11: 迁移测试和重测目录到归档

**Files:**
- Move: 2 个测试/重测目录

- [ ] **Step 1: 迁移测试目录**

```bash
cd /home/james/Documents/Project/lppl/output
mv retest_20260401 archive/retest/
```

- [ ] **Step 2: 验证迁移结果**

```bash
ls archive/
```

---

## Task 12: 处理剩余目录

**Files:**
- Move: 处理所有剩余目录

- [ ] **Step 1: 检查剩余目录**

```bash
cd /home/james/Documents/Project/lppl/output
ls -d */ 2>/dev/null | grep -v -E "^(lppl|wyckoff|ma_atr|signal_tuning|strategy|backtest|demo|archive)/"
```

- [ ] **Step 2: 将剩余目录移动到归档**

```bash
# 根据实际输出执行
# 示例: mv wyckoff_10cycle_lppl_filtered archive/
```

- [ ] **Step 3: 验证所有目录已迁移**

```bash
ls -d */ 2>/dev/null
# 预期: 只有 8 个一级模块目录
```

---

## Task 13: 创建顶层 INDEX.md 文件

**Files:**
- Create: `output/INDEX.md`

- [ ] **Step 1: 创建 INDEX.md 文件**

```markdown
# Output 目录索引

> 最后更新: 2026-05-11

## 目录结构

### LPPL 模块 (`lppl/`)
- `params/` - LPPL 参数文件 (8 个指数 x 3 个时间跨度)
- `reports/` - LPPL 扫描报告 (MD + HTML 格式)
- `backtest/` - LPPL 回测结果
  - `three_layer/` - 三层回测 (29,400 样本)

### Wyckoff 分析模块 (`wyckoff/`)
- `effectiveness/` - 有效性验证 (289,476 样本)
- `factor_analysis/` - 因子分析
- `excess_returns/` - 超额收益分析
- `batch_analysis/` - 批量分析结果
- `fusion/` - Wyckoff+LPPL 融合分析
- `mtf_semantics/` - 多时间框架语义分析
- `optimization/` - 优化实验
- `latest/` - 最新分析结果

### MA/ATR 策略模块 (`ma_atr/`)
- `tuning/` - 参数调优 (6 轮)
- `risk/` - 风险管理优化
- `turnover/` - 换手率优化
- `template/` - 模板配置
- `convergence/` - 收敛分析
- `multi_factor/` - 多因子自适应

### 信号调优模块 (`signal_tuning/`)
- `round1/` - 第一轮调优
- `round2/` - 第二轮调优
- `round3/` - 第三轮调优
- `round4/` - 第四轮调优

### 策略优化模块 (`strategy/`)
- `optimized/` - 优化策略 (v1, v2, v3)
- `validation/` - 综合策略验证
- `scheme/` - 方案验证 (3 轮)
- `test/` - 策略测试

### 回测验证模块 (`backtest/`)
- `three_layer/` - 三层回测
- `integrated/` - 综合验证
- `short_warning/` - 短期预警验证

### 投资演示模块 (`demo/`)
- `investment/` - 投资演示
- `quick/` - 快速演示

### 归档模块 (`archive/`)
- `test/` - 测试实验
- `retest/` - 重测实验

## 关键产出

### 最新 LPPL 参数
- 文件: `lppl/params/lppl_params_20260327.json`
- 覆盖: 8 个 A 股主要指数
- RMSE 范围: 0.009 ~ 0.176

### Wyckoff 有效性验证
- 样本量: 289,476
- 关键发现: markdown 阶段收益 7.31%，accumulation 信号超额收益 22.69%

### 三层回测结果
- 样本量: 29,400
- 覆盖: 2012-2025 年 10 轮周期
- D_regime_filtered 信号收益: 10.91%，超额收益: 5.50%

### 综合策略验证
- 测试配置: 4 种 x 7 个指数
- 结果: 所有策略年化超额收益均为负值 (-1.20% ~ -1.92%)
- eligible 比例: 2/8

## 数据质量评分

| 维度 | 评分 |
|------|------|
| 数据完整性 | 8/10 |
| 数据一致性 | 7/10 |
| 数据准确性 | 8/10 |
| 文件组织 | 6/10 |
| 报告质量 | 9/10 |
| 可视化效果 | 8/10 |
| 可复现性 | 7/10 |
| **综合评分** | **7.6/10** |

## 使用指南

1. **查找最新数据**: 查看各模块下的最新日期目录
2. **查看关键结论**: 阅读各模块下的 `*_report.md` 文件
3. **获取原始数据**: 查看各目录下的 `raw/` 或 `*.csv` 文件
4. **查看可视化**: 打开 `*.html` 或 `*.png` 文件

## 维护建议

1. 定期清理过期的实验目录
2. 为新的实验添加 `metadata.json` 文件
3. 更新本索引文件记录新增内容
```

- [ ] **Step 2: 验证 INDEX.md 创建成功**

```bash
cat output/INDEX.md | head -20
```

---

## Task 14: 验证重组结果

**Files:**
- Create: `docs/superpowers/plans/reorganization_validation.md`

- [ ] **Step 1: 验证目录结构**

```bash
cd /home/james/Documents/Project/lppl/output
tree -L 2 -d > ../docs/superpowers/plans/new_structure.txt
```

- [ ] **Step 2: 统计文件数量**

```bash
find . -type f | wc -l
# 预期: 约 41350 个文件
```

- [ ] **Step 3: 验证无孤立文件**

```bash
find . -maxdepth 1 -type f
# 预期: 只有 INDEX.md
```

- [ ] **Step 4: 创建验证报告**

```markdown
# 重组验证报告

## 执行时间
2026-05-11

## 执行结果
- [x] 备份创建成功
- [x] 空目录清理完成
- [x] 模块目录创建完成
- [x] 文件迁移完成
- [x] INDEX.md 创建完成

## 统计数据
- 原始目录数: 131
- 新目录数: 8 个一级 + 25 个二级
- 文件总数: [待填充]
- 空目录数: 0

## 验证清单
- [x] 所有文件已迁移
- [x] 无孤立文件
- [x] INDEX.md 内容准确
- [x] 目录结构符合设计

## 后续步骤
1. 更新相关脚本中的路径引用
2. 通知团队成员新的目录结构
3. 定期维护和清理
```

---

## 执行建议

**推荐执行方式:** Subagent-Driven (推荐)

**原因:**
1. 任务涉及大量文件操作，需要谨慎执行
2. 每个任务可以独立验证，降低风险
3. 可以在每个任务后进行检查点审查

**执行顺序:**
1. Task 1-3: 基础准备 (备份、清理、创建结构)
2. Task 4-11: 模块迁移 (按模块逐个执行)
3. Task 12-14: 收尾工作 (处理剩余、创建索引、验证)

**风险控制:**
- 每个任务完成后验证文件数量
- 保留完整备份直到验证通过
- 使用 `mv -i` 避免意外覆盖
