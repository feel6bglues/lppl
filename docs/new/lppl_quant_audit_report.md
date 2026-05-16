# LPPL 量化系统深度审计报告

> 生成日期: 2026-05-16
> 审计范围: 全代码库量化正确性、代码质量、测试体系、可复现性、基础设施
> 方法: 两轮独立分析 + 源代码逐行核实

---

## 0. 执行摘要与风险评级

| 评级 | 意义 |
|------|------|
| CRITICAL | 导致回测指标不可信，必须立即修复 |
| HIGH | 严重影响系统可靠性，应尽快修复 |
| MEDIUM | 降低开发效率和可维护性 |
| LOW | 建议项，长期改进 |

**综合评级: EXPLORATORY — 当前产出不可用于实盘资本配置决策**

核心风险链: look-ahead bias (3处) + survivorship bias + 费用缺失 → 回测收益始终偏乐观 → 夏普比率、胜率等指标不可信 → 无法区分真实 alpha 和偏差收益

**报告范围**: 全代码库审计, 附录 A 共记录 35 项发现（CRITICAL×5, HIGH×13, MEDIUM×14, LOW×3）

---

## 1. CRITICAL: Look-Ahead & Survivorship Bias

### 1.1 未来数据参与 ATR 计算

- **文件**: `scripts/backtest_core.py:130-139`
- **证据**: `f = df[df["date"] > a].head(mh)` 提取了入场日期之后的数据，第139行 `atr = calc_atr(pd.concat([hist, f.head(20)]), 20)` 将未来 bar 与历史数据拼接后计算 ATR
- **影响**: ATR 在入场时刻就"知道"未来20天的波动率，止损/止盈距离被系统性低估，策略夏普被高估
- **修复**: ATR 应只从历史数据计算，移除 `f.head(20)`

### 1.2 Same-Bar Execution

**位置 A**: `src/investment/backtest.py:1190-1195`
- `equity_df` 的信号列（如 `target_position`）在传入前已用该行数据计算
- 信号已知该日收盘信息，但执行以该日开盘价成交，产生系统性乐观偏差
- **修复**: 信号必须基于 `t-1` 数据，执行在 `t` 的开盘 (t+1 convention)

**位置 B**: `src/execution/simulator.py:42-48`
- `run_daily` 接收的信号可能包含当天数据，但立即以当天开盘价执行
- **修复**: 信号和数据必须有明确的时间界限，执行延迟到下一 bar

### 1.3 Survivorship Bias

- **文件**: `scripts/backtest_core.py:37-51`
- **证据**: `load_stocks` 读取 `data/stock_list.csv` (当前5200只股票) 并应用到所有历史窗口。A股历史上已退市的股票被完全排除
- **影响**: 退市股往往是跌幅最大的股票。排除它们使策略回测表现系统性偏上
- **修复**: 使用数据快照时间点的 universe，或使用历史成分股列表

---

## 2. CRITICAL: Blocking Runtime Bugs

### 2.1 Wyckoff 分析器 TypeError 崩溃

- **文件**: `src/wyckoff/analyzer.py:632-674`
- **证据**: `itertuples()` 返回 `namedtuple` 但代码使用字典索引：`row["high"]` (line 646), `row["open"]` (line 646-647), `row["volume"]` (line 664), `row["close"]` (line 670), `row["date"]` (line 668)
- **影响**: `_detect_limit_moves` 运行时崩溃，导致 13/22 个集成测试失败 (59%)
- **修复**: `row["high"]` → `row.high`, `row["open"]` → `row.open`, 以此类推

### 2.2 模块导入顺序不规范
- **文件**: `src/lppl_core.py:2,41,139,158`

- **严重度**: MEDIUM (非阻断)

- **证据**: `import numpy as np` 出现在函数定义之后 (行41). `validate_input_data(df: pd.DataFrame, ...)` 在行139使用 `pd` 注解. 但文件头有 `from __future__ import annotations` (PEP 563), 所有注解为惰性字符串, 不会导致运行时崩溃. (已验证: `import_ok True`)

- **影响**: 类型检查器 (mypy/pyright) 报错, 但不是阻断性 bug

- **修复**: 将所有 import 移至文件顶部

## 3. HIGH: 核心算法缺陷

### 3.1 R² 无 clamp (classify_top_phase 默认阈值 0.5 部分缓解)

- **文件**: `src/lppl_engine.py:257-259`
- **证据**: `r_squared = 1 - (ss_res / ss_tot)` 未 clamp。负 R² 意味着模型比取均值更差
- **修复**: `r_squared = max(0.0, 1 - ss_res / ss_tot)`

### 3.2 DE 优化器固定随机种子

