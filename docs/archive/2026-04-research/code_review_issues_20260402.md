# 代码审查最终核验报告：因子计算、参数设置与逻辑问题

> 核验日期：2026-04-02
> 核验范围：`src/`、`scripts/`、`output/`
> 核验目标：对原审查文档中的 17 条 finding 做最终收口，并标注是否成立

## 总结

最终结论如下：

- `确认成立`：10 条
- `设计取舍 / 口径问题`：5 条
- `不成立`：2 条

从影响面看，优先级最高的是 `ISSUE-003`、`ISSUE-008`、`ISSUE-009`、`ISSUE-010`，因为它们会直接影响分组排序、候选筛选和最终报告可读性。

## 最终判定

### 确认成立

#### ISSUE-003: `_risk_band` 风险分层过于严格

`_risk_band()` 把 `annualized_excess_return <= 0.0` 直接判成 `DANGER`，高弹性组当前结果里也确实全部落入 `DANGER`。见 [src/investment/tuning.py](/home/james/Documents/Project/lppl/src/investment/tuning.py#L42-L53) 和 [output/grouped_ma_rescan_high_beta/summary.csv](/home/james/Documents/Project/lppl/output/grouped_ma_rescan_high_beta/summary.csv)

#### ISSUE-005: YAML 最优参数与类默认值差异大

`InvestmentSignalConfig.for_symbol()` 的默认值与 YAML 候选参数不一致，虽然 `from_mapping()` 会覆盖，但维护上存在双体系默认值。见 [src/investment/backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py#L99-L161) 和 [output/grouped_ma_rescan_candidate_yaml.yaml](/home/james/Documents/Project/lppl/output/grouped_ma_rescan_candidate_yaml.yaml)

#### ISSUE-006: 高弹性组 `enable_volatility_scaling` 搜索空间不完整

`HIGH_BETA_PLAN` 只扫 `True`，没有 `False` 分支。见 [src/investment/group_rescan.py](/home/james/Documents/Project/lppl/src/investment/group_rescan.py#L68-L86)

#### ISSUE-008: 分组聚合使用均值掩盖个体差异

`summarize_rescan_results()` 对超额、回撤、交易次数等使用均值，确实会掩盖单指数差异。见 [src/investment/group_rescan.py](/home/james/Documents/Project/lppl/src/investment/group_rescan.py#L278-L307)

#### ISSUE-009: `eligible_count` 与评分口径不一致

`eligible_count` 按硬门槛聚合，但 `hard_reject=False` 让不合格候选仍参与评分，`objective_score` 会显得很高。见 [src/investment/group_rescan.py](/home/james/Documents/Project/lppl/src/investment/group_rescan.py#L311-L334) 和 [output/grouped_ma_rescan_balanced/summary.csv](/home/james/Documents/Project/lppl/output/grouped_ma_rescan_balanced/summary.csv)

#### ISSUE-010: `turnover_cap=8.0` 对快 MA 组合过严

平衡组中多个 `MA10/120` 候选因 `turnover_cap` 被拒绝，说明该门槛对快 MA 组合偏紧。见 [src/investment/group_rescan.py](/home/james/Documents/Project/lppl/src/investment/group_rescan.py#L48-L86) 和 [output/grouped_ma_rescan_balanced/summary.csv](/home/james/Documents/Project/lppl/output/grouped_ma_rescan_balanced/summary.csv)

#### ISSUE-011: 正负 Bubble 分类依赖 `b` 参数索引

当前实现直接用 `params[4]` 判断 `b` 的正负，顺序变动就会出错。见 [src/lppl_engine.py](/home/james/Documents/Project/lppl/src/lppl_engine.py#L852-L857)

#### ISSUE-013: `tc_bound` 上限仅 100 天

`LPPLConfig.tc_bound` 和 `lppl_core.py` 的边界都把 `tc` 限制在 100 天内。见 [src/lppl_engine.py](/home/james/Documents/Project/lppl/src/lppl_engine.py#L49-L53) 和 [src/lppl_core.py](/home/james/Documents/Project/lppl/src/lppl_core.py#L158-L166)

#### ISSUE-015: `build_merged_candidate_yaml_lines` 忽略高弹性组

函数接收了 `high_beta_summary_df`，但当前实现直接丢弃，没有写入高弹性组候选。见 [src/investment/group_rescan.py](/home/james/Documents/Project/lppl/src/investment/group_rescan.py#L148-L165)

#### ISSUE-016: `932000.SH` 不在 `LOCAL_DATA_INDICES` 中

`INDICES` 包含 `932000.SH`，但它被单独放进 `AKSHARE_INDICES`，不会走本地 TDX 分支。见 [src/constants.py](/home/james/Documents/Project/lppl/src/constants.py#L6-L40)

### 设计取舍 / 口径问题

#### ISSUE-001: Calmar 比率口径不一致

当前主路径里 `calmar_ratio` 来自 `backtest.py`，不会触发 `group_rescan.py` 的 fallback；但 backtest 里使用的是策略年化回报，不是超额回报。严格说这不是已发生的 bug，更像评分口径风险。见 [src/investment/backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py#L1257-L1269) 和 [src/investment/group_rescan.py](/home/james/Documents/Project/lppl/src/investment/group_rescan.py#L245-L250)

#### ISSUE-004: 年化回报基于交易日行数而非自然日

年化回报确实按 `len(equity_df)` 计算，这是口径选择，不是实现错误。见 [src/investment/backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py#L1257-L1260)

#### ISSUE-007: 高弹性组 `scoring_profile` 降低超额权重

`risk_reduction` 把 `annualized_excess_return` 权重从 `0.25` 降到 `0.15`，这是偏好选择，不是 bug。见 [src/investment/tuning.py](/home/james/Documents/Project/lppl/src/investment/tuning.py#L8-L33)

#### ISSUE-012: 模块级全局 config 引用

`calculate_risk_level()` 依赖模块级 `config`，这是结构性耦合问题，但当前不会直接导致错误。见 [src/lppl_engine.py](/home/james/Documents/Project/lppl/src/lppl_engine.py#L379-L388) 和 [src/lppl_engine.py](/home/james/Documents/Project/lppl/src/lppl_engine.py#L876-L877)

#### ISSUE-014: `ensemble_grid_search.py` 的 objective 函数偏重 recall

目标函数确实偏 recall，但这属于搜索目标选择，不是实现错误。见 [scripts/ensemble_grid_search.py](/home/james/Documents/Project/lppl/scripts/ensemble_grid_search.py#L36-L40)

### 不成立

#### ISSUE-002: `_evaluate_ma_cross_atr` 卖出逻辑不对称

非动量分支里的卖出条件并不是“只有死叉”，而是 `bearish_cross and atr_ratio >= vol_breakout_mult`，卖出同样有 ATR 过滤。见 [src/investment/backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py#L423-L426)

#### ISSUE-017: `INDICES` 字典包含 `932000.SH` 但 `LOCAL_DATA_INDICES` 不包含

这是 `ISSUE-016` 的重复表述。`DataManager.get_data()` 会先判断 `LOCAL_DATA_INDICES`，再走 `AKSHARE_INDICES` 分支，不会静默跳过。见 [src/data/manager.py](/home/james/Documents/Project/lppl/src/data/manager.py#L427-L436)

## 建议优先级

### 立即处理

- `ISSUE-003`
- `ISSUE-008`
- `ISSUE-009`
- `ISSUE-010`

### 结构优化

- `ISSUE-005`
- `ISSUE-006`
- `ISSUE-011`
- `ISSUE-013`
- `ISSUE-015`
- `ISSUE-016`

### 策略或口径说明

- `ISSUE-001`
- `ISSUE-004`
- `ISSUE-007`
- `ISSUE-012`
- `ISSUE-014`

### 删除

- `ISSUE-002`
- `ISSUE-017`

## 一句话结论

这份原始审查里，真正需要优先修的是分层、聚合和筛选口径问题，而不是卖出逻辑或数据分流本身；最终可落地的问题集中在 `tuning.py` 和 `group_rescan.py`。
