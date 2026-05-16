# Scripts 目录说明

> **⚠️ RESEARCH SCRIPTS — 不受 CI 或量化审计覆盖**
> 本目录中的脚本是实验/研究代码，不满足生产代码标准。
> 不运行 `ruff`/`mypy`，不要求测试覆盖，可能有重复代码。
> 所有生产逻辑已在 `src/` 中维护。详见 `scripts/ARCHITECTURE.md`。

本目录包含实验/研究脚本和工具脚本。

## 脚本分类

### 活跃脚本 (Active)
- `ensemble_grid_search.py` - 网格搜索最优参数
- `train_test_group_rescan.py` - 分组重扫描

### 实验脚本 (Experimental)
- `test_lppl_ma.py` - MA策略实验

### 遗留脚本 (Legacy - 向后兼容)
- `lppl_backtest.py` - 历史回测（独立实现，不依赖src）
- `lppl.py` - 早期原型
- `verify_lppl.py` - 早期验证（被 src/cli/lppl_verify_v2.py 取代）

## 开发建议
新项目请使用 `src/cli/` 下的正式入口。
