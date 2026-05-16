# LPPL 量化系统修复计划 — Sprint 8/9/10

> 生成日期: 2026-05-16
> 基线: Sprint 1-7 封板（docs/new/remediation_closeout.md）
> 范围: 残余治理 + Sprint 6b + CI Phase 2

---

## 当前状态（基线）

| 指标 | 值 |
|------|----|
| `src/` sys.path.insert | **0 处** ✅ |
| `src/` 全局 filterwarnings("ignore") | **0 处** ✅ |
| 全项目 sys.path.insert | **97 处** ❌（83 处在 scripts/） |
| 测试失败 | **8 个已知失败** ❌ |
| 合约测试 | `tests/contract/` 已创建但缺少实质性 contract tests ❌ |
| CI 类型 | 仅 Phase 1: lint + compile + unit ✅ |
| 残留 lint | 750 non-auto-fixable ❌ |
| Sprint 6b | 未开始 ❌ |
| 存活者偏差 | 已记录但未解决 ⚠️ |

---

## Sprint 8: 绿色测试套件 + 合约测试奠基

**目标**: 零容忍失败。任何 CI 能跑的东西必须是绿色的。

### 8.1 修复 3 类已知失败

当前 8 个失败分 3 类，每类根因不同，需不同策略：

#### 8.1.1 `test_cli_warning_filters_are_targeted` (1 test)

- **根因**: 测试断言 `assertFalse(['ignore'])`，与 Sprint 4 的局部 warning 过滤策略冲突
- **修复方案**: 修改测试逻辑，验证 `filterwarnings` 调用使用 `module=` 参数而非全局 `'ignore'`
- **工作量**: ~20 行，1 个 PR
- **判定标准**: `python -m pytest tests/unit/test_cli_entrypoints.py::test_cli_warning_filters_are_targeted -v` 通过

#### 8.1.2 `test_backtest_smoke.*` (6 tests)

- **根因**: 这些测试不属于 unit test 边界。它们用 subprocess 调 `scripts/run_backtest.py`，依赖本地 TDX 数据和真实运行环境。已有 `@pytest.mark.skipif(not LPPL_TDX_DATA_DIR)` 被 CI 正确跳过，但放在 `tests/unit/` 中模糊了测试分层约定。
- **修复方案**:
  - 将这些测试从 `tests/unit/` 移到 `tests/integration/` — 它们不是单元测试
  - 添加 `@pytest.mark.tdx` 标记，纳入集成/回放层
  - 可选：创建一个最小 mock 版本的 smoke test，用 fake data + mock DataManager 验证 schema 逻辑而非完整 subprocess
- **工作量**: 移动 + 重标记，~100 行修改
- **判定标准**: `pytest tests/unit/ -v` 全部绿色，分层边界清晰；`pytest tests/integration/ -m tdx -v` 可选执行

#### 8.1.3 `test_run_function_importable` (1 test)

- **根因**: 该测试调用了真实回测路径，依赖数据/环境/worker 初始化，不满足 unit/contract 边界。不只是 import path 的问题。
- **修复方案**: 先将测试标记为 `@pytest.mark.skip(reason="待 Sprint 9 迁移后重建")` 确保绿色。Sprint 9 策略迁入 `src/strategies/` 后，用纯函数 import 测试替代。
- **工作量**: 1 行 skip + Sprint 9 中重建
- **判定标准**: Sprint 9 交付时取消 skip，新测试在 `tests/contract/` 中验证 import + 基础合约

### 8.2 Contract Test 脚手架

- 创建 `tests/contract/test_data_contract.py` — 验证 DataBundle 的 schema 合约
- 创建 `tests/contract/test_backtest_contract.py` — 验证 `run_strategy_backtest` 输入/输出合约
- 不依赖 TDX 数据；使用 `tests/fixtures/` 中的静态 parquet/csv
- 加入 CI 的 `pytest tests/contract/ -v` 步骤

