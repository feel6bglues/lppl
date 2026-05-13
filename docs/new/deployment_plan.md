# LPPL/Wyckoff 量化交易系统 — 工程化落地实施方案

> 版本: v1.0  
> 日期: 2026-05-13  
> 状态: 规划阶段  
> 前置: 三策略组合已验证（夏普1.116, 蒙特卡洛100%正向）

---

## 一、系统架构总览

```
                        通达信 .day 文件
                              │
                    ┌─────────┴──────────┐
                    │  增量数据加载模块    │
                    │  (IncrementalLoader)│
                    └─────────┬──────────┘
                              │
                    ┌─────────┴──────────┐
                    │  数据校验 & 清洗     │
                    │  ─ 日期连续性        │
                    │  ─ 价格非负           │
                    │  ─ 复权一致性         │
                    └─────────┬──────────┘
                              │
                    ┌─────────┴──────────┐
                    │  信号生成引擎        │
                    │  ─ Wyckoff v2+P3    │
                    │  ─ MA5/20 金叉      │
                    │  ─ 短期反转         │
                    └─────────┬──────────┘
                              │ 买卖清单
                    ┌─────────┴──────────┐
                    │  组合管理器          │
                    │  ─ 资金分配          │
                    │  ─ 约束检查          │
                    │  ─ 冲突解决          │
                    └─────────┬──────────┘
                              │ 订单列表
              ┌───────────────┼───────────────┐
              │               │               │
     ┌────────┴───┐   ┌──────┴─────┐   ┌────┴────┐
     │  风控模块   │   │ 交易执行   │   │ 状态持久 │
     │  ─ VaR     │   │ ─ QMT     │   │ ─ SQLite │
     │  ─ 回撤    │   │ ─ PTrade  │   │ ─ 4张表  │
     │  ─ 集中度  │   │ ─ 模拟    │   │          │
     └────────────┘   └────────────┘   └─────────┘
                              │
                    ┌─────────┴──────────┐
                    │  调度 & 通知 & 报告  │
                    │  ─ cron / Airflow   │
                    │  ─ 钉钉/微信推送     │
                    │  ─ 每日报告         │
                    └────────────────────┘
```

---

## 二、Phase 1：最小可行产品（MVP）

**目标**: 每日收盘后自动运行，输出信号清单。不需要券商接口，不做组合管理。

**时间**: 2周  
**产出**: 每日运行的信号生成脚本 + SQLite数据库 + 模拟交易记录

---

### 模块 1.1：增量数据加载

**文件**: `src/data/incremental_loader.py`

**核心功能**:

```python
class IncrementalLoader:
    """
    增量加载通达信日线数据
    
    职责:
    1. 扫描 TDX .day 文件目录, 发现新数据
    2. 只加载有更新的文件
    3. 维护数据状态追踪表
    """
    
    def __init__(self, db_path: str = "data/lday_data.db"):
        self.db_path = db_path
    
    def get_data_status(self) -> pd.DataFrame:
        """从SQLite读取每只股票的最后处理日期"""
        
    def scan_tdx_files(self, tdx_dir: str) -> List[Dict]:
        """扫描TDX目录, 发现所有.lday文件的修改时间"""
        
    def load_incremental(self, symbol: str, last_date: str) -> pd.DataFrame:
        """增量加载: 只读取last_date之后的数据"""
        
    def run_daily_update(self) -> Dict:
        """
        每日更新入口:
        1. scan_tdx_files() → 发现有更新的文件
        2. 对每个有更新的文件: load_incremental() 
        3. 更新data_status表
        4. 返回更新结果统计
        """
```

**数据状态表 (SQLite)**:

```sql
CREATE TABLE data_status (
    symbol TEXT PRIMARY KEY,
    code TEXT,
    market TEXT,
    name TEXT,
    last_date DATE,           -- 本地数据最后日期
    file_mtime TIMESTAMP,      -- .lday文件最后修改时间
    row_count INT,
    data_quality TEXT,         -- ok / warning / error
    last_checked TIMESTAMP
);
```

