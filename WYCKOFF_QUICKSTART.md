# 威科夫多模态分析系统 - 快速开始

## 安装

确保已安装项目依赖：

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## 使用方法

统一入口优先：

```bash
.venv/bin/python main.py wyckoff-multimodal ...
```

根目录 `wyckoff_multimodal_analysis.py` 仍可用，但仅作为兼容 wrapper 保留。

### 1. 数据-only 模式 (指数)

```bash
.venv/bin/python main.py wyckoff-multimodal --symbol 000300.SH
```

### 2. 数据-only 模式 (个股)

```bash
.venv/bin/python main.py wyckoff-multimodal --symbol 600519.SH
```

### 3. 数据 + 图片融合模式

```bash
.venv/bin/python main.py wyckoff-multimodal --symbol 600519.SH --chart-dir output/MA/plots
```

### 4. 图片-only 模式

```bash
.venv/bin/python main.py wyckoff-multimodal --chart-dir output/MA/plots
```

### 5. 文件输入模式

```bash
.venv/bin/python main.py wyckoff-multimodal --input-file data/600519.parquet
```

## 输出目录结构

```
output/wyckoff/<symbol>/
├── raw/
│   └── analysis_<symbol>.json          # 原始分析结果 JSON
├── plots/
│   └── <symbol>_wyckoff_overview.png   # 威科夫概览图 (可选)
├── reports/
│   ├── <symbol>_wyckoff_report.md      # Markdown 报告
│   └── <symbol>_wyckoff_report.html    # HTML 报告
├── summary/
│   └── analysis_summary_<symbol>.csv   # CSV 摘要
├── state/
│   └── <symbol>_wyckoff_state.json     # 状态文件 (连续性追踪)
└── evidence/
    └── <symbol>_chart_manifest.json    # 图像清单 (如有图片)
```

## 核心特性

### Step 0: BC 定位
- 自动扫描 Buying Climax
- BC 未找到 → D 级置信度 + abandon

### Step 1: 大局观与阶段
- 5 阶段识别：accumulation / markup / distribution / markdown / no_trade_zone
- 边界来源：BC / AR / SC / ST / 放量极值带

### Step 2: 努力与结果
- 放量滞涨 / 缩量上推检测
- 吸筹/派发证据评分

### Step 3: Phase C 终极测试
- Spring / UTAD / ST / False Breakout 检测
- Spring 后自动 T+3 冷冻期

### Step 3.5: 反事实压力测试
- 四组反证评估
- 反证强于正证 → 推翻结论

### Step 4: T+1 与盈亏比
- T+1 风险评估
- R:R < 1:2.5 → 强制放弃

### Step 5: 交易计划
- A 股强约束：Distribution/Markdown 禁止多头
- 固定输出字段：direction / trigger / invalidation / target_1

## 运行测试

```bash
# 单元测试
.venv/bin/python -m pytest tests/unit/test_wyckoff_*.py -v

# 集成测试
.venv/bin/python -m pytest tests/integration/test_wyckoff_*.py -v

# 全部测试
.venv/bin/python -m pytest tests/ -v
```

## 示例输出

### Markdown 报告摘要

```markdown
# 威科夫多模态分析报告 - 600519.SH

**分析日期**: 2026-04-08
**资产类型**: stock

## Step 0: BC 定位
- **BC 是否找到**: 是
- **置信度**: B

## Step 1: 大局观与阶段
- **当前阶段**: accumulation
- **上边界**: 1800
- **下边界**: 1600

## Step 5: 交易计划
- **方向**: watch_only
- **触发条件**: spring_confirmation
- **止损**: 1580
- **目标**: 1800
- **置信度**: B
```

## 注意事项

1. **图像引擎依赖**: 图像质量评估需要 OpenCV (`pip install opencv-python`)
2. **LLM 增强**: 可选，无需配置也可完整运行
3. **A 股约束**: 系统严格遵守 T+1 制度，绝不输出做空建议
4. **保守降级**: 证据冲突/图像模糊/BC 不清时自动降级

## 常见问题

### Q: 找不到 BC 怎么办？
A: BC 未找到时系统自动输出 `abandon` 结论，这是正常的风控机制。

### Q: 图片-only 模式为什么置信度最高 C 级？
A: 缺少 OHLCV 数据支持，视觉证据只能作为低置信观察。

### Q: Spring 冷冻期多久？
A: Spring 检测后自动设置 T+3 冷冻期，冷冻期内只允许 `watch_only`。

## 架构文档

详细架构设计请参考：
- `docs/PRD_WYCKOFF_MULTIMODAL_ANALYSIS_20260407.md`
- `docs/ARCH_WYCKOFF_MULTIMODAL_ANALYSIS_20260407.md`
- `docs/DETAILED_IMPLEMENTATION_PLAN_WYCKOFF_20260408.md`
