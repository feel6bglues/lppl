# 第二轮全面修复计划 — CPR-002

生成日期：2026-05-13  
依据：第二轮全面审查（python-reviewer + security-reviewer + architect）  
基线：`pytest tests/unit: 176/176`, `ruff: 0 errors`, `compileall: PASS`

---

## 1. 本轮基线对比

| 指标 | 上一轮 | 本轮 | 目标 |
|------|--------|------|------|
| CRITICAL | 7 | **0** ✅ | — |
| HIGH | 11 | **3** | 0 |
| MEDIUM | 16 | **7** | ≤ 3 |
| LOW | 12 | **5** | ≤ 3 |
| 测试通过 | 176 | **176** | 176 |
| Ruff | 0 | **0** | 0 |

---

## 2. 任务总览

| ID | 优先级 | 类型 | 问题 | 主要文件 | 预计耗时 |
|:--:|:------:|:----:|------|---------|:-------:|
| R2-01 | P0 | SEC | API Key CLI 参数移除 | `src/cli/wyckoff_multimodal_analysis.py` | 5min |
| R2-02 | P0 | ARCH | 配置类风险阈值去重 | `src/investment/backtest.py` | 15min |
| R2-03 | P0 | ARCH | 大型函数拆分 — `generate_investment_signals` | `src/investment/backtest.py` | 45min |
| R2-04 | P1 | CODE | `iterrows()` → `itertuples()` 替换 | 22 处，分散多个文件 | 30min |
| R2-05 | P1 | CODE | 魔法数字提取为命名常量 | `lppl_core.py`, `wyckoff/analyzer.py` | 20min |
| R2-06 | P1 | CODE | 公共函数参数校验 | `lppl_engine.py`, `tdx_loader.py` | 20min |
| R2-07 | P1 | ARCH | 深度嵌套降低 | `wyckoff/analyzer.py`, `wyckoff_phase_enhancer.py` | 30min |
| R2-08 | P1 | ARCH | 自定义异常推广使用 | `src/exceptions.py`, 各模块边界 | 20min |
| R2-09 | P2 | SEC | 并发数据更新文件锁 | `src/data/manager.py` | 15min |
| R2-10 | P2 | ARCH | 硬编码路径统一 | `src/constants.py` | 10min |
| R2-11 | P2 | LOW | 死代码 `lppl_fit.py` 清理 | `src/lppl_fit.py` | 5min |
| R2-12 | P2 | LOW | CLI 入口标准化 (argparse) | `src/cli/*.py` | 30min |

---

## 3. P0 任务详案

### R2-01 移除 CLI API Key 参数

**文件：** `src/cli/wyckoff_multimodal_analysis.py:154, 489-490`

**问题：** API Key 可通过 `--llm-api-key` 参数传入，暴露在进程列表和 shell 历史中。

**修复方案：**
- 删除 `parser.add_argument("--llm-api-key", ...)`
- 删除 `if args.llm_api_key: config.llm_api_key = ...`
- API Key 只通过 `WYCKOFF_LLM_API_KEY` 环境变量加载（`wyckoff/config.py:170` 已实现）

**验收命令：**
```bash
.venv/bin/python -m pytest tests/unit -q && ruff check src
```

**风险：** 低。不影响功能路径。

### R2-02 配置类风险阈值去重

**文件：** `src/investment/backtest.py:26-28`

**问题：** `InvestmentSignalConfig` 中 `danger_days/warning_days/watch_days` 与 `LPPLConfig` 重复，实际代码已使用 `lppl_config`。

**修复方案：**
- 保留字段（向后兼容），但将默认值改为从 `LPPLConfig` 读取的委托方式
- 或在字段注释中明确：新代码请使用 `lppl_config` 参数

**验收命令：**
```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q
```

**风险：** 低。仅注释变更，无行为变化。

### R2-03 大型函数拆分 — `generate_investment_signals`

**文件：** `src/investment/backtest.py:~230-830`

**问题：** `generate_investment_signals()` 约 600 行，包含 MA cross ATR、MA convergence、multi-factor 等多个信号模型的逻辑，嵌套分支难以测试。

**修复方案：**
- 提取 `_generate_ma_cross_atr_signals()` — MA cross ATR 模型逻辑
- 提取 `_generate_ma_convergence_signals()` — MA convergence 模型逻辑  
- 提取 `_generate_multi_factor_signals()` — 多因子模型逻辑
- 提取 `_generate_legacy_signals()` — LPPL 基础模型逻辑
- `generate_investment_signals` 只保留调度逻辑 + 公共指标计算

**结构预览：**
```python
def generate_investment_signals(df, ...):
    price_df = _normalize_price_frame(df)
    _compute_common_indicators(price_df, signal_config)
    
    if is_ma_cross_atr:
        return _generate_ma_cross_atr_signals(price_df, signal_config, ...)
    elif is_ma_convergence:
        return _generate_ma_convergence_signals(price_df, signal_config, ...)
    ...
```

**验收命令：**
```bash
.venv/bin/python -m pytest tests/unit/test_investment_backtest.py -q
```

**风险：** 中。涉及核心回测逻辑，需确保 47 个测试全部通过。

---

## 4. P1 任务详案

### R2-04 `iterrows()` → `itertuples()` 替换

**影响范围：** 22 处，分布如下：

