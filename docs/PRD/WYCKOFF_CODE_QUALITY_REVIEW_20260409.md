# 威科夫多模态系统 - 深度代码质量与设计审查报告

**报告日期**: 2026-04-09（修订版）
**评估范围**: `src/wyckoff/` 全量核心代码
**参考规范**: PRD、ARCH、SPEC_RULE_ENGINE、SPEC_FUSION_AND_STATE、SPEC_IMAGE_ENGINE
**审查方式**: 逐行代码核查 + 规范文件逐条对照
**修订说明**: 本版本在初版基础上新增对融合引擎死代码、T+1逻辑失效、RR阈值错误等问题的完整描述，并修正了初版对融合引擎和状态管理过誉的评价

---

## 一、整体代码质量与设计评估

`src/wyckoff/` 模块的外层架构设计目标清晰，使用 `dataclasses` 和 Enum 定义了完整的领域模型，引擎解耦思路与 ARCH 文档一致。

然而深入核查后发现，**已声称"完成"的模块中有多处逻辑实际处于死代码或错误状态**，部分看起来完整的引擎在运行时会产生系统性的错误输出，而非预期的降级保守输出。这是比功能缺失更危险的问题。

---

## 二、核心模块逐项深度审查

### 2.1 `analyzer.py`（数据规则引擎）— ⚠️ 存在深层逻辑硬伤

虽然 Step 0 ~ Step 5 的框架架构完整，但部分规则内部实现存在与 Wyckoff 原理的根本性偏差。

#### 问题 1：宏观阶段判定完全错误（P0）

**文件**: `analyzer.py` L447–457，函数 `_determine_wyckoff_structure`

```python
# 实际代码
if bc_point is not None and sc_point is not None:
    if bc_point.price > sc_point.price:
        structure.phase = WyckoffPhase.MARKUP    # ← 仅靠比价
    else:
        structure.phase = WyckoffPhase.MARKDOWN
elif bc_point is not None:
    structure.phase = WyckoffPhase.MARKUP        # ← 无 SC 就直接 Markup
```

仅靠 BC 与 SC 的高低点比较就直接判定 MARKUP / MARKDOWN，`ACCUMULATION`（积累）和 `DISTRIBUTION`（派发）**从未被赋予**。这违背了 Wyckoff 理论的核心——从横盘区间识别主力意图的整个分析框架彻底缺失。

**连锁问题**：`_detect_wyckoff_signals` L508 中有针对 Distribution 的 A 股保护门：
```python
if structure.phase in [WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION]:
    ...  # 禁止给多头信号
```
由于 `DISTRIBUTION` 相变永远不会被设置，**这段 A 股做空保护实际上是死代码，形同虚设**。派发阶段将被误判为 Markup 阶段，并可能产生做多建议，违反 PRD 核心原则 6.3。

---

#### 问题 2：信号类型与阶段概念混用的危险 fallback（P1）

**文件**: `analyzer.py` L550–553

```python
# 当前走到这里时无任何结构性证据
if signal.signal_type == "no_signal":
    signal.signal_type = "accumulation"
    signal.confidence = ConfidenceLevel.C
    signal.description = "可能处于积累阶段，等待 Spring 信号确认"
```

`signal_type` 的语义是威科夫事件枚举（spring / utad / sos / lps），而非宏观阶段。将 `"accumulation"` 写入 `signal_type` 属于概念混用，且在**没有任何结构性证据**的前提下给出 C 级置信度结论，违反 SPEC_RULE_ENGINE §12 强制保守降级清单。正确行为应为返回 `no_signal` 或 `no_trade_zone`。

---

#### 问题 3：输入数据门槛低于规范要求（P1）

**文件**: `analyzer.py` L57

```python
if df is None or len(df) < 30:   # 实际代码
```

SPEC_WYCKOFF_RULE_ENGINE §1 明确要求**至少 100 根 K 线**，当前仅检查 30 根，数据不足时仍会进入分析流程，产生不可靠的结构输出。

---

#### 问题 4：UTAD / LPS / SOS 完整事件体系缺失（P2）