- **文件**: `src/lppl_core.py:206` — `seed=42`
- **影响**: 每次运行找到相同的局部最优，无法探索参数空间
- **修复**: 实施多起点策略：用不同种子运行 3-5 次取最优

### 3.3 集成(Ensemble)共识阈值过低

- **文件**: `src/lppl_engine.py:71` — `consensus_threshold: float = 0.15`
- **影响**: 默认 3 个窗口，0.15 意味着仅 1 个窗口通过即可触发信号
- **修复**: 提高到 `0.5`（多数同意）

### 3.4 方向共识仅用 b 参数

- **文件**: `src/lppl_engine.py:901-904`
- **证据**: 仅用 b 参数的符号判定泡沫方向。LPPL 模型的泡沫形态由 b, c, m, ω 共同决定
- **修复**: 增加综合判定：`b < 0 AND m in [0.1, 0.9] AND |c| > threshold`

### 3.5 Walk-Forward 标签定义缺陷

- **文件**: `src/verification/walk_forward.py:13-22`
- **问题**: "未来60天内跌幅>10%"作为成功标签。不校验预测 tc 与实际底部的时间差和幅度误差
- **修复**: 增加时间对齐度量和幅度误差度量

---

## 4. HIGH: Execution Realism 不足

### 4.1 模拟器无交易费用

- **文件**: `src/execution/simulator.py:68,115`
- **证据**: `execute_buy`: `self._cash -= cost` — 无买入费用。`check_stops`: `self._cash += proceeds` — 无卖出费用
- **影响**: A 股有 0.1% 印花税（卖出单边）+ ~0.025% 佣金。高频策略被系统性高估
- **修复**: 加入对称费用模型

### 4.2 流动性约束默认关闭

- **文件**: `src/investment/backtest.py:127-129`
- **证据**: `enable_limit_move_constraint: bool = False`, `suspend_if_volume_zero: bool = False`
- **修复**: 默认启用涨跌停约束

### 4.3 止盈止损假设精确成交

- **文件**: `scripts/backtest_core.py:155-187`
- **严重度**: HIGH
- **证据**: 在 `f.iterrows()` 中假设 `if lo <= ss: ep = ss` — 精确成交在止损价。无缺口穿越模型, 无部分成交, 无订单优先级
- **修复**: 加入缺口穿越逻辑: 若 `lo <= sl < hi` 则成交; 若 `hi < sl` 则在下一个开盘价成交

### 4.4 缺失日期回退到最新数据行

- **文件**: `src/execution/simulator.py:41,44`

- **严重度**: HIGH

- **证据**: `execute_buy` 按传入 date 查找数据: `day_data = df[df["date"] == target_date]` (行42). 若日期不存在 (如节假日或未来日期), 回退到 `df.tail(1)` (行44), 返回最新可用数据行

- **影响**: 如果信号日期匹配不到数据（含未来日期场景）, 可能使用未来数据进行交易, 构成数据泄漏风险

- **修复**: 当目标日期无匹配数据时, 不应执行交易, 或应明确 fail/skip

---

## 5. HIGH: 可复现性不足

### 5.1 数据库持久化跨运行

- **文件**: `src/storage/database.py:11` (`data/trading.db`), `src/execution/simulator.py:23-25` (从 DB 恢复资金)
- **影响**: 第二次运行从第一次运行结束的状态继续
- **修复**: 使用 run-specific DB 路径或 in-memory DB

### 5.2 数据源版本不固定

- **文件**: `src/data/manager.py:476-479`
- **证据**: 通达信本地文件是可变数据源，两次相同参数运行可能因 TDX 数据更新而产生不同结果
- **修复**: 支持数据快照 pinning，记录数据文件哈希/修改时间

### 5.3 回测元数据记录不完整

- **文件**: `scripts/backtest_core.py:420-445`
- **证据**: 记录种子但不记录实际采样的窗口列表、universe 成员列表、数据文件路径和哈希
- **修复**: 扩展 reproducibility 字典包含完整元数据

---

## 6. MEDIUM: 测试体系缺陷

### 6.1 13 个集成测试因阻断性 Bug 失败

- 13/22 集成测试 FAIL，根本原因是 Bug 2.1 (analyzer.py namedtuple 误用)

### 6.2 核心数学逻辑无直接测试

- LPPL 函数与解析解一致性验证、参数边界条件、数值稳定性（NaN/Inf）、R² 正确性、优化器收敛性均无直接测试

### 6.3 测试过度依赖 Mock

- 95%+ 的测试使用 heavy mocking，无法发现模块间集成问题

### 6.4 测试基础设施缺失

- `pytest-cov` 未安装，`pytest` 不在 `requirements.txt`，fixture 仅 3 个用例

