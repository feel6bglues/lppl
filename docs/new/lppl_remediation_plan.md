# LPPL 量化系统修复与工程化计划

> 基于 `docs/new/lppl_quant_audit_report.md` (2026-05-16) 的 35 项发现制定的工程化修复方案
> 目标: 从 research platform → production-grade quant trading system

---

## 0. 项目设计方向复核

### 0.1 当前架构诊断

```
顶层入口 (10+ wrapper .py)      ← 历史遗留, 耦合度高
    │
    ├── src/cli/ (9 模块)       ← 包含业务逻辑和 sys.path, 不是纯路由
    │
    ├── src/ (60 模块)          ← 实际引擎, 但边界模糊
    │   ├── lppl_core/engine    ← LPPL 泡沫检测核心
    │   ├── wyckoff/ (12 模块)  ← 威科夫分析 (最大子系统)
    │   ├── investment/ (10 模块) ← 回测与信号
    │   ├── execution/          ← 模拟器
    │   ├── storage/            ← 持久化
    │   ├── data/               ← 数据管理
    │   └── reporting/          ← 报告生成
    │
    ├── scripts/ (95 脚本)      ← research 代码 (生产逻辑散落其中)
    │
    └── tests/
        ├── unit/ (163 tests, 1 FAIL)
        └── integration/ (22 tests, 13 ERROR)
```

### 0.2 设计方向评估

| 维度 | 当前状态 | 目标状态 |
|------|---------|---------|
| **量化正确性** | 3 条 look-ahead 路径, survivorship bias, 费用缺失 | 零前瞻偏差, 完整费用模型, 可审计 |
| **模块边界** | scripts/ 含持久性策略逻辑, src/cli 含业务逻辑 | scripts/ 仅 disposable research, src/ 为 production 边界 |
| **可复现性** | 跨运行 DB 污染, 可变数据源, 元数据不足 | run-id 隔离, 数据版本 fixed, 全元数据记录 |
| **测试** | 13/22 集成测试 FAIL, coverage 不可用, output/ 耦合 | 全部测试通过, coverage ≥ 80%, 隔离的 fixture |
| **工程基建** | 无 CI, 硬编码路径, 全局 warning 抑制, 101 处 sys.path | CI pipeline, 环境变量合约, 局部 warning, 单一入口 |

### 0.3 核心设计原则

1. **t+1 执行公约**: 信号永远基于截至昨日的数据, 交易在今日开盘执行
2. **隔离执行**: 每次回测 = 独立 DB + 固定数据快照 + 完整元数据
3. **费用透明**: 买卖对称费用 + 印花税 + 滑点, 默认启用
4. **窄接口宽实现**: 模块间通过 dataclass/Protocol 通信, 实现可替换
5. **测试即文档**: 核心路径必须有测试, 测试不依赖 output/ 产物

---

## 1. Sprint 1: 量化正确性修复 (最高优先级)

> 目标: 消除所有 look-ahead, survivorship bias, 费用缺失
> 工期: 2 天
> 验证: 修复后跑 smoke test, 确认回测收益显著低于修复前

### 1.1 修复未来 ATR (scripts/backtest_core.py:139)

**当前代码**:
```python
f = df[df["date"] > a].head(mh)           # 未来数据
atr = calc_atr(pd.concat([hist, f.head(20)]), 20)  # 未来 bar 参与 ATR 计算
```

**修复方案**:
```python
# ATR 只从历史数据计算
atr = calc_atr(hist.tail(60), 20) if len(hist) >= 60 else entry * 0.02
```

**验收标准**:
- [ ] `trade_wyckoff` 不再引用 `df[df["date"] > a]` 计算 ATR
- [ ] ATR 值仅基于 `as_of_date` 之前的数据
- [ ] 修复前后的回测结果存在可解释的系统性差异 (偏差路径已被删除)
- [ ] Monte Carlo bootstrap 下超额收益的统计显著性重新评估

