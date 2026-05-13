# 威科夫多模态分析系统 - 详细实施计划

**文档日期**: 2026-04-08
**基于**: PRD / ARCH / SPEC 全套规范文档 (2026-04-07)
**代码库分析日期**: 2026-04-08
**适用对象**: 实现工程师 / 代码审查者

---

## 0. 现状审计与差距分析

### 0.1 现有可复用能力

| 模块 | 文件 | 可复用点 | 复用方式 |
|------|------|---------|---------|
| 数据管理 | `src/data/manager.py` | DataManager 类、validate_dataframe、parquet 读写 | 继承/扩展 |
| 通达信读取 | `src/data/tdx_reader.py` | TDXReader、LPPL_TO_TDX_MAP | 扩展个股映射 |
| K线绘图 | `src/reporting/plot_generator.py` | `_plot_candlesticks()`、matplotlib 配置 | 直接调用/扩展 |
| 报告生成 | `src/reporting/investment_report.py` | MD/HTML 模板模式 | 参考实现新模板 |
| 常量定义 | `src/constants.py` | INDICES、REQUIRED_COLUMNS、输出目录常量 | 扩展 |
| 异常体系 | `src/exceptions.py` | LPPLException 层级 | 扩展威科夫异常 |
| CLI 模式 | `src/cli/index_investment_analysis.py` | argparse 模式、output_dirs 组织 | 参考实现 |

### 0.2 现有能力缺口（需新建）

| 缺口项 | PRD 要求 | 优先级 | 工作量估计 |
|--------|---------|--------|-----------|
| 个股数据支持 | 支持 A 股个股 OHLCV 读取 | P0 | 中 |
| 文件输入模式 | `--input-file` 读取 CSV/Parquet | P0 | 小 |
| Symbol 标准化 | 指数 + 个股统一格式 | P0 | 小 |
| Wyckoff Models | DailyRuleResult / ImageEvidenceBundle / AnalysisResult 等 dataclass | P0 | 中 |
| 规则引擎 | Step 0~5 完整规则链 | P0 | 大 |
| 图像引擎 | 图片扫描、symbol 归属、timeframe 识别、质量分级 | P1 | 大 |
| 融合引擎 | 冲突矩阵、一致性评分、置信度计算 | P1 | 中 |
| 状态管理 | AnalysisState、Spring 冷冻期状态机、连续性追踪 | P1 | 中 |
| 报告层 | Step 0~5 结构化报告 + 附录 A/B | P1 | 中 |
| CLI 入口 | wyckoff_multimodal_analysis.py | P0 | 中 |

### 0.3 关键约束

- **不影响现有主线**: LPPL verify / walk-forward / index_investment_analysis 必须不受影响
- **TDXReader 当前仅支持 8 个指数**: 需要扩展个股映射或新增 akshare 个股路径
- **DataManager.validate_symbol 仅接受 INDICES 字典中的 key**: 需要放宽校验
- **PlotGenerator 已有 `_plot_candlesticks` 方法**: 可直接用于威科夫图表
- **requirements.txt 无图像处理依赖**: Phase 3 需新增 Pillow/OpenCV

---

## 1. Phase 1: 数据层扩展

### 1.1 目标

使系统能够读取：A 股指数 + A 股个股 + 外部文件输入，并统一输出标准 DataFrame。

### 1.2 任务清单

#### Task 1.1.1: 扩展 constants.py — 新增威科夫相关常量

**文件**: `src/constants.py`

**新增内容**:
```python
# 威科夫相关常量
WYCKOFF_PHASES = ["accumulation", "markup", "distribution", "markdown", "no_trade_zone"]
WYCKOFF_DIRECTIONS = ["long_setup", "watch_only", "no_trade_zone", "abandon"]
WYCKOFF_CONFIDENCE_LEVELS = ["A", "B", "C", "D"]
VOLUME_LABELS = ["extreme_high", "above_average", "contracted", "extreme_contracted"]
IMAGE_QUALITY_LEVELS = ["high", "medium", "low", "unusable"]
VISUAL_TRENDS = ["uptrend", "downtrend", "range", "unclear"]
TIMEFRAME_HINTS = ["weekly", "daily", "60m", "30m", "15m", "5m", "unknown_tf"]
VISUAL_ANOMALIES = ["long_upper_wick", "long_lower_wick", "gap", "false_breakout",
                     "quick_recovery", "volume_stagnation"]

# 威科夫输出目录
WYCKOFF_OUTPUT_DIR = os.environ.get("LPPL_WYCKOFF_DIR", os.path.join(OUTPUT_DIR, "wyckoff"))

# 规则引擎参数
MIN_WYCKOFF_DATA_ROWS = 100
BC_LOOKBACK_WINDOW = 120
SPRING_FREEZE_DAYS = 3
MIN_RR_RATIO = 2.5
```

**验收标准**: 常量可导入，无语法错误，不破坏现有常量。

---

#### Task 1.1.2: 新增 exceptions — 威科夫异常类

**文件**: `src/exceptions.py`

**新增内容**:
```python
class WyckoffError(LPPLException):
    pass

class BCNotFoundError(WyckoffError):
    pass

class InvalidInputDataError(WyckoffError):
    pass

class ImageProcessingError(WyckoffError):
    pass

class FusionConflictError(WyckoffError):
    pass

class RuleEngineError(WyckoffError):
    pass
```

**验收标准**: 异常层级正确，可被 except 捕获。

---

#### Task 1.1.3: 新增 `src/wyckoff/models.py` — 核心数据模型

**文件**: `src/wyckoff/__init__.py` (空 init)
**文件**: `src/wyckoff/models.py`

**必须实现的 dataclass**:

