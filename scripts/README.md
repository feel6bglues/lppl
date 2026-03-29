# 脚本说明

此目录存放研究型与实验型脚本，不属于主流程必跑入口：

- `ensemble_grid_search.py`：参数网格搜索。
- `lppl_backtest.py`：回测分析。
- `verify_lppl.py`：早期验证脚本（保留用于对照）。
- `test_lppl_ma.py`：多窗口+移动平均实验脚本。
- `lppl.py`：早期扫描原型脚本。

生产/日常流程请使用根目录兼容入口或 `src/cli/` 下对应实现。
