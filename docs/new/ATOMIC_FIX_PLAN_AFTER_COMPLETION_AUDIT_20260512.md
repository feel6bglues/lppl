# 核实后新版原子化修复计划

生成日期：2026-05-12  
依据文档：`docs/new/ATOMIC_REMEDIATION_COMPLETION_AUDIT_20260512.md`  
目标：针对完成度核实报告中仍未闭环的项目和已登记失败项，重新制定一版更窄、更可验收的原子化修复计划。

## 1. 当前基线

当前可确认的质量基线：

```text
compileall: PASS
ruff: PASS
wyckoff unit subset: PASS
tests/unit: FAIL, 145 passed, 29 failed
```

当前失败主要分布：

| 模块 | 失败数 | 根因摘要 |
|---|---:|---|
| DataManager | 5 | `amount` 被设为必填列，旧 OHLCV 输入和测试夹具缺列。 |
| investment backtest | 21 | 回测/信号行为与既有断言不一致，涉及持仓、再平衡、MA/ATR、多因子、warning/watch 等。 |
| LPPL ensemble | 1 | `positive_consensus_rate` 分母口径争议。 |
| LPPL verify CLI | 2 | `tc_bound` 默认值和 fallback `param_source` 标记变化。 |
| LPPL computation config | 未直接计入失败 | `LPPLComputation` 未接收并传递 `LPPLConfig`，P0-02 未闭环。 |
| LPPL core risk function | 未直接计入失败 | `lppl_core.calculate_risk_level()` 硬编码仍保留，P1-04 未闭环。 |

## 2. 执行原则

本轮计划只做“收敛失败项”和“闭环未完成项”，不继续扩大重构面。

- 每个任务只处理一个失败根因。
- 每个任务必须有独立测试命令。
- 优先恢复现有测试通过，不把行为变更伪装成测试修正。
- 若确实需要改变行为，必须先补设计说明，再改测试。
- 不在本轮新增大范围架构迁移。

## 3. 任务总览

| ID | 优先级 | 任务 | 主要文件 | 验收命令 |
|---|---:|---|---|---|
| A0-01 | P0 | 完成 `LPPLComputation` 配置注入 | `src/computation.py`, `tests/unit/test_computation_compat.py` | `.venv/bin/python -m pytest tests/unit/test_computation_compat.py tests/unit/test_lppl_engine_ensemble.py -q` |
| A0-02 | P0 | 修复 `amount` 必填导致的数据层回归 | `src/constants.py`, `src/data/manager.py`, `src/lppl_core.py`, `tests/unit/test_data_manager_statuses.py` | `.venv/bin/python -m pytest tests/unit/test_data_manager_statuses.py -q` |
| A0-03 | P0 | 修复 LPPL ensemble 正/负共识率分母 | `src/lppl_engine.py`, `tests/unit/test_lppl_engine_ensemble.py` | `.venv/bin/python -m pytest tests/unit/test_lppl_engine_ensemble.py -q` |
| A0-04 | P0 | 修复 LPPL verify 默认配置和 fallback 标记 | `src/cli/lppl_verify_v2.py`, `tests/unit/test_lppl_verify_outputs.py` | `.venv/bin/python -m pytest tests/unit/test_lppl_verify_outputs.py -q` |
| A0-05 | P0 | 恢复 investment backtest 既有行为 | `src/investment/backtest.py`, `tests/unit/test_investment_backtest.py` | `.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q` |
| A0-06 | P0 | 跑通全量 unit 质量门禁 | 多模块 | `.venv/bin/python scripts/verify_src_quality.py` |
| A1-01 | P1 | 收敛 `lppl_core.calculate_risk_level()` 旧硬编码口径 | `src/lppl_core.py`, `src/lppl_engine.py`, LPPL tests | `.venv/bin/python -m pytest tests/unit/test_lppl_engine_ensemble.py tests/unit/test_computation_compat.py -q` |
| A1-02 | P1 | 复核 Wyckoff 旧入口 deprecated/wrapper 状态 | `src/wyckoff/analyzer.py`, `src/wyckoff/data_engine.py`, docs/tests | Wyckoff subset |

## 4. P0 任务详案

### A0-01 完成 `LPPLComputation` 配置注入

问题：

