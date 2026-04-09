# A股威科夫多模态分析系统架构设计

**文档日期**: 2026-04-07  
**适用对象**: 后端工程师 / AI 工程师 / 测试工程师  
**文档目标**: 定义系统模块边界、数据流、输出工件与降级路径

---

## 1. 架构总览

系统采用六层结构：

1. CLI 输入层
2. 数据引擎层
3. 图像引擎层
4. 融合引擎层
5. 报告层
6. 状态与工件持久化层

LLM 增强层作为可选侧挂模块存在，不参与主裁决。

---

## 2. 模块分层

### 2.1 CLI 输入层

职责：

- 接收 `symbol` / `input-file` / `chart-dir` / `chart-files`
- 组织输出目录
- 调度数据、图像、融合、报告与状态流程

建议入口：

- `wyckoff_multimodal_analysis.py`
- `src/cli/wyckoff_multimodal_analysis.py`

### 2.2 数据引擎层

职责：

- 读取标准 OHLCV
- 执行日线规则
- 输出 `DailyRuleResult`

### 2.3 图像引擎层

职责：

- 扫描项目图表文件夹
- 提取视觉证据
- 识别 timeframe 与质量
- 输出 `ImageEvidenceBundle`

### 2.4 融合引擎层

职责：

- 合并数据引擎与图像引擎结果
- 计算冲突与一致性
- 生成最终 `AnalysisResult`

### 2.5 报告层

职责：

- 渲染 Markdown / HTML
- 生成图表
- 生成附录与证据摘要

### 2.6 状态层

职责：

- 保存分析状态
- 保存冷冻期信息
- 支持连续性追踪

---

## 3. 建议模块结构

建议新增目录：

- `src/wyckoff/__init__.py`
- `src/wyckoff/models.py`
- `src/wyckoff/data_engine.py`
- `src/wyckoff/image_engine.py`
- `src/wyckoff/fusion_engine.py`
- `src/wyckoff/reporting.py`
- `src/wyckoff/state.py`
- `src/wyckoff/config.py`

建议新增 CLI：

- `src/cli/wyckoff_multimodal_analysis.py`
- 根目录 wrapper: `wyckoff_multimodal_analysis.py`

---

## 4. 数据流

### 4.1 数据-only

1. CLI 读取参数
2. 数据引擎加载 OHLCV
3. 日线规则引擎输出事实
4. 融合引擎直接透传为最终结论
5. 报告层输出
6. 状态层落盘

### 4.2 图片-only

1. CLI 扫描图像
2. 图像引擎提取证据
3. 融合引擎生成低置信视觉结论
4. 报告层输出视觉证据报告
5. 状态层可选落盘

### 4.3 数据 + 图片融合

1. 读取数据
2. 扫描图片
3. 分别输出 `DailyRuleResult` 与 `ImageEvidenceBundle`
4. 融合引擎生成 `AnalysisResult`
5. 报告层渲染
6. 状态层落盘

---

## 5. 主次裁判关系

### 5.1 数据优先

数据引擎主裁判：

- 日线阶段
- BC 定位
- T+1 风险
- R:R
- 交易计划字段

### 5.2 图像辅助

图像引擎辅助裁判：

- 周线背景
- 盘中结构确认
- 边界区视觉提示
- K 线异常形态提示
- 图片质量与冲突提示

### 5.3 LLM 不裁判

LLM 不参与：

- 阶段识别
- BC 判定
- 方向判断
- 风险门槛判定

---

## 6. 输出目录

单次分析建议输出结构：

```text
output/wyckoff/<symbol_or_run_id>/
├── raw/
├── plots/
├── reports/
├── summary/
├── state/
└── evidence/
```

---

## 7. 与现有系统的关系

### 7.1 复用能力

可复用：

- `DataManager`
- `TDXReader`
- `PlotGenerator` 的 K 线绘图基础
- 现有 Markdown / HTML 报告输出风格

### 7.2 不应耦合

不应强耦合：

- LPPL 扫描主逻辑
- `index_investment_analysis.py` 现有信号链路
- 既有 verification report schema

---

## 8. 降级路径

### 8.1 无 LLM

- 回退 deterministic 模板报告

### 8.2 图像不可用

- 只运行数据引擎

### 8.3 数据不可用

- 仅输出低置信视觉报告

### 8.4 图像与数据强冲突

- 降低置信度
- 输出保守结论
- 写入冲突清单

---

## 9. 错误处理原则

- 输入非法：明确报错并退出
- 数据不足：返回 `abandon`
- 图像模糊：证据降级但不中断整条链路
- LLM 异常：降级到模板报告
- 任何关键字段缺失：禁止输出高置信结论

---

## 10. 架构完成标志

当以下条件全部满足时，视为架构实现完成：

- CLI 可运行三种模式
- 数据引擎、图像引擎、融合引擎分离
- 状态与报告工件完整输出
- 降级路径可验证
- 不影响现有主线
