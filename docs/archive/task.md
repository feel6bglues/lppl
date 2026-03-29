# LPPL 系统优化与整改实施计划

> 最近更新时间: 2026-03-29
> 当前版本: v1.3.1
> 当前状态: ✅ v1.3 验证体系与质量门禁已形成闭环

---

## 一、项目概述

### 优化目标

1. **性能提升**: 通过 Numba JIT 加速核心数学计算 5-10 倍
2. **并发优化**: 使用 joblib 替代 ProcessPoolExecutor，提升稳定性
3. **数据迁移**: 从 akshare 迁移到通达信本地数据，摆脱网络依赖
4. **AI 对齐**: 调整风险阈值与输出格式，适配 AI 决策系统
5. **功能扩展**: 新增负向泡沫检测（抄底信号）

### 预期收益

| 指标 | 当前 | 优化后 | 提升 |
|-----|------|-------|------|
| 单次优化时间 | ~2s | ~0.2s | 10x |
| 总扫描时间 | ~5min | ~2min | 2.5x |
| 内存峰值 | 不稳定 | 可控 | - |
| 网络依赖 | 8个指数 | 1个指数(中证2000) | 87.5%减少 |
| 数据延迟 | 实时 | 通达信日更 | - |

---

## 二、依赖更新

### requirements.txt 内容

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

# Local data (mootdx + tdxpy for binary parsing)
mootdx>=0.11.7
tdxpy>=0.2.5
```

### 安装命令

```bash
pip install 'mootdx[all]'
```

---

## 三、实施阶段

### Phase 1: P0 核心优化 ✅

#### 任务 T2.1: 引入 Numba 依赖

- **任务ID**: T2.1
- **描述**: 在 `requirements.txt` 中添加 `numba>=0.58.0`
- **涉及文件**: `requirements.txt`
- **状态**: ✅ 已完成

---

#### 任务 T2.2: Numba JIT 加速 lppl_func

- **任务ID**: T2.2
- **描述**: 对 `lppl_func` 添加 `@njit` 装饰器
- **涉及文件**: `src/lppl_core.py`
- **状态**: ✅ 已完成

---

#### 任务 T2.3: Numba JIT 加速 cost_function

- **任务ID**: T2.3
- **描述**: 对 `cost_function` 添加 `@njit` 装饰器
- **涉及文件**: `src/lppl_core.py`
- **状态**: ✅ 已完成

---

#### 任务 T4.1: 风险阈值调整

- **任务ID**: T4.1
- **描述**: 调整风险评级阈值，与 AI 提示词对齐
- **涉及文件**: `src/lppl_core.py`

| days_left | 风险等级 | 含义 |
|-----------|---------|------|
| < 5 天 | 极高危 (DANGER) | 紧急预警，需立即关注 |
| < 20 天 | 高危 (Warning) | 高风险，注意市场波动 |
| < 60 天 | 观察 (Watch) | 中等风险，持续关注 |
| >= 60 天 | 安全 (Safe) | 暂无崩盘风险 |
| 模型无效 | 无效模型 (假信号) | LPPL 模型参数不满足条件 |

- **状态**: ✅ 已完成

---

### Phase 2: P1 并发优化 ✅

#### 任务 T3.1: 引入 joblib 依赖

- **任务ID**: T3.1
- **状态**: ✅ 已完成

---

#### 任务 T3.2: 替换并发实现

- **任务ID**: T3.2
- **描述**: 使用 joblib Parallel 替代 ProcessPoolExecutor
- **涉及文件**: `src/computation.py`
- **状态**: ✅ 已完成

---

#### 任务 T3.3: 并发管理清理

- **任务ID**: T3.3
- **状态**: ✅ 已完成

---

### Phase 3: P1 数据源迁移 ✅

#### 任务 T-M1: 安装 mootdx 依赖

- **任务ID**: T-M1
- **描述**: 安装 mootdx 和 tdxpy 库
- **验证**: `pip install 'mootdx[all]'`
- **状态**: ✅ 已完成

---

#### 任务 T-M2: 创建 TDXReader 模块

- **任务ID**: T-M2
- **描述**: 创建通达信本地数据读取模块
- **涉及文件**: `src/data/tdx_reader.py` (新建)
- **功能**:
  - 直接读取 `.day` 二进制文件（不依赖 Wine）
  - 支持上证/深证指数
  - 自动解析价格和日期
- **状态**: ✅ 已完成

---

#### 任务 T-M3: 更新常量配置

- **任务ID**: T-M3
- **描述**: 更新指数配置，区分本地和 akshare 数据源
- **涉及文件**: `src/constants.py`
- **配置**:

```python
TDX_DATA_DIR: str = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"

