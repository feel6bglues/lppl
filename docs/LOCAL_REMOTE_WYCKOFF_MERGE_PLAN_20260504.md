# 本地与远程 Wyckoff 代码合并清单

日期: 2026-05-04

## 结论

当前应以远程主线 `origin/main` / `de78385` 作为基线继续推进。

原因:

- 远程主线已经接入现有项目结构，包含 CLI、Wyckoff 模块、脚本、文档和已提交测试。
- 本地未跟踪的多模态实现不是完整分支，运行时依赖 `stash` 中的基础设施补丁。
- 本地新实现目前无法独立通过测试收集，不适合作为直接替换主线。

## 已确认状态

当前工作区包含两类本地内容:

1. `stash@{0}`
- `src/constants.py`
- `src/data/manager.py`
- `src/exceptions.py`

2. 未跟踪文件
- `src/cli/wyckoff_multimodal_analysis.py`
- `src/wyckoff/config.py`
- `src/wyckoff/data_engine.py`
- `src/wyckoff/reporting.py`
- `tests/unit/test_wyckoff_data_engine.py`
- `tests/unit/test_wyckoff_models.py`
- `tests/integration/test_wyckoff_integration.py`
- 若干设计文档和根目录 wrapper 文件

## 验证结果

已执行:

- `.venv/bin/pytest -q tests/unit/test_wyckoff_analyzer.py`
- `.venv/bin/pytest -q tests/unit/test_wyckoff_analyzer.py tests/unit/test_wyckoff_models.py tests/unit/test_wyckoff_data_engine.py tests/integration/test_wyckoff_integration.py`

结果:

- 远程现有测试 `tests/unit/test_wyckoff_analyzer.py` 为 `21 passed, 1 failed`。
- 本地新测试链在收集阶段失败，关键错误为:
  - `src.wyckoff.models` 缺少 `BCResult`
  - `src.constants` 缺少 `MIN_WYCKOFF_DATA_ROWS`
  - `src.constants` 缺少 `WYCKOFF_OUTPUT_DIR`

判断:

- 远程主线可作为主版本继续修复。
- 本地新实现处于“依赖未补齐”的半集成状态。

## 文件级建议

### 一类: 优先吸收

这些改动属于基础设施增强，和远程主线方向一致，且能直接补齐本地多模态实现的缺口。

`src/constants.py`
- 建议吸收 `stash` 中新增的 Wyckoff 常量。
- 价值:
  - 为 `src/wyckoff/config.py` 和 `src/wyckoff/data_engine.py` 提供常量依赖。
  - 不会直接替换远程 Wyckoff 核心算法，风险相对可控。
- 风险:
  - 枚举值命名需要与现有 `models.py`、`fusion_engine.py` 保持一致，避免同义不同名。

`src/exceptions.py`
- 建议吸收 `stash` 中新增的 Wyckoff 异常类型。
- 价值:
  - 能提升规则引擎和输入校验的错误边界表达能力。
  - 属于低耦合基础设施改动。

`src/data/manager.py`
- 建议有选择地吸收 `stash` 中的 Wyckoff 数据入口扩展。
- 优先保留的方法:
  - `normalize_symbol`
  - `classify_asset_type`
  - `read_from_file`
  - `get_wyckoff_data`
- 价值:
  - 支持指数、个股、文件输入三种入口。
  - 对新 CLI 和后续数据入口统一都有帮助。
- 风险:
  - `classify_asset_type` 当前按代码前缀判断，规则较粗。
  - `normalize_symbol` 默认 6 位代码补成 `.SH`，对深市个股可能误判。

### 二类: 条件吸收

这些文件代表新的架构方向，但不能整套直接并入，需要先和远程现有导出面、模型层、状态层做兼容设计。

`src/cli/wyckoff_multimodal_analysis.py`
- 建议保留思路，不建议直接纳入主入口。
- 价值:
  - 模式划分清晰，支持 `data_only` / `image_only` / `fusion`。
  - 输入校验意识比远程现有 CLI 更强。
- 问题:
  - 依赖 `src.wyckoff.config`、`src.wyckoff.data_engine`、`src.wyckoff.reporting`。
  - 当前项目导出面仍以 `src.wyckoff.analyzer` 和 `src.cli.wyckoff_analysis` 为主。