**TDX .day 文件扫描**:

```python
TDX_PATHS = {
    "sh": "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/",
    "sz": "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/",
}
# .day 文件名规则: sh600519.day, sz000001.day
# .lday 是复权后的文件, 命名相同
```

**运行时间目标**: 5,199只股票增量加载 → < 10分钟

---

### 模块 1.2：信号生成引擎

**文件**: `src/engine/daily_signal_engine.py`

**核心功能**:

```python
class DailySignalEngine:
    """
    每日信号生成引擎
    
    输入: 增量数据 + SQLite历史状态
    输出: 买卖清单 (DataFrame)
    """
    
    def __init__(self):
        self.wyckoff = WyckoffEngine(lookback_days=400, ...)
        
    def run_wyckoff(self, symbol: str, df: pd.DataFrame, regime: str) -> Optional[Dict]:
        """Wyckoff v2+P3 单日信号"""
        # 需要: 最近400天数据
        # 输出: (action, entry_price, stop_loss, first_target, confidence)
        
    def run_ma_cross(self, symbol: str, df: pd.DataFrame) -> Optional[Dict]:
        """MA5/20 金叉信号"""
        # 需要: 最近30天数据
        # 输出: (action, entry_price) 
        
    def run_reversal(self, symbol: str, df: pd.DataFrame) -> Optional[Dict]:
        """短期反转信号"""
        # 需要: 最近10天数据  
        # 输出: (action, entry_price, stop_loss, take_profit)
    
    def generate_daily_signals(self, date: str) -> pd.DataFrame:
        """
        每日信号生成主流程:
        1. 从SQLite读取已有数据
        2. 运行三策略
        3. 合并信号
        4. 写入SQLite
        5. 返回信号清单
        """
```

**信号表 (SQLite)**:

```sql
CREATE TABLE daily_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date DATE,
    symbol TEXT,
    strategy TEXT,           -- wyckoff / ma_cross / str_reversal
    action TEXT,             -- buy / sell / hold
    entry_price REAL,
    stop_loss REAL,
    take_profit REAL,
    confidence TEXT,         -- A/B/C/D (仅Wyckoff)
    regime TEXT,             -- bull/bear/range
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, symbol, strategy)
);
```

**运行时间目标**: 5,199只 × 3策略 → < 15分钟

---

### 模块 1.3：SQLite 状态库

**文件**: `src/storage/database.py`

**数据库结构**:

```sql
-- 1. 数据状态表
CREATE TABLE data_status (
    symbol TEXT PRIMARY KEY, code TEXT, market TEXT, name TEXT,
    last_date DATE, file_mtime TIMESTAMP, row_count INT,
    data_quality TEXT, last_checked TIMESTAMP
);

-- 2. 信号表
CREATE TABLE daily_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date DATE, symbol TEXT, strategy TEXT,
    action TEXT, entry_price REAL, stop_loss REAL,
    take_profit REAL, confidence TEXT, regime TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, symbol, strategy)
);

-- 3. 持仓表
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_date DATE NOT NULL,
    entry_price REAL NOT NULL,
    quantity INT NOT NULL,
    current_price REAL,
    strategy TEXT,              -- 入场策略
    stop_loss REAL,
    take_profit REAL,
    status TEXT DEFAULT 'open', -- open / closed
    exited_date DATE,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, entry_date)
);

-- 4. 交易记录表
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, entry_date DATE, exit_date DATE,
    direction TEXT, quantity INT,
    entry_price REAL, exit_price REAL,
    pnl REAL, pnl_pct REAL,
    strategy TEXT, exit_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. 组合净值表
CREATE TABLE portfolio_snapshots (
    date DATE PRIMARY KEY,
    cash REAL, market_value REAL,
    total_value REAL, daily_pnl REAL,
    total_pnl REAL, total_pnl_pct REAL,
    n_positions INT, n_signals INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_signals_date ON daily_signals(signal_date);
CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_trades_entry ON trades(entry_date);
```

