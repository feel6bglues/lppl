# 技术债务修复日志
**日期**: 2026-04-04  
**目标**: 收敛 LPPL 模块边界，修复规则分裂与兼容路径回归  
**当前口径**: 本文档只记录已核验的事实，不再使用“完全可靠”之类无法证明的表述

---

## 执行摘要

| 项目 | 状态 | 说明 |
|------|------|------|
| `lppl_core` 去主路径化 | 已完成 | 新代码应优先使用 `src.lppl_engine` |
| `backtest.py` 导入收敛 | 已完成 | 不再直接依赖 `src.lppl_core` |
| `computation.py` 导入收敛 | 已完成 | 已加兼容适配，避免任务签名回归 |
| YAML `danger_days: 20` 覆盖清理 | 已完成 | 当前 `optimal_params.yaml` 已删除该覆盖 |
| 脚本分层说明 | 已完成 | `scripts/README.md` 已补充分类说明 |
| 全量测试 | 通过 | `110 passed` |
| Ruff | 通过 | `All checks passed!` |

**当前结论**:

- 核心主路径已经进一步收敛到 `src.lppl_engine`
- 遗留模块仍然存在，但已被明确标注角色
- 老计算链 `src.computation` 的签名回归已补上兼容层

---

## 一、已完成修复

### 1. `lppl_core.py` 标记为内部兼容模块

**现状**:

- 模块头部已明确标记 `INTERNAL MODULE - DO NOT IMPORT DIRECTLY`
- 模块加载会发出 `DeprecationWarning`
- `__all__ = []`

**说明**:

这一步的目标不是“删除 `lppl_core`”，而是把它从公共主入口降级为**兼容层**。

**重要说明**:

`lppl_core.py` 当前并不是“所有函数都重定向到 `lppl_engine`”。

实际情况是：

- 已重定向：
  - `lppl_func()`
  - `cost_function()`

- 仍保留本地实现：
  - `validate_input_data()`
  - `fit_single_window_task()`
  - `calculate_risk_level()`
  - `detect_negative_bubble()`
  - `calculate_bottom_signal_strength()`

所以，正确表述应是：

> `lppl_core.py` 已被降级为兼容层，但尚未完全变成纯转发模块。

---

### 2. `backtest.py` 导入统一到 `lppl_engine`

**修复前**:

- 同时从 `lppl_core` 与 `lppl_engine` 取函数

**修复后**:

- [`src/investment/backtest.py`](/home/james/Documents/Project/lppl/src/investment/backtest.py) 已统一从 `src.lppl_engine` 导入：
  - `LPPLConfig`
  - `calculate_bottom_signal_strength`
  - `classify_top_phase`
  - `detect_negative_bubble`
  - `process_single_day_ensemble`
  - `scan_single_date`

**结果**:

主回测路径不再直接依赖 `lppl_core`。

---

### 3. `computation.py` 导入统一，并补上签名兼容层

**修复前问题**:

`src.computation` 历史上使用的是旧任务格式：

```python
(window_size, dates_series, prices_array)
```

而统一后的 `src.lppl_engine.fit_single_window()` 签名是：

```python
fit_single_window(close_prices, window_size, config=None)
```

如果直接把旧 `task` 三元组传进去，会发生参数错位。

**修复方式**:

新增兼容函数：

- [`src/computation.py`](/home/james/Documents/Project/lppl/src/computation.py) 中的 `_fit_single_window_compat()`

它负责：

1. 解包旧三元组任务
2. 按新签名调用 `fit_single_window(prices_array, window_size)`
3. 将结果补齐为旧输出链期望的字段：
   - `window`
   - `last_date`

**结果**:

`src.computation` 已完成导入收敛，同时不再破坏旧调用路径。

---

### 4. YAML 中 `danger_days: 20` 覆盖清理

**修复前**:

多个 symbol 在 [`config/optimal_params.yaml`](/home/james/Documents/Project/lppl/config/optimal_params.yaml) 中显式覆盖：

```yaml
danger_days: 20
```

这会与当前代码默认风险口径冲突。