**测试**:
- 单元测试: 构造已知波动率的历史数据, 验证 `calc_atr` 输出与手动计算一致
- 回归测试: 在固定数据集上运行修复前后的回测, 检查结果存在可解释的系统性差异, Monte Carlo bootstrap 下超额收益的统计显著性重新评估

### 1.2 修复 Same-Bar Execution (src/investment/backtest.py:1190)

**当前代码**:
```python
for row_idx, row in enumerate(equity_df.itertuples(...)):
    execution_base_price = float(row.open if ... else row.close)
```

**修复方案**: 信号生成与执行分离
```python
# 信号生成阶段 (shift signals forward by 1 bar)
signal_df["target_position_tomorrow"] = signal_df["target_position"].shift(1)

# 执行阶段 (t+1)
for row_idx, row in enumerate(equity_df.itertuples(...)):
    target = row.target_position_tomorrow  # 基于昨日数据的信号
    execution_base_price = float(row.open) # 今日开盘执行
```

**验收标准**:
- [ ] 任何 bar 的交易信号仅使用该 bar 之前的数据
- [ ] `execution_base_price` 永远取 `t+1` 的价格
- [ ] 回测中无"同一 bar 生成信号并成交"的路径

**测试**:
- 数据流测试: 构造 5-bar 数据, 验证信号列 `shift(1)` 后执行
- 回归测试: 修复前后 results 存在可解释的系统性差异, Monte Carlo bootstrap 下超额收益统计显著性重估

### 1.3 修复 Same-Bar Execution (src/execution/simulator.py:42)

**当前代码**:
```python
def execute_buy(self, signal: Dict, date: str):
    df = self.loader.load_latest_data(symbol, lookback=60)
    target_date = pd.Timestamp(date)
    day_data = df[df["date"] == target_date]
    if day_data.empty:
        day_data = df.tail(1)  # ← 数据泄漏风险
    row = day_data.iloc[-1]
    price = float(row["open"])  # 同日开盘成交
```

**修复方案**:
```python
def execute_buy(self, signal: Dict, date: str):
    df = self.loader.load_latest_data(symbol, lookback=60)
    signal_date = pd.Timestamp(date)
    # 验证信号日期是过去 (已经被处理过的)
    # 取信号日期之后第一个交易日的数据执行
    all_dates = df["date"].sort_values()
    exec_idx = all_dates.searchsorted(signal_date, side="right")  # 严格 > signal_date
    if exec_idx >= len(all_dates):
        return None  # 无可用执行日期, skip
    exec_date = all_dates.iloc[exec_idx]
    day_data = df[df["date"] == exec_date]
    row = day_data.iloc[-1]
    price = float(row["open"])
```

**验收标准**:
- [ ] 信号生成日期与执行日期严格不同 (t+1)
- [ ] 日期不匹配时返回 None, 不自动 fallback
- [ ] 去除 `df.tail(1)` 数据泄漏路径

### 1.4 修复 Survivorship Bias (scripts/backtest_core.py:37)

**当前代码**:
```python
stocks = load_stocks(PROJECT_ROOT.parent / "data" / "stock_list.csv", ...)
# 今天的股票列表应用到所有历史窗口
```

**修复方案**:

**方案 A: 真正修复 (优先, 需引入历史成分股数据源)**
```python
# 使用数据快照时间点的 universe, 而非今日列表
stocks = load_historical_universe(as_of_date, data_dir)
# 需要历史成分股数据 (中证/国证/万得 API)
```
影响: 可消除 survivorship bias, 但需额外数据采购或接入工作。

**方案 B: 仅记录偏差来源 (最小改动, 不修复偏差)**
```python
# 记录 universe 快照, 让偏差可审计
reproducibility = {
    "universe_snapshot": sorted(stocks),          # 实际使用的股票列表
    "universe_as_of": "today",                     # 始终是当前日期
    "universe_has_delisted_stocks": False,         # 已知含 survivorship bias
    "universe_source": str(csv_path),
    "universe_mtime": os.path.getmtime(csv_path),
}
```
**重要**: 方案 B 不修复 survivorship bias, 仅让偏差可追溯。

