# 全面修复计划 — CPR-001

生成日期：2026-05-13  
依据文档：`docs/new/lppl_codebase_review.md`  
审查范围：`src/`（57 文件，18,606 行）+ `scripts/`（40 文件，33,761 行）  
审查方式：Python-reviewer + security-reviewer + architect 并行审查

---

## 1. 综述

本次修复基于三个专业 agent 对全部 97 个源文件的并行审查。当前基线：

- `pytest tests/unit`: **176/176 passed**
- `ruff check src`: **0 errors**
- `compileall -q src`: **PASS**

共发现 **46 个问题**，按严重级分布：

| 严重级 | 数量 | 需关闭条件 |
|--------|:----:|-----------|
| 🔴 CRITICAL | 7 | 全部修复 |
| 🟠 HIGH | 11 | 全部修复 |
| 🟡 MEDIUM | 16 | 至少 80% 修复 |
| 🟢 LOW | 12 | 至少 60% 修复 |

---

## 2. 执行原则

- **测试先行**：每个修复后必须 `pytest tests/unit -q` 验证
- **原子化**：每个任务只解决一个问题
- **不扩大范围**：当前周期只修审查出的问题，不做新功能
- **保持向后兼容**：不改变 CLI 接口和报告输出格式

---

## 3. CRITICAL 修复

### CPR-C01 裸 `except Exception:` 精确化

**文件：** `src/lppl_engine.py:278, 348, 383`, `src/lppl_core.py:237`

**问题：** 多处 `except Exception:` 吞掉严重错误（KeyboardInterrupt、MemoryError）：

- `lppl_engine.py:278` — `fit_single_window()`: `except Exception: return None`
- `lppl_engine.py:348` — `fit_single_window_lbfgsb()`: `except Exception: continue`
- `lppl_engine.py:383` — `fit_single_window_lbfgsb()`: `except Exception: return None`
- `lppl_core.py:237` — `fit_single_window_task()`: `except Exception: return None`

**修复方案：**
- 替换为具体异常类型：`(ValueError, TypeError, FloatingPointError)`
- 添加 `logger.debug` 记录失败原因
- 保留 `RuntimeError` 传播（不捕获）

**测试：** `pytest tests/unit/test_lppl_engine_ensemble.py -q`

**风险：** 低。纯数值计算路径，预期异常类型明确。

### CPR-C02 `GLOBAL_EXECUTOR` 改为 contextmanager

**文件：** `src/computation.py:45-69`

**问题：** 全局可变进程池 + `multiprocessing.Lock` 在 fork 模式下失效。

**修复方案：**
- 将 `GLOBAL_EXECUTOR` 改为 `LPPLComputation` 类属性
- 使用 `threading.Lock` 替代 `multiprocessing.Lock`
- 提供 `@contextmanager` 包装确保使用后 shutdown

**测试：** `pytest tests/unit/test_computation_compat.py -q`

**风险：** 中。影响多进程并行路径，需验证回退路径完好。

### CPR-C03 `__import__` 改为 `importlib.import_module`

**文件：** `src/cli/main.py:34`

**问题：** 动态模块导入使用 `__import__`，虽有限制但仍不安全。

**修复方案：**
- 替换为 `importlib.import_module(module_path)`
- 保留 `ENTRYPOINT_ALIASES` 白名单限制

**测试：** 手动验证 CLI 入口：
```bash
.venv/bin/python main.py --help
.venv/bin/python main.py wyckoff --help
```

**风险：** 低。纯 import 机制替换，行为不变。

### CPR-C04 `itertuples` 索引对齐修复

**文件：** `src/investment/backtest.py:324-330`

**问题：** `enumerate(price_df.itertuples())` 在 `generate_investment_signals` 中与 `output_mask` 的索引对齐存在风险：

```python
output_mask_values = output_mask.to_numpy(dtype=bool, copy=False)
for idx, row in enumerate(price_df.itertuples(index=False)):
    if not output_mask_values[idx]:
        continue
```

