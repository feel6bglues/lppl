# 威科夫多模态输出 Schema 规范

**文档日期**: 2026-04-07  
**适用对象**: 后端工程师 / 报告工程师 / LLM 工程师 / 测试工程师  
**文档目标**: 锁定 JSON / CSV / 报告字段与 LLM 契约

---

## 1. `AnalysisResult` 必须字段

```text
symbol
asset_type
analysis_date
input_sources
timeframes_seen
bc_found
phase
micro_action
boundary_upper_zone
boundary_lower_zone
volume_profile_label
spring_detected
utad_detected
counterfactual_summary
t1_risk_assessment
rr_assessment
decision
trigger
invalidation
target_1
confidence
abandon_reason
conflicts
```

---

## 2. `ImageEvidenceBundle` 必须字段

```text
files
detected_timeframe
image_quality
visual_trend
visual_phase_hint
visual_boundaries
visual_anomalies
visual_volume_labels
trust_level
```

---

## 3. `AnalysisState` 必须字段

```text
symbol
asset_type
analysis_date
last_phase
last_micro_action
last_confidence
bc_found
spring_detected
freeze_until
watch_status
trigger_armed
trigger_text
invalid_level
target_1
weekly_context
intraday_context
conflict_summary
last_decision
abandon_reason
```

---

## 4. CSV Summary 字段

至少包含：

- `symbol`
- `asset_type`
- `analysis_date`
- `phase`
- `micro_action`
- `decision`
- `confidence`
- `bc_found`
- `spring_detected`
- `rr_assessment`
- `t1_risk_assessment`
- `trigger`
- `invalidation`
- `target_1`
- `abandon_reason`

---

## 5. Markdown / HTML 报告字段映射

### Step 0

来源字段：

- `bc_found`
- `phase`
- `confidence`
- `abandon_reason`

### Step 1

来源字段：

- `timeframes_seen`
- `phase`
- `boundary_upper_zone`
- `boundary_lower_zone`

### Step 2

来源字段：

- `volume_profile_label`
- `micro_action`
- `conflicts`

### Step 3

来源字段：

- `spring_detected`
- `utad_detected`
- `t1_risk_assessment`

### Step 3.5

来源字段：

- `counterfactual_summary`
- `conflicts`

### Step 4

来源字段：

- `rr_assessment`
- `invalidation`
- `target_1`

### Step 5

来源字段：

- `micro_action`
- `decision`
- `trigger`
- `invalidation`
- `target_1`
- `confidence`

### 附录 A

来源字段：

- `AnalysisState`

### 附录 B

来源字段：

- `ImageEvidenceBundle`
- `conflicts`

---

## 6. LLM 输入契约

LLM 输入只允许包含：

- `AnalysisResult`
- `ImageEvidenceBundle` 摘要
- `AnalysisState` 摘要
- 报告模板结构
- 禁止改写字段列表

LLM 不得直接读取：

- 原始图片二进制
- 原始完整 OHLCV 全量序列

---

## 7. LLM 禁止改写字段

以下字段一律由规则或融合层决定，LLM 不得改写：

- `phase`
- `micro_action`
- `decision`
- `confidence`
- `boundary_upper_zone`
- `boundary_lower_zone`
- `spring_detected`
- `utad_detected`
- `trigger`
- `invalidation`
- `target_1`
- `abandon_reason`

---

## 8. LLM 输出要求

LLM 输出必须：

- 严格按 Step 0 ~ Step 5 模板写中文
- 不得编造成交量数字
- 不得给出做空建议
- 不得忽略 T+1 冷冻期
- 不得忽略 R:R 门槛

---

## 9. Deterministic Fallback

若出现以下任一情况，必须回退模板报告：

- 无 LLM 配置
- LLM 请求失败
- LLM 输出缺字段
- LLM 输出与结构字段冲突

模板报告应保证：

- 字段完整
- 结构固定
- 可直接交付使用

---

## 10. JSON 输出最小示例

```json
{
  "symbol": "600519.SH",
  "asset_type": "stock",
  "analysis_date": "2026-04-07",
  "input_sources": ["data", "images"],
  "timeframes_seen": ["daily", "weekly", "60m"],
  "bc_found": true,
  "phase": "accumulation",
  "micro_action": "spring_candidate",
  "boundary_upper_zone": "recent_supply_zone",
  "boundary_lower_zone": "spring_low_zone",
  "volume_profile_label": "contracted",
  "spring_detected": true,
  "utad_detected": false,
  "counterfactual_summary": "weekly overhead supply remains a risk",
  "t1_risk_assessment": "medium",
  "rr_assessment": "pass",
  "decision": "watch_only",
  "trigger": "wait_for_breakout_and_low_volume_retest",
  "invalidation": "below_spring_low",
  "target_1": "nearest_untested_supply_zone",
  "confidence": "B",
  "abandon_reason": "",
  "conflicts": ["weekly_supply_overhang"]
}
```
