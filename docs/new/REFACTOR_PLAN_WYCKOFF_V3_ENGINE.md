# Wyckoff 引擎合并重构计划（v2）

> **目标**：彻底删除 `analyzer.py` 和 `data_engine.py`，以全新 `engine.py` 替代，100% 实现 Promote_v3.0.md 的 10 条规则 + 九步工作流。
>
> **原则**：不保留兼容层，不保留旧模块。新模块是唯一入口。

---

## 一、重构背景

### 现状

| 文件 | 来源 | 角色 |
|------|------|------|
| `src/wyckoff/analyzer.py` (767+行) | 远程主线 | 当前生产版本 |
| `src/wyckoff/data_engine.py` (951行) | 本地新开发 | v3.0 规则引擎原型 |

两套链路各有硬伤（详见 `REFACTOR_PLAN_WYCKOFF_V3_ENGINE.md` v1 版本），需合并为单一模块。

### 删除决策

- **analyzer.py**：阶段判定正确，但缺少努力与结果、反事实、Spring 量能验证等 v3.0 核心功能
- **data_engine.py**：阶段判定根本性错误（把"价格小幅波动"等同于 Accumulation）
- 两套都需大幅改造，改造成本 > 新建成本
- 决定：**两者均删除，全新构建 `engine.py`**

---

## 二、删除范围

### 2.1 删除的文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `src/wyckoff/analyzer.py` | 767+ | 删除 |
| `src/wyckoff/data_engine.py` | 951 | 删除 |
| `tests/unit/test_wyckoff_analyzer.py` | 1003 | 删除（测试目标已不存在） |
| `tests/unit/test_wyckoff_data_engine.py` | ~170 | 删除（测试目标已不存在） |

### 2.2 受影响需更新的文件

| 文件 | 当前引用 | 需改为引用 |
|------|---------|-----------|
| `src/wyckoff/__init__.py` | `from src.wyckoff.analyzer import WyckoffAnalyzer` | `from src.wyckoff.engine import WyckoffEngine` |
| `src/wyckoff/__init__.py` | `from src.wyckoff.data_engine import DataEngine` | 删除此行 |
| `src/cli/wyckoff_analysis.py` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `src/cli/wyckoff_multimodal_analysis.py` | `from src.wyckoff.data_engine import DataEngine` | `from src.wyckoff import WyckoffEngine` |
| `src/wyckoff/__init__.py` 的 `__all__` | 包含 `WyckoffAnalyzer`, `DataEngine` | 替换为 `WyckoffEngine` |
| `scripts/batch_wyckoff_analysis.py` | `from src.wyckoff.analyzer import WyckoffAnalyzer` | `from src.wyckoff.engine import WyckoffEngine` |
| `scripts/run_wyckoff_latest_stock_batch.py` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `scripts/replay_wyckoff_samples.py` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `scripts/generate_wyckoff_daily_replay.py` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `tests/integration/test_wyckoff_sample_replay.py` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `tests/integration/test_wyckoff_integration.py` | `from src.wyckoff.data_engine import DataEngine` | `from src.wyckoff import WyckoffEngine` |
| `tests/unit/test_wyckoff_exports.py` | 检查 `DataEngine` 存在 | 检查 `WyckoffEngine` 存在 |

### 2.3 不受影响的文件（保持不变）

| 文件 | 说明 |
|------|------|
| `src/wyckoff/models.py` | 仅新增 v3.0 数据结构，不删除旧结构 |
| `src/wyckoff/fusion_engine.py` | 保持 `fuse()` 接口不变，接受 `WyckoffReport` |
| `src/wyckoff/config.py` | 保持不变 |
| `src/wyckoff/reporting.py` | 保持不变 |
| `src/wyckoff/state.py` | 保持不变 |
| `src/wyckoff/image_engine.py` | 保持不变 |

---

## 三、新建文件

### 3.1 `src/wyckoff/engine.py`（~900行）

统一的 v3.0 威科夫分析引擎，取代 analyzer.py + data_engine.py。

```python
class WyckoffEngine:
    """v3.0 威科夫分析引擎 - 唯一入口"""

    def __init__(self, config: Optional[WyckoffConfig] = None):
        self.config = config or WyckoffConfig()

    def analyze(self, df, symbol, period="日线", multi_timeframe=False,
                image_evidence=None) -> WyckoffReport:
        """主入口 - 严格按 v3.0 九步执行"""
```

