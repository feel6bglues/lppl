# LPPL 泡沫检测系统

基于 LPPL (Log-Periodic Power Law) 模型的金融泡沫检测系统。

## 项目结构

```
lppl/
├── main.py                 # 兼容入口（wrapper）
├── lppl_verify_v2.py       # 兼容入口（wrapper）
├── lppl_walk_forward.py    # 兼容入口（wrapper）
├── index_investment_analysis.py  # 指数投资分析入口（wrapper）
├── generate_optimal8_report.py  # 兼容入口（wrapper）
├── src/
│   ├── cli/                # 实际 CLI 实现
│   │   ├── main.py
│   │   ├── lppl_verify_v2.py
│   │   ├── lppl_walk_forward.py
│   │   ├── index_investment_analysis.py
│   │   └── generate_optimal8_report.py
│   ├── constants.py        # 配置常量
│   ├── lppl_core.py        # LPPL 核心算法
│   ├── lppl_engine.py      # LPPL 计算引擎
│   ├── lppl_fit.py         # 模型拟合
│   ├── computation.py      # 并发计算
│   ├── data/
│   │   ├── manager.py      # 数据管理
│   │   └── tdx_reader.py   # 通达信数据读取
│   ├── investment/
│   │   └── backtest.py     # 投资信号、回测、回撤计算
│   ├── reporting/
│   │   ├── html_generator.py       # HTML 报告生成
│   │   ├── investment_report.py    # 投资分析报告生成
│   │   ├── plot_generator.py       # 图表生成
│   │   └── verification_report.py  # 验证报告生成
│   └── verification/
│       └── walk_forward.py # Walk-Forward 验证
├── tests/
│   ├── unit/               # 单元测试
│   ├── integration/        # 集成测试
│   └── fixtures/           # 测试数据
├── scripts/                # 研究/实验脚本
│   ├── ensemble_grid_search.py
│   ├── lppl_backtest.py
│   ├── verify_lppl.py
│   ├── test_lppl_ma.py
│   └── lppl.py
├── docs/                   # 项目文档
│   ├── 使用文档.md
│   ├── lppl_backtest_report.md
│   └── archive/            # 历史规划文档归档
│       ├── plan.md
│       ├── task.md
│       └── target.md
├── output/                 # 输出目录
│   └── MA/                 # 验证输出
│       ├── raw/            # 原始数据
│       ├── plots/          # 图表
│       ├── reports/        # 报告
│       └── summary/        # 汇总
└── data/                   # 数据目录
```

文档入口：
- 详细使用说明：`docs/使用文档.md`
- 历史规划归档：`docs/archive/`

## 环境配置

### 依赖安装

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install 'mootdx[all]'
```

### 环境变量

```bash
# 通达信数据目录 (可选，有默认值)
export LPPL_TDX_DATA_DIR="/path/to/tdx/vipdoc"

# 输出目录 (可选)
export LPPL_VERIFY_OUTPUT_DIR="output/MA"
export LPPL_PLOTS_DIR="output/MA/plots"
export LPPL_REPORTS_DIR="output/MA/reports"
export LPPL_SUMMARY_DIR="output/MA/summary"
export LPPL_RAW_DIR="output/MA/raw"
```

## 快速上手（3条命令）

```bash
# 1) 安装依赖
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) 先跑验证（推荐：按指数最优参数）
.venv/bin/python lppl_verify_v2.py --all --ensemble --use-optimal-config

# 3) 再跑盲测（单指数示例）
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH --ensemble --use-optimal-config

# 4) 跑指数投资分析（净值/回撤/K线对比）
.venv/bin/python index_investment_analysis.py \
  --symbol 000001.SH \
  --start-date 2023-01-01 \
  --end-date 2024-12-31

# 5) 跑信号调优（单指数示例）
.venv/bin/python tune_signal_model.py \
  --symbol 000001.SH \
  --start-date 2023-01-01 \
  --end-date 2024-12-31