`computation.py` 已切换到 `lppl_engine.calculate_risk_level()`，但 `LPPLComputation` 没有接收、保存、传递 `LPPLConfig`。当前只是从 `lppl_core` 硬编码阈值切换到 `lppl_engine.DEFAULT_CONFIG`，没有真正使用调用方配置。

目标：

- `LPPLComputation` 构造函数可接收 `lppl_config`。
- `_format_output()` 使用 `self.lppl_config` 调用 `calculate_risk_level()`。
- `_fit_single_window_compat()` 若需要保持纯函数，可暂不接入配置；若要统一，也应支持可选配置但不破坏现有测试。

建议测试：

在 `tests/unit/test_computation_compat.py` 新增：

- 构造 `LPPLConfig(window_range=[50], danger_days=15, warning_days=20, watch_days=30)`。
- 创建 `LPPLComputation(lppl_config=custom_config)`。
- 调用 `_format_output()`，传入 `days_left=10` 的结果。
- 断言风险标签按自定义配置进入高危或 danger 语义，而不是默认观察。

最小实现步骤：

1. 在 `src/computation.py` 导入 `LPPLConfig` 和 `DEFAULT_CONFIG`。
2. 修改构造函数：

```python
def __init__(
    self,
    output_dir: str = None,
    max_workers: Optional[int] = None,
    lppl_config: Optional[LPPLConfig] = None,
):
    self.lppl_config = lppl_config or DEFAULT_CONFIG
```

3. 修改 `_format_output()`：

```python
risk_label, _, _ = calculate_risk_level(
    m,
    w,
    days_left,
    lppl_config=self.lppl_config,
)
```

4. 不改 `process_index_multiprocess()` 的扫描窗口行为。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_computation_compat.py tests/unit/test_lppl_engine_ensemble.py -q
```

完成标准：

- 新测试通过。
- 旧测试通过。
- `computation.py` 的风险标签能被调用方传入的 `LPPLConfig` 影响。

### A0-02 修复 `amount` 必填导致的数据层回归

问题：

`REQUIRED_COLUMNS` 当前包含 `amount`，导致原本合法的 OHLCV 数据被判定非法：

```text
Missing required columns: ['amount']
```

影响：

- TDX mock 数据失败。
- parquet cache 测试失败。
- CSV 文件输入失败。
- Wyckoff 文件输入失败。

目标：

- 基础数据校验只要求 OHLCV 必需列。
- `amount` 作为可选增强列：存在时校验非负，不存在时允许。
- 不破坏已有真实 TDX/AkShare 数据中的 `amount` 字段。
- `src/lppl_core.validate_input_data()` 通过 `REQUIRED_COLUMNS` 间接受影响，本任务需确认其仍接受无 `amount` 的基础 OHLCV 输入。

建议测试：

在 `tests/unit/test_data_manager_statuses.py` 保持现有测试不改或只补充：

- 无 `amount` 的 OHLCV DataFrame 可通过 `validate_dataframe()`。
- 有 `amount` 且为负值时失败。
- 有 `amount` 且非负时通过。

最小实现步骤：

1. 将 `REQUIRED_COLUMNS` 改回基础列：

```python
REQUIRED_COLUMNS = ["date", "open", "close", "high", "low", "volume"]
```

2. 在 `validate_dataframe()` 中保留：

```python
if "amount" in df.columns and (df["amount"] < 0).any():
    return False, "Invalid data: negative amount found"
```

3. 不在读取层强行填充 `amount = 0.0`，避免误导金额维度分析。
4. 不批量修改既有测试夹具来补 `amount`；只在测试中新增“负 `amount` 应失败、非负 `amount` 应通过”的覆盖。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_data_manager_statuses.py -q
```

完成标准：

- 数据层 5 个失败全部通过。
- 无 `amount` 的 OHLCV 仍合法。
- 有负 `amount` 仍能被拒绝。

### A0-03 修复 LPPL ensemble 正/负共识率分母

问题：

测试 `test_process_single_day_ensemble_uses_valid_window_denominator_for_positive_consensus` 期望：

```text
positive_consensus_rate = 0.5
```

当前实现输出：

```text
positive_consensus_rate = 0.3333333333333333
```

根因：

