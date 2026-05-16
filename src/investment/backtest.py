# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from src.lppl_core import calculate_bottom_signal_strength, detect_negative_bubble
from src.lppl_engine import LPPLConfig, process_single_day_ensemble, scan_single_date


@dataclass
class InvestmentSignalConfig:
    # Position sizing
    full_position: float = 1.0
    half_position: float = 0.5
    flat_position: float = 0.0
    initial_position: float = 0.0

    # LPPL signal thresholds
    strong_buy_days: int = 20
    buy_days: int = 40
    strong_sell_days: int = 20
    reduce_days: int = 60
    # NOTE: danger_days / warning_days / watch_days 与 src.lppl_engine.LPPLConfig 重复。
    # 实际风险判断已通过 lppl_config 传入，此处字段为历史遗留，仅供向后兼容。
    # 如需调整风险阈值，请修改 src.lppl_engine.LPPLConfig 中的对应字段。
    danger_days: int = 5
    watch_days: int = 25
    warning_days: int = 12
    danger_r2_offset: float = 0.0
    positive_consensus_threshold: float = 0.25
    negative_consensus_threshold: float = 0.20
    rebound_days: int = 15
    warning_trade_enabled: bool = True

    # Signal model selection
    signal_model: str = "legacy"

    # MA cross ATR v1 fields (baseline)
    trend_fast_ma: int = 20
    trend_slow_ma: int = 60
    trend_slope_window: int = 5
    atr_period: int = 14
    atr_ma_window: int = 40
    buy_volatility_cap: float = 1.05
    vol_breakout_mult: float = 1.15
    buy_confirm_days: int = 2
    sell_confirm_days: int = 2
    cooldown_days: int = 10
    full_exit_days: int = 3
    regime_filter_ma: int = 120
    regime_filter_buffer: float = 1.0
    regime_filter_reduce_enabled: bool = True
    risk_drawdown_stop_threshold: float = 0.15
    risk_drawdown_lookback: int = 120
    min_hold_bars: int = 0

    # Multi-factor adaptive strategy fields
    ma_short: int = 10
    ma_mid: int = 30
    ma_long: int = 60
    htf_ma: int = 180
    atr_low_threshold: float = 0.95
    atr_high_threshold: float = 1.15
    atr_low_percentile: float = 0.20
    atr_high_percentile: float = 0.80
    atr_percentile_window: int = 126
    bb_period: int = 20
    bb_std: float = 2.0
    bb_width_cap: float = 0.03
    bb_width_threshold: float = 0.08
    bb_narrow_threshold: float = 0.05
    bb_wide_threshold: float = 0.10
    buy_score_threshold: float = 0.3
    sell_score_threshold: float = -0.3
    reduce_score_threshold: float = -0.1
    buy_vote_threshold: int = 3
    sell_vote_threshold: int = 3
    atr_stop_mult: float = 2.5
    trend_threshold: float = 0.05
    atr_transition_low: float = 1.00
    atr_transition_high: float = 1.05
    buy_reentry_drawdown_threshold: float = 0.0
    buy_reentry_lookback: int = 0
    post_sell_reentry_cooldown_days: int = 0
    high_volatility_mult: float = 1.0
    high_volatility_position_cap: float = 1.0
    allow_top_risk_override_min_hold: bool = False
    enable_regime_hysteresis: bool = False
    require_trend_recovery_for_buy: bool = False
    first_cross_only: bool = False
    cross_persistence: int = 1
    atr_deadband: float = 0.0
    slope_threshold: float = 0.0
    atr_stop_enabled: bool = False
    trend_weight: float = 0.40
    volatility_weight: float = 0.30
    market_state_weight: float = 0.20
    momentum_weight: float = 0.10

    @classmethod
    def from_mapping(cls, symbol: str, mapping: Dict[str, Any]) -> "InvestmentSignalConfig":
        """Build a config from a resolved parameter mapping.

        Extra keys in the mapping are ignored so callers can pass the output of
        the optimal-parameter resolver directly.
        """
        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in mapping.items() if key in allowed}
        return cls(**values)


@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    buy_fee: float = 0.0003
    sell_fee: float = 0.0003
    slippage: float = 0.0005
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    execution_price: str = "open"

    # 成交约束（默认开启）
    enable_limit_move_constraint: bool = True
    max_participation_rate: float = 0.25
    suspend_if_volume_zero: bool = True


def _normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized["date"] = pd.to_datetime(normalized["date"])
    normalized = normalized.sort_values("date").reset_index(drop=True)

    if "open" not in normalized.columns:
        normalized["open"] = normalized["close"]
    if "high" not in normalized.columns:
        normalized["high"] = normalized[["open", "close"]].max(axis=1)
    if "low" not in normalized.columns:
        normalized["low"] = normalized[["open", "close"]].min(axis=1)
    if "volume" not in normalized.columns:
        normalized["volume"] = 0.0

    return normalized


def _resolve_action(previous_target: float, next_target: float) -> str:
    if next_target > previous_target:
        return "buy" if previous_target <= 0.0 else "add"
    if next_target < previous_target:
        return "sell" if next_target <= 0.0 else "reduce"
    return "hold"