# 6) 跑二轮原子化调优（局部精调示例）
.venv/bin/python tune_signal_model.py \
  --symbols 000300.SH,000016.SH \
  --start-date 2020-01-01 \
  --sell-votes 2,3 \
  --sell-confirms 2,3 \
  --vol-breakout-grid 1.00,1.02 \
  --drawdown-grid 0.05,0.08 \
  --cooldown-grid 10,15 \
  --buy-volatility-cap-grid 1.00 \
  --scoring-profile risk_reduction
```

说明：
- 若不想启用最优参数模式，去掉 `--use-optimal-config` 即可。
- 最优参数默认读取 `config/optimal_params.yaml`，可用 `--optimal-config-path` 指定其他路径。
- 投资分析建议显式传入 `--start-date` / `--end-date`，避免扫描全历史带来的额外耗时。
- 信号调优会在 `config/optimal_params.yaml` 的 LPPL 最优参数基础上，继续搜索多因子买卖信号参数。
- 二轮调优支持 `--symbols`、`--cooldown-grid`、`--buy-volatility-cap-grid` 和评分硬门槛参数，适合分批细调。

## 质量门禁命令

### 1. 代码编译检查

```bash
# 编译所有核心模块
.venv/bin/python -m compileall main.py src lppl_verify_v2.py lppl_walk_forward.py index_investment_analysis.py
```

### 2. 单元测试

```bash
# 运行所有单元测试
.venv/bin/python -m unittest discover tests/unit/ -v

# 运行单个测试文件
.venv/bin/python -m unittest tests.unit.test_lppl_engine_ensemble -v
```

### 3. Lint 检查

```bash
# 运行 Ruff 静态检查
.venv/bin/ruff check .
```

### 4. 集成测试

```bash
# 运行所有集成测试
.venv/bin/python -m unittest discover tests/integration/ -v

# 运行单个集成测试
.venv/bin/python -m unittest tests.integration.test_end_to_end -v
```

### 5. 全量测试

```bash
# 运行所有测试 (单元 + 集成)
.venv/bin/python -m unittest discover tests/unit -v
.venv/bin/python -m unittest discover tests/integration -v
```

### 6. Smoke Run

```bash
# 单指数最小验证链路
.venv/bin/python lppl_verify_v2.py --symbol 000001.SH --max-peaks 1

# Walk-forward 最小盲测
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH --step 20 --lookahead 60

# 指数投资分析最小链路
.venv/bin/python index_investment_analysis.py \
  --symbol 000001.SH \
  --start-date 2025-01-01 \
  --end-date 2025-12-31 \
  --output output/investment_smoke

# 单指数信号调优最小链路
.venv/bin/python tune_signal_model.py \
  --symbol 000001.SH \
  --start-date 2024-01-01 \
  --end-date 2024-06-30 \
  --positive-offsets 0.00 \
  --negative-offsets 0.00 \
  --sell-votes 3 \
  --buy-votes 3 \
  --sell-confirms 2 \
  --buy-confirms 2 \
  --vol-breakout-grid 1.05 \
  --drawdown-grid 0.05
```

## 运行指南

### 主程序 - LPPL 扫描

```bash
# 运行主程序，扫描所有指数
.venv/bin/python main.py
```

输出文件:
- `output/lppl_report_YYYYMMDD.md` - Markdown 报告
- `output/lppl_report_YYYYMMDD.html` - HTML 可视化报告
- `output/lppl_params_YYYYMMDD.json` - 完整参数 JSON

### 验证程序 - LPPL 验证

```bash
# 验证单个指数 (默认上证综指)
.venv/bin/python lppl_verify_v2.py --symbol 000001.SH

# 验证所有指数
.venv/bin/python lppl_verify_v2.py --all

# 使用 Ensemble 模式
.venv/bin/python lppl_verify_v2.py --symbol 000001.SH --ensemble

# 验证所有指数 + Ensemble 模式
.venv/bin/python lppl_verify_v2.py --all --ensemble

# 自定义参数
.venv/bin/python lppl_verify_v2.py --symbol 000001.SH --max-peaks 5 --step 5 --ma 5

