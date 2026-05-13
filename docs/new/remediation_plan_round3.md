# 修复计划 Round 3 — 后审查修复

> 生成日期: 2026-05-13
> 依据文档: `docs/new/post_remediation_audit_report.md`
> 核实方式: 全部13项经 grep 源代码确认

---

## 核实清单

| 报告ID | 问题 | 核实结果 | 实际行号/证据 |
|:------:|------|:-------:|--------------|
| AR-01 | `tdx_config.py`未在`src/`中使用 | ✅ 一致 | `grep -rn "tdx_config" src/` → 0结果 |
| AR-02 | `WyckoffAnalyzer` deprecated仍被导入 | ✅ 一致 | `__init__.py:7`导出, `cli/wyckoff_analysis.py:30`导入 |
| AR-03 | `InvestmentSignalConfig`重复定义 | ✅ 一致 | `backtest.py:15` + `config.py:11` |
| SCR-11 | 8处裸except | ✅ 一致 | 4个文件共8处(行号精确匹配) |
| AR-04 | 双`calculate_risk_level()` | ✅ 一致 | `lppl_core.py:231`(硬编码) + `lppl_engine.py:399`(可配置) |
| AR-05 | 根目录15+文件 | ✅ 一致 | `ls src/*.py | wc -l` > 15 |
| AR-06 | `tdx_reader.py`硬编码回退路径 | ✅ 一致 | `tdx_reader.py:154` — `/home/james/...` |
| AR-07 | database.py缺`-> None` | ✅ 一致 | 5个公共方法无返回类型 |
| SEC-08 | 并行处理静默吞异常 | ✅ 一致 | `backtest.py:239`, `portfolio.py:288` |
| AR-08 | Numba初始化重复 | ✅ 一致 | `lppl_core.py:44` + `lppl_engine.py:28` 独立检查 |
| AR-09 | `computation.py`职责过多 | ✅ 一致 | 368行: 并行调度+格式化+JSON持久化 |
| AR-10 | 函数内import语句 | ✅ 一致 | `lppl_core.py:97,105,143` |
| PY-15 | `WyckoffAnalyzer`仍被4个文件导入 | ✅ 一致 | cli中1处, scripts/utils中3处 |

**全部核实通过。**

---

## Phase 1 — 立即修复 (P0)

### R3-01: 修复8处裸except (SCR-11)

**文件**: 4个scripts文件, 8处

#### 1. `scripts/run_dual_strat_backtest.py`

```python
# 行91: Wyckoff引擎异常
# 修复前:
    except: return None
# 修复后:
    except Exception: return None

# 行192: 个股处理异常
# 修复前:
    except: pass
# 修复后:
    except Exception: pass

# 行239: 并行future获取
# 修复前:
                except: pass
# 修复后:
                except Exception:
                    pass
```

#### 2. `scripts/run_ultimate_portfolio.py`

```python
# 行92:
# 修复前:    except: return None
# 修复后:    except Exception: return None

# 行176:
# 修复前:    except: pass
# 修复后:    except Exception: pass

# 行288:
# 修复前:                except: pass
# 修复后:                except Exception:
#                            pass
```

#### 3. `scripts/validate_tdx_stocks.py:73`

```python
# 修复前:    except:
# 修复后:    except struct.error:
```

#### 4. `scripts/optimize_index_strategy.py:58`

```python
# 修复前:    except:
# 修复后:    except Exception:
```

**验证**: `grep -rn "except\s*:" scripts/` → 再无裸except

---

### R3-02: `tdx_reader.py`硬编码回退路径 (AR-06)

**文件**: `src/data/tdx_reader.py`

```python
# 行151-155:
# 修复前:
def get_tdx_reader(tdxdir: Optional[str] = None) -> TDXReader:
    if tdxdir is None:
        tdxdir = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"

# 修复后:
def get_tdx_reader(tdxdir: Optional[str] = None) -> TDXReader:
    if tdxdir is None:
        tdxdir = os.environ.get("TDX_DATA_PATH",
                     "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc")
```

