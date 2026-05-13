from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


class Database:
    def __init__(self, db_path: str = "data/trading.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS data_status (
                    symbol TEXT PRIMARY KEY,
                    code TEXT,
                    market TEXT,
                    name TEXT,
                    last_date DATE,
                    file_mtime TIMESTAMP,
                    row_count INT DEFAULT 0,
                    data_quality TEXT DEFAULT 'ok',
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS daily_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_date DATE NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    confidence TEXT,
                    regime TEXT,
                    score REAL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(signal_date, symbol, strategy)
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    entry_date DATE NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    current_price REAL,
                    strategy TEXT,
                    stop_loss REAL,
                    take_profit REAL,
                    entry_reason TEXT,
                    status TEXT DEFAULT 'open',
                    exited_date DATE,
                    exit_price REAL,
                    exit_reason TEXT,
                    pnl REAL,
                    pnl_pct REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, entry_date)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    entry_date DATE NOT NULL,
                    exit_date DATE,
                    direction TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    strategy TEXT,
                    exit_reason TEXT,
                    regime TEXT,
                    score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    date DATE PRIMARY KEY,
                    cash REAL DEFAULT 0,
                    market_value REAL DEFAULT 0,
                    total_value REAL DEFAULT 0,
                    daily_pnl REAL DEFAULT 0,
                    daily_pnl_pct REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    total_pnl_pct REAL DEFAULT 0,
                    n_positions INTEGER DEFAULT 0,
                    n_signals INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_signals_date ON daily_signals(signal_date);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol ON daily_signals(symbol);
                CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
                CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_date);
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            """)

    def upsert_data_status(
        self, symbol: str, code: str = "", market: str = "", name: str = "",
        last_date: Optional[str] = None, file_mtime: Optional[str] = None,
        row_count: int = 0, data_quality: str = "ok",
    ):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO data_status(symbol, code, market, name, last_date, file_mtime, row_count, data_quality, last_checked)
                VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(symbol) DO UPDATE SET
                    code=excluded.code, market=excluded.market, name=excluded.name,
                    last_date=excluded.last_date, file_mtime=excluded.file_mtime,
                    row_count=excluded.row_count, data_quality=excluded.data_quality,
                    last_checked=CURRENT_TIMESTAMP
            """, (symbol, code, market, name, last_date, file_mtime, row_count, data_quality))

    def get_data_status(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql("SELECT * FROM data_status ORDER BY symbol", conn)

    def get_stale_symbols(self, max_age_days: int = 5) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT symbol FROM data_status
                WHERE last_date IS NULL
                   OR julianday('now') - julianday(last_date) > ?
                ORDER BY symbol
            """, (max_age_days,)).fetchall()
            return [r["symbol"] for r in rows]

    def insert_signal(self, signal_date: str, symbol: str, strategy: str,
                      action: str, entry_price: Optional[float] = None,
                      stop_loss: Optional[float] = None,
                      take_profit: Optional[float] = None,
                      confidence: Optional[str] = None,
                      regime: Optional[str] = None,
                      score: Optional[float] = None,
                      details: Optional[str] = None):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO daily_signals(signal_date, symbol, strategy, action,
                    entry_price, stop_loss, take_profit, confidence, regime, score, details)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(signal_date, symbol, strategy) DO UPDATE SET
                    action=excluded.action, entry_price=excluded.entry_price,
                    stop_loss=excluded.stop_loss, take_profit=excluded.take_profit,
                    confidence=excluded.confidence, regime=excluded.regime,
                    score=excluded.score, details=excluded.details
            """, (signal_date, symbol, strategy, action, entry_price,
                  stop_loss, take_profit, confidence, regime, score, details))

    def get_signals(self, date: Optional[str] = None,
                    strategy: Optional[str] = None,
                    action: Optional[str] = None) -> pd.DataFrame:
        clauses = []
        params: list = []
        if date:
            clauses.append("signal_date = ?")
            params.append(date)
        if strategy:
            clauses.append("strategy = ?")
            params.append(strategy)
        if action:
            clauses.append("action = ?")
            params.append(action)
        where = " AND ".join(clauses) if clauses else "1=1"
        with self._connect() as conn:
            return pd.read_sql(f"SELECT * FROM daily_signals WHERE {where} ORDER BY signal_date, symbol", conn, params=params)

    def open_position(self, symbol: str, entry_date: str, entry_price: float,
                      quantity: int, strategy: str = "", stop_loss: Optional[float] = None,
                      take_profit: Optional[float] = None,
                      entry_reason: Optional[str] = None) -> bool:
        with self._connect() as conn:
            try:
                conn.execute("""
                    INSERT INTO positions(symbol, entry_date, entry_price, quantity,
                        current_price, strategy, stop_loss, take_profit, entry_reason, status)
                    VALUES(?,?,?,?,?,?,?,?,?,'open')
                """, (symbol, entry_date, entry_price, quantity, entry_price,
                      strategy, stop_loss, take_profit, entry_reason))
                return True
            except sqlite3.IntegrityError:
                return False

    def close_position(self, symbol: str, exit_date: str, exit_price: float,
                       exit_reason: str = ""):
        with self._connect() as conn:
            pos = conn.execute("""
                SELECT id, entry_price, quantity FROM positions
                WHERE symbol = ? AND status = 'open' ORDER BY entry_date LIMIT 1
            """, (symbol,)).fetchone()
            if pos is None:
                return
            pid, entry_price, qty = pos["id"], pos["entry_price"], pos["quantity"]
            pnl = (exit_price - entry_price) * qty
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            conn.execute("""
                UPDATE positions SET status='closed', exited_date=?, exit_price=?,
                    exit_reason=?, pnl=?, pnl_pct=?, current_price=?
                WHERE id=?
            """, (exit_date, exit_price, exit_reason, pnl, pnl_pct, exit_price, pid))

    def get_open_positions(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM positions WHERE status='open' ORDER BY entry_date
            """).fetchall()
            return [dict(r) for r in rows]

    def get_all_positions(self) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql("SELECT * FROM positions ORDER BY entry_date", conn)

    def record_trade(self, symbol: str, entry_date: str, exit_date: Optional[str],
                     direction: str, quantity: int, entry_price: float,
                     exit_price: Optional[float] = None,
                     pnl: Optional[float] = None,
                     pnl_pct: Optional[float] = None,
                     strategy: str = "", exit_reason: str = "",
                     regime: Optional[str] = None,
                     score: Optional[float] = None):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO trades(symbol, entry_date, exit_date, direction,
                    quantity, entry_price, exit_price, pnl, pnl_pct,
                    strategy, exit_reason, regime, score)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (symbol, entry_date, exit_date, direction, quantity,
                  entry_price, exit_price, pnl, pnl_pct,
                  strategy, exit_reason, regime, score))

    def get_trades(self, limit: int = 100) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql(
                f"SELECT * FROM trades ORDER BY entry_date DESC LIMIT {limit}", conn)

    def snapshot_portfolio(self, date: str, cash: float, market_value: float,
                           total_value: float, daily_pnl: float = 0,
                           daily_pnl_pct: float = 0,
                           n_positions: int = 0, n_signals: int = 0):
        with self._connect() as conn:
            prev = conn.execute(
                "SELECT total_value FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
            ).fetchone()
            total_pnl = total_value - (prev["total_value"] if prev else total_value)
            prev_total = prev["total_value"] if prev else total_value
            total_pnl_pct_val = (total_value / prev_total - 1) * 100 if prev_total > 0 else 0
            conn.execute("""
                INSERT INTO portfolio_snapshots(date, cash, market_value, total_value,
                    daily_pnl, daily_pnl_pct, total_pnl, total_pnl_pct,
                    n_positions, n_signals)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(date) DO UPDATE SET
                    cash=excluded.cash, market_value=excluded.market_value,
                    total_value=excluded.total_value, daily_pnl=excluded.daily_pnl,
                    daily_pnl_pct=excluded.daily_pnl_pct, total_pnl=excluded.total_pnl,
                    total_pnl_pct=excluded.total_pnl_pct,
                    n_positions=excluded.n_positions, n_signals=excluded.n_signals
            """, (date, cash, market_value, total_value,
                  daily_pnl, daily_pnl_pct, total_pnl, total_pnl_pct_val,
                  n_positions, n_signals))

    def get_portfolio(self, limit: int = 30) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql(
                f"SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT {limit}", conn)

    def get_stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            n_stocks = conn.execute("SELECT COUNT(*) FROM data_status").fetchone()[0]
            n_signals = conn.execute("SELECT COUNT(*) FROM daily_signals").fetchone()[0]
            n_open = conn.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
            n_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            n_snapshots = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
            return {
                "stocks": n_stocks, "signals": n_signals,
                "open_positions": n_open, "trades": n_trades,
                "snapshots": n_snapshots,
            }
