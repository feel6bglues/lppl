# 威科夫融合引擎与状态管理规范

**文档日期**: 2026-04-07  
**适用对象**: 融合引擎实现者 / 状态管理实现者 / 测试工程师  
**文档目标**: 锁定双引擎裁决规则、冲突矩阵和状态文件结构

---

## 1. 融合目标

融合引擎负责：

- 合并数据引擎与图像引擎结果
- 发现冲突与一致性
- 计算最终置信度
- 生成统一 `AnalysisResult`
- 保存可持续跟踪的状态文件

---

## 2. 主次裁判规则

### 2.1 数据主判

以下字段必须以数据引擎为准：

- `bc_found`
- `phase`
- `micro_action`
- `spring_detected`
- `utad_detected`
- `t1_risk_assessment`
- `rr_assessment`
- `decision`
- `trigger`
- `invalidation`
- `target_1`

### 2.2 图像辅助

图像证据主要作用于：

- `weekly_context`
- `intraday_context`
- `visual_boundary_confirmation`
- `cross_timeframe_alignment`
- `confidence_adjustment`

---

## 3. 融合顺序

融合必须按以下顺序执行：

1. 读取 `DailyRuleResult`
2. 读取 `ImageEvidenceBundle`
3. 计算图片可用性与可信度
4. 生成冲突列表
5. 计算一致性评分
6. 调整最终置信度
7. 复核保守门槛
8. 输出 `AnalysisResult`

---

## 4. 冲突矩阵

### 4.1 数据 = Distribution，图片 = Markup

- 结果：保留 `watch_only` 或 `abandon`
- 处理：置信度降级
- 备注：写入 `phase_conflict_distribution_vs_markup`

### 4.2 数据 = Spring candidate，周线图片 = 高位供应区

- 结果：不允许直接做多
- 处理：降级到 `watch_only`
- 备注：写入 `weekly_overhead_supply_conflict`

### 4.3 数据 = No Trade Zone，图片 = 局部突破

- 结果：保持 `no_trade_zone`
- 处理：图片不推翻数据结论

### 4.4 数据 = 多头候选，盘中图片无确认

- 结果：保留 trigger，不提高置信度

### 4.5 多张图片互相冲突

- 结果：图像证据整体降级
- 处理：`image_confidence_cap = low`

---

## 5. 一致性评分

一致性评分由以下维度组成：

- 阶段一致性
- 趋势一致性
- 边界一致性
- 多周期上下文一致性
- 图像质量权重

结果可分为：

- `high_alignment`
- `medium_alignment`
- `low_alignment`
- `conflicted`

---

## 6. 最终置信度规则

最终置信度由四部分组成：

- `rule_score`
- `image_quality_score`
- `cross_tf_score`
- `consistency_score`

### A级

- 数据结论明确
- 周线与盘中图像支持
- 冲突少
- 图像质量高

### B级

- 数据明确
- 图像多数支持
- 有少量不确定点

### C级

- 规则结论勉强成立
- 图片冲突明显或质量一般
- 只能观察

### D级

- BC 不成立
- 图片不可用
- 冲突大
- 结构混乱

强制规则：

- 图片永远不能单独把 C 提升到 A
- 图片 `low/unusable` 只能降级，不能升级

---

## 7. 保守复核门槛

融合完成后，必须再次检查：

- `bc_found == false`
- `phase in {distribution, markdown}`
- `rr_assessment` 不合格
- `spring_detected` 且冷冻期未结束
- `consistency_score == conflicted`

任一命中时，最终结论必须保守降级。

---

## 8. 状态文件 schema

状态文件必须至少包含：

- `symbol`
- `asset_type`
- `analysis_date`
- `last_phase`
- `last_micro_action`
- `last_confidence`
- `bc_found`
- `spring_detected`
- `freeze_until`
- `watch_status`
- `trigger_armed`
- `trigger_text`
- `invalid_level`
- `target_1`
- `weekly_context`
- `intraday_context`
- `conflict_summary`
- `last_decision`
- `abandon_reason`

---

## 9. Spring 冷冻期状态机

### 初始状态

- `spring_detected = false`
- `watch_status = none`

### 识别到 Spring

- `spring_detected = true`
- `freeze_until = detect_date + 3 trading days`
- `watch_status = cooling_down`

### 冷冻期内

- 不允许输出 `long_setup`
- 只允许 `watch_only`

### 冷冻期结束后

- 若 trigger 满足且结构未破坏，可升级为执行候选

---

## 10. 附录 A 连续性追踪模板

每次输出必须包含：

- 上次结论
- 本次结论
- 周线背景是否变化
- 日线阶段是否变化
- 冷冻期是否结束
- trigger 是否接近
- invalidation 是否被破坏
- 下次观察重点

---

## 11. 融合完成标志

以下全部满足时视为融合层实现完成：

- 数据与图片可合并
- 冲突矩阵生效
- 置信度可复算
- 状态文件落盘
- 连续性追踪模板可生成
