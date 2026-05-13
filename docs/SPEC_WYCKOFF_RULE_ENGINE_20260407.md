# 威科夫规则引擎规范

**文档日期**: 2026-04-07  
**适用对象**: 规则引擎实现者 / 测试工程师  
**文档目标**: 锁定日线规则，不允许实现时自由补决策

---

## 1. 输入数据规范

输入 DataFrame 必须包含：

- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`

数据要求：

- 至少 100 根 K 线
- 时间升序
- 无负成交量
- 开高低收为正

若不满足，直接输出：

- `confidence = D`
- `decision = abandon`
- `abandon_reason = invalid_input_data`

---

## 2. 执行总顺序

规则引擎必须严格按以下顺序执行：

1. 输入校验
2. 预处理
3. Step 0 BC定位扫描
4. Step 1 大局观与阶段
5. Step 2 努力与结果
6. Step 3 Phase C 终极测试
7. Step 3.5 反事实压力测试
8. Step 4 T+1 与盈亏比评估
9. Step 5 交易计划生成

不得跳步。

---

## 3. 预处理

预处理阶段必须输出：

- 最近窗口趋势方向
- 相对量能标签
- 波动分层
- 局部高低点候选
- 缺口候选
- 长影线候选
- 涨跌停异常候选

量能标签只允许以下枚举：

- `extreme_high`
- `above_average`
- `contracted`
- `extreme_contracted`

严禁输出编造的成交量绝对数字。

---

## 4. Step 0: BC定位扫描

### 4.1 强制原则

任何方向性判断前必须先定位 BC。

### 4.2 BC 候选条件

BC 候选至少满足：

- 左侧存在明显上涨
- 是局部高点或近似局部高点
- 成交量标签为 `extreme_high` 或 `above_average`
- 伴随以下任一增强信号：
  - 高位长上影
  - 放量滞涨
  - 跳空后衰竭
  - 假突破后回落

### 4.3 终止规则

若无任何 BC 候选达到阈值：

- `bc_found = false`
- `confidence = D`
- `decision = abandon`
- `abandon_reason = bc_not_found`

后续 Step 1~5 不得输出方向性结论。

---

## 5. Step 1: 大局观与阶段

### 5.1 时间周期

默认按日线结构逻辑分析。

### 5.2 阶段识别

只允许以下阶段：

- `accumulation`
- `markup`
- `distribution`
- `markdown`
- `no_trade_zone`

### 5.3 边界来源

边界只允许来自：

- BC
- AR
- SC
- ST
- 放量极值带
- 关键起跌点
- 未测试缺口带

不得用主观画线代替结构边界。

---

## 6. Step 2: 努力与结果

必须识别以下现象：

- 放量滞涨
- 缩量上推
- 下边界供给枯竭
- 高位炸板遗迹
- 涨跌停异常
- 吸筹倾向
- 派发倾向

规则要求：

- 派发证据强于吸筹证据时，不得输出积极做多计划
- 图表信号杂乱时，输出 `no_trade_zone`

---

## 7. Step 3: Phase C 终极测试

必须识别：

- `spring_detected`
- `utad_detected`
- `st_detected`
- `false_breakout_detected`

Spring / UTAD 判断必须考虑：

- 是否刺穿边界
- 是否快速收回
- 相对量能状态
- 是否存在二次测试需要

---

## 8. Step 3.5: 反事实压力测试

每次给出方向前必须先生成反证。

至少评估以下反证：

- 这是 UTAD 不是突破
- 这是派发不是吸筹
- 这是无序震荡不是 Phase C
- 买入后次日可能进入流动性真空

规则：

- 若反证总强度 >= 正证总强度
- 则推翻原多头结论
- 输出 `watch_only`、`no_trade_zone` 或 `abandon`

---

## 9. Step 4: T+1 与盈亏比

### 9.1 T+1 风险

必须评估：

- 若当日收盘买入
- 次日无法卖出前可能承受的最不利结构性回撤

输出必须是结构性风险结论，不要求虚构精确未来波动。

### 9.2 Spring 冷冻期

若发现 Spring：

- `freeze_until = detect_date + 3 trading days`
- 冷冻期内只允许观察

### 9.3 盈亏比门槛

第一目标位只能取最近未测试强阻力。

若 `R:R < 1:2.5`：

- `decision = abandon`
- `abandon_reason = unfavorable_rr`

---

## 10. Step 5: 交易计划

固定输出字段：

- `current_assessment`
- `execution_preconditions`
- `direction`
- `entry_trigger`
- `invalidation`
- `target_1`
- `confidence`

### 10.1 方向约束

只允许：

- `long_setup`
- `watch_only`
- `no_trade_zone`
- `abandon`

### 10.2 A股强约束

若阶段为 `distribution` 或 `markdown`：

- 只能输出 `watch_only` 或 `abandon`
- 禁止任何做空或反向交易建议

---

## 11. 置信度分级

### A级

- BC 明确
- 边界清晰
- Phase C 明确
- 反证弱
- R:R >= 1:3

### B级

- BC 明确
- 结构较清晰
- 有少量不确定点
- R:R >= 1:2.5

### C级

- 结构勉强成立
- 证据冲突较多
- 仅允许观察

### D级

- BC 不成立
- 数据差
- 结构混乱
- 反证更强

不确定时永远降一级。

---

## 12. 强制保守降级清单

出现以下任一情况，必须降级：

- 找不到 BC
- 图表无序震荡
- 阶段不清
- 反证更强
- R:R 不足
- Spring 未满 T+3
- 派发 / Markdown

---

## 13. 禁止行为

规则引擎严禁：

- 编造成交量绝对数值
- 编造未识别出的结构点
- 忽略 T+1 约束
- 在 Distribution / Markdown 给多头计划
- 在 BC 未定位前做方向推演
