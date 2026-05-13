# LPPL 量化金融分析系统 — 源代码评估与改进意见

> 评估日期：2026-05-12
> 代码总量：约 21,440 行 Python（src/ 目录）
> 评估版本：main branch (commit 2d1c616)

---

## 一、系统架构总览

系统分为三大核心模块：

| 模块 | 文件数 | 核心职责 |
|------|--------|---------|
| **LPPL 核心** | ~8 文件 | 对数周期幂律模型（LPPL）的拟合、风险检测、多窗口扫描与集成分析 |
| **Wyckoff 威科夫分析** | ~12 文件 | 量价关系分析、BC/SC 检测、10 条规则引擎、图像识别融合、多模态决策 |
| **投资回测** | ~8 文件 | 信号生成、回测引擎、因子组合评分、策略参数调优 |

### 1.1 LPPL 模块结构

```
src/lppl_core.py         # 底层数值核心：LPPL 函数、代价函数、单窗口拟合、输入校验
src/lppl_engine.py        # 工业级引擎：LPPLConfig、DE/L-BFGS-B 优化、Ensemble 集成、峰值分析
src/lppl_multifit.py      # 三层多窗口拟合：short[40,60,80]、medium[80,120,180]、long[180,240,360]
src/lppl_cluster.py       # 信号聚类检测：30 天窗口内 danger 信号密度分析
src/lppl_regime.py        # 市场环境检测：基于均线排列与波动率的牛熊震荡市分类
src/lppl_fit.py           # [已弃用] 极速拟合模块（L-BFGS-B 多初始值）
```

### 1.2 Wyckoff 模块结构

```
src/wyckoff/config.py          # 规则/图像/融合引擎配置
src/wyckoff/models.py          # 数据模型：阶段/置信度/量能等级/结构/信号/交易计划
src/wyckoff/analyzer.py        # 核心分析器：多时间框架 BC/SC 扫描、结构识别
src/wyckoff/engine.py          # 威科夫引擎：协调分析器、图像引擎、融合引擎的顶层入口
src/wyckoff/data_engine.py     # 数据规则引擎：Step 0~5 完整规则链实现
src/wyckoff/rules.py           # V3Rules：10 条独立规则验证器
src/wyckoff/fusion_engine.py   # 融合引擎：数据+图像的冲突检测与最终决策
src/wyckoff/image_engine.py    # 图像引擎：K 线图视觉分析
src/wyckoff/reporting.py       # 报告生成
src/wyckoff/state.py           # 状态管理
```

### 1.3 投资回测模块结构

```
src/investment/config.py               # 信号与回测配置 dataclass
src/investment/signal_models.py         # 信号映射：单窗口/Ensemble/多因子自适应
src/investment/backtest.py              # [生产入口] 回测引擎
src/investment/backtest_engine.py       # [已弃用] 旧版回测引擎
src/investment/factor_combination.py    # 因子组合引擎：三层过滤 + 49,866 样本实证数据
src/investment/indicators.py            # 技术指标计算
src/investment/tuning.py                # 参数调优
src/investment/optimized_strategy.py    # 优化策略
```

### 1.4 基础设施模块

```
src/data/manager.py    # DataManager：TDX + akshare + parquet 三级数据管道
src/data/tdx_loader.py # 通达信 .day 文件统一加载器
src/data/tdx_reader.py # TDX 读取封装
src/parallel.py        # 并行计算工具：worker 池、内存安全阀
src/computation.py     # LPPLComputation：多指数批处理扫描 + 报告生成
src/constants.py       # 全局常量：指数列表、窗口配置、目录配置
src/exceptions.py      # 异常层次：LPPLException 及其子类
```

---

## 二、优势与亮点

### 2.1 LPPL 建模功底扎实

