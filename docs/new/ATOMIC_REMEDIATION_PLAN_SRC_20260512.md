# src 原子化修复计划

生成日期：2026-05-12  
依据文档：`docs/new/SRC_CODE_REVIEW_ASSESSMENT_20260512.md`  
目标：将审查报告中的风险拆解为可独立实施、可独立验证、可独立提交的修复任务。

## 1. 执行原则

每个修复任务必须满足以下要求：

- 原子化：单个任务只解决一个明确问题，不混入顺手重构。
- 测试先行：能写测试的修复先补失败测试，再实现。
- 行为可验证：每个任务都有明确命令或断言作为验收标准。
- 入口收敛：涉及重复实现时，先建立兼容层，再逐步迁移，不一次性大拆。
- 不破坏历史输出：报告字段、CLI 参数、已有测试约定需要兼容，除非明确标记迁移。

推荐分支/提交粒度：每个任务一个 commit。高风险任务可拆为“测试 commit”和“实现 commit”。

## 2. 优先级总览

### P0：恢复可信基础

这些任务阻塞测试、风控或数据正确性，应最先做。

| ID | 任务 | 主要文件 | 验收命令 |
|---|---|---|---|
| P0-01 | 恢复 `_fit_single_window_compat` 兼容函数 | `src/computation.py`, `tests/unit/test_computation_compat.py` | `.venv/bin/python -m pytest tests/unit/test_computation_compat.py -q` |
| P0-02 | 让 LPPL 风险评级使用调用方配置 | `src/lppl_engine.py`, `tests/unit/test_lppl_engine_ensemble.py` | `.venv/bin/python -m pytest tests/unit/test_lppl_engine_ensemble.py -q` |
| P0-03 | 修复 Wyckoff 交易计划空 DataFrame 风控输入 | `src/wyckoff/engine.py`, `tests/unit/test_wyckoff_analyzer.py` 或新增测试 | `.venv/bin/python -m pytest tests/unit/test_wyckoff_analyzer.py -q` |
| P0-04 | 修复纯数字股票代码交易所推断 | `src/data/manager.py`, `tests/unit/test_data_manager_statuses.py` | `.venv/bin/python -m pytest tests/unit/test_data_manager_statuses.py -q` |
| P0-05 | 跑通全量 unit 测试收集 | 多模块 | `.venv/bin/python -m pytest tests/unit -q` |

### P1：收敛核心口径

这些任务降低长期维护风险，避免不同入口输出不同结论。

| ID | 任务 | 主要文件 | 验收命令 |
|---|---|---|---|
| P1-01 | 明确 investment 回测唯一入口 | `src/investment/*`, `src/cli/index_investment_analysis.py` | `.venv/bin/python -m pytest tests/unit/test_investment_backtest.py tests/integration/test_index_investment_analysis.py -q` |
| P1-02 | 迁移完整绩效指标到模块化回测实现 | `src/investment/backtest_engine.py`, `tests/unit/test_investment_backtest.py` | `.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q` |
| P1-03 | 明确 Wyckoff v3 唯一入口并加版本字段 | `src/wyckoff/engine.py`, `src/wyckoff/models.py`, reporting/CLI | `.venv/bin/python -m pytest tests/unit/test_wyckoff_* tests/integration/test_wyckoff_*.py -q` |
| P1-04 | LPPL 数值核心入口收敛设计与第一步迁移 | `src/lppl_core.py`, `src/lppl_engine.py`, `src/lppl_fit.py` | `.venv/bin/python -m pytest tests/unit/test_lppl_engine_ensemble.py tests/unit/test_computation_compat.py -q` |

### P2：提升生产级质量

这些任务提升可观测性、真实交易约束和代码卫生。

| ID | 任务 | 主要文件 | 验收命令 |
|---|---|---|---|
| P2-01 | LPPL 拟合失败原因结构化 | `src/lppl_engine.py`, `src/lppl_core.py` | 新增失败原因测试 + LPPL 单测通过 |
| P2-02 | 回测加入涨跌停/停牌/容量约束骨架 | `src/investment/backtest_engine.py` | 新增成交约束测试通过 |
| P2-03 | 库代码输出从 `print` 收敛到 logger | `src/computation.py`, CLI | 对应 CLI 测试通过 |
| P2-04 | Ruff 自动修复安全项 | 多模块 | `.venv/bin/python -m ruff check src` |
| P2-05 | 固化全量验证脚本或 Make 目标 | `pyproject.toml` 或 scripts | 单命令完成 compile/lint/unit |

## 3. P0 原子任务详案

