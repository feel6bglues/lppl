from dataclasses import dataclass


@dataclass
class StrategyResult:
    ret: float
    days: int