**验收标准**:
- [ ] 方案 A: universe 限定到每个回测窗口的 snapshot 日期
- [ ] 方案 A: 排除退市股票不影响回测 (即仅使用当期存在的股票)
- [ ] 方案 B: reproducibility 字典明确标注 `universe_has_delisted_stocks: False`
- [ ] 无论方案 A/B, 报告输出明确标注 survivorship bias 的处理方式

### 1.5 修复模拟器费用缺失 (src/execution/simulator.py:68,115)

**当前代码**:
```python
self._cash -= cost                    # 买入, 无费用
self._cash += proceeds                # 卖出, 无费用
```

**修复方案**:
```python
# 配置
BUY_FEE_RATE = 0.00025    # 佣金万2.5
SELL_FEE_RATE = 0.00025   # 佣金
STAMP_TAX_RATE = 0.001    # 印花税 0.1% (卖出单边)

# 买入
cost = quantity * buy_price
fee = cost * BUY_FEE_RATE
self._cash -= (cost + fee)

# 卖出
proceeds = qty * exit_price
fee = proceeds * SELL_FEE_RATE
stamp_tax = proceeds * STAMP_TAX_RATE
self._cash += (proceeds - fee - stamp_tax)
```

**验收标准**:
- [ ] 买入扣佣金, 卖出扣佣金 + 印花税
- [ ] 费用率可通过配置参数调整
- [ ] 修复后的总收益与换手率成反比 (高换手策略费用冲击更大, 符合经济学预期)

### 1.6 修复流动性约束默认关闭 (src/investment/backtest.py:127)

**当前代码**:
```python
enable_limit_move_constraint: bool = False
suspend_if_volume_zero: bool = False
```

**修复方案**: 默认启用
```python
enable_limit_move_constraint: bool = True
suspend_if_volume_zero: bool = True
```

**验收标准**:
- [ ] 涨跌停日不可交易
- [ ] 零成交量日不可交易
- [ ] 回测中出现极限价格时的成交次数下降

### 1.7 修复止盈止损缺口穿越 (scripts/backtest_core.py:155-187)

**当前代码**:
```python
if lo <= ss:
    ep = ss              # 精确成交在止损价, 无缺口模型
```

**修复方案**: 日线回测统一采用保守成交假设

```python
# 缺口穿越逻辑 (日线, t+1 执行)
# 规则: 优先判断开盘缺口穿越, 再判断盘中触发
#       1. 开盘即跳空穿越 → 按开盘价成交 (缺口场景)
#       2. 盘中触及 → 按止损/止盈价成交 (保守)
#       3. 未触及 → 继续持有
row = day_data  # 当前执行 bar

if row["open"] <= sl < row["low"]:
    # 场景: 开盘即跳空跌破止损, 低点低于止损但开盘更低
    # 成交: 按开盘价 (缺口无法以 sl 成交)
    ep = row["open"]
elif row["open"] >= tp > row["high"]:
    # 场景: 开盘即跳空涨破止盈
    ep = row["open"]
elif row["low"] <= sl <= row["high"]:
    # 场景: 盘中正常触及止损
    ep = sl
elif row["high"] >= tp >= row["low"]:
    # 场景: 盘中正常触及止盈
    ep = tp
else:
    # 未触及, 继续持有
    ep = None
```

**注意**: 这是日线回测假设, 不是逐笔成交模拟。不模拟订单队列、部分成交、盘口深度。
    ep = close           # 未触及, 继续持有
```

**验收标准**:
- [ ] 跳空跌破止损时以下一 bar 开盘价成交
- [ ] 盘中触及止损时以止损价成交
- [ ] 修复后最大回撤应增加 (更真实的场景)

---

## 2. Sprint 2: 可复现性修复

> 目标: 每次运行完全可复现, 有完整审计链
> 工期: 2 天
> 验证: 相同参数运行两次, 结果完全一致

### 2.1 数据库隔离 (src/storage/database.py:11, src/execution/simulator.py:23)

**当前代码**:
```python
class Database:
    def __init__(self, db_path: str = "data/trading.db"):
        ...

