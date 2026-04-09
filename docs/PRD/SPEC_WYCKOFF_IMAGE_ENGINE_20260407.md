# 威科夫图像引擎规范

**文档日期**: 2026-04-07  
**适用对象**: 图像分析实现者 / 多模态工程师 / 测试工程师  
**文档目标**: 规范图像扫描、归类、质量分级与视觉证据输出

---

## 1. 图像输入来源

支持以下输入方式：

- `--chart-dir`
- `--chart-files`
- 项目已有 `output/**/plots/*`

支持格式：

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`

---

## 2. 文件扫描规则

### 2.1 扫描范围

- 若提供 `--chart-dir`，递归扫描其下所有支持格式图片
- 若提供 `--chart-files`，只消费显式文件列表

### 2.2 清单输出

必须生成 `chart_manifest`，记录：

- 文件路径
- 文件名
- 相对目录
- 文件修改时间
- 归属 symbol
- 推断 timeframe
- 图像质量

---

## 3. 标的归属规则

优先级如下：

1. 文件名包含标准 symbol
2. 父目录名包含标准 symbol
3. 命令行显式指定 `--symbol`
4. 无法归属则记为 `unassigned`

`unassigned` 图片不得进入主结论，只能写入 evidence 警告。

---

## 4. 时间周期识别规则

优先级如下：

1. 文件名识别
2. OCR 辅读图文字
3. 视觉布局启发式
4. 无法识别则标为 `unknown_tf`

建议识别值：

- `weekly`
- `daily`
- `60m`
- `30m`
- `15m`
- `5m`
- `unknown_tf`

---

## 5. 图像质量分级

图像质量分为：

- `high`
- `medium`
- `low`
- `unusable`

### 5.1 high

- 分辨率足够
- K 线区清晰
- 边界可辨
- 量能区清晰

### 5.2 medium

- 结构仍可辨认
- 少量遮挡或压缩

### 5.3 low

- 只能看大趋势
- 细节难辨

### 5.4 unusable

- 严重模糊
- 重度遮挡
- 主图裁切过度
- 无法区分 K 线与量能区

`low` 和 `unusable` 图片不得提升置信度。

---

## 6. 视觉证据输出范围

图像引擎只允许输出以下类别：

- `visual_trend`
- `visual_phase_hint`
- `visual_boundary_hint`
- `visual_anomalies`
- `visual_volume_label`
- `image_quality`
- `trust_level`

### 6.1 趋势

- `uptrend`
- `downtrend`
- `range`
- `unclear`

### 6.2 阶段提示

- `possible_accumulation`
- `possible_markup`
- `possible_distribution`
- `possible_markdown`
- `unclear`

### 6.3 边界提示

- 箱体上沿
- 箱体下沿
- 通道上轨
- 通道下轨
- 供应区
- 需求区

### 6.4 异常 K 线提示

- 长上影
- 长下影
- 跳空
- 假突破
- 快速收回
- 放量滞涨

### 6.5 量能标签

只允许：

- `extreme_high`
- `above_average`
- `contracted`
- `extreme_contracted`
- `unclear`

---

## 7. 禁止输出内容

图像引擎严禁输出：

- 精确 OHLC 数值
- 成交量绝对数值
- 最终交易方向
- 最终买点、止损、目标位

图像引擎只能提供证据，不得直接生成交易计划。

---

## 8. 传统视觉预处理职责

允许的职责：

- 裁切主图区和量能区
- 边缘/轮廓检测
- K 线密度与颜色分布分析
- 水平边界带候选提取
- OCR 辅读文字

不要求：

- 精确还原每一根 K 线的数值

---

## 9. 多模态模型职责

多模态模型仅可做：

- 图像结构摘要
- 周期识别辅助
- 边界与趋势提示
- 视觉异常整理

多模态模型不得：

- 直接生成买卖建议
- 推翻数据引擎的日线事实

---

## 10. 图片-only 模式限制

若缺少 OHLCV 数据：

- 可输出视觉证据报告
- 可输出低置信观察结论
- 不可输出高置信执行级计划

默认限制：

- `confidence <= C`
- `decision` 只允许 `watch_only`、`no_trade_zone` 或 `abandon`

---

## 11. 失败与回退

### 11.1 无可用图片

- 记录空 manifest
- 由数据引擎单独运行

### 11.2 图片全部 unusable

- 图像证据层失效
- 不影响数据-only 结论

### 11.3 图片冲突过大

- 图像层整体降级
- 写入 conflict 列表

---

## 12. 最小可交付要求

图像引擎实现完成的最低标准：

- 可扫描文件夹
- 可归属 symbol
- 可识别 timeframe 或标记 unknown
- 可输出质量等级
- 可输出视觉证据 bundle
- 可生成 manifest