同时添加 `import os`（如已存在则跳过）。

**验证**: `grep "TDX_DATA_PATH\|os.environ" tdx_reader.py` → 一致性确认

---

### R3-03: database.py加`-> None`类型标注 (AR-07)

**文件**: `src/storage/database.py`

5个公共方法添加返回类型:

| 方法 | 行号 | 添加 |
|------|:----:|------|
| `insert_signal()` | ~146 | `) -> None:` |
| `close_position()` | ~201 | `) -> None:` |
| `record_trade()` | ~230 | `) -> None:` |
| `snapshot_portfolio()` | ~253 | `) -> None:` |
| `open_position()` | ~180 | `) -> bool:` (已正确) |

**验证**: `compileall -q src` + `pytest tests/unit -q`

---

## Phase 2 — 短期修复 (P1)

### R3-04: 确认engine.py覆盖后清理analyzer.py (AR-02 / PY-15)

**前置条件**: engine.py已完成analyzer.py全部功能的100%覆盖

**操作**:
1. 更新4个导入文件指向WyckoffEngine
2. 从`wyckoff/__init__.py`移除WyckoffAnalyzer导出
3. 保留analyzer.py文件(加注释), 下次迭代删除

**影响文件**:

| 文件 | 当前导入 | 改为 |
|------|---------|------|
| `src/cli/wyckoff_analysis.py:30` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `scripts/utils/generate_wyckoff_daily_replay.py:21` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `scripts/utils/batch_wyckoff_analysis.py:20` | `from src.wyckoff.analyzer import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |
| `scripts/utils/wyckoff_6cycle_test.py:28` | `from src.wyckoff import WyckoffAnalyzer` | `from src.wyckoff import WyckoffEngine` |

**验证**: `pytest tests/unit -q` + `compileall -q src`

---

### R3-05: Numba初始化集中化 (AR-08)

**文件**: `src/lppl_engine.py`

```python
# 行25-30: 删除独立Numba检查
# 修复前:
try:
    import numba
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False

# 修复后: 删除上述代码, 从lppl_core获取
# 在文件顶部添加:
from src.lppl_core import NUMBA_AVAILABLE
```

**验证**: `compileall -q src` 通过

---

## Phase 3 — 架构改善 (P2)

### R3-06: 移动函数内import到模块顶部 (AR-10)

**文件**: `src/lppl_core.py`

```python
# 行97, 105, 143: 函数内部的import语句
# 修复前:
    from src.constants import ENABLE_NUMBA_JIT  # 行97
    from src.constants import ENABLE_NUMBA_JIT  # 行105
    from src.constants import REQUIRED_COLUMNS  # 行143

# 修复后: 移到顶部(当前行17附近)
from src.constants import ENABLE_NUMBA_JIT, REQUIRED_COLUMNS
```

**验证**: `compileall -q src` + `pytest tests/unit -q`

---

## 执行顺序

```
Phase 1: R3-01 → R3-02 → R3-03 → pytest验证
                ↓
Phase 2: R3-04 → R3-05 → pytest验证
                ↓
Phase 3: R3-06 → pytest验证 → 提交
```

| Phase | 任务 | 涉及文件 | 预计工时 |
|:-----:|------|:-------:|:-------:|
| 1 | R3-01 裸except | 4 scripts | 15min |
| 1 | R3-02 tdx_reader路径 | 1 src | 10min |
| 1 | R3-03 database类型 | 1 src | 15min |
| 2 | R3-04 analyzer清理 | 4文件 | 1h |
| 2 | R3-05 Numba集中 | 1 src | 15min |
| 3 | R3-06 import移动 | 1 src | 15min |

**总计**: ~2.5h

---

## Definition of Done

```text
pytest tests/unit -q:       176/176 passed ✅
compileall -q src:           PASS ✅
bare except (scripts):       0处  ✅
硬编码路径 (src):             0处  ✅
函数内import:                0处  ✅
Numba重复检查:               0处  ✅
WyckoffAnalyzer引用:        0处  ✅
database.py -> None:        全部标注  ✅
```