LOCAL_DATA_INDICES: List[str] = [
    "000001.SH",  # 上证综指
    "399001.SZ",  # 深证成指
    "399006.SZ",  # 创业板指
    "000016.SH",  # 上证50
    "000300.SH",  # 沪深300
    "000905.SH",  # 中证500
    "000852.SH",  # 中证1000
]

AKSHARE_INDICES: List[str] = [
    "932000.SH",  # 中证2000 (仅此指数使用 akshare)
]
```

- **状态**: ✅ 已完成

---

#### 任务 T-M4: 集成 TDXReader 到 DataManager

- **任务ID**: T-M4
- **描述**: 修改 DataManager 集成通达信读取
- **涉及文件**: `src/data/manager.py`
- **新增方法**:
  - `_read_from_tdx()`: 从通达信读取
  - `_read_from_parquet()`: 从本地缓存读取
- **读取优先级**:
  1. 本地索引 → TDXReader 读取
  2. 中证2000 → akshare 获取
  3. 全部失败 → parquet 缓存
- **状态**: ✅ 已完成

---

### Phase 4: P2 输出与负向泡沫 ✅

#### 任务 T4.2: Markdown 格式优化

- **任务ID**: T4.2
- **状态**: ✅ 已完成

---

#### 任务 T5.1: 负向泡沫检测函数

- **任务ID**: T5.1
- **描述**: 实现负向泡沫（抄底信号）检测函数
- **涉及文件**: `src/lppl_core.py`
- **新增函数**:
  - `detect_negative_bubble()`: 检测抄底信号
  - `calculate_bottom_signal_strength()`: 计算信号强度
- **状态**: ✅ 已完成

---

#### 任务 T5.2: 集成到计算流程

- **任务ID**: T5.2
- **状态**: ✅ 已完成

---

#### 任务 T5.3: 更新报告生成

- **任务ID**: T5.3
- **状态**: ✅ 已完成

---

## 四、数据源配置

### 指数数据源映射

| 指数名称 | LPPL代码 | 数据源 | 路径 |
|---------|---------|-------|------|
| 上证综指 | 000001.SH | **TDX本地** | `sh/lday/sh000001.day` |
| 深证成指 | 399001.SZ | **TDX本地** | `sz/lday/sz399001.day` |
| 创业板指 | 399006.SZ | **TDX本地** | `sz/lday/sz399006.day` |
| 上证50 | 000016.SH | **TDX本地** | `sh/lday/sh000016.day` |
| 沪深300 | 000300.SH | **TDX本地** | `sh/lday/sh000300.day` |
| 中证500 | 000905.SH | **TDX本地** | `sh/lday/sh000905.day` |
| 中证1000 | 000852.SH | **TDX本地** | `sh/lday/sh000852.day` |
| 中证2000 | 932000.SH | **akshare** | 在线获取 |

### 通达信数据格式

```
文件格式: .day (二进制)
记录大小: 32 字节/条
日期格式: YYYYMMDD 整数
价格单位: 分 (除以100得到元)
```

---

## 五、功能开关配置

```python
ENABLE_NUMBA_JIT: bool = True          # Numba JIT 加速
ENABLE_JOBLIB_PARALLEL: bool = True    # joblib 并行处理
ENABLE_INCREMENTAL_UPDATE: bool = True # 增量数据更新
ENABLE_NEGATIVE_BUBBLE: bool = True   # 负向泡沫检测
```

---

## 六、测试验证（v1.2 存量）

### 单元测试

| 测试项 | 状态 |
|-------|------|
| TDXReader 读取7个指数 | ✅ |
| DataManager 集成 TDX | ✅ |
| calculate_risk_level 边界值 | ✅ |
| detect_negative_bubble 信号检测 | ✅ |
| main.py 完整流程 | ✅ |

### 性能基准

| 指标 | 目标 | 实际 |
|-----|------|------|
| 7个指数扫描时间 | < 180s | ~138s ✅ |
| 单指数平均时间 | < 20s | ~19s ✅ |

---

## 七、v1.3 整改与可视化实施清单

> 目标:
> 1. 修正验证链路名实不符的问题
> 2. 将 Ensemble 真正接入主验证流程
> 3. 输出可追溯的原始验证明细数据
> 4. 自动生成 PNG 图表，并嵌入 Markdown / HTML 报告
> 5. 建立最小回归基线与测试门禁

### Phase A: P0 数据与配置修正

#### 任务 A1: 统一 DataManager 状态枚举

- **任务ID**: A1
- **优先级**: P0
- **涉及文件**: `src/data/manager.py`, `main.py`
- **状态**: ✅ 已完成
- **动作**:
  - 收敛 `update_all_data()` 返回状态
  - 区分 `available_local`, `available_cache`, `updated_remote`, `stale`, `missing`, `failed`
  - 让 `main.py` 按统一状态统计成功/失败
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_data_manager_statuses`
  - `.venv/bin/python -m compileall main.py src tests/unit/test_data_manager_statuses.py`
