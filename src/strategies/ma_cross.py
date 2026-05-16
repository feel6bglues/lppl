from typing import Dict, Optional

import pandas as pd

from src.strategies import backtest as _bt


def trade_ma(df: pd.DataFrame, as_of_date: str,
             cost_buy: Optional[float] = None, cost_sell: Optional[float] = None) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a].tail(30)
    if len(h) < 25:
        return None
    mf = float(h.tail(5)["close"].mean())
    ms = float(h.tail(20)["close"].mean())
    ph = df[df["date"] <= a].tail(30).head(25)
    if len(ph) < 25:
        return None
    pf = float(ph.tail(5)["close"].mean())
    ps = float(ph.tail(20)["close"].mean())
    if not (pf <= ps and mf > ms):
        return None
    entry = float(h.iloc[-1]["close"])
    fut = df[df["date"] > a]
    ed = None
    for i in range(5, min(120, len(fut) - 20)):
        sub = fut.iloc[:i + 20]
        sf = float(sub.tail(5)["close"].mean())
        ss = float(sub.tail(20)["close"].mean())
        if sf < ss:
            ed = i
            break
    if ed is None:
        ed = min(120, len(fut) - 1)
    fx = fut.iloc[:ed + 1]
    if len(fx) < 5:
        return None
    ep = float(fx.iloc[-1]["close"])
    tr = (ep - entry) / entry * 100
    cb = cost_buy if cost_buy is not None else _bt.COST_BUY
    cs = cost_sell if cost_sell is not None else _bt.COST_SELL
    tr -= (cb + cs) * 100
    return {"ret": round(tr, 2), "days": len(fx)}