- **Numba JIT 加速**：`_lppl_func_numba` / `_cost_function_numba` 提供高效数值运算（`src/lppl_core.py:74-95`、`src/lppl_engine.py:111-167`），且带纯 Python 回退，确保无 Numba 环境下仍可运行。
- **双优化器路径**：`differential_evolution` 全局优化（`src/lppl_core.py:209-213`）避免局部最优陷阱；`L-BFGS-B` 快速逼近（`src/lppl_engine.py:282-384`）适用于扫描场景。

### 2.2 三层多时间框架设计合理

- `src/lppl_multifit.py` 的三层窗口配置基于实证分析：
  - short [40,60,80]：m 范围 0.10-0.25，捕捉短期泡沫
  - medium [80,120,180]：m 范围 0.15-0.90，捕捉主趋势
  - long [180,240,360]：m 范围 0.15-0.60，捕捉大周期
- **Ensemble 集成**（`src/lppl_engine.py:815-894`）通过跨窗口共识度过滤假信号，含崩溃时间聚类分析和正/负泡沫分离，是专业级的做法。

### 2.3 市场状态感知

- `MarketRegimeDetector`（`src/lppl_regime.py:62-133`）基于 60/120/250 日均线排列和年化波动率区分 5 种市场状态（强牛/弱牛/震荡/弱熊/强熊），动态调整信号权重、盈亏比乘数和仓位比例。
- `FactorCombinationEngine`（`src/investment/factor_combination.py:109-432`）基于 49,866 个样本的实证交叉分析数据做因子组合评分，是数据驱动决策的良好实践。

### 2.4 数据管道设计认真

- **三级数据获取**：TDX 本地数据（最快）→ parquet 缓存（次之）→ akshare 远程（最后回退），含自动降级。
- **增量更新**：`incremental_update_data` 支持仅拉取缺失交易日的数据，节省带宽和 API 配额。
- **完备的 DataFrame 验证**：`validate_dataframe` 检查列完整性、空值、价格正性、high<low 比例、日期格式等 9 项指标。
- **TDX 解析正确性**：`tdx_loader.py` 正确解析 `volume`（uint32, 字节 24-28）和 `amount`（float, 字节 20-23），价格乘数统一为 100.0，这个细节在同类项目中常被忽视。

### 2.5 Wyckoff 规则引擎专业化

- **严格规则链**：`DataEngine.run()` 强制按 Step 0（BC 扫描）→ Step 1（阶段识别）→ Step 2（努力结果）→ Step 3（Phase C 测试）→ Step 3.5（反事实）→ Step 4（风险评估）→ Step 5（交易计划）顺序执行。
- **V3Rules 的 10 条独立规则**（`src/wyckoff/rules.py`）涵盖量能分类（Rule 1）、阶段禁止做多（Rule 2）、T+1 极限回撤测试含涨跌停流动性警告（Rule 3）、矛盾信号强制空仓（Rule 4）、BC/TR 降级（Rule 5）、Spring 验证（Rule 6）等。
- **多模态融合**：`FusionEngine` 将图像视觉分析结论（趋势、阶段、异常形态）与数据规则引擎结果融合，含冲突矩阵检测和自动降级机制。

### 2.6 异常类层次清晰

```
LPPLException
├── DataValidationError
├── DataFetchError
├── DataNotFoundError
├── ComputationError
├── ConfigurationError
└── WyckoffError
    ├── BCNotFoundError
    ├── InvalidInputDataError
    ├── ImageProcessingError
    ├── FusionConflictError
    └── RuleEngineError
```

细分类别有利于精准异常捕获和上层逻辑分支。

---

## 三、关键缺陷与风险

### CRITICAL (P0)

#### 问题 1：重复代码严重（DRY 违背）

**位置**：`src/lppl_core.py` vs `src/lppl_engine.py`

**描述**：
`lppl_func`、`_lppl_func_numba`、`_cost_function_numba`、`cost_function` 四个函数在两个文件中各有一份近乎相同的实现。文件中已自认：