def _map_single_window_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
    if not result:
        return "none", 0.0, "无信号", current_target

    params = result.get("params", ())
    b_value = float(params[4]) if len(params) > 4 else 0.0
    days_to_crash = float(result.get("days_to_crash", 9999.0))
    m_value = float(result.get("m", 0.0))
    w_value = float(result.get("w", 0.0))
    rmse = float(result.get("rmse", 1.0))
    r_squared = float(result.get("r_squared", 0.0))

    is_negative, bottom_signal = detect_negative_bubble(m_value, w_value, b_value, days_to_crash)
    if is_negative:
        bottom_strength = calculate_bottom_signal_strength(m_value, w_value, b_value, rmse)
        if days_to_crash < signal_config.strong_buy_days:
            return "negative_bubble", bottom_strength, bottom_signal, signal_config.full_position
        if days_to_crash < signal_config.buy_days:
            target = max(current_target, signal_config.half_position)
            return "negative_bubble", bottom_strength, bottom_signal, target
        return "negative_bubble_watch", bottom_strength, bottom_signal, current_target

    danger_r2 = min(1.0, max(0.0, lppl_config.r2_threshold + lppl_config.danger_r2_offset))
    if b_value <= 0 and days_to_crash < lppl_config.danger_days and r_squared >= danger_r2:
        return "bubble_risk", r_squared, "高危信号", signal_config.flat_position

    warning_threshold = max(0.0, lppl_config.r2_threshold - 0.1)
    if b_value <= 0 and days_to_crash < lppl_config.warning_days and r_squared >= warning_threshold:
        target = min(current_target, signal_config.half_position)
        return "bubble_warning", r_squared, "观察信号", target

    watch_threshold = max(0.0, lppl_config.r2_threshold - 0.2)
    if b_value <= 0 and days_to_crash < lppl_config.watch_days and r_squared >= watch_threshold:
        return "bubble_watch", r_squared, "关注信号", current_target

    return "none", 0.0, "无信号", current_target


def _map_ensemble_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
    if not result:
        return "none", 0.0, "无信号", current_target

    signal_strength = float(result.get("signal_strength", 0.0))
    positive_consensus = float(
        result.get("positive_consensus_rate", result.get("consensus_rate", 0.0))
    )
    negative_consensus = float(result.get("negative_consensus_rate", 0.0))
    positive_days = result.get("predicted_crash_days")
    negative_days = result.get("predicted_rebound_days")

    if negative_days is not None and negative_consensus > positive_consensus:
        negative_days = float(negative_days)
        if negative_days < signal_config.strong_buy_days:
            return (
                "negative_bubble",
                signal_strength,
                "Ensemble 抄底共识",
                signal_config.full_position,
            )
        if negative_days < signal_config.buy_days:
            target = max(current_target, signal_config.half_position)
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", target
        return "negative_bubble_watch", signal_strength, "Ensemble 抄底观察", current_target

    if positive_days is not None:
        positive_days = float(positive_days)
        if positive_days < lppl_config.danger_days:
            return "bubble_risk", signal_strength, "Ensemble 高危共识", signal_config.flat_position
        if positive_days < lppl_config.warning_days:
            target = min(current_target, signal_config.half_position)
            return "bubble_warning", signal_strength, "Ensemble 观察信号", target

    return "none", 0.0, "无信号", current_target


