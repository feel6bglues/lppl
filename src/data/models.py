from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd


@dataclass
class DataSourceMeta:
    symbol: str
    source: str
    file_path: Optional[str] = None
    file_mtime: Optional[str] = None
    file_size: Optional[int] = None
    rows: int = 0
    date_range: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DataBundle:
    df: pd.DataFrame
    meta: DataSourceMeta