> "NOTE: 与 src.lppl_core.xxx 为重复实现。等价性已通过测试验证。后续收敛时此函数应改为对 lppl_core.xxx 的委托调用。"

但至今未收敛。涉及约 **300 行完全重复的数值核心代码**，一处修改必须手动同步另一处。

**风险**：数值核心不一致 → 不同路径调用得到不同拟合结果 → 信号矛盾

**修复方案**：
- `lppl_engine.py` 中的四个函数改为直接委托 `lppl_core` 对应函数
- 保留 `lppl_engine.py` 中的函数签名作为向后兼容的转发层
- 单测验证转发前后数值等价

```python
# lppl_engine.py 修复示例
def lppl_func(t, tc, m, w, a, b, c, phi):
    return lppl_core.lppl_func(t, tc, m, w, a, b, c, phi)
```

---

#### 问题 2：优化器风险控制不足

**位置**：`src/lppl_core.py:209-213`、`src/lppl_engine.py:235-244`

**描述**：
`fit_single_window` 使用 `scipy.optimize.differential_evolution`：

```python
result = differential_evolution(
    cost_function, bounds,
    args=(t_data, log_price_data),
    strategy='best1bin',
    maxiter=100, popsize=15, tol=0.05,
    seed=42, workers=1  # 强制单线程！
)
```

问题：
- `maxiter=100, popsize=15` = 最多 1,500 次目标函数评估，无超时保护
- `workers=1` 强制单线程，无视全局 `n_workers` 配置
- 无迭代收敛早期停止机制
- 指数级窗口扫描：8 个指数 × 7 个窗口 × 数百历史日 = 数万优化问题，单次卡死阻塞全流程

**风险**：生产环境 OOM / 死锁 / 扫描耗时过长

**修复方案**：
- 添加 `timeout` 参数包裹 `differential_evolution`
- 使用 `workers` 代替 `workers=1`
- 实现收敛早期停止（patience 参数）
- 注入可中断的 `callback` 函数

```python
import signal

class TimeoutError(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutError("Optimization timed out")

def fit_single_window_with_timeout(..., timeout_seconds=30):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_seconds)
    try:
        result = differential_evolution(..., workers=config.n_workers)
        signal.alarm(0)
        ...
    except TimeoutError:
        return None
```

---

#### 问题 3：并行资源管理存在生产事故风险

**位置**：`src/computation.py:49-52`、`src/lppl_engine.py:73-75`、`src/parallel.py:23-38`

**描述**：
三个模块各自实现 worker 数量计算逻辑，策略互不一致：

| 模块 | 策略 | 上限 |
|------|------|------|
| `computation.py:49-52` | `max(1, min(4, cpu_count-2))` | 硬编码 **max=4** |
| `lppl_engine.py:73-75` | `max(1, (os.cpu_count() or 4) - 2)` | **无上限** |
| `parallel.py:23-26` | `max(1, cpu_count - 2)` | **无上限** |

在 64 核机器上，`lppl_engine.py` 和 `parallel.py` 会启动 62 个 worker，乘以每个 worker 的内存开销（`parallel.py:29` 假设 200MB/worker）→ 12.4GB 峰值内存。

此外，`computation.py:48-69` 的全局 `GLOBAL_EXECUTOR` 进程池缺少自动回收和优雅关闭机制。

**风险**：高核环境 OOM 崩溃；进程池泄漏

**修复方案**：
- 统一 worker 计算逻辑到一个共享函数 `get_optimal_workers(max_workers=8)`
- 设置合理的默认上限（建议 8-16）
- `GLOBAL_EXECUTOR` 改为 contextmanager 模式，确保使用后自动 shutdown

```python
# parallel.py — 统一入口
def get_optimal_workers(reserve=2, max_workers=8):
    cpu_workers = max(1, (os.cpu_count() or 4) - reserve)
    return min(cpu_workers, max_workers)

@contextmanager
def global_executor(max_workers=None):
    workers = max_workers or get_optimal_workers()
    executor = ProcessPoolExecutor(max_workers=workers)
    try:
        yield executor
    finally:
        executor.shutdown(wait=True)
```