`src/wyckoff/config.py`
- 建议后续作为配置层候选保留。
- 价值:
  - 规则引擎、图像引擎、融合引擎配置被显式拆开。
- 问题:
  - 常量来源尚未并入主线。
  - 还没有和现有 CLI、现有配置文件体系完成统一。

`src/wyckoff/data_engine.py`
- 不建议直接替换 `src/wyckoff/analyzer.py`。
- 价值:
  - 结构比现有 `WyckoffAnalyzer` 更模块化。
  - 测试目标和规则链边界更清晰。
- 问题:
  - 依赖新的数据模型定义。
  - 与当前 `src/wyckoff/__init__.py` 的导出接口不兼容。
  - 现有融合层、状态层和调用方都还不是围绕 `DailyRuleResult` 设计的。

`src/wyckoff/reporting.py`
- 建议保留为报告输出层重构候选，不建议直接接管当前输出逻辑。
- 价值:
  - 报告职责被独立出来，比 CLI 内直接写文件更清晰。
- 问题:
  - 依赖新的 `AnalysisResult` / `ImageEvidenceBundle` 结构。
  - 尚未确认和现有 `FusionEngine` 的字段完全一致。

### 三类: 暂缓吸收

这些文件当前主要服务于“新模型 + 新数据引擎”分支。在模型层未统一之前，直接并入只会扩大不兼容面。

`tests/unit/test_wyckoff_models.py`
- 暂缓。
- 原因:
  - 依赖 `BCResult`、`DailyRuleResult`、`ChartManifest` 等新模型。
  - 当前主线 `src/wyckoff/models.py` 不提供这些类型。

`tests/unit/test_wyckoff_data_engine.py`
- 暂缓。
- 原因:
  - 依赖 `DataEngine` 和新配置层。
  - 只有在模型层和常量层合并后才有意义。

`tests/integration/test_wyckoff_integration.py`
- 暂缓。
- 原因:
  - 依赖完整的新 CLI 与新引擎组合。
  - 当前还没有通过最小集成。

`wyckoff_multimodal_analysis.py`
- 暂缓。
- 原因:
  - 只是新 CLI 的根目录 wrapper。
  - 主体未稳定前没有单独引入价值。

文档类未跟踪文件
- 先保留，不优先并入。
- 原因:
  - 大量设计文档可作为参考，但不应先于代码整合进入主线。

`.git-archive-backup/`
- 不并入主线。
- 原因:
  - 属于归档/备份材料，不是生产代码。

## 推荐执行顺序

第一步: 吸收 `stash` 中的基础设施补丁
- 目标:
  - 让主线具备更完整的常量、异常和数据入口能力。
- 范围:
  - `src/constants.py`
  - `src/exceptions.py`
  - `src/data/manager.py`

第二步: 修复远程现有 Wyckoff 测试失败
- 目标:
  - 把 `tests/unit/test_wyckoff_analyzer.py` 先恢复到全绿。
- 原因:
  - 主线本身还不稳定，先修现有回归，比直接引入新引擎更稳。

第三步: 单独设计“新模型层”迁移方案
- 目标:
  - 决定是否让 `DataEngine` 与 `WyckoffAnalyzer` 并存，还是逐步替换。
- 要先解决:
  - `src/wyckoff/models.py` 是否新增并兼容新旧两套数据结构
  - `src/wyckoff/__init__.py` 的导出面如何保持兼容
  - `FusionEngine` / `StateManager` 的输入输出协议如何统一

第四步: 引入 `config.py` / `reporting.py` / 新测试
- 前提:
  - 第二步和第三步完成后再推进。

## 不建议的做法

- 不建议直接把未跟踪的 `src/wyckoff/data_engine.py` 整体替换现有 `src/wyckoff/analyzer.py`。
- 不建议先并入新测试再补代码，这会让主线立即进入不可运行状态。
- 不建议先并入全部设计文档，代码边界未定时文档会先过期。

## 下一步

按当前建议，最合理的起点是:

1. 先把 `stash` 里的 3 个文件整理成可提交补丁。
2. 跑现有 Wyckoff 测试，修掉 `test_analyze_uptrend` 的失败。
3. 再决定是否开始做新模型层兼容。
