# 生产就绪修复计划 — 已核实修正版

> 生成日期: 2026-05-14
> 核实范围: `daily_signals` 输出链路 + 最近两天回测输出链路 + 回测脚本框架层
> 目标: 将当前输出从“研究产物”收敛为“口径清晰、失败可见、可复核的准生产级产物”

---

## 一、核实结论

这份计划基于当前仓库代码和最近两天真实产物核实后整理，不再沿用未验证的假设。

### 已确认的 `daily_signals` 问题

| ID | 问题 | 代码位置 | 产物证据 |
|---|---|---|---|
| D1 | `risk_pct` 可为负数 | `scripts/generate_daily_signals.py:159` | [signals_2026-05-13.csv:2](/home/james/Documents/Project/lppl/output/daily_signals/signals_2026-05-13.csv:2) |
| D2 | `regime` 字段与过滤口径不一致，出现 `bear` 标签残留 | `scripts/generate_daily_signals.py:129-155` | `signals_2026-05-13.{csv,json}` 中 6 条 `wyckoff` bear |
| D3 | JSON 输出包含非标准 `NaN` token | `scripts/generate_daily_signals.py:366-372` | [signals_2026-05-13.json:26](/home/james/Documents/Project/lppl/output/daily_signals/signals_2026-05-13.json:26) |
| D4 | 分析日期未对齐；`get_latest_date()` 定义但未使用 | `scripts/generate_daily_signals.py:71, 283` | 代码核实 |
| D5 | 多进程异常和数据不足被静默吞掉 | `scripts/generate_daily_signals.py:240-263, 292-300` | 代码核实 |
| D6 | 脚本没有 logger 初始化，无法稳定输出诊断信息 | 文件头 | 代码核实 |

### 已确认的回测口径问题

| ID | 问题 | 代码位置 | 产物证据 |
|---|---|---|---|
| B1 | `dual_strat_backtest` 实际采样 `2020-2025`，输出却写 `2020-2026` | `scripts/run_dual_strat_backtest.py:62, 328-333` | [dual_results.json](/home/james/Documents/Project/lppl/output/dual_strat_backtest_2020/dual_results.json) |
| B2 | `tristrat` 结果缺少 period / sample interval 元信息 | `scripts/run_tristrat_v6_str*.py` 输出段 | 三个 `v6_results.json` |
| B3 | ATR 算法不一致：信号脚本用近似 True Range，回测脚本仅用 `high-low` | `generate_daily_signals.py:186-191`, `run_dual_strat_backtest.py:78-81` | 代码核实 |
| B4 | Monte Carlo 未固定 `np.random.seed`，结果不可完全复现 | 各回测脚本 MC 段 | 代码核实 |
| B5 | 组合 Sharpe 是公式估算值，不是真实组合收益序列 | `run_dual_strat_backtest.py`, `run_dual_strat_wyckoff_ma.py`, `run_tristrat_v6_str*.py` | 代码核实 |
| B6 | 双策略脚本之间成本口径不同，输出文件名未体现 | `run_dual_strat_backtest.py`, `run_dual_strat_wyckoff_ma.py` | 两个 `dual_results.json` 对比 |

### 已确认的框架层问题

| ID | 问题 | 说明 |
|---|---|---|
| F1 | 6 个变体脚本高度重复 | `load_stocks / load_csi300 / get_regime / calc_atr / trade_wyckoff / trade_ma / process_stock / compute_stats` 大量复制 |
| F2 | 输出 schema 不统一 | `daily_signals`、`dual_results`、`v6_results` 顶层结构和元信息不一致 |
| F3 | 当前不适合先抽框架 | 先抽框架会把 period / 成本 / ATR / 组合 Sharpe 的现有不一致固化进去 |

---

## 二、修复原则

1. 先修数据可信度，再修回测口径，再抽框架。
2. 先让错误可见，再收敛行为。
3. 不引入未经验证的新交易规则。
4. 不把“研究输出”误标成“生产输出”。

