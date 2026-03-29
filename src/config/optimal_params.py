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
    "consensus_threshold",
    "danger_days",
    "warning_days",
    "optimizer",
    "lookahead_days",
    "drop_threshold",
    "ma_window",
    "max_peaks",
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

    resolved["param_source"] = "optimal_yaml"
    return resolved, warnings
