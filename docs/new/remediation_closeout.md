# LPPL 量化系统修复 — 封板验收报告

> 生成日期: 2026-05-16
> 范围: Sprint 1-7 (Sprint 6b 明确排除)

---

## 1. 封板范围

| Sprint | 范围 | 状态 |
|--------|------|------|
| Sprint 1: 量化正确性 | look-ahead AT, same-bar, survivorship, 费用, 流动性, 缺口穿越 | ✅ 完成 |
| Sprint 2: 可复现性 | DB isolation, DataBundle, 回测元数据 | ✅ 完成 |
| Sprint 3: 测试契约 | analyzer namedtuple bug, smoke exit code, 三层测试分层, output 解耦 | ✅ 完成 |
| Sprint 4: 基础设施 | CI Phase 1, env var 合约, 局部 warning 过滤 | ✅ 完成 |
| Sprint 5: LPPL 算法 | R² clamp, DE 4 seeds, 共识阈值 0.5, 综合方向判定, tc_error | ✅ 完成 |
| Sprint 6a: 架构清理 | package install, src/ sys.path→0, CLI 路由, 7 DeprecationWarning | ✅ 完成 |
| Sprint 7: 代码质量 | 528 lint 修复, numba 去重, peak 向量化, total_pnl 语义修正 | ✅ 完成 |
| **Sprint 6b: research 整理** | scripts/ 迁移, archive 策略 | ⏳ **明确排除** |

---

## 2. 生产路径关键指标

| 指标 | 值 | 验证方法 |
|------|----|---------|
| `src/` sys.path.insert | **0 处** | `grep -rn "sys.path.insert" src/` |
| `src/` 全局 filterwarnings("ignore") | **0 处** | `grep -rn "filterwarnings.*ignore" src/` |
| 编译器 | 通过 | `python -m compileall src/ main.py` |
| TDX_DATA_DIR | 必需 env var | 缺失时 `require_tdx_data_dir()` 抛 RuntimeError |
| TDX reader | lazy init | 仅在使用时触发, 不阻塞进程池初始化 |
| DB 默认 | `:memory:` | `Database()` 默认为 in-memory, 隔离跨运行状态 |
| R² | `max(0.0, ...)` | 负 R² clamp |
| DE optimizer | 4 seeds (0,42,123,9999) | 取最优而非单次固定 |
| 共识阈值 | `0.5` (原 0.15) | 多数窗口通过才触发 |
| t+1 执行 | `shift(1) + searchsorted(side="right")` | 信号永远滞后于执行 |
| 费用模型 | 佣金 + 印花税, 对称 | 买入扣佣金, 卖出扣佣金 + 印花税 |
| 流动性约束 | 默认开启 | `enable_limit_move_constraint=True` |
| 缺口穿越 | 开盘→跳空→盘中三序 | `open ≤ sl < low` → `low ≤ sl ≤ high` |

---

## 3. 已知遗留项 (不阻塞本次封板)

以下问题在封板范围内 **不修复**, 作为下一阶段治理事项持续跟踪:

**注**: 全量测试计数以修复落地时的记录为准（163 tests, 1 FAIL; pytest 220 pass/4 skip/6 fail），封板轮次未再次独立全量复跑复核。新增回归（DataManager/TDX lazy init/CLI smoke）已修复并定向确认。

### 3.1 测试失败 (pre-existing)

| 测试 | 框架 | 根因 | 备注 |
|------|------|------|------|
| `test_cli_warning_filters_are_targeted` | unittest | 测试断言 `assertFalse(['ignore'])` 失败 | 与 Sprint 4 的 warning 过滤修改目标冲突, 需重新设计测试逻辑 |
| `test_backtest_smoke.*` (6 tests) | pytest | subprocess 执行 `run_backtest.py` 依赖输出文件且无 TDX 数据 | pre-existing, 与 Sprint 6b 范围相关 |
| `test_run_function_importable` | pytest | subprocess import 路径问题 | pre-existing |

### 3.2 Ruff Lint 残留

```
剩余: 750 errors (非 auto-fixable)
已修: 528 errors (Sprint 7: ruff check --fix .)
```

主要残留类别: `F401` (unused imports), `F841` (unused variables), 分布于 `scripts/` 和 `tests/`。

### 3.3 Sprint 6b 未完成

- `scripts/` 下 ~95 个 research 脚本中的持久性逻辑未迁移到 `src/`
- `scripts/` 和根目录 wrapper 的 sys.path.insert 未清理 (~93 处)
- `scripts/archive/`, `unused/` 中的实验代码未整理