- 总体 `consensus_rate` 应该是 `valid_n / total_windows`。
- 正泡沫/负泡沫内部占比更适合使用 `valid_n` 作为分母，表示有效拟合中的方向结构。
- 当前实现使用 `total_windows` 作为分母，导致方向占比被无效窗口稀释。

目标：

- 保持 `consensus_rate = valid_n / total_windows`。
- 修改：

```python
positive_consensus_rate = len(positive_fits) / valid_n
negative_consensus_rate = len(negative_fits) / valid_n
```

前置条件：

- 若策略设计明确要求方向共识也按总窗口算，则应更新测试和文档。
- 当前按现有测试优先，修改实现。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_lppl_engine_ensemble.py -q
```

完成标准：

- ensemble 全部单测通过。
- 总体共识和方向共识含义在注释中明确。

### A0-04 修复 LPPL verify 默认配置和 fallback 标记

问题：

失败包括：

```text
test_create_config_aligns_with_core_lppl_thresholds
expected tc_bound (1, 150), got (1, 60)

test_main_marks_default_fallback_when_optimal_config_load_fails
expected param_source default_fallback, got default_cli
```

目标：

- 恢复测试期望的默认 `tc_bound`。
- 使用 `--use-optimal-config` 但配置加载失败时，`param_source` 标记为 `default_fallback`。
- 不影响正常加载 optimal config 的路径。

建议测试：

使用现有 `tests/unit/test_lppl_verify_outputs.py`，必要时补充：

- optimal config 加载成功时 `param_source` 不为 fallback。
- 未要求 optimal config 时仍是 `default_cli`。
- 要求 optimal config 但加载失败时是 `default_fallback`。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_lppl_verify_outputs.py -q
```

完成标准：

- 2 个现有失败通过。
- `default_cli` 与 `default_fallback` 语义明确区分。

### A0-05 恢复 investment backtest 既有行为

问题：

`tests/unit/test_investment_backtest.py` 有 21 个失败，涉及核心交易行为：

- 多因子信号模型
- MA cross ATR
- MA convergence ATR
- LPPL warning/watch
- min hold
- reentry cooldown
- stepwise position ladder
- hold day rebalance

目标：

- 先恢复既有测试语义。
- 不在本任务中重写策略。
- 不把测试改成适配新行为，除非有明确策略设计文档。

拆分原则：

该任务很大，必须继续拆成子任务。不要一次性改完 21 个失败。

#### A0-05a 修复 hold 日再平衡行为

代表失败：

```text
test_run_strategy_backtest_does_not_rebalance_on_hold_days
Expected len(trades_df) == 1, got 3
```

目标：

- `action == "hold"` 时不因 target_position 漂移自动再平衡。
- 只有 `buy/add/sell/reduce` 行为触发交易，除非明确配置开启再平衡。

验收：

```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q -k "does_not_rebalance_on_hold_days"
```

#### A0-05b 修复 LPPL warning/watch 交易语义

代表失败：

- `test_generate_investment_signals_can_treat_warning_as_observation_only_in_legacy`
- `test_generate_investment_signals_treats_watch_as_non_tradable`
- `test_generate_investment_signals_supports_relaxed_danger_r2_threshold`

目标：

- `warning_trade_enabled=False` 时 warning 只观察，不调仓。
- watch 信号不触发交易。
- danger R2 offset 按配置生效。

验收：

```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q -k "warning or watch or relaxed_danger"
```

#### A0-05c 修复 MA cross ATR 行为

代表失败：

- `test_ma_cross_atr_v1_sells_after_bearish_cross_when_atr_keeps_expanding`
- `test_ma_cross_atr_v1_blocks_sell_without_continuing_atr_expansion`
- `test_ma_cross_atr_lppl_model_buys_on_golden_cross_with_atr_confirmation`
- `test_ma_cross_atr_lppl_model_reduces_on_death_cross_with_atr_confirmation`

目标：

- 恢复金叉买入、死叉/ATR 扩张卖出/减仓、无持续 ATR 扩张不卖出的既有语义。
- 不让 LPPL 风险层覆盖 MA/ATR 基础逻辑，除非测试明确要求。

验收：

```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q -k "ma_cross_atr"
```

#### A0-05d 修复 MA convergence ATR 行为

代表失败：

