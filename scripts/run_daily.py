#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.tdx_loader import load_tdx_data
from src.data.incremental_loader import IncrementalLoader
from src.storage.database import Database
from src.engine.daily_signal_engine import DailySignalEngine
from src.execution.simulator import SimulatedBroker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("daily_run")

DEFAULT_CONFIG = PROJECT_ROOT / "config" / "trading.yaml"
CSI300_PATH = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day"


def load_config(path: str) -> Dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_csi300() -> Optional[pd.DataFrame]:
    df = load_tdx_data(CSI300_PATH)
    if df is not None and not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    return None


def load_stock_list() -> Dict[str, str]:
    sh_dir = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/")
    sz_dir = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/")
    symbols: Dict[str, str] = {}
    for dpath in [sh_dir, sz_dir]:
        if not dpath.exists():
            continue
        for f in dpath.iterdir():
            if f.suffix != ".day":
                continue
            name = f.stem
            if name.startswith("sh"):
                symbol = f"{name[2:]}.SH"
            elif name.startswith("sz"):
                symbol = f"{name[2:]}.SZ"
            else:
                continue
            symbols[symbol] = ""
    return symbols


def cmd_update(args):
    config = load_config(str(args.config))
    db = Database(config["data"]["db_path"])
    loader = IncrementalLoader(db)
    logger.info("Running TDX data update...")
    result = loader.run_daily_update()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    stats = db.get_stats()
    print(f"\nDB stats: {stats}")


def cmd_signals(args):
    config = load_config(str(args.config))
    db = Database(config["data"]["db_path"])
    loader = IncrementalLoader(db)
    run_date = args.date or str(date.today())

    csi300 = load_csi300()
    if csi300 is not None:
        last_tdx_date = str(csi300["date"].max().date())
        if last_tdx_date < run_date:
            run_date = last_tdx_date
            logger.info(f"Using latest TDX date: {run_date}")

    logger.info(f"Loading stock data for {run_date}...")
    stock_list = load_stock_list()
    logger.info(f"Found {len(stock_list)} stocks in TDX")

    stock_data: Dict[str, pd.DataFrame] = {}
    name_map: Dict[str, str] = {}

    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    if csv_path.exists():
        import csv
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                code = str(row.get("code", "")).strip()
                market = str(row.get("market", "")).strip().upper()
                name = str(row.get("name", "")).replace("\x00", "").strip()
                if code and len(code) == 6:
                    sym = f"{code}.{market}"
                    name_map[sym] = name

    limit = args.limit or 200
    symbols = sorted(stock_list.keys())[:limit] if limit > 0 else sorted(stock_list.keys())

    for symbol in symbols:
        df = loader.load_latest_data(symbol, lookback=500)
        if df is not None and len(df) >= 100:
            stock_data[symbol] = df

    logger.info(f"Loaded {len(stock_data)} stocks with sufficient data")

    engine = DailySignalEngine(config)
    all_signals = engine.generate_batch(
        stock_data, name_map, run_date, csi300,
        n_workers=args.workers,
    )
    merged = engine.merge_signals(all_signals)

    for _, sig in merged.iterrows():
        db.insert_signal(
            run_date, sig["symbol"], sig["strategy"], sig["action"],
            entry_price=sig.get("entry_price"),
            stop_loss=sig.get("stop_loss"),
            take_profit=sig.get("take_profit"),
            confidence=sig.get("confidence"),
            regime=sig.get("regime", ""),
            score=sig.get("score"),
            details=f"phase={sig.get('phase','')} dir={sig.get('direction','')}",
        )

    output = {
        "date": run_date,
        "total_signals": len(merged),
        "by_strategy": merged["strategy"].value_counts().to_dict() if not merged.empty else {},
        "signals": merged.to_dict("records") if not merged.empty else [],
    }
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n{'='*60}")
    print(f"Total signals: {len(merged)}")
    if not merged.empty:
        print(f"By strategy: {merged['strategy'].value_counts().to_dict()}")
        print(f"Top signals:")
        for _, r in merged.head(10).iterrows():
            print(f"  {r['symbol']:12s} {r['strategy']:12s} "
                  f"score={r['score']:.3f} entry={r.get('entry_price',''):>8}")
    print(f"{'='*60}")


