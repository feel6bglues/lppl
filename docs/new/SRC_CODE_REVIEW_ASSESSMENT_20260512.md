# src 代码完整审查评估报告

生成日期：2026-05-12  
审查范围：`src/` 全部 Python 源码，重点覆盖 LPPL 引擎、Wyckoff 引擎、投资信号/回测、数据读取、报告和 CLI。

## 1. 结论摘要

当前项目已经具备较完整的量化研究系统形态：包含本地/远程数据读取、LPPL 泡沫拟合、Wyckoff 结构分析、多周期融合、投资信号生成、回测、调参、报告输出和 CLI 工作流。代码量约 2.1 万行，模块边界基本成型，测试目录也覆盖了 unit 和 integration 两类用例。

但从顶级量化工程标准看，当前仍不适合直接作为稳定实盘或半实盘决策引擎。主要瓶颈不是功能缺失，而是：

- 核心算法入口存在重复实现和行为分叉。
- 风险评级和交易计划中有配置未贯通、风控输入遗漏的问题。
- 测试当前无法完整收集运行。
- 数据标准化和股票代码解析存在会影响实际标的读取的边界错误。
- 异常处理偏向静默失败，量化结果可解释性和可审计性不足。

综合评价：**6/10**。适合作为研究型原型和离线验证系统；若要进入稳定生产级研究流水线，需要先完成入口收敛、测试修复、风控口径统一和数据边界加固。

## 2. 审查方法

本次审查采用只读方式，未修改源代码。执行过以下验证：

```bash
python3 -m compileall -q src
.venv/bin/python -m ruff check src
.venv/bin/python -m pytest tests/unit -q
```

验证结果：

- `python3 -m compileall -q src`：通过，源码语法层面可编译。
- `.venv/bin/python -m ruff check src`：失败，发现 48 个 lint 问题，主要是导入排序、未使用导入/变量、可读性问题。
- `.venv/bin/python -m pytest tests/unit -q`：失败，测试收集阶段报错，`tests/unit/test_computation_compat.py` 期望 `src.computation._fit_single_window_compat`，但当前模块不存在该符号。

## 3. 模块结构概览

`src/` 主要由以下模块组成：

- `lppl_engine.py`、`lppl_core.py`、`lppl_fit.py`、`lppl_multifit.py`、`lppl_cluster.py`、`lppl_regime.py`：LPPL 拟合、风险分类、多窗口集成和行情状态检测。
- `wyckoff/`：Wyckoff 结构分析、规则引擎、图像证据、融合、状态管理和报告。
- `investment/`：信号映射、指标计算、策略回测、参数调优和组合因子。
- `data/`：本地 TDX 数据读取、AkShare 拉取、parquet 缓存和数据校验。
- `verification/`：walk-forward 验证。
- `reporting/`：Markdown、HTML、图表和验证报告。
- `cli/`：各类命令行入口。

整体设计方向是合理的，但多个历史版本仍并存，导致“唯一可信入口”不清晰。

## 4. 高优先级问题

### 4.1 单元测试当前无法完整运行

文件：`src/computation.py`

问题：`tests/unit/test_computation_compat.py` 从 `src.computation` 导入 `_fit_single_window_compat`，但当前 `src/computation.py` 没有该函数，导致测试在收集阶段中断。

影响：

- CI 或本地回归无法完整执行。
- 后续任何功能修改都缺少可靠防线。
- 该问题通常意味着重构过程中遗留了测试/实现不一致。

建议：

1. 判断 `_fit_single_window_compat` 是应恢复的兼容层，还是测试已过时。
2. 若 `LPPLComputation` 仍需兼容旧任务元组，应恢复该函数并让 `process_index_multiprocess()` 使用同一个适配路径。
3. 修复后先跑 `tests/unit/test_computation_compat.py`，再跑全量 unit。

### 4.2 LPPL 风险评级使用全局配置，调参结果无法贯通

文件：`src/lppl_engine.py`

问题：`calculate_risk_level(m, w, days_left, r2=1.0)` 内部使用模块级全局 `config`，而不是调用方传入的 `LPPLConfig`。这会导致实际扫描或调优中传入的 `danger_days`、`warning_days`、`watch_days`、`r2_threshold` 无法影响风险评级。

影响：

- 调参报告和交易信号可能使用一套阈值，风险标签却使用另一套默认阈值。
- 回测和实盘信号解释不一致。
- 对“危险/观察/安全”的判断不可追溯。

建议：

- 将函数签名改为 `calculate_risk_level(..., config: LPPLConfig | None = None)`。
- 默认使用 `DEFAULT_CONFIG`，调用方显式传入当前配置。
- 为不同 `danger_days`、`warning_days`、`watch_days` 增加回归测试。

### 4.3 Wyckoff 交易计划遗漏涨跌停/炸板风控输入

文件：`src/wyckoff/engine.py`

