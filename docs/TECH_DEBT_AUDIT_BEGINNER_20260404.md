# LPPL 项目历史债务审计与新手处理指南

**文档日期**: 2026-04-04  
**适用对象**: 第一次接手本项目的开发者  
**目标**: 让新手能看懂项目现在“哪里还能跑、哪里容易踩坑、下一步应该先修什么”

---

## 1. 先说结论

这个项目**不是不可维护**，但它有比较明显的**历史债务**。

当前状态可以概括成一句话：

> 核心功能已经逐步稳定，但规则说明、配置来源、遗留模块和文档收口还没有完全跟上。

这意味着：

- 你现在可以继续开发，不需要推倒重来。
- 但如果不先处理关键债务，后面每次改规则、加功能、调参数，都会更容易改错地方。

---

## 2. 什么是“历史债务”

在这个项目里，“历史债务”不是单纯指 bug，而是指这些问题：

1. **同一件事有多套写法**
   - 代码一套
   - 文档一套
   - 配置一套
   - 输出报告里又一套

2. **旧实现没有彻底下线**
   - 新模块已经可用
   - 旧模块还留着
   - 维护者很难判断到底该改哪份

3. **项目长期靠“补丁式前进”**
   - 问题发现后会新增计划文档、实验脚本、报告文件
   - 但不一定把旧说明和旧逻辑一起收口

---

## 3. 当前最重要的债务类型

下面按影响从高到低说明。

### 3.1 规则口径债务

这是当前最重要的一类。

项目最近已经把核心风险阈值逐步收敛到：

- `< 5`：极高危
- `< 12`：高危
- `< 25`：观察

但仓库里仍有很多地方保留旧口径：

- [`README.md`](/home/james/Documents/Project/lppl/README.md)
- [`docs/使用文档.md`](/home/james/Documents/Project/lppl/docs/使用文档.md)
- [`src/cli/lppl_verify_v2.py`](/home/james/Documents/Project/lppl/src/cli/lppl_verify_v2.py)
- [`src/reporting/html_generator.py`](/home/james/Documents/Project/lppl/src/reporting/html_generator.py)
- [`config/optimal_params.yaml`](/home/james/Documents/Project/lppl/config/optimal_params.yaml)

**为什么危险**：

- 新手会以为文档和代码一致，实际上不一致。
- 你改了核心逻辑，不代表生成的报告文字是对的。
- 你看 YAML 以为是当前规则，实际上可能是旧实验口径。

**简单理解**：

系统里已经不只存在“代码 bug”，而是存在“事实源分裂”。

---

### 3.2 模块重复债务

LPPL 相关逻辑现在分散在多个文件中：

- [`src/lppl_engine.py`](/home/james/Documents/Project/lppl/src/lppl_engine.py)
- [`src/lppl_core.py`](/home/james/Documents/Project/lppl/src/lppl_core.py)
- [`src/lppl_fit.py`](/home/james/Documents/Project/lppl/src/lppl_fit.py)
- [`src/computation.py`](/home/james/Documents/Project/lppl/src/computation.py)

这些文件并不是完全重复，但它们都覆盖了 LPPL 计算链路的一部分。

**为什么危险**：

- 改风险阈值时，可能只改了 `lppl_engine.py`，没改 `lppl_core.py`
- 改拟合边界时，可能还有旧模块继续使用旧参数
- 新手不知道“真正主实现”是哪一个

**当前建议**：

- 把 `src/lppl_engine.py` 视为主引擎
- 其余文件先视为“兼容层 / 历史层 / 待收口层”
- 在没有明确清理计划前，不要同时在多个 LPPL 文件里做同类改动

---

### 3.3 参数来源债务

项目里现在同时存在两套甚至三套参数来源：

1. 代码内默认值  
   见 [`src/investment/backtest.py`](/home/james/Documents/Project/lppl/src/investment/backtest.py) 中 `InvestmentSignalConfig`

2. 按指数/分组内置默认值  
   同样在 `for_symbol()` 里

3. YAML 配置文件  
   见 [`config/optimal_params.yaml`](/home/james/Documents/Project/lppl/config/optimal_params.yaml)

**为什么危险**：

- 你以为改 YAML 就生效，但某些运行路径先吃代码默认值
- 你以为代码默认值是当前标准，但 YAML 又覆盖成另一套
- 同一个 symbol 在不同入口里可能看到不同的有效参数

**新手最容易犯的错**：

直接改一个地方，然后以为“全项目都改好了”。

实际上，这个项目里参数变更必须至少检查：

- 默认 dataclass
- `for_symbol()`
- YAML defaults
- YAML symbol overrides
- CLI 实际读取逻辑

---

### 3.4 超大文件债务

当前几个核心文件已经很大：