### P0-01 恢复 `_fit_single_window_compat` 兼容函数

问题来源：unit 测试收集失败，`tests/unit/test_computation_compat.py` 导入不存在的 `_fit_single_window_compat`。

目标：

- 恢复兼容函数，让旧任务元组 `(window_size, dates_series, prices_array)` 能适配到当前 `src.lppl_engine.fit_single_window()`。
- 保持返回字段兼容 `LPPLComputation._format_output()`：至少包含 `window`、`params`、`rmse`、`last_date`。

建议测试：

- 保留现有 `tests/unit/test_computation_compat.py`。
- 如有必要，新增一例：当 `fit_single_window()` 返回缺失 `params` 或异常时，兼容函数返回 `None`。

实现步骤：

1. 在 `src/computation.py` 导入 `fit_single_window`。
2. 新增 `_fit_single_window_compat(task)`。
3. 将 `window_size` 映射为返回字段 `window`。
4. 从 `dates_series` 取最后一个日期，统一转为 `pd.Timestamp`。
5. 若底层返回 `None`，兼容函数返回 `None`。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_computation_compat.py -q
```

完成标准：

- 测试通过。
- 不修改 LPPL 拟合算法行为。
- 不改变 `LPPLComputation.process_index_multiprocess()` 的现有执行路径，除非单独开后续任务。

### P0-02 让 LPPL 风险评级使用调用方配置

问题来源：`src/lppl_engine.py` 的 `calculate_risk_level()` 使用全局 `config`。

目标：

- 风险评级函数接收可选 `LPPLConfig`。
- 默认行为保持兼容。
- 调用方传入自定义阈值时，风险标签和 `is_danger/is_warning` 按自定义配置变化。

> **⚠️ 重要发现：风险评级存在三套重复实现**
> 核查发现当前风控阈值有三套口径并存：
> 1. `lppl_engine.calculate_risk_level` — 使用 `LPPLConfig.danger_days/warning_days/watch_days`
> 2. `lppl_core.calculate_risk_level` — 硬编码阈值（`days_left < 5 / < 20 / < 60`），无 config 参数
> 3. `backtest.py` 的 `InvestmentSignalConfig` — 定义了第三套独立的风险阈值
>
> `computation.py:16` 导入的是第 2 套（`lppl_core` 版）。若只改 `lppl_engine` 版，
> `computation.py` 的行为不会改变。三套口径需要统一，否则"让风险评级使用调用方配置"的目标只完成一半。
>
> **范围划分：** 本任务（P0）只处理前两套（`lppl_engine` + `computation.py`）。
> 第三套（`backtest.py` 的 `InvestmentSignalConfig`）归入 P1-02，因为涉及回测行为变化，
> 需要在指标迁移时一起评估，不宜在 P0 阶段引入策略行为变更。

建议测试：

- 在 `tests/unit/test_lppl_engine_ensemble.py` 增加测试：
  - 默认配置下 `days_left=10` 为观察或 warning 语义。
  - 自定义 `danger_days=15` 时同一输入进入 danger。
  - 高 `r2_threshold` 时低 R2 不触发 danger。
- 新增 `test_computation_risk_level_uses_config.py`：
  - 验证 `computation.py` 最终使用的风险阈值与调用方传入的配置一致。

实现步骤：

1. 修改 `lppl_engine.calculate_risk_level` 函数签名为：

```python
def calculate_risk_level(
    m: float,
    w: float,
    days_left: float,
    r2: float = 1.0,
    lppl_config: LPPLConfig | None = None,
) -> Tuple[str, bool, bool]:
```

2. 函数内部使用 `cfg = lppl_config or DEFAULT_CONFIG`。
3. 将全局 `config` 引用替换为 `cfg`。
4. 将 `computation.py` 的导入从 `from src.lppl_core import calculate_risk_level` 切换到 `from src.lppl_engine import calculate_risk_level`，确保 `LPPLComputation` 也使用调用方可控的风险阈值。
5. 将 `backtest.py` 的 `InvestmentSignalConfig` 第三套阈值登记为 P1-02 的遗留项，不在本任务处理。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_lppl_engine_ensemble.py tests/unit/test_computation_compat.py -q
```

完成标准：

- 旧调用不破坏。
- 新测试证明配置生效。
- `computation.py` 不再绕过配置体系使用硬编码阈值。
- `backtest.py` 第三套阈值已登记为 P1-02 遗留项，不在 P0 范围。

### P0-03 修复 Wyckoff 交易计划空 DataFrame 风控输入

