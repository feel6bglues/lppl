from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def score_wyckoff(phase: str) -> float:
    scores = {"markdown": 0.8, "accumulation": 0.6,
              "distribution": 0.3, "markup": 0.3}
    return scores.get(phase, 0.3)


def score_maatr(df: pd.DataFrame, as_of_date: str) -> float:
    as_of = pd.Timestamp(as_of_date)
    h = df[df["date"] <= as_of].tail(100)
    if len(h) < 60:
        return 0.5
    c = float(h.iloc[-1]["close"])
    m20 = float(h.tail(20)["close"].mean())
    m60 = float(h.tail(60)["close"].mean())
    tr = 0.5 + 0.5 * ((m20 - m60) / m60) if m60 > 0 else 0.5
    hi = float(h.tail(60)["high"].max())
    lo = float(h.tail(60)["low"].min())
    pr = (c - lo) / (hi - lo) if hi > lo else 0.5
    return max(0, min(1, 0.6 * tr + 0.4 * pr))


def score_regime(market_regime: str) -> float:
    return {"bull": 0.8, "range": 0.6, "bear": 0.0, "unknown": 0.3}.get(market_regime, 0.3)


def get_market_regime(csi300: Optional[pd.DataFrame], as_of_date: str) -> str:
    if csi300 is None:
        return "unknown"
    as_of = pd.Timestamp(as_of_date)
    h = csi300[csi300["date"] <= as_of]
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


def generate_ma_signals(df: pd.DataFrame, symbol: str, name: str,
                        as_of_date: str, config: Dict) -> List[Dict]:
    results: List[Dict] = []
    fast_p = config.get("fast_period", 5)
    slow_p = config.get("slow_period", 20)
    atr_p = config.get("atr_period", 20)

    h = df[df["date"] <= pd.Timestamp(as_of_date)].tail(slow_p + 10)
    if len(h) < slow_p + 1:
        return results

    ma_fast = float(h.tail(fast_p)["close"].mean())
    ma_slow = float(h.tail(slow_p)["close"].mean())
    prev_fast = float(h.tail(fast_p + 1).head(fast_p)["close"].mean())
    prev_slow = float(h.tail(slow_p + 1).head(slow_p)["close"].mean())

    if prev_fast <= prev_slow and ma_fast > ma_slow:
        hi = float(h.tail(60)["high"].max()) if len(h) >= 60 else float(h["high"].max())
        lo = float(h.tail(60)["low"].min()) if len(h) >= 60 else float(h["low"].min())
        current = float(h.iloc[-1]["close"])
        pr = (current - lo) / (hi - lo) if hi > lo else 0.5
        score = max(0, min(1, 0.5 + 0.5 * pr))

        atr_score = 0.5
        if len(h) >= atr_p + 1:
            tr_values = []
            for i in range(1, min(atr_p + 1, len(h))):
                hi_i = float(h.iloc[-i]["high"])
                lo_i = float(h.iloc[-i]["low"])
                cl_prev = float(h.iloc[-i - 1]["close"])
                tr_i = max(hi_i - lo_i, abs(hi_i - cl_prev), abs(lo_i - cl_prev))
                tr_values.append(tr_i)
            atr = float(np.mean(tr_values)) if tr_values else current * 0.02
            atr_ratio = atr / current if current > 0 else 0.05
            if atr_ratio < 0.03:
                atr_score = 0.8
            elif atr_ratio < 0.05:
                atr_score = 0.6

        final_score = 0.6 * score + 0.4 * atr_score
        if final_score >= 0.3:
            results.append({
                "symbol": symbol, "name": name, "action": "buy",
                "entry_price": current, "stop_loss": current * 0.93,
                "take_profit": current * 1.08, "confidence": "B",
                "strategy": "ma_cross",
                "phase": "ma_cross", "regime": "", "score": round(final_score, 3),
                "direction": "做多",
            })
    return results


def generate_reversal_signals(df: pd.DataFrame, symbol: str, name: str,
                              as_of_date: str, config: Dict) -> List[Dict]:
    results: List[Dict] = []
    lookback = config.get("lookback_days", 5)
    threshold = config.get("threshold_pct", 5.0)

    h = df[df["date"] <= pd.Timestamp(as_of_date)].tail(lookback + 2)
    if len(h) < lookback + 1:
        return results

    closes = h["close"].values
    pct_changes = [(closes[-1] - closes[0]) / closes[0] * 100]
    for i in range(1, min(3, len(closes) - 1)):
        pct = (closes[-1] - closes[-(i + 1)]) / closes[-(i + 1)] * 100
        pct_changes.append(pct)

    avg_decline = abs(min(pct_changes))
    if avg_decline >= threshold:
        current = float(closes[-1])
        results.append({
            "symbol": symbol, "name": name, "action": "buy",
            "entry_price": current,
            "stop_loss": current * (1 - config.get("stop_loss_pct", 4.0) / 100),
            "take_profit": current * (1 + config.get("take_profit_pct", 4.0) / 100),
            "confidence": "C", "strategy": "reversal",
            "phase": "reversal", "regime": "", "score": round(avg_decline / 10, 3),
            "direction": "反弹做多",
        })
    return results