`output_mask` 基于 `price_df` 的日期过滤创建，使用布尔数组与 `enumerate` 位置索引对应。虽然 `price_df` 经过 `_normalize_price_frame` 后索引连续，但依赖隐式对齐。

注：`run_strategy_backtest` 中另一个 `equity_df.itertuples`（第 888 行）有 `reset_index(drop=True)` 保证，无此问题。

**修复方案：**
- 将日期过滤改为基于 `row.date` 比较，消除索引对齐依赖

**测试：** `pytest tests/unit/test_investment_backtest.py -q`

**风险：** 中。影响信号生成核心循环，需验证 47 个测试全部通过。

### CPR-C05 LLM API Key 只从环境变量读取

**文件：** `src/wyckoff/config.py:139`

**问题：** `config.llm_api_key` 可以从 YAML 加载，提交后泄露风险。

**修复方案：**
- 从 YAML 加载路径中移除 `api_key` 字段
- 强制 `LLMConfig` 只接受环境变量 `WYCKOFF_LLM_API_KEY`

**测试：** `pytest tests/unit/test_wyckoff_models.py -q`

**风险：** 低。不影响无 LLM 功能的路径。

### CPR-C06 LPPL 数值核心去重

**文件：** `src/lppl_engine.py` → 委托 `src/lppl_core.py`

**问题：** `lppl_func`、`cost_function` 在两文件中重复实现。涉及约 **50-60 行** 函数体完全重复（加上 Numba 变体约 90 行）。文件已自认重复：

```python
# lppl_engine.py:131-132
# NOTE: 与 src.lppl_core.lppl_func 为重复实现。等价性已通过测试验证。
```

**修复方案：**
- `lppl_engine.lppl_func` → `return lppl_core.lppl_func(...)`
- `lppl_engine.cost_function` → `return lppl_core.cost_function(...)`
- 保留 `_lppl_func_numba` / `_cost_function_numba` 私有函数
- 等价性测试已存在（`LPPLCoreEquivalenceTests`）

**测试：** `pytest tests/unit/test_lppl_engine_ensemble.py::LPPLCoreEquivalenceTests -v`

**风险：** 中。虽然等价性已验证，但 `lppl_engine` 版本有 try/except 而 `lppl_core` 版本是条件判断。需保留异常回退。

### CPR-C07 `_worker_dm` 初始化竞态修复

**文件：** `src/parallel.py:16-17`

**问题：** `_worker_loaded` 无锁访问，多进程初始化可能重复执行。

**修复方案：**
- 使用 `multiprocessing.Value('i', 0)` 作为初始化标志
- 使用 `multiprocessing.Lock()` 保护初始化块

**测试：** `python3 -c "from src.parallel import get_optimal_workers; print(get_optimal_workers())"`

**风险：** 低。初始化路径，不影响正常计算。

---

## 4. HIGH 修复

### CPR-H01 配置类重复阈值消除

**文件：** `src/investment/backtest.py`, `src/investment/config.py`

**问题：** `InvestmentSignalConfig` 中 `danger_days/warning_days/watch_days` 与 `LPPLConfig` 重复。

**修复方案：**
- `InvestmentSignalConfig` 中的这三个字段直接委托到 `LPPLConfig`
- 保留字段用于向后兼容，但加 deprecated 注解

**测试：** `pytest tests/unit/test_investment_backtest.py -q`

### CPR-H02 `backtest.py` 补充类型标注

**文件：** `src/investment/backtest.py`

**问题：** `_map_single_window_signal`、`_map_ensemble_signal`、`generate_investment_signals` 等缺少类型标注。

**修复方案：**
- 为所有函数补充 `-> Tuple[str, float, str, float]` 等返回类型
- 为参数补充 `Optional[Dict[str, Any]]` 等

**测试：** `python3 -m ruff check src && python3 -m compileall -q src`

### CPR-H03 信号映射去重

