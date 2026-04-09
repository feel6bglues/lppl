# 威科夫多模态分析实施计划

**文档日期**: 2026-04-07  
**适用对象**: 工程负责人 / 实现工程师 / 测试工程师  
**文档目标**: 规定开发阶段、文件边界、依赖顺序与 DoD

---

## 1. 总体里程碑

项目分 6 个阶段交付：

1. 数据层扩展
2. 规则引擎
3. 图像引擎
4. 融合引擎与状态层
5. 报告层与可选 LLM
6. 测试、文档、Smoke Run

---

## 2. Phase 1: 数据层扩展

### 目标

- 支持指数 + 个股 + 文件输入

### 涉及模块

- `src/data/manager.py`
- `src/data/tdx_reader.py`
- `src/wyckoff/config.py`

### 产出

- symbol 标准化
- 个股数据读取
- 统一 DataFrame 输出

### DoD

- 个股和指数都能读取
- 数据-only 最小链路可跑

---

## 3. Phase 2: 规则引擎

### 目标

- 实现 Step 0 ~ Step 5 日线规则

### 涉及模块

- `src/wyckoff/models.py`
- `src/wyckoff/data_engine.py`

### 产出

- `DailyRuleResult`
- BC 扫描
- 阶段识别
- T+1 与 R:R
- 交易计划骨架

### DoD

- 关键强约束单测通过

---

## 4. Phase 3: 图像引擎

### 目标

- 扫描项目图表文件夹并输出视觉证据

### 涉及模块

- `src/wyckoff/image_engine.py`

### 产出

- chart manifest
- timeframe 识别
- 图像质量评分
- visual evidence bundle

### DoD

- 能处理现有 `output/**/plots/*.png`

---

## 5. Phase 4: 融合引擎与状态层

### 目标

- 合并数据与图像证据
- 输出统一结果并落盘状态

### 涉及模块

- `src/wyckoff/fusion_engine.py`
- `src/wyckoff/state.py`

### 产出

- 冲突矩阵
- 最终置信度
- 状态文件
- 连续性追踪模板

### DoD

- 冲突场景集成测试通过

---

## 6. Phase 5: 报告层与可选 LLM

### 目标

- 生成 deterministic 报告
- 支持 optional LLM 增强

### 涉及模块

- `src/wyckoff/reporting.py`
- `src/cli/wyckoff_multimodal_analysis.py`

### 产出

- Markdown / HTML
- 附录 A / B
- fallback 机制

### DoD

- 无 LLM 配置时仍可完整输出

---

## 7. Phase 6: 测试、文档、Smoke Run

### 目标

- 完成单测、集成、回归
- 更新 README 与使用文档

### 涉及模块

- `tests/unit/*`
- `tests/integration/*`
- `README.md`
- `docs/使用文档.md`

### 产出

- 测试用例
- 最小运行命令
- 使用文档补充

### DoD

- 关键测试通过
- Smoke run 通过

---

## 8. 依赖顺序

严格依赖如下：

1. 数据层
2. 规则引擎
3. 图像引擎
4. 融合引擎
5. 报告层
6. 测试与文档

不得先做报告层再反推 schema。

---

## 9. 风险点

- 个股路径与 symbol 兼容性
- 图片命名不规范导致归属失败
- 图像质量不稳定
- 结构规则过松导致误判
- LLM 输出越权改写

---

## 10. 实施完成标准

以下全部满足时，实施计划视为完成：

- 代码主链可运行
- 三种模式可执行
- 报告与状态工件完整
- 强约束规则全部通过测试
- 文档更新完成