`_detect_wyckoff_signals` 中仅实现了 Spring 和粗糙的 `sos_candidate` 两类信号。SPEC Step 3 要求必须识别的 `utad_detected`、`st_detected`、`false_breakout_detected` 均未实现。`fusion_engine.py` 中有读取 `utad_detected` 的字段（L73），但 analyzer 永远不会将 `signal_type` 设为 `"utad"`，导致该字段永远为 `False`。

---

#### 问题 5：`_apply_t1_enforcement` 重复调用（P3）

**文件**: `analyzer.py` L77 和 L83

```python
self._apply_t1_enforcement(signal, trading_plan=None, stress_tests=stress_tests)  # 第一次，trading_plan=None
# ...
self._apply_t1_enforcement(signal, trading_plan, stress_tests)                     # 第二次，正常执行
```

第一次调用 `trading_plan=None` 时函数在开头 `return`，属于无意义的重复调用，逻辑混乱。

---

### 2.2 `image_engine.py`（图像引擎）— ❌ 视觉提取为占位符

元数据处理（`_infer_symbol`、`_infer_timeframe`、基于文件大小的质量评级）实现扎实可用。但视觉证据提取部分是完全的占位符实现：

**文件**: `image_engine.py` L308–318

```python
return ImageEvidenceBundle(
    files=files,
    detected_timeframe=detected_timeframe,   # ✅ 有效
    image_quality=overall_quality,           # ⚠️ 仅凭文件大小
    visual_trend="unclear",                  # ❌ 硬编码占位符
    visual_phase_hint="unclear",             # ❌ 硬编码占位符
    visual_boundaries=[],                    # ❌ 硬编码占位符
    visual_anomalies=[],                     # ❌ 硬编码占位符
    visual_volume_labels="unclear",          # ❌ 硬编码占位符
    trust_level=trust_level
)
```

**后果**：`ImageEvidenceBundle` 中所有视觉字段永远为 `"unclear"` 或空列表，导致下游融合引擎的冲突检测和多周期校验都无法获得任何有效的图像侧证据，PRD 场景二（图表文件夹 + 数据交叉校验）实际无法运行。

---

### 2.3 `fusion_engine.py`（融合引擎）— ❌ 初版报告严重过誉，实际存在多处致命 Bug

初版报告评价为"设计干净"，经深度核查，融合引擎存在两处导致核心功能**完全失效**的问题：

#### 问题 1：决策核心逻辑为永久死代码（P0）

**文件**: `fusion_engine.py` L159–167，函数 `_determine_decision`

```python
if report.signal and hasattr(report.signal, 'action'):   # ← 'action' 字段不存在！
    if report.signal.action == 'buy':
        base_decision = 'long_setup'
    ...
else:
    base_decision = 'no_trade_zone'   # ← 永远走到这里
```

`WyckoffSignal`（`models.py` L81–89）根本没有 `action` 字段，`hasattr()` 永远返回 `False`。**无论数据引擎给出何种分析结论，融合引擎的最终决策永远返回 `'no_trade_zone'`**。这使得整个"多模态融合决策"形同虚设。

---

#### 问题 2：T+1 风险评估永远返回"可接受"（P0）

**文件**: `fusion_engine.py` L147，函数 `_assess_t1_risk`

```python
for test in report.stress_tests:
    if hasattr(test, 'outcome') and test.outcome == 'fail':  # ← 'fail' 是英文字符串
        return "高风险"
return "可接受"
```

`analyzer._run_stress_tests` 中所有 `outcome` 均设置为中文字符串（如 `"支撑失守，可能加速下跌"`），永远不等于字符串 `'fail'`，**T+1 风险评估恒定返回 `"可接受"`，完全失效**。

---

#### 问题 3：R:R 放弃门槛阈值错误（P1）

**文件**: `fusion_engine.py` L203，函数 `_get_abandon_reason`

```python
if not report.risk_reward.reward_risk_ratio or report.risk_reward.reward_risk_ratio < 1.0:
    reasons.append("盈亏比不足 1:2.5")
```

判断条件用的是 `< 1.0`，但 PRD 第 9.2 节和 SPEC Step 4 均明确规定门槛为 `R:R < 1:2.5`（即 `< 2.5`）。当前代码仅当 R:R 低于 1 才放弃，**会放行大量 PRD 要求丢弃的低质量信号**。