---

### HIGH (P1)

#### 问题 4：输入校验不一致

**位置**：`src/lppl_core.py:46-56` vs `src/data/manager.py:63-95`

**描述**：
`precheck_fit_input` 只检查 close 数组的五个条件（长度、正性、有限性、常数性），而 `validate_dataframe` 检查完整 DataFrame 的九项指标。同一数据流经不同入口时校验粒度不同：

```
DataManager.get_data() → validate_dataframe（完整校验）
LPPLComputation.run_computation() → validate_input_data → fit_single_window_task → precheck_fit_input（轻量校验）
```

部分路径（如直接调用 `scan_date_range`）完全跳过 DataFrame 级校验。

**风险**：畸形数据从旁路进入拟合流程

**修复方案**：
- 统一到一个校验函数，前置完整校验
- 拟合层只断言（`assert`），不重复校验

```python
def validate_and_prepare(df, symbol):
    """统一入口：校验 + 标准化"""
    is_valid, msg = validate_dataframe(df, symbol)
    if not is_valid:
        raise DataValidationError(f"{symbol}: {msg}")
    return df["close"].values.astype(np.float64)
```

---

#### 问题 5：风险等级判定系统混乱

**位置**：
- `src/lppl_core.py:241-252` — `calculate_risk_level`
- `src/lppl_engine.py:391-425` — `calculate_risk_level`
- `src/lppl_multifit.py:72-81` — `_classify_phase`

**描述**：
三个独立实现的风险判定函数，逻辑相似但阈值和输出不同：

| 函数 | danger 阈值 | 输出格式 |
|------|-----------|---------|
| `lppl_core.calculate_risk_level` | days<5 → 极高危 | 中文字符串 |
| `lppl_engine.calculate_risk_level` | 依赖 config.danger_days | 英文/中文混合 |
| `lppl_multifit._classify_phase` | 依赖 config.danger_days | 英文 phase 名称 |

上层调用方（如 `computation.py:116`）调用 `lppl_engine.calculate_risk_level`，而 `signal_models.py` 直接检查 `days_to_crash < config.danger_days`，不使用风险函数。

**风险**：同一组 (m, w, days_left) 在不同路径得到不同的风险结论

**修复方案**：
- 保留一个权威实现（建议在 `lppl_engine.py`），另两处改为委托调用
- 输出统一为 `RiskLevel` 枚举：`SAFE / WATCH / WARNING / DANGER / INVALID`

---

#### 问题 6：参数边界配置分散

**位置**：`src/lppl_core.py:199-207`、`src/lppl_engine.py:51-56`、`src/lppl_multifit.py:35-68`、`src/lppl_regime.py:18-24`

**描述**：
LPPL 模型关键参数 m 和 w 的边界在多个文件中独立硬编码：

| 位置 | m_bounds | w_bounds |
|------|---------|---------|
| `lppl_core.py`（DE 优化） | (0.1, 0.9) | (6, 13) |
| `lppl_engine.py`（默认配置） | (0.1, 0.9) | (6, 13) |
| `lppl_multifit.py` short | (0.10, 0.25) | (6.0, 13.0) |
| `lppl_multifit.py` medium | (0.15, 0.90) | (6.0, 12.0) |
| `lppl_multifit.py` long | (0.15, 0.60) | (7.0, 12.5) |

相似地，`danger_days / warning_days / watch_days` 也在 `InvestmentSignalConfig`（`src/investment/config.py:31-33`）和 `LPPLConfig`（`src/lppl_engine.py:58-61`）中重复定义。

**风险**：修改一处忘记同步另一处 → 不同扫描路径产量化结果不一致