---

## 三、修复计划

### Phase A: `daily_signals` 数据层修复（P0）

目标：让实时信号输出至少满足“严格 JSON、字段语义清楚、失败样本可见、分析日期可解释”。

#### A1. 初始化 logging

**问题**  
当前脚本直接 `print`，无 logger，后续任何警告或统计都没有稳定出口。

**修改**

在 [scripts/generate_daily_signals.py](/home/james/Documents/Project/lppl/scripts/generate_daily_signals.py) 文件头增加：

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("daily_signals")
```

---

#### A2. 修正分析日期策略

**问题**  
当前 [scripts/generate_daily_signals.py:283](/home/james/Documents/Project/lppl/scripts/generate_daily_signals.py:283) 直接使用 `csi_last`。这不是“对齐”，只是“拿指数日期当全市场日期”。

**约束**  
当前脚本是多进程按股票加载数据，主线程并不持有全市场 `last_date`。因此不建议在 P0 强行做一次全市场预扫描。

**P0 修复策略**

- 保留 `as_of_date = csi_last`
- 但把它明确定义为 `market_anchor_date`
- 对每只股票增加最新日期检查
- 把“因日期落后被跳过”单独记为 `stale_symbol`

示意：

```python
market_anchor_date = csi_last

if str(df["date"].max().date()) < market_anchor_date:
    skips.append({
        "symbol": sym,
        "reason": "stale_symbol",
        "stock_last_date": str(df["date"].max().date()),
        "market_anchor_date": market_anchor_date,
    })
    return {"signals": [], "errors": [], "skips": skips}
```

**说明**  
这一步不是“完全日期对齐”，而是先把未对齐造成的影响显式化。  
真正的“共同日期”或“按股票自有最新日分析”留到 P1 口径设计。

---

#### A3. 修正负风险值

**问题**  
当前 [scripts/generate_daily_signals.py:159](/home/james/Documents/Project/lppl/scripts/generate_daily_signals.py:159) 在 `stop_loss >= entry` 时会生成负风险。

**修复**

```python
# 修复前
"risk_pct": round((1 - stop_loss / entry) * 100, 2) if stop_loss else None,

# 修复后
"risk_pct": round((1 - stop_loss / entry) * 100, 2)
if stop_loss and entry and stop_loss < entry
else None,
```

并在构造返回值前增加：

```python
if stop_loss and entry and stop_loss >= entry:
    logger.warning(
        "%s: stop_loss(%.3f) >= entry(%.3f), risk_pct forced to None",
        symbol, stop_loss, entry
    )
```

**验收**

- `risk_pct` 不再出现负数
- [signals_2026-05-13.csv:2](/home/james/Documents/Project/lppl/output/daily_signals/signals_2026-05-13.csv:2) 这类样本应变成空值而不是负值

---

#### A4. 修正 JSON 非标准 `NaN`

**问题**  
当前不是 `"nan"` 字符串问题，而是 Python `json.dump` 默认允许输出裸 `NaN` token。

**修复**

```python
import math

def clean_json_value(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: clean_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json_value(v) for v in obj]
    return obj