- **验收标准**:
  - 本地 TDX 可读时，不再出现“数据不可用但随后又成功加载”的矛盾日志

#### 任务 A2: 修正本地指数可用性判断

- **任务ID**: A2
- **优先级**: P0
- **涉及文件**: `src/data/manager.py`
- **前置依赖**: A1
- **状态**: ✅ 已完成
- **动作**:
  - 本地指数优先检查 TDX 数据可读性，而不是 parquet 是否存在
  - akshare 指数继续走远程 / parquet fallback
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_data_manager_statuses`
  - `.venv/bin/python - <<'PY' ... DataManager().update_all_data() ... PY`
- **验收标准**:
  - `update_all_data()` 的结果与 `get_all_indices_data()` 的实际加载结果一致

#### 任务 A3: 删除 `_read_from_parquet()` 不可达重复代码

- **任务ID**: A3
- **优先级**: P0
- **涉及文件**: `src/data/manager.py`
- **状态**: ✅ 已完成
- **动作**:
  - 删除 `return` 之后的重复逻辑
  - 明确 `_read_from_tdx()` / `_read_from_parquet()` / `get_data()` 职责边界
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_data_manager_statuses`
  - `.venv/bin/python -m compileall main.py src tests/unit/test_data_manager_statuses.py`
  - `.venv/bin/python - <<'PY' ... DataManager().update_all_data() ... PY`
- **验收标准**:
  - 数据读取路径单一、无不可达代码

#### 任务 A4: 外置化 TDX 路径与验证配置