- `test_ma_convergence_atr_v1_buys_on_bb_contraction_low_atr_breakout`
- `test_ma_convergence_atr_v2_buys_on_golden_cross_with_atr_low`

目标：

- 恢复 position_reason 文案和触发条件。
- 保持 v1/v2 分支区别。

验收：

```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q -k "ma_convergence"
```

#### A0-05e 修复多因子持仓约束

代表失败：

- `test_generate_investment_signals_applies_regime_hysteresis_to_bottom_regime`
- `test_generate_investment_signals_blocks_immediate_reentry_after_sell`
- `test_generate_investment_signals_blocks_sell_during_min_hold_without_override`
- `test_generate_investment_signals_caps_buy_position_under_high_volatility`
- `test_generate_investment_signals_requires_confirmation_for_large_cap_sell`
- `test_generate_investment_signals_requires_drawdown_reentry_for_bottom_buy`
- `test_generate_investment_signals_requires_lppl_vote`
- `test_generate_investment_signals_respects_signal_window`
- `test_generate_investment_signals_supports_stepwise_position_ladder`

目标：

- 恢复 min hold、reentry cooldown、drawdown reentry、LPPL vote、stepwise ladder、高波动仓位上限等既有行为。
- 每修一类约束，单独跑对应 `-k` 测试。

验收：

```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q
```

完成标准：

- `tests/unit/test_investment_backtest.py` 全部通过。
- 若有意变更策略行为，必须先新增设计记录，再更新测试。

### A0-06 跑通全量 unit 质量门禁

目标：

- 当前所有 P0 失败项修复后，跑全量验证脚本。

验收命令：

```bash
.venv/bin/python scripts/verify_src_quality.py
```

完成标准：

```text
compileall: PASS
ruff: PASS
pytest tests/unit -q: PASS
```

失败处理规则：

- 若仍有失败，不在 A0-06 中混合修复。
- 将失败按模块拆成新的 A0-07、A0-08 等任务。

## 5. P1 任务详案

### A1-01 收敛 `lppl_core.calculate_risk_level()` 旧硬编码口径

问题：

`lppl_core.calculate_risk_level()` 仍保留硬编码阈值：

```python
if days_left < 5:
elif days_left < 20:
elif days_left < 60:
```

目标：

- 避免后续调用方再次绕过 `LPPLConfig`。
- 明确 `lppl_core` 不再维护独立风险口径。

可选方案：

方案 A：保留兼容函数，但转调 `lppl_engine.calculate_risk_level()`。

方案 B：标记 deprecated，并在注释中明确不得用于新代码。

方案 C：迁移所有调用后删除该函数。

推荐：

先做方案 A 或 B，避免大范围破坏。

验收命令：

```bash
rg -n "from src.lppl_core import .*calculate_risk_level|lppl_core.calculate_risk_level|calculate_risk_level\\(" src tests
.venv/bin/python -m pytest tests/unit/test_computation_compat.py tests/unit/test_lppl_engine_ensemble.py -q
```

完成标准：

- 新代码不再从 `lppl_core` 导入风险评级函数。
- 若函数保留，文档说明其兼容用途和默认配置行为。

### A1-02 复核 Wyckoff 旧入口状态

问题：

Wyckoff v3 报告版本字段已完成，但旧入口 `WyckoffAnalyzer` / `DataEngine` 是否 wrapper/deprecated 仍未完全确认。

目标：

- 明确 `WyckoffEngine` 为推荐入口。
- 旧入口不再声称是同等生产入口。
- 报告或模块注释能说明版本关系。

实施步骤：

1. 搜索入口引用：

```bash
rg -n "WyckoffAnalyzer|DataEngine|WyckoffEngine" src tests scripts
```

2. 记录实际调用路径。
3. 对旧入口增加 docstring deprecated 说明，或包装到 `WyckoffEngine`。
4. 不在本任务中重写规则逻辑。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_wyckoff_analyzer.py tests/unit/test_wyckoff_models.py -q
```

完成标准：

- 推荐入口清楚。
- 旧入口状态清楚。
- Wyckoff 单测通过。

## 6. 推荐执行顺序

严格按 Section 10.6 的“修正后的推荐执行顺序（完整版）”执行。该顺序是本计划的唯一执行顺序；本节不再维护第二套顺序，避免执行歧义。

## 7. 每个任务的交付模板

每完成一个任务，建议在提交说明中记录：

```markdown
## Task