- [`src/investment/backtest.py`](/home/james/Documents/Project/lppl/src/investment/backtest.py): 1444 行
- [`tests/unit/test_investment_backtest.py`](/home/james/Documents/Project/lppl/tests/unit/test_investment_backtest.py): 1418 行
- [`src/lppl_engine.py`](/home/james/Documents/Project/lppl/src/lppl_engine.py): 897 行
- [`src/cli/lppl_verify_v2.py`](/home/james/Documents/Project/lppl/src/cli/lppl_verify_v2.py): 649 行

**为什么危险**：

- 文件太大时，行为耦合增加
- 一次小修改容易波及多个逻辑块
- 审查和定位回归会变慢

**这不是马上要炸的 bug**，但它会持续提高维护成本。

---

### 3.5 入口脚本迁移未收口债务

项目根目录保留了很多入口壳文件：

- [`lppl_verify_v2.py`](/home/james/Documents/Project/lppl/lppl_verify_v2.py)
- [`index_investment_analysis.py`](/home/james/Documents/Project/lppl/index_investment_analysis.py)
- [`generate_optimal8_report.py`](/home/james/Documents/Project/lppl/generate_optimal8_report.py)
- [`tune_signal_model.py`](/home/james/Documents/Project/lppl/tune_signal_model.py)
- [`lppl_walk_forward.py`](/home/james/Documents/Project/lppl/lppl_walk_forward.py)

它们多数只是转发到 `src/cli/*`。

**为什么危险**：

- 文档里可能教你跑根目录脚本
- 代码里真正实现却在 `src/cli`
- 测试有时会依赖包装层行为

**建议理解方式**：

这是项目从“脚本项目”向“模块化项目”迁移过程中留下的中间态。

---

### 3.6 文档堆积债务

根目录和 `docs/` 下现在有大量阶段性文件：

- 审查报告
- 修复计划
- 实验复盘
- 实施计划
- 优化报告

这些文件有价值，但也带来一个问题：

> 新人很难判断哪份文档是“历史记录”，哪份文档是“当前权威结论”。

这会造成两个后果：

- 误读旧方案
- 根据过期结论继续开发

---

### 3.7 测试与运行方式债务

当前测试是可用的，但工程组织还不够统一。

常见症状：

- 测试代码使用 `unittest`
- 实际最方便的运行方式是 `pytest -q`
- 文档仍大量写 `python -m unittest discover`
- 运行时有时需要显式加 `PYTHONPATH=.`

**为什么危险**：

- 新手容易“按文档操作失败”
- CI 和本地运行方式可能不一致
- 环境问题会被误认为业务问题

---

## 4. 历史债务的根源是什么

从仓库现状看，债务主要来自 4 个长期演化原因：

1. **项目迭代很快**
   - 先求结果，再逐步收口

2. **多轮实验推动代码变化**
   - 每轮实验都会新增脚本、参数、文档、结论

3. **主功能已经向前走，但外围没完全同步**
   - 核心逻辑修了
   - 文档、HTML、CLI 文案、YAML 还保留旧值

4. **模块迁移未彻底完成**
   - 新模块建立了
   - 旧模块没有完全下线

---

## 5. 新手应该怎么理解这些债务

不要把它理解成“项目质量差”。

更准确的理解是：

- 项目已经有比较强的功能雏形
- 也有越来越多的测试保护
- 但它还处于“高迭代收敛期”，没有完全进入“稳定维护期”

所以你接手时的正确策略不是“到处重构”，而是：

1. 先确认当前主路径
2. 再确认哪份配置真的生效
3. 最后才做结构清理

---

## 6. 推荐的处理顺序

下面是按我建议的优先级整理的处理路线。

### P0：先统一规则事实源

这是最值得先做的事。

**目标**：

让下面这些地方说的是同一套规则：

- 核心代码
- CLI 报告文案
- HTML 展示
- README
- 使用文档
- YAML 默认配置

**处理后你会得到什么**：

- 新人不再被文档误导
- 审计报告和系统输出更可信
- 后续修改不会老是“代码对了，说明错了”

**建议先改的文件**：

- [`README.md`](/home/james/Documents/Project/lppl/README.md)
- [`docs/使用文档.md`](/home/james/Documents/Project/lppl/docs/使用文档.md)
- [`src/cli/lppl_verify_v2.py`](/home/james/Documents/Project/lppl/src/cli/lppl_verify_v2.py)
- [`src/reporting/html_generator.py`](/home/james/Documents/Project/lppl/src/reporting/html_generator.py)
- [`config/optimal_params.yaml`](/home/james/Documents/Project/lppl/config/optimal_params.yaml)

---

### P1：明确主实现，收敛 LPPL 模块

**目标**：

明确哪些模块是主线，哪些模块只是遗留兼容。

**建议做法**：

1. 在文档中明确：
   - `src/lppl_engine.py` 是主引擎
   - `src/lppl_core.py` 是底层兼容/辅助层
   - `src/lppl_fit.py` 是历史实验模块或待废弃模块
   - `src/computation.py` 是老输出链路，需评估是否保留

2. 给遗留模块添加清晰注释：
   - “主路径使用/非主路径使用/待迁移/待废弃”