**修复方案**：
- 将 `ParameterBounds` 和 `RiskThresholds` 定义为全局配置 dataclass
- 集中管理，各模块引用统一实例

---

#### 问题 7：全局可变状态隐患

**位置**：`src/lppl_engine.py:898`、`src/computation.py:45-69`

**描述**：
```python
# lppl_engine.py:898 — 模块级可变对象
config = DEFAULT_CONFIG

# computation.py:45-48 — 全局进程池
GLOBAL_EXECUTOR = None
_executor_lock = multiprocessing.Lock()
```

多线程/多进程环境下：
- 模块级 `config` 被意外修改会影响同一进程内所有调用方
- `GLOBAL_EXECUTOR` 的锁定机制在 fork 模式下可能失效

**风险**：竞态条件导致的不可预测行为

**修复方案**：
- 模块级配置改为 read-only 或使用 `copy.deepcopy`
- `GLOBAL_EXECUTOR` 替换为 `@contextmanager`

---

### MEDIUM (P2)

#### 问题 8：后处理中的"崩盘日期"误导

**位置**：`src/computation.py:114`

```python
crash_date = last_date + timedelta(days=int(days_left))
```

**描述**：LPPL 的 $t_c$（临界时间）是对数时间坐标上的理论奇点，代表模型发散的时刻，并非精确的日期预测。将其直接计算为日历日期并展示给终端用户，可能造成以下误导：
- 用户理解为精确预测 → 产生 false confidence
- $t_c$ 的置信区间往往很宽，单点估计无意义
- 即使参数有效，$t_c$ 也可能落在过去（`days_left < 0` 被截断为 0，`computation.py:107-108`）

**修复方案**：
- 报告中使用 "预估崩盘时间窗口（±X 天）" 代替单点日期
- 基于 Ensemble 的 tc_std 给出置信区间

---

#### 问题 9：回测引擎滑点模型过于简单

**位置**：`src/investment/backtest.py:304-305`（从 `backtest_engine.py:225-226` 继承）

```python
execution_buy_price = execution_base_price * (1.0 + backtest_config.slippage)
execution_sell_price = execution_base_price * (1.0 - backtest_config.slippage)
```

**描述**：滑点固定为 0.05%，缺乏以下因素：
- 基于 ATR（平均真实波幅）的动态滑点
- 基于成交量的市场冲击成本模型
- 大单交易的流动性折价

对于日频回测此简化尚可接受，但对信号驱动的策略，固定滑点会低估高波动日的交易成本。

**修复方案**：
- 提供可插拔的 `SlippageModel` 接口
- 实现 ATR-based 和 Volume-based 滑点模型作为默认选项

```python
class AtrSlippageModel:
    def __init__(self, base_slippage=0.0003, atr_multiplier=0.1):
        self.base = base_slippage
        self.atr_mult = atr_multiplier
    
    def compute(self, price, atr):
        return self.base + self.atr_mult * (atr / price)
```

---

#### 问题 10：威科夫置信度对齐逻辑脆弱

**位置**：`src/wyckoff/analyzer.py:133-145`

```python
conf_map = {
    "A": ConfidenceLevel.A,
    "B": ConfidenceLevel.B,
    "C": ConfidenceLevel.C,
    "D": ConfidenceLevel.D,
}
if analysis_result.confidence in conf_map:
    report.trading_plan.confidence = conf_map[analysis_result.confidence]
```

**描述**：
- 使用硬编码字符串映射字典，如果融合引擎输出新值（如 "A+"），静默失败
- 只输出 `logger.warning`，不阻断流程也不设置合理的默认值
- `factor_combination.py:162-168` 的 `CONFIDENCE_WEIGHTS` 将 `Confidence.A` 权重设为 `0.0`，这看似是一个 bug（A 是最高置信度，不应该权重为 0）

**风险**：置信度丢失或被错误解释

