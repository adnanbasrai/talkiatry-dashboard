"""
smoke_test.py
-------------
Run: python tests/smoke_test.py
Verifies all major compute functions load and execute without errors.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from data.loader import load_referrals, _csv_mtime
from data.transforms import (
    compute_metrics, compute_velocity, compute_period_metrics,
    compute_entity_table, compute_account_signals_table,
    last_complete_periods, generate_summary,
)
from data.constants import MIN_REFS, INTAKE_HEALTHY, BOOKED_HEALTHY

def run():
    print("Loading data...")
    df = load_referrals(_mtime=_csv_mtime())
    assert not df.empty, "Data is empty"
    print(f"  ✓ Loaded {len(df):,} rows")

    ne = df[df["AREA"] == "Northeast"]
    assert not ne.empty

    print("Testing compute_metrics...")
    m = compute_metrics(ne)
    assert m["referrals"] > 0
    assert 0 <= m["pct_intake"] <= 1
    print(f"  ✓ {m['referrals']:,} referrals, {m['pct_intake']:.1%} intake")

    print("Testing compute_account_signals_table...")
    sig = compute_account_signals_table(ne, "month_of")
    assert not sig.empty
    print(f"  ✓ {len(sig)} accounts")

    print("Testing compute_entity_table (clinics)...")
    ct = compute_entity_table(ne, "REFERRING_CLINIC", "month_of")
    assert not ct.empty
    print(f"  ✓ {len(ct)} clinics")

    print("Testing compute_entity_table (providers)...")
    pt = compute_entity_table(ne, "REFERRING_PHYSICIAN", "month_of")
    assert not pt.empty
    print(f"  ✓ {len(pt)} providers")

    print("Testing last_complete_periods...")
    periods = sorted(ne["month_of"].dropna().unique())
    curr, prev, prev2 = last_complete_periods(periods, "month_of")
    assert curr is not None
    print(f"  ✓ curr={curr}, prev={prev}")

    print("Testing generate_summary...")
    s = generate_summary(ne, "month_of")
    print(f"  ✓ summary generated")

    print("Testing constants import...")
    assert MIN_REFS == 5
    assert INTAKE_HEALTHY == 0.55
    assert BOOKED_HEALTHY == 0.35
    print(f"  ✓ constants correct")

    print("\n✅ All smoke tests passed.")

if __name__ == "__main__":
    run()