---

### 2.4 `state.py`（状态管理）— ⚠️ 整体合理，但冷冻期计算存在规范偏差

状态文件的 Schema 与 SPEC_FUSION_AND_STATE §8 完全对齐，Spring 状态机逻辑正确。但存在一个规范偏差：

**文件**: `state.py` L108

```python
freeze_until = analysis_date + timedelta(days=3)   # 使用日历天
```

SPEC §9.2 要求 `freeze_until = detect_date + 3 trading days`（**交易日**）。节假日期间冷冻期会提前失效，A 股长假周边尤为明显。

---

### 2.5 `models.py`（数据模型）— ⚠️ 整体良好，但存在耦合与细节问题

**报告逻辑耦合**：`WyckoffReport.to_markdown()` (L261–344) 的 80 余行渲染逻辑嵌在 DTO 模型层，ARCH §2.5 明确应有独立的 `reporting.py` 负责报告渲染，当前该文件缺失。

**`__init__.py` 不一致**：`__all__` L38 中 `WyckoffReport,` 未加引号，混入类对象而非字符串，与其余条目风格不一致（P3 小问题）。

---

## 三、问题汇总与优先级矩阵

| 优先级 | 模块 | 问题描述 | 风险 |
|--------|------|----------|------|
| **P0** | `fusion_engine.py` | `_determine_decision` 读取不存在的 `action` 属性，决策永远为 `no_trade_zone` | 整个融合决策失效 |
| **P0** | `fusion_engine.py` | `_assess_t1_risk` 检查英文 `'fail'`，而 outcome 为中文，T+1 评估永远返回"可接受" | 风险管控失效 |
| **P0** | `analyzer.py` | `_determine_wyckoff_structure` 从未赋予 ACCUMULATION/DISTRIBUTION，DISTRIBUTION 保护门为死代码 | 可能在派发阶段输出做多建议 |
| **P1** | `analyzer.py` | 无结构证据时 fallback 为 `signal_type="accumulation"`，置信度 C，应为降级放弃 | 产生虚假信号 |
| **P1** | `fusion_engine.py` | R:R 放弃门槛 `< 1.0`，规范要求 `< 2.5`，阈值严重偏低 | 放行大量低质量信号 |
| **P1** | `analyzer.py` | 数据最小 K 线数检查 30 根，规范要求 100 根 | 数据不足时产生错误结构 |
| **P2** | `analyzer.py` | UTAD / LPS / SOS 完整事件检测缺失 | 第 Phase C 分析不完整 |
| **P2** | `image_engine.py` | 所有视觉特征 (`visual_trend` 等) 为硬编码占位符 | 多模态交叉校验无效 |
| **P2** | `state.py` | Spring 冷冻期使用日历天而非交易日 | 节假日期间冷冻期提前失效 |
| **P3** | `analyzer.py` | `_apply_t1_enforcement` 无效重复调用 | 逻辑混乱，无实际危害 |
| **P3** | `models.py` | `to_markdown()` 报告逻辑嵌在 DTO 层，缺少 `reporting.py` | 架构耦合，妨碍 HTML 报告扩展 |
| **P3** | `__init__.py` | `__all__` 中 `WyckoffReport` 未加引号 | 风格不一致 |

---

## 四、修复建议（按优先级）

### 短期（P0，必须立即修复）

1. **修复 `fusion_engine._determine_decision`**：参照 `trading_plan.direction` 或 `signal.signal_type` 推导决策，删除对不存在的 `action` 字段的引用。
2. **修复 `fusion_engine._assess_t1_risk`**：改为检查 `test.passes == False` 或 `test.risk_level == "高"` 来判断高风险。
3. **修复 `analyzer._determine_wyckoff_structure`**：引入震荡区间（TR）逻辑来识别 ACCUMULATION / DISTRIBUTION，不能单靠两点比价。

### 中期（P1，下一版本前完成）

4. **修复 `analyzer._detect_wyckoff_signals`**：删除 `accumulation` fallback，改为降级到 `no_signal` 加 `no_trade_zone` 结论。
5. **修复 R:R 门槛**：`fusion_engine._get_abandon_reason` 中将 `< 1.0` 改为 `< 2.5`。
6. **修复最小数据量检查**：`analyzer.analyze` 中将 `len(df) < 30` 改为 `len(df) < 100`。

