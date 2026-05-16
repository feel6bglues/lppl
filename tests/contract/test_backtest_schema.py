"""合约测试: 验证生产路径的关键函数输入/输出 schema（无 TDX 依赖）"""

from dataclasses import fields

import numpy as np
import pandas as pd
import pytest

from src.investment.backtest import (
    BacktestConfig,
    InvestmentSignalConfig,
    _check_trade_constraints,
    calculate_drawdown,
    run_strategy_backtest,
)


class TestBacktestConfigContract:
    def test_backtest_config_has_required_fields(self):
        field_names = {f.name for f in fields(BacktestConfig)}
        for required in ("initial_capital", "buy_fee", "sell_fee", "slippage",
                         "enable_limit_move_constraint", "max_participation_rate"):
            assert required in field_names, f"BacktestConfig missing {required}"

    def test_backtest_defaults_are_safe(self):
        cfg = BacktestConfig()
        assert cfg.buy_fee > 0
        assert cfg.sell_fee > 0
        assert cfg.slippage > 0
        assert cfg.enable_limit_move_constraint is True
        assert cfg.max_participation_rate > 0

    def test_investment_signal_config_has_required_fields(self):
        field_names = {f.name for f in fields(InvestmentSignalConfig)}
        for required in ("signal_model", "full_position", "flat_position",
                         "danger_days", "warning_days"):
            assert required in field_names, f"InvestmentSignalConfig missing {required}"


class TestBacktestExecutionContract:
    @pytest.fixture
    def sample_data(self):
        dates = pd.date_range("2020-01-01", periods=252, freq="D")
        return pd.DataFrame({
            "date": dates,
            "open": np.linspace(100, 110, 252),
            "high": np.linspace(101, 112, 252),
            "low": np.linspace(99, 108, 252),
            "close": np.linspace(100, 110, 252),
            "volume": np.full(252, 1_000_000.0),
            "target_position": [0.0] * 252,
            "action": ["hold"] * 252,
            "lppl_signal": ["none"] * 252,
            "signal_strength": [0.0] * 252,
            "position_reason": ["无信号"] * 252,
        })

    def test_run_strategy_backtest_returns_expected_types(self, sample_data):
        result_df, trades_df, summary = run_strategy_backtest(sample_data)
        assert isinstance(result_df, pd.DataFrame)
        assert isinstance(trades_df, pd.DataFrame)
        assert isinstance(summary, dict)
        assert "final_nav" in summary
        assert "total_return" in summary
        assert summary["final_nav"] == 1.0
        assert summary["trade_count"] == 0

    def test_run_strategy_backtest_buy_signal_creates_trades(self, sample_data):
        df = sample_data.copy()
        df.loc[50:, "target_position"] = 1.0
        df.loc[50:, "action"] = "buy"
        result_df, trades_df, summary = run_strategy_backtest(df)
        assert summary["trade_count"] >= 1
        assert summary["final_nav"] > 1.0

    def test_check_trade_constraints_rejects_zero_volume(self):
        class MockRow:
            volume = 0.0
            high = 101.0
            low = 99.0
            close = 100.0
        cfg = BacktestConfig(suspend_if_volume_zero=True)
        allowed, reason = _check_trade_constraints(MockRow(), cfg, "buy", 0.0)
        assert not allowed
        assert "volume_zero" in reason

    def test_calculate_drawdown(self):
        nav = pd.Series([1.0, 1.1, 1.2, 1.15, 1.25, 1.3])
        dd = calculate_drawdown(nav)
        assert isinstance(dd, pd.DataFrame)
        assert "drawdown" in dd.columns
        assert dd["drawdown"].min() <= -0.04

    def test_constant_hold_returns_no_trades(self, sample_data):
        df = sample_data.copy()
        df["target_position"] = 0.0
        df["action"] = "hold"
        _, trades_df, _ = run_strategy_backtest(df)
        assert len(trades_df) == 0