- **任务ID**: A4
- **优先级**: P0
- **涉及文件**: `src/constants.py`
- **状态**: ✅ 已完成
- **动作**:
  - `TDX_DATA_DIR` 改为环境变量优先
  - 为验证体系预留 `LPPL_VERIFY_OUTPUT_DIR`, `LPPL_PLOTS_DIR` 等配置入口
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_data_manager_statuses tests.unit.test_constants_config`
  - `.venv/bin/python -m compileall main.py src tests/unit/test_data_manager_statuses.py tests/unit/test_constants_config.py`
- **验收标准**:
  - 不改源码即可迁移到新机器

### Phase B: P0 验证链路收敛

#### 任务 B1: 明确 `lppl_verify_v2.py` 的双模式职责

- **任务ID**: B1
- **优先级**: P0
- **涉及文件**: `lppl_verify_v2.py`
- **状态**: ✅ 已完成
- **动作**:
  - 保留 `single-window` 与 `ensemble` 两种模式
  - 将命令行帮助文本、报告标题、输出文件名与真实模式对齐
- **验证**:
  - `.venv/bin/python -m compileall lppl_verify_v2.py`
  - `.venv/bin/python lppl_verify_v2.py --help`
- **验收标准**:
  - 用户从命令行和报告中能看出当前运行的是哪种验证模式

#### 任务 B2: 新增 `analyze_peak_ensemble()`

- **任务ID**: B2
- **优先级**: P0
- **涉及文件**: `src/lppl_engine.py`
- **前置依赖**: B1
- **状态**: ✅ 已完成
- **动作**:
  - 不修改现有 `analyze_peak()` 语义
  - 新增专门的 `analyze_peak_ensemble()`，内部基于 `process_single_day_ensemble()`
  - 返回 summary + timeline 两层数据
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_lppl_engine_ensemble`
  - `.venv/bin/python -m compileall src lppl_verify_v2.py tests/unit/test_lppl_engine_ensemble.py`
- **验收标准**:
  - `--ensemble` 模式不再走 `scan_single_date()` 单窗口最优路径

#### 任务 B3: 将 `--ensemble` 真正接入新路径

- **任务ID**: B3
- **优先级**: P0
- **涉及文件**: `lppl_verify_v2.py`
- **前置依赖**: B2
- **状态**: ✅ 已完成
- **动作**:
  - `args.ensemble` 时调用 `analyze_peak_ensemble()`
  - 非 ensemble 时继续调用 `analyze_peak()`
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_lppl_engine_ensemble`
  - `.venv/bin/python -m compileall lppl_verify_v2.py src tests/unit/test_lppl_engine_ensemble.py`
- **验收标准**:
  - Ensemble 输出包含 `consensus_rate`, `valid_windows`, `predicted_crash_days`, `tc_std`, `signal_strength`

#### 任务 B4: 消除验证逻辑中的硬编码阈值

- **任务ID**: B4
- **优先级**: P0
- **涉及文件**: `src/lppl_engine.py`
- **前置依赖**: B2
- **状态**: ✅ 已完成
- **动作**:
  - `calculate_trend_scores()` 中的 danger/warning 判定改为使用 `config`
  - `process_single_day_ensemble()` 的 `min_r2` / `consensus_threshold` 与配置统一
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_lppl_engine_ensemble`
  - `.venv/bin/python -m compileall src tests/unit/test_lppl_engine_ensemble.py`
- **验收标准**:
  - 所有 danger / warning / consensus 判定均可通过配置追踪

### Phase C: P1 原始结果输出标准化

#### 任务 C1: 设计验证结果数据模型

- **任务ID**: C1
- **优先级**: P1
- **涉及文件**: `src/lppl_engine.py`, `lppl_verify_v2.py`
- **状态**: ✅ 已完成
- **动作**:
  - 统一 `summary` 结构
  - 统一 `timeline` 结构
  - 规定字段命名，避免脚本内动态拼字段
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_lppl_engine_ensemble tests.unit.test_lppl_verify_outputs`
  - `.venv/bin/python -m compileall src lppl_verify_v2.py tests/unit/test_lppl_engine_ensemble.py tests/unit/test_lppl_verify_outputs.py`
- **验收标准**:
  - single-window 与 ensemble 可共享下游报告和绘图模块

#### 任务 C2: 保存每个 peak 的 timeline 明细

- **任务ID**: C2
- **优先级**: P1
- **涉及文件**: `lppl_verify_v2.py`
- **前置依赖**: C1
- **状态**: ✅ 已完成
- **动作**:
  - 每个 peak 保存 `raw_<symbol>_<mode>_<peak_date>.parquet`
  - 汇总保存 `summary_<mode>.csv`
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_lppl_verify_outputs`
  - `.venv/bin/python -m compileall lppl_verify_v2.py tests/unit/test_lppl_verify_outputs.py`
