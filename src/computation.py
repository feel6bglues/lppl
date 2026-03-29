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
