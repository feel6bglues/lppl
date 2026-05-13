# 生产就绪修复计划 v2 — 修正版

> 生成日期: 2026-05-13
> 版本说明: 基于 v1 审查意见全面修正。修正项: JSON NaN 根因、负风险修复逻辑、代码片段兼容性、日期对齐、回测口径统一、框架抽象顺序
> 覆盖范围: daily_signals 数据层 + 回测校准层 + 框架抽象层

---

## 一、issue 核实表

每个 issue 标注对应代码行和核实方式。

| # | issue | 源码行号 | 核实方式 |
|:-:|-------|---------|----------|
| **数据层 — daily_signals** | | | |
| D1 | 负风险: 600015.SH 止损>入场, risk_pct 为负数 | `generate_daily_signals.py:159` | `grep 600015 output/…csv` |
| D2 | bear regime 标签: 宏观 bull 但个股 bear 时, regime 字段显示 bear | `generate_daily_signals.py:129-133` | 产出文件 6 条 bear |
| D3 | JSON NaN: `json.dump(allow_nan=True)` 输出裸 NaN token, 非 "nan" 字符串 | `generate_daily_signals.py:366` | `grep NaN output/…json` |
| D4 | 日期未对齐: `get_latest_date()` 已定义(行71)但不使用；实际直接用 `csi_last` | `generate_daily_signals.py:71,283` | 代码审查 |
| D5 | 无失败统计: `except Exception: pass` 不记录失败原因 | `generate_daily_signals.py:297-299` | 代码审查 |
| D6 | 无 logging: 脚本无 logger 初始化，无法输出警告 | 文件头 | 代码审查 |
| **回测层 — 口径一致性** | | | |
| B1 | period 元信息缺失: tristrat 输出无 period/sample_interval 字段 | `run_tristrat_v6_str.py:59` outputs/json | 产出文件审查 |
| B2 | 窗口口径不同: dual_strat 20窗 vs 30窗, period 元信息写错 | `run_dual_strat_backtest.py:62` | "2020-2026"应为"2020-2025" |
| B3 | ATR 算法两处实现不同: daily_signals 行 200-204 vs run_dual_strat_backtest 行 78 | 代码对比 | 一个用 SMA, 一个用 numpy mean |
| B4 | MC 未固定 seed: `gen_windows` 用 `SEED` 但 MC 模拟无 seed | 所有回测脚本 | 代码审查 |
| B5 | 组合 Sharpe 不是基于真实组合序列: 用公式 `avg_s × sqrt(n/(1+(n-1)×avg_rho))` 而非真实组合净值 | `run_dual_strat_backtest.py:317` | 代码审查 |
| **框架层** | | | |
| F1 | 6 个变体脚本, 公共函数重复实现 | 6 个文件对比 | `diff run_*.py` |
| F2 | 输出 schema 不统一: 各文件字段名/结构不一致 | 多文件输出对比 | 产出 JSON 对比 |

---

## 二、修复方案（全部经源码行对行核实）

### Phase A: 数据层 — 使 `daily_signals` 可信任 (P0)

#### A1: 日期对齐（优先级最高）

**根因**: `get_latest_date()`(行71)已实现但不被调用。行283直接用 `csi_last` 作为 `as_of_date`, 个股最新日可能早于指数最新日(停牌/退市), 导致用未来数据计算信号。

**修复**: 在行283处修正:

```python
# 修复前 (行283):
as_of_date = csi_last

# 修复后:
# 用指数日期锚定，但对齐到所有数据都存在的共同日期
stock_last_dates: List[str] = []
# 这里不扫描全量股票(太大)，而是依赖 TDX 数据状态表的 last_date
# 简化方案: 取 csi_last 和提前扫描的个股 min(last_date) 中的较小值
# 更务实现: 仍用 csi_last, 但每个个股检查 df["date"].max() >= as_of_date
as_of_date = csi_last
```

同时在 `process_stock` 中增加数据完整性检查:

```python
# 在 process_stock 中(行 282-288):
def process_stock(args):
    si, as_of_date, csi = args
    sym, name = si["symbol"], si["name"]
    signals = []
    try:
        dm = DataManager()
        df = dm.get_data(sym)
        if df is None or df.empty or len(df) < 300:
            return signals  # 数据不足, 静默跳过
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        # ==== 新增: 数据完整性检查 ====
        if str(df["date"].max().date()) < as_of_date:
            return signals  # 个股最新日早于分析日, 跳过
        # ============================
        ...
```

---

#### A2: 负风险值截断