**修复后**:

当前 `config/optimal_params.yaml` 中已删除这些 `danger_days: 20` 覆盖项。

**结果**:

运行时不再被旧 YAML 风险阈值强行拉回旧口径。

---

### 5. `scripts/README.md` 已补充脚本分类说明

当前脚本目录已按下列角色标注：

- Active
- Experimental
- Legacy

这不是功能修复，但能降低新人误用遗留脚本的概率。

---

## 二、验证结果

### 1. 全量测试

```bash
PYTHONPATH=. .venv/bin/pytest -q
110 passed in 8.58s
```

### 2. 单元测试

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/unit
98 passed in 4.95s
```

### 3. 集成测试

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/integration
10 passed in 5.33s
```

### 4. 静态检查

```bash
.venv/bin/ruff check src tests *.py
All checks passed!
```

### 5. 新增的兼容性测试

新增测试文件：

- [`tests/unit/test_computation_compat.py`](/home/james/Documents/Project/lppl/tests/unit/test_computation_compat.py)

覆盖内容：

- 旧三元组任务能被正确转换为 `fit_single_window(close_prices, window_size)`
- 结果会补齐 `window` 与 `last_date`
- engine 返回 `None` 时兼容层也返回 `None`

---

## 三、当前模块边界结论

### `src/lppl_engine.py`

**角色**: 主公共 API 源

建议新代码优先从这里导入。

### `src/lppl_core.py`

**角色**: 已降级的内部兼容层

可以保留用于历史路径兼容，但不应再作为新增功能的依赖入口。

### `src/computation.py`

**角色**: 老扫描主程序链路

当前仍有实际入口 [`src/cli/main.py`](/home/james/Documents/Project/lppl/src/cli/main.py) 使用它，因此它不是死代码。  
后续如果要继续收敛模块边界，需要为它补更多直接测试，而不是仅依赖全量回归兜底。

---

## 四、这次没有完成的事

以下事项没有被宣称为“已彻底解决”：

1. `lppl_core.py` 尚未完全变成纯转发模块
2. README / 使用文档 / HTML 展示 / CLI 文案中的旧风险口径并未在本日志对应修复中一起收口
3. `backtest.py` 超大文件问题仍然存在
4. 遗留脚本仍然保留，仅增加说明，未做统一迁移

---

## 五、修复后应如何表述

不建议再使用：

- “系统达到完全可靠、可用状态”
- “所有公共函数已重定向”
- “单元测试 108 passed”

更准确的表述应为：

> 本轮技术债修复已完成 LPPL 主路径导入收敛、YAML 旧阈值覆盖清理、`src.computation` 兼容适配和脚本分层说明补充；  
> 当前全量测试和静态检查通过，但项目仍保留兼容层与遗留模块，尚未完成所有结构性债务清理。

---

## 六、修改文件

- [`src/lppl_core.py`](/home/james/Documents/Project/lppl/src/lppl_core.py)
- [`src/lppl_engine.py`](/home/james/Documents/Project/lppl/src/lppl_engine.py)
- [`src/investment/backtest.py`](/home/james/Documents/Project/lppl/src/investment/backtest.py)
- [`src/computation.py`](/home/james/Documents/Project/lppl/src/computation.py)
- [`config/optimal_params.yaml`](/home/james/Documents/Project/lppl/config/optimal_params.yaml)
- [`scripts/README.md`](/home/james/Documents/Project/lppl/scripts/README.md)
- [`tests/unit/test_computation_compat.py`](/home/james/Documents/Project/lppl/tests/unit/test_computation_compat.py)

---

## 七、最终结论

这轮修复的有效成果是：

- 主路径进一步向 `lppl_engine` 收敛
- 旧 YAML 风险覆盖被清掉
- `src.computation` 的签名回归已修复
- 全量测试、分项测试和 Ruff 当前通过

当前更合理的结论不是“完全收敛”，而是：

> 技术债修复已经进入“可验证收口阶段”，主回归已被压住，但仍存在文档口径统一、兼容模块清理和超大文件拆分等后续工作。