- ID: A0-XX
- Goal:

## Changed Files

- src/...
- tests/...

## Verification

- [ ] targeted pytest command
- [ ] .venv/bin/python -m ruff check src
- [ ] python3 -m compileall -q src

## Behavioral Notes

- Existing behavior restored:
- Intentional behavior change:
- Remaining risks:
```

## 8. Definition of Done

本轮新版计划完成时，必须满足：

- `scripts/verify_src_quality.py` 返回 0。
- `tests/unit/test_data_manager_statuses.py` 全部通过。
- `tests/unit/test_lppl_engine_ensemble.py` 全部通过。
- `tests/unit/test_lppl_verify_outputs.py` 全部通过。
- `tests/unit/test_investment_backtest.py` 全部通过。
- `LPPLComputation` 风险评级使用调用方配置。
- `amount` 不再作为基础 OHLCV 必填列，或测试夹具与设计明确同步。
- investment backtest 不在 hold 日隐式再平衡，除非显式配置开启。
- `lppl_core.calculate_risk_level()` 不再作为独立硬编码风险口径被新代码使用。

## 9. 不做事项

本轮不要做：

- 不继续扩大 Ruff 自动重排范围；当前 Ruff 已通过。
- 不新增新的策略模型。
- 不继续迁移 `backtest.py` / `backtest_engine.py` 的入口关系，除非为修复测试所必需。
- 不重写 Wyckoff 规则引擎。
- 不把 21 个 investment 失败一次性用改测试方式压掉。

## 10. 核实补充（基于 docs/new/ATOMIC_REMEDIATION_COMPLETION_AUDIT_20260512.md 修正版）

以下为对上一轮计划的独立审查发现，补充到本计划中。

### 10.1 补充原子任务

| ID | 优先级 | 任务 | 主要文件 | 验收命令 | 触发条件 |
|----|--------|------|---------|---------|---------|
| **A0-07** | P0 | A0-02 后重新评估 A0-05 失败范围 | 无代码改动，仅评估 | 更新 A0-05 子任务拆分 | A0-02 完成后执行 |
| **A0-08** | P0 | 对齐 `_check_trade_constraints` 调用方式 | `src/investment/backtest.py` | `.venv/bin/python -m pytest tests/unit/test_investment_backtest.py::TradeConstraintTests -q` | A0-02 完成后执行 |

### 10.2 补充任务详案

#### A0-07 A0-02 后重新评估 A0-05 失败范围

问题：

21 个 backtest 失败中，部分根因是测试数据缺少 `amount` 列导致 `validate_dataframe` 拒绝。
A0-02 将 `amount` 改为可选后，这部分失败将自动恢复。

目标：

- 在 A0-02 完成后，重新跑一次 `pytest tests/unit/test_investment_backtest.py -q`。
- 记录剩余失败数量和清单。
- 将剩余失败重新归因到 A0-05a~e 中，必要时新增子类别。
- 更新 A0-05 的验收命令和完成标准。

不单独设验收命令，跟随 A0-05 的测试命令。

完成标准：

- 剩余失败列表明确。
- 每个剩余失败都有对应的 A0-05 子任务。
- 更新后的 A0-05 拆分与实际情况一致。

#### A0-08 对齐 `_check_trade_constraints` 调用方式

问题：

P2-02 新增的 `_check_trade_constraints_df()` 在 `run_strategy_backtest` 中通过 `equity_df` + `row_idx` 的方式调用。若 `equity_df` 在后续处理中被切片或重新索引，`iloc[row_idx]` 可能指向错误行。

此外，`_check_trade_constraints()`（基于 namedtuple 的版本）暂未被 `run_strategy_backtest` 使用，存在两套检查路径。

目标：

- 统一使用基于 DataFrame 的检查路径（当前已实现）。
- 确保 `row_idx` 与 `equity_df` 的 `reset_index(drop=True)` 一致（当前实现已保证）。
- 将 `_check_trade_constraints()`（namedtuple 版）标记为内部保留备用。

最小实现步骤：

1. 确认 `run_strategy_backtest` 中 `row_idx` 始终对应 `equity_df.iloc[row_idx]`。
2. 在 `_check_trade_constraints()` 函数上方加注释：`# 预留外部调用接口，当前未使用`。
3. 不修改 trade 执行逻辑。