问题：`_step5_trading_plan()` 中调用 `self._detect_limit_moves(pd.DataFrame())`，实际传入空 DataFrame。注释中也写明“需要传入df”。

影响：

- 涨跌停、炸板、撬板等 A 股流动性风险不会进入止损规则。
- T+1 风控可能低估尾部风险。
- 对短线交易计划尤其危险，因为止损可执行性没有被真实评估。

建议：

- 将 `df` 传入 `_step5_trading_plan()`。
- 使用真实最近 K 线计算 `limit_moves_data`。
- 增加“近期涨停炸板导致止损警告”的测试用例。

### 4.4 投资回测存在两套实现，口径分叉

文件：

- `src/investment/backtest.py`
- `src/investment/backtest_engine.py`
- `src/investment/config.py`
- `src/investment/indicators.py`
- `src/investment/signal_models.py`

问题：`backtest.py` 是较大的历史一体化实现，支持更多信号模型和绩效指标；`backtest_engine.py` 是较新模块化实现，但功能和指标更少。两者同时存在，且函数名高度重叠。

影响：

- 不同 CLI 或测试可能走不同实现。
- 同一策略在不同入口下可能输出不同指标。
- 后续调参结果难以确认使用的是哪套回测口径。

建议：

1. 明确唯一生产入口，建议保留模块化版本作为主入口。
2. 将 `backtest.py` 中仍需要的指标，如 `annualized_benchmark`、`annualized_excess_return`、`calmar_ratio`、`turnover_rate`、`whipsaw_rate`，迁移到模块化实现。
3. 将旧文件降级为兼容 re-export 或删除，避免双实现长期并存。

### 4.5 股票代码标准化对深市纯数字代码处理错误

文件：`src/data/manager.py`

问题：`normalize_symbol()` 对所有纯 6 位代码默认补 `.SH`。例如 `002216` 会被解析为 `002216.SH`，而实际应为 `002216.SZ`。

影响：

- 深市个股读取路径错误。
- TDX 本地数据无法命中正确文件。
- 批量分析时可能出现“无数据”或错误市场数据。

建议：

- 按 A 股代码规则推断交易所：
  - `000/001/002/003/300/301` 等常见深市前缀默认 `.SZ`。
  - `600/601/603/605/688/689` 等默认 `.SH`。
  - 指数代码按既有 `INDICES` 映射优先。
- 对 `002216`、`300442`、`600859`、`603637` 增加测试。

## 5. 中优先级问题

### 5.1 LPPL 拟合异常静默吞掉

文件：

- `src/lppl_engine.py`
- `src/lppl_core.py`
- `src/lppl_fit.py`

问题：多处 `except Exception: return None` 或 `except Exception: pass`。拟合失败、数值溢出、数据非法、优化器失败都被统一折叠为“无信号”。

影响：

- 研究阶段难以区分“模型确实无信号”和“数据/优化器失败”。
- 批量扫描时失败率无法监控。
- 参数调优可能把工程失败误判成策略表现差。

建议：

- 定义结构化失败原因，例如 `FitFailureReason`。
- 在批量扫描结果中记录 `failure_reason`、`window_size`、`date`。
- 对非正价格、NaN、inf、常数价格序列做显式前置校验。

### 5.2 LPPL 核心实现重复

文件：

- `src/lppl_engine.py`
- `src/lppl_core.py`
- `src/lppl_fit.py`

问题：LPPL 函数、cost function、单窗口拟合逻辑在多个文件中重复实现。不同文件对边界、异常处理、返回字段和风险判断的口径不同。

影响：

- 模型维护成本高。
- 修复数值问题时容易漏改。
- 不同调用路径输出不可比。

建议：

- 统一 `lppl_core.py` 为底层数值核心。
- `lppl_engine.py` 只保留策略级扫描、集成和风险解释。
- `lppl_fit.py` 若无独立用途，应合并或标记 deprecated。

### 5.3 Wyckoff 存在多代引擎并存

文件：

- `src/wyckoff/engine.py`
- `src/wyckoff/analyzer.py`
- `src/wyckoff/data_engine.py`

问题：`engine.py` 标注为 v3.0 唯一入口，但 `analyzer.py` 和 `data_engine.py` 仍保留大量完整逻辑，CLI 和测试仍可能直接使用旧入口。

影响：

- 规则口径不唯一。
- 修复 v3 引擎后，旧入口仍可能输出不同结论。
- 用户难以判断报告来自哪一代规则。

建议：

- 明确 `WyckoffEngine` 为唯一分析入口。
- `WyckoffAnalyzer` 和 `DataEngine` 若仍需兼容，应作为 wrapper 调用 `WyckoffEngine`，不要保留独立判断逻辑。
- 在报告中输出 `engine_version` 和 `ruleset_version`。

### 5.4 回测缺少更严格的成交约束

