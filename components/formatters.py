"""
formatters.py
-------------
Shared display formatters for metrics, percentages, and dates.
Import from here to keep formatting consistent across tables, tooltips, and PDFs.
"""
from __future__ import annotations

import math
import pandas as pd


def fmt_referrals(n) -> str:
    """Format an integer referral count with thousands separator. e.g. 1234 → '1,234'"""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(v) -> str:
    """Format a 0–1 float as a percentage. e.g. 0.512 → '51.2%'"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.1%}"


def fmt_signed_pct(v) -> str:
    """Format a 0–1 float as a signed percentage. e.g. 0.05 → '+5.0%', -0.1 → '-10.0%'"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1%}"


def fmt_pp(v) -> str:
    """Format a percentage-point change (0–1 input). e.g. 0.03 → '+3.0pp'"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    pp = v * 100
    sign = "+" if pp >= 0 else ""
    return f"{sign}{pp:.1f}pp"


def fmt_days(v) -> str:
    """Format a number of days. e.g. 14 → '14d'"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{int(v)}d"


def fmt_date(dt, fmt: str = "%Y-%m-%d") -> str:
    """Format a date or Timestamp. Returns '—' for null values."""
    if dt is None or (isinstance(dt, float) and math.isnan(dt)):
        return "—"
    try:
        if hasattr(dt, "strftime"):
            return dt.strftime(fmt)
        return str(dt)[:10]
    except Exception:
        return "—"


def clean_npi(npi) -> str:
    """Clean a raw NPI value (may arrive as float 1234567890.0 from pandas).

    Strips trailing '.0' from float representations, removes sentinel strings
    (nan, None, 0), and returns an empty string for missing values.

    Args:
        npi: Raw NPI value from DataFrame cell.

    Returns:
        Clean NPI string, or "" if missing/invalid.
    """
    s = str(npi).strip()
    if s in ("nan", "None", "", "0", "0.0"):
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s