def cmd_execute(args):
    config = load_config(str(args.config))
    db = Database(config["data"]["db_path"])
    run_date = args.date or str(date.today())

    signals = db.get_signals(date=run_date, action="buy")
    broker = SimulatedBroker(db, initial_capital=config["execution"]["initial_capital"])

    if args.dry_run:
        print(f"DRY RUN for {run_date}:")
        print(f"  Buy signals: {len(signals)}")
        for _, s in signals.head(20).iterrows():
            print(f"  BUY  {s['symbol']:12s} {s['strategy']:12s} "
                  f"entry={s['entry_price']:.2f} score={s['score']:.3f}")
        return

    logger.info(f"Executing trades for {run_date}...")
    result = broker.run_daily(run_date, signals)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"\n  Buys: {len(result['buys'])}")
    print(f"  Sells (stops): {len(result['sells'])}")
    print(f"  Cash: {result['snapshot']['cash']:.2f}")
    print(f"  Total: {result['snapshot']['total_value']:.2f}")
    print(f"  Positions: {result['snapshot']['n_positions']}")


def cmd_status(args):
    db = Database()
    stats = db.get_stats()
    print("=== Database Status ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()
    port = db.get_portfolio(limit=5)
    if not port.empty:
        print("=== Recent Portfolio ===")
        print(port.to_string(index=False))
    print()
    trades = db.get_trades(limit=10)
    if not trades.empty:
        print("=== Recent Trades ===")
        print(trades.to_string(index=False))
    print()
    open_pos = db.get_open_positions()
    if open_pos:
        print("=== Open Positions ===")
        for p in open_pos:
            print(f"  {p['symbol']:12s} entry={p['entry_price']:.2f} "
                  f"qty={p['quantity']} sl={p['stop_loss']} tp={p['take_profit']}")


def cmd_run(args):
    config = load_config(str(args.config))
    db = Database(config["data"]["db_path"])
    loader = IncrementalLoader(db)
    run_date = args.date or str(date.today())

    csi300 = load_csi300()
    if csi300 is not None:
        last_tdx_date = str(csi300["date"].max().date())
        if last_tdx_date < run_date:
            run_date = last_tdx_date

    logger.info(f"=== Daily Run: {run_date} ===")
    logger.info("Step 1/3: Updating data...")
    loader.run_daily_update()
    logger.info("Step 2/3: Generating signals...")
    stock_list = load_stock_list()
    stock_data: Dict[str, pd.DataFrame] = {}
    name_map: Dict[str, str] = {}
    limit = args.limit or 200
    symbols = sorted(stock_list.keys())[:limit] if limit > 0 else sorted(stock_list.keys())
    for symbol in symbols:
        df = loader.load_latest_data(symbol, lookback=500)
        if df is not None and len(df) >= 100:
            stock_data[symbol] = df
    engine = DailySignalEngine(config)
    all_signals = engine.generate_batch(stock_data, name_map, run_date, csi300, n_workers=args.workers)
    merged = engine.merge_signals(all_signals)
    for _, sig in merged.iterrows():
        db.insert_signal(run_date, sig["symbol"], sig["strategy"], sig["action"],
                         entry_price=sig.get("entry_price"), stop_loss=sig.get("stop_loss"),
                         take_profit=sig.get("take_profit"), confidence=sig.get("confidence"),
                         regime=sig.get("regime", ""), score=sig.get("score"))
    logger.info(f"Signals generated: {len(merged)}")
    logger.info("Step 3/3: Executing trades...")
    broker = SimulatedBroker(db, initial_capital=config["execution"]["initial_capital"])
    if not args.dry_run:
        result = broker.run_daily(run_date, merged)
        logger.info(f"Buys: {len(result['buys'])}, Sells: {len(result['sells'])}")
    else:
        logger.info("DRY RUN - no trades executed")
    logger.info("=== Done ===")


def main():
    parser = argparse.ArgumentParser(description="LPPL Daily Trading System")
    sub = parser.add_subparsers(dest="command")

    for name in ("update", "signals", "execute", "status", "run"):
        p = sub.add_parser(name)
        p.add_argument("--config", default=str(DEFAULT_CONFIG), help="Config file path")
        p.add_argument("--date", help="Run date (YYYY-MM-DD)")
        p.add_argument("--limit", type=int, default=200, help="Max stocks to process")
        p.add_argument("--workers", type=int, default=4, help="Parallel workers")
        p.add_argument("--dry-run", action="store_true", help="Preview only, no trades")
        p.set_defaults(command=name)

    sub.choices["status"].set_defaults(limit=0)
    sub.choices["update"].set_defaults(limit=0)

    args = parser.parse_args()

    commands = {
        "update": cmd_update,
        "signals": cmd_signals,
        "execute": cmd_execute,
        "status": cmd_status,
        "run": cmd_run,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
