# 全代码库审查修复计划

> 生成日期: 2026-05-13
> 依据文档: `docs/new/full_codebase_audit_report.md`
> 审查范围: `src/` (69文件) + `scripts/` (92文件) = 161个Python文件

---

## 核实清单

本计划每一条修复项均经过对源代码的直接核实。核实结果如下：

| 审查报告ID | 核实方式 | 实际行号/文件 | 是否一致 |
|:----------:|---------|:----------:|:-------:|
| SEC-01 | `grep -n "LIMIT {" storage/database.py` | 251 | ✅ 一致 |
| SEC-02 | `grep -n "LIMIT {" storage/database.py` | 282 | ✅ 一致 |
| SEC-03 | `grep -n "symbol.*replace.*state" wyckoff/state.py` | 254 | ✅ 一致 |
| SEC-06 | `grep -n "/home/james" incremental_loader.py` | 16,17,139 | ✅ 一致(3处) |
| PY-01 | `grep -n "def validate_input_data" lppl_core.py` | 138 `df`无类型 | ✅ 一致 |
| PY-02 | `grep -n "def _connect" database.py` | 16 返回原始连接 | ✅ 一致 |
| PY-03 | `grep -n "def fit_single_window_task" lppl_core.py` | 158 `args: Tuple` | ✅ 一致 |
| PY-04 | `grep -n "def process_index_multiprocess" computation.py` | 122 | ✅ 一致 |
| PY-05 | `grep -n "def calculate_wyckoff_return" trading.py` | 16 | ✅ 一致 |
| PY-06 | `grep -n "def upsert_data_status" database.py` | 116 | ✅ 一致 |
| PY-07 | `grep -c "pd.read_parquet" manager.py` | 8处 | ✅ 一致 |
| PY-08 | `grep -n "_worker_dm\|_worker_loaded" parallel.py` | 20,21,52,60,61,64,66 | ✅ 一致 |
| PY-09 | `grep -n "days_left < " lppl_core.py` | 242,244 (5/20) | ✅ 一致 |
| ARC-01 | `wc -l backtest.py` | 1321行(报告写800+，实际更严重) | ⚠️ 低估 |
| SCR-01 | `grep -c "/home/james/" scripts/*.py` | 33处 | ✅ 一致 |
| SCR-02 | `grep -rn "except\s*:" scripts/*.py` | 20+处 | ✅ 一致 |
| SCR-03 | `grep -rn "fetch_and_align" scripts/*.py` | 3个文件 | ✅ 一致 |
| SCR-05 | `grep -rl "000001.SH.*上证综指" scripts/*.py` | 8个文件 | ✅ 一致 |

**结论：审查报告的全部18项核实均与源代码一致。ARC-01的行数实际为1321行，比报告的"800+"更严重。**

---

## Phase 1 — 安全与稳定性 (P0)

### F-01: SQL注入修复 (SEC-01/02)

**文件**: `src/storage/database.py`

**修复方案**: 将f-string LIMIT改为参数化查询

```python
# 修复前 (line 251):
pd.read_sql(f"SELECT * FROM trades ORDER BY entry_date DESC LIMIT {limit}", conn)

# 修复后:
pd.read_sql("SELECT * FROM trades ORDER BY entry_date DESC LIMIT ?", conn, params=(limit,))
```

```python
# 修复前 (line 282):
pd.read_sql(f"SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT {limit}", conn)

# 修复后:
pd.read_sql("SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT ?", conn, params=(limit,))
```

**验证**: `pytest tests/unit -q` 通过

---

### F-02: 硬编码路径环境变量化 (SEC-06 / SCR-01)

**文件**: `src/data/incremental_loader.py` (3处), 33+个scripts文件

**修复方案**:

`src/data/incremental_loader.py`:
```python
# 修复前 (line 16-17):
SH_DIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/"
SZ_DIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/"

# 修复后:
import os
_TDX_BASE = os.environ.get("TDX_DATA_PATH", "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc")
SH_DIR = f"{_TDX_BASE}/sh/lday/"
SZ_DIR = f"{_TDX_BASE}/sz/lday/"
```

Line 139同理。

