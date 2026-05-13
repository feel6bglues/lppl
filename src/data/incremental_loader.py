from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.data.tdx_loader import load_tdx_data
from src.storage.database import Database

logger = logging.getLogger(__name__)

SH_DIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/"
SZ_DIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/"


def _code_from_filename(fname: str) -> Tuple[Optional[str], Optional[str]]:
    name = fname.lower()
    if name.startswith("sh") and name.endswith(".day"):
        return name[2:-4], "SH"
    if name.startswith("sz") and name.endswith(".day"):
        return name[2:-4], "SZ"
    return None, None


class IncrementalLoader:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.sh_dir = Path(SH_DIR)
        self.sz_dir = Path(SZ_DIR)

    def scan_tdx_files(self) -> List[Dict]:
        found: List[Dict] = []
        for dpath, market in [(self.sh_dir, "SH"), (self.sz_dir, "SZ")]:
            if not dpath.exists():
                logger.warning(f"TDX dir not found: {dpath}")
                continue
            for f in dpath.iterdir():
                if f.suffix != ".day":
                    continue
                code, mkt = _code_from_filename(f.name)
                if code is None:
                    continue
                mtime = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                symbol = f"{code}.{mkt}"
                found.append({
                    "symbol": symbol, "code": code, "market": mkt,
                    "filepath": str(f), "mtime": mtime, "fname": f.name,
                })
        return found

    def find_new_files(self, files: List[Dict]) -> List[Dict]:
        status = self.db.get_data_status()
        stale: List[Dict] = []
        for f in files:
            if status.empty:
                stale.append(f)
                continue
            row = status[status["symbol"] == f["symbol"]]
            if row.empty:
                stale.append(f)
                continue
            last_mtime = row.iloc[0].get("file_mtime")
            if last_mtime and str(last_mtime) >= f["mtime"]:
                continue
            stale.append(f)
        return stale

    def load_file(self, filepath: str, max_records: Optional[int] = None) -> Optional[pd.DataFrame]:
        return load_tdx_data(filepath, max_records=max_records)

    def update_stock(self, symbol: str, code: str, market: str,
                     filepath: str, mtime: str, name: str = "") -> Dict:
        df = self.load_file(filepath)
        if df is None or df.empty:
            self.db.upsert_data_status(symbol, code, market, name,
                                       last_date=None, file_mtime=mtime,
                                       row_count=0, data_quality="empty")
            return {"symbol": symbol, "status": "empty", "rows": 0}
        last_date = str(df["date"].max().date())
        self.db.upsert_data_status(symbol, code, market, name,
                                   last_date=last_date, file_mtime=mtime,
                                   row_count=len(df), data_quality="ok")
        return {"symbol": symbol, "status": "updated", "rows": len(df), "last_date": last_date}

    def run_daily_update(self, name_map: Optional[Dict[str, str]] = None) -> Dict:
        logger.info("Scanning TDX files...")
        all_files = self.scan_tdx_files()
        logger.info(f"Found {len(all_files)} .day files")
        to_load = self.find_new_files(all_files)
        logger.info(f"Files needing update: {len(to_load)}")
        results: List[Dict] = []
        for f in to_load:
            nm = name_map.get(f["symbol"], "") if name_map else ""
            try:
                r = self.update_stock(
                    f["symbol"], f["code"], f["market"],
                    f["filepath"], f["mtime"], name=nm,
                )
                results.append(r)
            except Exception as e:
                logger.error(f"Failed to load {f['symbol']}: {e}")
                results.append({"symbol": f["symbol"], "status": "error", "error": str(e)})
        updated = [r for r in results if r.get("status") == "updated"]
        empty = [r for r in results if r.get("status") == "empty"]
        errors = [r for r in results if r.get("status") == "error"]
        return {
            "total_scanned": len(all_files),
            "loaded": len(to_load),
            "updated": len(updated),
            "empty": len(empty),
            "errors": len(errors),
            "skipped": len(all_files) - len(to_load),
            "details": results,
        }

    def load_latest_data(self, symbol: str, lookback: int = 400) -> Optional[pd.DataFrame]:
        status = self.db.get_data_status()
        row = status[status["symbol"] == symbol]
        if row.empty:
            logger.warning(f"No data status for {symbol}, scanning...")
            all_files = self.scan_tdx_files()
            match = [f for f in all_files if f["symbol"] == symbol]
            if not match:
                return None
            f = match[0]
            df = self.load_file(f["filepath"])
            if df is None:
                return None
            self.db.upsert_data_status(symbol, f["code"], f["market"], "",
                                       last_date=str(df["date"].max().date()),
                                       file_mtime=f["mtime"], row_count=len(df))
        else:
            code = row.iloc[0].get("code", "")
            market = row.iloc[0].get("market", "")
            fpath = f"/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/{market.lower()}/lday/{market.lower()}{code}.day"
            if not os.path.exists(fpath):
                return None
            df = self.load_file(fpath)
            if df is None:
                return None
        return df.tail(lookback).reset_index(drop=True) if len(df) > lookback else df