- **验收标准**:
  - 绘图模块不需要重新计算即可生成图片

#### 任务 C3: 标准化输出目录结构

- **任务ID**: C3
- **优先级**: P1
- **涉及文件**: `lppl_verify_v2.py`, `src/constants.py`
- **前置依赖**: C2
- **状态**: ✅ 已完成
- **动作**:
  - 使用如下目录:
    - `output/MA/raw/`
    - `output/MA/plots/`
    - `output/MA/reports/`
    - `output/MA/summary/`
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_constants_config tests.unit.test_lppl_verify_outputs`
  - `.venv/bin/python -m compileall src lppl_verify_v2.py tests/unit/test_constants_config.py tests/unit/test_lppl_verify_outputs.py`
- **验收标准**:
  - 原始数据、图片、报告、汇总表分目录存放

### Phase D: P1 图片输出与清晰展示

#### 任务 D1: 新增绘图模块

- **任务ID**: D1
- **优先级**: P1
- **涉及文件**: `src/reporting/plot_generator.py` (新建)
- **状态**: ✅ 已完成
- **动作**:
  - 创建统一绘图入口类或函数
  - 接收 timeline / summary 数据，输出 PNG
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_plot_generator`
  - `.venv/bin/python -m compileall src/reporting tests/unit/test_plot_generator.py`
- **验收标准**:
  - 绘图逻辑不散落在验证脚本中

#### 任务 D2: 生成单案例价格时间线图

- **任务ID**: D2
- **优先级**: P1
- **涉及文件**: `src/reporting/plot_generator.py`
- **前置依赖**: D1, C2
- **状态**: ✅ 已完成
- **动作**:
  - 绘制价格曲线
  - 标记 peak date
  - 标记 warning / danger 点
  - 标记首次 danger 时间
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_plot_generator`
- **验收标准**:
  - 单张图可以清楚看出价格、高点、信号出现位置

#### 任务 D3: 生成 Ensemble 共识度图

- **任务ID**: D3
- **优先级**: P1
- **涉及文件**: `src/reporting/plot_generator.py`
- **前置依赖**: D1, B3, C2
- **状态**: ✅ 已完成
- **动作**:
  - 绘制 `consensus_rate`
  - 绘制阈值线 `consensus_threshold`
  - 标注首次越线位置
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_plot_generator`
- **验收标准**:
  - 能直观看出是否形成多窗口共识

#### 任务 D4: 生成预测崩盘时间离散图

- **任务ID**: D4
- **优先级**: P1
- **涉及文件**: `src/reporting/plot_generator.py`
- **前置依赖**: D1, B3, C2
- **状态**: ✅ 已完成
- **动作**:
  - 对 `predicted_crash_days` / `tc_std` 做分布展示
  - 支持箱线图或带状图
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_plot_generator`
- **验收标准**:
  - 能直观看出预测时间是否收敛

#### 任务 D5: 生成汇总统计图

- **任务ID**: D5
- **优先级**: P1
- **涉及文件**: `src/reporting/plot_generator.py`
- **前置依赖**: C2, D1
- **状态**: ✅ 已完成
- **动作**:
  - 检测率柱状图
  - 提前天数箱线图
  - 各指数热力图或散点汇总图
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_plot_generator`
  - `.venv/bin/python -m compileall src/reporting tests/unit/test_plot_generator.py`
- **验收标准**:
  - 一张总图能对不同指数和不同模式进行横向对比

### Phase E: P1 报告层集成

#### 任务 E1: 新增验证报告生成器