---

### 模块 1.4：模拟交易执行

**文件**: `src/execution/simulator.py`

```python
class SimulatedBroker:
    """
    模拟交易执行器
    
    功能:
    1. 接收订单 → 检查是否可成交
    2. 基于真实日线数据模拟成交
    3. 记录成交结果
    """
    
    def place_order(self, symbol: str, direction: str, 
                    quantity: int, price: float) -> Dict:
        """
        模拟下单:
        - 检查当日是否有足够流动性(成交量>0)
        - 使用次日真实开盘价/收盘价作为成交价
        - 记录成交
        """
        
    def get_positions(self) -> List[Dict]:
        """获取当前持仓"""
        
    def get_account(self) -> Dict:
        """获取账户信息(现金/市值/总资产)"""
```

---

## 三、Phase 2：实盘准备

**目标**: 对接券商接口, 实现实盘交易能力

**时间**: +2周

---

### 模块 2.1：组合管理器

**文件**: `src/portfolio/manager.py`

```python
class PortfolioManager:
    """
    组合管理:
    - 资金分配: 等权 / 波动率加权 / 凯利
    - 约束检查: 集中度/行业/杠杆
    - 冲突解决: 多策略信号合并
    """
    
    ALLOCATION_MODES = ["equal_weight", "volatility_weighted", "kelly"]
    MAX_POSITIONS = 30
    MAX_SINGLE_STOCK = 0.05   # 单股 ≤ 5%
    MAX_SINGLE_SECTOR = 0.20  # 单行业 ≤ 20%
    MAX_LEVERAGE = 1.0        # 无杠杆
    MAX_CORRELATION = 0.6     # 与300相关度
    
    def allocate(self, signals: pd.DataFrame, 
                 capital: float) -> pd.DataFrame:
        """
        1. 按策略类型分组
        2. 每组内等权分配资金
        3. 检查约束
        4. 返回带仓位的订单列表
        """
```

---

### 模块 2.2：风控模块

**文件**: `src/risk/controller.py`

```python
class RiskController:
    """
    多层级风险控制
    """
    
    # 事前风控 (订单执行前)
    def pre_trade_check(self, order: Dict, 
                        portfolio: Dict) -> Tuple[bool, str]:
        """检查: 资金够? 集中度? 连续亏损?"""
    
    # 事后风控 (持仓监控)
    def post_trade_check(self, positions: List[Dict]) -> List[Dict]:
        """检查止损触发, 返回需平仓的持仓"""
    
    # 组合级风控
    def portfolio_risk_check(self, portfolio: Dict) -> Dict:
        """VaR / 回撤 / 相关度检查"""
```

**风控参数**:

```yaml
risk_params:
  max_drawdown_pct: 15        # 最大回撤15% → 减半仓位
  max_drawdown_stop: 25       # 最大回撤25% → 全部平仓
  consecutive_losses: 5       # 连续亏损5笔 → 暂停策略
  var_confidence: 0.95        # VaR 95% 置信度
  max_daily_var_pct: 2.0      # 单日VaR < 2%
  position_stop_loss: 0.07    # 单笔止损7%
  trailing_stop_atr: 2.0      # 移动止损ATR倍数
```

---

### 模块 2.3：交易执行接口

**文件**: `src/execution/broker_base.py`, `src/execution/broker_qmt.py`

```python
from abc import ABC, abstractmethod

class BrokerAPI(ABC):
    """券商API抽象层"""
    
    @abstractmethod
    def place_order(self, symbol: str, direction: str,
                    order_type: str, price: float, 
                    quantity: int) -> str:
        """下单 → 返回订单ID"""
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> str:
        """查询订单状态"""
    
    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """查询持仓"""
    
    @abstractmethod
    def get_account(self) -> Dict:
        """查询账户"""
```

