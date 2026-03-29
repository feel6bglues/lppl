# LPPL 系统重构与优化计划

> 项目: Log-Periodic Power Law (LPPL) 金融市场崩盘预测系统
> 版本: v1.2.0
> 日期: 2026-03-24
> 状态: ✅ 全部完成

---

## 一、项目背景

LPPL 模型是一种用于检测金融市场泡沫和预测崩盘时间的技术方法。本项目重构旨在提升性能、摆脱网络依赖，并适配 AI 决策系统。

---

## 二、重构目标

| 目标 | 描述 | 优先级 |
|-----|------|--------|
| 性能提升 | Numba JIT 加速核心计算 5-10 倍 | P0 |
| 并发优化 | joblib 替代 ProcessPoolExecutor | P1 |
| 数据迁移 | 从 akshare 迁移到通达信本地数据 | P1 |
| AI 对齐 | 风险阈值与输出格式适配 AI 提示词 | P1 |
| 功能扩展 | 新增负向泡沫检测（抄底信号） | P2 |

---

## 三、目录结构规划

```
lppl/
├── .venv/                      # 虚拟环境
├── src/
│   ├── __init__.py
│   ├── constants.py            # 配置常量（含功能开关）
│   ├── exceptions.py            # 自定义异常
│   ├── lppl_core.py            # 核心LPPL算法 (Numba JIT)
│   ├── computation.py           # 并行计算引擎 (joblib)
│   ├── data/
│   │   ├── __init__.py
│   │   ├── manager.py          # 数据管理器
│   │   └── tdx_reader.py       # 通达信本地数据读取
│   └── reporting/
│       ├── __init__.py
│       └── html_generator.py   # HTML报告生成
├── main.py                     # 主入口
├── requirements.txt             # 依赖清单
├── task.md                      # 实施计划与状态
├── output/                      # 报告输出目录
└── data/                       # 本地数据缓存
```

---

## 四、核心依赖

### requirements.txt

```txt
# Core dependencies
numpy>=1.24.0
pandas>=2.0.0
scipy>=1.10.0
pyarrow>=14.0.0

# Data fetching
akshare>=1.12.0

# Performance optimization
numba>=0.58.0
joblib>=1.3.0

# Local TDX data reader
mootdx>=0.11.7
tdxpy>=0.2.5
```

---

## 五、数据源架构

### 指数配置

| 指数名称 | 代码 | 数据源 | 路径/方式 |
|---------|------|-------|---------|
| 上证综指 | 000001.SH | TDX本地 | `vipdoc/sh/lday/sh000001.day` |
| 深证成指 | 399001.SZ | TDX本地 | `vipdoc/sz/lday/sz399001.day` |
| 创业板指 | 399006.SZ | TDX本地 | `vipdoc/sz/lday/sz399006.day` |
| 上证50 | 000016.SH | TDX本地 | `vipdoc/sh/lday/sh000016.day` |
| 沪深300 | 000300.SH | TDX本地 | `vipdoc/sh/lday/sh000300.day` |
| 中证500 | 000905.SH | TDX本地 | `vipdoc/sh/lday/sh000905.day` |
| 中证1000 | 000852.SH | TDX本地 | `vipdoc/sh/lday/sh000852.day` |
| 中证2000 | 932000.SH | akshare | `stock_zh_index_hist_csindex` |

### 数据读取优先级

```
1. 本地索引 → TDXReader (不依赖网络)
2. 中证2000 → akshare (仅此指数使用网络)
3. 全部失败 → parquet 缓存 (本地备份)
```

---

## 六、功能开关

在 `src/constants.py` 中定义：

```python
ENABLE_NUMBA_JIT: bool = True           # Numba JIT 加速
ENABLE_JOBLIB_PARALLEL: bool = True    # joblib 并行处理
ENABLE_INCREMENTAL_UPDATE: bool = True # 增量数据更新
ENABLE_NEGATIVE_BUBBLE: bool = True    # 负向泡沫检测
```