def _compute_common_indicators(
    price_df: pd.DataFrame,
    signal_config: InvestmentSignalConfig,
    is_ma_cross_atr: bool = False,
    is_ma_cross_atr_long_hold: bool = False,
    is_ma_convergence_v1: bool = False,
    is_ma_convergence_v2: bool = False,
    is_multi_factor: bool = False,
) -> None:
    fast_ma_col = (
        signal_config.trend_fast_ma
        if (is_ma_cross_atr or is_ma_cross_atr_long_hold)
        else signal_config.ma_short
    )
    slow_ma_col = (
        signal_config.trend_slow_ma
        if (is_ma_cross_atr or is_ma_cross_atr_long_hold)
        else signal_config.ma_mid
    )

    price_df["ma_fast"] = price_df["close"].rolling(fast_ma_col, min_periods=1).mean()
    price_df["ma_slow"] = price_df["close"].rolling(slow_ma_col, min_periods=1).mean()
    price_df["ma_regime"] = (
        price_df["close"].rolling(signal_config.regime_filter_ma, min_periods=1).mean()
    )
    price_df["ma_long_model"] = (
        price_df["close"].rolling(signal_config.ma_long, min_periods=1).mean()
    )

    prev_close = price_df["close"].shift(1).fillna(price_df["close"])
    true_range = pd.concat(
        [
            (price_df["high"] - price_df["low"]).abs(),
            (price_df["high"] - prev_close).abs(),
            (price_df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    price_df["atr"] = true_range.rolling(signal_config.atr_period, min_periods=1).mean()
    price_df["atr_ma"] = (
        price_df["atr"].rolling(signal_config.atr_ma_window, min_periods=1).mean()
    )
    price_df["atr_ratio"] = (price_df["atr"] / price_df["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)
    if is_ma_convergence_v1:
        min_periods = max(1, min(signal_config.atr_percentile_window, 20))
        price_df["atr_low_quantile"] = (
            price_df["atr_ratio"]
            .rolling(signal_config.atr_percentile_window, min_periods=min_periods)
            .quantile(signal_config.atr_low_percentile)
            .fillna(price_df["atr_ratio"])
        )
        price_df["atr_high_quantile"] = (
            price_df["atr_ratio"]
            .rolling(signal_config.atr_percentile_window, min_periods=min_periods)
            .quantile(signal_config.atr_high_percentile)
            .fillna(price_df["atr_ratio"])
        )

    price_df["ma_fast_prev"] = price_df["ma_fast"].shift(1)
    price_df["ma_slow_prev"] = price_df["ma_slow"].shift(1)
    price_df["bullish_cross"] = (price_df["ma_fast"] > price_df["ma_slow"]) & (
        price_df["ma_fast_prev"].fillna(price_df["ma_fast"])
        <= price_df["ma_slow_prev"].fillna(price_df["ma_slow"])
    )
    price_df["bearish_cross"] = (price_df["ma_fast"] < price_df["ma_slow"]) & (
        price_df["ma_fast_prev"].fillna(price_df["ma_fast"])
        >= price_df["ma_slow_prev"].fillna(price_df["ma_slow"])
    )

    price_df["risk_rolling_peak"] = (
        price_df["close"].rolling(signal_config.risk_drawdown_lookback, min_periods=1).max()
    )
    price_df["risk_price_drawdown"] = (price_df["close"] / price_df["risk_rolling_peak"]) - 1.0

    if is_multi_factor or is_ma_convergence_v1 or is_ma_convergence_v2:
        price_df["bb_middle"] = (
            price_df["close"].rolling(signal_config.bb_period, min_periods=1).mean()
        )
        price_df["bb_std"] = (
            price_df["close"].rolling(signal_config.bb_period, min_periods=1).std().fillna(0.0)
        )
        price_df["bb_upper"] = price_df["bb_middle"] + signal_config.bb_std * price_df["bb_std"]
        price_df["bb_lower"] = price_df["bb_middle"] - signal_config.bb_std * price_df["bb_std"]
        price_df["bb_width"] = (
            (price_df["bb_upper"] - price_df["bb_lower"])
            / price_df["bb_middle"].replace(0.0, pd.NA)
        ).fillna(0.0)


def _generate_ma_cross_atr_signals(
    price_df: pd.DataFrame,
    symbol: str,
    signal_config: InvestmentSignalConfig,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    current_target = signal_config.initial_position
    buy_confirm_count = 0
    sell_confirm_count = 0
    cooldown_remaining = 0
    holding_bars = 0
    records = []

    for row in price_df.itertuples(index=False):
        ts = row.date
        if ts < start_ts or ts > end_ts:
            continue

        close_price = float(row.close)
        bullish_cross = bool(row.bullish_cross)
        bearish_cross = bool(row.bearish_cross)
        atr_ratio = float(row.atr_ratio)
        regime_ma = float(getattr(row, "ma_regime", close_price))
        regime_ratio = close_price / regime_ma if regime_ma > 0 else 1.0
        risk_drawdown = float(row.risk_price_drawdown)

        if current_target > signal_config.flat_position + 1e-8:
            holding_bars += 1
        elif cooldown_remaining > 0:
            cooldown_remaining -= 1

        buy_candidate = (
            bullish_cross
            and atr_ratio <= signal_config.buy_volatility_cap
            and regime_ratio >= signal_config.regime_filter_buffer
        )
        sell_candidate = bearish_cross or atr_ratio > signal_config.vol_breakout_mult

        if buy_candidate:
            buy_confirm_count += 1
        else:
            buy_confirm_count = 0

        if sell_candidate:
            sell_confirm_count += 1
        else:
            sell_confirm_count = 0

        next_target = current_target
        position_reason = "无信号"

        if (
            current_target > signal_config.flat_position + 1e-8
            and signal_config.regime_filter_reduce_enabled
            and risk_drawdown <= -signal_config.risk_drawdown_stop_threshold
        ):
            next_target = signal_config.flat_position
            position_reason = "回撤止损"
        elif buy_candidate:
            next_target = signal_config.full_position
            position_reason = f"MA金叉买入(ATR={atr_ratio:.2f})"
        elif sell_candidate:
            next_target = signal_config.flat_position
            if bearish_cross:
                position_reason = f"MA死叉卖出(ATR={atr_ratio:.2f})"
            else:
                position_reason = f"ATR高波卖出(ATR={atr_ratio:.2f})"

        action = _resolve_action(current_target, next_target)
        current_target = next_target

        records.append(
            {
                "date": row.date,
                "symbol": symbol,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": close_price,
                "volume": float(row.volume),
                "lppl_signal": "none",
                "signal_strength": 0.0,
                "position_reason": position_reason,
                "action": action,
                "target_position": float(current_target),
            }
        )

    return pd.DataFrame(records)


def _generate_ma_cross_atr_long_hold_signals(
    price_df: pd.DataFrame,
    symbol: str,
    signal_config: InvestmentSignalConfig,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    current_target = signal_config.initial_position
    buy_confirm_count = 0
    sell_confirm_count = 0
    cooldown_remaining = 0
    holding_bars = 0
    records = []

    for row in price_df.itertuples(index=False):
        ts = row.date
        if ts < start_ts or ts > end_ts:
            continue

        close_price = float(row.close)
        bearish_cross = bool(row.bearish_cross)
        atr_ratio = float(row.atr_ratio)
        regime_ma = float(getattr(row, "ma_regime", close_price))
        regime_ratio = close_price / regime_ma if regime_ma > 0 else 1.0
        risk_drawdown = float(row.risk_price_drawdown)

        if current_target > signal_config.flat_position + 1e-8:
            holding_bars += 1
        elif cooldown_remaining > 0:
            cooldown_remaining -= 1

        long_hold_buy_setup = (
            float(row.ma_fast) > float(row.ma_slow)
            and atr_ratio <= signal_config.buy_volatility_cap
            and regime_ratio >= signal_config.regime_filter_buffer
        )
        long_hold_sell_setup = (
            float(row.ma_fast) < float(row.ma_slow)
            or atr_ratio > signal_config.vol_breakout_mult
        )

        if long_hold_buy_setup:
            buy_confirm_count += 1
        else:
            buy_confirm_count = 0

        if long_hold_sell_setup:
            sell_confirm_count += 1
        else:
            sell_confirm_count = 0

        previous_target = current_target
        next_target = current_target
        position_reason = "无信号"

        if (
            current_target > signal_config.flat_position + 1e-8
            and signal_config.regime_filter_reduce_enabled
            and risk_drawdown <= -signal_config.risk_drawdown_stop_threshold
        ):
            next_target = signal_config.flat_position
            position_reason = "回撤止损"
        else:
            can_buy = (
                current_target <= signal_config.flat_position + 1e-8
                and cooldown_remaining <= 0
                and buy_confirm_count >= max(1, signal_config.buy_confirm_days)
            )
            can_sell = (
                current_target > signal_config.flat_position + 1e-8
                and sell_confirm_count >= max(1, signal_config.sell_confirm_days)
                and holding_bars >= int(signal_config.min_hold_bars)
            )

            if can_buy:
                next_target = signal_config.full_position
                position_reason = (
                    f"长持仓买入(确认={buy_confirm_count},ATR={atr_ratio:.2f},"
                    f"冷却={cooldown_remaining})"
                )
            elif (
                current_target > signal_config.flat_position + 1e-8
                and sell_confirm_count >= max(1, signal_config.sell_confirm_days)
                and holding_bars < int(signal_config.min_hold_bars)
            ):
                next_target = current_target
                position_reason = f"持仓不足{int(signal_config.min_hold_bars)}天,暂缓卖出"
            elif can_sell:
                next_target = signal_config.flat_position
                if bearish_cross:
                    position_reason = f"长持仓MA死叉卖出(ATR={atr_ratio:.2f})"
                else:
                    position_reason = f"长持仓ATR高波卖出(ATR={atr_ratio:.2f})"
            else:
                next_target = current_target
                if (
                    current_target <= signal_config.flat_position + 1e-8
                    and cooldown_remaining > 0
                ):
                    position_reason = f"冷却中({cooldown_remaining}天)"
                else:
                    position_reason = f"长持仓持有(ATR={atr_ratio:.2f},持仓={holding_bars}天)"

        action = _resolve_action(current_target, next_target)
        current_target = next_target

        if (
            previous_target <= signal_config.flat_position + 1e-8
            and current_target > signal_config.flat_position + 1e-8
        ):
            holding_bars = 0
            buy_confirm_count = 0
        elif (
            previous_target > signal_config.flat_position + 1e-8
            and current_target <= signal_config.flat_position + 1e-8
        ):
            holding_bars = 0
            sell_confirm_count = 0
            cooldown_remaining = int(signal_config.cooldown_days)

        records.append(
            {
                "date": row.date,
                "symbol": symbol,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": close_price,
                "volume": float(row.volume),
                "lppl_signal": "none",
                "signal_strength": 0.0,
                "position_reason": position_reason,
                "action": action,
                "target_position": float(current_target),
            }
        )

    return pd.DataFrame(records)


def _generate_ma_convergence_signals(
    price_df: pd.DataFrame,
    symbol: str,
    signal_config: InvestmentSignalConfig,
    is_v2: bool,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    current_target = signal_config.initial_position
    buy_confirm_count = 0
    sell_confirm_count = 0
    cooldown_remaining = 0
    holding_bars = 0
    records = []

    for row in price_df.itertuples(index=False):
        ts = row.date
        if ts < start_ts or ts > end_ts:
            continue

        close_price = float(row.close)
        atr_ratio = float(row.atr_ratio)
        regime_ma = float(getattr(row, "ma_regime", close_price))
        regime_ratio = close_price / regime_ma if regime_ma > 0 else 1.0
        risk_drawdown = float(row.risk_price_drawdown)
        ma_fast = float(row.ma_fast)
        ma_slow = float(row.ma_slow)
        ma_long_model = float(getattr(row, "ma_long_model", close_price))
        bb_width = float(row.bb_width)
        bullish_cross = bool(row.bullish_cross)
        bearish_cross = bool(row.bearish_cross)

        if current_target > signal_config.flat_position + 1e-8:
            holding_bars += 1
        elif cooldown_remaining > 0:
            cooldown_remaining -= 1

        if is_v2:
            buy_setup = (
                bullish_cross
                and regime_ratio >= signal_config.regime_filter_buffer
                and (
                    atr_ratio < signal_config.atr_low_threshold
                    or bb_width < signal_config.bb_width_threshold
                )
            )
            sell_setup = (
                bearish_cross
                or (
                    regime_ratio < signal_config.regime_filter_buffer
                    and risk_drawdown <= -signal_config.risk_drawdown_stop_threshold
                )
                or atr_ratio > signal_config.atr_high_threshold
            )
        else:
            atr_low_q = float(getattr(row, "atr_low_quantile", atr_ratio))
            atr_high_q = float(getattr(row, "atr_high_quantile", atr_ratio))
            buy_setup = (
                bb_width <= signal_config.bb_width_cap
                and atr_ratio <= atr_low_q
                and (
                    close_price > float(getattr(row, "bb_upper", close_price))
                    or (ma_fast > ma_slow > ma_long_model)
                )
            )
            sell_setup = (
                bb_width <= signal_config.bb_width_cap
                and atr_ratio >= atr_high_q
                and (bearish_cross or regime_ratio < signal_config.regime_filter_buffer)
            )

        buy_confirm_count = buy_confirm_count + 1 if buy_setup else 0
        sell_confirm_count = sell_confirm_count + 1 if sell_setup else 0
        previous_target = current_target
        next_target = current_target
        position_reason = "无信号"

        if (
            current_target > signal_config.flat_position + 1e-8
            and signal_config.regime_filter_reduce_enabled
            and risk_drawdown <= -signal_config.risk_drawdown_stop_threshold
        ):
            next_target = signal_config.flat_position
            position_reason = "回撤止损"
        elif (
            current_target <= signal_config.flat_position + 1e-8
            and cooldown_remaining <= 0
            and buy_confirm_count >= max(1, signal_config.buy_confirm_days)
        ):
            next_target = signal_config.full_position
            position_reason = "收敛策略买入"
        elif (
            current_target > signal_config.flat_position + 1e-8
            and sell_confirm_count >= max(1, signal_config.sell_confirm_days)
            and holding_bars >= int(signal_config.min_hold_bars)
        ):
            next_target = signal_config.flat_position
            position_reason = "收敛策略卖出"
        else:
            next_target = current_target
            if current_target <= signal_config.flat_position + 1e-8 and cooldown_remaining > 0:
                position_reason = f"冷却中({cooldown_remaining}天)"
            else:
                position_reason = "收敛策略持有"

        action = _resolve_action(current_target, next_target)
        current_target = next_target
        if (
            previous_target <= signal_config.flat_position + 1e-8
            and current_target > signal_config.flat_position + 1e-8
        ):
            holding_bars = 0
            buy_confirm_count = 0
        elif (
            previous_target > signal_config.flat_position + 1e-8
            and current_target <= signal_config.flat_position + 1e-8
        ):
            holding_bars = 0
            sell_confirm_count = 0
            cooldown_remaining = int(signal_config.cooldown_days)

        records.append(
            {
                "date": row.date,
                "symbol": symbol,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": close_price,
                "volume": float(row.volume),
                "lppl_signal": "none",
                "signal_strength": 0.0,
                "position_reason": position_reason,
                "action": action,
                "target_position": float(current_target),
            }
        )

    return pd.DataFrame(records)


def _generate_multifactor_signals(
    price_df: pd.DataFrame,
    symbol: str,
    signal_config: InvestmentSignalConfig,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    current_target = signal_config.initial_position
    records = []

    for row in price_df.itertuples(index=False):
        ts = row.date
        if ts < start_ts or ts > end_ts:
            continue

        close_price = float(row.close)
        bullish_cross = bool(row.bullish_cross)
        bearish_cross = bool(row.bearish_cross)
        atr_ratio = float(row.atr_ratio)
        regime_ma = float(getattr(row, "ma_regime", close_price))
        regime_ratio = close_price / regime_ma if regime_ma > 0 else 1.0
        bb_width = float(getattr(row, "bb_width", 0.10))

        trend_score = 0.0
        if bullish_cross:
            trend_score = 1.0
        elif bearish_cross:
            trend_score = -1.0
        if regime_ratio >= 1.02:
            trend_score += 0.5
        elif regime_ratio <= 0.98:
            trend_score -= 0.5

        vol_score = 0.0
        if atr_ratio < signal_config.atr_low_threshold:
            vol_score = 1.0
        elif atr_ratio > signal_config.atr_high_threshold:
            vol_score = -1.0

        state_score = 0.0
        if bb_width < signal_config.bb_narrow_threshold:
            state_score = 0.5
        elif bb_width > signal_config.bb_wide_threshold:
            state_score = -0.5

        ma_fast = float(row.ma_fast)
        ma_slow = float(row.ma_slow)
        momentum_score = 0.5 if ma_fast > ma_slow else -0.5

        total_score = (
            trend_score * signal_config.trend_weight
            + vol_score * signal_config.volatility_weight
            + state_score * signal_config.market_state_weight
            + momentum_score * signal_config.momentum_weight
        )

        risk_drawdown = float(row.risk_price_drawdown)

        vol_position_cap = float(signal_config.full_position)
        if atr_ratio > signal_config.atr_high_threshold:
            vol_position_cap = 0.5
        elif atr_ratio > 1.05:
            vol_position_cap = 0.7

        next_target = current_target
        position_reason = "无信号"

        if (
            current_target > signal_config.flat_position + 1e-8
            and signal_config.regime_filter_reduce_enabled
            and risk_drawdown <= -signal_config.risk_drawdown_stop_threshold
        ):
            next_target = signal_config.flat_position
            position_reason = f"回撤止损(评分={total_score:.2f})"
        elif total_score >= signal_config.buy_score_threshold and trend_score > 0:
            next_target = min(signal_config.full_position, vol_position_cap)
            position_reason = f"多因子买入(评分={total_score:.2f})"
        elif total_score <= signal_config.sell_score_threshold and trend_score < 0:
            next_target = signal_config.flat_position
            position_reason = f"多因子卖出(评分={total_score:.2f})"
        elif (
            total_score < 0
            and total_score > signal_config.sell_score_threshold
            and current_target > signal_config.flat_position + 1e-8
        ):
            next_target = signal_config.half_position
            position_reason = f"多因子减仓(评分={total_score:.2f})"
        else:
            position_reason = f"多因子持有(评分={total_score:.2f})"

        action = _resolve_action(current_target, next_target)
        current_target = next_target

        records.append(
            {
                "date": row.date,
                "symbol": symbol,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": close_price,
                "volume": float(row.volume),
                "lppl_signal": "none",
                "signal_strength": 0.0,
                "position_reason": position_reason,
                "action": action,
                "target_position": float(current_target),
            }
        )

    return pd.DataFrame(records)


def _generate_legacy_signals(
    price_df: pd.DataFrame,
    symbol: str,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    scan_step: int,
    close_prices: np.ndarray,
    warmup: int,
    use_ensemble: bool,
) -> pd.DataFrame:
    current_target = signal_config.initial_position
    scan_counter = 0
    records = []

    for idx, row in enumerate(price_df.itertuples(index=False)):
        ts = row.date
        if ts < start_ts or ts > end_ts:
            continue

        lppl_signal = "none"
        signal_strength = 0.0
        position_reason = "无信号"
        next_target = current_target
        close_price = float(row.close)

        if idx >= warmup and scan_counter % scan_step == 0:
            if use_ensemble:
                result = process_single_day_ensemble(
                    close_prices,
                    idx,
                    lppl_config.window_range,
                    min_r2=lppl_config.r2_threshold,
                    consensus_threshold=lppl_config.consensus_threshold,
                    config=lppl_config,
                )
                lppl_signal, signal_strength, position_reason, next_target = (
                    _map_ensemble_signal(
                        result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
                )
            else:
                result = scan_single_date(
                    close_prices, idx, lppl_config.window_range, lppl_config
                )
                lppl_signal, signal_strength, position_reason, next_target = (
                    _map_single_window_signal(
                        result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
                )
        if not signal_config.warning_trade_enabled and lppl_signal in (
            "bubble_warning",
            "bubble_watch",
        ):
            next_target = current_target
            if lppl_signal == "bubble_warning":
                position_reason = "观察信号不交易"
            elif lppl_signal == "bubble_watch":
                position_reason = "关注信号不交易"

        if idx >= warmup:
            scan_counter += 1

        action = _resolve_action(current_target, next_target)
        current_target = next_target

        records.append(
            {
                "date": row.date,
                "symbol": symbol,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": close_price,
                "volume": float(row.volume),
                "lppl_signal": lppl_signal,
                "signal_strength": float(signal_strength),
                "position_reason": position_reason,
                "action": action,
                "target_position": float(current_target),
            }
        )

    return pd.DataFrame(records)


def generate_investment_signals(
    df: pd.DataFrame,
    symbol: str,
    signal_config: Optional[InvestmentSignalConfig] = None,
    lppl_config: Optional[LPPLConfig] = None,
    use_ensemble: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scan_step: int = 1,
) -> pd.DataFrame:
    signal_config = signal_config or InvestmentSignalConfig()
    lppl_config = lppl_config or LPPLConfig(window_range=[40, 60, 80], n_workers=1)
    price_df = _normalize_price_frame(df)
    scan_step = max(1, int(scan_step))

    start_ts = pd.to_datetime(start_date) if start_date else price_df["date"].min()
    end_ts = pd.to_datetime(end_date) if end_date else price_df["date"].max()

    close_prices = price_df["close"].values
    warmup = max(lppl_config.window_range)

    is_ma_cross_atr = signal_config.signal_model == "ma_cross_atr_v1"
    is_ma_cross_atr_long_hold = signal_config.signal_model == "ma_cross_atr_long_hold_v1"
    is_ma_convergence_v1 = signal_config.signal_model == "ma_convergence_atr_v1"
    is_ma_convergence_v2 = signal_config.signal_model == "ma_convergence_atr_v2"
    is_multi_factor = signal_config.signal_model == "multi_factor_adaptive_v1"

    if (
        is_ma_cross_atr
        or is_ma_cross_atr_long_hold
        or is_ma_convergence_v1
        or is_ma_convergence_v2
        or is_multi_factor
    ):
        _compute_common_indicators(
            price_df, signal_config, is_ma_cross_atr, is_ma_cross_atr_long_hold,
            is_ma_convergence_v1, is_ma_convergence_v2, is_multi_factor,
        )

    if is_ma_cross_atr:
        return _generate_ma_cross_atr_signals(price_df, symbol, signal_config, start_ts, end_ts)
    if is_ma_cross_atr_long_hold:
        return _generate_ma_cross_atr_long_hold_signals(price_df, symbol, signal_config, start_ts, end_ts)
    if is_ma_convergence_v1:
        return _generate_ma_convergence_signals(price_df, symbol, signal_config, False, start_ts, end_ts)
    if is_ma_convergence_v2:
        return _generate_ma_convergence_signals(price_df, symbol, signal_config, True, start_ts, end_ts)
    if is_multi_factor:
        return _generate_multifactor_signals(price_df, symbol, signal_config, start_ts, end_ts)

    return _generate_legacy_signals(price_df, symbol, signal_config, lppl_config, start_ts, end_ts, scan_step, close_prices, warmup, use_ensemble)


def calculate_drawdown(nav_series: pd.Series) -> pd.DataFrame:
    nav = pd.Series(nav_series, copy=True).astype(float).reset_index(drop=True)
    running_max = nav.cummax()
    drawdown = (nav / running_max) - 1.0
    return pd.DataFrame(
        {
            "strategy_nav": nav,
            "running_max": running_max,
            "drawdown": drawdown,
        }
    )


def _annualized_turnover_rate(
    trades_df: pd.DataFrame,
    initial_capital: float,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> tuple[float, float]:
    if trades_df.empty or initial_capital <= 0:
        return 0.0, 0.0
    notional = float((trades_df["price"].astype(float) * trades_df["units"].astype(float)).sum())
    cumulative_turnover = notional / initial_capital
    years = max((end_ts - start_ts).days / 365.25, 1 / 365.25)
    return cumulative_turnover, cumulative_turnover / years


def _whipsaw_rate(trades_df: pd.DataFrame) -> float:
    if trades_df.empty or len(trades_df) < 2:
        return 0.0

    pair_count = len(trades_df) // 2
    if pair_count <= 0:
        return 0.0

    dates = pd.to_datetime(trades_df["date"])
    entry_dates = dates.iloc[0 : pair_count * 2 : 2].reset_index(drop=True)
    exit_dates = dates.iloc[1 : pair_count * 2 : 2].reset_index(drop=True)
    hold_days = (exit_dates - entry_dates).dt.days
    return float((hold_days <= 20).mean())


def summarize_strategy_performance(
    equity_df: pd.DataFrame, trades_df: pd.DataFrame
) -> Dict[str, Any]:
    if equity_df.empty:
        return {
            "final_nav": 1.0,
            "total_return": 0.0,
            "benchmark_return": 0.0,
            "annualized_return": 0.0,
            "annualized_benchmark": 0.0,
            "annualized_excess_return": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
            "signal_count": 0,
            "average_position": 0.0,
            "turnover_rate": 0.0,
            "annualized_turnover_rate": 0.0,
            "whipsaw_rate": 0.0,
            "latest_action": "hold",
            "latest_signal": "none",
        }

    final_nav = float(equity_df["strategy_nav"].iloc[-1])
    total_return = final_nav - 1.0
    benchmark_return = float(equity_df["benchmark_nav"].iloc[-1] - 1.0)
    periods = max(len(equity_df), 1)
    annualized_return = (final_nav ** (252.0 / periods) - 1.0) if final_nav > 0 else -1.0
    max_drawdown = float(equity_df["drawdown"].min())
    signal_count = int((equity_df["action"] != "hold").sum())
    annualized_benchmark = (
        ((1.0 + benchmark_return) ** (252.0 / periods) - 1.0) if benchmark_return > -1.0 else -1.0
    )
    annualized_excess_return = annualized_return - annualized_benchmark
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown < 0 else annualized_return
    start_ts = pd.to_datetime(equity_df["date"].iloc[0])
    end_ts = pd.to_datetime(equity_df["date"].iloc[-1])
    initial_capital = float(equity_df["portfolio_value"].iloc[0])
    turnover_rate, annualized_turnover_rate = _annualized_turnover_rate(
        trades_df, initial_capital, start_ts, end_ts
    )
    whipsaw_rate = _whipsaw_rate(trades_df)

    return {
        "final_nav": final_nav,
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "annualized_return": annualized_return,
        "annualized_benchmark": annualized_benchmark,
        "annualized_excess_return": annualized_excess_return,
        "calmar_ratio": calmar_ratio,
        "max_drawdown": max_drawdown,
        "trade_count": int(len(trades_df)),
        "signal_count": signal_count,
        "average_position": float(equity_df["executed_position"].mean()),
        "turnover_rate": turnover_rate,
        "annualized_turnover_rate": annualized_turnover_rate,
        "whipsaw_rate": whipsaw_rate,
        "latest_action": str(equity_df["action"].iloc[-1]),
        "latest_signal": str(equity_df["lppl_signal"].iloc[-1]),
    }


def _check_trade_constraints(
    row: Any,
    backtest_config: BacktestConfig,
    trade_type: str,
    current_units: float,
) -> Tuple[bool, str]:
    """
    检查成交约束，返回 (允许交易, 拒绝原因)

    NOTE: 当前未被 run_strategy_backtest 使用（该函数使用 _check_trade_constraints_df）。
    保留此接口以供外部直接调用。
    """
    if (
        not backtest_config.enable_limit_move_constraint
        and not backtest_config.suspend_if_volume_zero
    ):
        return True, ""

    volume = float(getattr(row, "volume", 0))
    high = float(getattr(row, "high", 0))
    low = float(getattr(row, "low", 0))
    close = float(getattr(row, "close", 0))
    prev_close = float(getattr(row, "prev_close", 0))
    if prev_close <= 0:
        prev_close = close
    price_range = high - low if high > low else close * 0.01

    if backtest_config.suspend_if_volume_zero and volume <= 0:
        return False, "volume_zero"

    if backtest_config.enable_limit_move_constraint:
        pct_change = (close - prev_close) / prev_close if prev_close > 0 else 0
        is_limit_up = pct_change > 0.095
        is_limit_down = pct_change < -0.095

        if trade_type in ("buy", "add") and is_limit_up:
            return False, "limit_up_cannot_buy"
        if trade_type in ("sell", "reduce") and is_limit_down:
            return False, "limit_down_cannot_sell"

        participation = volume * price_range
        max_allowed = backtest_config.max_participation_rate * participation
        if max_allowed <= 0:
            return False, "insufficient_liquidity"

    return True, ""


def _check_trade_constraints_df(
    df: pd.DataFrame,
    row_idx: int,
    backtest_config: BacktestConfig,
    trade_type: str,
    current_units: float,
) -> Tuple[bool, str, float]:
    """从 DataFrame 检查成交约束，返回 (allowed, reason, max_allowed)

    max_allowed 为 0 表示无参与率限制（约束未启用）。"""
    if (
        not backtest_config.enable_limit_move_constraint
        and not backtest_config.suspend_if_volume_zero
    ):
        return True, "", 0.0
    row = df.iloc[row_idx]
    volume = float(row["volume"]) if "volume" in df.columns else 0
    high = float(row["high"]) if "high" in df.columns else 0
    low = float(row["low"]) if "low" in df.columns else 0
    close = float(row["close"]) if "close" in df.columns else 0
    if "prev_close" in df.columns:
        prev_close = float(row["prev_close"])
    elif row_idx > 0 and "close" in df.columns:
        prev_close = float(df.iloc[row_idx - 1]["close"])
    else:
        prev_close = close

    if backtest_config.suspend_if_volume_zero and volume <= 0:
        return False, "volume_zero", 0.0

    if backtest_config.enable_limit_move_constraint:
        pct_change = (close - prev_close) / prev_close if prev_close > 0 else 0
        is_limit_up = pct_change > 0.095
        is_limit_down = pct_change < -0.095

        if trade_type in ("buy", "add") and is_limit_up:
            return False, "limit_up_cannot_buy", 0.0
        if trade_type in ("sell", "reduce") and is_limit_down:
            return False, "limit_down_cannot_sell", 0.0

        price_range = high - low if high > low else close * 0.01
        participation = volume * price_range
        if participation > 0:
            max_allowed = backtest_config.max_participation_rate * participation
            if max_allowed <= 0:
                return False, "insufficient_liquidity", 0.0
            return True, "", max_allowed

    return True, "", 0.0


def run_strategy_backtest(
    signal_df: pd.DataFrame,
    backtest_config: Optional[BacktestConfig] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    backtest_config = backtest_config or BacktestConfig()
    equity_df = _normalize_price_frame(signal_df)

    # t+1 执行: 将信号向后偏移一个交易日
    # 当前 bar 的信号基于截至昨日的数据生成, 在下个 bar 的开盘执行
    if "target_position" in equity_df.columns:
        equity_df["target_position"] = equity_df["target_position"].shift(1).fillna(0.0)

    if backtest_config.start_date:
        equity_df = equity_df[equity_df["date"] >= pd.to_datetime(backtest_config.start_date)]
    if backtest_config.end_date:
        equity_df = equity_df[equity_df["date"] <= pd.to_datetime(backtest_config.end_date)]
    equity_df = equity_df.reset_index(drop=True)

    if equity_df.empty:
        raise ValueError("No data available for the requested backtest window")

    cash = float(backtest_config.initial_capital)
    units = 0.0
    prev_value = float(backtest_config.initial_capital)
    prev_close = float(equity_df.iloc[0]["close"])
    first_close = float(equity_df.iloc[0]["close"])

    trades = []
    records = []

    row_fields = list(equity_df.columns)
    for row_idx, row in enumerate(equity_df.itertuples(index=False, name="BacktestRow")):
        execution_base_price = float(
            row.open if backtest_config.execution_price == "open" else row.close
        )
        execution_buy_price = execution_base_price * (1.0 + backtest_config.slippage)
        execution_sell_price = execution_base_price * (1.0 - backtest_config.slippage)
        target_position = float(getattr(row, "target_position", 0.0))

        portfolio_value_before_trade = cash + units * execution_base_price
        current_holdings_value = units * execution_base_price
        desired_holdings_value = portfolio_value_before_trade * target_position

        trade_type = "hold"
        trade_rejected_reason = ""

        if desired_holdings_value > current_holdings_value + 1e-8:
            buy_allowed, buy_reason, max_allowed = _check_trade_constraints_df(
                equity_df,
                row_idx,
                backtest_config,
                "buy",
                units,
            )
            if not buy_allowed:
                trade_type = "hold"
                trade_rejected_reason = buy_reason
            else:
                trade_value = desired_holdings_value - current_holdings_value
                affordable_units = cash / (execution_buy_price * (1.0 + backtest_config.buy_fee))
                desired_units = trade_value / execution_buy_price
                units_to_buy = min(affordable_units, desired_units)
                order_value = units_to_buy * execution_buy_price
                if max_allowed > 0 and order_value > max_allowed:
                    units_to_buy = int(max_allowed / execution_buy_price / 100) * 100
                    order_value = units_to_buy * execution_buy_price
                if units_to_buy > 1e-8:
                    gross_cost = units_to_buy * execution_buy_price
                    fee = gross_cost * backtest_config.buy_fee
                    cash -= gross_cost + fee
                    units += units_to_buy
                    trade_type = "buy" if current_holdings_value <= 1e-8 else "add"
                    trades.append(
                        {
                            "date": row.date,
                            "symbol": getattr(row, "symbol", ""),
                            "trade_type": trade_type,
                            "price": execution_buy_price,
                            "target_position": target_position,
                            "executed_position": 0.0,
                            "units": units_to_buy,
                            "cash_after_trade": cash,
                            "portfolio_value_after_trade": cash + units * execution_base_price,
                        }
                    )
        elif desired_holdings_value < current_holdings_value - 1e-8:
            sell_allowed, sell_reason, max_allowed = _check_trade_constraints_df(
                equity_df,
                row_idx,
                backtest_config,
                "sell",
                units,
            )
            if not sell_allowed:
                trade_type = "hold"
                trade_rejected_reason = sell_reason
            else:
                trade_value = current_holdings_value - desired_holdings_value
                units_to_sell = min(units, trade_value / execution_sell_price)
                order_value = units_to_sell * execution_sell_price
                if max_allowed > 0 and order_value > max_allowed:
                    units_to_sell = int(max_allowed / execution_sell_price / 100) * 100
                    order_value = units_to_sell * execution_sell_price
                if units_to_sell > 1e-8:
                    gross_proceeds = units_to_sell * execution_sell_price
                    fee = gross_proceeds * backtest_config.sell_fee
                    cash += gross_proceeds - fee
                    units -= units_to_sell
                    trade_type = "sell" if target_position <= 1e-8 else "reduce"
                    trades.append(
                        {
                            "date": row.date,
                            "symbol": getattr(row, "symbol", ""),
                            "trade_type": trade_type,
                            "price": execution_sell_price,
                            "target_position": target_position,
                            "executed_position": 0.0,
                            "units": units_to_sell,
                            "cash_after_trade": cash,
                            "portfolio_value_after_trade": cash + units * execution_base_price,
                        }
                    )

        holdings_value = units * float(row.close)
        portfolio_value = cash + holdings_value
        strategy_nav = portfolio_value / backtest_config.initial_capital
        benchmark_nav = float(row.close) / first_close
        daily_return = 0.0 if not records else (portfolio_value / prev_value) - 1.0
        benchmark_return = 0.0 if not records else (float(row.close) / prev_close) - 1.0
        executed_position = (holdings_value / portfolio_value) if portfolio_value > 0 else 0.0

        if trades and pd.Timestamp(trades[-1]["date"]) == pd.Timestamp(row.date):
            trades[-1]["executed_position"] = executed_position

        row_dict = dict(zip(row_fields, row))
        records.append(
            {
                **row_dict,
                "executed_position": executed_position,
                "cash": cash,
                "units": units,
                "holdings_value": holdings_value,
                "portfolio_value": portfolio_value,
                "strategy_nav": strategy_nav,
                "benchmark_nav": benchmark_nav,
                "daily_return": daily_return,
                "benchmark_return": benchmark_return,
                "excess_return": daily_return - benchmark_return,
                "trade_flag": trade_type != "hold",
                "trade_rejected_reason": trade_rejected_reason if trade_rejected_reason else "",
            }
        )

        prev_value = portfolio_value
        prev_close = float(row.close)

    result_df = pd.DataFrame(records)
    drawdown_df = calculate_drawdown(result_df["strategy_nav"])
    result_df["running_max"] = drawdown_df["running_max"]
    result_df["drawdown"] = drawdown_df["drawdown"]

    trades_df = pd.DataFrame(trades)
    summary = summarize_strategy_performance(result_df, trades_df)
    summary["start_date"] = result_df.iloc[0]["date"].strftime("%Y-%m-%d")
    summary["end_date"] = result_df.iloc[-1]["date"].strftime("%Y-%m-%d")
    summary["symbol"] = str(result_df.iloc[0].get("symbol", ""))

    return result_df, trades_df, summary