**根因**: 行159 `(1 - stop_loss / entry) * 100`, 当 `stop_loss >= entry` 时结果为负数或零。

**修复**: 整行替换。这行代码在 `check_wyckoff_signal` 返回值字典中：

```python
# 修复前 (行159):
"risk_pct": round((1 - stop_loss / entry) * 100, 2) if stop_loss else None,

# 修复后:
"risk_pct": round((1 - stop_loss / entry) * 100, 2) if stop_loss and stop_loss < entry else None,
```

同时在上方(约行139)加断言日志(需先初始化logging,见A6):
```python
if stop_loss and entry and stop_loss >= entry:
    logger.warning(f"{symbol}: stop_loss({stop_loss:.3f}) >= entry({entry:.3f}), risk_pct set to None")
```

**验证**: `grep "600015" output/…csv` 确认 `risk_pct` 为 null/空 而非负数。

---

#### A3: JSON NaN 标准化

**根因**: `json.dump` 默认 `allow_nan=True`(行366), 允许输出裸 `NaN` token。不是 `default=str` 的问题。

**修复**: 在 `json.dump` 前清洗数据，同时关闭 `allow_nan` 在开发环境暴露问题:

```python
import math

def _clean_nan(obj):
    """将 NaN/Infinity 递归替换为 None, 确保 JSON 标准合规"""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    return obj

# 在行366-372处修改:
records = _clean_nan(df.to_dict("records"))
with json_path.open("w", encoding="utf-8") as f:
    json.dump({
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "date": ts,
        "total_signals": len(records),
        "n_stocks_scanned": len(stocks),
        "by_strategy": {"wyckoff": len(wyc), "ma_cross": len(ma)},
        "signals": records,
    }, f, ensure_ascii=False, indent=2)
```

**验证**: `grep -c "NaN" output/…json` 结果应为 0。

---

#### A4: bear regime 修正

**根因**: 行131 `regime` 字段用个股制度, 行132仅过滤宏观制度。宏观bull但个股bear时, `regime` 字段值为 `bear`, 但信号未被过滤, 产生矛盾。

**修复**: 在 `check_wyckoff_signal` 函数内, 行132后增加:

```python
    # ==== 已存在: macro_regime == "bear" 过滤 ====
    if macro_regime == "bear":
        return None
    # ==== 新增: 个股bear制度下, 仅允许accumulation相位 ====
    # 注意: 此时 phase 变量尚未定义(它在行140), 不能在这里引用
    # 改为在返回前检查 regime 字段一致性
```

由于 `phase` 变量在行140才定义, 不能在行132处引用。正确做法: 在返回值字典组装完毕后(约行160后)检查:

```python
# 在行161 return 之前增加:
if stock_regime == "bear" and phase not in ("accumulation",):
    return None
```

---

#### A5: 失败样本统计

**根因**: `except Exception: pass`(行297)完全忽略异常, 不记录哪个股票、什么原因。

**修复**: 改造 `process_stock` 返回结构, 以及主循环汇总:

```python
# process_stock 改造:
def process_stock(args):
    si, as_of_date, csi = args
    sym, name = si["symbol"], si["name"]
    signals = []
    errors = []
    try:
        dm = DataManager()
        df = dm.get_data(sym)
        if df is None or df.empty or len(df) < 300:
            errors.append({"symbol": sym, "reason": "insufficient_data"})
            return {"signals": signals, "errors": errors}
        ...
    except Exception as e:
        errors.append({"symbol": sym, "reason": type(e).__name__, "msg": str(e)})
    return {"signals": signals, "errors": errors}
```

主循环改造(行294-302):
```python
all_signals = []
all_errors = []
with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
    for b in range(0, len(args_list), bs):
        batch = args_list[b:b + bs]
        futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
        for f in as_completed(futures):
            try:
                result = f.result(timeout=120)
                all_signals.extend(result.get("signals", []))
                all_errors.extend(result.get("errors", []))
            except Exception as e:
                all_errors.append({"symbol": "unknown", "reason": "future_timeout"})
        ...
```

输出汇总:
```python
print(f"\n失败统计: {len(all_errors)}次")
from collections import Counter
for reason, cnt in Counter(e["reason"] for e in all_errors).most_common(5):
    print(f"  {reason}: {cnt}")
```

---

#### A6: 初始化 logging

**根因**: 脚本未初始化 logger, 无法输出警告日志。

**修复**: 在文件头(行10后)添加:

```python
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("daily_signals")
```

---