```

写文件时：

```python
records = clean_json_value(df.to_dict("records"))
payload = {
    "schema_version": "1.0",
    "generated_at": datetime.now().isoformat(),
    "date": ts,
    "market_anchor_date": market_anchor_date,
    "total_signals": len(records),
    "n_stocks_scanned": len(stocks),
    "by_strategy": {"wyckoff": len(wyc), "ma_cross": len(ma)},
    "signals": records,
}
json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
```

**验收**

- JSON 中 `NaN` 数量为 0
- 严格 JSON 解析器可直接读取

---

#### A5. 修正 `regime` 字段语义，不直接发明新过滤规则

**问题**  
当前 `macro_regime` 用来过滤，`stock_regime` 用来展示，两者混在一个 `regime` 字段里，导致产物出现 `bear` 标签残留。

**不直接做的事**  
不在 P0 直接引入“`stock_regime == bear` 且 `phase != accumulation` 就过滤”的新业务规则。这个规则目前没有正式规范支撑。

**P0 修复策略**

把一个 `regime` 字段拆为两个字段：

```python
"macro_regime": macro_regime,
"stock_regime": stock_regime,
"effective_regime": regime,
```

如果要兼容旧字段，可保留：

```python
"regime": regime,
```

同时在输出摘要里增加计数：

- `macro_bear_filtered_count`
- `stock_bear_signal_count`

**验收**

- 不再把“展示字段”和“过滤字段”混为一个概念
- bear 样本是否保留变成显式业务决策，而不是产物歧义

---

#### A6. 增加 `errors / skips / no_signal` 三类统计

**问题**  
当前计划只提 `errors`，不够。项目里“异常失败”、“数据不足/日期落后被跳过”、“正常但无信号”是三种不同状态。

**修复**

`process_stock` 返回统一结构：

```python
{
    "signals": [...],
    "errors": [...],
    "skips": [...],
    "status": "ok" | "error" | "skip" | "no_signal",
}
```

建议分类：

- `errors`
  - 读取异常
  - WyckoffEngine 异常
  - Future timeout
- `skips`
  - `insufficient_data`
  - `stale_symbol`
- `no_signal`
  - 数据正常，但 `wyckoff` / `ma_cross` 都未触发

主循环汇总后输出：

```python
summary = {
    "n_scanned": len(stocks),
    "n_signals": len(all_signals),
    "n_errors": len(all_errors),
    "n_skips": len(all_skips),
    "n_no_signal": no_signal_count,
}
```

并把这些写入 JSON 顶层统计，而不只是 stdout。

**验收**

- 5199 只股票的扫描结果状态可解释
- 不再用“有没有信号”代替“有没有处理成功”

---

### Phase B: 回测口径统一（P1）

目标：让最近两天生成的回测输出至少具备“可解释、可横向比较、可复现到限定范围”。

#### B1. 统一 `config` 元信息

所有回测 JSON 必须至少包含：

```python
"config": {
    "schema_version": "1.0",
    "generated_at": "ISO8601",
    "n_stocks": int,
    "n_windows": int,
    "min_year": int | None,
    "max_year": int | None,
    "period_label": str,
    "with_costs": bool,
    "cost_model": {...} | None,
    "seed_python_random": int | None,
    "seed_numpy": int | None,
    "strategies_used": [...],
    "portfolio_sharpe_method": "estimated_from_correlation" | "actual_from_portfolio_returns",
}
```

最小修正项：

- [scripts/run_dual_strat_backtest.py](/home/james/Documents/Project/lppl/scripts/run_dual_strat_backtest.py) 的 period 改成真实的 `2020-2025`
- 三个 `tristrat` 输出增加 period 元信息
- 双策略输出显式写清 `with_costs`

---

#### B2. 统一 ATR 算法

**问题**  
`daily_signals` 近似 True Range，`run_dual_strat_backtest.py` 只算 `high-low`。

**修复**

把回测中的 `calc_atr()` 对齐到信号脚本的实现逻辑，至少统一为同一种近似 True Range 算法。

**注意**  
这里的目标不是金融教科书上的“最优 ATR 实现”，而是**项目内口径一致**。

---

#### B3. 收敛可复现性定义

**问题**  
只加 `np.random.seed(42)` 不足以让结果“完全可复现”。

**P1 目标**

把可复现性定义为：

1. 在同一份输入数据快照上
2. 在相同脚本版本上
3. 在固定 `random.seed` 和 `np.random.seed` 下
4. Monte Carlo 结果可复现到相同数值

需要做的修改：

```python
random.seed(SEED)
np.random.seed(SEED)
```

并在输出里增加：

```python
"data_snapshot_note": "Results depend on local TDX data snapshot"
```

**说明**  
这解决的是“算法随机性”，不解决“底层市场数据每天变化”。

---

#### B4. 明确组合 Sharpe 计算方法

**问题**  
当前组合 Sharpe 是估算值，不是真实组合净值序列。

**P1 修复**

- 先保留公式法
- 但必须在输出中标明 `portfolio_sharpe_method = estimated_from_correlation`
- 在文档里明确“不可与真实组合回测 Sharpe 等价理解”

**P2 或后续**

如果要改成真实组合 Sharpe，需要先定义：

- 时间粒度
- 组合持仓重叠规则
- 现金占用方式
- 再平衡和空仓收益处理

在这些规则未定前，不直接承诺“本轮修成真实组合序列”。

---

#### B5. 统一成本口径或至少显式区分

**问题**  
`run_dual_strat_backtest.py` 扣成本，`run_dual_strat_wyckoff_ma.py` 不扣成本，文件名却不足以表达差异。

**修复**

二选一：

1. 统一都扣成本  
2. 保留两种版本，但输出目录名和 JSON 元信息显式写清

建议先做方案 2，低风险：

- `dual_strat_backtest_2020_costs`
- `dual_strat_wyckoff_ma_nocost`

或至少在 JSON 中强制要求：

```python
"with_costs": true | false
```

---

### Phase C: 框架收敛（P2）

原则：**先统一口径，再抽象框架。**

#### C1. 不直接合并 6 个脚本

当前不直接创建一个“大一统 backtest 框架”替换全部脚本。  
先逐个脚本把以下口径收敛：

- period
- 成本
- ATR
- seed
- 输出 schema
- portfolio sharpe method

#### C2. 收敛后再提取公共函数

建议拆成两个文件：

- `scripts/backtest_common.py`
- `scripts/run_backtest.py`

先提取这些真正已统一的部分：

- `load_stocks`
- `load_csi300`
- `get_regime`
- 统一版 `calc_atr`
- `ann_sharpe`
- JSON 输出函数

不要在口径未统一前抽象 `trade_wyckoff / trade_ma / trade_str` 的业务参数。

---

## 四、执行顺序

```text
Phase A (P0, 约 1.5h)
  A1 logging
  A2 分析日期策略显式化
  A3 负风险修复
  A4 JSON 严格化
  A5 regime 字段拆分
  A6 errors / skips / no_signal 统计