```python
class QMTBroker(BrokerAPI):
    """QMT (迅投) 实现"""
    
    def __init__(self):
        from xtquant import xtdata, xttrader
        # QMT 初始化代码
        
    def place_order(self, ...):
        # QMT 下单接口
```

```python
class SimBroker(BrokerAPI):
    """模拟实现 (用于Phase 1测试)"""
    # 使用历史数据模拟成交
```

---

### 模块 2.4：调度与通知

**文件**: `src/scheduler/daily_run.py`

```python
def daily_pipeline(run_date: str = None):
    """
    每日收盘后运行流程:
    
    1. [15:00] TDX数据更新完成
    2. [15:05] IncrementalLoader.run_daily_update()
    3. [15:15] DailySignalEngine.generate_daily_signals()
    4. [15:30] PortfolioManager.allocate()
    5. [15:32] RiskController.pre_trade_check()
    6. [15:35] BrokerAPI.place_order()   (Phase 2)
    7. [15:40] 生成每日报告 + 推送通知
    """
```

**通知格式 (钉钉/微信)**:

```markdown
## 📊 交易日报 2026-05-13

### 今日信号
- 买入: 5只 (Wyckoff: 2, MA: 2, 反转: 1)
- 卖出: 3只 (止损: 1, 止盈: 2)

### 持仓
- 总持仓: 12只
- 总仓位: 35.2%
- 今日盈亏: +0.82%

### 风险
- VaR(95%): 1.23%
- 最大回撤: -3.45%
- 集中度: 最高行业银行18%
```

---

## 四、Phase 3：运维稳定

| 模块 | 说明 | 优先级 |
|------|------|--------|
| Web Dashboard | Flask/Gradio 实时监控 | 低 |
| 自动调度 | cron / Airflow DAG | 中 |
| 日志审计 | 所有操作可追溯 | 中 |
| 策略迭代 | 根据实盘数据微调参数 | 持续 |

---

## 五、项目文件结构

```
lppl/
├── src/
│   ├── data/
│   │   ├── incremental_loader.py   # [Phase 1] 增量数据加载
│   │   ├── tdx_loader.py           # 已有
│   │   └── manager.py               # 已有
│   ├── engine/
│   │   └── daily_signal_engine.py   # [Phase 1] 信号生成引擎
│   ├── wyckoff/
│   │   ├── engine.py               # 已有
│   │   ├── models.py               # 已有
│   │   ├── rules.py                # 已有
│   │   └── trading.py              # 已有
│   ├── storage/
│   │   └── database.py             # [Phase 1] SQLite管理
│   ├── portfolio/
│   │   └── manager.py              # [Phase 2] 组合管理
│   ├── risk/
│   │   └── controller.py           # [Phase 2] 风控
│   ├── execution/
│   │   ├── broker_base.py          # [Phase 2] API抽象
│   │   ├── broker_qmt.py           # [Phase 2] QMT实现
│   │   └── simulator.py            # [Phase 1] 模拟执行
│   └── scheduler/
│       └── daily_run.py            # [Phase 2] 每日调度
├── scripts/
│   ├── run_daily.py                # [Phase 1] 每日运行入口
│   └── (已有回测脚本保留)
├── docs/
│   └── new/
│       └── deployment_plan.md      # 本文档
├── data/
│   └── trading.db                  # [Phase 1] SQLite数据库
└── config/
    └── trading.yaml                # [Phase 1] 策略配置
```

---

## 六、文件创建清单与时间估算

### Phase 1 (2周)

| 文件 | 预计工时 | 说明 |
|------|---------|------|
| `src/data/incremental_loader.py` | 2天 | TDX文件扫描 + 增量读取 + 状态管理 |
| `src/storage/database.py` | 1天 | SQLite建表 + CRUD操作 |
| `src/engine/daily_signal_engine.py` | 3天 | 三策略封装 + 信号合并 + 日记化 |
| `src/execution/simulator.py` | 1天 | 模拟撮合 + 持仓追踪 |
| `scripts/run_daily.py` | 1天 | 每日运行入口脚本 |
| `config/trading.yaml` | 0.5天 | 策略/风控/资金参数配置 |
| 集成测试 | 2天 | 端到端验证 |
| **Total** | **~10.5天** | |