class SimulatedBroker:
    def __init__(self, ...):
        port = self.db.get_portfolio(limit=1)
        if not port.empty:
            self._cash = float(port.iloc[0]["cash"])  # 跨运行污染
```

**修复方案**:
```python
@dataclass
class RunContext:
    run_id: str                    # UUID
    db_path: str                   # run-specific
    created_at: str
    metadata: Dict

class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or f"data/trading_{uuid4().hex[:8]}.db"
        # 或使用 :memory:
```

**验收标准**:
- [ ] 每次运行使用独立 DB (run-specific path 或 in-memory)
- [ ] SimulatedBroker 不从已有 DB 恢复状态
- [ ] 两次相同参数运行结果完全一致

### 2.2 数据源版本固定 (src/data/manager.py:476)

**当前代码**: 通达信本地文件无版本, 直接读取

**修复方案**: 使用显式 DataBundle 结构代替 DataFrame 隐式属性

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class DataSourceMeta:
    symbol: str
    source: str                  # "tdx_local" | "akshare" | "parquet_cache"
    file_path: Optional[str] = None
    file_mtime: Optional[str] = None
    file_size: Optional[int] = None
    rows: int = 0
    date_range: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class DataBundle:
    df: pd.DataFrame
    meta: DataSourceMeta

class DataManager:
    def get_data(self, symbol: str) -> Optional[DataBundle]:
        df = self._read_from_tdx(symbol)
        meta = DataSourceMeta(
            symbol=symbol,
            source="tdx_local",
            file_path=tdx_path,
            file_mtime=datetime.fromtimestamp(os.path.getmtime(tdx_path)).isoformat(),
            file_size=os.path.getsize(tdx_path),
            rows=len(df),
            date_range=f"{df['date'].min()} ~ {df['date'].max()}",
        )
        return DataBundle(df=df, meta=meta)
```

**验收标准**:
- [ ] 每个数据请求返回 `DataBundle` 而非裸 `DataFrame`
- [ ] `DataBundle.meta` 包含文件路径、修改时间、大小
- [ ] 序列化/copy 时 DataSourceMeta 不丢失
- [ ] 两次运行若数据源不同, 元数据可追溯

### 2.3 完整回测元数据 (scripts/backtest_core.py:420)

**当前代码**:
```python
"reproducibility": {
    "mc_seeded": True,
    "mc_seed": 42,
    "window_seeded": True,
    "window_seed": 42,
}
```

**修复方案**:
```python
"reproducibility": {
    "run_id": "a1b2c3d4",
    "created_at": "2026-05-16T10:30:00",
    "mc_seed": 42,
    "window_seed": 42,
    "windows_sampled": sorted(random.sample(...)),  # 实际窗口列表
    "universe": sorted(stock_symbols),              # 实际 universe
    "universe_size": len(stocks),
    "data_sources": {sym: source_info for sym, source_info in ...},
    "code_version": git_head_hash,
    "config_snapshot": {**config_dict},
}
```

**验收标准**:
- [ ] reproducibility 包含 run_id, 窗口列表, universe, 数据源信息
- [ ] 给定 reproducibility 元数据, 可以精确重现

---

## 3. Sprint 3: 测试契约修复

> 目标: 默认 pytest 快速且确定, 不依赖 output/ 产物
> 工期: 2 天
> 验证: `pytest tests/` 全部通过, < 30 秒

### 3.1 修复阻断性 Bug (src/wyckoff/analyzer.py:646)

**当前代码**:
```python
for row in recent.itertuples():
    high_change = (row["high"] - row["open"]) / row["open"]  # TypeError
```

**修复**: 所有 `row["col"]` → `row.col`:
```python
high_change = (row.high - row.open) / row.open
low_change = (row.low - row.open) / row.open
volume_level = self._classify_volume(row.volume, df["volume"])
```