**修复方案**：
- 使用 `try/except` 捕获未知值并降级到 `ConfidenceLevel.D`
- 修复 `CONFIDENCE_WEIGHTS` 中 Confidence.A 的权重

---

#### 问题 11：FactorCombinationEngine v1/v2 逻辑冲突

**位置**：`src/investment/factor_combination.py`

**描述**：
- `evaluate_v2` 的文档说明 "不排除 range 制度（占 35% 交易日）"，但 `_check_exclusion`（v1 使用）将 `Regime.RANGE` 完全排除
- `evaluate_v2` 对 bear+markdown 给出 0.70 做多仓位，v1 同样的组合在 `COMBO_LOOKUP` 中预期收益为正但方向判定取决于 `_determine_direction`
- `scan_all` 默认使用 v1，但不是所有调用方清楚自己在用哪个版本

**风险**：调用方无意识地在 v1 和 v2 之间切换，得到不同的仓位建议

**修复方案**：
- 标记 v1 为 @deprecated
- v2 作为唯一生产路径
- 添加调用方日志，记录使用哪个版本

---

### LOW (P3)

#### 问题 12：Deprecated 文件未清理

**位置**：`src/lppl_fit.py`、`src/investment/backtest_engine.py`

**描述**：
两个文件明确标记为 deprecated（`lppl_fit.py:6`：已弃用；`backtest_engine.py:4-7`：DEPRECATED），但仍然被某些模块引用。`backtest_engine.py` 甚至使用 `warnings.warn` 发出 DeprecationWarning，说明未被移除的原因仅是"保留参考"。

**影响**：开发者不确定该用哪个入口，测试覆盖也需要兼顾两个实现。

**修复方案**：
- 删除两个 deprecated 文件
- 将所有引用改为新路径
- 如果确实需要参考，移入 `docs/archive/` 目录

---

#### 问题 13：空 except 与静默失败

**位置**：多处

```
src/lppl_engine.py:138, 181, 279, 351, 384    # except Exception: pass
src/computation.py:193, 218                      # else: pass
src/lppl_fit.py:102                              # except Exception: continue
```

**描述**：
大量空 `except` / 空 `pass` 让异常完全透明。虽然某些是底层数值运算异常（预期会发生的），但没有日志记录意味着调试时无法区分"正常失败"和"异常失败"。

**修复方案**：
- 记录异常到 `logger.debug()` 至少一行
- 区分预期的数值异常（catch `FloatingPointError`）和非预期的编程错误（let it crash）

---

#### 问题 14：Backtest.__init__ 的困惑性导入

**位置**：`src/investment/__init__.py:15-31`

```python
from .backtest import BacktestConfig, InvestmentSignalConfig  # from backtest.py
from .config import BacktestConfig as BacktestConfigBase      # from config.py
from .config import InvestmentSignalConfig as InvestmentSignalConfigBase
```

**描述**：
`BacktestConfig` 和 `InvestmentSignalConfig` 同时从 `backtest.py` 和 `config.py` 导出，名称仅通过 `Base` 后缀区分。用户导入 `from src.investment import BacktestConfig` 得到的是 `backtest.py` 中的类，但 IDE 和静态分析工具可能指向 `config.py`。

**影响**：开发体验差，容易导入错误的配置类。

**修复方案**：
- `config.py` 只保留纯配置，不从 `backtest.py` 重导出
- `backtest.py` 不定义配置类，直接从 `config.py` 导入

---

#### 问题 15：未使用的导入

**位置**：`src/lppl_fit.py:9-11`、`src/wyckoff/analyzer.py:7-32`

**描述**：
- `lppl_fit.py` 导入 `numpy`、`numba`、`scipy.optimize` 但整个文件已弃用
- `analyzer.py` 的 import 列表从 `models.py` 导入了 20+ 个符号，部分可能未被使用

**影响**：轻微。增加启动时间，降低代码可读性。

---

## 四、改进优先级矩阵