**Sprint 8 交付物清单**:
- [ ] `test_cli_warning_filters_are_targeted` 修复
- [ ] 6 个 `test_backtest_smoke.*` 移到 `tests/integration/`，加 `@pytest.mark.tdx`
- [ ] `test_run_function_importable` 临时 skip 并加 TODO tracker
- [ ] `pytest tests/unit/ -v` 全绿
- [ ] CI 运行 `pytest tests/unit/ tests/contract/ -v` 全绿
- [ ] `tests/contract/` 至少 2 个真实的 schema 合约测试

---

## Sprint 9: Research 表面清理（原名 Sprint 6b）

**目标**: 消除 ~93 处 `sys.path.insert`，将持久性策略逻辑从 `scripts/` 迁入 `src/`。

### 9.1 策略迁移: `scripts/backtest_core.py` → `src/strategies/`

当前 `scripts/backtest_core.py` 包含 3 个策略实现：
- `trade_wyckoff` (line 112-208)
- `trade_ma` (line 212-244)  
- `trade_str_reversal` (line 248-276)

以及回测编排 `run_backtest` (line 334-460)。

**迁移方案**:

```
src/strategies/
├── __init__.py                  # 导出 StrategyResult, run_backtest
├── base.py                      # BaseStrategy ABC + StrategyResult dataclass
├── wyckoff.py                   # WyckoffStrategy（从 backtest_core.py trade_wyckoff 迁移）
├── ma_cross.py                  # MaCrossStrategy（从 backtest_core.py trade_ma 迁移）
├── str_reversal.py              # ReversalStrategy（从 backtest_core.py trade_str_reversal 迁移）
├── registry.py                  # STRATEGY_MAP 统一注册
├── backtest.py                  # run_backtest 编排（并行调度、统计、蒙特卡洛）
├── regime.py                    # get_regime 市场制度判定
└── indicators.py                # calc_atr 等共享指标
```

**关键要求**:
- 零 `sys.path.insert` — 使用 `from src.strategies.xxx import ...`
- 使用 `src.data.manager.DataManager` 替代 scripts/ 中的自定义数据加载
- 保持 `scripts/backtest_core.py` 作为 thin 兼容层（from src.strategies.backtest import run_backtest）
- 保持 `scripts/run_backtest.py` 功能不变

**工作量**: ~600 行新代码 + ~200 行迁移
**风险**: 中 — 虽然策略逻辑是纯函数，但兼容层、测试重建、回测行为一致性需要额外验证

### 9.2 Sys.path Debt 清理

| 位置 | 数量 | 策略 |
|------|------|------|
| `scripts/`（非 archive） | ~60 files | 每条 insert 审查。如果是 import src.xxx，直接改用 `from src.xxx`。如果是 import 内部模块，考虑合并或归档。 |
| `scripts/archive/` | ~11 files | 全部标记 `# ARCHIVED` 注释 |
| `scripts/tuning/` | ~14 files | 暂保留 research-only，加 `# RESEARCH ONLY` header。**不做 sys.path.insert 标准化** — 不新增变体写法。如需统一，通过 package install 路径解决。 |
| `scripts/utils/` | ~15 files | 移到 `src/utils/` 或 `scripts/_utils/` |
| 根 wrapper | 11 files | 确认已 delegating 到 `src.cli`，inser 清理 |

### 9.3 Research-only 目录标记

- `scripts/README.md` 增加醒目 banner: **⚠️ RESEARCH SCRIPTS — NOT COVERED BY CI OR QUANT AUDIT**
- 每个 `scripts/` 文件第一行加注释 `# RESEARCH ONLY — not production code`
- `scripts/tuning/` 和 `scripts/archive/` 同样处理
- 创建 `scripts/ARCHITECTURE.md` 说明 research 脚本和 `src/` 的关系

**Sprint 9 交付物清单**:
- [ ] `src/strategies/` 包创建 + 3 策略迁移
- [ ] `scripts/backtest_core.py` 变为 thin 兼容层
- [ ] 80%+ 的 `scripts/` sys.path.insert 已清理
- [ ] 根 wrapper sys.path 确认 0 处
- [ ] Research-only 标记覆盖全部 scripts/
- [ ] `pytest tests/unit/ -v` 仍然绿色（含更新后的兼容层测试）

