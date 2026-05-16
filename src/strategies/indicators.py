import numpy as np
import pandas as pd


def calc_atr(s: pd.DataFrame, p: int = 20) -> float:
    if len(s) < p + 1:
        return 0.0
    tr_vals = []
    for i in range(1, min(p + 1, len(s))):
        hi = float(s.iloc[-i]["high"])
        lo = float(s.iloc[-i]["low"])
        pc = float(s.iloc[-i - 1]["close"])
        tr_vals.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return float(np.mean(tr_vals)) if tr_vals else 0.0