- **任务ID**: E1
- **优先级**: P1
- **涉及文件**: `src/reporting/verification_report.py` (新建)
- **状态**: ✅ 已完成
- **动作**:
  - 读取 summary + plots
  - 生成验证专用 Markdown 报告
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_verification_report`
  - `.venv/bin/python -m compileall src/reporting tests/unit/test_verification_report.py`
- **验收标准**:
  - 验证报告与主扫描报告分离

#### 任务 E2: 生成验证 HTML 报告

- **任务ID**: E2
- **优先级**: P1
- **涉及文件**: `src/reporting/verification_report.py`, `src/reporting/html_generator.py`
- **前置依赖**: E1, D2, D3, D5
- **状态**: ✅ 已完成
- **动作**:
  - 为每个 peak 展示缩略图和统计卡片
  - 增加模式标签和关键指标区域
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_verification_report`
  - `.venv/bin/python -m compileall src/reporting tests/unit/test_verification_report.py`
- **验收标准**:
  - HTML 中可直接查看图片，不必手工打开目录

#### 任务 E3: 将报告生成接入 `lppl_verify_v2.py`

- **任务ID**: E3
- **优先级**: P1
- **涉及文件**: `lppl_verify_v2.py`
- **前置依赖**: E1, E2
- **状态**: ✅ 已完成
- **动作**:
  - 在验证运行结束后自动生成 MD / HTML / CSV / PNG
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_lppl_verify_outputs tests.unit.test_verification_report tests.unit.test_plot_generator`
  - `.venv/bin/python -m compileall lppl_verify_v2.py src/reporting tests/unit/test_lppl_verify_outputs.py tests/unit/test_verification_report.py tests/unit/test_plot_generator.py`
- **验收标准**:
  - 单次命令可产出完整验证工件

### Phase F: P2 盲测与回归基线

#### 任务 F1: 固化代表性历史基线样本

- **任务ID**: F1
- **优先级**: P2
- **涉及文件**: `tests/fixtures/` (新建), `output/MA/summary/`
- **状态**: ✅ 已完成
- **动作**:
  - 固化 `000001.SH`, `000300.SH`, `399006.SZ` 的代表周期
  - 记录检测率、首次 danger、提前天数、R²、共识度
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_verification_baselines`
  - `.venv/bin/python -m compileall tests/unit/test_verification_baselines.py`
- **验收标准**:
  - 后续算法改动可做回归对比

#### 任务 F2: 新增 walk-forward 盲测脚本