# 使用按指数最优参数（YAML）
.venv/bin/python lppl_verify_v2.py --all --ensemble --use-optimal-config
```

参数说明:
- `--symbol, -s`: 指数代码
- `--all, -a`: 验证所有 8 个指数
- `--ensemble, -e`: 使用 Ensemble 多窗口共识模式
- `--max-peaks, -m`: 每个指数最多分析的高点数 (默认 10)
- `--step`: 扫描步长 (默认 5)
- `--ma`: 移动平均窗口 (默认 5)
- `--output, -o`: 输出目录 (默认 output/MA)
- `--use-optimal-config`: 启用按指数最优参数模式（从 YAML 读取）
- `--optimal-config-path`: 最优参数 YAML 路径 (默认 `config/optimal_params.yaml`)

### Walk-Forward 盲测

```bash
# 单窗口模式
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH

# Ensemble 模式
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH --ensemble

# 自定义参数
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH --step 5 --lookahead 60 --drop-threshold 0.10

# 使用按指数最优参数（YAML）
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH --ensemble --use-optimal-config
```

参数说明:
- `--symbol, -s`: 指数代码 (默认 000001.SH)
- `--ensemble, -e`: 使用 Ensemble 模式
- `--step`: 扫描步长 (默认 5)
- `--lookahead`: 未来观察天数 (默认 60)
- `--drop-threshold`: 未来跌幅阈值 (默认 0.10)
- `--output, -o`: 输出目录
- `--use-optimal-config`: 启用按指数最优参数模式（从 YAML 读取）
- `--optimal-config-path`: 最优参数 YAML 路径 (默认 `config/optimal_params.yaml`)

### 指数投资分析

```bash
# 单指数投资分析
.venv/bin/python index_investment_analysis.py \
  --symbol 000001.SH \
  --start-date 2023-01-01 \
  --end-date 2024-12-31

# 自定义资金、滑点和手续费
.venv/bin/python index_investment_analysis.py \
  --symbol 000300.SH \
  --start-date 2021-01-01 \
  --end-date 2024-12-31 \
  --initial-capital 1000000 \
  --buy-fee 0.0003 \
  --sell-fee 0.0003 \
  --slippage 0.0005 \
  --step 5 \
  --output output/investment

# 使用按指数最优参数（YAML）
.venv/bin/python index_investment_analysis.py \
  --symbol 000001.SH \
  --start-date 2023-01-01 \
  --end-date 2024-12-31 \
  --use-optimal-config