```python
@dataclass
class ChartManifestItem:
    file_path: str
    file_name: str
    relative_dir: str
    modified_time: str
    symbol: str
    inferred_timeframe: str
    image_quality: str

@dataclass
class ChartManifest:
    files: List[ChartManifestItem]
    total_count: int
    usable_count: int
    scan_time: str

@dataclass
class PreprocessingResult:
    trend_direction: str
    volume_label: str
    volatility_layer: str
    local_highs: List[Dict]
    local_lows: List[Dict]
    gap_candidates: List[Dict]
    long_wick_candidates: List[Dict]
    limit_anomalies: List[Dict]

@dataclass
class BCResult:
    found: bool
    candidate_index: int
    candidate_date: str
    candidate_price: float
    volume_label: str
    enhancement_signals: List[str]

@dataclass
class PhaseResult:
    phase: str
    boundary_upper_zone: str
    boundary_lower_zone: str
    boundary_sources: List[str]

@dataclass
class EffortResult:
    phenomena: List[str]
    accumulation_evidence: float
    distribution_evidence: float
    net_bias: str

@dataclass
class PhaseCTestResult:
    spring_detected: bool
    utad_detected: bool
    st_detected: bool
    false_breakout_detected: bool
    spring_date: Optional[str]
    utad_date: Optional[str]

@dataclass
class CounterfactualResult:
    is_utad_not_breakout: str
    is_distribution_not_accumulation: str
    is_chaos_not_phase_c: str
    liquidity_vacuum_risk: str
    total_pro_score: float
    total_con_score: float
    conclusion_overturned: bool

@dataclass
class RiskAssessment:
    t1_risk_level: str
    t1_structural_description: str
    rr_ratio: float
    rr_assessment: str
    freeze_until: Optional[str]

@dataclass
class TradingPlan:
    current_assessment: str
    execution_preconditions: List[str]
    direction: str
    entry_trigger: str
    invalidation: str
    target_1: str

@dataclass
class DailyRuleResult:
    symbol: str
    asset_type: str
    analysis_date: str
    input_source: str
    preprocessing: PreprocessingResult
    bc_result: BCResult
    phase_result: PhaseResult
    effort_result: EffortResult
    phase_c_test: PhaseCTestResult
    counterfactual: CounterfactualResult
    risk: RiskAssessment
    plan: TradingPlan
    confidence: str
    decision: str
    abandon_reason: str

@dataclass
class VisualEvidence:
    visual_trend: str
    visual_phase_hint: str
    visual_boundaries: Dict[str, str]
    visual_anomalies: List[str]
    visual_volume_label: str

@dataclass
class ImageEvidenceBundle:
    manifest: ChartManifest
    detected_timeframes: List[str]
    overall_image_quality: str
    visual_evidence_list: List[VisualEvidence]
    trust_level: str

@dataclass
class ConflictItem:
    conflict_type: str
    data_verdict: str
    image_verdict: str
    resolution: str
    severity: str

@dataclass
class AnalysisResult:
    symbol: str
    asset_type: str
    analysis_date: str
    input_sources: List[str]
    timeframes_seen: List[str]
    bc_found: bool
    phase: str
    micro_action: str
    boundary_upper_zone: str
    boundary_lower_zone: str
    volume_profile_label: str
    spring_detected: bool
    utad_detected: bool
    counterfactual_summary: str
    t1_risk_assessment: str
    rr_assessment: str
    decision: str
    trigger: str
    invalidation: str
    target_1: str
    confidence: str
    abandon_reason: str
    conflicts: List[str]
    image_bundle: Optional[ImageEvidenceBundle]
    consistency_score: str
    weekly_context: str
    intraday_context: str

@dataclass
class AnalysisState:
    symbol: str
    asset_type: str
    analysis_date: str
    last_phase: str
    last_micro_action: str
    last_confidence: str
    bc_found: bool
    spring_detected: bool
    freeze_until: Optional[str]
    watch_status: str
    trigger_armed: bool
    trigger_text: str
    invalid_level: str
    target_1: str
    weekly_context: str
    intraday_context: str
    conflict_summary: List[str]
    last_decision: str
    abandon_reason: str
```

**验收标准**: 所有 dataclass 可实例化，字段类型正确，与 SPEC_WYCKOFF_OUTPUT_SCHEMA 一致。

---

#### Task 1.1.4: 新增 `src/wyckoff/config.py` — 威科夫配置

**文件**: `src/wyckoff/config.py`

**内容**:
- 规则引擎参数配置（BC 窗口、量能阈值等）
- 图像引擎参数配置（质量阈值、分辨率门槛）
- 融合引擎参数配置（冲突权重、置信度计算系数）
- 输出目录组织配置

**验收标准**: 配置可从 YAML 或环境变量加载。

---

#### Task 1.1.5: 扩展数据层 — 支持个股和文件输入

**修改文件**: `src/data/manager.py`
**修改文件**: `src/data/tdx_reader.py`
**修改文件**: `src/constants.py`

**具体改动**:

1. **constants.py** — 新增:
   - `STOCK_SYMBOL_PATTERN`: 个股代码正则 (如 `^\d{6}\.(SH|SZ)$`)
   - 扩展 `INDICES` 或新增 `ALL_SYMBOLS` 包含个股白名单逻辑
   - 新增 `VALIDATE_SYMBOL_STRICT_MODE` 标志（威科夫模式下放宽）

2. **tdx_reader.py** — 扩展 `LPPL_TO_TDX_MAP`:
   - 支持动态个股映射（通过 code 前缀推断 market）
   - 新增 `stock_daily(code: str)` 方法读取个股 .day 文件
   - 新增 `_resolve_stock_path(lppl_code: str) -> Optional[Path]`

