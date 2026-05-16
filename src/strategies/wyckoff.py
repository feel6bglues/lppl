from typing import Dict, Optional

import pandas as pd

from src.strategies import backtest as _bt
from src.strategies.indicators import calc_atr
from src.strategies.regime import get_regime
from src.wyckoff.engine import WyckoffEngine

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}


def trade_wyckoff(df: pd.DataFrame, as_of_date: str, csi: pd.DataFrame,
                  cost_buy: Optional[float] = None, cost_sell: Optional[float] = None) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    av = df[df["date"] <= a]
    if len(av) < 100:
        return None
    try:
        eng = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
        rpt = eng.analyze(av, symbol="", period="日线", multi_timeframe=True)
    except Exception:
        return None
    rr = rpt.risk_reward
    we = rr.entry_price if (rr and rr.entry_price and rr.entry_price > 0) else None
    sl = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss > 0) else None
    ft = rr.first_target if (rr and rr.first_target and rr.first_target > 0) else None
    if rpt.signal.signal_type == "no_signal" or rpt.trading_plan.direction == "空仓观望":
        return None
    regime = get_regime(csi, as_of_date) if csi is not None else "unknown"
    if regime == "bear":
        return None
    p = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_m, ts_d, mh = p["atr_mult"], p["ts"], p["mh"]
    f = df[df["date"] > a].head(mh)
    if len(f) < mh * 0.5:
        return None
    cc = float(av.iloc[-1]["close"])
    use_we = we and we > 0 and abs(we - cc) / cc > 0.001
    entry = we if use_we else cc
    hist = av.tail(60)
    atr = calc_atr(hist, 20) if len(hist) >= 21 else entry * 0.02
    if atr <= 0:
        atr = entry * 0.02
    ss = sl if (sl and sl > 0) else entry * 0.93
    et = ft if (ft and ft > 0) else None
    atr_t = entry + 2.0 * atr
    eff_t = max(et, atr_t) if (et and et > entry) else (atr_t if atr_t > entry else None)
    peak = entry
    ts_p = None
    half = False
    s2 = False
    ep = None
    er = "max_hold"
    hs = False
    ht = False
    d_ = 0
    for _, rw in f.iterrows():
        d_ += 1
        c = float(rw["close"])
        hi = float(rw["high"])
        lo = float(rw["low"])
        peak = max(peak, hi)
        if hi < ss:
            ep = float(rw["open"])
            er = "gap_stop_loss"
            hs = True
            break
        if lo <= ss <= hi:
            ep = ss
            er = "stop_loss"
            hs = True
            break
        if d_ <= 30 and not half and eff_t and hi >= eff_t:
            half = True
            s1p = eff_t
            s2 = True
            ts_p = peak - atr_m * atr
            ht = True
            continue
        if d_ == 30:
            s2 = True
            ts_p = peak - atr_m * atr
        if s2:
            t = peak - atr_m * atr
            ts_p = max(ts_p, t) if ts_p else t
            if lo <= ts_p:
                ep = ts_p
                er = "trailing_stop"
                break
            if d_ > ts_d and not half:
                ep = c
                er = "time_stop"
                break
        ep = c
    if not hs and d_ >= mh:
        ep = float(f.iloc[-1]["close"])
        er = "max_hold"
    if half and ht:
        r1 = (s1p - entry) / entry * 100
        r2 = (ep - entry) / entry * 100
        tr = 0.5 * r1 + 0.5 * r2
        er = f"target_50pct+{er}"
    else:
        tr = (ep - entry) / entry * 100
    cb = cost_buy if cost_buy is not None else _bt.COST_BUY
    cs = cost_sell if cost_sell is not None else _bt.COST_SELL
    tr -= (cb + cs) * 100
    return {"ret": round(tr, 2), "days": d_}
