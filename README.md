# LPPL 泡沫检测系统

基于 LPPL (Log-Periodic Power Law) 模型的金融泡沫检测系统。

## 项目结构

```
lppl/
├── main.py                 # 主程序入口
├── lppl_verify_v2.py       # 验证脚本
├── lppl_walk_forward.py    # Walk-Forward 盲测脚本
├── src/
│   ├── constants.py        # 配置常量
│   ├── lppl_core.py        # LPPL 核心算法
│   ├── lppl_engine.py      # LPPL 计算引擎
│   ├── lppl_fit.py         # 模型拟合
│   ├── computation.py      # 并发计算
│   ├── data/
│   │   ├── manager.py      # 数据管理
│   │   └── tdx_reader.py   # 通达信数据读取
│   ├── reporting/
│   │   ├── html_generator.py       # HTML 报告生成
│   │   ├── plot_generator.py       # 图表生成
│   │   └── verification_report.py  # 验证报告生成
│   └── verification/
│       └── walk_forward.py # Walk-Forward 验证
├── tests/
│   ├── unit/               # 单元测试
│   ├── integration/        # 集成测试
│   └── fixtures/           # 测试数据
├── output/                 # 输出目录
│   └── MA/                 # 验证输出
│       ├── raw/            # 原始数据
│       ├── plots/          # 图表
│       ├── reports/        # 报告
│       └── summary/        # 汇总
└── data/                   # 数据目录
```

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

## 质量门禁命令

### 1. 代码编译检查

```bash
# 编译所有核心模块
.venv/bin/python -m compileall main.py src lppl_verify_v2.py lppl_walk_forward.py
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
```

参数说明:
- `--symbol, -s`: 指数代码
- `--all, -a`: 验证所有 8 个指数
- `--ensemble, -e`: 使用 Ensemble 多窗口共识模式
- `--max-peaks, -m`: 每个指数最多分析的高点数 (默认 10)
- `--step`: 扫描步长 (默认 5)
- `--ma`: 移动平均窗口 (默认 5)
- `--output, -o`: 输出目录 (默认 output/MA)

### Walk-Forward 盲测

```bash
# 单窗口模式
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH

# Ensemble 模式
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH --ensemble

# 自定义参数
.venv/bin/python lppl_walk_forward.py --symbol 000001.SH --step 5 --lookahead 60 --drop-threshold 0.10
```

参数说明:
- `--symbol, -s`: 指数代码 (默认 000001.SH)
- `--ensemble, -e`: 使用 Ensemble 模式
- `--step`: 扫描步长 (默认 5)
- `--lookahead`: 未来观察天数 (默认 60)
- `--drop-threshold`: 未来跌幅阈值 (默认 0.10)
- `--output, -o`: 输出目录

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

## 许可证

MIT License
