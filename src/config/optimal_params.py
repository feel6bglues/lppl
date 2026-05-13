# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - guarded by runtime dependency
    yaml = None


ALLOWED_KEYS = {
    "step",
    "window_set",
    "window_range",
    "r2_threshold",
    "danger_r2_offset",
    "consensus_threshold",
    "danger_days",
    "warning_days",
    "watch_days",
    "warning_trade_enabled",
    "full_exit_days",
    "optimizer",
    "lookahead_days",
    "drop_threshold",
    "ma_window",
    "max_peaks",
    "signal_model",
    "initial_position",
    "positive_consensus_threshold",
    "negative_consensus_threshold",
    "rebound_days",
    "trend_fast_ma",
    "trend_slow_ma",
    "trend_slope_window",
    "atr_period",
    "atr_ma_window",
    "vol_breakout_mult",
    "buy_volatility_cap",
    "high_volatility_mult",
    "high_volatility_position_cap",
    "drawdown_confirm_threshold",
    "buy_reentry_drawdown_threshold",
    "buy_reentry_lookback",
    "buy_trend_slow_buffer",
    "regime_filter_ma",
    "regime_filter_buffer",
    "regime_filter_reduce_enabled",
    "risk_drawdown_stop_threshold",
    "risk_drawdown_lookback",
    "buy_vote_threshold",
    "sell_vote_threshold",
    "buy_confirm_days",
    "sell_confirm_days",
    "cooldown_days",
    "post_sell_reentry_cooldown_days",
    "min_hold_bars",
    "allow_top_risk_override_min_hold",
    "enable_regime_hysteresis",
    "require_trend_recovery_for_buy",
}


def _as_positive_int(value: Any, key: str, warnings: List[str], fallback: int) -> int:
    try:
        v = int(value)
        if v <= 0:
            raise ValueError
        return v
    except Exception:
        warnings.append(f"{key}={value} 非法，回退默认值 {fallback}")
        return fallback


def _as_unit_float(value: Any, key: str, warnings: List[str], fallback: float) -> float:
    try:
        v = float(value)
        if not (0.0 <= v <= 1.0):
            raise ValueError
        return v
    except Exception:
        warnings.append(f"{key}={value} 非法，回退默认值 {fallback}")
        return fallback


