# 2026-04 研究归档索引

本目录存放 2026-03-29 到 2026-04-03 期间产生的阶段性材料。

这些文档的用途是：

- 保留当时的审计结论、修复计划和研究思路
- 帮助回溯为什么会做出后续代码和配置调整
- 为后续复盘提供历史上下文

这些文档**不作为当前主流程运行依据**。  
当前应优先参考：

- [`使用文档.md`](/home/james/Documents/Project/lppl/docs/使用文档.md)
- [`因子交易策略新手指南.md`](/home/james/Documents/Project/lppl/docs/因子交易策略新手指南.md)
- [`TECH_DEBT_REMEDIATION_LOG_20260404.md`](/home/james/Documents/Project/lppl/docs/TECH_DEBT_REMEDIATION_LOG_20260404.md)
- [`e2e_optimization_report_20260404.md`](/home/james/Documents/Project/lppl/e2e_optimization_report_20260404.md)

## 文档清单

- [`code_review_issues_20260402.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/code_review_issues_20260402.md)
  代码审查最终核验报告，记录 17 条历史 finding 的判定结果。

- [`fix_plan_20260402.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/fix_plan_20260402.md)
  基于审查问题制定的修复路线，适合回看修复优先级演变。

- [`strategy_reevaluation_plan_20260403.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/strategy_reevaluation_plan_20260403.md)
  针对多轮实验后的策略重评估与再调优计划。

- [`TEST_PLAN_MA20_MA60_ATR_LPPL.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/TEST_PLAN_MA20_MA60_ATR_LPPL.md)
  双均线 + ATR + LPPL 状态机方案的阶段性测试计划。

- [`beginner_execution_runbook.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/beginner_execution_runbook.md)
  当时面向接手者的执行手册，保留了阶段性判断。

- [`lppl_signal_experiment_retro_20260329.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/lppl_signal_experiment_retro_20260329.md)
  LPPL 参数源和实验轮次复盘。

- [`momentum_factor_optimization_proposal.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/momentum_factor_optimization_proposal.md)
  动量因子增强方向的研究提案。

- [`next_strategy_implementation_plan_20260401.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/next_strategy_implementation_plan_20260401.md)
  某一阶段“下一步怎么做”的实施计划。

- [`strategy_return_audit_20260401.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/strategy_return_audit_20260401.md)
  已落盘参数组合的收益口径审计。

- [`渐进式融合测试方案.md`](/home/james/Documents/Project/lppl/docs/archive/2026-04-research/渐进式融合测试方案.md)
  渐进式动量增强方案的阶段性设计文档。

## 使用建议

- 需要当前运行命令时，不要直接照抄本目录中的命令，先对照主文档。
- 需要理解某个历史决策时，优先从审计报告和修复计划开始。
- 需要回看实验方向演进时，再查策略计划、测试计划和研究提案。
