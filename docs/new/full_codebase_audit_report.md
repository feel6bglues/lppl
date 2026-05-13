# 全代码库审查报告

> 生成日期: 2026-05-13
> 审查范围: `src/` (69文件) + `scripts/` (92文件) = 161个Python文件
> 审查方式: python-reviewer + security-reviewer + architect + code-reviewer 并行审查
> 测试基线: pytest tests/unit: 176/176 passed | ruff: 1708 errors

---

## 一、总体统计

| 审查维度 | 发现数量 |
|---------|:-------:|
| Python代码质量问题 | 24 (2 CRITICAL + 8 HIGH + 14 MEDIUM) |
| 安全漏洞 | 7 (0 CRITICAL + 2 HIGH + 2 MEDIUM + 3 LOW) |
| 架构设计问题 | 6+ 架构弱点 + 5 优先修复项 |
| 脚本质量问题 | 14 (3 CRITICAL + 4 HIGH + 4 MEDIUM + 3 LOW) |
| **总计** | **~51项** |

---

## 二、Python代码质量 (python-reviewer)

### CRITICAL

| ID | 问题 | 文件 | 行号 |
|----|------|------|:----:|
| PY-01 | 公共函数`validate_input_data`的`df`参数缺少类型标注 | `src/lppl_core.py` | 138 |
| PY-02 | SQLite连接未使用上下文管理器，资源可能泄漏 | `src/storage/database.py` | 17-21 |

### HIGH

| ID | 问题 | 文件 | 行号 |
|----|------|------|:----:|
| PY-03 | `args`参数类型标注不精确 | `src/lppl_core.py` | 158 |
| PY-04 | `process_index_multiprocess`的`df`缺类型标注 | `src/computation.py` | 122 |
| PY-05 | Wyckoff `calculate_wyckoff_return`缺`df`类型标注 | `src/wyckoff/trading.py` | 16 |
| PY-06 | `upsert_data_status`缺返回类型标注 | `src/storage/database.py` | 146 |
| PY-07 | `pd.read_parquet`重复调用8次可提取为helper | `src/data/manager.py` | 多处 |
| PY-08 | 全局可变状态`_worker_dm`竞态风险 | `src/parallel.py` | 22,52,66 |

### MEDIUM

| ID | 问题 | 文件 | 严重级 |
|----|------|------|:-----:|
| PY-09 | 魔法数字(5/20/60天)未提取为常量 | `src/lppl_core.py` | MEDIUM |
| PY-10 | 数据库查询`params`使用`list`而非`List[Any]` | `src/storage/database.py` | MEDIUM |
| PY-11 | 异常处理中logging.debug可能隐藏问题 | `src/lppl_core.py` | MEDIUM |
| PY-12 | `except Exception`过宽 | `src/data/manager.py` | MEDIUM |
| PY-13 | CLI返回类型`dict`应为`Dict[str,str]` | `src/cli/` | MEDIUM |
| PY-14 | 缺少docstring的公共函数 | 多处 | MEDIUM |

---

## 三、安全漏洞 (security-reviewer)

### HIGH

| ID | 问题 | 文件 | 行号 | 说明 |
|----|------|------|:----:|------|
| SEC-01 | **SQL注入**: `limit`参数直接拼接到SQL | `src/storage/database.py` | 251 | `f"SELECT ... LIMIT {limit}"` |
| SEC-02 | **SQL注入**: 同上模式 | `src/storage/database.py` | 282 | 需改为参数化查询`?` |

### MEDIUM

| ID | 问题 | 文件 | 说明 |
|----|------|------|------|
| SEC-03 | 路径遍历: `symbol`直接用于文件名 | `src/wyckoff/state.py`:254 | 需校验symbol格式 |
| SEC-04 | CLI路径未做遍历检查 | `src/cli/generate_optimal8_report.py`:10 | 当前仅本地使用 |

### LOW

| ID | 问题 | 文件 | 说明 |
|----|------|------|------|
| SEC-05 | 动态导入白名单安全但需保持 | `src/cli/main.py`:28-34 | 当前安全 |
| SEC-06 | 硬编码用户路径 | `src/data/incremental_loader.py`:16-17 | 建议环境变量化 |
| SEC-07 | API key从环境变量读取(正确做法) | `src/wyckoff/config.py`:170 | ✅ 良好实践 |

### 安全性检查清单

| 检查项 | 状态 |
|-------|:---:|
| 硬编码密钥 | ✅ 未发现 |
| SQL注入 | ❌ 2处需修复 |
| 命令注入 | ✅ 未使用os.system/subprocess |
| 反序列化 | ✅ 使用yaml.safe_load |
| 路径遍历 | ⚠️ 2处需加固 |
| 文件锁 | ✅ 使用fcntl.flock |

---

## 四、架构设计 (architect)

### 好的设计

| 方面 | 评价 |
|------|------|
| 模块级分离 | ✅ `investment`, `wyckoff`, `data`, `storage` 领域清晰 |
| 异常层次 | ✅ `LPPLException` → 6个子类，层级合理 |
| 配置dataclass | ✅ `LPPLConfig`, `InvestmentSignalConfig` 可注入 |
| 纯函数核心 | ✅ `lppl_core` 纯数值计算，可测试 |
| 常量集中 | ✅ `constants.py` 单一事实来源 |

### 架构弱点