Phase B (P1, 约 2h)
  B1 回测 config 元信息统一
  B2 ATR 统一
  B3 seed + 数据快照说明
  B4 组合 Sharpe 方法显式标注
  B5 成本口径显式区分

Phase C (P2, 约 3h)
  C1 逐脚本收敛
  C2 提取公共函数
  C3 新 CLI 入口
  C4 旧脚本 deprecated 标记
```

---

## 五、Definition of Done

### `daily_signals`

- JSON 中 `NaN` 数量为 0
- `risk_pct` 无负数
- 顶层包含 `schema_version`、`generated_at`、`market_anchor_date`
- 5199 只股票扫描结果状态可解释，而不是“都有信号”
- 顶层包含 `errors / skips / no_signal` 统计

### 回测输出

- 每个结果文件都有明确 period / with_costs / seeds / sharpe_method
- `dual_strat_backtest_2020` 的 period 元信息修正为真实值
- 双策略与三策略输出 schema 可横向对照
- ATR 口径在信号脚本与回测脚本间一致

### 框架层

- 只有在口径统一后才进行公共抽象
- 抽出的公共函数不再复制粘贴

---

## 六、不做事项

- 不修改 `WyckoffEngine` 核心置信度逻辑
- 不修改 MA5/20 金叉触发条件
- 不引入数据库存储
- 不新增交易策略
- 不在本轮直接把估算型组合 Sharpe 伪装成真实组合回测 Sharpe
