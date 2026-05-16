from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.incremental_loader import IncrementalLoader
from src.storage.database import Database

logger = logging.getLogger(__name__)


class SimulatedBroker:
    def __init__(self, db: Optional[Database] = None,
                 initial_capital: float = 100000.0,
                 slippage_pct: float = 0.001,
                 buy_fee_pct: float = 0.00025,
                 sell_fee_pct: float = 0.00025,
                 stamp_tax_pct: float = 0.001):
        self.db = db or Database()
        self.initial_capital = initial_capital
        self.slippage = slippage_pct
        self.buy_fee_pct = buy_fee_pct
        self.sell_fee_pct = sell_fee_pct
        self.stamp_tax_pct = stamp_tax_pct
        self._cash = initial_capital
        self.loader = IncrementalLoader(self.db)

    def get_cash(self) -> float:
        return self._cash

    def get_total_value(self) -> float:
        port = self.db.get_portfolio(limit=1)
        if not port.empty:
            return float(port.iloc[0]["total_value"])
        return self.initial_capital

    def execute_buy(self, signal: Dict, date: str) -> Optional[Dict]:
        symbol = signal["symbol"]
        df = self.loader.load_latest_data(symbol, lookback=60)
        if df is None or df.empty:
            return None
        # t+1 执行: 信号日期之后第一个可用的交易日
        signal_date = pd.Timestamp(date)
        all_dates = df["date"].dropna().sort_values()
        exec_idx = all_dates.searchsorted(signal_date, side="right")
        if exec_idx >= len(all_dates):
            logger.warning("No available execution date after %s for %s", date, symbol)
            return None
        exec_date = all_dates.iloc[exec_idx]
        day_data = df[df["date"] == exec_date]
        if day_data.empty:
            return None
        row = day_data.iloc[-1]
        price = float(row["open"])
        buy_price = price * (1 + self.slippage)

        cash = self.get_cash()
        position_value = cash * 0.2
        quantity = int(position_value / buy_price / 100) * 100
        if quantity <= 0:
            return None
        cost = quantity * buy_price
        if cost > cash:
            quantity = int(cash / buy_price / 100) * 100
            if quantity <= 0:
                return None
            cost = quantity * buy_price

        # 买入费用: 佣金
        fee = cost * self.buy_fee_pct
        total_cost = cost + fee
        if total_cost > cash:
            return None

        entry_date = str(exec_date.date())
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")
        strategy = signal.get("strategy", "")

        self._cash -= total_cost
        self.db.open_position(
            symbol, entry_date, buy_price, quantity,
            strategy=strategy, stop_loss=stop_loss,
            take_profit=take_profit,
            entry_reason=signal.get("direction", ""),
        )
        return {
            "symbol": symbol, "date": entry_date, "price": buy_price,
            "quantity": quantity, "cost": cost, "strategy": strategy,
        }

    def check_stops(self, date: str) -> List[Dict]:
        closed: List[Dict] = []
        positions = self.db.get_open_positions()
        target_date = pd.Timestamp(date)
        for pos in positions:
            symbol = pos["symbol"]
            df = self.loader.load_latest_data(symbol, lookback=30)
            if df is None or df.empty:
                continue
            day_data = df[df["date"] <= target_date].tail(1)
            if day_data.empty:
                continue
            row = day_data.iloc[-1]
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])

            sl = pos.get("stop_loss")
            tp = pos.get("take_profit")
            exit_price = None
            exit_reason = ""

            if sl and sl > 0 and low <= sl:
                exit_price = sl
                exit_reason = "stop_loss"
            elif tp and tp > 0 and high >= tp:
                exit_price = tp
                exit_reason = "take_profit"
            elif pos.get("entry_date") and (pd.Timestamp(date) - pd.Timestamp(pos["entry_date"])).days >= 60:
                exit_price = close
                exit_reason = "max_hold"

            if exit_price and exit_reason:
                self.db.close_position(symbol, str(target_date.date()), exit_price, exit_reason)
                qty = pos["quantity"]
                proceeds = qty * exit_price
                # 卖出费用: 佣金 + 印花税 (A 股卖出单边)
                fee = proceeds * self.sell_fee_pct
                stamp_tax = proceeds * self.stamp_tax_pct
                self._cash += (proceeds - fee - stamp_tax)
                pnl = (exit_price - pos["entry_price"]) * qty
                self.db.record_trade(
                    symbol, pos["entry_date"], str(target_date.date()),
                    "sell", qty, pos["entry_price"], exit_price,
                    pnl=pnl, pnl_pct=(exit_price / pos["entry_price"] - 1) * 100,
                    strategy=pos.get("strategy", ""), exit_reason=exit_reason,
                )
                closed.append({
                    "symbol": symbol, "exit_date": str(target_date.date()),
                    "exit_price": exit_price, "pnl": pnl, "reason": exit_reason,
                })
        return closed

    def snapshot(self, date: str):
        positions = self.db.get_open_positions()
        total_mv = 0.0
        for pos in positions:
            symbol = pos["symbol"]
            df = self.loader.load_latest_data(symbol, lookback=30)
            if df is None or df.empty:
                continue
            day_data = df[df["date"] <= pd.Timestamp(date)].tail(1)
            if day_data.empty:
                continue
            price = float(day_data.iloc[-1]["close"])
            total_mv += price * pos["quantity"]
        cash = self.get_cash()
        total_value = cash + total_mv
        signals_today = self.db.get_signals(date=date)
        self.db.snapshot_portfolio(
            date, cash, total_mv, total_value,
            n_positions=len(positions),
            n_signals=len(signals_today),
        )

    def run_daily(self, date: str, signals: pd.DataFrame) -> Dict:
        result: Dict[str, Any] = {"date": date, "buys": [], "sells": [], "snapshot": None}
        closed = self.check_stops(date)
        result["sells"] = closed
        if signals is not None and not signals.empty:
            for _, sig in signals.iterrows():
                sig_dict = sig.to_dict()
                exec_result = self.execute_buy(sig_dict, date)
                if exec_result:
                    result["buys"].append(exec_result)
        self.snapshot(date)
        result["snapshot"] = {
            "cash": self.get_cash(),
            "total_value": self.get_total_value(),
            "n_positions": len(self.db.get_open_positions()),
        }
        return result
