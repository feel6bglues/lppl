from src.strategies.ma_cross import trade_ma
from src.strategies.str_reversal import trade_str_reversal
from src.strategies.wyckoff import trade_wyckoff

STRATEGY_MAP = {
    "wyckoff": trade_wyckoff,
    "ma_cross": trade_ma,
    "str_reversal": trade_str_reversal,
}