3. **manager.py** — 新增方法:
   - `get_stock_data(symbol: str) -> Optional[pd.DataFrame]`: 个股数据读取
   - `read_from_file(file_path: str) -> Optional[pd.DataFrame]`: CSV/Parquet 文件输入
   - `normalize_symbol(symbol: str) -> str`: symbol 标准化
   - `classify_asset_type(symbol: str) -> str`: 返回 "index" 或 "stock"
   - 修改 `validate_symbol()` 在威科夫模式下允许个股代码

**验收标准**:
- 能读取至少一个测试个股数据
- 能从 CSV/Parquet 文件读取数据并输出标准 DataFrame
- `normalize_symbol("600519")` → `"600519.SH"`
- `classify_asset_type("000300.SH")` → `"index"`
- `classify_asset_type("600519.SH")` → `"stock"`

---

### 1.3 Phase 1 DoD

- [ ] `src/wyckoff/__init__.py` 存在且可导入
- [ ] `src/wyckoff/models.py` 所有 dataclass 定义完整
- [ ] `src/wyckoff/config.py` 存在且可加载配置
- [ ] `src/constants.py` 新增威科夫常量且无破坏性变更
- [ ] `src/exceptions.py` 新增威科夫异常类
- [ ] `DataManager` 支持个股数据读取（至少 1 个测试用例通过）
- [ ] `DataManager` 支持文件输入（CSV/Parquet）
- [ ] symbol 标准化和资产分类功能可用
- [ ] 现有 `index_investment_analysis.py` 不受影响（回归测试通过）

---

## 2. Phase 2: 规则引擎

### 2.1 目标

实现 Step 0 ~ Step 5 完整日线规则链，输出 `DailyRuleResult`。

### 2.2 任务清单

#### Task 2.1: 新增 `src/wyckoff/data_engine.py` — 数据引擎主入口

**文件**: `src/wyckoff/data_engine.py`

**职责**:
- 接收 DataFrame + symbol
- 调用预处理 → BC扫描 → 阶段识别 → 努力结果 → Phase C 测试 → 反事实 → 风险评估 → 交易计划
- 输出 `DailyRuleResult`
- 严格按 SPEC_WYCKOFF_RULE_ENGINE 第 2 节的执行顺序执行

**核心类与方法**:
```python
class DataEngine:
    def __init__(self, config: WyckoffConfig):
        self.config = config

    def run(self, df: pd.DataFrame, symbol: str, asset_type: str) -> DailyRuleResult:
        """主入口，严格按 Step 0~5 顺序执行"""

    def _step_validate(self, df: pd.DataFrame) -> None:
        """输入校验 — SPEC Section 1"""

    def _step_preprocess(self, df: pd.DataFrame) -> PreprocessingResult:
        """预处理 — SPEC Section 3"""

    def _step0_bc_scan(self, df: pd.DataFrame, prep: PreprocessingResult) -> BCResult:
        """BC 定位扫描 — SPEC Section 4"""

    def _step1_phase_identify(self, df: pd.DataFrame, bc: BCResult,
                               prep: PreprocessingResult) -> PhaseResult:
        """大局观与阶段 — SPEC Section 5"""

    def _step2_effort_result(self, df: pd.DataFrame, phase: PhaseResult,
                              prep: PreprocessingResult) -> EffortResult:
        """努力与结果 — SPEC Section 6"""

    def _step3_phase_c_test(self, df: pd.DataFrame, phase: PhaseResult,
                             bc: BCResult, prep: PreprocessingResult) -> PhaseCTestResult:
        """Phase C 终极测试 — SPEC Section 7"""

    def _step35_counterfactual(self, df: pd.DataFrame, results: Dict) -> CounterfactualResult:
        """反事实压力测试 — SPEC Section 8"""

    def _step4_risk_assessment(self, df: pd.DataFrame, results: Dict,
                                phase_c: PhaseCTestResult) -> RiskAssessment:
        """T+1 与盈亏比 — SPEC Section 9"""

    def _step5_trading_plan(self, results: Dict) -> TradingPlan:
        """交易计划 — SPEC Section 10"""
```

**验收标准**: 
- 执行顺序严格遵守 Step 0→5
- BC 未找到时返回 D 级 + abandon
- Distribution/Markdown 时只输出 watch_only/abandon

---

#### Task 2.2: 实现预处理模块 (`_step_preprocess`)

**关键算法**:
1. **趋势方向**: 近 N 日收盘价线性回归斜率 + MA 交叉判断
2. **量能标签**: 最近 20 日成交量 vs 60 日均值比值分档
   - `extreme_high`: > 2.0 倍
   - `above_average`: 1.2 ~ 2.0 倍
   - `contracted`: 0.5 ~ 1.2 倍
   - `extreme_contracted`: < 0.5 倍
3. **波动分层**: ATR(14) / 收盘价 分档
4. **局部高低点**: 窗口内 rolling max/min
5. **缺口候选**: `low > prev_high` 或 `high < prev_low`
6. **长影线候选**: `(high - low) > 3 * |close - open|`
7. **涨跌停异常**: 涨跌幅 >= 9.5%

**验收标准**: 所有标签使用枚举值，不编造绝对数值。

---

#### Task 2.3: 实现 BC 定位扫描 (`_step0_bc_scan`)

**SPEC Section 4 强制要求**:
- 任何方向性判断前必须先定位 BC
- BC 候选条件：
  1. 左侧存在明显上涨（前 60 日涨幅 > 15%）
  2. 是局部高点或近似局部高点（rolling(20).max() 的 top 3）
  3. 成交量标签为 extreme_high 或 above_average
  4. 伴随增强信号之一：高位长上影 / 放量滞涨 / 跳空后衰竭 / 假突破后回落
- 终止规则：无候选 → `bc_found=false`, `confidence=D`, `decision=abandon`, `abandon_reason=bc_not_found`