**验收标准**:
- [ ] `_detect_limit_moves` 不崩溃
- [ ] 集成测试通过率从 9/22 → 22/22

### 3.2 smoke 测试加退出码检查 (tests/unit/test_backtest_cli.py:60)

**当前代码**:
```python
assert fp.exists()  # 不检查子进程是否成功
```

**修复**:
```python
result = subprocess.run([...], capture_output=True, ...)
assert result.returncode == 0, f"CLI failed:\nstdout:{result.stdout[:500]}\nstderr:{result.stderr[:500]}"
assert fp.exists()
```

**验收标准**:
- [ ] 子进程非零退出码导致测试失败
- [ ] 失败时输出 stdout/stderr 便于调试

### 3.3 分层测试策略

**设计**: 三层测试, 每层有不同环境要求

| 层级 | 内容 | 数据依赖 | 默认运行 |
|------|------|---------|---------|
| L1: unit | 纯逻辑, 无数据依赖 | 无 | `pytest tests/unit` ✅ |
| L2: contract | fixture-based 集成, 用预置数据文件 | `tests/fixtures/*` | `pytest tests/contract` ✅ |
| L3: replay | 依赖 TDX 本地数据的回放/批量测试 | TDX_DATA_DIR | 单独标记 `--tdx` ❌ |

**pytest.ini 配置**:
```ini
[pytest]
testpaths = tests/unit tests/contract
markers =
    slow: marks tests as slow
    tdx: requires TDX_DATA_DIR environment variable
```

**验收标准**:
- [ ] 默认 `pytest` 只跑 L1 + L2, 不需要 TDX 数据
- [ ] L3 测试标记 `@pytest.mark.tdx`, 仅在 `TDX_DATA_DIR` 设置时运行
- [ ] CI 中只跑 L1 + L2

### 3.4 解耦 output/ 依赖 (tests/unit/test_backtest_schema.py)

**当前**: 验证 `output/` 下的 checked-in 产物

**修复方案**:
```python
@pytest.fixture
def temp_output(tmp_path):
    """临时输出目录, 每次测试独立"""
    return tmp_path / "output"

def test_schema(temp_output):
    result = run_backtest(..., output_dir=str(temp_output))
    schema = load_result(temp_output / "results.json")
    assert validate_schema(schema)
```

**验收标准**:
- [ ] 所有测试使用 `tmp_path` fixture, 不依赖仓库中的 `output/`
- [ ] 测试可并行运行 (无共享状态)

---

## 4. Sprint 4: 基础设施修复

> 目标: CI green, 路径标准化, warning 可见
> 工期: 2 天

### 4.1 添加 CI Pipeline (两阶段)

**设计**: 先上 minimal CI, 等 Sprint 3/4 落地后再追加 gated integration

#### Phase 1: Minimal CI (Sprint 4 交付)
```yaml
name: CI
on: [push, pull_request]
jobs:
  lint-and-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt pytest
      - run: ruff check .
      - run: python -m compileall src/
      - run: python -m pytest tests/unit/ -v
```

#### Phase 2: Gated Integration (Sprint 4 + Sprint 3 落地后追加)
```yaml
  integration:
    needs: lint-and-unit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt pytest
      - run: python -m pytest tests/contract/ -v --timeout=120
```

**验收标准**:
- [ ] Phase 1: ruff, compile, unit tests 全部通过, 运行时间 < 3 分钟
- [ ] Phase 2: contract tests 全部通过, 不依赖 TDX_DATA_DIR
- [ ] TDX 依赖测试永远不在 CI 中运行 (仅本地)

### 4.2 统一环境变量合约

**当前**: 4 处硬编码 `/home/james/.local/share/tdxcfv/...`

**修复**: 单一环境变量合约 + 清晰报错

```python
# src/constants.py
TDX_DATA_DIR = os.environ.get("TDX_DATA_DIR")
if not TDX_DATA_DIR:
    raise RuntimeError(
        "TDX_DATA_DIR environment variable is required.\n"
        "Set it to your TDX vipdoc root, e.g.:\n"
        "  export TDX_DATA_DIR=/path/to/vipdoc"
    )
```