文件：

- `src/investment/backtest.py`
- `src/investment/backtest_engine.py`

问题：当前回测按 open/close 加滑点成交，但没有处理涨跌停不可成交、停牌、成交量容量、价格跳空穿越止损等约束。

影响：

- A 股策略收益可能被高估。
- 高换手策略或小盘股回测偏差更明显。
- T+1 风险在 Wyckoff 分析中提到，但回测执行层没有完全体现。

建议：

- 引入成交可行性检查：涨跌停、停牌、成交额容量、最大参与率。
- 交易成本按标的类型和交易方向细分。
- 对开盘一字板、跳空低开止损失败等情况进行压力测试。

## 6. 低优先级问题

### 6.1 Ruff 风格问题较多

当前 Ruff 发现 48 个问题，多数可自动修复：

- 导入未排序。
- 未使用导入。
- 未使用变量。
- `tdx_loader.py` 中变量名 `l` 可读性差。

这些不是核心算法错误，但会降低代码审查效率。建议先修复测试失败，再运行：

```bash
.venv/bin/python -m ruff check src --fix
```

对 `--unsafe-fixes` 应谨慎使用，先看 diff。

### 6.2 CLI 和库代码输出方式混杂

部分核心路径中仍存在 `print()`，与 logging 混用。建议：

- 库代码只使用 logger。
- CLI 层负责用户可见输出。
- 批量扫描进度可抽象为 progress callback。

### 6.3 类型约束不足

当前大量函数返回 `Dict[str, Any]`，对量化系统不利。建议对关键结果建模：

- LPPL fit result
- LPPL scan result
- investment signal row
- backtest summary
- Wyckoff risk result

可以先用 `dataclass`，后续再考虑 Pydantic。

## 7. 正向评价

项目已有不少值得保留的工程基础：

- 数据校验层存在，能检查空数据、缺列、负成交量、非正价格、日期格式等。
- LPPL 引擎支持 DE 和 L-BFGS-B，并有多窗口 ensemble 思路。
- Wyckoff v3 引擎有较完整的 Step 0 到 Step 5 规则链。
- 报告输出体系较完整，支持 Markdown、HTML、图表和原始 JSON。
- 测试目录结构较好，unit/integration 分层明确。
- CLI 覆盖了验证、walk-forward、调参、投资分析、Wyckoff 多模态分析等关键流程。

这些说明项目不是零散脚本，而是已经进入“系统化研究平台”的阶段。

## 8. 推荐整改路线

### 第一阶段：恢复基本可信度

目标：让测试能完整运行，核心入口不再明显断裂。

1. 修复 `_fit_single_window_compat` 缺失或同步删除过时测试。
2. 修复 `calculate_risk_level()` 使用全局配置的问题。
3. 修复 Wyckoff `_step5_trading_plan()` 空 DataFrame 风控输入。
4. 修复 `normalize_symbol()` 对深市股票的默认交易所判断。
5. 跑通 `.venv/bin/python -m pytest tests/unit -q`。

### 第二阶段：统一核心口径

目标：消除重复实现造成的研究结果分叉。

1. 确定 LPPL 唯一数值核心。
2. 确定 investment backtest 唯一入口。
3. 确定 Wyckoff 唯一分析入口。
4. 将旧实现改为 wrapper 或 deprecated shim。
5. 把报告和 CLI 全部指向唯一入口。

### 第三阶段：提升量化严谨性

目标：让结果具备更强的可解释性和可审计性。

1. 为 LPPL 拟合失败记录结构化原因。
2. 加入 walk-forward、分市场状态、分波动环境的稳定性报告。
3. 回测加入涨跌停、停牌、容量、T+1、滑点压力测试。
4. 报告中输出配置快照和模型版本。
5. 建立固定基准数据集，防止算法改动导致信号漂移而无人发现。

## 9. 建议新增测试

建议优先补充以下测试：

- `normalize_symbol("002216") == "002216.SZ"`
- `normalize_symbol("300442") == "300442.SZ"`
- `normalize_symbol("600859") == "600859.SH"`
- LPPL 不同 `danger_days` 配置下风险评级不同。
- LPPL 非正价格输入返回明确失败原因。
- Wyckoff 近期炸板/跌停场景进入止损流动性警告。
- `backtest.py` 和最终保留的回测入口在同一信号输入下输出一致或明确差异。
- CLI 入口使用唯一回测实现。

## 10. 最终判断

该项目已经从脚本集合演化为较完整的量化研究系统，但还处于“多版本并存、口径待收敛”的阶段。最关键的改进不是继续增加因子或新模型，而是先把现有算法结果变得稳定、可测试、可复现、可解释。

如果按上述路线整改，项目可以较快提升到 **7.5/10**；若再补齐真实交易约束、失败原因审计、版本化报告和稳定性验证，可接近生产级研究平台标准。