scripts文件中的路径（以 `run_dual_strat_wyckoff_ma.py` 为例）：
```python
# 修复前:
CSI300_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")

# 修复后:
import os
_TDX_BASE = Path(os.environ.get("TDX_DATA_PATH", "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"))
CSI300_PATH = _TDX_BASE / "sh" / "lday" / "sh000300.day"
```

**影响范围**: `scripts/run_daily.py`, `scripts/run_dual_strat_*.py`, `scripts/run_tristrat_v6*.py`, `scripts/generate_daily_signals.py`, `scripts/validate_*.py` 等33个文件

**验证**: 环境变量未设置时默认值不变，功能一致

---

### F-03: 全局可变状态修复 (PY-08)

**文件**: `src/parallel.py`

**修复方案**: 用 `threading.Lock()` 保护初始化，确保单次初始化

```python
# 修复前 (line 20-69):
_worker_dm = None
_worker_loaded = False

def worker_init():
    global _worker_dm, _worker_loaded
    ...
    _worker_dm = DataManager()
    _worker_loaded = True

# 修复后:
import threading
_worker_dm = None
_worker_loaded = False
_worker_lock = threading.Lock()

def worker_init():
    global _worker_dm, _worker_loaded
    if _worker_loaded:
        return
    with _worker_lock:
        if _worker_loaded:  # double-check
            return
        _worker_dm = DataManager()
        _worker_loaded = True
```

**验证**: `pytest tests/unit -q` 通过

---

## Phase 2 — 代码质量 (P1)

### F-04: 类型标注补充 (PY-01/03/04/05/06)

**文件与修复**:

| 文件 | 行号 | 修复前 | 修复后 |
|------|:----:|--------|--------|
| `src/lppl_core.py` | 138 | `def validate_input_data(df,` | `def validate_input_data(df: pd.DataFrame,` |
| `src/lppl_core.py` | 158 | `args: Tuple` | `args: Tuple[int, pd.Series, np.ndarray]` |
| `src/computation.py` | 122 | `df` (无类型) | `df: pd.DataFrame` |
| `src/wyckoff/trading.py` | 16 | `df` (无类型) | `df: pd.DataFrame` |
| `src/storage/database.py` | 116 | 无返回类型 | `-> None:` |

**验证**: `python3 -m compileall -q src` 通过

---

### F-05: 裸except修复 (SCR-02)

**文件**: 33+个scripts文件中的20+处裸except

**修复方案**: 替换为具体异常类型 + logging

```python
# 修复前:
except: pass

# 修复后:
except Exception as e:
    logger.debug(f"Signal skipped: {e}")
```

**影响文件**: `run_dual_strat_wyckoff_ma.py`, `run_tristrat_v6*.py`, `run_multistrat_v*.py`, `generate_daily_signals.py` 等

**验证**: `pytest tests/unit -q` 通过

---

### F-06: 提取parquet读取helper (PY-07)

**文件**: `src/data/manager.py`

**修复方案**: 提取 `_read_parquet_file` 方法

```python
# 新增方法:
def _read_parquet_file(self, file_path: str) -> Optional[pd.DataFrame]:
    """从parquet文件读取并标准化DataFrame"""
    if not os.path.exists(file_path):
        return None
    try:
        df = pd.read_parquet(file_path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        is_valid, msg = validate_dataframe(df, os.path.basename(file_path))
        if not is_valid:
            logger.error(f"Parquet validation failed for {file_path}: {msg}")
            return None
        return df
    except Exception as e:
        logger.error(f"Error reading parquet {file_path}: {e}")
        return None
```

然后将8处 `pd.read_parquet` 替换为 `self._read_parquet_file(...)` 调用。

**验证**: `pytest tests/unit -q` 通过

---

### F-07: 路径遍历加固 (SEC-03)

**文件**: `src/wyckoff/state.py:254`

**修复方案**: 校验symbol格式

```python
# 修复前:
state_file = Path(state_dir) / f"{symbol.replace('.', '_')}_wyckoff_state.json"

# 修复后:
import re
if not re.match(r'^[A-Za-z0-9._]+$', symbol):
    return {"error": "Invalid symbol format"}
base_dir = Path(state_dir).resolve()
state_file = base_dir / f"{symbol.replace('.', '_')}_wyckoff_state.json"
if not state_file.resolve().is_relative_to(base_dir):
    return {"error": "Invalid symbol - path traversal detected"}
```