问题来源：`src/wyckoff/engine.py` 的 `_step5_trading_plan()` 调用 `_detect_limit_moves(pd.DataFrame())`。

目标：

- 用真实 K 线数据计算涨跌停/炸板事件。
- 止损规则接收到真实 `limit_moves_data`。
- 不改变无涨跌停场景的输出。

建议测试：

- 构造最近 20 根 K 线，其中包含涨停后炸板或跌停事件。
- 调用 `WyckoffEngine.analyze()` 或更窄的内部函数测试。
- 断言交易计划中的 stop loss 风控描述包含流动性警告，或 `rule10_stop_loss()` 接收到非空 limit move 数据。

实现步骤：

1. 修改 `_step5_trading_plan()` 签名，增加 `df: pd.DataFrame`。
2. `_analyze_single()` 调用 `_step5_trading_plan()` 时传入 `frame`。
3. 将 `pd.DataFrame()` 替换为 `df`。
4. 对空 df 保留防御逻辑，避免旧测试异常。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_wyckoff_analyzer.py -q
```

完成标准：

- 相关单测通过。
- 新增测试能证明真实涨跌停数据进入风控。
- 不扩大改动到 Wyckoff 阶段判定逻辑。

### P0-04 修复纯数字股票代码交易所推断

问题来源：`src/data/manager.py` 的 `normalize_symbol()` 对所有 6 位纯数字默认补 `.SH`。

目标：

- 纯数字代码按 A 股常见前缀推断交易所。
- 已带 `.SH/.SZ` 的输入保持原样。
- 指数代码优先按项目现有 `INDICES` 映射处理。

建议测试：

在 `tests/unit/test_data_manager_statuses.py` 增加：

```python
assert manager.normalize_symbol("002216") == "002216.SZ"
assert manager.normalize_symbol("300442") == "300442.SZ"
assert manager.normalize_symbol("600859") == "600859.SH"
assert manager.normalize_symbol("603637") == "603637.SH"
assert manager.normalize_symbol("000001.SH") == "000001.SH"
```

实现步骤：

1. 新增私有辅助函数 `_infer_exchange_from_code(code: str) -> str`。
2. 深市前缀：`000`、`001`、`002`、`003`、`300`、`301`、`399`。
3. 沪市前缀：`600`、`601`、`603`、`605`、`688`、`689`、`000` 指数需谨慎，优先 `INDICES`。
4. 若无法识别，保守抛出 `ValueError` 或保持旧行为需要明确测试。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_data_manager_statuses.py -q
```

完成标准：

- 常见深市/沪市股票解析正确。
- 不破坏现有指数代码。
- TDX 读取路径能根据 `.SZ/.SH` 正确定位。

### P0-05 跑通全量 unit 测试收集

目标：

- 在完成 P0-01 到 P0-04 后，确认 unit 测试不再因导入错误或基础边界失败中断。

执行步骤：

1. 运行全量 unit：

```bash
.venv/bin/python -m pytest tests/unit -q
```

2. 如出现失败，按“一个失败原因一个任务”的方式继续拆分，不在 P0-05 中混合修复。
3. 记录失败用例、原因、归属模块。

完成标准：

- `tests/unit` 全部通过，或剩余失败全部被登记为独立后续任务。
- 不进入 integration 修复，避免范围扩大。

## 4. P1 原子任务详案

### P1-01 明确 investment 回测唯一入口

> **⚠️ 重要发现：`backtest_engine.py` 目前无人使用**
> 核查确认 `backtest_engine.py`（309行，模块化实现）**没有任何导入者**，是完全闲置的孤儿模块。
> 所有生产代码和测试都走 `backtest.py`（878行）。
> 因此真实问题不是"两套并存、入口不唯一"，而是：有一个废弃的新实现需要决定去向。

目标：

- 决定 `backtest_engine.py` 的去留：补齐指标后切换为生产入口，或标记 deprecated 后删除。
- 确保指标口径唯一，不因文件冗余导致后续开发者误用。

前置依赖：

- 先完成 P1-02（迁移绩效指标），使 `backtest_engine.py` 功能完备后再评估切换成本。

实施步骤：

1. 搜索所有导入：

```bash
rg -n "investment\\.backtest|investment\\.backtest_engine|generate_investment_signals|run_strategy_backtest" src tests scripts
```

2. 确认 `backtest_engine.py` 的零引用状态。
3. 完成 P1-02 将 `backtest.py` 独有但 `backtest_engine.py` 缺失的绩效指标迁移过去。
4. 切换 `src/investment/__init__.py` 导出为 `backtest_engine`，旧 `backtest.py` 降级为兼容 wrapper 或加 deprecation warning。
5. 更新 CLI 和测试指向新入口。