**文件：** `src/investment/backtest.py` vs `src/investment/signal_models.py`

**问题：** `_map_single_window_signal` / `_map_ensemble_signal` 在两文件中有重叠逻辑。

**修复方案：**
- 标记 `backtest.py` 中的版本为 deprecated
- 统一使用 `signal_models.py` 中的版本
- `backtest.py` 中的改为委托调用

**测试：** `pytest tests/unit/test_investment_backtest.py -q`

### CPR-H04 优化器超时保护

**文件：** `src/lppl_engine.py:241`

**问题：** `differential_evolution` 无超时保护，单次调用可能卡死 30+ 秒。

**修复方案：**
- 使用 `signal.SIGALRM` 或 `multiprocessing.Timeout` 包裹
- 超时后返回 None 并记录 `track_fit_failure("optimizer_timeout")`

**测试：** `pytest tests/unit/test_lppl_engine_ensemble.py -q`

### CPR-H05 并行 Worker 上限统一

**文件：** `src/computation.py:49-52`, `src/lppl_engine.py:73-75`, `src/parallel.py:23-26`

**问题：** 三个模块各自实现 worker 数量计算，高核环境 OOM 风险。

**修复方案：**
- 统一使用 `src/parallel.py` 中的 `get_optimal_workers(max_workers=8)`
- 移除 `computation.py` 和 `lppl_engine.py` 中的重复实现

**测试：** 验证三个模块仍能正常并行处理

**风险：** 中。影响并行性能，需要验证低核环境回退。

### CPR-H06~H11 其他 HIGH 修复

| 编号 | 问题 | 修复方案 | 主要文件 |
|------|------|---------|---------|
| H06 | 数据未检查价格极端异常 | 新增 `validate_financial_data_sanity()` | `data/manager.py` |
| H07 | 输出路径无校验 | 新增 `validate_output_path()` | `cli/wyckoff_analysis.py` |
| H08 | API 无速率限制 | 循环中添加 `time.sleep(1.0)` | `data/manager.py` |
| H09 | CLI 缺输入校验 | 添加 argparse `type=`/`choices=` | 各 cli 模块 |
| H10 | 行情数据未校验空值传播 | 在 `validate_dataframe` 中增加空值比例限制 | `data/manager.py` |
| H11 | 脚本缺少 `if __name__` 保护 | 为每个可执行脚本添加入口守卫 | `scripts/*.py` |

---

## 5. MEDIUM 修复

| 编号 | 问题 | 文件 | 建议修复 |
|------|------|------|---------|
| CPR-M01 | 缺少 docstring | `tdx_loader.py` | 添加 PEP 257 格式 docstring |
| CPR-M02 | 魔法数字 0.8/0.6/2/1 | `wyckoff/analyzer.py:210` | 提取为命名常量 |
| CPR-M03 | 回测循环 >4 层嵌套 | `backtest_engine.py:72-130` | 提取 `_calculate_trade()` 函数 |
| CPR-M04 | 异常使用不一致 | 多处 | 统一使用 `src/exceptions.py` 中的类型 |
| CPR-M05 | `is None` vs `== None` 混用 | 多处 | 统一为 `is None` |
| CPR-M06 | akshare 状态静默失败 | `manager.py` | 未知状态打印 warning |
| CPR-M07 | 配置无模式校验 | `config/optimal_params.py` | 使用 Pydantic 验证 YAML |
| CPR-M08 | 数据层校验与计算层校验分离 | 多处 | 统一到 `DataValidator` 类 |
| CPR-M09 | 自定义异常未被所有模块使用 | 多处 | 全面采用 `exceptions.py` |
| CPR-M10 | 日志使用 f-string 非延迟插值 | `data/manager.py` | 热路径改为 `%s` 格式 |
| CPR-M11 | `WindowConfig` 硬编码 | `constants.py` | 改为 YAML 可配置 |
| CPR-M12 | yaml.safe_load 无异常处理 | `wyckoff/config.py` | 添加 `try/except` |
| CPR-M13 | `classify_top_phase` 返回字符串而非枚举 | `lppl_engine.py` | 使用 `PhaseLevel` 枚举 |
| CPR-M14 | `_format_output` 返回 List 而非 Dict | `computation.py` | 改为 TypedDict |
| CPR-M15 | tests 中测试数据缺少 `amount` 列 | `test_data_manager_statuses.py` | 补全测试夹具 |
| CPR-M16 | 依赖版本未固定 | `requirements.txt` | 固定主要依赖版本号 |

