"""Small helpers shared by the reference implementation (pure Python + pandas)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "samples"


def round_half_up(value: Fraction | float | int | None, digits: int = 0) -> float | None:
    """Round like Excel and Spark's round(): halves go away from zero (Python's round() goes to even)."""
    if value is None:
        return None
    if isinstance(value, Fraction):
        d = Decimal(value.numerator) / Decimal(value.denominator)
    else:
        d = Decimal(str(value))
    q = Decimal(1).scaleb(-digits)
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def minutes_between(start: datetime, end: datetime) -> Fraction:
    """Exact minutes between two datetimes (no floating-point error at rounding boundaries)."""
    delta: timedelta = end - start
    return Fraction(delta.days * 86400 + delta.seconds, 60)


def hours_between(start: datetime, end: datetime) -> Fraction:
    return minutes_between(start, end) / 60


def days_between(start: datetime, end: datetime) -> Fraction:
    return minutes_between(start, end) / 1440


def age_in_years(birth: date, when: datetime | date) -> int:
    """Completed years, the same as Excel DATEDIF(birth, when, "Y")."""
    w = when.date() if isinstance(when, datetime) else when
    return w.year - birth.year - ((w.month, w.day) < (birth.month, birth.day))


def read_csv(path: str | Path, datetime_cols: tuple[str, ...] = (), date_cols: tuple[str, ...] = ()) -> pd.DataFrame:
    """Read a sample CSV as strings, converting the named columns to datetimes or dates. Empty cells become None."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df.astype(object).where(df != "", None)
    for c in datetime_cols:
        if c in df.columns:
            df[c] = pd.Series([datetime.fromisoformat(v) if v else None for v in df[c]], index=df.index, dtype=object)
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.Series([date.fromisoformat(v[:10]) if v else None for v in df[c]], index=df.index, dtype=object)
    return df


def to_num(v):
    """'78' -> 78, '2.6' -> 2.6, None -> None."""
    if v is None or v == "":
        return None
    f = float(v)
    return int(f) if f.is_integer() else f