### 3.2 `src/wyckoff/rules.py`（~300行）

v3.0 规则执行器，10 条规则的独立验证层。

```python
class V3Rules:
    """v3.0 规则执行器 - 10 条规则的独立验证"""
```

### 3.3 `tests/unit/test_wyckoff_engine.py`（~400行）

新引擎的单元测试，替代 test_wyckoff_analyzer.py + test_wyckoff_data_engine.py。

### 3.4 `tests/unit/test_wyckoff_rules.py`（~200行）

规则层的单元测试，10 条规则逐一验证。

---

## 四、数据模型变更（models.py 新增）

```python
@dataclass
class Rule0Result:
    """Step 0: BC/TR 定位扫描输出"""
    bc_found: bool
    bc_position: Optional[BCPoint]
    bc_in_chart: bool               # BC 是否在图表范围内
    tr_upper: Optional[float]
    tr_lower: Optional[float]
    tr_source: str                  # "bc_ar" | "sc_spring" | "rolling_range" | "none"
    validity: str                   # "full" | "partial" | "tr_fallback" | "insufficient"
    confidence_base: str            # 起评等级: A/B/C/D


@dataclass
class Step1Result:
    """Step 1: 大局观与宏观定调"""
    phase: WyckoffPhase
    sub_phase: str                  # Phase A/B/C/D/E 细分
    unknown_candidate: str
    prior_trend_pct: float
    is_in_tr: bool
    short_trend_pct: float
    relative_position: float
    ma5: float
    ma20: float
    boundary_upper: float
    boundary_lower: float
    boundary_source: List[str]


@dataclass
class Step2Result:
    """Step 2: 努力与结果"""
    phenomena: List[str]
    accumulation_evidence: float
    distribution_evidence: float
    net_bias: str                   # "accumulation" | "distribution" | "neutral"


@dataclass
class Step3Result:
    """Step 3: Spring/UTAD + T+1 风险"""
    spring_detected: bool
    spring_quality: str             # "一级(缩量)" | "二级(放量需ST)" | "无"
    spring_date: Optional[str]
    spring_low_price: Optional[float]
    utad_detected: bool
    utad_quality: str
    utad_date: Optional[str]
    st_detected: bool
    lps_confirmed: bool             # v3.0 规则6
    spring_volume: str
    t1_max_drawdown_pct: float
    t1_verdict: str                 # "安全" | "偏薄" | "超限"
    t1_description: str


@dataclass
class CounterfactualResult:
    """Step 3.5: 反事实压力测试"""
    utad_not_breakout: str
    distribution_not_accumulation: str
    chaos_not_phase_c: str
    liquidity_vacuum_risk: str
    total_pro_score: float
    total_con_score: float
    conclusion_overturned: bool
    counterfactual_scenario: str    # v3.0 要求的文本描述
    forward_evidence: List[str]
    backward_evidence: List[str]


@dataclass
class StopLossResult:
    """规则10: 精确止损"""
    entry_price: float
    stop_loss_price: float          # = 关键低点 * 0.995
    stop_pct: float
    precision_warning: bool         # 止损区间 < 1.5%
    liquidity_risk_warning: str
    stop_logic: str


@dataclass
class RiskRewardResult:
    """Step 4: 盈亏比投影"""
    entry_price: float
    stop_loss: float
    first_target: float
    first_target_source: str        # "tr_upper" | "bearish_candle" | "gap_lower"
    rr_ratio: float
    rr_verdict: str                 # "excellent" | "pass" | "marginal" | "fail"
    gain_pct: float


@dataclass
class ConfidenceResult:
    """规则8: 置信度矩阵"""
    level: str                      # "A" | "B" | "C" | "D"
    bc_located: bool                # 条件①
    spring_lps_verified: bool       # 条件②
    counterfactual_passed: bool     # 条件③
    rr_qualified: bool              # 条件④
    multiframe_aligned: bool        # 条件⑤
    position_size: str
    reason: str


@dataclass
class V3TradingPlan:
    """Step 5: 机构级实战交易计划"""
    current_assessment: str
    multi_timeframe_statement: str
    execution_preconditions: List[str]
    direction: str
    entry_trigger: str
    observation_window: str
    stop_loss: StopLossResult
    target: RiskRewardResult
    confidence: ConfidenceResult
```