### Phase B: 回测口径统一 (P1)

#### B1: period 元信息标准化

所有回测输出 JSON 必须包含:

```python
"config": {
    "n_stocks": int,
    "n_windows": int,
    "min_year": int,
    "max_year": int,
    "with_costs": bool,
    "cost_model": {"buy": 0.075, "sell": 0.175, "round_trip": 0.25},
    "seed": int,
    "strategies_used": [...],
}
```

检查并修正 `run_dual_strat_backtest.py:62` 的 "2020-2026" → "2020-2025"。

---

#### B2: ATR 算法统一

当前两处实现:

| 位置 | 实现 | 特点 |
|:----:|------|------|
| `generate_daily_signals.py:200-204` | `for i in 1..20: max(hi-lo, hi-pc, lo-pc)` → `np.mean` | 标准 ATR(20) |
| `run_dual_strat_backtest.py:78` | `hi[i]-lo[i] for i in range(p)` → `np.mean` | **仅用 HH-LL, 不含 gap** |

后者缺失 `abs(hi-pc)` 和 `abs(lo-pc)`, 在跳空日低估真实波幅。统一为前者。

**修复**: `run_dual_strat_backtest.py:78` 改为与 daily_signals 一致的实现。

---

#### B3: MC seed 固定

在各回测脚本的 `run()` 函数入口增加:

```python
np.random.seed(42)
```

确保 MC 模拟可复现。

---

#### B4: 组合 Sharpe 改用真实净值序列

当前公式 `avg_s × sqrt(n / (1+(n-1)×avg_rho))` 是理论估算, 不是真实组合收益。

**修复**: 在有完整回测的脚本中, 构建等权组合日收益序列:

```python
# 伪代码: 需各策略在相同窗口上有收益
# 假设 wyckoff_rets, ma_rets 是同一组 windows 上的收益数组
combo_ret = 0.5 * wyckoff_rets + 0.5 * ma_rets
combo_sharpe = ann_sharpe(combo_ret, avg_days)
```

对于无法获取配对收益的场景(如当前 daily_signals 无回测), 保留公式法但标注:

```python
"portfolio_sharpe_method": "estimated_from_correlation"  # 或 "actual_from_portfolio_returns"
```

---

### Phase C: 框架统一 (P2, 口径统一后执行)

原则: **先定口径, 再抽框架**。在 Phase B 完成前不做框架抽象。

步骤:

| # | 动作 | 前置条件 |
|:-:|------|---------|
| C1 | 定义统一口径文档(即本计划 Phase B) | — |
| C2 | 逐个脚本按口径修正 | Phase B 完成 |
| C3 | 提取公共函数到 `scripts/backtest_core.py` | C2 完成 |
| C4 | 创建 `scripts/run_backtest.py` CLI 入口 | C3 完成 |
| C5 | 旧脚本加 deprecated 标记 | C4 验证通过 |

---

## 三、执行顺序

```
Phase A (数据层, 约 1.5h)
  A6 logging初始化 → A1日期对齐 → A2负风险 → A3 JSON NaN → A4 bear修正 → A5失败统计
  ↓ 验证: python scripts/generate_daily_signals.py
  ↓ 验证: grep -c NaN output/…json → 0
  ↓ 验证: grep 600015 output/…json | python -c "import json,sys; d=json.load(sys.stdin); ..."

Phase B (口径统一, 约 2h)
  B1 period元信息 → B2 ATR统一 → B3 MC seed → B4 组合Sharpe
  ↓ 验证: 所有回测输出含 period/seed/cost_model 元信息
  ↓ 验证: ATR结果与daily_signals一致

Phase C (框架抽象, 约 3h, 在B完成后启动)
  C1-C5 逐步
```

---

## 四、不做事项

- 不改 WyckoffEngine 核心置信度逻辑(已在 Round 2 完成)
- 不改 MA5/20 金叉触发条件(已在 Round 1 完成)
- 不引入数据库存储(保留 JSON+CSV)
- 不新增策略

---

## 五、Definition of Done

```text
daily_signals JSON:            NaN=0处, risk_pct无负数, schema_version=1.0  ✅
daily_signals 信号数:           5,199只全覆盖                                  ✅
失败样本统计:                    按reason分组的report                              ✅
回测period元信息:                所有输出JSON含min_year/max_year/with_costs        ✅
ATR算法统一:                    两处实现diff=0                                 ✅
MC seed固定:                   np.random.seed(42)                             ✅
组合Sharpe方法标注:              method标注 + 真实序列                                     ✅
```