验收命令：

```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py::TradeConstraintTests -q
```

完成标准：

- TradeConstraintTests 4 个测试通过。
- 代码无死路径风险。

### 10.3 核实发现的执行顺序修正

原计划执行顺序对大部分任务正确，但以下三项建议调整：

```
原顺序:                    修正后:
A0-02                      A0-02
  → A0-01                    → A0-01
    → A0-03                    → A1-01 (提前：趁 computation.py 刚改完，立即收敛旧函数)
      → A0-04                    → A0-07 (重新评估 A0-05 范围)
        → A0-05a...e                → A0-03 / A0-04 (可并行)
          → A0-06                    → A0-05a→b→c→d→e
            → A1-01                    → A0-06
              → A1-02                    → A1-02
```

修正理由：

| 调整 | 理由 |
|------|------|
| A1-01 提前到 A0-01 后 | A0-01 已将 `computation.py` 切到 `lppl_engine` 版，此时 `lppl_core` 旧函数已无调用者。加 deprecated 注释工作量极小（< 5 行），趁热打铁避免遗漏 |
| A0-07 插入 A0-03 前 | A0-02 解除 `amount` 必填后，backtest 失败数可能大幅减少。先评估再拆分 A0-05，避免对"假失败"浪费调试时间 |
| A0-03/A0-04 可并行 | 两个任务修改不同文件（`lppl_engine.py` vs `cli/lppl_verify_v2.py`），无依赖冲突 |

### 10.4 补充风险登记

#### 风险 A：A0-03 分母口径变更影响策略可比性

将 `positive_consensus_rate` 分母从 `total_windows` 改为 `valid_n` 会改变输出值。如果已有回测结果或生产运行依赖旧口径，切换后不可比。

缓解措施：

- 在 commit message 中明确注明口径变更。
- 在 `process_single_day_ensemble` 的 docstring 中记录两种口径含义：

```python
# consensus_rate = valid_n / total_windows（总窗口占比）
# positive_consensus_rate = len(positive_fits) / valid_n（有效拟合中的正泡沫占比）
# negative_consensus_rate = len(negative_fits) / valid_n（有效拟合中的负泡沫占比）
```

#### 风险 B：A0-02 修改 `REQUIRED_COLUMNS` 后真实数据流可能受影响

如果下游代码（如 Wyckoff `DataEngine`、`FactorCombinationEngine`）已依赖 `amount` 列的存在性，降级为可选后可能导致 `amount` 缺失时静默降级。

缓解措施：

- 在 A0-02 的 PR 描述中列出所有引用 `amount` 的代码路径。
- 对每个路径确认：`amount` 缺失时是静默降级（可接受）、报错（需修复）、还是不影响。

### 10.5 补充不做事项

在原计划 Section 9 基础上补充：

- 不在 A0-05 子任务中修改 `REQUIRED_COLUMNS` 或 `validate_dataframe`——已在 A0-02 统一处理。
- 不在单个 commit 中混合 A0-03 分母修复和 A0-04 CLI 输出修复——两者语义无关。
- 不在 A0-02 中同时改变 `amount` 校验策略和测试夹具策略——选择一个路径并保持一致。

### 10.6 修正后的推荐执行顺序（完整版）

```
Step 1: A0-02   amount 改为可选列；不批量修改测试夹具
Step 2: A0-08   _check_trade_constraints 对齐（可选，低风险）
Step 3: A0-01   LPPLComputation 配置注入
Step 4: A1-01   收敛 lppl_core 旧风险函数（趁热打铁）
Step 5: A0-07   重新评估 backtest 失败范围
Step 6: A0-03   LPPL ensemble 分母（与 A0-04 可并行）
Step 7: A0-04   LPPL verify 输出（与 A0-03 可并行）
Step 8: A0-05a  hold 日再平衡
Step 9: A0-05b  warning/watch 交易语义
Step 10: A0-05c MA cross ATR
Step 11: A0-05d MA convergence ATR
Step 12: A0-05e 多因子持仓约束
Step 13: A0-06   全量验证脚本
Step 14: A1-02   Wyckoff 旧入口复核（最低优先级）
```