---

## 五、engine.py 核心设计

### 5.1 类结构

```python
class WyckoffEngine:
    """v3.0 威科夫分析引擎 - 唯一入口"""

    def __init__(self, config: Optional[WyckoffConfig] = None):
        self.config = config or WyckoffConfig()
        self.rules = V3Rules()

    def analyze(self, df, symbol, period="日线", multi_timeframe=False,
                image_evidence=None) -> WyckoffReport:
        """主入口"""
        if multi_timeframe and period == "日线":
            return self._analyze_multiframe(df, symbol, image_evidence)
        return self._analyze_single(df, symbol, period, image_evidence)

    def _analyze_single(self, df, symbol, period, image_evidence) -> WyckoffReport:
        """单周期 - Step 0→5"""

    def _step0_bc_tr_scan(self, df) -> Rule0Result:
        """Step 0: BC/TR 定位扫描"""

    def _step1_phase_determine(self, df, rule0) -> Step1Result:
        """Step 1: 大局观与阶段判定"""

    def _step2_effort_result(self, df, step1) -> Step2Result:
        """Step 2: 努力与结果"""

    def _step3_phase_c_t1(self, df, step1, rule0) -> Step3Result:
        """Step 3: Spring/UTAD + T+1"""

    def _step35_counterfactual(self, df, step1, step2, step3, rule0) -> CounterfactualResult:
        """Step 3.5: 反事实"""

    def _step4_risk_reward(self, df, step1, step3, rule0) -> RiskRewardResult:
        """Step 4: 盈亏比"""

    def _calc_confidence(self, rule0, step3, cf, rr, multiframe) -> ConfidenceResult:
        """规则8: 置信度"""

    def _step5_trading_plan(self, step1, step3, cf, rr, confidence) -> V3TradingPlan:
        """Step 5: 交易计划"""

    def _apply_a_stock_rules(self, step1, plan) -> V3TradingPlan:
        """A 股铁律最终检查"""

    def _analyze_multiframe(self, df, symbol, image_evidence) -> WyckoffReport:
        """多周期分析"""

    def _classify_volume(self, volume, volume_series) -> VolumeLevel:
        """相对量能分类"""

    def _scan_bc_sc(self, df) -> Tuple[BCPoint, SCPoint]:
        """BC/SC 评分系统"""

    def _resample_ohlcv(self, df, rule) -> pd.DataFrame:
        """OHLCV 重采样"""

    def _build_report(self, ...) -> WyckoffReport:
        """构建最终报告"""
```

### 5.2 逐步实现逻辑

#### Step 0: BC/TR 定位扫描

```
1. analyzer.py 的 BC 评分系统（量能+上影线+回调确认）→ _scan_bc_sc()
2. analyzer.py 的 SC 评分系统
3. analyzer.py 的量能分类 → _classify_volume()
4. NEW: BC 不可见时，用近60日滚动区间识别 TR 边界
5. 返回 Rule0Result.validity:
   - "full": BC+TR 都可见 → 起评 A
   - "partial": BC 或 TR 之一可见 → 起评 B
   - "tr_fallback": BC 不可见但 TR 明确 → 起评 C
   - "insufficient": BC 和 TR 都不可见 → D 级，终止
```

#### Step 1: 阶段判定

```
来源：analyzer.py 的 _determine_wyckoff_structure（核心保留）

1. 近60日振幅判断是否在 TR 内
2. TR 内：看 TR 前趋势方向
   - >10% 下跌 → ACCUMULATION
   - >10% 上涨 → DISTRIBUTION
   - 不明显 → 回退到 BC/SC 位置 + 均线判定
3. TR 外：按短期趋势判定 MARKUP/MARKDOWN
4. UNKNOWN 子状态分类（phase_a/sc_st/upthrust/phase_b）
5. 边界锚定：优先用 BC/AR/SC 价格，否则 rolling 30日极值
6. NEW: 补充 Phase A/B/C/D/E 细分
```

#### Step 2: 努力与结果

