# 修复后审查报告 — Round 4

> 生成日期: 2026-05-13
> 审查范围: `src/` + `scripts/` = 162个Python文件
> 审查方式: python-reviewer + security-reviewer + code-reviewer + build-error-resolver 并行审查
> 测试基线: pytest tests/unit: **176/176 passed** | bare except: **0处** | ruff: 1784 errors(格式为主)

---

## 一、三轮修复前后对比

| 指标 | 修复前 | Round 1 | Round 2 | Round 3 | **当前** |
|------|:-----:|:-------:|:-------:|:-------:|:-------:|
| 测试通过 | 176/176 | 176/176 | 176/176 | 176/176 | **✅ 176/176** |
| SQL注入 | 2处 | 0处 | 0处 | 0处 | **✅ 0处** |
| 硬编码路径(scripts) | 33 | 0 | 0 | 0 | **✅ 0处** |
| 硬编码路径(src) | 3处 | 1处 | 1处 | **0处** | **✅ 0处** |
| 裸except | 33处 | 8处 | 8处 | 0处 | **✅ 0处** |
| 路径遍历 | 1处 | 0处 | 0处 | 0处 | **✅ 0处** |
| 魔法数字 | 3处 | 0处 | 0处 | 0处 | **✅ 0处** |
| -> None类型标注 | 0 | 1 | 1 | 5 | **✅ 5处** |
| Numba重复检查 | 2处 | 2处 | 2处 | **0处** | **✅ 0处** |
| 函数内import | 3处 | 3处 | 3处 | **0处** | **✅ 0处** |
| 环境变量(TDX) | 否 | 是 | 是 | 是 | **✅ 是** |

---

## 二、当前CRITICAL/HIGH问题

### CRITICAL (1项)

| ID | 问题 | 文件 | 行数 | 说明 |
|:--:|------|------|:---:|------|
| R4-01 | Wyckoff `analyzer.py` **废弃但仍被使用** | `src/wyckoff/analyzer.py` | 1646 | docstring说"新代码不应直接引用"，但4个文件仍导入使用，测试仍在测试它 |

### HIGH (5项)

| ID | 问题 | 文件 | 说明 |
|:--:|------|------|------|
| R4-02 | `backtest.py:run_strategy_backtest` 超长(157行) — 神函数 | `src/investment/backtest.py` | 混合权益追踪/交易执行/风控/净值计算7项职责 |
| R4-03 | `engine.py:_step1_phase_determine` (160行, 5层嵌套) | `src/wyckoff/engine.py` | 20+条件分支难以追踪 |
| R4-04 | `factor_combination.py` 定义重复Enum | `src/investment/factor_combination.py` | Regime/Phase等在wyckoff/models.py已存在 |
| R4-05 | `get_data` 回退链5层嵌套 (60行) | `src/data/manager.py` | 数据源选择逻辑过于复杂 |
| R4-06 | `multiframe or True` 永远是True—参数无效 | `src/wyckoff/engine.py:771` | 逻辑bug: 参数被忽略 |

---

## 三、剩余安全风险

| 检查项 | 状态 |
|-------|:----:|
| SQL注入 | ✅ 全部参数化查询 |
| 路径遍历 | ✅ symbol regex + resolve校验 |
| 裸except | ✅ 0处 |
| 硬编码密钥 | ✅ 未发现 |
| 命令注入 | ✅ 未使用os.system |
| 反序列化 | ✅ yaml.safe_load |
| 本次新修 | ✅ tdx_reader.py补`import os` (R4审查中发现) |

**安全等级: LOW** — 无剩余CRITICAL/HIGH安全漏洞。

---

## 四、生产就绪度评估

| 维度 | 评级 | 说明 |
|------|:---:|------|
| 测试覆盖 | ⚠️ 单元176/176通过 | 集成测试有3个collect error，wyckoff_6cycle_test等 |
| 安全 | ✅ 低风险 | 无SQL注入/路径遍历/密钥泄露 |
| 配置管理 | ✅ | TDX_DATA_PATH环境变量化 |
| 代码质量 | ⚠️ | 深度嵌套函数+超长文件仍有 |
| 文档 | ✅ | docs/new/ 完整审计记录 |

**生产就绪度: ⚠️ 接近但未就绪** — 安全上已就绪，但`analyzer.py`(1646行废弃文件)和超长函数需处理。

---

## 五、下阶段优先级

| 优先级 | 任务 | 预计工时 |
|:-----:|------|:-------:|
| 🔴 P0 | `tdx_reader.py` 已修 `import os` (本次审查发现, 已当场修复) | **已修** |
| 🟠 P1 | 确认`engine.py`完全覆盖后删除`analyzer.py` | 2h |
| 🟠 P1 | 修复3个集成测试collect error | 1h |
| 🟡 P2 | `engine.py:_step1_phase_determine` 拆分为独立判定类 | 3h |
| 🟡 P2 | `backtest.py:run_strategy_backtest` 拆分 | 2h |
| 🟡 P2 | `multiframe or True` 逻辑修复 | 15min |

---

## 六、总结

三轮修复后代码库安全状况良好，**安全等级已降至LOW**。安全方面(SQL注入/路径遍历/裸except/硬编码密钥/命令注入)已全部清理。主要剩余问题是**架构债务**——`analyzer.py`(1646行废弃文件)和超长函数。下阶段应聚焦删除废弃代码和拆分超长函数。
