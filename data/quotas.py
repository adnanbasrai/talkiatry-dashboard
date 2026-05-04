"""
quotas.py
---------
PPM quota targets by period. Update ACTIVE_QUOTA_PERIOD to switch quarters.
To add Q3: copy the Q2_2026 block, update keys and dates, set ACTIVE_QUOTA_PERIOD = "Q3_2026".
"""
import pandas as pd

QUOTA_PERIODS = {
    "Q2_2026": {
        "label":   "Q2 2026",
        "start":   pd.Timestamp("2026-04-01"),
        "end":     pd.Timestamp("2026-06-30"),
        "targets": {
            # Northeast
            "Luke Young":          {"providers": 685,  "referrals": 1513, "visits": 542},
            "Danielle Maddi":      {"providers": 218,  "referrals": 481,  "visits": 173},
            "Christopher Breen":   {"providers": 153,  "referrals": 337,  "visits": 122},
            "Brittany Smith":      {"providers": 190,  "referrals": 419,  "visits": 151},
            "Ashley Alexander":    {"providers": 315,  "referrals": 695,  "visits": 250},
            # West
            "Zane Culver":         {"providers": 325,  "referrals": 718,  "visits": 257},
            "Stephanie Campos":    {"providers": 331,  "referrals": 730,  "visits": 262},
            "Russell Whittaker":   {"providers": 126,  "referrals": 279,  "visits": 99},
            "Kailye Bachman":      {"providers": 190,  "referrals": 419,  "visits": 150},
            "John Yee":            {"providers": 137,  "referrals": 303,  "visits": 108},
            "Jenny Miller":        {"providers": 153,  "referrals": 337,  "visits": 122},
            "Brooke Garlick":      {"providers": 258,  "referrals": 570,  "visits": 204},
            "Alisyn Rogers":       {"providers": 526,  "referrals": 1161, "visits": 416},
            # Central
            "Rachel LaTourette":   {"providers": 308,  "referrals": 681,  "visits": 243},
            "Marcus Lightford":    {"providers": 258,  "referrals": 568,  "visits": 205},
            "Marc Lansing":        {"providers": 288,  "referrals": 636,  "visits": 227},
            "Jack Kushner":        {"providers": 155,  "referrals": 342,  "visits": 123},
            "Elizabeth Grados":    {"providers": 157,  "referrals": 347,  "visits": 124},
            "AnaCristina Ojeda":   {"providers": 215,  "referrals": 474,  "visits": 171},
            "Alex Hale":           {"providers": 230,  "referrals": 508,  "visits": 181},
        },
    },
}

ACTIVE_QUOTA_PERIOD = "Q2_2026"
