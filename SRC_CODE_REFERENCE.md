# LPPL Source Code Reference

> Auto-generated on 2026-05-07 for code review purposes.

---

## Table of Contents

- [src/__init__.py](#src__init__py)
- [src/computation.py](#src_computation_py)
- [src/constants.py](#src_constants_py)
- [src/exceptions.py](#src_exceptions_py)
- [src/lppl_core.py](#src_lppl_core_py)
- [src/lppl_engine.py](#src_lppl_engine_py)
- [src/lppl_fit.py](#src_lppl_fit_py)
- [src/cli/__init__.py](#src_cli__init__py)
- [src/cli/main.py](#src_cli_main_py)
- [src/cli/generate_optimal8_report.py](#src_cli_generate_optimal8_report_py)
- [src/cli/index_investment_analysis.py](#src_cli_index_investment_analysis_py)
- [src/cli/lppl_verify_v2.py](#src_cli_lppl_verify_v2_py)
- [src/cli/lppl_walk_forward.py](#src_cli_lppl_walk_forward_py)
- [src/cli/tune_signal_model.py](#src_cli_tune_signal_model_py)
- [src/cli/wyckoff_analysis.py](#src_cli_wyckoff_analysis_py)
- [src/cli/wyckoff_multimodal_analysis.py](#src_cli_wyckoff_multimodal_analysis_py)
- [src/config/__init__.py](#src_config__init__py)
- [src/config/optimal_params.py](#src_config_optimal_params_py)
- [src/data/__init__.py](#src_data__init__py)
- [src/data/manager.py](#src_data_manager_py)
- [src/data/tdx_reader.py](#src_data_tdx_reader_py)
- [src/investment/__init__.py](#src_investment__init__py)
- [src/investment/backtest.py](#src_investment_backtest_py)
- [src/investment/backtest_engine.py](#src_investment_backtest_engine_py)
- [src/investment/config.py](#src_investment_config_py)
- [src/investment/group_rescan.py](#src_investment_group_rescan_py)
- [src/investment/indicators.py](#src_investment_indicators_py)
- [src/investment/optimized_strategy.py](#src_investment_optimized_strategy_py)
- [src/investment/signal_models.py](#src_investment_signal_models_py)
- [src/investment/tuning.py](#src_investment_tuning_py)
- [src/reporting/__init__.py](#src_reporting__init__py)
- [src/reporting/html_generator.py](#src_reporting_html_generator_py)
- [src/reporting/investment_report.py](#src_reporting_investment_report_py)
- [src/reporting/optimal8_readable_report.py](#src_reporting_optimal8_readable_report_py)
- [src/reporting/plot_generator.py](#src_reporting_plot_generator_py)
- [src/reporting/verification_report.py](#src_reporting_verification_report_py)
- [src/verification/__init__.py](#src_verification__init__py)
- [src/verification/walk_forward.py](#src_verification_walk_forward_py)
- [src/wyckoff/__init__.py](#src_wyckoff__init__py)
- [src/wyckoff/analyzer.py](#src_wyckoff_analyzer_py)
- [src/wyckoff/config.py](#src_wyckoff_config_py)
- [src/wyckoff/data_engine.py](#src_wyckoff_data_engine_py)
- [src/wyckoff/engine.py](#src_wyckoff_engine_py)
- [src/wyckoff/fusion_engine.py](#src_wyckoff_fusion_engine_py)
- [src/wyckoff/image_engine.py](#src_wyckoff_image_engine_py)
- [src/wyckoff/models.py](#src_wyckoff_models_py)
- [src/wyckoff/reporting.py](#src_wyckoff_reporting_py)
- [src/wyckoff/rules.py](#src_wyckoff_rules_py)
- [src/wyckoff/state.py](#src_wyckoff_state_py)

---

## src/__init__.py

```python
import os

# LPPL - Log-Periodic Power Law Market Crash Prediction System

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

__version__ = "1.0.0"
```

---

## src/computation.py

```python
# -*- coding: utf-8 -*-
import logging
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.constants import ENABLE_JOBLIB_PARALLEL, OUTPUT_DIR, WINDOW_CONFIG
from src.lppl_core import (
    calculate_bottom_signal_strength,
    calculate_risk_level,
    detect_negative_bubble,
    fit_single_window_task,
    validate_input_data,
)

logger = logging.getLogger(__name__)

JOBLIB_AVAILABLE = False
try:
    from joblib import Parallel, delayed
    JOBLIB_AVAILABLE = True
    logger.info("joblib parallel processing available")
except ImportError:
    JOBLIB_AVAILABLE = False
    logger.warning("joblib not available, using ProcessPoolExecutor")


def performance_monitor(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed = end_time - start_time
        logger.info(f"{func.__name__} executed in {elapsed:.2f} seconds")
        return result
    return wrapper


GLOBAL_EXECUTOR = None
_executor_lock = multiprocessing.Lock()


def get_optimal_workers() -> int:
    cpu_count = multiprocessing.cpu_count()
    optimal_workers = max(1, min(4, cpu_count - 2))
    return optimal_workers


def init_global_executor() -> None:
    global GLOBAL_EXECUTOR
    with _executor_lock:
        if GLOBAL_EXECUTOR is None:
            workers = get_optimal_workers()
            GLOBAL_EXECUTOR = ProcessPoolExecutor(max_workers=workers)
            logger.info(f"Global process pool initialized with {workers} workers")


def shutdown_global_executor() -> None:
    global GLOBAL_EXECUTOR
    with _executor_lock:
        if GLOBAL_EXECUTOR is not None:
            GLOBAL_EXECUTOR.shutdown(wait=True)
            GLOBAL_EXECUTOR = None
            logger.info("Global process pool shutdown")


class LPPLComputation:
    def __init__(self, output_dir: str = None, max_workers: Optional[int] = None):
        self.output_dir = output_dir or OUTPUT_DIR
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        self.max_workers = max_workers if max_workers else get_optimal_workers()
        logger.info(f"LPPLComputation initialized with max_workers={self.max_workers}")

    def _format_output(
        self,
        symbol: str,
        name: str,
        window: int,
        res: Dict[str, Any],
        time_span: str = ""
    ) -> List:
        try:
            tc, m, w, a, b, c, phi = res["params"]
            days_left = tc - window

            if days_left < 0:
                days_left = 0

            last_date = res["last_date"]
            if not hasattr(last_date, 'strftime'):
                last_date = pd.Timestamp(last_date)

            crash_date = last_date + timedelta(days=int(days_left))

            risk = calculate_risk_level(m, w, days_left)

            is_negative, bottom_signal = detect_negative_bubble(m, w, b, days_left)
            bottom_strength = calculate_bottom_signal_strength(m, w, b, res['rmse']) if is_negative else 0.0

            return [
                name, symbol, time_span, window,
                f"{res['rmse']:.5f}", f"{m:.3f}", f"{w:.3f}",
                f"{days_left:.1f} 天", crash_date.strftime('%Y-%m-%d'), risk,
                bottom_signal, f"{bottom_strength:.2f}"
            ]
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error formatting output: {e}")
            return []

    def process_index_multiprocess(
        self,
        symbol: str,
        name: str,
        df: pd.DataFrame
    ) -> Tuple[List, List]:
        logger.info(f"  > Scanning {name} ({symbol}) with Batch Parallel Processing...")

        is_valid, msg = validate_input_data(df, symbol)
        if not is_valid:
            logger.error(f"Invalid input data for {symbol}: {msg}")
            return [], []

        tasks = []
        windows = WINDOW_CONFIG.all_windows

        dates_array = df['date'].values
        prices_array = df['close'].values

        for window in windows:
            if len(df) >= window:
                tasks.append((
                    window,
                    dates_array[-window:],
                    prices_array[-window:]
                ))

        if not tasks:
            logger.warning(f"  No valid windows for {symbol}")
            return [], []

        results = {
            "short": {"rmse": float('inf'), "res": None},
            "medium": {"rmse": float('inf'), "res": None},
            "long": {"rmse": float('inf'), "res": None}
        }

        cnt_success = 0
        print(f"  > Scanning {name} ({symbol})...", end="", flush=True)
        start_time = time.time()

        if JOBLIB_AVAILABLE and ENABLE_JOBLIB_PARALLEL:
            parallel_results = Parallel(
                n_jobs=self.max_workers,
                backend='loky',
                timeout=300,
                verbose=0
            )(
                delayed(fit_single_window_task)(task)
                for task in tasks
            )

            for i, res in enumerate(parallel_results):
                window = tasks[i][0]
                if res is not None:
                    print(".", end="", flush=True)
                    cnt_success += 1

                    category = WINDOW_CONFIG.get_category(window)
                    if res["rmse"] < results[category]["rmse"]:
                        results[category]["rmse"] = res["rmse"]
                        results[category]["res"] = res
                else:
                    print("x", end="", flush=True)
        else:
            batch_size = self.max_workers * 2

            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                for i in range(0, len(tasks), batch_size):
                    batch = tasks[i:i + batch_size]

                    future_to_window = {
                        executor.submit(fit_single_window_task, task): task[0]
                        for task in batch
                    }

                    for future in as_completed(future_to_window):
                        window = future_to_window[future]
                        try:
                            res = future.result(timeout=120)
                            if res:
                                print(".", end="", flush=True)
                                cnt_success += 1

                                category = WINDOW_CONFIG.get_category(window)
                                if res["rmse"] < results[category]["rmse"]:
                                    results[category]["rmse"] = res["rmse"]
                                    results[category]["res"] = res
                            else:
                                print("x", end="", flush=True)
                        except FuturesTimeoutError:
                            print("T", end="", flush=True)
                            logger.warning(f"Task timeout for window {window}")
                        except Exception as e:
                            print("E", end="", flush=True)
                            logger.warning(f"Error processing window {window}: {e}")

        elapsed_time = time.time() - start_time
        print(f" Done (Time: {elapsed_time:.2f}s, Success: {cnt_success}/{len(tasks)})")

        output_rows = []
        params_data = []

        span_map = {"short": "短期", "medium": "中期", "long": "长期"}

        for key, val in results.items():
            if val["res"]:
                res = val["res"]
                formatted = self._format_output(symbol, name, res["window"], res, span_map[key])
                if formatted:
                    output_rows.append(formatted)

                    params_data.append({
                        "symbol": symbol, "name": name, "time_span": span_map[key],
                        "window": res["window"], "params": res["params"].tolist(),
                        "rmse": res["rmse"], "last_date": res["last_date"].strftime('%Y-%m-%d')
                    })

        return output_rows, params_data

    @performance_monitor
    def run_computation(
        self,
        data_dict: Dict[str, Dict[str, Any]],
        close_executor: bool = False
    ) -> List:
        if not data_dict:
            logger.warning("Empty data_dict provided")
            return []

        all_report_data = []
        all_params_data = []

        index_tasks = []
        for symbol, info in data_dict.items():
            name = info.get("name", symbol)
            df = info.get("data")

            is_valid, msg = validate_input_data(df, symbol)
            if is_valid:
                index_tasks.append((symbol, name, df))
            else:
                print(f"  Skipping {name} ({symbol}): {msg}")

        if not index_tasks:
            logger.warning("No valid indices to process")
            return []

        print(f"Processing {len(index_tasks)} indices (parallel windows)...")

        for symbol, name, df in index_tasks:
            logger.info(f"Processing {name} ({symbol})...")
            try:
                rows, params = self.process_index_multiprocess(symbol, name, df)
                if rows:
                    all_report_data.extend(rows)
                    all_params_data.extend(params)
                    logger.info(f"Completed processing {name} ({symbol})")
            except Exception as e:
                logger.error(f"Error processing {name} ({symbol}): {e}")

        if all_report_data:
            try:
                all_report_data.sort(key=lambda x: float(x[4]) if x[4] else float('inf'))
            except (ValueError, IndexError) as e:
                logger.warning(f"Error sorting results: {e}")

        return all_report_data, all_params_data

    def generate_markdown(self, report_data: List, data_date: str = None) -> Optional[str]:
        if not report_data:
            logger.warning("No report data provided")
            return None

        if data_date is None:
            data_date = datetime.now().strftime('%Y%m%d')

        filename = f"lppl_report_{data_date}.md"
        file_path = os.path.join(self.output_dir, filename)

        markdown_content = f"# LPPL模型扫描报告\n\n**生成时间**: {datetime.now()}\n\n**数据日期**: {data_date}\n\n"
        markdown_content += "| 指数名称 | 指数代码 | 时间跨度 | 窗口(天) | RMSE | m | w | 距离崩盘 | 崩盘日期 | 风险等级 | 抄底信号 | 信号强度 |\n"
        markdown_content += "|---|---|---|---|---|---|---|---|---|---|---|---|\n"

        for row in report_data:
            if row:
                line = "|" + "|".join(str(x) for x in row) + "|\n"
                markdown_content += line

        markdown_content += "\n\n---\n\n### AI Agent Context Block\n\n"
        markdown_content += "```markdown\n"
        markdown_content += f"# LPPL Scan Data - {data_date}\n"
        markdown_content += "| Index | Code | Window | Crash_Date | Days_Left | Risk | m | RMSE | Bottom_Signal |\n"
        markdown_content += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"

        for row in report_data:
            if row and len(row) >= 12:
                risk_level = row[9]
                bottom_signal = row[10] if len(row) > 10 else "无"
                if "极高" in risk_level or "高" in risk_level or "抄底" in bottom_signal or "上证" in row[0] or "创业" in row[0]:
                    days = str(row[7]).replace(" 天", "")
                    m_val = row[5]
                    rmse_val = row[4]
                    markdown_content += f"| {row[0]} | {row[1]} | {row[3]} ({row[2]}) | {row[8]} | {days} | {risk_level} | {m_val} | {rmse_val} | {bottom_signal} |\n"

        markdown_content += "```\n"

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            print(f"Markdown report saved to: {file_path}")
            return file_path
        except PermissionError as e:
            print(f"Permission denied saving MD: {e}")
            return None
        except OSError as e:
            print(f"OS error saving MD: {e}")
            return None

    def save_params_to_json(self, params_data: List, data_date: str = None) -> Optional[str]:
        if not params_data:
            logger.warning("No parameters to save")
            return None

        import json

        if data_date is None:
            data_date = datetime.now().strftime('%Y%m%d')

        filename = f"lppl_params_{data_date}.json"
        file_path = os.path.join(self.output_dir, filename)

        json_data = {
            "data_date": data_date,
            "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "parameters": params_data
        }

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
            print(f"Full LPPL parameters saved to: {file_path}")
            return file_path
        except PermissionError as e:
            print(f"Permission denied saving parameters: {e}")
            return None
        except OSError as e:
            print(f"OS error saving parameters: {e}")
            return None
```

---

## src/constants.py

```python
# -*- coding: utf-8 -*-
import os
from dataclasses import dataclass
from typing import Dict, List

INDICES: Dict[str, str] = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "932000.SH": "中证2000",
}

LEGACY_TO_NEW_SYMBOL_MAP: Dict[str, str] = {
    "sh000001": "000001.SH",
    "sz399001": "399001.SZ",
    "sz399006": "399006.SZ",
    "sh000016": "000016.SH",
    "sh000300": "000300.SH",
    "sh000905": "000905.SH",
    "sh000852": "000852.SH",
    "sh000857": "932000.SH",
    "932000": "932000.SH",
}

LOCAL_DATA_INDICES: List[str] = [
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000016.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "932000.SH",
]

AKSHARE_INDICES: List[str] = [
    "932000.SH",
]

TDX_DATA_DIR: str = os.environ.get(
    "LPPL_TDX_DATA_DIR",
    "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"
)

REQUIRED_COLUMNS: List[str] = ["date", "open", "close", "high", "low", "volume"]

MIN_DATA_ROWS: int = 100

MAX_DATA_AGE_DAYS: int = 7


@dataclass(frozen=True)
class WindowConfig:
    short_windows: List[int]
    medium_windows: List[int]
    long_windows: List[int]

    @property
    def all_windows(self) -> List[int]:
        return self.short_windows + self.medium_windows + self.long_windows

    def get_category(self, window: int) -> str:
        if window < 200:
            return "short"
        elif 200 <= window <= 500:
            return "medium"
        else:
            return "long"


WINDOW_CONFIG = WindowConfig(
    short_windows=list(range(50, 300, 10)),
    medium_windows=list(range(300, 600, 20)),
    long_windows=list(range(600, 1200, 50)),
)

DEFAULT_DATA_DIR: str = os.environ.get(
    "LPPL_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
)

OUTPUT_DIR: str = "output"
VERIFY_OUTPUT_DIR: str = os.environ.get(
    "LPPL_VERIFY_OUTPUT_DIR",
    os.path.join(OUTPUT_DIR, "MA")
)
PLOTS_OUTPUT_DIR: str = os.environ.get(
    "LPPL_PLOTS_DIR",
    os.path.join(VERIFY_OUTPUT_DIR, "plots")
)
REPORTS_OUTPUT_DIR: str = os.environ.get(
    "LPPL_REPORTS_DIR",
    os.path.join(VERIFY_OUTPUT_DIR, "reports")
)
SUMMARY_OUTPUT_DIR: str = os.environ.get(
    "LPPL_SUMMARY_DIR",
    os.path.join(VERIFY_OUTPUT_DIR, "summary")
)
RAW_OUTPUT_DIR: str = os.environ.get(
    "LPPL_RAW_DIR",
    os.path.join(VERIFY_OUTPUT_DIR, "raw")
)

DATA_COLUMNS: Dict[str, str] = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover",
}

ENABLE_NUMBA_JIT: bool = True
ENABLE_JOBLIB_PARALLEL: bool = True
ENABLE_INCREMENTAL_UPDATE: bool = True
ENABLE_NEGATIVE_BUBBLE: bool = True

WYCKOFF_PHASES: List[str] = [
    "accumulation",
    "markup",
    "distribution",
    "markdown",
]

WYCKOFF_DIRECTIONS: List[str] = [
    "bullish",
    "bearish",
    "neutral",
]

WYCKOFF_CONFIDENCE_LEVELS: List[str] = [
    "very_high",
    "high",
    "medium",
    "low",
    "very_low",
]

VOLUME_LABELS: List[str] = [
    "very_low",
    "low",
    "normal",
    "high",
    "very_high",
    "climax",
]

IMAGE_QUALITY_LEVELS: List[str] = [
    "low",
    "medium",
    "high",
    "ultra",
]

VISUAL_TRENDS: List[str] = [
    "strong_uptrend",
    "weak_uptrend",
    "sideways",
    "weak_downtrend",
    "strong_downtrend",
]

TIMEFRAME_HINTS: List[str] = [
    "intraday",
    "short_term",
    "medium_term",
    "long_term",
    "multi_year",
]

VISUAL_ANOMALIES: List[str] = [
    "gap_up",
    "gap_down",
    "spike_high",
    "spike_low",
    "doji",
    "engulfing",
    "divergence",
]

WYCKOFF_OUTPUT_DIR: str = os.environ.get(
    "LPPL_WYCKOFF_OUTPUT_DIR",
    os.path.join(OUTPUT_DIR, "wyckoff"),
)

MIN_WYCKOFF_DATA_ROWS: int = 200
BC_LOOKBACK_WINDOW: int = 20
SPRING_FREEZE_DAYS: int = 3
MIN_RR_RATIO: float = 2.5
```

---

## src/exceptions.py

```python
# -*- coding: utf-8 -*-

class LPPLException(Exception):
    pass


class DataValidationError(LPPLException):
    pass


class DataFetchError(LPPLException):
    pass


class DataNotFoundError(LPPLException):
    pass


class ComputationError(LPPLException):
    pass


class ConfigurationError(LPPLException):
    pass


class WyckoffError(LPPLException):
    pass


class BCNotFoundError(WyckoffError):
    pass


class InvalidInputDataError(WyckoffError):
    pass


class ImageProcessingError(WyckoffError):
    pass


class FusionConflictError(WyckoffError):
    pass


class RuleEngineError(WyckoffError):
    pass
```

---

## src/lppl_core.py

```python
# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

NUMBA_AVAILABLE = False
try:
    from numba import njit
    NUMBA_AVAILABLE = True
    logger.info("Numba JIT compilation available")
except ImportError:
    NUMBA_AVAILABLE = False
    logger.warning("Numba not available, using pure Python implementation")


def _lppl_func_python(
    t: np.ndarray,
    tc: float,
    m: float,
    w: float,
    a: float,
    b: float,
    c: float,
    phi: float
) -> np.ndarray:
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau ** m) + c * (tau ** m) * np.cos(w * np.log(tau) + phi)


if NUMBA_AVAILABLE:
    @njit(cache=True, fastmath=True)
    def _lppl_func_numba(
        t: np.ndarray,
        tc: float,
        m: float,
        w: float,
        a: float,
        b: float,
        c: float,
        phi: float
    ) -> np.ndarray:
        tau = tc - t
        n = len(tau)
        result = np.empty(n)
        for i in range(n):
            if tau[i] < 1e-8:
                tau_i = 1e-8
            else:
                tau_i = tau[i]
            result[i] = a + b * (tau_i ** m) + c * (tau_i ** m) * np.cos(w * np.log(tau_i) + phi)
        return result


def lppl_func(
    t: np.ndarray,
    tc: float,
    m: float,
    w: float,
    a: float,
    b: float,
    c: float,
    phi: float
) -> np.ndarray:
    from src.constants import ENABLE_NUMBA_JIT
    if NUMBA_AVAILABLE and ENABLE_NUMBA_JIT:
        return _lppl_func_numba(t, tc, m, w, a, b, c, phi)
    return _lppl_func_python(t, tc, m, w, a, b, c, phi)


def cost_function(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:
    from src.constants import ENABLE_NUMBA_JIT
    if NUMBA_AVAILABLE and ENABLE_NUMBA_JIT:
        return _cost_function_numba(params, t, log_prices)
    return _cost_function_python(params, t, log_prices)


def _cost_function_python(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:
    tc, m, w, a, b, c, phi = params
    try:
        prediction = _lppl_func_python(t, tc, m, w, a, b, c, phi)
        residuals = prediction - log_prices
        return np.sum(residuals ** 2)
    except (FloatingPointError, OverflowError, ValueError):
        return 1e10


if NUMBA_AVAILABLE:
    @njit(cache=True, fastmath=True)
    def _cost_function_numba(params: np.ndarray, t: np.ndarray, log_prices: np.ndarray) -> float:
        tc = params[0]
        m = params[1]
        w = params[2]
        a = params[3]
        b = params[4]
        c = params[5]
        phi = params[6]

        prediction = _lppl_func_numba(t, tc, m, w, a, b, c, phi)
        residuals = prediction - log_prices
        return np.sum(residuals ** 2)


def validate_input_data(
    df,
    symbol: str
) -> Tuple[bool, str]:
    if df is None or df.empty:
        return False, "DataFrame is None or empty"

    from src.constants import REQUIRED_COLUMNS
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return False, f"Missing required columns: {missing_cols}"

    if len(df) < 50:
        return False, f"Insufficient data rows: {len(df)} < 50"

    if df["close"].isnull().any():
        return False, "Null values found in close column"

    if (df["close"] <= 0).any():
        return False, "Non-positive prices found in close column"

    return True, "Validation passed"


def fit_single_window_task(args: Tuple) -> Optional[Dict[str, Any]]:
    window_size, dates_series, prices_array = args

    try:
        if len(prices_array) < 50 or window_size <= 0:
            return None

        t_data = np.arange(len(prices_array))
        log_price_data = np.log(prices_array)

        if np.any(np.isnan(log_price_data)) or np.any(np.isinf(log_price_data)):
            return None

        current_t = len(prices_array)
        last_date_raw = dates_series.iloc[-1] if hasattr(dates_series, 'iloc') else dates_series[-1]
        if hasattr(last_date_raw, 'to_pydatetime'):
            last_date = last_date_raw
        else:
            import pandas as pd
            last_date = pd.Timestamp(last_date_raw)

        price_min = np.min(log_price_data)
        price_max = np.max(log_price_data)

        if price_min == price_max:
            return None

        bounds = [
            (current_t + 1, current_t + 100),
            (0.1, 0.9),
            (6, 13),
            (price_min, price_max * 1.1),
            (-20, 20),
            (-20, 20),
            (0, 2 * np.pi)
        ]

        from scipy.optimize import differential_evolution
        result = differential_evolution(
            cost_function, bounds, args=(t_data, log_price_data),
            strategy='best1bin', maxiter=100, popsize=15, tol=0.05,
            seed=42, workers=1
        )

        if not result.success or not np.isfinite(result.fun):
            return None

        fitted_curve = lppl_func(t_data, *result.x)
        mse = np.mean((fitted_curve - log_price_data) ** 2)

        if not np.isfinite(mse):
            return None

        rmse = np.sqrt(mse)

        if not np.isfinite(rmse) or rmse > 10:
            return None

        return {
            "window": window_size,
            "params": result.x,
            "rmse": rmse,
            "last_date": last_date
        }
    except (ValueError, TypeError, FloatingPointError):
        return None
    except Exception:
        return None


def calculate_risk_level(m: float, w: float, days_left: float) -> str:
    if 0.1 < m < 0.9 and 6 < w < 13:
        if days_left < 5:
            return "极高危 (DANGER)"
        elif days_left < 20:
            return "高危 (Warning)"
        elif days_left < 60:
            return "观察 (Watch)"
        else:
            return "安全 (Safe)"
    else:
        return "无效模型 (假信号)"


def detect_negative_bubble(m: float, w: float, b: float, days_left: float) -> Tuple[bool, str]:
    is_negative = False
    signal = "无抄底信号"

    if 0.1 < m < 0.9 and 6 < w < 13:
        if b > 0:
            is_negative = True
            if days_left < 20:
                signal = "强抄底信号 (Strong Buy)"
            elif days_left < 40:
                signal = "中等抄底信号 (Buy)"
            else:
                signal = "弱抄底信号 (Watch for Buy)"

    return is_negative, signal


def calculate_bottom_signal_strength(m: float, w: float, b: float, rmse: float) -> float:
    strength = 0.0

    if not (0.1 < m < 0.9 and 6 < w < 13):
        return 0.0

    if b <= 0:
        return 0.0

    m_score = 1.0 - abs(m - 0.5) / 0.4

    w_score = 1.0 - abs(w - 8.0) / 5.0

    b_score = min(b / 1.0, 1.0)

    rmse_score = max(0.0, 1.0 - rmse / 0.1)

    strength = (m_score * 0.3 + w_score * 0.3 + b_score * 0.2 + rmse_score * 0.2)

    return min(max(strength, 0.0), 1.0)
```

---

## src/lppl_engine.py

```python
# -*- coding: utf-8 -*-
"""
LPPL 工业级引擎 - 统一核心模块

包含:
- 底层Numba加速算子
- 单窗口/多窗口拟合
- 风险判定
- 峰值检测与分析
"""

import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution, minimize

try:
    from numba import njit
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

warnings.filterwarnings("ignore")


# ============================================================================
# 配置类
# ============================================================================

@dataclass
class LPPLConfig:
    """LPPL配置参数"""
    # 窗口配置
    window_range: List[int]

    # 优化器配置 (使用DE保持与原verify_lppl.py一致)
    optimizer: str = 'de'
    maxiter: int = 100
    popsize: int = 15
    tol: float = 0.05

    # 风险阈值 (与plan.md v1.2.0一致)
    m_bounds: Tuple[float, float] = (0.1, 0.9)
    w_bounds: Tuple[float, float] = (6, 13)
    tc_bound: Tuple[float, float] = (1, 100)  # days after current_t

    # 信号阈值
    r2_threshold: float = 0.5
    danger_r2_offset: float = 0.0
    danger_days: int = 5
    warning_days: int = 12
    watch_days: int = 25

    # Ensemble配置
    consensus_threshold: float = 0.15

    # 并行配置
    n_workers: int = -1

    def __post_init__(self):
        self.danger_days = max(1, int(self.danger_days))
        self.warning_days = max(self.danger_days + 1, int(self.warning_days))
        self.watch_days = max(self.warning_days + 1, int(self.watch_days))
        if self.n_workers == -1:
            import os
            self.n_workers = max(1, (os.cpu_count() or 4) - 2)


DEFAULT_CONFIG = LPPLConfig(
    window_range=list(range(40, 100, 20)),  # 与verify_lppl.py一致
)


def warning_r2_threshold(config: LPPLConfig) -> float:
    return max(0.0, float(config.r2_threshold) - 0.05)


def watch_r2_threshold(config: LPPLConfig) -> float:
    return max(0.0, float(config.r2_threshold) - 0.15)


def danger_r2_threshold(config: LPPLConfig) -> float:
    return min(1.0, max(0.0, float(config.r2_threshold) + float(config.danger_r2_offset)))


def classify_top_phase(days_left: float, r2: float, config: LPPLConfig) -> str:
    if days_left < 0:
        return "none"
    if days_left < config.danger_days and r2 >= danger_r2_threshold(config):
        return "danger"
    if days_left < config.warning_days and r2 >= warning_r2_threshold(config):
        return "warning"
    if days_left < config.watch_days and r2 >= watch_r2_threshold(config):
        return "watch"
    return "none"


# ============================================================================
# Numba加速底层算子
# ============================================================================

@njit(cache=True)
def _lppl_func_numba(t: np.ndarray, tc: float, m: float, w: float,
                     a: float, b: float, c: float, phi: float) -> np.ndarray:
    """LPPL模型函数 - Numba加速"""
    n = len(t)
    result = np.empty(n)
    for i in range(n):
        tau = tc - t[i]
        if tau < 1e-8:
            tau = 1e-8
        power = tau ** m
        result[i] = a + b * power + c * power * np.cos(w * np.log(tau) + phi)
    return result


def lppl_func(t: np.ndarray, tc: float, m: float, w: float,
              a: float, b: float, c: float, phi: float) -> np.ndarray:
    """LPPL模型函数 - 自动选择Numba或纯Python"""
    if NUMBA_AVAILABLE:
        try:
            return _lppl_func_numba(t, tc, m, w, a, b, c, phi)
        except Exception:
            pass
    # 纯Python回退
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau ** m) + c * (tau ** m) * np.cos(w * np.log(tau) + phi)


@njit(cache=True)
def _cost_function_numba(params: np.ndarray, t: np.ndarray,
                         log_prices: np.ndarray) -> float:
    """代价函数 - Numba加速"""
    tc = params[0]
    m = params[1]
    w = params[2]
    a = params[3]
    b = params[4]
    c = params[5]
    phi = params[6]

    n = len(t)
    total = 0.0
    for i in range(n):
        tau = tc - t[i]
        if tau < 1e-8:
            tau = 1e-8
        power = tau ** m
        pred = a + b * power + c * power * np.cos(w * np.log(tau) + phi)
        diff = pred - log_prices[i]
        total += diff * diff
    return total


def cost_function(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:
    """代价函数 - 自动选择优化"""
    if NUMBA_AVAILABLE:
        try:
            return _cost_function_numba(np.array(params), t, log_prices)
        except Exception:
            pass
    # 纯Python回退
    tc, m, w, a, b, c, phi = params
    prediction = lppl_func(t, tc, m, w, a, b, c, phi)
    residuals = prediction - log_prices
    return np.sum(residuals ** 2)


# ============================================================================
# 拟合函数
# ============================================================================

def fit_single_window(close_prices: np.ndarray, window_size: int,
                      config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """拟合单个窗口 (使用DE优化器，与verify_lppl.py一致)"""
    if config is None:
        config = DEFAULT_CONFIG
    if len(close_prices) < window_size:
        return None
    t_data = np.arange(window_size, dtype=np.float64)
    price_data = close_prices[-window_size:]
    log_price_data = np.log(price_data)
    current_t = float(window_size)
    log_min = np.min(log_price_data)
    log_max = np.max(log_price_data)
    bounds = [
        (current_t + config.tc_bound[0], current_t + config.tc_bound[1]),
        config.m_bounds, config.w_bounds,
        (log_min, log_max * 1.1), (-20, 20), (-20, 20), (0, 2 * np.pi)
    ]
    try:
        result = differential_evolution(
            cost_function, bounds, args=(t_data, log_price_data),
            strategy='best1bin', maxiter=config.maxiter, popsize=config.popsize,
            tol=config.tol, seed=42, workers=1
        )
        if not result.success:
            return None
        tc, m, w, a, b, c, phi = result.x
        days_to_crash = tc - current_t
        fitted_curve = lppl_func(t_data, tc, m, w, a, b, c, phi)
        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - np.mean(log_price_data)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        rmse = np.sqrt(np.mean((fitted_curve - log_price_data) ** 2))
        is_danger = (
            (config.m_bounds[0] < m < config.m_bounds[1])
            and (config.w_bounds[0] < w < config.w_bounds[1])
            and classify_top_phase(days_to_crash, r_squared, config) == "danger"
        )
        return {
            'window_size': window_size, 'rmse': rmse, 'r_squared': r_squared,
            'm': m, 'w': w, 'tc': tc, 'days_to_crash': days_to_crash,
            'is_danger': bool(is_danger), 'params': (tc, m, w, a, b, c, phi),
        }
    except Exception:
        return None


def fit_single_window_lbfgsb(close_prices: np.ndarray, window_size: int,
                              config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """拟合单个窗口 (使用L-BFGS-B优化器)"""
    if config is None:
        config = DEFAULT_CONFIG
    if len(close_prices) < window_size:
        return None
    t_data = np.arange(window_size, dtype=np.float64)
    price_data = close_prices[-window_size:]
    log_price_data = np.log(price_data)
    current_t = float(window_size)
    log_mean = np.mean(log_price_data)
    log_min = np.min(log_price_data)
    log_max = np.max(log_price_data)
    log_range = log_max - log_min
    if log_range < 1e-6 or log_range > 50:
        return None
    bounds = [
        (current_t + config.tc_bound[0], current_t + config.tc_bound[1]),
        config.m_bounds, config.w_bounds,
        (log_min - 0.5 * log_range, log_max + 0.5 * log_range),
        (-log_range * 3, log_range * 3), (-log_range * 3, log_range * 3), (0, 2 * np.pi)
    ]
    initial_guesses = [
        [current_t + 5, 0.5, 8.5, log_mean, log_range * 0.1, log_range * 0.01, 0.0],
        [current_t + 10, 0.4, 9.5, log_mean, log_range * 0.05, -log_range * 0.02, np.pi/2],
        [current_t + 15, 0.6, 7.5, log_mean, log_range * 0.08, log_range * 0.005, np.pi],
        [current_t + 8, 0.7, 8.0, log_mean, log_range * 0.06, -log_range * 0.01, np.pi/4],
    ]
    best_cost = np.inf
    best_params = None
    for x0 in initial_guesses:
        try:
            res = minimize(cost_function, x0, args=(t_data, log_price_data),
                          method='L-BFGS-B', bounds=bounds, options={'maxiter': 50, 'ftol': 0.1})
            if res.fun < best_cost:
                best_cost = res.fun
                best_params = res.x
        except Exception:
            continue
    if best_params is None:
        return None
    try:
        tc, m, w, a, b, c, phi = best_params
        days_to_crash = tc - current_t
        fitted_curve = lppl_func(t_data, tc, m, w, a, b, c, phi)
        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - log_mean) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        rmse = np.sqrt(best_cost / len(log_price_data))
        is_danger = (
            (config.m_bounds[0] < m < config.m_bounds[1])
            and (config.w_bounds[0] < w < config.w_bounds[1])
            and classify_top_phase(days_to_crash, r_squared, config) == "danger"
        )
        return {
            'window_size': window_size, 'rmse': rmse, 'r_squared': r_squared,
            'm': m, 'w': w, 'tc': tc, 'days_to_crash': days_to_crash,
            'is_danger': bool(is_danger), 'params': (tc, m, w, a, b, c, phi),
        }
    except Exception:
        return None


def calculate_risk_level(m: float, w: float, days_left: float, r2: float = 1.0) -> Tuple[str, bool, bool]:
    """计算风险等级"""
    valid_model = (DEFAULT_CONFIG.m_bounds[0] < m < DEFAULT_CONFIG.m_bounds[1] and
                   DEFAULT_CONFIG.w_bounds[0] < w < DEFAULT_CONFIG.w_bounds[1])
    if not valid_model:
        return "无效模型", False, False
    phase = classify_top_phase(days_left, r2, DEFAULT_CONFIG)
    is_danger = phase == "danger"
    is_warning = phase in {"warning", "danger"}
    if days_left < 5:
        return "极高危", is_danger, is_warning
    elif days_left < DEFAULT_CONFIG.danger_days:
        return "高危", is_danger, is_warning
    elif days_left < DEFAULT_CONFIG.watch_days:
        return "观察", is_danger, is_warning
    else:
        return "安全", is_danger, is_warning


def scan_single_date(close_prices: np.ndarray, idx: int, window_range: List[int],
                    config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """扫描单个日期的所有窗口"""
    if config is None:
        config = DEFAULT_CONFIG
    results = []
    for window_size in window_range:
        if idx < window_size:
            continue
        subset = close_prices[idx - window_size:idx]
        if config.optimizer == 'lbfgsb':
            res = fit_single_window_lbfgsb(subset, window_size, config)
        else:
            res = fit_single_window(subset, window_size, config)
        if res is not None:
            res['idx'] = idx
            results.append(res)
    if not results:
        return None
    return min(results, key=lambda x: x['rmse'])


def find_local_highs(df: pd.DataFrame, min_gap: int = 60, min_drop_pct: float = 0.05,
                     window: int = 20) -> List[Dict[str, Any]]:
    """查找局部最高点"""
    highs = []
    close = df['close'].values
    dates = df['date'].values
    for i in range(window, len(close) - window):
        local_max = np.max(close[i-window:i+window+1])
        if close[i] == local_max:
            future_window = min(60, len(close) - i - 1)
            if future_window > 0:
                future_min = np.min(close[i+1:i+1+future_window])
                drop_pct = (close[i] - future_min) / close[i]
                if drop_pct >= min_drop_pct:
                    too_close = any(abs(i - h['idx']) < min_gap for h in highs)
                    if not too_close:
                        highs.append({'idx': i, 'date': dates[i], 'price': close[i], 'drop_pct': drop_pct})
    return highs


def calculate_trend_scores(daily_results: List[Dict], ma_window: int = 5,
                         config: LPPLConfig = None) -> pd.DataFrame:
    """计算趋势评分"""
    if config is None:
        config = DEFAULT_CONFIG
    if not daily_results:
        return pd.DataFrame()
    df = pd.DataFrame(daily_results).sort_values('idx').reset_index(drop=True)
    if 'is_danger' not in df.columns:
        df['is_danger'] = df.apply(lambda r: (
            config.m_bounds[0] < r['m'] < config.m_bounds[1] and
            config.w_bounds[0] < r['w'] < config.w_bounds[1] and
            r['days_to_crash'] < config.danger_days and r['r_squared'] > config.r2_threshold
        ), axis=1)
    df['r2_ma'] = df['r_squared'].rolling(window=ma_window, min_periods=1).mean()
    df['danger_count'] = df['is_danger'].rolling(window=ma_window, min_periods=1).sum()
    df['trend_score'] = df['r2_ma'] * (df['danger_count'] / ma_window)
    return df


def analyze_peak(df: pd.DataFrame, peak_idx: int, window_range: List[int], scan_step: int = 2,
                ma_window: int = 5, config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """分析单个高点前后的LPPL信号"""
    if config is None:
        config = DEFAULT_CONFIG
    close_prices = df['close'].values
    start_idx = max(max(window_range) + 5, peak_idx - 120)
    end_idx = peak_idx
    if start_idx >= end_idx:
        return None
    indices = list(range(start_idx, end_idx + 1, scan_step))
    from joblib import Parallel, delayed
    results = Parallel(n_jobs=config.n_workers, backend='loky', verbose=0)(
        delayed(scan_single_date)(close_prices, idx, window_range, config) for idx in indices
    )
    results = [r for r in results if r is not None]
    if len(results) == 0:
        return None
    for r in results:
        r['date'] = df.iloc[r['idx']]['date']
        r['price'] = df.iloc[r['idx']]['close']
        r['days_to_peak'] = r['idx'] - peak_idx
    trend_df = calculate_trend_scores(results, ma_window, config)
    danger_signals = trend_df[trend_df['is_danger']]
    danger_before_peak = danger_signals[danger_signals['days_to_peak'] <= 0]
    first_danger = danger_before_peak.sort_values('date').iloc[0] if len(danger_before_peak) > 0 else None
    before_peak = trend_df[trend_df['days_to_peak'] <= 0]
    best_trend = before_peak.loc[before_peak['trend_score'].idxmax()] if len(before_peak) > 0 and len(before_peak[before_peak['trend_score'] > 0]) > 0 else None
    peak_date = df.iloc[peak_idx]['date']
    peak_price = df.iloc[peak_idx]['close']
    return {
        'peak_idx': peak_idx, 'peak_date': peak_date if isinstance(peak_date, str) else peak_date.strftime('%Y-%m-%d'),
        'peak_price': peak_price, 'total_scans': len(results), 'danger_count': len(danger_signals),
        'danger_before_peak': len(danger_before_peak),
        'first_danger_days': first_danger['days_to_peak'] if first_danger is not None else None,
        'first_danger_r2': first_danger['r_squared'] if first_danger is not None else None,
        'first_danger_m': first_danger['m'] if first_danger is not None else None,
        'first_danger_w': first_danger['w'] if first_danger is not None else None,
        'best_trend_days': best_trend['days_to_peak'] if best_trend is not None else None,
        'best_trend_score': best_trend['trend_score'] if best_trend is not None else None,
        'best_trend_r2': best_trend['r_squared'] if best_trend is not None else None,
        'detected': len(danger_before_peak) > 0, 'mode': 'single_window', 'timeline': trend_df.to_dict('records'),
    }


def process_single_day_ensemble(close_prices: np.ndarray, idx: int, window_range: List[int],
                               min_r2: float = None, consensus_threshold: float = None,
                               config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """处理特定交易日，执行系综集成"""
    if config is None:
        config = DEFAULT_CONFIG
    if min_r2 is None:
        min_r2 = config.r2_threshold
    if consensus_threshold is None:
        consensus_threshold = config.consensus_threshold
    valid_fits = []
    total_windows = len(window_range)
    for w_size in window_range:
        if idx < w_size:
            continue
        subset = close_prices[idx - w_size:idx]
        if config.optimizer == 'lbfgsb':
            res = fit_single_window_lbfgsb(subset, w_size, config)
        else:
            res = fit_single_window(subset, w_size, config)
        if res is not None and res['r_squared'] > min_r2:
            if config.m_bounds[0] < res['m'] < config.m_bounds[1] and config.w_bounds[0] < res['w'] < config.w_bounds[1]:
                valid_fits.append(res)
    valid_n = len(valid_fits)
    consensus_rate = valid_n / total_windows if total_windows > 0 else 0
    if consensus_rate < consensus_threshold:
        return None
    tc_array = np.array([fit['days_to_crash'] for fit in valid_fits])
    tc_std = np.std(tc_array)
    signal_strength = consensus_rate * (1.0 / (tc_std + 1.0))
    return {
        'idx': idx, 'consensus_rate': consensus_rate, 'valid_windows': valid_n,
        'predicted_crash_days': np.median(tc_array), 'tc_std': tc_std,
        'signal_strength': signal_strength, 'avg_r2': np.mean([fit['r_squared'] for fit in valid_fits]),
    }


config = DEFAULT_CONFIG
```

---

## src/lppl_fit.py

```python
# -*- coding: utf-8 -*-
"""
LPPL 回测 - 极速拟合模块
使用向量化预计算 + 快速优化
"""

import numpy as np
from numba import njit
from scipy.optimize import minimize


@njit(cache=True, parallel=True)
def lppl_vectorized(t, tc, m, w, a, b, c, phi):
    """LPPL 模型函数 - Numba 并行加速"""
    n = len(t)
    result = np.empty(n)
    for i in range(n):
        tau = tc - t[i]
        if tau < 1e-8:
            tau = 1e-8
        power = tau ** m
        result[i] = a + b * power + c * power * np.cos(w * np.log(tau) + phi)
    return result


@njit(cache=True)
def compute_cost(params, t, log_prices):
    """成本函数"""
    tc, m, w, a, b, c, phi = params
    prediction = lppl_vectorized(t, tc, m, w, a, b, c, phi)
    return np.sum((prediction - log_prices) ** 2)


def fit_single_point(data):
    """
    极速拟合 - 仅使用 L-BFGS-B 快速优化
    
    Args:
        data: tuple (idx, close_prices, window_size)
    
    Returns:
        dict 或 None
    """
    idx, close_prices, window_size = data

    if idx < window_size:
        return None

    close_subset = close_prices[max(0, idx - window_size):idx]

    if len(close_subset) < window_size:
        return None

    t_data = np.arange(len(close_subset), dtype=np.float64)
    log_prices = np.log(close_subset)
    current_t = float(len(close_subset))

    log_price_mean = np.mean(log_prices)
    log_price_min = np.min(log_prices)
    log_price_max = np.max(log_prices)
    log_price_range = log_price_max - log_price_min

    if log_price_range < 1e-6 or log_price_range > 50:
        return None

    bounds = [
        (current_t + 1, current_t + 100),
        (0.1, 0.9),
        (6, 13),
        (log_price_min - 0.5 * log_price_range, log_price_max + 0.5 * log_price_range),
        (-log_price_range * 3, log_price_range * 3),
        (-log_price_range * 3, log_price_range * 3),
        (0, 2 * np.pi)
    ]

    initial_guesses = [
        [current_t + 5, 0.5, 8.5, log_price_mean, log_price_range * 0.1, log_price_range * 0.01, 0.0],
        [current_t + 10, 0.4, 9.5, log_price_mean, log_price_range * 0.05, -log_price_range * 0.02, np.pi/2],
        [current_t + 15, 0.6, 7.5, log_price_mean, log_price_range * 0.08, log_price_range * 0.005, np.pi],
        [current_t + 8, 0.7, 8.0, log_price_mean, log_price_range * 0.06, -log_price_range * 0.01, np.pi/4],
    ]

    best_cost = np.inf
    best_params = None

    for x0 in initial_guesses:
        try:
            res = minimize(
                compute_cost,
                x0,
                args=(t_data, log_prices),
                method='L-BFGS-B',
                bounds=bounds,
                options={'maxiter': 50, 'ftol': 0.1}
            )

            if res.fun < best_cost:
                best_cost = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        return None

    try:
        tc, m, w, a, b, c, phi = best_params
        days_to_crash = tc - current_t

        fitted_curve = lppl_vectorized(t_data, tc, m, w, a, b, c, phi)
        ss_res = np.sum((log_prices - fitted_curve) ** 2)
        ss_tot = np.sum((log_prices - log_price_mean) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        is_danger = (0.1 < m < 0.9) and (6 < w < 13) and (days_to_crash < 10) and (r_squared > 0.7)

        return {
            "idx": idx,
            "is_danger": bool(is_danger),
            "days_to_crash": float(days_to_crash) if is_danger else None,
            "m": float(m),
            "w": float(w),
            "rmse": float(np.sqrt(best_cost / len(log_prices))),
            "r_squared": float(r_squared)
        }
    except Exception:
        return None
```

---

## src/cli/__init__.py

```python
# -*- coding: utf-8 -*-
```

---

## src/cli/main.py

```python
# -*- coding: utf-8 -*-
import logging
import sys
from datetime import datetime
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

ENTRYPOINT_ALIASES = {
    "wyckoff": "src.cli.wyckoff_analysis",
    "wyckoff-multimodal": "src.cli.wyckoff_multimodal_analysis",
}

def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])

def dispatch_subcommand(argv: Optional[List[str]] = None) -> Optional[int]:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return None
    module_path = ENTRYPOINT_ALIASES.get(args[0])
    if module_path is None:
        return None
    module = __import__(module_path, fromlist=["main"])
    sub_main: Callable[[], int] = getattr(module, "main")
    original_argv = sys.argv[:]
    sys.argv = [original_argv[0], *args[1:]]
    try:
        result = sub_main()
    except SystemExit as exc:
        result = exc.code if isinstance(exc.code, int) else 0
    finally:
        sys.argv = original_argv
    return 0 if result is None else result

def main(argv: Optional[List[str]] = None) -> int:
    dispatched = dispatch_subcommand(argv)
    if dispatched is not None:
        return dispatched
    setup_logging()
    logger.info("=" * 80)
    logger.info("LPPL模型扫描系统 - 主程序入口")
    logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)

    logger.info("[1/3] 数据管理模块 - 检查数据可用性")
    logger.info("-" * 60)
    data_manager = None
    computation = None
    html_generator = None

    try:
        from src.data.manager import DataManager, summarize_update_results
        data_manager = DataManager()
        data_results = data_manager.update_all_data()
        success_count, failed_count = summarize_update_results(data_results)
        logger.info(f"数据检查完成: 可用 {success_count} 个, 不可用 {failed_count} 个")
        if failed_count == len(data_results):
            logger.error("错误: 所有数据不可用，无法继续执行")
            return 1
        data_dict = data_manager.get_all_indices_data()
        if not data_dict:
            logger.error("错误: 无法加载任何有效数据")
            return 1
        logger.info(f"成功加载 {len(data_dict)} 个指数数据")
    except FileNotFoundError as e:
        logger.error(f"错误: 数据目录不存在 - {e}")
        return 1
    except ImportError as e:
        logger.error(f"错误: 模块导入失败 - {e}")
        return 1
    except Exception as e:
        logger.error(f"错误: 数据管理模块执行失败 - {type(e).__name__}: {e}")
        return 1

    logger.info("")
    logger.info("[2/3] 多线程计算模块 - 执行LPPL模型扫描")
    logger.info("-" * 60)

    try:
        from src.computation import LPPLComputation
        computation = LPPLComputation()
        report_data, params_data = computation.run_computation(data_dict, close_executor=True)
        if not report_data:
            logger.warning("警告: 计算模块未返回任何结果")
            markdown_path = None
            data_date = datetime.now().strftime('%Y%m%d')
        else:
            logger.info(f"计算完成: 生成 {len(report_data)} 条扫描结果")
            if params_data:
                data_dates = []
                for param in params_data:
                    last_date_str = param.get("last_date")
                    if last_date_str:
                        try:
                            from datetime import datetime as dt
                            data_date_val = dt.strptime(last_date_str, '%Y-%m-%d')
                            data_dates.append(data_date_val)
                        except ValueError:
                            pass
                if data_dates:
                    latest_data_date = max(data_dates)
                    data_date = latest_data_date.strftime('%Y%m%d')
                else:
                    data_date = datetime.now().strftime('%Y%m%d')
            else:
                data_date = datetime.now().strftime('%Y%m%d')
            markdown_path = computation.generate_markdown(report_data, data_date=data_date)
            if not markdown_path:
                logger.warning("警告: 无法生成Markdown报告")
            if params_data:
                params_path = computation.save_params_to_json(params_data, data_date=data_date)
                if params_path:
                    logger.info(f"参数文件保存成功: {params_path}")
    except ImportError as e:
        logger.error(f"错误: 计算模块导入失败 - {e}")
        return 1
    except MemoryError as e:
        logger.error(f"错误: 内存不足 - {e}")
        return 1
    except Exception as e:
        logger.error(f"错误: 计算模块执行失败 - {type(e).__name__}: {e}")
        return 1

    logger.info("")
    logger.info("[3/3] HTML生成模块 - 生成可视化报告")
    logger.info("-" * 60)

    try:
        from src.reporting import HTMLGenerator
        html_generator = HTMLGenerator()
        if not report_data:
            logger.warning("没有报告数据，跳过HTML生成")
        else:
            html_path = html_generator.generate_report(report_data, data_date=data_date)
            if html_path:
                logger.info(f"HTML报告生成成功: {html_path}")
            else:
                logger.warning("警告: HTML报告生成失败")
    except ImportError as e:
        logger.error(f"错误: HTML生成模块导入失败 - {e}")
        return 1
    except Exception as e:
        logger.error(f"错误: HTML生成模块执行失败 - {type(e).__name__}: {e}")
        return 1

    logger.info("")
    logger.info("=" * 80)
    logger.info("LPPL模型扫描系统 - 执行完成")
    logger.info(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    logger.info("执行完成! 您可以在浏览器中打开HTML文件查看详细结果。")
    return 0

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    exit_code = 0
    try:
        exit_code = main()
    except KeyboardInterrupt:
        logger.info("\n用户强制停止脚本")
        exit_code = 0
    except SystemExit as e:
        exit_code = e.code
    except Exception as e:
        logger.error(f"\n发生未捕获异常: {type(e).__name__}: {e}")
        exit_code = 1
    sys.exit(exit_code)
```

---

## src/cli/generate_optimal8_report.py

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path
from src.reporting import Optimal8ReadableReportGenerator

def _resolve_summary_csv(requested_path: str) -> Path:
    summary_path = Path(requested_path)
    if summary_path.exists():
        return summary_path
    summary_dir = summary_path.parent
    pattern = "walk_forward_optimal_8index_summary_*.csv"
    candidates = sorted(summary_dir.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"未找到输入文件: {requested_path}")

def main() -> None:
    parser = argparse.ArgumentParser(description="生成8指数风控结果可读报告（优化版）")
    parser.add_argument("--summary-csv", default="output/MA/summary/latest_walk_forward_optimal_8index_summary.csv", help="输入汇总CSV路径")
    parser.add_argument("--report-dir", default="output/MA/reports", help="输出报告目录")
    parser.add_argument("--plot-dir", default="output/MA/plots", help="输出图表目录")
    parser.add_argument("--output-stem", default="optimal8_human_friendly_report_v2", help="输出文件名前缀")
    args = parser.parse_args()
    try:
        summary_path = _resolve_summary_csv(args.summary_csv)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    generator = Optimal8ReadableReportGenerator(report_dir=args.report_dir, plot_dir=args.plot_dir)
    outputs = generator.generate(summary_csv=str(summary_path), output_stem=args.output_stem)
    print("报告生成完成:")
    for key, value in outputs.items():
        print(f"- {key}: {value}")

if __name__ == "__main__":
    main()
```

---

## src/cli/index_investment_analysis.py

```python
# -*- coding: utf-8 -*-
import argparse
import os
from typing import Dict
import pandas as pd
from src.cli.lppl_verify_v2 import SYMBOLS, create_config
from src.config import load_optimal_config, resolve_symbol_params
from src.data.manager import DataManager
from src.investment import BacktestConfig, InvestmentSignalConfig, generate_investment_signals, run_strategy_backtest
from src.reporting import InvestmentReportGenerator, PlotGenerator

def resolve_output_dirs(base_output_dir: str) -> Dict[str, str]:
    return {"base": base_output_dir, "raw": os.path.join(base_output_dir, "raw"),
            "plots": os.path.join(base_output_dir, "plots"), "reports": os.path.join(base_output_dir, "reports"),
            "summary": os.path.join(base_output_dir, "summary")}

def ensure_output_dirs(output_dirs: Dict[str, str]) -> None:
    for path in output_dirs.values():
        os.makedirs(path, exist_ok=True)

def main() -> None:
    parser = argparse.ArgumentParser(description="指数投资分析引擎")
    parser.add_argument("--symbol", "-s", default="000001.SH", help="指数代码")
    parser.add_argument("--ensemble", "-e", action="store_true", help="使用 Ensemble 模式")
    parser.add_argument("--start-date", help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--step", type=int, default=5, help="扫描步长")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--buy-fee", type=float, default=0.0003, help="买入手续费")
    parser.add_argument("--sell-fee", type=float, default=0.0003, help="卖出手续费")
    parser.add_argument("--slippage", type=float, default=0.0005, help="滑点")
    parser.add_argument("--output", "-o", default="output/investment", help="输出目录")
    parser.add_argument("--use-optimal-config", action="store_true", help="按指数从 YAML 读取最优 LPPL 参数")
    parser.add_argument("--optimal-config-path", default="config/optimal_params.yaml", help="最优参数 YAML 路径")
    args = parser.parse_args()
    if args.symbol not in SYMBOLS:
        raise SystemExit(f"未知指数代码: {args.symbol}")
    output_dirs = resolve_output_dirs(args.output)
    ensure_output_dirs(output_dirs)
    data_manager = DataManager()
    df = data_manager.get_data(args.symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据")
    lppl_config = create_config(args.ensemble)
    lppl_config.n_workers = 1
    lppl_config.optimizer = "lbfgsb" if lppl_config.optimizer == "de" else lppl_config.optimizer
    param_source = "default_cli"
    fallback = {"step": args.step, "window_range": list(lppl_config.window_range), "r2_threshold": lppl_config.r2_threshold,
                "danger_r2_offset": lppl_config.danger_r2_offset, "consensus_threshold": lppl_config.consensus_threshold,
                "danger_days": lppl_config.danger_days, "warning_days": lppl_config.warning_days, "watch_days": lppl_config.watch_days,
                "optimizer": lppl_config.optimizer, "lookahead_days": 60, "drop_threshold": 0.10, "ma_window": 5, "max_peaks": 10,
                "signal_model": "multi_factor_v1", "initial_position": 0.0, "positive_consensus_threshold": lppl_config.consensus_threshold,
                "negative_consensus_threshold": max(0.10, lppl_config.consensus_threshold - 0.05), "rebound_days": lppl_config.danger_days,
                "trend_fast_ma": 20, "trend_slow_ma": 120, "trend_slope_window": 10, "atr_period": 14, "atr_ma_window": 60,
                "vol_breakout_mult": 1.05, "buy_volatility_cap": 1.05, "drawdown_confirm_threshold": 0.05, "buy_vote_threshold": 3,
                "sell_vote_threshold": 3, "buy_confirm_days": 2, "sell_confirm_days": 2, "cooldown_days": 15, "require_trend_recovery_for_buy": True}
    if args.use_optimal_config:
        optimal_data = load_optimal_config(args.optimal_config_path)
        resolved, warnings = resolve_symbol_params(optimal_data, args.symbol, fallback)
        for message in warnings:
            print(f"⚠️ {message}")
        lppl_config.window_range = list(resolved["window_range"])
        lppl_config.optimizer = resolved["optimizer"]
        lppl_config.r2_threshold = resolved["r2_threshold"]
        lppl_config.danger_r2_offset = resolved["danger_r2_offset"]
        lppl_config.consensus_threshold = resolved["consensus_threshold"]
        lppl_config.danger_days = resolved["danger_days"]
        lppl_config.warning_days = resolved["warning_days"]
        lppl_config.watch_days = resolved["watch_days"]
        args.step = resolved["step"]
        param_source = resolved["param_source"]
    else:
        resolved = dict(fallback)
    signal_config = InvestmentSignalConfig.from_mapping(args.symbol, resolved)
    signal_df = generate_investment_signals(df=df, symbol=args.symbol, signal_config=signal_config, lppl_config=lppl_config,
                                            use_ensemble=args.ensemble, start_date=args.start_date, end_date=args.end_date, scan_step=args.step)
    signal_df["param_source"] = param_source
    equity_df, trades_df, summary = run_strategy_backtest(signal_df, BacktestConfig(initial_capital=args.initial_capital, buy_fee=args.buy_fee,
                                                                                        sell_fee=args.sell_fee, slippage=args.slippage,
                                                                                        start_date=args.start_date, end_date=args.end_date))
    summary["name"] = SYMBOLS[args.symbol]
    summary["mode"] = "ensemble" if args.ensemble else "single_window"
    summary["param_source"] = param_source
    summary["step"] = args.step
    summary_df = pd.DataFrame([summary])
    mode_slug = "ensemble" if args.ensemble else "single_window"
    symbol_slug = args.symbol.replace(".", "_")
    signals_path = os.path.join(output_dirs["raw"], f"signals_{symbol_slug}_{mode_slug}.csv")
    equity_path = os.path.join(output_dirs["raw"], f"equity_{symbol_slug}_{mode_slug}.csv")
    trades_path = os.path.join(output_dirs["raw"], f"trades_{symbol_slug}_{mode_slug}.csv")
    summary_path = os.path.join(output_dirs["summary"], f"summary_{symbol_slug}_{mode_slug}.csv")
    signal_df.to_csv(signals_path, index=False)
    equity_df.to_csv(equity_path, index=False)
    trades_df.to_csv(trades_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    plot_generator = PlotGenerator(output_dir=output_dirs["plots"])
    metadata = {"symbol": args.symbol, "name": SYMBOLS[args.symbol], "start_date": summary["start_date"], "end_date": summary["end_date"],
                "max_drawdown": summary["max_drawdown"], "total_return": summary["total_return"]}
    overview_path = plot_generator.generate_strategy_overview_plot(equity_df, trades_df, metadata)
    drawdown_path = plot_generator.generate_strategy_drawdown_plot(equity_df, metadata)
    report_generator = InvestmentReportGenerator(output_dir=output_dirs["reports"])
    plot_paths = {"核心图表": [overview_path, drawdown_path]}
    markdown_path = report_generator.generate_markdown_report(summary_df, plot_paths)
    html_path = report_generator.generate_html_report(summary_df, plot_paths)
    print(f"逐日信号已保存: {signals_path}")
    print(f"净值明细已保存: {equity_path}")
    print(f"交易流水已保存: {trades_path}")
    print(f"汇总统计已保存: {summary_path}")
    print(f"Markdown 报告已保存: {markdown_path}")
    print(f"HTML 报告已保存: {html_path}")

if __name__ == "__main__":
    main()
```

---

## src/cli/lppl_verify_v2.py

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LPPL 算法验证程序 V2 (专业修正版)

修正内容：
1. 删除了重复定义的 print_summary 函数
2. 重构了 Ensemble 模式的窗口矩阵 (从 3 个窗口扩大到 12 个窗口)
3. 强制使用差分进化算法(DE)作为全局优化器

Ensemble 模式参数 (对齐 target.md):
- 窗口范围: 40-150天 (共12个窗口)
- 共识阈值: 25% (12窗口中至少3个达成共识)
- 强制使用 DE 优化器

使用方法:
    python lppl_verify_v2.py --all
    python lppl_verify_v2.py --symbol 000001.SH
    python lppl_verify_v2.py --symbol 000001.SH --ensemble
"""

import argparse
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# 添加项目根路径（兼容直接运行 src/cli/*.py）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 导入引擎模块
from src.config import load_optimal_config, resolve_symbol_params
from src.constants import (
    PLOTS_OUTPUT_DIR,
    RAW_OUTPUT_DIR,
    REPORTS_OUTPUT_DIR,
    SUMMARY_OUTPUT_DIR,
    VERIFY_OUTPUT_DIR,
)
from src.lppl_engine import (
    LPPLConfig,
    analyze_peak,
    analyze_peak_ensemble,
    find_local_highs,
)
from src.reporting import PlotGenerator, VerificationReportGenerator

# CPU核心数
CPU_CORES = max(1, (os.cpu_count() or 4) - 2)

# 指数配置 (与verify_lppl.py一致)
SYMBOLS = {
    '000001.SH': '上证综指',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
    '000016.SH': '上证50',
    '000300.SH': '沪深300',
    '000905.SH': '中证500',
    '000852.SH': '中证1000',
    '932000.SH': '中证2000',
}


def get_mode_metadata(use_ensemble: bool) -> dict:
    if use_ensemble:
        return {
            "mode_slug": "ensemble",
            "mode_label": "Ensemble 多窗口共识",
            "window_label": "40-150天 (12窗口)",
            "report_title": "LPPL 算法验证报告 V2 - Ensemble 模式",
            "results_filename": "peak_verification_v2_ensemble.csv",
            "report_filename": "verification_report_v2_ensemble.md",
        }

    return {
        "mode_slug": "single_window",
        "mode_label": "单窗口独立",
        "window_label": "40-80天 (3窗口)",
        "report_title": "LPPL 算法验证报告 V2 - 单窗口模式",
        "results_filename": "peak_verification_v2_single_window.csv",
        "report_filename": "verification_report_v2_single_window.md",
    }


def resolve_output_dirs(base_output_dir: str = None) -> dict:
    if base_output_dir:
        verify_dir = base_output_dir
        return {
            "base": verify_dir,
            "raw": os.path.join(verify_dir, "raw"),
            "plots": os.path.join(verify_dir, "plots"),
            "reports": os.path.join(verify_dir, "reports"),
            "summary": os.path.join(verify_dir, "summary"),
        }

    return {
        "base": VERIFY_OUTPUT_DIR,
        "raw": RAW_OUTPUT_DIR,
        "plots": PLOTS_OUTPUT_DIR,
        "reports": REPORTS_OUTPUT_DIR,
        "summary": SUMMARY_OUTPUT_DIR,
    }


def ensure_output_dirs(output_dirs: dict) -> None:
    for path in output_dirs.values():
        os.makedirs(path, exist_ok=True)


def create_config(use_ensemble: bool = False) -> LPPLConfig:
    """
    创建 LPPL 配置 - 对齐 target.md 参数
    
    真正的 Ensemble 需要足够的样本量。
    使用 40 到 150 天，步长 10 天，共计 12 个观察窗口。
    
    Args:
        use_ensemble: 是否使用 Ensemble 模式
    
    Returns:
        LPPLConfig 对象
    """
    # 12个窗口: 40,50,60,70,80,90,100,110,120,130,140,150
    w_range = list(range(40, 160, 10)) if use_ensemble else list(range(40, 100, 20))

    return LPPLConfig(
        window_range=w_range,
        optimizer='de',  # 强制使用差分进化算法(DE)
        maxiter=100,     # 增加迭代次数
        popsize=15,     # 保持足够种群
        tol=0.05,       # 适度容忍
        m_bounds=(0.1, 0.9),
        w_bounds=(6.0, 13.0),
        tc_bound=(1, 60),
        r2_threshold=0.6 if use_ensemble else 0.5,
        danger_r2_offset=0.0,
        danger_days=20,
        warning_days=60,
        # 12个窗口中，至少需要3个(25%)达成共识，才能触发信号
        consensus_threshold=0.25 if use_ensemble else 0.0,
        n_workers=CPU_CORES,
    )


def run_verification(symbol: str, name: str,
                    use_ensemble: bool = False,
                    scan_step: int = 5,
                    ma_window: int = 5,
                    min_peak_drop: float = 0.10,
                    min_peak_gap: int = 120,
                    max_peaks: int = 10,
                    config_override: dict = None,
                    param_source: str = "default_cli"):
    """
    运行单个指数的验证
    
    Args:
        symbol: 指数代码
        name: 指数名称
        use_ensemble: 是否使用 Ensemble 模式 (12窗口多窗口共识)
        scan_step: 扫描步长
        ma_window: 移动平均窗口
        min_peak_drop: 最小跌幅
        min_peak_gap: 最小间隔
        max_peaks: 最多分析的高点数
    
    Returns:
        list of dict: 验证结果
    """
    from src.data.manager import DataManager
    mode_meta = get_mode_metadata(use_ensemble)

    print(f"\n{'='*80}")
    print(f"{name} ({symbol}) | 模式: {mode_meta['mode_label']}")
    print(f"{'='*80}")

    # 获取数据
    dm = DataManager()
    df = dm.get_data(symbol)

    if df is None or df.empty:
        print("  无数据")
        return []

    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])

    date_range = f"{df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}"
    print(f"  数据: {len(df)}天 ({date_range})")

    # 查找局部最高点
    highs = find_local_highs(df, min_gap=min_peak_gap, min_drop_pct=min_peak_drop)

    print(f"  找到 {len(highs)} 个有效高点:")
    for h in highs:
        h['date'] = pd.to_datetime(h['date'])
        print(f"    {h['date'].strftime('%Y-%m-%d')}: {h['price']:.2f} (下跌{h['drop_pct']*100:.1f}%)")

    # 限制分析数量
    highs_sorted = sorted(highs, key=lambda x: x['drop_pct'], reverse=True)[:max_peaks]
    print(f"\n  分析跌幅最大的 {len(highs_sorted)} 个高点:")

    # 创建配置
    config = create_config(use_ensemble)
    if config_override:
        config.window_range = list(config_override.get("window_range", config.window_range))
        config.optimizer = str(config_override.get("optimizer", config.optimizer))
        config.r2_threshold = float(config_override.get("r2_threshold", config.r2_threshold))
        config.danger_r2_offset = float(config_override.get("danger_r2_offset", config.danger_r2_offset))
        config.consensus_threshold = float(
            config_override.get("consensus_threshold", config.consensus_threshold)
        )
        config.danger_days = int(config_override.get("danger_days", config.danger_days))
        config.warning_days = int(config_override.get("warning_days", config.warning_days))
        config.watch_days = int(config_override.get("watch_days", config.watch_days))
        scan_step = int(config_override.get("step", scan_step))
        ma_window = int(config_override.get("ma_window", ma_window))
        max_peaks = int(config_override.get("max_peaks", max_peaks))

    print(
        "  生效参数: "
        f"source={param_source}, step={scan_step}, ma={ma_window}, max_peaks={max_peaks}, "
        f"windows={config.window_range[0]}-{config.window_range[-1]} ({len(config.window_range)}), "
        f"optimizer={config.optimizer}, r2={config.r2_threshold:.2f}, "
        f"consensus={config.consensus_threshold:.2f}, danger_days={config.danger_days}"
    )

    # 分析每个高点
    results = []
    for peak in highs_sorted:
        print(f"\n  分析高点: {peak['date'].strftime('%Y-%m-%d')} ({peak['price']:.2f})")

        analyze_func = analyze_peak_ensemble if use_ensemble else analyze_peak
        result = analyze_func(
            df,
            peak['idx'],
            config.window_range,
            scan_step=scan_step,
            ma_window=ma_window,
            config=config
        )

        if result is not None:
            result['symbol'] = symbol
            result['name'] = name
            result['drop_pct'] = peak['drop_pct']
            result["param_source"] = param_source
            result["step"] = scan_step
            result["ma_window"] = ma_window
            result["optimizer"] = config.optimizer
            result["window_count"] = len(config.window_range)
            result["window_min"] = min(config.window_range)
            result["window_max"] = max(config.window_range)
            result["r2_threshold"] = config.r2_threshold
            result["consensus_threshold"] = config.consensus_threshold
            result["danger_days"] = config.danger_days
            results.append(result)

            if result['detected']:
                print(f"    ✅ 检测到预警: {result['first_danger_days']}天前, R²={result['first_danger_r2']:.3f}")
            else:
                print("    ❌ 未检测到预警")
        else:
            print("    ⚠️ 分析失败")

    return results


def print_summary(results_df: pd.DataFrame):
    """打印验证结果汇总"""
    print("\n" + "="*100)
    print("验证结果汇总")
    print("="*100)

    total = len(results_df)
    detected = results_df['detected'].sum()
    detection_rate = detected / total * 100 if total > 0 else 0

    print(f"\n总高点数: {total}")
    print(f"检测到预警: {detected} ({detection_rate:.1f}%)")

    # 按指数统计
    print(f"\n{'指数':<10} {'高点数':>6} {'检测数':>6} {'检测率':>8} {'平均天数':>10}")
    print("-"*50)

    for name in results_df['name'].unique():
        idx_data = results_df[results_df['name'] == name]
        idx_total = len(idx_data)
        idx_detected = idx_data['detected'].sum()
        idx_rate = idx_detected / idx_total * 100 if idx_total > 0 else 0

        detected_data = idx_data[idx_data['detected']]
        avg_days = detected_data['first_danger_days'].mean() if len(detected_data) > 0 else np.nan

        days_str = f"{avg_days:.0f}d" if pd.notna(avg_days) else "N/A"
        print(f"{name:<10} {idx_total:>6} {idx_detected:>6} {idx_rate:>7.1f}% {days_str:>10}")

    # 高置信度案例
    high_conf = results_df[(results_df['detected']) & (results_df['first_danger_r2'] > 0.8)]
    print(f"\n高置信度案例 (R²>0.8): {len(high_conf)}个")

    if len(high_conf) > 0:
        print(f"\n{'指数':<10} {'高点日期':<12} {'高点价格':>10} {'预警天数':>10} {'R²':>6} {'m':>6} {'w':>6}")
        print("-"*70)
        for _, row in high_conf.sort_values('first_danger_r2', ascending=False).iterrows():
            m_val = row['first_danger_m'] if pd.notna(row['first_danger_m']) else 0
            w_val = row['first_danger_w'] if pd.notna(row['first_danger_w']) else 0
            print(f"{row['name']:<10} {row['peak_date']:<12} {row['peak_price']:>10.2f} {row['first_danger_days']:>10.0f} {row['first_danger_r2']:>6.3f} {m_val:>6.3f} {w_val:>6.3f}")


def save_results(all_results: list, output_dir: str = "output/MA",
                 use_ensemble: bool = False) -> pd.DataFrame:
    """保存结果到CSV"""
    if not all_results:
        return None

    output_dirs = resolve_output_dirs(output_dir)
    ensure_output_dirs(output_dirs)

    results_df = pd.DataFrame(all_results)
    mode_meta = get_mode_metadata(use_ensemble)

    for result in all_results:
        timeline = result.get("timeline")
        if not timeline:
            continue

        raw_filename = (
            f"raw_{result['symbol'].replace('.', '_')}_"
            f"{mode_meta['mode_slug']}_{result['peak_date']}.parquet"
        )
        raw_path = os.path.join(output_dirs["raw"], raw_filename)
        pd.DataFrame(timeline).to_parquet(raw_path, index=False)

    # 保存原始结果
    output_path = os.path.join(output_dirs["summary"], mode_meta["results_filename"])
    summary_df = results_df.drop(columns=["timeline"], errors="ignore")
    summary_df.to_csv(output_path, index=False)
    print(f"\n结果已保存到 {output_path}")

    return summary_df


def generate_verification_artifacts(
    all_results: list,
    output_dir: str = "output/MA",
    use_ensemble: bool = False,
) -> dict:
    if not all_results:
        return {}

    mode_meta = get_mode_metadata(use_ensemble)
    output_dirs = resolve_output_dirs(output_dir)
    ensure_output_dirs(output_dirs)

    summary_df = save_results(all_results, output_dir, use_ensemble)
    plot_generator = PlotGenerator(output_dirs["plots"])
    report_generator = VerificationReportGenerator(output_dirs["reports"])

    plot_paths = {
        "案例价格时间线图": [],
        "案例 Ensemble 共识图": [],
        "案例预测时间离散图": [],
        "汇总统计图": [],
    }

    for result in all_results:
        timeline = result.get("timeline")
        if not timeline:
            continue

        timeline_df = pd.DataFrame(timeline)
        metadata = {
            "symbol": result["symbol"],
            "name": result["name"],
            "peak_date": result["peak_date"],
            "mode": result.get("mode", mode_meta["mode_slug"]),
            "first_danger_days": result.get("first_danger_days"),
        }

        timeline_plot = plot_generator.generate_price_timeline_plot(timeline_df, metadata)
        plot_paths["案例价格时间线图"].append(timeline_plot)

        if use_ensemble and "consensus_rate" in timeline_df.columns:
            consensus_plot = plot_generator.generate_consensus_plot(
                timeline_df,
                metadata,
                consensus_threshold=create_config(True).consensus_threshold,
            )
            plot_paths["案例 Ensemble 共识图"].append(consensus_plot)

        if use_ensemble and {"predicted_crash_days", "tc_std"}.issubset(timeline_df.columns):
            dispersion_plot = plot_generator.generate_crash_dispersion_plot(timeline_df, metadata)
            plot_paths["案例预测时间离散图"].append(dispersion_plot)

    summary_plot = plot_generator.generate_summary_statistics_plot(summary_df)
    plot_paths["汇总统计图"].append(summary_plot)

    markdown_path = report_generator.generate_markdown_report(
        summary_df=summary_df,
        use_ensemble=use_ensemble,
        plot_paths=plot_paths,
        filename=mode_meta["report_filename"],
    )
    html_filename = mode_meta["report_filename"].replace(".md", ".html")
    html_path = report_generator.generate_html_report(
        summary_df=summary_df,
        use_ensemble=use_ensemble,
        plot_paths=plot_paths,
        filename=html_filename,
    )

    return {
        "summary_df": summary_df,
        "plot_paths": plot_paths,
        "markdown_path": markdown_path,
        "html_path": html_path,
        "output_dirs": output_dirs,
    }


def generate_report(results_df: pd.DataFrame, output_path: str, use_ensemble: bool):
    """生成 Markdown 报告"""
    mode_meta = get_mode_metadata(use_ensemble)
    lines = []
    lines.append(f"# {mode_meta['report_title']}")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**模式**: {mode_meta['mode_label']}")
    lines.append("**优化器**: Differential Evolution (DE)")
    lines.append("")
    lines.append("**参数**:")
    lines.append(f"- 窗口范围: {mode_meta['window_label']}")
    lines.append("- 扫描步长: 5 天")
    lines.append("- 移动平均: 5 天")
    lines.append("- 风险判定: (0.1 < m < 0.9) AND (6 < w < 13) AND (days < 20) AND (R² > 0.5)")
    if use_ensemble:
        lines.append("- 共识阈值: 25% (12窗口中至少3个)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 汇总统计
    total = len(results_df)
    detected = results_df['detected'].sum()
    detection_rate = detected / total * 100 if total > 0 else 0

    lines.append("## 一、验证结果汇总")
    lines.append("")
    lines.append(f"- **总高点数**: {total}")
    lines.append(f"- **检测到预警**: {detected} ({detection_rate:.1f}%)")
    lines.append("")

    # 按指数统计表
    lines.append("| 指数 | 高点数 | 检测数 | 检测率 |")
    lines.append("|:-----|-------:|-------:|-------:|")

    for name in results_df['name'].unique():
        idx_data = results_df[results_df['name'] == name]
        idx_total = len(idx_data)
        idx_detected = idx_data['detected'].sum()
        idx_rate = idx_detected / idx_total * 100 if idx_total > 0 else 0
        lines.append(f"| {name} | {idx_total} | {idx_detected} | {idx_rate:.1f}% |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 高置信度案例
    high_conf = results_df[(results_df['detected']) & (results_df['first_danger_r2'] > 0.8)]
    lines.append("## 二、高置信度案例 (R²>0.8)")
    lines.append("")

    if len(high_conf) > 0:
        lines.append("| 指数 | 高点日期 | 高点价格 | 预警天数 | R² | m | w |")
        lines.append("|:-----|:---------|---------:|---------:|----:|----:|----:|")

        for _, row in high_conf.sort_values('first_danger_r2', ascending=False).iterrows():
            m_val = f"{row['first_danger_m']:.3f}" if pd.notna(row['first_danger_m']) else "N/A"
            w_val = f"{row['first_danger_w']:.3f}" if pd.notna(row['first_danger_w']) else "N/A"
            lines.append(f"| {row['name']} | {row['peak_date']} | {row['peak_price']:.2f} | {row['first_danger_days']:.0f} | {row['first_danger_r2']:.3f} | {m_val} | {w_val} |")
    else:
        lines.append("无高置信度案例")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 三、结论")
    lines.append("")
    lines.append(f"本次验证共分析 {total} 个历史高点，")
    lines.append(f"检测到预警信号 {detected} 个，")
    lines.append(f"整体检测率为 {detection_rate:.1f}%。")

    if len(high_conf) > 0:
        high_conf_rate = len(high_conf) / detected * 100 if detected > 0 else 0
        lines.append(f"其中高置信度案例 (R²>0.8) {len(high_conf)} 个，")
        lines.append(f"占检测到信号的 {high_conf_rate:.1f}%。")

    # 写入文件
    content = "\n".join(lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"报告已保存到 {output_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='LPPL 算法验证程序 V2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python lppl_verify_v2.py --all
  python lppl_verify_v2.py --symbol 000001.SH
  python lppl_verify_v2.py --symbol 000001.SH --ensemble
        """
    )

    parser.add_argument('--symbol', '-s', default=None,
                        help='指数代码 (如 000001.SH)')
    parser.add_argument('--all', '-a', action='store_true',
                        help='验证所有8个指数')
    parser.add_argument('--ensemble', '-e', action='store_true',
                        help='使用 Ensemble 模式 (12窗口多窗口共识)')
    parser.add_argument('--max-peaks', '-m', type=int, default=10,
                        help='每个指数最多分析的高点数 (默认10)')
    parser.add_argument('--step', type=int, default=5,
                        help='扫描步长 (默认: 5)')
    parser.add_argument('--ma', type=int, default=5,
                        help='移动平均窗口 (默认: 5)')
    parser.add_argument('--output', '-o', default='output/MA',
                        help='输出目录 (默认 output/MA)')
    parser.add_argument(
        "--use-optimal-config",
        action="store_true",
        help="按指数从YAML读取最优参数（缺失配置会回退默认值）",
    )
    parser.add_argument(
        "--optimal-config-path",
        default="config/optimal_params.yaml",
        help="最优参数YAML路径",
    )

    args = parser.parse_args()
    mode_meta = get_mode_metadata(args.ensemble)

    # 参数显示
    print(f"\n{'='*60}")
    print("LPPL 算法验证程序 V2")
    print(f"{'='*60}")
    print("参数配置:")
    print(f"  窗口范围: {mode_meta['window_label']}")
    print(f"  扫描步长: {args.step}天")
    print(f"  移动平均: {args.ma}天")
    print("  最小跌幅: 10%")
    print("  最小间隔: 120天")
    print(f"  模式: {mode_meta['mode_label']}")
    print("  优化器: Differential Evolution (DE)")
    print(f"{'='*60}\n")

    # 选择要验证的指数
    if args.all:
        symbols_to_verify = SYMBOLS
    elif args.symbol:
        if args.symbol not in SYMBOLS:
            print(f"未知的指数代码: {args.symbol}")
            print(f"可用指数: {', '.join(SYMBOLS.keys())}")
            return
        symbols_to_verify = {args.symbol: SYMBOLS[args.symbol]}
    else:
        # 默认测试上证综指
        symbols_to_verify = {'000001.SH': '上证综指'}

    # 运行验证
    all_results = []
    optimal_data = None
    if args.use_optimal_config:
        try:
            optimal_data = load_optimal_config(args.optimal_config_path)
            print(f"已加载最优参数配置: {args.optimal_config_path}")
        except Exception as e:
            print(f"⚠️ 最优参数加载失败，整体回退默认参数: {e}")

    for symbol, name in symbols_to_verify.items():
        config_override = None
        param_source = "default_cli"
        if args.use_optimal_config and optimal_data is not None:
            base_config = create_config(args.ensemble)
            fallback = {
                "step": args.step,
                "window_range": list(base_config.window_range),
                "r2_threshold": base_config.r2_threshold,
                "consensus_threshold": base_config.consensus_threshold,
                "danger_days": base_config.danger_days,
                "warning_days": base_config.warning_days,
                "optimizer": base_config.optimizer,
                "lookahead_days": 60,
                "drop_threshold": 0.10,
                "ma_window": args.ma,
                "max_peaks": args.max_peaks,
            }
            config_override, warnings = resolve_symbol_params(optimal_data, symbol, fallback)
            for msg in warnings:
                print(f"⚠️ {msg}")
            param_source = config_override.get("param_source", "default_fallback")

        results = run_verification(
            symbol, name,
            use_ensemble=args.ensemble,
            scan_step=args.step,
            ma_window=args.ma,
            max_peaks=args.max_peaks,
            config_override=config_override,
            param_source=param_source,
        )
        all_results.extend(results)

    # 打印汇总
    if all_results:
        results_df = pd.DataFrame(all_results)
        print_summary(results_df)

        artifacts = generate_verification_artifacts(all_results, args.output, args.ensemble)
        if artifacts:
            print(f"\nMarkdown 报告已生成: {artifacts['markdown_path']}")
            print(f"HTML 报告已生成: {artifacts['html_path']}")
    else:
        print("\n无验证结果")


if __name__ == "__main__":
    main()
```

---

## src/cli/lppl_walk_forward.py

```python
# -*- coding: utf-8 -*-
import argparse
import os
import pandas as pd
from src.cli.lppl_verify_v2 import SYMBOLS, create_config
from src.config import load_optimal_config, resolve_symbol_params
from src.constants import SUMMARY_OUTPUT_DIR
from src.data.manager import DataManager
from src.verification import run_walk_forward

def main() -> None:
    parser = argparse.ArgumentParser(description="LPPL Walk-Forward 盲测")
    parser.add_argument("--symbol", "-s", default="000001.SH", help="指数代码")
    parser.add_argument("--ensemble", "-e", action="store_true", help="使用 Ensemble 模式")
    parser.add_argument("--step", type=int, default=5, help="扫描步长")
    parser.add_argument("--lookahead", type=int, default=60, help="未来观察天数")
    parser.add_argument("--drop-threshold", type=float, default=0.10, help="未来跌幅阈值")
    parser.add_argument("--output", "-o", default=SUMMARY_OUTPUT_DIR, help="输出目录")
    parser.add_argument("--use-optimal-config", action="store_true", help="按指数从YAML读取最优参数")
    parser.add_argument("--optimal-config-path", default="config/optimal_params.yaml", help="最优参数YAML路径")
    args = parser.parse_args()
    if args.symbol not in SYMBOLS:
        raise SystemExit(f"未知指数代码: {args.symbol}")
    os.makedirs(args.output, exist_ok=True)
    dm = DataManager()
    df = dm.get_data(args.symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据")
    config = create_config(args.ensemble)
    scan_step = args.step
    lookahead_days = args.lookahead
    drop_threshold = args.drop_threshold
    param_source = "default_cli"
    if args.use_optimal_config:
        fallback = {"step": args.step, "window_range": list(config.window_range), "r2_threshold": config.r2_threshold,
                    "danger_r2_offset": config.danger_r2_offset, "consensus_threshold": config.consensus_threshold,
                    "danger_days": config.danger_days, "warning_days": config.warning_days, "watch_days": config.watch_days,
                    "optimizer": config.optimizer, "lookahead_days": args.lookahead, "drop_threshold": args.drop_threshold}
        try:
            optimal_data = load_optimal_config(args.optimal_config_path)
            resolved, warnings = resolve_symbol_params(optimal_data, args.symbol, fallback)
            for msg in warnings:
                print(f"⚠️ {msg}")
            config.window_range = list(resolved["window_range"])
            config.optimizer = resolved["optimizer"]
            config.r2_threshold = resolved["r2_threshold"]
            config.danger_r2_offset = resolved["danger_r2_offset"]
            config.consensus_threshold = resolved["consensus_threshold"]
            config.danger_days = resolved["danger_days"]
            config.warning_days = resolved["warning_days"]
            config.watch_days = resolved["watch_days"]
            scan_step = resolved["step"]
            lookahead_days = resolved["lookahead_days"]
            drop_threshold = resolved["drop_threshold"]
            param_source = resolved["param_source"]
        except Exception as e:
            print(f"⚠️ 最优参数文件加载失败，使用默认参数: {e}")
            param_source = "default_fallback"
    print(f"生效参数: source={param_source}, step={scan_step}, windows={config.window_range[0]}-{config.window_range[-1]} ({len(config.window_range)})")
    records_df, summary = run_walk_forward(df=df, symbol=args.symbol, window_range=config.window_range, config=config,
                                           scan_step=scan_step, lookahead_days=lookahead_days, drop_threshold=drop_threshold, use_ensemble=args.ensemble)
    records_df["param_source"] = param_source
    mode_slug = "ensemble" if args.ensemble else "single_window"
    records_path = os.path.join(args.output, f"walk_forward_{args.symbol.replace('.', '_')}_{mode_slug}.csv")
    summary_path = os.path.join(args.output, f"walk_forward_{args.symbol.replace('.', '_')}_{mode_slug}_summary.csv")
    summary["param_source"] = param_source
    summary["step"] = scan_step
    summary["window_min"] = min(config.window_range)
    summary["window_max"] = max(config.window_range)
    summary["window_count"] = len(config.window_range)
    records_df.to_csv(records_path, index=False)
    pd.DataFrame([summary]).to_csv(summary_path, index=False)
    print(f"逐日记录已保存: {records_path}")
    print(f"汇总统计已保存: {summary_path}")

if __name__ == "__main__":
    main()
```

---

## src/cli/tune_signal_model.py

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
from datetime import datetime
from itertools import product
from typing import Dict, Iterable, List, Tuple

import pandas as pd

from src.cli.lppl_verify_v2 import SYMBOLS, create_config
from src.config import load_optimal_config, resolve_symbol_params
from src.constants import INDICES
from src.data.manager import DataManager
from src.investment import (
    BacktestConfig,
    InvestmentSignalConfig,
    generate_investment_signals,
    run_strategy_backtest,
    score_signal_tuning_results,
)
from src.reporting import Optimal8ReadableReportGenerator


def parse_float_list(value: str) -> List[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def parse_int_list(value: str) -> List[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def _resolve_requested_symbols(args: argparse.Namespace) -> List[str]:
    if getattr(args, "symbols", None):
        symbols = [item.strip() for item in str(args.symbols).split(",") if item.strip()]
    elif args.symbol:
        symbols = [args.symbol]
    elif args.all:
        symbols = list(INDICES.keys())
    else:
        raise SystemExit("请提供 --symbol、--symbols 或 --all")

    unknown = [symbol for symbol in symbols if symbol not in SYMBOLS]
    if unknown:
        raise SystemExit(f"未知指数代码: {unknown}")
    return symbols


def _fallback_config(base_step: int, use_ensemble: bool) -> Dict[str, object]:
    lppl_config = create_config(use_ensemble)
    lppl_config.optimizer = "lbfgsb" if lppl_config.optimizer == "de" else lppl_config.optimizer
    return {
        "step": base_step,
        "window_range": list(lppl_config.window_range),
        "r2_threshold": lppl_config.r2_threshold,
        "danger_r2_offset": lppl_config.danger_r2_offset,
        "consensus_threshold": lppl_config.consensus_threshold,
        "danger_days": lppl_config.danger_days,
        "warning_days": lppl_config.warning_days,
        "watch_days": lppl_config.watch_days,
        "optimizer": lppl_config.optimizer,
        "lookahead_days": 60,
        "drop_threshold": 0.10,
        "ma_window": 5,
        "max_peaks": 10,
        "signal_model": "multi_factor_v1",
        "initial_position": 0.0,
        "positive_consensus_threshold": lppl_config.consensus_threshold,
        "negative_consensus_threshold": max(0.10, lppl_config.consensus_threshold - 0.05),
        "rebound_days": lppl_config.danger_days,
        "trend_fast_ma": 20,
        "trend_slow_ma": 120,
        "trend_slope_window": 10,
        "atr_period": 14,
        "atr_ma_window": 60,
        "vol_breakout_mult": 1.05,
        "buy_volatility_cap": 1.05,
        "drawdown_confirm_threshold": 0.05,
        "buy_vote_threshold": 3,
        "sell_vote_threshold": 3,
        "buy_confirm_days": 2,
        "sell_confirm_days": 2,
        "cooldown_days": 15,
        "require_trend_recovery_for_buy": True,
    }


def _resolve_configs(
    symbol: str,
    optimal_config_path: str,
    base_step: int,
    use_ensemble: bool,
) -> Tuple[Dict[str, object], object]:
    lppl_config = create_config(use_ensemble)
    lppl_config.n_workers = -1  # 自动使用所有CPU核心
    lppl_config.optimizer = "lbfgsb" if lppl_config.optimizer == "de" else lppl_config.optimizer
    fallback = _fallback_config(base_step, use_ensemble)
    optimal_data = load_optimal_config(optimal_config_path)
    resolved, warnings = resolve_symbol_params(optimal_data, symbol, fallback)
    for message in warnings:
        print(f"⚠️ {message}")

    lppl_config.window_range = list(resolved["window_range"])
    lppl_config.optimizer = resolved["optimizer"]
    lppl_config.r2_threshold = resolved["r2_threshold"]
    lppl_config.danger_r2_offset = resolved["danger_r2_offset"]
    lppl_config.consensus_threshold = resolved["consensus_threshold"]
    lppl_config.danger_days = resolved["danger_days"]
    lppl_config.warning_days = resolved["warning_days"]
    lppl_config.watch_days = resolved["watch_days"]
    return resolved, lppl_config


def _candidate_grid(
    args: argparse.Namespace,
) -> Iterable[Tuple[float, float, int, int, int, int, float, float, int, float, bool, int, float, float, float, bool]]:
    first_cross_only = getattr(args, "first_cross_only", "false")
    cross_persistence = getattr(args, "cross_persistence", "1")
    atr_deadband = getattr(args, "atr_deadband", "0.0")
    slope_threshold = getattr(args, "slope_threshold", "0.0")
    atr_stop_mult = getattr(args, "atr_stop_mult", "0.0")
    return product(
        parse_float_list(args.positive_offsets),
        parse_float_list(args.negative_offsets),
        parse_int_list(args.sell_votes),
        parse_int_list(args.buy_votes),
        parse_int_list(args.sell_confirms),
        parse_int_list(args.buy_confirms),
        parse_float_list(args.vol_breakout_grid),
        parse_float_list(args.drawdown_grid),
        parse_int_list(args.cooldown_grid),
        parse_float_list(args.buy_volatility_cap_grid),
        parse_bool_list(first_cross_only),
        parse_int_list(cross_persistence),
        parse_float_list(atr_deadband),
        parse_float_list(slope_threshold),
        parse_float_list(atr_stop_mult),
    )


def parse_bool_list(value: str) -> List[bool]:
    result = []
    for x in value.split(","):
        x = x.strip().lower()
        if x in ("true", "1", "yes", "on"):
            result.append(True)
        elif x in ("false", "0", "no", "off"):
            result.append(False)
        else:
            raise ValueError(f"Invalid boolean value: {x}")
    return result


def _run_single_symbol(
    symbol: str,
    args: argparse.Namespace,
    output_dir: str,
) -> Dict[str, object]:
    resolved, lppl_config = _resolve_configs(symbol, args.optimal_config_path, args.step, args.ensemble)

    dm = DataManager()
    df = dm.get_data(symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {symbol} 数据")

    rows: List[Dict[str, object]] = []
    base_positive = float(resolved["positive_consensus_threshold"])
    base_negative = float(resolved["negative_consensus_threshold"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for idx, candidate in enumerate(_candidate_grid(args), start=1):
        (
            positive_offset,
            negative_offset,
            sell_votes,
            buy_votes,
            sell_confirm_days,
            buy_confirm_days,
            vol_breakout_mult,
            drawdown_confirm_threshold,
            cooldown_days,
            buy_volatility_cap,
            first_cross_only,
            cross_persistence,
            atr_deadband,
            slope_threshold,
            atr_stop_mult,
        ) = candidate
        candidate_mapping = dict(resolved)
        candidate_mapping.update(
            {
                "positive_consensus_threshold": min(max(base_positive + positive_offset, 0.05), 0.95),
                "negative_consensus_threshold": min(max(base_negative + negative_offset, 0.05), 0.95),
                "sell_vote_threshold": sell_votes,
                "buy_vote_threshold": buy_votes,
                "sell_confirm_days": sell_confirm_days,
                "buy_confirm_days": buy_confirm_days,
                "vol_breakout_mult": vol_breakout_mult,
                "drawdown_confirm_threshold": drawdown_confirm_threshold,
                "cooldown_days": cooldown_days,
                "buy_volatility_cap": buy_volatility_cap,
                "signal_model": "multi_factor_v1",
                "first_cross_only": first_cross_only,
                "cross_persistence": cross_persistence,
                "atr_deadband": atr_deadband,
                "slope_threshold": slope_threshold,
                "atr_stop_mult": atr_stop_mult,
                "atr_stop_enabled": atr_stop_mult > 0,
            }
        )
        signal_config = InvestmentSignalConfig.from_mapping(symbol, candidate_mapping)
        signal_df = generate_investment_signals(
            df=df,
            symbol=symbol,
            signal_config=signal_config,
            lppl_config=lppl_config,
            use_ensemble=args.ensemble,
            start_date=args.start_date,
            end_date=args.end_date,
            scan_step=int(resolved["step"]),
        )
        _, _, summary = run_strategy_backtest(
            signal_df,
            BacktestConfig(
                initial_capital=args.initial_capital,
                buy_fee=args.buy_fee,
                sell_fee=args.sell_fee,
                slippage=args.slippage,
                start_date=args.start_date,
                end_date=args.end_date,
            ),
        )
        rows.append(
            {
                "run_id": idx,
                "symbol": symbol,
                "name": INDICES[symbol],
                "mode": "ensemble" if args.ensemble else "single_window",
                "window_count": len(lppl_config.window_range),
                "window_min": min(lppl_config.window_range),
                "window_max": max(lppl_config.window_range),
                "step": int(resolved["step"]),
                "positive_consensus_threshold": candidate_mapping["positive_consensus_threshold"],
                "negative_consensus_threshold": candidate_mapping["negative_consensus_threshold"],
                "sell_vote_threshold": sell_votes,
                "buy_vote_threshold": buy_votes,
                "sell_confirm_days": sell_confirm_days,
                "buy_confirm_days": buy_confirm_days,
                "vol_breakout_mult": vol_breakout_mult,
                "drawdown_confirm_threshold": drawdown_confirm_threshold,
                "cooldown_days": cooldown_days,
                "buy_volatility_cap": buy_volatility_cap,
                "first_cross_only": first_cross_only,
                "cross_persistence": cross_persistence,
                "atr_deadband": atr_deadband,
                "slope_threshold": slope_threshold,
                "atr_stop_mult": atr_stop_mult,
                "atr_stop_enabled": atr_stop_mult > 0,
                **summary,
            }
        )

    scored = score_signal_tuning_results(
        pd.DataFrame(rows),
        min_trade_count=args.min_trades,
        max_drawdown_cap=args.max_drawdown_cap,
        turnover_cap=args.turnover_cap,
        whipsaw_cap=args.whipsaw_cap,
        scoring_profile=args.scoring_profile,
    )
    raw_dir = os.path.join(output_dir, "raw")
    summary_dir = os.path.join(output_dir, "summary")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(summary_dir, exist_ok=True)

    symbol_slug = symbol.replace(".", "_")
    csv_path = os.path.join(summary_dir, f"signal_tuning_{symbol_slug}_{stamp}.csv")
    md_path = os.path.join(summary_dir, f"signal_tuning_{symbol_slug}_{stamp}.md")
    scored.to_csv(csv_path, index=False)

    top_n = min(10, len(scored))
    top_columns = [
        "symbol",
        "objective_score",
        "annualized_excess_return",
        "calmar_ratio",
        "max_drawdown",
        "trade_count",
        "turnover_rate",
        "whipsaw_rate",
        "positive_consensus_threshold",
        "negative_consensus_threshold",
        "sell_vote_threshold",
        "buy_vote_threshold",
        "sell_confirm_days",
        "buy_confirm_days",
        "vol_breakout_mult",
        "drawdown_confirm_threshold",
        "cooldown_days",
        "buy_volatility_cap",
        "reject_reason",
    ]
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    f"# {symbol} 信号调优结果",
                    "",
                    f"- 运行模式: {'ensemble' if args.ensemble else 'single_window'}",
                    f"- 参数组合数: {len(scored)}",
                    "",
                    scored[top_columns].head(top_n).to_markdown(index=False),
                ]
            )
        )

    print(f"{symbol} 调优结果已保存: {csv_path}")
    return scored.iloc[0].to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="指数买卖信号调优工具")
    parser.add_argument("--symbol", help="单个指数代码")
    parser.add_argument("--symbols", help="多个指数代码，逗号分隔")
    parser.add_argument("--all", action="store_true", help="对全部 8 个指数调优")
    parser.add_argument("--ensemble", action="store_true", help="使用 Ensemble 模式")
    parser.add_argument("--start-date", help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--step", type=int, default=5, help="回退步长，仅在 YAML 缺失时生效")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--buy-fee", type=float, default=0.0003, help="买入手续费")
    parser.add_argument("--sell-fee", type=float, default=0.0003, help="卖出手续费")
    parser.add_argument("--slippage", type=float, default=0.0005, help="滑点")
    parser.add_argument("--output", default="output/signal_tuning", help="输出目录")
    parser.add_argument(
        "--optimal-config-path",
        default="config/optimal_params.yaml",
        help="最优参数 YAML 路径",
    )
    parser.add_argument("--positive-offsets", default="-0.05,0.00,0.05", help="顶部共识阈值偏移")
    parser.add_argument("--negative-offsets", default="0.00,0.05", help="底部共识阈值偏移")
    parser.add_argument("--sell-votes", default="2,3", help="卖出投票门槛")
    parser.add_argument("--buy-votes", default="3", help="买入投票门槛")
    parser.add_argument("--sell-confirms", default="1,2", help="卖出确认天数")
    parser.add_argument("--buy-confirms", default="2,3", help="买入确认天数")
    parser.add_argument("--vol-breakout-grid", default="1.02,1.05,1.08", help="ATR 突破阈值")
    parser.add_argument("--drawdown-grid", default="0.05,0.08,0.10", help="回撤确认阈值")
    parser.add_argument("--cooldown-grid", default="10,15", help="冷却期天数")
    parser.add_argument("--buy-volatility-cap-grid", default="1.00,1.05", help="买入波动率上限")
    parser.add_argument("--first-cross-only", default="false,true", help="首次交叉触发")
    parser.add_argument("--cross-persistence", default="3,5", help="交叉持续天数")
    parser.add_argument("--atr-deadband", default="0.0,0.3,0.5", help="ATR死区")
    parser.add_argument("--slope-threshold", default="0.0,0.001", help="MA斜率门槛")
    parser.add_argument("--atr-stop-mult", default="0.0,2.0,2.5,3.0", help="ATR止损倍数")
    parser.add_argument(
        "--scoring-profile",
        default="balanced",
        choices=["balanced", "signal_release", "risk_reduction"],
        help="评分偏好",
    )
    parser.add_argument("--min-trades", type=int, default=3, help="最少交易次数")
    parser.add_argument("--max-drawdown-cap", type=float, default=-0.35, help="最大回撤硬门槛")
    parser.add_argument("--turnover-cap", type=float, default=8.0, help="换手率硬门槛")
    parser.add_argument("--whipsaw-cap", type=float, default=0.35, help="反复打脸率硬门槛")
    args = parser.parse_args()

    symbols = _resolve_requested_symbols(args)
    os.makedirs(args.output, exist_ok=True)

    best_rows = []
    for symbol in symbols:
        best_rows.append(_run_single_symbol(symbol, args, args.output))

    if len(best_rows) > 1:
        combined_df = pd.DataFrame(best_rows).sort_values("objective_score", ascending=False).reset_index(drop=True)
        summary_dir = os.path.join(args.output, "summary")
        report_dir = os.path.join(args.output, "reports")
        plot_dir = os.path.join(args.output, "plots")
        os.makedirs(summary_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_csv = os.path.join(summary_dir, f"optimal8_signal_tuning_summary_{stamp}.csv")
        combined_df.to_csv(combined_csv, index=False)
        report_generator = Optimal8ReadableReportGenerator(report_dir=report_dir, plot_dir=plot_dir)
        report_outputs = report_generator.generate(combined_csv, output_stem="optimal8_signal_tuning_report")
        print(f"8指数汇总已保存: {combined_csv}")
        print(f"8指数报告已保存: {report_outputs['report_path']}")


if __name__ == "__main__":
    main()

```

---

## src/cli/wyckoff_analysis.py

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫 (Wyckoff) A 股实战分析工具
基于 Richard Wyckoff 理论的 K 线与量价分析

使用方法:
    python wyckoff_analysis.py --symbol 000001.SH
    python wyckoff_analysis.py --symbol 000001.SH --lookback 120
    python wyckoff_analysis.py --symbol 000300.SH --output output/wyckoff
    python wyckoff_analysis.py --symbol 000001.SH --mode fusion --chart-dir charts/000001
"""

import logging
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.lppl_verify_v2 import SYMBOLS
from src.data.manager import DataManager
from src.wyckoff import WyckoffAnalyzer, WyckoffReport
from src.wyckoff.fusion_engine import FusionEngine
from src.wyckoff.image_engine import ImageEngine
from src.wyckoff.state import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def resolve_output_dirs(base_output_dir: str) -> Dict[str, str]:
    return {
        "base": base_output_dir,
        "reports": os.path.join(base_output_dir, "reports"),
        "raw": os.path.join(base_output_dir, "raw"),
        "summary": os.path.join(base_output_dir, "summary"),
        "state": os.path.join(base_output_dir, "state"),
        "evidence": os.path.join(base_output_dir, "evidence"),
        "plots": os.path.join(base_output_dir, "plots"),
    }


def ensure_output_dirs(output_dirs: Dict[str, str]) -> None:
    for path in output_dirs.values():
        os.makedirs(path, exist_ok=True)


def _save_all_outputs(
    report: WyckoffReport,
    image_evidence,
    analysis_result,
    output_dirs: Dict[str, str],
    symbol: str,
    mode: str
) -> None:
    """保存所有输出文件"""
    import json
    from datetime import datetime
    
    symbol_slug = symbol.replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    analysis_date = (
        str(report.structure.current_date)[:10]
        if report.structure and getattr(report.structure, "current_date", None)
        else datetime.now().strftime("%Y-%m-%d")
    )
    
    # 1. raw/analysis_<symbol>.json
    raw_analysis = {
        "symbol": report.symbol,
        "period": report.period,
        "structure": {
            "phase": report.structure.phase.value if hasattr(report.structure.phase, 'value') else str(report.structure.phase),
            "unknown_candidate": report.structure.unknown_candidate if report.structure else "",
            "current_date": analysis_date,
            "bc_point": {
                "date": report.structure.bc_point.date if report.structure.bc_point else None,
                "price": report.structure.bc_point.price if report.structure.bc_point else None,
            } if report.structure else None,
            "sc_point": {
                "date": report.structure.sc_point.date if report.structure and report.structure.sc_point else None,
                "price": report.structure.sc_point.price if report.structure and report.structure.sc_point else None,
            },
            "trading_range_high": report.structure.trading_range_high if report.structure else None,
            "trading_range_low": report.structure.trading_range_low if report.structure else None,
            "current_price": report.structure.current_price if report.structure else None,
        },
        "signal": {
            "signal_type": report.signal.signal_type if report.signal else None,
            "confidence": report.signal.confidence.value if report.signal and hasattr(report.signal.confidence, 'value') else None,
            "description": report.signal.description if report.signal else None,
        },
        "risk_reward": {
            "entry_price": report.risk_reward.entry_price if report.risk_reward else None,
            "stop_loss": report.risk_reward.stop_loss if report.risk_reward else None,
            "first_target": report.risk_reward.first_target if report.risk_reward else None,
            "reward_risk_ratio": report.risk_reward.reward_risk_ratio if report.risk_reward else 0,
        },
        "trading_plan": {
            "direction": report.trading_plan.direction if report.trading_plan else None,
            "trigger_condition": report.trading_plan.trigger_condition if report.trading_plan else None,
            "invalidation_point": report.trading_plan.invalidation_point if report.trading_plan else None,
        } if report.trading_plan else None,
        "multi_timeframe": {
            "enabled": report.multi_timeframe.enabled if report.multi_timeframe else False,
            "alignment": report.multi_timeframe.alignment if report.multi_timeframe else "",
            "summary": report.multi_timeframe.summary if report.multi_timeframe else "",
            "constraint_note": report.multi_timeframe.constraint_note if report.multi_timeframe else "",
            "monthly_phase": (
                report.multi_timeframe.monthly.phase.value
                if report.multi_timeframe and report.multi_timeframe.monthly
                else ""
            ),
            "weekly_phase": (
                report.multi_timeframe.weekly.phase.value
                if report.multi_timeframe and report.multi_timeframe.weekly
                else ""
            ),
            "daily_phase": (
                report.multi_timeframe.daily.phase.value
                if report.multi_timeframe and report.multi_timeframe.daily
                else ""
            ),
            "daily_unknown_candidate": (
                report.multi_timeframe.daily.unknown_candidate
                if report.multi_timeframe and report.multi_timeframe.daily
                else ""
            ),
        },
    }
    with open(os.path.join(output_dirs["raw"], f"analysis_{symbol_slug}_{timestamp}.json"), "w", encoding="utf-8") as f:
        json.dump(raw_analysis, f, ensure_ascii=False, indent=2)
    
    # 2. raw/image_evidence_<symbol>.json (如果有图像证据)
    if image_evidence and hasattr(image_evidence, 'files') and image_evidence.files:
        image_evidence_dict = {
            "files": image_evidence.files,
            "detected_timeframe": image_evidence.detected_timeframe,
            "image_quality": image_evidence.image_quality,
            "trust_level": image_evidence.trust_level,
        }
        with open(os.path.join(output_dirs["raw"], f"image_evidence_{symbol_slug}_{timestamp}.json"), "w", encoding="utf-8") as f:
            json.dump(image_evidence_dict, f, ensure_ascii=False, indent=2)
    
    # 3. summary/analysis_summary_<symbol>.csv (增强为SPEC要求)
    summary_data = [
        ["symbol", "asset_type", "analysis_date", "phase", "micro_action", "decision", "confidence", 
         "bc_found", "spring_detected", "rr_assessment", "t1_risk_assessment", "trigger", 
         "invalidation", "target_1", "abandon_reason", "mtf_alignment", "monthly_phase", "weekly_phase", "daily_phase", "daily_unknown_candidate"],
        [
            report.symbol,
            "stock" if symbol.endswith(('.SH', '.SZ')) else "index",
            analysis_date,
            report.structure.phase.value if report.structure and hasattr(report.structure.phase, 'value') else "unknown",
            report.signal.signal_type if report.signal else "N/A",
            analysis_result.decision if analysis_result else (report.trading_plan.direction if report.trading_plan else "N/A"),
            report.signal.confidence.value if report.signal and hasattr(report.signal.confidence, 'value') else "D",
            "Yes" if report.structure and report.structure.bc_point else "No",
            "Yes" if report.signal and report.signal.signal_type == "spring" else "No",
            analysis_result.rr_assessment if analysis_result else ("pass" if report.risk_reward and report.risk_reward.reward_risk_ratio >= 2.5 else "fail"),
            analysis_result.t1_risk_assessment if analysis_result else (report.signal.t1_risk评估 if report.signal and report.signal.t1_risk评估 else "N/A"),
            report.trading_plan.trigger_condition if report.trading_plan else "N/A",
            report.trading_plan.invalidation_point if report.trading_plan else "N/A",
            report.trading_plan.first_target if report.trading_plan else "N/A",
            analysis_result.abandon_reason if analysis_result else "",
            report.multi_timeframe.alignment if report.multi_timeframe else "",
            report.multi_timeframe.monthly.phase.value if report.multi_timeframe and report.multi_timeframe.monthly else "",
            report.multi_timeframe.weekly.phase.value if report.multi_timeframe and report.multi_timeframe.weekly else "",
            report.multi_timeframe.daily.phase.value if report.multi_timeframe and report.multi_timeframe.daily else "",
            report.multi_timeframe.daily.unknown_candidate if report.multi_timeframe and report.multi_timeframe.daily else "",
        ]
    ]
    import csv
    with open(os.path.join(output_dirs["summary"], f"analysis_summary_{symbol_slug}_{timestamp}.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(summary_data)
    
    # 4. evidence/<symbol>_conflicts.json (如果有冲突)
    if analysis_result and hasattr(analysis_result, 'conflicts') and analysis_result.conflicts:
        conflicts_dict = {
            "symbol": symbol,
            "analysis_date": datetime.now().strftime('%Y-%m-%d'),
            "conflicts": analysis_result.conflicts,
            "conflict_count": len(analysis_result.conflicts),
        }
        with open(os.path.join(output_dirs["evidence"], f"{symbol_slug}_conflicts_{timestamp}.json"), "w", encoding="utf-8") as f:
            json.dump(conflicts_dict, f, ensure_ascii=False, indent=2)
    
    # 4. state/<symbol>_wyckoff_state.json (融合模式时由StateManager生成)
    # 5. evidence/<symbol>_chart_manifest.json (图像扫描时由ImageEngine生成)
    
    # 6. plots - 暂时跳过，需要matplotlib等绘图库
    # 7. reports - 已在上方单独保存
    
    logger.info(f"所有输出文件已保存到：{output_dirs['base']}")


def _generate_html_report(report: WyckoffReport, reports_dir: str, symbol: str, mode: str) -> None:
    """生成HTML报告"""
    from datetime import datetime
    
    symbol_slug = symbol.replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    markdown_content = report.to_markdown()
    
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>威科夫分析报告 - {symbol}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        .container {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 25px; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
        .highlight {{ background: #e8f5e9; padding: 10px; border-radius: 4px; margin: 10px 0; }}
        .warning {{ background: #fff3e0; padding: 10px; border-radius: 4px; margin: 10px 0; }}
        .confidence {{ display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: bold; }}
        .confidence-A {{ background: #4CAF50; color: white; }}
        .confidence-B {{ background: #8BC34A; color: white; }}
        .confidence-C {{ background: #FFC107; color: #333; }}
        .confidence-D {{ background: #f44336; color: white; }}
        .signal {{ display: inline-block; padding: 4px 12px; border-radius: 4px; background: #2196F3; color: white; margin: 4px; }}
        .step {{ margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        {markdown_to_html(markdown_content)}
    </div>
</body>
</html>"""
    
    filepath = os.path.join(reports_dir, f"wyckoff_{symbol_slug}_{mode}_{timestamp}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"HTML报告已保存：{filepath}")


def markdown_to_html(md_text: str) -> str:
    """简单的Markdown转HTML"""
    import re
    html = md_text
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*\*(.+)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'^(.+)$', r'<p>\1</p>', html)
    return html


def main() -> None:
    parser = ArgumentParser(description="威科夫 A 股实战分析")
    parser.add_argument("--symbol", "-s", default="000001.SH", help="指数代码")
    parser.add_argument("--lookback", "-l", type=int, default=120, help="回看天数")
    parser.add_argument("--output", "-o", default="output/wyckoff", help="输出目录")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--as-of", default=None, help="历史回放截止日期，格式 YYYY-MM-DD")
    # 多模态分析参数 (PRD第7节输入模式)
    parser.add_argument("--input-file", default=None, help="标准OHLCV文件路径")
    parser.add_argument("--chart-dir", default=None, help="图表文件夹路径（可选）")
    parser.add_argument("--chart-files", default=None, help="显式图片文件列表（逗号分隔）")
    parser.add_argument("--mode", choices=["data-only", "images-only", "fusion"], default="data-only", help="分析模式")
    parser.add_argument("--multi-timeframe", action="store_true", help="使用日线合成周线/月线进行多周期分析")
    args = parser.parse_args()

    # 数据源选择 (PRD第7节: 数据-only / 图片-only / 数据+图片融合)
    df = None
    if args.input_file:
        # 从文件加载OHLCV数据
        logger.info(f"正在从文件加载数据：{args.input_file}")
        if not os.path.exists(args.input_file):
            raise SystemExit(f"数据文件不存在：{args.input_file}")
        df = pd.read_csv(args.input_file)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        symbol_from_file = os.path.basename(args.input_file).split('.')[0]
        if not args.symbol or args.symbol == "000001.SH":
            args.symbol = symbol_from_file
    elif args.symbol:
        # 从DataManager加载
        symbol_label = SYMBOLS.get(args.symbol, args.symbol)
        logger.info(f"正在加载 {args.symbol} ({symbol_label}) 数据...")
        data_manager = DataManager()
        df = data_manager.get_data(args.symbol)
    else:
        raise SystemExit("请提供 --symbol 或 --input-file")
    
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据，请检查数据源")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if args.as_of:
        as_of = pd.to_datetime(args.as_of)
        df = df[df["date"] <= as_of].copy().reset_index(drop=True)
        if df.empty:
            raise SystemExit(f"{args.symbol} 在 {args.as_of} 之前无可用数据")

    logger.info(f"数据加载完成，共 {len(df)} 条记录，最新日期：{df['date'].iloc[-1].date()}")
    
    # 初始化输出目录
    output_dirs = resolve_output_dirs(args.output)
    ensure_output_dirs(output_dirs)

    # 多模态分析
    image_evidence = None
    analysis_result = None
    
    # 图像输入 (支持 --chart-dir 或 --chart-files，参考SPEC_IMAGE_ENGINE第1-2节)
    if args.mode in ["images-only", "fusion"] and (args.chart_dir or args.chart_files):
        logger.info("正在扫描图表...")
        image_engine = ImageEngine()
        
        if args.chart_files:
            # 显式文件列表模式
            file_list = [f.strip() for f in args.chart_files.split(',')]
            manifest = image_engine.scan_chart_files(file_list, args.symbol)
        else:
            # 文件夹模式
            manifest = image_engine.scan_chart_directory(args.chart_dir, args.symbol)
        
        image_evidence = image_engine.extract_visual_evidence(manifest)
        
        # 保存chart_manifest
        image_engine.generate_chart_manifest_json(
            manifest, 
            os.path.join(output_dirs["evidence"], f"{args.symbol.replace('.', '_')}_chart_manifest.json")
        )
        
        logger.info(f"图像扫描完成：{len(manifest['files'])} 张图片，时间周期：{image_evidence.detected_timeframe}")
    
    logger.info("正在执行威科夫分析...")
    
    analyzer = WyckoffAnalyzer(lookback_days=args.lookback)
    report = analyzer.analyze(
        df,
        symbol=args.symbol,
        period="日线",
        image_evidence=image_evidence,
        multi_timeframe=args.multi_timeframe,
    )
    
    if args.mode == "fusion":
        logger.info("正在执行融合分析...")
        fusion_engine = FusionEngine()
        analysis_result = fusion_engine.fuse(
            report=report,
            image_evidence=image_evidence
        )
        
        # 状态管理
        state_manager = StateManager()
        state_manager.update_state(
            symbol=args.symbol,
            analysis_result=analysis_result,
            output_path=os.path.join(output_dirs["state"], f"{args.symbol.replace('.', '_')}_wyckoff_state.json")
        )
        logger.info(f"融合分析完成：决策={analysis_result.decision}, 置信度={analysis_result.confidence}")
        
    # 生成所有输出文件
    _save_all_outputs(report, image_evidence, analysis_result, output_dirs, args.symbol, args.mode)
    
    # 生成HTML报告
    _generate_html_report(report, output_dirs["reports"], args.symbol, args.mode)

    print("\n" + "=" * 60)
    print("威科夫分析报告")
    print("=" * 60)
    print(report.to_markdown())
    
    if analysis_result:
        print("\n" + "=" * 60)
        print("融合分析结果")
        print("=" * 60)
        print(f"决策：{analysis_result.decision}")
        print(f"置信度：{analysis_result.confidence}")
        print(f"触发条件：{analysis_result.trigger}")
        print(f"失效位：{analysis_result.invalidation}")
        print(f"目标位：{analysis_result.target_1}")
        print("=" * 60)

    mode_slug = args.mode
    symbol_slug = args.symbol.replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"wyckoff_{symbol_slug}_{mode_slug}_{timestamp}.md"
    filepath = os.path.join(output_dirs["reports"], filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())

    logger.info(f"报告已保存：{filepath}")


if __name__ == "__main__":
    main()

```

---

## src/cli/wyckoff_multimodal_analysis.py

```python
# -*- coding: utf-8 -*-
"""
威科夫多模态分析系统 - CLI 入口

遵循 ARCH_WYCKOFF_MULTIMODAL_ANALYSIS Section 3 规范
支持三种模式:
1. data-only: 仅数值数据分析
2. image-only: 仅图片视觉巡检
3. fusion: 数据 + 图片融合分析
"""
import argparse
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Optional
from pathlib import Path

from src.data.manager import DataManager
from src.wyckoff.config import load_config
from src.wyckoff.data_engine import DataEngine
from src.wyckoff.fusion_engine import FusionEngine, StateManager
from src.wyckoff.image_engine import ImageEngine
from src.wyckoff.reporting import WyckoffReportGenerator

logger = logging.getLogger(__name__)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            'wyckoff_analysis.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        ),
    ]
)


def validate_input_file(file_path: str) -> bool:
    """
    验证输入文件安全性 - 防止路径遍历攻击
    
    Args:
        file_path: 文件路径
        
    Returns:
        是否合法
    """
    if not file_path:
        return False
    
    # 检查路径遍历攻击
    if '..' in file_path:
        logger.error(f"路径遍历攻击检测：{file_path}")
        return False
    
    # 检查扩展名白名单
    ext = os.path.splitext(file_path)[1].lower()
    allowed_extensions = ['.csv', '.parquet']
    if ext not in allowed_extensions:
        logger.error(f"不支持的文件扩展名：{ext}，仅支持 {allowed_extensions}")
        return False
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        logger.error(f"文件不存在：{file_path}")
        return False
    
    return True


def validate_chart_dir(chart_dir: str) -> bool:
    """
    验证图表目录安全性 - 防止目录遍历攻击
    
    Args:
        chart_dir: 目录路径
        
    Returns:
        是否合法
    """
    if not chart_dir:
        return False
    
    # 检查路径遍历
    if '..' in chart_dir:
        logger.error(f"路径遍历攻击检测：{chart_dir}")
        return False
    
    # 检查目录是否存在
    if not os.path.exists(chart_dir):
        logger.error(f"目录不存在：{chart_dir}")
        return False
    
    # 检查是否为目录
    if not os.path.isdir(chart_dir):
        logger.error(f"路径不是目录：{chart_dir}")
        return False
    
    return True


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='威科夫多模态分析系统 - A 股威科夫分析引擎',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 数据-only 模式 (指数)
  python -m src.cli.wyckoff_multimodal_analysis --symbol 000300.SH
  
  # 数据-only 模式 (个股)
  python -m src.cli.wyckoff_multimodal_analysis --symbol 600519.SH
  
  # 数据 + 图片融合模式
  python -m src.cli.wyckoff_multimodal_analysis --symbol 600519.SH --chart-dir output/MA/plots
  
  # 图片-only 模式
  python -m src.cli.wyckoff_multimodal_analysis --chart-dir output/MA/plots
  
  # 文件输入模式
  python -m src.cli.wyckoff_multimodal_analysis --input-file data/600519.parquet
        """
    )
    
    # 输入参数
    parser.add_argument(
        "--symbol", "-s",
        type=str,
        help="标的代码 (如 000300.SH 或 600519.SH)"
    )
    parser.add_argument(
        "--input-file", "-f",
        type=str,
        help="OHLCV 文件路径 (CSV/Parquet)"
    )
    parser.add_argument(
        "--chart-dir",
        type=str,
        help="图表目录路径"
    )
    parser.add_argument(
        "--chart-files",
        nargs="+",
        help="图表文件列表"
    )
    
    # 输出参数
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="output/wyckoff",
        help="输出目录 (默认：output/wyckoff)"
    )
    
    # 运行模式
    parser.add_argument(
        "--mode",
        choices=["auto", "data_only", "image_only", "fusion"],
        default="auto",
        help="运行模式 (默认：auto 自动判断)"
    )
    
    # LLM 配置 (可选)
    parser.add_argument(
        "--llm-provider",
        type=str,
        help="LLM 提供商 (可选)"
    )
    parser.add_argument(
        "--llm-api-key",
        type=str,
        help="LLM API Key (可选)"
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        help="LLM 模型 (可选)"
    )
    
    # 其他配置
    parser.add_argument(
        "--config",
        type=str,
        help="YAML 配置文件路径"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出"
    )
    
    return parser.parse_args()


def determine_mode(args) -> str:
    """
    自动判断运行模式
    
    - 有 symbol/input_file + 有 chart_dir/chart_files → fusion
    - 有 symbol/input-file 但无图片 → data_only
    - 只有 chart_dir/chart-files → image_only
    """
    if args.mode != "auto":
        return args.mode
    
    has_data = args.symbol or args.input_file
    has_images = args.chart_dir or args.chart_files
    
    if has_data and has_images:
        return "fusion"
    elif has_data:
        return "data_only"
    elif has_images:
        return "image_only"
    else:
        logger.error("必须提供 symbol/input-file 或 chart-dir/chart-files")
        sys.exit(1)


def run_data_only_mode(args, config, output_dir: str) -> None:
    """数据-only 模式"""
    logger.info("=" * 60)
    logger.info("威科夫多模态分析 - 数据-only 模式")
    logger.info("=" * 60)
    
    # 1. 数据获取
    data_manager = DataManager()
    df, asset_type, input_source = data_manager.get_wyckoff_data(
        symbol=args.symbol,
        input_file=args.input_file,
    )
    
    symbol = args.symbol or "file_input"
    if symbol == "file_input":
        symbol = args.input_file.replace("/", "_").replace("\\", "_").replace(".parquet", "").replace(".csv", "")
    
    logger.info(f"数据获取成功：{len(df)} rows, {asset_type}")
    
    # 2. 规则引擎
    data_engine = DataEngine(config)
    data_result = data_engine.run(df, symbol, asset_type)
    
    logger.info(f"规则引擎完成：phase={data_result.phase_result.phase}, "
                f"decision={data_result.plan.direction}, confidence={data_result.confidence}")
    
    # 3. 融合引擎 (透传)
    fusion_engine = FusionEngine(config)
    analysis_result = fusion_engine.fuse(data_result, None)
    
    # 4. 状态管理
    state_manager = StateManager(output_dir)
    state = state_manager.create_state_from_result(analysis_result)
    state_manager.save_state(state)
    
    # 5. 报告生成
    report_gen = WyckoffReportGenerator(output_dir)
    report_gen.generate_markdown_report(analysis_result, state, None)
    report_gen.generate_html_report(analysis_result, state, None)
    report_gen.generate_summary_csv(analysis_result)
    report_gen.generate_raw_json(analysis_result)
    
    logger.info("=" * 60)
    logger.info("分析完成！输出目录：" + output_dir)
    logger.info("=" * 60)


def run_image_only_mode(args, config, output_dir: str) -> None:
    """图片-only 模式"""
    logger.info("=" * 60)
    logger.info("威科夫多模态分析 - 图片-only 模式")
    logger.info("=" * 60)
    
    # 1. 图像引擎
    image_engine = ImageEngine(config)
    image_bundle = image_engine.run(
        chart_dir=args.chart_dir,
        chart_files=args.chart_files,
    )
    
    logger.info(f"图像扫描完成：{image_bundle.manifest.total_count} files, "
                f"{image_bundle.manifest.usable_count} usable, "
                f"quality={image_bundle.overall_image_quality}")
    
    # 2. 融合引擎 (低置信)
    fusion_engine = FusionEngine(config)
    
    # 创建虚拟 data_result (无数据)
    from src.wyckoff.models import DailyRuleResult, PreprocessingResult, BCResult, PhaseResult, EffortResult, PhaseCTestResult, CounterfactualResult, RiskAssessment, TradingPlan
    
    data_result = DailyRuleResult(
        symbol="image_only",
        asset_type="unknown",
        analysis_date=datetime.now().strftime("%Y-%m-%d"),
        input_source="images",
        preprocessing=PreprocessingResult(
            trend_direction="unclear",
            volume_label="unclear",
            volatility_layer="unclear",
            local_highs=[],
            local_lows=[],
            gap_candidates=[],
            long_wick_candidates=[],
            limit_anomalies=[],
        ),
        bc_result=BCResult(
            found=False,
            candidate_index=-1,
            candidate_date="",
            candidate_price=0.0,
            volume_label="unknown",
            enhancement_signals=[],
        ),
        phase_result=PhaseResult(
            phase="no_trade_zone",
            boundary_upper_zone="0",
            boundary_lower_zone="0",
            boundary_sources=[],
        ),
        effort_result=EffortResult(
            phenomena=[],
            accumulation_evidence=0.0,
            distribution_evidence=0.0,
            net_bias="neutral",
        ),
        phase_c_test=PhaseCTestResult(
            spring_detected=False,
            utad_detected=False,
            st_detected=False,
            false_breakout_detected=False,
            spring_date=None,
            utad_date=None,
        ),
        counterfactual=CounterfactualResult(
            is_utad_not_breakout="unknown",
            is_distribution_not_accumulation="unknown",
            is_chaos_not_phase_c="unknown",
            liquidity_vacuum_risk="unknown",
            total_pro_score=0.0,
            total_con_score=0.0,
            conclusion_overturned=False,
        ),
        risk=RiskAssessment(
            t1_risk_level="unknown",
            t1_structural_description="",
            rr_ratio=0.0,
            rr_assessment="fail",
            freeze_until=None,
        ),
        plan=TradingPlan(
            current_assessment="图片-only 模式",
            execution_preconditions=[],
            direction="watch_only",
            entry_trigger="",
            invalidation="",
            target_1="",
        ),
        confidence="C",  # 图片-only 最高 C 级
        decision="watch_only",
        abandon_reason="",
    )
    
    analysis_result = fusion_engine.fuse(data_result, image_bundle)
    
    # 3. 状态管理
    state_manager = StateManager(output_dir)
    state = state_manager.create_state_from_result(analysis_result)
    state_manager.save_state(state)
    
    # 4. 报告生成
    report_gen = WyckoffReportGenerator(output_dir)
    report_gen.generate_markdown_report(analysis_result, state, image_bundle)
    report_gen.generate_html_report(analysis_result, state, image_bundle)
    report_gen.generate_evidence_json(image_bundle)
    
    logger.info("=" * 60)
    logger.info("分析完成！输出目录：" + output_dir)
    logger.info("注意：图片-only 模式仅生成视觉证据报告，不给出生成执行级交易计划")
    logger.info("=" * 60)


def run_fusion_mode(args, config, output_dir: str) -> None:
    """数据 + 图片融合模式"""
    logger.info("=" * 60)
    logger.info("威科夫多模态分析 - 融合模式")
    logger.info("=" * 60)
    
    # 1. 数据获取
    data_manager = DataManager()
    df, asset_type, input_source = data_manager.get_wyckoff_data(
        symbol=args.symbol,
        input_file=args.input_file,
    )
    
    symbol = args.symbol or "file_input"
    if symbol == "file_input":
        symbol = args.input_file.replace("/", "_").replace("\\", "_").replace(".parquet", "").replace(".csv", "")
    
    logger.info(f"数据获取成功：{len(df)} rows, {asset_type}")
    
    # 2. 规则引擎
    data_engine = DataEngine(config)
    data_result = data_engine.run(df, symbol, asset_type)
    
    logger.info(f"规则引擎完成：phase={data_result.phase_result.phase}, "
                f"decision={data_result.plan.direction}, confidence={data_result.confidence}")
    
    # 3. 图像引擎
    image_engine = ImageEngine(config)
    image_bundle = image_engine.run(
        chart_dir=args.chart_dir,
        chart_files=args.chart_files,
        explicit_symbol=args.symbol,
    )
    
    logger.info(f"图像扫描完成：{image_bundle.manifest.total_count} files, "
                f"{image_bundle.manifest.usable_count} usable")
    
    # 4. 融合引擎
    fusion_engine = FusionEngine(config)
    analysis_result = fusion_engine.fuse(data_result, image_bundle)
    
    logger.info(f"融合完成：final_confidence={analysis_result.confidence}, "
                f"consistency={analysis_result.consistency_score}")
    
    # 5. 状态管理
    state_manager = StateManager(output_dir)
    
    # 加载历史状态
    previous_state = state_manager.load_state(symbol)
    if previous_state:
        logger.info(f"加载历史状态：phase={previous_state.last_phase}, "
                    f"decision={previous_state.last_decision}")
    
    # 保存新状态
    state = state_manager.create_state_from_result(analysis_result)
    state_manager.save_state(state)
    
    # 生成连续性追踪模板
    continuity = state_manager.generate_continuity_template(analysis_result, previous_state)
    logger.info(f"连续性追踪：phase_changed={continuity['phase_changed']}, "
                f"freeze_ended={continuity['freeze_period_ended']}")
    
    # 6. 报告生成
    report_gen = WyckoffReportGenerator(output_dir)
    report_gen.generate_markdown_report(analysis_result, state, image_bundle)
    report_gen.generate_html_report(analysis_result, state, image_bundle)
    report_gen.generate_summary_csv(analysis_result)
    report_gen.generate_raw_json(analysis_result)
    report_gen.generate_evidence_json(image_bundle)
    
    logger.info("=" * 60)
    logger.info("分析完成！输出目录：" + output_dir)
    logger.info("=" * 60)


def main():
    """主函数"""
    args = parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 安全验证：输入文件
    if args.input_file and not validate_input_file(args.input_file):
        logger.error("输入文件验证失败，程序退出")
        sys.exit(1)
    
    # 安全验证：图表目录
    if args.chart_dir and not validate_chart_dir(args.chart_dir):
        logger.error("图表目录验证失败，程序退出")
        sys.exit(1)
    
    # 安全验证：图表文件列表
    if args.chart_files:
        for file_path in args.chart_files:
            if not validate_input_file(file_path):
                logger.error(f"图表文件验证失败：{file_path}")
                sys.exit(1)
    
    # 加载配置
    config = load_config(args.config)
    
    # 覆盖 LLM 配置
    if args.llm_provider:
        config.llm_provider = args.llm_provider
    if args.llm_api_key:
        config.llm_api_key = args.llm_api_key
    if args.llm_model:
        config.llm_model = args.llm_model
    
    # 确定输出目录
    if args.symbol:
        output_dir = os.path.join(args.output, args.symbol.replace(".", "_"))
    else:
        output_dir = os.path.join(args.output, datetime.now().strftime("%Y%m%d_%H%M%S"))
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 确定运行模式
    mode = determine_mode(args)
    logger.info(f"运行模式：{mode}")
    logger.info(f"输出目录：{output_dir}")
    
    # 执行对应模式
    if mode == "data_only":
        run_data_only_mode(args, config, output_dir)
    elif mode == "image_only":
        run_image_only_mode(args, config, output_dir)
    elif mode == "fusion":
        run_fusion_mode(args, config, output_dir)
    else:
        logger.error(f"未知模式：{mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()

```

---

## src/config/__init__.py

```python
# -*- coding: utf-8 -*-

from .optimal_params import load_optimal_config, resolve_symbol_params

__all__ = ["load_optimal_config", "resolve_symbol_params"]
```

---

## src/config/optimal_params.py

```python
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
    resolved["signal_model"] = str(resolved.get("signal_model", fallback.get("signal_model", "multi_factor_v1")))
    resolved["initial_position"] = _as_unit_float(
        resolved.get("initial_position", fallback.get("initial_position", 0.0)),
        "initial_position",
        warnings,
        float(fallback.get("initial_position", 0.0)),
    )
    resolved["positive_consensus_threshold"] = _as_unit_float(
        resolved.get("positive_consensus_threshold", resolved.get("consensus_threshold", fallback.get("consensus_threshold", 0.25))),
        "positive_consensus_threshold",
        warnings,
        float(fallback.get("positive_consensus_threshold", fallback.get("consensus_threshold", 0.25))),
    )
    resolved["negative_consensus_threshold"] = _as_unit_float(
        resolved.get("negative_consensus_threshold", resolved.get("consensus_threshold", fallback.get("consensus_threshold", 0.20))),
        "negative_consensus_threshold",
        warnings,
        float(fallback.get("negative_consensus_threshold", fallback.get("consensus_threshold", 0.20))),
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
        resolved.get("high_volatility_position_cap", fallback.get("high_volatility_position_cap", 0.5)),
        "high_volatility_position_cap",
        warnings,
        float(fallback.get("high_volatility_position_cap", 0.5)),
    )
    resolved["drawdown_confirm_threshold"] = _as_unit_float(
        resolved.get("drawdown_confirm_threshold", fallback.get("drawdown_confirm_threshold", 0.05)),
        "drawdown_confirm_threshold",
        warnings,
        float(fallback.get("drawdown_confirm_threshold", 0.05)),
    )
    resolved["buy_reentry_drawdown_threshold"] = _as_unit_float(
        resolved.get("buy_reentry_drawdown_threshold", fallback.get("buy_reentry_drawdown_threshold", 0.08)),
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
        resolved.get("regime_filter_ma", fallback.get("regime_filter_ma", resolved["trend_slow_ma"])),
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

```

---

## src/data/__init__.py

```python
# -*- coding: utf-8 -*-
from .manager import DataManager

__all__ = ["DataManager"]
```

---

## src/data/manager.py

```python
# -*- coding: utf-8 -*-
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.constants import (
    AKSHARE_INDICES,
    DATA_COLUMNS,
    DEFAULT_DATA_DIR,
    ENABLE_INCREMENTAL_UPDATE,
    INDICES,
    LOCAL_DATA_INDICES,
    MAX_DATA_AGE_DAYS,
    MIN_DATA_ROWS,
    REQUIRED_COLUMNS,
    TDX_DATA_DIR,
)
from src.exceptions import DataFetchError, DataValidationError, InvalidInputDataError

logger = logging.getLogger(__name__)

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
    logger.info(f"akshare version: {ak.__version__}")
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.warning("akshare not available, some indices may not be accessible")


class DataAvailabilityStatus:
    AVAILABLE_LOCAL = "available_local"
    AVAILABLE_CACHE = "available_cache"
    UPDATED_REMOTE = "updated_remote"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


AVAILABLE_DATA_STATUSES = {
    DataAvailabilityStatus.AVAILABLE_LOCAL,
    DataAvailabilityStatus.AVAILABLE_CACHE,
    DataAvailabilityStatus.UPDATED_REMOTE,
    DataAvailabilityStatus.STALE,
}

FAILED_DATA_STATUSES = {
    DataAvailabilityStatus.MISSING,
    DataAvailabilityStatus.FAILED,
}


def summarize_update_results(results: Dict[str, str]) -> Tuple[int, int]:
    success_count = sum(1 for status in results.values() if status in AVAILABLE_DATA_STATUSES)
    failed_count = sum(1 for status in results.values() if status in FAILED_DATA_STATUSES)
    return success_count, failed_count


def validate_dataframe(df: pd.DataFrame, symbol: str) -> Tuple[bool, str]:
    if df is None or df.empty:
        return False, "DataFrame is None or empty"

    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return False, f"Missing required columns: {missing_cols}"

    if len(df) < MIN_DATA_ROWS:
        return False, f"Insufficient data rows: {len(df)} < {MIN_DATA_ROWS}"

    null_counts = df[REQUIRED_COLUMNS].isnull().sum()
    if null_counts.any():
        return False, f"Null values found in columns: {null_counts[null_counts > 0].to_dict()}"

    bad_high_low = (df["high"] < df["low"]).sum()
    if bad_high_low > len(df) * 0.01:
        return False, f"Too many high < low: {bad_high_low} rows ({bad_high_low/len(df)*100:.1f}%)"

    if (df["close"] <= 0).any() or (df["open"] <= 0).any():
        return False, "Invalid data: non-positive prices found"

    if (df["volume"] < 0).any():
        return False, "Invalid data: negative volume found"

    dates = pd.to_datetime(df["date"], errors="coerce")
    if dates.isnull().any():
        return False, "Invalid date format found"

    return True, "Validation passed"


def validate_symbol(symbol: str) -> bool:
    if not symbol or not isinstance(symbol, str):
        return False
    if symbol in INDICES:
        return True
    return re.fullmatch(r"\d{6}\.(SH|SZ)", symbol) is not None


class DataManager:
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        if not os.path.exists(self.data_dir):
            logger.error(f"Data directory not found: {self.data_dir}")
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")
        logger.info(f"DataManager initialized with data_dir: {self.data_dir}")

        from src.data.tdx_reader import TDXReader
        self.tdx_reader = TDXReader(TDX_DATA_DIR)
        logger.info(f"TDX Reader initialized with tdxdir: {TDX_DATA_DIR}")

    def _get_file_path(self, symbol: str) -> str:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")
        return os.path.join(self.data_dir, f"{symbol}.parquet")

    def _is_akshare_index(self, symbol: str) -> bool:
        return symbol in AKSHARE_INDICES

    def _classify_cached_dataframe(self, df: pd.DataFrame, symbol: str) -> str:
        is_valid, msg = validate_dataframe(df, symbol)
        if not is_valid:
            logger.error(f"Cached data validation failed for {symbol}: {msg}")
            return DataAvailabilityStatus.FAILED

        last_date = pd.to_datetime(df["date"]).max()
        days_diff = (datetime.now().date() - last_date.date()).days
        if days_diff > MAX_DATA_AGE_DAYS:
            return DataAvailabilityStatus.STALE
        return DataAvailabilityStatus.AVAILABLE_CACHE

    def _get_local_index_status(self, symbol: str) -> str:
        try:
            tdx_df = self.tdx_reader.daily(symbol)
            if tdx_df is not None and not tdx_df.empty:
                is_valid, msg = validate_dataframe(tdx_df, symbol)
                if is_valid:
                    return DataAvailabilityStatus.AVAILABLE_LOCAL
                logger.warning(f"TDX data validation failed for {symbol}: {msg}")
        except Exception as e:
            logger.error(f"Error checking TDX data for {symbol}: {e}")

        file_path = self._get_file_path(symbol)
        if not os.path.exists(file_path):
            return DataAvailabilityStatus.MISSING

        try:
            parquet_df = pd.read_parquet(file_path)
            parquet_df["date"] = pd.to_datetime(parquet_df["date"])
            parquet_df = parquet_df.sort_values("date").reset_index(drop=True)
            return self._classify_cached_dataframe(parquet_df, symbol)
        except Exception as e:
            logger.error(f"Error checking cached parquet for {symbol}: {e}")
            return DataAvailabilityStatus.FAILED

    def _normalize_akshare_update_status(self, status: str, rows: int = 0) -> str:
        if status in {"incremental", "full_fetch"} and rows > 0:
            return DataAvailabilityStatus.UPDATED_REMOTE
        if status in {"up_to_date", "no_new_data"}:
            return DataAvailabilityStatus.AVAILABLE_CACHE
        if status in {"not_found"}:
            return DataAvailabilityStatus.MISSING
        return DataAvailabilityStatus.FAILED

    def _fetch_akshare_data(self, symbol: str) -> Optional[pd.DataFrame]:
        if not AKSHARE_AVAILABLE:
            logger.error(f"akshare is not available for {symbol}")
            raise DataFetchError("akshare library is not available")

        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        try:
            pure_symbol = symbol.replace(".SH", "").replace(".SZ", "")

            logger.info(f"Fetching data for {symbol} using akshare (code: {pure_symbol})")

            if symbol == "932000.SH":
                start_date = "20100101"
                end_date = datetime.now().strftime("%Y%m%d")

                logger.info(f"Using stock_zh_index_hist_csindex for {symbol}")
                df = ak.stock_zh_index_hist_csindex(
                    symbol=pure_symbol,
                    start_date=start_date,
                    end_date=end_date
                )

                if df is None or df.empty:
                    logger.warning(f"No data returned from akshare for {symbol}")
                    return None

                df = df.rename(columns=DATA_COLUMNS)
                df = df.dropna(subset=["open", "high", "low", "close", "volume"])
            else:
                df = ak.index_zh_a_hist(
                    symbol=pure_symbol,
                    period="daily",
                    start_date="20100101",
                    end_date=datetime.now().strftime("%Y%m%d")
                )

                if df is None or df.empty:
                    logger.warning(f"No data returned from akshare for {symbol}")
                    return None

                df = df.rename(columns=DATA_COLUMNS)

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(df, symbol)
            if not is_valid:
                logger.error(f"Data validation failed for {symbol}: {msg}")
                return None

            self._save_data(symbol, df)

            logger.info(f"Successfully fetched data for {symbol} (rows: {len(df)}, last date: {df['date'].iloc[-1].date()})")
            return df
        except ValueError as e:
            logger.error(f"Value error fetching akshare data for {symbol}: {e}")
            raise
        except KeyError as e:
            logger.error(f"Key error fetching akshare data for {symbol}: {e}")
            raise DataFetchError(f"API response missing expected data: {e}")
        except ConnectionError as e:
            logger.error(f"Connection error fetching akshare data for {symbol}: {e}")
            raise DataFetchError(f"Network connection failed: {e}")
        except Exception as e:
            logger.error(f"Error fetching akshare data for {symbol}: {type(e).__name__}: {e}")
            return None

    def _save_data(self, symbol: str, df: pd.DataFrame) -> None:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        is_valid, msg = validate_dataframe(df, symbol)
        if not is_valid:
            raise DataValidationError(f"Invalid data before saving: {msg}")

        try:
            file_path = self._get_file_path(symbol)
            df.to_parquet(file_path, index=False)
            logger.info(f"Data saved to {file_path}")
        except PermissionError as e:
            logger.error(f"Permission denied saving data for {symbol}: {e}")
            raise
        except OSError as e:
            logger.error(f"OS error saving data for {symbol}: {e}")
            raise

    def _get_last_date_from_file(self, symbol: str) -> Optional[datetime]:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            return None

        try:
            df = pd.read_parquet(file_path)
            if df.empty:
                return None
            df["date"] = pd.to_datetime(df["date"])
            return df["date"].max()
        except Exception as e:
            logger.error(f"Error reading last date for {symbol}: {e}")
            return None

    def _append_data_to_file(self, symbol: str, new_data: pd.DataFrame) -> bool:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        if new_data is None or new_data.empty:
            logger.warning(f"No new data to append for {symbol}")
            return False

        file_path = self._get_file_path(symbol)

        try:
            if os.path.exists(file_path):
                existing_df = pd.read_parquet(file_path)
                existing_df["date"] = pd.to_datetime(existing_df["date"])
                new_data["date"] = pd.to_datetime(new_data["date"])

                combined_df = pd.concat([existing_df, new_data], ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset=["date"], keep="last")
                combined_df = combined_df.sort_values("date").reset_index(drop=True)
            else:
                new_data["date"] = pd.to_datetime(new_data["date"])
                combined_df = new_data.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(combined_df, symbol)
            if not is_valid:
                logger.error(f"Combined data validation failed for {symbol}: {msg}")
                return False

            combined_df.to_parquet(file_path, index=False)
            logger.info(f"Data appended for {symbol}, total rows: {len(combined_df)}")
            return True
        except Exception as e:
            logger.error(f"Error appending data for {symbol}: {e}")
            return False

    def incremental_update_data(self, symbol: str) -> Tuple[str, int]:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        if not ENABLE_INCREMENTAL_UPDATE:
            logger.info(f"Incremental update disabled, fetching full data for {symbol}")
            df = self._fetch_akshare_data(symbol) if self._is_akshare_index(symbol) else None
            return ("full_fetch", len(df) if df is not None else 0)

        last_date = self._get_last_date_from_file(symbol)
        today = datetime.now().date()

        if last_date is None:
            logger.info(f"No existing data for {symbol}, performing full fetch")
            df = self._fetch_akshare_data(symbol) if self._is_akshare_index(symbol) else None
            return ("full_fetch", len(df) if df is not None else 0)

        days_diff = (today - last_date.date()).days

        if days_diff <= 0:
            logger.info(f"Data for {symbol} is already up-to-date (last date: {last_date.date()})")
            return ("up_to_date", 0)

        logger.info(f"Incremental update for {symbol}: {days_diff} days to fetch (from {last_date.date()} to {today})")

        if not self._is_akshare_index(symbol):
            logger.warning(f"Incremental update not supported for local data index {symbol}")
            return ("not_supported", 0)

        try:
            pure_symbol = symbol.replace(".SH", "").replace(".SZ", "")
            start_date = (last_date + pd.Timedelta(days=1)).strftime("%Y%m%d")
            end_date = today.strftime("%Y%m%d")

            if symbol == "932000.SH":
                new_df = ak.stock_zh_index_hist_csindex(
                    symbol=pure_symbol,
                    start_date=start_date,
                    end_date=end_date
                )
                if new_df is not None and not new_df.empty:
                    new_df = new_df.rename(columns=DATA_COLUMNS)
                    new_df = new_df.dropna(subset=["open", "high", "low", "close", "volume"])
                    if new_df.empty:
                        new_df = None
            else:
                new_df = ak.index_zh_a_hist(
                    symbol=pure_symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date
                )
                new_df = new_df.rename(columns=DATA_COLUMNS)

            if new_df is None or new_df.empty:
                logger.info(f"No new data available for {symbol} from {start_date} to {end_date}")
                return ("no_new_data", 0)

            new_df["date"] = pd.to_datetime(new_df["date"])

            rows_added = len(new_df)

            if self._append_data_to_file(symbol, new_df):
                logger.info(f"Incremental update successful for {symbol}: {rows_added} rows added")
                return ("incremental", rows_added)
            else:
                logger.warning(f"Failed to append incremental data for {symbol}")
                return ("append_failed", 0)

        except Exception as e:
            logger.error(f"Error during incremental update for {symbol}: {e}")
            return ("error", 0)

    def check_data_timeliness(self, symbol: str) -> Tuple[bool, Optional[datetime], Optional[str]]:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        if self._is_akshare_index(symbol):
            try:
                df = self._fetch_akshare_data(symbol)
                if df is not None and not df.empty:
                    last_date = df["date"].max()
                    today = datetime.now().date()
                    days_diff = (today - last_date.date()).days
                    if days_diff >= 1:
                        return False, last_date, None
                    else:
                        return True, last_date, None
                return False, None, None
            except DataFetchError as e:
                logger.error(f"Failed to fetch data for timeliness check: {e}")
                return False, None, None

        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            return False, None, file_path

        try:
            df = pd.read_parquet(file_path)
            df["date"] = pd.to_datetime(df["date"])
            last_date = df["date"].max()

            today = datetime.now().date()
            days_diff = (today - last_date.date()).days

            if days_diff >= 1:
                return False, last_date, file_path
            else:
                return True, last_date, file_path
        except ValueError as e:
            logger.error(f"Data format error checking timeliness for {symbol}: {e}")
            return False, None, file_path
        except KeyError as e:
            logger.error(f"Missing column checking timeliness for {symbol}: {e}")
            return False, None, file_path
        except Exception as e:
            logger.error(f"Error checking data timeliness for {symbol}: {type(e).__name__}: {e}")
            return False, None, file_path

    def get_data(self, symbol: str) -> Optional[pd.DataFrame]:
        if not validate_symbol(symbol):
            logger.error(f"Invalid symbol requested: {symbol}")
            return None

        if symbol in LOCAL_DATA_INDICES:
            return self._read_from_tdx(symbol)

        # 个股优先从本地通达信读取，失败后再回退到缓存 parquet
        tdx_df = self._read_from_tdx(symbol)
        if tdx_df is not None and not tdx_df.empty:
            return tdx_df

        if self._is_akshare_index(symbol):
            file_path = self._get_file_path(symbol)
            if os.path.exists(file_path):
                try:
                    df = pd.read_parquet(file_path)
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").reset_index(drop=True)

                    is_valid, msg = validate_dataframe(df, symbol)
                    if is_valid:
                        return df
                    else:
                        logger.warning(f"Cached data validation failed for {symbol}: {msg}, will refetch")
                except ValueError as e:
                    logger.error(f"Data format error reading local data for {symbol}: {e}")
                except KeyError as e:
                    logger.error(f"Missing column reading local data for {symbol}: {e}")
                except Exception as e:
                    logger.error(f"Error reading local data for {symbol}: {type(e).__name__}: {e}")

            return self._fetch_akshare_data(symbol)

        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            logger.warning(f"No data found for {symbol}")
            return None

        try:
            df = pd.read_parquet(file_path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(df, symbol)
            if not is_valid:
                logger.error(f"Data validation failed for {symbol}: {msg}")
                return None

            return df
        except ValueError as e:
            logger.error(f"Data format error reading data for {e}")
            return None
        except KeyError as e:
            logger.error(f"Missing column reading data for {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading data for {type(e).__name__}: {e}")
            return None

    def _read_from_tdx(self, symbol: str) -> Optional[pd.DataFrame]:
        """从通达信本地读取数据"""
        try:
            df = self.tdx_reader.daily(symbol)
            if df is None or df.empty:
                logger.warning(f"No data from TDX for {symbol}")
                return self._read_from_parquet(symbol)

            is_valid, msg = validate_dataframe(df, symbol)
            if is_valid:
                return df
            else:
                logger.warning(f"TDX data validation failed for {symbol}: {msg}")
                return self._read_from_parquet(symbol)

        except Exception as e:
            logger.error(f"Error reading from TDX for {symbol}: {e}")
            return self._read_from_parquet(symbol)

    def _read_from_parquet(self, symbol: str) -> Optional[pd.DataFrame]:
        """从本地parquet缓存读取数据"""
        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            logger.warning(f"No parquet file found for {symbol}")
            return None

        try:
            df = pd.read_parquet(file_path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(df, symbol)
            if is_valid:
                return df
            else:
                logger.error(f"Parquet data validation failed for {symbol}: {msg}")
                return None

        except Exception as e:
            logger.error(f"Error reading parquet for {symbol}: {e}")
            return None

    def update_all_data(self) -> Dict[str, str]:
        results = {}

        for symbol, name in INDICES.items():
            logger.info(f"\nProcessing {name} ({symbol})...")

            if self._is_akshare_index(symbol):
                if ENABLE_INCREMENTAL_UPDATE:
                    try:
                        status, rows = self.incremental_update_data(symbol)
                        normalized_status = self._normalize_akshare_update_status(status, rows)
                        results[symbol] = normalized_status
                        if normalized_status == DataAvailabilityStatus.UPDATED_REMOTE:
                            logger.info(f"Data for {symbol} incrementally updated ({rows} rows added)")
                        elif normalized_status == DataAvailabilityStatus.AVAILABLE_CACHE:
                            logger.info(f"Data for {symbol} is already up-to-date")
                        elif status == "full_fetch" and rows > 0:
                            logger.info(f"Data for {symbol} fetched fully ({rows} rows)")
                        elif normalized_status == DataAvailabilityStatus.FAILED:
                            logger.warning(f"Data update for {symbol} failed with status: {status}")
                        else:
                            logger.warning(f"Data update for {symbol} returned status: {status}")
                    except Exception as e:
                        logger.error(f"Incremental update failed for {symbol}: {e}")
                        results[symbol] = DataAvailabilityStatus.FAILED
                else:
                    try:
                        df = self._fetch_akshare_data(symbol)
                        if df is not None and not df.empty:
                            last_date = df["date"].max()
                            logger.info(f"Data for {symbol} fetched from akshare (last date: {last_date.date()})")
                            results[symbol] = DataAvailabilityStatus.UPDATED_REMOTE
                        else:
                            logger.warning(f"Failed to fetch data from akshare for {symbol}")
                            results[symbol] = DataAvailabilityStatus.FAILED
                    except DataFetchError as e:
                        logger.error(f"Data fetch failed for {symbol}: {e}")
                        results[symbol] = DataAvailabilityStatus.FAILED
                continue

            try:
                status = self._get_local_index_status(symbol)
                results[symbol] = status
                if status == DataAvailabilityStatus.AVAILABLE_LOCAL:
                    logger.info(f"Data for {symbol} is available from local TDX source")
                elif status == DataAvailabilityStatus.AVAILABLE_CACHE:
                    logger.info(f"Data for {symbol} is available from parquet cache")
                elif status == DataAvailabilityStatus.STALE:
                    logger.info(f"Data for {symbol} is only available from stale parquet cache")
                elif status == DataAvailabilityStatus.MISSING:
                    logger.warning(f"No local or cached data found for {symbol}")
                else:
                    logger.error(f"Failed to determine local data status for {symbol}")
            except Exception as e:
                logger.error(f"Error processing {symbol}: {type(e).__name__}: {e}")
                results[symbol] = DataAvailabilityStatus.FAILED

        return results

    def get_all_indices_data(self) -> Dict[str, Dict[str, Any]]:
        all_data = {}
        for symbol, name in INDICES.items():
            df = self.get_data(symbol)
            if df is not None and not df.empty:
                is_valid, msg = validate_dataframe(df, symbol)
                if is_valid:
                    all_data[symbol] = {
                        "name": name,
                        "data": df
                    }
                else:
                    logger.warning(f"Skipping {symbol} due to validation failure: {msg}")
            else:
                logger.warning(f"No valid data retrieved for {symbol}")
        return all_data

    def normalize_symbol(self, symbol: str) -> str:
        symbol = symbol.strip().upper()

        if re.fullmatch(r"\d{6}\.(SH|SZ)", symbol):
            return symbol

        if re.fullmatch(r"\d{6}", symbol):
            return f"{symbol}.SH"

        match = re.search(r"(\d{6})", symbol)
        if match:
            code = match.group(1)
            if "SZ" in symbol:
                return f"{code}.SZ"
            return f"{code}.SH"

        raise ValueError(f"Unable to parse symbol: {symbol}")

    def classify_asset_type(self, symbol: str) -> str:
        normalized = self.normalize_symbol(symbol)
        if normalized in INDICES:
            return "index"
        if normalized.startswith("399") or normalized.startswith("932000"):
            return "index"
        return "stock"

    def read_from_file(self, file_path: str) -> pd.DataFrame:
        if not os.path.exists(file_path):
            raise InvalidInputDataError(f"File does not exist: {file_path}")

        if file_path.endswith(".parquet"):
            df = pd.read_parquet(file_path)
        elif file_path.endswith(".csv"):
            df = pd.read_csv(file_path)
        else:
            raise InvalidInputDataError(f"Unsupported file format: {file_path}")

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

        is_valid, msg = validate_dataframe(df, "file_input")
        if not is_valid:
            raise InvalidInputDataError(f"File data validation failed: {msg}")

        return df

    def get_wyckoff_data(
        self,
        symbol: Optional[str] = None,
        input_file: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, str, str]:
        if input_file:
            return self.read_from_file(input_file), "unknown", "file"

        if not symbol:
            raise InvalidInputDataError("Either symbol or input_file is required")

        normalized = self.normalize_symbol(symbol)
        asset_type = self.classify_asset_type(normalized)
        df = self.get_data(normalized)

        if df is None or df.empty:
            raise InvalidInputDataError(f"Unable to load data for {normalized}")

        return df, asset_type, "data"

```

---

## src/data/tdx_reader.py

```python
# -*- coding: utf-8 -*-
"""通达信本地数据读取模块 - 直接读取通达信 .day 二进制文件"""
import logging
import re
import struct
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd

logger = logging.getLogger(__name__)
TDX_DAY_RECORD_SIZE = 32
TDX_DAY_FORMAT = '<IIIIIfII'

LPPL_TO_TDX_MAP = {"000001.SH": {"market": "sh", "code": "000001"}, "399001.SZ": {"market": "sz", "code": "399001"},
                   "399006.SZ": {"market": "sz", "code": "399006"}, "000016.SH": {"market": "sh", "code": "000016"},
                   "000300.SH": {"market": "sh", "code": "000300"}, "000905.SH": {"market": "sh", "code": "000905"},
                   "000852.SH": {"market": "sh", "code": "000852"}}

class TDXReader:
    def __init__(self, tdxdir: str):
        self.tdxdir = Path(tdxdir)
        if not self.tdxdir.exists():
            raise FileNotFoundError(f"TDX directory not found: {tdxdir}")
        logger.info(f"TDXReader initialized with tdxdir: {tdxdir}")

    def _parse_lppl_code(self, lppl_code: str) -> Optional[Tuple[str, str]]:
        if lppl_code in LPPL_TO_TDX_MAP:
            return LPPL_TO_TDX_MAP[lppl_code]["market"], LPPL_TO_TDX_MAP[lppl_code]["code"]
        match = re.fullmatch(r"(\d{6})\.(SH|SZ)", lppl_code)
        if not match:
            logger.warning(f"Unsupported LPPL symbol format: {lppl_code}")
            return None
        code, exchange = match.groups()
        return exchange.lower(), code

    def _get_file_path(self, lppl_code: str) -> Optional[Path]:
        parsed = self._parse_lppl_code(lppl_code)
        if parsed is None:
            return None
        market, code = parsed
        file_path = self.tdxdir / market / "lday" / f"{market}{code}.day"
        if not file_path.exists():
            logger.warning(f"Tdx file not found: {file_path}")
            return None
        return file_path

    def daily(self, lppl_code: str) -> Optional[pd.DataFrame]:
        file_path = self._get_file_path(lppl_code)
        if file_path is None:
            return None
        try:
            records = []
            with open(file_path, 'rb') as f:
                while True:
                    data = f.read(TDX_DAY_RECORD_SIZE)
                    if not data or len(data) < TDX_DAY_RECORD_SIZE:
                        break
                    try:
                        unpacked = struct.unpack(TDX_DAY_FORMAT, data)
                        date_int, open_price, high_price, low_price, close_price, amount, volume, _ = unpacked
                        if date_int < 19900101 or date_int > 21000101:
                            continue
                        date_str = str(date_int)
                        records.append({"date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}",
                                       "open": open_price / 100.0, "high": high_price / 100.0,
                                       "low": low_price / 100.0, "close": close_price / 100.0, "volume": volume, "amount": amount})
                    except (struct.error, ValueError) as e:
                        logger.warning(f"Failed to parse record: {e}")
                        continue
            if not records:
                return None
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.error(f"Error reading TDX file {file_path}: {e}")
            return None

def get_tdx_reader(tdxdir: Optional[str] = None) -> TDXReader:
    if tdxdir is None:
        tdxdir = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"
    return TDXReader(tdxdir)
```

---

## src/investment/backtest.py

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, Optional, Tuple

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

    if b_value <= 0 and days_to_crash < lppl_config.danger_days and r_squared >= lppl_config.r2_threshold:
        return "bubble_risk", r_squared, "高危信号", signal_config.flat_position

    warning_threshold = max(0.0, lppl_config.r2_threshold - 0.1)
    if b_value <= 0 and days_to_crash < lppl_config.warning_days and r_squared >= warning_threshold:
        target = min(current_target, signal_config.half_position)
        return "bubble_warning", r_squared, "观察信号", target

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
    positive_consensus = float(result.get("positive_consensus_rate", result.get("consensus_rate", 0.0)))
    negative_consensus = float(result.get("negative_consensus_rate", 0.0))
    positive_days = result.get("predicted_crash_days")
    negative_days = result.get("predicted_rebound_days")

    if negative_days is not None and negative_consensus > positive_consensus:
        negative_days = float(negative_days)
        if negative_days < signal_config.strong_buy_days:
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", signal_config.full_position
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
    output_mask = (price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)

    current_target = signal_config.initial_position
    records = []
    close_prices = price_df["close"].values
    warmup = max(lppl_config.window_range)
    scan_counter = 0
    
    # Check signal model
    is_ma_cross_atr = signal_config.signal_model == "ma_cross_atr_v1"
    is_ma_cross_atr_long_hold = signal_config.signal_model == "ma_cross_atr_long_hold_v1"
    is_ma_convergence_v1 = signal_config.signal_model == "ma_convergence_atr_v1"
    is_ma_convergence_v2 = signal_config.signal_model == "ma_convergence_atr_v2"
    is_multi_factor = signal_config.signal_model == "multi_factor_adaptive_v1"

    # For MA cross ATR model, compute indicators
    if is_ma_cross_atr or is_ma_cross_atr_long_hold or is_ma_convergence_v1 or is_ma_convergence_v2 or is_multi_factor:
        # Compute MA indicators
        fast_ma_col = signal_config.trend_fast_ma if (is_ma_cross_atr or is_ma_cross_atr_long_hold) else signal_config.ma_short
        slow_ma_col = signal_config.trend_slow_ma if (is_ma_cross_atr or is_ma_cross_atr_long_hold) else signal_config.ma_mid
        
        price_df["ma_fast"] = price_df["close"].rolling(fast_ma_col, min_periods=1).mean()
        price_df["ma_slow"] = price_df["close"].rolling(slow_ma_col, min_periods=1).mean()
        price_df["ma_regime"] = price_df["close"].rolling(signal_config.regime_filter_ma, min_periods=1).mean()
        price_df["ma_long_model"] = price_df["close"].rolling(signal_config.ma_long, min_periods=1).mean()
        
        # Compute ATR
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
        price_df["atr_ma"] = price_df["atr"].rolling(signal_config.atr_ma_window, min_periods=1).mean()
        price_df["atr_ratio"] = (price_df["atr"] / price_df["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)
        if is_ma_convergence_v1:
            min_periods = max(1, min(signal_config.atr_percentile_window, 20))
            price_df["atr_low_quantile"] = price_df["atr_ratio"].rolling(
                signal_config.atr_percentile_window, min_periods=min_periods
            ).quantile(signal_config.atr_low_percentile).fillna(price_df["atr_ratio"])
            price_df["atr_high_quantile"] = price_df["atr_ratio"].rolling(
                signal_config.atr_percentile_window, min_periods=min_periods
            ).quantile(signal_config.atr_high_percentile).fillna(price_df["atr_ratio"])
        
        # Compute MA crosses
        price_df["ma_fast_prev"] = price_df["ma_fast"].shift(1)
        price_df["ma_slow_prev"] = price_df["ma_slow"].shift(1)
        price_df["bullish_cross"] = (
            (price_df["ma_fast"] > price_df["ma_slow"])
            & (price_df["ma_fast_prev"].fillna(price_df["ma_fast"]) <= price_df["ma_slow_prev"].fillna(price_df["ma_slow"]))
        )
        price_df["bearish_cross"] = (
            (price_df["ma_fast"] < price_df["ma_slow"])
            & (price_df["ma_fast_prev"].fillna(price_df["ma_fast"]) >= price_df["ma_slow_prev"].fillna(price_df["ma_slow"]))
        )
        
        # Risk drawdown
        price_df["risk_rolling_peak"] = price_df["close"].rolling(signal_config.risk_drawdown_lookback, min_periods=1).max()
        price_df["risk_price_drawdown"] = (price_df["close"] / price_df["risk_rolling_peak"]) - 1.0
        
        # For multi-factor, also compute BB
        if is_multi_factor or is_ma_convergence_v1 or is_ma_convergence_v2:
            price_df["bb_middle"] = price_df["close"].rolling(signal_config.bb_period, min_periods=1).mean()
            price_df["bb_std"] = price_df["close"].rolling(signal_config.bb_period, min_periods=1).std().fillna(0.0)
            price_df["bb_upper"] = price_df["bb_middle"] + signal_config.bb_std * price_df["bb_std"]
            price_df["bb_lower"] = price_df["bb_middle"] - signal_config.bb_std * price_df["bb_std"]
            price_df["bb_width"] = ((price_df["bb_upper"] - price_df["bb_lower"]) / price_df["bb_middle"].replace(0.0, pd.NA)).fillna(0.0)

    buy_confirm_count = 0
    sell_confirm_count = 0
    cooldown_remaining = 0
    holding_bars = 0

    output_mask_values = output_mask.to_numpy(dtype=bool, copy=False)
    for idx, row in enumerate(price_df.itertuples(index=False)):
        if not output_mask_values[idx]:
            continue

        lppl_signal = "none"
        signal_strength = 0.0
        position_reason = "无信号"
        next_target = current_target
        close_price = float(row.close)

        if is_ma_cross_atr or is_ma_cross_atr_long_hold:
            # MA cross ATR model logic
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

            # Buy/sell conditions
            buy_candidate = (
                bullish_cross
                and atr_ratio <= signal_config.buy_volatility_cap
                and regime_ratio >= signal_config.regime_filter_buffer
            )
            sell_candidate = bearish_cross or atr_ratio > signal_config.vol_breakout_mult
            long_hold_buy_setup = (
                float(row.ma_fast) > float(row.ma_slow)
                and atr_ratio <= signal_config.buy_volatility_cap
                and regime_ratio >= signal_config.regime_filter_buffer
            )
            long_hold_sell_setup = (
                float(row.ma_fast) < float(row.ma_slow)
                or atr_ratio > signal_config.vol_breakout_mult
            )

            confirm_buy_signal = long_hold_buy_setup if is_ma_cross_atr_long_hold else buy_candidate
            confirm_sell_signal = long_hold_sell_setup if is_ma_cross_atr_long_hold else sell_candidate

            if confirm_buy_signal:
                buy_confirm_count += 1
            else:
                buy_confirm_count = 0

            if confirm_sell_signal:
                sell_confirm_count += 1
            else:
                sell_confirm_count = 0

            previous_target = current_target

            # Risk layer
            if (
                current_target > signal_config.flat_position + 1e-8
                and signal_config.regime_filter_reduce_enabled
                and risk_drawdown <= -signal_config.risk_drawdown_stop_threshold
            ):
                next_target = signal_config.flat_position
                position_reason = "回撤止损"
            elif is_ma_cross_atr_long_hold:
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
                    position_reason = (
                        f"持仓不足{int(signal_config.min_hold_bars)}天,暂缓卖出"
                    )
                elif can_sell:
                    next_target = signal_config.flat_position
                    if bearish_cross:
                        position_reason = f"长持仓MA死叉卖出(ATR={atr_ratio:.2f})"
                    else:
                        position_reason = f"长持仓ATR高波卖出(ATR={atr_ratio:.2f})"
                else:
                    next_target = current_target
                    if current_target <= signal_config.flat_position + 1e-8 and cooldown_remaining > 0:
                        position_reason = f"冷却中({cooldown_remaining}天)"
                    else:
                        position_reason = f"长持仓持有(ATR={atr_ratio:.2f},持仓={holding_bars}天)"
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

            if is_ma_cross_atr_long_hold:
                if previous_target <= signal_config.flat_position + 1e-8 and current_target > signal_config.flat_position + 1e-8:
                    holding_bars = 0
                    buy_confirm_count = 0
                elif previous_target > signal_config.flat_position + 1e-8 and current_target <= signal_config.flat_position + 1e-8:
                    holding_bars = 0
                    sell_confirm_count = 0
                    cooldown_remaining = int(signal_config.cooldown_days)

        elif is_ma_convergence_v1 or is_ma_convergence_v2:
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

            if is_ma_convergence_v1:
                atr_low_q = float(getattr(row, "atr_low_quantile", atr_ratio))
                atr_high_q = float(getattr(row, "atr_high_quantile", atr_ratio))
                buy_setup = (
                    bb_width <= signal_config.bb_width_cap
                    and atr_ratio <= atr_low_q
                    and (close_price > float(getattr(row, "bb_upper", close_price)) or (ma_fast > ma_slow > ma_long_model))
                )
                sell_setup = (
                    bb_width <= signal_config.bb_width_cap
                    and atr_ratio >= atr_high_q
                    and (bearish_cross or regime_ratio < signal_config.regime_filter_buffer)
                )
            else:
                buy_setup = (
                    bullish_cross
                    and regime_ratio >= signal_config.regime_filter_buffer
                    and (atr_ratio < signal_config.atr_low_threshold or bb_width < signal_config.bb_width_threshold)
                )
                sell_setup = (
                    bearish_cross
                    or (regime_ratio < signal_config.regime_filter_buffer and risk_drawdown <= -signal_config.risk_drawdown_stop_threshold)
                    or atr_ratio > signal_config.atr_high_threshold
                )

            buy_confirm_count = buy_confirm_count + 1 if buy_setup else 0
            sell_confirm_count = sell_confirm_count + 1 if sell_setup else 0
            previous_target = current_target

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
            if previous_target <= signal_config.flat_position + 1e-8 and current_target > signal_config.flat_position + 1e-8:
                holding_bars = 0
                buy_confirm_count = 0
            elif previous_target > signal_config.flat_position + 1e-8 and current_target <= signal_config.flat_position + 1e-8:
                holding_bars = 0
                sell_confirm_count = 0
                cooldown_remaining = int(signal_config.cooldown_days)
            
        elif is_multi_factor:
            # Multi-factor adaptive model logic
            bullish_cross = bool(row.bullish_cross)
            bearish_cross = bool(row.bearish_cross)
            atr_ratio = float(row.atr_ratio)
            regime_ma = float(getattr(row, "ma_regime", close_price))
            regime_ratio = close_price / regime_ma if regime_ma > 0 else 1.0
            bb_width = float(getattr(row, "bb_width", 0.10))
            
            # Compute scores
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
            
            # Position sizing based on volatility
            vol_position_cap = float(signal_config.full_position)
            if atr_ratio > signal_config.atr_high_threshold:
                vol_position_cap = 0.5
            elif atr_ratio > 1.05:
                vol_position_cap = 0.7
            
            # Decision logic
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
            elif total_score < 0 and total_score > signal_config.sell_score_threshold and current_target > signal_config.flat_position + 1e-8:
                next_target = signal_config.half_position
                position_reason = f"多因子减仓(评分={total_score:.2f})"
            else:
                position_reason = f"多因子持有(评分={total_score:.2f})"
            
            action = _resolve_action(current_target, next_target)
            current_target = next_target
            
        else:
            # Legacy LPPL model
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
                    lppl_signal, signal_strength, position_reason, next_target = _map_ensemble_signal(
                        result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
                else:
                    result = scan_single_date(close_prices, idx, lppl_config.window_range, lppl_config)
                    lppl_signal, signal_strength, position_reason, next_target = _map_single_window_signal(
                        result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
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


def summarize_strategy_performance(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> Dict[str, Any]:
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
    annualized_benchmark = ((1.0 + benchmark_return) ** (252.0 / periods) - 1.0) if benchmark_return > -1.0 else -1.0
    annualized_excess_return = annualized_return - annualized_benchmark
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown < 0 else annualized_return
    start_ts = pd.to_datetime(equity_df["date"].iloc[0])
    end_ts = pd.to_datetime(equity_df["date"].iloc[-1])
    initial_capital = float(equity_df["portfolio_value"].iloc[0])
    turnover_rate, annualized_turnover_rate = _annualized_turnover_rate(trades_df, initial_capital, start_ts, end_ts)
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


def run_strategy_backtest(
    signal_df: pd.DataFrame,
    backtest_config: Optional[BacktestConfig] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    backtest_config = backtest_config or BacktestConfig()
    equity_df = _normalize_price_frame(signal_df)

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
    for row in equity_df.itertuples(index=False, name="BacktestRow"):
        execution_base_price = float(row.open if backtest_config.execution_price == "open" else row.close)
        execution_buy_price = execution_base_price * (1.0 + backtest_config.slippage)
        execution_sell_price = execution_base_price * (1.0 - backtest_config.slippage)
        target_position = float(getattr(row, "target_position", 0.0))

        portfolio_value_before_trade = cash + units * execution_base_price
        current_holdings_value = units * execution_base_price
        desired_holdings_value = portfolio_value_before_trade * target_position

        trade_type = "hold"
        if desired_holdings_value > current_holdings_value + 1e-8:
            trade_value = desired_holdings_value - current_holdings_value
            affordable_units = cash / (execution_buy_price * (1.0 + backtest_config.buy_fee))
            desired_units = trade_value / execution_buy_price
            units_to_buy = min(affordable_units, desired_units)
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
            trade_value = current_holdings_value - desired_holdings_value
            units_to_sell = min(units, trade_value / execution_sell_price)
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

```

---

## src/investment/backtest_engine.py

```python
# -*- coding: utf-8 -*-
"""Backtesting engine for investment strategies."""
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import pandas as pd
from src.lppl_engine import LPPLConfig, process_single_day_ensemble, scan_single_date
from .config import BacktestConfig, InvestmentSignalConfig
from .indicators import compute_indicators, normalize_price_frame
from .signal_models import evaluate_multi_factor_adaptive, map_ensemble_signal, map_single_window_signal, resolve_action

def generate_investment_signals(df: pd.DataFrame, symbol: str, signal_config: Optional[InvestmentSignalConfig] = None,
                                lppl_config: Optional[LPPLConfig] = None, use_ensemble: bool = False,
                                start_date: Optional[str] = None, end_date: Optional[str] = None, scan_step: int = 1) -> pd.DataFrame:
    signal_config = signal_config or InvestmentSignalConfig()
    lppl_config = lppl_config or LPPLConfig(window_range=[40, 60, 80], n_workers=1)
    is_multi_factor = signal_config.signal_model == "multi_factor_adaptive_v1"
    price_df = compute_indicators(normalize_price_frame(df), signal_config) if is_multi_factor else normalize_price_frame(df)
    scan_step = max(1, int(scan_step))
    start_ts = pd.to_datetime(start_date) if start_date else price_df["date"].min()
    end_ts = pd.to_datetime(end_date) if end_date else price_df["date"].max()
    output_mask = (price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)
    current_target = signal_config.initial_position
    records = []
    close_prices = price_df["close"].values
    warmup = max(lppl_config.window_range)
    scan_counter = 0
    for idx, row in price_df.iterrows():
        if not output_mask.iloc[idx]:
            continue
        next_target = current_target
        position_reason = "无信号"
        if is_multi_factor:
            next_target, position_reason = evaluate_multi_factor_adaptive(row, signal_config, current_target)
        else:
            if idx >= warmup and scan_counter % scan_step == 0:
                if use_ensemble:
                    result = process_single_day_ensemble(close_prices, idx, lppl_config.window_range,
                                                         min_r2=lppl_config.r2_threshold, consensus_threshold=lppl_config.consensus_threshold, config=lppl_config)
                    _, _, position_reason, next_target = map_ensemble_signal(result, current_target, signal_config, lppl_config)
                else:
                    result = scan_single_date(close_prices, idx, lppl_config.window_range, lppl_config)
                    _, _, position_reason, next_target = map_single_window_signal(result, current_target, signal_config, lppl_config)
            if idx >= warmup:
                scan_counter += 1
        action = resolve_action(current_target, next_target)
        current_target = next_target
        records.append({"date": row["date"], "symbol": symbol, "open": float(row["open"]), "high": float(row["high"]),
                       "low": float(row["low"]), "close": float(row["close"]), "volume": float(row["volume"]),
                       "action": action, "target_position": float(current_target), "position_reason": position_reason})
    return pd.DataFrame(records)

def calculate_drawdown(nav_series: pd.Series) -> pd.DataFrame:
    nav = pd.Series(nav_series, copy=True).astype(float).reset_index(drop=True)
    running_max = nav.cummax()
    drawdown = (nav / running_max) - 1.0
    return pd.DataFrame({"strategy_nav": nav, "running_max": running_max, "drawdown": drawdown})

def summarize_strategy_performance(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> Dict[str, Any]:
    if equity_df.empty:
        return {"final_nav": 1.0, "total_return": 0.0, "benchmark_return": 0.0, "annualized_return": 0.0, "max_drawdown": 0.0, "trade_count": 0}
    final_nav = float(equity_df["strategy_nav"].iloc[-1])
    total_return = final_nav - 1.0
    benchmark_return = float(equity_df["benchmark_nav"].iloc[-1] - 1.0)
    periods = max(len(equity_df), 1)
    annualized_return = (final_nav ** (252.0 / periods) - 1.0) if final_nav > 0 else -1.0
    max_drawdown = float(equity_df["drawdown"].min())
    return {"final_nav": final_nav, "total_return": total_return, "benchmark_return": benchmark_return,
            "annualized_return": annualized_return, "max_drawdown": max_drawdown, "trade_count": int(len(trades_df)),
            "latest_action": str(equity_df["action"].iloc[-1]), "latest_signal": "none"}

def run_strategy_backtest(signal_df: pd.DataFrame, backtest_config: Optional[BacktestConfig] = None) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    backtest_config = backtest_config or BacktestConfig()
    equity_df = normalize_price_frame(signal_df)
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
    for row in equity_df.to_dict("records"):
        execution_base_price = float(row["open"] if backtest_config.execution_price == "open" else row["close"])
        execution_buy_price = execution_base_price * (1.0 + backtest_config.slippage)
        execution_sell_price = execution_base_price * (1.0 - backtest_config.slippage)
        target_position = float(row.get("target_position", 0.0))
        portfolio_value_before_trade = cash + units * execution_base_price
        current_holdings_value = units * execution_base_price
        desired_holdings_value = portfolio_value_before_trade * target_position
        trade_type = "hold"
        if desired_holdings_value > current_holdings_value + 1e-8:
            trade_value = desired_holdings_value - current_holdings_value
            affordable_units = cash / (execution_buy_price * (1.0 + backtest_config.buy_fee))
            units_to_buy = min(affordable_units, trade_value / execution_buy_price)
            if units_to_buy > 1e-8:
                gross_cost = units_to_buy * execution_buy_price
                cash -= gross_cost + gross_cost * backtest_config.buy_fee
                units += units_to_buy
                trade_type = "buy"
                trades.append({"date": row["date"], "symbol": row.get("symbol", ""), "trade_type": trade_type, "price": execution_buy_price, "units": units_to_buy})
        elif desired_holdings_value < current_holdings_value - 1e-8:
            trade_value = current_holdings_value - desired_holdings_value
            units_to_sell = min(units, trade_value / execution_sell_price)
            if units_to_sell > 1e-8:
                gross_proceeds = units_to_sell * execution_sell_price
                cash += gross_proceeds - gross_proceeds * backtest_config.sell_fee
                units -= units_to_sell
                trade_type = "sell"
                trades.append({"date": row["date"], "symbol": row.get("symbol", ""), "trade_type": trade_type, "price": execution_sell_price, "units": units_to_sell})
        holdings_value = units * float(row["close"])
        portfolio_value = cash + holdings_value
        strategy_nav = portfolio_value / backtest_config.initial_capital
        benchmark_nav = float(row["close"]) / first_close
        daily_return = 0.0 if not records else (portfolio_value / prev_value) - 1.0
        benchmark_return = 0.0 if not records else (float(row["close"]) / prev_close) - 1.0
        executed_position = (holdings_value / portfolio_value) if portfolio_value > 0 else 0.0
        records.append({**row, "executed_position": executed_position, "cash": cash, "units": units, "portfolio_value": portfolio_value,
                       "strategy_nav": strategy_nav, "benchmark_nav": benchmark_nav, "daily_return": daily_return,
                       "benchmark_return": benchmark_return, "excess_return": daily_return - benchmark_return})
        prev_value = portfolio_value
        prev_close = float(row["close"])
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
```

---

## src/investment/indicators.py

```python
# -*- coding: utf-8 -*-
"""Technical indicator computation for investment strategies."""
from __future__ import annotations
import pandas as pd
from .config import InvestmentSignalConfig

def normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
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

def compute_indicators(df: pd.DataFrame, config: InvestmentSignalConfig) -> pd.DataFrame:
    enriched = df.copy()
    enriched["ma_short"] = enriched["close"].rolling(config.ma_short, min_periods=1).mean()
    enriched["ma_mid"] = enriched["close"].rolling(config.ma_mid, min_periods=1).mean()
    enriched["ma_long"] = enriched["close"].rolling(config.ma_long, min_periods=1).mean()
    enriched["ma_regime"] = enriched["close"].rolling(config.regime_filter_ma, min_periods=1).mean()
    enriched["ma_short_prev"] = enriched["ma_short"].shift(1)
    enriched["ma_mid_prev"] = enriched["ma_mid"].shift(1)
    enriched["bullish_cross"] = (enriched["ma_short"] > enriched["ma_mid"]) & (enriched["ma_short_prev"].fillna(enriched["ma_short"]) <= enriched["ma_mid_prev"].fillna(enriched["ma_mid"]))
    enriched["bearish_cross"] = (enriched["ma_short"] < enriched["ma_mid"]) & (enriched["ma_short_prev"].fillna(enriched["ma_short"]) >= enriched["ma_mid_prev"].fillna(enriched["ma_mid"]))
    prev_close = enriched["close"].shift(1).fillna(enriched["close"])
    true_range = pd.concat([(enriched["high"] - enriched["low"]).abs(), (enriched["high"] - prev_close).abs(), (enriched["low"] - prev_close).abs()], axis=1).max(axis=1)
    enriched["atr"] = true_range.rolling(config.atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(config.atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = (enriched["atr"] / enriched["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)
    enriched["bb_middle"] = enriched["close"].rolling(config.bb_period, min_periods=1).mean()
    enriched["bb_std_dev"] = enriched["close"].rolling(config.bb_period, min_periods=1).std().fillna(0.0)
    enriched["bb_upper"] = enriched["bb_middle"] + config.bb_std * enriched["bb_std_dev"]
    enriched["bb_lower"] = enriched["bb_middle"] - config.bb_std * enriched["bb_std_dev"]
    enriched["bb_width"] = ((enriched["bb_upper"] - enriched["bb_lower"]) / enriched["bb_middle"].replace(0.0, pd.NA)).fillna(0.0)
    enriched["risk_rolling_peak"] = enriched["close"].rolling(config.risk_drawdown_lookback, min_periods=1).max()
    enriched["risk_price_drawdown"] = (enriched["close"] / enriched["risk_rolling_peak"]) - 1.0
    return enriched
```

---

## src/investment/optimized_strategy.py

```python
# -*- coding: utf-8 -*-
"""MA+ATR优化策略 - 平衡交易频率与收益"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import pandas as pd

@dataclass
class OptimizedSignalConfig:
    full_position: float = 1.0
    half_position: float = 0.5
    flat_position: float = 0.0
    initial_position: float = 0.0
    ma_fast: int = 10
    ma_slow: int = 30
    atr_period: int = 14
    atr_ma_window: int = 40
    atr_low_threshold: float = 0.95
    atr_high_threshold: float = 1.15
    regime_filter_ma: int = 120
    regime_filter_buffer: float = 1.0
    confirm_days: int = 2
    cooldown_days: int = 15
    min_hold_bars: int = 10
    position_low_vol: float = 1.0
    position_normal_vol: float = 0.7
    position_high_vol: float = 0.5
    drawdown_stop: float = 0.15
    drawdown_lookback: int = 120

def compute_indicators(df: pd.DataFrame, config: OptimizedSignalConfig) -> pd.DataFrame:
    enriched = df.copy()
    enriched["ma_fast"] = enriched["close"].rolling(config.ma_fast, min_periods=1).mean()
    enriched["ma_slow"] = enriched["close"].rolling(config.ma_slow, min_periods=1).mean()
    enriched["ma_regime"] = enriched["close"].rolling(config.regime_filter_ma, min_periods=1).mean()
    enriched["ma_fast_prev"] = enriched["ma_fast"].shift(1)
    enriched["ma_slow_prev"] = enriched["ma_slow"].shift(1)
    enriched["bullish_cross"] = (enriched["ma_fast"] > enriched["ma_slow"]) & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) <= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
    enriched["bearish_cross"] = (enriched["ma_fast"] < enriched["ma_slow"]) & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) >= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
    prev_close = enriched["close"].shift(1).fillna(enriched["close"])
    true_range = pd.concat([(enriched["high"] - enriched["low"]).abs(), (enriched["high"] - prev_close).abs(), (enriched["low"] - prev_close).abs()], axis=1).max(axis=1)
    enriched["atr"] = true_range.rolling(config.atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(config.atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = (enriched["atr"] / enriched["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)
    enriched["rolling_peak"] = enriched["close"].rolling(config.drawdown_lookback, min_periods=1).max()
    enriched["drawdown"] = (enriched["close"] / enriched["rolling_peak"]) - 1.0
    return enriched

def generate_signals(df: pd.DataFrame, symbol: str, config: OptimizedSignalConfig, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
    price_df = compute_indicators(df, config)
    price_df["date"] = pd.to_datetime(price_df["date"])
    start_ts = pd.to_datetime(start_date) if start_date else price_df["date"].min()
    end_ts = pd.to_datetime(end_date) if end_date else price_df["date"].max()
    output_mask = (price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)
    current_target = config.initial_position
    holding_bars = 0
    cooldown_remaining = 0
    confirm_buy_count = 0
    confirm_sell_count = 0
    pending_action = None
    records = []
    for idx, row in price_df.iterrows():
        if not output_mask.iloc[idx]:
            continue
        close_price = float(row["close"])
        bullish_cross = bool(row.get("bullish_cross", False))
        bearish_cross = bool(row.get("bearish_cross", False))
        atr_ratio = float(row.get("atr_ratio", 1.0))
        regime_ma = float(row.get("ma_regime", close_price))
        regime_ratio = close_price / regime_ma if regime_ma > 0 else 1.0
        drawdown = float(row.get("drawdown", 0.0))
        action = "hold"
        position_reason = "无信号"
        next_target = current_target
        if current_target > config.flat_position + 1e-8 and drawdown <= -config.drawdown_stop and regime_ratio < 1.0:
            next_target = config.flat_position
            action = "sell"
            position_reason = "回撤止损"
            holding_bars = 0
            cooldown_remaining = config.cooldown_days
        elif bullish_cross and cooldown_remaining <= 0:
            if regime_ratio >= config.regime_filter_buffer and atr_ratio <= config.atr_high_threshold:
                if config.confirm_days <= 1:
                    if current_target < config.full_position - 1e-8:
                        next_target = config.position_low_vol if atr_ratio < config.atr_low_threshold else (config.position_normal_vol if atr_ratio < 1.05 else config.position_high_vol)
                        action = "buy" if current_target <= config.flat_position + 1e-8 else "add"
                        position_reason = f"MA金叉买入(ATR={atr_ratio:.2f})"
                else:
                    if pending_action == "buy":
                        confirm_buy_count += 1
                        if confirm_buy_count >= config.confirm_days and current_target < config.full_position - 1e-8:
                            next_target = config.position_low_vol if atr_ratio < config.atr_low_threshold else config.position_normal_vol
                            action = "buy"
                            position_reason = f"MA金叉确认买入(ATR={atr_ratio:.2f})"
                            confirm_buy_count = 0
                            pending_action = None
                    else:
                        pending_action = "buy"
                        confirm_buy_count = 1
        elif bearish_cross and current_target > config.flat_position + 1e-8:
            if holding_bars >= config.min_hold_bars:
                if config.confirm_days <= 1:
                    next_target = config.flat_position
                    action = "sell"
                    position_reason = f"MA死叉卖出(ATR高波={atr_ratio:.2f})"
                    holding_bars = 0
                    cooldown_remaining = config.cooldown_days
                else:
                    if pending_action == "sell":
                        confirm_sell_count += 1
                        if confirm_sell_count >= config.confirm_days:
                            next_target = config.flat_position
                            action = "sell"
                            holding_bars = 0
                            cooldown_remaining = config.cooldown_days
                            confirm_sell_count = 0
                            pending_action = None
                    else:
                        pending_action = "sell"
                        confirm_sell_count = 1
        elif regime_ratio < 1.0 and current_target > config.half_position + 1e-8 and cooldown_remaining <= 0:
            next_target = config.half_position
            action = "reduce"
            position_reason = "趋势减弱减仓"
        if next_target != current_target:
            current_target = next_target
            if action in ["sell", "reduce"]:
                holding_bars = 0
            elif action in ["buy", "add"]:
                holding_bars = 0
        if current_target > config.flat_position + 1e-8:
            holding_bars += 1
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        records.append({"date": row["date"], "symbol": symbol, "close": close_price, "action": action, "target_position": float(current_target), "position_reason": position_reason})
    return pd.DataFrame(records)

def run_backtest(signal_df: pd.DataFrame, config: Optional[Any] = None) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    from dataclasses import dataclass
    @dataclass
    class BacktestConfig:
        initial_capital: float = 1_000_000.0
        buy_fee: float = 0.0003
        sell_fee: float = 0.0003
        slippage: float = 0.0005
        start_date: Optional[str] = None
        end_date: Optional[str] = None
    config = config or BacktestConfig()
    equity_df = signal_df.copy()
    equity_df["date"] = pd.to_datetime(equity_df["date"])
    cash = config.initial_capital
    units = 0.0
    prev_value = config.initial_capital
    trades = []
    records = []
    for row in equity_df.to_dict("records"):
        exec_price_buy = float(row["close"]) * (1.0 + config.slippage)
        exec_price_sell = float(row["close"]) * (1.0 - config.slippage)
        target_position = float(row.get("target_position", 0.0))
        portfolio_value = cash + units * float(row["close"])
        current_holdings_value = units * float(row["close"])
        desired_value = portfolio_value * target_position
        trade_type = "hold"
        if desired_value > current_holdings_value + 1e-8:
            trade_value = desired_value - current_holdings_value
            buy_units = min(cash / exec_price_buy / (1.0 + config.buy_fee), trade_value / exec_price_buy)
            if buy_units > 1e-8:
                cost = buy_units * exec_price_buy
                cash -= cost + cost * config.buy_fee
                units += buy_units
                trade_type = "buy"
                trades.append({"date": row["date"], "type": trade_type, "price": exec_price_buy, "units": buy_units})
        elif desired_value < current_holdings_value - 1e-8:
            trade_value = current_holdings_value - desired_value
            sell_units = min(units, trade_value / exec_price_sell)
            if sell_units > 1e-8:
                proceeds = sell_units * exec_price_sell
                cash += proceeds - proceeds * config.sell_fee
                units -= sell_units
                trade_type = "sell"
                trades.append({"date": row["date"], "type": trade_type, "price": exec_price_sell, "units": sell_units})
        portfolio_value = cash + units * float(row["close"])
        strategy_nav = portfolio_value / config.initial_capital
        benchmark_nav = float(row["close"]) / float(equity_df.iloc[0]["close"])
        daily_return = 0.0 if not records else (portfolio_value / prev_value) - 1.0
        records.append({**row, "portfolio_value": portfolio_value, "strategy_nav": strategy_nav, "benchmark_nav": benchmark_nav, "daily_return": daily_return})
        prev_value = portfolio_value
    result_df = pd.DataFrame(records)
    result_df["running_max"] = result_df["strategy_nav"].cummax()
    result_df["drawdown"] = result_df["strategy_nav"] / result_df["running_max"] - 1.0
    trades_df = pd.DataFrame(trades)
    final_nav = float(result_df["strategy_nav"].iloc[-1])
    total_return = final_nav - 1.0
    max_drawdown = float(result_df["drawdown"].min())
    summary = {"final_nav": final_nav, "total_return": total_return, "max_drawdown": max_drawdown, "trade_count": len(trades_df)}
    return result_df, trades_df, summary
```

---

## src/investment/signal_models.py

```python
# -*- coding: utf-8 -*-
"""Signal evaluation models for investment strategies."""
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import pandas as pd
from src.lppl_core import calculate_bottom_signal_strength, detect_negative_bubble
from src.lppl_engine import LPPLConfig
from .config import InvestmentSignalConfig

def resolve_action(previous_target: float, next_target: float) -> str:
    if next_target > previous_target:
        return "buy" if previous_target <= 0.0 else "add"
    if next_target < previous_target:
        return "sell" if next_target <= 0.0 else "reduce"
    return "hold"

def evaluate_multi_factor_adaptive(row: pd.Series, config: InvestmentSignalConfig, current_target: float) -> Tuple[float, str]:
    close_price = float(row["close"])
    bullish_cross = bool(row.get("bullish_cross", False))
    bearish_cross = bool(row.get("bearish_cross", False))
    trend_score = 0.0
    if bullish_cross:
        trend_score = 1.0
    elif bearish_cross:
        trend_score = -1.0
    htf_ma = float(row.get("ma_regime", close_price))
    htf_ratio = close_price / htf_ma if htf_ma > 0 else 1.0
    if htf_ratio >= 1.02:
        trend_score += 0.5
    elif htf_ratio <= 0.98:
        trend_score -= 0.5
    atr_ratio = float(row.get("atr_ratio", 1.0))
    vol_score = 0.0
    if atr_ratio < config.atr_low_threshold:
        vol_score = 1.0
    elif atr_ratio > config.atr_high_threshold:
        vol_score = -1.0
    bb_width = float(row.get("bb_width", 0.10))
    state_score = 0.0
    if bb_width < config.bb_narrow_threshold:
        state_score = 0.5
    elif bb_width > config.bb_wide_threshold:
        state_score = -0.5
    ma_short = float(row.get("ma_short", close_price))
    ma_mid = float(row.get("ma_mid", close_price))
    momentum_score = 0.5 if ma_short > ma_mid else -0.5
    total_score = trend_score * config.trend_weight + vol_score * config.volatility_weight + state_score * config.market_state_weight + momentum_score * config.momentum_weight
    risk_drawdown = float(row.get("risk_price_drawdown", 0.0))
    vol_position_cap = config.full_position
    if atr_ratio > config.atr_high_threshold:
        vol_position_cap = 0.5
    elif atr_ratio > 1.05:
        vol_position_cap = 0.7
    next_target = current_target
    if current_target > config.flat_position + 1e-8 and config.regime_filter_reduce_enabled and risk_drawdown <= -config.risk_drawdown_stop_threshold:
        next_target = config.flat_position
        return next_target, f"回撤止损(评分={total_score:.2f})"
    if total_score >= config.buy_score_threshold and trend_score > 0:
        next_target = min(config.full_position, vol_position_cap)
        return next_target, f"多因子买入(评分={total_score:.2f})"
    if total_score <= config.sell_score_threshold and trend_score < 0:
        next_target = config.flat_position
        return next_target, f"多因子卖出(评分={total_score:.2f})"
    if total_score < 0 and current_target > config.flat_position + 1e-8:
        next_target = config.half_position
        return next_target, f"多因子减仓(评分={total_score:.2f})"
    return next_target, f"多因子持有(评分={total_score:.2f})"

def map_single_window_signal(result: Optional[Dict[str, Any]], current_target: float, signal_config: InvestmentSignalConfig, lppl_config: LPPLConfig) -> Tuple[str, float, str, float]:
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
            return "negative_bubble", bottom_strength, bottom_signal, max(current_target, signal_config.half_position)
        return "negative_bubble_watch", bottom_strength, bottom_signal, current_target
    if b_value <= 0 and days_to_crash < lppl_config.danger_days and r_squared >= lppl_config.r2_threshold:
        return "bubble_risk", r_squared, "高危信号", signal_config.flat_position
    warning_threshold = max(0.0, lppl_config.r2_threshold - 0.1)
    if b_value <= 0 and days_to_crash < lppl_config.warning_days and r_squared >= warning_threshold:
        return "bubble_warning", r_squared, "观察信号", min(current_target, signal_config.half_position)
    return "none", 0.0, "无信号", current_target

def map_ensemble_signal(result: Optional[Dict[str, Any]], current_target: float, signal_config: InvestmentSignalConfig, lppl_config: LPPLConfig) -> Tuple[str, float, str, float]:
    if not result:
        return "none", 0.0, "无信号", current_target
    signal_strength = float(result.get("signal_strength", 0.0))
    positive_consensus = float(result.get("positive_consensus_rate", result.get("consensus_rate", 0.0)))
    negative_consensus = float(result.get("negative_consensus_rate", 0.0))
    positive_days = result.get("predicted_crash_days")
    negative_days = result.get("predicted_rebound_days")
    if negative_days is not None and negative_consensus > positive_consensus:
        negative_days = float(negative_days)
        if negative_days < signal_config.strong_buy_days:
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", signal_config.full_position
        if negative_days < signal_config.buy_days:
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", max(current_target, signal_config.half_position)
        return "negative_bubble_watch", signal_strength, "Ensemble 抄底观察", current_target
    if positive_days is not None:
        positive_days = float(positive_days)
        if positive_days < lppl_config.danger_days:
            return "bubble_risk", signal_strength, "Ensemble 高危共识", signal_config.flat_position
        if positive_days < lppl_config.warning_days:
            return "bubble_warning", signal_strength, "Ensemble 观察信号", min(current_target, signal_config.half_position)
    return "none", 0.0, "无信号", current_target
```

---

## src/investment/tuning.py

```python
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict
import pandas as pd

SCORING_PROFILES: Dict[str, Dict[str, float]] = {
    "balanced": {"calmar_ratio": 0.30, "annualized_excess_return": 0.25, "max_drawdown": 0.20, "trade_count": 0.10, "turnover_rate": 0.10, "whipsaw_rate": 0.05},
    "signal_release": {"calmar_ratio": 0.20, "annualized_excess_return": 0.25, "max_drawdown": 0.10, "trade_count": 0.25, "turnover_rate": 0.10, "whipsaw_rate": 0.10},
    "risk_reduction": {"calmar_ratio": 0.35, "annualized_excess_return": 0.15, "max_drawdown": 0.25, "trade_count": 0.05, "turnover_rate": 0.15, "whipsaw_rate": 0.05},
}

def _rank_metric(series: pd.Series, higher_is_better: bool) -> pd.Series:
    if len(series) <= 1:
        return pd.Series([1.0] * len(series), index=series.index, dtype=float)
    return series.rank(pct=True, ascending=higher_is_better).astype(float)

def _risk_band(row: pd.Series) -> str:
    max_drawdown = float(row.get("max_drawdown", 0.0))
    annualized_excess_return = float(row.get("annualized_excess_return", 0.0))
    calmar_ratio = float(row.get("calmar_ratio", 0.0))
    if max_drawdown <= -0.25 or annualized_excess_return <= 0.0:
        return "DANGER"
    if max_drawdown <= -0.18 or calmar_ratio < 0.20:
        return "Warning"
    if max_drawdown <= -0.10 or calmar_ratio < 0.50:
        return "Watch"
    return "Safe"

def _suggest_position(risk_band: str) -> str:
    return {"DANGER": "0-20%", "Warning": "20-40%", "Watch": "60-80%", "Safe": "80-100%"}.get(risk_band, "60-80%")

def _build_reject_reason(row: pd.Series, min_trade_count: int, max_drawdown_cap: float, turnover_cap: float, whipsaw_cap: float) -> str:
    reasons = []
    if float(row.get("trade_count", 0.0)) < float(min_trade_count):
        reasons.append("trade_count")
    if float(row.get("annualized_excess_return", 0.0)) <= 0.0:
        reasons.append("non_positive_excess")
    if float(row.get("max_drawdown", 0.0)) <= float(max_drawdown_cap):
        reasons.append("max_drawdown_cap")
    turnover_to_check = row.get("annualized_turnover_rate", row.get("turnover_rate", 0.0))
    if float(turnover_to_check) >= float(turnover_cap):
        reasons.append("turnover_cap")
    if float(row.get("whipsaw_rate", 0.0)) > float(whipsaw_cap):
        reasons.append("whipsaw_cap")
    return ",".join(reasons)

def score_signal_tuning_results(results_df: pd.DataFrame, min_trade_count: int = 3, max_drawdown_cap: float = -0.35,
                                  turnover_cap: float = 8.0, whipsaw_cap: float = 0.35, scoring_profile: str = "balanced",
                                  hard_reject: bool = True) -> pd.DataFrame:
    if results_df.empty:
        return results_df.copy()
    if scoring_profile not in SCORING_PROFILES:
        raise ValueError(f"未知 scoring_profile: {scoring_profile}")
    scored = results_df.copy().reset_index(drop=True)
    profile = SCORING_PROFILES[scoring_profile]
    scored["reject_reason"] = scored.apply(_build_reject_reason, axis=1, min_trade_count=min_trade_count,
                                          max_drawdown_cap=max_drawdown_cap, turnover_cap=turnover_cap, whipsaw_cap=whipsaw_cap)
    scored["eligible"] = scored["reject_reason"] == ""
    for column in ["calmar_ratio", "annualized_excess_return", "max_drawdown", "trade_count", "turnover_rate", "whipsaw_rate"]:
        if column not in scored.columns:
            scored[column] = 0.0
    scored["turnover_for_ranking"] = scored.get("annualized_turnover_rate", scored.get("turnover_rate", 0.0))
    metric_ranks = pd.DataFrame(index=scored.index)
    metric_ranks["calmar_ratio_rank"] = _rank_metric(scored["calmar_ratio"], higher_is_better=True)
    metric_ranks["annualized_excess_return_rank"] = _rank_metric(scored["annualized_excess_return"], higher_is_better=True)
    metric_ranks["max_drawdown_rank"] = _rank_metric(scored["max_drawdown"], higher_is_better=True)
    metric_ranks["trade_count_rank"] = _rank_metric(scored["trade_count"], higher_is_better=True)
    metric_ranks["turnover_rate_rank"] = _rank_metric(scored["turnover_for_ranking"], higher_is_better=False)
    metric_ranks["whipsaw_rate_rank"] = _rank_metric(scored["whipsaw_rate"], higher_is_better=False)
    scored["objective_score"] = (metric_ranks["calmar_ratio_rank"] * profile["calmar_ratio"] +
                                  metric_ranks["annualized_excess_return_rank"] * profile["annualized_excess_return"] +
                                  metric_ranks["max_drawdown_rank"] * profile["max_drawdown"] +
                                  metric_ranks["trade_count_rank"] * profile["trade_count"] +
                                  metric_ranks["turnover_rate_rank"] * profile["turnover_rate"] +
                                  metric_ranks["whipsaw_rate_rank"] * profile["whipsaw_rate"])
    if hard_reject:
        scored.loc[~scored["eligible"], "objective_score"] = -1.0
    scored["risk_band"] = scored.apply(_risk_band, axis=1)
    scored["suggest_position"] = scored["risk_band"].map(_suggest_position)
    scored["objective_score"] = scored["objective_score"].astype(float)
    return scored.sort_values(["objective_score", "eligible", "calmar_ratio", "annualized_excess_return"],
                              ascending=[False, False, False, False]).reset_index(drop=True)
```

---

## src/reporting/__init__.py

```python
# -*- coding: utf-8 -*-
from .html_generator import HTMLGenerator
from .investment_report import InvestmentReportGenerator
from .optimal8_readable_report import Optimal8ReadableReportGenerator
from .plot_generator import PlotGenerator
from .verification_report import VerificationReportGenerator

__all__ = ["HTMLGenerator", "InvestmentReportGenerator", "Optimal8ReadableReportGenerator", "PlotGenerator", "VerificationReportGenerator"]
```

---

## src/reporting/html_generator.py

```python
# -*- coding: utf-8 -*-
import logging
import os
from datetime import datetime
from typing import List

from src.constants import INDICES, OUTPUT_DIR

logger = logging.getLogger(__name__)


class HTMLGenerator:
    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or OUTPUT_DIR
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_html(self, report_data: List) -> str:
        index_order = list(INDICES.keys())

        html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LPPL模型扫描 - 实时风险监控</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; min-height: 100vh; }
        .header { text-align: center; margin-bottom: 30px; padding: 25px; background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-radius: 16px; border: 1px solid #334155; box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        .header h1 { font-size: 28px; background: linear-gradient(90deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }
        .subtitle { color: #64748b; font-size: 14px; }
        .time-section { margin-bottom: 40px; }
        .section-header { display: flex; align-items: center; margin-bottom: 20px; padding: 15px 20px; border-radius: 12px; border-left: 6px solid; background: rgba(30, 41, 59, 0.5); backdrop-filter: blur(10px); }
        .section-header.all-codes { border-color: #4ade80; background: linear-gradient(90deg, rgba(74,222,128,0.1) 0%, transparent 100%); }
        .section-header.short-term { border-color: #38bdf8; background: linear-gradient(90deg, rgba(56,189,248,0.1) 0%, transparent 100%); }
        .section-header.medium-term { border-color: #fbbf24; background: linear-gradient(90deg, rgba(251,191,36,0.1) 0%, transparent 100%); }
        .section-header.long-term { border-color: #a78bfa; background: linear-gradient(90deg, rgba(167,139,250,0.1) 0%, transparent 100%); }
        .section-icon { font-size: 24px; margin-right: 15px; }
        .section-title { font-size: 20px; font-weight: bold; color: #f1f5f9; }
        .section-desc { font-size: 13px; color: #94a3b8; margin-left: auto; font-family: 'Courier New', monospace; }
        .cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }
        .index-card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; position: relative; overflow: hidden; transition: all 0.3s ease; }
        .index-card:hover { transform: translateY(-3px); box-shadow: 0 20px 40px rgba(0,0,0,0.4); border-color: #475569; }
        .index-card::before { content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 3px; background: var(--border-color); }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .index-info h3 { font-size: 18px; color: #f8fafc; margin-bottom: 4px; }
        .index-code { font-size: 12px; color: #64748b; font-family: 'Courier New', monospace; background: #0f172a; padding: 2px 8px; border-radius: 4px; display: inline-block; }
        .risk-badge { padding: 6px 12px; border-radius: 20px; font-size: 11px; font-weight: bold; letter-spacing: 0.5px; }
        .danger { background: #dc2626; color: white; box-shadow: 0 0 10px rgba(220,38,38,0.4); }
        .warning { background: #ea580c; color: white; }
        .medium { background: #0284c7; color: white; }
        .metrics-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 15px; }
        .metric { text-align: center; padding: 10px; background: #0f172a; border-radius: 8px; border: 1px solid #334155; }
        .metric-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
        .metric-value { font-size: 16px; font-weight: bold; color: #e2e8f0; }
        .metric-rmse { color: #38bdf8; }
        .metric-m { color: #a78bfa; }
        .metric-w { color: #fbbf24; }
        .days-highlight { display: flex; justify-content: space-between; align-items: center; background: linear-gradient(90deg, rgba(15,23,42,0.8) 0%, rgba(30,41,59,0.8) 100%); padding: 12px; border-radius: 8px; margin-top: 10px; border: 1px solid #334155; }
        .days-label { font-size: 12px; color: #94a3b8; }
        .days-value { font-size: 24px; font-weight: bold; color: #f87171; }
        .crash-date { font-size: 14px; color: #cbd5e1; font-family: 'Courier New', monospace; }
        .progress-container { margin-top: 12px; }
        .progress-bar { width: 100%; height: 6px; background: #334155; border-radius: 3px; overflow: hidden; }
        .progress-fill { height: 100%; background: var(--border-color); border-radius: 3px; transition: width 1s ease; }
        .critical-alert { background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%); border: 1px solid #dc2626; border-radius: 12px; padding: 20px; margin-bottom: 30px; display: flex; align-items: center; gap: 20px; box-shadow: 0 10px 30px rgba(220,38,38,0.3); }
        .alert-icon-big { font-size: 40px; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .alert-content h2 { color: #fca5a5; margin-bottom: 5px; }
        .legend-box { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-top: 30px; }
        .legend-title { color: #f8fafc; margin-bottom: 15px; font-size: 16px; }
        .legend-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; font-size: 13px; color: #94a3b8; line-height: 1.6; }
        .empty-state { text-align: center; padding: 40px; color: #64748b; font-style: italic; background: rgba(30,41,59,0.3); border-radius: 12px; border: 2px dashed #334155; }
    </style>
</head>
<body>
    <div class="header">
        <h1>LPPL 模型扫描监控台</h1>
        <div class="subtitle">实时风险监控 | 数据更新: {current_time}</div>
    </div>

    {critical_alert}

    <div class="time-section">
        <div class="section-header short-term">
            <span class="section-icon">📊</span>
            <div>
                <div class="section-title">短期扫描</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">周期: 70-200天 | 适配游资热点与情绪驱动</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{short_term_cards}</div>
    </div>

    <div class="time-section">
        <div class="section-header medium-term">
            <span class="section-icon">📈</span>
            <div>
                <div class="section-title">中期扫描</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">周期: 300-500天 | 适配行业轮动与结构</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{medium_term_cards}</div>
    </div>

    <div class="time-section">
        <div class="section-header long-term">
            <span class="section-icon">📅</span>
            <div>
                <div class="section-title">长期扫描</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">周期: 520-700天 | 适配长期趋势与基本面</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{long_term_cards}</div>
    </div>

    <div class="time-section">
        <div class="section-header all-codes">
            <span class="section-icon">📋</span>
            <div>
                <div class="section-title">所有代码</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">汇总所有指数的扫描结果</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{all_codes_cards}</div>
    </div>

    <div class="legend-box">
        <div class="legend-title">📋 指标说明与结果解读</div>
        <div class="legend-grid">
            <div><strong style="color: #4ade80;">所有代码</strong><br>汇总所有指数的扫描结果，按 RMSE 排序，方便整体了解市场风险状况。</div>
            <div><strong style="color: #38bdf8;">短期扫描 (70-200天)</strong><br>适配热点轮动与情绪驱动，RMSE通常较低，预测时效性强。</div>
            <div><strong style="color: #fbbf24;">中期扫描 (300-500天)</strong><br>适配行业结构与估值回归，可观察资金流向与板块轮动。</div>
            <div><strong style="color: #a78bfa;">长期扫描 (520-700天)</strong><br>适配长期趋势与基本面，可观察大周期顶部与反转信号。</div>
            <div><strong style="color: #f87171;">关键指标</strong><br>RMSE&lt;0.02(优秀)、0.02-0.05(良好)、&gt;0.08(较差)；m最佳值0.1-0.5；w最佳值6-13(接近8最佳)。</div>
        </div>
    </div>
</body>
</html>
        """

        all_codes_data = []
        short_term_data = []
        medium_term_data = []
        long_term_data = []

        for row in report_data:
            if len(row) >= 12:
                name, symbol, time_span, window, rmse, m, w, days_left, crash_date, risk, bottom_signal, bottom_strength = row[:12]
            elif len(row) == 10:
                name, symbol, time_span, window, rmse, m, w, days_left, crash_date, risk = row
                bottom_signal = "无抄底信号"
                bottom_strength = "0.00"
            else:
                continue

            window = int(window)
            rmse_val = float(rmse)

            all_codes_data.append((name, symbol, time_span, window, rmse, m, w, days_left, crash_date, risk, rmse_val, bottom_signal, bottom_strength))

            if time_span == "短期":
                short_term_data.append((name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val, bottom_signal, bottom_strength))
            elif time_span == "中期":
                medium_term_data.append((name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val, bottom_signal, bottom_strength))
            elif time_span == "长期":
                long_term_data.append((name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val, bottom_signal, bottom_strength))

        def sort_by_index_order(data):
            return sorted(data, key=lambda x: index_order.index(x[1]) if x[1] in index_order else len(index_order))

        all_codes_data = sort_by_index_order(all_codes_data)
        short_term_data = sort_by_index_order(short_term_data)
        medium_term_data = sort_by_index_order(medium_term_data)
        long_term_data = sort_by_index_order(long_term_data)

        critical_alert = ""
        high_risk_items = []

        for data in [short_term_data, medium_term_data, long_term_data]:
            for item in data:
                if len(item) >= 12:
                    name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val, bottom_signal, bottom_strength = item[:12]
                else:
                    name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val = item[:10]
                    bottom_signal = ""
                risk_str = str(risk) if risk else ""
                if "极高" in risk_str or ("高" in risk_str and float(str(days_left).split()[0]) < 20):
                    high_risk_items.append((name, symbol, days_left, crash_date))

        if high_risk_items:
            alert_content = ""
            for item in high_risk_items:
                name, symbol, days_left, crash_date = item
                alert_content += f"<strong>{name}({symbol})</strong> 预计{days_left}后于 {crash_date} 达到临界点，<br>"

            critical_alert = f"""
            <div class="critical-alert">
                <div class="alert-icon-big">⚠️</div>
                <div class="alert-content">
                    <h2>高风险预警</h2>
                    <p style="color: #fecaca; line-height: 1.6;">
                        {alert_content}
                        请注意市场短期波动风险，建议谨慎操作。
                    </p>
                </div>
            </div>
            """

        def generate_cards(data, border_color):
            cards = []
            for item in data:
                if len(item) >= 12:
                    name, symbol, time_span, window, rmse, m, w, days_left, crash_date, risk, bottom_signal, bottom_strength = item[:12]
                    rmse_val = float(rmse) if isinstance(rmse, str) else rmse
                elif len(item) == 11:
                    name, symbol, time_span, window, rmse, m, w, days_left, crash_date, risk, rmse_val = item
                else:
                    name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val = item[:10]
                    rmse_val = float(rmse) if isinstance(rmse, str) else rmse

                risk_class = "medium"
                risk_str = str(risk) if risk else ""
                if "极高" in risk_str:
                    risk_class = "danger"
                elif "高" in risk_str:
                    risk_class = "warning"

                progress_width = min(100, int((1 - min(rmse_val, 0.1) / 0.1) * 100))

                card = f"""
                <div class="index-card" style="--border-color: {border_color};">
                    <div class="card-header">
                        <div class="index-info">
                            <h3>{name}</h3>
                            <span class="index-code">{symbol}</span>
                        </div>
                        <span class="risk-badge {risk_class}">{risk}</span>
                    </div>
                    <div class="metrics-row">
                        <div class="metric">
                            <div class="metric-label">窗口(天)</div>
                            <div class="metric-value">{window}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">RMSE</div>
                            <div class="metric-value metric-rmse">{rmse}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">m / w</div>
                            <div class="metric-value" style="font-size: 12px;">{m} / {w}</div>
                        </div>
                    </div>
                    <div class="days-highlight">
                        <div>
                            <div class="days-label">距离崩盘</div>
                        </div>
                        <div style="text-align: right;">
                            <div class="days-value">{days_left}</div>
                            <div class="crash-date">{crash_date}</div>
                        </div>
                    </div>
                    <div class="progress-container">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {progress_width}%; background: {border_color};"></div>
                        </div>
                    </div>
                </div>
                """
                cards.append(card)

            if not cards:
                cards.append('<div class="empty-state">暂无扫描数据</div>')

            return "".join(cards)

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        html_content = html_template.replace("{current_time}", current_time)
        html_content = html_content.replace("{critical_alert}", critical_alert)
        html_content = html_content.replace("{all_codes_cards}", generate_cards(all_codes_data, "#4ade80"))
        html_content = html_content.replace("{short_term_cards}", generate_cards(short_term_data, "#38bdf8"))
        html_content = html_content.replace("{medium_term_cards}", generate_cards(medium_term_data, "#fbbf24"))
        html_content = html_content.replace("{long_term_cards}", generate_cards(long_term_data, "#a78bfa"))

        return html_content

    def save_html(self, html_content: str, filename: str = None, data_date: str = None) -> str:
        if not filename:
            if data_date is None:
                data_date = datetime.now().strftime('%Y%m%d')
            filename = f"lppl_report_{data_date}.html"

        file_path = os.path.join(self.output_dir, filename)

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"HTML report saved to: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Error saving HTML report: {e}")
            return None

    def generate_report(self, report_data: List, data_date: str = None) -> str:
        if not report_data:
            logger.warning("No report data provided")
            return None

        html_content = self.generate_html(report_data)
        html_path = self.save_html(html_content, data_date=data_date)

        return html_path

```

---

## src/reporting/investment_report.py

```python
# -*- coding: utf-8 -*-
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


class InvestmentReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_markdown_report(
        self,
        summary_df: pd.DataFrame,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: str = "investment_analysis_report.md",
    ) -> str:
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        lines = [
            "# 指数投资分析报告",
            "",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 一、策略摘要",
            "",
        ]

        for _, row in summary_df.iterrows():
            lines.extend(
                [
                    f"### {row.get('name', '')} ({row.get('symbol', '')})",
                    "",
                    f"- 回测区间: {row.get('start_date', '')} ~ {row.get('end_date', '')}",
                    f"- 最新信号: {row.get('latest_signal', '')}",
                    f"- 最新动作: {row.get('latest_action', '')}",
                    f"- 最终净值: {row.get('final_nav', 0.0):.4f}",
                    f"- 策略收益: {row.get('total_return', 0.0):.2%}",
                    f"- 基准收益: {row.get('benchmark_return', 0.0):.2%}",
                    f"- 最大回撤: {row.get('max_drawdown', 0.0):.2%}",
                    f"- 交易次数: {int(row.get('trade_count', 0))}",
                    "",
                ]
            )

        lines.extend(["## 二、汇总表", "", summary_df.to_markdown(index=False), "", "## 三、图表", ""])
        if not plot_paths:
            lines.append("暂无图表输出")
        else:
            for section, paths in plot_paths.items():
                lines.extend([f"### {section}", ""])
                for path in paths:
                    rel_path = os.path.relpath(path, self.output_dir)
                    lines.append(f"![{os.path.basename(path)}]({rel_path})")
                lines.append("")

        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        return file_path

    def generate_html_report(
        self,
        summary_df: pd.DataFrame,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: str = "investment_analysis_report.html",
    ) -> str:
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        cards = []
        for _, row in summary_df.iterrows():
            cards.append(
                f"""
                <div class="card">
                  <h2>{row.get('name', '')} ({row.get('symbol', '')})</h2>
                  <div class="grid">
                    <div><span>回测区间</span><strong>{row.get('start_date', '')} ~ {row.get('end_date', '')}</strong></div>
                    <div><span>最新信号</span><strong>{row.get('latest_signal', '')}</strong></div>
                    <div><span>最新动作</span><strong>{row.get('latest_action', '')}</strong></div>
                    <div><span>最终净值</span><strong>{row.get('final_nav', 0.0):.4f}</strong></div>
                    <div><span>策略收益</span><strong>{row.get('total_return', 0.0):.2%}</strong></div>
                    <div><span>最大回撤</span><strong>{row.get('max_drawdown', 0.0):.2%}</strong></div>
                  </div>
                </div>
                """
            )

        sections = []
        for section, paths in plot_paths.items():
            images = []
            for path in paths:
                rel_path = os.path.relpath(path, self.output_dir)
                images.append(
                    f"""
                    <figure class="plot-item">
                      <img src="{rel_path}" alt="{os.path.basename(path)}" />
                      <figcaption>{os.path.basename(path)}</figcaption>
                    </figure>
                    """
                )
            sections.append(
                f"""
                <section>
                  <h2>{section}</h2>
                  <div class="plot-grid">{''.join(images)}</div>
                </section>
                """
            )

        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>指数投资分析报告</title>
  <style>
    body {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      background: #f8fafc;
      color: #0f172a;
      margin: 0;
      padding: 32px;
    }}
    .hero {{
      background: linear-gradient(135deg, #0f172a, #1d4ed8);
      color: white;
      border-radius: 18px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    .card {{
      background: white;
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
      margin-bottom: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    span {{
      display: block;
      font-size: 12px;
      color: #64748b;
    }}
    strong {{
      font-size: 18px;
    }}
    .plot-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
    }}
    .plot-item {{
      background: white;
      border-radius: 14px;
      padding: 12px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .plot-item img {{
      width: 100%;
      border-radius: 10px;
    }}
  </style>
</head>
<body>
  <div class="hero">
    <h1>指数投资分析报告</h1>
    <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </div>
  {''.join(cards)}
  {''.join(sections) if sections else '<p>暂无图表输出</p>'}
</body>
</html>
        """

        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(html)

        return file_path

```

---

## src/reporting/optimal8_readable_report.py

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _set_chinese_font() -> None:
    mpl.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC",
        "Microsoft YaHei",
        "AR PL UKai CN",
        "DejaVu Sans",
    ]
    mpl.rcParams["axes.unicode_minus"] = False


class Optimal8ReadableReportGenerator:
    def __init__(self, report_dir: str, plot_dir: str):
        self.report_dir = Path(report_dir)
        self.plot_dir = Path(plot_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.plot_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, summary_csv: str, output_stem: str = "optimal8_human_friendly_report_v2") -> Dict[str, str]:
        _set_chinese_font()
        summary_path = Path(summary_csv)
        if not summary_path.exists():
            raise FileNotFoundError(f"未找到汇总文件: {summary_csv}")

        df = pd.read_csv(summary_path).sort_values("objective_score", ascending=False).reset_index(drop=True)
        if df.empty:
            raise ValueError(f"汇总文件为空: {summary_csv}")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        band_colors = {"DANGER": "#dc2626", "Warning": "#f59e0b", "Watch": "#2563eb", "Safe": "#16a34a"}
        colors = [band_colors.get(x, "#6b7280") for x in df["risk_band"]]

        chart1 = self._plot_priority(df, colors, stamp)
        if {"precision", "recall"}.issubset(df.columns):
            chart2 = self._plot_precision_recall(df, stamp)
        else:
            chart2 = self._plot_trade_quality(df, stamp)

        if {"true_positive", "false_positive"}.issubset(df.columns):
            chart3 = self._plot_signal_structure(df, stamp)
        else:
            chart3 = self._plot_drawdown_trade_count(df, stamp)
        chart4 = self._plot_param_profile(df, stamp)
        report = self._write_markdown(df, [chart1, chart2, chart3, chart4], output_stem, stamp)

        return {
            "report_path": str(report),
            "chart_priority": str(chart1),
            "chart_precision_recall": str(chart2),
            "chart_signal_structure": str(chart3),
            "chart_param_profile": str(chart4),
        }

    def _plot_priority(self, df: pd.DataFrame, colors, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        y = np.arange(len(df))
        ax.barh(y, df["objective_score"], color=colors)
        ax.set_yticks(y)
        ax.set_yticklabels(df["symbol"])
        ax.invert_yaxis()
        ax.set_xlabel("综合评分（objective_score）")
        ax.set_title("图1｜8指数风险控制优先级（从高到低）")
        for i, (v, band) in enumerate(zip(df["objective_score"], df["risk_band"])):
            ax.text(v + 0.004, i, f"{v:.3f}  {band}", va="center", fontsize=9)
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_priority_score_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_precision_recall(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        x = np.arange(len(df))
        width = 0.36
        ax.bar(x - width / 2, df["precision"] * 100, width, label="Precision(%)", color="#1d4ed8")
        ax.bar(x + width / 2, df["recall"] * 100, width, label="Recall(%)", color="#16a34a")
        ax.set_xticks(x)
        ax.set_xticklabels(df["symbol"])
        ax.set_ylim(0, 105)
        ax.set_ylabel("百分比（%）")
        ax.set_title("图2｜命中质量对比（Precision vs Recall）")
        for i, (p, r) in enumerate(zip(df["precision"] * 100, df["recall"] * 100)):
            ax.text(i - width / 2, p + 1.5, f"{p:.1f}", ha="center", fontsize=8)
            ax.text(i + width / 2, r + 1.5, f"{r:.1f}", ha="center", fontsize=8)
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_precision_recall_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_signal_structure(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.bar(df["symbol"], df["true_positive"], label="TP", color="#16a34a")
        ax.bar(df["symbol"], df["false_positive"], bottom=df["true_positive"], label="FP", color="#ef4444")
        ax.set_title("图3｜信号结构（TP/FP）")
        ax.set_ylabel("次数")
        for i, (tp, fp) in enumerate(zip(df["true_positive"], df["false_positive"])):
            ax.text(i, tp + fp + 0.08, f"{int(tp)}/{int(fp)}", ha="center", fontsize=8)
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_signal_structure_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_trade_quality(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        x = np.arange(len(df))
        width = 0.36
        calmar = df.get("calmar_ratio", pd.Series([0.0] * len(df))).astype(float)
        excess = df.get("annualized_excess_return", pd.Series([0.0] * len(df))).astype(float) * 100.0
        ax.bar(x - width / 2, calmar, width, label="Calmar", color="#1d4ed8")
        ax.bar(x + width / 2, excess, width, label="Annualized Excess(%)", color="#16a34a")
        ax.set_xticks(x)
        ax.set_xticklabels(df["symbol"])
        ax.set_title("图2｜交易质量对比（Calmar vs 年化超额）")
        for i, (c_val, e_val) in enumerate(zip(calmar, excess)):
            ax.text(i - width / 2, c_val + 0.03, f"{c_val:.2f}", ha="center", fontsize=8)
            ax.text(i + width / 2, e_val + 0.30, f"{e_val:.1f}", ha="center", fontsize=8)
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_trade_quality_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_drawdown_trade_count(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax1 = plt.subplots(figsize=(12, 6))
        trade_count = df.get("trade_count", pd.Series([0] * len(df))).astype(float)
        max_drawdown = df.get("max_drawdown", pd.Series([0.0] * len(df))).astype(float) * 100.0
        ax1.bar(df["symbol"], trade_count, color="#2563eb", alpha=0.78)
        ax1.set_ylabel("trade_count", color="#2563eb")
        ax1.tick_params(axis="y", labelcolor="#2563eb")
        ax1.set_title("图3｜交易结构（交易次数 vs 最大回撤）")
        ax1.grid(axis="y", alpha=0.2)
        ax2 = ax1.twinx()
        ax2.plot(df["symbol"], max_drawdown, color="#dc2626", marker="o", linewidth=2)
        ax2.set_ylabel("max_drawdown(%)", color="#dc2626")
        ax2.tick_params(axis="y", labelcolor="#dc2626")
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_trade_structure_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_param_profile(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax1.bar(df["symbol"], df["step"], color="#7c3aed", alpha=0.78)
        ax1.set_ylabel("step", color="#7c3aed")
        ax1.tick_params(axis="y", labelcolor="#7c3aed")
        ax1.set_title("图4｜参数画像（step 与窗口数量）")
        ax1.grid(axis="y", alpha=0.2)
        ax2 = ax1.twinx()
        ax2.plot(df["symbol"], df["window_count"], color="#f97316", marker="o", linewidth=2)
        ax2.set_ylabel("window_count", color="#f97316")
        ax2.tick_params(axis="y", labelcolor="#f97316")
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_param_profile_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _write_markdown(self, df: pd.DataFrame, charts, output_stem: str, stamp: str) -> Path:
        d = df.copy()
        for c in ["precision", "recall", "false_positive_rate", "annualized_excess_return", "max_drawdown"]:
            if c in d.columns:
                d[c] = (d[c].astype(float) * 100).map(lambda x: f"{x:.1f}%")
        d["objective_score"] = d["objective_score"].map(lambda x: f"{x:.3f}")
        for c in ["step", "window_count", "signal_count", "true_positive", "false_positive", "trade_count"]:
            if c in d.columns:
                d[c] = d[c].astype(int)
        if "calmar_ratio" in d.columns:
            d["calmar_ratio"] = d["calmar_ratio"].map(lambda x: f"{float(x):.2f}")
        if "turnover_rate" in d.columns:
            d["turnover_rate"] = (d["turnover_rate"].astype(float) * 100).map(lambda x: f"{x:.1f}%")
        if "whipsaw_rate" in d.columns:
            d["whipsaw_rate"] = (d["whipsaw_rate"].astype(float) * 100).map(lambda x: f"{x:.1f}%")

        detail_columns = [
            "symbol",
            "risk_band",
            "suggest_position",
            "objective_score",
            "annualized_excess_return",
            "calmar_ratio",
            "max_drawdown",
            "trade_count",
            "turnover_rate",
            "whipsaw_rate",
            "precision",
            "recall",
            "false_positive_rate",
            "signal_count",
            "true_positive",
            "false_positive",
            "step",
            "window_count",
        ]
        detail_columns = [column for column in detail_columns if column in d.columns]

        report = self.report_dir / f"{output_stem}_{stamp}.md"
        lines = [
            "# 8指数风控结果可读报告（优化版）",
            "",
            f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "- 读取模式: `optimal_yaml`（已按指数生效）",
            "",
            "## 阅读顺序（30秒）",
            "",
            "1. 先看图1确定风险优先级。",
            "2. 再看图2判断误报/漏报平衡。",
            "3. 图3确认信号结构是否健康。",
            "4. 图4用于参数复盘与稳定性观察。",
            "",
            "## 执行摘要",
            "",
            f"- DANGER: {', '.join(df[df['risk_band'] == 'DANGER']['symbol'].tolist()) or '无'}",
            f"- Warning: {', '.join(df[df['risk_band'] == 'Warning']['symbol'].tolist()) or '无'}",
            f"- Watch: {', '.join(df[df['risk_band'] == 'Watch']['symbol'].tolist()) or '无'}",
            "",
            "## 图表",
            "",
            f"### 图1 风险优先级\n![图1](../plots/{charts[0].name})",
            "",
            f"### 图2 命中质量\n![图2](../plots/{charts[1].name})",
            "",
            f"### 图3 信号结构\n![图3](../plots/{charts[2].name})",
            "",
            f"### 图4 参数画像\n![图4](../plots/{charts[3].name})",
            "",
            "## 指数明细（用于执行）",
            "",
            d[detail_columns].to_markdown(index=False),
            "",
            "## 输出可读性优化点",
            "",
            "- 所有指标统一百分比展示，降低换算负担。",
            "- 图题和字段中文化，减少术语跳转。",
            "- 指标、图和行动建议保持同一排序。",
        ]
        report.write_text("\n".join(lines), encoding="utf-8")
        return report

```

---

## src/reporting/plot_generator.py

```python
# -*- coding: utf-8 -*-
import os
from typing import Dict, Optional

os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.patches import Rectangle

from src.constants import PLOTS_OUTPUT_DIR


def _configure_matplotlib_fonts() -> None:
    candidates = [
        "Microsoft YaHei",
        "Droid Sans Fallback",
        "AR PL UMing CN",
        "AR PL UKai CN",
    ]
    available = []
    for font_name in candidates:
        try:
            font_manager.findfont(font_name, fallback_to_default=False)
            available.append(font_name)
        except ValueError:
            continue

    if available:
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = available + list(plt.rcParams.get("font.sans-serif", []))
    plt.rcParams["axes.unicode_minus"] = False


_configure_matplotlib_fonts()


class PlotGenerator:
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or PLOTS_OUTPUT_DIR
        os.makedirs(self.output_dir, exist_ok=True)

    def _save_figure(self, fig: plt.Figure, filename: str) -> str:
        file_path = os.path.join(self.output_dir, filename)
        fig.tight_layout()
        fig.savefig(file_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return file_path

    def generate_price_timeline_plot(
        self,
        timeline_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        timeline_df = timeline_df.copy()
        timeline_df["date"] = pd.to_datetime(timeline_df["date"])

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(timeline_df["date"], timeline_df["price"], color="#111827", linewidth=1.5, label="Price")

        if "is_warning" in timeline_df.columns:
            warning_df = timeline_df[timeline_df["is_warning"]]
            if not warning_df.empty:
                ax.scatter(warning_df["date"], warning_df["price"], color="#f59e0b", s=25, label="Warning")

        if "is_danger" in timeline_df.columns:
            danger_df = timeline_df[timeline_df["is_danger"]]
            if not danger_df.empty:
                ax.scatter(danger_df["date"], danger_df["price"], color="#dc2626", s=35, label="Danger")

        peak_date = pd.to_datetime(metadata["peak_date"])
        ax.axvline(peak_date, color="#2563eb", linestyle="--", linewidth=1.2, label="Peak Date")

        first_danger_days = metadata.get("first_danger_days")
        if first_danger_days is not None and "is_danger" in timeline_df.columns:
            danger_df = timeline_df[timeline_df["is_danger"]]
            if not danger_df.empty:
                first_danger = danger_df.sort_values("date").iloc[0]
                ax.scatter(
                    [first_danger["date"]],
                    [first_danger["price"]],
                    color="#7f1d1d",
                    s=80,
                    marker="*",
                    label="First Danger",
                )

        ax.set_title(f"{metadata['name']} {metadata['peak_date']} Price Timeline")
        ax.set_xlabel("Date")
        ax.set_ylabel("Price")
        ax.grid(True, alpha=0.25)
        ax.legend()

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_timeline.png"
        return self._save_figure(fig, filename)

    def generate_consensus_plot(
        self,
        timeline_df: pd.DataFrame,
        metadata: Dict[str, str],
        consensus_threshold: float,
        filename: Optional[str] = None,
    ) -> str:
        timeline_df = timeline_df.copy()
        timeline_df["date"] = pd.to_datetime(timeline_df["date"])

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(timeline_df["date"], timeline_df["consensus_rate"], color="#059669", linewidth=2, label="Consensus Rate")
        ax.axhline(consensus_threshold, color="#dc2626", linestyle="--", linewidth=1.2, label="Consensus Threshold")

        if "valid_windows" in timeline_df.columns:
            ax2 = ax.twinx()
            ax2.bar(timeline_df["date"], timeline_df["valid_windows"], alpha=0.15, color="#2563eb", label="Valid Windows")
            ax2.set_ylabel("Valid Windows")

        ax.set_title(f"{metadata['name']} {metadata['peak_date']} Ensemble Consensus")
        ax.set_xlabel("Date")
        ax.set_ylabel("Consensus Rate")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper left")

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_consensus.png"
        return self._save_figure(fig, filename)

    def generate_crash_dispersion_plot(
        self,
        timeline_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        timeline_df = timeline_df.copy()
        timeline_df["date"] = pd.to_datetime(timeline_df["date"])

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        axes[0].plot(
            timeline_df["date"],
            timeline_df["predicted_crash_days"],
            color="#7c3aed",
            linewidth=1.8,
            label="Predicted Crash Days",
        )
        axes[0].set_ylabel("Crash Days")
        axes[0].grid(True, alpha=0.25)
        axes[0].legend()

        axes[1].fill_between(
            timeline_df["date"],
            0,
            timeline_df["tc_std"],
            color="#f97316",
            alpha=0.35,
            label="tc std",
        )
        axes[1].set_ylabel("tc std")
        axes[1].set_xlabel("Date")
        axes[1].grid(True, alpha=0.25)
        axes[1].legend()

        fig.suptitle(f"{metadata['name']} {metadata['peak_date']} Crash Dispersion")

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_dispersion.png"
        return self._save_figure(fig, filename)

    def generate_summary_statistics_plot(
        self,
        summary_df: pd.DataFrame,
        filename: str = "verification_summary.png",
    ) -> str:
        summary_df = summary_df.copy()
        detect_rate = summary_df.groupby("name")["detected"].mean().sort_values(ascending=False) * 100
        lead_days = (
            summary_df[summary_df["detected"]]
            .groupby("name")["first_danger_days"]
            .apply(lambda s: (-1 * s.dropna()).tolist())
        )

        fig, axes = plt.subplots(2, 1, figsize=(12, 9))

        detect_rate.plot(kind="bar", color="#2563eb", ax=axes[0])
        axes[0].set_title("Detection Rate by Index")
        axes[0].set_ylabel("Detection Rate (%)")
        axes[0].grid(True, axis="y", alpha=0.25)

        boxplot_data = [values for values in lead_days.tolist() if values]
        labels = [name for name, values in lead_days.items() if values]
        if boxplot_data:
            axes[1].boxplot(boxplot_data, tick_labels=labels)
            axes[1].set_title("Lead Days Distribution")
            axes[1].set_ylabel("Lead Days")
            axes[1].tick_params(axis="x", rotation=25)
            axes[1].grid(True, axis="y", alpha=0.25)
        else:
            axes[1].text(0.5, 0.5, "No detected samples", ha="center", va="center")
            axes[1].set_axis_off()

        return self._save_figure(fig, filename)

    def _plot_candlesticks(self, ax: plt.Axes, price_df: pd.DataFrame) -> None:
        candle_width = 0.6
        for row in price_df.itertuples(index=False):
            x_value = mdates.date2num(pd.to_datetime(row.date))
            open_price = float(row.open)
            high_price = float(row.high)
            low_price = float(row.low)
            close_price = float(row.close)
            color = "#16a34a" if close_price >= open_price else "#dc2626"

            ax.vlines(x_value, low_price, high_price, color=color, linewidth=1.0, alpha=0.9)

            lower = min(open_price, close_price)
            body_height = abs(close_price - open_price)
            if body_height < 1e-8:
                body_height = 0.02
            ax.add_patch(
                Rectangle(
                    (x_value - candle_width / 2.0, lower),
                    candle_width,
                    body_height,
                    facecolor=color,
                    edgecolor=color,
                    alpha=0.85,
                )
            )

    def generate_strategy_overview_plot(
        self,
        equity_df: pd.DataFrame,
        trades_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        equity_df = equity_df.copy()
        equity_df["date"] = pd.to_datetime(equity_df["date"])
        trades_df = trades_df.copy()
        if "trade_type" not in trades_df.columns:
            trades_df = pd.DataFrame(columns=["date", "trade_type"])
        if not trades_df.empty and "date" in trades_df.columns:
            trades_df["date"] = pd.to_datetime(trades_df["date"])

        fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [1, 1.2]})

        axes[0].plot(
            equity_df["date"],
            equity_df["strategy_nav"],
            color="#1d4ed8",
            linewidth=2.0,
            label="Strategy NAV",
        )
        axes[0].plot(
            equity_df["date"],
            equity_df["benchmark_nav"],
            color="#64748b",
            linewidth=1.8,
            linestyle="--",
            label="Benchmark NAV",
        )
        axes[0].set_ylabel("NAV")
        axes[0].set_title(
            f"{metadata['name']} ({metadata['symbol']}) | "
            f"{metadata['start_date']} ~ {metadata['end_date']} | "
            f"收益 {metadata['total_return']:.2%} | "
            f"最大回撤 {metadata['max_drawdown']:.2%}"
        )
        axes[0].grid(True, alpha=0.25)
        axes[0].legend(loc="upper left")

        self._plot_candlesticks(axes[1], equity_df[["date", "open", "high", "low", "close"]])

        marker_styles = {
            "buy": ("^", "#16a34a", "Buy"),
            "add": ("^", "#0ea5e9", "Add"),
            "reduce": ("v", "#f59e0b", "Reduce"),
            "sell": ("v", "#dc2626", "Sell"),
        }
        added_labels = set()
        for trade_type, (marker, color, label) in marker_styles.items():
            trade_points = trades_df[trades_df["trade_type"] == trade_type]
            if trade_points.empty:
                continue

            merged = trade_points.merge(
                equity_df[["date", "open", "high", "low", "close"]],
                on="date",
                how="left",
            )
            scatter_label = label if label not in added_labels else None
            axes[1].scatter(
                merged["date"],
                merged["close"],
                marker=marker,
                color=color,
                s=80,
                label=scatter_label,
                zorder=5,
            )
            added_labels.add(label)

        axes[1].set_ylabel("Price")
        axes[1].set_xlabel("Date")
        axes[1].grid(True, alpha=0.2)
        if added_labels:
            axes[1].legend(loc="upper left")
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_strategy_overview.png"
        return self._save_figure(fig, filename)

    def generate_strategy_drawdown_plot(
        self,
        equity_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        equity_df = equity_df.copy()
        equity_df["date"] = pd.to_datetime(equity_df["date"])

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.fill_between(equity_df["date"], equity_df["drawdown"], 0, color="#dc2626", alpha=0.35)
        ax.plot(equity_df["date"], equity_df["drawdown"], color="#b91c1c", linewidth=1.8)

        trough_idx = equity_df["drawdown"].idxmin()
        peak_idx = equity_df.loc[:trough_idx, "strategy_nav"].idxmax()
        ax.axvspan(
            equity_df.loc[peak_idx, "date"],
            equity_df.loc[trough_idx, "date"],
            color="#fca5a5",
            alpha=0.18,
        )
        ax.scatter(
            [equity_df.loc[trough_idx, "date"]],
            [equity_df.loc[trough_idx, "drawdown"]],
            color="#7f1d1d",
            s=60,
            zorder=5,
        )

        ax.set_title(f"{metadata['name']} ({metadata['symbol']}) 回撤曲线")
        ax.set_ylabel("Drawdown")
        ax.set_xlabel("Date")
        ax.grid(True, alpha=0.25)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_strategy_drawdown.png"
        return self._save_figure(fig, filename)

```

---

## src/reporting/verification_report.py

```python
# -*- coding: utf-8 -*-
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


class VerificationReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_markdown_report(
        self,
        summary_df: pd.DataFrame,
        use_ensemble: bool,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: Optional[str] = None,
    ) -> str:
        mode_label = "Ensemble 多窗口共识" if use_ensemble else "单窗口独立"
        filename = filename or (
            "verification_report_ensemble.md" if use_ensemble else "verification_report_single_window.md"
        )
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        total = len(summary_df)
        detected = int(summary_df["detected"].sum()) if "detected" in summary_df.columns else 0
        detection_rate = detected / total * 100 if total > 0 else 0

        lines = [
            "# LPPL 验证报告",
            "",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**验证模式**: {mode_label}",
            "",
            "## 一、总体结果",
            "",
            f"- 总样本数: {total}",
            f"- 检测到预警: {detected}",
            f"- 检测率: {detection_rate:.1f}%",
            "",
            "## 二、汇总表",
            "",
        ]

        summary_for_report = summary_df.drop(columns=["timeline"], errors="ignore")
        lines.append(summary_for_report.to_markdown(index=False))
        lines.extend(["", "## 三、图片输出", ""])

        if not plot_paths:
            lines.append("暂无图片输出")
        else:
            for section, paths in plot_paths.items():
                if not paths:
                    continue
                lines.append(f"### {section}")
                lines.append("")
                for path in paths:
                    rel_path = os.path.relpath(path, self.output_dir)
                    lines.append(f"![{os.path.basename(path)}]({rel_path})")
                lines.append("")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return file_path

    def generate_html_report(
        self,
        summary_df: pd.DataFrame,
        use_ensemble: bool,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: Optional[str] = None,
    ) -> str:
        mode_label = "Ensemble 多窗口共识" if use_ensemble else "单窗口独立"
        filename = filename or (
            "verification_report_ensemble.html" if use_ensemble else "verification_report_single_window.html"
        )
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        total = len(summary_df)
        detected = int(summary_df["detected"].sum()) if "detected" in summary_df.columns else 0
        detection_rate = detected / total * 100 if total > 0 else 0

        cards_html = []
        for _, row in summary_df.iterrows():
            cards_html.append(
                f"""
                <div class="card">
                    <div class="card-title">{row.get('name', '')} ({row.get('symbol', '')})</div>
                    <div class="card-grid">
                        <div><span>Detected</span><strong>{row.get('detected', '')}</strong></div>
                        <div><span>Lead Days</span><strong>{row.get('first_danger_days', '')}</strong></div>
                        <div><span>R²</span><strong>{row.get('first_danger_r2', '')}</strong></div>
                    </div>
                </div>
                """
            )

        plots_html = []
        for section, paths in plot_paths.items():
            if not paths:
                continue
            images = []
            for path in paths:
                rel_path = os.path.relpath(path, self.output_dir)
                images.append(
                    f"""
                    <figure class="plot-item">
                        <img src="{rel_path}" alt="{os.path.basename(path)}" />
                        <figcaption>{os.path.basename(path)}</figcaption>
                    </figure>
                    """
                )
            plots_html.append(
                f"""
                <section class="plot-section">
                    <h2>{section}</h2>
                    <div class="plot-grid">
                        {''.join(images)}
                    </div>
                </section>
                """
            )

        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LPPL 验证报告</title>
  <style>
    body {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      margin: 0;
      padding: 32px;
      background: #f8fafc;
      color: #0f172a;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a, #1d4ed8);
      color: white;
      padding: 24px;
      border-radius: 16px;
      margin-bottom: 24px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}
    .stat, .card {{
      background: white;
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .card-title {{
      font-weight: 700;
      margin-bottom: 12px;
    }}
    .card-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .card-grid span {{
      display: block;
      font-size: 12px;
      color: #64748b;
    }}
    .card-grid strong {{
      font-size: 18px;
    }}
    .plot-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
    }}
    .plot-item {{
      background: white;
      border-radius: 14px;
      padding: 12px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .plot-item img {{
      width: 100%;
      border-radius: 10px;
      display: block;
    }}
    figcaption {{
      margin-top: 8px;
      font-size: 13px;
      color: #475569;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>LPPL 验证报告</h1>
    <p>模式: {mode_label}</p>
    <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </div>

  <div class="stats">
    <div class="stat"><div>总样本数</div><strong>{total}</strong></div>
    <div class="stat"><div>检测到预警</div><strong>{detected}</strong></div>
    <div class="stat"><div>检测率</div><strong>{detection_rate:.1f}%</strong></div>
  </div>

  <section>
    <h2>案例卡片</h2>
    {''.join(cards_html)}
  </section>

  {''.join(plots_html) if plots_html else '<p>暂无图片输出</p>'}
</body>
</html>
        """

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html)

        return file_path

```

---

## src/verification/__init__.py

```python
# -*- coding: utf-8 -*-

from .walk_forward import evaluate_future_drawdown, run_walk_forward, summarize_walk_forward

__all__ = ["evaluate_future_drawdown", "run_walk_forward", "summarize_walk_forward"]
```

---

## src/verification/walk_forward.py

```python
# -*- coding: utf-8 -*-
from typing import Dict, List, Tuple
import pandas as pd
from src.lppl_engine import LPPLConfig, process_single_day_ensemble, scan_single_date

def evaluate_future_drawdown(close_prices, idx: int, lookahead_days: int = 60, drop_threshold: float = 0.10) -> Tuple[bool, float]:
    future_prices = close_prices[idx + 1: idx + 1 + lookahead_days]
    if len(future_prices) == 0:
        return False, 0.0
    current_price = close_prices[idx]
    future_min = min(future_prices)
    realized_drop = (current_price - future_min) / current_price
    return realized_drop >= drop_threshold, realized_drop

def summarize_walk_forward(records_df: pd.DataFrame) -> Dict[str, float]:
    total_points = len(records_df)
    signal_count = int(records_df["signal_detected"].sum()) if total_points > 0 else 0
    event_count = int(records_df["event_hit"].sum()) if total_points > 0 else 0
    true_positive = int(((records_df["signal_detected"]) & (records_df["event_hit"])).sum()) if total_points > 0 else 0
    false_positive = int(((records_df["signal_detected"]) & (~records_df["event_hit"])).sum()) if total_points > 0 else 0
    false_negative = int(((~records_df["signal_detected"]) & (records_df["event_hit"])).sum()) if total_points > 0 else 0
    precision = true_positive / signal_count if signal_count > 0 else 0.0
    recall = true_positive / event_count if event_count > 0 else 0.0
    false_positive_rate = false_positive / total_points if total_points > 0 else 0.0
    signal_density = signal_count / total_points if total_points > 0 else 0.0
    return {"total_points": total_points, "signal_count": signal_count, "event_count": event_count, "true_positive": true_positive,
            "false_positive": false_positive, "false_negative": false_negative, "precision": precision, "recall": recall,
            "false_positive_rate": false_positive_rate, "signal_density": signal_density}

def run_walk_forward(df: pd.DataFrame, symbol: str, window_range: List[int], config: LPPLConfig, scan_step: int = 5,
                    lookahead_days: int = 60, drop_threshold: float = 0.10, use_ensemble: bool = False) -> Tuple[pd.DataFrame, Dict[str, float]]:
    df = df.sort_values("date").reset_index(drop=True).copy()
    df["date"] = pd.to_datetime(df["date"])
    close_prices = df["close"].values
    start_idx = max(window_range)
    end_idx = len(df) - lookahead_days - 1
    records: List[Dict] = []
    for idx in range(start_idx, end_idx + 1, scan_step):
        event_hit, realized_drop = evaluate_future_drawdown(close_prices, idx, lookahead_days, drop_threshold)
        if use_ensemble:
            signal_result = process_single_day_ensemble(close_prices, idx, window_range, min_r2=config.r2_threshold,
                                                        consensus_threshold=config.consensus_threshold, config=config)
            signal_detected = bool(signal_result and signal_result["predicted_crash_days"] < config.danger_days)
        else:
            signal_result = scan_single_date(close_prices, idx, window_range, config)
            signal_detected = bool(signal_result and signal_result.get("is_danger"))
        records.append({"symbol": symbol, "date": df.iloc[idx]["date"].strftime("%Y-%m-%d"), "price": float(df.iloc[idx]["close"]),
                       "signal_detected": signal_detected, "event_hit": event_hit, "realized_drop": realized_drop,
                       "lookahead_days": lookahead_days, "drop_threshold": drop_threshold, "mode": "ensemble" if use_ensemble else "single_window"})
    records_df = pd.DataFrame(records)
    summary = summarize_walk_forward(records_df)
    summary["symbol"] = symbol
    summary["mode"] = "ensemble" if use_ensemble else "single_window"
    summary["lookahead_days"] = lookahead_days
    summary["drop_threshold"] = drop_threshold
    return records_df, summary
```

---

## src/wyckoff/__init__.py

```python
# -*- coding: utf-8 -*-
"""Wyckoff Analysis Module - 基于 Richard Wyckoff 理论的 A 股实战分析系统"""
from src.wyckoff.analyzer import WyckoffAnalyzer
from src.wyckoff.config import WyckoffConfig, load_config
from src.wyckoff.data_engine import DataEngine
from src.wyckoff.engine import WyckoffEngine
from src.wyckoff.fusion_engine import FusionEngine, StateManager as MultimodalStateManager
from src.wyckoff.image_engine import ImageEngine
from src.wyckoff.models import (AnalysisResult, AnalysisState, BCPoint, BCResult, ChartManifest, ChartManifestItem, ChipAnalysis,
    ConfidenceLevel, CounterfactualResult, DailyRuleResult, EffortResult, ImageEvidenceBundle, LimitMove, LimitMoveType, MultiTimeframeContext,
    PhaseCTestResult, PhaseResult, PreprocessingResult, RiskRewardProjection, RiskAssessment, SCPoint, StressTest, SupportResistance,
    TimeframeSnapshot, TradingPlan, VisualEvidence, VolumeLevel, WyckoffPhase, WyckoffReport, WyckoffSignal, WyckoffStructure)
from src.wyckoff.state import StateManager

__all__ = ["WyckoffAnalyzer", "WyckoffEngine", "WyckoffPhase", "ConfidenceLevel", "WyckoffSignal", "TradingPlan", "WyckoffReport", "VolumeLevel",
           "BCPoint", "BCResult", "ChartManifest", "ChartManifestItem", "SCPoint", "SupportResistance", "WyckoffStructure", "RiskRewardProjection",
           "ImageEvidenceBundle", "AnalysisResult", "AnalysisState", "MultiTimeframeContext", "LimitMove", "LimitMoveType", "StressTest",
           "TimeframeSnapshot", "ChipAnalysis", "PreprocessingResult", "PhaseResult", "EffortResult", "PhaseCTestResult", "CounterfactualResult",
           "RiskAssessment", "DailyRuleResult", "VisualEvidence", "ImageEngine", "FusionEngine", "StateManager", "DataEngine", "WyckoffConfig",
           "load_config", "MultimodalStateManager"]
```

---

## src/wyckoff/analyzer.py

```python
# -*- coding: utf-8 -*-
"""
Wyckoff 核心分析引擎
基于 Richard Wyckoff 理论的 A 股实战分析
"""

import logging
from typing import List, Optional, Tuple

import pandas as pd

from src.wyckoff.models import (
    AnalysisState,
    BCPoint,
    ChipAnalysis,
    ConfidenceLevel,
    ImageEvidenceBundle,
    LimitMove,
    LimitMoveType,
    MultiTimeframeContext,
    RiskRewardProjection,
    SCPoint,
    StressTest,
    SupportResistance,
    TimeframeSnapshot,
    TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)

logger = logging.getLogger(__name__)


class WyckoffAnalyzer:
    """威科夫分析器"""
    
    def __init__(self, lookback_days: int = 120):
        self.lookback_days = lookback_days
        self.weekly_min_rows = 20
        self.monthly_min_rows = 12
        self.multi_timeframe_lookback_days = max(lookback_days, 800)

    def _normalize_input_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.sort_values("date").reset_index(drop=True)

    def _resample_ohlcv(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        frame = self._normalize_input_frame(df).set_index("date")
        resampled = (
            frame.resample(rule, label="right", closed="right")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return resampled

    def _build_timeframe_snapshot(self, report: WyckoffReport) -> TimeframeSnapshot:
        return TimeframeSnapshot(
            period=report.period,
            phase=report.structure.phase,
            unknown_candidate=report.structure.unknown_candidate,
            current_price=report.structure.current_price,
            current_date=report.structure.current_date,
            trading_range_high=report.structure.trading_range_high,
            trading_range_low=report.structure.trading_range_low,
            bc_price=report.structure.bc_point.price if report.structure.bc_point else None,
            sc_price=report.structure.sc_point.price if report.structure.sc_point else None,
            signal_type=report.signal.signal_type,
            signal_description=report.signal.description,
        )

    def _analyze_timeframe(
        self,
        df: pd.DataFrame,
        symbol: str,
        period: str,
        min_rows: int,
        lookback: int,
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        frame = self._normalize_input_frame(df)
        if frame is None or len(frame) < min_rows:
            reason = f"数据不足，需要至少 {min_rows} 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, period, reason)

        frame = frame.tail(lookback).reset_index(drop=True)

        bc_point, sc_point = self._scan_bc_sc(frame)

        if bc_point is None and sc_point is None:
            return self._create_no_signal_report(symbol, period, "未找到BC/SC点")

        structure = self._determine_wyckoff_structure(frame, bc_point, sc_point)
        signal = self._detect_wyckoff_signals(frame, structure)
        limit_moves = self._detect_limit_moves(frame)
        chip_analysis = self._analyze_chips(frame, structure)
        stress_tests = self._run_stress_tests(frame, structure, signal)
        risk_reward = self._calculate_risk_reward(frame, structure, signal)
        trading_plan = self._build_trading_plan(structure, signal, risk_reward, stress_tests)
        self._apply_t1_enforcement(signal, trading_plan, stress_tests)

        report = WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=trading_plan,
            limit_moves=limit_moves,
            stress_tests=stress_tests,
            chip_analysis=chip_analysis,
        )

        if image_evidence is not None and period == "日线":
            from src.wyckoff.fusion_engine import FusionEngine

            fusion_engine = FusionEngine()
            analysis_result = fusion_engine.fuse(report, image_evidence)
            report.analysis_result = analysis_result

            if hasattr(analysis_result, "confidence") and analysis_result.confidence:
                try:
                    conf_map = {
                        "A": ConfidenceLevel.A,
                        "B": ConfidenceLevel.B,
                        "C": ConfidenceLevel.C,
                        "D": ConfidenceLevel.D,
                    }
                    if analysis_result.confidence in conf_map:
                        report.trading_plan.confidence = conf_map[analysis_result.confidence]
                        report.signal.confidence = conf_map[analysis_result.confidence]
                except Exception as e:
                    logger.warning(f"无法更新置信度: {e}")

            from datetime import datetime

            analysis_state = AnalysisState(
                symbol=symbol,
                asset_type="stock" if symbol.endswith(".SH") or symbol.endswith(".SZ") else "index",
                analysis_date=datetime.now().strftime("%Y-%m-%d"),
                last_phase=report.structure.phase.value,
                last_micro_action=report.signal.signal_type,
                last_confidence=report.signal.confidence.value,
                bc_found=report.structure.bc_point is not None,
                spring_detected=report.signal.signal_type == "spring",
                weekly_context="",
                intraday_context="",
                last_decision=report.trading_plan.direction,
            )
            report.analysis_state = analysis_state

        return report
    
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        period: str = "日线",
        image_evidence: Optional[ImageEvidenceBundle] = None,
        multi_timeframe: bool = False,
    ) -> WyckoffReport:
        """
        执行完整威科夫分析
        
        Args:
            df: K线数据 DataFrame，需要包含 date, open, high, low, close, volume 列
            symbol: 指数/股票代码
            period: 分析周期
            image_evidence: 可选的图像证据包
            
        Returns:
            WyckoffReport: 完整的分析报告
        """
        if multi_timeframe and period == "日线":
            return self.analyze_multiframe(df, symbol=symbol, image_evidence=image_evidence)

        min_rows = 100 if period == "日线" else self.weekly_min_rows
        lookback = self.lookback_days if period == "日线" else max(min_rows, min(len(df), self.lookback_days))
        return self._analyze_timeframe(
            df=df,
            symbol=symbol,
            period=period,
            min_rows=min_rows,
            lookback=lookback,
            image_evidence=image_evidence,
        )

    def analyze_multiframe(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        frame = self._normalize_input_frame(df)
        if frame is None or len(frame) < 100:
            reason = f"数据不足，需要至少 100 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, "日线+周线+月线", reason)

        long_frame = frame.tail(self.multi_timeframe_lookback_days).reset_index(drop=True)
        weekly_df = self._resample_ohlcv(long_frame, "W-FRI")
        monthly_df = self._resample_ohlcv(long_frame, "ME")

        daily_report = self._analyze_timeframe(
            df=frame,
            symbol=symbol,
            period="日线",
            min_rows=100,
            lookback=self.lookback_days,
            image_evidence=image_evidence,
        )
        weekly_report = self._analyze_timeframe(
            df=weekly_df,
            symbol=symbol,
            period="周线",
            min_rows=self.weekly_min_rows,
            lookback=min(len(weekly_df), 180),
        )
        monthly_report = self._analyze_timeframe(
            df=monthly_df,
            symbol=symbol,
            period="月线",
            min_rows=self.monthly_min_rows,
            lookback=min(len(monthly_df), 120),
        )

        return self._merge_multitimeframe_reports(
            symbol=symbol,
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

    def _merge_multitimeframe_reports(
        self,
        symbol: str,
        daily_report: WyckoffReport,
        weekly_report: WyckoffReport,
        monthly_report: WyckoffReport,
    ) -> WyckoffReport:
        final_report = daily_report
        monthly_phase = monthly_report.structure.phase
        weekly_phase = weekly_report.structure.phase
        daily_phase = daily_report.structure.phase
        rr_ratio = final_report.risk_reward.reward_risk_ratio or 0.0

        alignment = "mixed"
        if monthly_phase == weekly_phase == daily_phase:
            alignment = "fully_aligned"
        elif weekly_phase == daily_phase:
            alignment = "weekly_daily_aligned"
        elif monthly_phase == weekly_phase:
            alignment = "higher_timeframe_aligned"

        summary = (
            f"月线={monthly_phase.value} / 周线={weekly_phase.value} / 日线={daily_phase.value}"
        )
        constraint_note = "维持日线结论"
        markup_keywords = ("Spring→ST→SOS", "Lack of Supply", "Test", "Shakeout", "BUEC", "Phase E", "SOS")
        markup_context = final_report.signal.description or ""

        if monthly_phase == WyckoffPhase.MARKDOWN or weekly_phase == WyckoffPhase.MARKDOWN:
            final_report.structure.phase = WyckoffPhase.MARKDOWN
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = (
                f"上级周期压制明确：月线={monthly_phase.value}，周线={weekly_phase.value}，"
                "当前按 Markdown 风险处理，A股禁止做空，维持空仓观望"
            )
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = final_report.signal.description
            final_report.trading_plan.preconditions = "等待周线止跌或重新进入可定义的积累结构"
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = "上级周期为 Markdown，覆盖日线做多倾向"
        elif monthly_phase == WyckoffPhase.DISTRIBUTION or weekly_phase == WyckoffPhase.DISTRIBUTION:
            final_report.structure.phase = WyckoffPhase.DISTRIBUTION
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = (
                f"上级周期派发风险未解除：月线={monthly_phase.value}，周线={weekly_phase.value}，"
                "当前仅允许空仓观察"
            )
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = final_report.signal.description
            final_report.trading_plan.preconditions = "等待周线重新完成止跌或积累验证"
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = "上级周期派发压力覆盖日线信号"
        elif weekly_phase == WyckoffPhase.UNKNOWN and daily_phase == WyckoffPhase.MARKUP:
            final_report.signal.confidence = ConfidenceLevel.C
            final_report.trading_plan.confidence = ConfidenceLevel.C
            if monthly_phase == WyckoffPhase.MARKUP and rr_ratio >= 2.5 and any(
                keyword in markup_context for keyword in markup_keywords
            ):
                if "Phase E" in markup_context or "Lack of Supply" in markup_context:
                    final_report.trading_plan.direction = "持有观察 / 空仓者观望"
                else:
                    final_report.trading_plan.direction = "买入观察 / 轻仓试探"
                final_report.trading_plan.preconditions = (
                    "周线结构仍未完全确认，只允许沿日线右侧结构做观察或轻仓试探，"
                    "不得脱离 LPS/Test/BUEC 纪律追价"
                )
                constraint_note = "周线未确认，但月线仍偏多，保留日线右侧观察语义"
            else:
                final_report.trading_plan.direction = "空仓观望"
                final_report.trading_plan.preconditions = "周线结构未确认，日线信号仅作观察"
                constraint_note = "周线未确认，日线做多信号自动降级"
        elif monthly_phase == WyckoffPhase.MARKUP and weekly_phase == WyckoffPhase.MARKUP:
            if (
                final_report.trading_plan.direction == "空仓观望"
                and "Phase E" in final_report.signal.description
                and rr_ratio > 0
            ):
                final_report.trading_plan.direction = "持有观察"
            elif rr_ratio <= 0:
                final_report.trading_plan.direction = "空仓观望"
                final_report.trading_plan.current_qualification = (
                    "多周期上涨结构成立，但当前位置已明显脱离低风险击球区，"
                    "短线盈亏比不再有效，按 No Trade Zone 处理"
                )
                final_report.trading_plan.preconditions = "等待回踩 LPS/BUEC 或重新形成可定义低风险结构"
            elif final_report.trading_plan.direction == "空仓观望" and rr_ratio >= 2.5:
                if "Lack of Supply / Test" in markup_context or "Shakeout/Test" in markup_context:
                    final_report.trading_plan.direction = "买入观察 / 轻仓试探"
                    final_report.trading_plan.preconditions = (
                        "月线与周线同向偏多，日线处于回踩测试区，仅允许围绕 LPS/Test 轻仓试探"
                    )
                elif "Lack of Supply" in markup_context or "SOS" in markup_context:
                    final_report.trading_plan.direction = "持有观察 / 空仓者观望"
                    final_report.trading_plan.preconditions = (
                        "月线与周线同向偏多，日线处于推进或蓄势段，优先持有观察，空仓者等待更优击球点"
                    )
            if final_report.signal.confidence == ConfidenceLevel.A:
                final_report.signal.confidence = ConfidenceLevel.B
            final_report.trading_plan.confidence = final_report.signal.confidence
            constraint_note = "月线与周线共振支持日线上涨结构"

        if (
            daily_phase == WyckoffPhase.MARKDOWN
            and monthly_phase == WyckoffPhase.MARKUP
            and weekly_phase == WyckoffPhase.MARKUP
            and final_report.structure.trading_range_low is not None
            and final_report.structure.current_price is not None
            and final_report.structure.current_price <= final_report.structure.trading_range_low * 1.03
        ):
            final_report.structure.phase = WyckoffPhase.UNKNOWN
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.C
            final_report.signal.description = (
                "上级周期仍偏多，但日线在区间下沿附近出现 SC / Phase A 候选扰动，"
                "当前保持不确定性观察"
            )
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = final_report.signal.description
            final_report.trading_plan.preconditions = "等待 AR / ST / Phase B 结构补全"
            final_report.trading_plan.trigger_condition = "观察是否出现 SC 后的 AR 反弹与 ST 回测"
            final_report.trading_plan.invalidation_point = (
                f"若继续失守 {final_report.structure.trading_range_low:.2f} 则回归 Markdown"
            )
            final_report.trading_plan.first_target = "第一观察目标 AR 反弹确认"
            final_report.trading_plan.confidence = ConfidenceLevel.C
            constraint_note = "高周期未破坏，但日线正在测试潜在 SC / Phase A 低点"
        elif (
            final_report.structure.phase == WyckoffPhase.UNKNOWN
            and monthly_phase == WyckoffPhase.MARKUP
            and weekly_phase in {WyckoffPhase.MARKUP, WyckoffPhase.UNKNOWN}
        ):
            unknown_candidate = final_report.structure.unknown_candidate
            trigger_parts = ["等待 ST 缩量确认"]
            if final_report.structure.trading_range_high is not None:
                trigger_parts.append(
                    f"或放量突破 {final_report.structure.trading_range_high:.2f} 后再确认"
                )
            qualification = "上级周期仍偏多，"
            if unknown_candidate == "phase_a_candidate":
                qualification += "日线按再积累 / Phase A-AR 反弹观察区处理，暂不追价，等待 ST 或 Phase B 边界清晰"
            elif unknown_candidate == "sc_st_candidate":
                qualification += "日线按再积累 / SC-ST 候选扰动区处理，等待吸收完成后的二次确认"
            elif unknown_candidate == "upthrust_candidate":
                qualification += "日线按再积累 / Phase B-Upthrust 候选区处理，优先等待假突破失败后的回落确认"
            else:
                qualification += "日线按再积累 / Phase B 观察区处理，等待更清晰的 TR 结构"
            final_report.trading_plan.current_qualification = qualification
            final_report.trading_plan.trigger_condition = "，".join(trigger_parts)
            final_report.trading_plan.invalidation_point = (
                f"失守 {final_report.structure.trading_range_low:.2f} 则回到更弱结构"
                if final_report.structure.trading_range_low is not None
                else "失守近期低点则放弃观察"
            )
            final_report.trading_plan.first_target = (
                f"第一观察目标 {final_report.structure.trading_range_high:.2f}"
                if final_report.structure.trading_range_high is not None
                else "第一观察目标 TR 上沿确认"
            )
            final_report.trading_plan.preconditions = "上级周期偏多，但日线尚未给出可执行的 LPS/Breakout 触发"
            final_report.trading_plan.confidence = ConfidenceLevel.C
            if (
                weekly_phase == WyckoffPhase.MARKUP
                and rr_ratio >= 2.5
                and unknown_candidate in {"phase_a_candidate", "sc_st_candidate"}
            ):
                final_report.trading_plan.direction = "买入观察 / 轻仓试探"
                final_report.trading_plan.preconditions = (
                    "上级周期偏多，日线已进入 Phase A/AR 或 SC/ST 低位候选区，"
                    "仅允许围绕 ST/AR 确认做轻仓试探"
                )
            constraint_note = "上级周期偏多，保留日线 Phase A/B 结构化等待计划"

        if (
            final_report.structure.phase == WyckoffPhase.ACCUMULATION
            and final_report.signal.signal_type == "no_signal"
            and rr_ratio >= 2.5
            and monthly_phase not in {WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION}
            and weekly_phase not in {WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION}
        ):
            trigger_note = (
                "日线处于积累/再积累结构且赔率充足，但周线事件触发不足，"
                "当前仅跟踪 Spring/Test/LPS 触发"
            )
            if final_report.trading_plan.current_qualification:
                if trigger_note not in final_report.trading_plan.current_qualification:
                    final_report.trading_plan.current_qualification = (
                        f"{final_report.trading_plan.current_qualification}；{trigger_note}"
                    )
            else:
                final_report.trading_plan.current_qualification = trigger_note
            final_report.trading_plan.preconditions = (
                "等待日线出现 Spring 后缩量测试、LPS 站稳或 TR 上沿有效突破"
            )
            if "等待触发" not in final_report.signal.description:
                final_report.signal.description = (
                    f"{final_report.signal.description}；多周期未压制，但需等待触发确认"
                )

        final_report.period = "日线+周线+月线"
        final_report.multi_timeframe = MultiTimeframeContext(
            enabled=True,
            monthly=self._build_timeframe_snapshot(monthly_report),
            weekly=self._build_timeframe_snapshot(weekly_report),
            daily=self._build_timeframe_snapshot(daily_report),
            alignment=alignment,
            summary=summary,
            constraint_note=constraint_note,
        )

        if final_report.analysis_state is not None:
            final_report.analysis_state.weekly_context = (
                f"月线={monthly_phase.value}; 周线={weekly_phase.value}; 日线={daily_phase.value}"
            )

        return final_report
    
    def _scan_bc_sc(self, df: pd.DataFrame) -> Tuple[Optional[BCPoint], Optional[SCPoint]]:
        """
        扫描 BC 和 SC 点（增强版）
        
        BC 识别逻辑：
        1. 阶段性高点（50 日内最高或次高）
        2. 放量（>1.5 倍均量或百分位>0.7）
        3. 长上影线（high-close > 0.5*(high-low)）
        4. 后续有回调确认（高点后价格下跌>5%）
        
        SC 识别逻辑：
        1. 阶段性低点（50 日内最低或次低）
        2. 放量或极度缩量
        3. 长下影线（close-low > 0.5*(high-low)）
        4. 后续有反弹确认
        """
        bc_point = None
        sc_point = None
        
        df = df.copy()
        df["vol_rank"] = df["volume"].rank(pct=True)
        df["range"] = df["high"] - df["low"]
        df["upper_shadow"] = df["high"] - df["close"]
        df["lower_shadow"] = df["close"] - df["low"]
        df["shadow_ratio"] = df["upper_shadow"] / (df["range"] + 1e-9)
        df["lower_shadow_ratio"] = df["lower_shadow"] / (df["range"] + 1e-9)
        
        # 寻找峰值和谷值
        peak_idx = df["high"].idxmax()
        trough_idx = df["low"].idxmin()
        
        # BC 点增强识别
        bc_candidates = []
        for idx in df.nlargest(5, "high").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            shadow_ratio = row["shadow_ratio"]
            
            # 评分系统
            score = 0
            if vol_rank > 0.8:
                score += 2
            elif vol_rank > 0.6:
                score += 1
            
            if shadow_ratio > 0.6:  # 长上影
                score += 2
            elif shadow_ratio > 0.4:
                score += 1
            
            # 检查后续回调
            peak_pos = df.index.get_loc(idx)
            if peak_pos < len(df) - 5:
                subsequent_low = df.iloc[peak_pos+1:peak_pos+10]["close"].min()
                peak_price = row["high"]
                if (peak_price - subsequent_low) / peak_price > 0.05:
                    score += 2  # 有确认回调
            
            bc_candidates.append((idx, score, row))
        
        # 选择最佳 BC 候选
        bc_candidates.sort(key=lambda x: x[1], reverse=True)
        if bc_candidates:
            best_bc = bc_candidates[0]
            idx, score, row = best_bc
            volume_level = self._classify_volume(row["volume"], df["volume"])
            bc_point = BCPoint(
                date=str(row["date"]),
                price=float(row["high"]),
                volume_level=volume_level,
                is_extremum=(idx == peak_idx),
                confidence_score=score,  # 自定义字段，用于置信度计算
            )
        
        # SC 点增强识别
        sc_candidates = []
        for idx in df.nsmallest(5, "low").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            lower_shadow_ratio = row["lower_shadow_ratio"]
            
            # 评分系统
            score = 0
            if vol_rank > 0.8:  # 放量
                score += 2
            elif vol_rank < 0.2:  # 极度缩量（恐慌后无人卖出）
                score += 1
            
            if lower_shadow_ratio > 0.6:  # 长下影
                score += 2
            elif lower_shadow_ratio > 0.4:
                score += 1
            
            # 检查后续反弹
            trough_pos = df.index.get_loc(idx)
            if trough_pos < len(df) - 5:
                subsequent_high = df.iloc[trough_pos+1:trough_pos+10]["close"].max()
                trough_price = row["low"]
                if (subsequent_high - trough_price) / trough_price > 0.05:
                    score += 2  # 有确认反弹
            
            sc_candidates.append((idx, score, row))
        
        # 选择最佳 SC 候选
        sc_candidates.sort(key=lambda x: x[1], reverse=True)
        if sc_candidates:
            best_sc = sc_candidates[0]
            idx, score, row = best_sc
            volume_level = self._classify_volume(row["volume"], df["volume"])
            sc_point = SCPoint(
                date=str(row["date"]),
                price=float(row["low"]),
                volume_level=volume_level,
                is_extremum=(idx == trough_idx),
                confidence_score=score,
            )
        
        return bc_point, sc_point
    
    def _classify_volume(self, volume: float, volume_series: pd.Series) -> VolumeLevel:
        """相对量能分类"""
        mean_vol = volume_series.mean()
        vol_ratio = volume / mean_vol
        
        if vol_ratio > 2.0:
            return VolumeLevel.EXTREME_HIGH
        elif vol_ratio > 1.5:
            return VolumeLevel.HIGH
        elif vol_ratio > 0.7:
            return VolumeLevel.AVERAGE
        elif vol_ratio > 0.4:
            return VolumeLevel.LOW
        else:
            return VolumeLevel.EXTREME_LOW
    
    def _detect_limit_moves(self, df: pd.DataFrame) -> List[LimitMove]:
        """检测涨跌停与炸板异动"""
        limit_moves = []
        
        recent = df.tail(20)
        
        for idx, row in recent.iterrows():
            pct_change = (row["close"] - row["open"]) / row["open"]
            is_limit_up = pct_change > 0.095
            is_limit_down = pct_change < -0.095
            
            if not is_limit_up and not is_limit_down:
                continue
            
            high_change = (row["high"] - row["open"]) / row["open"]
            low_change = (row["low"] - row["open"]) / row["open"]
            
            if is_limit_up:
                if high_change < 0.095:
                    move_type = LimitMoveType.BREAK_LIMIT_UP
                    is_broken = True
                else:
                    move_type = LimitMoveType.LIMIT_UP
                    is_broken = False
            else:
                if low_change > -0.095:
                    move_type = LimitMoveType.BREAK_LIMIT_DOWN
                    is_broken = True
                else:
                    move_type = LimitMoveType.LIMIT_DOWN
                    is_broken = False
            
            volume_level = self._classify_volume(row["volume"], df["volume"])
            
            limit_moves.append(LimitMove(
                date=str(row["date"]),
                move_type=move_type,
                price=float(row["close"]),
                volume_level=volume_level,
                is_broken=is_broken,
            ))
        
        return limit_moves
    
    def _analyze_chips(self, df: pd.DataFrame, structure: WyckoffStructure) -> ChipAnalysis:
        """筹码微观分析"""
        analysis = ChipAnalysis()
        
        recent = df.tail(20)
        
        price_change = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[0]
        volume_change = (recent["volume"].iloc[-1] - recent["volume"].iloc[0]) / recent["volume"].iloc[0]
        
        if price_change > 0.05 and volume_change < -0.3:
            analysis.volume_price_divergence = True
            analysis.warnings.append("量价背离：价格上涨但量能萎缩")
        
        if price_change < -0.05 and volume_change > 0.3:
            analysis.distribution_signature = True
        
        if price_change > 0.05 and volume_change > 0.2:
            analysis.absorption_signature = True
            analysis.institutional_footprint = True
        
        if structure.phase == WyckoffPhase.MARKUP:
            vol_trend = pd.Series(recent["volume"].values).corr(pd.Series(range(len(recent))))
            if vol_trend < -0.3:
                analysis.warnings.append("上涨中量能递减，需警惕")
        
        return analysis
    
    def _run_stress_tests(
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure,
        signal: WyckoffSignal
    ) -> List[StressTest]:
        """反事实压力测试"""
        stress_tests = []
        
        if structure.trading_range_low is None or structure.current_price is None:
            return stress_tests
        
        current = structure.current_price
        low = structure.trading_range_low
        
        test1 = StressTest(
            scenario_name="假突破跌破",
            scenario_description=f"如果价格跌破支撑位 {low:.2f} 会怎样",
            outcome="",
            passes=False,
        )
        break_scenario = current * 0.97
        if break_scenario < low:
            test1.outcome = "支撑失守，可能加速下跌"
            test1.risk_level = "高"
            test1.passes = False
        else:
            test1.outcome = "仍在支撑上方运行"
            test1.risk_level = "低"
            test1.passes = True
        stress_tests.append(test1)
        
        test2 = StressTest(
            scenario_name="恶劣天气",
            scenario_description="如果大盘暴跌 5% 会怎样",
            outcome="",
            passes=False,
        )
        adverse_scenario = current * 0.95
        if adverse_scenario < low:
            test2.outcome = "可能被拖累跌破支撑"
            test2.risk_level = "高"
            test2.passes = False
        else:
            test2.outcome = "有支撑保护"
            test2.risk_level = "中"
            test2.passes = True
        stress_tests.append(test2)
        
        test3 = StressTest(
            scenario_name="假突破高",
            scenario_description="如果现在入场后假突破怎么办",
            outcome="",
            passes=False,
        )
        if signal.signal_type == "spring":
            test3.outcome = "需等待二次确认"
            test3.risk_level = "中"
            test3.passes = True
        else:
            test3.outcome = "未到Spring，等待信号"
            test3.risk_level = "低"
            test3.passes = True
        stress_tests.append(test3)
        
        return stress_tests
    
    def _apply_t1_enforcement(
        self, 
        signal: WyckoffSignal,
        trading_plan: Optional[TradingPlan],
        stress_tests: List[StressTest]
    ) -> None:
        """T+1 零容错强制执行"""
        if trading_plan is None:
            return
        
        if signal.signal_type == "spring":
            signal.description += " [Spring冷静期3天]"
            trading_plan.spring_cooldown_days = 3
            trading_plan.direction = "空仓观望"
        
        has_high_risk = any(st.risk_level == "高" for st in stress_tests)
        
        if has_high_risk and signal.signal_type == "spring":
            trading_plan.t1_blocked = True
            trading_plan.direction = "T+1零容错阻止，空仓观望"
            trading_plan.trigger_condition = "风险过高，禁止入场"
        
    def _determine_wyckoff_structure(
        self,
        df: pd.DataFrame,
        bc_point: Optional[BCPoint],
        sc_point: Optional[SCPoint]
    ) -> WyckoffStructure:
        """
        确定威科夫宏观阶段与结构边界

        阶段判断顺序：
        1. 先检测最近 60 日是否处于横盘震荡区间（TR）
           - 判定标准：(最高-最低)/最低 <= 20%，且近期短趋势幅度 < 5%
        2. 若处于 TR，则看 TR 前的趋势方向：
           - TR 前有明显下跌（>10%） → ACCUMULATION
           - TR 前有明显上涨（>10%） → DISTRIBUTION
           - 前期趋势不明显 → UNKNOWN（保守处理）
        3. 若不处于 TR，则按近期短趋势方向判定：
           - 上行趋势 → MARKUP
           - 下行趋势 → MARKDOWN
           - 趋势不明 → UNKNOWN
        4. BC / SC 位置仅用于支撑阻力与边界辅助，不主导阶段判断
        """
        structure = WyckoffStructure()
        structure.bc_point = bc_point
        structure.sc_point = sc_point

        # --- Step 1：计算近 60 日价格振幅，判断是否处于 TR ---
        recent_60 = df.tail(60)
        price_high = float(recent_60["high"].max())
        price_low = float(recent_60["low"].min())
        current_price = float(df.iloc[-1]["close"])
        ma5 = float(df.tail(5)["close"].mean())
        ma20 = float(df.tail(20)["close"].mean())
        total_range_pct = (price_high - price_low) / price_low if price_low > 0 else 1.0
        relative_position = (
            (current_price - price_low) / (price_high - price_low)
            if price_high > price_low
            else 0.5
        )

        # 近 20 日 vs 前 20 日均价变化，衡量短期趋势
        if len(df) >= 40:
            recent_mean = float(df.tail(20)["close"].mean())
            prev_mean = float(df.iloc[-40:-20]["close"].mean())
        else:
            recent_mean = float(df.tail(10)["close"].mean())
            prev_mean = float(df.head(10)["close"].mean())
        short_trend_pct = (recent_mean - prev_mean) / prev_mean if prev_mean > 0 else 0.0

        is_in_trading_range = (total_range_pct <= 0.20) and (abs(short_trend_pct) < 0.05)

        if is_in_trading_range:
            # --- Step 2：TR 内，看 TR 前的方向来区分 Accumulation vs Distribution ---
            # 用 TR 起点前 40 根 K 线的头尾收盘价判断先前趋势
            prior_window = df.iloc[:-60] if len(df) > 60 else pd.DataFrame()
            if len(prior_window) >= 10:
                prior_first = float(prior_window["close"].iloc[0])
                prior_last = float(prior_window["close"].iloc[-1])
                prior_trend_pct = (prior_last - prior_first) / prior_first if prior_first > 0 else 0.0
            else:
                prior_trend_pct = 0.0

            if prior_trend_pct < -0.10:
                # TR 前有明显下跌：主力可能正在低位吸筹 → Accumulation
                structure.phase = WyckoffPhase.ACCUMULATION
            elif prior_trend_pct > 0.10:
                # TR 前有明显上涨：主力可能正在高位派发 → Distribution
                structure.phase = WyckoffPhase.DISTRIBUTION
            else:
                # 前期趋势不明显时，结合 BC/SC、均线位置和当前相对位置做回退判定。
                if relative_position <= 0.40 and bc_point is not None:
                    structure.phase = WyckoffPhase.ACCUMULATION
                elif (
                    (relative_position >= 0.55 or short_trend_pct >= 0.03)
                    and (
                        (current_price > ma20 * 0.97 and ma5 >= ma20 * 0.97)
                        or (current_price > ma5 and relative_position >= 0.50)
                    )
                ):
                    structure.phase = WyckoffPhase.MARKUP
                elif (
                    bc_point is not None
                    and current_price <= bc_point.price * 0.90
                    and current_price < ma20
                    and ma5 <= ma20
                    and short_trend_pct <= 0
                ):
                    structure.phase = WyckoffPhase.MARKDOWN
                else:
                    structure.phase = WyckoffPhase.UNKNOWN
                    logger.debug(
                        "TR 前趋势幅度不足 10%%（prior_trend=%.2f%%），且 BC/SC "
                        "回退判定不足，降级为 UNKNOWN",
                        prior_trend_pct * 100,
                    )
        else:
            # --- Step 3：非 TR，按短期趋势方向判定 Markup / Markdown ---
            if short_trend_pct >= 0.03 and (
                (current_price > ma20 and ma5 >= ma20)
                or (current_price > ma5 and relative_position >= 0.50)
            ):
                structure.phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.015
                and current_price > ma20
                and ma5 >= ma20 * 0.98
                and relative_position >= 0.70
            ):
                structure.phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.05
                and ma5 >= ma20
                and current_price >= ma20 * 0.99
                and relative_position >= 0.65
            ):
                # 强势上涨过程中的正常回撤不应直接降级为 UNKNOWN。
                structure.phase = WyckoffPhase.MARKUP
            elif short_trend_pct <= -0.03 and current_price < ma20:
                structure.phase = WyckoffPhase.MARKDOWN
            elif (
                bc_point is not None
                and current_price <= bc_point.price * 0.90
                and current_price < ma20
                and ma5 <= ma20
                and short_trend_pct <= 0
            ):
                structure.phase = WyckoffPhase.MARKDOWN
            elif (
                bc_point is not None
                and short_trend_pct <= -0.04
                and relative_position <= 0.20
                and current_price <= bc_point.price * 0.78
            ):
                structure.phase = WyckoffPhase.MARKDOWN
            elif (
                sc_point is not None
                and short_trend_pct >= 0.03
                and total_range_pct <= 0.60
                and relative_position >= 0.75
                and current_price >= sc_point.price * 1.20
                and current_price > ma20
                and ma5 >= ma20 * 0.99
            ):
                structure.phase = WyckoffPhase.MARKUP
            else:
                structure.phase = WyckoffPhase.UNKNOWN

        # --- 区间边界计算（取近 30 日极值） ---
        recent_df = df.tail(30)
        structure.trading_range_high = float(recent_df["high"].max())
        structure.trading_range_low = float(recent_df["low"].min())
        structure.current_price = current_price
        structure.current_date = str(df.iloc[-1]["date"])

        if structure.phase == WyckoffPhase.UNKNOWN:
            structure.unknown_candidate = self._classify_unknown_candidate(
                df=df,
                structure=structure,
            )
        else:
            structure.unknown_candidate = ""

        # --- 支撑 / 阻力位（BC/SC 作为关键锚点） ---
        if bc_point is not None:
            structure.support_levels.append(
                SupportResistance(
                    level=bc_point.price,
                    type="support",
                    source="BC",
                    strength=0.8,
                )
            )
        if sc_point is not None:
            structure.resistance_levels.append(
                SupportResistance(
                    level=sc_point.price,
                    type="resistance",
                    source="SC",
                    strength=0.8,
                )
            )

        return structure

    def _classify_unknown_candidate(
        self,
        df: pd.DataFrame,
        structure: WyckoffStructure,
    ) -> str:
        if structure.phase != WyckoffPhase.UNKNOWN or df.empty:
            return ""

        if structure.trading_range_low is None or structure.trading_range_high is None:
            return "unknown_range"

        last_row = df.iloc[-1]
        close_price = float(last_row["close"])
        open_price = float(last_row["open"])
        high_price = float(last_row["high"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0

        range_low = structure.trading_range_low
        range_high = structure.trading_range_high
        if range_high <= range_low:
            return "unknown_range"

        range_span = range_high - range_low
        relative_position = (close_price - range_low) / range_span
        close_location = (close_price - low_price) / max(high_price - low_price, 0.01)

        if (
            relative_position <= 0.38
            and close_location >= 0.58
            and (lower_wick > max(body, 0.01) or vol_ratio >= 1.05)
        ):
            return "sc_st_candidate"
        if (
            relative_position <= 0.50
            and close_price >= open_price
            and close_location >= 0.62
            and vol_ratio >= 0.95
        ):
            return "phase_a_candidate"
        if (
            relative_position >= 0.62
            and upper_wick > max(body * 1.2, 0.01)
            and vol_ratio >= 1.0
        ):
            return "upthrust_candidate"
        if 0.38 < relative_position < 0.68:
            return "phase_b_range"
        return "unknown_range"
    
    def _detect_wyckoff_signals(
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure
    ) -> WyckoffSignal:
        """
        检测威科夫事件信号

        产出的 signal_type 为结构事件枚举，只允许：
        spring / utad / sos_candidate / no_signal
        严禁将宏观阶段名（如 'accumulation'）写入 signal_type。
        """
        signal = WyckoffSignal()
        signal.phase = structure.phase

        last_price = structure.current_price
        last_vol = df.iloc[-1]["volume"]
        last_low = float(df.iloc[-1]["low"])
        last_high = float(df.iloc[-1]["high"])
        volume_level = self._classify_volume(last_vol, df["volume"])
        signal.volume_confirmation = volume_level

        # A 股铁律：Distribution / Markdown 阶段禁止给任何做多方向信号
        if structure.phase in [WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION]:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = self._describe_markdown_context(df, structure)
            return signal

        # 阶段不明确：保守处理
        if structure.phase == WyckoffPhase.UNKNOWN:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = self._describe_unknown_context(df, structure)
            return signal

        # BC 未定位：无法做任何方向推演（SPEC RC §4.3 强制规则）
        if structure.bc_point is None:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = "未找到 BC 点，无法确认趋势方向，放弃"
            return signal

        # --- Spring 检测：仅在 ACCUMULATION 阶段有效 ---
        # Spring = 价格刺穿或接近区间下边界，且随即快速收回
        if (structure.phase == WyckoffPhase.ACCUMULATION
                and structure.trading_range_low is not None):
            low_bound = structure.trading_range_low
            close_near_low = last_price <= low_bound * 1.018
            intraday_spring = (
                last_low <= low_bound * 1.01
                and last_price >= last_low * 1.015
            )
            if close_near_low or intraday_spring:
                signal.signal_type = "spring"
                signal.trigger_price = last_price
                signal.confidence = ConfidenceLevel.B
                signal.description = (
                    f"价格回踩震荡区间下边界 {low_bound:.2f} 附近，"
                    "检测到日线 Spring 候选信号，需等待 T+3 冷冻期后二次确认"
                )
                signal.t1_risk评估 = self._assess_t1_risk(df, structure, last_price)
                return signal

            if len(df) >= 3:
                recent3 = df.tail(3)
                prior_close = float(df.iloc[-2]["close"])
                recent_low3 = float(recent3["low"].min())
                spring_cluster = recent_low3 <= low_bound * 1.02
                bullish_reclaim = last_price >= prior_close * 1.02
                last_close_strong = last_price >= (last_high + last_low) / 2
                volume_contracting = last_vol <= float(recent3.iloc[:-1]["volume"].max())
                if spring_cluster and bullish_reclaim and last_close_strong and volume_contracting:
                    structure.phase = WyckoffPhase.MARKUP
                    signal.phase = WyckoffPhase.MARKUP
                    signal.signal_type = "sos_candidate"
                    signal.trigger_price = last_price
                    signal.confidence = ConfidenceLevel.B
                    signal.description = (
                        "Spring→ST→SOS 三步确认完成，结构从 Phase C/Phase D 观察区"
                        "转入右侧 Markup 启动段"
                    )
                    return signal

        # --- SOS 候选：价格接近区间上边界，可能进入 Markup ---
        if (signal.signal_type == "no_signal"
                and structure.trading_range_high is not None):
            high_bound = structure.trading_range_high
            recent_breakout = last_price >= df.tail(5)["close"].max() * 0.995
            close_strong = last_price >= last_high * 0.985
            if last_price >= high_bound * 0.98 or (
                structure.phase == WyckoffPhase.MARKUP
                and recent_breakout
                and close_strong
            ):
                signal.signal_type = "sos_candidate"
                signal.trigger_price = last_price
                signal.confidence = ConfidenceLevel.B if structure.phase == WyckoffPhase.MARKUP else ConfidenceLevel.C
                signal.description = (
                    f"价格向震荡区间上边界 {high_bound:.2f} 发起攻击，"
                    "出现日线 SOS/LPS 观察信号，仅允许按 V3.0 纪律等待确认"
                )
                if structure.phase == WyckoffPhase.MARKUP:
                    signal.description = self._describe_markup_context(df, structure, default=signal.description)
                return signal

        # --- 无明确事件信号：保守降级为空仓观望（不得编造方向结论）---
        # SPEC §12 强制保守降级清单：信号不明确时输出 no_signal，置信度 D
        signal.signal_type = "no_signal"
        signal.confidence = ConfidenceLevel.D
        if structure.phase == WyckoffPhase.MARKUP:
            signal.description = self._describe_markup_context(df, structure)
        else:
            signal.description = (
                f"当前处于 {structure.phase.value} 阶段，"
                "价格在区间内部运行，无明确事件信号，建议空仓观望，等待 Spring 或 SOS 确认"
            )
        return signal

    def _describe_markdown_context(self, df: pd.DataFrame, structure: WyckoffStructure) -> str:
        last_row = df.iloc[-1]
        open_price = float(last_row["open"])
        close_price = float(last_row["close"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        lower_wick = min(close_price, open_price) - low_price
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0
        recent_low = float(df.tail(min(20, len(df)))["low"].min())

        if lower_wick > max(body * 1.5, 0.01) and vol_ratio >= 1.5 and low_price <= recent_low * 1.01:
            return "当前处于 Markdown 延续阶段，但日线出现 SC 候选异动，仍需空仓观望，等待 AR/ST 结构补全"

        return "当前处于 Markdown/派发下跌阶段，A 股禁止做空，建议空仓观望"

    def _describe_unknown_context(self, df: pd.DataFrame, structure: WyckoffStructure) -> str:
        if structure.unknown_candidate == "phase_a_candidate":
            return "阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确"
        if structure.unknown_candidate == "sc_st_candidate":
            return "阶段不明确，当前出现 SC/ST 候选扰动，但证据不足，建议空仓观望"
        if structure.unknown_candidate == "upthrust_candidate":
            return "阶段不明确，当前更像 Phase B / Upthrust 观察区，建议空仓等待方向重新选择"
        if structure.unknown_candidate == "phase_b_range":
            return "阶段不明确，当前更像 Phase B 震荡观察区，建议等待 TR 边界和 ST/UT 进一步清晰"

        last_row = df.iloc[-1]
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0
        close_price = float(last_row["close"])
        open_price = float(last_row["open"])
        high_price = float(last_row["high"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        range_low = structure.trading_range_low
        range_high = structure.trading_range_high
        relative_position = 0.5
        close_location = 0.5
        if range_low is not None and range_high is not None and range_high > range_low:
            range_span = range_high - range_low
            relative_position = (close_price - range_low) / range_span
            close_location = (close_price - low_price) / max(high_price - low_price, 0.01)

        if structure.sc_point is not None and close_price >= structure.sc_point.price * 1.08 and vol_ratio >= 1.2:
            return "阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确"
        if (
            relative_position >= 0.62
            and upper_wick > max(body * 1.2, 0.01)
            and vol_ratio >= 1.0
        ):
            return "阶段不明确，当前更像 Phase B / Upthrust 观察区，建议空仓等待方向重新选择"
        if (
            relative_position <= 0.38
            and close_location >= 0.58
            and (lower_wick > max(body, 0.01) or vol_ratio >= 1.05)
        ):
            return "阶段不明确，当前出现 SC/ST 候选扰动，但证据不足，建议空仓观望"
        if (
            relative_position <= 0.50
            and close_price >= open_price
            and close_location >= 0.62
            and vol_ratio >= 0.95
        ):
            return "阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确"
        if 0.38 < relative_position < 0.68:
            return "阶段不明确，当前更像 Phase B 震荡观察区，建议等待 TR 边界和 ST/UT 进一步清晰"
        return "阶段不明确，当前存在较强不确定性，建议空仓观望"

    def _describe_markup_context(
        self,
        df: pd.DataFrame,
        structure: WyckoffStructure,
        default: Optional[str] = None,
    ) -> str:
        last_row = df.iloc[-1]
        open_price = float(last_row["open"])
        close_price = float(last_row["close"])
        high_price = float(last_row["high"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0
        recent_5 = df.tail(min(5, len(df)))
        recent_10 = df.tail(min(10, len(df)))
        prior_window = df.iloc[:-5] if len(df) > 5 else pd.DataFrame()
        prior_ceiling = (
            float(prior_window.tail(min(40, len(prior_window)))["high"].max())
            if not prior_window.empty
            else None
        )
        recent_low5 = float(recent_5["low"].min())
        recent_high10 = float(recent_10["high"].max())
        recent_spread_avg = float((recent_10["high"] - recent_10["low"]).mean())
        spread = high_price - low_price
        bc_price = structure.bc_point.price if structure.bc_point is not None else structure.trading_range_high

        if prior_ceiling is not None and close_price > prior_ceiling * 1.01:
            if low_price <= prior_ceiling * 1.01 and close_price >= prior_ceiling * 1.02:
                return (
                    f"当前处于 Phase E 突破后的 BUEC/LPS 回踩确认区，"
                    f"价格回测 {prior_ceiling:.2f} 一线后重新站稳"
                )
            if vol_ratio >= 1.0:
                return (
                    f"当前处于 Phase E Markup 延续段，价格已跃过前高 {prior_ceiling:.2f}，"
                    "出现 Phase E / SOS 动能扩张信号"
                )
            return "当前处于 Phase E（主升浪）延续段，趋势仍由多头掌控，优先按持仓保护思路处理"

        if bc_price is not None and close_price > bc_price * 1.01:
            if low_price <= bc_price * 1.01 and vol_ratio < 1.0:
                return (
                    f"当前处于 Phase E 突破后的 BUEC/LPS 回踩确认区，"
                    f"价格回测 {bc_price:.2f} 一线后重新站稳"
                )
            if vol_ratio >= 1.05:
                return (
                    f"当前处于 Phase E Markup 延续段，价格已跃过 BC {bc_price:.2f}，"
                    "出现 Phase E / SOS 动能扩张信号"
                )
            return "当前处于 Phase E Markup 延续段，趋势保持强势，优先按持仓保护思路处理"

        if lower_wick > max(body * 1.0, 0.01) and low_price <= recent_low5 * 1.005:
            return "当前处于 Markup 回踩中的 Shakeout/Test 观察区，轻仓试探需等待确认下影吸收有效"

        if close_price <= recent_low5 * 1.05 and vol_ratio < 0.95:
            return "当前处于 Markup 回踩中的 Lack of Supply / Test 观察区，等待缩量测试结束"

        if (
            spread <= recent_spread_avg * 0.90
            and vol_ratio <= 1.15
            and close_price < recent_high10 * 0.995
        ):
            return "当前处于 Markup 中段的 Lack of Supply 蓄势区，持有者继续观察，空仓者等待更优击球点"

        if (
            upper_wick > max(body * 1.5, 0.01)
            and vol_ratio < 1.0
            and bc_price is not None
            and high_price >= bc_price * 0.97
        ):
            return "当前处于 Markup 上沿的 Lack of Demand 警戒区，需防冲高受阻后的再平衡"

        return default or (
            "当前处于 Markup 过程中，价格在区间内部运行，无明确事件信号，"
            "建议空仓观望，等待 LPS、Test 或突破后的 BUEC 结构"
        )
    
    def _assess_t1_risk(
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure, 
        entry_price: float
    ) -> str:
        """T+1 风险评估"""
        recent = df.tail(10)
        
        avg_daily_range = (recent["high"] - recent["low"]).mean()
        range_pct = avg_daily_range / entry_price
        
        if range_pct > 0.05:
            risk_level = "高"
        elif range_pct > 0.03:
            risk_level = "中"
        else:
            risk_level = "低"
        
        if structure.bc_point is not None:
            distance = abs(entry_price - structure.bc_point.price) / structure.bc_point.price
            if distance < 0.10:
                support_strength = "强"
            elif distance < 0.20:
                support_strength = "中"
            else:
                support_strength = "弱"
        else:
            support_strength = "未确定"
        
        return f"基于10日平均振幅{range_pct*100:.1f}%，风险等级{risk_level}，支撑强度{support_strength}"
    
    def _calculate_risk_reward(
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure,
        signal: WyckoffSignal
    ) -> RiskRewardProjection:
        """计算盈亏比"""
        proj = RiskRewardProjection()

        current_price = structure.current_price
        proj.entry_price = current_price

        if current_price is None:
            return proj

        if structure.phase in {WyckoffPhase.ACCUMULATION, WyckoffPhase.MARKUP}:
            if structure.trading_range_low is not None:
                proj.stop_loss = structure.trading_range_low * 0.98
            elif structure.sc_point is not None:
                proj.stop_loss = structure.sc_point.price * 0.99
            if structure.bc_point is not None:
                proj.first_target = structure.bc_point.price
            elif structure.trading_range_high is not None:
                proj.first_target = structure.trading_range_high
        elif signal.signal_type != "no_signal":
            if structure.trading_range_low is not None:
                proj.stop_loss = structure.trading_range_low * 0.98
            if structure.trading_range_high is not None:
                proj.first_target = structure.trading_range_high
        elif (
            structure.phase == WyckoffPhase.UNKNOWN
            and structure.trading_range_low is not None
            and structure.trading_range_high is not None
            and any(
                keyword in signal.description
                for keyword in ("Phase A/AR", "SC/ST")
            )
        ):
            proj.stop_loss = structure.trading_range_low * 0.98
            proj.first_target = structure.trading_range_high

        if proj.stop_loss is not None:
            proj.risk_amount = current_price - proj.stop_loss
        if proj.first_target is not None:
            proj.reward_amount = proj.first_target - current_price

        if proj.risk_amount and proj.risk_amount > 0:
            proj.reward_risk_ratio = proj.reward_amount / proj.risk_amount
            if structure.phase == WyckoffPhase.UNKNOWN:
                if "Phase A/AR" in signal.description:
                    proj.structure_based = (
                        f"基于 Phase A/AR 候选结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
                    )
                elif "SC/ST" in signal.description:
                    proj.structure_based = (
                        f"基于 SC/ST 候选结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
                    )
                else:
                    proj.structure_based = (
                        f"基于结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
                    )
            else:
                proj.structure_based = (
                    f"基于结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
                )
        
        return proj
    
    def _build_trading_plan(
        self, 
        structure: WyckoffStructure,
        signal: WyckoffSignal,
        risk_reward: RiskRewardProjection,
        stress_tests: Optional[List[StressTest]] = None
    ) -> TradingPlan:
        """构建交易计划"""
        plan = TradingPlan()

        if signal.signal_type == "no_signal":
            plan.direction = "空仓观望"
            plan.confidence = signal.confidence
            plan.preconditions = "需等待明确信号"

            if structure.phase == WyckoffPhase.ACCUMULATION:
                plan.current_qualification = (
                    "当前处于 Phase B/Phase C 过渡观察区，优先等待 Spring、ST 或 SOS 确认"
                )
                plan.trigger_condition = (
                    f"关注 {structure.trading_range_low:.2f} 附近是否出现 Spring，"
                    "或确认阳线拉离下沿后的二次缩量回踩"
                    if structure.trading_range_low is not None
                    else "等待 Spring 或 SOS 明确信号"
                )
                plan.invalidation_point = (
                    f"有效跌破 {structure.trading_range_low:.2f} 则继续观望"
                    if structure.trading_range_low is not None
                    else "N/A"
                )
                plan.first_target = (
                    f"第一观察目标 {structure.bc_point.price:.2f}"
                    if structure.bc_point is not None
                    else "待确认"
                )
            elif structure.phase == WyckoffPhase.MARKUP:
                markup_context = signal.description or ""
                is_generic_markup_context = markup_context.startswith("当前处于 Markup 过程中")
                near_bc = (
                    structure.bc_point is not None
                    and structure.current_price is not None
                    and structure.current_price >= structure.bc_point.price * 0.93
                )
                if (
                    not is_generic_markup_context
                    and any(keyword in markup_context for keyword in ("Phase E", "BUEC", "Lack of Supply", "Lack of Demand", "Shakeout", "Test"))
                ):
                    plan.current_qualification = markup_context
                elif near_bc or (risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio < 2.5):
                    plan.current_qualification = (
                        "当前处于 Phase D/Markup 推进阶段，但已逼近 BC 压力区，"
                        "按 V3.0 纪律属于 No Trade Zone"
                    )
                else:
                    plan.current_qualification = "当前处于 Markup 早中段，等待更优 LPS/Backup 位置"
                lower_hint = structure.trading_range_low if structure.trading_range_low is not None else 0.0
                bc_hint = structure.bc_point.price if structure.bc_point is not None else structure.trading_range_high
                plan.trigger_condition = (
                    f"等待回踩 {lower_hint:.2f} 一带出现缩量 LPS，"
                    f"或放量突破 {bc_hint:.2f} 后回踩确认"
                )
                plan.invalidation_point = (
                    f"跌破 {structure.trading_range_low:.2f} 则放弃追踪当前上涨节奏"
                    if structure.trading_range_low is not None
                    else "N/A"
                )
                plan.first_target = (
                    f"第一目标 {structure.bc_point.price:.2f}"
                    if structure.bc_point is not None
                    else "待确认"
                )
                if not is_generic_markup_context and "Phase E" in markup_context:
                    plan.direction = "持有观察 / 空仓者观望"
                elif (
                    not is_generic_markup_context
                    and ("Shakeout" in markup_context or "BUEC" in markup_context)
                ):
                    if risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio >= 0.3:
                        plan.direction = "买入观察 / 轻仓试探"
                elif not is_generic_markup_context and "Lack of Supply / Test" in markup_context:
                    if risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio < 0.5:
                        plan.current_qualification = (
                            "当前处于 Markup / Phase D 推进段的回踩测试区，"
                            "但按 V3.0 纪律仍属于 No Trade Zone"
                        )
                    plan.direction = "空仓观望"
                elif not is_generic_markup_context and "Lack of Supply" in markup_context:
                    plan.direction = "持有观察 / 空仓者观望"
            else:
                plan.current_qualification = signal.description
                if "Phase A/AR" in signal.description:
                    plan.trigger_condition = (
                        f"等待 {structure.trading_range_low:.2f} 一带完成 ST 缩量确认，"
                        f"或重新放量攻击 {structure.trading_range_high:.2f}"
                        if structure.trading_range_low is not None and structure.trading_range_high is not None
                        else "等待 ST 缩量确认或 TR 上沿重新发起攻击"
                    )
                    plan.invalidation_point = (
                        f"有效失守 {structure.trading_range_low:.2f} 则放弃 Phase A/AR 设想"
                        if structure.trading_range_low is not None
                        else "失守近期低点则放弃 Phase A/AR 设想"
                    )
                    plan.first_target = (
                        f"第一观察目标 {structure.trading_range_high:.2f}"
                        if structure.trading_range_high is not None
                        else "第一观察目标 TR 上沿"
                    )
                elif "SC/ST" in signal.description:
                    plan.trigger_condition = (
                        "等待 SC 后的 AR 反弹出现，并观察 ST 二次回测是否缩量止跌"
                    )
                    plan.invalidation_point = (
                        f"若继续跌破 {structure.trading_range_low:.2f} 则回归更弱结构"
                        if structure.trading_range_low is not None
                        else "若继续跌破近期低点则回归更弱结构"
                    )
                    plan.first_target = (
                        f"第一观察目标 {structure.trading_range_high:.2f}"
                        if structure.trading_range_high is not None
                        else "第一观察目标 AR 高点确认"
                    )
                elif "Upthrust" in signal.description:
                    plan.trigger_condition = (
                        f"等待价格从 {structure.trading_range_high:.2f} 一带回落并重新选择方向"
                        if structure.trading_range_high is not None
                        else "等待上沿假突破回落后重新选择方向"
                    )
                    plan.invalidation_point = (
                        f"若继续站稳 {structure.trading_range_high:.2f} 上方，则当前 Upthrust 假设失效"
                        if structure.trading_range_high is not None
                        else "若继续强势上攻，则当前 Upthrust 假设失效"
                    )
                    plan.first_target = (
                        f"第一观察目标回到区间中枢，关注 {((structure.trading_range_low or 0.0) + (structure.trading_range_high or 0.0)) / 2:.2f}"
                        if structure.trading_range_low is not None and structure.trading_range_high is not None
                        else "第一观察目标为区间中枢确认"
                    )
                elif "Phase B" in signal.description:
                    plan.trigger_condition = (
                        f"等待 {structure.trading_range_low:.2f}-{structure.trading_range_high:.2f} 区间边界被明确测试"
                        if structure.trading_range_low is not None and structure.trading_range_high is not None
                        else "等待 TR 边界被再次明确测试"
                    )
                    plan.invalidation_point = "区间边界未明确前不执行"
                    plan.first_target = (
                        f"第一观察目标 {structure.trading_range_high:.2f}"
                        if structure.trading_range_high is not None
                        else "第一观察目标 TR 上沿"
                    )
                else:
                    plan.trigger_condition = "N/A"
                    plan.invalidation_point = "N/A"
                    plan.first_target = "N/A"
            return plan
        
        if structure.phase == WyckoffPhase.MARKDOWN:
            plan.direction = "空仓观望"
            plan.trigger_condition = "N/A"
            plan.invalidation_point = "N/A"
            plan.first_target = "N/A"
            plan.confidence = ConfidenceLevel.D
            plan.current_qualification = "当前处于 Markdown 阶段"
            plan.preconditions = "禁止做空"
            return plan

        plan.confidence = signal.confidence
        plan.current_qualification = signal.description
        plan.preconditions = "需大盘指数/所属板块不出现系统性单边暴跌"

        if risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio < 2.5:
            if structure.phase == WyckoffPhase.MARKUP:
                if "Spring→ST→SOS" in signal.description and risk_reward.reward_risk_ratio >= 1.2:
                    plan.direction = "做多观察 / 轻仓试探"
                elif "Phase E" in signal.description or "Lack of Supply" in signal.description:
                    plan.direction = "持有观察 / 空仓者观望"
                elif any(keyword in signal.description for keyword in ("BUEC", "Shakeout", "Test")):
                    plan.direction = "买入观察 / 轻仓试探"
                else:
                    plan.direction = "空仓观望"
            else:
                plan.direction = "空仓观望"
            plan.trigger_condition = "当前盈亏比不足 1:2.5，继续等待更优入场位置"
            plan.invalidation_point = "N/A"
            plan.first_target = "N/A"
            plan.preconditions = "仅当后续回踩或突破回踩使盈亏比达到 1:2.5 以上时再评估"
            return plan

        if signal.signal_type == "spring":
            plan.direction = "空仓观望"
            plan.trigger_condition = (
                f"T+3 冷冻期结束后，若价格仍守住 {structure.trading_range_low} "
                f"且出现放量确认，再等待缩量回踩不破后评估入场"
            )
            plan.invalidation_point = f"跌破 {structure.trading_range_low} 放弃 Spring 设想"
        else:
            plan.direction = "空仓观望"
            plan.trigger_condition = "等待价格突破震荡区间上边界并回踩确认"
            plan.invalidation_point = f"跌破 {structure.current_price * 0.95} 止损"
        
        if risk_reward.first_target is not None:
            plan.first_target = f"第一目标位 {risk_reward.first_target}"
        else:
            plan.first_target = "待确认"
        
        return plan
    
    def _create_no_signal_report(
        self, 
        symbol: str, 
        period: str, 
        reason: str
    ) -> WyckoffReport:
        """创建无信号报告"""
        structure = WyckoffStructure()
        structure.phase = WyckoffPhase.UNKNOWN
        
        signal = WyckoffSignal()
        signal.signal_type = "no_signal"
        signal.confidence = ConfidenceLevel.D
        signal.description = f"当前图表信号杂乱，处于不可交易区（No Trade Zone），建议放弃。原因: {reason}"
        
        risk_reward = RiskRewardProjection()
        
        plan = TradingPlan()
        plan.direction = "空仓观望"
        plan.trigger_condition = "N/A"
        plan.invalidation_point = "N/A"
        plan.first_target = "N/A"
        plan.confidence = ConfidenceLevel.D
        plan.current_qualification = signal.description
        
        return WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=plan,
        )

```

---

## src/wyckoff/config.py

```python
# -*- coding: utf-8 -*-
"""威科夫多模态分析系统 - 配置管理"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import yaml
from src.constants import WYCKOFF_OUTPUT_DIR, MIN_WYCKOFF_DATA_ROWS, BC_LOOKBACK_WINDOW, SPRING_FREEZE_DAYS, MIN_RR_RATIO

@dataclass
class RuleEngineConfig:
    min_data_rows: int = MIN_WYCKOFF_DATA_ROWS
    bc_lookback_window: int = BC_LOOKBACK_WINDOW
    spring_freeze_days: int = SPRING_FREEZE_DAYS
    min_rr_ratio: float = MIN_RR_RATIO
    bc_min_price_increase_pct: float = 15.0
    bc_volume_multiplier_high: float = 2.0
    bc_volume_multiplier_avg: float = 1.2
    volume_extreme_high_threshold: float = 2.0
    volume_above_avg_threshold: float = 1.2
    volume_contracted_low: float = 0.5
    confidence_a_rr_min: float = 3.0
    confidence_b_rr_min: float = 2.5

@dataclass
class ImageEngineConfig:
    supported_formats: List[str] = field(default_factory=lambda: ['.png', '.jpg', '.jpeg', '.webp'])
    quality_high_min_resolution: int = 1920
    quality_medium_min_resolution: int = 1280
    quality_low_min_resolution: int = 800
    blur_threshold_high: float = 100.0
    blur_threshold_medium: float = 50.0
    blur_threshold_low: float = 20.0
    weekly_keywords: List[str] = field(default_factory=lambda: ['weekly', '周线', 'week'])
    daily_keywords: List[str] = field(default_factory=lambda: ['daily', '日线', 'day'])
    minute_keywords: Dict[str, List[str]] = field(default_factory=lambda: {'60m': ['60m', '60min', '60 分钟', '1h'], '30m': ['30m', '30min', '30 分钟'], '15m': ['15m', '15min', '15 分钟'], '5m': ['5m', '5min', '5 分钟']})

@dataclass
class FusionEngineConfig:
    phase_conflict_weight: float = 1.0
    trend_conflict_weight: float = 0.8
    boundary_conflict_weight: float = 0.6
    image_quality_weight: float = 0.3
    consistency_weight: float = 0.4
    cross_tf_weight: float = 0.3
    auto_downgrade_on_conflict: bool = True
    auto_downgrade_on_low_quality: bool = True

@dataclass
class OutputConfig:
    base_dir: str = WYCKOFF_OUTPUT_DIR
    raw_dir: str = "raw"
    plots_dir: str = "plots"
    reports_dir: str = "reports"
    summary_dir: str = "summary"
    state_dir: str = "state"
    evidence_dir: str = "evidence"
    def get_full_path(self, sub_dir: str, filename: str) -> str:
        dir_path = os.path.join(self.base_dir, sub_dir)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, filename)

@dataclass
class WyckoffConfig:
    rule_engine: RuleEngineConfig = field(default_factory=RuleEngineConfig)
    image_engine: ImageEngineConfig = field(default_factory=ImageEngineConfig)
    fusion_engine: FusionEngineConfig = field(default_factory=FusionEngineConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'WyckoffConfig':
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        config = cls()
        if 'rule_engine' in data:
            config.rule_engine = RuleEngineConfig(**data['rule_engine'])
        if 'image_engine' in data:
            config.image_engine = ImageEngineConfig(**data['image_engine'])
        if 'fusion_engine' in data:
            config.fusion_engine = FusionEngineConfig(**data['fusion_engine'])
        if 'output' in data:
            config.output = OutputConfig(**data['output'])
        if 'llm' in data:
            config.llm_provider = data['llm'].get('provider')
            config.llm_api_key = data['llm'].get('api_key')
            config.llm_model = data['llm'].get('model')
        return config
    @classmethod
    def from_env(cls) -> 'WyckoffConfig':
        config = cls()
        if os.environ.get('WYCKOFF_LLM_PROVIDER'):
            config.llm_provider = os.environ.get('WYCKOFF_LLM_PROVIDER')
        if os.environ.get('WYCKOFF_LLM_API_KEY'):
            config.llm_api_key = os.environ.get('WYCKOFF_LLM_API_KEY')
        if os.environ.get('WYCKOFF_LLM_MODEL'):
            config.llm_model = os.environ.get('WYCKOFF_LLM_MODEL')
        return config

def load_config(yaml_path: Optional[str] = None) -> WyckoffConfig:
    if yaml_path and os.path.exists(yaml_path):
        return WyckoffConfig.from_yaml(yaml_path)
    return WyckoffConfig.from_env()
```

---

## src/wyckoff/data_engine.py

```python
# -*- coding: utf-8 -*-
"""
威科夫规则引擎 - 日线规则链实现

严格遵循 SPEC_WYCKOFF_RULE_ENGINE 定义的 Step 0 ~ Step 5 顺序
"""
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.constants import (
    MIN_WYCKOFF_DATA_ROWS,
    WYCKOFF_PHASES,
    WYCKOFF_DIRECTIONS,
    WYCKOFF_CONFIDENCE_LEVELS,
    VOLUME_LABELS,
)
from src.exceptions import InvalidInputDataError, BCNotFoundError

from src.wyckoff.config import WyckoffConfig, RuleEngineConfig
from src.wyckoff.models import (
    DailyRuleResult,
    PreprocessingResult,
    BCResult,
    PhaseResult,
    EffortResult,
    PhaseCTestResult,
    CounterfactualResult,
    RiskAssessment,
    TradingPlan,
)

logger = logging.getLogger(__name__)


class DataEngine:
    """
    威科夫数据引擎 - 实现 Step 0 ~ Step 5 完整规则链
    
    SPEC_WYCKOFF_RULE_ENGINE Section 2 强制顺序:
    1. 输入校验 → 2. 预处理 → 3. Step 0 BC 定位 → 4. Step 1 阶段识别
    → 5. Step 2 努力结果 → 6. Step 3 Phase C 测试 → 7. Step 3.5 反事实
    → 8. Step 4 风险评估 → 9. Step 5 交易计划
    """
    
    def __init__(self, config: Optional[WyckoffConfig] = None):
        self.config = config or WyckoffConfig()
        self.rule_config = self.config.rule_engine
    
    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        asset_type: str,
        analysis_date: Optional[str] = None,
    ) -> DailyRuleResult:
        """
        规则引擎主入口 - 严格按 Step 0→5 顺序执行
        
        Args:
            df: OHLCV DataFrame
            symbol: 标的代码
            asset_type: 资产类型 ("index" 或 "stock")
            analysis_date: 分析日期（可选，默认使用 df 最后日期）
            
        Returns:
            DailyRuleResult
        """
        # Step 1: 输入校验
        self._step_validate(df)
        
        # Step 2: 预处理
        preprocessing = self._step_preprocess(df)
        
        # Step 0: BC 定位扫描 (必须在方向性判断前执行)
        bc_result = self._step0_bc_scan(df, preprocessing)
        
        # BC 未找到 → 直接返回 D 级 + abandon
        if not bc_result.found:
            return self._create_abandon_result(
                df, symbol, asset_type, analysis_date,
                preprocessing, bc_result,
                reason="bc_not_found"
            )
        
        # Step 1: 阶段识别
        phase_result = self._step1_phase_identify(df, bc_result, preprocessing)
        
        # Step 2: 努力与结果
        effort_result = self._step2_effort_result(df, phase_result, preprocessing)
        
        # Step 3: Phase C 终极测试
        phase_c_test = self._step3_phase_c_test(df, phase_result, bc_result, preprocessing)
        
        # Step 3.5: 反事实压力测试
        counterfactual = self._step35_counterfactual(
            df, bc_result, phase_result, effort_result, phase_c_test
        )
        
        # Step 4: T+1 与盈亏比评估
        risk_assessment = self._step4_risk_assessment(
            df, phase_result, phase_c_test, counterfactual
        )
        
        # Step 5: 交易计划
        trading_plan = self._step5_trading_plan(
            bc_result, phase_result, effort_result, phase_c_test,
            counterfactual, risk_assessment
        )
        
        # 计算置信度
        confidence = self._calc_confidence(
            bc_result, phase_result, phase_c_test,
            counterfactual, risk_assessment
        )
        
        # 构建最终结果
        return DailyRuleResult(
            symbol=symbol,
            asset_type=asset_type,
            analysis_date=analysis_date or str(df['date'].max().date()),
            input_source="data",
            preprocessing=preprocessing,
            bc_result=bc_result,
            phase_result=phase_result,
            effort_result=effort_result,
            phase_c_test=phase_c_test,
            counterfactual=counterfactual,
            risk=risk_assessment,
            plan=trading_plan,
            confidence=confidence,
            decision=trading_plan.direction,
            abandon_reason="" if trading_plan.direction != "abandon" else "unfavorable_rr_or_structure",
        )
    
    def _step_validate(self, df: pd.DataFrame) -> None:
        """
        Step 1: 输入校验 - SPEC Section 1
        
        强制要求:
        - 至少 100 根 K 线
        - 时间升序
        - 无负成交量
        - 开高低收为正
        """
        if df is None or df.empty:
            raise InvalidInputDataError("DataFrame is None or empty")
        
        if len(df) < MIN_WYCKOFF_DATA_ROWS:
            raise InvalidInputDataError(
                f"Insufficient data rows: {len(df)} < {MIN_WYCKOFF_DATA_ROWS}"
            )
        
        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise InvalidInputDataError(f"Missing required columns: {missing_cols}")
        
        # 检查负值
        if (df['volume'] < 0).any():
            raise InvalidInputDataError("Invalid data: negative volume found")
        
        if (df[['open', 'high', 'low', 'close']] <= 0).any().any():
            raise InvalidInputDataError("Invalid data: non-positive prices found")
        
        # 检查高<低
        bad_hl = (df['high'] < df['low']).sum()
        if bad_hl > len(df) * 0.01:
            raise InvalidInputDataError(f"Too many high < low: {bad_hl} rows")
        
        logger.info(f"输入校验通过：{len(df)} rows")
    
    def _step_preprocess(self, df: pd.DataFrame) -> PreprocessingResult:
        """
        Step 2: 预处理 - SPEC Section 3
        
        输出:
        - 趋势方向
        - 量能标签
        - 波动分层
        - 局部高低点
        - 缺口候选
        - 长影线候选
        - 涨跌停异常
        """
        # 1. 趋势方向 (近 20 日线性回归斜率)
        recent_close = df['close'].tail(20).values
        x = np.arange(len(recent_close))
        slope = np.polyfit(x, recent_close, 1)[0]
        if slope > 0.02:
            trend_direction = "uptrend"
        elif slope < -0.02:
            trend_direction = "downtrend"
        else:
            trend_direction = "range"
        
        # 2. 量能标签 (最近 20 日 vs 60 日均值)
        recent_vol = df['volume'].tail(20).mean()
        avg_vol_60 = df['volume'].tail(60).mean()
        vol_ratio = recent_vol / avg_vol_60 if avg_vol_60 > 0 else 1.0
        
        if vol_ratio > self.rule_config.volume_extreme_high_threshold:
            volume_label = "extreme_high"
        elif vol_ratio > self.rule_config.volume_above_avg_threshold:
            volume_label = "above_average"
        elif vol_ratio < self.rule_config.volume_contracted_low:
            volume_label = "extreme_contracted"
        else:
            volume_label = "contracted"
        
        # 3. 波动分层 (ATR/收盘价)
        atr_14 = self._calc_atr(df, 14)
        vol_ratio = (atr_14 / df['close'].iloc[-1]).iloc[-1]
        if vol_ratio > 0.03:
            volatility_layer = "high"
        elif vol_ratio > 0.015:
            volatility_layer = "medium"
        else:
            volatility_layer = "low"
        
        # 4. 局部高低点 (rolling 20)
        rolling_high = df['high'].rolling(20).max()
        rolling_low = df['low'].rolling(20).min()
        
        local_highs = []
        local_lows = []
        for i in range(20, len(df)):
            if df['high'].iloc[i] == rolling_high.iloc[i]:
                local_highs.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'price': df['high'].iloc[i]
                })
            if df['low'].iloc[i] == rolling_low.iloc[i]:
                local_lows.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'price': df['low'].iloc[i]
                })
        
        # 5. 缺口候选
        gap_candidates = []
        for i in range(1, len(df)):
            if df['low'].iloc[i] > df['high'].iloc[i-1]:
                gap_candidates.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'gap_up',
                    'size': df['low'].iloc[i] - df['high'].iloc[i-1]
                })
            elif df['high'].iloc[i] < df['low'].iloc[i-1]:
                gap_candidates.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'gap_down',
                    'size': df['low'].iloc[i-1] - df['high'].iloc[i]
                })
        
        # 6. 长影线候选
        long_wick_candidates = []
        for i in range(len(df)):
            body = abs(df['close'].iloc[i] - df['open'].iloc[i])
            wick = (df['high'].iloc[i] - df['low'].iloc[i]) - body
            if body > 0 and wick > 3 * body:
                wick_type = "upper" if df['close'].iloc[i] > df['open'].iloc[i] else "lower"
                long_wick_candidates.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': wick_type,
                    'wick_ratio': wick / body
                })
        
        # 7. 涨跌停异常 (A 股±10%)
        limit_anomalies = []
        for i in range(1, len(df)):
            pct_change = (df['close'].iloc[i] - df['close'].iloc[i-1]) / df['close'].iloc[i-1]
            if pct_change >= 0.095:
                limit_anomalies.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'limit_up',
                    'pct': pct_change
                })
            elif pct_change <= -0.095:
                limit_anomalies.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'limit_down',
                    'pct': pct_change
                })
        
        return PreprocessingResult(
            trend_direction=trend_direction,
            volume_label=volume_label,
            volatility_layer=volatility_layer,
            local_highs=local_highs[-10:],  # 最近 10 个
            local_lows=local_lows[-10:],
            gap_candidates=gap_candidates[-10:],
            long_wick_candidates=long_wick_candidates[-10:],
            limit_anomalies=limit_anomalies[-10:],
        )
    
    def _step0_bc_scan(self, df: pd.DataFrame, prep: PreprocessingResult) -> BCResult:
        """
        Step 0: BC 定位扫描 - SPEC Section 4
        
        强制原则：任何方向性判断前必须先定位 BC
        
        BC 候选条件:
        1. 左侧存在明显上涨（前 60 日涨幅 > 15%）
        2. 是局部高点或近似局部高点
        3. 成交量标签为 extreme_high 或 above_average
        4. 伴随增强信号之一
        """
        # 1. 检查左侧上涨
        if len(df) < 60:
            return BCResult(
                found=False, candidate_index=-1, candidate_date="",
                candidate_price=0.0, volume_label="unknown",
                enhancement_signals=[]
            )
        
        # 检查最近 60 日前的上涨
        lookback_start = max(0, len(df) - 120)
        lookback_mid = max(0, len(df) - 60)
        
        if lookback_mid <= lookback_start:
            return BCResult(found=False, candidate_index=-1, candidate_date="",
                          candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
        
        price_start = df['close'].iloc[lookback_start]
        price_mid = df['close'].iloc[lookback_mid]
        price_increase = (price_mid - price_start) / price_start
        
        if price_increase < self.rule_config.bc_min_price_increase_pct / 100:
            logger.info(f"左侧上涨不足 {self.rule_config.bc_min_price_increase_pct}%")
            return BCResult(found=False, candidate_index=-1, candidate_date="",
                          candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
        
        # 2. 找局部高点 (rolling 20 max)
        rolling_high = df['high'].rolling(20).max()
        bc_candidates = []
        
        for i in range(lookback_start, lookback_mid):
            if df['high'].iloc[i] >= rolling_high.iloc[i] * 0.98:  # 近似高点
                bc_candidates.append(i)
        
        if not bc_candidates:
            return BCResult(found=False, candidate_index=-1, candidate_date="",
                          candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
        
        # 3. 检查成交量和增强信号
        for idx in reversed(bc_candidates):
            # 检查成交量
            vol_20 = df['volume'].iloc[max(0, idx-20):idx+1].mean()
            avg_vol_60 = df['volume'].iloc[max(0, idx-60):idx+1].mean()
            vol_ratio = vol_20 / avg_vol_60 if avg_vol_60 > 0 else 1.0
            
            if vol_ratio < self.rule_config.bc_volume_multiplier_avg:
                continue
            
            # 检查增强信号
            enhancement_signals = []
            
            # 高位长上影
            for wick in prep.long_wick_candidates:
                if abs(wick['index'] - idx) <= 5 and wick['type'] == 'upper':
                    enhancement_signals.append("long_upper_wick")
            
            # 放量滞涨
            if vol_ratio > self.rule_config.bc_volume_multiplier_high:
                pct_change = (df['close'].iloc[idx] - df['open'].iloc[idx]) / df['open'].iloc[idx]
                if pct_change < 0.01:
                    enhancement_signals.append("volume_stagnation")
            
            # 跳空后衰竭
            for gap in prep.gap_candidates:
                if abs(gap['index'] - idx) <= 3 and gap['type'] == 'gap_up':
                    enhancement_signals.append("gap_exhaustion")
            
            # 假突破
            if len(enhancement_signals) >= 1:
                return BCResult(
                    found=True,
                    candidate_index=idx,
                    candidate_date=str(df['date'].iloc[idx].date()),
                    candidate_price=float(df['high'].iloc[idx]),
                    volume_label="extreme_high" if vol_ratio > self.rule_config.bc_volume_multiplier_high else "above_average",
                    enhancement_signals=enhancement_signals
                )
        
        return BCResult(found=False, candidate_index=-1, candidate_date="",
                       candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
    
    def _step1_phase_identify(
        self,
        df: pd.DataFrame,
        bc_result: BCResult,
        prep: PreprocessingResult,
    ) -> PhaseResult:
        """
        Step 1: 大局观与阶段识别 - SPEC Section 5
        
        阶段: accumulation / markup / distribution / markdown / no_trade_zone
        """
        bc_idx = bc_result.candidate_index
        bc_price = bc_result.candidate_price
        
        # BC 后价格行为
        post_bc_df = df.iloc[bc_idx:].reset_index(drop=True)
        current_price = post_bc_df['close'].iloc[-1]
        price_change = (current_price - bc_price) / bc_price
        
        # 边界来源
        boundary_sources = ["BC"]
        
        # 找 AR (Automatic Rally) 高点
        ar_high = post_bc_df['high'].rolling(10).max().max()
        if ar_high > bc_price * 0.98:
            boundary_sources.append("AR")
        
        # 找 SC (Selling Climax) 低点
        sc_low = post_bc_df['low'].min()
        if sc_low < bc_price * 0.85:
            boundary_sources.append("SC")
        
        # 阶段判定
        if price_change < -0.15:
            # 大幅下跌 → distribution 或 markdown
            if prep.trend_direction == "downtrend":
                phase = "markdown"
            else:
                phase = "distribution"
            boundary_upper = str(bc_price)
            boundary_lower = str(sc_low)
        elif price_change > 0.05:
            # 上涨 → markup
            phase = "markup"
            boundary_upper = str(ar_high)
            boundary_lower = str(bc_price)
        elif -0.15 <= price_change <= 0.05:
            # 区间震荡 → accumulation
            phase = "accumulation"
            boundary_upper = str(ar_high)
            boundary_lower = str(sc_low)
        else:
            phase = "no_trade_zone"
            boundary_upper = str(bc_price)
            boundary_lower = str(sc_low)
        
        return PhaseResult(
            phase=phase,
            boundary_upper_zone=boundary_upper,
            boundary_lower_zone=boundary_lower,
            boundary_sources=boundary_sources,
        )
    
    def _step2_effort_result(
        self,
        df: pd.DataFrame,
        phase_result: PhaseResult,
        prep: PreprocessingResult,
    ) -> EffortResult:
        """
        Step 2: 努力与结果 - SPEC Section 6
        
        识别现象:
        - 放量滞涨
        - 缩量上推
        - 下边界供给枯竭
        - 高位炸板遗迹
        """
        phenomena = []
        accumulation_score = 0.0
        distribution_score = 0.0
        
        # 1. 放量滞涨
        if prep.volume_label in ["extreme_high", "above_average"]:
            recent_pct = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]
            if recent_pct < 0.01:
                phenomena.append("volume_stagnation")
                distribution_score += 0.3
        
        # 2. 缩量上推
        if prep.volume_label == "contracted":
            recent_pct = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]
            if recent_pct > 0.02:
                phenomena.append("low_volume_rally")
                accumulation_score += 0.2
        
        # 3. 下边界供给枯竭
        lower_boundary = float(phase_result.boundary_lower_zone)
        if df['low'].iloc[-1] <= lower_boundary * 1.02:
            if prep.volume_label == "extreme_contracted":
                phenomena.append("supply_drying_at_support")
                accumulation_score += 0.3
        
        # 4. 高位炸板遗迹
        for anomaly in prep.limit_anomalies:
            if anomaly['type'] == 'limit_up':
                idx = anomaly['index']
                if idx > len(df) - 20:
                    # 最近 20 日有涨停
                    post_limit_pct = (df['close'].iloc[-1] - df['close'].iloc[idx]) / df['close'].iloc[idx]
                    if post_limit_pct < -0.05:
                        phenomena.append("failed_limit_up")
                        distribution_score += 0.3
        
        # 5. 吸筹/派发倾向
        net_bias_score = accumulation_score - distribution_score
        if net_bias_score > 0.2:
            net_bias = "accumulation"
        elif net_bias_score < -0.2:
            net_bias = "distribution"
        else:
            net_bias = "neutral"
        
        return EffortResult(
            phenomena=phenomena,
            accumulation_evidence=accumulation_score,
            distribution_evidence=distribution_score,
            net_bias=net_bias,
        )
    
    def _step3_phase_c_test(
        self,
        df: pd.DataFrame,
        phase_result: PhaseResult,
        bc_result: BCResult,
        prep: PreprocessingResult,
    ) -> PhaseCTestResult:
        """
        Step 3: Phase C 终极测试 - SPEC Section 7
        
        检测:
        - Spring (刺穿下边界后快速收回)
        - UTAD (刺穿上边界后快速回落)
        - ST (Secondary Test)
        - False Breakout
        """
        spring_detected = False
        utad_detected = False
        st_detected = False
        false_breakout_detected = False
        spring_date = None
        utad_date = None
        
        lower_boundary = float(phase_result.boundary_lower_zone)
        upper_boundary = float(phase_result.boundary_upper_zone)
        
        # Spring 检测
        for i in range(len(df) - 5, len(df)):
            if df['low'].iloc[i] < lower_boundary:
                # 刺穿下边界
                if i < len(df) - 1:
                    # 检查是否快速收回
                    recovery_price = df['close'].iloc[i+1:]
                    if (recovery_price > lower_boundary).any():
                        spring_detected = True
                        spring_date = str(df['date'].iloc[i].date())
                        break
        
        # UTAD 检测
        for i in range(len(df) - 5, len(df)):
            if df['high'].iloc[i] > upper_boundary:
                # 刺穿上边界
                if i < len(df) - 1:
                    # 检查是否快速回落
                    decline_price = df['close'].iloc[i+1:]
                    if (decline_price < upper_boundary).any():
                        utad_detected = True
                        utad_date = str(df['date'].iloc[i].date())
                        break
        
        # ST 检测 (Spring 后的二次测试)
        if spring_detected and spring_date:
            spring_idx = df[df['date'].astype(str) == spring_date].index[0]
            post_spring = df.iloc[spring_idx:]
            if len(post_spring) > 3:
                # 检查是否有回测 Spring 低点但不破
                retest_low = post_spring['low'].iloc[1:].min()
                spring_low = df['low'].iloc[spring_idx]
                if retest_low >= spring_low * 0.99:
                    st_detected = True
        
        # False Breakout 检测
        for gap in prep.gap_candidates:
            if gap['index'] > len(df) - 10:
                # 最近 10 日的缺口
                if gap['type'] == 'gap_up':
                    post_gap_close = df['close'].iloc[gap['index']+1:].iloc[:3]
                    if (post_gap_close < df['close'].iloc[gap['index']]).any():
                        false_breakout_detected = True
        
        return PhaseCTestResult(
            spring_detected=spring_detected,
            utad_detected=utad_detected,
            st_detected=st_detected,
            false_breakout_detected=false_breakout_detected,
            spring_date=spring_date,
            utad_date=utad_date,
        )
    
    def _step35_counterfactual(
        self,
        df: pd.DataFrame,
        bc_result: BCResult,
        phase_result: PhaseResult,
        effort_result: EffortResult,
        phase_c_test: PhaseCTestResult,
    ) -> CounterfactualResult:
        """
        Step 3.5: 反事实压力测试 - SPEC Section 8
        
        四组反证:
        1. 这是 UTAD 不是突破
        2. 这是派发不是吸筹
        3. 这是无序震荡不是 Phase C
        4. 买入后次日可能进入流动性真空
        """
        pro_score = 0.0
        con_score = 0.0
        
        # 反证 1: UTAD 不是突破
        if phase_c_test.utad_detected:
            con_score += 0.3
        elif phase_result.phase == "markup":
            pro_score += 0.2
        
        # 反证 2: 派发不是吸筹
        if effort_result.net_bias == "distribution":
            con_score += 0.3
        elif effort_result.net_bias == "accumulation":
            pro_score += 0.2
        
        # 反证 3: 无序震荡不是 Phase C
        if phase_result.phase == "no_trade_zone":
            con_score += 0.4
        elif phase_c_test.spring_detected or phase_c_test.utad_detected:
            pro_score += 0.2
        
        # 反证 4: 流动性真空
        recent_vol = df['volume'].tail(5).mean()
        avg_vol_20 = df['volume'].tail(20).mean()
        if recent_vol < avg_vol_20 * 0.5:
            liquidity_risk = "high"
            con_score += 0.2
        elif recent_vol < avg_vol_20 * 0.7:
            liquidity_risk = "medium"
        else:
            liquidity_risk = "low"
        
        # 结论是否被推翻
        conclusion_overturned = con_score >= pro_score
        
        return CounterfactualResult(
            is_utad_not_breakout="likely" if phase_c_test.utad_detected else "unlikely",
            is_distribution_not_accumulation="likely" if effort_result.net_bias == "distribution" else "unlikely",
            is_chaos_not_phase_c="likely" if phase_result.phase == "no_trade_zone" else "unlikely",
            liquidity_vacuum_risk=liquidity_risk,
            total_pro_score=pro_score,
            total_con_score=con_score,
            conclusion_overturned=conclusion_overturned,
        )
    
    def _step4_risk_assessment(
        self,
        df: pd.DataFrame,
        phase_result: PhaseResult,
        phase_c_test: PhaseCTestResult,
        counterfactual: CounterfactualResult,
    ) -> RiskAssessment:
        """
        Step 4: T+1 与盈亏比评估 - SPEC Section 9
        
        输出:
        - T+1 风险等级
        - R:R 评估
        - Spring 冷冻期
        """
        # T+1 风险评估
        atr_14 = self._calc_atr(df, 14).iloc[-1]
        current_price = df['close'].iloc[-1]
        t1_risk_pct = atr_14 / current_price
        
        if t1_risk_pct > 0.04:
            t1_risk_level = "critical"
        elif t1_risk_pct > 0.03:
            t1_risk_level = "high"
        elif t1_risk_pct > 0.02:
            t1_risk_level = "medium"
        else:
            t1_risk_level = "low"
        
        t1_description = f"基于 ATR(14)={t1_risk_pct:.2%}，次日可能承受 {t1_risk_pct:.2%} 波动"
        
        # R:R 计算
        entry_price = current_price
        invalidation_price = float(phase_result.boundary_lower_zone) * 0.98
        target_price = float(phase_result.boundary_upper_zone) * 1.02
        
        risk = entry_price - invalidation_price
        reward = target_price - entry_price
        
        rr_ratio = reward / risk if risk > 0 else 0.0
        
        if rr_ratio >= self.rule_config.confidence_a_rr_min:
            rr_assessment = "excellent"
        elif rr_ratio >= self.rule_config.confidence_b_rr_min:
            rr_assessment = "pass"
        else:
            rr_assessment = "fail"
        
        # Spring 冷冻期
        freeze_until = None
        if phase_c_test.spring_detected and phase_c_test.spring_date:
            from datetime import datetime, timedelta
            spring_dt = datetime.strptime(phase_c_test.spring_date, "%Y-%m-%d")
            freeze_until = str((spring_dt + timedelta(days=self.rule_config.spring_freeze_days)).date())
        
        return RiskAssessment(
            t1_risk_level=t1_risk_level,
            t1_structural_description=t1_description,
            rr_ratio=rr_ratio,
            rr_assessment=rr_assessment,
            freeze_until=freeze_until,
        )
    
    def _step5_trading_plan(
        self,
        bc_result: BCResult,
        phase_result: PhaseResult,
        effort_result: EffortResult,
        phase_c_test: PhaseCTestResult,
        counterfactual: CounterfactualResult,
        risk: RiskAssessment,
    ) -> TradingPlan:
        """
        Step 5: 交易计划 - SPEC Section 10
        
        固定输出字段:
        - current_assessment
        - execution_preconditions
        - direction
        - entry_trigger
        - invalidation
        - target_1
        """
        # A 股强约束：Distribution/Markdown 只能 watch_only 或 abandon
        if phase_result.phase in ["distribution", "markdown"]:
            return TradingPlan(
                current_assessment=f"{phase_result.phase} 阶段，禁止做多",
                execution_preconditions=[],
                direction="watch_only",
                entry_trigger="",
                invalidation=phase_result.boundary_upper_zone,
                target_1="",
            )
        
        # R:R 不合格 → abandon
        if risk.rr_assessment == "fail":
            return TradingPlan(
                current_assessment=f"盈亏比不足 (R:R={risk.rr_ratio:.2f})",
                execution_preconditions=[],
                direction="abandon",
                entry_trigger="",
                invalidation=phase_result.boundary_lower_zone,
                target_1="",
            )
        
        # Spring 冷冻期 → watch_only
        if phase_c_test.spring_detected and risk.freeze_until:
            from datetime import datetime
            freeze_dt = datetime.strptime(risk.freeze_until, "%Y-%m-%d").date()
            if datetime.now().date() <= freeze_dt:
                return TradingPlan(
                    current_assessment=f"Spring 冷冻期至 {risk.freeze_until}",
                    execution_preconditions=["等待冷冻期结束"],
                    direction="watch_only",
                    entry_trigger="",
                    invalidation=phase_result.boundary_lower_zone,
                    target_1=phase_result.boundary_upper_zone,
                )
        
        # 反事实结论被推翻 → watch_only
        if counterfactual.conclusion_overturned:
            return TradingPlan(
                current_assessment="反证据强于正证据",
                execution_preconditions=["等待更明确信号"],
                direction="watch_only",
                entry_trigger="",
                invalidation=phase_result.boundary_lower_zone,
                target_1=phase_result.boundary_upper_zone,
            )
        
        # 多头候选
        preconditions = []
        if phase_c_test.st_detected:
            preconditions.append("ST 确认完成")
        
        trigger = "breakout_and_retest"
        if phase_c_test.spring_detected:
            trigger = "spring_confirmation"
        
        return TradingPlan(
            current_assessment=f"{phase_result.phase} 阶段，多头候选",
            execution_preconditions=preconditions,
            direction="long_setup",
            entry_trigger=trigger,
            invalidation=phase_result.boundary_lower_zone,
            target_1=phase_result.boundary_upper_zone,
        )
    
    def _calc_confidence(
        self,
        bc_result: BCResult,
        phase_result: PhaseResult,
        phase_c_test: PhaseCTestResult,
        counterfactual: CounterfactualResult,
        risk: RiskAssessment,
    ) -> str:
        """
        计算置信度 - SPEC Section 11
        
        A/B/C/D 四级
        """
        score = 0.0
        
        # BC 明确性
        if bc_result.found and len(bc_result.enhancement_signals) >= 2:
            score += 0.3
        elif bc_result.found:
            score += 0.2
        
        # 阶段清晰性
        if phase_result.phase in ["accumulation", "markup"]:
            score += 0.2
        elif phase_result.phase == "no_trade_zone":
            score -= 0.2
        
        # Phase C 明确性
        if phase_c_test.spring_detected or phase_c_test.utad_detected:
            score += 0.2
        
        # 反事实
        if not counterfactual.conclusion_overturned:
            score += 0.1
        else:
            score -= 0.2
        
        # R:R
        if risk.rr_assessment == "excellent":
            score += 0.2
        elif risk.rr_assessment == "pass":
            score += 0.1
        else:
            score -= 0.2
        
        # 分级
        if score >= 0.8:
            return "A"
        elif score >= 0.6:
            return "B"
        elif score >= 0.4:
            return "C"
        else:
            return "D"
    
    def _create_abandon_result(
        self,
        df: pd.DataFrame,
        symbol: str,
        asset_type: str,
        analysis_date: Optional[str],
        preprocessing: PreprocessingResult,
        bc_result: BCResult,
        reason: str,
    ) -> DailyRuleResult:
        """创建放弃结论的结果"""
        return DailyRuleResult(
            symbol=symbol,
            asset_type=asset_type,
            analysis_date=analysis_date or str(df['date'].max().date()),
            input_source="data",
            preprocessing=preprocessing,
            bc_result=bc_result,
            phase_result=PhaseResult(
                phase="no_trade_zone",
                boundary_upper_zone="0",
                boundary_lower_zone="0",
                boundary_sources=[],
            ),
            effort_result=EffortResult(
                phenomena=[],
                accumulation_evidence=0.0,
                distribution_evidence=0.0,
                net_bias="neutral",
            ),
            phase_c_test=PhaseCTestResult(
                spring_detected=False,
                utad_detected=False,
                st_detected=False,
                false_breakout_detected=False,
                spring_date=None,
                utad_date=None,
            ),
            counterfactual=CounterfactualResult(
                is_utad_not_breakout="unknown",
                is_distribution_not_accumulation="unknown",
                is_chaos_not_phase_c="unknown",
                liquidity_vacuum_risk="unknown",
                total_pro_score=0.0,
                total_con_score=0.0,
                conclusion_overturned=False,
            ),
            risk=RiskAssessment(
                t1_risk_level="unknown",
                t1_structural_description="",
                rr_ratio=0.0,
                rr_assessment="fail",
                freeze_until=None,
            ),
            plan=TradingPlan(
                current_assessment=f"BC 未找到，{reason}",
                execution_preconditions=[],
                direction="abandon",
                entry_trigger="",
                invalidation="",
                target_1="",
            ),
            confidence="D",
            decision="abandon",
            abandon_reason=reason,
        )
    
    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算 ATR"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        
        return atr

```

---

## src/wyckoff/engine.py

```python
# -*- coding: utf-8 -*-
"""
v3.0 威科夫分析引擎 - 唯一入口
合并 analyzer.py + data_engine.py，100% 实现 Promote_v3.0.md
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import pandas as pd
import numpy as np

from src.wyckoff.models import (
    BCPoint,
    ChipAnalysis,
    ConfidenceLevel,
    ConfidenceResult,
    ImageEvidenceBundle,
    LimitMove,
    LimitMoveType,
    MultiTimeframeContext,
    RiskRewardProjection,
    RiskRewardResult,
    Rule0Result,
    SCPoint,
    Step1Result,
    Step2Result,
    Step3Result,
    StopLossResult,
    StressTest,
    SupportResistance,
    TimeframeSnapshot,
    TradingPlan,
    V3CounterfactualResult,
    V3TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from src.wyckoff.rules import V3Rules

logger = logging.getLogger(__name__)


class WyckoffEngine:
    """v3.0 威科夫分析引擎 - 唯一入口"""

    def __init__(self, lookback_days: int = 120, weekly_lookback: int = 180, monthly_lookback: int = 120):
        self.lookback_days = lookback_days
        self.weekly_min_rows = 20
        self.monthly_min_rows = 12
        self.weekly_lookback = weekly_lookback  # 周线回看行数
        self.monthly_lookback = monthly_lookback  # 月线回看行数
        # 计算多周期分析所需的日线数据量
        # 周线: weekly_lookback周 × 7天
        # 月线: monthly_lookback月 × 30天
        weekly_days = weekly_lookback * 7
        monthly_days = monthly_lookback * 30
        self.multi_timeframe_lookback_days = max(lookback_days, weekly_days, monthly_days)
        self.rules = V3Rules()

    def _normalize_input_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.sort_values("date").reset_index(drop=True)

    def _resample_ohlcv(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        frame = self._normalize_input_frame(df).set_index("date")
        resampled = (
            frame.resample(rule, label="right", closed="right")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return resampled

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        period: str = "日线",
        multi_timeframe: bool = False,
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        """主入口 - 严格按 v3.0 九步执行"""
        if multi_timeframe and period == "日线":
            return self._analyze_multiframe(df, symbol, image_evidence)
        return self._analyze_single(df, symbol, period, image_evidence)

    def _analyze_single(
        self,
        df: pd.DataFrame,
        symbol: str,
        period: str,
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        """单周期 - Step 0→5"""
        frame = self._normalize_input_frame(df)
        
        # 根据周期设置正确的最小行数
        if period == "日线":
            min_rows = 100
        elif period == "周线":
            min_rows = self.weekly_min_rows
        else:  # 月线
            min_rows = self.monthly_min_rows
        
        if frame is None or len(frame) < min_rows:
            reason = f"数据不足，需要至少 {min_rows} 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, period, reason)

        # 根据周期设置正确的回看行数
        if period == "日线":
            lookback = self.lookback_days
        elif period == "周线":
            lookback = min(len(frame), self.weekly_lookback)
        else:  # 月线
            lookback = min(len(frame), self.monthly_lookback)
        
        frame = frame.tail(lookback).reset_index(drop=True)

        # Step 0: BC/TR 定位扫描
        rule0 = self._step0_bc_tr_scan(frame)
        
        if rule0.validity == "insufficient":
            return self._create_no_signal_report(symbol, period, "BC和TR均不可见，结构不足")

        # Step 1: 大局观与阶段判定
        step1 = self._step1_phase_determine(frame, rule0)

        # 规则4: 诚实不作为原则 - 检测信号矛盾
        contradictions = 0
        if step1.phase == WyckoffPhase.UNKNOWN:
            contradictions += 1
        if rule0.validity in ("partial", "tr_fallback"):
            contradictions += 1
        
        struct_clarity = "清晰"
        if step1.phase == WyckoffPhase.UNKNOWN:
            struct_clarity = "混沌"
        elif contradictions >= 2:
            struct_clarity = "矛盾"
        
        if self.rules.rule4_no_trade_zone(contradictions, struct_clarity):
            return self._create_no_signal_report(symbol, period, "信号矛盾或结构混沌，进入No Trade Zone")

        # Step 2: 努力与结果
        step2 = self._step2_effort_result(frame, step1)

        # Step 3: Spring/UTAD + T+1
        step3 = self._step3_phase_c_t1(frame, step1, rule0)

        # Step 3.5: 反事实
        step35 = self._step35_counterfactual(frame, step1, step2, step3, rule0)

        # Step 4: 盈亏比
        rr_result = self._step4_risk_reward(frame, step1, step3, rule0)

        # 置信度计算
        confidence = self._calc_confidence(rule0, step3, step35, rr_result, False)

        # Step 5: 交易计划
        v3_plan = self._step5_trading_plan(step1, step3, step35, rr_result, confidence)

        # A 股铁律最终检查
        v3_plan = self._apply_a_stock_rules(step1, v3_plan)

        # 构建最终报告
        return self._build_report(
            symbol, period, frame, rule0, step1, step2, step3, step35, rr_result, confidence, v3_plan
        )

    def _step0_bc_tr_scan(self, df: pd.DataFrame) -> Rule0Result:
        """Step 0: BC/TR 定位扫描"""
        bc_point, sc_point = self._scan_bc_sc(df)
        
        # 计算 TR 边界
        recent_60 = df.tail(60)
        tr_upper = float(recent_60["high"].max())
        tr_lower = float(recent_60["low"].min())
        
        bc_found = bc_point is not None
        sc_found = sc_point is not None
        tr_defined = (tr_upper - tr_lower) / tr_lower <= 0.25 if tr_lower > 0 else False
        
        # 使用规则5进行降级策略
        fallback = self.rules.rule5_bc_tr_fallback(bc_found, tr_defined)
        
        return Rule0Result(
            bc_found=bc_found,
            bc_position=bc_point,
            sc_found=sc_found,
            sc_position=sc_point,
            bc_in_chart=bc_found,
            tr_upper=tr_upper if tr_defined else None,
            tr_lower=tr_lower if tr_defined else None,
            tr_source="bc_ar" if bc_found else ("sc_spring" if sc_found else ("rolling_range" if tr_defined else "none")),
            validity=fallback["validity"],
            confidence_base=fallback["confidence_base"],
        )

    def _step1_phase_determine(self, df: pd.DataFrame, rule0: Rule0Result) -> Step1Result:
        """Step 1: 大局观与阶段判定（保留 analyzer.py 核心逻辑）"""
        recent_60 = df.tail(60)
        price_high = float(recent_60["high"].max())
        price_low = float(recent_60["low"].min())
        current_price = float(df.iloc[-1]["close"])
        ma5 = float(df.tail(5)["close"].mean())
        ma20 = float(df.tail(20)["close"].mean())
        total_range_pct = (price_high - price_low) / price_low if price_low > 0 else 1.0
        relative_position = (
            (current_price - price_low) / (price_high - price_low)
            if price_high > price_low
            else 0.5
        )

        # 近 20 日 vs 前 20 日均价变化
        if len(df) >= 40:
            recent_mean = float(df.tail(20)["close"].mean())
            prev_mean = float(df.iloc[-40:-20]["close"].mean())
        else:
            recent_mean = float(df.tail(10)["close"].mean())
            prev_mean = float(df.head(10)["close"].mean())
        short_trend_pct = (recent_mean - prev_mean) / prev_mean if prev_mean > 0 else 0.0

        is_in_trading_range = (total_range_pct <= 0.20) and (abs(short_trend_pct) < 0.05)

        phase = WyckoffPhase.UNKNOWN
        unknown_candidate = ""

        if is_in_trading_range:
            # TR 内，看 TR 前的方向
            prior_window = df.iloc[:-60] if len(df) > 60 else pd.DataFrame()
            if len(prior_window) >= 10:
                prior_first = float(prior_window["close"].iloc[0])
                prior_last = float(prior_window["close"].iloc[-1])
                prior_trend_pct = (prior_last - prior_first) / prior_first if prior_first > 0 else 0.0
            else:
                prior_trend_pct = 0.0

            # 使用最佳版本阈值(a438a32)
            # 1. 前趋势下跌>10%
            # 2. 或 relative_position<=0.40 + BC定位
            if prior_trend_pct < -0.10:
                phase = WyckoffPhase.ACCUMULATION
            elif prior_trend_pct > 0.10:
                phase = WyckoffPhase.DISTRIBUTION
            else:
                if relative_position <= 0.40 and rule0.bc_found:
                    phase = WyckoffPhase.ACCUMULATION
                elif (
                    (relative_position >= 0.55 or short_trend_pct >= 0.03)
                    and (
                        (current_price > ma20 * 0.97 and ma5 >= ma20 * 0.97)
                        or (current_price > ma5 and relative_position >= 0.50)
                    )
                ):
                    phase = WyckoffPhase.MARKUP
                elif (
                    rule0.bc_found
                    and rule0.bc_position is not None
                    and current_price <= rule0.bc_position.price * 0.85
                    and current_price < ma20 * 0.95
                    and ma5 <= ma20
                    and short_trend_pct <= -0.02
                ):
                    phase = WyckoffPhase.MARKDOWN
                else:
                    phase = WyckoffPhase.UNKNOWN
        else:
            # 非 TR，按短期趋势方向判定
            # 使用60日均线辅助判断，减少短期波动干扰
            ma60 = float(df.tail(60)["close"].mean()) if len(df) >= 60 else ma20
            
            if short_trend_pct >= 0.03 and (
                (current_price > ma20 and ma5 >= ma20)
                or (current_price > ma5 and relative_position >= 0.50)
            ):
                phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.015
                and current_price > ma20
                and ma5 >= ma20 * 0.98
                and relative_position >= 0.70
            ):
                phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.05
                and ma5 >= ma20
                and current_price >= ma20 * 0.99
                and relative_position >= 0.65
            ):
                phase = WyckoffPhase.MARKUP
            # 使用最佳版本阈值(a438a32)
            elif short_trend_pct <= -0.05 and current_price < ma20 * 0.95:
                phase = WyckoffPhase.MARKDOWN
            elif (
                rule0.bc_found
                and rule0.bc_position is not None
                and current_price <= rule0.bc_position.price * 0.90
                and current_price < ma20
                and ma5 <= ma20
                and short_trend_pct <= 0
            ):
                phase = WyckoffPhase.MARKDOWN
            elif (
                rule0.bc_found
                and rule0.bc_position is not None
                and short_trend_pct <= -0.04
                and relative_position <= 0.25
                and current_price <= rule0.bc_position.price * 0.75
            ):
                phase = WyckoffPhase.MARKDOWN
            # 新增：非TR分支的Accumulation检测
            # 捕捉从下跌转向积累的早期形态
            elif (
                short_trend_pct <= -0.02
                and relative_position <= 0.40
                and current_price < ma20
                and ma5 <= ma20
                and (rule0.bc_found or rule0.sc_found)
            ):
                phase = WyckoffPhase.ACCUMULATION
            else:
                phase = WyckoffPhase.UNKNOWN

        # UNKNOWN 子状态分类
        if phase == WyckoffPhase.UNKNOWN:
            unknown_candidate = self._classify_unknown_candidate(df, phase, rule0)

        # Phase A/B/C/D/E 细分（创建临时Step1Result用于分类）
        sub_phase = ""
        temp_step1 = Step1Result(
            phase=phase,
            boundary_upper=rule0.tr_upper if rule0.tr_upper else price_high,
            boundary_lower=rule0.tr_lower if rule0.tr_lower else price_low,
        )
        if phase == WyckoffPhase.ACCUMULATION:
            sub_phase = self._classify_accumulation_sub_phase(df, temp_step1, rule0)
        elif phase == WyckoffPhase.DISTRIBUTION:
            sub_phase = self._classify_distribution_sub_phase(df, temp_step1, rule0)

        # 边界锚定
        boundary_upper = rule0.tr_upper if rule0.tr_upper else price_high
        boundary_lower = rule0.tr_lower if rule0.tr_lower else price_low
        boundary_source = []
        if rule0.bc_found:
            boundary_source.append("BC")
        if rule0.tr_source == "rolling_range":
            boundary_source.append("rolling_30d")

        return Step1Result(
            phase=phase,
            sub_phase=sub_phase,
            unknown_candidate=unknown_candidate,
            prior_trend_pct=0.0,
            is_in_tr=is_in_trading_range,
            short_trend_pct=short_trend_pct,
            relative_position=relative_position,
            ma5=ma5,
            ma20=ma20,
            boundary_upper=boundary_upper,
            boundary_lower=boundary_lower,
            boundary_source=boundary_source,
        )

    def _step2_effort_result(self, df: pd.DataFrame, step1: Step1Result) -> Step2Result:
        """Step 2: 努力与结果（含跳空缺口检测）"""
        phenomena = []
        accumulation_evidence = 0.0
        distribution_evidence = 0.0
        
        recent_20 = df.tail(20)
        if len(recent_20) < 10:
            return Step2Result()
        
        avg_vol = recent_20["volume"].mean()
        price_change = (recent_20["close"].iloc[-1] - recent_20["close"].iloc[0]) / recent_20["close"].iloc[0]
        vol_change = (recent_20["volume"].iloc[-1] - avg_vol) / avg_vol if avg_vol > 0 else 0
        
        # 放量滞涨 → 派发倾向
        if vol_change > 0.3 and abs(price_change) < 0.02:
            distribution_evidence += 0.3
            phenomena.append("放量滞涨")
        
        # 缩量上推 → 吸筹倾向
        if vol_change < -0.3 and price_change > 0.02:
            accumulation_evidence += 0.2
            phenomena.append("缩量上推")
        
        # 下边界供给枯竭
        if step1.boundary_lower > 0:
            recent_low = float(recent_20["low"].min())
            if recent_low <= step1.boundary_lower * 1.02:
                low_vol = recent_20[recent_20["low"] <= step1.boundary_lower * 1.02]["volume"].mean()
                if low_vol < avg_vol * 0.7:
                    accumulation_evidence += 0.3
                    phenomena.append("下边界供给枯竭")
        
        # 高位炸板遗迹
        for _, row in recent_20.iterrows():
            pct = (row["close"] - row["open"]) / row["open"] if row["open"] > 0 else 0
            if pct > 0.09 and row["high"] > row["close"] * 1.02:
                distribution_evidence += 0.3
                phenomena.append("高位炸板遗迹")
                break
        
        # 跳空缺口检测
        for i in range(1, len(recent_20)):
            prev_row = recent_20.iloc[i-1]
            curr_row = recent_20.iloc[i]
            
            # 向上跳空缺口：当前最低价 > 前一天最高价
            if curr_row["low"] > prev_row["high"]:
                gap_size = (curr_row["low"] - prev_row["high"]) / prev_row["high"] * 100
                if gap_size > 1.0:  # 缺口大于1%
                    # 判断缺口类型
                    if curr_row["close"] > curr_row["open"]:  # 阳线
                        phenomena.append(f"向上突破缺口({gap_size:.1f}%)")
                        accumulation_evidence += 0.2
                    else:  # 阴线
                        phenomena.append(f"向上竭尽缺口({gap_size:.1f}%)")
                        distribution_evidence += 0.2
            
            # 向下跳空缺口：当前最高价 < 前一天最低价
            elif curr_row["high"] < prev_row["low"]:
                gap_size = (prev_row["low"] - curr_row["high"]) / prev_row["low"] * 100
                if gap_size > 1.0:  # 缺口大于1%
                    # 判断缺口类型
                    if curr_row["close"] < curr_row["open"]:  # 阴线
                        phenomena.append(f"向下逃逸缺口({gap_size:.1f}%)")
                        distribution_evidence += 0.3
                    else:  # 阳线
                        phenomena.append(f"向下竭尽缺口({gap_size:.1f}%)")
                        accumulation_evidence += 0.2
        
        net_bias = "neutral"
        if accumulation_evidence > distribution_evidence + 0.1:
            net_bias = "accumulation"
        elif distribution_evidence > accumulation_evidence + 0.1:
            net_bias = "distribution"
        
        return Step2Result(
            phenomena=phenomena,
            accumulation_evidence=round(accumulation_evidence, 2),
            distribution_evidence=round(distribution_evidence, 2),
            net_bias=net_bias,
        )

    def _step3_phase_c_t1(self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result) -> Step3Result:
        """Step 3: Spring/UTAD + T+1 风险"""
        spring_detected = False
        spring_quality = "无"
        spring_date = None
        spring_low_price = None
        utad_detected = False
        st_detected = False
        lps_confirmed = False
        spring_volume = ""
        
        # Spring 检测（在 ACCUMULATION 和 UNKNOWN 阶段都可能有效）
        if step1.phase in (WyckoffPhase.ACCUMULATION, WyckoffPhase.UNKNOWN) and step1.boundary_lower > 0:
            low_bound = step1.boundary_lower
            recent_20 = df.tail(20)
            
            for i, row in recent_20.iterrows():
                # 使用最佳版本阈值(a438a32)
                # 1. 允许3%的误差
                # 2. 收回到边界附近（97%）
                if row["low"] < low_bound * 1.03:  # 允许3%的误差
                    # 检查是否快速收回
                    if row["close"] >= low_bound * 0.97:  # 收回到边界附近
                        spring_detected = True
                        spring_date = str(row["date"])
                        spring_low_price = float(row["low"])
                        
                        # 量能质量评估
                        vol_level = self.rules.rule1_relative_volume(row["volume"], df["volume"])
                        spring_volume = vol_level
                        
                        if vol_level in ("地量", "萎缩"):
                            spring_quality = "一级(缩量)"
                        else:
                            spring_quality = "二级(放量需ST)"
                        
                        # LPS 验证（规则6）- 检查后续K线
                        post_spring_idx = df.index.get_loc(i)
                        if post_spring_idx < len(df) - 3:
                            post_spring_df = df.iloc[post_spring_idx+1:]
                            lps_result = self.rules.rule6_spring_validation(True, post_spring_df, spring_low_price)
                            lps_confirmed = lps_result["lps_confirmed"]
                            if lps_confirmed:
                                spring_quality = lps_result["quality"]
                        break
            
            # 如果没有检测到Spring，检查是否有SOS信号
            if not spring_detected and step1.phase == WyckoffPhase.ACCUMULATION:
                # 优化：放宽SOS检测条件
                # 1. 价格突破上边界95%（原98%）
                # 2. 量能配合条件放宽
                if step1.boundary_upper > 0:
                    recent_5 = df.tail(5)
                    for _, row in recent_5.iterrows():
                        if row["close"] > step1.boundary_upper * 0.95:
                            # 检查量能配合（放宽条件）
                            vol_level = self.rules.rule1_relative_volume(row["volume"], df["volume"])
                            if vol_level in ("高于平均", "天量", "平均"):  # 原：仅"高于平均"和"天量"
                                st_detected = True
                                break
        
        # UTAD 检测（DISTRIBUTION 阶段）
        if step1.phase == WyckoffPhase.DISTRIBUTION and step1.boundary_upper > 0:
            high_bound = step1.boundary_upper
            recent_10 = df.tail(10)
            
            for _, row in recent_10.iterrows():
                if row["high"] > high_bound * 1.02 and row["close"] <= high_bound * 1.01:
                    utad_detected = True
                    break
        
        # T+1 压力测试（含涨跌停流动性警告）
        current_price = float(df.iloc[-1]["close"])
        recent_30_low = float(df.tail(30)["low"].min())
        limit_moves = self._detect_limit_moves(df)
        limit_moves_data = [
            {"price": lm.price, "type": lm.move_type.value}
            for lm in limit_moves
        ]
        t1_result = self.rules.rule3_t1_risk_test(current_price, recent_30_low, limit_moves_data)
        
        return Step3Result(
            spring_detected=spring_detected,
            spring_quality=spring_quality,
            spring_date=spring_date,
            spring_low_price=spring_low_price,
            utad_detected=utad_detected,
            utad_quality="无",
            utad_date=None,
            st_detected=st_detected,
            lps_confirmed=lps_confirmed,
            spring_volume=spring_volume,
            t1_max_drawdown_pct=t1_result["pct"],
            t1_verdict=t1_result["verdict"],
            t1_description=t1_result["desc"],
        )

    def _step35_counterfactual(
        self, df: pd.DataFrame, step1: Step1Result, step2: Step2Result, 
        step3: Step3Result, rule0: Rule0Result
    ) -> V3CounterfactualResult:
        """Step 3.5: 反事实压力测试"""
        forward_evidence = []
        backward_evidence = []
        
        # 正证：吸筹证据
        if step2.net_bias == "accumulation":
            forward_evidence.extend(step2.phenomena)
        
        # 反证：派发证据
        if step2.net_bias == "distribution":
            backward_evidence.extend(step2.phenomena)
        
        # 正证：Spring 确认
        if step3.spring_detected and step3.lps_confirmed:
            forward_evidence.append("Spring+LPS确认")
        
        # 反证：UTAD 或假突破
        if step3.utad_detected:
            backward_evidence.append("UTAD假突破")
        
        pro_score = len(forward_evidence) * 2.0
        con_score = len(backward_evidence) * 2.0
        
        # 使用规则7仲裁
        cf_result = self.rules.rule7_counterfactual(pro_score, con_score)
        
        # 生成反事实场景描述
        scenario = ""
        if cf_result["overturned"]:
            scenario = f"反证({con_score:.1f})占优，原判断被推翻。反证：{', '.join(backward_evidence)}"
        elif cf_result["verdict"] == "降档":
            scenario = f"反证({con_score:.1f})接近正证({pro_score:.1f})，降档处理。需进一步验证。"
        else:
            scenario = f"正证({pro_score:.1f})占优，维持判断。正证：{', '.join(forward_evidence)}"
        
        return V3CounterfactualResult(
            utad_not_breakout="是" if not step3.utad_detected else "否",
            distribution_not_accumulation="是" if step2.net_bias != "distribution" else "否",
            chaos_not_phase_c="是" if step1.phase != WyckoffPhase.UNKNOWN else "否",
            liquidity_vacuum_risk="低" if step3.t1_verdict == "安全" else "高",
            total_pro_score=pro_score,
            total_con_score=con_score,
            conclusion_overturned=cf_result["overturned"],
            counterfactual_scenario=scenario,
            forward_evidence=forward_evidence,
            backward_evidence=backward_evidence,
        )

    def _step4_risk_reward(
        self, df: pd.DataFrame, step1: Step1Result, step3: Step3Result, rule0: Rule0Result
    ) -> RiskRewardResult:
        """Step 4: 盈亏比投影（规则10精度，多种目标位来源）"""
        current_price = float(df.iloc[-1]["close"])
        
        # 止损价 = 关键结构低点 × 0.995
        key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
        if key_low <= 0:
            key_low = float(df.tail(30)["low"].min())
        
        stop_loss_result = self.rules.rule10_stop_loss(key_low)
        stop_loss = stop_loss_result.stop_loss_price
        
        # 目标位：多种来源
        first_target = step1.boundary_upper
        first_target_source = "tr_upper"
        
        # 尝试其他目标位来源
        recent_20 = df.tail(20)
        
        # 1. 大阴线起跌点（前一天收盘价 > 当天收盘价 * 1.03）
        for i in range(len(recent_20)-1, 0, -1):
            prev_close = float(recent_20.iloc[i-1]["close"])
            curr_close = float(recent_20.iloc[i]["close"])
            if prev_close > curr_close * 1.03:
                # 大阴线起跌点
                bearish_target = prev_close
                if bearish_target > current_price and bearish_target < first_target:
                    first_target = bearish_target
                    first_target_source = "bearish_candle"
                    break
        
        # 2. 跳空缺口下沿
        for i in range(1, len(recent_20)):
            prev_row = recent_20.iloc[i-1]
            curr_row = recent_20.iloc[i]
            # 向上跳空缺口
            if curr_row["low"] > prev_row["high"]:
                gap_target = float(curr_row["low"])
                if gap_target > current_price and gap_target < first_target:
                    first_target = gap_target
                    first_target_source = "gap_lower"
                    break
        
        # 计算盈亏比
        risk = current_price - stop_loss
        reward = first_target - current_price
        
        if risk > 0:
            rr_ratio = reward / risk
        else:
            rr_ratio = 0.0
        
        # 判定 - v3.0要求盈亏比 >= 1:2.5
        if rr_ratio >= 2.5:
            rr_verdict = "excellent"
        elif rr_ratio >= 2.0:
            rr_verdict = "pass"
        elif rr_ratio >= 1.5:
            rr_verdict = "marginal"
        else:
            rr_verdict = "fail"
        
        gain_pct = (first_target - current_price) / current_price * 100 if current_price > 0 else 0
        
        return RiskRewardResult(
            entry_price=current_price,
            stop_loss=stop_loss,
            first_target=first_target,
            first_target_source=first_target_source,
            rr_ratio=round(rr_ratio, 2),
            rr_verdict=rr_verdict,
            gain_pct=round(gain_pct, 2),
        )

    def _calc_confidence(
        self, rule0: Rule0Result, step3: Step3Result, 
        cf: V3CounterfactualResult, rr: RiskRewardResult, multiframe: bool
    ) -> ConfidenceResult:
        """规则8: 置信度矩阵 - 5项条件"""
        # 条件① BC已定位
        bc_located = rule0.bc_found
        
        # 条件② Spring/LPS结构完整且已验证
        spring_lps_verified = step3.spring_detected and step3.lps_confirmed
        
        # 条件③ 反事实推演无法推翻正向判断
        counterfactual_passed = not cf.conclusion_overturned
        
        # 条件④ 盈亏比 ≥ 1:2.5
        rr_qualified = rr.rr_ratio >= 2.5
        
        # 条件⑤ 多周期方向一致
        multiframe_aligned = multiframe
        
        # 特殊情况：如果处于ACCUMULATION且有Spring信号，即使LPS未验证也可降级处理
        if step3.spring_detected and not spring_lps_verified:
            # Spring已检测但LPS未验证，降级到C
            return ConfidenceResult(
                level="C",
                bc_located=bc_located,
                spring_lps_verified=False,
                counterfactual_passed=counterfactual_passed,
                rr_qualified=rr_qualified,
                multiframe_aligned=multiframe_aligned,
                position_size="试仓",
                reason="Spring已检测但LPS未验证，降级到C",
            )
        
        # 特殊情况：如果处于MARKUP且盈亏比达标，可给B级
        if rr_qualified and not bc_located:
            return ConfidenceResult(
                level="C",
                bc_located=False,
                spring_lps_verified=spring_lps_verified,
                counterfactual_passed=counterfactual_passed,
                rr_qualified=True,
                multiframe_aligned=multiframe_aligned,
                position_size="试仓",
                reason="盈亏比达标但BC未定位，降级到C",
            )
        
        return self.rules.rule8_confidence_matrix(
            bc_located, spring_lps_verified, counterfactual_passed, rr_qualified, multiframe_aligned
        )

    def _step5_trading_plan(
        self, step1: Step1Result, step3: Step3Result, 
        cf: V3CounterfactualResult, rr: RiskRewardResult, confidence: ConfidenceResult
    ) -> V3TradingPlan:
        """Step 5: 交易计划（完整字段填充）"""
        # 基本方向 - 根据阶段和信号确定
        direction = "空仓观望"
        
        # 规则2: Markdown禁止做多
        if step1.phase == WyckoffPhase.MARKDOWN:
            direction = "空仓观望"
        elif step1.phase == WyckoffPhase.DISTRIBUTION:
            direction = "空仓观望"
        elif step1.phase == WyckoffPhase.ACCUMULATION:
            # ACCUMULATION阶段：Spring+LPS确认后可做多
            if step3.spring_detected and step3.lps_confirmed:
                if rr.rr_ratio >= 2.5:
                    direction = "做多"
                else:
                    direction = "轻仓试探"
            elif step3.spring_detected:
                # Spring已检测但LPS未确认，可观察
                direction = "观察等待"
            else:
                direction = "空仓观望"
        elif step1.phase == WyckoffPhase.MARKUP:
            # MARKUP阶段：有信号且盈亏比达标可做多
            if rr.rr_ratio >= 2.5:
                direction = "做多"
            elif rr.rr_ratio >= 1.5:
                direction = "轻仓试探"
            else:
                direction = "持有观察"
        elif step1.phase == WyckoffPhase.UNKNOWN:
            # UNKNOWN阶段：根据子状态判断
            if step1.unknown_candidate in ("phase_a_candidate", "sc_st_candidate"):
                if step3.spring_detected:
                    direction = "观察等待"
                else:
                    direction = "空仓观望"
            else:
                direction = "空仓观望"
        
        # 止损结果（含涨跌停流动性警告）
        key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
        limit_moves = self._detect_limit_moves(pd.DataFrame())  # 需要传入df
        limit_moves_data = [
            {"price": lm.price, "type": lm.move_type.value}
            for lm in limit_moves
        ]
        stop_loss_result = self.rules.rule10_stop_loss(key_low, limit_moves_data)
        
        # 多周期一致性声明
        multi_timeframe_statement = "本次分析未提供周线图，置信度已自动降一级"
        
        # 执行前提
        execution_preconditions = [
            "大盘指数未出现单边系统性暴跌",
            "所属板块未出现重大利空政策消息",
        ]
        
        # 5项置信度核对
        confidence_checks = {
            "BC定位": "已完成" if confidence.bc_located else "未完成",
            "Spring/LPS验证": "完整" if confidence.spring_lps_verified else "未验证",
            "反事实排除": "已排除" if confidence.counterfactual_passed else "反事实占优",
            "盈亏比达标": "是" if confidence.rr_qualified else "否",
            "多周期一致": "是" if confidence.multiframe_aligned else "否",
        }
        
        return V3TradingPlan(
            current_assessment=f"当前处于{step1.phase.value}阶段",
            multi_timeframe_statement=multi_timeframe_statement,
            execution_preconditions=execution_preconditions,
            direction=direction,
            entry_trigger=f"价格站稳{step1.boundary_upper:.2f}上方" if step1.boundary_upper > 0 else "",
            observation_window="3-5个交易日",
            stop_loss=stop_loss_result,
            target=rr,
            confidence=confidence,
        )

    def _apply_a_stock_rules(self, step1: Step1Result, plan: V3TradingPlan) -> V3TradingPlan:
        """A 股铁律最终检查"""
        # 规则2: Markdown 禁止做多
        blocked, reason = self.rules.rule2_no_long_in_markdown(step1.phase, "")
        if blocked:
            plan.direction = "空仓观望"
            plan.current_assessment = reason
        
        return plan

    def _build_report(
        self, symbol: str, period: str, df: pd.DataFrame,
        rule0: Rule0Result, step1: Step1Result, step2: Step2Result,
        step3: Step3Result, step35: V3CounterfactualResult,
        rr: RiskRewardResult, confidence: ConfidenceResult, v3_plan: V3TradingPlan
    ) -> WyckoffReport:
        """构建最终报告"""
        current_price = float(df.iloc[-1]["close"])
        current_date = str(df.iloc[-1]["date"])
        
        # 构建结构
        structure = WyckoffStructure(
            phase=step1.phase,
            unknown_candidate=step1.unknown_candidate,
            bc_point=rule0.bc_position,
            sc_point=None,
            support_levels=[],
            resistance_levels=[],
            trading_range_high=step1.boundary_upper,
            trading_range_low=step1.boundary_lower,
            current_price=current_price,
            current_date=current_date,
        )
        
        # 构建信号
        signal_type = "no_signal"
        signal_description = ""
        
        if step3.spring_detected:
            signal_type = "spring"
            signal_description = f"检测到Spring信号，质量：{step3.spring_quality}"
            if step3.lps_confirmed:
                signal_description += "，LPS已确认"
        elif step3.utad_detected:
            signal_type = "utad"
            signal_description = "检测到UTAD假突破信号"
        elif step3.st_detected:
            signal_type = "sos_candidate"
            signal_description = "检测到SOS候选信号"
        elif step1.phase == WyckoffPhase.ACCUMULATION:
            signal_type = "accumulation"
            signal_description = "处于积累阶段，等待Spring/SOS信号"
        elif step1.phase == WyckoffPhase.MARKUP:
            signal_type = "markup"
            signal_description = "处于上涨阶段"
        elif step1.phase == WyckoffPhase.MARKDOWN:
            signal_type = "markdown"
            signal_description = "处于下跌阶段，空仓观望"
        elif step1.phase == WyckoffPhase.DISTRIBUTION:
            signal_type = "distribution"
            signal_description = "处于派发阶段，空仓观望"
        else:
            signal_type = "no_signal"
            signal_description = "阶段不明确，空仓观望"
        
        signal = WyckoffSignal(
            signal_type=signal_type,
            trigger_price=current_price,
            volume_confirmation=VolumeLevel.AVERAGE,
            confidence=ConfidenceLevel[confidence.level],
            phase=step1.phase,
            description=signal_description if signal_description else v3_plan.current_assessment,
            t1_risk评估=step3.t1_description,
        )
        
        # 盈亏比投影
        risk_reward = RiskRewardProjection(
            entry_price=rr.entry_price,
            stop_loss=rr.stop_loss,
            first_target=rr.first_target,
            reward_risk_ratio=rr.rr_ratio,
            risk_amount=rr.entry_price - rr.stop_loss,
            reward_amount=rr.first_target - rr.entry_price,
            structure_based=rr.first_target_source,
        )
        
        # 交易计划
        trading_plan = TradingPlan(
            direction=v3_plan.direction,
            trigger_condition=v3_plan.entry_trigger,
            invalidation_point=v3_plan.stop_loss.stop_logic if v3_plan.stop_loss else "",
            first_target=f"{rr.first_target:.2f}" if rr.first_target > 0 else "",
            confidence=ConfidenceLevel[confidence.level],
            preconditions="; ".join(v3_plan.execution_preconditions) if v3_plan.execution_preconditions else "",
            current_qualification=v3_plan.current_assessment,
        )
        
        # 压力测试
        stress_tests = []
        for evidence in step35.forward_evidence:
            stress_tests.append(StressTest(
                scenario_name="正证",
                scenario_description=evidence,
                outcome="支持判断",
                passes=True,
                risk_level="低",
            ))
        for evidence in step35.backward_evidence:
            stress_tests.append(StressTest(
                scenario_name="反证",
                scenario_description=evidence,
                outcome="质疑判断",
                passes=False,
                risk_level="高",
            ))
        
        # 涨跌停检测
        limit_moves = self._detect_limit_moves(df)
        
        # 筹码分析
        chip_analysis = self._analyze_chips(df, structure)
        
        return WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=trading_plan,
            limit_moves=limit_moves,
            stress_tests=stress_tests,
            chip_analysis=chip_analysis,
        )

    def _classify_unknown_candidate(
        self, df: pd.DataFrame, phase: WyckoffPhase, rule0: Rule0Result
    ) -> str:
        """UNKNOWN 子状态分类"""
        if phase != WyckoffPhase.UNKNOWN or df.empty:
            return ""
        
        if rule0.tr_upper is None or rule0.tr_lower is None:
            return "unknown_range"
        
        last_row = df.iloc[-1]
        close_price = float(last_row["close"])
        open_price = float(last_row["open"])
        high_price = float(last_row["high"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0

        range_low = rule0.tr_lower
        range_high = rule0.tr_upper
        if range_high <= range_low:
            return "unknown_range"

        range_span = range_high - range_low
        relative_position = (close_price - range_low) / range_span
        close_location = (close_price - low_price) / max(high_price - low_price, 0.01)

        if (
            relative_position <= 0.38
            and close_location >= 0.58
            and (lower_wick > max(body, 0.01) or vol_ratio >= 1.05)
        ):
            return "sc_st_candidate"
        if (
            relative_position <= 0.50
            and close_price >= open_price
            and close_location >= 0.62
            and vol_ratio >= 0.95
        ):
            return "phase_a_candidate"
        if (
            relative_position >= 0.62
            and upper_wick > max(body * 1.2, 0.01)
            and vol_ratio >= 1.0
        ):
            return "upthrust_candidate"
        if 0.38 < relative_position < 0.68:
            return "phase_b_range"
        return "unknown_range"

    def _classify_accumulation_sub_phase(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> str:
        """Accumulation Phase A/B/C/D/E 细分"""
        if df.empty:
            return ""
        
        recent_20 = df.tail(20)
        if len(recent_20) < 10:
            return ""
        
        current_price = float(df.iloc[-1]["close"])
        boundary_lower = step1.boundary_lower
        boundary_upper = step1.boundary_upper
        
        if boundary_lower <= 0 or boundary_upper <= 0:
            return ""
        
        range_span = boundary_upper - boundary_lower
        relative_position = (current_price - boundary_lower) / range_span
        
        # 检查是否有Spring信号
        has_spring = False
        for _, row in recent_20.iterrows():
            if row["low"] < boundary_lower * 1.03 and row["close"] >= boundary_lower * 0.97:
                has_spring = True
                break
        
        # 检查是否有SOS信号
        has_sos = False
        for _, row in recent_20.tail(5).iterrows():
            if row["close"] > boundary_upper * 0.98:
                vol_level = self.rules.rule1_relative_volume(row["volume"], df["volume"])
                if vol_level in ("高于平均", "天量"):
                    has_sos = True
                    break
        
        # Phase分类
        if has_spring and has_sos:
            return "Phase D"  # Spring + SOS = Phase D
        elif has_spring:
            return "Phase C"  # Spring = Phase C
        elif relative_position <= 0.40:
            # 检查是否有SC信号
            for _, row in recent_20.iterrows():
                if row["low"] < boundary_lower * 1.05:
                    vol_level = self.rules.rule1_relative_volume(row["volume"], df["volume"])
                    if vol_level in ("天量", "高于平均"):
                        return "Phase A"  # SC = Phase A
            return "Phase B"  # 区间下部但无SC
        elif relative_position >= 0.60:
            return "Phase B"  # 区间上部
        else:
            return "Phase B"  # 区间中部

    def _classify_distribution_sub_phase(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> str:
        """Distribution Phase A/B/C/D/E 细分"""
        if df.empty:
            return ""
        
        recent_20 = df.tail(20)
        if len(recent_20) < 10:
            return ""
        
        current_price = float(df.iloc[-1]["close"])
        boundary_lower = step1.boundary_lower
        boundary_upper = step1.boundary_upper
        
        if boundary_lower <= 0 or boundary_upper <= 0:
            return ""
        
        range_span = boundary_upper - boundary_lower
        relative_position = (current_price - boundary_lower) / range_span
        
        # 检查是否有UTAD信号
        has_utad = False
        for _, row in recent_20.iterrows():
            if row["high"] > boundary_upper * 1.02 and row["close"] <= boundary_upper * 1.01:
                has_utad = True
                break
        
        # 检查是否有BC信号
        has_bc = rule0.bc_found
        
        # Phase分类
        if has_utad:
            return "Phase C"  # UTAD = Phase C
        elif has_bc:
            if relative_position >= 0.60:
                return "Phase B"  # BC后高位震荡
            else:
                return "Phase D"  # BC后下跌
        elif relative_position >= 0.70:
            return "Phase A"  # 高位
        elif relative_position <= 0.30:
            return "Phase D"  # 低位
        else:
            return "Phase B"  # 中部震荡

    def _classify_volume(self, volume: float, volume_series: pd.Series) -> VolumeLevel:
        """相对量能分类"""
        return VolumeLevel(self.rules.rule1_relative_volume(volume, volume_series))

    def _scan_bc_sc(self, df: pd.DataFrame) -> Tuple[Optional[BCPoint], Optional[SCPoint]]:
        """BC/SC 评分系统"""
        bc_point = None
        sc_point = None
        
        df = df.copy()
        df["vol_rank"] = df["volume"].rank(pct=True)
        df["range"] = df["high"] - df["low"]
        df["upper_shadow"] = df["high"] - df["close"]
        df["lower_shadow"] = df["close"] - df["low"]
        df["shadow_ratio"] = df["upper_shadow"] / (df["range"] + 1e-9)
        df["lower_shadow_ratio"] = df["lower_shadow"] / (df["range"] + 1e-9)
        
        peak_idx = df["high"].idxmax()
        trough_idx = df["low"].idxmin()
        
        # BC 点识别
        bc_candidates = []
        for idx in df.nlargest(5, "high").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            shadow_ratio = row["shadow_ratio"]
            
            score = 0
            if vol_rank > 0.8:
                score += 2
            elif vol_rank > 0.6:
                score += 1
            
            if shadow_ratio > 0.6:
                score += 2
            elif shadow_ratio > 0.4:
                score += 1
            
            peak_pos = df.index.get_loc(idx)
            if peak_pos < len(df) - 5:
                subsequent_low = df.iloc[peak_pos+1:peak_pos+10]["close"].min()
                peak_price = row["high"]
                if (peak_price - subsequent_low) / peak_price > 0.05:
                    score += 2
            
            bc_candidates.append((idx, score, row))
        
        bc_candidates.sort(key=lambda x: x[1], reverse=True)
        if bc_candidates:
            best_bc = bc_candidates[0]
            idx, score, row = best_bc
            volume_level = self._classify_volume(row["volume"], df["volume"])
            bc_point = BCPoint(
                date=str(row["date"]),
                price=float(row["high"]),
                volume_level=volume_level,
                is_extremum=(idx == peak_idx),
                confidence_score=score,
            )
        
        # SC 点识别
        sc_candidates = []
        for idx in df.nsmallest(5, "low").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            lower_shadow_ratio = row["lower_shadow_ratio"]
            
            score = 0
            if vol_rank > 0.8:
                score += 2
            elif vol_rank < 0.2:
                score += 1
            
            if lower_shadow_ratio > 0.6:
                score += 2
            elif lower_shadow_ratio > 0.4:
                score += 1
            
            trough_pos = df.index.get_loc(idx)
            if trough_pos < len(df) - 5:
                subsequent_high = df.iloc[trough_pos+1:trough_pos+10]["close"].max()
                trough_price = row["low"]
                if (subsequent_high - trough_price) / trough_price > 0.05:
                    score += 2
            
            sc_candidates.append((idx, score, row))
        
        sc_candidates.sort(key=lambda x: x[1], reverse=True)
        if sc_candidates:
            best_sc = sc_candidates[0]
            idx, score, row = best_sc
            volume_level = self._classify_volume(row["volume"], df["volume"])
            sc_point = SCPoint(
                date=str(row["date"]),
                price=float(row["low"]),
                volume_level=volume_level,
                is_extremum=(idx == trough_idx),
                confidence_score=score,
            )
        
        return bc_point, sc_point

    def _detect_limit_moves(self, df: pd.DataFrame) -> List[LimitMove]:
        """检测涨跌停与炸板异动"""
        limit_moves = []
        recent = df.tail(20)
        
        for idx, row in recent.iterrows():
            pct_change = (row["close"] - row["open"]) / row["open"]
            is_limit_up = pct_change > 0.095
            is_limit_down = pct_change < -0.095
            
            if not is_limit_up and not is_limit_down:
                continue
            
            high_change = (row["high"] - row["open"]) / row["open"]
            low_change = (row["low"] - row["open"]) / row["open"]
            
            if is_limit_up:
                if high_change < 0.095:
                    move_type = LimitMoveType.BREAK_LIMIT_UP
                    is_broken = True
                else:
                    move_type = LimitMoveType.LIMIT_UP
                    is_broken = False
            else:
                if low_change > -0.095:
                    move_type = LimitMoveType.BREAK_LIMIT_DOWN
                    is_broken = True
                else:
                    move_type = LimitMoveType.LIMIT_DOWN
                    is_broken = False
            
            volume_level = self._classify_volume(row["volume"], df["volume"])
            
            limit_moves.append(LimitMove(
                date=str(row["date"]),
                move_type=move_type,
                price=float(row["close"]),
                volume_level=volume_level,
                is_broken=is_broken,
            ))
        
        return limit_moves

    def _analyze_chips(self, df: pd.DataFrame, structure: WyckoffStructure) -> ChipAnalysis:
        """筹码微观分析"""
        analysis = ChipAnalysis()
        recent = df.tail(20)
        
        if len(recent) < 10:
            return analysis
        
        price_change = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[0]
        volume_change = (recent["volume"].iloc[-1] - recent["volume"].iloc[0]) / recent["volume"].iloc[0]
        
        if price_change > 0.05 and volume_change < -0.3:
            analysis.volume_price_divergence = True
            analysis.warnings.append("量价背离：价格上涨但量能萎缩")
        
        if price_change < -0.05 and volume_change > 0.3:
            analysis.distribution_signature = True
        
        if price_change > 0.05 and volume_change > 0.2:
            analysis.absorption_signature = True
            analysis.institutional_footprint = True
        
        return analysis

    def _analyze_multiframe(
        self, df: pd.DataFrame, symbol: str, image_evidence: Optional[ImageEvidenceBundle] = None
    ) -> WyckoffReport:
        """多周期分析"""
        frame = self._normalize_input_frame(df)
        if frame is None or len(frame) < 100:
            reason = f"数据不足，需要至少 100 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, "日线+周线+月线", reason)

        long_frame = frame.tail(self.multi_timeframe_lookback_days).reset_index(drop=True)
        weekly_df = self._resample_ohlcv(long_frame, "W-FRI")
        monthly_df = self._resample_ohlcv(long_frame, "ME")

        daily_report = self._analyze_single(frame, symbol, "日线", image_evidence)
        weekly_report = self._analyze_single(weekly_df, symbol, "周线")
        monthly_report = self._analyze_single(monthly_df, symbol, "月线")

        return self._merge_multitimeframe_reports(
            symbol=symbol,
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

    def _merge_multitimeframe_reports(
        self,
        symbol: str,
        daily_report: WyckoffReport,
        weekly_report: WyckoffReport,
        monthly_report: WyckoffReport,
    ) -> WyckoffReport:
        """多周期融合"""
        final_report = daily_report
        monthly_phase = monthly_report.structure.phase
        weekly_phase = weekly_report.structure.phase
        daily_phase = daily_report.structure.phase
        rr_ratio = final_report.risk_reward.reward_risk_ratio or 0.0

        alignment = "mixed"
        if monthly_phase == weekly_phase == daily_phase:
            alignment = "fully_aligned"
        elif weekly_phase == daily_phase:
            alignment = "weekly_daily_aligned"
        elif monthly_phase == weekly_phase:
            alignment = "higher_timeframe_aligned"

        summary = f"月线={monthly_phase.value} / 周线={weekly_phase.value} / 日线={daily_phase.value}"
        constraint_note = "维持日线结论"

        # 使用规则9进行多周期一致性判断
        alignment_type, alignment_desc = self.rules.rule9_multiframe_alignment(
            daily_phase, weekly_phase, monthly_phase
        )

        if alignment_type == "markdown_override":
            final_report.structure.phase = WyckoffPhase.MARKDOWN
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = alignment_desc
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = alignment_desc
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = alignment_desc
        elif alignment_type == "distribution_override":
            final_report.structure.phase = WyckoffPhase.DISTRIBUTION
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = alignment_desc
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = alignment_desc
        elif alignment_type == "degraded":
            final_report.signal.confidence = ConfidenceLevel.C
            final_report.trading_plan.confidence = ConfidenceLevel.C
            constraint_note = alignment_desc
        elif alignment_type == "aligned":
            if final_report.signal.confidence == ConfidenceLevel.A:
                final_report.signal.confidence = ConfidenceLevel.B
            final_report.trading_plan.confidence = final_report.signal.confidence
            constraint_note = alignment_desc

        final_report.period = "日线+周线+月线"
        final_report.multi_timeframe = MultiTimeframeContext(
            enabled=True,
            monthly=self._build_timeframe_snapshot(monthly_report),
            weekly=self._build_timeframe_snapshot(weekly_report),
            daily=self._build_timeframe_snapshot(daily_report),
            alignment=alignment,
            summary=summary,
            constraint_note=constraint_note,
        )

        return final_report

    def _build_timeframe_snapshot(self, report: WyckoffReport) -> TimeframeSnapshot:
        """构建周期快照"""
        return TimeframeSnapshot(
            period=report.period,
            phase=report.structure.phase,
            unknown_candidate=report.structure.unknown_candidate,
            current_price=report.structure.current_price,
            current_date=report.structure.current_date,
            trading_range_high=report.structure.trading_range_high,
            trading_range_low=report.structure.trading_range_low,
            bc_price=report.structure.bc_point.price if report.structure.bc_point else None,
            sc_price=report.structure.sc_point.price if report.structure.sc_point else None,
            signal_type=report.signal.signal_type,
            signal_description=report.signal.description,
        )

    def _create_no_signal_report(self, symbol: str, period: str, reason: str) -> WyckoffReport:
        """创建无信号报告"""
        structure = WyckoffStructure(
            phase=WyckoffPhase.UNKNOWN,
            unknown_candidate="",
            bc_point=None,
            sc_point=None,
            current_price=0.0,
            current_date="",
        )
        
        signal = WyckoffSignal(
            signal_type="no_signal",
            confidence=ConfidenceLevel.D,
            description=reason,
        )
        
        risk_reward = RiskRewardProjection()
        trading_plan = TradingPlan(
            direction="空仓观望",
            current_qualification=reason,
            confidence=ConfidenceLevel.D,
        )
        
        return WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=trading_plan,
        )
```

---

## src/wyckoff/fusion_engine.py

```python
# -*- coding: utf-8 -*-
"""
Wyckoff 融合引擎
负责融合数据引擎和图像引擎的分析结果，处理冲突，输出最终决策
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from src.wyckoff.models import AnalysisResult, AnalysisState, ImageEvidenceBundle, WyckoffReport

logger = logging.getLogger(__name__)


class FusionEngine:
    """融合引擎 - 融合数据与图像分析结果"""
    
    def __init__(self, config=None):
        self.config = config
        # 冲突矩阵定义
        self.conflict_matrix = {
            ('accumulation', 'possible_distribution'): 'high',
            ('markup', 'possible_markdown'): 'high',
            ('distribution', 'possible_accumulation'): 'high',
            ('markdown', 'possible_markup'): 'high',
        }
    
    def fuse(
        self,
        report: WyckoffReport,
        image_evidence: Optional[ImageEvidenceBundle] = None
    ) -> AnalysisResult:
        """
        融合数据与图像分析结果
        
        Args:
            report: 数据引擎分析报告
            image_evidence: 图像证据包（可选）
            
        Returns:
            AnalysisResult 融合分析结果
        """
        if hasattr(report, "phase_result") and hasattr(report, "bc_result"):
            return self._fuse_daily_rule_result(report, image_evidence)

        # 初始化结果
        result = AnalysisResult()
        
        # 从报告中提取核心字段
        result.symbol = report.symbol
        if report.structure and getattr(report.structure, "current_date", None):
            result.analysis_date = str(report.structure.current_date)[:10]
        else:
            result.analysis_date = ""
        result.input_sources = ["data"]
        
        # 处理图像证据
        if image_evidence:
            result.input_sources.append("images")
            result.timeframes_seen = self._extract_timeframes(image_evidence)
            
            # 检查冲突
            conflicts = self._detect_conflicts(report, image_evidence)
            result.conflicts = conflicts
        
        # 核心分析字段
        result.bc_found = report.structure.bc_point is not None if report.structure else False
        result.phase = self._map_phase(report.signal.phase.value if hasattr(report.signal.phase, 'value') else str(report.signal.phase) if report.signal and report.signal.phase else "unknown")
        result.micro_action = report.signal.signal_type if report.signal and hasattr(report.signal, 'signal_type') else ""
        
        # 边界与量能
        if report.structure:
            result.boundary_upper_zone = str(report.structure.trading_range_high) if report.structure.trading_range_high else ""
            result.boundary_lower_zone = str(report.structure.trading_range_low) if report.structure.trading_range_low else ""
        if report.signal and report.signal.volume_confirmation:
            result.volume_profile_label = report.signal.volume_confirmation.value if hasattr(report.signal.volume_confirmation, 'value') else str(report.signal.volume_confirmation)
        
        # 特殊信号
        result.spring_detected = report.signal.signal_type == "spring" if report.signal and hasattr(report.signal, 'signal_type') else False
        result.utad_detected = report.signal.signal_type == "utad" if report.signal and hasattr(report.signal, 'signal_type') else False
        
        # 风险评估
        result.counterfactual_summary = "压力测试通过" if report.stress_tests else "未执行压力测试"
        result.t1_risk_assessment = self._assess_t1_risk(report)
        result.rr_assessment = "pass" if report.risk_reward and hasattr(report.risk_reward, 'reward_risk_ratio') and report.risk_reward.reward_risk_ratio >= 2.5 else "fail"
        
        # 交易计划
        result.decision = self._determine_decision(report, image_evidence)
        if report.trading_plan:
            result.trigger = report.trading_plan.trigger_condition if hasattr(report.trading_plan, 'trigger_condition') else ""
            result.invalidation = report.trading_plan.invalidation_point if hasattr(report.trading_plan, 'invalidation_point') else ""
            result.target_1 = report.trading_plan.first_target if hasattr(report.trading_plan, 'first_target') else ""
        result.confidence = report.signal.confidence.value if report.signal and hasattr(report.signal.confidence, 'value') else (report.signal.confidence if report.signal and report.signal.confidence else "D")
        result.abandon_reason = self._get_abandon_reason(report, image_evidence)
        
        return result

    def _fuse_daily_rule_result(self, result_obj, image_evidence: Optional[ImageEvidenceBundle]) -> AnalysisResult:
        result = AnalysisResult(
            symbol=result_obj.symbol,
            asset_type=result_obj.asset_type,
            analysis_date=result_obj.analysis_date,
            input_sources=["data"] + (["images"] if image_evidence else []),
            timeframes_seen=image_evidence.detected_timeframes if image_evidence else [],
            bc_found=result_obj.bc_result.found,
            phase=result_obj.phase_result.phase,
            micro_action=result_obj.plan.current_assessment if result_obj.plan else "",
            boundary_upper_zone=result_obj.phase_result.boundary_upper_zone,
            boundary_lower_zone=result_obj.phase_result.boundary_lower_zone,
            volume_profile_label=result_obj.preprocessing.volume_label,
            spring_detected=result_obj.phase_c_test.spring_detected if result_obj.phase_c_test else False,
            utad_detected=result_obj.phase_c_test.utad_detected if result_obj.phase_c_test else False,
            counterfactual_summary=(
                "conclusion_overturned"
                if result_obj.counterfactual and result_obj.counterfactual.conclusion_overturned
                else "not_overturned"
            ),
            t1_risk_assessment=result_obj.risk.t1_risk_level if result_obj.risk else "unknown",
            rr_assessment=result_obj.risk.rr_assessment if result_obj.risk else "fail",
            trigger=result_obj.plan.entry_trigger if result_obj.plan else "",
            invalidation=result_obj.plan.invalidation if result_obj.plan else "",
            target_1=result_obj.plan.target_1 if result_obj.plan else "",
            confidence=result_obj.confidence,
            abandon_reason=result_obj.abandon_reason,
            image_bundle=image_evidence,
        )
        result.conflicts = self._detect_daily_rule_conflicts(result_obj, image_evidence) if image_evidence else []
        result.consistency_score = "high_alignment" if not result.conflicts else "conflicted"

        if result.rr_assessment == "fail":
            result.decision = "abandon"
            if not result.abandon_reason:
                result.abandon_reason = "unfavorable_rr_or_structure"
        elif result_obj.phase_result.phase in ["distribution", "markdown"]:
            result.decision = "watch_only"
        else:
            result.decision = result_obj.decision

        return result
    
    def _extract_timeframes(self, image_evidence: ImageEvidenceBundle) -> List[str]:
        """从图像证据提取时间周期"""
        tf = image_evidence.detected_timeframe
        if tf and tf != "unknown_tf":
            return [tf]
        return []
    
    def _detect_conflicts(
        self,
        report: WyckoffReport,
        image_evidence: ImageEvidenceBundle
    ) -> List[str]:
        """检测数据与图像之间的冲突"""
        conflicts = []
        
        # 阶段冲突检测
        data_phase = (
            report.signal.phase.value
            if hasattr(report.signal, "phase") and hasattr(report.signal.phase, "value")
            else str(getattr(report.signal, "phase", "unknown"))
        )
        image_phase_hint = image_evidence.visual_phase_hint
        
        conflict_key = (data_phase, image_phase_hint)
        if conflict_key in self.conflict_matrix:
            severity = self.conflict_matrix[conflict_key]
            conflicts.append(f"阶段冲突：数据={data_phase}, 图像={image_phase_hint}, 严重程度={severity}")
        
        # 趋势冲突检测
        if image_evidence.visual_trend != "unclear":
            # 简单逻辑：数据看多 vs 图像看空
            if data_phase in ['accumulation', 'markup'] and image_evidence.visual_trend == 'downtrend':
                conflicts.append("趋势冲突：数据看多，图像显示下降趋势")
            elif data_phase in ['distribution', 'markdown'] and image_evidence.visual_trend == 'uptrend':
                conflicts.append("趋势冲突：数据看空，图像显示上升趋势")
        
        # 图像质量警告
        if image_evidence.image_quality in ['low', 'unusable']:
            conflicts.append(f"图像质量警告：{image_evidence.image_quality}，可能影响判断")
        
        return conflicts

    def _detect_daily_rule_conflicts(
        self,
        rule_result,
        image_evidence: ImageEvidenceBundle,
    ) -> List[str]:
        conflicts = []
        image_phase_hint = "unclear"
        image_trend = "unclear"
        if image_evidence.visual_evidence_list:
            image_phase_hint = image_evidence.visual_evidence_list[0].visual_phase_hint
            image_trend = image_evidence.visual_evidence_list[0].visual_trend

        conflict_key = (rule_result.phase_result.phase, image_phase_hint)
        if conflict_key in self.conflict_matrix:
            conflicts.append(
                f"阶段冲突：数据={rule_result.phase_result.phase}, 图像={image_phase_hint}, 严重程度={self.conflict_matrix[conflict_key]}"
            )

        if rule_result.phase_result.phase in ['distribution', 'markdown'] and image_trend == 'uptrend':
            conflicts.append("趋势冲突：数据看空，图像显示上升趋势")
        elif rule_result.phase_result.phase in ['accumulation', 'markup'] and image_trend == 'downtrend':
            conflicts.append("趋势冲突：数据看多，图像显示下降趋势")

        return conflicts
    
    def _map_phase(self, phase: str) -> str:
        """映射阶段到标准格式"""
        phase_map = {
            'accumulation': 'accumulation',
            'markup': 'markup',
            'distribution': 'distribution',
            'markdown': 'markdown',
            'unknown': 'no_trade_zone',
        }
        return phase_map.get(phase, 'no_trade_zone')
    
    def _assess_t1_risk(self, report: WyckoffReport) -> str:
        """评估 T+1 风险"""
        if not report.stress_tests:
            return "未评估"
        
        # 检查压力测试是否有高风险场景未通过
        # 注意：不得检查 outcome 字符串，应检查 passes 和 risk_level 字段
        for test in report.stress_tests:
            if not test.passes and getattr(test, 'risk_level', '') == '高':
                return "高风险"
        
        # 次级检查：任意场景未通过则标记为中等风险
        any_fail = any(not test.passes for test in report.stress_tests)
        return "中等风险" if any_fail else "可接受"
    
    def _determine_decision(
        self,
        report: WyckoffReport,
        image_evidence: Optional[ImageEvidenceBundle]
    ) -> str:
        """确定最终交易决策"""
        # T+1 零容错阻止：最高优先级，直接返回
        if report.trading_plan and getattr(report.trading_plan, 't1_blocked', False):
            return 'no_trade_zone'

        # 盈亏比硬门槛：不足 1:2.5 一律不准入场
        if report.risk_reward and getattr(report.risk_reward, "reward_risk_ratio", 0) < 2.5:
            return "no_trade_zone"
        
        # 数据引擎主判：从 trading_plan.direction 与 signal.signal_type 推导决策
        # WyckoffSignal 没有 action 字段，必须通过 signal_type 和 phase 判断
        base_decision = 'no_trade_zone'
        if report.signal and report.trading_plan:
            signal_type = getattr(report.signal, 'signal_type', 'no_signal')
            direction = getattr(report.trading_plan, 'direction', '')
            phase_val = getattr(report.signal.phase, 'value', '') if report.signal.phase else ''
            
            if phase_val in ('distribution', 'markdown'):
                # A 股铁律：派发 / 下跌阶段只能空仓或放弃
                base_decision = 'no_trade_zone'
            elif signal_type == 'spring':
                # Spring 信号：T+3 冷冻期内只允许观察，冷冻期结束才可执行
                base_decision = 'watch_only'
            elif signal_type in ('sos_candidate', 'accumulation'):
                base_decision = 'watch_only'
            elif signal_type == 'no_signal' or phase_val == 'unknown':
                base_decision = 'no_trade_zone'
            elif '做多' in direction:
                base_decision = 'long_setup'
        
        # 图像证据降级（图像只能降级，不能升级置信度）
        if image_evidence:
            if image_evidence.image_quality == 'unusable':
                if base_decision == 'long_setup':
                    base_decision = 'watch_only'
            
            if image_evidence.trust_level == 'low':
                if base_decision == 'long_setup':
                    base_decision = 'watch_only'
        
        # 冲突降级
        if image_evidence and len(self._detect_conflicts(report, image_evidence)) > 0:
            if base_decision == 'long_setup':
                base_decision = 'watch_only'
        
        return base_decision
    
    def _get_abandon_reason(
        self,
        report: WyckoffReport,
        image_evidence: Optional[ImageEvidenceBundle]
    ) -> str:
        """获取放弃原因"""
        reasons = []
        
        # 检查 BC 是否找到
        if not (report.structure and report.structure.bc_point):
            reasons.append("未找到 BC 点")
        
        # 检查盈亏比：PRD 要求 R:R >= 1:2.5，不足则放弃
        if report.risk_reward and hasattr(report.risk_reward, 'reward_risk_ratio'):
            if not report.risk_reward.reward_risk_ratio or report.risk_reward.reward_risk_ratio < 2.5:
                reasons.append("盈亏比不足 1:2.5")
        
        # 检查图像质量
        if image_evidence and image_evidence.image_quality == 'unusable':
            reasons.append("图像质量不可用")
        
        # 检查冲突
        if image_evidence and len(self._detect_conflicts(report, image_evidence)) > 0:
            reasons.append("数据与图像结论冲突")
        
        return "; ".join(reasons) if reasons else ""


class StateManager:
    """兼容新多模态 CLI 的轻量状态管理器。"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.state_dir = self.output_dir / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _get_state_path(self, symbol: str) -> Path:
        return self.state_dir / f"{symbol.replace('.', '_')}_wyckoff_state.json"

    def create_state_from_result(self, analysis_result: AnalysisResult) -> AnalysisState:
        return AnalysisState(
            symbol=analysis_result.symbol,
            asset_type=analysis_result.asset_type,
            analysis_date=analysis_result.analysis_date,
            last_phase=analysis_result.phase,
            last_micro_action=analysis_result.micro_action,
            last_confidence=analysis_result.confidence,
            bc_found=analysis_result.bc_found,
            spring_detected=analysis_result.spring_detected,
            freeze_until=None,
            watch_status="watching" if analysis_result.decision in ["watch_only", "long_setup"] else "none",
            trigger_armed=analysis_result.decision == "long_setup",
            trigger_text=analysis_result.trigger,
            invalid_level=analysis_result.invalidation,
            target_1=analysis_result.target_1,
            weekly_context=analysis_result.weekly_context,
            intraday_context=analysis_result.intraday_context,
            conflict_summary=analysis_result.conflicts,
            last_decision=analysis_result.decision,
            abandon_reason=analysis_result.abandon_reason,
        )

    def save_state(self, state: AnalysisState) -> str:
        state_path = self._get_state_path(state.symbol)
        payload = {
            "symbol": state.symbol,
            "asset_type": state.asset_type,
            "analysis_date": state.analysis_date,
            "last_phase": state.last_phase,
            "last_micro_action": state.last_micro_action,
            "last_confidence": state.last_confidence,
            "bc_found": state.bc_found,
            "spring_detected": state.spring_detected,
            "freeze_until": state.freeze_until,
            "watch_status": state.watch_status,
            "trigger_armed": state.trigger_armed,
            "trigger_text": state.trigger_text,
            "invalid_level": state.invalid_level,
            "target_1": state.target_1,
            "weekly_context": state.weekly_context,
            "intraday_context": state.intraday_context,
            "conflict_summary": state.conflict_summary,
            "last_decision": state.last_decision,
            "abandon_reason": state.abandon_reason,
        }
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return str(state_path)

    def load_state(self, symbol: str) -> Optional[AnalysisState]:
        state_path = self._get_state_path(symbol)
        if not state_path.exists():
            return None
        with open(state_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return AnalysisState(**payload)

    def generate_continuity_template(self, analysis_result: AnalysisResult, previous_state: Optional[AnalysisState]) -> dict:
        return {
            "phase_changed": bool(previous_state and previous_state.last_phase != analysis_result.phase),
            "freeze_period_ended": bool(previous_state and previous_state.freeze_until and not analysis_result.spring_detected),
        }

```

---

## src/wyckoff/image_engine.py

```python
# -*- coding: utf-8 -*-
"""
Wyckoff 图像引擎
负责扫描图表文件夹、提取视觉证据、识别时间周期与图像质量
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.wyckoff.models import ChartManifest, ChartManifestItem, ImageEvidenceBundle

logger = logging.getLogger(__name__)

# 支持的图片格式
SUPPORTED_IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.webp'}

# 时间周期识别模式
TIMEFRAME_PATTERNS = {
    'weekly': [r'weekly', r'周线', r'w[1-9]*', r'week'],
    'daily': [r'daily', r'日线', r'd[1-9]*', r'day'],
    '60m': [r'60m', r'60 分钟', r'60min'],
    '30m': [r'30m', r'30 分钟', r'30min'],
    '15m': [r'15m', r'15 分钟', r'15min'],
    '5m': [r'5m', r'5 分钟', r'5min'],
}

# 标的识别模式
SYMBOL_PATTERNS = [
    r'(\d{6}\.\w{2,3})',  # 600519.SH, 000001.SZ
    r'(\d{6})',  # 600519
]


class ImageEngine:
    """图像引擎 - 负责扫描和处理图表图片"""
    
    def __init__(self, config=None):
        self.supported_formats = SUPPORTED_IMAGE_FORMATS
        self.timeframe_patterns = TIMEFRAME_PATTERNS
        self.symbol_patterns = SYMBOL_PATTERNS
        self.config = config
    
    def scan_chart_directory(
        self,
        chart_dir: str,
        target_symbol: Optional[str] = None,
        recursive: bool = True
    ) -> Dict[str, List[dict]]:
        """
        扫描图表文件夹
        
        Args:
            chart_dir: 图表文件夹路径
            target_symbol: 目标标的代码（可选）
            recursive: 是否递归扫描子目录
            
        Returns:
            图表清单字典，包含文件信息和推断属性
        """
        chart_path = Path(chart_dir)
        if not chart_path.exists():
            logger.warning(f"图表文件夹不存在：{chart_dir}")
            return {'files': [], 'warnings': [f'文件夹不存在：{chart_dir}']}
        
        manifest = {'files': [], 'warnings': []}
        
        # 扫描图片文件
        if recursive:
            image_files = list(chart_path.rglob('*'))
        else:
            image_files = list(chart_path.glob('*'))
        
        for file_path in image_files:
            if not file_path.is_file():
                continue
            
            # 检查文件格式
            suffix = file_path.suffix.lower()
            if suffix not in self.supported_formats:
                continue
            
            # 获取文件信息
            file_info = {
                'file_path': str(file_path),
                'file_name': file_path.name,
                'relative_dir': str(file_path.parent.relative_to(chart_path)),
                'modified_time': self._get_modified_time(file_path),
            }
            
            # 推断标的归属
            file_info['symbol'] = self._infer_symbol(file_path.name, file_path.parent.name, target_symbol)
            
            # 推断时间周期
            file_info['timeframe'] = self._infer_timeframe(file_path.name)
            
            # 评估图像质量（基础版本 - 基于文件大小）
            file_info['image_quality'] = self._assess_image_quality_basic(file_path)
            
            manifest['files'].append(file_info)
        
        logger.info(f"扫描完成，找到 {len(manifest['files'])} 张图片")
        return manifest
    
    def scan_chart_files(
        self,
        file_paths: List[str],
        target_symbol: Optional[str] = None
    ) -> Dict[str, List[dict]]:
        """
        扫描显式指定的图片文件列表 (SPEC_IMAGE_ENGINE第2.2节)
        
        Args:
            file_paths: 图片文件路径列表
            target_symbol: 目标标的代码（可选）
            
        Returns:
            图表清单字典
        """
        manifest = {'files': [], 'warnings': []}
        
        for file_path_str in file_paths:
            file_path = Path(file_path_str)
            
            if not file_path.exists():
                manifest['warnings'].append(f"文件不存在：{file_path_str}")
                continue
            
            if not file_path.is_file():
                manifest['warnings'].append(f"不是文件：{file_path_str}")
                continue
            
            suffix = file_path.suffix.lower()
            if suffix not in self.supported_formats:
                manifest['warnings'].append(f"不支持格式：{file_path_str}")
                continue
            
            file_info = {
                'file_path': str(file_path),
                'file_name': file_path.name,
                'relative_dir': str(file_path.parent.name),
                'modified_time': self._get_modified_time(file_path),
                'symbol': self._infer_symbol(file_path.name, file_path.parent.name, target_symbol),
                'timeframe': self._infer_timeframe(file_path.name),
                'image_quality': self._assess_image_quality_basic(file_path),
            }
            manifest['files'].append(file_info)
        
        logger.info(f"扫描完成，找到 {len(manifest['files'])} 张图片")
        return manifest
    
    def _get_modified_time(self, file_path: Path) -> str:
        """获取文件修改时间"""
        try:
            mtime = os.path.getmtime(file_path)
            from datetime import datetime
            return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logger.warning(f"无法获取文件修改时间：{file_path}, 错误：{e}")
            return "unknown"
    
    def _infer_symbol(
        self,
        file_name: str,
        parent_dir: str,
        target_symbol: Optional[str] = None
    ) -> str:
        """
        推断图片归属的标的
        
        优先级：
        1. 文件名包含标准 symbol
        2. 父目录名包含标准 symbol
        3. 命令行显式指定 symbol
        4. 无法归属则记为 unassigned
        """
        # 优先级 1: 文件名包含
        for pattern in self.symbol_patterns:
            match = re.search(pattern, file_name)
            if match:
                symbol = match.group(1)
                # 标准化格式
                if len(symbol) == 6 and symbol.isdigit():
                    # 尝试推断后缀
                    if symbol.startswith('6'):
                        return f"{symbol}.SH"
                    elif symbol.startswith(('0', '3')):
                        return f"{symbol}.SZ"
                return symbol
        
        # 优先级 2: 父目录名包含
        for pattern in self.symbol_patterns:
            match = re.search(pattern, parent_dir)
            if match:
                symbol = match.group(1)
                if len(symbol) == 6 and symbol.isdigit():
                    if symbol.startswith('6'):
                        return f"{symbol}.SH"
                    elif symbol.startswith(('0', '3')):
                        return f"{symbol}.SZ"
                return symbol
        
        # 优先级 3: 显式指定
        if target_symbol:
            return target_symbol
        
        # 优先级 4: 无法归属
        return "unassigned"
    
    def _infer_timeframe(self, file_name: str) -> str:
        """
        推断图片时间周期
        
        优先级：
        1. 文件名识别
        2. 无法识别则标为 unknown_tf
        """
        file_name_lower = file_name.lower()
        
        for timeframe, patterns in self.timeframe_patterns.items():
            for pattern in patterns:
                if re.search(pattern, file_name_lower, re.IGNORECASE):
                    return timeframe
        
        return "unknown_tf"
    
    def _assess_image_quality_basic(self, file_path: Path) -> str:
        """
        基础图像质量评估（基于文件大小）
        
        质量分级：
        - high: 文件较大，可能分辨率足够
        - medium: 中等大小
        - low: 文件较小，可能分辨率不足
        - unusable: 文件过小，可能不可用
        """
        try:
            file_size = file_path.stat().st_size
            
            # 简单阈值判断（单位：字节）
            if file_size > 500 * 1024:  # > 500KB
                return "high"
            elif file_size > 100 * 1024:  # > 100KB
                return "medium"
            elif file_size > 20 * 1024:  # > 20KB
                return "low"
            else:
                return "unusable"
        except Exception as e:
            logger.warning(f"无法评估图像质量：{file_path}, 错误：{e}")
            return "medium"
    
    def extract_visual_evidence(
        self,
        manifest: Dict[str, List[dict]]
    ) -> ImageEvidenceBundle:
        """
        从图表清单提取视觉证据包
        
        Args:
            manifest: 图表清单
            
        Returns:
            ImageEvidenceBundle 图像证据包
        """
        files = [f['file_path'] for f in manifest.get('files', [])]
        manifest_items = [
            ChartManifestItem(
                file_path=f['file_path'],
                file_name=f['file_name'],
                relative_dir=f.get('relative_dir', ''),
                modified_time=f.get('modified_time', ''),
                symbol=f.get('symbol', 'unassigned'),
                inferred_timeframe=f.get('timeframe', 'unknown_tf'),
                image_quality=f.get('image_quality', 'medium'),
            )
            for f in manifest.get('files', [])
        ]
        
        if not files:
            return ImageEvidenceBundle(
                files=[],
                detected_timeframe="unknown_tf",
                image_quality="unusable",
                trust_level="low"
            )
        
        # 统计时间周期
        timeframes = {}
        for f in manifest.get('files', []):
            tf = f.get('timeframe', 'unknown_tf')
            timeframes[tf] = timeframes.get(tf, 0) + 1
        
        # 选择最常见的时间周期
        detected_timeframe = max(timeframes.keys(), key=lambda k: timeframes[k]) if timeframes else "unknown_tf"
        
        # 评估整体图像质量
        quality_counts = {}
        for f in manifest.get('files', []):
            q = f.get('image_quality', 'medium')
            quality_counts[q] = quality_counts.get(q, 0) + 1
        
        # 选择最常见的质量等级
        quality_order = ['high', 'medium', 'low', 'unusable']
        overall_quality = 'medium'
        for q in quality_order:
            if quality_counts.get(q, 0) > 0:
                overall_quality = q
                break
        
        # 确定信任级别
        if overall_quality in ['high', 'medium'] and detected_timeframe != 'unknown_tf':
            trust_level = 'high'
        elif overall_quality == 'low':
            trust_level = 'low'
        else:
            trust_level = 'medium'
        
        return ImageEvidenceBundle(
            files=files,
            detected_timeframe=detected_timeframe,
            image_quality=overall_quality,
            visual_trend="unclear",  # 基础版本暂不识别趋势
            visual_phase_hint="unclear",  # 基础版本暂不识别阶段
            visual_boundaries=[],
            visual_anomalies=[],
            visual_volume_labels="unclear",
            trust_level=trust_level,
            manifest=ChartManifest(
                files=manifest_items,
                total_count=len(manifest_items),
                usable_count=len(manifest_items),
                scan_time="",
            ),
            detected_timeframes=[detected_timeframe] if detected_timeframe != "unknown_tf" else [],
            overall_image_quality=overall_quality,
        )
    
    def generate_chart_manifest_json(
        self,
        manifest: Dict[str, List[dict]],
        output_path: str
    ) -> None:
        """
        生成图表清单 JSON 文件
        
        Args:
            manifest: 图表清单
            output_path: 输出文件路径
        """
        import json
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        logger.info(f"图表清单已保存到：{output_file}")
    
    def scan_and_extract(
        self,
        chart_dir: str,
        target_symbol: Optional[str] = None,
        output_manifest_path: Optional[str] = None
    ) -> Tuple[ImageEvidenceBundle, Dict[str, List[dict]]]:
        """
        扫描图表文件夹并提取视觉证据
        
        Args:
            chart_dir: 图表文件夹路径
            target_symbol: 目标标的代码
            output_manifest_path: 清单输出路径（可选）
            
        Returns:
            (ImageEvidenceBundle, manifest) 元组
        """
        # 扫描图表文件夹
        manifest = self.scan_chart_directory(chart_dir, target_symbol)
        
        # 提取视觉证据
        evidence = self.extract_visual_evidence(manifest)
        
        # 生成清单文件
        if output_manifest_path:
            self.generate_chart_manifest_json(manifest, output_manifest_path)
        
        return evidence, manifest

    def run(
        self,
        chart_dir: Optional[str] = None,
        chart_files: Optional[List[str]] = None,
        explicit_symbol: Optional[str] = None,
    ) -> ImageEvidenceBundle:
        """兼容新多模态 CLI 的统一入口。"""
        if chart_files:
            manifest = self.scan_chart_files(chart_files, explicit_symbol)
        elif chart_dir:
            manifest = self.scan_chart_directory(chart_dir, explicit_symbol)
        else:
            return ImageEvidenceBundle()

        return self.extract_visual_evidence(manifest)


def main():
    """图像引擎 CLI 入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Wyckoff 图像引擎')
    parser.add_argument('--chart-dir', required=True, help='图表文件夹路径')
    parser.add_argument('--symbol', default=None, help='目标标的代码')
    parser.add_argument('--output-manifest', default=None, help='清单输出路径')
    parser.add_argument('--output-dir', default='output/wyckoff', help='输出目录')
    
    args = parser.parse_args()
    
    # 创建图像引擎
    engine = ImageEngine()
    
    # 扫描并提取证据
    evidence, manifest = engine.scan_and_extract(
        args.chart_dir,
        args.symbol,
        args.output_manifest
    )
    
    # 打印结果
    print(f"扫描完成，找到 {len(manifest['files'])} 张图片")
    print(f"主要时间周期：{evidence.detected_timeframe}")
    print(f"整体图像质量：{evidence.image_quality}")
    print(f"信任级别：{evidence.trust_level}")


if __name__ == '__main__':
    main()

```

---

## src/wyckoff/models.py

```python
# -*- coding: utf-8 -*-
"""
Wyckoff Analysis Data Models
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WyckoffPhase(Enum):
    """威科夫周期阶段"""
    ACCUMULATION = "accumulation"      # 积累阶段
    MARKUP = "markup"                  # 上涨阶段
    DISTRIBUTION = "distribution"      # 派发阶段
    MARKDOWN = "markdown"              # 下跌阶段
    UNKNOWN = "unknown"                # 未知/不可交易


class ConfidenceLevel(Enum):
    """置信度等级"""
    A = "A"    # 高置信度 - 信号清晰
    B = "B"    # 中置信度 - 信号较明确
    C = "C"    # 低置信度 - 信号模糊
    D = "D"    # 放弃 - 信号杂乱/无法辨认


class VolumeLevel(Enum):
    """量能等级（相对描述）"""
    EXTREME_HIGH = "天量/爆量"          # 显著高于平均
    HIGH = "高于平均"                   # 明显高于平均
    AVERAGE = "平均"                   # 接近平均
    LOW = "萎缩"                       # 低于平均
    EXTREME_LOW = "地量"               # 极度萎缩


@dataclass
class BCPoint:
    """买入高潮点 (Buying Climax)"""
    date: str
    price: float
    volume_level: VolumeLevel
    is_extremum: bool = True
    confidence_score: int = 0  # BC 置信度评分（0-10）


@dataclass
class SCPoint:
    """卖出高潮点 (Selling Climax)"""
    date: str
    price: float
    volume_level: VolumeLevel
    is_extremum: bool = True
    confidence_score: int = 0  # SC 置信度评分（0-10）


@dataclass
class SupportResistance:
    """支撑/阻力位"""
    level: float
    type: str  # "support" or "resistance"
    source: str  # "BC", "SC", "AR", "自然回撤"
    strength: float = 1.0  # 0-1, 强度


@dataclass
class WyckoffStructure:
    """威科夫结构"""
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    unknown_candidate: str = ""
    bc_point: Optional[BCPoint] = None
    sc_point: Optional[SCPoint] = None
    support_levels: List[SupportResistance] = field(default_factory=list)
    resistance_levels: List[SupportResistance] = field(default_factory=list)
    trading_range_high: Optional[float] = None
    trading_range_low: Optional[float] = None
    current_price: Optional[float] = None
    current_date: Optional[str] = None


@dataclass
class WyckoffSignal:
    """威科夫交易信号"""
    signal_type: str = "no_signal"  # "spring", "utad", "sos", "lps", "bc", "sc", "no_signal"
    trigger_price: Optional[float] = None
    volume_confirmation: Optional[VolumeLevel] = None
    confidence: ConfidenceLevel = ConfidenceLevel.D
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    description: str = ""
    t1_risk评估: str = ""  # T+1 风险评估


@dataclass
class RiskRewardProjection:
    """盈亏比投影"""
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    first_target: Optional[float] = None
    reward_risk_ratio: float = 0.0
    risk_amount: float = 0.0
    reward_amount: float = 0.0
    structure_based: str = ""  # 结构描述


@dataclass
class TradingPlan:
    """交易计划"""
    direction: str = "空仓观望"  # "long" or "empty" (空仓观望)
    trigger_condition: str = ""  # 入场触发条件
    invalidation_point: str = ""  # 失效点/止损点
    first_target: str = ""  # 第一目标位
    confidence: ConfidenceLevel = ConfidenceLevel.D
    preconditions: str = ""  # 执行前提
    current_qualification: str = ""  # 当前定性
    spring_cooldown_days: int = 0  # Spring 冷静期
    t1_blocked: bool = False  # T+1 零容错阻止
    current_assessment: str = ""  # 新规则引擎字段
    execution_preconditions: List[str] = field(default_factory=list)  # 新规则引擎字段
    entry_trigger: str = ""  # 新规则引擎字段
    invalidation: str = ""  # 新规则引擎字段
    target_1: str = ""  # 新规则引擎字段

    def __post_init__(self) -> None:
        if self.entry_trigger and not self.trigger_condition:
            self.trigger_condition = self.entry_trigger
        elif self.trigger_condition and not self.entry_trigger:
            self.entry_trigger = self.trigger_condition

        if self.invalidation and not self.invalidation_point:
            self.invalidation_point = self.invalidation
        elif self.invalidation_point and not self.invalidation:
            self.invalidation = self.invalidation_point

        if self.target_1 and not self.first_target:
            self.first_target = self.target_1
        elif self.first_target and not self.target_1:
            self.target_1 = self.first_target

        if self.current_assessment and not self.current_qualification:
            self.current_qualification = self.current_assessment
        elif self.current_qualification and not self.current_assessment:
            self.current_assessment = self.current_qualification

        if self.execution_preconditions and not self.preconditions:
            self.preconditions = "; ".join(self.execution_preconditions)
        elif self.preconditions and not self.execution_preconditions:
            self.execution_preconditions = [self.preconditions]


@dataclass
class ChartManifestItem:
    """图片清单中的单个文件"""
    file_path: str
    file_name: str
    relative_dir: str
    modified_time: str
    symbol: str
    inferred_timeframe: str
    image_quality: str


@dataclass
class ChartManifest:
    """图片清单摘要"""
    files: List[ChartManifestItem] = field(default_factory=list)
    total_count: int = 0
    usable_count: int = 0
    scan_time: str = ""


@dataclass
class VisualEvidence:
    """单张或一组图表的视觉结论"""
    visual_trend: str = "unclear"
    visual_phase_hint: str = "unclear"
    visual_boundaries: Dict[str, Any] = field(default_factory=dict)
    visual_anomalies: List[str] = field(default_factory=list)
    visual_volume_label: str = "unclear"


class LimitMoveType(Enum):
    """涨跌停类型"""
    LIMIT_UP = "涨停"
    LIMIT_DOWN = "跌停"
    BREAK_LIMIT_UP = "炸板"  # 涨停被砸
    BREAK_LIMIT_DOWN = "撬板"  # 跌停被撬
    NONE = "无"


@dataclass
class LimitMove:
    """涨跌停事件"""
    date: str
    move_type: LimitMoveType
    price: float
    volume_level: VolumeLevel
    is_broken: bool = False


@dataclass
class StressTest:
    """反事实压力测试"""
    scenario_name: str = ""
    scenario_description: str = ""
    outcome: str = ""
    passes: bool = False
    risk_level: str = ""  # "低", "中", "高"


@dataclass
class ChipAnalysis:
    """筹码微观分析"""
    absorption_signature: bool = False  # 吸筹痕迹
    distribution_signature: bool = False  # 派发痕迹
    volume_price_divergence: bool = False  # 量价背离
    institutional_footprint: bool = False  # 机构痕迹
    warnings: List[str] = field(default_factory=list)


@dataclass
class ImageEvidenceBundle:
    """图像证据包 - 图像引擎输出"""
    files: List[str] = field(default_factory=list)  # 图片文件列表
    detected_timeframe: str = "unknown_tf"  # 检测到的时间周期 (weekly/daily/60m/30m/15m/5m/unknown_tf)
    image_quality: str = "medium"  # 图像质量 (high/medium/low/unusable)
    visual_trend: str = "unclear"  # 视觉趋势 (uptrend/downtrend/range/unclear)
    visual_phase_hint: str = "unclear"  # 视觉阶段提示 (possible_accumulation/possible_markup/possible_distribution/possible_markdown/unclear)
    visual_boundaries: List[dict] = field(default_factory=list)  # 视觉边界 [{'type': 'upper/lower', 'level': float}]
    visual_anomalies: List[str] = field(default_factory=list)  # 视觉异常 (长上影/长下影/跳空/假突破/快速收回/放量滞涨)
    visual_volume_labels: str = "unclear"  # 视觉量能标签 (extreme_high/above_average/contracted/extreme_contracted/unclear)
    trust_level: str = "medium"  # 信任级别 (high/medium/low)
    manifest: Optional[ChartManifest] = None  # 新图像引擎字段
    detected_timeframes: List[str] = field(default_factory=list)  # 新图像引擎字段
    overall_image_quality: str = ""  # 新图像引擎字段
    visual_evidence_list: List[VisualEvidence] = field(default_factory=list)  # 新图像引擎字段

    def __post_init__(self) -> None:
        if self.manifest is None:
            manifest_items = [
                ChartManifestItem(
                    file_path=file_path,
                    file_name=file_path.split("/")[-1],
                    relative_dir="",
                    modified_time="",
                    symbol="unassigned",
                    inferred_timeframe=self.detected_timeframe,
                    image_quality=self.image_quality,
                )
                for file_path in self.files
            ]
            self.manifest = ChartManifest(
                files=manifest_items,
                total_count=len(manifest_items),
                usable_count=len(manifest_items),
                scan_time="",
            )

        if self.detected_timeframes:
            if not self.detected_timeframe or self.detected_timeframe == "unknown_tf":
                self.detected_timeframe = self.detected_timeframes[0]
        elif self.detected_timeframe and self.detected_timeframe != "unknown_tf":
            self.detected_timeframes = [self.detected_timeframe]

        if self.overall_image_quality:
            if not self.image_quality:
                self.image_quality = self.overall_image_quality
        else:
            self.overall_image_quality = self.image_quality

        if not self.visual_evidence_list and (
            self.visual_trend != "unclear"
            or self.visual_phase_hint != "unclear"
            or self.visual_boundaries
            or self.visual_anomalies
            or self.visual_volume_labels != "unclear"
        ):
            boundaries: Dict[str, Any]
            if isinstance(self.visual_boundaries, dict):
                boundaries = self.visual_boundaries
            else:
                boundaries = {"levels": self.visual_boundaries}
            self.visual_evidence_list = [
                VisualEvidence(
                    visual_trend=self.visual_trend,
                    visual_phase_hint=self.visual_phase_hint,
                    visual_boundaries=boundaries,
                    visual_anomalies=self.visual_anomalies,
                    visual_volume_label=self.visual_volume_labels,
                )
            ]


@dataclass
class PreprocessingResult:
    trend_direction: str
    volume_label: str
    volatility_layer: str
    local_highs: List[Dict[str, Any]] = field(default_factory=list)
    local_lows: List[Dict[str, Any]] = field(default_factory=list)
    gap_candidates: List[Dict[str, Any]] = field(default_factory=list)
    long_wick_candidates: List[Dict[str, Any]] = field(default_factory=list)
    limit_anomalies: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BCResult:
    found: bool
    candidate_index: int
    candidate_date: str
    candidate_price: float
    volume_label: str
    enhancement_signals: List[str] = field(default_factory=list)


@dataclass
class PhaseResult:
    phase: str
    boundary_upper_zone: str
    boundary_lower_zone: str
    boundary_sources: List[str] = field(default_factory=list)


@dataclass
class EffortResult:
    phenomena: List[str] = field(default_factory=list)
    accumulation_evidence: float = 0.0
    distribution_evidence: float = 0.0
    net_bias: str = "neutral"


@dataclass
class PhaseCTestResult:
    spring_detected: bool = False
    utad_detected: bool = False
    st_detected: bool = False
    false_breakout_detected: bool = False
    spring_date: Optional[str] = None
    utad_date: Optional[str] = None


@dataclass
class CounterfactualResult:
    is_utad_not_breakout: str = "unknown"
    is_distribution_not_accumulation: str = "unknown"
    is_chaos_not_phase_c: str = "unknown"
    liquidity_vacuum_risk: str = "unknown"
    total_pro_score: float = 0.0
    total_con_score: float = 0.0
    conclusion_overturned: bool = False


@dataclass
class RiskAssessment:
    t1_risk_level: str = "unknown"
    t1_structural_description: str = ""
    rr_ratio: float = 0.0
    rr_assessment: str = "fail"
    freeze_until: Optional[str] = None


# ===== v3.0 数据结构 (REFACTOR_PLAN_WYCKOFF_V3_ENGINE.md P1) =====


@dataclass
class Rule0Result:
    """Step 0: BC/TR 定位扫描输出"""
    bc_found: bool = False
    bc_position: Optional[BCPoint] = None
    sc_found: bool = False
    sc_position: Optional[SCPoint] = None
    bc_in_chart: bool = False
    tr_upper: Optional[float] = None
    tr_lower: Optional[float] = None
    tr_source: str = "none"  # "bc_ar" | "sc_spring" | "rolling_range" | "none"
    validity: str = "insufficient"  # "full" | "partial" | "tr_fallback" | "insufficient"
    confidence_base: str = "D"  # 起评等级: A/B/C/D


@dataclass
class Step1Result:
    """Step 1: 大局观与宏观定调"""
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    sub_phase: str = ""  # Phase A/B/C/D/E 细分
    unknown_candidate: str = ""
    prior_trend_pct: float = 0.0
    is_in_tr: bool = False
    short_trend_pct: float = 0.0
    relative_position: float = 0.0
    ma5: float = 0.0
    ma20: float = 0.0
    boundary_upper: float = 0.0
    boundary_lower: float = 0.0
    boundary_source: List[str] = field(default_factory=list)


@dataclass
class Step2Result:
    """Step 2: 努力与结果"""
    phenomena: List[str] = field(default_factory=list)
    accumulation_evidence: float = 0.0
    distribution_evidence: float = 0.0
    net_bias: str = "neutral"  # "accumulation" | "distribution" | "neutral"


@dataclass
class Step3Result:
    """Step 3: Spring/UTAD + T+1 风险"""
    spring_detected: bool = False
    spring_quality: str = "无"  # "一级(缩量)" | "二级(放量需ST)" | "无"
    spring_date: Optional[str] = None
    spring_low_price: Optional[float] = None
    utad_detected: bool = False
    utad_quality: str = "无"
    utad_date: Optional[str] = None
    st_detected: bool = False
    lps_confirmed: bool = False  # v3.0 规则6
    spring_volume: str = ""
    t1_max_drawdown_pct: float = 0.0
    t1_verdict: str = "安全"  # "安全" | "偏薄" | "超限"
    t1_description: str = ""


@dataclass
class V3CounterfactualResult:
    """Step 3.5: 反事实压力测试 (v3.0增强版)"""
    utad_not_breakout: str = "unknown"
    distribution_not_accumulation: str = "unknown"
    chaos_not_phase_c: str = "unknown"
    liquidity_vacuum_risk: str = "unknown"
    total_pro_score: float = 0.0
    total_con_score: float = 0.0
    conclusion_overturned: bool = False
    counterfactual_scenario: str = ""
    forward_evidence: List[str] = field(default_factory=list)
    backward_evidence: List[str] = field(default_factory=list)


@dataclass
class StopLossResult:
    """规则10: 精确止损"""
    entry_price: float = 0.0
    stop_loss_price: float = 0.0
    stop_pct: float = 0.0
    precision_warning: bool = False
    liquidity_risk_warning: str = ""
    stop_logic: str = ""


@dataclass
class RiskRewardResult:
    """Step 4: 盈亏比投影"""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    first_target: float = 0.0
    first_target_source: str = ""  # "tr_upper" | "bearish_candle" | "gap_lower"
    rr_ratio: float = 0.0
    rr_verdict: str = "fail"  # "excellent" | "pass" | "marginal" | "fail"
    gain_pct: float = 0.0


@dataclass
class ConfidenceResult:
    """规则8: 置信度矩阵"""
    level: str = "D"  # "A" | "B" | "C" | "D"
    bc_located: bool = False  # 条件①
    spring_lps_verified: bool = False  # 条件②
    counterfactual_passed: bool = False  # 条件③
    rr_qualified: bool = False  # 条件④
    multiframe_aligned: bool = False  # 条件⑤
    position_size: str = ""
    reason: str = ""


@dataclass
class V3TradingPlan:
    """Step 5: 机构级实战交易计划"""
    current_assessment: str = ""
    multi_timeframe_statement: str = ""
    execution_preconditions: List[str] = field(default_factory=list)
    direction: str = "空仓观望"
    entry_trigger: str = ""
    observation_window: str = ""
    stop_loss: Optional[StopLossResult] = None
    target: Optional[RiskRewardResult] = None
    confidence: Optional[ConfidenceResult] = None


@dataclass
class AnalysisResult:
    """分析结果 - 融合引擎输出"""
    symbol: str = ""
    asset_type: str = "stock"  # "stock" or "index"
    analysis_date: str = ""
    input_sources: List[str] = field(default_factory=list)  # ["data", "images"]
    timeframes_seen: List[str] = field(default_factory=list)  # ["daily", "weekly", "60m"]
    
    # 核心字段
    bc_found: bool = False
    phase: str = "unknown"  # accumulation/markup/distribution/markdown/no_trade_zone
    micro_action: str = ""
    
    # 边界与量能
    boundary_upper_zone: str = ""  # 上边界区域
    boundary_lower_zone: str = ""  # 下边界区域
    volume_profile_label: str = ""  # 量能标签
    
    # 特殊信号
    spring_detected: bool = False
    utad_detected: bool = False
    
    # 风险评估
    counterfactual_summary: str = ""  # 反事实总结
    t1_risk_assessment: str = ""  # T+1 风险评估
    rr_assessment: str = ""  # 盈亏比评估 (pass/fail)
    
    # 交易计划字段
    decision: str = "no_trade_zone"  # long_setup/watch_only/no_trade_zone/abandon
    trigger: str = ""
    invalidation: str = ""
    target_1: str = ""
    confidence: str = "D"  # A/B/C/D
    abandon_reason: str = ""  # 放弃原因
    conflicts: List[str] = field(default_factory=list)  # 冲突列表
    image_bundle: Optional[ImageEvidenceBundle] = None
    consistency_score: str = ""
    weekly_context: str = ""
    intraday_context: str = ""


@dataclass
class AnalysisState:
    """分析状态 - 状态持久化"""
    symbol: str = ""
    asset_type: str = "stock"
    analysis_date: str = ""
    
    # 上次分析结果
    last_phase: str = ""
    last_micro_action: str = ""
    last_confidence: str = "D"
    
    # 关键状态
    bc_found: bool = False
    spring_detected: bool = False
    freeze_until: Optional[str] = None  # Spring 冷冻期截止日期
    watch_status: str = "none"  # none/watching/cooling_down
    
    # 触发器状态
    trigger_armed: bool = False
    trigger_text: str = ""
    invalid_level: str = ""
    target_1: str = ""
    
    # 上下文
    weekly_context: str = ""
    intraday_context: str = ""
    conflict_summary: Any = field(default_factory=list)
    
    # 决策记录
    last_decision: str = ""
    abandon_reason: str = ""


@dataclass
class DailyRuleResult:
    symbol: str
    asset_type: str
    analysis_date: str
    input_source: str
    preprocessing: PreprocessingResult
    bc_result: BCResult
    phase_result: PhaseResult
    effort_result: Optional[EffortResult]
    phase_c_test: Optional[PhaseCTestResult]
    counterfactual: Optional[CounterfactualResult]
    risk: Optional[RiskAssessment]
    plan: Optional[TradingPlan]
    confidence: str = "D"
    decision: str = "abandon"
    abandon_reason: str = ""


@dataclass
class TimeframeSnapshot:
    """单一周期快照"""
    period: str
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    unknown_candidate: str = ""
    current_price: Optional[float] = None
    current_date: Optional[str] = None
    trading_range_high: Optional[float] = None
    trading_range_low: Optional[float] = None
    bc_price: Optional[float] = None
    sc_price: Optional[float] = None
    signal_type: str = "no_signal"
    signal_description: str = ""


@dataclass
class MultiTimeframeContext:
    """多周期上下文"""
    enabled: bool = False
    monthly: Optional[TimeframeSnapshot] = None
    weekly: Optional[TimeframeSnapshot] = None
    daily: Optional[TimeframeSnapshot] = None
    alignment: str = "single_timeframe"
    summary: str = ""
    constraint_note: str = ""


@dataclass
class WyckoffReport:
    """威科夫分析报告"""
    symbol: str
    period: str  # "daily", "weekly", etc.
    structure: WyckoffStructure
    signal: WyckoffSignal
    risk_reward: RiskRewardProjection
    trading_plan: TradingPlan
    limit_moves: List[LimitMove] = field(default_factory=list)
    stress_tests: List[StressTest] = field(default_factory=list)
    chip_analysis: Optional[ChipAnalysis] = None
    
    # 多模态扩展字段
    image_evidence: Optional[ImageEvidenceBundle] = None
    analysis_result: Optional[AnalysisResult] = None
    analysis_state: Optional[AnalysisState] = None
    multi_timeframe: Optional[MultiTimeframeContext] = None
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = [
            f"# 威科夫分析报告 - {self.symbol}",
            f"**分析周期**: {self.period}",
            "",
        ]

        if self.multi_timeframe and self.multi_timeframe.enabled:
            lines.extend([
                "## Step -1: 多周期总览",
                f"- **一致性**: {self.multi_timeframe.alignment}",
                f"- **结论摘要**: {self.multi_timeframe.summary}",
                f"- **约束说明**: {self.multi_timeframe.constraint_note}",
            ])
            if self.multi_timeframe.monthly:
                lines.append(
                    f"- **月线**: {self.multi_timeframe.monthly.phase.value} @ {self.multi_timeframe.monthly.current_date}"
                )
            if self.multi_timeframe.weekly:
                lines.append(
                    f"- **周线**: {self.multi_timeframe.weekly.phase.value} @ {self.multi_timeframe.weekly.current_date}"
                )
            if self.multi_timeframe.daily:
                lines.append(
                    f"- **日线**: {self.multi_timeframe.daily.phase.value} @ {self.multi_timeframe.daily.current_date}"
                )
            lines.append("")

        lines.extend([
            "## Step 0: BC 定位扫描",
            f"- **BC点**: {self.structure.bc_point.date if self.structure.bc_point else '未找到'} @ {self.structure.bc_point.price if self.structure.bc_point else 'N/A'}",
            f"- **SC点**: {self.structure.sc_point.date if self.structure.sc_point else '未找到'} @ {self.structure.sc_point.price if self.structure.sc_point else 'N/A'}",
            "",
            "## Step 1: 大局观与宏观定调",
            f"- **当前阶段**: {self.structure.phase.value}",
            f"- **Unknown子状态**: {self.structure.unknown_candidate or 'N/A'}",
            f"- **震荡区间**: {self.structure.trading_range_low} - {self.structure.trading_range_high}",
            f"- **当前价格**: {self.structure.current_price}",
            "",
        ])
        
        limit_moves_str = ""
        if self.limit_moves:
            lm_lines = [f"- **{lm.move_type.value}** @ {lm.date} ${lm.price}" for lm in self.limit_moves[:3]]
            limit_moves_str = "\n".join(["## Step 1.5: 涨跌停与炸板异动"] + lm_lines)
            lines.append(limit_moves_str)
        
        lines.extend([
            "",
            "## Step 2: 极端流动性与筹码微观扫描",
            f"- **量能状态**: {self.signal.volume_confirmation.value if self.signal.volume_confirmation else 'N/A'}",
        ])
        
        if self.chip_analysis:
            chip_lines = []
            if self.chip_analysis.absorption_signature:
                chip_lines.append("检测到吸筹痕迹")
            if self.chip_analysis.distribution_signature:
                chip_lines.append("检测到派发痕迹")
            if self.chip_analysis.volume_price_divergence:
                chip_lines.append("⚠️ 量价背离警告")
            if self.chip_analysis.warnings:
                chip_lines.extend([f"⚠️ {w}" for w in self.chip_analysis.warnings])
            if chip_lines:
                lines.append("- " + "; ".join(chip_lines))
        
        lines.extend([
            "",
            "## Step 3: T+1 风险评估",
            f"- **T+1风险**: {self.signal.t1_risk评估}",
            "",
            "## Step 3.5: 反事实压力测试",
        ])
        
        if self.stress_tests:
            for st in self.stress_tests:
                status = "✅" if st.passes else "❌"
                lines.append(f"- {status} **{st.scenario_name}**: {st.outcome}")
        else:
            lines.append("- 无压力测试结果")
        
        lines.extend([
            "",
            "## Step 4: 盈亏比投影",
            f"- **入场价**: {self.risk_reward.entry_price}",
            f"- **止损位**: {self.risk_reward.stop_loss}",
            f"- **第一目标**: {self.risk_reward.first_target}",
            f"- **盈亏比**: {self.risk_reward.reward_risk_ratio:.2f}",
            "",
            "## Step 5: 交易计划",
            f"- **【当前定性】**: {self.trading_plan.current_qualification}",
            f"- **【执行前提】**: {self.trading_plan.preconditions}",
            f"- **【操作方向】**: {self.trading_plan.direction}",
            f"- **【精确入场 Trigger】**: {self.trading_plan.trigger_condition}",
            f"- **【铁律止损点】**: {self.trading_plan.invalidation_point}",
            f"- **【第一目标位】**: {self.trading_plan.first_target}",
            "",
        ])
        
        if self.trading_plan.spring_cooldown_days > 0:
            lines.append(f"- **【Spring冷静期】**: {self.trading_plan.spring_cooldown_days}天")
        
        if self.trading_plan.t1_blocked:
            lines.append("- **【T+1零容错】**: ❌ 阻止入场")
        
        lines.append(f"**【置信度等级】**: {self.trading_plan.confidence.value}")
        
        return "\n".join(lines)

```

---

## src/wyckoff/reporting.py

```python
# -*- coding: utf-8 -*-
"""
威科夫报告生成器 - Markdown/HTML/CSV/JSON 报告输出

遵循 SPEC_WYCKOFF_OUTPUT_SCHEMA Section 4-5 规范
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from src.wyckoff.models import (
    AnalysisResult,
    AnalysisState,
    ImageEvidenceBundle,
)

logger = logging.getLogger(__name__)


class WyckoffReportGenerator:
    """
    威科夫报告生成器 - 生成 Markdown/HTML/CSV/JSON 报告
    
    SPEC_WYCKOFF_OUTPUT_SCHEMA Section 5 映射:
    - Step 0: BC 定位
    - Step 1: 大局观与阶段
    - Step 2: 努力与结果
    - Step 3: Phase C 终极测试
    - Step 3.5: 反事实压力测试
    - Step 4: T+1 与盈亏比
    - Step 5: 交易计划
    - 附录 A: 连续性追踪
    - 附录 B: 视觉证据摘要
    """
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.raw_dir = os.path.join(output_dir, "raw")
        self.reports_dir = os.path.join(output_dir, "reports")
        self.summary_dir = os.path.join(output_dir, "summary")
        self.evidence_dir = os.path.join(output_dir, "evidence")
        
        for dir_path in [self.raw_dir, self.reports_dir, self.summary_dir, self.evidence_dir]:
            os.makedirs(dir_path, exist_ok=True)
    
    def generate_markdown_report(
        self,
        result: AnalysisResult,
        state: Optional[AnalysisState] = None,
        image_bundle: Optional[ImageEvidenceBundle] = None,
    ) -> str:
        """生成 Markdown 报告"""
        report_lines = []
        
        # 标题
        report_lines.append(f"# 威科夫多模态分析报告 - {result.symbol}")
        report_lines.append(f"\n**分析日期**: {result.analysis_date}")
        report_lines.append(f"**资产类型**: {result.asset_type}")
        report_lines.append(f"**输入来源**: {', '.join(result.input_sources)}")
        report_lines.append("")
        
        # Step 0: BC 定位
        report_lines.append("## Step 0: BC 定位")
        report_lines.append(f"- **BC 是否找到**: {'是' if result.bc_found else '否'}")
        if result.bc_found:
            report_lines.append(f"- **置信度**: {result.confidence}")
        else:
            report_lines.append(f"- **放弃原因**: {result.abandon_reason}")
        report_lines.append("")
        
        # Step 1: 大局观与阶段
        report_lines.append("## Step 1: 大局观与阶段")
        report_lines.append(f"- **当前阶段**: {result.phase}")
        report_lines.append(f"- **时间周期**: {', '.join(result.timeframes_seen)}")
        report_lines.append(f"- **上边界**: {result.boundary_upper_zone}")
        report_lines.append(f"- **下边界**: {result.boundary_lower_zone}")
        report_lines.append("")
        
        # Step 2: 努力与结果
        report_lines.append("## Step 2: 努力与结果")
        report_lines.append(f"- **量能标签**: {result.volume_profile_label}")
        report_lines.append(f"- **微观行为**: {result.micro_action}")
        if result.conflicts:
            report_lines.append(f"- **冲突**: {', '.join(result.conflicts)}")
        report_lines.append("")
        
        # Step 3: Phase C 终极测试
        report_lines.append("## Step 3: Phase C 终极测试")
        report_lines.append(f"- **Spring 检测**: {'是' if result.spring_detected else '否'}")
        report_lines.append(f"- **UTAD 检测**: {'是' if result.utad_detected else '否'}")
        report_lines.append(f"- **T+1 风险**: {result.t1_risk_assessment}")
        report_lines.append("")
        
        # Step 3.5: 反事实压力测试
        report_lines.append("## Step 3.5: 反事实压力测试")
        report_lines.append(f"- **反证摘要**: {result.counterfactual_summary}")
        report_lines.append(f"- **一致性评分**: {result.consistency_score}")
        report_lines.append("")
        
        # Step 4: T+1 与盈亏比
        report_lines.append("## Step 4: T+1 与盈亏比")
        report_lines.append(f"- **R:R 评估**: {result.rr_assessment}")
        report_lines.append(f"- **止损位**: {result.invalidation}")
        report_lines.append(f"- **目标位**: {result.target_1}")
        report_lines.append("")
        
        # Step 5: 交易计划
        report_lines.append("## Step 5: 交易计划")
        report_lines.append(f"- **当前评估**: {result.micro_action}")
        report_lines.append(f"- **方向**: {result.decision}")
        report_lines.append(f"- **触发条件**: {result.trigger}")
        report_lines.append(f"- **止损**: {result.invalidation}")
        report_lines.append(f"- **目标**: {result.target_1}")
        report_lines.append(f"- **置信度**: {result.confidence}")
        if result.abandon_reason:
            report_lines.append(f"- **放弃原因**: {result.abandon_reason}")
        report_lines.append("")
        
        # 附录 A: 连续性追踪
        report_lines.append("## 附录 A: 连续性追踪")
        if state:
            report_lines.append(f"- **上次阶段**: {state.last_phase}")
            report_lines.append(f"- **上次决策**: {state.last_decision}")
            report_lines.append(f"- **周线背景**: {result.weekly_context}")
            report_lines.append(f"- **盘中背景**: {result.intraday_context}")
        else:
            report_lines.append("*首次分析，无历史状态*")
        report_lines.append("")
        
        # 附录 B: 视觉证据摘要
        report_lines.append("## 附录 B: 视觉证据摘要")
        if image_bundle:
            report_lines.append(f"- **图像总数**: {image_bundle.manifest.total_count}")
            report_lines.append(f"- **可用图像**: {image_bundle.manifest.usable_count}")
            report_lines.append(f"- **整体质量**: {image_bundle.overall_image_quality}")
            report_lines.append(f"- **信任等级**: {image_bundle.trust_level}")
            report_lines.append(f"- **检测周期**: {', '.join(image_bundle.detected_timeframes)}")
        else:
            report_lines.append("*无图像数据*")
        report_lines.append("")
        
        report_text = "\n".join(report_lines)
        
        # 保存报告
        report_path = os.path.join(
            self.reports_dir,
            f"{result.symbol}_wyckoff_report.md"
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        logger.info(f"Markdown 报告已保存：{report_path}")
        return report_path
    
    def generate_html_report(
        self,
        result: AnalysisResult,
        state: Optional[AnalysisState] = None,
        image_bundle: Optional[ImageEvidenceBundle] = None,
    ) -> str:
        """生成 HTML 报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>威科夫多模态分析报告 - {result.symbol}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .section {{ background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 5px; }}
        .metric {{ display: inline-block; margin: 10px 20px; }}
        .metric-label {{ font-weight: bold; color: #7f8c8d; }}
        .metric-value {{ color: #2c3e50; font-size: 1.1em; }}
        .positive {{ color: #27ae60; }}
        .negative {{ color: #e74c3c; }}
        .neutral {{ color: #f39c12; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #3498db; color: white; }}
    </style>
</head>
<body>
    <h1>威科夫多模态分析报告 - {result.symbol}</h1>
    <p><strong>分析日期</strong>: {result.analysis_date} | <strong>资产类型</strong>: {result.asset_type}</p>
    
    <div class="section">
        <h2>Step 0: BC 定位</h2>
        <div class="metric">
            <span class="metric-label">BC 是否找到:</span>
            <span class="metric-value {'positive' if result.bc_found else 'negative'}">{'是' if result.bc_found else '否'}</span>
        </div>
        <div class="metric">
            <span class="metric-label">置信度:</span>
            <span class="metric-value">{result.confidence}</span>
        </div>
    </div>
    
    <div class="section">
        <h2>Step 1: 大局观与阶段</h2>
        <table>
            <tr><th>指标</th><th>值</th></tr>
            <tr><td>当前阶段</td><td>{result.phase}</td></tr>
            <tr><td>时间周期</td><td>{', '.join(result.timeframes_seen)}</td></tr>
            <tr><td>上边界</td><td>{result.boundary_upper_zone}</td></tr>
            <tr><td>下边界</td><td>{result.boundary_lower_zone}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 2: 努力与结果</h2>
        <table>
            <tr><th>指标</th><th>值</th></tr>
            <tr><td>量能标签</td><td>{result.volume_profile_label}</td></tr>
            <tr><td>微观行为</td><td>{result.micro_action}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 3: Phase C 终极测试</h2>
        <table>
            <tr><th>检测项</th><th>结果</th></tr>
            <tr><td>Spring</td><td class="{'positive' if result.spring_detected else 'negative'}">{'是' if result.spring_detected else '否'}</td></tr>
            <tr><td>UTAD</td><td class="{'positive' if result.utad_detected else 'negative'}">{'是' if result.utad_detected else '否'}</td></tr>
            <tr><td>T+1 风险</td><td>{result.t1_risk_assessment}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 4: T+1 与盈亏比</h2>
        <table>
            <tr><th>指标</th><th>值</th></tr>
            <tr><td>R:R 评估</td><td class="{'positive' if result.rr_assessment == 'excellent' else 'neutral'}">{result.rr_assessment}</td></tr>
            <tr><td>止损位</td><td>{result.invalidation}</td></tr>
            <tr><td>目标位</td><td>{result.target_1}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 5: 交易计划</h2>
        <table>
            <tr><th>字段</th><th>值</th></tr>
            <tr><td>当前评估</td><td>{result.micro_action}</td></tr>
            <tr><td>方向</td><td class="{'positive' if result.decision == 'long_setup' else 'negative'}">{result.decision}</td></tr>
            <tr><td>触发条件</td><td>{result.trigger}</td></tr>
            <tr><td>止损</td><td>{result.invalidation}</td></tr>
            <tr><td>目标</td><td>{result.target_1}</td></tr>
            <tr><td>置信度</td><td>{result.confidence}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>附录 A: 连续性追踪</h2>
        <p>{'周线背景：' + result.weekly_context if result.weekly_context else '首次分析，无历史状态'}</p>
    </div>
    
    <div class="section">
        <h2>附录 B: 视觉证据摘要</h2>
        <p>{'图像总数：' + str(image_bundle.manifest.total_count) if image_bundle else '无图像数据'}</p>
    </div>
    
    <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #7f8c8d; font-size: 0.9em;">
        生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 威科夫多模态分析系统 v1.0
    </footer>
</body>
</html>"""
        
        # 保存报告
        report_path = os.path.join(
            self.reports_dir,
            f"{result.symbol}_wyckoff_report.html"
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"HTML 报告已保存：{report_path}")
        return report_path
    
    def generate_summary_csv(self, result: AnalysisResult) -> str:
        """生成 CSV Summary - SPEC Section 4"""
        df = pd.DataFrame([{
            'symbol': result.symbol,
            'asset_type': result.asset_type,
            'analysis_date': result.analysis_date,
            'phase': result.phase,
            'micro_action': result.micro_action,
            'decision': result.decision,
            'confidence': result.confidence,
            'bc_found': result.bc_found,
            'spring_detected': result.spring_detected,
            'rr_assessment': result.rr_assessment,
            't1_risk_assessment': result.t1_risk_assessment,
            'trigger': result.trigger,
            'invalidation': result.invalidation,
            'target_1': result.target_1,
            'abandon_reason': result.abandon_reason,
        }])
        
        csv_path = os.path.join(
            self.summary_dir,
            f"analysis_summary_{result.symbol}.csv"
        )
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        logger.info(f"CSV Summary 已保存：{csv_path}")
        return csv_path
    
    def generate_raw_json(self, result: AnalysisResult) -> str:
        """生成原始 JSON - SPEC Section 1"""
        json_path = os.path.join(
            self.raw_dir,
            f"analysis_{result.symbol}.json"
        )
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self._result_to_dict(result), f, indent=2, ensure_ascii=False)
        
        logger.info(f"原始 JSON 已保存：{json_path}")
        return json_path
    
    def generate_evidence_json(self, bundle: ImageEvidenceBundle) -> str:
        """生成图像证据 JSON - SPEC Section 2"""
        json_path = os.path.join(
            self.evidence_dir,
            f"image_evidence_{bundle.manifest.files[0].symbol if bundle.manifest.files else 'unknown'}.json"
        )
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self._bundle_to_dict(bundle), f, indent=2, ensure_ascii=False)
        
        logger.info(f"图像证据 JSON 已保存：{json_path}")
        return json_path
    
    def generate_conflicts_json(self, conflicts: List[dict]) -> str:
        """生成冲突清单 JSON"""
        json_path = os.path.join(
            self.evidence_dir,
            "conflicts.json"
        )
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(conflicts, f, indent=2, ensure_ascii=False)
        
        logger.info(f"冲突清单 JSON 已保存：{json_path}")
        return json_path
    
    def _result_to_dict(self, result: AnalysisResult) -> dict:
        """将 AnalysisResult 转换为字典"""
        return {
            'symbol': result.symbol,
            'asset_type': result.asset_type,
            'analysis_date': result.analysis_date,
            'input_sources': result.input_sources,
            'timeframes_seen': result.timeframes_seen,
            'bc_found': result.bc_found,
            'phase': result.phase,
            'micro_action': result.micro_action,
            'boundary_upper_zone': result.boundary_upper_zone,
            'boundary_lower_zone': result.boundary_lower_zone,
            'volume_profile_label': result.volume_profile_label,
            'spring_detected': result.spring_detected,
            'utad_detected': result.utad_detected,
            'counterfactual_summary': result.counterfactual_summary,
            't1_risk_assessment': result.t1_risk_assessment,
            'rr_assessment': result.rr_assessment,
            'decision': result.decision,
            'trigger': result.trigger,
            'invalidation': result.invalidation,
            'target_1': result.target_1,
            'confidence': result.confidence,
            'abandon_reason': result.abandon_reason,
            'conflicts': result.conflicts,
            'consistency_score': result.consistency_score,
            'weekly_context': result.weekly_context,
            'intraday_context': result.intraday_context,
        }
    
    def _bundle_to_dict(self, bundle: ImageEvidenceBundle) -> dict:
        """将 ImageEvidenceBundle 转换为字典"""
        return {
            'manifest': {
                'total_count': bundle.manifest.total_count,
                'usable_count': bundle.manifest.usable_count,
                'scan_time': bundle.manifest.scan_time,
                'files': [
                    {
                        'file_path': f.file_path,
                        'file_name': f.file_name,
                        'symbol': f.symbol,
                        'inferred_timeframe': f.inferred_timeframe,
                        'image_quality': f.image_quality,
                    }
                    for f in bundle.manifest.files
                ],
            },
            'detected_timeframes': bundle.detected_timeframes,
            'overall_image_quality': bundle.overall_image_quality,
            'trust_level': bundle.trust_level,
            'visual_evidence_count': len(bundle.visual_evidence_list),
        }

```

---

## src/wyckoff/rules.py

```python
# -*- coding: utf-8 -*-
"""威科夫规则引擎 - 实现 SPEC_WYCKOFF_RULE_ENGINE"""
from typing import List, Optional
from src.wyckoff.models import BCResult, ChipAnalysis, EffortResult, PhaseResult, PreprocessingResult, RiskAssessment, TradingPlan, WyckoffPhase

class WyckoffRules:
    """威科夫规则引擎 - 核心规则实现"""
    
    @staticmethod
    def detect_bc(preprocessing: PreprocessingResult, phase_result: PhaseResult) -> BCResult:
        """BC (Buying Climax) 检测"""
        if not preprocessing.local_highs:
            return BCResult(found=False, candidate_index=-1, candidate_date="", candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
        for idx, high in enumerate(preprocessing.local_highs):
            if high.get("volume_label") in ["very_high", "climax"] and high.get("price_increase_pct", 0) >= 15.0:
                return BCResult(found=True, candidate_index=idx, candidate_date=high.get("date", ""), candidate_price=high.get("price", 0.0),
                               volume_label=high.get("volume_label", "unknown"), enhancement_signals=["high_volume", "price_increase"])
        return BCResult(found=False, candidate_index=-1, candidate_date="", candidate_price=0.0, volume_label="unknown", enhancement_signals=[])

    @staticmethod
    def determine_phase(preprocessing: PreprocessingResult, bc_result: BCResult, effort_result: EffortResult) -> PhaseResult:
        """确定威科夫阶段"""
        if bc_result.found:
            if preprocessing.trend_direction == "down" and effort_result.net_bias == "accumulation":
                return PhaseResult(phase=WyckoffPhase.ACCUMULATION, boundary_upper_zone="", boundary_lower_zone="", boundary_sources=["bc_found"])
        if preprocessing.trend_direction == "up":
            return PhaseResult(phase=WyckoffPhase.MARKUP, boundary_upper_zone="", boundary_lower_zone="", boundary_sources=["trend_up"])
        if preprocessing.trend_direction == "down":
            return PhaseResult(phase=WyckoffPhase.MARKDOWN, boundary_upper_zone="", boundary_lower_zone="", boundary_sources=["trend_down"])
        return PhaseResult(phase=WyckoffPhase.NO_TRADE_ZONE, boundary_upper_zone="0", boundary_lower_zone="0", boundary_sources=[])

    @staticmethod
    def calculate_risk_reward(current_price: float, stop_loss: float, targets: List[float]) -> RiskAssessment:
        """计算风险收益比"""
        if not targets or stop_loss >= current_price:
            return RiskAssessment(entry_price=current_price, stop_loss=stop_loss, reward_risk_ratio=0.0, risk_level="high")
        reward = max(targets) - current_price
        risk = current_price - stop_loss
        if risk <= 0:
            return RiskAssessment(entry_price=current_price, stop_loss=stop_loss, reward_risk_ratio=0.0, risk_level="high")
        rr_ratio = reward / risk
        risk_level = "low" if rr_ratio >= 3.0 else "medium" if rr_ratio >= 2.0 else "high"
        return RiskAssessment(entry_price=current_price, stop_loss=stop_loss, reward_risk_ratio=rr_ratio, risk_level=risk_level)

    @staticmethod
    def generate_trading_plan(phase: WyckoffPhase, bc_result: BCResult, risk_assessment: RiskAssessment, current_price: float) -> Optional[TradingPlan]:
        """生成交易计划"""
        if phase == WyckoffPhase.ACCUMULATION and bc_result.found:
            if risk_assessment.reward_risk_ratio >= 2.5:
                return TradingPlan(direction="long", trigger_condition="price突破BC高点", invalidation_point=bc_result.candidate_price * 0.98,
                                  first_target=current_price * 1.10, stop_loss=bc_result.candidate_price * 0.97)
        if phase == WyckoffPhase.MARKUP:
            return TradingPlan(direction="long", trigger_condition="价格回落至支撑位", invalidation_point=current_price * 0.95,
                              first_target=current_price * 1.15, stop_loss=current_price * 0.93)
        return None

    @staticmethod
    def analyze_chips(volume_profile: List[dict]) -> ChipAnalysis:
        """筹码分析"""
        if not volume_profile:
            return ChipAnalysis(distribution="unknown", accumulation_zones=[], distribution_zones=[])
        high_vol_zones = [z for z in volume_profile if z.get("volume_label") in ["high", "very_high", "climax"]]
        if high_vol_zones:
            return ChipAnalysis(distribution="accumulation", accumulation_zones=[z.get("price") for z in high_vol_zones], distribution_zones=[])
        return ChipAnalysis(distribution="unknown", accumulation_zones=[], distribution_zones=[])
```

---

## src/wyckoff/state.py

```python
# -*- coding: utf-8 -*-
"""Wyckoff 状态管理器 - 负责分析状态的持久化、连续性追踪和 Spring 冷冻期管理"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self):
        self.spring_freeze_days = 3

    def update_state(self, symbol: str, analysis_result, output_path: str, prev_state = None):
        from src.wyckoff.models import AnalysisState
        state = AnalysisState()
        state.symbol = symbol
        state.asset_type = analysis_result.asset_type
        state.analysis_date = analysis_result.analysis_date
        state.last_phase = analysis_result.phase
        state.last_micro_action = analysis_result.micro_action
        state.last_confidence = analysis_result.confidence
        state.bc_found = analysis_result.bc_found
        state.spring_detected = analysis_result.spring_detected
        state.freeze_until = self._calculate_freeze_until(analysis_result, prev_state)
        state.watch_status = self._determine_watch_status(state)
        if analysis_result.decision == 'long_setup':
            state.trigger_armed = True
            state.trigger_text = analysis_result.trigger
            state.invalid_level = analysis_result.invalidation
            state.target_1 = analysis_result.target_1
        else:
            state.trigger_armed = False
        state.last_decision = analysis_result.decision
        state.abandon_reason = analysis_result.abandon_reason
        self.save_state(state, output_path)
        return state

    @staticmethod
    def _add_trading_days(start_date, n_days):
        current = start_date
        added = 0
        while added < n_days:
            current += timedelta(days=1)
            if current.weekday() < 5:
                added += 1
        return current

    def _calculate_freeze_until(self, analysis_result, prev_state):
        if not analysis_result.spring_detected:
            if prev_state:
                return prev_state.freeze_until
            return None
        try:
            analysis_date = datetime.strptime(analysis_result.analysis_date, '%Y-%m-%d')
        except (ValueError, TypeError):
            analysis_date = datetime.now()
        freeze_until = self._add_trading_days(analysis_date, self.spring_freeze_days)
        return freeze_until.strftime('%Y-%m-%d')

    def _determine_watch_status(self, state):
        if state.freeze_until:
            try:
                freeze_date = datetime.strptime(state.freeze_until, '%Y-%m-%d')
                if datetime.now() <= freeze_date:
                    return "cooling_down"
            except (ValueError, TypeError):
                pass
        if state.trigger_armed:
            return "watching"
        return "none"

    def save_state(self, state, output_path):
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        state_dict = {'symbol': state.symbol, 'asset_type': state.asset_type, 'analysis_date': state.analysis_date,
                     'last_phase': state.last_phase, 'last_micro_action': state.last_micro_action, 'last_confidence': state.last_confidence,
                     'bc_found': state.bc_found, 'spring_detected': state.spring_detected, 'freeze_until': state.freeze_until,
                     'watch_status': state.watch_status, 'trigger_armed': state.trigger_armed, 'trigger_text': state.trigger_text,
                     'invalid_level': state.invalid_level, 'target_1': state.target_1, 'last_decision': state.last_decision,
                     'abandon_reason': state.abandon_reason}
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(state_dict, f, ensure_ascii=False, indent=2)
        logger.info(f"状态已保存到：{output_file}")

    def load_state(self, input_path):
        input_file = Path(input_path)
        if not input_file.exists():
            logger.warning(f"状态文件不存在：{input_path}")
            return None
        with open(input_file, 'r', encoding='utf-8') as f:
            state_dict = json.load(f)
        from src.wyckoff.models import AnalysisState
        return AnalysisState(**state_dict)

    def is_in_freeze_period(self, state):
        if not state.freeze_until:
            return False
        try:
            freeze_date = datetime.strptime(state.freeze_until, '%Y-%m-%d')
            return datetime.now() <= freeze_date
        except (ValueError, TypeError):
            return False
```

---

*Total files: 48 Python source files across 8 modules*
*Generated for code review on 2026-05-07*