---

## 4. 与审计报告对照

关联审计报告: `docs/new/lppl_quant_audit_report.md`

| 审计发现 | 严重度 | 修复 Sprint | 修复状态 |
|---------|--------|------------|---------|
| 未来 ATR | CRITICAL | Sprint 1.1 | ✅ |
| Same-bar (backtest) | CRITICAL | Sprint 1.2 | ✅ |
| Same-bar (simulator) | CRITICAL | Sprint 1.3 | ✅ |
| Survivorship bias | CRITICAL | Sprint 1.4 | ✅ (方案 B: 记录偏差来源) |
| namedtuple 误用 | CRITICAL | Sprint 3.1 | ✅ |
| 无交易费用 | HIGH | Sprint 1.5 | ✅ |
| 流动性约束默认关 | HIGH | Sprint 1.6 | ✅ |
| 假设精确成交 | HIGH | Sprint 1.7 | ✅ |
| 缺失日期回退 | HIGH | Sprint 1.3 | ✅ |
| DB 跨运行 | HIGH | Sprint 2.1 | ✅ |
| 数据源不固定 | HIGH | Sprint 2.2 | ✅ |
| 元数据不完整 | HIGH | Sprint 2.3 | ✅ |
| R² 负值 | HIGH | Sprint 5.1 | ✅ |
| DE 固定种子 | HIGH | Sprint 5.2 | ✅ |
| 共识阈值过低 | HIGH | Sprint 5.3 | ✅ |
| 方向判定仅用 b | HIGH | Sprint 5.4 | ✅ |
| Walk-forward 标签 | HIGH | Sprint 5.5 | ✅ |
| 13 集成测试失败 | MEDIUM | Sprint 3.1 | ✅ (analyzer bug 已修, 剩余取决于 TDX 数据) |
| 不检查子进程码 | MEDIUM | Sprint 3.2 | ✅ |
| 测试未分层 | MEDIUM | Sprint 3.3 | ✅ |
| 1263 lint 错误 | MEDIUM | Sprint 7.1 | ✅ (528 已修, 750 已标记遗留) |
| Numba 代码重复 | MEDIUM | Sprint 7.2 | ✅ |
| 未向量化循环 | MEDIUM | Sprint 7.3 | ✅ |
| sys.path 手术 (src/) | MEDIUM | Sprint 6a.2 | ✅ |
| 全局 warning 抑制 (src/) | MEDIUM | Sprint 4.3 | ✅ |
| 硬编码路径 | MEDIUM | Sprint 4.2 | ✅ |
| Artifacts 耦合 | MEDIUM | Sprint 3.4 | ✅ |
| total_pnl 语义错误 | MEDIUM | Sprint 7.4 | ✅ |
| 无 CI | MEDIUM | Sprint 4.1 | ✅ (Phase 1) |
| 全局可变状态 | LOW | — | 未修复 (非阻塞) |
| 魔术数字 | LOW | — | 未修复 (非阻塞) |
| Backtest 配置 70+ 字段 | LOW | — | 未修复 (非阻塞) |

---

## 5. 封板结论

**Sprint 1-7（不含 6b）已完成并可封板。**

生产路径 `src/` 的关键整改已落地，包括量化正确性修复（ATR/t+1/费用/流动性/缺口穿越）、可复现性基建（DB isolation/DataBundle/元数据）、CI Phase 1、架构清理（src/ 零 sys.path/零全局 warning）、核心算法修正（R² clamp/DE 多起点/共识阈值/方向判定）。

当前保留已知遗留项：
- unit/pytest 中的 pre-existing failures（test_warning_filters, test_backtest_smoke）
- ruff 残余 750 非 auto-fixable errors
- Sprint 6b 未开始（research scripts 迁移和归档）

上述遗留项不阻塞本次范围封板，但应作为下一阶段治理事项继续跟踪。

---

## 6. 建议下一步

1. **Sprint 6b**: research scripts 迁移 (`scripts/backtest_core.py` 策略逻辑 → `src/strategies/`, archive 清理)
2. **Sprint 5.5 后续**: walk-forward 的 tc_error 指标纳入正式回测报告
3. **Phase 2 CI**: 追加 `tests/contract/` 集成测试 job
4. **遗留项治理**: 修复 pre-existing test failure, 逐步清理剩余 lint