```
来源：data_engine.py 的 _step2_effort_result（直接取用，逻辑无问题）

1. 放量滞涨 → 派发倾向 +0.3
2. 缩量上推 → 吸筹倾向 +0.2
3. 下边界供给枯竭 → 吸筹 +0.3
4. 高位炸板遗迹 → 派发 +0.3
5. 返回 net_bias
```

#### Step 3: Spring/UTAD + T+1

```
Spring 检测（改造 data_engine.py）：
1. 刺穿下边界：df['low'].iloc[i] < boundary_lower
2. 快速收回：后续 K 线 close 回到 boundary_lower 以上
3. NEW: 量能质量评估（v3.0 规则6）
   - 缩量 Spring → "一级"（供给枯竭）
   - 放量 Spring → "二级"（需 ST 验证）
4. NEW: LPS 验证
   - 后续地量 K 线出现（< 天量柱的 30%）
   - 价格未破 Spring 极低点
   - 出现反弹收阳
   - 三条同时满足 → lps_confirmed = True
5. NEW: Spring 后放量创新低 → 信号作废，重新 Step 0

UTAD 检测（同理改造）

T+1 压力测试（全新）：
1. 入场价 = 当前 close
2. 流动性真空区 = 最近30日最低价区域
3. 极限回撤 = (入场价 - 流动性真空区低点) / 入场价
4. 判定：< 3% 安全 | 3-5% 偏薄 | > 5% 超限
```

#### Step 3.5: 反事实

```
来源：data_engine.py 的 _step35_counterfactual（扩展）

1. 4 组反证评分（取自 data_engine.py）
2. NEW: counterfactual_scenario 文本生成
3. NEW: forward_evidence / backward_evidence 列表
4. 结论被推翻 → 强制 D 级，停止分析
```

#### Step 4: 盈亏比

```
全新实现（规则10精度）：

1. 止损价 = 关键结构低点 × 0.995
   - 关键结构低点 = Spring 极低点 / SC 低点 / TR 下边界
2. 止损区间 < 1.5% → precision_warning = True
3. 止损位附近有涨跌停 → 流动性风险警告
4. 目标位必须来自结构化来源（TR上沿/大阴线起跌点/缺口下沿）
5. RR = (目标 - 入场) / (入场 - 止损)
6. RR < 1:2.5 → fail
```

#### Step 5: 交易计划

```
全新实现（v3.0 完整格式）：

输出字段（不可省略）：
- 当前定性
- 多周期一致性声明
- 执行前提
- 操作方向
- 精确入场 Trigger（附观察期限）
- 铁律止损点 Invalidation（含价格、幅度、流动性警告、逻辑描述）
- 第一目标位 Take Profit（含价格、来源、收益率、盈亏比）
- 置信度等级（含等级、仓位比例、量化矩阵5项核对）
```

#### 置信度计算（规则8）

```
A 级 = 5 项全部满足：
  ① BC已定位
  ② Spring/LPS结构完整且已验证
  ③ 反事实无法推翻
  ④ 盈亏比 ≥ 1:2.5
  ⑤ 多周期方向一致

B 级 = 4 项满足
C 级 = 3 项满足
D 级 = 任何一项触发：BC缺失+TR不明 / Markdown / 信号矛盾 / 反事实占优
```

---

## 六、rules.py 设计

```python
class V3Rules:
    """v3.0 规则执行器 - 10 条规则的独立验证层"""

    @staticmethod
    def rule1_relative_volume(volume, volume_series) -> str:
        """规则1: 相对量能"""

    @staticmethod
    def rule2_no_long_in_markdown(phase, signal) -> bool:
        """规则2: Markdown 禁止做多"""

    @staticmethod
    def rule3_t1_risk_test(entry_price, support_low) -> dict:
        """规则3: T+1 极限回撤"""

    @staticmethod
    def rule4_no_trade_zone(contradictions_count, struct_clarity) -> bool:
        """规则4: 诚实不作为"""

    @staticmethod
    def rule5_bc_tr_fallback(bc_found, tr_defined) -> dict:
        """规则5: BC/TR 降级"""

    @staticmethod
    def rule6_spring_validation(spring_detected, post_spring_df, spring_low) -> dict:
        """规则6: Spring 结构事件验证"""

    @staticmethod
    def rule7_counterfactual(pro_score, con_score) -> str:
        """规则7: 反事实仲裁"""

    @staticmethod
    def rule8_confidence_matrix(bc_located, spring_lps, cf_passed, rr_ok, mtf_ok) -> str:
        """规则8: 置信度矩阵"""

    @staticmethod
    def rule9_multiframe_alignment(daily_phase, weekly_phase, monthly_phase) -> str:
        """规则9: 多周期一致性"""

    @staticmethod
    def rule10_stop_loss(key_low) -> dict:
        """规则10: 止损精度"""
```