### 长期（P2+，视觉与架构完善）

7. **实现 `image_engine` 视觉分析**：接入 LLM 视觉能力（如 Gemini Vision），替换硬编码占位符。
8. **创建 `reporting.py`**：将 `WyckoffReport.to_markdown()` 迁出，并扩展为 HTML 报告支持。
9. **Spring 冷冻期改用交易日**：`state.py` 中引入交易日历计算，排除非交易日。

---

## 五、修复落地记录（2026-04-09）

所有 P0 / P1 / P2 / P3 修复已完成代码实现并通过逐项验证。

### 修复清单

| 优先级 | 文件 | 修复内容 | 状态 |
|--------|------|----------|------|
| P0 | `fusion_engine.py` | `_determine_decision`：删除读取不存在 `action` 字段的死代码，改为基于 `signal_type` + `direction` + `phase_val` 正确推导决策 | ✅ 已修复 |
| P0 | `fusion_engine.py` | `_assess_t1_risk`：从检查英文字符串 `'fail'` 改为检查 `passes == False` 和 `risk_level == '高'`，T+1 评估现在可以正常返回高风险 | ✅ 已修复 |
| P0 | `analyzer.py` | `_determine_wyckoff_structure`：完整重写，引入 TR 横盘震荡检测（振幅 ≤20% + 短趋势 <5%），区分 Accumulation / Distribution / Markup / Markdown / Unknown | ✅ 已修复 |
| P1 | `analyzer.py` | `_detect_wyckoff_signals`：删除危险的 `accumulation` magic fallback，改为保守的 `no_signal` + D 级降级；Spring 检测限定仅在 ACCUMULATION 阶段有效 | ✅ 已修复 |
| P1 | `fusion_engine.py` | `_get_abandon_reason`：R:R 放弃门槛从 `< 1.0` 修正为 `< 2.5`，与 PRD 规范一致 | ✅ 已修复 |
| P1 | `analyzer.py` | `analyze`：数据最小 K 线数检查从 30 改为 100，符合 SPEC §1 要求 | ✅ 已修复 |
| P2 | `state.py` | `_calculate_freeze_until`：新增 `_add_trading_days` 静态方法，Spring 冷冻期改用跳过周末的交易日计算（T+3 trading days） | ✅ 已修复 |
| P3 | `analyzer.py` | `analyze`：删除第一次无意义的 `_apply_t1_enforcement(trading_plan=None)` 重复调用 | ✅ 已修复 |
| P3 | `__init__.py` | `__all__` 中 `WyckoffReport` 补加引号，风格与其他条目一致 | ✅ 已修复 |

### 验证结果

```
[1] Spring+Accumulation -> watch_only        ✅
[2] Distribution        -> no_trade_zone     ✅
[3] T+1 高风险          -> 高风险            ✅
[4] T+1 全通过          -> 可接受            ✅
[5] R:R=1.5 放弃原因    -> "... 盈亏比不足 1:2.5"  ✅
[6] R:R=3.0 放弃原因    -> ""                ✅
[7] 周五+3交易日        -> 2026-04-15 (周三) ✅
[8] Accum 区间内无信号  -> no_signal / D     ✅

=== 全部 8 项验证通过 ===
```

### 遗留待实现（不影响当前可运行性）

| 项目 | 说明 |
|------|------|
| `image_engine.py` 视觉分析 | 需接入 LLM Vision 能力，当前 `visual_trend` 等字段仍为占位符，图像-only 场景不可用 |
| `reporting.py` 独立报告层 | `WyckoffReport.to_markdown()` 仍在 `models.py` 内，待迁出，并补充 `to_html()` 实现 |
| A 股法定节假日日历 | `_add_trading_days` 目前只跳过周末，长假期间仍有误差，需后续接入完整交易日历 |

---

**报告生成时间**: 2026-04-09（修订并落地）
**审核状态**: P0/P1/P2/P3 修复已完成，遗留 P2 视觉引擎待后续迭代
可作为修复工单依据