```

输出文件：
- `output/investment/raw/signals_*.csv` - 逐日投资信号
- `output/investment/raw/equity_*.csv` - 逐日净值、仓位、回撤
- `output/investment/raw/trades_*.csv` - 交易流水
- `output/investment/summary/summary_*.csv` - 策略汇总
- `output/investment/plots/*_strategy_overview.png` - 净值 vs 基准 + 日K线 + 买卖点
- `output/investment/plots/*_strategy_drawdown.png` - 回撤曲线
- `output/investment/reports/investment_analysis_report.md` - Markdown 报告
- `output/investment/reports/investment_analysis_report.html` - HTML 报告

参数说明：
- `--symbol, -s`: 指数代码
- `--start-date`: 回测起始日期 `YYYY-MM-DD`
- `--end-date`: 回测结束日期 `YYYY-MM-DD`
- `--ensemble, -e`: 使用 Ensemble 多窗口共识模式
- `--step`: LPPL 信号扫描步长，越大越快，默认 `5`
- `--initial-capital`: 初始资金，默认 `1000000`
- `--buy-fee`: 买入手续费，默认 `0.0003`
- `--sell-fee`: 卖出手续费，默认 `0.0003`
- `--slippage`: 滑点，默认 `0.0005`
- `--output, -o`: 输出目录，默认 `output/investment`
- `--use-optimal-config`: 启用按指数最优参数模式（从 YAML 读取）
- `--optimal-config-path`: 最优参数 YAML 路径

说明：
- 投资分析当前按`指数层`运行，不做 ETF/场外基金映射。
- 回测模型为`收盘后出信号，下一交易日开盘执行`。
- 若区间很长，优先通过 `--start-date` / `--end-date` 和 `--step` 控制性能。

### 最优参数配置（YAML）

- 默认配置文件：`config/optimal_params.yaml`
- 结构：
  - `window_sets`: 窗口集合定义
  - `symbols`: 每个指数的最优参数（`step/window_set/r2_threshold/consensus_threshold/danger_days/optimizer`）
  - `defaults`: 全局默认参数
- 回退策略：
  - 若配置文件缺失、无法解析，或某指数未配置，系统会打印告警并回退到默认参数，不中断运行

### 8指数可读报告（固化模板）

```bash
# 基于 8 指数 walk-forward 汇总 CSV 生成可读报告 + 4 张图
.venv/bin/python generate_optimal8_report.py \
  --summary-csv output/MA/summary/walk_forward_optimal_8index_summary_YYYYMMDD_HHMMSS.csv
```

输出：
- `output/MA/reports/optimal8_human_friendly_report_v2_*.md`
- `output/MA/plots/optimal8_*_readable_*.png`

## 验证循环 (Verification Loop)

每次重要变更后执行以下步骤:

```bash
#!/bin/bash
# verification_loop.sh

echo "=== 1. 编译检查 ==="
.venv/bin/python -m compileall main.py src lppl_verify_v2.py lppl_walk_forward.py tests/ || exit 1

echo "=== 2. 单元测试 ==="
.venv/bin/python -m unittest discover tests/unit/ -v || exit 1

echo "=== 3. Lint 检查 ==="
.venv/bin/ruff check . || exit 1

echo "=== 4. 集成测试 ==="
.venv/bin/python -m unittest discover tests/integration/ -v || exit 1

echo "=== 5. Smoke Test (单指数验证) ==="
.venv/bin/python lppl_verify_v2.py --symbol 000001.SH --max-peaks 1 || exit 1

echo "=== 6. Wyckoff Analysis Smoke Test ==="
.venv/bin/python wyckoff_analysis.py --symbol 000001.SH || exit 1

echo "=== 所有验证通过 ==="
```

## 支持的指数

| 代码 | 名称 | 数据源 |
|-----|------|-------|
| 000001.SH | 上证综指 | TDX 本地 |
| 399001.SZ | 深证成指 | TDX 本地 |
| 399006.SZ | 创业板指 | TDX 本地 |
| 000016.SH | 上证50 | TDX 本地 |
| 000300.SH | 沪深300 | TDX 本地 |
| 000905.SH | 中证500 | TDX 本地 |
| 000852.SH | 中证1000 | TDX 本地 |
| 932000.SH | 中证2000 | akshare |

## 风险等级定义

| days_left | 风险等级 | 含义 |
|-----------|---------|------|
| < 5 天 | 极高危 (DANGER) | 紧急预警，需立即关注 |
| < 20 天 | 高危 (Warning) | 高风险，注意市场波动 |
| < 60 天 | 观察 (Watch) | 中等风险，持续关注 |
| >= 60 天 | 安全 (Safe) | 暂无崩盘风险 |

## 输出工件

验证程序生成四类工件:

1. **raw/**: 每个 peak 的原始 timeline 数据 (parquet)
2. **plots/**: PNG 图表
   - 价格时间线图
   - Ensemble 共识度图
   - 预测崩盘时间离散图
   - 汇总统计图
3. **reports/**: Markdown 和 HTML 报告
4. **summary/**: 汇总 CSV 文件

## 版本历史

| 版本 | 日期 | 变更 |
|-----|------|-----|
| v1.0.0 | 2026-03-08 | 初始版本 |
| v1.1.0 | 2026-03-08 | 优化计划 |
| v1.2.0 | 2026-03-24 | 数据源迁移到通达信本地 |
| v1.3.0 | 2026-03-29 | 验证体系整改与可视化增强 |
| v1.4.0 | 2026-03-29 | 新增按指数最优参数 YAML 配置模式 |

## 许可证

MIT License
