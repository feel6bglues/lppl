import pandas as pd


def get_regime(csi: pd.DataFrame, d: str) -> str:
    if csi is None:
        return "unknown"
    a = pd.Timestamp(d)
    h = csi[csi["date"] <= a]
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