---

## 七、多周期融合

来源：analyzer.py 的 `_merge_multitimeframe_reports`（保持不变）

```
1. 日线按 W-FRI 重采样为周线
2. 日线按 ME 重采样为月线
3. 对三个周期分别执行 _analyze_single
4. 融合规则：
   - 月线/周线 Markdown → 覆盖日线，强制空仓
   - 月线/周线 Distribution → 覆盖日线
   - 周线 Unknown + 日线 Markup → 降级为 C
   - 月线+周线同时 Markup → 支持日线
   - RR <= 0 → No Trade Zone
```

---

## 八、调用方迁移

### 8.1 CLI 迁移

**`src/cli/wyckoff_analysis.py`（旧 CLI）**：
```python
# 旧
from src.wyckoff import WyckoffAnalyzer
analyzer = WyckoffAnalyzer(lookback_days=args.lookback)
report = analyzer.analyze(df, symbol=symbol, period="日线",
                          image_evidence=image_evidence,
                          multi_timeframe=args.multi_timeframe)

# 新
from src.wyckoff import WyckoffEngine
engine = WyckoffEngine(config=config)
report = engine.analyze(df, symbol=symbol, period="日线",
                        multi_timeframe=args.multi_timeframe,
                        image_evidence=image_evidence)
```

**`src/cli/wyckoff_multimodal_analysis.py`（新多模态 CLI）**：
```python
# 旧
from src.wyckoff.data_engine import DataEngine
data_engine = DataEngine(config)
data_result = data_engine.run(df, symbol, asset_type)
analysis_result = fusion_engine.fuse(data_result, None)

# 新
from src.wyckoff import WyckoffEngine
engine = WyckoffEngine(config=config)
report = engine.analyze(df, symbol, period="日线",
                        image_evidence=image_bundle)
analysis_result = fusion_engine.fuse(report, image_bundle)
```

**注意**：`FusionEngine.fuse()` 的 `if hasattr(report, "phase_result")` 分支将不再被触发，因为新引擎返回 `WyckoffReport` 而非 `DailyRuleResult`。fusion_engine.py 中 `_fuse_daily_rule_result` 方法可删除。

### 8.2 Script 迁移

所有 scripts/ 下的文件：
```python
# 旧
from src.wyckoff.analyzer import WyckoffAnalyzer
# 或
from src.wyckoff import WyckoffAnalyzer

# 新
from src.wyckoff import WyckoffEngine
```

### 8.3 Test 迁移

| 旧文件 | 操作 | 新文件 |
|--------|------|--------|
| `test_wyckoff_analyzer.py` | 删除 | `test_wyckoff_engine.py` |
| `test_wyckoff_data_engine.py` | 删除 | `test_wyckoff_engine.py` |
| `test_wyckoff_sample_replay.py` | 更新 import | 保持 |
| `test_wyckoff_integration.py` | 更新 import | 保持 |
| `test_wyckoff_exports.py` | 更新检查项 | 保持 |

---

## 九、fusion_engine.py 清理

`FusionEngine.fuse()` 中的分支逻辑需要清理：

```python
# 删除此分支
if hasattr(report, "phase_result") and hasattr(report, "bc_result"):
    return self._fuse_daily_rule_result(report, image_evidence)

# 删除 _fuse_daily_rule_result 方法（约40行）

# 保留的主逻辑（处理 WyckoffReport）
result = AnalysisResult()
result.bc_found = report.structure.bc_point is not None
...
```

---

## 十、`__init__.py` 更新