**收益**：

- 后续修 bug 时不会改错文件
- 减少规则再次分叉

---

### P1：收敛参数系统

**目标**：

确定“唯一默认参数源”。

**建议原则**：

- 如果项目未来以 YAML 驱动为主，就让 YAML 成为主事实源
- 代码默认值仅做兜底，不再承担完整业务参数定义

**不要继续放任的状态**：

- dataclass 一套默认值
- `for_symbol()` 一套分组值
- YAML defaults 一套
- symbol overrides 再来一套

---

### P2：拆分超大文件

**优先拆分对象**：

1. [`src/investment/backtest.py`](/home/james/Documents/Project/lppl/src/investment/backtest.py)
2. [`src/lppl_engine.py`](/home/james/Documents/Project/lppl/src/lppl_engine.py)

**建议拆分方向**：

- 指标计算
- 信号映射
- 状态机与仓位控制
- 回测执行
- 绩效统计

**注意**：

新手不要一上来做“大重构”。  
应先在测试保护下按功能切块。

---

### P2：统一测试和运行入口

**目标**：

让“如何运行项目”对新人只剩一种标准答案。

**建议方向**：

1. 统一主测试命令为：

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

2. 在文档里把 `unittest discover` 降级为兼容说明，不再作为主入口。

3. 后续考虑把根目录壳脚本收敛到正式 CLI 入口。

---

### P3：文档治理

**目标**：

让新手知道：

- 哪份文档是当前权威说明
- 哪份文档只是历史记录

**建议做法**：

1. 主文档只保留：
   - README
   - 使用文档
   - 当前审计/当前优化结论

2. 计划、复盘、阶段性报告移入 `docs/archive/` 或单独 `docs/audits/`

3. 每份文档开头标明：
   - 是否当前有效
   - 是否仅作历史记录

---

## 7. 新手实际操作建议

如果你刚接手项目，按下面顺序最安全。

### 第一步：先确认环境是否正常

执行：

```bash
PYTHONPATH=. .venv/bin/pytest -q
.venv/bin/ruff check src tests *.py
```

如果这两步不通过，不要先改业务逻辑。

---

### 第二步：先读这几份文件

建议阅读顺序：

1. [`README.md`](/home/james/Documents/Project/lppl/README.md)
2. [`docs/使用文档.md`](/home/james/Documents/Project/lppl/docs/使用文档.md)
3. [`e2e_optimization_report_20260404.md`](/home/james/Documents/Project/lppl/e2e_optimization_report_20260404.md)
4. [`src/lppl_engine.py`](/home/james/Documents/Project/lppl/src/lppl_engine.py)
5. [`src/investment/backtest.py`](/home/james/Documents/Project/lppl/src/investment/backtest.py)

---

### 第三步：不要直接改所有同类文件

例如你要改风险规则，不要同时去改：

- `README`
- `docs`
- `lppl_core`
- `lppl_engine`
- `html_generator`
- `cli 文案`

正确做法是：

1. 先找主实现
2. 改主实现
3. 跑测试
4. 再把文档和展示层补齐

---

### 第四步：每次改动后做最小回归

建议至少执行：

```bash
PYTHONPATH=. .venv/bin/pytest -q
.venv/bin/ruff check src tests *.py
```

如果涉及 CLI 或报告输出，再补：

```bash
PYTHONPATH=. .venv/bin/python lppl_verify_v2.py --symbol 000001.SH --max-peaks 1
```

---

## 8. 验收标准

后续如果要说“历史债务收敛了一大步”，至少应满足下面 5 条：

1. README、使用文档、CLI 报告、HTML 展示、YAML 使用同一套风险规则。
2. LPPL 主实现只有一个清晰主入口，不再存在多套并行逻辑来源。
3. 参数默认值有唯一事实源。
4. 主测试命令和文档说明一致。
5. 新人能在不翻历史审计文档的情况下完成基本开发与验证。

---

## 9. 一句话版本

如果你只记一件事，请记这个：

> 这个项目现在最大的问题不是“功能不能跑”，而是“很多地方都还能跑，但不是同一套事实”。  
> 新手接手时，最该先做的不是继续堆功能，而是先把规则、配置、文档和主实现收拢到同一个中心。

---

## 10. 本文档对应的建议优先级

| 优先级 | 事项 | 是否建议新手先做 |
|---|---|---|
| P0 | 统一规则事实源 | 是 |
| P1 | 明确主实现与遗留模块角色 | 是 |
| P1 | 收敛参数系统 | 是 |
| P2 | 拆分超大文件 | 否，需在熟悉项目后进行 |
| P2 | 统一测试和入口 | 是 |
| P3 | 文档归档治理 | 是 |

---

**最终建议**：

新手接手本项目时，不要把它当成“需要全面重写的老项目”，也不要把它当成“已经完全稳定的产品项目”。  
最合适的定位是：

> 一个已经有较强主功能、但仍需要系统性收口历史债务的研究型工程项目。