---

## 七、风险阈值

| days_left | 风险等级 | 颜色 | 含义 |
|-----------|---------|------|------|
| < 5 天 | 极高危 (DANGER) | 🔴 | 紧急预警，需立即关注 |
| < 20 天 | 高危 (Warning) | 🟠 | 高风险，注意市场波动 |
| < 60 天 | 观察 (Watch) | 🟡 | 中等风险，持续关注 |
| >= 60 天 | 安全 (Safe) | 🟢 | 暂无崩盘风险 |
| 模型无效 | 无效模型 (假信号) | ⚪ | LPPL 模型参数不满足条件 |

**模型有效条件**: `0.1 < m < 0.9` 且 `6 < w < 13`

---

## 八、性能目标

| 指标 | 当前 | 目标 | 提升 |
|-----|------|------|------|
| 单次优化时间 | ~2s | ~0.2s | 10x |
| 7指数总扫描时间 | ~5min | ~2min | 2.5x |
| 网络依赖 | 8个指数 | 1个指数 | 87.5%减少 |

---

## 九、实施阶段

### Phase 1: P0 核心优化 ✅
- [x] T2.1 引入 Numba 依赖
- [x] T2.2 Numba JIT 加速 lppl_func
- [x] T2.3 Numba JIT 加速 cost_function
- [x] T4.1 风险阈值调整

### Phase 2: P1 并发优化 ✅
- [x] T3.1 引入 joblib 依赖
- [x] T3.2 替换并发实现
- [x] T3.3 并发管理清理

### Phase 3: P1 数据源迁移 ✅
- [x] T-M1 安装 mootdx 依赖
- [x] T-M2 创建 TDXReader 模块
- [x] T-M3 更新常量配置
- [x] T-M4 集成 DataManager

### Phase 4: P2 输出与负向泡沫 ✅
- [x] T4.2 Markdown 格式优化
- [x] T5.1 负向泡沫检测函数
- [x] T5.2 集成到计算流程
- [x] T5.3 更新报告生成

---

## 十、通达信数据格式

```
文件格式: .day (二进制)
记录大小: 32 字节/条
日期格式: YYYYMMDD 整数
价格单位: 分 (除以100得到元)

字段结构:
- date (4字节): 日期整数如 20260324
- open (4字节): 开盘价(分)
- high (4字节): 最高价(分)
- low (4字节): 最低价(分)
- close (4字节): 收盘价(分)
- amount (4字节): 成交额
- volume (4字节): 成交量
- unknown (4字节): 保留
```

---

## 十一、运行指南

### 环境准备

```bash
cd /home/james/Documents/Project/lppl
source .venv/bin/activate
pip install -r requirements.txt
```

### 运行程序

```bash
python main.py
```

### 输出文件

```
output/
├── lppl_report_YYYYMMDD.md      # Markdown 报告
├── lppl_report_YYYYMMDD.html     # HTML 可视化报告
└── lppl_params_YYYYMMDD.json   # 完整参数 JSON
```

---

## 十二、版本历史

| 版本 | 日期 | 变更 |
|-----|------|-----|
| v1.0.0 | 2026-03-08 | 初始版本 |
| v1.1.0 | 2026-03-08 | 优化计划 |
| v1.1.1 | 2026-03-24 | 修复风险阈值对齐问题 |
| v1.2.0 | 2026-03-24 | 数据源迁移到通达信本地 |

---

## 十三、验证清单

- [x] Numba JIT 编译成功
- [x] joblib 并行处理正常
- [x] TDXReader 读取7个本地指数成功
- [x] akshare 中证2000获取成功
- [x] 风险阈值正确：<5=DANGER, <20=Warning, <60=Watch, >=60=Safe
- [x] 负向泡沫检测功能正常
- [x] Markdown/HTML 报告生成正常
- [x] main.py 完整流程测试通过
- [x] **项目与计划对齐度: 100%**