```python
# 旧
from src.wyckoff.analyzer import WyckoffAnalyzer
from src.wyckoff.data_engine import DataEngine

# 新
from src.wyckoff.engine import WyckoffEngine

__all__ = [
    "WyckoffEngine",      # 替代 WyckoffAnalyzer + DataEngine
    # 保留的旧导出
    "WyckoffPhase",
    "ConfidenceLevel",
    "WyckoffSignal",
    "TradingPlan",
    "WyckoffReport",
    # ... 其余不变
]
```

---

## 十一、测试策略

### 11.1 新增测试

**`tests/unit/test_wyckoff_engine.py`**：
- `test_step0_bc_found` - BC 定位成功
- `test_step0_bc_missing_tr_fallback` - BC 不可见但 TR 明确（规则5）
- `test_step0_both_missing` - BC 和 TR 都不可见
- `test_step1_tr_accumulation` - TR 前下跌→ACCUMULATION
- `test_step1_tr_distribution` - TR 前上涨→DISTRIBUTION
- `test_step1_markup` - 非 TR 上涨→MARKUP
- `test_step1_markdown` - 非 TR 下跌→MARKDOWN
- `test_step1_unknown_substates` - UNKNOWN 子状态分类
- `test_step2_effort_accumulation` - 吸筹证据
- `test_step2_effort_distribution` - 派发证据
- `test_step3_spring_pierce_recover` - Spring 刺穿+收回
- `test_step3_spring_lps_confirm` - Spring LPS 验证（规则6）
- `test_step3_spring_volume_quality` - Spring 量能分级
- `test_step3_spring_invalidated` - Spring 后放量创新低作废
- `test_step35_counterfactual_overturn` - 反事实推翻（规则7）
- `test_step35_counterfactual_downgrade` - 反事实降档
- `test_step4_stop_loss_precision` - 止损精度 0.5%（规则10）
- `test_step4_stop_loss_precision_warning` - 止损区间 < 1.5% 警告
- `test_step4_rr_excellent` - RR >= 2.5
- `test_step4_rr_fail` - RR < 2.5
- `test_confidence_a_all_conditions` - A 级（5项全满足）
- `test_confidence_d_markdown` - D 级（Markdown）
- `test_confidence_d_counterfactual` - D 级（反事实占优）
- `test_a_stock_no_long_in_markdown` - 规则2 验证
- `test_multiframe_markdown_overrides_daily` - 多周期压制
- `test_multiframe_fully_aligned` - 三周期共振
- `test_full_analysis_uptrend` - 完整流程：上涨
- `test_full_analysis_downtrend` - 完整流程：下跌
- `test_full_analysis_insufficient_data` - 完整流程：数据不足

**`tests/unit/test_wyckoff_rules.py`**：
- `test_rule1_extreme_high` - 规则1 天量
- `test_rule1_extreme_low` - 规则1 地量
- `test_rule2_markdown_block` - 规则2 Markdown 阻止
- `test_rule3_t1_safe` - 规则3 T+1 安全
- `test_rule3_t1_exceed` - 规则3 T+1 超限
- `test_rule4_no_trade_zone` - 规则4 诚实不作为
- `test_rule5_full` - 规则5 完整结构
- `test_rule5_tr_fallback` - 规则5 TR 替代
- `test_rule5_insufficient` - 规则5 结构不足
- `test_rule6_lps_confirm` - 规则6 LPS 确认
- `test_rule6_lps_not_confirm` - 规则6 LPS 未确认
- `test_rule7_maintain` - 规则7 维持判断
- `test_rule7_overturn` - 规则7 推翻
- `test_rule8_a_grade` - 规则8 A 级
- `test_rule8_d_grade` - 规则8 D 级
- `test_rule9_fully_aligned` - 规则9 三周期共振
- `test_rule9_markdown_override` - 规则9 Markdown 覆盖
- `test_rule10_stop_precision` - 规则10 止损精度
- `test_rule10_precision_warning` - 规则10 精度警告

### 11.2 删除测试

- `tests/unit/test_wyckoff_analyzer.py`（1003行，24个测试）
- `tests/unit/test_wyckoff_data_engine.py`（~170行，8个测试）

### 11.3 验收标准