**验收标准**:
- [ ] 无硬编码机器路径
- [ ] 缺失环境变量时抛 `RuntimeError` 而非静默使用默认值

### 4.3 局部 Warning 过滤

**当前**:
```python
warnings.filterwarnings("ignore")  # 全局抑制
```

**修复**:
```python
# 只抑制特定模块的已知 harmless warning
warnings.filterwarnings("once", category=RuntimeWarning, module="numba")
# 或升级为 logging
import logging
logging.captureWarnings(True)
```

**验收标准**:
- [ ] 全局 `filterwarnings("ignore")` 被移除
- [ ] 数值不稳定 (NaN, Inf) 和 SciPy 弃用 warning 可见

---

## 5. Sprint 5: LPPL 核心算法优化

> 目标: 提高模型可靠性, 消除假信号
> 工期: 3 天

### 5.1 R² 负值 clamp

**文件**: `src/lppl_engine.py:257-259`

```python
r_squared = max(0.0, 1 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0
```

**测试**: 构造 `ss_res > ss_tot` 的退化数据, 验证 R² = 0.0

### 5.2 DE 多起点策略

**文件**: `src/lppl_core.py:206`

```python
best_result = None
best_fun = float("inf")
for seed in [0, 42, 123, 9999]:
    result = differential_evolution(..., seed=seed)
    if result.success and result.fun < best_fun:
        best_result = result
        best_fun = result.fun
```

**测试**: 验证多次运行返回不同但更优的解

### 5.3 共识阈值提高

**文件**: `src/lppl_engine.py:71`

```python
consensus_threshold: float = 0.5  # 原 0.15
```

**测试**: 验证 3 窗口中至少 2 个通过才触发信号

### 5.4 综合方向判定

**文件**: `src/lppl_engine.py:901-904`

```python
def is_valid_bubble(m, w, b, c):
    return (
        0.1 < m < 0.9
        and 6 < w < 13
        and b < 0                          # 超指数增长
        and abs(c) > 0.01                  # 振荡幅度足够
    )
```

**测试**: 构造已知泡沫/非泡沫参数向量, 验证判定正确性

### 5.5 Walk-Forward 多维度评估

**文件**: `src/verification/walk_forward.py:13-22`

```python
# 新增指标
tc_error_days = abs(predicted_tc - actual_bottom_date).days  # 时间误差
magnitude_error = abs(predicted_drop - actual_drop)           # 幅度误差
```

**测试**: 验证新指标随预测精度改善而改善

---

## 6. Sprint 6a: 生产路径架构清理