**验证**: `pytest tests/unit -q` 通过

---

## Phase 3 — 脚本治理 (P1-P2)

### F-08: 提取INDICES到共用config (SCR-05)

**新建文件**: `scripts/config_indices.py`

```python
"""共用指数配置"""
INDICES = {
    "000001.SH": "上证综指", "399001.SZ": "深证成指",
    "399006.SZ": "创业板指", "000016.SH": "上证50",
    "000300.SH": "沪深300", "000905.SH": "中证500",
    "000852.SH": "中证1000",
}
```

**影响文件**: 8个validate/run脚本改为 `from scripts.config_indices import INDICES`

**验证**: 导入路径正确

---

### F-09: 提取fetch_and_align到共用模块 (SCR-03)

**新建文件**: `scripts/utils/data_utils.py`

```python
"""共用数据获取工具"""
def fetch_and_align(INDICES, AKSHARE_SYMBOLS):
    """获取并对齐多个指数数据"""
    ...  # 从validate_p1_p2.py:60-75提取
```

**影响文件**: `validate_p1_p2.py`, `validate_costs_walkforward.py`, `validate_large_scale.py` 改为导入

**验证**: 三个文件输出结果一致

---

## Phase 4 — 架构改善 (P2)

### F-10: 魔法数字常量化 (PY-09)

**文件**: `src/lppl_core.py`

```python
# 修复前 (line 242-246):
if days_left < 5: return "极高危 (DANGER)"
elif days_left < 20: return "高危 (Warning)"
elif days_left < 60: return "观察 (Watch)"

# 修复后:
DANGER_DAYS = 5
WARNING_DAYS = 20
WATCH_DAYS = 60

if days_left < DANGER_DAYS: return "极高危 (DANGER)"
elif days_left < WARNING_DAYS: return "高危 (Warning)"
elif days_left < WATCH_DAYS: return "观察 (Watch)"
```

**验证**: `pytest tests/unit -q` 通过

---

### F-11: God Module拆分 (ARC-01) — 暂不执行

**文件**: `src/investment/backtest.py` (1321行)

**现状**: 虽然1321行确实过长，但该文件当前176个测试全部通过，功能稳定。贸然拆分可能引入回归问题。

**建议**: 仅在以下条件满足时执行：
1. 所有Phase 1-3修复完成并验证通过
2. 有完整的集成测试覆盖
3. 拆分为 `signal_generator.py` + `backtest_engine.py` + `metrics.py`

**暂不执行，列为后续计划。**

---

## 执行顺序与验证

```
Phase 1 (安全) ─→ pytest验证 ─→ Phase 2 (质量) ─→ pytest验证 ─→ Phase 3 (脚本) ─→ Phase 4 (架构)
```

| Phase | 任务 | 涉及文件数 | 预计工时 | 验证命令 |
|:-----:|------|:--------:|:-------:|---------|
| 1 | F-01 SQL注入 + F-02 路径 + F-03 竞态 | 3核心+33脚本 | 3h | `pytest tests/unit -q` |
| 2 | F-04 类型 + F-05 裸except + F-06 helper + F-07 遍历 | 10+文件 | 3h | `pytest + compileall` |
| 3 | F-08 INDICES + F-09 fetch_and_align | 11文件 | 2h | `pytest + 手动测试` |
| 4 | F-10 魔法数字 + F-11 God Module(暂缓) | 2文件 | 1h | `pytest tests/unit -q` |

---

## Definition of Done

```text
pytest tests/unit -q:       176/176 passed ✅
ruff check src scripts:      0 critical errors ✅
compileall -q src:           PASS ✅
SQL注入:                     0处 ✅
硬编码路径(src/):            0处 ✅
裸except(scripts/):          <5处 ✅ (仅保留已知安全的)
路径遍历:                    已加固 ✅
```

---

## 不做事项

- 不重构 `backtest.py` (1321行God Module) — 仅列为后续计划
- 不引入新依赖
- 不修改CLI入口接口
- 不修改回测策略逻辑
- 不在本周期内完成DI改造(ARC-02)和配置统一(ARC-03)