| 文件 | 行号 |
|------|------|
| `src/lppl_engine.py` | 603, 616 |
| `src/wyckoff/analyzer.py` | 637 |
| `src/wyckoff/engine.py` | 451, 521, 560, 579, 1095, 1102, 1116, 1150, 1280 |
| `src/wyckoff/rules.py` | 151 |
| `src/investment/backtest_engine.py` | 74 |
| `src/investment/optimized_strategy.py` | 133 |
| `src/investment/factor_combination.py` | 469 |
| `src/investment/group_rescan.py` | 398 |
| `src/cli/lppl_verify_v2.py` | 327, 503 |
| `src/reporting/investment_report.py` | 32, 77 |
| `src/reporting/verification_report.py` | 93 |

**修复方案：**
- 逐处替换 `for idx, row in df.iterrows()` → `for row in df.itertuples()`
- 注意 `itertuples` 是 namedtuple（`.` 访问），非 dict（`[]` 访问）

**验收命令：**
```bash
.venv/bin/python scripts/verify_src_quality.py
```

**风险：** 中。22 处需要逐个验证 column 访问方式变更。

### R2-05 魔法数字提取

**文件：**

| 文件 | 行号 | 魔法数字 | 常量名建议 |
|------|------|---------|-----------|
| `src/lppl_core.py` | 117 | `rmse > 10` | `LPPL_RMSE_THRESHOLD = 10.0` |
| `src/wyckoff/analyzer.py` | 637 | `df.tail(20)` | `LIMIT_MOVE_LOOKBACK = 20` |
| `src/wyckoff/engine.py` | 多处 | `0.05`, `0.8`, `0.6` | 按语义命名 |

**验收命令：**
```bash
.venv/bin/python -m pytest tests/unit -q
```

### R2-06 公共函数参数校验

**文件：** `src/lppl_engine.py:fit_single_window()`, `src/data/tdx_loader.py`

**修复方案：**
- `fit_single_window`: 添加 `close_prices` 非空/非零校验
- `load_tdx_data`: 添加文件路径有效性校验

**验收命令：**
```bash
ruff check src && pytest tests/unit/test_lppl_engine_ensemble.py -q
```

### R2-07 深度嵌套降低

**文件：** `src/wyckoff/analyzer.py`, `src/wyckoff_phase_enhancer.py`

**策略：** 使用 guard clause 提前返回，减少 `if/elif` 层级。

**验收命令：**
```bash
.venv/bin/python -m pytest tests/unit/test_wyckoff_analyzer.py -q
```

### R2-08 自定义异常推广

**文件：** 各模块入口边界

**策略：**
- `src/data/manager.py` 已使用 `DataValidationError` → 推广到 `lppl_engine.py`
- `src/lppl_core.py` 中 `validate_input_data` 使用 `DataValidationError`
- `src/exceptions.py` 中补充缺失类型

**验收命令：**
```bash
python3 -m compileall -q src
```

---

## 5. P2 任务详案

### R2-09 并发数据更新文件锁

**文件：** `src/data/manager.py:299-315`

**策略：** 在 Parquet 写入时添加 `fcntl.flock`（POSIX）或等效机制。

### R2-10 硬编码路径统一

**文件：** `src/constants.py`

**策略：** 确认 `TDX_DATA_DIR` 可以通过环境变量 `LPPL_TDX_DATA_DIR` 覆盖，硬编码路径作为兜底。添加注释说明可覆盖性。

### R2-11 死代码 `lppl_fit.py` 清理

**文件：** `src/lppl_fit.py`

**策略：** 确认无任何导入后删除该文件。

### R2-12 CLI 入口标准化

**文件：** `src/cli/*.py`

**策略：** 统一使用 `argparse.ArgumentParser`，统一 `--help` 输出格式。

---

## 6. 执行顺序

```
Phase 1 — P0（约 1h）
  R2-01: API Key CLI 参数移除（5min）
  R2-02: 配置类阈值去重（15min）
  R2-03: generate_investment_signals 拆分（45min）
  验证：pytest tests/unit/test_investment_backtest.py -q

Phase 2 — P1（约 2h）
  R2-04: iterrows→itertuples（30min，可并行处理）
  R2-05: 魔法数字提取（20min）
  R2-06: 参数校验（20min）
  R2-07: 深度嵌套降低（30min）
  R2-08: 自定义异常推广（20min）
  验证：python3 scripts/verify_src_quality.py

Phase 3 — P2（约 1h）
  R2-09: 文件锁（15min）
  R2-10: 路径统一（10min）
  R2-11: lppl_fit.py 清理（5min）
  R2-12: CLI 标准化（30min）
  验证：python3 scripts/verify_src_quality.py
```

---

## 7. Definition of Done

```text
pytest tests/unit -q:    176/176 passed ✅
ruff check src:             0 errors ✅
compileall -q src:           PASS ✅
P0 items fixed:             3/3   ✅
P1 items fixed:             5/5   ✅
P2 items fixed:             4/4   ✅
```

---

## 8. 不做事项

- 不在此轮重构整个 Wyckoff analyzer/engine 合并（已在 P1 计划中标注为下次迭代）
- 不在此轮替换 CLI 框架（Click/Typer 迁移列为独立项目）
- 不在此轮修改回测策略逻辑本身（只做函数拆分和行为不变的优化）

---

## 9. 建议执行起始

从 **R2-01**（API Key CLI 参数移除）开始，5 分钟完成，零风险，快速建立节奏。