**验收标准**: 
- 有明确上涨 + 高位放量时能找到 BC
- 无 BC 时立即终止后续步骤

---

#### Task 2.4: 实现阶段识别 (`_step1_phase_identify`)

**阶段判定逻辑概要**:

| 阶段 | 判定条件摘要 |
|------|-------------|
| accumulation | BC 后下跌 + 低位缩量 + 底部区间震荡 |
| markup | BC 后回调不破关键支撑 + 放量上攻 |
| distribution | 高位震荡 + 放量滞涨 + 派发信号 > 吸筹信号 |
| markdown | 跌破关键支撑 + 下方无承接 |
| no_trade_zone | 信号杂乱 / 无法归入上述任一阶段 |

**边界来源优先级**: BC → AR → SC → ST → 放量极值带 → 关键起跌点 → 未测试缺口带

**验收标准**: 只输出 5 种合法阶段值。

---

#### Task 2.5: 实现努力与结果 (`_step2_effort_result`)

**必须识别的现象**:
- 放量滞涨: 涨幅 < 1% 且 volume_label in {extreme_high, above_average}
- 缩量上推: 涨幅 > 1% 且 volume_label == contracted
- 下边界供给枯竭: 接近下边界 + 缩量 + 下影线
- 高位炸板遗迹: 高位长上影 + 极端放量
- 吸筹/派发倾向: 综合评分

**强制规则**:
- 派发证据强于吸筹证据 → 不得输出积极做多计划
- 信号杂乱 → no_trade_zone

---

#### Task 2.6: 实现 Phase C 终极测试 (`_step3_phase_c_test`)

**Spring 检测**:
- 刺穿下边界（close < boundary_lower 连续 1-2 日）
- 快速收回（2 日内回到边界上方）
- 相对量能: 缩量刺穿更可信
- 二次测试需要: Spring 后是否出现 ST

**UTAD 检测**:
- 刺穿上边界后快速回落
- 伴随放量

**验收标准**: Spring 检测后自动设置 freeze_until = detect_date + 3 trading days。

---

#### Task 2.7: 实现反事实压力测试 (`_step35_counterfactual`)

**四组反证**:
1. 这是 UTAD 不是突破
2. 这是派发不是吸筹
3. 这是无序震荡不是 Phase C
4. 买入后次日可能进入流动性真空

**裁决规则**: 反证总强度 >= 正证总强度 → 推翻多头结论 → watch_only/no_trade_zone/abandon

---

#### Task 2.8: 实现 T+1 与盈亏比 (`_step4_risk_assessment`)

**T+1 风险评估**:
- 分析最近波动率水平
- 评估次日最大不利结构性回撤可能
- 输出: low / medium / high / critical

**R:R 计算**:
- 第一目标位 = 最近未测试强阻力
- 入场位 = 当前价或 trigger 价
- 止损位 = invalidation 位
- 若 R:R < 1:2.5 → abandon

**Spring 冷冻期**:
- spring_detected=True → freeze_until = detect_date + 3 trading days
- 冷冻期内只允许 watch_only

---

#### Task 2.9: 实现交易计划 (`_step5_trading_plan`)

**固定输出字段**: current_assessment, execution_preconditions, direction, entry_trigger, invalidation, target_1

**方向约束**: 只允许 long_setup / watch_only / no_trade_zone / abandon

**A股强约束**: distribution 或 markdown → 只能 watch_only 或 abandon

**置信度分级** (SPEC Section 11):

| 等级 | 条件 |
|------|------|
| A | BC 明确 + 边界清晰 + Phase C 明确 + 反证弱 + R:R >= 1:3 |
| B | BC 明确 + 结构较清晰 + 少量不确定 + R:R >= 1:2.5 |
| C | 结构勉强成立 + 证据冲突较多 → 仅观察 |
| D | BC 不成立 / 数据差 / 结构混乱 / 反证更强 |

**强制保守降级** (SPEC Section 12): 任一命中即降级。

---

### 2.3 Phase 2 DoD

- [ ] `src/wyckoff/data_engine.py` 存在且 `DataEngine.run()` 可执行
- [ ] Step 0: BC 未找到 → D 级 + abandon（单测覆盖）
- [ ] Step 1: 只输出 5 种合法阶段值（单测覆盖）
- [ ] Step 2: 派发强于吸筹时不给做多（单测覆盖）
- [ ] Step 3: Spring 检测 + T+3 冷冻期（单测覆盖）
- [ ] Step 3.5: 反证更强时推翻多头（单测覆盖）
- [ ] Step 4: R:R < 1:2.5 时 abandon（单测覆盖）
- [ ] Step 5: Distribution/Markdown 严禁多头（单测覆盖）
- [ ] 量能标签只使用 4 种枚举值（单测覆盖）
- [ ] 整体链路可通过单个指数跑通（集成测试）

---

## 3. Phase 3: 图像引擎

### 3.1 目标

扫描项目图表文件夹，提取视觉证据，输出 `ImageEvidenceBundle`。

### 3.2 任务清单

#### Task 3.1: 新增 `src/wyckoff/image_engine.py` — 图像引擎

**文件**: `src/wyckoff/image_engine.py`

**核心类与方法**:
```python
class ImageEngine:
    def __init__(self, config: WyckoffConfig):
        self.config = config

    def scan_directory(self, chart_dir: str) -> ChartManifest:
        """递归扫描目录下所有图片"""

    def scan_files(self, chart_files: List[str]) -> ChartManifest:
        """扫描显式文件列表"""

    def assign_symbol(self, item: ChartManifestItem, explicit_symbol: Optional[str] = None) -> str:
        """标的归属 — SPEC Section 3 优先级规则"""

    def detect_timeframe(self, item: ChartManifestItem) -> str:
        """时间周期识别 — SPEC Section 4"""

    def assess_quality(self, image_path: str) -> str:
        """图像质量分级 — SPEC Section 5"""

    def extract_visual_evidence(self, item: ChartManifestItem) -> VisualEvidence:
        """提取视觉证据 — SPEC Section 6"""

    def run(self, chart_dir: Optional[str] = None,
             chart_files: Optional[List[str]] = None,
             explicit_symbol: Optional[str] = None) -> ImageEvidenceBundle:
        """图像引擎主入口"""
```