def _as_float(value: Any, key: str, warnings: List[str], fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        warnings.append(f"{key}={value} 非法，回退默认值 {fallback}")
        return fallback


def _as_non_negative_float(value: Any, key: str, warnings: List[str], fallback: float) -> float:
    try:
        v = float(value)
        if v < 0.0:
            raise ValueError
        return v
    except Exception:
        warnings.append(f"{key}={value} 非法，回退默认值 {fallback}")
        return fallback


def _as_bool(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def load_optimal_config(path: str) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML 未安装，无法加载 YAML 配置")

    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"最优参数配置不存在: {path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("最优参数配置格式错误：根节点必须是字典")

    data.setdefault("defaults", {})
    data.setdefault("window_sets", {})
    data.setdefault("symbols", {})
    return data


def resolve_symbol_params(
    config_data: Dict[str, Any],
    symbol: str,
    fallback: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []

    defaults = config_data.get("defaults", {}) or {}
    symbols = config_data.get("symbols", {}) or {}
    window_sets = config_data.get("window_sets", {}) or {}

    symbol_cfg = symbols.get(symbol)
    if symbol_cfg is None:
        resolved = dict(fallback)
        resolved["param_source"] = "default_fallback"
        warnings.append(f"{symbol} 未在最优参数配置中定义，使用默认参数")
        return resolved, warnings

    resolved = dict(fallback)
    for source in (defaults, symbol_cfg):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if key in ALLOWED_KEYS:
                resolved[key] = value

    if "window_set" in resolved:
        name = resolved["window_set"]
        if name in window_sets:
            resolved["window_range"] = list(window_sets[name])
        else:
            warnings.append(f"{symbol} 配置的 window_set={name} 未定义，回退默认窗口")
            resolved["window_set"] = "default_fallback"
            resolved["window_range"] = list(fallback["window_range"])
    elif "window_range" in resolved and isinstance(resolved["window_range"], list):
        resolved["window_range"] = [int(x) for x in resolved["window_range"]]
    else:
        resolved["window_set"] = "default_fallback"
        resolved["window_range"] = list(fallback["window_range"])

    resolved["step"] = _as_positive_int(
        resolved.get("step", fallback["step"]), "step", warnings, int(fallback["step"])
    )
    resolved["danger_days"] = _as_positive_int(
        resolved.get("danger_days", fallback["danger_days"]),
        "danger_days",
        warnings,
        int(fallback["danger_days"]),
    )
    resolved["warning_days"] = _as_positive_int(
        resolved.get("warning_days", fallback["warning_days"]),
        "warning_days",
        warnings,
        int(fallback["warning_days"]),
    )
    resolved["watch_days"] = _as_positive_int(
        resolved.get("watch_days", fallback.get("watch_days", resolved["warning_days"])),
        "watch_days",
        warnings,
        int(fallback.get("watch_days", resolved["warning_days"])),
    )
    resolved["warning_days"] = max(resolved["danger_days"] + 1, resolved["warning_days"])
    resolved["watch_days"] = max(resolved["warning_days"] + 1, resolved["watch_days"])
    resolved["lookahead_days"] = _as_positive_int(
        resolved.get("lookahead_days", fallback["lookahead_days"]),
        "lookahead_days",
        warnings,
        int(fallback["lookahead_days"]),
    )
    resolved["ma_window"] = _as_positive_int(
        resolved.get("ma_window", fallback["ma_window"]),
        "ma_window",
        warnings,
        int(fallback["ma_window"]),
    )
    resolved["max_peaks"] = _as_positive_int(
        resolved.get("max_peaks", fallback["max_peaks"]),
        "max_peaks",
        warnings,
        int(fallback["max_peaks"]),
    )
    resolved["r2_threshold"] = _as_unit_float(
        resolved.get("r2_threshold", fallback["r2_threshold"]),
        "r2_threshold",
        warnings,
        float(fallback["r2_threshold"]),
    )
    resolved["danger_r2_offset"] = _as_float(
        resolved.get("danger_r2_offset", fallback.get("danger_r2_offset", 0.0)),
        "danger_r2_offset",
        warnings,
        float(fallback.get("danger_r2_offset", 0.0)),
    )
    resolved["consensus_threshold"] = _as_unit_float(
        resolved.get("consensus_threshold", fallback["consensus_threshold"]),
        "consensus_threshold",
        warnings,
        float(fallback["consensus_threshold"]),
    )
    resolved["drop_threshold"] = _as_unit_float(
        resolved.get("drop_threshold", fallback["drop_threshold"]),
        "drop_threshold",
        warnings,
        float(fallback["drop_threshold"]),
    )
    resolved["optimizer"] = str(resolved.get("optimizer", fallback["optimizer"]))
    resolved["signal_model"] = str(
        resolved.get("signal_model", fallback.get("signal_model", "multi_factor_v1"))
    )
    resolved["initial_position"] = _as_unit_float(
        resolved.get("initial_position", fallback.get("initial_position", 0.0)),
        "initial_position",
        warnings,
        float(fallback.get("initial_position", 0.0)),
    )
    resolved["positive_consensus_threshold"] = _as_unit_float(
        resolved.get(
            "positive_consensus_threshold",
            resolved.get("consensus_threshold", fallback.get("consensus_threshold", 0.25)),
        ),
        "positive_consensus_threshold",
        warnings,
        float(
            fallback.get("positive_consensus_threshold", fallback.get("consensus_threshold", 0.25))
        ),
    )
    resolved["negative_consensus_threshold"] = _as_unit_float(
        resolved.get(
            "negative_consensus_threshold",
            resolved.get("consensus_threshold", fallback.get("consensus_threshold", 0.20)),
        ),
        "negative_consensus_threshold",
        warnings,
        float(
            fallback.get("negative_consensus_threshold", fallback.get("consensus_threshold", 0.20))
        ),
    )
    resolved["rebound_days"] = _as_positive_int(
        resolved.get("rebound_days", fallback.get("rebound_days", fallback["danger_days"])),
        "rebound_days",
        warnings,
        int(fallback.get("rebound_days", fallback["danger_days"])),
    )
    resolved["trend_fast_ma"] = _as_positive_int(
        resolved.get("trend_fast_ma", fallback.get("trend_fast_ma", 20)),
        "trend_fast_ma",
        warnings,
        int(fallback.get("trend_fast_ma", 20)),
    )
    resolved["trend_slow_ma"] = _as_positive_int(
        resolved.get("trend_slow_ma", fallback.get("trend_slow_ma", 120)),
        "trend_slow_ma",
        warnings,
        int(fallback.get("trend_slow_ma", 120)),
    )
    resolved["trend_slope_window"] = _as_positive_int(
        resolved.get("trend_slope_window", fallback.get("trend_slope_window", 10)),
        "trend_slope_window",
        warnings,
        int(fallback.get("trend_slope_window", 10)),
    )
    resolved["atr_period"] = _as_positive_int(
        resolved.get("atr_period", fallback.get("atr_period", 14)),
        "atr_period",
        warnings,
        int(fallback.get("atr_period", 14)),
    )
    resolved["atr_ma_window"] = _as_positive_int(
        resolved.get("atr_ma_window", fallback.get("atr_ma_window", 60)),
        "atr_ma_window",
        warnings,
        int(fallback.get("atr_ma_window", 60)),
    )
    resolved["vol_breakout_mult"] = _as_non_negative_float(
        resolved.get("vol_breakout_mult", fallback.get("vol_breakout_mult", 1.05)),
        "vol_breakout_mult",
        warnings,
        float(fallback.get("vol_breakout_mult", 1.05)),
    )
    resolved["buy_volatility_cap"] = _as_non_negative_float(
        resolved.get("buy_volatility_cap", fallback.get("buy_volatility_cap", 1.05)),
        "buy_volatility_cap",
        warnings,
        float(fallback.get("buy_volatility_cap", 1.05)),
    )
    resolved["high_volatility_mult"] = _as_non_negative_float(
        resolved.get("high_volatility_mult", fallback.get("high_volatility_mult", 1.15)),
        "high_volatility_mult",
        warnings,
        float(fallback.get("high_volatility_mult", 1.15)),
    )
    resolved["high_volatility_position_cap"] = _as_unit_float(
        resolved.get(
            "high_volatility_position_cap", fallback.get("high_volatility_position_cap", 0.5)
        ),
        "high_volatility_position_cap",
        warnings,
        float(fallback.get("high_volatility_position_cap", 0.5)),
    )
    resolved["drawdown_confirm_threshold"] = _as_unit_float(
        resolved.get(
            "drawdown_confirm_threshold", fallback.get("drawdown_confirm_threshold", 0.05)
        ),
        "drawdown_confirm_threshold",
        warnings,
        float(fallback.get("drawdown_confirm_threshold", 0.05)),
    )
    resolved["buy_reentry_drawdown_threshold"] = _as_unit_float(
        resolved.get(
            "buy_reentry_drawdown_threshold", fallback.get("buy_reentry_drawdown_threshold", 0.08)
        ),
        "buy_reentry_drawdown_threshold",
        warnings,
        float(fallback.get("buy_reentry_drawdown_threshold", 0.08)),
    )
    resolved["buy_reentry_lookback"] = _as_positive_int(
        resolved.get("buy_reentry_lookback", fallback.get("buy_reentry_lookback", 20)),
        "buy_reentry_lookback",
        warnings,
        int(fallback.get("buy_reentry_lookback", 20)),
    )
    resolved["buy_trend_slow_buffer"] = _as_unit_float(
        resolved.get("buy_trend_slow_buffer", fallback.get("buy_trend_slow_buffer", 0.98)),
        "buy_trend_slow_buffer",
        warnings,
        float(fallback.get("buy_trend_slow_buffer", 0.98)),
    )
    resolved["regime_filter_ma"] = _as_positive_int(
        resolved.get(
            "regime_filter_ma", fallback.get("regime_filter_ma", resolved["trend_slow_ma"])
        ),
        "regime_filter_ma",
        warnings,
        int(fallback.get("regime_filter_ma", resolved["trend_slow_ma"])),
    )
    resolved["regime_filter_buffer"] = _as_non_negative_float(
        resolved.get("regime_filter_buffer", fallback.get("regime_filter_buffer", 1.0)),
        "regime_filter_buffer",
        warnings,
        float(fallback.get("regime_filter_buffer", 1.0)),
    )
    resolved["regime_filter_reduce_enabled"] = _as_bool(
        resolved.get(
            "regime_filter_reduce_enabled",
            fallback.get("regime_filter_reduce_enabled", True),
        ),
        bool(fallback.get("regime_filter_reduce_enabled", True)),
    )
    resolved["risk_drawdown_stop_threshold"] = _as_unit_float(
        resolved.get(
            "risk_drawdown_stop_threshold",
            fallback.get("risk_drawdown_stop_threshold", 0.15),
        ),
        "risk_drawdown_stop_threshold",
        warnings,
        float(fallback.get("risk_drawdown_stop_threshold", 0.15)),
    )
    resolved["risk_drawdown_lookback"] = _as_positive_int(
        resolved.get(
            "risk_drawdown_lookback",
            fallback.get("risk_drawdown_lookback", 120),
        ),
        "risk_drawdown_lookback",
        warnings,
        int(fallback.get("risk_drawdown_lookback", 120)),
    )
    resolved["buy_vote_threshold"] = _as_positive_int(
        resolved.get("buy_vote_threshold", fallback.get("buy_vote_threshold", 3)),
        "buy_vote_threshold",
        warnings,
        int(fallback.get("buy_vote_threshold", 3)),
    )
    resolved["sell_vote_threshold"] = _as_positive_int(
        resolved.get("sell_vote_threshold", fallback.get("sell_vote_threshold", 3)),
        "sell_vote_threshold",
        warnings,
        int(fallback.get("sell_vote_threshold", 3)),
    )
    resolved["buy_confirm_days"] = _as_positive_int(
        resolved.get("buy_confirm_days", fallback.get("buy_confirm_days", 2)),
        "buy_confirm_days",
        warnings,
        int(fallback.get("buy_confirm_days", 2)),
    )
    resolved["sell_confirm_days"] = _as_positive_int(
        resolved.get("sell_confirm_days", fallback.get("sell_confirm_days", 2)),
        "sell_confirm_days",
        warnings,
        int(fallback.get("sell_confirm_days", 2)),
    )
    resolved["cooldown_days"] = _as_positive_int(
        resolved.get("cooldown_days", fallback.get("cooldown_days", 15)),
        "cooldown_days",
        warnings,
        int(fallback.get("cooldown_days", 15)),
    )
    resolved["post_sell_reentry_cooldown_days"] = _as_positive_int(
        resolved.get(
            "post_sell_reentry_cooldown_days",
            fallback.get("post_sell_reentry_cooldown_days", 10),
        ),
        "post_sell_reentry_cooldown_days",
        warnings,
        int(fallback.get("post_sell_reentry_cooldown_days", 10)),
    )
    resolved["min_hold_bars"] = _as_non_negative_float(
        resolved.get("min_hold_bars", fallback.get("min_hold_bars", 0)),
        "min_hold_bars",
        warnings,
        float(fallback.get("min_hold_bars", 0)),
    )
    resolved["min_hold_bars"] = int(resolved["min_hold_bars"])
    resolved["allow_top_risk_override_min_hold"] = _as_bool(
        resolved.get(
            "allow_top_risk_override_min_hold",
            fallback.get("allow_top_risk_override_min_hold", True),
        ),
        bool(fallback.get("allow_top_risk_override_min_hold", True)),
    )
    resolved["warning_trade_enabled"] = _as_bool(
        resolved.get(
            "warning_trade_enabled",
            fallback.get("warning_trade_enabled", True),
        ),
        bool(fallback.get("warning_trade_enabled", True)),
    )
    resolved["full_exit_days"] = _as_positive_int(
        resolved.get("full_exit_days", fallback.get("full_exit_days", 3)),
        "full_exit_days",
        warnings,
        int(fallback.get("full_exit_days", 3)),
    )
    resolved["enable_regime_hysteresis"] = _as_bool(
        resolved.get(
            "enable_regime_hysteresis",
            fallback.get("enable_regime_hysteresis", True),
        ),
        bool(fallback.get("enable_regime_hysteresis", True)),
    )
    resolved["require_trend_recovery_for_buy"] = _as_bool(
        resolved.get(
            "require_trend_recovery_for_buy",
            fallback.get("require_trend_recovery_for_buy", True),
        ),
        bool(fallback.get("require_trend_recovery_for_buy", True)),
    )

    resolved["param_source"] = "optimal_yaml"
    return resolved, warnings