### 6.5 Smoke 测试不检查子进程退出码

- **文件**: `tests/unit/test_backtest_cli.py:50-60`
- `assert fp.exists()` 仅检查产物存在，不检查 `result.returncode`
- **修复**: 加入 `assert result.returncode == 0`

### 6.6 集成测试不在默认 pytest 路径

- **文件**: `pytest.ini:5` — `testpaths = tests/unit`
- **修复**: 将 integration tests 加入默认路径

---

## 7. MEDIUM: 代码质量与架构

### 7.1 1263 个 Lint 错误

- `ruff check .` 报告 1263 个错误，527 个可自动修复
- 主要类别: F541 (无插值 f-string ~500+), I001 (导入顺序 ~100+), F401 (未用导入 ~200+), E712 (True/False 比较 ~50+)

### 7.2 Numba 函数代码重复

- `src/lppl_core.py:77-92,122-136` + `src/lppl_engine.py:96-124,134-157`
- 两个文件各定义一次 `_lppl_func_numba` 和 `_cost_function_numba`

### 7.3 Python 循环未向量化

- `src/lppl_engine.py:344-369` — Peak detection 使用显式 Python 循环
- 优化: 替换为 `pd.Series(close).rolling().max()`

### 7.4 架构边界模糊
**统计口径**: 全仓库 `*.py` 文件中的 `sys.path.insert` 调用, 排除 `.venv/`, `__pycache__/`, `.git/`。包含 `archive/`, `unused/`, `scripts/tuning/`, `scripts/utils/` 等全部子目录
- **sys.path 手术**: 全仓库共 **101 处** `sys.path.insert`, 分布在 scripts/ (52处), scripts/archive/ (10处), scripts/tuning/ (11处), scripts/utils/ (10处), unused/ (7处), 根目录 (5处), tests/ (4处), src/cli/ (2处)。影响 PyInstaller 打包, pytest 隔离, mypy 静态分析
- **修复**: 统一安装为 package 或通过 `PYTHONPATH` 约定


## 8. MEDIUM: 基础设施与运维

### 8.1 全局 Warning 抑制

- `src/lppl_engine.py:37`, `src/cli/lppl_verify_v2.py:32` — 全局 `warnings.filterwarnings("ignore")`

### 8.2 硬编码机器特定路径

- `src/constants.py:44-46`, `config/trading.yaml:3-6` — 4 处包含 `/home/james/.local/share/tdxcfv/...`

### 8.3 Runtime Artifacts 耦合到版本管理

- `.gitignore:17-32` — 通过 4 条否定模式选择性 re-include output 文件，测试依赖被跟踪的产物

### 8.4 Metric 语义不一致

- `src/storage/database.py:253-276` — `total_pnl` 实际存储的是与上一快照的差值 (delta)，而非累计总 PnL

### 8.5 无 CI Pipeline

- `.github/workflows/` 不存在

---

## 9. LOW: 代码风格与维护性

| 问题 | 位置 | 说明 |
|------|------|------|
| 全局可变状态 | `src/lppl_engine.py:934` | `config = DEFAULT_CONFIG` 模块级赋值 |
| 魔术数字 | 多处 | RMSE_THRESHOLD, bounds 无文献依据 |
| Backtest 配置 70+ 字段 | `src/investment/backtest.py:42-200+` | 部分与 LPPLConfig 重复 |
| 无 benchmark 对比 | — | LPPL 仅与自身比较 |
| 文档字符串不完整 | `src/lppl_engine.py` | 关键函数缺少文档 |

---

## 10. 优先修复路线图

### Week 1 — 量化正确性冲刺 (1-2天)
1. `scripts/backtest_core.py:139` — 移除未来 bar ATR (5行)
2. `src/investment/backtest.py:1190` — 改为 t+1 执行 (10行)
3. `src/execution/simulator.py:42` — 信号/执行时间界限 (10行)
4. `scripts/backtest_core.py:37` — universe 限定到快照时间 (15行)
5. `src/execution/simulator.py:68,115` — 对称费用 (5行)
6. `src/investment/backtest.py:127` — 默认启用流动性约束 (1行)
7. `src/wyckoff/analyzer.py:646` — namedtuple 访问修复 (5行)
8. `src/lppl_core.py:2` — import 顺序修复 (5行)

### Week 2 — 核心算法修复 (2-3天)
1. `src/lppl_engine.py` — R² clamp (2行)
2. `src/lppl_core.py` — DE 多起点 (15行)
3. `src/lppl_engine.py` — 共识阈值 0.15→0.5 (1行)
4. `src/lppl_engine.py` — 综合方向判定 (20行)
5. `src/verification/walk_forward.py` — 时间对齐度量 (30行)
6. `ruff check --fix .` (批量)
7. 消除重复 numba 函数 (10行)