---

#### Task 3.2: 实现文件扫描 (`scan_directory` / `scan_files`)

**SPEC Section 2 要求**:
- 支持格式: .png / .jpg / .jpeg / .webp
- `--chart-dir`: 递归扫描
- `--chart-files`: 显式列表
- 输出 `ChartManifest` 含: 文件路径、文件名、相对目录、修改时间、归属 symbol、推断 timeframe、图像质量

**依赖**: Pillow (PIL) 用于基本图片信息读取

**验收标准**: 能扫描 `output/**/plots/*.png` 并生成完整 manifest。

---

#### Task 3.3: 实现标的归属 (`assign_symbol`)

**SPEC Section 3 优先级**:
1. 文件名包含标准 symbol（如 `600519`、`000001`）
2. 父目录名包含标准 symbol
3. 命令行显式指定 `--symbol`
4. 无法归属 → `unassigned`

**unassigned 图片不得进入主结论，只能写入 evidence 警告。**

**验收标准**: 正确归属已有 plots 目录下的图片。

---

#### Task 3.4: 实现时间周期识别 (`detect_timeframe`)

**SPEC Section 4 优先级**:
1. 文件名识别（含 `weekly`/`周线`/`60min`/`日线` 等关键词）
2. OCR 辅读图文字（可选，Phase 3 v1 可仅做关键词匹配）
3. 视觉布局启发式（图片宽高比等，v1 可简化）
4. 无法识别 → `unknown_tf`

**建议识别值**: weekly / daily / 60m / 30m / 15m / 5m / unknown_tf

---

#### Task 3.5: 实现图像质量分级 (`assess_quality`)

**SPEC Section 5 标准**:

| 等级 | 标准 |
|------|------|
| high | 分辨率足够 + K线清晰 + 边界可辨 + 量能区清晰 |
| medium | 结构可辨认 + 少量遮挡或压缩 |
| low | 只能看大趋势 + 细节难辨 |
| unusable | 严重模糊 / 重度遮挡 / 主图裁切过度 |

**技术方案**:
- 使用 PIL 读取图片尺寸（分辨率判断）
- 使用拉普拉斯方差判断模糊程度
- 可选: 使用 OpenCV 做 K线区检测（v1 可简化为分辨率+清晰度）

**约束**: low 和 unusable 图片不得提升置信度。

---

#### Task 3.6: 实现视觉证据提取 (`extract_visual_evidence`)

**SPEC Section 6 允许输出的类别**:
- `visual_trend`: uptrend / downtrend / range / unclear
- `visual_phase_hint`: possible_accumulation / possible_markup / possible_distribution / possible_markdown / unclear
- `visual_boundary_hint`: 箱体上下沿 / 通道轨 / 供应区 / 需求区
- `visual_anomalies`: 长上影 / 长下影 / 跳空 / 假突破 / 快速收回 / 放量滞涨
- `visual_volume_label`: extreme_high / above_average / contracted / extreme_contracted / unclear

**禁止输出**: 精确 OHLC 数值、成交量绝对数值、最终交易方向、买卖建议

**v1 实现策略**:
- 基础版: 图片元数据分析 + 文件名启发式
- 进阶版（可选）: 集成多模态 LLM 视觉能力

---

### 3.3 Phase 3 DoD

- [ ] `src/wyckoff/image_engine.py` 存在且可执行
- [ ] 能扫描 `output/**/plots/*.png` 生成 manifest
- [ ] symbol 归属规则正确（单测覆盖）
- [ ] timeframe 识别支持 unknown_tf 回退（单测覆盖）
- [ ] 图像质量分级 4 档齐全（单测覆盖）
- [ ] 低质量图片不能提升置信度（单测覆盖）
- [ ] 不输出成交量绝对数值（单测覆盖）
- [ ] 图片-only 模式 confidence <= C（单测覆盖）

---

## 4. Phase 4: 融合引擎与状态层

### 4.1 目标

合并数据引擎与图像引擎结果，计算冲突与一致性，生成最终 `AnalysisResult`，落盘状态文件。

### 4.2 任务清单

#### Task 4.1: 新增 `src/wyckoff/fusion_engine.py` — 融合引擎

**文件**: `src/wyckoff/fusion_engine.py`

**核心类与方法**:
```python
class FusionEngine:
    def __init__(self, config: WyckoffConfig):
        self.config = config

    def fuse(self, data_result: DailyRuleResult,
             image_bundle: Optional[ImageEvidenceBundle] = None) -> AnalysisResult:
        """融合主入口 — SPEC Section 3 融合顺序"""

    def _check_data_availability(self, data_result: Optional[DailyRuleResult],
                                  image_bundle: Optional[ImageEvidenceBundle]) -> str:
        """计算数据可用性与可信度"""

    def _generate_conflicts(self, data_result: DailyRuleResult,
                            image_bundle: ImageEvidenceBundle) -> List[ConflictItem]:
        """生成冲突列表 — SPEC Section 4 冲突矩阵"""

    def _calc_consistency_score(self, conflicts: List[ConflictItem],
                                 image_quality: str) -> str:
        """一致性评分 — SPEC Section 5"""

    def _adjust_confidence(self, base_confidence: str,
                           consistency: str,
                           image_quality: str,
                           cross_tf_alignment: str) -> str:
        """调整最终置信度 — SPEC Section 6"""

    def _conservative_check(self, result: AnalysisResult) -> AnalysisResult:
        """保守复核门槛 — SPEC Section 7"""
```

