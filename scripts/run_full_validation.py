#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("full_validation")

STOCK_CSV = PROJECT_ROOT / "data" / "stock_list.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "full_validation"
DB_PATH = str(OUTPUT_DIR / "validation.db")
REPORT_PATH = OUTPUT_DIR / "analysis_report.json"
N_DATES = 20
N_WORKERS = min(16, os.cpu_count() or 8)
WYCKOFF_TIMEOUT = 120
SEED = 42
RANDOM = random.Random(SEED)


def load_stock_list(limit: int = 0) -> List[Dict]:
    stocks = []
    with open(STOCK_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = row.get("code", "").strip()
            market = str(row.get("market", "")).strip().upper()
            name = row.get("name", "").replace("\x00", "").strip()
            pre_close = float(row.get("pre_close", 0))
            if not (code.isdigit() and len(code) == 6 and market in ("SH", "SZ")):
                continue
            if pre_close <= 1:
                continue
            symbol = f"{code}.{market}"
            stocks.append({"symbol": symbol, "code": code, "market": market, "name": name})
    if limit > 0 and len(stocks) > limit:
        RANDOM.shuffle(stocks)
        stocks = stocks[:limit]
    return stocks


def load_csi300() -> Optional[pd.DataFrame]:
    from scripts.utils.tdx_config import CSI300_PATH
    from src.data.tdx_loader import load_tdx_data
    df = load_tdx_data(str(CSI300_PATH))
    if df is not None and not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    return None


def select_dates(csi300: pd.DataFrame, n: int = N_DATES) -> List[str]:
    d = csi300[(csi300["date"] >= "2012-01-01") & (csi300["date"] <= "2025-12-31")]
    dates = d["date"].dt.strftime("%Y-%m-%d").tolist()
    RANDOM.shuffle(dates)
    return sorted(dates[:n])


def get_regime(csi300: pd.DataFrame, d: str) -> str:
    h = csi300[csi300["date"] <= pd.Timestamp(d)]
    if len(h) < 120:
        return "unknown"
    c = float(h.iloc[-1]["close"])
    m120 = float(h.tail(120)["close"].mean())
    m60 = float(h.tail(60)["close"].mean())
    if c > m120 * 1.02 and m60 > m120:
        return "bull"
    if c < m120 * 0.98:
        return "bear"
    return "range"


def _worker_process_stock_all_dates(args: Tuple) -> List[Dict]:
    """
    股票级并行: 一个worker读取1只股票的全部数据,
    处理所有日期后一次性返回.
    """
    symbol, name, dates, wyckoff_cfg = args
    results: List[Dict] = []
    try:
        from scripts.utils.tdx_config import TDX_BASE
        from src.data.tdx_reader import TDXReader
        reader = TDXReader(str(TDX_BASE))
        df = reader.daily(symbol)
        if df is None or df.empty or len(df) < 200:
            return results
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    except Exception:
        return results

    try:
        from src.wyckoff.engine import WyckoffEngine
        eng = WyckoffEngine(
            lookback_days=wyckoff_cfg.get("lookback_days", 400),
            weekly_lookback=wyckoff_cfg.get("weekly_lookback", 120),
            monthly_lookback=wyckoff_cfg.get("monthly_lookback", 40),
        )
    except Exception:
        return results

    from src.engine.daily_signal_engine import (
        generate_ma_signals,
        generate_reversal_signals,
        score_maatr,
        score_wyckoff,
    )
    ma_cfg = {"fast_period": 5, "slow_period": 20, "atr_period": 20}
    rev_cfg = {"lookback_days": 5, "threshold_pct": 5.0,
               "stop_loss_pct": 4.0, "take_profit_pct": 4.0}

    for as_of_date in dates:
        try:
            av = df[df["date"] <= pd.Timestamp(as_of_date)]
            if len(av) < 100:
                continue
            t0 = time.time()

            for sig in generate_ma_signals(av, symbol, name, as_of_date, ma_cfg):
                sig["as_of_date"] = as_of_date
                results.append(sig)
            for sig in generate_reversal_signals(av, symbol, name, as_of_date, rev_cfg):
                sig["as_of_date"] = as_of_date
                results.append(sig)

            if len(av) < 150:
                continue

            rpt = eng.analyze(av, symbol=symbol, period="日线", multi_timeframe=True)
            sig_type = rpt.signal.signal_type
            direction = rpt.trading_plan.direction
            if sig_type == "no_signal" or direction == "空仓观望":
                continue
            rr = rpt.risk_reward
            entry_p = float(rr.entry_price) if (rr and rr.entry_price and rr.entry_price > 0) else None
            sl = float(rr.stop_loss) if (rr and rr.stop_loss and rr.stop_loss > 0) else None
            tp = float(rr.first_target) if (rr and rr.first_target and rr.first_target > 0) else None
            phase = rpt.structure.phase.value
            conf = rpt.signal.confidence.value if rpt.signal.confidence else "C"
            wy_s1 = score_wyckoff(phase)
            wy_s2 = score_maatr(av, as_of_date)
            score = 0.40 * wy_s1 + 0.40 * wy_s2 + 0.20
            if score >= wyckoff_cfg.get("score_threshold", 0.45):
                results.append({
                    "as_of_date": as_of_date, "symbol": symbol, "name": name,
                    "action": "buy", "entry_price": entry_p, "stop_loss": sl,
                    "take_profit": tp, "confidence": conf, "strategy": "wyckoff",
                    "phase": phase, "regime": "", "score": round(score, 3),
                    "direction": direction,
                })
        except Exception:
            pass
    return results


class FullValidator:
    def __init__(self, stocks: List[Dict], dates: List[str], csi300: pd.DataFrame,
                 db_path: str = DB_PATH, n_workers: int = N_WORKERS):
        self.stocks = stocks
        self.dates = dates
        self.csi300 = csi300
        self.n_workers = n_workers
        from src.storage.database import Database
        self.db = Database(db_path)
        self.wyckoff_cfg = {"lookback_days": 400, "weekly_lookback": 120,
                            "monthly_lookback": 40, "score_threshold": 0.45}

    def is_date_processed(self, d: str) -> bool:
        signals = self.db.get_signals(date=d)
        return len(signals) > 0

    def generate_regime_map(self) -> Dict[str, str]:
        return {d: get_regime(self.csi300, d) for d in self.dates}

    def run_all(self) -> List[Dict]:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        regime_map = self.generate_regime_map()
        logger.info(f"Processing {len(self.stocks)} stocks across {len(self.dates)} dates "
                    f"with {self.n_workers} workers")

        total = len(self.stocks)
        args_list = [
            (s["symbol"], s["name"], self.dates, self.wyckoff_cfg)
            for s in self.stocks
        ]

        all_signals: List[Dict] = []
        t_start = time.time()

        with ProcessPoolExecutor(max_workers=self.n_workers) as ex:
            # 流式提交: submit N_WORKERS*2 个, 每完成1个就提交下一个
            futures = {}
            it = iter(args_list)
            initial_batch = min(self.n_workers * 2, total)
            for _ in range(initial_batch):
                try:
                    a = next(it)
                    futures[ex.submit(_worker_process_stock_all_dates, a)] = a[0]
                except StopIteration:
                    break

            completed = 0
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for f in done:
                    sym = futures.pop(f)
                    try:
                        sigs = f.result(timeout=WYCKOFF_TIMEOUT)
                        all_signals.extend(sigs)
                    except Exception as e:
                        logger.warning(f"Worker failed for {sym}: {e}")
                    completed += 1
                    if completed % 500 == 0:
                        elapsed = time.time() - t_start
                        rate = completed / elapsed
                        logger.info(f"  {completed}/{total} stocks, "
                                    f"{len(all_signals)} signals, "
                                    f"{rate:.0f} stocks/min")
                    try:
                        a = next(it)
                        futures[ex.submit(_worker_process_stock_all_dates, a)] = a[0]
                    except StopIteration:
                        pass

        # 写入DB
        for sig in all_signals:
            d = sig["as_of_date"]
            sig["regime"] = regime_map.get(d, "")
            self.db.insert_signal(
                d, sig["symbol"], sig["strategy"], sig["action"],
                entry_price=sig.get("entry_price"),
                stop_loss=sig.get("stop_loss"),
                take_profit=sig.get("take_profit"),
                confidence=sig.get("confidence"),
                regime=sig["regime"], score=sig.get("score"),
                details=f"phase={sig.get('phase','')} dir={sig.get('direction','')}",
            )

        elapsed = time.time() - t_start
        logger.info(f"Completed {total} stocks in {elapsed:.0f}s "
                    f"({total/elapsed:.0f} stocks/s, {len(all_signals)} signals)")

        date_results = []
        for d in self.dates:
            sigs = self.db.get_signals(date=d)
            date_results.append({
                "date": d, "regime": regime_map.get(d, ""),
                "signals": len(sigs), "skipped": False,
            })
        return date_results

    def analyze(self, results: List[Dict]) -> Dict:
        all_sigs = []
        for d in self.dates:
            sigs = self.db.get_signals(date=d)
            if not sigs.empty:
                all_sigs.append(sigs)
        if not all_sigs:
            return {"error": "No signals generated"}
        df = pd.concat(all_sigs, ignore_index=True)
        by_date = df.groupby("signal_date").agg(
            total=("id", "count"),
            wyckoff=("strategy", lambda x: (x == "wyckoff").sum()),
            ma_cross=("strategy", lambda x: (x == "ma_cross").sum()),
            reversal=("strategy", lambda x: (x == "reversal").sum()),
        ).reset_index()
        by_date.columns = ["date", "total", "wyckoff", "ma_cross", "reversal"]
        by_strategy = df.groupby("strategy").agg(
            count=("id", "count"),
            mean_score=("score", "mean"),
            max_score=("score", "max"),
        ).reset_index().to_dict("records")
        regime_dist = df.groupby("regime").agg(
            count=("id", "count"),
        ).reset_index().to_dict("records")
        top_stocks = df.groupby("symbol").agg(
            count=("id", "count"),
            mean_score=("score", "mean"),
            strategies=("strategy", lambda x: list(set(x))),
        ).reset_index().sort_values("count", ascending=False).head(30)
        signal_scores = df["score"].describe().to_dict()
        return {
            "config": {
                "n_stocks": len(self.stocks),
                "n_dates": len(self.dates),
                "date_range": f"{min(self.dates)} ~ {max(self.dates)}",
                "n_workers": self.n_workers,
            },
            "overall": {
                "total_signals": len(df),
                "uniq_stocks": df["symbol"].nunique(),
                "signals_per_date": round(len(df) / len(self.dates), 1),
                "signals_per_stock": round(len(df) / len(self.stocks), 3),
            },
            "by_date": by_date.to_dict("records"),
            "by_strategy": by_strategy,
            "by_regime": regime_dist,
            "score_stats": {
                "min": float(signal_scores.get("min", 0)),
                "max": float(signal_scores.get("max", 0)),
                "mean": float(signal_scores.get("mean", 0)),
                "std": float(signal_scores.get("std", 0)),
                "q25": float(signal_scores.get("25%", 0)),
                "q50": float(signal_scores.get("50%", 0)),
                "q75": float(signal_scores.get("75%", 0)),
            },
            "top_stocks": top_stocks.to_dict("records"),
            "date_results": [
                {"date": r["date"], "regime": r["regime"],
                 "signals": r["signals"], "skipped": r.get("skipped", False)}
                for r in results
            ],
        }

    def print_report(self, analysis: Dict):
        print(f"\n{'='*70}")
        print("  全量验证分析报告 (v2 - 股票级并行)")
        print(f"{'='*70}")
        cfg = analysis.get("config", {})
        ov = analysis.get("overall", {})
        print(f"\n配置: {cfg.get('n_stocks')} 股票 x {cfg.get('n_dates')} 日期")
        print(f"    范围: {cfg.get('date_range')}")
        print(f"    并行: {cfg.get('n_workers')} workers (股票级)")
        print(f"\n总体: {ov.get('total_signals')} 总信号量")
        print(f"     {ov.get('uniq_stocks')} 只股票产生过信号")
        print(f"     {ov.get('signals_per_date')} 信号/日 平均")
        print("\n策略分布:")
        for s in analysis.get("by_strategy", []):
            print(f"  {s['strategy']:12s}: {s['count']:6d}  "
                  f"均分={s['mean_score']:.3f}  最高={s['max_score']:.3f}")
        print("\n市场状态分布:")
        for r in analysis.get("by_regime", []):
            print(f"  {r['regime']:12s}: {r['count']:6d}")
        sc = analysis.get("score_stats", {})
        print(f"\n得分统计: 最小={sc.get('min'):.3f}  Q25={sc.get('q25'):.3f}  "
              f"中位={sc.get('q50'):.3f}  均值={sc.get('mean'):.3f}  "
              f"Q75={sc.get('q75'):.3f}  最大={sc.get('max'):.3f}")
        print("\n每日信号:")
        for r in analysis.get("date_results", []):
            print(f"  {r['date']} [{r['regime']:8s}]: {r['signals']:5d} signals" +
                  (" (cached)" if r.get("skipped") else ""))
        print("\n高频股票 Top 10:")
        for s in analysis.get("top_stocks", [])[:10]:
            print(f"  {s['symbol']:12s}: {s['count']:3d}次  "
                  f"均分={s['mean_score']:.3f}  "
                  f"策略={','.join(s['strategies'])}")
        print(f"\n{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="Full validation of signal engine")
    parser.add_argument("--limit-stocks", type=int, default=0)
    parser.add_argument("--limit-dates", type=int, default=N_DATES)
    parser.add_argument("--workers", type=int, default=N_WORKERS)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    if args.quick:
        args.limit_stocks = args.limit_stocks or 500
        args.limit_dates = min(args.limit_dates, 5)

    if args.report_only:
        from src.storage.database import Database
        db = Database(DB_PATH)
        sig_dates = list(db.get_signals()["signal_date"].unique())
        if not sig_dates:
            logger.error("No signals found in DB")
            return
        all_sigs = []
        for d in sig_dates:
            sigs = db.get_signals(date=d)
            if not sigs.empty:
                all_sigs.append(sigs)
        if all_sigs:
            df = pd.concat(all_sigs, ignore_index=True)
            logger.info(f"DB has {len(df)} signals across {len(sig_dates)} dates")
            val = FullValidator([], sig_dates, None, DB_PATH, args.workers)
            results = [{"date": d, "regime": "", "signals": len(db.get_signals(date=d))}
                       for d in sig_dates]
            analysis = val.analyze(results)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(REPORT_PATH, "w") as f:
                json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
            val.print_report(analysis)
        return

    logger.info(f"Workers: {args.workers} (CPU cores: {os.cpu_count()})")
    logger.info("Loading stock list...")
    stocks = load_stock_list(limit=args.limit_stocks)
    logger.info(f"Loaded {len(stocks)} stocks")

    logger.info("Loading CSI300...")
    csi300 = load_csi300()
    if csi300 is None:
        logger.error("Failed to load CSI300")
        sys.exit(1)
    logger.info(f"CSI300: {len(csi300)} rows, {csi300['date'].min().date()} ~ {csi300['date'].max().date()}")

    dates = select_dates(csi300, args.limit_dates)
    logger.info(f"Selected {len(dates)} dates: {dates[0]} ~ {dates[-1]}")

    val = FullValidator(stocks, dates, csi300, DB_PATH, args.workers)
    date_results = val.run_all()
    analysis = val.analyze(date_results)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    val.print_report(analysis)
    logger.info(f"Report saved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