- **任务ID**: F2
- **优先级**: P2
- **涉及文件**: `lppl_walk_forward.py` (新建) 或 `src/verification/walk_forward.py` (新建)
- **状态**: ✅ 已完成
- **动作**:
  - 逐日滚动，只使用当日之前数据
  - 输出 precision / recall / false positive rate / signal density
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_walk_forward`
  - `.venv/bin/python -m compileall src/verification lppl_walk_forward.py tests/unit/test_walk_forward.py`
  - `.venv/bin/python lppl_walk_forward.py --help`
- **验收标准**:
  - 不再只依赖已知高点回看验证

### Phase G: P2 测试与质量门禁

#### 任务 G1: 新增单元测试

- **任务ID**: G1
- **优先级**: P2
- **涉及文件**: `tests/unit/`
- **状态**: ✅ 已完成
- **动作**:
  - 覆盖 `find_local_highs()`, `scan_single_date()`, `process_single_day_ensemble()`
  - 覆盖绘图函数的最小输出检查
- **验证**:
  - `.venv/bin/python -m unittest tests.unit.test_lppl_engine_ensemble -v`
  - `.venv/bin/python -m unittest discover tests/unit -v`
  - `.venv/bin/python -m compileall tests/unit`
- **验收标准**:
  - 核心函数具备稳定单测

#### 任务 G2: 新增集成测试

- **任务ID**: G2
- **优先级**: P2
- **涉及文件**: `tests/integration/`
- **状态**: ✅ 已完成
- **动作**:
  - 跑一个单指数 + 单 peak 的完整链路
  - 校验 CSV / PNG / MD / HTML 是否都被生成
- **验证**:
  - `.venv/bin/python -m unittest discover tests/integration -v`
  - `.venv/bin/python -m compileall tests/integration`
- **备注**:
  - 集成测试已收敛为稳定的最小链路，避免真实重计算导致超时
  - `run_verification()` 路径与工件生成路径分层验证，覆盖单窗口与 Ensemble 两种模式
- **验收标准**:
  - 验证体系具备最小端到端覆盖

#### 任务 G3: 建立验证命令清单

- **任务ID**: G3
- **优先级**: P2
- **涉及文件**: `README.md` 或后续文档
- **状态**: ✅ 已完成
- **动作**:
  - 列出 compile / lint / test / smoke run 命令
  - 形成最小 verification-loop
- **验证**:
  - `.venv/bin/ruff check src tests main.py lppl_verify_v2.py lppl_walk_forward.py`
  - 按 README 中 verification loop 顺序执行 compile / lint / unit / integration / smoke
- **验收标准**:
  - 每次重要变更后可重复执行质量门禁

### Phase H: 建议执行顺序

1. A1 → A2 → A3 → A4
2. B1 → B2 → B3 → B4
3. C1 → C2 → C3
4. D1 → D2 → D3 → D4 → D5
5. E1 → E2 → E3
6. F1 → F2
7. G1 → G2 → G3

### Phase I: 最小可交付版本（MVP）

- [x] A1 统一 DataManager 状态
- [x] A3 删除不可达重复代码
- [x] B2 新增 `analyze_peak_ensemble()`
- [x] B3 接入 `--ensemble`
- [x] C2 保存原始 timeline parquet
- [x] D2 单案例价格时间线图
- [x] D3 Ensemble 共识度图
- [x] D5 汇总检测率图
- [x] E3 自动生成 MD / HTML / CSV / PNG

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|-----|------|-----|
| v1.0.0 | 2026-03-08 | 初始版本 |
| v1.1.0 | 2026-03-08 | 优化计划 |
| v1.1.1 | 2026-03-24 | 修复风险阈值对齐问题 |
| v1.2.0 | 2026-03-24 | 数据源迁移到通达信本地 |
| v1.3.0 | 2026-03-29 | 验证体系整改与可视化增强 |
| v1.3.1 | 2026-03-29 | 收敛 G2 集成测试并校正任务状态 |

---

## 九、运行指南

### 环境准备

```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
pip install 'mootdx[all]'
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

## 十、成功标准达成情况

- [x] Numba JIT 加速后 `lppl_func` 执行时间减少 > 50%
- [x] 风险阈值调整后，days_left < 5 正确标记为 DANGER
- [x] joblib 并发执行无错误，性能不低于 ProcessPoolExecutor
- [x] TDXReader 成功读取7个本地指数
- [x] DataManager 正确路由数据源（TDX / akshare / parquet）
- [x] 负向泡沫检测功能正常
- [x] 功能开关全部定义并可配置
- [ ] main.py 完整流程测试通过
- [ ] **项目与计划对齐度: 100%**

### v1.3 新增成功标准

- [x] `--ensemble` 模式真正走 Ensemble 分析链路
- [x] 每个 peak 至少生成 2 张图片
- [x] 自动输出 `raw/`, `plots/`, `reports/`, `summary/` 四类工件
- [x] Markdown / HTML 报告可嵌入图片并正常引用
- [x] 固化至少 3 组历史回归基线
- [x] 提供 walk-forward 盲测结果统计

### 当前未完全闭环事项

- [ ] 主流程运行时仍存在 Matplotlib 中文字体缺失告警
- [ ] 汇总图仍存在 Matplotlib `boxplot(labels=...)` 弃用告警