class DailySignalEngine:
    def __init__(self, config: Dict):
        self.config = config
        self.wyckoff_cfg = config.get("strategies", {}).get("wyckoff", {})
        self.ma_cfg = config.get("strategies", {}).get("ma_atr", {})
        self.rev_cfg = config.get("strategies", {}).get("reversal", {})

    def generate_signals(self, df: pd.DataFrame, symbol: str, name: str,
                         as_of_date: str) -> List[Dict]:
        signals: List[Dict] = []
        if self.wyckoff_cfg.get("enabled", True):
            try:
                sigs = self._run_wyckoff(df, symbol, name, as_of_date)
                signals.extend(sigs)
            except Exception as e:
                logger.error(f"Wyckoff error for {symbol}: {e}")
        if self.ma_cfg.get("enabled", True):
            try:
                sigs = generate_ma_signals(df, symbol, name, as_of_date, self.ma_cfg)
                signals.extend(sigs)
            except Exception as e:
                logger.error(f"MA error for {symbol}: {e}")
        if self.rev_cfg.get("enabled", True):
            try:
                sigs = generate_reversal_signals(df, symbol, name, as_of_date, self.rev_cfg)
                signals.extend(sigs)
            except Exception as e:
                logger.error(f"Reversal error for {symbol}: {e}")
        return signals

    def _run_wyckoff(self, df: pd.DataFrame, symbol: str, name: str,
                     as_of_date: str) -> List[Dict]:
        from src.wyckoff.engine import WyckoffEngine
        eng = WyckoffEngine(
            lookback_days=self.wyckoff_cfg.get("lookback_days", 400),
            weekly_lookback=self.wyckoff_cfg.get("weekly_lookback", 120),
            monthly_lookback=self.wyckoff_cfg.get("monthly_lookback", 40),
        )
        av = df[df["date"] <= pd.Timestamp(as_of_date)]
        if len(av) < 100:
            return []
        rpt = eng.analyze(av, symbol=symbol, period="日线", multi_timeframe=True)
        rr = rpt.risk_reward
        sig = rpt.signal.signal_type
        ph = rpt.structure.phase.value
        direction = rpt.trading_plan.direction
        if sig == "no_signal" or direction == "空仓观望":
            return []
        entry_p = float(rr.entry_price) if (rr and rr.entry_price and rr.entry_price > 0) else None
        sl = float(rr.stop_loss) if (rr and rr.stop_loss and rr.stop_loss > 0) else None
        ft = float(rr.first_target) if (rr and rr.first_target and rr.first_target > 0) else None
        s1 = score_wyckoff(ph)
        confidence = rpt.signal.confidence.value if rpt.signal.confidence else "C"
        return [{
            "symbol": symbol, "name": name, "action": "buy",
            "entry_price": entry_p, "stop_loss": sl, "take_profit": ft,
            "confidence": confidence, "strategy": "wyckoff",
            "phase": ph, "regime": "", "score": round(s1, 3),
            "direction": direction,
        }]

    def generate_batch(self, stock_data: Dict[str, pd.DataFrame],
                       name_map: Dict[str, str],
                       as_of_date: str,
                       csi300: Optional[pd.DataFrame] = None,
                       n_workers: int = 1) -> List[Dict]:
        all_signals: List[Dict] = []
        regime = get_market_regime(csi300, as_of_date) if csi300 is not None else "unknown"
        if regime == "bear":
            logger.info("Bear market regime, skipping all signals")
            return all_signals

        total = len(stock_data)
        for i, (symbol, df) in enumerate(stock_data.items()):
            name = name_map.get(symbol, "")
            sigs = self.generate_signals(df, symbol, name, as_of_date)
            all_signals.extend(sigs)
            if (i + 1) % 50 == 0:
                logger.info(f"  Processed {i+1}/{total} stocks, signals so far: {len(all_signals)}")
        return all_signals

    def merge_signals(self, all_signals: List[Dict]) -> pd.DataFrame:
        if not all_signals:
            return pd.DataFrame()
        df = pd.DataFrame(all_signals)
        if df.empty:
            return df
        df = df.sort_values("score", ascending=False)
        df = df.drop_duplicates(subset=["symbol"], keep="first")
        return df