---

#### Task 4.2: 实现冲突矩阵 (`_generate_conflicts`)

**SPEC Section 4 五种冲突场景**:

| # | 场景 | 结果 | 处理 |
|---|------|------|------|
| 4.1 | 数据=Distribution, 图片=Markup | watch_only/abandon | 置信度降级 |
| 4.2 | 数据=Spring candidate, 周线=高位供应区 | 不允许多做 | 降级到 watch_only |
| 4.3 | 数据=No Trade Zone, 图片=局部突破 | 保持 no_trade_zone | 图片不推翻数据 |
| 4.4 | 数据=多头候选, 盘中=无确认 | 保留 trigger | 不提高置信度 |
| 4.5 | 多张图片互相冲突 | 图像整体降级 | image_confidence_cap = low |

**验收标准**: 5 种冲突场景全覆盖。

---

#### Task 4.3: 实现一致性评分 (`_calc_consistency_score`)

**SPEC Section 5 维度**:
- 阶段一致性
- 趋势一致性
- 边界一致性
- 多周期上下文一致性
- 图像质量权重

**输出等级**: high_alignment / medium_alignment / low_alignment / conflicted

---

#### Task 4.4: 实现最终置信度规则 (`_adjust_confidence`)

**SPEC Section 6 四维组成**: rule_score + image_quality_score + cross_tf_score + consistency_score

**强制规则**:
- 图片永远不能单独把 C 提升到 A
- 图片 low/unusable 只能降级，不能升级

**验收标准**: 符合 A/B/C/D 四级定义。

---

#### Task 4.5: 实现保守复核 (`_conservative_check`)

**SPEC Section 7 五项检查**:
1. `bc_found == false` → 降级
2. `phase in {distribution, markdown}` → 降级
3. `rr_assessment` 不合格 → 降级
4. `spring_detected` 且冷冻期未结束 → 降级
5. `consistency_score == conflicted` → 降级

---

#### Task 4.6: 新增 `src/wyckoff/state.py` — 状态管理层

**文件**: `src/wyckoff/state.py`

**核心类与方法**:
```python
class StateManager:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def load_state(self, symbol: str) -> Optional[AnalysisState]:
        """加载上次分析状态"""

    def save_state(self, state: AnalysisState) -> str:
        """保存状态到 JSON 文件"""

    def generate_continuity_template(self, current: AnalysisResult,
                                      previous: Optional[AnalysisState]) -> Dict:
        """连续性追踪模板 — SPEC Appendix A"""
```

**状态文件 schema** — SPEC Section 8 必须包含全部 23 个字段。

**Spring 冷冻期状态机** — SPEC Section 9:
- 初始: spring_detected=false, watch_status=none
- 识别到 Spring: spring_detected=true, freeze_until=detect_date+3d, watch_status=cooling_down
- 冷冻期内: 不允许 long_setup，只允许 watch_only
- 冷冻期结束后: 可升级为执行候选

---

### 4.3 Phase 4 DoD

- [ ] `src/wyckoff/fusion_engine.py` 存在且 `fuse()` 可执行
- [ ] 5 种冲突场景全覆盖（单测/集成测试）
- [ ] 一致性评分 4 档齐全
- [ ] 置信度四维计算正确
- [ ] 保守复核五项检查生效
- [ ] `src/wyckoff/state.py` 存在且状态文件可读写
- [ ] Spring 冷冻期状态机正确（单测覆盖）
- [ ] 连续性追踪模板可生成
- [ ] 数据+图片融合模式可跑通（集成测试）

---

## 5. Phase 5: 报告层与 CLI 入口

### 5.1 目标

生成 deterministic Markdown / HTML 报告，创建 CLI 入口，支持可选 LLM 增强。

### 5.2 任务清单

#### Task 5.1: 新增 `src/wyckoff/reporting.py` — 威科夫报告生成器

**文件**: `src/wyckoff/reporting.py`

**核心类与方法**:
```python
class WyckoffReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

    def generate_markdown_report(self, result: AnalysisResult,
                                   state: Optional[AnalysisState] = None,
                                   image_bundle: Optional[ImageEvidenceBundle] = None) -> str:
        """生成 Step 0~5 + 附录 A/B Markdown 报告"""

    def generate_html_report(self, result: AnalysisResult,
                               state: Optional[AnalysisState] = None,
                               image_bundle: Optional[ImageEvidenceBundle] = None) -> str:
        """生成 HTML 报告"""

    def generate_summary_csv(self, result: AnalysisResult) -> str:
        """生成 CSV Summary — SPEC Section 4"""

    def generate_raw_json(self, result: AnalysisResult) -> str:
        """生成原始 JSON — SPEC Section 1"""

    def generate_evidence_json(self, bundle: ImageEvidenceBundle) -> str:
        """生成图像证据 JSON — SPEC Section 2"""

    def generate_conflicts_json(self, conflicts: List[ConflictItem]) -> str:
        """生成冲突清单 JSON"""
```

**报告结构** (按 SPEC_WYCKOFF_OUTPUT_SCHEMA Section 5):

```
# 威科夫多模态分析报告 - {symbol}
## Step 0: BC 定位
## Step 1: 大局观与阶段
## Step 2: 努力与结果
## Step 3: Phase C 终极测试
## Step 3.5: 反事实压力测试
## Step 4: T+1 与盈亏比
## Step 5: 交易计划
## 附录 A: 连续性追踪
## 附录 B: 视觉证据摘要
```

---

#### Task 5.2: 新增 `src/cli/wyckoff_multimodal_analysis.py` — CLI 入口