| ID | 问题 | 影响范围 | 技术难度 | 优先级 |
|----|------|---------|---------|--------|
| 1 | LPPL 核心重复代码 | 全系统 | 低 | **P0** |
| 2 | 优化器风险控制不足 | 全系统 | 中 | **P0** |
| 3 | 并行资源管理风险 | 全系统 | 中 | **P0** |
| 4 | 输入校验不一致 | 数据管道 | 低 | P1 |
| 5 | 风险等级系统混乱 | LPPL+回测 | 低 | P1 |
| 6 | 参数边界分散 | LPPL 全模块 | 低 | P1 |
| 7 | 全局可变状态隐患 | 多线程场景 | 中 | P1 |
| 8 | 崩盘日期误导 | 报告输出 | 低 | P2 |
| 9 | 滑点模型过于简单 | 回测精度 | 低 | P2 |
| 10 | 威科夫置信度对齐脆弱 | Wyckoff | 低 | P2 |
| 11 | 因子组合引擎 v1/v2 冲突 | 投资决策 | 中 | P2 |
| 12 | Deprecated 文件 | 代码维护 | 低 | P3 |
| 13 | 空 except 与静默失败 | 可调试性 | 低 | P3 |
| 14 | 导入困惑 | 开发体验 | 低 | P3 |
| 15 | 未使用的导入 | 代码整洁 | 低 | P3 |

## 五、总体评价

### 架构评分：7/10

- **优点**：设计思想清晰，三层 LPPL + Wyckoff 多模态 + 投资回测的层次划分合理；市场状态感知和因子组合评分是亮点。
- **扣分项**：DRY 问题严重（~300 行重复的 LPPL 数值核心），配置散落在 5+ 个文件中，v1/v2 逻辑共存未清理。

### 代码质量评分：6.5/10

- **优点**：Numba 加速、DE 全局优化、Ensemble 共识等专业工具选择正确；数据校验完备；异常层次清晰。
- **扣分项**：空 except 泛滥、全局可变状态、deprecated 文件残留、缺乏统一的并行策略。

### 生产就绪度：5.5/10

**不建议在未解决 P0 问题前投入实盘交易**。主要障碍：
1. 重复的数值核心可能产生不一致的拟合结果
2. 无超时保护的优化器可能在极端行情数据上卡死
3. 并行策略不统一，高核环境有 OOM 风险

### 最有价值的部分

1. **三层多窗口 LPPL + Ensemble 共识设计** — 量化泡沫检测的核心竞争力
2. **MarketRegimeDetector + FactorCombinationEngine** — 市场状态感知和因子组合评分，数据驱动决策
3. **TDX + akshare + parquet 三级数据管道** — 数据获取的稳健性行业领先
4. **Wyckoff 规则引擎 Step 0~5** — 严谨的交易流程设计，含 T+1 风控

### 核心改进路线图

```
Phase 1 (立即)                      Phase 2 (1-2周)                  Phase 3 (1月)
┌─────────────────────┐    ┌─────────────────────────┐    ┌──────────────────────┐
│ ✓ 消除 LPPL 重复代码 │    │ ✓ 统一风险等级判定系统     │    │ ✓ 动态滑点模型        │
│ ✓ 优化器加超时保护    │    │ ✓ 参数边界集中配置        │    │ ✓ v1/v2 因子引擎清理   │
│ ✓ 统一并行策略+上限   │    │ ✓ 修复置信度对齐脆弱性     │    │ ✓ 报告输出增加置信区间  │
│ ✓ 修复全局可变状态    │    │ ✓ 清理 deprecated 文件   │    │ ✓ 全模块代码风格统一    │
└─────────────────────┘    └─────────────────────────┘    └──────────────────────┘
  影响：消除生产事故风险         影响：消除信号矛盾             影响：提升策略质量
```

---

*本评估基于 main branch (commit 2d1c616) 的 src/ 目录源代码，2026-05-12 完成。*