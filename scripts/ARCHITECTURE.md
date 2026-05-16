# Scripts/ 与 src/ 架构关系

```
scripts/                          src/
├── backtest_core.py ──compat──►  strategies/       # 多股票并行回测
│   ├── run_backtest              ├── backtest.py   # 编排 + 统计
│   ├── trade_wyckoff             ├── wyckoff.py    # Wyckoff 策略
│   ├── trade_ma                  ├── ma_cross.py   # MA5/20 金叉策略
│   ├── trade_str_reversal        ├── str_reversal.py # 短期反转策略
│   ├── get_regime                ├── regime.py     # 市场制度判定
│   ├── calc_atr                  ├── indicators.py # 共享指标
│   └── STRATEGY_MAP              └── registry.py   # 策略注册表
│
├── run_backtest.py               investment/       # 单股票净值回测引擎
│   (thin wrapper)                ├── backtest.py   # 信号生成 + 执行 + NAV
│                                 ├── signal_models.py
│                                 └── config.py
├── tuning/ ──research-only──►    (无对应关系)
└── archive/ ──frozen──►          (无对应关系)
```

## 原则

1. **生产代码在 `src/`** — 所有可复用的策略、指标、引擎逻辑都在 `src/` 中。
2. **`scripts/` 是研究表面** — 脚本可能包含实验性代码、快速原型、一次性分析。
3. **兼容层** — `scripts/backtest_core.py` 现在是 thin compat 层，所有实现已迁移到 `src/strategies/`。
4. **无交叉依赖** — `src/` 不导入 `scripts/`。`scripts/` 可以通过兼容层导入 `src/`。
5. **QA 差异** — `src/` 运行 ruff + pytest + compileall。`scripts/` 明确不要求这些。

## 迁移状态 (Sprint 9)

- [x] `scripts/backtest_core.py` → `src/strategies/` (完整迁移)
- [ ] `scripts/utils/` → `src/` (未来 Sprint)
- [ ] 其余 60+ scripts → 研究代码标记已完成