### Week 3 — 可复现性与测试基建 (2天)
1. `database.py` — run-specific DB 路径 (10行)
2. `manager.py` — 数据源版本固定 (20行)
3. `backtest_core.py` — 完整元数据记录 (15行)
4. `test_backtest_cli.py` — 加退出码检查 (1行)
5. `pytest.ini` — 包含集成测试 (1行)
6. 核心 LPPL 数学正确性测试 (5+ 个)
7. pytest-cov + coverage 门槛
8. 添加 GitHub Actions CI

### Week 4 — 架构清理 (2-3天)
1. src/cli 仅做路由 (sys.path 统一)
2. 消除 sys.path 手术
3. 局部 warning 过滤
4. 统一环境变量合约
5. output 测试用 temp dir
6. total_pnl 语义修正
7. Backtest 配置类拆分

---

## 附录 A: 全部发现与源代码映射

| 发现 | 文件:行号 | 严重度 |
|------|-----------|--------|
| 未来 ATR | `scripts/backtest_core.py:130,139` | CRITICAL |
| Same-bar (backtest) | `src/investment/backtest.py:1190-1195` | CRITICAL |
| Same-bar (simulator) | `src/execution/simulator.py:42-48` | CRITICAL |
| Survivorship bias | `scripts/backtest_core.py:37-51` | CRITICAL |
| namedtuple 误用 | `src/wyckoff/analyzer.py:646-674` | CRITICAL |
| Import 顺序不规范 | `src/lppl_core.py:41,139,158` | MEDIUM |
| R² 负值 | `src/lppl_engine.py:257-259` | HIGH |
| DE 固定种子 | `src/lppl_core.py:206` | HIGH |
| 共识阈值过低 | `src/lppl_engine.py:71` | HIGH |
| 方向判定仅用 b | `src/lppl_engine.py:901-904` | HIGH |
| Walk-forward 标签 | `src/verification/walk_forward.py:13-22` | HIGH |
| 无交易费用 | `src/execution/simulator.py:68,115` | HIGH |
| 流动性约束默认关 | `src/investment/backtest.py:127-129` | HIGH |
| 假设精确成交 | `scripts/backtest_core.py:155-187` | HIGH |
| 缺失日期回退尾行 | `src/execution/simulator.py:41,44` | HIGH |
| DB 跨运行 | `src/storage/database.py:11` | HIGH |
| 从 DB 恢复资金 | `src/execution/simulator.py:23-25` | HIGH |
| 数据源不固定 | `src/data/manager.py:476-479` | HIGH |
| 元数据不完整 | `scripts/backtest_core.py:420-445` | HIGH |
| 13 集成测试失败 | `tests/integration/` | MEDIUM |
| 不检查子进程码 | `tests/unit/test_backtest_cli.py:60` | MEDIUM |
| 集成测试不在路径 | `pytest.ini:5` | MEDIUM |
| 1263 lint 错误 | 全仓库 | MEDIUM |
| Numba 代码重复 | `lppl_core.py` + `lppl_engine.py` | MEDIUM |
| 未向量化循环 | `src/lppl_engine.py:344-369` | MEDIUM |
| 架构边界模糊 | `scripts/` + `src/cli/` | MEDIUM |
| sys.path 手术（共101处） | 全仓库含 archive/tuning/unused/scripts/tests | MEDIUM |
| 全局 warning 抑制 | `lppl_engine.py:37` + `lppl_verify_v2.py:32` | MEDIUM |
| 硬编码路径 | `constants.py:44-46`, `trading.yaml:3-6` | MEDIUM |
| Artifacts 耦合 | `.gitignore:17-32` | MEDIUM |
| total_pnl 语义错误 | `storage/database.py:253-276` | MEDIUM |
| 无 CI | `.github/workflows/` 不存在 | MEDIUM |
| 全局可变状态 | `src/lppl_engine.py:934` | LOW |
| 魔术数字 | 多处 | LOW |
| Backtest 配置 70+ 字段 | `backtest.py:42-200+` | LOW |

---

## 附录 B: 测试运行日志（确认）

```
单元测试: 163 run, 1 FAILED (test_cli_warning_filters_are_targeted) — 已验证环境: .venv (Python 3.12), 2026-05-16
集成测试: 22 run, 13 ERROR (TypeError from analyzer.py:646) — 已验证环境: .venv (Python 3.12), 2026-05-16
Lint: 1263 errors found (527 auto-fixable via ruff --fix) — 已验证环境: ruff via .venv, 2026-05-16
Coverage: 不可用 (pytest-cov 未安装)
CI:       不存在
```
