from typing import Dict, Optional

import pandas as pd

from src.strategies import backtest as _bt


def trade_str_reversal(df: pd.DataFrame, as_of_date: str,
                       cost_buy: Optional[float] = None, cost_sell: Optional[float] = None) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a].tail(10)
    if len(h) < 8:
        return None
    p5 = float(h.iloc[-1]["close"])
    p0 = float(h.iloc[-6]["close"]) if len(h) >= 6 else float(h.iloc[0]["close"])
    ret_5d = (p5 - p0) / p0 * 100
    if ret_5d > -5.0:
        return None
    entry = p5
    fut = df[df["date"] > a].head(5)
    if len(fut) < 3:
        return None
    tp = entry * 1.04
    sl = entry * 0.96
    ep, ed = entry, len(fut)
    for i, (_, rw) in enumerate(fut.iterrows()):
        c, hi, lo = float(rw["close"]), float(rw["high"]), float(rw["low"])
        if hi >= tp:
            ep, ed = tp, i + 1
            break
        if lo <= sl:
            ep, sl = sl, i + 1
            break
        ep, ed = c, i + 1
    tr = (ep - entry) / entry * 100
    cb = cost_buy if cost_buy is not None else _bt.COST_BUY
    cs = cost_sell if cost_sell is not None else _bt.COST_SELL
    tr -= (cb + cs) * 100
    return {"ret": round(tr, 2), "days": ed}