### Phase 2 (+2周)

| 文件 | 预计工时 | 说明 |
|------|---------|------|
| `src/portfolio/manager.py` | 2天 | 资金分配 + 约束 + 冲突 |
| `src/risk/controller.py` | 2天 | 事前/事后/组合级风控 |
| `src/execution/broker_base.py` | 0.5天 | 抽象接口 |
| `src/execution/broker_qmt.py` | 2天 | QMT对接 |
| `src/scheduler/daily_run.py` | 1天 | 流水线编排 |
| 通知集成(钉钉/微信) | 0.5天 | 消息推送 |
| **Total** | **~8天** | |

---

## 七、里程碑

```
M0: 当前状态
  - 三策略回测通过, 夏普1.116 ✅
  - TDX数据每日更新 ✅
  - 无工程化代码 ❌

M1: Phase 1 完成 (2周后)
  - 每日信号自动生成
  - SQLite记录所有信号和模拟交易
  - 可通过 run_daily.py 一键运行

M2: Phase 2 完成 (4周后)
  - 对接QMT/PTrade
  - 组合管理和风控
  - 每日自动运行 + 推送通知

M3: 稳定运行 (6周+)
  - Web Dashboard
  - 日志审计
  - 策略迭代反馈
```

---

## 八、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| TDX数据延迟或缺失 | 中 | 信号无法生成 | 备用数据源(akshare/东方财富) |
| QMT接口变更 | 低 | 交易执行中断 | BrokerAPI抽象层隔离变更 |
| 回测夏普与实盘差距大 | 高 | 策略不盈利 | 小资金先跑, 观察到偏差后调整 |
| 策略在极端行情失效 | 中 | 大幅回撤 | 风控模块自动暂停机制 |
| SQLite性能瓶颈 | 低 | 查询变慢 | 5000只×每日信号, SQLite足够 |
| 实盘滑点超出预期 | 中 | 收益降低 | 信号中预留滑点缓冲(0.1%-0.3%) |

---

## 九、附录

### A. 配置模板 (config/trading.yaml)

```yaml
data:
  tdx_paths:
    sh: "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/"
    sz: "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/"
  db_path: "data/trading.db"

strategies:
  wyckoff:
    enabled: true
    lookback_days: 400
    weight: 0.34
  
  ma_cross:
    enabled: true
    fast_period: 5
    slow_period: 20
    weight: 0.33
  
  reversal:
    enabled: true
    lookback_days: 5
    threshold_pct: 5.0
    hold_days: 5
    take_profit_pct: 4.0
    stop_loss_pct: 4.0
    weight: 0.33

risk:
  max_positions: 30
  max_single_stock_pct: 5.0
  max_single_sector_pct: 20.0
  max_drawdown_pct: 15.0
  max_drawdown_stop_pct: 25.0
  consecutive_losses: 5
  var_confidence: 0.95
  max_daily_var_pct: 2.0

execution:
  broker: "simulator"  # simulator / qmt
  order_timeout_minutes: 30
  slippage_pct: 0.1
```

### B. 每日运行命令

```bash
# 全量运行 (首次)
python scripts/run_daily.py --full

# 增量运行 (每日更新后)
python scripts/run_daily.py --date 2026-05-13

# 查看持仓
python scripts/run_daily.py --positions

# 查看今日信号
python scripts/run_daily.py --signals
```

---

> 本方案按 Phase 1 → Phase 2 → Phase 3 分阶段实施。数据已就绪，策略已验证。从 Phase 1 开始，2周内可产出一个每日自动运行的信号系统。