---

## 6. LOW 修复

| 编号 | 问题 | 建议修复 |
|------|------|---------|
| CPR-L01 | CLI 使用 `print()` | 替换为 `logger.info()` / `click.echo()` |
| CPR-L02 | 长行 >120 字符 | `ruff format` 自动格式化 |
| CPR-L03 | 循环内外重复初始化 | 删除外层死代码 |
| CPR-L04 | 废弃文件引用未清理 | 清理 `lppl_fit.py` 的剩余引用 |
| CPR-L05 | 阴影内置类型名 | 变量重命名 |
| CPR-L06 | 标点符号全角/半角不统一 | 统一为半角 |
| CPR-L07 | 字符串拼接使用 `+` 而非 f-string | 统一为 f-string |
| CPR-L08 | 复数 `s` 单复数不一致 | 变量名规范化 |
| CPR-L09 | 注释混用中英文 | 统一为英文 |
| CPR-L10 | lint ignore 注释冗余 | 清理 `# noqa` |
| CPR-L11 | 未使用的 `__init__.py` | 清理空文件 |
| CPR-L12 | 显式 `import sys` 未被使用 | 清理未使用导入 |

---

## 7. 执行顺序

```
Phase 1 — CRITICAL（约 2h）
  ├── CPR-C05: API key 环境变量（5min，无风险）
  ├── CPR-C03: importlib 替换（5min，低风险）
  ├── CPR-C01: except 精确化（15min，低风险）
  ├── CPR-C04: itertuples 索引修复（15min，中风险）
  ├── CPR-C07: worker 竞态修复（10min，低风险）
  ├── CPR-C02: GLOBAL_EXECUTOR contextmanager（30min，中风险）
  └── CPR-C06: LPPL 核心去重（30min，中风险）
  └── 验证：pytest tests/unit -q → 176 passed

Phase 2 — HIGH（约 3h）
  ├── H01~H06: 配置、类型、超时、并行上限等
  ├── H07~H11: 输入校验、速率限制、if __name__ 等
  └── 验证：pytest tests/unit -q + ruff 0 errors

Phase 3 — MEDIUM（约 4h）
  ├── M01~M06: docstring、魔法数字、嵌套提取
  ├── M07~M12: 配置校验、异常统一、YAML 安全
  └── M13~M16: 枚举返回、TypedDict、测试夹具、版本锁定
  └── 验证：pytest tests/unit -q

Phase 4 — LOW（约 2h）
  ├── L01~L06: print→logger、ruff format、死代码
  ├── L07~L12: 命名规范、注释清理、未使用导入
  └── 验证：ruff check src + compileall
```

---

## 8. Definition of Done

```text
pytest tests/unit -q:      176/176 passed ✅
ruff check src:             0 errors ✅
compileall -q src:           PASS ✅
CRITICAL items fixed:        7/7   ✅
HIGH items fixed:           11/11  ✅
MEDIUM items fixed:         13/16  ✅
LOW items fixed:             8/12  ✅
```

---

## 9. 不做事项

- 不在此阶段重构整个 `generate_investment_signals`（400+ 行）
- 不在此阶段将 CLI 迁移到 Click/Typer
- 不在此阶段引入新的第三方依赖
- 不在此阶段修改 `backtest.py` 的回测策略逻辑（只修缺陷）

---

## 10. 下一步

建议从 **CPR-C05**（API key 环境变量）开始。该任务范围最小、风险最低、收益明确。