**文件**: `src/cli/wyckoff_multimodal_analysis.py`

**CLI 参数设计**:

```python
parser.add_argument("--symbol", "-s", help="标的代码 (如 000300.SH 或 600519.SH)")
parser.add_argument("--input-file", "-f", help="OHLCV 文件路径 (CSV/Parquet)")
parser.add_argument("--chart-dir", help="图表目录路径")
parser.add_argument("--chart-files", nargs="+", help="图表文件列表")
parser.add_argument("--output", "-o", default="output/wyckoff", help="输出目录")
parser.add_argument("--mode", choices=["auto", "data_only", "image_only", "fusion"],
                    default="auto", help="运行模式")
parser.add_argument("--llm-provider", help="LLM 提供商 (可选)")
parser.add_argument("--llm-api-key", help="LLM API Key (可选)")
```

**三种模式调度逻辑** (ARCH Section 4):

1. **data-only**: DataManager → DataEngine → FusionEngine(透传) → ReportGenerator → StateManager
2. **image-only**: ImageEngine → FusionEngine(低置信) → ReportGenerator(视觉报告)
3. **fusion**: DataManager + ImageEngine → DataEngine + ImageEngine → Fuse → Report → State

**auto 模式判断**:
- 有 symbol/input_file + 有 chart_dir/chart_files → fusion
- 有 symbol/input-file 但无图片 → data_only
- 只有 chart_dir/chart-files → image_only

**输出目录结构** (ARCH Section 6):
```
output/wyckoff/<symbol_or_run_id>/
├── raw/
│   ├── analysis_<symbol>.json
│   └── image_evidence_<symbol>.json
├── plots/
│   ├── <symbol>_wyckoff_overview.png
│   └── <symbol>_multiframe_evidence.png
├── reports/
│   ├── <symbol>_wyckoff_report.md
│   └── <symbol>_wyckoff_report.html
├── summary/
│   └── analysis_summary_<symbol>.csv
├── state/
│   └── <symbol>_wyckoff_state.json
└── evidence/
    ├── <symbol>_chart_manifest.json
    └── <symbol>_conflicts.json
```

---

#### Task 5.3: 实现可选 LLM 增强

**SPEC_WYCKOFF_OUTPUT_SCHEMA Section 6~8 约束**:

**LLM 输入契约**:
- 只包含: AnalysisResult + ImageEvidenceBundle 摘要 + AnalysisState 摘要 + 报告模板结构 + 禁止改写字段列表
- 不得读取: 原始图片二进制 / 原始完整 OHLCV 全量序列

**LLM 禁止改写字段** (13 个): phase, micro_action, decision, confidence, boundary_upper_zone, boundary_lower_zone, spring_detected, utad_detected, trigger, invalidation, target_1, abandon_reason

**Deterministic Fallback** (SPEC Section 9):
- 无 LLM 配置 → 模板报告
- LLM 请求失败 → 模板报告
- LLM 输出缺字段 → 模板报告
- LLM 输出与结构字段冲突 → 模板报告

**v1 策略**: LLM 增强作为 Phase 5.5 可选项，v1 先确保 deterministic 报告完整可用。

---

### 5.3 Phase 5 DoD

- [ ] `src/wyckoff/reporting.py` 存在且可生成 MD/HTML/CSV/JSON
- [ ] 报告包含 Step 0~5 + 附录 A/B 完整结构
- [ ] `src/cli/wyckoff_multimodal_analysis.py` 存在且三种模式可运行
- [ ] data-only 模式: 可生成 JSON/CSV/MD/HTML/state
- [ ] image-only 模式: 可生成 evidence/MD/HTML，confidence <= C
- [ ] fusion 模式: 可生成全套工件
- [ ] 无 LLM 配置时 deterministic 报告仍完整输出
- [ ] 输出目录结构符合 ARCH Section 6
- [ ] LLM 不可用时自动回退模板报告

---

## 6. Phase 6: 测试、文档、Smoke Run

### 6.1 目标

完成单元测试、集成测试、回归测试，更新文档，执行 Smoke Run。

### 6.2 任务清单

#### Task 6.1: 单元测试

**目录**: `tests/unit/test_wyckoff_*`

| 测试文件 | 覆盖范围 | 关键用例数 |
|----------|---------|-----------|
| `test_wyckoff_models.py` | models.py dataclass | ≥ 5 |
| `test_wyckoff_config.py` | config.py 加载 | ≥ 3 |
| `test_wyckoff_data_engine.py` | 规则引擎全流程 | ≥ 15 |
| `test_wyckoff_data_engine_bc.py` | BC 扫描专项 | ≥ 5 |
| `test_wyckoff_data_engine_phase.py` | 阶段识别专项 | ≥ 5 |
| `test_wyckoff_data_engine_spring.py` | Spring + 冷冻期 | ≥ 5 |
| `test_wyckoff_data_engine_rr.py` | R:R 门槛 | ≥ 3 |
| `test_wyckoff_data_engine_counterfactual.py` | 反事实压力测试 | ≥ 4 |
| `test_wyckoff_image_engine.py` | 图像引擎 | ≥ 8 |
| `test_wyckoff_fusion_engine.py` | 融合引擎 | ≥ 8 |
| `test_wyckoff_state.py` | 状态管理 | ≥ 5 |

**发布阻断项级用例** (TEST_PLAN Section 7):
1. 找不到 BC 但仍给方向性判断 → 必须 FAIL
2. Distribution / Markdown 输出多头计划 → 必须 FAIL
3. Spring 冷冻期内允许开仓 → 必须 FAIL
4. 图像冲突时没有降级 → 必须 FAIL
5. 图片-only 输出 A/B 级结论 → 必须 FAIL
6. LLM 改写结构字段 → 必须 FAIL
7. 缺少 state 或 evidence 工件 → 必须 FAIL