| ID | 问题 | 严重级 | 建议 |
|----|------|:-----:|------|
| ARC-01 | **God Module**: `investment/backtest.py` 800+行混合信号/回测/风控 | 🔴 P0 | 拆分为 SignalGenerator, BacktestEngine, MetricsCalculator |
| ARC-02 | **DI缺失**: DataManager/TDXReader内联实例化，不可mock | 🟠 P1 | 构造函数注入 |
| ARC-03 | **配置重复**: `InvestmentSignalConfig`和`LPPLConfig`字段重叠 | 🟠 P1 | 统一Config基类 |
| ARC-04 | **循环调用**: `lppl_engine.lppl_func()`委托到`lppl_core`再重复实现 | 🟠 P1 | 去重，只留一个实现 |
| ARC-05 | **无抽象层**: 直接函数调用，无interface/contract | 🟡 P2 | 增加 ABC: `IDataProvider`, `ISignalGenerator` |
| ARC-06 | **管道缺失**: 数据流转隐式，不易追踪 | 🟡 P2 | 增加 `Pipeline` 类 |

### 模块耦合图

```
cli/main ─→ data.manager ─→ data.tdx_reader
         ─→ computation ─→ lppl_engine ─→ lppl_core
                          ─→ lppl_multifit
         ─→ reporting.HTMLGenerator
         
investment/backtest ─→ lppl_core (函数级)
                   ─→ lppl_engine (LPPLConfig)
                   ─→ investment/indicators
                   ─→ investment/signal_models
```

---

## 五、脚本代码质量 (code-reviewer)

### CRITICAL

| ID | 问题 | 影响文件数 | 说明 |
|----|------|:--------:|------|
| SCR-01 | **硬编码用户路径** `~/tdxcfv/` | **33+** | 不可移植，需环境变量 |
| SCR-02 | **裸except** `except: pass` 静默失败 | 多处 | 信号生成错误被隐藏 |
| SCR-03 | **重复代码** `fetch_and_align()` 在3个文件中完全一样 | 3 | 需提取到共用模块 |

### HIGH

| ID | 问题 | 说明 |
|----|------|------|
| SCR-04 | 重复的回测函数(`bt()`)分散在多个validate脚本 | 需统一BacktestEngine |
| SCR-05 | `INDICES`字典在10+个文件中重复定义 | 需提取到config |
| SCR-06 | 魔法数字(MA周期/阈值)不命名 | 需常量或dataclass |

### MEDIUM

| ID | 问题 | 说明 |
|----|------|------|
| SCR-07 | 命名不一致(snake_case vs camelCase) | 需统一 |
| SCR-08 | 文件过大: 3个脚本超1000行 | 需拆分 |
| SCR-09 | 多数函数缺类型标注 | 需补充 |
| SCR-10 | 使用`print()`而非logging | 需替换 |

---

## 六、修复优先级矩阵

### Phase 1 — 安全与稳定性 (P0)

| 优先级 | ID | 任务 | 文件 | 预计工时 |
|:-----:|:--:|------|------|:-------:|
| 🔴 P0 | SEC-01 | SQL注入修复: limit参数化 | `storage/database.py:251` | 15min |
| 🔴 P0 | SEC-02 | SQL注入修复: 同上 | `storage/database.py:282` | 15min |
| 🔴 P0 | SCR-01 | 硬编码路径改为环境变量 | 33+脚本 | 2h |
| 🔴 P0 | PY-08 | 全局可变状态修复 | `parallel.py` | 30min |

### Phase 2 — 代码质量 (P1)

| 优先级 | ID | 任务 | 文件 | 预计工时 |
|:-----:|:--:|------|------|:-------:|
| 🟠 P1 | ARC-01 | 拆分God Module | `backtest.py` | 4h |
| 🟠 P1 | PY-07 | 提取parquet读取helper | `manager.py` | 30min |
| 🟠 P1 | SCR-02 | 修复裸except | 多处 | 1h |
| 🟠 P1 | SCR-05 | 提取INDICES到config | 10+文件 | 1h |
| 🟠 P1 | PY-01/03/04 | 补充类型标注 | 多处 | 1h |

### Phase 3 — 架构改善 (P2)

| 优先级 | ID | 任务 | 预计工时 |
|:-----:|:--:|------|:-------:|
| 🟡 P2 | SCR-03 | 创建`scripts/utils/`共用模块 | 2h |
| 🟡 P2 | ARC-02 | DI改造: DataManager可注入 | 3h |
| 🟡 P2 | ARC-03 | 配置统一 | 2h |
| 🟡 P2 | PY-09 | 魔法数字常量 | 1h |

---

## 七、当前基线

```
pytest tests/unit -q:       176/176 passed ✅
ruff check src scripts:      1708 errors ⚠️  (主要E702/E701格式问题)
compileall -q src:           PASS ✅
```

---

## 八、良好实践确认

| 实践 | 状态 | 说明 |
|------|:---:|------|
| 异常层次 | ✅ | `LPPLException` 6子类合理 |
| 环境变量API Key | ✅ | `WYCKOFF_LLM_API_KEY` |
| 配置文件安全加载 | ✅ | `yaml.safe_load()` 非 `yaml.load()` |
| 文件锁定 | ✅ | `fcntl.flock` 保护并发写入 |
| 纯函数可测试核心 | ✅ | `lppl_core` 数值计算 |
| DataFrame验证 | ✅ | 9项指标校验 |
| T+1风控 | ✅ | Wyckoff引擎内置 |
| 交易成本模型 | ✅ | 0.25%回合成本 |