1. `pytest tests/unit/test_wyckoff_engine.py` 全部通过
2. `pytest tests/unit/test_wyckoff_rules.py` 全部通过
3. `pytest tests/integration/test_wyckoff_integration.py` 全部通过
4. `pytest tests/integration/test_wyckoff_sample_replay.py` 全部通过
5. 全量 5199 只股票分析不再出现"阶段判定错误"
6. 规则8 置信度严格按 5 项条件判定
7. 规则6 Spring 不再使用 T+3 日历冷冻期
8. Step 5 输出每个字段都有值
9. 盈亏比止损精度 = 关键低点 × 0.995

---

## 十二、实施阶段

| 阶段 | 内容 | 删除 | 新增 | 更新 | 风险 |
|------|------|------|------|------|------|
| **P1** | 模型层：models.py 新增 v3.0 数据结构 | — | 14个dataclass | models.py | 低 |
| **P2** | 规则层：新建 rules.py | — | rules.py | — | 低 |
| **P3** | 引擎核心：新建 engine.py | — | engine.py | — | 中 |
| **P4** | 多周期融合 + 最终报告构建 | — | engine.py扩展 | — | 中 |
| **P5** | 删除旧模块 + 更新调用方 | analyzer.py, data_engine.py | — | 12个文件 | 高 |
| **P6** | 测试迁移 + 全量回归 | 2个旧测试文件 | 2个新测试文件 | 3个测试文件 | 中 |

### 执行顺序

```
P1: models.py 新增 v3.0 数据结构
  ↓
P2: 新建 rules.py + test_wyckoff_rules.py
  ↓
P3: 新建 engine.py (Step 0→5) + test_wyckoff_engine.py
  ↓
P4: engine.py 多周期融合 + _build_report
  ↓
P5: 删除 analyzer.py + data_engine.py + 更新所有调用方
  ↓
P6: 删除旧测试 + 更新集成测试 + 全量回归
```

---

## 十三、Promote_v3.0.md 规则映射

| v3.0 规则 | 实现位置 | 来源 |
|-----------|---------|------|
| 规则1: 相对量能 | `rules.py: rule1_relative_volume` | 两套都有，统一 |
| 规则2: A股单向做多 | `rules.py: rule2_no_long_in_markdown` | analyzer.py 保留 |
| 规则3: T+1零容错 | `rules.py: rule3_t1_risk_test` + `engine.py: _step3_t1` | **全新** |
| 规则4: 诚实不作为 | `rules.py: rule4_no_trade_zone` | **全新** |
| 规则5: BC/TR定位 | `rules.py: rule5_bc_tr_fallback` + `engine.py: _step0` | analyzer基础+降级 |
| 规则6: Spring验证 | `rules.py: rule6_spring_validation` + `engine.py: _step3` | data_engine改造 |
| 规则7: 反事实 | `rules.py: rule7_counterfactual` + `engine.py: _step35` | data_engine扩展 |
| 规则8: 置信度 | `rules.py: rule8_confidence_matrix` | **全新** |
| 规则9: 多周期 | `rules.py: rule9_multiframe_alignment` + `engine.py: _multiframe` | analyzer保留 |
| 规则10: 止损精度 | `rules.py: rule10_stop_loss` + `engine.py: _step4` | **全新** |

---

## 十四、Promote_v3.0.md 九步工作流映射

| v3.0 Step | 实现位置 | 来源 |
|-----------|---------|------|
| Step 0: BC/TR 定位 | `engine.py: _step0_bc_tr_scan` | analyzer + 规则5降级 |
| Step 1: 大局观 | `engine.py: _step1_phase_determine` | **analyzer核心保留** |
| Step 2: 努力与结果 | `engine.py: _step2_effort_result` | **data_engine直接取用** |
| Step 3: Spring/UTAD+T+1 | `engine.py: _step3_phase_c_t1` | data_engine改造+全新T+1 |
| Step 3.5: 反事实 | `engine.py: _step35_counterfactual` | data_engine扩展 |
| Step 4: 盈亏比 | `engine.py: _step4_risk_reward` | **全新** |
| Step 5: 交易计划 | `engine.py: _step5_trading_plan` | **全新** |

---

*REFACTOR_PLAN_WYCKOFF_V3_ENGINE.md v2 | 2026-05-04*
*彻底删除 analyzer.py + data_engine.py，全新构建 engine.py*
*基于 Promote_v3.0.md + 4份连续性分析档案*