验收标准：

- 文档或模块注释明确唯一入口。
- 不改变策略行为（新旧入口对同一信号输出一致）。
- CLI 和测试全部指向同一实现。

### P1-02 迁移完整绩效指标到模块化回测实现

目标：

- 将 `backtest.py` 中已有但 `backtest_engine.py` 缺失的关键绩效指标迁移过去。

指标清单：

- `annualized_benchmark`
- `annualized_excess_return`
- `calmar_ratio`
- `turnover_rate`
- `annualized_turnover_rate`
- `whipsaw_rate`

附加（P0-02 遗留）：统一 `backtest.py` 中 `InvestmentSignalConfig` 的风险阈值定义，改为复用 `LPPLConfig` 的对应字段，消除第三套口径。

建议测试：

- 基于固定信号 DataFrame，断言 summary 包含上述字段。
- 对空 trades、单笔 trades、多笔 trades 分别测试换手率和 whipsaw。
- 新旧入口对同一信号输入输出一致。
- `InvestmentSignalConfig` 不再维护独立的风险阈值硬编码。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q
```

完成标准：

- 模块化回测 summary 字段不低于旧实现。
- CLI 报告不缺字段。
- 旧入口仍兼容。

### P1-03 明确 Wyckoff v3 唯一入口并加版本字段

目标：

- 让报告能够明确展示使用的 Wyckoff 引擎版本和规则版本。
- 避免 `analyzer.py`、`data_engine.py`、`engine.py` 长期各自输出不同结论。

实施步骤：

1. 在 `WyckoffReport` 或报告 metadata 中增加：
   - `engine_version`
   - `ruleset_version`
2. `WyckoffEngine` 输出 `engine_version="v3"`。
3. CLI 报告输出版本字段。
4. 不立即删除旧引擎，先让旧入口 wrapper 或明确 deprecated。

建议测试：

- `WyckoffEngine.analyze()` 返回报告含版本字段。
- Markdown/HTML 报告包含版本字段。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_wyckoff_models.py tests/unit/test_wyckoff_analyzer.py -q
```

### P1-04 LPPL 数值核心入口收敛设计与第一步迁移

目标：

- 降低 `lppl_engine.py`、`lppl_core.py`、`lppl_fit.py` 重复实现导致的口径分叉。
- 第一阶段只做低风险迁移，不做大规模重写。

实施步骤：

