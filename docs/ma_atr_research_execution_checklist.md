# MA + ATR 研发执行任务清单

日期：2026-03-30

本文档是 [ma_atr_research_roadmap_for_newcomers.md](/home/james/Documents/Project/lppl/docs/ma_atr_research_roadmap_for_newcomers.md) 的执行版。

目标只有一个：

- 把研发路线拆成新人可以逐条执行、逐条验收的任务

---

## 1. 执行总原则

1. 先修口径，再做参数。
2. 先跑样本外，再跑全量。
3. 先看结果是否一致，再看是否优化成功。
4. 任何任务只要引入新的指标，必须先写清楚单位和口径。

---

## 2. 第一阶段：基线复核

### 任务 2.1 复核当前文档和结果

- [ ] 阅读 `docs/ma_atr_turnover_gap_fix_report.md`
- [ ] 阅读 `docs/ma_atr_turnover_gap_fix_verification_report.md`
- [ ] 阅读 `docs/ma_atr_turnover_gap_newbie_summary_and_next_plan.md`
- [ ] 阅读 `docs/ma_atr_research_roadmap_for_newcomers.md`

#### 验收标准

- 能说清楚当前基线是 `Template A` 和 `Template B`
- 能说清楚 `turnover_rate`、`annualized_turnover_rate`、`turnover_gap` 三者区别
- 能说清楚为什么 `399006.SZ` 需要单独处理

### 任务 2.2 核对报告和 CSV

- [ ] 检查 `IS`、`OOS`、`FULL` 三个目录下的 `stage4_best` CSV
- [ ] 检查报告里的收益、回撤、换手数值是否与 CSV 一致
- [ ] 检查报告没有再把 `turnover_rate` 乘 100

#### 验收标准

- 报告与 CSV 完全一致
- 没有出现 `4000%` 这种错误换手显示

---

## 3. 第二阶段：口径修复验证

### 任务 3.1 检查代码口径

- [ ] 打开 `src/investment/backtest.py`
- [ ] 确认 `turnover_rate` 是累计换手率
- [ ] 确认 `annualized_turnover_rate` 是按投资年数年化后的换手率
- [ ] 确认 `turnover_gap = annualized_turnover_rate - turnover_cap`

#### 验收标准

- 同一个指标在代码、报告、CSV 里使用同一单位

### 任务 3.2 检查调优口径

- [ ] 打开 `src/investment/tuning.py`
- [ ] 确认 `turnover_cap` 比较用的是 `annualized_turnover_rate`
- [ ] 确认评分排序也优先使用 `annualized_turnover_rate`

#### 验收标准

- `turnover_cap` 不再和累计换手混用

### 任务 3.3 重新生成修复报告

- [ ] 使用修正版报告生成脚本重新生成报告
- [ ] 检查 `annualized_return` 和 `annualized_excess_return` 是否分开显示
- [ ] 检查 `turnover_gap` 是否写明公式

#### 验收标准

- 新报告与 CSV 一致
- `turnover_gap` 可直接从报告中复算

---

## 4. 第三阶段：样本外稳定性确认

### 任务 4.1 先看 OOS

- [ ] 查看 `Template A` 的 OOS 结果
- [ ] 查看 `Template B` 的 OOS 结果
- [ ] 记录每个指数的 `annualized_excess_return`
- [ ] 记录每个指数的 `max_drawdown`
- [ ] 记录每个指数的 `trade_count`
- [ ] 记录每个指数的 `annualized_turnover_rate`

#### 验收标准

- `Template A` OOS 仍然稳定
- `Template B` OOS 仍然稳定
- `399006.SZ` 仍然是重点观察对象

### 任务 4.2 比较 IS 和 OOS

- [ ] 对比同一指数的 IS 和 OOS
- [ ] 检查 OOS 是否明显退化
- [ ] 检查 OOS 是否出现换手暴涨

#### 验收标准

- OOS 没有出现明显塌陷
- OOS 的换手控制优于或不差于 IS

---

## 5. 第四阶段：换手治理任务

### 任务 5.1 锁定需要治理的指数

优先顺序：

1. `399006.SZ`
2. `000300.SH`
3. `000905.SH`

#### 验收标准

- 每个指数都能明确说出为什么要优先治理

### 任务 5.2 小范围扰动测试

- [ ] 只在现有稳定参数附近做小扰动
- [ ] 不扩 MA/ATR 大网格
- [ ] 不引入新的复杂模型
- [ ] 记录每次扰动对 `turnover_rate` 的影响
- [ ] 记录每次扰动对 `annualized_excess_return` 的影响

#### 验收标准

- 交易次数下降
- 年化超额不明显变差

### 任务 5.3 判断是否需要模板分层

- [ ] 检查 `Template A` 是否适合大盘/宽基
- [ ] 检查 `Template B` 是否适合高波动指数
- [ ] 判断 `399006.SZ` 是否需要单独模板

#### 验收标准

- 能明确指出哪些指数不该共用同一模板

---

## 6. 第五阶段：状态识别原型

### 任务 6.1 准备轻量特征

- [ ] 收集均线斜率
- [ ] 收集 ATR 水平
- [ ] 收集最近回撤
- [ ] 收集最近波动率
- [ ] 收集最近若干日收益方向

#### 验收标准

- 特征都能从现有数据直接生成

### 任务 6.2 做一个最小可用路由器

- [ ] 用逻辑回归或 LightGBM 做模板路由
- [ ] 输出“用 Template A / Template B / 保守模式”
- [ ] 不直接做股票买卖预测

#### 验收标准

- 路由结果可解释
- 路由不会导致换手暴增

### 任务 6.3 离线验证

- [ ] 用样本外验证路由器
- [ ] 检查状态切换频率
- [ ] 检查切换后策略表现

#### 验收标准

- 路由器能减少错误模板使用
- 路由器不会制造更多噪声交易

---

## 7. 每周执行建议

### 第 1 周

- 完成基线复核
- 完成口径修复验证
- 重跑并核对报告

### 第 2 周

- 聚焦 `399006.SZ`
- 做小范围参数扰动
- 记录换手变化

### 第 3 周

- 决定是否做模板分层
- 如果需要，设计路由规则

### 第 4 周

- 做轻量状态识别原型
- 只做离线验证，不上复杂模型

---

## 8. 最终交付物

这一阶段结束时，应该至少产出以下内容：

- 一份与 CSV 完全一致的修复报告
- 一份面向新人的基线总结
- 一份明确的下一轮实验矩阵
- 一份模板分层或状态识别原型说明

---

## 9. 停止条件

如果出现以下任一情况，先停下来，不要继续扩实验：

- 报告和 CSV 再次不一致
- `turnover_rate` 和 `annualized_turnover_rate` 口径混乱
- 只在全量上好看，OOS 变差
- 参数范围不断扩大
- `399006.SZ` 问题没有单独隔离