---

#### Task 6.2: 集成测试

**目录**: `tests/integration/test_wyckoff_*`

| 测试文件 | 覆盖范围 |
|----------|---------|
| `test_wyckoff_data_only.py` | data-only 模式端到端 |
| `test_wyckoff_image_only.py` | image-only 模式端到端 |
| `test_wyckoff_fusion.py` | fusion 模式端到端 |
| `test_wyckoff_conflict_scenarios.py` | 5 种冲突场景集成验证 |

---

#### Task 6.3: 回归测试

**必须验证不影响现有系统**:
- [ ] `index_investment_analysis.py` 正常运行
- [ ] `lppl_verify_v2.py` 正常运行
- [ ] `lppl_walk_forward.py` 正常运行
- [ ] `main.py` 正常运行
- [ ] 现有 reporting 测试通过
- [ ] 现有 plot_generator 测试通过

---

#### Task 6.4: Smoke Test

**最小链路覆盖** (TEST_PLAN Section 5):

1. 单指数 data-only: `python -m src.cli.wyckoff_multimodal_analysis --symbol 000300.SH`
2. 单个股 data-only: `python -m src.cli.wyckoff_multimodal_analysis --symbol 600519.SH`
3. 单指数 data+图片: 加 `--chart-dir output/MA/plots`
4. 单个股 data+图片: 同上
5. 图片-only: 仅 `--chart-dir output/MA/plots`

---

#### Task 6.5: 文档更新

- [ ] README.md 新增威科夫模块说明
- [ ] `docs/使用文档.md` 新增威科夫命令用法
- [ ] 各模块 docstring 补充

---

### 6.3 Phase 6 DoD

- [ ] 单元测试覆盖率 > 80%（目标模块）
- [ ] 发布阻断项级用例全部通过
- [ ] 三种模式集成测试通过
- [ ] 回归测试全部通过（现有主线不受影响）
- [ ] Smoke Test 5 场景全部通过
- [ ] 文档更新完成

---

## 7. 依赖关系图

```
Phase 1 (数据层)
    ├── constants.py 扩展
    ├── exceptions.py 扩展
    ├── models.py (新建)
    ├── config.py (新建)
    └── data 层扩展 (manager.py / tdx_reader.py)
         │
         ▼
Phase 2 (规则引擎) ← 依赖 Phase 1
    └── data_engine.py (新建)
         │
         ▼
Phase 3 (图像引擎) ← 依赖 Phase 1 (models + config)，可与 Phase 2 并行
    └── image_engine.py (新建)
         │
         ▼
Phase 4 (融合+状态) ← 依赖 Phase 2 + Phase 3
    ├── fusion_engine.py (新建)
    └── state.py (新建)
         │
         ▼
Phase 5 (报告+CLI) ← 依赖 Phase 4
    ├── reporting.py (新建)
    └── cli/wyckoff_multimodal_analysis.py (新建)
         │
         ▼
Phase 6 (测试+文档) ← 依赖 Phase 5
```

---

## 8. 风险点与缓解措施

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 个股 TDX 路径映射不全 | 数据不可用 | 中 | akshare 作为 fallback |
| 图片命名不规范 | symbol 归属失败率高 | 高 | unassigned 安全回退 |
| 规则引擎过松/过严 | 误判/漏判 | 中 | 单测锁定行为 |
| 图像质量不稳定 | 证据不可靠 | 高 | 质量分级 + 降级机制 |
| LLM 输出越权 | 结论被篡改 | 低 | 禁止改写列表 + deterministic fallback |
| 性能问题 (大量图片) | 运行超时 | 低 | 并行处理 + 超时控制 |

---

## 9. 文件变更清单汇总

### 新建文件 (12 个)

| 文件路径 | 所属 Phase |
|----------|-----------|
| `src/wyckoff/__init__.py` | Phase 1 |
| `src/wyckoff/models.py` | Phase 1 |
| `src/wyckoff/config.py` | Phase 1 |
| `src/wyckoff/data_engine.py` | Phase 2 |
| `src/wyckoff/image_engine.py` | Phase 3 |
| `src/wyckoff/fusion_engine.py` | Phase 4 |
| `src/wyckoff/state.py` | Phase 4 |
| `src/wyckoff/reporting.py` | Phase 5 |
| `src/cli/wyckoff_multimodal_analysis.py` | Phase 5 |
| `tests/unit/test_wyckoff_models.py` | Phase 6 |
| `tests/unit/test_wyckoff_data_engine.py` | Phase 6 |
| `tests/integration/test_wyckoff_fusion.py` | Phase 6 |

### 修改文件 (4 个)

| 文件路径 | 修改内容 | 所属 Phase |
|----------|---------|-----------|
| `src/constants.py` | 新增威科夫常量 | Phase 1 |
| `src/exceptions.py` | 新增威科夫异常类 | Phase 1 |
| `src/data/manager.py` | 新增个股/文件输入方法 | Phase 1 |
| `src/data/tdx_reader.py` | 扩展个股映射 | Phase 1 |

---

## 10. 实施完成标志

以下 **全部满足** 时视为实施完成：

- [ ] 12 个新文件 + 4 个修改文件全部到位
- [ ] CLI 可运行三种模式 (data-only / image-only / fusion)
- [ ] 数据引擎、图像引擎、融合引擎分离且独立可测
- [ ] 状态与报告工件完整输出（10 类工件齐全）
- [ ] 降级路径可验证（无 LLM / 图像不可用 / 数据不可用 / 冲突）
- [ ] 7 项发布阻断项级测试全部通过
- [ ] 现有 LPPL / investment 主线回归测试通过
- [ ] Smoke Run 5 场景全部通过