> 目标: 消除生产路径上的 sys.path, 建立 package 安装, 统一 CLI 入口
> 工期: 2 天
> 范围: src/cli/, main.py, src/*.py — 不涉及 scripts/ 迁移

### 6a.1 安装为可编辑 package

**文件**: `pyproject.toml` (已有, 需补充 build-system 配置)

```bash
pip install -e .
```

之后 `from src.lppl_core import lppl_func` 直接工作, 无需 sys.path

### 6a.2 消除生产路径上的 sys.path.insert

**目标文件** (共 ~8 处, 非 101 处):
- `src/cli/lppl_verify_v2.py:37`
- `src/cli/wyckoff_analysis.py:26`
- `main.py` (根目录入口)
- `wyckoff_analysis.py`, `wyckoff_multimodal_analysis.py` (根目录 wrapper)

**操作**: 全部删除, 改为 `from src.xxx import yyy` (通过 `pip install -e .` 解析)

**不做**: `scripts/` 和 `unused/` 和 `archive/` 中的 sys.path 保留 (research 代码)

### 6a.3 CLI 路由化 (src/cli/ → pure dispatch)

**当前**: `src/cli/lppl_verify_v2.py` 含 sys.path + 业务逻辑

**目标**: CLI 模块只做参数解析和路由
```python
def main():
    args = parse_args()
    service = VerificationService(config=args.config)
    result = service.run(symbol=args.symbol, ensemble=args.ensemble)
    report = ReportGenerator(result)
    report.save(args.output)
```

### 6a.4 根目录 wrapper 精简

**当前**: 10+ 个根目录 `*.py` 文件指向 `src/cli/` 中的函数

**操作**: 将根目录 wrapper 统一为单一 `main.py` + subcommand pattern
```bash
python main.py verify --symbol 000001.SH
python main.py walk-forward --symbol 000001.SH
python main.py wyckoff --symbol 000001.SH
```

保留旧 wrapper 作为 deprecated shim, 加 `DeprecationWarning`。

---

## 6b. Sprint 6b: Research 代码整理 (后续阶段)

> 目标: 迁移/归档 scripts/ 中的持久性逻辑
> 工期: 3 天 (与 Sprint 6a 独立, 可后续执行)

### 6b.1 迁移策略逻辑 scripts/ → src/strategies/

**迁移清单**:
| 文件 | 目标位置 | 原因 |
|------|---------|------|
| `scripts/backtest_core.py` 中 trade_wyckoff/trade_ma/trade_str_reversal | `src/strategies/` | 持久性业务逻辑 |
| `scripts/run_backtest.py` CLI 入口 | `src/cli/run_backtest.py` | CLI 统一 |

### 6b.2 scripts/ 归档策略

| 类型 | 数量 | 处理方式 |
|------|------|---------|
| 已确认不再使用的实验脚本 | ~40 | 移入 `scripts/archive/` |
| 仍在活跃使用的回测脚本 | ~30 | 保留但改用 `pip install -e .` 后的 import 路径 |
| 可合并到统一入口的 | ~15 | 提取公共逻辑到 src/, wrapper 留在 scripts/ |


---

## 7. Sprint 7: 代码质量与长期维护

> 目标: lint free, 无重复代码, 向量化
> 工期: 1 天 (可并行)

### 7.1 自动修复 lint

```bash
ruff check --fix .
# 消除 ~527 个可自动修复的错误
```

### 7.2 消除 Numba 重复

`src/lppl_engine.py` 中的 `_lppl_func_numba` 和 `_cost_function_numba` 改为 `from src.lppl_core import ...`

### 7.3 Peak Detection 向量化

```python
# 当前 (O(n*window))
for i in range(window, len(close) - window):
    local_max = np.max(close[i-window:i+window+1])

# 优化后 (O(n))
rolling_max = pd.Series(close).rolling(window*2+1, center=True).max()
is_peak = close == rolling_max
```

### 7.4 修正 total_pnl 语义

`src/storage/database.py:253` — 重命名列或修正计算:
- 方案 A: 列名 `total_pnl` → `snapshot_pnl` (明确语义)
- 方案 B: `total_pnl` = 从起始的累计值 (需遍历所有历史快照计算)

---

## 8. 整体路线图与依赖关系

```
Sprint 1 (量化正确性)    ← 无前置依赖, 最高 ROI
  ├── 1.1 未来 ATR
  ├── 1.2 same-bar (backtest)
  ├── 1.3 same-bar (simulator)
  ├── 1.4 survivorship
  ├── 1.5 费用模型
  ├── 1.6 流动性约束
  └── 1.7 缺口穿越

Sprint 2 (可复现性)      ← 依赖 Sprint 1(1.5) 的费用模型
  ├── 2.1 DB 隔离
  ├── 2.2 数据源固定
  └── 2.3 元数据完整

Sprint 3 (测试契约)      ← 可并行
  ├── 3.1 阻断 bug 修复 ← 无前置
  ├── 3.2 smoke 退出码  ← 无前置
  ├── 3.3 pytest 路径   ← 无前置
  └── 3.4 output 解耦    ← 无前置

Sprint 4 (基础设施)      ← 可并行
  ├── 4.1 CI pipeline
  ├── 4.2 环境变量合约
  └── 4.3 warning 过滤

Sprint 5 (核心算法)      ← 可并行 (与 Sprint 1-4 独立)
  ├── 5.1 R² clamp
  ├── 5.2 DE 多起点
  ├── 5.3 共识阈值
  ├── 5.4 方向判定
  └── 5.5 walk-forward

Sprint 6a (生产路径架构)  ← 依赖 Sprint 3(测试通过) 和 Sprint 4(CI)
  ├── 6a.1 package install
  ├── 6a.2 生产路径 sys.path 消除
  ├── 6a.3 CLI 纯路由
  └── 6a.4 wrapper 精简

Sprint 6b (research 整理)  ← 与 Sprint 6a 独立, 可后续执行
  ├── 6b.1 策略逻辑迁移
  └── 6b.2 归档策略

Sprint 7 (代码质量)      ← 可并行, 无前置
  ├── 7.1 ruff --fix
  ├── 7.2 消除重复
  ├── 7.3 向量化
  └── 7.4 total_pnl 语义
```

**关键路径**: Sprint 1 → Sprint 2 → Sprint 6
**并行路径**: Sprint 3, 4, 5, 7
**总工期估计**: 12-16 人天 (含验证, Sprint 6b 额外 +3 天)

---

## 9. 验收检查清单

### 量化正确性
- [ ] `scripts/backtest_core.py` 无未来数据 ATR
- [ ] `src/investment/backtest.py` 无 same-bar 执行
- [ ] `src/execution/simulator.py` 无同日执行, 无 df.tail(1) fallback
- [ ] 买卖对称费用 + 印花税已实现
- [ ] 流动性约束默认启用
- [ ] 缺口穿越模型已实现

### 可复现性
- [ ] 每次运行使用独立 DB 或 in-memory
- [ ] SimulatedBroker 不从历史状态恢复
- [ ] 回测元数据包含 run_id, windows, universe, 数据源

### 测试
- [ ] `pytest tests/` 全部通过
- [ ] 集成测试通过率 22/22
- [ ] smoke 测试检查子进程退出码
- [ ] 测试不依赖 `output/` 仓库文件

### 基础设施
- [ ] CI pipeline green
- [ ] 无硬编码 `/home/james/...` 路径
- [ ] 无全局 `warnings.filterwarnings("ignore")`

### 架构 (Sprint 6a)
- [ ] 生产路径 0 处 `sys.path.insert` (src/cli/, 根目录 wrapper, main.py)
- [ ] `pip install -e .` 可用
- [ ] `src/cli/` 仅做路由
- [ ] 根目录 wrapper 统一为 `python main.py <subcommand>`

### 架构 (Sprint 6b)
- [ ] `scripts/backtest_core.py` 中策略逻辑已迁移到 `src/strategies/`
- [ ] `scripts/run_backtest.py` 入口已统一
- [ ] 已确认不再使用的实验脚本已归档到 `scripts/archive/`

### 算法
- [ ] R² clamp: `max(0.0, 1 - ss_res/ss_tot)`
- [ ] DE 多起点 (≥3 种子)
- [ ] 共识阈值 ≥ 0.5
- [ ] 方向判定使用多参数综合判定

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 修复后夏普大幅下降, 策略看似"失效" | 高 | 中 | 预期行为 — 偏差消除后真实 alpha 浮现。使用 Monte Carlo 验证超额收益的统计显著性 |
| 95 个 scripts/ 修改量大 | 中 | 高 | 分批迁移, 先处理 architecture boundary 问题, research 脚本可保留但用 `PYTHONPATH` 而非 sys.path |
| 集成测试修复后仍有 flaky test | 低 | 低 | 数据相关测试标记 `@pytest.mark.slow`, CI 中分离 fast/slow |
| 通达信历史成分股数据不可得 | 中 | 中 | 退而求其次: 记录 universe 快照 + 注明 survivorship bias 的量化影响 |
| 修复回测引擎影响现有研究产出 | 高 | 高 | 并行维护两套配置: `--legacy-mode` 保留旧行为, `--production-mode` 用新引擎, 对比运行后切换 |