---

## Sprint 10: CI Phase 2 + 存活者偏差治理

### 10.1 CI Phase 2 — 合约+集成门禁

```yaml
# 新增 CI job
contract-tests:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install -r requirements.txt pytest
    - run: python -m pytest tests/contract/ -v
```

后续可考虑：
- 使用 Python 3.12 的 `@pytest.fixture` 生成 fake OHLCV 数据，替代 TDX 依赖
- 添加 data-environment 处理测试（DataManager 在 TDX 不存在时的行为）

### 10.2 存活者偏差治理

当前状态: `backtest_core.py:457-458`:
```python
"universe_has_delisted_stocks": False,
"survivorship_bias_note": "universe is today's stock list, not historical; results may be optimistic",
```

这是 **方案 B: 记录偏差来源**。方案 A 需要 real point-in-time universe data。

**可行步骤**:
1. **输出层治理**（收益确定，2-3 天）
   - 在所有回测报告中增加显眼 banner: `⚠️ 回测使用当前股票池，未排除已退市股票，收益可能被高估`
   - 在 `run_backtest` 返回值增加 `survivorship_bias_warning` 字段
   - smoke test schema 增加对该字段的断言

2. **数据源治理**（中等投入，1-2 周）
   - 调研 TDX 是否提供历史成分股列表（CSI300 等指数有已知的 daily constituent 文件）
   - 对指数回测，使用 `akshare` 获取历史成分股列表并按日期过滤
   - 这部分是量化模型风险而非代码风险，不需要一步到位

3. **量化影响**（持续）
   - 运行对照实验: 对比当前 universe 和 subset（仅沪深300成分股）的回测结果差异
   - 在 docs/ 中记录发现

### 10.3 残留 Lint 清理

750 non-auto-fixable errors，主要分布在 `scripts/` 和 `tests/`。

| 类别 | 数量估计 | 策略 |
|------|---------|------|
| F401 (unused import) | ~400 | 只在 `scripts/` 中的: 批量 `ruff check --fix --unsafe-fixes` |
| F841 (unused variable) | ~200 | 同上 |
| 其他 | ~150 | 逐文件审查 |

**目标**: 不是清到 0（scripts/ 是 research 代码），而是在 `tests/unit/` 和 `tests/contract/` 中清到 0。

**Sprint 10 交付物清单**:
- [ ] CI 新增 contract-test job
- [ ] CI 运行 `pytest tests/unit/ tests/contract/ -v` 全绿（含新合约测试）
- [ ] 所有回测输出包含存活者偏差警告
- [ ] `tests/unit/` 和 `tests/contract/` 中 lint 0 errors
- [ ] 存活者偏差影响对照实验完成，结果记录到 docs/

---

## 总路线图

| Sprint | 主题 | 优先级 | 预估工作量 | 依赖 |
|--------|------|--------|-----------|------|
| **Sprint 8** | 绿色测试 + 合约奠基 | **P0** | 1-2 天 | 无 |
| **Sprint 9** | Research 表面清理 (6b) | **P1** | 3-5 天 | Sprint 8 |
| **Sprint 10** | CI Phase 2 + 存活者偏差 | **P1** | 3-5 天 | Sprint 9 |

**关键路径**: Sprint 8 → Sprint 9 → Sprint 10，因为：
1. 必须先有绿色测试套件，才能信任后续重构
2. Strategy 迁移（Sprint 9）后才能添加有意义的合约测试（Sprint 10）
3. 存活者偏差治理需要策略迁移完成后的稳定基线

**边界条件**:
- 不对 `scripts/` 做全面质量提升 — 它们明确标记为 research-only，QA 覆盖是刻意的
- 不要求在 CI 中运行集成测试（TDX 依赖无法在 GitHub Actions 中满足）
- 存活者偏差不要求完全消除，但必须量化并在输出中显式披露