1. 确认 `lppl_core.py` 作为底层数值核心。
2. 在 `lppl_engine.py` 中复用 `lppl_core.lppl_func` 和 `lppl_core.cost_function`，或先补等价性测试。
3. 标记 `lppl_fit.py` 的用途：保留、合并或 deprecated。
4. 新增测试证明同一参数下两个入口的 `lppl_func` 输出一致。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_lppl_engine_ensemble.py tests/unit/test_computation_compat.py -q
```

完成标准：

- 数值输出一致。
- 不改变策略扫描结果。
- 后续可以继续迁移单窗口拟合。

## 5. P2 原子任务详案

### P2-01 LPPL 拟合失败原因结构化

目标：

- 区分“无信号”和“工程失败/数据失败/优化失败”。

建议数据结构：

```python
FitFailureReason = Literal[
    "insufficient_data",
    "non_positive_price",
    "nan_or_inf",
    "constant_price",
    "optimizer_failed",
    "numeric_error",
]
```

实施策略：

- 不一次性改变所有返回类型。
- 先新增内部 helper，批量扫描中记录失败统计。
- 对外保持 `None` 兼容，后续再升级为结构化 result。

验收标准：

- 非正价格输入有明确失败原因测试。
- 常数价格输入有明确失败原因测试。
- 批量扫描日志或结果能统计失败原因。

### P2-02 回测加入成交约束骨架

目标：

- 为 A 股真实交易限制建立扩展点。

第一阶段只实现接口和测试，不追求完整交易所规则。

建议配置：

- `enable_limit_move_constraint: bool`
- `max_participation_rate: float`
- `suspend_if_volume_zero: bool`

建议测试：

- 当 `volume == 0` 且开启约束时，不成交。
- 当涨停无法买入时，买入信号顺延或跳过。
- 当跌停无法卖出时，卖出失败并记录原因。

验收标准：

- 旧默认行为不变。
- 开启约束时交易流水包含 skipped/rejected 原因。

### P2-03 库代码输出从 `print` 收敛到 logger

目标：

- 库代码不直接打印，CLI 层负责用户输出。

实施范围：

- `src/computation.py`
- 其他非 CLI 模块中的 `print()`

实施步骤：

1. 搜索：

```bash
rg -n "print\\(" src
```

2. 先只处理非 `src/cli/` 文件。
3. 替换为 `logger.info/warning/error`。
4. CLI 若需要进度输出，后续通过 callback 处理。

验收标准：

- 非 CLI 核心模块无直接 `print()`，或保留项有明确理由。
- CLI 测试通过。

### P2-04 Ruff 自动修复安全项

目标：

- 清理导入排序、未使用导入、未使用变量等低风险问题。

实施步骤：

1. 运行安全自动修复：

```bash
.venv/bin/python -m ruff check src --fix
```

2. 查看 diff。
3. 对 `--unsafe-fixes` 暂不启用，单独评估。
4. 手工处理剩余 F841、E741 等问题。

验收命令：

```bash
.venv/bin/python -m ruff check src
.venv/bin/python -m pytest tests/unit -q
```

完成标准：

- Ruff 通过。
- Unit 测试通过。
- 不混入行为变更。

### P2-05 固化全量验证脚本或 Make 目标

目标：

- 给后续修复建立统一验证入口。

建议新增脚本：

```bash
scripts/verify_src_quality.py
```

或在 `pyproject.toml` / Makefile 中提供命令。

最小验证内容：

```bash
python3 -m compileall -q src
.venv/bin/python -m ruff check src
.venv/bin/python -m pytest tests/unit -q
```

验收标准：

- 单命令能完成基础质量门禁。
- README 或 docs 中记录使用方式。

## 6. 建议执行顺序

严格建议按以下顺序执行：

1. P0-01：先恢复测试收集。
2. P0-02：修 LPPL 配置贯通。
3. P0-03：修 Wyckoff 风控输入。
4. P0-04：修股票代码解析。
5. P0-05：跑全量 unit，登记剩余失败。
6. P1-01：明确 investment 唯一入口。
7. P1-02：迁移完整绩效指标。
8. P1-03：Wyckoff 入口版本化。
9. P1-04：LPPL 数值核心收敛第一步。
10. P2-01 到 P2-05：按风险和时间窗口分批做。

不要在 P0 阶段做大规模重构。P0 的目标是恢复可信基础，不是完成架构整理。

## 7. 每个任务的完成模板

建议每完成一个任务，都在提交说明或 PR 描述中填写：

```markdown
## 修复目标

- [任务 ID] 简述问题

## 改动范围

- 修改文件：
- 新增/更新测试：

## 验证

- [ ] python3 -m compileall -q src
- [ ] .venv/bin/python -m ruff check src
- [ ] .venv/bin/python -m pytest <相关测试> -q

## 风险

- 行为兼容性：
- 仍未覆盖：
```

## 8. Definition of Done

本轮修复计划全部完成时，应满足：

- `tests/unit` 可完整通过。
- `ruff check src` 通过或剩余问题有明确豁免说明。
- LPPL 风险评级不再依赖隐式全局配置（`lppl_engine` + `computation.py` 均已统一）。
- `backtest.py` 第三套风险阈值已登记并纳入 P1-02 迁移计划。
- Wyckoff 交易计划使用真实 K 线计算涨跌停/炸板风控。
- `normalize_symbol()` 对常见沪深股票解析正确。
- investment 回测入口和绩效指标口径明确。
- Wyckoff 报告可识别引擎/规则版本。
- LPPL 重复实现有明确收敛路线，至少完成第一步等价性验证。

## 9. 不建议现在做的事

- 不建议一次性删除 `backtest.py`、`analyzer.py`、`data_engine.py` 等历史实现。
- 不建议在 P0 阶段重写 LPPL 拟合器。
- 不建议同时修改 CLI 输出、报告格式、回测算法和数据层。
- 不建议在未跑通 unit 前处理大批 Ruff 自动修复。
- 不建议把 integration 中依赖本机 TDX 数据的失败和 unit 基础失败混在一个任务中处理。
- 不建议在 P0-02 中只改 `lppl_engine` 版 `calculate_risk_level` 而跳过 `computation.py` 的同步——那会让"配置贯通"目标只完成一半。
- 不建议在 P0-02 中处理 `backtest.py` 的 `InvestmentSignalConfig` 第三套阈值（已归入 P1-02），P0 阶段修改回测阈值可能引入策略行为变化，集中精力修复测试收集和配置贯通即可。

## 10. 下一步建议

从 P0-01 开始实施。该任务范围最小、收益最大，修复后才能让后续测试暴露真实失败，而不是停在导入错误阶段。
