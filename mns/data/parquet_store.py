from __future__ import annotations

from pathlib import Path

import pandas as pd

from mns.data.timeframes import normalize_timeframe, timeframe_aliases


class ParquetStore:
    def __init__(self, root: str | Path = "data/parquet") -> None:
        self.root = Path(root)

    def kline_path(self, *, timeframe: str, trade_date: str) -> Path:
        timeframe = normalize_timeframe(timeframe)
        return self.root / "kline" / f"timeframe={timeframe}" / f"trade_date={trade_date}" / "part-000.parquet"

    def write_kline(self, df: pd.DataFrame, *, timeframe: str, trade_date: str) -> Path:
        path = self.kline_path(timeframe=timeframe, trade_date=trade_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            df.to_parquet(path, index=False)
        except ImportError as exc:
            raise RuntimeError("pyarrow is required to write Parquet files. Run `pip install -e .`.") from exc
        return path

    def read_kline(self, *, timeframe: str, trade_date: str) -> pd.DataFrame:
        for alias in timeframe_aliases(timeframe):
            path = self.kline_path(timeframe=alias, trade_date=trade_date)
            if not path.exists():
                continue
            try:
                return pd.read_parquet(path)
            except ImportError as exc:
                raise RuntimeError("pyarrow is required to read Parquet files. Run `pip install -e .`.") from exc
        return pd.DataFrame()
